"""실행 계측을 ★읽을 수 있게★ 한다 — 쓰기 전용이던 텔레메트리 (①)

## 무엇이 문제였나

`_worker` 는 실행마다 계측을 남긴다(`duration_s`·`cpu_util_pct`·`peak_rss_mb`·
`db_queries`·`queue_wait_s`·`symbols_by_source`…). 저장소에는 `get_telemetry()` 도
있다. 그런데 ★그것을 사용자에게 돌려주는 경로가 하나도 없었다★ — 어떤 라우트도
UI 도 `telemetry` 를 반환하지 않는다.

그래서 "백테스트가 5분 걸렸다" 를 받아들고도 **5분 중 몇 분이 데이터 로딩이고
몇 분이 시뮬레이션인지** 아무도 답할 수 없었다. 계측이 있는데 못 읽으니
성능 논의가 전부 추측이 된다.

두 가지를 함께 고친다:
  ① `GET /runs/{id}/telemetry` — `run_status` 와 **같은** 404/503 규약.
  ② `_worker` 가 **단계별 시간**(`load_s`·`sim_s`)을 남긴다. 지금은 `duration_s`
     총합뿐이라 어느 단계가 병목인지 분해할 수 없다.

★미상은 0 이 아니다★ 계측이 없으면 `{}` 도 0 도 아니고 `available: false` + 사유다.
"""
from __future__ import annotations

import os
import threading
import time
from types import SimpleNamespace

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402

import src.data.backtest_runs as br  # noqa: E402
from src.api.backtest_run_routes import router  # noqa: E402

URL = "/api/v1/backtest/runs/{}/telemetry"


@pytest.fixture
def client(monkeypatch, tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path}/runs.db",
                        connect_args={"check_same_thread": False, "timeout": 30})
    monkeypatch.setattr(br, "_engine", lambda: eng)
    monkeypatch.setattr(br, "_inited", False)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _mk(strategy_name: str = "계측 시험") -> str:
    rid = br.create_run(strategy_name, {"universe": "kospi200"})
    assert rid, "테스트 준비 실패 — run 을 만들지 못했다"
    return rid


# ── 계약 ────────────────────────────────────────────────────────────────────

def test_the_route_returns_what_the_worker_recorded(client):
    rid = _mk()
    br.set_telemetry(rid, {"duration_s": 12.5, "load_s": 9.0, "sim_days": 728})
    b = client.get(URL.format(rid)).json()
    assert b["available"] is True, b
    assert b["telemetry"]["duration_s"] == 12.5
    assert b["telemetry"]["load_s"] == 9.0
    assert b["run_id"] == rid


def test_a_run_without_telemetry_says_so_instead_of_inventing_zeros(client):
    """★미상 ≠ 0★ 아직 안 끝난 실행은 계측이 없다 — `{}` 로 뭉개지 않는다."""
    rid = _mk()
    r = client.get(URL.format(rid))
    assert r.status_code == 200
    b = r.json()
    assert b["available"] is False
    assert b["telemetry"] is None, "빈 dict 은 '측정해봤더니 없음'으로 읽힌다"
    assert b["reason"], "왜 없는지 말하지 않는다"


def test_a_missing_run_is_404_not_an_empty_reading(client):
    r = client.get(URL.format("bt_없는실행"))
    assert r.status_code == 404, r.text


def test_a_store_failure_is_503_not_404(client, monkeypatch):
    """★없음과 못 읽음은 다르다★ `run_status` 와 같은 규약을 쓴다.

    404 로 내보내면 프런트가 '만료된 링크'로 오인한다 — 그 구분을 위해
    `BacktestStoreError` 가 존재한다.
    """
    def _boom(run_id, strict=False):
        if strict:
            raise br.BacktestStoreError("커넥션 풀 고갈")
        return None
    monkeypatch.setattr(br, "get_status", _boom)
    r = client.get(URL.format("bt_아무거나"))
    assert r.status_code == 503, r.text


