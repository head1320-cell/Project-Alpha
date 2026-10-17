"""기업 분석 모델 — 엔진(순수 함수) 단위 테스트 (BL3 W3b-C1)
==============================================================================
손으로 푼 수로 못 박는다. 공통 규칙: 가정은 가정이라 적고(`inputs[].basis`), 확률·가중은 조용히 정규화하지 않고,
적자·음수 입력에서 분수·나눗셈이 터지지 않게 사유 있는 `available: false` 로 멈춘다.
"""
from __future__ import annotations

import math

import pytest

from src.data.dart_client import FinancialStatement
from src.engine.valuation import practice_models as pm
from src.engine.valuation.valuation_models import ValuationParams, compute_dcf

P = ValuationParams(risk_free_rate=0.03, market_premium=0.06, beta=1.0, terminal_growth_rate=0.02, projection_years=10)


def _fs(year="2024", rev=1000.0, op=100.0, ni=80.0, ta=1000.0, tl=400.0, te=600.0, ca=500.0, cl=200.0,
        ocf=120.0, capex=40.0, shares=10, dps=2.0, eps=None, bps=None):
    return FinancialStatement(corp_code="x", corp_name="테스트", bsns_year=year, reprt_code="11011", revenue=rev,
                              operating_profit=op, net_income=ni, total_assets=ta, total_liabilities=tl,
                              total_equity=te, current_assets=ca, current_liabilities=cl, operating_cf=ocf,
                              capex=capex, shares_outstanding=shares, dps=dps, eps=eps, bps=bps)


def _basis(out, key):
    return next(i["basis"] for i in out["inputs"] if i["key"] == key)


# ══ WACC — DCF 엔진과 같은 식(두 벌이 갈라지지 않게 대조) ═══════════════════

def test_wacc_by_hand():
    # ke = 0.03 + 1×0.06 = 0.09 · kd = 0.045 · E/V = 0.6 · D/V = 0.4 · t = 0.22
    assert pm.dcf_wacc(_fs(), P) == pytest.approx(0.09 * 0.6 + 0.045 * 0.78 * 0.4)


@pytest.mark.parametrize("te,tl", [(600, 400), (100, 900), (900, 50), (1, 0)])
def test_wacc_equals_what_the_dcf_engine_reports(te, tl):
    fs = _fs(te=te, tl=tl)
    reported = compute_dcf(fs, P).assumptions["wacc_pct"]
    assert round(pm.dcf_wacc(fs, P) * 100, 2) == reported


# ══ EVA · 가치 동인 ═══════════════════════════════════════════════════════════

def test_eva_by_hand():
    out = pm.eva_analysis([_fs()], _fs(), P, fade_years=5)
    assert out["available"] is True
    w = 0.09 * 0.6 + 0.045 * 0.78 * 0.4
    row = out["years"][-1]
    assert row["nopat"] == pytest.approx(78.0)
    assert row["invested_capital"] == pytest.approx(800.0)
    assert row["eva"] == pytest.approx(78.0 - w * 800.0)
    assert row["roic"] == pytest.approx(78.0 / 800.0)
    # 소멸: EVA_t = EVA0 × (1 − t/(N+1)), t=1..5, WACC 로 할인
    eva0 = 78.0 - w * 800.0
    pv = sum(eva0 * (1 - t / 6) / (1 + w) ** t for t in range(1, 6))
    assert out["valuation"]["pv_eva"] == pytest.approx(pv)
    assert out["valuation"]["firm_value"] == pytest.approx(800.0 + pv)
    assert out["valuation"]["per_share"] == pytest.approx((800.0 + pv - 400.0) / 10)
    assert _basis(out, "invested_capital") == "근사" and _basis(out, "fade_years") == "가정"


