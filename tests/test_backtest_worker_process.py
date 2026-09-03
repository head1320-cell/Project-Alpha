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

    class _FakeFuture:
        """★진짜 `submit()` 은 Future 를 돌려준다★

        예전 더블은 `None` 을 돌려줬다. 그때는 `_submit` 이 반환값을 버렸으니
        통과했지만, **버리는 것이 바로 그 사고였다**(`test_backtest_worker_death`).
        더블이 실제 계약을 모사하지 않으면 그 계약을 시험할 수 없다.
        """

        def add_done_callback(self, cb):
            called["callback"] = cb

    class _FakePool:
        def submit(self, fn, *a):
            called["fn"], called["args"] = fn, a
            return _FakeFuture()

    orig = brr._get_pool
    brr._get_pool = lambda: _FakePool()
    try:
        brr._submit(len, "abc")
    finally:
        brr._get_pool = orig
    assert called["fn"] is len and called["args"] == ("abc",)
    # ★Future 를 버리지 않는다★ 버리면 자식의 죽음이 어디에도 나타나지 않는다.
    assert callable(called.get("callback")), (
        "submit 의 Future 에 콜백을 달지 않았다 — 워커가 죽어도 아무도 모른다")


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


def test_max_workers_leaves_a_core_for_the_api(monkeypatch):
    """★코어를 전부 쓰지 않는다 (P0-3)★

    `.md` §9 는 "폭주 백테스트가 API 요청을 굶기면 안 된다" 를 hard requirement 로
    적었다. `uvicorn --workers 1` 인 API 가 같은 기계에서 도는데 마지막 코어까지
    워커에게 주면 정확히 그 일이 일어난다.
    """
    monkeypatch.delenv("BACKTEST_WORKERS", raising=False)
    n = brr._max_workers()
    usable = brr._usable_cpus()
    assert n == max(1, min(usable - 1, brr._MAX_WORKERS_CAP)), (n, usable)
    if usable > 1:
        assert n < usable, "코어를 전부 워커에게 줬다 — API 가 굶는다"


def test_max_workers_is_capped_and_overridable(monkeypatch):
    """상한과 덮어쓰기 — 실행당 RSS 가 90~247 MB 라(감사 §3.6) 무한정 늘리면
    CPU 가 아니라 메모리에서 터진다."""
    monkeypatch.setenv("BACKTEST_WORKERS", "7")
    assert brr._max_workers() == 7, "명시적 지정은 존중한다(운영 기계가 다를 수 있다)"
    monkeypatch.delenv("BACKTEST_WORKERS", raising=False)
    assert brr._max_workers() <= brr._MAX_WORKERS_CAP, "기본값에는 하드 캡이 걸린다"
    monkeypatch.setenv("BACKTEST_WORKERS", "쓰레기")
    assert brr._max_workers() >= 1, "잘못된 값이 크래시를 내면 안 된다"


def _spin(seconds: float) -> int:
    """CPU 바운드 작업 — 자식에서 돌려면 모듈 최상위여야 한다.

    ★PID 를 돌려준다★ "GIL 큐가 아니다" 는 시간이 아니라 **어느 프로세스가 돌았는가**
    로 직접 잴 수 있다. 스레드였다면 전부 같은 PID 다.
    """
    t0 = time.perf_counter()
    x = 0
    while time.perf_counter() - t0 < seconds:
        x += 1
    return os.getpid()


def _who(hold: float) -> int:
    """워밍업용 — 잠깐 자고 자기 PID 를 보고한다."""
    time.sleep(hold)
    return os.getpid()


def _warm_until_all_workers_are_up(pool, n: int, timeout: float = 30.0) -> set[int]:
    """★워커 n 개가 **전부** 살아날 때까지 기다린다★

    예전 워밍업은 `list(pool.map(int, [0] * n))` 이었는데, `int` 가 즉시 끝나서
    **먼저 준비된 워커 하나가 n 개를 다 처리했다.** 실측: 워밍업 뒤 살아 있는 워커가
    1/3 이었고 나머지 2개는 **측정 구간 안에서** 스폰됐다 — `spawn` 이라 자식이
    파이썬을 새로 띄우고 모듈 트리를 전부 다시 import 한다. 0.6초짜리 작업 위에
    0.7초가 얹혀 임계 1.26초를 0.04초 차이로 넘겼다(부하 걸면 3/3 재현).

    각 작업이 잠깐 자므로 한 워커가 전부 삼킬 수 없다. 서로 다른 PID 를 n 개 볼
    때까지 반복한다.

    ★풀이 아예 별개 프로세스가 아니면 즉시 포기한다★ 스레드 풀이면 워커의 PID 가
    **테스트 자신의 PID** 와 같아서 서로 다른 PID 가 영영 n 개가 되지 않는다. 그때
    타임아웃까지 버티면 31초를 쓰고 "워밍업이 1/3 만 깨웠다" 는 **엉뚱한 사유**로
    실패한다 — 진짜 사유는 "GIL 큐" 이고 그 단언은 도달조차 못 한다. (실제로 변이
    프로브를 돌려 이 순서 문제를 발견했다.) 그래서 여기서 빠져나와 아래 단언들이
    말하게 한다.
    """
    seen: set[int] = set()
    t0 = time.perf_counter()
    while len(seen) < n and time.perf_counter() - t0 < timeout:
        futs = [pool.submit(_who, 0.25) for _ in range(n)]
        seen.update(f.result() for f in futs)
        if os.getpid() in seen:
            break            # 별개 프로세스가 아니다 — 기다려도 달라지지 않는다
    return seen


