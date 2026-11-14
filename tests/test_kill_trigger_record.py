"""AP2·AP4·AP5 — 발동 기록이 ★하지 않은 일을 했다고 말하지 않는다★

실측으로 찾은 거짓 셋을 고정한다:

    ① `dd_at_trigger` 가 저장소 전체에서 언제나 `0` 이었다 — 기본값이 `0` 이고
       **어느 호출부도 `dd_pct` 를 넘기지 않는다**. 드로다운 때문에 발동한 사건의
       드로다운이 `0` 으로 남는다(AM 의 `"dev"` 와 같은 모양).
    ② `hold` 모드는 청산을 **아예 하지 않는데** 응답이 `liquidation_complete: True`
       를 냈다(초기 dict 가 교체되지 않는다).
    ③ `kis_client=None` 이면 취소를 **건너뛰는데** `n_orders_cancelled=0` 이 남아
       ★"취소할 주문이 없었다" 와 구별되지 않았다★.

★주문 로직은 0줄 바뀌지 않는다★ — 바뀌는 것은 **무엇을 했다고 말하는가**뿐이다.
"""
from __future__ import annotations

import json
import os
import pathlib

import pytest
from sqlalchemy import create_engine, text

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.domain.kill_action import (  # noqa: E402
    ACTION_BLOCK_NEW_ORDERS,
    ACTION_CANCEL_OPEN,
    ACTION_LIQUIDATE,
    ACTION_NOTIFY,
    OBSERVED,
    STATE_DONE,
    STATE_SKIPPED,
    UNOBSERVED,
)
from src.execution.kill_switch import KillSwitch, KillSwitchConfig  # noqa: E402
from src.execution.live_schemas import init_live_trading_schema  # noqa: E402


class _FakeKIS:
    """결정론적 가짜 브로커 — `test_kill_switch_honesty.py` 와 같은 모양."""

    def __init__(self, positions=None):
        self._positions = positions if positions is not None else []
        self.cancelled: list[str] = []

    def get_balance(self) -> dict:
        return {"positions": list(self._positions), "evaluated_total": 5_000_000}

    def cancel_order(self, *a, **kw):
        self.cancelled.append(str(a) + str(kw))
        return {"ok": True}

    def place_order(self, ticker, side, quantity, order_type):
        return {"order_no": "T-1"}


@pytest.fixture()
def engine():
    eng = create_engine("sqlite://")
    init_live_trading_schema(eng)
    return eng


@pytest.fixture()
def ks(engine):
    return KillSwitch(engine=engine, audit_trail=None, config=KillSwitchConfig())


def _row(engine, event_id: str) -> dict:
    with engine.connect() as conn:
        r = conn.execute(text("SELECT * FROM live_kill_events WHERE event_id = :e"),
                         {"e": event_id}).fetchone()
    return dict(r._mapping)


def _action(result: dict, name: str) -> dict:
    return next(r for r in result["actions"]["records"] if r["action"] == name)


# ── ① ★안 실은 값은 0 이 아니라 NULL★ ──────────────────────────────────────

def test_an_unloaded_drawdown_is_recorded_as_null_not_zero(ks, engine):
    """★이 프로그램의 핵심★ — 기본값 `0` 이 관측 행세를 하던 자리."""
    out = ks.trigger(source="auto_dd", reason="테스트")
    row = _row(engine, out["event_id"])
    assert row["dd_at_trigger"] is None
    assert row["equity_at_trigger"] is None


def test_a_loaded_drawdown_is_recorded(ks, engine):
    """★짝★ — 언제나 NULL 인 구현을 배제한다."""
    out = ks.trigger(source="auto_dd", reason="테스트",
                     equity=1_000_000.0, dd_pct=0.12)
    row = _row(engine, out["event_id"])
    assert row["dd_at_trigger"] == pytest.approx(0.12)
    assert row["equity_at_trigger"] == pytest.approx(1_000_000.0)


def test_a_measured_zero_drawdown_is_still_an_observation(ks, engine):
    """★잰 0 은 관측이다★ — 문제는 **안 실은** 0 이지 잰 0 이 아니다."""
    out = ks.trigger(source="manual", reason="테스트", equity=0.0, dd_pct=0.0)
    assert out["observations"]["dd_pct"]["state"] == OBSERVED
    assert _row(engine, out["event_id"])["dd_at_trigger"] == pytest.approx(0.0)


