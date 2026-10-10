"""AK1 — 비용 성분과 그 상태 (순수 계층).

## ★두 축을 섞지 않는다★

    비용 성분(무엇을 재나)  ⟂  그 성분의 상태(부과했나 · 껐나 · 못 쟀나)

## ★`off` 와 `unmeasurable` 이 이 모듈의 요점★

둘 다 **0원을 부과**하지만 뜻이 정반대다. **끈 것**은 사용자의 선택이고,
**못 잰 것**은 ★비용이 실제보다 싸게 나왔다는 경고★ 다. 한 상태로 접으면
"시장충격을 안 켰다" 와 "켰는데 거래대금이 없어 못 쟀다" 가 리포트에서
구별되지 않고, 뒤쪽은 **조용히 싼 백테스트**가 된다.
"""
from __future__ import annotations

import ast
import dataclasses
import math
import pathlib

import pytest

from src.domain.cost_model import (
    COMPONENTS,
    STATE_CHARGED,
    STATE_OFF,
    STATE_UNMEASURABLE,
    STATES,
    CostPolicy,
    cost_label,
    policy_label,
    round_trip_bps,
    trade_cost,
)

_MODULE = (pathlib.Path(__file__).resolve().parents[1]
           / "src" / "domain" / "cost_model.py")

#: 기존 엔진 기본값 — 수수료 15bp · 슬리피지 5bp, 나머지 전부 꺼짐.
BASE = CostPolicy(commission_bps=15.0, slippage_bps=5.0)
#: 실행 준비실(`execution_plan`)과 같은 요율.
FULL = CostPolicy(commission_bps=1.5, slippage_bps=0.0,
                  charge_tax=True, tax_bps=18.0,
                  charge_spread=True, spread_bps=5.0,
                  charge_impact=True, impact_coeff=10.0)


def _by_name(breakdown) -> dict:
    return {c.name: c for c in breakdown.components}


# ═══════════════════════════════════════════════════════════════════════════
# ① ★수치 불변★ — 기본 정책은 오늘의 엔진과 산수가 같다
# ═══════════════════════════════════════════════════════════════════════════

def test_the_default_policy_costs_exactly_commission_plus_slippage():
    """★열셋을 한 함수로 모아도 값이 같아야 한다★"""
    value = 1_899_949.5
    got = trade_cost(value, "buy", BASE)
    assert got.total_krw == pytest.approx(value * 0.0015 + value * 0.0005)
    assert _by_name(got)["commission"].krw == pytest.approx(value * 0.0015)
    assert _by_name(got)["slippage"].krw == pytest.approx(value * 0.0005)


def test_the_default_policy_charges_nothing_for_the_three_new_components():
    for side in ("buy", "sell"):
        comps = _by_name(trade_cost(1_000_000.0, side, BASE))
        for name in ("tax", "spread", "impact"):
            assert comps[name].krw == 0.0
            assert comps[name].state == STATE_OFF


# ═══════════════════════════════════════════════════════════════════════════
# ③ ★`off` ≠ `unmeasurable`★ — 둘 다 0원인데 다른 사실이다
# ═══════════════════════════════════════════════════════════════════════════

def test_off_and_unmeasurable_are_different_states():
    off = _by_name(trade_cost(1e6, "buy", BASE))["impact"]
    on_no_data = _by_name(trade_cost(
        1e6, "buy", CostPolicy(charge_impact=True, impact_coeff=10.0)))["impact"]
    assert off.krw == on_no_data.krw == 0.0, "둘 다 0원인 것이 이 검사의 전제다"
    assert off.state != on_no_data.state
    assert on_no_data.state == STATE_UNMEASURABLE


def test_an_unmeasurable_component_always_carries_a_reason():
    """★사유 없는 미상은 침묵 폴백★ (CLAUDE.md §4)"""
    comp = _by_name(trade_cost(
        1e6, "buy", CostPolicy(charge_impact=True, impact_coeff=10.0)))["impact"]
    assert comp.reason