def test_value_driver_by_hand_and_growth_that_destroys_value():
    w = 0.09 * 0.6 + 0.045 * 0.78 * 0.4
    out = pm.eva_analysis([_fs()], _fs(), P, fade_years=5, g=0.02, ronic=0.10)
    vd = out["value_driver"]
    assert vd["available"] is True
    assert vd["value"] == pytest.approx(78 * 1.02 * (1 - 0.02 / 0.10) / (w - 0.02))
    assert vd["growth_creates_value"] is True
    # 짝: RONIC < WACC 면 성장이 가치를 깎는다
    low = pm.eva_analysis([_fs()], _fs(), P, fade_years=5, g=0.02, ronic=0.03)["value_driver"]
    assert low["growth_creates_value"] is False


@pytest.mark.parametrize("kw,why", [({"g": 0.2, "ronic": 0.1}, "성장률"), ({"g": 0.02, "ronic": 0.0}, "RONIC"),
                                    ({"g": 0.02, "ronic": -0.1}, "RONIC")])
def test_value_driver_refuses_impossible_inputs(kw, why):
    vd = pm.eva_analysis([_fs()], _fs(), P, fade_years=5, **kw)["value_driver"]
    assert vd["available"] is False and why in vd["reason"]


def test_a_loss_making_company_has_no_value_driver_but_still_reports_eva():
    loss = _fs(op=-50)
    out = pm.eva_analysis([loss], loss, P, fade_years=5, g=0.02, ronic=0.1)
    assert out["years"][-1]["eva"] < 0
    assert out["value_driver"]["available"] is False and "적자" in out["value_driver"]["reason"]


def test_eva_without_total_assets_says_so():
    fs = _fs(ta=None, cl=None)
    out = pm.eva_analysis([fs], fs, P, fade_years=5)
    assert out["available"] is False and "투하자본" in out["reason"]


def test_eva_without_current_liabilities_uses_total_assets_and_says_which():
    """유동부채를 모르면 총자산을 투하자본으로 — EVA 를 낮게 잡는 쪽의 근사이고, 그 사실을 행마다 적는다."""
    fs = _fs(cl=None)
    out = pm.eva_analysis([fs], fs, P, fade_years=5)
    row = out["years"][-1]
    assert row["invested_capital"] == pytest.approx(1000.0) and "유동부채" in row["ic_method"]
    # 짝: 유동부채가 있으면 빼고, 방법 이름도 다르다
    row2 = pm.eva_analysis([_fs()], _fs(), P, fade_years=5)["years"][-1]
    assert row2["invested_capital"] == pytest.approx(800.0) and row2["ic_method"] != row["ic_method"]


# ══ 가치의 층 (Greenwald 3층 + 확률 가중) ═════════════════════════════════════

def test_value_layers_by_hand():
    hist = [_fs("2022", rev=800, op=40), _fs("2023", rev=900, op=90), _fs("2024", rev=1000, op=100)]
    w = 0.09 * 0.6 + 0.045 * 0.78 * 0.4
    out = pm.value_layers(hist, hist[-1], P, full_value_per_share=120.0, weights=(0.2, 0.3, 0.5))
    assert out["available"] is True
    margin = (40 / 800 + 90 / 900 + 100 / 1000) / 3
    epv_ps = (margin * 1000 * 0.78 / w - 400) / 10
    L = {x["key"]: x for x in out["layers"]}
    assert L["asset"]["per_share"] == pytest.approx(60.0)            # 자본 600 / 10주
    assert L["epv"]["per_share"] == pytest.approx(epv_ps)
    assert L["growth"]["per_share"] == pytest.approx(120.0 - epv_ps)
    assert out["weighted_per_share"] == pytest.approx(0.2 * 60 + 0.3 * epv_ps + 0.5 * 120)
    assert out["normalization"]["years"] == 3
    assert _basis(out, "asset") == "근사"


