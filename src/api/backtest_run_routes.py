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
from concurrent.futures import CancelledError, ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool

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


# 동시 실행 상한의 하드 캡. 이 이상은 코어가 많아도 올리지 않는다 — 실행당 메모리가
# 실측 90~247 MB 라(감사 §3.6) 무한정 늘리면 CPU 가 아니라 메모리에서 터진다.
_MAX_WORKERS_CAP = 4


def _usable_cpus() -> int:
    """이 프로세스가 **실제로 쓸 수 있는** 코어 수.

    컨테이너에서는 `os.cpu_count()` 가 호스트 전체를 보고하므로 affinity 를 먼저 본다.
    (cgroup 쿼터는 둘 다 반영하지 않는다 — 그건 여기서 알 수 없고, 알 수 없다고 적는다.)
    """
    try:
        return max(1, len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        return max(1, os.cpu_count() or 1)


def _max_workers() -> int:
    """동시 실행 상한 (P0-3).

    ★코어를 전부 쓰지 않는다★ `cpu_count - 1` 이다. `uvicorn --workers 1` 인 API
    프로세스가 같은 기계에서 돌고, `.md` §9 는 "폭주 백테스트가 API 요청을 굶기면
    안 된다" 를 **hard requirement** 로 못박았다. 마지막 코어를 워커에게 주면 정확히
    그 일이 일어난다.

    `BACKTEST_WORKERS` 로 덮을 수 있다(운영에서 기계가 다를 수 있으므로). 잘못된
    값은 크래시가 아니라 기본값으로 떨어진다.
    """
    raw = os.getenv("BACKTEST_WORKERS")
    if raw is not None:
        try:
            return max(1, int(raw))
        except ValueError:
            logger.warning(f"BACKTEST_WORKERS 값이 잘못됨({raw!r}) — 기본값을 쓴다")
    return max(1, min(_usable_cpus() - 1, _MAX_WORKERS_CAP))


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

def _reset_pool() -> None:
    """★broken 된 풀을 버리고 다음 제출에서 새로 만든다★

    자식이 비정상 종료하면 `ProcessPoolExecutor` 는 **풀 전체**를 broken 으로
    표시하고 이후 모든 `submit()` 이 즉시 실패한다. 예전에는 `_POOL` 을 앱 종료
    외에 재설정하지 않아서, 한 번 죽으면 **API 를 재시작할 때까지 모든 백테스트가
    실패했다** — 사용자가 말한 "계속 일어난다" 가 그것이다.
    """
    global _POOL
    with _POOL_LOCK:
        pool, _POOL = _POOL, None
    if pool is not None:
        try:
            pool.shutdown(wait=False, cancel_futures=True)
        except Exception:                       # noqa: BLE001
            logger.debug("broken 풀 정리 중 오류(무시)", exc_info=True)


def _on_worker_done(run_id: str | None, fut) -> None:
    """★죽은 자식을 관측한다★

    `_worker` 는 자기 예외를 잡아 failed 로 기록한다. 그러나 자식이 **SIGKILL**
    되면(OOM killer 가 대표적이다 — 실행당 RSS 90~247MB × 워커 4개) 그 `except` 는
    돌지 못한다. 예전에는 `submit()` 의 Future 를 버려서 그 죽음을 아무도 관측하지
    못했고, 행은 비종료로 남아 `RunMonitor` 가 1초마다 영원히 폴링했다.
    """
    try:
        exc = fut.exception()
    except CancelledError:
        return
    except Exception:                           # noqa: BLE001
        return
    if exc is None:
        return                                  # 정상 완료 — `_worker` 가 이미 기록했다

    if isinstance(exc, BrokenProcessPool):
        _reset_pool()
    logger.error(f"백테스트 워커가 비정상 종료했다 (run={run_id}): {type(exc).__name__}")
    if not run_id:
        return
    try:
        br.set_error(
            run_id, "worker_died",
            "실행 워커가 비정상 종료했습니다("
            f"{type(exc).__name__}). 메모리 부족이나 프로세스 종료일 수 있습니다 — "
            "유니버스 범위를 줄여 다시 실행해 보세요.")
    except Exception:                           # noqa: BLE001
        logger.exception(f"워커 사망을 기록하지 못했다 (run={run_id})")


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

    ★Future 를 버리지 않는다★ 버리면 자식의 죽음이 어디에도 나타나지 않는다
    (`tests/test_backtest_worker_death.py` 가 그 사고를 재현한다). 첫 인자가
    run_id 라는 것은 두 호출부의 규약이고, 아니면 그냥 로그만 남긴다.
    """
    run_id = args[0] if args and isinstance(args[0], str) else None
    try:
        fut = _get_pool().submit(fn, *args)
    except BrokenProcessPool:
        # 이전 실행의 자식이 죽어 풀이 broken 이다 — 버리고 **한 번만** 다시 세운다.
        logger.warning("워커 풀이 broken 상태라 새로 세운다")
        _reset_pool()
        fut = _get_pool().submit(fn, *args)
    fut.add_done_callback(lambda f: _on_worker_done(run_id, f))


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


#: 저장소 실패의 후보 원인 — ★가설을 가를 수 있어야 관측이다★
#: 사용자 화면의 "연결이 불안정합니다"(status 폴링 3회 연속 실패)가 어느 쪽인지
#: 다음 번에 말할 수 있게 하는 것이 목적이다. 재현하지 못한 상태라 **고치지 않고
#: 관측만** 한다.
_STORE_FAILURE_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    # SQLAlchemy QueuePool 고갈 — pool_size=5 + overflow=10, pool_timeout 기본 30초.
    # 30초는 1초 폴링 주기보다 길어 요청이 쌓인다.
    ("pool_exhausted", ("queuepool", "connection pool", "pool limit")),
    # SQLite 폴백 시 워커의 진행 UPDATE 와 API 의 SELECT 가 쓰기 락에서 만난다.
    ("store_locked", ("database is locked", "database table is locked", "deadlock")),
    ("store_unreachable", ("could not translate host name", "could not connect",
                           "connection refused", "server closed the connection")),
)

#: 사용자에게 보일 문구 — ★원문은 절대 싣지 않는다★ DB 예외 문자열에는 접속
#: URL(자격증명 포함)이 섞일 수 있다. 분류만 내보내고 원문은 로그에 남긴다.
_STORE_FAILURE_MESSAGE = {
    "pool_exhausted": "실행 저장소 커넥션이 모두 사용 중입니다 — 잠시 후 재시도하세요.",
    "store_locked": "실행 저장소가 잠겨 있습니다(동시 쓰기) — 잠시 후 재시도하세요.",
    "store_unreachable": "실행 저장소에 연결할 수 없습니다 — 잠시 후 재시도하세요.",
    "unknown": "실행 저장소를 일시적으로 사용할 수 없습니다 — 원인을 확인 중입니다. 잠시 후 재시도하세요.",
}


def classify_store_failure(message: str) -> str:
    """저장소 실패 문자열을 후보 원인으로 분류한다. ★미상은 분류가 아니다★ —
    짚이는 것이 없으면 그럴듯한 라벨을 붙이지 않고 `"unknown"` 이라고 적는다."""
    low = (message or "").lower()
    for cause, needles in _STORE_FAILURE_HINTS:
        if any(n in low for n in needles):
            return cause
    return "unknown"


def _store_unavailable(exc: Exception, where: str) -> HTTPException:
    """503 + 분류된 사유. 원문은 로그에만 남긴다(자격증명 유출 방지)."""
    cause = classify_store_failure(str(exc))
    logger.warning(f"실행 저장소 실패({where}) cause={cause}: {exc}")
    return HTTPException(503, {"cause": cause, "message": _STORE_FAILURE_MESSAGE[cause]})


def _record_phase_seconds(tele: dict, marks: dict) -> None:
    """단계별 소요를 계측에 싣는다 — ★잰 것만 싣는다★.

    `marks` 는 `cb` 가 각 단계에 **처음 진입한** 시각과, 코어가 끝난 시각이다.
      load_s = 로딩 시작 → 시뮬레이션 시작 (시뮬레이션에 도달했을 때만)
      sim_s  = 시뮬레이션 시작 → 코어 종료

    ★미측정 ≠ 0★ 경계가 없으면 키를 만들지 않는다. `sim_s: 0` 을 넣으면
    "시뮬레이션이 0초였다"로 읽히는데, 사실은 거기까지 가지도 않은 것이다.
    (`.md` §30 의 cache hit rate 를 뺀 규율과 같다.)
    """
    ld, sim, end = marks.get("loading_data_t0"), marks.get("simulating_t0"), marks.get("core_end")
    if ld is not None and sim is not None:
        tele["load_s"] = round(sim - ld, 3)
    elif ld is not None and end is not None:
        # 시뮬레이션에 도달하지 못한 채 코어가 끝났다 — 로딩만 잰다.
        tele["load_s"] = round(end - ld, 3)
    if sim is not None and end is not None:
        tele["sim_s"] = round(end - sim, 3)


#: 결과의 진단 키 → 텔레메트리에 실을 **필드**. ★손으로 세지 않는다★
#:
#: 사유 원본(토큰별 사유·종목 목록·사유 히스토그램)은 결과에 그대로 있고,
#: 여기에는 **수치만** 싣는다 — 텔레메트리 행을 부풀리지 않기 위해서다.
_TELEMETRY_FIELDS: dict[str, tuple[str, ...]] = {
    "signal_path": ("vectorized", "per_bar", "failed", "vectorized_pct"),
    "macro_lookahead": ("pit", "live", "blocked", "pit_pct"),
    "fundamentals_pit": ("measured", "estimated", "unknown", "measured_pct"),
    "price_basis": ("state", "uniform_adjusted_pct"),
    "universe": ("survivorship", "effective", "fell_back"),
}


def _diagnostic_telemetry(result: dict | None) -> dict:
    """결과의 진단을 텔레메트리 필드로 접는다. ★순수 함수★

    ★없는 것에 키를 만들지 않는다★ 결과에 그 진단이 없거나 `None` 이면 여기에도
    키가 생기지 않는다. `None` 을 넣으면 나중에 이 행을 읽는 사람이 "재봤더니
    없더라" 로 읽는데, 그것은 하지 않은 진술이다 — `symbols_by_source` 가 이미
    같은 규율이다(`.md` §30 의 cache hit rate 를 넣지 않은 이유와 같다).

    ★모양이 다르면 추측하지 않는다★ dict 가 아니면 그냥 건너뛴다.
    """
    out: dict = {}
    for key, fields in _TELEMETRY_FIELDS.items():
        got = (result or {}).get(key)
        if isinstance(got, dict):
            out[key] = {f: got.get(f) for f in fields}
    ev = (result or {}).get("pit_evidence")
    if isinstance(ev, dict) and ev.get("status"):
        # ★한 줄로 답하는 값★ — 축별 사유는 결과에 그대로 있다.
        out["pit_status"] = ev["status"]
        for name in ("broken_axes", "unknown_axes"):
            if ev.get(name):
                out[name] = list(ev[name])
    return out


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
        # 단계별 시각 — ★`duration_s` 총합만으로는 병목을 못 가른다★
        # "5분 중 몇 분이 로딩이고 몇 분이 시뮬레이션인가" 를 답하려면 단계 경계가
        # 있어야 한다. `cb` 는 이미 단계를 보고 있으므로 계측 지점을 새로 만들지
        # 않고 여기에 시각만 찍는다. ★돌지 않은 단계는 키를 만들지 않는다★
        marks: dict[str, float] = {}

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
                # ★왜 느렸는지 나중에 물을 수 있게 한다★ 엔진이 로딩을 마치며
                # 출처 구성(db/kis/mock/unknown)을 한 번 보고한다. DB 적재가 얇아
                # KIS 로 떨어지면 종목당 ~74콜 × 초당 20콜 전역 한도라 200종목이면
                # 최소 12분이다 — 그 사실이 응답 어디에도 없었다.
                if evt.get("sources"):
                    tele["symbols_by_source"] = dict(evt["sources"])
                # ★"적재는 됐는데 구간을 덮지 못했다" 를 사용자가 볼 수 있게★
                if evt.get("coverage"):
                    tele["symbols_by_coverage"] = dict(evt["coverage"])
            elif phase == "simulating":
                stage = "simulating"
                pct = 30 + (55 * done / total if done and total else 0)
                msg = f"시뮬레이션 {done}/{total}일" if total else "주문·체결 시뮬레이션"
                if total:
                    tele["sim_days"] = total
            else:
                return

            marks.setdefault(f"{stage}_t0", time.perf_counter())

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
            marks["core_end"] = time.perf_counter()
            _record_phase_seconds(tele, marks)
        except _Cancelled:
            logger.info(f"backtest run {run_id} 취소 감지 — 워커 정지")
            tele["cancelled"] = True
            # ★실패·취소야말로 단계 분해가 필요하다★ 어디까지 갔다 멈췄는지가
            # 진단의 전부다. 도달하지 못한 단계는 여전히 키를 만들지 않는다.
            marks["core_end"] = time.perf_counter()
            _record_phase_seconds(tele, marks)
            _finish_telemetry(run_id, tele, meter, t_start, cpu0)
            return
        except Exception:
            logger.exception(f"backtest run {run_id} 엔진 실패")
            br.set_error(run_id, "engine_error", "백테스트 실행 중 오류가 발생했습니다.")
            tele["failure_code"] = "engine_error"
            marks["core_end"] = time.perf_counter()
            _record_phase_seconds(tele, marks)
            _finish_telemetry(run_id, tele, meter, t_start, cpu0)
            return

        # 엔진이 지표까지 계산해 반환 → 마무리 단계 전이 후 결과 저장
        br.advance(run_id, "calculating_metrics", message="성과·리스크 지표 정리", progress=88)
        br.advance(run_id, "persisting_results", message="재현 가능한 결과 저장", progress=96)
        # ★왜 느렸는지 나중에 물을 수 있게 한다★ 벡터화/per-bar 폴백 비율은
        # 실행 시간을 5배까지 가르는데 지금까지 응답 어디에도 없었다.
        # ★진단 집계는 한 곳에서★ 예전에는 여기서 키를 하나씩 꺼냈는데, 정작
        # 라우트가 그 키들을 응답에 넣지 않아 **한 번도 실린 적이 없었다**(R1).
        # 손으로 세는 자리를 없애 같은 단선이 다시 생기지 않게 한다.
        tele.update(_diagnostic_telemetry(result))
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
        # ★`is_pit_verified` 컬럼이 드디어 쓰인다★ 지금까지 아무도 넘기지 않아
        # 화면 배지가 모든 실행에서 "PIT 미검증" 이었다. ★미상은 거짓이 아니다★ —
        # 컬럼이 NULL 을 받으므로 3-값을 그대로 보낸다.
        from src.engine.run_evidence import is_pit_verified_flag
        _ev = (result or {}).get("pit_evidence") or {}
        r = br.set_result(run_id, result, is_mock_data=is_mock,
                          is_pit_verified=is_pit_verified_flag(
                              _ev.get("status") if isinstance(_ev, dict) else None))
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
        try:
            _submit(_worker, run_id, req.config, time.time())
        except Exception as e:
            # ★행을 만들어 놓고 닫지 않으면 고아가 된다★ 아무 워커도 집어 가지
            # 않는 `queued` 행이 남고, 프런트는 그것을 영원히 폴링한다.
            logger.exception("워커 디스패치 실패")
            try:
                br.set_error(run_id, "dispatch_failed",
                             f"백테스트 워커를 시작하지 못했습니다: {type(e).__name__}")
            except Exception:                   # noqa: BLE001
                logger.exception("디스패치 실패를 기록하지 못했다")
            # ★사유를 지우지 않는다★ "처리 중 오류" 로 뭉개면 원인을 못 찾는다.
            raise HTTPException(
                503, "백테스트 워커를 시작하지 못했습니다 — 잠시 후 다시 시도하세요 "
                     f"({type(e).__name__}).") from e
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
    except br.BacktestStoreError as e:
        raise _store_unavailable(e, "status") from e
    if st is None:
        raise HTTPException(404, "실행을 찾을 수 없습니다.")
    return st


@router.get("/runs/{run_id}/telemetry")
def run_telemetry(run_id: str):
    """실행 계측 조회 — ★쓰기 전용이던 계측을 읽을 수 있게 한다★.

    `_worker` 는 실행마다 `duration_s`·`cpu_s`·`cpu_util_pct`·`peak_rss_mb`·
    `db_queries`·`queue_wait_s`·`symbols_by_source`·`load_s`·`sim_s` 를 남기는데,
    그것을 돌려주는 경로가 없었다. 그래서 "왜 5분 걸렸나" 를 물어도 로딩과
    시뮬레이션 중 어느 쪽인지 분해할 수 없었다.

    404/503 매핑은 `run_status` 와 **같은 규약**이다 — 진짜 없는 실행만 404,
    저장소 오류는 503(프런트가 '만료된 링크'로 오인하지 않게).

    ★미상은 0 이 아니다★ 계측이 아직 없으면 `{}` 도 0 도 아니고
    `available: false` + 사유다.
    """
    try:
        st = br.get_status(run_id, strict=True)
    except br.BacktestStoreError as e:
        raise _store_unavailable(e, "telemetry.status") from e
    if st is None:
        raise HTTPException(404, "실행을 찾을 수 없습니다.")
    try:
        tele = br.get_telemetry(run_id, strict=True)
    except br.BacktestStoreError as e:
        raise _store_unavailable(e, "telemetry") from e
    if tele is None:
        reason = ("실행이 아직 끝나지 않아 계측이 기록되기 전입니다."
                  if st.get("status") not in br.TERMINAL
                  else "이 실행에는 계측 기록이 없습니다(계측 도입 이전이거나 계측 컬럼 미사용).")
        return {"run_id": run_id, "status": st.get("status"),
                "available": False, "telemetry": None, "reason": reason}
    return {"run_id": run_id, "status": st.get("status"),
            "available": True, "telemetry": tele, "reason": None}


@router.get("/runs/{run_id}")
def run_full(run_id: str):
    try:
        r = br.get_run(run_id, strict=True)
    except br.BacktestStoreError as e:
        raise _store_unavailable(e, "full") from e
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
    # ★재시도도 같은 규율★ 제출이 실패하면 방금 만든 행을 닫는다 — 고아 `queued`
    # 를 남기지 않는다(`create_run` 과 같은 이유).
    try:
        _submit(_worker, new_id, config, time.time())
    except Exception as e:
        logger.exception("재시도 워커 디스패치 실패")
        try:
            br.set_error(new_id, "dispatch_failed",
                         f"백테스트 워커를 시작하지 못했습니다: {type(e).__name__}")
        except Exception:                       # noqa: BLE001
            logger.exception("디스패치 실패를 기록하지 못했다")
        raise HTTPException(
            503, "백테스트 워커를 시작하지 못했습니다 — 잠시 후 다시 시도하세요 "
                 f"({type(e).__name__}).") from e
    return {"run_id": new_id, "status": "queued", "retried_from": run_id}


@router.delete("/runs/{run_id}")
def run_delete(run_id: str):
    if not br.delete_run(run_id):
        raise HTTPException(404, "실행을 찾을 수 없습니다.")
    return {"deleted": True}


def _window_as_of(months: dict) -> str | None:
    """백테스트 창의 **마지막 달 말일**. ★없으면 지어내지 않는다★ (P9 ①)."""
    import calendar
    if not months:
        return None
    try:
        y, m = (int(x) for x in max(months).split("-"))
        return f"{y:04d}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}"
    except (ValueError, TypeError, calendar.IllegalMonthError):
        return None


def _proxy_selection(window_as_of: str | None, truncated: bool, prox: dict) -> dict:
    """대리계열 선택의 ★시점 표기★ — 두 분기가 같은 라벨을 쓰게 한 곳에서 만든다."""
    from src.engine.factor_exposure import proxy_table_block
    return {
        "window_as_of": window_as_of,
        "truncated_to_window": bool(truncated),
        # ★자르지 않았으면 지킨 것이 아니다★ `resolve_proxies()` 는 as_of 를 안
        # 주면 `as_of_honored: True` 를 돌려준다 — 계열 축에서는 참이지만(자를
        # 것이 없었다) 그대로 실으면 "창 시점을 지켰다" 로 읽힌다. 공허한 참이다.
        "as_of_honored": bool(truncated and prox.get("as_of_honored")),
        "reason": (None if truncated else
                   "대리계열을 창 시점으로 자르지 않았습니다 — 계열은 오늘까지이고 "
                   "회귀는 공통 달 교집합으로 돌았습니다(계수에 룩어헤드는 "
                   "없습니다). 다만 어느 후보를 쓸지는 오늘까지의 관측 수로 "
                   "골랐습니다. truncate_to_window=true 로 자를 수 있고, 그러면 "
                   "수치가 달라지거나 쓸 계열이 없어 거절될 수 있습니다."),
        # 표가 그 창에 유효했는가 — 절단 여부와 **무관한** 질문이다.
        "proxy_table": proxy_table_block(window_as_of),
    }


@router.get("/runs/{run_id}/factor-attribution")
def run_factor_attribution(run_id: str, truncate_to_window: bool = False):
    """★무엇이 이 수익을 만들었나★ 실현수익을 매크로 팩터와 α 로 쪼갠다 (P3-2).

    결합 OLS `r_t = α + Σβᵢfᵢ,t` — 단변량이면 상관된 팩터의 공통 변동을 중복
    흡수한다. 팩터별 VIF 를 함께 내며, 높은 팩터의 기여는 짝과 상쇄되므로
    **개별 값으로 읽지 말라**는 라벨이 붙는다.

    ★산술 합과 복리 총수익은 다른 숫자다★ 항등식은 월별 수익률의 산술 합에
    대해 닫히고, 복리와의 차이는 `compounding_gap_pct` 로 나간다.

    아직 끝나지 않았거나 옛 스키마라 월별 수익률이 없으면 **200 + 사유**다 —
    실행이 존재하는데 500 을 내지 않는다.
    """
    try:
        r = br.get_run(run_id, strict=True)
    except br.BacktestStoreError as e:
        raise _store_unavailable(e, "full") from e
    if r is None:
        raise HTTPException(404, "실행을 찾을 수 없습니다.")

    from src.api.json_safe import finite_payload
    from src.engine.backtest_attribution import (
        factor_attribution,
        monthly_returns_from_result,
    )

    monthly = monthly_returns_from_result(r.get("result"))
    if not monthly["available"]:
        return {"available": False, "reason": monthly["reason"],
                "run_id": run_id, "status": r.get("status")}

    # ★귀인한 창을 응답이 말한다 (P9 ①)★ 대리계열 **선택**은 오늘까지의 관측
    # 수로 이뤄지는데, 그 사실이 응답 어디에도 없었다. 계수에는 수치적
    # 룩어헤드가 없다(`factor_attribution` 이 공통 달로 교집합을 잡는다) —
    # 고치는 것은 **선택의 시점 표기**다.
    # ★라벨 기본 · 절단은 플래그★ 절단을 기본으로 켜면 계열이 짧아져 귀인
    # 수치가 움직인다. 그것은 이 슬라이스의 범위가 아니다(P5 ③ 과 같은 규율).
    window_as_of = _window_as_of(monthly["returns"])
    try:
        from src.engine.factor_exposure import resolve_proxies
        prox = resolve_proxies(as_of=window_as_of if truncate_to_window else None)
    except Exception:
        logger.exception("팩터 계열 해소 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")
    # ★모든 분기가 같은 라벨을 낸다★ 절단을 켜면 계열이 짧아져 아무 팩터도
    # 안 남을 수 있다(정직한 거절이다). 그때 라벨이 빠지면 소비자는 **왜**
    # 거절됐는지 — 자른 탓인지 수집기가 빈 탓인지 — 구별할 수 없다.
    if not prox.get("available"):
        return {"available": False, "reason": prox.get("reason"),
                "run_id": run_id, "status": r.get("status"),
                "proxy_selection": _proxy_selection(
                    window_as_of, truncate_to_window, prox)}

    out = factor_attribution(monthly["returns"], prox["resolved"])
    out.update(proxy_selection=_proxy_selection(
        window_as_of, truncate_to_window, prox))
    out.update(run_id=run_id, status=r.get("status"),
               strategy_name=r.get("strategy_name"),
               months_from_run=monthly["n_months"],
               skipped_rows=monthly["skipped_rows"],
               proxies={f: i["series"] for f, i in prox["resolved"].items()},
               unresolved=prox.get("unresolved", {}))
    return finite_payload(out)
