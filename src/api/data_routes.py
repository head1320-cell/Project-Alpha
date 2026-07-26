"""데이터 적재·DB 상태·심볼 마스터·관리자 동기화 — main_api.py에서 분리(경로·동작 불변).
"""

import logging

from fastapi import APIRouter, HTTPException, Query

from src.state.ingest_state import INGEST_RUNNING, INGEST_STATUS, INGEST_TARGETS

logger = logging.getLogger("api.data")
router = APIRouter(tags=["data"])

# 심볼 수급 백필 진행 플래그 — 이 라우터 안에서만 쓰인다(데몬 스레드에서 변경).
_FLOWS_BACKFILL_RUNNING = {"krx": False}


@router.get("/api/v1/data/krx-status")
def krx_status():
    """KRX 적재(daily_prices) 커버리지 — 자동 백필 진행상황 관측."""
    import os

    from src.data.mock_gate import mock_allowed
    out = {
        "krx_key": bool(os.getenv("KRX_API_KEY")),
        "autobackfill": os.getenv("KRX_AUTOBACKFILL", "1") != "0",
        "backfill_start": os.getenv("KRX_BACKFILL_START", "2010-01-04"),
        # KIS 기반 전종목 OHLCV 사전 적재 활성 여부 (KRX 키 없이 daily_prices를 채우는 경로)
        "kis_prewarm": (
            not mock_allowed()
            and bool(os.getenv("KIS_APP_KEY"))
            and os.getenv("OHLCV_PREWARM", "1") != "0"
        ),
    }
    try:
        from sqlalchemy import text

        from src.database import get_engine
        engine = get_engine()
        if engine is None:
            return {**out, "available": False}
        with engine.connect() as conn:
            row = conn.execute(text(
                'SELECT MIN(trade_date), MAX(trade_date), '
                'COUNT(DISTINCT ticker), COUNT(*) FROM daily_prices')).fetchone()
            idx = conn.execute(text(
                "SELECT COUNT(*) FROM daily_prices "
                "WHERE ticker IN ('KOSPI','KOSDAQ')")).scalar()
        out.update({
            "available": True,
            "start_date": str(row[0])[:10] if row and row[0] else None,
            "end_date": str(row[1])[:10] if row and row[1] else None,
            "tickers": int(row[2]) if row and row[2] else 0,
            "rows": int(row[3]) if row and row[3] else 0,
            "index_rows": int(idx) if idx else 0,
        })
    except Exception as e:
        import logging
        logging.getLogger("api.main").debug(f"krx-status 조회 실패: {e}")
        out.update({"available": False})
    return out