def test_value_layers_refuse_weights_that_do_not_sum_to_one():
    out = pm.value_layers([_fs()], _fs(), P, full_value_per_share=120.0, weights=(0.5, 0.5, 0.5))
    assert out["available"] is False and "합" in out["reason"]
    # 짝: 합이 1 이면 계산한다(조용히 나눠 맞추지 않았다는 것을 이 짝이 보인다)
    assert pm.value_layers([_fs()], _fs(), P, full_value_per_share=120.0, weights=(0.2, 0.3, 0.5))["available"]


def test_negative_normalized_earnings_leave_the_epv_layer_unmeasured():
    hist = [_fs("2023", op=-30), _fs("2024", op=-10)]
    out = pm.value_layers(hist, hist[-1], P, full_value_per_share=120.0, weights=(1.0, 0.0, 0.0))
    L = {x["key"]: x for x in out["layers"]}
    assert L["epv"]["per_share"] is None and "적자" in L["epv"]["reason"]
    # 가중이 EPV 에 걸리지 않으면 계산은 된다(자산층만)
    assert out["weighted_per_share"] == pytest.approx(60.0)
    # 짝: EPV 에 가중을 두면 미상을 0 으로 채우지 않고 멈춘다
    bad = pm.value_layers(hist, hist[-1], P, full_value_per_share=120.0, weights=(0.5, 0.5, 0.0))
    assert bad["weighted_per_share"] is None and "EPV" in bad["weighted_reason"]


# ══ 배수 · PEG · 정당 배수 ════════════════════════════════════════════════════

def test_multiples_by_hand():
    fs = _fs(ni=80, te=600, shares=10, dps=2.0)            # EPS 8 · BPS 60 · ROE 13.33% · 배당성향 25%
    out = pm.multiples_matrix(fs, price=100.0, params=P, eps_growth_pct=10.0,
                              growth_axis=[5, 10, 20], peg_axis=[0.5, 1.0, 1.5])
    assert out["available"] is True
    assert out["eps"] == pytest.approx(8.0) and out["per"] == pytest.approx(12.5)
    assert out["peg"] == pytest.approx(1.25)
    assert out["matrix"]["prices"][1][1] == pytest.approx(8.0 * 1.0 * 10)   # 성장 10% × PEG 1.0
    roe, ke, g = 80 / 600, 0.09, 0.02
    j = out["justified"]
    assert j["pbr"] == pytest.approx((roe - g) / (ke - g))
    assert j["pbr_price"] == pytest.approx((roe - g) / (ke - g) * 60)
    assert j["per"] == pytest.approx(0.25 * 1.02 / (ke - g))
    assert _basis(out, "eps_growth") == "관측"


def test_multiples_refuse_a_loss_making_company():
    out = pm.multiples_matrix(_fs(ni=-10), price=100.0, params=P, eps_growth_pct=10.0,
                              growth_axis=[10], peg_axis=[1.0])
    assert out["available"] is False and "EPS" in out["reason"]


def test_peg_needs_positive_growth_and_justified_needs_ke_above_g():
    out = pm.multiples_matrix(_fs(), price=100.0, params=P, eps_growth_pct=-5.0, growth_axis=[10], peg_axis=[1.0])
    assert out["peg"] is None and "성장" in out["peg_reason"]
    hot = ValuationParams(risk_free_rate=0.0, market_premium=0.01, beta=1.0, terminal_growth_rate=0.02)
    out = pm.multiples_matrix(_fs(), price=100.0, params=hot, eps_growth_pct=10.0, growth_axis=[10], peg_axis=[1.0])
    assert out["justified"]["pbr"] is None and "Ke" in out["justified"]["reason"]


def test_an_unobserved_growth_rate_is_labelled_as_missing_not_zero():
    out = pm.multiples_matrix(_fs(), price=100.0, params=P, eps_growth_pct=None, growth_axis=[10], peg_axis=[1.0])
    assert out["peg"] is None and _basis(out, "eps_growth") == "미상"


