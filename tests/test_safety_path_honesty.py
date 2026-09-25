"""BH1 · 안전 경로 정직성 — ★아무것도 무장하지 않는다★
==============================================================================
스펙 `docs/superpowers/specs/2026-09-25-bh-safety-attribution-regime-design.md` §4.1 ·
대상 `src/execution/kill_switch.py` · `risk_gateway.py` · `risk_monitor.py` ·
`src/api/stage13_routes.py`(readiness) · `src/engine/realism_engine.py` ·
`src/services/narrative/prompts.py`

## 거는 것

- ★입력이 있으면 판정(발동·차단)은 한 글자도 바뀌지 않는다★ — 경계 골든.
- 미상은 0 이 아니다 — `systemic_risk_score` 가 없으면 발동도 통과도 아니고 "못 봤다".
- 게이트웨이 ⑧ 은 조용히 건너뛰지 않는다 — 못 본 것을 `checks_unverified` 에 이름으로.
- `recommended_mode` 를 `mode` 로 **매핑하지 않는다** — 그것은 방어 모드 매수 차단을 켜는
  판정 변경이다(별도 승인). 불일치는 사유 문구로 남는다.
- readiness 라우트는 감시 데몬과 **같은** 국면 입력을 본다.
"""
from __future__ import annotations

import os
import sys
import types

import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.execution.kill_switch import KillSwitch, KillSwitchConfig  # noqa: E402
from src.execution.risk_gateway import RiskGateway, RiskLimits  # noqa: E402
from tests.test_kill_switch_readiness_route import _admin, client  # noqa: E402,F401


@pytest.fixture()
def ks(monkeypatch) -> KillSwitch:
    switch = KillSwitch(engine=None, audit_trail=None, config=KillSwitchConfig())
    monkeypatch.setattr(switch, "is_active", lambda: False)
    return switch


_CALM = {"cumulative_dd_pct": 0.01, "current_drawdown_pct": 0.0,
         "api_failure_count": 0}


# ── 킬스위치 auto_risk — 경계 골든 ────────────────────────────────────────

def test_a_panic_score_at_the_threshold_fires(ks):
    """★짝★ — 발동 경로가 살아 있다(항상-불발 구현 배제). 임계 85 이상."""
    src, why = ks.should_auto_trigger(_CALM, {"systemic_risk_score": 85.0})
    assert src == "auto_risk" and "85" in why


def test_just_below_the_threshold_does_not_fire(ks):
    assert ks.should_auto_trigger(_CALM, {"systemic_risk_score": 84.99}) is None


@pytest.mark.parametrize("regime_state", [
    None, {}, {"regime": "Goldilocks"}, {"systemic_risk_score": None},
])
def test_an_unknown_score_neither_fires_nor_passes(ks, regime_state):
    """★미상은 발동도 "정상" 도 아니다★ — 불발이고, 못 봤다고 말한다."""
    assert ks.should_auto_trigger(_CALM, regime_state) is None
    assert any(u.startswith("auto_risk") for u in ks.unverified_checks(_CALM, regime_state))


def test_a_known_score_is_not_unverified(ks):
    """★짝★ — 값이 있으면 auto_risk 는 무장(항상-unverified 구현 배제)."""
    assert not any(u.startswith("auto_risk")
                   for u in ks.unverified_checks(_CALM, {"systemic_risk_score": 10}))


# ── 게이트웨이 ⑧ — 조용히 건너뛰지 않는다 ────────────────────────────────

_BUY = {"ticker": "005930", "side": "BUY", "quantity": 10, "price": 70_000,
        "strategy_id": 1}
_BIG_BUY = {**_BUY, "quantity": 1_000}          # 7,000 만 원 — 방어 한도(50%) 초과


def _state(**over) -> dict:
    base = {"equity_krw": 100_000_000, "cash_krw": 90_000_000, "positions": {},
            "daily_turnover_krw": 0, "current_drawdown_pct": 0.0,
            "cumulative_dd_pct": 0.0, "drawdown_reason": None}
    base.update(over)
    return base


def _gw() -> RiskGateway:
    # 단일 전략·종목 한도를 풀어 ★⑧ 만★ 판정에 남긴다(다른 검사가 먼저 막으면 공허하다).
    return RiskGateway(engine=None, limits=RiskLimits(position_size_max_pct=1.0,
                                                      concentration_limit_pct=1.0,
                                                      market_impact_reject_bps=10**9),
                       universe={"005930"}, bypass_market_hours=True)


def _regime_unverified(res) -> list[str]:
    return [u for u in res.checks_unverified if u.startswith("regime_adaptive")]


def test_no_regime_state_is_recorded_as_unverified_not_skipped():
    res = _gw().check(_BUY, _state(), regime_state=None)
    assert _regime_unverified(res), res.checks_unverified
    assert not any(p.startswith("regime_adaptive") for p in res.checks_passed)
    assert res.approved is True, "★판정 불변★ — 미상 라벨은 주문을 막지 않는다"


def test_a_missing_score_is_unverified_even_in_normal_mode():
    res = _gw().check(_BUY, _state(), regime_state={"regime": "Goldilocks", "mode": "normal"})
    assert "systemic_risk_score" in " ".join(_regime_unverified(res))
    assert res.approved is True


def test_a_complete_calm_regime_state_still_passes():
    """★짝★ — 다 알면 전과 같이 `checks_passed`(항상-unverified 구현 배제)."""
    res = _gw().check(_BUY, _state(),
                      regime_state={"regime": "Goldilocks", "mode": "normal",
                                    "systemic_risk_score": 20})
    assert "regime_adaptive" in res.checks_passed
    assert _regime_unverified(res) == []


