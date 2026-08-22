"""BacktestRun API — create / status / result / cancel / retry (Backtest Run Workflow 5b)
==============================================================================
POST   /api/v1/backtest/runs                 — 실행 생성(queued) + 백그라운드 워커 기동, run_id 즉시 반환
GET    /api/v1/backtest/runs/{run_id}/status  — 폴링용 경량 상태(진행률·단계)
GET    /api/v1/backtest/runs/{run_id}         — 전체(완료 시 result 포함)
POST   /api/v1/backtest/runs/{run_id}/cancel   — 취소(비종료 상태만)
POST   /api/v1/backtest/runs/{run_id}/retry    — 동일 입력으로 새 run 생성(이력 불변)
GET    /api/v1/backtest/runs                   — 최근 실행 목록(비교·이력)

워커는 main_api의 _INGEST_STATUS 스레드 패턴과 동일하게 백그라운드 스레드에서 기존
엔진(_screen_to_backtest_core)을 돌리고, 진행/단계를 backtest_runs(DB)에 영속한다 →
새로고침·직접 URL·네트워크 단절에도 상태 복구.
"""

from __future__ import annotations

import logging
import multiprocessing as mp
import os
import threading
import time
from concurrent.futures import ProcessPoolExecutor

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

import src.data.backtest_runs as br

logger = logging.getLogger("api.backtest_run")

# ═══════════════════════════════════════════════════════════════════════════════
# 워커 프로세스 풀 (P0-2)
# ─────────────────────────────────────────────────────────────────────────────
# 예전에는 실행마다 `threading.Thread(daemon=True)` 를 **상한 없이** 띄웠다. 실측
# (`scripts/bench_backtest.py --stress`) 결과 4코어에서 동시 1/2/4 의 CPU 사용률이
# 107/103/105% 로 고정됐고 — GIL 이 천장이다 — 동시 4개가 순차 4회보다 **63% 느렸다.**
# 스레드는 처리량을 하나도 사지 못하면서 지연과 스레드 수만 늘렸다.
#
# ★fork 가 아니라 spawn 이다★ 기동 시 프리워밍 데몬 스레드가 7개 돌고(`lifecycle.py`)
# SQLAlchemy 엔진이 살아 있다. fork 는 스레드를 복제하지 않으면서 그들이 잡고 있던
# 락은 복제하고, 부모의 DB 커넥션을 자식이 물려받아 양쪽을 망가뜨린다. spawn 은
# 자식이 깨끗하게 시작한다(실측: 자식 스레드 1개 · 새 엔진 · 기동 4.4초).
# 풀이 프로세스를 재사용하므로 그 4.4초는 실행마다가 아니라 풀당 한 번이다.
#
# ★`uvicorn --workers 1` 을 어기지 않는다★ API 워커를 늘리는 것이 아니라 **CPU 작업을
# API 프로세스 밖으로 빼는** 것이다. 프로세스 로컬 캐시·DART 쿼터 카운터·적재 상태는
# API 프로세스에 그대로 남는다 — CLAUDE.md 가 워커 증설을 막은 이유가 그 상태다.
# ═══════════════════════════════════════════════════════════════════════════════

_POOL: ProcessPoolExecutor | None = None
_POOL_LOCK = threading.Lock()


def _max_workers() -> int:
    """P0-2 는 1 로 고정한다 — 동시성 확장은 P0-3 이다.

    회귀가 나면 원인이 하나여야 귀속이 된다. 격리와 동시성을 같이 넣으면 둘 중
    무엇 때문인지 가릴 수 없다.
    """
    try:
        return max(1, int(os.getenv("BACKTEST_WORKERS", "1")))
    except ValueError:
        return 1


def _get_pool() -> ProcessPoolExecutor:
    global _POOL
    if _POOL is None:
        with _POOL_LOCK:
            if _POOL is None:
                _POOL = ProcessPoolExecutor(
                    max_workers=_max_workers(),
                    mp_context=mp.get_context("spawn"),
                )
                logger.info(f"백테스트 워커 풀 기동 (spawn, max_workers={_max_workers()})")
    return _POOL