# ══ 영업 동인 몬테카를로 ═════════════════════════════════════════════════════

def _hist():
    return [_fs("2021", rev=800, op=72, capex=30), _fs("2022", rev=880, op=88, capex=33),
            _fs("2023", rev=968, op=97, capex=36), _fs("2024", rev=1064.8, op=106.5, capex=40)]


def test_driver_mc_centers_come_from_history_and_are_labelled_observed():
    out = pm.driver_monte_carlo(_hist(), _hist()[-1], P, sigma_growth=0.03, sigma_margin=0.02, sigma_reinvest=0.01,
                                years=5, n=500, seed=7, price=100.0)
    assert out["available"] is True
    c = out["centers"]
    assert c["growth"] == pytest.approx((1064.8 / 800) ** (1 / 3) - 1)
    assert c["margin"] == pytest.approx((72 / 800 + 88 / 880 + 97 / 968 + 106.5 / 1064.8) / 4)
    # 재투자율 = (NOPAT − (영업CF − CAPEX)) / 매출 — 감가상각을 영업CF 가 품고 있다(근사)
    h = _hist()
    assert c["reinvest"] == pytest.approx(sum((f.operating_profit * 0.78 - (120 - f.capex)) / f.revenue for f in h) / 4)
    assert _basis(out, "growth") == "관측" and _basis(out, "sigma_growth") == "가정"
    assert _basis(out, "reinvest_rate") == "근사"


def test_driver_mc_is_reproducible_with_the_seed_and_moves_without_it():
    a = pm.driver_monte_carlo(_hist(), _hist()[-1], P, sigma_growth=0.03, sigma_margin=0.02, sigma_reinvest=0.01,
                              years=5, n=500, seed=7, price=100.0)
    b = pm.driver_monte_carlo(_hist(), _hist()[-1], P, sigma_growth=0.03, sigma_margin=0.02, sigma_reinvest=0.01,
                              years=5, n=500, seed=7, price=100.0)
    c = pm.driver_monte_carlo(_hist(), _hist()[-1], P, sigma_growth=0.03, sigma_margin=0.02, sigma_reinvest=0.01,
                              years=5, n=500, seed=8, price=100.0)
    assert a["quantiles"] == b["quantiles"] and a["quantiles"] != c["quantiles"]


def test_driver_mc_with_zero_spread_collapses_to_the_deterministic_value():
    """σ=0 이면 모든 경로가 같다 — 분포가 한 점이어야 한다(무작위가 값을 만들지 않는다는 짝)."""
    out = pm.driver_monte_carlo(_hist(), _hist()[-1], P, sigma_growth=0.0, sigma_margin=0.0, sigma_reinvest=0.0,
                                years=5, n=200, seed=1, price=100.0)
    q = out["quantiles"]
    assert q["p10"] == pytest.approx(q["p90"])
    assert q["p50"] == pytest.approx(out["deterministic_per_share"])
    assert math.isfinite(q["p50"])


def test_driver_mc_needs_two_years_of_history():
    out = pm.driver_monte_carlo([_fs()], _fs(), P, sigma_growth=0.03, sigma_margin=0.02, sigma_reinvest=0.01,
                                years=5, n=100, seed=1, price=100.0)
    assert out["available"] is False and "2개" in out["reason"]


def test_driver_mc_refuses_a_terminal_growth_at_or_above_wacc():
    hot = ValuationParams(risk_free_rate=0.0, market_premium=0.01, beta=1.0, terminal_growth_rate=0.05)
    out = pm.driver_monte_carlo(_hist(), _hist()[-1], hot, sigma_growth=0.03, sigma_margin=0.02, sigma_reinvest=0.01,
                                years=5, n=100, seed=1, price=100.0)
    assert out["available"] is False and "WACC" in out["reason"]


# ══════════════════════════════════════════════════════════════════════════════
# C2 — 가정형 모델: 시나리오 가중 · 의사결정 나무 · SOTP·지주사 NAV · 실물옵션
# ══════════════════════════════════════════════════════════════════════════════