def test_an_off_component_says_it_was_switched_off_not_measured():
    """★'안 켰다' 를 '없다' 로 적지 않는다★"""
    comp = _by_name(trade_cost(1e6, "buy", BASE))["tax"]
    assert comp.reason and "선택" in comp.reason
    assert "없다는 뜻이 아" in comp.reason, "0 원을 부재로 읽히게 두면 안 된다"


def test_the_breakdown_reports_how_many_components_were_unmeasurable():
    got = trade_cost(1e6, "buy", CostPolicy(charge_impact=True, impact_coeff=10.0))
    assert got.n_unmeasurable == 1
    assert trade_cost(1e6, "buy", BASE).n_unmeasurable == 0


# ═══════════════════════════════════════════════════════════════════════════
# ④⑤⑮ 시장충격 — ★미상을 0 으로 부과하지 않는다★
# ═══════════════════════════════════════════════════════════════════════════

def test_impact_without_a_participation_rate_is_unmeasurable():
    """★0 은 '충격이 없었다' 는 **관측**이 되어 비용을 조용히 싸게 만든다★"""
    comp = _by_name(trade_cost(1e6, "buy", FULL, participation=None))["impact"]
    assert comp.state == STATE_UNMEASURABLE
    assert comp.krw == 0.0 and comp.reason


def test_impact_with_a_participation_rate_is_a_number():
    """★짝★ 언제나 미상인 구현을 배제한다."""
    comp = _by_name(trade_cost(1e6, "buy", FULL, participation=0.01))["impact"]
    assert comp.state == STATE_CHARGED
    assert comp.bps == pytest.approx(10.0 * math.sqrt(0.01))
    assert comp.krw == pytest.approx(1e6 * 10.0 * math.sqrt(0.01) / 1e4)


def test_impact_grows_with_participation():
    small = _by_name(trade_cost(1e6, "buy", FULL, participation=0.01))["impact"].krw
    big = _by_name(trade_cost(1e6, "buy", FULL, participation=0.25))["impact"].krw
    assert big > small > 0


@pytest.mark.parametrize("bad", [-0.01, float("nan"), float("inf"), "많음", True])
def test_a_broken_participation_never_reaches_the_square_root(bad):
    """★수치 안전★ (CLAUDE.md §6) — 음수·NaN 에서 안 터지고 미상이 된다."""
    comp = _by_name(trade_cost(1e6, "buy", FULL, participation=bad))["impact"]
    assert comp.state == STATE_UNMEASURABLE
    assert comp.krw == 0.0 and comp.reason


def test_impact_switched_on_without_a_coefficient_is_unmeasurable():
    comp = _by_name(trade_cost(
        1e6, "buy", CostPolicy(charge_impact=True), participation=0.01))["impact"]
    assert comp.state == STATE_UNMEASURABLE and comp.reason


# ═══════════════════════════════════════════════════════════════════════════
# ⑥⑦ 증권거래세 — ★매도에만★
# ═══════════════════════════════════════════════════════════════════════════

def test_the_sell_tax_is_charged_on_sells_only():
    assert _by_name(trade_cost(1e6, "sell", FULL))["tax"].krw == pytest.approx(1e6 * 0.0018)
    assert _by_name(trade_cost(1e6, "buy", FULL))["tax"].krw == 0.0


def test_the_buy_side_tax_says_why_it_is_zero():
    """★0 원인 이유가 '껐다' 가 아니라 '매수에는 없다' 임을 적는다★"""
    comp = _by_name(trade_cost(1e6, "buy", FULL))["tax"]
    assert comp.state == STATE_CHARGED, "켜져 있었고 평가됐다"
    assert comp.reason and "매도" in comp.reason


def test_switching_the_tax_on_makes_a_sell_more_expensive():
    """★짝★ 켜도 안 변하는 구현을 배제한다."""
    off = trade_cost(1e6, "sell", CostPolicy(commission_bps=1.5)).total_krw
    on = trade_cost(1e6, "sell", CostPolicy(commission_bps=1.5, charge_tax=True,
                                            tax_bps=18.0)).total_krw
    assert on > off
    assert on - off == pytest.approx(1e6 * 0.0018)


