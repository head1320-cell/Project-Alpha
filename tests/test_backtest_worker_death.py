"""워커 프로세스가 **죽었을 때** 무슨 일이 일어나는가.

## 왜 이 파일이 생겼나 — ★재현된 사고★

사용자 신고: *"로딩이 엄청 오래 걸리고 중간에 중단되는 상황이 계속 일어난다."*
추적해 보니 `_submit` 이 `ProcessPoolExecutor.submit()` 이 돌려주는 **Future 를
버리고 있었다.** 프로덕션과 같은 spawn 컨텍스트로 재현한 결과:

    ① 정상 작업: 정상 완료
    ② 자식을 SIGKILL — Future 를 버렸으므로 예외가 아무 데도 안 보인다
    ③ ★BrokenProcessPool — 제출이 즉시 실패★
    ④ ★BrokenProcessPool — 제출이 즉시 실패★

귀결이 둘이다:

1. 자식이 죽으면(OOM killer 가 대표적이다 — 실행당 RSS 90~247MB × 워커 4개)
   `_worker` 의 `except` 는 **돌지 못한다.** 그 행은 비종료 상태로 남고,
   `RunMonitor` 는 1초마다 영원히 폴링한다 → **"로딩이 끝나지 않는다."**
2. 풀이 **영구히** broken 이 된다. `_POOL` 은 앱 종료 외에 재설정되지 않으므로
   그 뒤 모든 백테스트가 실패한다 → **"계속 일어난다."**

★값만 보는 테스트로는 이것을 잡을 수 없다★ — 버려진 Future 는 어떤 응답도
바꾸지 않는다. 그래서 **자식을 실제로 죽이고** 행이 닫히는지 본다.
"""
from __future__ import annotations

import os
import signal
import time

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402

import src.data.backtest_runs as br  # noqa: E402
from src.api import backtest_run_routes as brr  # noqa: E402

TERMINAL = ("completed", "failed", "cancelled")


def _suicide(run_id: str, *_a) -> None:
    """자식이 OOM killer 에게 맞은 것과 같은 죽음. ★모듈 최상위여야 피클된다.★"""
    os.kill(os.getpid(), signal.SIGKILL)


def _fine(run_id: str, *_a) -> str:
    return "ok"


@pytest.fixture
def run_id():
    rid = br.create_run("워커 사망 테스트", {"_t": True}, requested_by="test")
    if rid is None:
        pytest.skip("실행 저장소를 쓸 수 없다")
    yield rid
    try:
        br.delete_run(rid)
    except Exception:
        pass


def _await_terminal(rid: str, timeout: float = 60.0) -> dict | None:
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout:
        st = br.get_status(rid)
        if st and st["status"] in TERMINAL:
            return st
        time.sleep(0.2)
    return br.get_status(rid)


def test_a_killed_worker_closes_its_run_instead_of_hanging(run_id):
    """★사고의 핵심★ 자식이 SIGKILL 되면 그 실행은 **failed 로 닫혀야** 한다.

    수정 전에는 Future 를 버려서 아무도 그 죽음을 관측하지 못했고, 행은
    비종료로 남아 프런트가 영원히 폴링했다.
    """
    brr.shutdown_pool()
    try:
        brr._submit(_suicide, run_id)
        st = _await_terminal(run_id)
    finally:
        brr.shutdown_pool()

    assert st is not None
    assert st["status"] == "failed", (
        f"자식이 죽었는데 실행이 '{st['status']}' 로 남아 있다 — "
        "프런트는 이 상태를 영원히 폴링한다")
    assert st.get("error_message"), "왜 끝났는지 말하지 않는다"


def test_the_pool_recovers_after_a_child_dies(run_id):
    """★풀이 영구히 죽어 있으면 안 된다★

    `ProcessPoolExecutor` 는 자식이 비정상 종료하면 **풀 전체**를 broken 으로
    표시하고, 이후 모든 `submit()` 이 즉시 실패한다. 재설정하지 않으면 사용자가
    말한 "계속 일어난다" 가 된다.
    """
    brr.shutdown_pool()
    try:
        brr._submit(_suicide, run_id)
        _await_terminal(run_id)
        # 죽은 뒤에 새 작업이 **돌아야** 한다.
        rid2 = br.create_run("복구 확인", {"_t": True}, requested_by="test")
        if rid2 is None:
            pytest.skip("실행 저장소를 쓸 수 없다")
        try:
            brr._submit(_fine, rid2)      # 예외가 나면 여기서 터진다
            time.sleep(2)
        finally:
            br.delete_run(rid2)
    finally:
        brr.shutdown_pool()