def test_scenarios_by_hand():
    rows = [{"name": "약세", "prob": 0.25, "value": 30000}, {"name": "기본", "prob": 0.5, "value": 50000},
            {"name": "강세", "prob": 0.25, "value": 80000}]
    out = pm.scenario_weighted(rows, price=45000)
    w = 0.25 * 30000 + 0.5 * 50000 + 0.25 * 80000
    assert out["weighted"] == pytest.approx(w)
    assert out["std"] == pytest.approx(math.sqrt(0.25 * (30000 - w) ** 2 + 0.5 * (50000 - w) ** 2 + 0.25 * (80000 - w) ** 2))
    assert out["prob_above_price"] == pytest.approx(0.75)
    assert out["worst"]["name"] == "약세" and out["best"]["name"] == "강세"


@pytest.mark.parametrize("rows,why", [
    ([{"name": "a", "prob": 0.5, "value": 1}, {"name": "b", "prob": 0.4, "value": 2}], "합"),
    ([{"name": "a", "prob": 1.0, "value": 1}], "2~5"),
    ([{"name": "a", "prob": 0.5, "value": 1}, {"name": "b", "prob": 0.5, "value": None}], "b"),
    ([{"name": "a", "prob": 1.2, "value": 1}, {"name": "b", "prob": -0.2, "value": 2}], "확률"),
])
def test_scenarios_refuse_bad_inputs(rows, why):
    out = pm.scenario_weighted(rows, price=1.0)
    assert out["available"] is False and why in out["reason"]


TREE = [{"id": "A", "parent": "", "label": "규제 승인", "prob": 0.6, "value": None},
        {"id": "B", "parent": "", "label": "승인 실패", "prob": 0.4, "value": 38000},
        {"id": "A1", "parent": "A", "label": "시장 안착", "prob": 0.7, "value": 80000},
        {"id": "A2", "parent": "A", "label": "경쟁 심화", "prob": 0.3, "value": 55000}]


def test_decision_tree_by_hand():
    out = pm.decision_tree(TREE, price=50000)
    assert out["available"] is True
    assert out["expected_value"] == pytest.approx(0.6 * (0.7 * 80000 + 0.3 * 55000) + 0.4 * 38000)
    paths = {p["path"][-1]: p["prob"] for p in out["paths"]}
    assert paths == pytest.approx({"A1": 0.42, "A2": 0.18, "B": 0.4})
    ev = {n["id"]: n["ev"] for n in out["nodes"]}
    assert ev["A"] == pytest.approx(72500)
    assert out["prob_above_price"] == pytest.approx(0.6)


@pytest.mark.parametrize("mut,why", [
    (lambda t: [*t[:2], {**t[2], "prob": 0.5}, t[3]], "합"),
    (lambda t: [*t, {"id": "C", "parent": "Z", "label": "고아", "prob": 1.0, "value": 1}], "Z"),
    (lambda t: [{**t[0], "parent": "A2"}, *t[1:]], "순환"),
    (lambda t: [*t[:3], {**t[3], "value": None}], "값"),
    (lambda t: [*t, {**t[3]}], "중복"),
    (lambda t: [], "가지"),
])
def test_decision_tree_refuses_broken_trees(mut, why):
    out = pm.decision_tree(mut([dict(x) for x in TREE]), price=1.0)
    assert out["available"] is False and why in out["reason"]


def test_decision_tree_depth_is_limited():
    deep = [{"id": f"n{i}", "parent": f"n{i - 1}" if i else "", "label": str(i), "prob": 1.0,
             "value": 1 if i == 5 else None} for i in range(6)]
    out = pm.decision_tree(deep, price=1.0)
    assert out["available"] is False and "깊이" in out["reason"]