def shutdown_pool() -> None:
    """앱 종료 훅 — ★기다리지 않는다★

    `shutdown(wait=True)` 면 진행 중인 백테스트가 끝날 때까지 uvicorn 종료가 막힌다
    (large 실측 19.2분). 예전 daemon 스레드는 즉시 죽었으므로 그 동작을 유지한다.
    진행 중이던 실행은 하트비트가 끊겨 기존 `sweep_orphaned()` 가 failed 로 확정한다 —
    수정 전과 동일한 복구 경로다.
    """
    global _POOL
    pool, _POOL = _POOL, None
    if pool is None:
        return
    try:
        pool.shutdown(wait=False, cancel_futures=True)
    except Exception:
        logger.exception("워커 풀 종료 중 오류(무시)")

def _submit(fn, *args) -> None:
    """워커 디스패치 — **프로덕션은 항상 프로세스 풀이다.**

    ★왜 이 한 줄짜리 함수가 있는가★
    워커가 별도 프로세스로 가면서 인프로세스 테스트 더블이 자식에 닿지 않게 됐다
    (기존 계약 테스트는 `br._engine` 과 `_screen_to_backtest_core` 를 monkeypatch 한다).
    그래서 테스트가 **운송 수단만** 갈아끼울 수 있는 지점을 하나 둔다 — 실행되는
    로직은 프로덕션과 같은 `_worker` 다.

    ★이걸로 프로덕션 경로가 검증되지 않는 것은 아니다★ 풀을 실제로 타는
    `tests/test_backtest_worker_process.py` 가 별도 프로세스에서 완주하는 것과
    텔레메트리가 남는 것을 함께 단언한다.
    """
    _get_pool().submit(fn, *args)


router = APIRouter(prefix="/api/v1/backtest", tags=["backtest-run"])


class CreateRunRequest(BaseModel):
    # screen-to-backtest 설정 전체를 그대로 담는다(입력 스냅샷 = 재현 단위).
    config: dict = Field(..., description="ScreenToBacktestRequest 페이로드")
    strategy_name: str = Field("백테스트", max_length=120)
    requested_by: str = Field("user", max_length=60)


class _Cancelled(Exception):
    pass


class _QueryMeter:
    """워커 프로세스 안에서 DB 쿼리 수·시간을 센다(`.md` §30).

    `scripts/bench_backtest.py` 가 밖에서 쓰던 기법(SQLAlchemy `before/after_cursor_execute`)
    을 워커 안으로 옮긴 것이다 — 새로 발명하지 않는다.
    """

    def __init__(self):
        self.n = 0
        self.seconds = 0.0
        self._eng = None

    def __enter__(self):
        try:
            from sqlalchemy import event

            from src.database import get_engine
            self._eng = get_engine()

            def before(conn, cur, stmt, params, ctx, many):
                ctx._bt_t0 = time.perf_counter()

            def after(conn, cur, stmt, params, ctx, many):
                self.n += 1
                t0 = getattr(ctx, "_bt_t0", None)
                if t0 is not None:
                    self.seconds += time.perf_counter() - t0

            event.listen(self._eng, "before_cursor_execute", before)
            event.listen(self._eng, "after_cursor_execute", after)
            self._before, self._after = before, after
        except Exception:
            self._eng = None
        return self

    def __exit__(self, *a):
        if self._eng is not None:
            try:
                from sqlalchemy import event
                event.remove(self._eng, "before_cursor_execute", self._before)
                event.remove(self._eng, "after_cursor_execute", self._after)
            except Exception:
                pass
        return False


def _peak_rss_mb() -> float | None:
    try:
        import resource
        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1)
    except Exception:
        return None


def _finish_telemetry(run_id: str, tele: dict, meter: _QueryMeter,
                      t_start: float, cpu0: float) -> None:
    """실행 계측을 마무리해 DB 에 남긴다. 성공·실패·취소 모든 경로에서 부른다."""
    tele["duration_s"] = round(time.perf_counter() - t_start, 3)
    tele["cpu_s"] = round(time.process_time() - cpu0, 3)
    if tele["duration_s"] > 0:
        tele["cpu_util_pct"] = round(tele["cpu_s"] / tele["duration_s"] * 100, 1)
    tele["peak_rss_mb"] = _peak_rss_mb()
    tele["db_queries"] = meter.n
    tele["db_seconds"] = round(meter.seconds, 3)
    tele["engine_version"] = br.engine_version()
    br.set_telemetry(run_id, tele)