def test_submit_still_dispatches_to_the_process_pool(run_id):
    """★짝★ 정상 경로가 망가지지 않았는지 — 콜백을 다느라 제출을 잃으면 안 된다."""
    brr.shutdown_pool()
    try:
        brr._submit(_fine, run_id)
        time.sleep(2)
        st = br.get_status(run_id)
        # `_fine` 은 상태를 바꾸지 않는다 — 여기서 거는 것은 "죽지도 실패하지도
        # 않았다" 이다. 콜백이 성공한 작업까지 failed 로 닫으면 이 단언이 깨진다.
        assert st is not None and st["status"] not in ("failed", "cancelled"), (
            f"정상 완료한 작업을 '{st and st['status']}' 로 닫았다")
    finally:
        brr.shutdown_pool()


def test_create_run_does_not_leave_an_orphan_row_when_dispatch_fails(monkeypatch):
    """★제출이 실패하면 방금 만든 행을 닫는다★

    `create_run` 은 행을 **먼저** 만들고 그다음 제출한다. 제출이 터지면 그 행은
    `queued` 로 영원히 남고 — 아무 워커도 집어 가지 않는다 — 사용자는 원인을 알
    수 없는 500 을 받는다.
    """
    from fastapi import HTTPException

    def _boom(*a, **k):
        raise RuntimeError("풀이 고장났다")

    monkeypatch.setattr(brr, "_submit", _boom)
    seen: dict = {}
    real_set_error = br.set_error

    def _spy(rid, code, msg):
        seen["run_id"], seen["code"], seen["msg"] = rid, code, msg
        return real_set_error(rid, code, msg)

    monkeypatch.setattr(br, "set_error", _spy)

    with pytest.raises(HTTPException) as e:
        brr.create_run(brr.CreateRunRequest(config={"_t": True},
                                            strategy_name="디스패치 실패"))
    try:
        assert seen.get("run_id"), "행을 만들어 놓고 닫지 않았다 — 고아 queued 가 남는다"
        st = br.get_status(seen["run_id"])
        assert st and st["status"] == "failed", st
        # ★사유를 지우지 않는다★ "처리 중 오류" 로 뭉개면 운영자가 원인을 못 찾는다.
        assert e.value.status_code in (500, 503)
        assert "처리 중 오류가 발생했습니다." != e.value.detail, (
            "실패 사유가 일반 문구로 뭉개졌다")
    finally:
        if seen.get("run_id"):
            br.delete_run(seen["run_id"])


# ══════════════════════════════════════════════════════════════════════════
# ★고아를 주기적으로 거둔다★ (커밋 ②)
# ══════════════════════════════════════════════════════════════════════════
#
# `sweep_orphaned()` 는 `run_startup()` 에서 **기동 시 한 번만** 불렸다. 그래서
# 워커가 죽어 비종료로 남은 행은 **서버를 재시작할 때까지** 그대로였다 — 사용자는
# 끝나지 않는 로딩을 보다가, 재시작 뒤에야 "중단됨" 을 본다.
#
# 콜백(커밋 ①)이 대부분을 잡지만 그것도 만능이 아니다: API 프로세스 자체가 죽거나
# 배포로 교체되면 콜백도 함께 사라진다. 주기 스윕이 그 마지막 그물이다.

def test_the_orphan_sweeper_runs_periodically_not_only_at_startup(monkeypatch):
    """★기동 1회면 서버를 재시작해야만 복구된다★

    ★소스 문자열이 아니라 동작으로 건다★ (BE) — 예전에는 `threading.Thread(
    target=_orphan_sweep_bg, ...)` 라는 **글자**를 찾았다. 데몬을 등록부
    (`_start_daemon_once`)로 옮기자 동작은 그대로인데 이 테스트만 깨졌다.
    기동 시퀀스가 **실제로** 그 루프를 넘기는지를 본다.
    """
    import asyncio

    from src.startup import lifecycle
    started: dict = {}
    monkeypatch.setattr(lifecycle, "_start_daemon_once",
                        lambda name, target: started.setdefault(name, target) and "started")
    asyncio.run(lifecycle.run_startup())
    assert started.get("orphan_sweep") is lifecycle._orphan_sweep_bg, (
        "기동 시퀀스가 주기 스윕 데몬을 띄우지 않는다 — 워커가 죽으면 재시작까지 "
        f"복구되지 않는다: {sorted(started)}")


