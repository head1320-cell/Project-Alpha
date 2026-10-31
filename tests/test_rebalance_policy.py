"""리밸런싱 정책 엔진 — 거래 **여부**를 판단한다 (Brief §10)

★이 파일이 거는 것★
  1. ★편익을 모르면 거래를 권하지 않는다★ 트리거만 보고 거래하라고 말하는 것이
     지금까지의 결함이었다(감사 §3.1 — "거래 여부를 아무도 판단하지 않는다").
  2. ★밴드가 고정이 아니다★ Brief §10 이 금지한 "고정 ±5%" 가 이름만 바뀌어
     되풀이되지 않는지 — 밴드가 **입력에 실제로 반응하는지** 잰다.
  3. ★연율과 일회성을 그냥 비교하지 않는다★ 보유기간 가정이 드러나는지.

★합성 μ/Σ 를 쓰되 비용은 실제 엔진을 태운다★ `execution_plan.build_plan` 이
수수료·세금·스프레드·임팩트를 계산하는 실물이고, 가격/유동성만 주입한다.
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from src.engine.rebalance_policy import (  # noqa: E402
    DECISION_HOLD,
    DECISION_TRADE,
    DECISION_UNDETERMINED,
    DEFAULT_RISK_AVERSION,
    detect_triggers,
    dynamic_band,
    expected_utility_gain,
    gradual_target,
    rebalance_decision,
    utility,
)

NAMES = ["005930", "000660"]
MU = np.array([0.12, 0.06])
SIGMA = np.array([[0.09, 0.02], [0.02, 0.06]])
PV = 100_000_000.0

CUR = {"005930": 40.0, "000660": 60.0}
TGT = {"005930": 70.0, "000660": 30.0}


def _px(_code):
    return 70000.0


def _adv(_code):
    return 5e11


def _decide(cur=None, tgt=None, **kw):
    kw.setdefault("names", NAMES)
    kw.setdefault("mu", MU)
    kw.setdefault("sigma", SIGMA)
    return rebalance_decision(cur or CUR, tgt or TGT, portfolio_value=PV,
                              price_of=_px, adv_of=_adv, **kw)


# ── 1. ★편익을 모르면 거래를 권하지 않는다★ ───────────────────────────────
def test_without_mu_sigma_the_decision_is_undetermined_not_trade():
    """★이것이 고치는 결함이다★ 트리거가 울려도 편익을 모르면 거래가 아니다."""
    out = rebalance_decision(CUR, TGT, portfolio_value=PV, names=NAMES,
                             price_of=_px, adv_of=_adv)
    assert out["decision"] == DECISION_UNDETERMINED
    assert out["reason"]
    assert out["benefit"]["available"] is False
    # 비용은 알 수 있으므로 그것까지 못 낸다고 하지는 않는다.
    assert out["cost"]["available"] is True


def test_with_mu_sigma_a_real_decision_comes_out():
    """★짝★ 전부 undetermined 면 위 테스트도 green 이다."""
    out = _decide()
    assert out["decision"] in (DECISION_TRADE, DECISION_HOLD)
    assert out["benefit"]["available"] is True
    assert out["reason"]


def test_a_trigger_alone_never_produces_a_trade():
    """★트리거는 검토의 시작이지 거래의 근거가 아니다★"""
    trig = detect_triggers(CUR, TGT, as_of="2026-08-23",
                           last_rebalance_date="2026-08-01")
    assert trig["available"] is True and trig["triggers"], "drift 트리거는 울린다"
    out = rebalance_decision(CUR, TGT, portfolio_value=PV, names=NAMES,
                             price_of=_px, adv_of=_adv, triggers=trig)
    assert out["decision"] == DECISION_UNDETERMINED
    assert "거래를 권하지 않습니다" in out["note"]


def test_the_dead_module_is_actually_called():
    """★341줄 호출자 0 이던 모듈을 실제로 태운다★ (감사가 지목한 그 파일)"""
    trig = detect_triggers(CUR, TGT, as_of="2026-08-23",
                           last_rebalance_date="2026-08-01")
    assert "drift" in trig["triggers"]
    assert trig["drift_pct"] == pytest.approx(30.0), "퍼센트→소수 변환이 맞는지"
    assert "거래 근거가 아닙니다" in trig["note"]


def test_a_broken_trigger_engine_does_not_kill_the_decision(monkeypatch):
    class _Boom:
        def __init__(self, *a, **kw):
            raise RuntimeError("트리거 불가")
    monkeypatch.setattr("src.engine.portfolio_rebalancer.PortfolioRebalancer", _Boom)
    trig = detect_triggers(CUR, TGT)
    assert trig["available"] is False and trig["reason"]


# ── 2. ★밴드가 고정이 아니다★ ─────────────────────────────────────────────
def test_the_band_responds_to_position_size():
    """★σ² 형태로 짰을 때 어떤 포지션에서도 20%p(상한 포화)가 나왔다★

    이름만 동적이고 실제로는 고정 밴드였다. 밴드는 0%·100% 근처에서 좁고
    중간에서 넓어야 한다.
    """
    widths = {w: dynamic_band(cost_pct=0.0785, target_weight_pct=w)["half_width_pct"]
              for w in (10.0, 30.0, 50.0, 70.0, 90.0)}
    assert widths[50.0] > widths[30.0] > widths[10.0], widths
    assert widths[50.0] > widths[70.0] > widths[90.0], widths
    assert widths[10.0] == pytest.approx(widths[90.0]), "대칭이어야 한다"
    assert len(set(widths.values())) > 1, "전부 같으면 고정 밴드다"


def test_the_band_scales_with_the_cube_root_of_cost():
    """비용 8배 → 밴드 2배. 세제곱근 비례가 실제로 성립하는지."""
    a = dynamic_band(cost_pct=0.05, target_weight_pct=50.0)["half_width_pct"]
    b = dynamic_band(cost_pct=0.40, target_weight_pct=50.0)["half_width_pct"]
    assert b == pytest.approx(a * 2.0, rel=0.02), (a, b)


def test_the_band_is_not_a_fixed_five_percent():
    """★Brief §10 이 명시적으로 금지한 것★"""
    got = {dynamic_band(cost_pct=c, target_weight_pct=w)["half_width_pct"]
           for c in (0.02, 0.1, 0.5) for w in (20.0, 50.0, 80.0)}
    assert 5.0 not in got or len(got) > 1
    assert len(got) >= 6, f"밴드가 입력에 반응하지 않는다: {got}"


def test_uncertainty_and_illiquidity_widen_the_band():
    base = dynamic_band(cost_pct=0.1, target_weight_pct=50.0)["half_width_pct"]
    unc = dynamic_band(cost_pct=0.1, target_weight_pct=50.0,
                       uncertainty=0.5)["half_width_pct"]
    illq = dynamic_band(cost_pct=0.1, target_weight_pct=50.0,
                        participation=0.5)["half_width_pct"]
    assert unc > base and illq > base


def test_the_band_reports_when_it_was_clamped():
    """★조용히 자르지 않는다★ 잘랐으면 밴드가 입력에 반응한 것처럼 보이면 안 된다."""
    tiny = dynamic_band(cost_pct=1e-9, target_weight_pct=50.0)
    assert tiny["clamped"] is True and tiny["clamp_reason"]
    normal = dynamic_band(cost_pct=0.0785, target_weight_pct=50.0)
    assert normal["clamped"] is False and normal["clamp_reason"] is None


def test_the_band_yields_a_target_range_not_a_point():
    """★Brief §9 — "SPY target 30%, range 25~34%"★"""
    b = dynamic_band(cost_pct=0.0785, target_weight_pct=30.0)
    assert b["low_pct"] < 30.0 < b["high_pct"]
    assert b["high_pct"] - b["low_pct"] == pytest.approx(2 * b["half_width_pct"], abs=1e-6)


def test_a_weight_outside_zero_to_hundred_is_refused():
    assert dynamic_band(cost_pct=0.1, target_weight_pct=140.0)["available"] is False
    assert dynamic_band(cost_pct=0.1, target_weight_pct=-5.0)["available"] is False


def test_a_negative_cost_is_refused_rather_than_cube_rooted():
    """★수치 안전★ 세제곱근에 음수가 들어가면 안 된다(CLAUDE.md)."""
    assert dynamic_band(cost_pct=-1.0, target_weight_pct=50.0)["available"] is False


def test_bands_are_per_asset_in_the_decision():
    out = _decide()
    by = out["band"]["by_asset"]
    assert set(by) == set(NAMES)
    assert by["005930"]["inputs"]["target_weight_pct"] == 70.0
    assert by["000660"]["inputs"]["target_weight_pct"] == 30.0


def test_everything_inside_its_band_is_a_hold():
    out = _decide(cur={"005930": 70.0, "000660": 30.0},
                  tgt={"005930": 70.2, "000660": 29.8})
    assert out["decision"] == DECISION_HOLD
    assert "밴드 안" in out["reason"]
    assert out["band"]["outside"] == []


# ── 3. ★편익 대 비용★ ─────────────────────────────────────────────────────
def test_the_benefit_is_scaled_to_a_stated_horizon():
    """★연율과 일회성을 그냥 비교하지 않는다★ 가정을 숨기면 기간을 골라
    어떤 거래든 정당화할 수 있다."""
    g = expected_utility_gain(CUR, TGT, names=NAMES, mu=MU, sigma=SIGMA,
                              horizon_days=63)
    assert g["available"] is True
    assert g["horizon_days"] == 63
    assert "연율" in g["note"] and "일회성" in g["note"]
    # 기간이 4배면 편익도 4배 — 환산이 실제로 일어난다.
    g4 = expected_utility_gain(CUR, TGT, names=NAMES, mu=MU, sigma=SIGMA,
                               horizon_days=252)
    # 4자리 반올림 잔차(≈1e-4)보다 큰 허용오차 — 재는 것은 4배 관계다.
    assert g4["gain_pct"] == pytest.approx(g["gain_pct"] * 4, abs=1e-3)


def test_a_longer_horizon_can_flip_hold_into_trade():
    """같은 거래가 기간 가정에 따라 갈린다 — 그래서 가정을 드러내야 한다."""
    short = _decide(horizon_days=5)
    long = _decide(horizon_days=252)
    assert short["decision"] == DECISION_HOLD
    assert long["decision"] == DECISION_TRADE
    assert long["benefit"]["gain_pct"] > short["benefit"]["gain_pct"]


def test_hysteresis_actually_raises_the_bar():
    """★히스테리시스가 없으면 비용과 편익이 같을 때도 거래해 왕복이 생긴다★"""
    lo = _decide(horizon_days=252, hysteresis_mult=0.0)
    hi = _decide(horizon_days=252, hysteresis_mult=50.0)
    assert lo["threshold_pct"] < hi["threshold_pct"]
    assert lo["decision"] == DECISION_TRADE
    assert hi["decision"] == DECISION_HOLD, "문턱을 크게 올리면 거래하지 않는다"


def test_the_cost_comes_from_the_existing_execution_engine(monkeypatch):
    """★비용 산수를 두 곳에 두지 않는다★ `build_plan` 을 실제로 부른다."""
    seen = {}
    import src.engine.execution_plan as ep
    real = ep.build_plan

    def _spy(cur, tgt, pv, **kw):
        seen["called"] = True
        return real(cur, tgt, pv, **kw)
    monkeypatch.setattr(ep, "build_plan", _spy)
    out = _decide()
    assert seen.get("called") is True
    assert out["cost"]["cost_krw"] > 0 and out["cost"]["cost_bp"] is not None


def test_an_unpriceable_book_is_undetermined_not_free(monkeypatch):
    """가격을 모르면 비용이 0 이 아니라 **모르는** 것이다."""
    out = rebalance_decision(CUR, TGT, portfolio_value=PV, names=NAMES,
                             mu=MU, sigma=SIGMA,
                             price_of=lambda c: None, adv_of=_adv)
    assert out["cost"]["missing_price"], "가격 없는 종목이 보고된다"
    assert out["decision"] in (DECISION_HOLD, DECISION_TRADE, DECISION_UNDETERMINED)


def test_a_zero_portfolio_is_refused():
    out = rebalance_decision(CUR, TGT, portfolio_value=0.0, names=NAMES,
                             mu=MU, sigma=SIGMA)
    assert out["decision"] == DECISION_UNDETERMINED and out["available"] is False


def test_mismatched_mu_shape_is_a_reason_not_a_crash():
    g = expected_utility_gain(CUR, TGT, names=NAMES, mu=np.array([0.1]), sigma=SIGMA)
    assert g["available"] is False and "모양" in g["reason"]


def test_non_finite_moments_are_refused():
    g = expected_utility_gain(CUR, TGT, names=NAMES,
                              mu=np.array([np.nan, 0.06]), sigma=SIGMA)
    assert g["available"] is False and g["reason"]


# ── 4. ★점진 이동★ ───────────────────────────────────────────────────────
def test_low_confidence_moves_only_part_of_the_way():
    """★확신이 없는 목표로 전량 이동하면 되돌리는 비용을 두 번 낸다★"""
    g = gradual_target({"A": 40.0, "B": 60.0}, {"A": 30.0, "B": 70.0}, 0.4)
    assert g["alpha"] == 0.4
    assert g["weights"]["A"] == pytest.approx(36.0)
    assert g["weights"]["B"] == pytest.approx(64.0)


def test_full_confidence_moves_all_the_way():
    g = gradual_target({"A": 40.0}, {"A": 30.0}, 1.0)
    assert g["weights"]["A"] == pytest.approx(30.0)


def test_a_missing_confidence_says_it_assumed_full_movement():
    """★가정을 숨기지 않는다★ α=1 을 조용히 쓰지 않는다."""
    g = gradual_target({"A": 40.0}, {"A": 30.0}, None)
    assert g["alpha"] == 1.0 and g["reason"]


def test_confidence_is_clamped_into_zero_one():
    assert gradual_target({"A": 40.0}, {"A": 30.0}, 5.0)["alpha"] == 1.0
    assert gradual_target({"A": 40.0}, {"A": 30.0}, -2.0)["alpha"] == 0.0


# ── 5. 효용 ───────────────────────────────────────────────────────────────
def test_utility_penalises_risk():
    w = np.array([0.5, 0.5])
    calm = utility(w, MU, SIGMA * 0.1, DEFAULT_RISK_AVERSION)
    wild = utility(w, MU, SIGMA * 10.0, DEFAULT_RISK_AVERSION)
    assert calm > wild, "같은 μ 라면 위험이 큰 쪽의 효용이 낮다"
