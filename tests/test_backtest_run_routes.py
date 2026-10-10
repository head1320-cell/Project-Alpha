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
import threading
import time

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402

import src.api.screener_routes as sr  # noqa: E402
import src.data.backtest_runs as br  # noqa: E402
from src.api.backtest_run_routes import router  # noqa: E402

CANNED = {"stats": {"total_return_pct": 12.3, "sharpe": 1.1}, "trades": [],
          "data_source": {"fully_real": False}}


@pytest.fixture
def client(monkeypatch, tmp_path):
    # ★파일 DB + 스레드별 커넥션★ — in-memory StaticPool은 하나의 DBAPI 커넥션을 모든
    # 스레드에 동시에 넘긴다. 워커의 engine.begin() 트랜잭션과 폴링 스레드의 읽기가 같은
    # 커넥션에서 겹치면 워커 쓰기가 조용히 실패해 실행이 비종료로 남는다(간헐 실패).
    # 운영은 커넥션 풀(Postgres)이라 스레드마다 별도 커넥션 — 그 구조를 그대로 모사한다.
    eng = create_engine(f"sqlite:///{tmp_path}/runs.db",
                        connect_args={"check_same_thread": False, "timeout": 30})
    monkeypatch.setattr(br, "_engine", lambda: eng)
    monkeypatch.setattr(br, "_inited", False)

    class _StubReq:
        def __init__(self, **kw):
            self.kw = kw

    monkeypatch.setattr(sr, "ScreenToBacktestRequest", _StubReq, raising=False)
    monkeypatch.setattr(sr, "_screen_to_backtest_core", lambda req, progress_cb=None: dict(CANNED), raising=False)

    # ★운송 수단만 바꾼다 (P0-2)★ 프로덕션 워커는 spawn 프로세스에서 돌기 때문에 위
    # monkeypatch 들이 자식에 닿지 않는다(자식은 진짜 DB 에 진짜 엔진을 돌린다).
    # 이 파일이 검증하는 것은 **워커 오케스트레이션과 API 계약**이므로(모듈 도크스트링),
    # 디스패치만 스레드로 바꿔 기존 의미를 그대로 유지한다 — 도는 로직은 같은 `_worker` 다.
    # 프로세스 경로 자체는 `tests/test_backtest_worker_process.py` 가 따로 단언한다.
    from src.api import backtest_run_routes as brr
    monkeypatch.setattr(
        brr, "_submit",
        lambda fn, *a: threading.Thread(target=fn, args=a, daemon=True).start())

    app = FastAPI()
    app.include_router(router)
    yield TestClient(app)
    # ★워커 스레드를 반드시 배수한 뒤 정리★ — 실행 워커는 daemon 스레드이고
    # backtest_runs._engine은 모듈 전역이라 호출 시점에 읽힌다. 살아남은 이전 테스트의
    # 워커가 다음 테스트의 엔진에 쓰기를 하면 상태가 뒤섞여 간헐 실패가 난다.
    _drain_workers()
    eng.dispose()


def _drain_workers(timeout: float = 15.0) -> None:
    """이 테스트가 띄운 백테스트 워커 스레드가 끝날 때까지 기다린다."""
    from src.api import backtest_run_routes as brr
    end = time.time() + timeout
    for t in list(threading.enumerate()):
        if t is threading.current_thread() or not t.is_alive():
            continue
        if getattr(t, "_target", None) is brr._worker:
            t.join(max(0.05, end - time.time()))


def _wait_terminal(client, rid, timeout=20.0):
    """워커가 종료 상태에 도달할 때까지 폴링(간격은 파일 SQLite 쓰기 경합을 줄이려 느슨하게)."""
    end = time.time() + timeout
    while time.time() < end:
        st = client.get(f"/api/v1/backtest/runs/{rid}/status").json()
        if st["status"] in br.TERMINAL:
            return st
        time.sleep(0.1)
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
    # cancel도 '없음'은 404 — 예전엔 없음·DB오류·이미종료가 전부 409로 뭉개져
    # 프론트가 "이미 끝난 실행"으로 오해했다(test_backtest_run_recovery가 3종을 고정).
    assert client.post("/api/v1/backtest/runs/bt_nope/cancel").status_code == 404


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
    # serialize (finish each run before the next) — SQLite serializes writers, so concurrent
    # posts would contend; production uses Postgres. The API contract under test is
    # "list returns created runs, newest first".
    ids = []
    for _ in range(2):
        rid = client.post("/api/v1/backtest/runs", json={"config": {"universe": "k"}}).json()["run_id"]
        _wait_terminal(client, rid)
        ids.append(rid)
    runs = client.get("/api/v1/backtest/runs").json()["runs"]
    listed = [r["run_id"] for r in runs]
    assert set(ids).issubset(set(listed)) and listed[0] == ids[-1]   # 최신순