@router.get("/api/v1/data/db-status")
def db_status():
    """모든 핵심 테이블 적재 현황 + 설정 + 도구별 준비상태 — 한 번에 점검(매번 SSH 불필요).
    대용량 daily_prices가 적재 쓰기 중이어도 빠르게 응답하도록 추정치(reltuples)+statement_timeout 사용."""
    import os

    from src.data.mock_gate import mock_allowed
    out: dict = {"available": False, "config": {}, "tables": {}, "tools": {}}
    out["config"] = {
        "kis_real": not mock_allowed() and bool(os.getenv("KIS_APP_KEY")),
        "dart_key": bool(os.getenv("DART_API_KEY")),
        "krx_key": bool(os.getenv("KRX_API_KEY")),
        "bok_key": bool(os.getenv("BOK_API_KEY")),
        "fred_key": bool(os.getenv("FRED_API_KEY")),
    }

    # 유니버스 적재 진행 — 마스터(전 상장) 대비 factor_snapshot 적재 수 (스크리너 유니버스 크기의 근거)
    def _universe_progress() -> dict:
        try:
            from src.data.snapshot_db import enabled as _sn_en
            from src.data.snapshot_db import ingested_codes
            from src.data.stock_master import build_master_universe, master_composition
            ing = set(ingested_codes()) if _sn_en() else set()
            prog = {}
            for k in ("kospi", "kosdaq", "etf", "all_listed"):
                m = build_master_universe(k)
                if m:
                    prog[k] = {"master": len(m), "ingested": sum(1 for c in m if c in ing)}
            return {"progress": prog, "composition": master_composition()}
        except Exception:
            return {"progress": {}, "composition": {}}

    out["universe_progress"] = _universe_progress()

    # 적재 상세 상태 + DART 사용량 — "버튼 눌러도 조용함"의 원인을 화면에 노출
    out["ingest_status"] = {k: dict(v) for k, v in INGEST_STATUS.items()}
    try:
        from src.data.dart_client import dart_usage
        out["dart_usage"] = dart_usage()
    except Exception:
        out["dart_usage"] = None
    try:
        from sqlalchemy import text

        from src.data.etf_prices import US_TO_KR
        from src.data.kis_flows import flows_status
        from src.database import get_engine
        engine = get_engine()
        if engine is None:
            out["ingest_running"] = dict(INGEST_RUNNING)
            return out

        etf_codes = sorted({c for c, _ in US_TO_KR.values()})
        ph = ",".join(f":c{i}" for i in range(len(etf_codes)))

        # AUTOCOMMIT: 각 쿼리 독립 트랜잭션 → statement_timeout 컷이 다음 쿼리를 오염시키지 않음.
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
            try:
                c.execute(text("SET statement_timeout = 5000"))  # Postgres: 슬로우/락대기 5s 컷
            except Exception:
                pass

            def q(sql: str, params: dict | None = None):
                try:
                    return c.execute(text(sql), params or {}).fetchone()
                except Exception:
                    return None

            # daily_prices 행수: 대용량 → Postgres 추정치(reltuples, 즉시) 우선, 실패 시 COUNT
            est = q("SELECT reltuples::bigint FROM pg_class WHERE relname='daily_prices'")
            dp_rows = int(est[0]) if (est and est[0] and int(est[0]) > 0) else None
            if dp_rows is None:
                cnt = q("SELECT COUNT(*) FROM daily_prices")
                dp_rows = int(cnt[0] or 0) if cnt else 0
            # 종목 수/기간 — 848만 행에서 COUNT(DISTINCT)+MIN+MAX 결합 쿼리가 5s 타임아웃
            # → "종목 0 · 기간 —" 오표시 + 백테스터(종목) 거짓 X이던 버그:
            #   ① 종목 수는 pg_stats n_distinct 추정(즉시), 실패 시에만 정확 카운트
            #   ② MIN/MAX는 개별 쿼리(인덱스 스캔, 각자 5s 컷) ③ 미확정은 None(0 금지 — 프론트 "—")
            nd = q("SELECT n_distinct FROM pg_stats WHERE tablename='daily_prices' AND attname='ticker'")
            dp_tickers = None
            if nd and nd[0] is not None:
                ndv = float(nd[0])
                dp_tickers = int(-ndv * (dp_rows or 0)) if ndv < 0 else int(ndv)
            if dp_tickers is None:
                cnt = q("SELECT COUNT(DISTINCT ticker) FROM daily_prices")
                dp_tickers = int(cnt[0]) if (cnt and cnt[0] is not None) else None
            dmin = q("SELECT MIN(trade_date) FROM daily_prices")
            dmax = q("SELECT MAX(trade_date) FROM daily_prices")
            dp_exists = q("SELECT 1 FROM daily_prices LIMIT 1") is not None
            idxr = q("SELECT COUNT(*), MIN(trade_date), MAX(trade_date) FROM daily_prices WHERE ticker IN ('KOSPI','KOSDAQ')")
            etf = q(f"SELECT COUNT(DISTINCT ticker), MIN(trade_date), MAX(trade_date) FROM daily_prices WHERE ticker IN ({ph})",  # noqa: S608 — 코드 화이트리스트
                    {f"c{i}": code for i, code in enumerate(etf_codes)})
            fs = q("SELECT COUNT(*) FROM factor_snapshot")
            fh = q("SELECT COUNT(*), MIN(bsns_year), MAX(bsns_year) FROM financials_history")
        fl = flows_status(engine)

        out["available"] = True
        out["tables"] = {
            "daily_prices": {"rows": dp_rows,
                             "tickers": dp_tickers,
                             "start": str(dmin[0])[:10] if (dmin and dmin[0]) else None,
                             "end": str(dmax[0])[:10] if (dmax and dmax[0]) else None},
            "index_kospi_kosdaq": {"rows": int(idxr[0] or 0) if idxr else 0,
                                   "start": str(idxr[1])[:10] if (idxr and idxr[1]) else None,
                                   "end": str(idxr[2])[:10] if (idxr and idxr[2]) else None},
            "etf_cross_asset": {"loaded": int(etf[0] or 0) if etf else 0, "total": len(etf_codes),
                                "start": str(etf[1])[:10] if (etf and etf[1]) else None,
                                "end": str(etf[2])[:10] if (etf and etf[2]) else None},
            "investor_flows": {"rows": fl.get("rows", 0), "tickers": fl.get("tickers", 0),
                               "start": fl.get("min_date"), "end": fl.get("max_date")},
            "factor_snapshot": {"rows": int(fs[0] or 0) if fs else 0},
            "financials_history": {"rows": int(fh[0] or 0) if fh else 0,
                                   "start": str(fh[1]) if (fh and fh[1]) else None,
                                   "end": str(fh[2]) if (fh and fh[2]) else None},
        }
        t = out["tables"]
        out["tools"] = {
            "스크리너(펀더멘털)": (t["factor_snapshot"]["rows"] or 0) > 0,
            "백테스터(종목)": dp_exists and (dp_tickers is None or dp_tickers > 5),
            "백테스터(매크로·ETF)": t["etf_cross_asset"]["loaded"] >= max(1, int(t["etf_cross_asset"]["total"] * 0.6)),
            "벤치마크·국면": (t["index_kospi_kosdaq"]["rows"] or 0) > 0,
            "수급 시그널": (t["investor_flows"]["rows"] or 0) > 0,
            "PIT 펀더멘털": (t["financials_history"]["rows"] or 0) > 0,
        }
    except Exception:
        logger.exception("db-status 조회 실패")
    out["ingest_running"] = dict(INGEST_RUNNING)
    return out

