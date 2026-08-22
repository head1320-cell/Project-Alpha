"""BacktestRun 복구·정직성 — 고아 정리, 취소 사유별 상태코드, 폴링 투영 비용.

이 세 가지가 실제 인시던트에서 겹쳐 "끝난 실행이 영원히 로딩 중"으로 보였다:
  · 워커는 daemon 스레드 → 재시작 시 행이 비종료로 영구 잔류(정리 주체 없음).
  · cancel 실패 사유 3종(없음·DB오류·이미종료)이 전부 409 → 프론트가 오해.
  · status 폴링이 result blob까지 매번 SELECT → 1초 주기로 커넥션 점유.
"""
import os
import time

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import src.data.backtest_runs as br  # noqa: E402
from src.api.backtest_run_routes import router  # noqa: E402


@pytest.fixture
def eng(monkeypatch):
    e = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    monkeypatch.setattr(br, "_engine", lambda: e)
    monkeypatch.setattr(br, "_inited", False)
    yield e
    e.dispose()


@pytest.fixture
def client(eng):
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _mk(status: str = "loading_data") -> str:
    rid = br.create_run("Condition", {"universe": "kospi200"})
    assert rid
    if status != "queued":
        br.advance(rid, status)
    return rid


# ── 고아 정리 ────────────────────────────────────────────────────────────────
def test_sweep_marks_silent_nonterminal_run_as_failed(eng):
    """워커가 사라진(하트비트 끊긴) 비종료 실행은 정직한 사유와 함께 failed로 확정된다."""
    rid = _mk("loading_data")
    assert br.get_status(rid)["status"] == "loading_data"

    # 하트비트를 과거로 —컨테이너 재시작으로 워커가 사라진 상황을 재현
    with eng.begin() as c:
        c.execute(text("UPDATE backtest_runs SET heartbeat_at = :h WHERE run_id = :i"),
                  {"h": time.time() - 5000, "i": rid})

    assert br.sweep_orphaned(max_silence_sec=900) == 1
    st = br.get_status(rid)
    assert st["status"] == "failed"
    assert st["error_code"] == "worker_lost"
    assert "재시작" in st["error_message"]      # 왜 죽었는지 사용자에게 밝힌다


def test_sweep_spares_live_and_terminal_runs(eng):
    """방금 하트비트를 찍은 실행과 이미 끝난 실행은 건드리지 않는다."""
    live = _mk("simulating")                       # advance가 하트비트를 방금 기록
    done = _mk("simulating")
    br.set_result(done, {"stats": {}})
    assert br.get_status(done)["status"] == "completed"

    assert br.sweep_orphaned(max_silence_sec=900) == 0
    assert br.get_status(live)["status"] == "simulating"
    assert br.get_status(done)["status"] == "completed"


def test_sweep_uses_created_at_when_heartbeat_missing(eng):
    """하트비트 컬럼이 비어 있는 구버전 행도 created_at으로 판정한다(멈춘 채 방치 금지)."""
    rid = _mk("loading_data")
    with eng.begin() as c:
        c.execute(text("UPDATE backtest_runs SET heartbeat_at = NULL, created_at = :t "
                       "WHERE run_id = :i"), {"t": time.time() - 5000, "i": rid})
    assert br.sweep_orphaned(max_silence_sec=900) == 1
    assert br.get_status(rid)["status"] == "failed"