def test_sotp_by_hand():
    segs = [{"name": "반도체", "metric": 1000.0, "multiple": 6.0}, {"name": "가전", "metric": 200.0, "multiple": 4.0}]
    subs = [{"code": "000660", "name": "SK하이닉스", "market_cap": 1000.0, "stake_pct": 20.0},
            {"code": "999999", "name": None, "market_cap": None, "stake_pct": 10.0, "reason": "모르는 종목"}]
    out = pm.sotp(segs, subs, net_debt=500.0, holding_discount_pct=30.0, shares=100_000_000)
    gross = 1000 * 6 + 200 * 4 + 1000 * 0.2
    nav = gross - 500
    assert out["gross"] == pytest.approx(gross) and out["nav"] == pytest.approx(nav)
    assert out["after_discount"] == pytest.approx(nav * 0.7)
    assert out["per_share"] == pytest.approx(nav * 0.7 * 1e8 / 100_000_000)
    assert [x["code"] for x in out["excluded"]] == ["999999"]
    assert out["per_share_before_discount"] == pytest.approx(nav * 1e8 / 100_000_000)


def test_sotp_needs_at_least_one_part():
    out = pm.sotp([], [], net_debt=0.0, holding_discount_pct=0.0, shares=1)
    assert out["available"] is False and "부문" in out["reason"]


def test_sotp_refuses_a_negative_multiple():
    out = pm.sotp([{"name": "x", "metric": 10.0, "multiple": -1.0}], [], net_debt=0.0, holding_discount_pct=0.0, shares=1)
    assert out["available"] is False and "배수" in out["reason"]


def _bs(S, K, T, r, q, s, call=True):
    N = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))  # noqa: E731
    d1 = (math.log(S / K) + (r - q + s * s / 2) * T) / (s * math.sqrt(T))
    d2 = d1 - s * math.sqrt(T)
    if call:
        return S * math.exp(-q * T) * N(d1) - K * math.exp(-r * T) * N(d2)
    return K * math.exp(-r * T) * N(-d2) - S * math.exp(-q * T) * N(-d1)


def test_real_option_black_scholes_textbook_value():
    out = pm.real_option(S=100, K=100, T=1, sigma=0.2, r=0.05, q=0.0, kind="call", n_steps=500)
    assert out["black_scholes"]["value"] == pytest.approx(10.4506, abs=1e-3)
    assert out["static_npv"] == pytest.approx(0.0)
    assert out["option_premium"] == pytest.approx(out["black_scholes"]["value"])


def test_real_option_leakage_matches_the_dividend_formula():
    out = pm.real_option(S=100, K=110, T=2, sigma=0.3, r=0.04, q=0.03, kind="call", n_steps=500)
    assert out["black_scholes"]["value"] == pytest.approx(_bs(100, 110, 2, 0.04, 0.03, 0.3), abs=1e-3)


def test_an_abandonment_option_values_early_exercise():
    out = pm.real_option(S=100, K=100, T=1, sigma=0.2, r=0.05, q=0.0, kind="put", n_steps=500)
    assert out["binomial"]["value"] > out["black_scholes"]["value"]
    assert out["early_exercise"]["premium"] > 0


def test_a_call_without_leakage_has_no_early_exercise_premium_only_grid_error():
    out = pm.real_option(S=100, K=100, T=1, sigma=0.2, r=0.05, q=0.0, kind="call", n_steps=200)
    ee = out["early_exercise"]
    assert ee["premium"] == 0.0 and "격자" in ee["note"]


@pytest.mark.parametrize("kw", [{"sigma": 0.0}, {"T": 0.0}, {"S": 0.0}, {"K": -1.0}])
def test_real_option_refuses_degenerate_inputs(kw):
    base = dict(S=100, K=100, T=1, sigma=0.2, r=0.05, q=0.0, kind="call", n_steps=200)
    out = pm.real_option(**{**base, **kw})
    assert out["available"] is False