def test_reading_telemetry_distinguishes_absent_from_unreadable(client, monkeypatch):
    """★짝★ 앞 테스트의 반대편 — 계측 조회 자체가 실패해도 '없음'이 되면 안 된다.

    `get_telemetry` 는 예외를 전부 삼켜 `None` 을 돌려줬다. 그러면 "아직 기록 전"과
    "DB 를 못 읽었다"가 같은 답이 된다 — ★침묵 폴백★ 이다.
    """
    rid = _mk()
    br.set_telemetry(rid, {"duration_s": 1.0})

    def _boom(run_id, strict=False):
        if strict:
            raise br.BacktestStoreError("telemetry 컬럼 읽기 실패")
        return None
    monkeypatch.setattr(br, "get_telemetry", _boom)
    r = client.get(URL.format(rid))
    assert r.status_code == 503, r.text


def test_the_store_reader_can_be_strict(tmp_path, monkeypatch):
    """저장소 계층의 계약 — `get_status` 가 이미 쓰는 `strict` 어휘를 그대로 쓴다."""
    eng = create_engine(f"sqlite:///{tmp_path}/s.db",
                        connect_args={"check_same_thread": False, "timeout": 30})
    monkeypatch.setattr(br, "_engine", lambda: eng)
    monkeypatch.setattr(br, "_inited", False)
    rid = _mk()
    assert br.get_telemetry(rid) is None          # 기록 전 — 관대 모드와 동일
    assert br.get_telemetry(rid, strict=True) is None

    monkeypatch.setattr(br, "_engine", lambda: (_ for _ in ()).throw(RuntimeError("DB 다운")))
    assert br.get_telemetry(rid) is None, "관대 모드는 기존 호출부를 위해 None 유지"
    with pytest.raises(br.BacktestStoreError):
        br.get_telemetry(rid, strict=True)


# ── 단계별 시간 — ★총합만으로는 병목을 못 가른다★ ──────────────────────────────

class _ScriptClock:
    """대본의 낮잠만 시간을 미는 시계 — 워커 모듈의 `time.perf_counter` 자리에만 꽂는다.

    ★실제 시계로 재면 디스크가 단계의 순서를 정한다★ 계측은 단계 안의 진행 기록(SQLite 커밋)
    시간도 그 단계에 넣는다 — 그것도 단계의 비용이라 계측의 뜻은 맞다. 그런데 CI 에서 시뮬레이션
    단계의 커밋 둘이 한 번 0.37초를 쓰자 로딩 0.30초 · 시뮬레이션 0.05초로 짠 대본이 뒤집혔다
    (2026-11-20 · `aeaea03` 의 PR 실행 · 같은 트리의 푸시 실행은 통과 · 그 단계의 쓰기만 0.4초 늦추면
    이 기계에서도 같은 꼴로 실패). 이 시험이 거는 것은 ★경계를 어디에 긋는가★(로딩 시작 →
    시뮬레이션 시작 → 코어 끝 · 총합과 같은 시계)이지 디스크의 빠르기가 아니라서 시계만 바꾼다.
    계측 코드(`_worker` · `_record_phase_seconds`)는 그대로 돈다.
    """

    def __init__(self) -> None:
        self._now = 1000.0
        self._lock = threading.Lock()

    def perf_counter(self) -> float:
        with self._lock:
            return self._now

    def nap(self, seconds: float) -> None:
        with self._lock:
            self._now += seconds