def test_the_tax_switched_on_without_a_rate_is_unmeasurable():
    comp = _by_name(trade_cost(1e6, "sell", CostPolicy(charge_tax=True)))["tax"]
    assert comp.state == STATE_UNMEASURABLE and comp.reason


# ═══════════════════════════════════════════════════════════════════════════
# ⑧ 스프레드 — 양방향, ★편도의 절반★
# ═══════════════════════════════════════════════════════════════════════════

def test_the_spread_costs_half_the_quoted_width_each_way():
    """`execution_plan:73` 의 `notional * spread * 0.5` 와 같은 뜻이다."""
    for side in ("buy", "sell"):
        comp = _by_name(trade_cost(1e6, side, FULL))["spread"]
        assert comp.bps == pytest.approx(2.5)
        assert comp.krw == pytest.approx(1e6 * 0.00025)


# ═══════════════════════════════════════════════════════════════════════════
# ⑩ ★실행 준비실과 같은 답★
# ═══════════════════════════════════════════════════════════════════════════

def test_a_full_policy_round_trip_matches_the_execution_desk():
    """`execution_plan.build_plan` 과 같은 요율·같은 식이면 같은 왕복이 나온다.

    매수 1.5 + 2.5 = 4bp · 매도 1.5 + 18 + 2.5 = 22bp → 26bp (충격 제외).
    """
    rt = round_trip_bps(FULL)
    assert rt["buy_bps"] == pytest.approx(4.0)
    assert rt["sell_bps"] == pytest.approx(22.0)
    assert rt["round_trip_bps"] == pytest.approx(26.0)


def test_the_engine_default_round_trip_is_forty_bps():
    """오늘의 `kis_backtest_engine` 기본값 — 15×2 + 5×2."""
    assert round_trip_bps(BASE)["round_trip_bps"] == pytest.approx(40.0)


def test_round_trip_says_impact_is_excluded():
    assert round_trip_bps(FULL)["impact_excluded"] is True
    assert round_trip_bps(FULL)["reason"]


# ═══════════════════════════════════════════════════════════════════════════
# 라벨 · 타입 · 순수성
# ═══════════════════════════════════════════════════════════════════════════

def test_every_component_appears_in_every_breakdown():
    """★빠진 성분은 0 이 아니라 부재다★ — 다섯이 언제나 실린다."""
    for policy in (BASE, FULL, CostPolicy()):
        assert set(_by_name(trade_cost(1e6, "sell", policy))) == set(COMPONENTS)


def test_the_label_carries_states_totals_and_the_unmeasured_count():
    got = cost_label(trade_cost(1e6, "sell", FULL))
    assert set(got["components"]) == set(COMPONENTS)
    assert got["total_krw"] > 0 and got["total_bps"] > 0
    assert got["n_unmeasurable"] == 1          # 충격 (참여율 없음)
    assert got["components"]["impact"]["state"] == STATE_UNMEASURABLE


def test_the_policy_label_admits_the_impact_coefficient_is_a_setting():
    """★`k=10` 은 측정치가 아니라 설정값이다★"""
    got = policy_label(FULL)
    assert got["impact_coeff"] == 10.0
    assert got["impact_coeff_note"]


def test_the_states_are_a_closed_vocabulary():
    assert len(set(STATES)) == len(STATES)
    assert {STATE_CHARGED, STATE_OFF, STATE_UNMEASURABLE} <= set(STATES)


def test_the_policy_is_immutable():
    with pytest.raises(dataclasses.FrozenInstanceError):
        BASE.commission_bps = 99.0   # type: ignore[misc]


def test_an_empty_policy_charges_nothing_and_says_so():
    got = trade_cost(1e6, "buy", CostPolicy())
    assert got.total_krw == 0.0
    assert all(c.reason for c in got.components if c.state != STATE_CHARGED)


