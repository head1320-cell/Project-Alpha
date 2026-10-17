"""참여율 충격 비용 — ★회전율에 비례하는 비용이 관문에 없었다★ (P3)
==============================================================================
설계: `docs/superpowers/specs/2026-08-30-participation-cost-capacity-design.md`

충격 비용은 회전율에 비례하는데 `regime-on` 은 `regime-off` 보다 **4.3배 더
거래한다**(8.5151% vs 1.9823%, 실측). 그런데 `walk_forward` 는 `cost_bps/1e4`
**정액**만 물렸다 — 얼마나 많이 거래하든 같은 요율이다. 즉 ④ 경제적 가치 관문이
재려는 바로 그 우위를 백테스트가 체계적으로 부풀린다. ★관문 자신의 편향★ 이다.

★비트 동일을 자기 자신과 비교해서 확인하지 않는다★ A3-a 에서 물린 것이다
(`build_panel(36)` vs `build_panel(36, scale=1.0)` — 둘 다 같은 분기라 공허했다).
`walk_forward(...)` 와 `walk_forward(..., impact=None)` 도 **같은 분기**라 서로
비교하면 아무것도 못 잡는다. 그래서 여기서는 **대수적 항등식**을 쓴다: 비중 경로는
`R_win` 에서만 나오므로 **비용에 불변**이고, 따라서

    equity(cost) = equity(0) × Π_k (1 − τ_k · bps_k/1e4)

가 정확히 성립해야 한다. 정액 경로에 충격이 몰래 끼면 이 항등식이 깨진다.
호스트가 달라도(OpenBLAS `DYNAMIC_ARCH` 흔들림, `f0c7b10`) 같은 프로세스 안의
두 실행을 비교하므로 안전하다 — 동결 해시보다 이쪽이 옳다.
"""

from __future__ import annotations

import ast
import inspect
import os
import textwrap
from dataclasses import fields

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402

from src.engine.market_impact import ImpactAssumptions, MarketImpactModel  # noqa: E402

PORTFOLIO = 1e11          # 1000억 — 설계 §0 의 실측 규모
MID = 1e10                # 100억 — 참여율이 아직 하루치 ADV 안쪽
TOP = 1e12                # 1조 — 사전등록 격자의 꼭대기
TINY = 1e3                # 1000원 — 참여율이 사실상 0


# ── 픽스처 ────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def panel():
    from scripts.t3_transmission import build_panel
    names, R, dates, points, _beta = build_panel(months=36)
    return names, R, dates, points


def _wf(panel, **kw):
    from src.engine.allocation_backtest import walk_forward
    names, R, dates, _points = panel
    base = {"model": "bl", "rebalance": "M", "min_train": 252, "cost_bps": 10.0}
    return walk_forward(names, R, dates, **{**base, **kw})


def _predicted_multiplier(rebalances, cost_bps: float, *, with_impact: bool) -> float:
    """보고된 회전율·충격으로 재구성한 누적 비용 배수."""
    m = 1.0
    for rb in rebalances:
        tau = float(rb["turnover_pct"]) / 100.0
        bps = float(cost_bps) + (float(rb["impact_bps"]) if with_impact else 0.0)
        m *= (1.0 - tau * bps / 1e4)
    return m


# ── ImpactAssumptions — 가정은 선언해야 한다 ──────────────────────────────
def test_the_portfolio_size_must_be_declared():
    """★기본값을 두지 않는 것이 계약이다★ 충격을 쓰려면 규모를 **말해야** 한다."""
    with pytest.raises(TypeError):
        ImpactAssumptions()                     # type: ignore[call-arg]


def test_the_other_defaults_are_the_conventions_the_repo_already_uses():
    """짝 — 규모만 필수다. 나머지는 `realism_engine` 이 쓰던 관례 그대로."""
    a = ImpactAssumptions(portfolio_krw=PORTFOLIO)
    assert a.adv_krw == 50e9
    assert a.volatility == 0.018
    assert a.alpha == 0.7