def _phase_client(monkeypatch, tmp_path, script):
    """`_screen_to_backtest_core` 를 진행 이벤트 대본으로 대체한 워커를 돌린다.

    ★운송 수단과 시계만 바꾼다★ (기존 `test_backtest_run_routes.py` 와 같은 기법) —
    도는 로직은 프로덕션과 같은 `_worker` 다. 대본의 낮잠은 `_ScriptClock` 만 민다(위 까닭).
    """
    import src.api.screener_routes as sr
    from src.api import backtest_run_routes as brr

    eng = create_engine(f"sqlite:///{tmp_path}/p.db",
                        connect_args={"check_same_thread": False, "timeout": 30})
    monkeypatch.setattr(br, "_engine", lambda: eng)
    monkeypatch.setattr(br, "_inited", False)
    clock = _ScriptClock()
    # 이 모듈의 시계만 — 전역 time 은 그대로(벽시계 · CPU 시간은 진짜). 모듈이 쓰는 셋 그대로:
    # 넷째 이름을 쓰기 시작하면 여기서 AttributeError 로 드러난다(조용히 진짜 시계로 돌지 않게).
    monkeypatch.setattr(brr, "time", SimpleNamespace(
        perf_counter=clock.perf_counter, process_time=time.process_time, time=time.time))

    class _StubReq:
        def __init__(self, **kw):
            pass

    monkeypatch.setattr(sr, "ScreenToBacktestRequest", _StubReq, raising=False)

    def _core(req, progress_cb=None):
        for phase, done, total, nap in script:
            if progress_cb:
                progress_cb({"phase": phase, "done": done, "total": total})
            clock.nap(nap)
        return {"stats": {}, "trades": [], "data_source": {"fully_real": False}}

    monkeypatch.setattr(sr, "_screen_to_backtest_core", _core, raising=False)
    monkeypatch.setattr(
        brr, "_submit",
        lambda fn, *a: threading.Thread(target=fn, args=a, daemon=True).start())

    app = FastAPI()
    app.include_router(brr.router)
    c = TestClient(app)
    r = c.post("/api/v1/backtest/runs",
               json={"config": {"universe": "kospi200"}, "strategy_name": "단계 계측"})
    assert r.status_code == 200, r.text
    rid = r.json()["run_id"]
    for _ in range(200):
        if (c.get(f"/api/v1/backtest/runs/{rid}/status").json()["status"]) in br.TERMINAL:
            break
        time.sleep(0.05)
    return c, rid


@pytest.mark.parametrize("script, want", [
    pytest.param([("loading", 1, 10, 0.30), ("loading", 10, 10, 0.0),
                  ("simulating", 1, 5, 0.05), ("simulating", 5, 5, 0.0)],
                 (0.30, 0.05), id="load-heavy"),
    # ★짝★ 순서를 뒤집은 대본 — 대본 순서와 같은 상수(0.3 · 0.05)를 박거나 둘을 바꿔 달면 여기서 깨진다
    pytest.param([("loading", 1, 10, 0.05), ("loading", 10, 10, 0.0),
                  ("simulating", 1, 5, 0.40), ("simulating", 5, 5, 0.0)],
                 (0.05, 0.40), id="sim-heavy"),
])
def test_telemetry_splits_loading_from_simulating(monkeypatch, tmp_path, script, want):
    """★5분 중 몇 분이 로딩인가★ — `duration_s` 총합만으로는 답할 수 없다.

    로딩과 시뮬레이션의 길이를 대본으로 정해 돌린다. 두 값이 ★대본의 값 그대로★여야 계측이
    진짜 단계를 잰 것이다 — 순서만 보면 대본 순서와 같은 상수를 박아도 통과하므로(2026-11-20
    변이로 확인) 거꾸로 된 대본을 짝으로 둔다. 총합도 같은 시계여야 한다(단계 합 = 총합 —
    예전의 '총합 + 0.5초 이하'는 CPU 시간을 총합으로 잡는 변이를 통과시켰다).
    """
    c, rid = _phase_client(monkeypatch, tmp_path, script)
    t = c.get(URL.format(rid)).json()["telemetry"]
    assert t is not None, "완료된 실행인데 계측이 없다"
    assert t.get("load_s") is not None and t.get("sim_s") is not None, t
    assert (t["load_s"], t["sim_s"]) == pytest.approx(want, abs=1e-3), (
        f"단계 경계를 잘못 그었다 — 대본은 로딩 {want[0]}초 · 시뮬레이션 {want[1]}초: {t}")
    assert t["duration_s"] == pytest.approx(t["load_s"] + t["sim_s"], abs=2e-3), (
        f"단계 합과 총합이 다르다 — 같은 시계를 안 쓴다: {t}")


def test_a_phase_that_never_ran_has_no_key_rather_than_zero(monkeypatch, tmp_path):
    """★미측정 ≠ 0★ 시뮬레이션까지 못 간 실행에 `sim_s: 0` 을 넣으면
    "시뮬레이션이 0초였다"로 읽힌다. 키를 만들지 않는 것이 정직하다."""
    script = [("loading", 1, 10, 0.05), ("loading", 10, 10, 0.0)]
    c, rid = _phase_client(monkeypatch, tmp_path, script)
    t = c.get(URL.format(rid)).json()["telemetry"]
    assert t is not None
    assert "load_s" in t, t
    assert "sim_s" not in t, f"돌지 않은 단계에 값을 지어냈다: {t}"