def test_the_domain_module_stays_pure():
    """★요율을 여기서 읽지 않는다★ — `market_rules` 는 엔진 경계에서 읽는다.

    도메인이 설정 계층을 import 하면 순수 함수를 설정 없이 시험할 수 없고,
    같은 산수가 환경변수에 따라 다른 답을 낸다.
    """
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    for name in imported:
        for bad in ("sqlalchemy", "fastapi", "requests", "pandas", "numpy", "scipy",
                    "src.database", "src.data", "src.engine", "src.execution", "src.api"):
            assert not name.startswith(bad), f"순수 계층이 {name} 을 import 한다"


# ═══════════════════════════════════════════════════════════════════════════
# AM5 · `cost_model_version` — ★설정의 해시이지 코드 버전이 아니다★
# ═══════════════════════════════════════════════════════════════════════════
#
# 채점표 #7 은 `cost_model_version` 이 **없다**고 적었다. AK 가 `CostPolicy` 를
# frozen dataclass 로 만들어 두었으므로 재료는 이미 있다 — 같은 정책은 같은
# 버전, 다른 정책은 다른 버전. 지금은 비용 설정이 다른 두 백테스트가 기록에서
# **구별되지 않는다**.

def _pol(**kw):
    from src.domain.cost_model import CostPolicy
    base = dict(commission_bps=15.0, slippage_bps=5.0)
    base.update(kw)
    return CostPolicy(**base)


def test_the_same_policy_always_gives_the_same_version():
    """★결정론적★ — 아니면 기록이 실행마다 달라져 쓸모가 없다."""
    from src.domain.cost_model import policy_version
    assert policy_version(_pol()) == policy_version(_pol())


def test_a_different_policy_gives_a_different_version():
    """★짝★ — 상수를 돌려주는 구현을 배제한다."""
    from src.domain.cost_model import policy_version
    base = policy_version(_pol())
    assert policy_version(_pol(commission_bps=1.5)) != base
    assert policy_version(_pol(slippage_bps=0.0)) != base
    assert policy_version(_pol(charge_tax=True)) != base
    assert policy_version(_pol(charge_spread=True)) != base
    assert policy_version(_pol(charge_impact=True)) != base
    assert policy_version(_pol(tax_bps=18.0)) != base
    assert policy_version(_pol(spread_bps=3.0)) != base
    assert policy_version(_pol(impact_coeff=0.1)) != base


def test_every_policy_field_moves_the_version():
    """★전수★ 필드를 새로 더하고 해시에서 빠뜨리면 여기서 걸린다.

    `dataclasses.fields` 로 읽으므로 **손으로 센 목록이 낡을 수 없다**.
    """
    import dataclasses

    from src.domain.cost_model import CostPolicy, policy_version
    base_policy = _pol()
    base = policy_version(base_policy)
    for f in dataclasses.fields(CostPolicy):
        cur = getattr(base_policy, f.name)
        if isinstance(cur, bool):
            nxt = not cur
        elif cur is None:
            nxt = 7.25
        else:
            nxt = float(cur) + 1.0
        moved = policy_version(dataclasses.replace(base_policy, **{f.name: nxt}))
        assert moved != base, f"{f.name} 이 버전을 움직이지 않는다"


def test_the_version_is_a_short_stable_hex_string():
    from src.domain.cost_model import policy_version
    v = policy_version(_pol())
    assert isinstance(v, str) and len(v) == 12
    assert all(c in "0123456789abcdef" for c in v)


def test_an_equal_but_differently_built_policy_matches():
    """`None` 과 0.0 을 같은 것으로 접지 않는다 — ★미상 ≠ 0★"""
    from src.domain.cost_model import policy_version
    assert policy_version(_pol(tax_bps=None)) != policy_version(_pol(tax_bps=0.0))


def test_an_int_and_a_float_of_the_same_value_are_the_same_policy():
    """★정준화★ `15` 와 `15.0` 이 다른 버전이면 해시가 표현을 센 것이다."""
    from src.domain.cost_model import policy_version
    assert policy_version(_pol(commission_bps=15)) == \
        policy_version(_pol(commission_bps=15.0))
