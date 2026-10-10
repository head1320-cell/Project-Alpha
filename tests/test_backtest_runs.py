"""BacktestRun 도메인 — 상태 전이 + 영속 + 복구 검증 (Backtest Run Workflow 5a)

핵심 주장(스펙):
  · 생성 → queued, 폴링용 경량 상태 반환.
  · 정상 lifecycle 전이 성공, 불법 전이(단계 건너뛰기)는 거부.
  · 종료 상태(failed/cancelled/completed→expired 외)는 불변.
  · set_error/cancel/set_result 정확 동작.
  · 새로고침 복구: 진행률이 DB에 영속돼 새 조회로 복구됨.
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import src.data.backtest_runs as br  # noqa: E402


@pytest.fixture
def store(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    monkeypatch.setattr(br, "_engine", lambda: eng)
    monkeypatch.setattr(br, "_inited", False)
    yield br
    eng.dispose()


def _create(s):
    return s.create_run("골든크로스", {"universe": "kospi200", "strategy_name": "GoldenCross"},
                        parameter_snapshot={"fee_bp": 15}, is_mock_data=True)


def test_create_is_queued_and_status_is_light(store):
    rid = _create(store)
    assert rid and rid.startswith("bt_")
    st = store.get_status(rid)
    assert st["status"] == "queued" and st["progress_percent"] == 2
    assert "result" not in st and "input_snapshot" not in st   # 경량
    full = store.get_run(rid)
    assert full["input_snapshot"]["universe"] == "kospi200" and full["is_mock_data"] is True


def test_legal_lifecycle_path(store):
    rid = _create(store)
    for to in ["validating", "loading_data", "simulating", "calculating_metrics", "persisting_results"]:
        r = store.transition(rid, to)
        assert r["ok"] is True, r
    assert store.get_status(rid)["current_stage"] == "persisting_results"
    # started_at stamped at validating
    assert store.get_run(rid)["started_at"] is not None
    ok = store.set_result(rid, {"stats": {"total_return_pct": 12.3}}, is_mock_data=True)
    assert ok["ok"] is True
    done = store.get_run(rid)
    assert done["status"] == "completed" and done["progress_percent"] == 100
    assert done["result"]["stats"]["total_return_pct"] == 12.3
    assert done["completed_at"] is not None


def test_illegal_transition_rejected(store):
    rid = _create(store)
    # queued → completed (건너뛰기) 불가
    r = store.transition(rid, "completed")
    assert r["ok"] is False and "전이 불가" in r["reason"]
    assert store.get_status(rid)["status"] == "queued"   # 상태 불변


def test_terminal_states_immutable(store):
    rid = _create(store)
    store.transition(rid, "validating")
    assert store.set_error(rid, "engine_error", "시뮬레이션 실패")["ok"] is True
    assert store.get_status(rid)["status"] == "failed"
    # failed 이후 어떤 전이도 불가
    assert store.transition(rid, "loading_data")["ok"] is False
    assert store.set_error(rid, "x", "y")["ok"] is False
    assert store.cancel(rid)["ok"] is False


def test_cancel_only_from_nonterminal(store):
    rid = _create(store)
    store.transition(rid, "validating")
    assert store.cancel(rid)["ok"] is True
    assert store.get_status(rid)["status"] == "cancelled"
    # completed 는 취소 불가
    rid2 = _create(store)
    for to in ["validating", "loading_data", "simulating", "calculating_metrics", "persisting_results"]:
        store.transition(rid2, to)
    store.set_result(rid2, {"stats": {}})
    assert store.cancel(rid2)["ok"] is False


def test_refresh_recovery_reads_persisted_progress(store):
    """새로고침 = 새 조회. 진행률이 DB에 영속돼 in-memory 없이 복구된다."""
    rid = _create(store)
    store.transition(rid, "validating")
    store.transition(rid, "loading_data")
    store.transition(rid, "simulating")
    store.update_progress(rid, 47.5, message="시뮬레이션 320/750일", stage="simulating")
    # 완전히 새로운 조회 (다른 커넥션 경유) — in-memory 상태 없음
    recovered = store.get_status(rid)
    assert recovered["status"] == "simulating"
    assert recovered["progress_percent"] == 47.5
    assert "320/750" in recovered["status_message"]


def test_completed_can_expire_only(store):
    rid = _create(store)
    for to in ["validating", "loading_data", "simulating", "calculating_metrics", "persisting_results"]:
        store.transition(rid, to)
    store.set_result(rid, {"stats": {}})
    assert store.transition(rid, "expired")["ok"] is True
    assert store.transition(rid, "queued")["ok"] is False


def test_list_runs_newest_first(store):
    ids = [_create(store) for _ in range(3)]
    rows = store.list_runs()
    assert [r["run_id"] for r in rows][:3] == ids[::-1]   # 최신순