@pytest.mark.parametrize("bad", [0.0, -1.0])
def test_a_nonpositive_adv_is_refused_with_a_reason(bad):
    """★침묵 0 금지★ `turnover_based_impact` 는 ADV≤0 이면 조용히 충격 0 을
    돌려준다 — **공짜 거래를 제조한다**. 경계에서 막아 그 경로에 못 가게 한다."""
    with pytest.raises(ValueError) as e:
        ImpactAssumptions(portfolio_krw=PORTFOLIO, adv_krw=bad)
    assert "ADV" in str(e.value) and str(bad) in str(e.value).replace("−", "-")


@pytest.mark.parametrize("bad", [0.0, -1.0])
def test_a_nonpositive_portfolio_is_refused_with_a_reason(bad):
    with pytest.raises(ValueError) as e:
        ImpactAssumptions(portfolio_krw=bad)
    assert str(e.value).strip()


def test_a_valid_adv_actually_charges_something():
    """짝 — 거부가 아니라 **값**이 나와야 한다(항상-거부 구현 배제)."""
    a = ImpactAssumptions(portfolio_krw=PORTFOLIO)
    assert a.impact_bps(0.085, PORTFOLIO)["impact_bps"] > 0


def test_four_times_the_size_doubles_the_impact():
    """★√법칙★ — 이것이 이 비용 모델의 정체다."""
    a = ImpactAssumptions(portfolio_krw=PORTFOLIO)
    one = a.impact_bps(0.05, 1e10)["impact_bps"]
    four = a.impact_bps(0.05, 4e10)["impact_bps"]
    assert four / one == pytest.approx(2.0, rel=1e-3)


def test_the_impact_is_not_linear_in_size():
    """짝 — 4배가 4배면 √이 아니라 정률이다."""
    a = ImpactAssumptions(portfolio_krw=PORTFOLIO)
    one = a.impact_bps(0.05, 1e10)["impact_bps"]
    four = a.impact_bps(0.05, 4e10)["impact_bps"]
    assert four / one < 3.0


def test_zero_turnover_costs_nothing():
    a = ImpactAssumptions(portfolio_krw=PORTFOLIO)
    assert a.impact_bps(0.0, PORTFOLIO)["impact_bps"] == 0.0


def test_positive_turnover_costs_something():
    """짝 — 회전율 0 만 0 이다(항상-0 구현 배제)."""
    a = ImpactAssumptions(portfolio_krw=PORTFOLIO)
    assert a.impact_bps(0.02, PORTFOLIO)["impact_bps"] > 0.0


def test_more_turnover_costs_more():
    a = ImpactAssumptions(portfolio_krw=PORTFOLIO)
    lo = a.impact_bps(0.0198, PORTFOLIO)["impact_bps"]
    hi = a.impact_bps(0.0852, PORTFOLIO)["impact_bps"]
    assert hi > lo, "회전율이 4.3배인데 더 비싸지 않다 — 편향이 그대로다"


def test_the_assumptions_travel_with_the_output():
    """★P1·P2′ 패턴★ 숫자는 그것을 만든 관례를 달고 다닌다."""
    c = ImpactAssumptions(portfolio_krw=PORTFOLIO).as_convention()
    assert c["portfolio_krw"] == PORTFOLIO
    assert c["adv_krw"] == 50e9
    assert c["volatility"] == 0.018
    assert c["alpha"] == 0.7
    assert c["law"] == "almgren_chriss_sqrt"
    # ★해상도를 신고한다★ 효과(8.5bp)의 1/850 이라 통계를 눈멀게 하지 않는다는
    # 논증이 성립하려면 그 수가 리포트에 있어야 한다(P1 의 `round(sharpe,2)` 교훈).
    assert c["impact_bps_resolution"] == 0.01


