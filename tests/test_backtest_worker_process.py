"""백테스트 워커가 **별도 프로세스**에서 돈다 (P0-2).

`test_backtest_run_routes.py` 는 `_submit` 을 스레드로 갈아끼워 오케스트레이션 계약을
검증한다. 그러면 **프로덕션 운송 수단(프로세스 풀)은 누가 검증하는가** — 이 파일이다.

감사 실측 근거(`scripts/bench_backtest.py --stress`, 4코어):

    동시 1 → CPU 107% · 동시 2 → 103% · 동시 4 → 105%   (GIL 이 천장)
    동시 4 = 27.06s  vs  순차 4회 = 16.6s               (스레드가 63% 손해)

스레드는 처리량을 하나도 사지 못했다. 그래서 프로세스로 옮겼고, 이 파일은 그것이
**실제로** 일어나는지 본다 — 설정값이 아니라 pid 로.
"""
import json
import multiprocessing as mp
import os
import time

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402

from src.api import backtest_run_routes as brr  # noqa: E402


def test_production_submit_uses_the_process_pool_not_a_thread():
    """★프로덕션 디스패치는 프로세스 풀이다★

    `_submit` 은 테스트가 갈아끼우는 지점이다. 갈아끼우지 않은 기본 구현이 스레드로
    되돌아가면 GIL 천장이 그대로 돌아온다 — 그 회귀를 여기서 잡는다.
    """
    src = brr._submit.__doc__ or ""
    assert "프로세스 풀" in src
    # 구현이 실제로 풀을 쓰는지 — 호출을 가로채 확인한다(풀을 실제로 띄우지 않는다).
    called = {}

    class _FakePool:
        def submit(self, fn, *a):
            called["fn"], called["args"] = fn, a

    orig = brr._get_pool
    brr._get_pool = lambda: _FakePool()
    try:
        brr._submit(len, "abc")
    finally:
        brr._get_pool = orig
    assert called["fn"] is len and called["args"] == ("abc",)


def test_pool_uses_spawn_not_fork():
    """★fork 가 아니라 spawn★

    기동 시 프리워밍 데몬 스레드가 7개 돌고 SQLAlchemy 엔진이 살아 있다. fork 는
    스레드를 복제하지 않으면서 그들이 잡고 있던 락은 복제하고, 부모의 DB 커넥션을
    자식이 물려받는다. 되돌리면 간헐적이고 재현이 어려운 고장이 된다.
    """
    pool = brr._get_pool()
    try:
        ctx = getattr(pool, "_mp_context", None)
        assert ctx is not None, "풀에 mp_context 가 없다"
        assert ctx.get_start_method() == "spawn", \
            f"start method 가 spawn 이 아니다: {ctx.get_start_method()}"
    finally:
        brr.shutdown_pool()


def test_max_workers_is_one_until_p0_3(monkeypatch):
    """P0-2 는 동시성 1 이다 — 확장은 P0-3 에서 처리량 가드와 함께 온다."""
    monkeypatch.delenv("BACKTEST_WORKERS", raising=False)
    assert brr._max_workers() == 1
    monkeypatch.setenv("BACKTEST_WORKERS", "4")
    assert brr._max_workers() == 4, "환경변수로 덮을 수 있어야 한다"
    monkeypatch.setenv("BACKTEST_WORKERS", "쓰레기")
    assert brr._max_workers() == 1, "잘못된 값이 크래시를 내면 안 된다"


def test_shutdown_does_not_wait_for_running_jobs():
    """★종료가 기다리면 안 된다★

    `shutdown(wait=True)` 면 진행 중인 백테스트가 끝날 때까지 uvicorn 종료가 막힌다
    (large 실측 19.2분). 예전 daemon 스레드는 즉시 죽었고, 유실된 실행은
    `sweep_orphaned()` 가 failed 로 확정한다 — 그 복구 경로를 유지한다.
    """
    pool = brr._get_pool()
    fut = pool.submit(time.sleep, 8)   # 아직 도는 작업을 하나 남겨 둔다
    t0 = time.perf_counter()
    brr.shutdown_pool()
    elapsed = time.perf_counter() - t0
    assert elapsed < 4.0, f"종료가 {elapsed:.1f}초 걸렸다 — 진행 중 작업을 기다렸다"
    fut.cancel()


def test_worker_signature_is_picklable_for_spawn():
    """spawn 은 워커와 인자를 피클한다 — 모듈 최상위 함수여야 하고 인자가 단순해야 한다."""
    import pickle
    assert brr._worker.__module__ == "src.api.backtest_run_routes"
    pickle.loads(pickle.dumps(("run", {"universe": "kospi200"}, time.time())))


@pytest.mark.skipif(mp.get_start_method(allow_none=True) == "fork",
                    reason="spawn 컨텍스트가 필요하다")
def test_child_process_is_really_separate_and_clean():
    """★진짜로 다른 프로세스인가★ pid 와 스레드 수로 확인한다.

    자식이 프리워밍 데몬 스레드를 물려받았다면 fork 로 새어 들어간 것이다.
    """
    pool = brr._get_pool()
    try:
        info = pool.submit(_child_report).result(timeout=180)
    finally:
        brr.shutdown_pool()
    assert info["pid"] != os.getpid(), "워커가 API 프로세스 안에서 돌았다"
    assert info["threads"] <= 3, f"자식이 스레드를 물려받았다: {info['threads']}"


def _child_report() -> dict:
    """자식에서 실행 — 모듈 최상위여야 피클된다."""
    import threading
    return {"pid": os.getpid(), "threads": threading.active_count()}


def test_telemetry_roundtrips_and_absent_is_none():
    """★계측은 남고, 없으면 None 이다★ 0 을 지어내지 않는다."""
    import src.data.backtest_runs as br
    rid = br.create_run("telemetry-test", {"_t": True}, requested_by="test")
    if rid is None:
        pytest.skip("실행 저장소를 쓸 수 없다")
    try:
        assert br.get_telemetry(rid) is None, "쓰기 전에는 None 이어야 한다"
        payload = {"worker_pid": 1234, "duration_s": 1.5, "db_queries": 7}
        assert br.set_telemetry(rid, payload) is True
        got = br.get_telemetry(rid)
        assert got == payload, got
        assert json.dumps(got)  # 직렬화 가능
    finally:
        br.delete_run(rid)