def _ingest_run(target: str):
    """단일 타깃 적재(동기) — 백그라운드 스레드서 호출. 키 없는 소스는 내부서 no-op(안전)."""
    import os
    start = os.getenv("KRX_BACKFILL_START", "2010-01-04")
    if target == "index":
        from src.data.krx_ingest import backfill_index
        return backfill_index(start=start)
    if target == "etf":
        from src.data.etf_prices import prewarm_etf_universe
        return prewarm_etf_universe("kr")
    if target == "stocks":
        from src.data.krx_ingest import backfill
        return backfill(start=start)            # KRX 전종목 일봉(+지수) 1회 백필
    if target == "factors":
        from src.data.snapshot_db import ingest_universe
        from src.engine.screener import resolve_universe
        st = INGEST_STATUS.setdefault("factors", {})
        out = {}
        # 지수 유니버스 먼저(빠른 부분 가용) → all_listed는 남은 종목만.
        # kospi200·kosdaq150 ⊂ all_listed 이므로 코드 단위 dedup으로 재평가·DART 낭비를 원천 차단.
        # (스냅샷 캐시가 재호출 자체는 이미 막지만, dedup은 재스캔 compute까지 제거하고 의도를 명확히 함)
        seen: set[str] = set()
        for uni in ("kospi200", "kosdaq150", "all_listed"):
            codes = [c for c in resolve_universe(uni) if c not in seen]
            seen.update(codes)
            if not codes:
                out[uni] = {"universe": uni, "skipped": "중복 제거 — 이미 처리됨", "saved": 0}
                continue

            def _cb(done, total, saved, fails, _u=uni, _st=st):
                _st["progress"] = {"stage": _u, "done": done, "total": total,
                                   "saved": saved, "failures": fails}
            r = ingest_universe(codes, progress_cb=_cb)
            out[uni] = r
            if r.get("aborted"):
                st["last_error"] = r["aborted"]  # DART 한도 등 — UI에 사유 노출
                break
        return out
    if target == "financials":
        # 무한루프인 _dart_history_backfill_bg()를 그대로 재사용하면 수동 버튼이 영원히
        # 안 끝나던 버그 — backfill_financials를 1회만 직접 호출(resume 기반이라 안전).
        from src.data.dart_history import backfill_financials, refetch_revenue_null
        years = int(os.getenv("DART_HISTORY_YEARS", "10") or 10)
        quarters = os.getenv("DART_HISTORY_QUARTERS", "0") != "0"
        max_calls = int(os.getenv("DART_HISTORY_MAX_CALLS", "18000") or 18000)
        st = INGEST_STATUS.setdefault("financials", {})

        def _cb(done, total, saved, calls, _st=st):
            _st["progress"] = {"stage": "all_listed", "done": done, "total": total,
                               "saved": saved, "failures": 0}
        r1 = backfill_financials(all_listed=True, years=years, include_quarters=quarters,
                                 max_calls=max_calls, progress_cb=_cb)
        # 2단계: 금융업 등 revenue=NULL 행을 확장 파서(영업수익/이자수익)로 재조회.
        # 쿼터 소진 중단이 아니면 남은 한도로 실행(멱등 — 이미 채워진 건 후보에서 빠짐).
        r2 = None
        if not r1.get("stopped_at_quota"):
            remaining = max(0, max_calls - int(r1.get("calls", 0)))

            def _cb2(done, total, updated, calls, _st=st):
                _st["progress"] = {"stage": "revenue_refetch(금융업)", "done": done,
                                   "total": total, "saved": updated, "failures": 0}
            r2 = refetch_revenue_null(max_calls=remaining or None, progress_cb=_cb2)
        return {"backfill": r1, "revenue_refetch": r2}
    if target == "flows":
        from src.data.kis_flows import sync_investor_flows
        return sync_investor_flows(all_listed=True)
    return {"error": f"unknown target: {target}"}