def test_the_sweeper_loop_actually_calls_sweep_orphaned(monkeypatch):
    """★루프가 진짜로 스윕을 부르는가★ — 이름만 있고 안 부르면 장식이다."""
    from src.startup import lifecycle
    calls = {"n": 0}

    def _fake_sweep(*a, **k):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise KeyboardInterrupt         # 루프를 빠져나오는 탈출구
        return 0

    monkeypatch.setattr("src.data.backtest_runs.sweep_orphaned", _fake_sweep)
    monkeypatch.setattr(lifecycle, "_ORPHAN_SWEEP_SEC", 0.01, raising=False)
    try:
        lifecycle._orphan_sweep_bg()
    except KeyboardInterrupt:
        pass
    assert calls["n"] >= 2, f"스윕이 {calls['n']}번만 불렸다 — 주기 실행이 아니다"


# ══════════════════════════════════════════════════════════════════════════
# ★두 복구 경로를 **따로** 건다★
# ══════════════════════════════════════════════════════════════════════════
#
# 변이 배터리에서 B2(`_submit` 의 재설정)와 B2b(`_on_worker_done` 의 재설정)가
# 각각 살아남았다 — 둘 중 하나만 있어도 복구가 되기 때문이다(서로를 가린다).
# 둘을 **동시에** 없애면 시스템이 깨끗이 실패하지 않고 **멈춘다**(실측: 10분
# 예산을 소진). 즉 방어가 이중이라는 것은 의도지만, 그러면 종단 테스트로는 각
# 경로를 가를 수 없다. 그래서 여기서 기제를 하나씩 직접 건다.

def test_reset_pool_actually_replaces_the_pool():
    """★재설정이 진짜 새 풀을 만드는가★ 이름만 있고 같은 객체를 돌려주면 장식이다."""
    brr.shutdown_pool()
    try:
        p1 = brr._get_pool()
        brr._reset_pool()
        p2 = brr._get_pool()
        assert p1 is not p2, "재설정 뒤에도 같은 풀 객체다 — broken 상태가 그대로다"
    finally:
        brr.shutdown_pool()


def test_a_dead_child_triggers_a_pool_reset(monkeypatch):
    """★B2b 를 따로 건다★ 자식 사망(BrokenProcessPool)이면 풀을 버려야 한다."""
    from concurrent.futures.process import BrokenProcessPool
    hit = {"n": 0}
    monkeypatch.setattr(brr, "_reset_pool", lambda: hit.__setitem__("n", hit["n"] + 1))
    monkeypatch.setattr(br, "set_error", lambda *a, **k: True)

    class _Fut:
        def exception(self):
            return BrokenProcessPool("자식이 죽었다")

    brr._on_worker_done("rid", _Fut())
    assert hit["n"] == 1, "자식이 죽었는데 풀을 재설정하지 않았다"


def test_a_healthy_finish_does_not_reset_the_pool(monkeypatch):
    """★짝★ 정상 완료마다 풀을 버리면 워커 재기동 비용(spawn 4.4초)을 매번 낸다."""
    hit = {"n": 0}
    monkeypatch.setattr(brr, "_reset_pool", lambda: hit.__setitem__("n", hit["n"] + 1))

    class _Fut:
        def exception(self):
            return None

    brr._on_worker_done("rid", _Fut())
    assert hit["n"] == 0, "정상 완료인데 풀을 버렸다"


def test_submit_retries_once_when_the_pool_is_broken(monkeypatch):
    """★B2 를 따로 건다★ broken 풀을 만나면 버리고 **한 번** 다시 세운다.

    재시도가 없으면 한 번 죽은 뒤 API 재시작까지 모든 백테스트가 실패한다 —
    사용자가 말한 "계속 일어난다" 가 그것이다.
    """
    from concurrent.futures.process import BrokenProcessPool
    calls = {"submit": 0, "reset": 0}

    class _Fut:
        def add_done_callback(self, cb):
            pass

    class _Pool:
        def submit(self, fn, *a):
            calls["submit"] += 1
            if calls["submit"] == 1:
                raise BrokenProcessPool("풀이 고장났다")
            return _Fut()

    pool = _Pool()
    monkeypatch.setattr(brr, "_get_pool", lambda: pool)
    monkeypatch.setattr(brr, "_reset_pool", lambda: calls.__setitem__("reset", 1))
    brr._submit(_fine, "rid")          # 예외가 새어 나오면 실패
    assert calls["reset"] == 1, "broken 풀을 버리지 않았다"
    assert calls["submit"] == 2, f"재시도하지 않았다 (submit {calls['submit']}회)"


