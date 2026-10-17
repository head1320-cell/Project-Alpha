"""AP1 — 킬스위치 조치 어휘. ★발동했는가 ⟂ 무엇을 했는가★

`live_kill_events` 한 행이 두 사실을 섞고 있었다 — *"발동했다"* 와 *"발동해서
정리했다"*. 그래서 `kis_client` 없이 발동한 자동 경로가 `n_orders_cancelled=0` 을
남기고, 그 `0` 은 **"취소할 주문이 없었다"** 와 구별되지 않았다.

★짝을 붙인다★ — 상태마다 "그 상태가 **아니어야** 하는" 경우를 함께 건다.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from src.domain.kill_action import (
    ACTION_BLOCK_NEW_ORDERS,
    ACTION_CANCEL_OPEN,
    ACTION_LABELS,
    ACTION_LIQUIDATE,
    ACTION_NOTIFY,
    ACTION_STATES,
    KILL_ACTIONS,
    OBSERVED,
    STATE_DONE,
    STATE_FAILED,
    STATE_SKIPPED,
    STATE_UNKNOWN,
    UNOBSERVED,
    ActionRecord,
    action_rollup,
    observation_state,
    observations,
    unknown_actions,
)

_MODULE = pathlib.Path("src/domain/kill_action.py")


# ── 레지스트리 ─────────────────────────────────────────────────────────────

def test_the_four_actions_are_registered_and_labelled():
    """★테스트의 테스트★ — 레지스트리를 비우면 아래 전수 검사들이 공허해진다."""
    assert KILL_ACTIONS == (ACTION_BLOCK_NEW_ORDERS, ACTION_CANCEL_OPEN,
                            ACTION_LIQUIDATE, ACTION_NOTIFY)
    assert set(ACTION_LABELS) == set(KILL_ACTIONS)
    assert all(ACTION_LABELS[a] for a in KILL_ACTIONS)


def test_the_four_states_are_registered():
    assert set(ACTION_STATES) == {STATE_DONE, STATE_SKIPPED, STATE_FAILED,
                                  STATE_UNKNOWN}


# ── ★사유 없는 미상·건너뜀·실패는 만들 수 없다★ ─────────────────────────

@pytest.mark.parametrize("state", [STATE_SKIPPED, STATE_FAILED, STATE_UNKNOWN])
def test_a_non_done_state_without_a_reason_cannot_be_built(state):
    """AD1 `AccountLimit` 의 선례 — 나중에 사유를 잊는 길 자체를 막는다."""
    with pytest.raises(ValueError):
        ActionRecord(action=ACTION_CANCEL_OPEN, state=state)


def test_done_needs_no_reason():
    """★짝★ — 한 일에는 사유를 강요하지 않는다(강요하면 빈 문자열이 생긴다)."""
    rec = ActionRecord(action=ACTION_CANCEL_OPEN, state=STATE_DONE,
                       detail={"n_cancelled": 0})
    assert rec.reason is None


@pytest.mark.parametrize("bad", [{"action": "정리"}, {"state": "완료"}])
def test_an_unknown_action_or_state_is_rejected(bad):
    kw = {"action": ACTION_CANCEL_OPEN, "state": STATE_DONE, **bad}
    if kw["state"] != STATE_DONE:
        kw["reason"] = "사유"
    with pytest.raises(ValueError):
        ActionRecord(**kw)


# ── ★이 프로그램의 핵심 구분: SKIPPED ≠ DONE(0건)★ ──────────────────────

def test_doing_nothing_and_skipping_are_not_the_same_fact():
    """★"취소할 주문이 없었다" ≠ "취소를 시도하지 않았다"★

    지금 저장소는 둘 다 `n_orders_cancelled=0` 으로 적는다. 그것이 이 모듈이
    존재하는 이유다.
    """
    did = ActionRecord(action=ACTION_CANCEL_OPEN, state=STATE_DONE,
                       detail={"n_cancelled": 0})
    skipped = ActionRecord(action=ACTION_CANCEL_OPEN, state=STATE_SKIPPED,
                           reason="브로커 클라이언트 없이 발동했습니다.")
    rolled = action_rollup([did, skipped])
    assert did.state != skipped.state
    assert ACTION_CANCEL_OPEN in rolled["done"]
    assert ACTION_CANCEL_OPEN in rolled["skipped"]
    assert rolled["done"] is not rolled["skipped"]


def test_the_rollup_sorts_every_action_into_exactly_one_bucket():
    recs = [
        ActionRecord(action=ACTION_BLOCK_NEW_ORDERS, state=STATE_DONE),
        ActionRecord(action=ACTION_CANCEL_OPEN, state=STATE_SKIPPED, reason="사유"),
        ActionRecord(action=ACTION_LIQUIDATE, state=STATE_FAILED, reason="사유"),
        ActionRecord(action=ACTION_NOTIFY, state=STATE_UNKNOWN, reason="사유"),
    ]
    r = action_rollup(recs)
    assert r["done"] == [ACTION_BLOCK_NEW_ORDERS]
    assert r["skipped"] == [ACTION_CANCEL_OPEN]
    assert r["failed"] == [ACTION_LIQUIDATE]
    assert r["unknown"] == [ACTION_NOTIFY]
    assert r["records"] == [rec.to_dict() for rec in recs]


def test_the_rollup_of_nothing_is_not_a_clean_bill():
    """★빈 목록이 "다 했다" 로 읽히면 안 된다★"""
    r = action_rollup([])
    assert r["done"] == []
    assert r["summary"]
    assert r["cleared"] is False


def test_only_a_run_that_did_everything_is_cleared():
    """`cleared` 는 ★넷이 전부 `done`★ 일 때만 참이다."""
    every = [ActionRecord(action=a, state=STATE_DONE) for a in KILL_ACTIONS]
    assert action_rollup(every)["cleared"] is True


@pytest.mark.parametrize("drop", list(KILL_ACTIONS))
def test_one_skipped_action_is_enough_to_lose_cleared(drop):
    """★짝★ — 하나만 건너뛰어도 "정리됐다" 가 아니다."""
    recs = [ActionRecord(action=a, state=STATE_DONE) for a in KILL_ACTIONS
            if a != drop]
    recs.append(ActionRecord(action=drop, state=STATE_SKIPPED, reason="사유"))
    assert action_rollup(recs)["cleared"] is False


def test_a_missing_action_is_not_silently_dropped():
    """넷 중 셋만 주면 남은 하나는 ★사라지지 않고 `unknown`★ 이다."""
    recs = [ActionRecord(action=a, state=STATE_DONE) for a in KILL_ACTIONS[:3]]
    r = action_rollup(recs)
    assert r["unknown"] == [KILL_ACTIONS[3]]
    assert r["cleared"] is False


# ── 관측 상태 ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", [0.0, 0, -0.05, 1_000_000.0])
def test_a_real_number_counts_as_observed_including_zero(value):
    """★진짜 0 은 관측이다★ — 문제는 **안 실은** 0 이지 잰 0 이 아니다."""
    assert observation_state(value) == OBSERVED


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), "0", True])
def test_anything_that_is_not_a_finite_number_is_unobserved(value):
    assert observation_state(value) == UNOBSERVED


def test_observations_carry_the_value_and_its_state_together():
    """★값과 그 값을 어떻게 알았나를 함께 낸다★ (AM 의 규율)"""
    obs = observations(equity_krw=None, dd_pct=0.12, regime="BEAR")
    assert obs["equity_krw"] == {"value": None, "state": UNOBSERVED}
    assert obs["dd_pct"] == {"value": 0.12, "state": OBSERVED}
    assert obs["regime"] == {"value": "BEAR", "state": OBSERVED}
    assert obs["any_unobserved"] is True


def test_a_fully_observed_trigger_says_so():
    """★짝★ — 항상 `any_unobserved=True` 인 구현을 배제한다."""
    obs = observations(equity_krw=1.0, dd_pct=0.0, regime="BULL")
    assert obs["any_unobserved"] is False


# ── 과거 행 ────────────────────────────────────────────────────────────────

def test_rows_written_before_this_program_are_unknown_not_done():
    """★소급하지 않는다★ — 안 적힌 것을 "했다" 로 채우면 없는 관측을 만든다."""
    recs = unknown_actions("이 기록은 조치 기록이 생기기 전에 쓰였습니다.")
    assert [r.action for r in recs] == list(KILL_ACTIONS)
    assert all(r.state == STATE_UNKNOWN and r.reason for r in recs)
    assert action_rollup(recs)["cleared"] is False


# ── 계층 경계 ──────────────────────────────────────────────────────────────

def test_the_module_touches_neither_storage_nor_network():
    """★`src/domain/` 은 순수하다★ — `test_risk_monitor_guard.py` 와 같은 규율."""
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
    assert not (imported & {"sqlalchemy", "requests", "httpx", "src"}), imported