def test_the_response_says_which_axes_were_not_observed(ks):
    out = ks.trigger(source="auto_cb", reason="테스트")
    obs = out["observations"]
    assert obs["dd_pct"]["state"] == UNOBSERVED
    assert obs["equity_krw"]["state"] == UNOBSERVED
    assert obs["any_unobserved"] is True


def test_the_notification_survives_missing_observations(ks):
    """★`f"{None:,.0f}"` 는 터진다★ — 미상이면 '미상' 을 찍는다(회귀 가드)."""
    out = ks.trigger(source="auto_dd", reason="테스트")   # 예외가 나면 실패
    assert out["event_id"]
    assert _action(out, ACTION_NOTIFY)["state"] == STATE_DONE


# ── ③ ★시도하지 않은 것과 할 일이 없던 것을 가른다★ ──────────────────────

def test_without_a_broker_client_the_cancel_is_skipped_not_done(ks, engine):
    out = ks.trigger(source="auto_dd", reason="테스트")
    rec = _action(out, ACTION_CANCEL_OPEN)
    assert rec["state"] == STATE_SKIPPED and rec["reason"]
    # ★0 건 취소와 구별된다★ — 컬럼도 0 이 아니라 NULL 이다.
    assert _row(engine, out["event_id"])["n_orders_cancelled"] is None


def test_with_a_broker_client_the_cancel_is_done_even_with_nothing_to_cancel(ks, engine):
    """★짝★ — 취소할 주문이 없어도 **시도했다**는 것은 다른 사실이다."""
    out = ks.trigger(source="manual", reason="테스트", kis_client=_FakeKIS())
    rec = _action(out, ACTION_CANCEL_OPEN)
    assert rec["state"] == STATE_DONE
    assert rec["detail"]["n_cancelled"] == 0
    assert _row(engine, out["event_id"])["n_orders_cancelled"] == 0


# ── ② ★청산하지 않고 "완료" 라고 말하지 않는다★ ─────────────────────────

def test_hold_mode_does_not_claim_a_completed_liquidation(ks):
    out = ks.trigger(source="auto_dd", reason="테스트", liquidation_mode="hold")
    rec = _action(out, ACTION_LIQUIDATE)
    assert rec["state"] == STATE_SKIPPED and rec["reason"]
    # ★미상은 거짓이 아니다★ — 시도하지 않았으면 True 도 False 도 아니다.
    assert out["liquidation_complete"] is None


def test_an_attempted_liquidation_still_reports_a_boolean(ks):
    """★짝★ — 언제나 `None` 인 구현을 배제한다(AF1 의 회계를 지킨다)."""
    kis = _FakeKIS(positions=[{"ticker": "005930", "quantity": 100,
                               "eval_amount": 7_000_000, "current_price": 70_000}])
    out = ks.trigger(source="manual", reason="테스트", kis_client=kis,
                     liquidation_mode="immediate")
    assert _action(out, ACTION_LIQUIDATE)["state"] == STATE_DONE
    assert isinstance(out["liquidation_complete"], bool)


def test_a_liquidation_mode_without_a_client_is_also_skipped(ks):
    """모드를 골라도 브로커가 없으면 판 것이 없다."""
    out = ks.trigger(source="auto_dd", reason="테스트", liquidation_mode="immediate")
    assert _action(out, ACTION_LIQUIDATE)["state"] == STATE_SKIPPED
    assert out["liquidation_complete"] is None


# ── 언제나 참인 조치 하나 ──────────────────────────────────────────────────

def test_blocking_new_orders_is_the_one_action_that_always_happened(ks):
    """★이벤트 행이 생기면 `is_active()` 가 참★ — 구조적으로 보장된다."""
    out = ks.trigger(source="auto_dd", reason="테스트")
    rec = _action(out, ACTION_BLOCK_NEW_ORDERS)
    assert rec["state"] == STATE_DONE
    assert rec["detail"]["guard"]           # 어디서 막는지 적는다
    assert ks.is_active() is True


def test_a_disabled_notification_is_skipped_with_a_reason(engine):
    cfg = KillSwitchConfig(notification_enabled=False)
    ks = KillSwitch(engine=engine, audit_trail=None, config=cfg)
    out = ks.trigger(source="manual", reason="테스트")
    rec = _action(out, ACTION_NOTIFY)
    assert rec["state"] == STATE_SKIPPED and rec["reason"]