def test_the_square_root_law_is_not_reimplemented_here():
    """★변이: 인라인 재구현★ 저장소가 이미 가진 모델을 부르지 않고 베끼면
    두 벌이 갈라진다 — P1(지표)·P2′(BL)에서 두 번 물린 형태다."""
    src = inspect.getsource(ImpactAssumptions.impact_bps)
    tree = ast.parse(textwrap.dedent(src))
    called = {n.func.attr for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert "turnover_based_impact" in called
    assert "sqrt" not in src, "√을 여기서 다시 계산하고 있다 — 위임해야 한다"


def test_it_delegates_to_the_model_the_rest_of_the_repo_uses():
    """짝 — 이름만 같은 다른 함수를 부르지 않았는지 값으로 확인한다."""
    a = ImpactAssumptions(portfolio_krw=PORTFOLIO, adv_krw=7e10,
                          volatility=0.021, alpha=0.55)
    mine = a.impact_bps(0.031, 3.3e10)
    theirs = MarketImpactModel.turnover_based_impact(
        turnover_pct=3.1, portfolio_equity=3.3e10, avg_adv_krw=7e10,
        avg_volatility=0.021, weighted_alpha=0.55)
    assert mine["impact_bps"] == theirs["impact_bps"]


# ── walk_forward — 기본 경로는 한 자도 바뀌지 않는다 ──────────────────────
def test_without_impact_the_recursion_is_flat_cost_only(panel):
    """★자기 자신과 비교하지 않는다★ 비중 경로는 비용에 불변이므로 두 비용
    수준 사이의 비율이 정액 공식과 **정확히** 맞아야 한다. 기본 경로에 충격이
    몰래 끼면 이 항등식이 깨진다."""
    free = _wf(panel, cost_bps=0.0)
    paid = _wf(panel, cost_bps=10.0)
    assert [r["date"] for r in free["rebalances"]] == \
           [r["date"] for r in paid["rebalances"]], "비중 경로가 비용에 흔들렸다"
    predicted = _predicted_multiplier(paid["rebalances"], 10.0, with_impact=False)
    ratio = paid["equity_curve"][-1] / free["equity_curve"][-1]
    assert ratio == pytest.approx(predicted, rel=1e-4)


def test_with_impact_the_recursion_pays_the_reported_impact(panel):
    """짝 — 충격을 주면 **보고된 충격만큼** 정확히 더 낸다."""
    free = _wf(panel, cost_bps=0.0)
    paid = _wf(panel, cost_bps=10.0,
               impact=ImpactAssumptions(portfolio_krw=PORTFOLIO))
    predicted = _predicted_multiplier(paid["rebalances"], 10.0, with_impact=True)
    ratio = paid["equity_curve"][-1] / free["equity_curve"][-1]
    assert ratio == pytest.approx(predicted, rel=1e-4)
    # 그리고 정액 예측과는 뚜렷하게 다르다 — 허용오차 안에 숨지 않는다
    flat = _predicted_multiplier(paid["rebalances"], 10.0, with_impact=False)
    assert abs(ratio - flat) > 1e-3


def test_the_default_path_charges_no_impact_at_all(panel):
    """★리포트가 아니라 값으로 잡는다.★

    기본 경로가 몰래 어떤 규모를 물어도 리포트는 여전히 `applied: False` 라고
    말한다 — 재귀와 보고가 갈라지는 변이는 보고만 봐서는 못 잡는다. 그리고 두
    **비용 수준** 사이의 비율로도 못 잡는다: 양쪽에 똑같이 낀 충격은 비율에서
    거의 상쇄된다(변이 배터리에서 실제로 확인했다). 그래서 정액 항을 0 으로
    없애고, 규모를 준 실행과의 비율이 **보고된 충격만으로** 설명되는지 본다.
    """
    none = _wf(panel, cost_bps=0.0)
    sized = _wf(panel, cost_bps=0.0,
                impact=ImpactAssumptions(portfolio_krw=PORTFOLIO))
    predicted = _predicted_multiplier(sized["rebalances"], 0.0, with_impact=True)
    assert sized["equity_curve"][-1] / none["equity_curve"][-1] == pytest.approx(
        predicted, rel=1e-4)
    assert predicted < 0.999, "충격이 사실상 0 이면 이 테스트는 공허하다"


def test_a_size_that_cannot_move_the_market_costs_essentially_nothing(panel):
    """★짝: 작은 주문은 정액과 사실상 같다★ — 항상-비싸지는 구현을 배제한다.

    ★"정확히 같다" 가 아니고, 그 차이가 발견이다.★ 공용
    `turnover_based_impact` 는 `round(impact_bps, 2)` 라 **0 이 아닌 모든 주문에
    0.01bp 바닥**이 생긴다. 1000원 포트폴리오의 참값은 0.0004bp 인데 가장 큰
    리밸런싱 한 번이 0.01bp 로 올려 붙는다(실측). 규모를 재는 구간(10억~1조,
    2.6~80bp)에서는 효과의 1/250 이하라 무해하지만 **모르는 채로 두지 않는다** —
    그래서 `as_convention()` 이 해상도를 신고한다. 공용 함수 자체는 고치지
    않는다: `realism_engine`·`instrument_selector` 산출이 함께 바뀐다.
    """
    flat = _wf(panel, cost_bps=10.0)
    tiny = _wf(panel, cost_bps=10.0, impact=ImpactAssumptions(portfolio_krw=TINY))
    assert tiny["impact"]["max_bps"] <= 0.01     # 해상도 바닥이지 그 이상이 아니다
    assert tiny["impact"]["total_cost_pct"] < 1e-3
    assert all(round(abs(a - b), 6) <= 1e-5
               for a, b in zip(tiny["equity_curve"], flat["equity_curve"]))


def test_impact_none_says_why_instead_of_going_quiet(panel):
    """★`{}` 나 사유 없는 빈 값 금지★ (CLAUDE.md §4)."""
    blk = _wf(panel)["impact"]
    assert blk["applied"] is False
    assert blk["convention"] is None
    assert blk["reason"] and blk["reason"].strip()


def test_impact_none_charges_zero_on_every_rebalance(panel):
    out = _wf(panel)
    assert out["rebalances"], "리밸런싱이 없으면 이 테스트는 공허하다"
    assert all(r["impact_bps"] == 0.0 for r in out["rebalances"])


def test_an_applied_impact_reports_its_assumptions_and_what_it_cost(panel):
    blk = _wf(panel, impact=ImpactAssumptions(portfolio_krw=MID))["impact"]
    assert blk["applied"] is True
    assert blk["convention"]["portfolio_krw"] == MID
    assert blk["mean_bps"] > 0 and blk["max_bps"] >= blk["mean_bps"]
    assert 0.0 < blk["max_participation"] < 1.0
    assert blk["beyond_model_range"] is False
    assert blk["total_cost_pct"] > 0


def test_exactly_one_day_of_volume_is_not_yet_beyond_the_range(panel):
    """짝 — 경계는 `> 1.0` 이지 `>= 1.0` 이 아니다.

    ★1000억에서 가장 큰 리밸런싱이 참여율 정확히 1.0 이다★(회전율 50.0% ×
    1000억 ÷ ADV 500억, 실측). 하루치를 **다 쓰는 것**과 **넘는 것**은 다르다.
    """
    blk = _wf(panel, impact=ImpactAssumptions(portfolio_krw=PORTFOLIO))["impact"]
    assert blk["max_participation"] == 1.0
    assert blk["beyond_model_range"] is False


def test_an_order_larger_than_a_day_of_volume_is_flagged_not_extrapolated(panel):
    """★검량 범위 밖을 침묵하며 외삽하지 않는다★ 하루치 ADV 를 넘는 주문에
    √법칙을 그대로 밀어 놓고 아무 말 없으면 그것이 조용한 제조다.

    ★사전등록 격자의 꼭대기(1조)가 이미 범위 밖이다★ — 최대 참여율 10.0(실측).
    용량 곡선을 읽을 때 이 사실이 함께 실려야 한다."""
    blk = _wf(panel, impact=ImpactAssumptions(portfolio_krw=TOP))["impact"]
    assert blk["max_participation"] > 1.0
    assert blk["beyond_model_range"] is True
    assert blk["reason"] and blk["reason"].strip()


def test_the_notional_follows_the_equity_curve(panel):
    """★고정 notional 이면 용량 곡선이 틀린다★ 수익이 나면 충격도 커진다."""
    seen: list[tuple[float, float]] = []
    out = _wf(panel, impact=_spy(ImpactAssumptions(portfolio_krw=PORTFOLIO), seen))
    assert len(seen) == len(out["rebalances"])
    notionals = [n for _t, n in seen]
    assert notionals[0] == pytest.approx(PORTFOLIO, rel=1e-12)
    assert len(set(round(n, 3) for n in notionals)) > 1, "notional 이 고정돼 있다"
    for k, rb in enumerate(out["rebalances"][1:], start=1):
        i = out["dates"].index(rb["date"])
        assert notionals[k] / PORTFOLIO == pytest.approx(
            out["equity_curve"][i - 1], rel=1e-4)


def _spy(assumptions, sink):
    """실제 구현을 그대로 쓰되 인자만 관찰한다 — mock 이 아니라 관찰이다."""
    class _Spy(type(assumptions)):
        def impact_bps(self, turnover, notional_krw):
            sink.append((float(turnover), float(notional_krw)))
            return super().impact_bps(turnover, notional_krw)
    return _Spy(**{f.name: getattr(assumptions, f.name)
                   for f in fields(assumptions)})


def test_the_arm_that_trades_more_pays_more(panel):
    """★이것이 P3 의 주장 자체다★ 정액은 회전율 4.3배를 같은 요율로 매겼다."""
    names, R, dates, points = panel
    a = ImpactAssumptions(portfolio_krw=PORTFOLIO)
    off = _wf(panel, impact=a)
    on = _wf(panel, impact=a, regime={"points": points, "weighting": "hard"})
    assert on["turnover_avg_pct"] > off["turnover_avg_pct"]
    assert on["impact"]["mean_bps"] > off["impact"]["mean_bps"]


# ══════════════════════════════════════════════════════════════════════════
# ★교정치가 출처를 달고 다닌다★ (P9 ②)
# ══════════════════════════════════════════════════════════════════════════
#
# `ASSET_CLASS_TIERS` 의 α(0.35~3.20)와 시총 임계값은 하드코딩이고 어디서 왔는지
# 아무 데도 없었다. 시장충격이 쓰는 수다. CLAUDE.md §4: "경제 가정을 파이프라인을
# 돌리려고 지어내지 마세요." ★수치는 한 글자도 안 바꾼다 — 출처만 적는다.★

def test_every_tier_declares_where_its_alpha_came_from():
    from src.engine.market_impact import ASSET_CLASS_TIERS, TIER_PROVENANCE
    assert set(TIER_PROVENANCE) == set(ASSET_CLASS_TIERS), \
        "티어와 출처 표가 어긋난다 — 하나가 빠지면 그 α 는 출처 없이 쓰인다"
    for tier, prov in TIER_PROVENANCE.items():
        assert prov["alpha"] in ("measured", "literature", "unmeasured"), (tier, prov)
        assert prov["reason"], f"{tier} 가 사유 없이 등급만 적었다"


def test_no_tier_claims_to_be_measured_without_evidence():
    """★거짓 승격을 막는다★ (변이 W6)

    `"measured"` 는 저장소에 근거가 있을 때만 쓴다. 지금은 어느 티어에도 그
    근거가 없으므로 하나도 `measured` 여서는 안 된다 — 언젠가 재면 그때
    올리면서 이 테스트도 함께 고치는 것이 맞다.
    """
    from src.engine.market_impact import TIER_PROVENANCE
    claimed = [t for t, p in TIER_PROVENANCE.items() if p["alpha"] == "measured"]
    assert claimed == [], (
        f"근거 없이 measured 라고 적힌 티어: {claimed} — 저장소에 그 측정이 없다")


def test_the_thresholds_declare_that_they_are_nominal_krw():
    """★명목 KRW 는 과거에 소급하면 티어가 밀린다★ 그 사실을 표가 말해야 한다."""
    from src.engine.market_impact import TIER_PROVENANCE
    for tier, prov in TIER_PROVENANCE.items():
        assert prov["threshold_basis"] == "nominal_krw", (tier, prov)


def test_a_known_class_says_its_alpha_came_from_the_tier_table():
    from src.engine.market_impact import MarketImpactModel
    est = MarketImpactModel().estimate_impact(
        order_value_krw=5e8, adv_krw=1e11, daily_volatility=0.018,
        asset_class="kospi_mid")
    assert est.alpha_source == "tier_table"
    assert est.alpha == 0.90


def test_an_unknown_class_does_not_pass_its_fallback_off_as_calibration():
    """★침묵 폴백 제거★ (변이 W7)

    모르는 자산군이면 `alpha_map.get(asset_class, (0, 1.0))[1]` 이 조용히 α=1.0
    을 준다 — 표에 없는 수인데 교정치처럼 보인다. ★수치 동작은 유지하되★
    그것이 측정이 아니라 폴백임을 산출이 말해야 한다.
    """
    from src.engine.market_impact import MarketImpactModel
    est = MarketImpactModel().estimate_impact(
        order_value_krw=5e8, adv_krw=1e11, daily_volatility=0.018,
        asset_class="존재하지않는군")
    assert est.alpha == 1.0, "수치 동작이 바뀌었다 — 이 슬라이스는 라벨만 늘린다"
    assert est.alpha_source == "fallback_unknown_class"


def test_an_uncomputable_estimate_does_not_call_its_zero_a_calibration():
    """`adv<=0` 이면 α=0 으로 돌아온다 — 그것은 '충격 없음' 이 아니라 **미상**이다."""
    from src.engine.market_impact import MarketImpactModel
    est = MarketImpactModel().estimate_impact(
        order_value_krw=5e8, adv_krw=0, daily_volatility=0.018,
        asset_class="kospi_mid")
    assert est.alpha == 0
    assert est.alpha_source == "unavailable"


def test_a_custom_alpha_for_an_unknown_tier_is_not_silently_dropped():
    """★조용히 무시하지 않는다★ 오타 하나가 아무 말 없이 사라지면 안 된다."""
    from src.engine.market_impact import MarketImpactModel
    m = MarketImpactModel(custom_alpha={"kospi_mid": 0.5, "오타티어": 9.9})
    assert m.alpha_map["kospi_mid"][1] == 0.5
    assert m.ignored_custom_alpha == ("오타티어",)


def test_the_assumptions_carry_the_alpha_provenance():
    """★가정이 산출과 함께 다닌다★ (P3 의 `as_convention` 관용구 재사용).

    ★등급을 **집합 안에 있다**로만 걸면 너무 약하다★ — 변이 W15 가 그것으로
    살아남았다(`"measured"` 도 집합 안에 있다). 이 α 는 티어 표의 포트폴리오
    가중 대표값이므로 **표보다 높은 등급을 주장할 수 없다**: 모든 티어가
    미측정인데 대표값만 측정일 수는 없다.
    """
    from src.engine.market_impact import TIER_PROVENANCE, ImpactAssumptions
    conv = ImpactAssumptions(portfolio_krw=1e10).as_convention()
    assert conv["alpha_provenance"] in ("measured", "literature", "unmeasured")
    assert conv["alpha_provenance_reason"]

    rank = {"unmeasured": 0, "literature": 1, "measured": 2}
    best_tier = max(rank[p["alpha"]] for p in TIER_PROVENANCE.values())
    assert rank[conv["alpha_provenance"]] <= best_tier, (
        f"대표 α 가 {conv['alpha_provenance']} 라는데 표의 최고 등급은 "
        f"{best_tier} 다 — 근거 없는 승격이다")