def test_pool_gives_real_parallelism_not_a_gil_queue(monkeypatch):
    """★프로세스 풀이 실제로 병렬이다 (P0-3)★

    수정 전(스레드) 실측: 4코어에서 동시 1/2/4 의 CPU 사용률이 107/103/105% 로 고정,
    동시 4개가 순차 4회보다 **63% 느렸다.** 스레드는 처리량을 하나도 사지 못했다.

    여기서는 **백테스트가 아니라 순수 CPU 작업**을 쓴다 — 병렬성이라는 성질만
    보려는 것이고, 실데이터·시드에 흔들리지 않아야 가드로 쓸 수 있다.
    (백테스트 실측치는 `docs/specs/2026-08-22-backtest-benchmark-results.md` 에 있다.)

    ★성질과 시간을 나눠 건다★ 이 테스트는 오래 플레이크였는데, 원인은 병렬성이
    아니라 워밍업이 워커를 하나만 깨운 것이었다(`_warm_until_all_workers_are_up`
    주석 참조). 그래서 두 단언을 분리한다:

      · **PID 개수** — 부하와 무관한 결정적 단언. "별개 프로세스" 를 사실로 말한다.
        스레드 풀로 되돌리면 PID 가 1개가 되어 곧바로 빨개진다.
      · **시간** — "동시에 돌았다". ★원리상 부하에 민감하다★ 배리어가 여유를 2배로
        넓혔을 뿐 없애지는 못한다. 둘 중 하나만으로는 성질이 닫히지 않는다
        (PID 만이면 순차 실행도 통과하고, 시간만이면 지금의 플레이크로 돌아간다).
    """
    monkeypatch.setenv("BACKTEST_WORKERS", "3")
    brr.shutdown_pool()
    pool = brr._get_pool()
    try:
        n = brr._max_workers()
        # ★스폰 비용을 측정에서 뺀다★ 워커가 전부 살아난 뒤에 재기 시작한다.
        warmed = _warm_until_all_workers_are_up(pool, n)

        unit = 0.6
        t0 = time.perf_counter()
        pids = list(pool.map(_spin, [unit] * n))
        wall = time.perf_counter() - t0
    finally:
        brr.shutdown_pool()

    # ★가장 먼저 가른다★ 워커가 테스트와 **같은 프로세스**면 그것이 곧 GIL 큐다.
    # 이 단언이 워밍업 단언보다 앞서야 스레드 회귀가 올바른 사유로 보고된다.
    assert os.getpid() not in warmed, (
        "워커가 테스트와 같은 프로세스에서 돌았다 — 프로세스 풀이 아니라 GIL 큐다")

    assert len(warmed) == n, (
        f"워밍업이 워커를 {len(warmed)}/{n} 개만 깨웠다 — 나머지는 측정 구간 안에서 "
        f"스폰되고, 그러면 이 테스트는 병렬성이 아니라 스폰 지연을 잰다")

    # ★GIL 큐면 PID 가 1개다★ 시간과 무관하게 성질을 직접 가른다.
    assert len(set(pids)) == n, (
        f"{n}개 작업이 서로 다른 프로세스 {len(set(pids))}개에서 돌았다 — "
        f"프로세스 풀이 아니라 GIL 큐다")

    serial = unit * n
    # 완전 병렬이면 `unit`, GIL 큐면 `serial`. 실측 여유를 두고 그 중간을 가른다.
    assert wall < serial * 0.7, (
        f"동시 {n}개가 {wall:.2f}초 — 순차 {serial:.2f}초 대비 이득이 없다(GIL 큐)")


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