# ── ★발동이 정리를 뜻하지 않는다★ ───────────────────────────────────────

def test_the_automatic_shaped_call_is_never_cleared(ks):
    """자동 경로의 모양(브로커 없음 · hold)으로 부르면 `cleared` 가 아니다."""
    out = ks.trigger(source="auto_dd", reason="테스트")
    assert out["actions"]["cleared"] is False
    assert out["actions"]["summary"]


def test_the_note_does_not_promise_that_positions_are_flat(ks):
    out = ks.trigger(source="auto_dd", reason="테스트")
    assert "뜻이 아닙니다" in out["actions"]["note"]


# ── 저장 ───────────────────────────────────────────────────────────────────

def test_the_actions_are_persisted_and_readable(ks, engine):
    out = ks.trigger(source="auto_dd", reason="테스트")
    stored = json.loads(_row(engine, out["event_id"])["actions_json"])
    assert stored["cleared"] is False
    assert {r["action"] for r in stored["records"]} == {
        ACTION_BLOCK_NEW_ORDERS, ACTION_CANCEL_OPEN, ACTION_LIQUIDATE, ACTION_NOTIFY}


# ── AP5 · 표면이 조치를 싣는다 ★과거 행은 소급하지 않는다★ ───────────────

def test_the_active_event_carries_its_actions(ks):
    out = ks.trigger(source="auto_dd", reason="테스트")
    active = ks.active_event()
    assert active["event_id"] == out["event_id"]
    assert active["actions"]["cleared"] is False
    assert {r["action"] for r in active["actions"]["records"]} == {
        ACTION_BLOCK_NEW_ORDERS, ACTION_CANCEL_OPEN, ACTION_LIQUIDATE, ACTION_NOTIFY}


def test_a_row_written_before_this_program_reports_unknown_actions(ks, engine):
    """★소급하지 않는다★ — 조치 기록이 없는 행을 "했다" 로 채우지 않는다."""
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO live_kill_events (event_id, trigger_source, trigger_reason) "
            "VALUES ('OLD-1', 'manual_x', '이 어휘 이전에 쓰인 행')"))
    row = ks.active_event()
    assert row["event_id"] == "OLD-1"
    assert row["actions"]["unknown"] == [
        ACTION_BLOCK_NEW_ORDERS, ACTION_CANCEL_OPEN, ACTION_LIQUIDATE, ACTION_NOTIFY]
    assert row["actions"]["cleared"] is False
    assert all(r["reason"] for r in row["actions"]["records"])


def test_an_unreadable_action_record_is_unknown_not_a_crash(ks, engine):
    """★깨진 기록은 미상이지 '했다' 가 아니다★"""
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO live_kill_events "
            "(event_id, trigger_source, trigger_reason, actions_json) "
            "VALUES ('BAD-1', 'manual_x', '깨진 기록', '{ not json')"))
    row = ks.active_event()
    assert row["actions"]["cleared"] is False
    assert row["actions"]["unknown"]


# ── AP5 · ★프런트 타입과 응답이 어긋나면 화면이 조용히 빈다★ ─────────────

#: 발동 응답 최상위 키 **골든**. 늘거나 줄면 이 테스트가 먼저 말한다.
TRIGGER_KEYS = {
    "event_id", "triggered_at", "trigger_source", "trigger_reason",
    "equity_at_trigger", "dd_at_trigger", "liquidation_mode",
    "n_orders_cancelled", "n_positions_closed", "krw_recovered",
    "liquidation", "liquidation_complete", "liquidation_note",
    "actions", "observations",
}

_TYPES_TS = pathlib.Path("frontend/src/entities/kill-switch/types.ts")


def test_the_trigger_response_shape_is_pinned(ks):
    assert set(ks.trigger(source="auto_dd", reason="테스트")) == TRIGGER_KEYS


def test_the_frontend_type_declares_every_trigger_key():
    """★타입은 화면이 없어도 계약이다★ — 키가 빠지면 나중에 `undefined` 로 샌다."""
    src = _TYPES_TS.read_text(encoding="utf-8")
    block = src.split("export interface KillTriggerResult {", 1)[1].split("\n}", 1)[0]
    declared = {line.split(":", 1)[0].strip().lstrip("/* ")
                for line in block.splitlines()
                if ":" in line and not line.strip().startswith(("*", "/"))}
    assert TRIGGER_KEYS <= declared, TRIGGER_KEYS - declared