def _worker(run_id: str, config: dict, submitted_at: float | None = None) -> None:
    """백그라운드 실행 — 상태/진행을 DB에 영속. 예외는 failed로 정직 기록(민감정보 제외).

    P0-2 부터 **별도 프로세스**에서 돈다(spawn). `submitted_at` 은 큐 대기 시간을 재기
    위한 제출 시각이며, 없으면 큐 대기를 기록하지 않는다(0 으로 지어내지 않는다).
    """
    t_start = time.perf_counter()
    cpu0 = time.process_time()
    tele: dict = {
        "worker_pid": os.getpid(),
        "queue_wait_s": (round(time.time() - submitted_at, 3)
                         if submitted_at is not None else None),
        # ★계측 지점이 없는 항목은 넣지 않는다★ `.md` §30 의 cache hit rate 는 로더에
        # 계측 지점이 없다. 키를 만들어 0 을 넣으면 "적중률 0%" 로 읽힌다.
    }
    meter = _QueryMeter()
    try:
        from src.api.screener_routes import ScreenToBacktestRequest, _screen_to_backtest_core

        # ★대기 중 취소를 존중한다 (P0-2 에서 새로 생긴 경우)★
        # 스레드일 때는 제출 즉시 시작해 창이 사실상 없었다. 진짜 큐가 생기면 실행이
        # 몇 분씩 대기할 수 있고 그 사이 취소될 수 있다. `transition` 은 종료 상태에서
        # 전이를 거부하는데, 예전 코드는 그 반환값을 **버렸다** — 취소된 실행이 그대로
        # 돌아갔다.
        tr = br.transition(run_id, "validating")
        if not tr.get("ok"):
            logger.info(f"backtest run {run_id} 시작 거부 — {tr.get('reason')}")
            tele["skipped"] = tr.get("reason")
            br.set_telemetry(run_id, tele)
            return
        try:
            req = ScreenToBacktestRequest(**config)
        except Exception as e:
            br.set_error(run_id, "invalid_config", f"설정 검증 실패: {e}")
            return

        seen = {"stage": "validating"}

        def cb(evt: dict) -> None:
            """진행 보고 + 협조적 취소 감지.

            ★커넥션 1회★: 예전엔 이벤트마다 (취소확인 SELECT + advance의 SELECT + UPDATE)로
            풀(pool_size=5 + overflow=10)에서 3번 체크아웃했다. 같은 단계 안의 세부 진행은
            조건부 UPDATE 한 번(touch_progress)이면 되고, 그 UPDATE가 걸리지 않을 때만
            (= 없거나 종료 상태) 상태를 확인한다. 단계가 바뀔 때만 advance로 전이한다.
            """
            phase = evt.get("phase")
            done, total = evt.get("done"), evt.get("total")
            if phase in ("screening", "screened", "loading"):
                stage = "loading_data"
                pct = 10 + (18 * done / total if done and total else 0)
                msg = f"데이터 로딩 {done}/{total}" if total else None
                if phase == "loading" and total:
                    tele["symbols_loaded"] = total
            elif phase == "simulating":
                stage = "simulating"
                pct = 30 + (55 * done / total if done and total else 0)
                msg = f"시뮬레이션 {done}/{total}일" if total else "주문·체결 시뮬레이션"
                if total:
                    tele["sim_days"] = total
            else:
                return

            if seen["stage"] == stage:
                if br.touch_progress(run_id, pct, msg) == "blocked":
                    st = br.get_status(run_id)
                    if st and st["status"] == "cancelled":
                        raise _Cancelled()
                return

            r = br.advance(run_id, stage, message=msg, progress=pct)
            if r.get("cancelled"):
                raise _Cancelled()
            seen["stage"] = stage

        try:
            with meter:
                result = _screen_to_backtest_core(req, progress_cb=cb)
        except _Cancelled:
            logger.info(f"backtest run {run_id} 취소 감지 — 워커 정지")
            tele["cancelled"] = True
            _finish_telemetry(run_id, tele, meter, t_start, cpu0)
            return
        except Exception:
            logger.exception(f"backtest run {run_id} 엔진 실패")
            br.set_error(run_id, "engine_error", "백테스트 실행 중 오류가 발생했습니다.")
            tele["failure_code"] = "engine_error"
            _finish_telemetry(run_id, tele, meter, t_start, cpu0)
            return

        # 엔진이 지표까지 계산해 반환 → 마무리 단계 전이 후 결과 저장
        br.advance(run_id, "calculating_metrics", message="성과·리스크 지표 정리", progress=88)
        br.advance(run_id, "persisting_results", message="재현 가능한 결과 저장", progress=96)
        ds = (result or {}).get("data_source") or {}
        is_mock = None
        if isinstance(ds, dict):
            fully_real = ds.get("fully_real")
            is_mock = (not fully_real) if fully_real is not None else None
        # 취소가 그 사이 들어왔으면 저장하지 않음
        st = br.get_status(run_id)
        if st and st["status"] == "cancelled":
            return
        _t = time.perf_counter()
        r = br.set_result(run_id, result, is_mock_data=is_mock)
        tele["persist_s"] = round(time.perf_counter() - _t, 3)
        if not r["ok"]:
            br.set_error(run_id, "persist_error", "결과 저장에 실패했습니다.")
            tele["failure_code"] = "persist_error"
        try:
            import json as _json
            tele["result_bytes"] = len(_json.dumps(result, default=str))
        except Exception:
            pass
        _finish_telemetry(run_id, tele, meter, t_start, cpu0)
    except Exception:
        logger.exception(f"backtest worker {run_id} 예기치 못한 실패")
        try:
            br.set_error(run_id, "worker_error", "실행 처리 중 오류가 발생했습니다.")
        except Exception:
            pass
        try:
            tele["failure_code"] = "worker_error"
            _finish_telemetry(run_id, tele, meter, t_start, cpu0)
        except Exception:
            pass


