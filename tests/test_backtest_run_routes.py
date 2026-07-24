"""BacktestRun API + background worker — integration/contract (Backtest Run Workflow 5b)

핵심 주장(스펙):
  · POST /runs → run_id 즉시 반환(결과 대기 없음) + 백그라운드 워커 기동.
  · 폴링 → completed 도달, GET /runs/{id} 에 result 포함.
  · 엔진 실패 → failed + 안전 에러메시지(민감정보 없음).
  · 취소 → cancelled. 재시도 → 새 run(이력 불변). 없는 run → 404.
  · 새로고침 복구 = 상태가 DB에서 조회됨(워커 스레드가 쓴 값).

엔진(_screen_to_backtest_core)은 자체 테스트가 있으므로, 여기선 워커 오케스트레이션과
API 계약만 검증하기 위해 canned 결과로 대체(빠르고 결정론적).
"""
import os
import time

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import src.api.screener_routes as sr  # noqa: E402
import src.data.backtest_runs as br  # noqa: E402
from src.api.backtest_run_routes import router  # noqa: E402

CANNED = {"stats": {"total_return_pct": 12.3, "sharpe": 1.1}, "trades": [],
          "data_source": {"fully_real": False}}


@pytest.fixture
def client(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    monkeypatch.setattr(br, "_engine", lambda: eng)
    monkeypatch.setattr(br, "_inited", False)

    class _StubReq:
        def __init__(self, **kw):
            self.kw = kw

    monkeypatch.setattr(sr, "ScreenToBacktestRequest", _StubReq, raising=False)
    monkeypatch.setattr(sr, "_screen_to_backtest_core", lambda req, progress_cb=None: dict(CANNED), raising=False)

    app = FastAPI()
    app.include_router(router)
    yield TestClient(app)
    eng.dispose()


def _wait_terminal(client, rid, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        st = client.get(f"/api/v1/backtest/runs/{rid}/status").json()
        if st["status"] in br.TERMINAL:
            return st
        time.sleep(0.03)
    return client.get(f"/api/v1/backtest/runs/{rid}/status").json()


def test_create_returns_run_id_immediately_then_completes(client):
    r = client.post("/api/v1/backtest/runs", json={"config": {"universe": "kospi200"}, "strategy_name": "골든크로스"})
    assert r.status_code == 200
    body = r.json()
    assert body["run_id"].startswith("bt_") and body["status"] == "queued"
    rid = body["run_id"]

    st = _wait_terminal(client, rid)
    assert st["status"] == "completed" and st["progress_percent"] == 100

    full = client.get(f"/api/v1/backtest/runs/{rid}").json()
    assert full["result"]["stats"]["total_return_pct"] == 12.3
    assert full["is_mock_data"] is True   # data_source.fully_real False → mock
    assert full["completed_at"] is not None


def test_engine_failure_sets_failed_with_safe_message(client, monkeypatch):
    def _boom(req, progress_cb=None):
        raise RuntimeError("DB password leak sensitive detail")
    monkeypatch.setattr(sr, "_screen_to_backtest_core", _boom, raising=False)

    rid = client.post("/api/v1/backtest/runs", json={"config": {"universe": "x"}}).json()["run_id"]
    st = _wait_terminal(client, rid)
    assert st["status"] == "failed"
    full = client.get(f"/api/v1/backtest/runs/{rid}").json()
    assert full["error_code"] == "engine_error"
    assert "sensitive" not in (full["error_message"] or "")   # no secret leak


def test_status_is_light_and_refresh_recovers(client):
    rid = client.post("/api/v1/backtest/runs", json={"config": {"universe": "k"}}).json()["run_id"]
    _wait_terminal(client, rid)
    # 폴링 응답은 경량(result/snapshot 없음) — 새로고침처럼 매번 DB에서 복구
    st = client.get(f"/api/v1/backtest/runs/{rid}/status").json()
    assert "result" not in st and "input_snapshot" not in st
    assert st["run_id"] == rid and st["status"] == "completed"


def test_unknown_run_404(client):
    assert client.get("/api/v1/backtest/runs/bt_nope/status").status_code == 404
    assert client.get("/api/v1/backtest/runs/bt_nope").status_code == 404
    assert client.post("/api/v1/backtest/runs/bt_nope/cancel").status_code == 409


def test_db_error_is_503_not_404(client, monkeypatch):
    """DB 일시 오류는 503(재시도 가능)로 구분 — 404(진짜 없음)로 뭉개지 않음.

    이래야 프론트 로딩 페이지가 일시적 프록시/DB blip을 '만료된 링크'로 오인해 폴링을
    포기하지 않는다. (진짜 없는 실행은 계속 404)
    """
    # 저장소 조회가 DB 오류를 던지도록 강제
    def _boom_fetch(run_id, full, strict=False):
        if strict:
            raise br.BacktestStoreError("connection reset")
        return None
    monkeypatch.setattr(br, "_fetch", _boom_fetch)
    assert client.get("/api/v1/backtest/runs/bt_any/status").status_code == 503
    assert client.get("/api/v1/backtest/runs/bt_any").status_code == 503


def test_retry_creates_new_run(client):
    rid = client.post("/api/v1/backtest/runs", json={"config": {"universe": "k"}, "strategy_name": "S"}).json()["run_id"]
    _wait_terminal(client, rid)
    rr = client.post(f"/api/v1/backtest/runs/{rid}/retry").json()
    assert rr["run_id"] != rid and rr["retried_from"] == rid
    st = _wait_terminal(client, rr["run_id"])
    assert st["status"] == "completed"
    # 원 실행은 그대로(이력 불변)
    assert client.get(f"/api/v1/backtest/runs/{rid}/status").json()["status"] == "completed"


def test_list_runs(client):
    # serialize (finish each run before the next) — the in-memory StaticPool shares a single
    # connection across worker threads, so concurrent posts would contend; production uses a
    # pooled engine. The API contract under test is "list returns created runs, newest first".
    ids = []
    for _ in range(2):
        rid = client.post("/api/v1/backtest/runs", json={"config": {"universe": "k"}}).json()["run_id"]
        _wait_terminal(client, rid)
        ids.append(rid)
    runs = client.get("/api/v1/backtest/runs").json()["runs"]
    listed = [r["run_id"] for r in runs]
    assert set(ids).issubset(set(listed)) and listed[0] == ids[-1]   # 최신순