def test_works_without_heartbeat_column(eng, monkeypatch):
    """마이그레이션(ALTER)이 막힌 배포에서도 진행률 기록이 깨지지 않아야 한다.

    heartbeat_at를 참조하는 UPDATE가 무조건 나가면, 컬럼이 없는 DB에선 진행률 쓰기가
    통째로 실패해 수정 전보다 나빠진다 — 하트비트 절만 빠지고 나머지는 동일해야 한다.
    """
    rid = _mk("simulating")
    with eng.begin() as c:                       # 컬럼 없는 구버전 스키마를 재현
        c.execute(text("ALTER TABLE backtest_runs DROP COLUMN heartbeat_at"))
    monkeypatch.setattr(br, "_has_heartbeat", False)

    assert br.touch_progress(rid, 33.0, "시뮬레이션 100/300일") == "updated"
    assert br.get_status(rid)["progress_percent"] == 33.0
    assert br.update_progress(rid, 44.0) is True
    assert br.advance(rid, "calculating_metrics")["ok"] is True
    br.heartbeat(rid)                            # no-op이어야 하고 예외를 던지면 안 된다

    # 고아 정리도 created_at 폴백으로 계속 동작
    with eng.begin() as c:
        c.execute(text("UPDATE backtest_runs SET created_at = :t WHERE run_id = :i"),
                  {"t": time.time() - 5000, "i": rid})
    assert br.sweep_orphaned(max_silence_sec=900) == 1
    assert br.get_status(rid)["status"] == "failed"


# ── 취소 사유별 상태코드 ─────────────────────────────────────────────────────
def test_cancel_missing_run_is_404_not_409(client):
    r = client.post("/api/v1/backtest/runs/bt_nope_00000000/cancel")
    assert r.status_code == 404


def test_cancel_terminal_run_is_409(client, eng):
    rid = _mk("simulating")
    br.set_result(rid, {"stats": {}})
    r = client.post(f"/api/v1/backtest/runs/{rid}/cancel")
    assert r.status_code == 409
    assert "종료" in r.json()["detail"]


def test_cancel_store_error_is_503_not_409(client, monkeypatch):
    """DB 장애를 '이미 끝났음'으로 위장하지 않는다 — 프론트가 재시도를 포기하지 않도록."""
    def boom(*a, **k):                      # 커넥션 자체가 죽은 상황을 재현
        raise RuntimeError("db down")
    monkeypatch.setattr(br, "_engine", boom)
    r = client.post("/api/v1/backtest/runs/bt_x_1/cancel")
    assert r.status_code == 503


def test_cancel_live_run_succeeds(client, eng):
    rid = _mk("simulating")
    assert client.post(f"/api/v1/backtest/runs/{rid}/cancel").status_code == 200
    assert br.get_status(rid)["status"] == "cancelled"


# ── 폴링 투영: result blob 제외 ──────────────────────────────────────────────
def test_status_projection_excludes_result_but_get_run_keeps_it(eng):
    rid = _mk("simulating")
    br.set_result(rid, {"stats": {"total_return_pct": 7.5}})

    st = br.get_status(rid)
    assert "result" not in st                       # 1초 폴링이 결과 blob을 실어 나르지 않음
    assert st["status"] == "completed"

    full = br.get_run(rid)
    assert full["result"]["stats"]["total_return_pct"] == 7.5   # 결과 페이지는 그대로 받음


def test_status_endpoint_does_not_ship_result(client, eng):
    rid = _mk("simulating")
    br.set_result(rid, {"stats": {"total_return_pct": 7.5}})
    body = client.get(f"/api/v1/backtest/runs/{rid}/status").json()
    assert "result" not in body
    assert client.get(f"/api/v1/backtest/runs/{rid}").json()["result"] is not None


# ── 진행 핫패스: 단일 UPDATE + 취소 감지 ─────────────────────────────────────
def test_touch_progress_single_update_and_blocks_on_cancel(eng):
    rid = _mk("simulating")
    assert br.touch_progress(rid, 42.0, "시뮬레이션 300/728일") == "updated"
    st = br.get_status(rid)
    assert st["progress_percent"] == 42.0 and "300/728" in st["status_message"]

    br.cancel(rid)
    # 종료 상태에선 WHERE에 걸려 rowcount 0 — 호출자가 그때만 상태를 확인하면 된다
    assert br.touch_progress(rid, 55.0) == "blocked"
    assert br.get_status(rid)["progress_percent"] == 42.0       # 취소 후 덮어쓰지 않음


def test_advance_reports_cancellation_without_extra_read(eng):
    rid = _mk("simulating")
    br.cancel(rid)
    r = br.advance(rid, "calculating_metrics")
    assert r["ok"] is False and r.get("cancelled") is True
