"""펀더멘털 적재 파이프라인 진단 — GCP 컨테이너에서 실행해 어디서 막히는지 확정.

    docker compose exec backend python scripts/diag_fundamentals.py

민감정보(키 전체)는 출력하지 않는다. 각 단계 독립 try/except라 하나 실패해도 계속 진행."""
import os

print("=" * 70)
print("1) 배포 코드 마커 (수정 반영 여부)")
try:
    from src.data.fundamentals_store import FundamentalsStore
    print("   _fs_from_history 존재      :", hasattr(FundamentalsStore, "_fs_from_history"))  # DB-우선
    print("   _get_fs 존재               :", hasattr(FundamentalsStore, "_get_fs"))
    import inspect

    from src.engine.screener import ValuationScreener
    print("   run(reattach_fundamentals) :", "reattach_fundamentals" in inspect.signature(ValuationScreener.run).parameters)
    import src.data.snapshot_db as sdb
    print("   snapshot_db.ingested_count :", hasattr(sdb, "ingested_count"))
except Exception as e:
    print("   ERR:", e)

print("=" * 70)
print("2) 실행 모드")
print("   KIS_USE_MOCK :", os.getenv("KIS_USE_MOCK"))
print("   DART_API_KEY :", "설정됨" if os.getenv("DART_API_KEY") else "없음")
try:
    from src.data.mock_gate import mock_allowed
    print("   mock_allowed :", mock_allowed(), "(False=운영, 합성 금지)")
except Exception as e:
    print("   ERR:", e)

print("=" * 70)
print("3) factor_snapshot vs financials_history 카운트")
tickers_fh: list[str] = []
ffl_codes: set[str] = set()
try:
    from sqlalchemy import text

    from src.database import get_engine
    eng = get_engine()
    with eng.connect() as c:
        total = c.execute(text("SELECT COUNT(*) FROM factor_snapshot")).scalar()
        ffl = c.execute(text("SELECT COUNT(*) FROM factor_snapshot WHERE cache_key LIKE 'ffl:%'")).scalar()
        item = c.execute(text("SELECT COUNT(*) FROM factor_snapshot WHERE cache_key LIKE 'item:%'")).scalar()
        fh = c.execute(text("SELECT COUNT(DISTINCT ticker) FROM financials_history")).scalar()
        ffl_codes = {r[0].split(":", 1)[1] for r in c.execute(text(
            "SELECT cache_key FROM factor_snapshot WHERE cache_key LIKE 'ffl:%'"))}
        tickers_fh = [r[0] for r in c.execute(text(
            "SELECT DISTINCT ticker FROM financials_history"))]
    print(f"   factor_snapshot 총행 : {total}")
    print(f"   ffl:  키(=유니버스)   : {ffl}")
    print(f"   item: 키             : {item}")
    print(f"   financials_history 종목: {fh}")
    missing = [t for t in tickers_fh if t not in ffl_codes]
    print(f"   → financials 있는데 ffl: 없는 종목: {len(missing)}  (이게 재적재로 채워져야 함)")
    print(f"   샘플 미충족 종목: {missing[:5]}")
except Exception as e:
    print("   ERR:", e)

print("=" * 70)
print("4) 미충족 종목 1건 파이프라인 추적 (DB→FS→raw→factors)")
try:
    from src.data.dart_history import history_snapshot
    from src.data.fundamentals_store import FundamentalsStore
    probe = next((t for t in tickers_fh if t not in ffl_codes), tickers_fh[0] if tickers_fh else "005930")
    print(f"   대상 종목: {probe}")
    for y in (2025, 2024, 2023):
        snap = history_snapshot(str(probe), str(y), "11011")
        has = bool(snap and (snap.get("revenue") is not None or snap.get("total_assets") is not None))
        print(f"   history_snapshot({probe},{y}) : {'데이터 있음' if has else '없음'}")
    st = FundamentalsStore()
    fs = st._fs_from_history(probe, 2025) if hasattr(st, "_fs_from_history") else None
    print(f"   _fs_from_history → FS      : {'생성됨' if fs is not None else 'None'}")
    raw = st._real_raw_financials(probe)
    print(f"   _real_raw_financials       : {'dict(비어있지않음)' if raw else 'None/빈값'}")
    fac = st._build_factors(probe)
    print(f"   _build_factors             : {f'팩터 {len(fac)}개' if fac else '빈 dict {} → 영속 안 됨'}")
    if fac:
        print(f"   샘플 팩터 roe/per          : {fac.get('roe')}, {fac.get('per')}")
