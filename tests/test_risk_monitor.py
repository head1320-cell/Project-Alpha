"""리스크 감시 루프 — ★관측만이 기본★ (P1-b)

## 왜 이것이 없었나 (실측)

탐지기는 이미 다 있었다 — `kill_switch.should_auto_trigger()`(4종 판정) ·
`KillSwitchConfig`(임계값) · `is_active()`(DB 실패 시 `True` 로 페일세이프) ·
`reconciler.start_periodic_sync()`. ★그런데 부르는 곳이 없었다.★
`should_auto_trigger` 의 유일한 호출부는 **클래스 docstring 의 사용 예시**였고,
그 주석은 *"모니터링 루프에서 호출"* 이라고 적혀 있는데 그 루프가 없었다.
`apscheduler` 는 requirements 에 선언만 되고 `src/` 안 사용처가 0 이었다.

## 이 파일이 못 박는 것

    ★한 주기가 돌면 판정이 감사 기록에 남는다.★
    ★"정상" 과 "못 봤다" 를 구분해 적는다.★
    ★자동 발동은 기본으로 꺼져 있고, 환경변수가 **정확히** "1" 일 때만 켜진다.★
    ★루프는 예외로 죽지 않는다.★
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.execution.audit_trail import AuditTrail  # noqa: E402
from src.execution.kill_switch import KillSwitchConfig  # noqa: E402
from src.execution.live_schemas import init_live_trading_schema  # noqa: E402
from src.execution.risk_monitor import (  # noqa: E402
    AUTOTRIGGER_ENV,
    VERDICT_OK,
    VERDICT_UNKNOWN,
    VERDICT_WOULD_TRIGGER,
    autotrigger_allowed,
    evaluate,
    run_once,
)


@pytest.fixture()
def engine():
    eng = create_engine("sqlite://")
    init_live_trading_schema(eng)
    return eng


class _FakeSwitch:
    """판정 로직만 본다 — DB 를 읽는 `is_active()` 는 고정."""

    def __init__(self, active: bool = False):
        self.config = KillSwitchConfig()
        self._active = active
        self.triggered: list[tuple[str, str]] = []

    def is_active(self) -> bool:
        return self._active

    def should_auto_trigger(self, account_state, regime_state=None):
        from src.execution.kill_switch import KillSwitch
        return KillSwitch.should_auto_trigger(self, account_state, regime_state)

    def unverified_checks(self, account_state, regime_state=None):
        from src.execution.kill_switch import KillSwitch
        return KillSwitch.unverified_checks(self, account_state, regime_state)

    def trigger(self, source, reason, **kw):
        self.triggered.append((source, reason))
        return {"event_id": "EVT-test"}


def _unknown_state() -> dict:
    return {"equity_krw": 1, "current_drawdown_pct": None, "cumulative_dd_pct": None,
            "drawdown_reason": "no_equity_history"}


def _calm_state() -> dict:
    # ★`api_failure_count` 가 추가됐다(AF2)★ — 이 상태는 "다 아는 상태" 를 자처하는데
    #   예전에는 API 실패 횟수를 **빠뜨린 채** 그렇게 불렀다. `unverified_checks()` 가
    #   그 항목을 세지 않았기 때문이고, 그것이 바로 AF 가 고친 사각지대다.
    #   "다 안다" 가 실제로 다 아는 상태를 뜻하도록 값을 채운다.
    return {"equity_krw": 1, "current_drawdown_pct": 0.01, "cumulative_dd_pct": 0.02,
            "drawdown_reason": None, "api_failure_count": 0}


def _breach_state() -> dict:
    return {"equity_krw": 1, "current_drawdown_pct": 0.0, "cumulative_dd_pct": 0.50,
            "drawdown_reason": None}


_CALM_REGIME = {"systemic_risk_score": 10}


def _rows(eng) -> list[dict]:
    with eng.connect() as c:
        return [dict(r._mapping) for r in c.execute(text(
            "SELECT * FROM live_audit_trail ORDER BY audit_id"))]


# ═══════════════════════════════════════════════════════════════════════════
# 판정 — ★"정상" 과 "못 봤다" 는 다르다★
# ═══════════════════════════════════════════════════════════════════════════

def test_unknown_drawdown_is_unknown_not_ok():
    v = evaluate(_FakeSwitch(), _unknown_state(), _CALM_REGIME)
    assert v.verdict == VERDICT_UNKNOWN
    assert any("no_equity_history" in u for u in v.unverified), v.unverified


def test_a_calm_and_fully_known_state_is_ok():
    """★짝★ 다 알고 한도 안이면 `ok` 다(항상-unknown 구현 배제)."""
    v = evaluate(_FakeSwitch(), _calm_state(), _CALM_REGIME)
    assert v.verdict == VERDICT_OK
    assert v.unverified == ()


def test_a_breach_is_would_trigger():
    v = evaluate(_FakeSwitch(), _breach_state(), _CALM_REGIME)
    assert v.verdict == VERDICT_WOULD_TRIGGER
    assert v.source == "auto_dd"
    assert v.reason and "한도 초과" in v.reason


def test_an_already_active_switch_does_not_re_trigger():
    v = evaluate(_FakeSwitch(active=True), _breach_state(), _CALM_REGIME)
    assert v.verdict != VERDICT_WOULD_TRIGGER


# ═══════════════════════════════════════════════════════════════════════════
# ⑦ 한 주기가 돌면 ★기록이 남는다★
# ═══════════════════════════════════════════════════════════════════════════

def test_one_cycle_leaves_an_audit_row(engine):
    run_once(kill_switch=_FakeSwitch(), audit=AuditTrail(engine),
             account_state=_unknown_state(), regime_state=_CALM_REGIME, last=None)
    rows = _rows(engine)
    assert len(rows) == 1, rows
    assert rows[0]["reason_code"] == VERDICT_UNKNOWN
    assert "no_equity_history" in (rows[0]["context_json"] or "")


def test_the_audit_row_says_ok_when_it_is_ok(engine):
    run_once(kill_switch=_FakeSwitch(), audit=AuditTrail(engine),
             account_state=_calm_state(), regime_state=_CALM_REGIME, last=None)
    assert _rows(engine)[0]["reason_code"] == VERDICT_OK


# ═══════════════════════════════════════════════════════════════════════════
# ⑨ 같은 판정은 ★한 번만★ 적는다
# ═══════════════════════════════════════════════════════════════════════════

def test_a_repeated_verdict_is_not_written_twice(engine):
    audit = AuditTrail(engine)
    kw = dict(kill_switch=_FakeSwitch(), audit=audit,
              account_state=_unknown_state(), regime_state=_CALM_REGIME)
    first = run_once(last=None, **kw)
    run_once(last=first, **kw)
    assert len(_rows(engine)) == 1, "같은 판정을 두 번 적었다"


def test_a_changed_verdict_is_written(engine):
    """★짝★ 바뀌면 반드시 적는다(항상-침묵 구현 배제)."""
    audit = AuditTrail(engine)
    ks = _FakeSwitch()
    first = run_once(kill_switch=ks, audit=audit, account_state=_unknown_state(),
                     regime_state=_CALM_REGIME, last=None)
    run_once(kill_switch=ks, audit=audit, account_state=_calm_state(),
             regime_state=_CALM_REGIME, last=first)
    assert len(_rows(engine)) == 2


# ═══════════════════════════════════════════════════════════════════════════
# ⑧ 자동 발동은 ★정확히 "1" 일 때만★
# ═══════════════════════════════════════════════════════════════════════════

def test_autotrigger_is_off_by_default(monkeypatch, engine):
    monkeypatch.delenv(AUTOTRIGGER_ENV, raising=False)
    ks = _FakeSwitch()
    run_once(kill_switch=ks, audit=AuditTrail(engine), account_state=_breach_state(),
             regime_state=_CALM_REGIME, last=None)
    assert ks.triggered == [], "★기본은 관측만이다★"


def test_autotrigger_fires_when_exactly_one(monkeypatch, engine):
    monkeypatch.setenv(AUTOTRIGGER_ENV, "1")
    ks = _FakeSwitch()
    run_once(kill_switch=ks, audit=AuditTrail(engine), account_state=_breach_state(),
             regime_state=_CALM_REGIME, last=None)
    assert [s for s, _ in ks.triggered] == ["auto_dd"]


@pytest.mark.parametrize("val", ["true", "TRUE", "yes", "on", "01", " 1", "1 ", "0", ""])
def test_only_the_exact_string_one_enables_autotrigger(monkeypatch, val):
    """`mock_gate.mock_allowed()` 와 같은 ★엄격 비교★ 관례."""
    monkeypatch.setenv(AUTOTRIGGER_ENV, val)
    assert autotrigger_allowed() is False, val


def test_autotrigger_does_not_fire_on_unknown(monkeypatch, engine):
    """★미상으로 계좌를 청산하지 않는다.★"""
    monkeypatch.setenv(AUTOTRIGGER_ENV, "1")
    ks = _FakeSwitch()
    run_once(kill_switch=ks, audit=AuditTrail(engine), account_state=_unknown_state(),
             regime_state=_CALM_REGIME, last=None)
    assert ks.triggered == []


# ═══════════════════════════════════════════════════════════════════════════
# ⑩ 루프는 ★죽지 않는다★
# ═══════════════════════════════════════════════════════════════════════════

def test_run_once_survives_a_broken_switch(engine):
    class _Boom(_FakeSwitch):
        """★실제 장애 모양★ — `is_active()` 가 DB 를 읽다가 터진다."""

        def is_active(self):
            raise RuntimeError("DB 폭발")

    v = run_once(kill_switch=_Boom(), audit=AuditTrail(engine),
                 account_state=_calm_state(), regime_state=_CALM_REGIME, last=None)
    assert v.verdict == VERDICT_UNKNOWN
    assert any("DB 폭발" in u for u in v.unverified), v.unverified


def test_run_once_survives_a_broken_audit():
    class _BoomAudit:
        def log(self, **kw):
            raise RuntimeError("감사 기록 실패")

    v = run_once(kill_switch=_FakeSwitch(), audit=_BoomAudit(),
                 account_state=_calm_state(), regime_state=_CALM_REGIME, last=None)
    assert v.verdict == VERDICT_OK, "기록에 실패해도 판정은 돌아와야 한다"


# ═══════════════════════════════════════════════════════════════════════════
# ★두 어휘를 조용히 잇지 않는다★ — stress_score ≠ systemic_risk_score
# ═══════════════════════════════════════════════════════════════════════════

def test_the_monitor_does_not_fabricate_a_systemic_risk_score():
    """★실측: `systemic_risk_score` 의 생산자가 저장소에 없다.★

    킬스위치의 `auto_risk` 는 `systemic_risk_score` 를 보는데, 그 값을 만든다고
    지목된 `src.engine.regime_model.MultiRegimeModel` 은 존재하지 않는다(두 모듈이
    `try/except` 안에서 임포트해 ImportError 를 삼킨다). `regime_analyzer` 가 드는
    것은 `stress_score` 이고, 둘을 잇는 코드는 어디에도 없다.

    파이프라인을 돌리려고 이름을 바꿔 끼우면 `auto_risk` 가 **확인되지 않은 양**으로
    발동하게 된다. 그래서 감시자는 그 칸을 비우고 `unverified` 로 남긴다.
    """
    from src.startup.lifecycle import _monitor_regime_state
    st = _monitor_regime_state()
    if st is not None:
        assert "systemic_risk_score" not in st, \
            "★확인되지 않은 매핑으로 그 칸을 채웠다★ — 잇기로 했다면 근거를 문서에 남길 것"


def test_the_producer_named_in_the_code_really_is_absent():
    """★테스트의 테스트★ 위 주장이 낡으면 여기서 먼저 깨진다."""
    import importlib
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("src.engine.regime_model")