@router.post("/api/v1/data/ingest/{target}")
def ingest_trigger(target: str):
    """테이블별/전체 적재 백그라운드 트리거. target ∈ {index,etf,stocks,factors,financials,flows,all}.
    키 없는 소스는 내부서 no-op. 중복 실행 가드. 진행은 db-status의 ingest_running."""
    import threading
    if target == "all":
        targets = list(INGEST_TARGETS)
    elif target in INGEST_TARGETS:
        targets = [target]
    else:
        raise HTTPException(404, f"unknown target: {target}")

    started = []
    for t in targets:
        if INGEST_RUNNING.get(t):
            continue

        def _run(tt: str):
            from datetime import datetime as _dt
            INGEST_RUNNING[tt] = True
            st = INGEST_STATUS.setdefault(tt, {})
            st.update({"running": True, "started_at": _dt.now().isoformat(timespec="seconds"),
                       "finished_at": None, "last_error": None, "result": None, "progress": None})
            try:
                logger.info(f"적재(수동) 시작: {tt}")
                r = _ingest_run(tt)
                st["result"] = r
                logger.info(f"적재(수동) 완료 [{tt}]: {r}")
            except Exception as e:
                st["last_error"] = str(e)[:300]  # UI 표면화 — "조용한 실패" 제거
                logger.exception(f"적재(수동) 실패 [{tt}]")
            finally:
                st["running"] = False
                st["finished_at"] = _dt.now().isoformat(timespec="seconds")
                INGEST_RUNNING[tt] = False

        threading.Thread(target=_run, args=(t,), daemon=True).start()
        started.append(t)

    return {"started": started, "running": dict(INGEST_RUNNING),
            "message": (f"적재 시작: {', '.join(started)}" if started else "모두 이미 실행 중")}

@router.get("/api/v1/data/ingest-doctor")
def ingest_doctor():
    """적재 데이터 소스(DART/KRX/KIS) 실도달 진단 — "가져오기가 되는가"를 UI에서 즉답.

    각 소스에 경량 실호출 1건: DART 기업개황(삼성전자) · KRX 지수 일별시세(최근 영업일) ·
    KIS 토큰. 키 미설정/mock은 정직하게 ok=False + 사유. DART 사용량 요약 동봉."""
    import os
    import time as _t
    from datetime import datetime as _dt
    from datetime import timedelta as _td

    out: dict = {}

    # DART
    if not os.getenv("DART_API_KEY"):
        out["dart"] = {"ok": False, "message": "DART_API_KEY 미설정"}
    else:
        try:
            from src.data.dart_client import STOCK_TO_CORP, DARTClient
            t0 = _t.time()
            c = DARTClient()
            data = c._get("company.json", {"corp_code": STOCK_TO_CORP.get("005930", "00126380")})
            ms = round((_t.time() - t0) * 1000)
            out["dart"] = ({"ok": True, "message": f"정상 (기업개황 응답 {ms}ms)", "latency_ms": ms}
                           if data else {"ok": False, "message": "응답 실패 — 아래 dart_usage.last_error 참조", "latency_ms": ms})
        except Exception as e:
            out["dart"] = {"ok": False, "message": f"예외: {str(e)[:120]}"}

    # KRX
    if not os.getenv("KRX_API_KEY"):
        out["krx"] = {"ok": False, "message": "KRX_API_KEY 미설정"}
    else:
        try:
            from src.data.krx_client import KRXClient
            kc = KRXClient()
            t0 = _t.time()
            day = (_dt.now() - _td(days=1))
            while day.weekday() >= 5:  # 최근 평일
                day -= _td(days=1)
            rows = kc.get_daily_all("KOSPI", day.strftime("%Y%m%d"))
            ms = round((_t.time() - t0) * 1000)
            out["krx"] = ({"ok": True, "message": f"정상 (KOSPI {len(rows)}행, {ms}ms)", "latency_ms": ms}
                          if rows else {"ok": False, "message": f"0행 응답 (휴장일/승인 범위 확인, {ms}ms)", "latency_ms": ms})
        except Exception as e:
            out["krx"] = {"ok": False, "message": f"예외: {str(e)[:120]}"}

    # KIS
    from src.data.mock_gate import mock_allowed
    if mock_allowed() or not os.getenv("KIS_APP_KEY"):
        out["kis"] = {"ok": False, "message": "mock 모드 또는 KIS 키 미설정"}
    else:
        try:
            from src.execution import kis_client as _kc
            t0 = _t.time()
            client = _kc.get_kis_client(force_reload=True)  # 팩토리(.env 분기) — KISClient()는 creds 필수
            pw = getattr(client, "prewarm_token", None)
            if callable(pw):
                pw()
            ms = round((_t.time() - t0) * 1000)
            out["kis"] = {"ok": True, "message": f"토큰 정상 ({ms}ms)", "latency_ms": ms}
        except Exception as e:
            out["kis"] = {"ok": False, "message": f"예외: {str(e)[:120]}"}

    try:
        from src.data.dart_client import dart_usage
        out["dart_usage"] = dart_usage()
    except Exception:
        out["dart_usage"] = None
    return out