def test_a_high_score_still_blocks_a_big_buy():
    """★판정 골든★ — 알 때의 차단은 그대로다."""
    res = _gw().check(_BIG_BUY, _state(),
                      regime_state={"regime": "Stagflation", "mode": "normal",
                                    "systemic_risk_score": 75})
    assert res.approved is False
    assert any("Defensive mode" in f for f in res.tier_failures)


@pytest.mark.parametrize("score,blocked", [(70, True), (69.99, False)])
def test_the_defensive_threshold_is_unchanged(score, blocked):
    """★경계 골든★ — 70 이상이면 방어(큰 매수 차단), 미만이면 아니다."""
    res = _gw().check(_BIG_BUY, _state(),
                      regime_state={"regime": "Stagflation", "mode": "normal",
                                    "systemic_risk_score": score})
    assert (res.approved is False) is blocked


def test_defensive_mode_without_a_score_still_blocks():
    """`mode == "defensive"` 만으로도 예전처럼 막는다 — 점수 미상이 차단을 끄지 않는다."""
    res = _gw().check(_BIG_BUY, _state(),
                      regime_state={"regime": "Stagflation", "mode": "defensive"})
    assert res.approved is False


def test_recommended_mode_is_not_mapped_into_the_decision():
    """★매핑하지 않는다★ — 분석기의 `recommended_mode="DEFENSIVE"` 로 매수를 막으면
    판정 변경이다. 막지 않고, 어휘가 어긋났다는 사실을 사유로 남긴다."""
    res = _gw().check(_BIG_BUY, _state(),
                      regime_state={"regime": "Stagflation",
                                    "recommended_mode": "DEFENSIVE"})
    assert res.approved is True
    joined = " ".join(_regime_unverified(res))
    assert "mode" in joined and "recommended_mode" in joined


# ── readiness 라우트 — 데몬과 같은 입력 ───────────────────────────────────

def _readiness(client):
    r = client.get("/api/v1/live/kill-switch/readiness", headers=_admin(client))
    assert r.status_code == 200, r.text[:300]
    return r.json()


def test_readiness_reads_the_same_regime_input_as_the_monitor(client, monkeypatch):
    """예전에는 `regime_state=None` 을 하드코딩해 데몬이 무엇을 보든 불능이었다."""
    import src.execution.risk_monitor as rm
    monkeypatch.setattr(rm, "current_regime_state",
                        lambda: {"regime": "Goldilocks", "systemic_risk_score": 10.0})
    body = _readiness(client)
    assert "auto_risk" in {a["trigger"] for a in body["armed"]}


def test_readiness_says_inoperable_when_the_monitor_sees_no_score(client, monkeypatch):
    """★짝★ — 지금 저장소의 실제 상태: 국면은 있어도 점수가 없다."""
    import src.execution.risk_monitor as rm
    monkeypatch.setattr(rm, "current_regime_state",
                        lambda: {"regime": "Goldilocks", "stress_score": 52.0})
    body = _readiness(client)
    ino = {i["trigger"]: i["reason"] for i in body["inoperable"]}
    assert "auto_risk" in ino and "systemic_risk_score" in ino["auto_risk"]


def test_the_lifecycle_alias_is_the_shared_function():
    """데몬(lifecycle)과 라우트가 두 벌을 두지 않는다."""
    import src.execution.risk_monitor as rm
    from src.startup import lifecycle
    assert lifecycle._monitor_regime_state is rm.current_regime_state


# ── 미상을 0 으로 만들던 나머지 두 곳 ───────────────────────────────────

def test_realism_does_not_turn_a_missing_score_into_zero(monkeypatch):
    """★regime_model 이 생기는 순간의 함정★ — 점수 키가 없으면 0.0 이 아니라 None."""
    import pandas as pd

    from src.engine.realism_engine import RealisticBacktester
    fake = types.ModuleType("src.engine.regime_model")

    class MultiRegimeModel:
        @staticmethod
        def classify_at_date(past, date):
            return {"regime": "Goldilocks"}

    fake.MultiRegimeModel = MultiRegimeModel
    monkeypatch.setitem(sys.modules, "src.engine.regime_model", fake)
    df = pd.DataFrame({"date": pd.to_datetime(["2024-01-02", "2024-01-03"]), "x": [1, 2]})
    assert RealisticBacktester._get_systemic_risk_pit(df, pd.Timestamp("2024-01-05")) is None

    MultiRegimeModel.classify_at_date = staticmethod(
        lambda past, date: {"regime": "Goldilocks", "systemic_risk_score": 42.0})
    assert RealisticBacktester._get_systemic_risk_pit(
        df, pd.Timestamp("2024-01-05")) == 42.0          # ★짝★ 값이 있으면 그 값


def test_the_briefing_prompt_does_not_invent_a_zero_score():
    from src.services.narrative.prompts import macro_briefing_prompt
    _sys, user = macro_briefing_prompt({"regime": "Goldilocks"})
    assert "0.0 / 100" not in user
    line = [ln for ln in user.splitlines() if "Systemic Risk Score" in ln][0]
    assert "미상" in line
    _sys, user2 = macro_briefing_prompt({"regime": "Goldilocks", "systemic_risk_score": 42})
    assert "42.0 / 100" in user2                          # ★짝★