@router.post("/runs")
def create_run(req: CreateRunRequest):
    """실행 생성 + 백그라운드 워커 기동. run_id 즉시 반환(결과 대기 없음)."""
    try:
        run_id = br.create_run(req.strategy_name, req.config, requested_by=req.requested_by)
        if run_id is None:
            raise HTTPException(503, "실행 저장소(DB)를 사용할 수 없어 백테스트를 생성할 수 없습니다.")
        _submit(_worker, run_id, req.config, time.time())
        return {"run_id": run_id, "status": "queued"}
    except HTTPException:
        raise
    except Exception:
        logger.exception("backtest run 생성 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/runs")
def list_runs(limit: int = Query(30, ge=1, le=100)):
    try:
        return {"runs": br.list_runs(limit=limit)}
    except Exception:
        logger.exception("backtest runs 목록 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/runs/{run_id}/status")
def run_status(run_id: str):
    # strict=True → DB 오류는 503(일시적, 프론트가 재시도), 진짜 없음만 404
    try:
        st = br.get_status(run_id, strict=True)
    except br.BacktestStoreError:
        raise HTTPException(503, "실행 저장소를 일시적으로 사용할 수 없습니다 — 잠시 후 재시도하세요.")
    if st is None:
        raise HTTPException(404, "실행을 찾을 수 없습니다.")
    return st


@router.get("/runs/{run_id}")
def run_full(run_id: str):
    try:
        r = br.get_run(run_id, strict=True)
    except br.BacktestStoreError:
        raise HTTPException(503, "실행 저장소를 일시적으로 사용할 수 없습니다 — 잠시 후 재시도하세요.")
    if r is None:
        raise HTTPException(404, "실행을 찾을 수 없습니다.")
    return r


@router.post("/runs/{run_id}/cancel")
def run_cancel(run_id: str):
    r = br.cancel(run_id)
    if not r["ok"]:
        # 사유별로 정직하게 구분 — 예전엔 '없음'과 'DB 오류'까지 409로 나가 프론트가
        # "이미 끝난 실행"으로 오해했다. run_status와 같은 매핑을 쓴다.
        if r.get("missing"):
            raise HTTPException(404, r["reason"])
        if r.get("store_error"):
            raise HTTPException(503, r["reason"])
        raise HTTPException(409, r["reason"])
    return {"ok": True, "status": "cancelled"}


@router.post("/runs/{run_id}/retry")
def run_retry(run_id: str):
    """동일 입력으로 새 실행 생성(이력 불변 — 원 실행은 그대로)."""
    src = br.get_run(run_id)
    if src is None:
        raise HTTPException(404, "실행을 찾을 수 없습니다.")
    config = src.get("input_snapshot") or {}
    new_id = br.create_run(src.get("strategy_name") or "백테스트", config,
                           requested_by=src.get("requested_by") or "user")
    if new_id is None:
        raise HTTPException(503, "실행 저장소(DB)를 사용할 수 없습니다.")
    _submit(_worker, new_id, config, time.time())
    return {"run_id": new_id, "status": "queued", "retried_from": run_id}


@router.delete("/runs/{run_id}")
def run_delete(run_id: str):
    if not br.delete_run(run_id):
        raise HTTPException(404, "실행을 찾을 수 없습니다.")
    return {"deleted": True}