except Exception as e:
    import traceback
    print("   ERR:", e)
    traceback.print_exc()

print("=" * 70)
print("5) DART 사용량")
try:
    from src.data.dart_client import dart_usage
    print("  ", dart_usage())
except Exception as e:
    print("   ERR:", e)

print("=" * 70)
print("6) ★수정 효과★ 미충족 종목 표본에 실제 적재 경로(get_factors)로 팩터가 생기는지")
print("   (완전연도 탐색+회계항등식 수정 반영 확인. buckets = 왜 비었었나 분류)")
try:
    import src.data.snapshot_db as sdb
    from src.data.fundamentals_store import FundamentalsStore
    store = FundamentalsStore.get_default()  # ingest와 동일한 싱글턴 경로
    # corp_code 맵 1회 프리워밍(최초 다운로드 ~30초일 수 있음 — 기다려주세요). 수정으로
    # DB 서빙 종목은 이 맵이 필요 없지만, 완전 DB연도가 없는 잔여 종목이 라이브 DART로
    # 폴백할 때만 사용 → 여기서 미리 채워 루프 중 멈춤을 방지. 실패해도 DB 경로는 동작.
    print("   corp_code 맵 프리워밍 중(최초 1회 ~30초, 기다려주세요)...", flush=True)
    try:
        from src.data.dart_client import _load_full_corp_map
        print(f"   corp_code 맵: {len(_load_full_corp_map())}개")
    except Exception as e:
        print(f"   corp_code 맵 프리워밍 실패(무시, DB 경로는 동작): {e}")
    sample = [t for t in tickers_fh if t not in ffl_codes][:40]
    print(f"   표본(미충족 종목): {len(sample)}개")
    base = sdb.ingested_count()
    built = empty = 0
    buckets = {"recovered_complete_year": 0, "financial_no_revenue": 0,
               "no_usable_year": 0}
    for code in sample:
        try:
            raw = store._real_raw_financials(code)
        except Exception:
            raw = None
        if raw is not None:
            buckets["recovered_complete_year"] += 1
        else:
            # 왜 여전히 None인가 — 연도별 필드 스캔으로 잔여 원인 분류
            rev_seen = eq_or_ni_seen = False
            for y in range(2025, 2017, -1):
                try:
                    from src.data.dart_history import history_snapshot
                    s = history_snapshot(str(code), str(y), "11011")
                except Exception:
                    s = None
                if not s:
                    continue
                if s.get("revenue") is not None:
                    rev_seen = True
                if s.get("net_income") is not None or s.get("total_equity") is not None:
                    eq_or_ni_seen = True
            if eq_or_ni_seen and not rev_seen:
                buckets["financial_no_revenue"] += 1   # 금융업 등 매출액 라인 부재(정직 잔여)
            else:
                buckets["no_usable_year"] += 1
        # 싱글턴 get_factors — ingest가 실제로 밟는 영속 경로
        fac = store.get_factors(code, None)
        if fac:
            built += 1
        else:
            empty += 1
    after = sdb.ingested_count()
    print(f"   get_factors 비어있지않음: {built} / 빈 dict: {empty}")
    print(f"   ffl: 실제 영속 증가분   : {after - base}  (이게 0보다 크면 수정으로 유니버스 확장됨)")
    print(f"   미복구 원인 분류        : {buckets}")
    print("   → recovered_complete_year 多 = 수정 효과. financial_no_revenue = 금융업(정직 잔여, 별도 과제).")
except Exception as e:
    import traceback
    print("   ERR:", e)
    traceback.print_exc()

print("=" * 70)
print("진단 끝. 6)의 'ffl: 실제 영속 증가분'이 표본에서 0보다 크면 수정이 유효 →")
print("전체 재적재(Data Infra '펀더멘털' 버튼) 시 유니버스가 재무시계열 종목수까지 차오름.")