@router.post("/api/v1/admin/sync")
async def v1_admin_trigger_sync():
    """Manually trigger a full KIS sync. For admin / CLI use."""
    try:
        from src.data_sync import run_full_sync
        result = await run_full_sync()
        return result
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")

@router.post("/api/v1/symbols/collect-master")
async def collect_master():
    """KOSPI/KOSDAQ 마스터파일 다운로드 → DB Upsert (인증 불필요)."""
    try:
        from src.database import get_engine
        from src.kis_master_parser import collect_master_files
        engine = get_engine()
        result = await collect_master_files(engine)
        return result
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")

@router.get("/api/v1/symbols/search")
async def symbol_search(
    q: str = Query(..., min_length=1, description="종목코드 또는 종목명"),
    market: str | None = Query(None, description="KOSPI / KOSDAQ"),
    limit: int = Query(30, ge=1, le=100),
):
    """인메모리 캐시에서 종목 검색 (즉시 응답)."""
    try:
        from src.kis_master_parser import _symbol_cache, search_symbols
        results = search_symbols(q, market, limit)

        # 캐시 미구축 시 DB fallback
        if not results and not _symbol_cache:
            from src.database import get_engine
            from src.kis_master_parser import load_symbol_cache
            engine = get_engine()
            load_symbol_cache(engine)
            results = search_symbols(q, market, limit)

        return {"query": q, "total": len(results), "items": results}
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")

@router.get("/api/v1/symbols/status")
def symbol_status():
    """마스터파일 로드 상태 확인."""
    from src.kis_master_parser import _last_fetched, _symbol_cache
    total = sum(len(v) for v in _symbol_cache.values())
    return {
        "loaded": total > 0,
        "total": total,
        "markets": {k: len(v) for k, v in _symbol_cache.items()},
        "last_fetched": _last_fetched.isoformat() if _last_fetched else None,
    }

@router.get("/api/v1/symbols/flows/status")
def symbols_flows_status():
    """investor_flows 수급 적재 현황 — 행수/종목수/날짜범위/세부주체 + 실행중 여부."""
    from src.data.kis_flows import flows_status
    st = flows_status()
    st["krx_backfill_running"] = _FLOWS_BACKFILL_RUNNING["krx"]
    return st

@router.post("/api/v1/symbols/flows/backfill-krx")
def symbols_flows_backfill_krx(start: str = "2018-01-01", all_listed: bool = True):
    """KRX MDC 과거 수급 확정치 백필 시작(백그라운드). KIS ~30영업일 제한 보완.
    운영(실데이터) 모드 전용 — mock 모드선 거부. 진행은 flows/status로 확인."""
    import threading

    from src.data.mock_gate import mock_allowed
    if mock_allowed():
        return {"started": False,
                "message": "mock 모드 — 실 KRX 백필은 실데이터 모드(KIS_USE_MOCK=0)에서만"}
    if _FLOWS_BACKFILL_RUNNING["krx"]:
        return {"started": False, "message": "이미 실행 중"}

    def _run():
        _FLOWS_BACKFILL_RUNNING["krx"] = True
        try:
            from src.data.krx_mdc import backfill_flows_krx
            logger.info(f"KRX 수급 백필 시작 (start={start}, all_listed={all_listed})")
            stats = backfill_flows_krx(start=start, all_listed=all_listed)
            logger.info(f"KRX 수급 백필 완료: {stats}")
        except Exception:
            logger.exception("KRX 수급 백필 실패")
        finally:
            _FLOWS_BACKFILL_RUNNING["krx"] = False

    threading.Thread(target=_run, daemon=True).start()
    return {"started": True, "start": start, "all_listed": all_listed,
            "message": "KRX 과거 수급 백필 시작(백그라운드). flows/status로 진행 확인."}