# ══════════════════════════════════════════════════════════════════════════
# ★콜드 로딩의 비용을 보이게 한다★ (커밋 ③)
# ══════════════════════════════════════════════════════════════════════════
#
# 진단의 두 번째 축은 **데이터 부족**이다. DB 적재가 얇으면(`len(df) >= 20` 미달)
# 종목마다 KIS 로 떨어지고, KIS 일봉은 1콜 ~100봉 + 초당 20콜 전역 레이트리밋이라
# 200종목이면 **최소 12분**이다. 그런데 응답 어디에도 "몇 종목이 KIS 로 갔는가" 가
# 없어서, 사용자는 느린 이유를 알 수 없었다.
#
# ★수치는 지어내지 않는다★ 로더가 `df.attrs["source"]` 로 실제 출처를 붙인다 —
# 그 계측 지점이 **있으므로** 셀 수 있다. 없으면 `"unknown"` 이지 0 이 아니다.

def test_the_engine_counts_where_each_symbol_came_from():
    """★출처별 종목 수를 센다★ 없으면 왜 느린지 말할 수 없다."""
    import pandas as pd

    from src.kis_backtest_engine import _count_source
    counts: dict = {}
    db = pd.DataFrame({"close": [1.0]}); db.attrs["source"] = "db"
    kis = pd.DataFrame({"close": [1.0]}); kis.attrs["source"] = "kis"
    bare = pd.DataFrame({"close": [1.0]})          # 태그가 없다
    _count_source(counts, db)
    _count_source(counts, kis)
    _count_source(counts, kis)
    _count_source(counts, bare)
    assert counts == {"db": 1, "kis": 2, "unknown": 1}, counts


def test_an_untagged_frame_is_unknown_not_zero():
    """★미상 ≠ 0★ 태그가 없으면 'db 0건' 이 아니라 '모른다' 다."""
    import pandas as pd

    from src.kis_backtest_engine import _count_source
    counts: dict = {}
    _count_source(counts, pd.DataFrame({"close": [1.0]}))
    assert counts == {"unknown": 1}
    assert "db" not in counts and "kis" not in counts


def test_the_worker_records_the_source_mix_in_telemetry():
    """★배선 ①★ 세기만 하고 텔레메트리에 안 실으면 사용자는 여전히 못 본다."""
    import inspect
    src = inspect.getsource(brr._worker)
    assert "symbols_by_source" in src, (
        "출처 구성을 텔레메트리에 싣지 않는다 — 느린 이유를 여전히 알 수 없다")


def test_the_engine_actually_emits_the_source_mix():
    """★배선 ② — 규칙과 배선은 다른 일이다(여덟 번째)★

    `_count_source` 를 아무리 정확히 시험해도, 엔진이 그 결과를 **보고하지 않으면**
    워커에 아무것도 도달하지 않는다. 변이 C4(엔진이 emit 을 생략)가 소스 검사만
    하는 테스트를 그대로 통과했다 — 워커 쪽 텍스트는 그대로였기 때문이다.

    그래서 엔진을 **실제로 돌려** 이벤트를 받는다.
    """
    from src.kis_backtest_engine import run_backtest
    events: list[dict] = []
    run_backtest(
        symbols=["005930", "000660"], strategy_name="GoldenCross",
        start_date="2024-01-02", end_date="2024-03-29",
        progress_cb=events.append)
    loading = [e for e in events if e.get("phase") == "loading" and "sources" in e]
    assert loading, (
        "엔진이 로딩 출처 구성을 한 번도 보고하지 않았다 — "
        f"받은 phase: {sorted({e.get('phase') for e in events})}")
    sources = loading[-1]["sources"]
    assert isinstance(sources, dict) and sources, sources
    assert all(isinstance(v, int) and v > 0 for v in sources.values()), sources
