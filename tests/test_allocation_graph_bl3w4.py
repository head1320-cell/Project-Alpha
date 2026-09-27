"""BL3 W4 · 리스크 노드 — VaR·ES · 몬테카를로 VaR · 변동성 모델 · 보유기간 VaR · FRTB ES · 롤링 샤프 · 동적 상관
==============================================================================
계획 `happy-percolating-falcon.md` §BL3 W4. 대상 `src/api/allocation_graph_nodes_risk.py`.

## 거는 것
- ★외부를 부르지 않는다★ — 화면 라우트(`/calculate-var` 등)는 종목마다 yfinance 를 부른다. 노드는 Returns 포트(DB 적재분·개발 mock)를
  받아 **같은 모델 클래스**를 직접 부른다. 그래서 골든은 "라우트" 가 아니라 **같은 계열에 모델을 직접 부른 값**이다.
- 모델은 로그수익률을 기대한다(라우트의 `fetch_returns` 가 로그) — 노드는 단순수익률을 `log1p` 로 정확히 바꾼다.
- 포트폴리오 계열 = 비중을 Returns 열에 맞춰 **gross(Σ|w|) 정규화** 후 Σwᵢrᵢ(라우트와 같은 규칙). 없는 이름·전부 0 은 사유 실패.
- 침묵 폴백을 노드가 **먼저 막는다**: 롤링 샤프는 창보다 짧으면 실패(0 을 내지 않는다) · FRTB 스트레스 창을 못 찾으면 '못 찾음' 을
  드러낸다(현재 ES 를 스트레스 ES 로 위장하지 않는다) · 뷰는 엄격한 JSON(무한대·NaN 없음).
- 계산 중 쓰기 0(`graph_write_guard`).
"""
from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.api import allocation_graph_nodes as gn  # noqa: E402
from src.engine import portfolio_graph as pg  # noqa: E402
from src.models.dcc_garch_wwr import dcc_garch_full_report  # noqa: E402
from src.models.frtb_es import FRTBExpectedShortfall  # noqa: E402
from src.models.garch import VolatilityModelComparison  # noqa: E402
from src.models.monte_carlo import MonteCarloVaR  # noqa: E402
from src.models.parametric import ParametricRiskModel  # noqa: E402
from src.models.portfolio_risk import PortfolioRiskModel  # noqa: E402
from src.models.risk_analytics import holding_period_var_es, rolling_sharpe  # noqa: E402
from tests.graph_write_guard import graph_write_guard  # noqa: E402,F401
from tests.test_allocation_graph import T3, _edge, _node, chain, market  # noqa: E402,F401

pytestmark = pytest.mark.usefixtures("graph_write_guard")

RISK = ("var_es", "mc_var", "vol_models", "holding_var", "frtb_es", "rolling_sharpe", "dcc_corr")
NEEDS_WEIGHTS = {"var_es", "mc_var", "vol_models", "holding_var", "frtb_es", "rolling_sharpe"}
FAST = {"mc_var": {"n_simulations": 2000}}


def _graph(kind, *, lookback=756, weights=True, **params):
    g = chain(risk=False, lookback=lookback)
    g["nodes"].append(_node("x", kind, **{**FAST.get(kind, {}), **params}))
    g["edges"].append(_edge("r", "returns", "x", "returns"))
    if weights and kind in NEEDS_WEIGHTS:
        g["edges"].append(_edge("o", "weights", "x", "weights"))
    return g


def _run(g):
    return pg.run(g, gn.REGISTRY)


def _ref(g):
    """같은 그래프의 수익률(단순)과 비중 — 골든 계산의 재료. 노드 코드를 거치지 않고 여기서 따로 만든다."""
    vals = pg._execute(g, gn.REGISTRY)[1]
    R = vals["r"]["returns"]["returns"]
    ow = vals["o"]["weights"]
    wd = dict(zip(ow["names"], np.asarray(ow["weights"], dtype=float)))
    w = np.array([wd.get(c, 0.0) for c in R.columns])
    w = w / np.abs(w).sum()
    lr_df = np.log1p(R)
    rp = np.log1p(R @ w)
    return R, w, lr_df, rp


def _run_node(kind, returns_df, weights=None, **params):
    """노드 처리기를 직접 — 그래프가 만들 수 없는 짧은 계열·이상한 비중을 넣어 본다."""
    spec = gn.REGISTRY.get(kind)
    inputs = {"returns": {"returns": returns_df, "bench": None, "coverage": {}, "names": list(returns_df.columns)}}
    if weights is not None:
        inputs["weights"] = {"names": list(weights), "weights": np.array(list(weights.values()), dtype=float)}
    return spec.run(inputs, spec.params_model(**params))


def _df(n, cols=("A", "B", "C"), seed=0, scale=0.012):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(end="2026-07-15", periods=n)
    return pd.DataFrame({c: rng.normal(0.0004, scale, n) for c in cols}, index=idx)


# ══ 공통 ════════════════════════════════════════════════════════════════════

def test_the_seven_risk_nodes_are_registered_with_returns_input():
    assert set(RISK) <= set(gn.REGISTRY.types())
    for k in RISK:
        ins = {p.name: p for p in gn.REGISTRY.get(k).inputs}
        assert ins["returns"].type == "Returns" and ins["returns"].required
        if k in NEEDS_WEIGHTS:
            assert ins["weights"].type == "Weights" and not ins["weights"].required   # 한 종목만 볼 때는 필요 없다


@pytest.mark.parametrize("kind", RISK)
def test_each_node_computes_on_the_chain_with_strict_json_and_labels(kind, market):
    rep = _run(_graph(kind))
    r = rep["nodes"]["x"]
    assert r["status"] == "ok", r["reason"]
    assert r["lineage"]["sources"] == rep["nodes"]["r"]["lineage"]["sources"]    # 수익률의 계보가 흘러온다
    json.dumps(r["view"], allow_nan=False)                                   # 무한대·NaN 없음(응답이 깨지지 않는다)
    assert r["view"]["meta"]["return_basis"].startswith("log1p")
    assert {i["basis"] for i in r["view"]["result"]["inputs"]} & {"가정", "근사"}
    assert r["explain"]["title"] and r["explain"]["trust"]


def test_mock_returns_make_every_risk_result_practice():
    """market 픽스처 없이 — 개발 mock 수익률(출처 mock)이면 하류 위험 수치도 전부 연습용이다."""
    for kind in ("var_es", "dcc_corr"):
        rep = _run(_graph(kind))
        assert rep["nodes"]["r"]["lineage"]["practice"] is True, rep["nodes"]["r"]["reason"]
        assert rep["nodes"]["x"]["status"] == "ok" and rep["nodes"]["x"]["lineage"]["practice"] is True


@pytest.mark.parametrize("kind", sorted(NEEDS_WEIGHTS))
def test_portfolio_without_weights_fails_and_a_single_ticker_needs_none(kind, market):
    bad = _run(_graph(kind, weights=False))["nodes"]["x"]
    assert bad["status"] == "failed" and "비중" in bad["reason"]
    ok = _run(_graph(kind, weights=False, series=T3[0]))["nodes"]["x"]
    assert ok["status"] == "ok", ok["reason"]
    assert ok["view"]["meta"]["series"] == T3[0]


def test_an_unknown_series_fails_listing_what_exists(market):
    r = _run(_graph("var_es", series="999999"))["nodes"]["x"]
    assert r["status"] == "failed" and "999999" in r["reason"] and T3[0] in r["reason"]


def test_weights_naming_a_missing_asset_fail():
    with pytest.raises(pg.NodeFailure, match="ZZZ"):
        _run_node("var_es", _df(300), {"A": 0.5, "ZZZ": 0.5})


def test_all_zero_weights_fail_instead_of_dividing_by_zero():
    with pytest.raises(pg.NodeFailure, match="0"):
        _run_node("var_es", _df(300), {"A": 0.0, "B": 0.0})


def test_gross_normalisation_is_labelled_only_when_it_changes_the_weights():
    scaled = _run_node("var_es", _df(300), {"A": 0.45, "B": 0.45})         # 10% 현금
    note = [i for i in scaled.view["result"]["inputs"] if i["key"] == "gross"]
    assert note and note[0]["basis"] == "가정" and "1" in note[0]["source"]
    whole = _run_node("var_es", _df(300), {"A": 0.5, "B": 0.5})
    assert not [i for i in whole.view["result"]["inputs"] if i["key"] == "gross"]


def test_a_return_at_or_below_minus_100pct_fails_instead_of_minus_infinity():
    df = _df(300)
    df.iloc[5, 0] = -1.0
    with pytest.raises(pg.NodeFailure, match="-100%"):
        _run_node("var_es", df, series="A")


# ══ 골든 — 같은 계열에 모델을 직접 ══════════════════════════════════════════

def test_var_es_equals_the_models_on_the_same_series(market):
    g = _graph("var_es", confidence_level=0.99, portfolio_value=2e8)
    r = _run(g)["nodes"]["x"]
    assert r["status"] == "ok", r["reason"]
    R, w, lr_df, rp = _ref(g)
    res = r["view"]["result"]
    for key, ewma in (("normal", False), ("ewma", True)):
        m = ParametricRiskModel(0.99, ewma)
        assert res[key]["var_pct"] == pytest.approx(m.calculate_var(rp))
        assert res[key]["es_pct"] == pytest.approx(m.calculate_es(rp))
        assert res[key]["var_amount"] == pytest.approx(m.calculate_var(rp) * 2e8)
    hv = ParametricRiskModel(0.99).historical_var(rp)
    assert res["historical"]["var_pct"] == pytest.approx(hv)
    assert res["historical"]["n_obs"] == len(rp)
    comp = PortfolioRiskModel(0.99, False).component_var(lr_df, w, 2e8)
    got = {c["name"]: c["amount"] for c in res["components"]}
    assert got == pytest.approx(dict(zip(R.columns, comp)))


def test_var_es_for_one_ticker_has_no_components_and_says_why(market):
    r = _run(_graph("var_es", series=T3[1], weights=False))["nodes"]["x"]
    assert r["view"]["result"]["components"] is None and r["view"]["result"]["components_reason"]


def test_mc_var_equals_the_multi_asset_model_and_is_reproducible(market):
    g = _graph("mc_var", n_simulations=3000, holding_period=5, confidence_level=0.95)
    a, b = _run(g)["nodes"]["x"], _run(g)["nodes"]["x"]
    assert a["status"] == "ok", a["reason"]
    R, w, lr_df, rp = _ref(g)
    ref = MonteCarloVaR(n_simulations=3000, holding_period=5, confidence_level=0.95, seed=42).multi_asset_var(
        lr_df, w, 1e8, use_ewma=True, ewma_lambda=0.94)
    got = a["view"]["result"]
    assert got["mc_var_amount"] == ref["mc_var_amount"] and got["mc_es_amount"] == ref["mc_es_amount"]
    assert got["histogram"] == json.loads(json.dumps(ref["histogram"]))
    assert a["view"] == b["view"]                                            # 시드 고정 — 같은 입력, 같은 수


def test_mc_var_for_one_ticker_uses_the_single_asset_model(market):
    g = _graph("mc_var", series=T3[0], weights=False, n_simulations=2000)
    r = _run(g)["nodes"]["x"]
    R = pg._execute(g, gn.REGISTRY)[1]["r"]["returns"]["returns"]
    ref = MonteCarloVaR(n_simulations=2000, holding_period=1, confidence_level=0.99, seed=42).single_asset_var(
        np.log1p(R[T3[0]]), 1e8, use_ewma=True, ewma_lambda=0.94)
    assert r["view"]["result"]["var_amount"] == ref["var_amount"]


def test_mc_var_caps_the_path_count():
    with pytest.raises(ValidationError):                                    # 짝은 아래 줄
        gn.REGISTRY.get("mc_var").params_model(n_simulations=50001)
    assert gn.REGISTRY.get("mc_var").params_model(n_simulations=50000).n_simulations == 50000


def test_vol_models_equals_the_comparison_with_infinities_removed(market):
    g = _graph("vol_models", ewma_lambda=0.97)
    r = _run(g)["nodes"]["x"]
    assert r["status"] == "ok", r["reason"]
    rp = _ref(g)[3]
    ref = VolatilityModelComparison(rp, 0.97).compare()
    got = r["view"]["result"]
    assert got["garch"] == ref["garch"] and got["model_selection"] == ref["model_selection"]
    assert got["ewma"]["half_life_days"] is None and ref["ewma"]["half_life_days"] == float("inf")


def test_vol_models_needs_60_observations():
    with pytest.raises(pg.NodeFailure, match="60"):
        _run_node("vol_models", _df(59), series="A")
    assert _run_node("vol_models", _df(60), series="A").view["result"]["observations"] == 60


def test_holding_var_equals_the_function(market):
    g = _graph("holding_var", holding_periods=[1, 10], confidence_levels=[0.99], method="historical")
    r = _run(g)["nodes"]["x"]
    rp = _ref(g)[3]
    ref = holding_period_var_es(rp, holding_periods=[1, 10], confidence_levels=[0.99],
                                portfolio_value=1e8, method="historical")
    assert r["view"]["result"]["results"] == ref["results"]


def test_frtb_equals_the_model_and_marks_a_found_stress_window(market):
    g = _graph("frtb_es", risk_factor_type="small_cap_equity")
    r = _run(g)["nodes"]["x"]
    rp = _ref(g)[3]
    ref = FRTBExpectedShortfall().single_ticker_report(rp, 1e8, "small_cap_equity")
    got = r["view"]["result"]
    assert got["imcc_capital_charge"] == ref["imcc_capital_charge"] and got["stressed_es"] == ref["stressed_es"]
    assert got["stress_window_found"] is True


def test_frtb_on_a_short_series_says_the_stress_window_was_not_found(market):
    r = _run(_graph("frtb_es", lookback=120))["nodes"]["x"]
    assert r["status"] == "ok", r["reason"]
    assert r["view"]["result"]["stress_window_found"] is False
    assert any("스트레스" in t["text"] and t["state"] != "confirmed" for t in r["explain"]["trust"])


def test_rolling_sharpe_equals_the_function(market):
    g = _graph("rolling_sharpe", window=126, risk_free_rate=0.025)
    r = _run(g)["nodes"]["x"]
    rp = _ref(g)[3]
    assert r["view"]["result"] | {"inputs": None} == rolling_sharpe(rp, window=126, risk_free_rate=0.025) | {"inputs": None}


def test_rolling_sharpe_shorter_than_the_window_fails_instead_of_reporting_zero():
    with pytest.raises(pg.NodeFailure, match="252"):
        _run_node("rolling_sharpe", _df(252), series="A", window=252)
    assert _run_node("rolling_sharpe", _df(253), series="A", window=252).view["result"]["values"]


def test_dcc_equals_the_report_on_log_returns(market):
    g = _graph("dcc_corr")
    r = _run(g)["nodes"]["x"]
    assert r["status"] == "ok", r["reason"]
    lr_df = _ref(g)[2]
    ref = dcc_garch_full_report(lr_df)
    got = r["view"]["result"]
    assert got["dcc_garch"] == json.loads(json.dumps(ref["dcc_garch"])) and got["dates"] == ref["dates"]


def test_dcc_refuses_too_many_assets_and_too_few_days():
    with pytest.raises(pg.NodeFailure, match="6"):
        _run_node("dcc_corr", _df(300, cols=tuple("ABCDEFG")))
    with pytest.raises(pg.NodeFailure, match="60"):
        _run_node("dcc_corr", _df(59))


# ══ R2 · 파생·신용 계산기 ═══════════════════════════════════════════════════
# 입력 포트가 없는 계산 노드(선물 헤지만 선택 포트). 모든 칸이 가정이다 — 시장에서 읽지 않는다.

from src.models.credit_spread_idr import CreditPosition, IncrementalRiskCharge  # noqa: E402
from src.models.cva_engine import CVAEngine  # noqa: E402
from src.models.ficc_engine import FICCEngine  # noqa: E402
from src.models.hedging import HedgingSimulator  # noqa: E402

CALC = ("option_calc", "bond_calc", "futures_hedge", "cva_calc", "irc_calc")


def _calc(kind, **params):
    g = {"format": pg.FORMAT, "version": pg.VERSION, "nodes": [_node("c", kind, **params)], "edges": []}
    return _run(g)


def test_the_calculators_are_registered_without_required_inputs():
    assert set(CALC) <= set(gn.REGISTRY.types())
    for k in CALC:
        assert all(not p.required for p in gn.REGISTRY.get(k).inputs)


@pytest.mark.parametrize("kind", CALC)
def test_each_calculator_computes_with_defaults_labels_every_input_and_is_strict_json(kind):
    r = _calc(kind)["nodes"]["c"]
    assert r["status"] == "ok", r["reason"]
    json.dumps(r["view"], allow_nan=False)
    ins = r["view"]["result"]["inputs"]
    assert ins and {i["basis"] for i in ins} <= {"가정", "관측", "근사"} and "가정" in {i["basis"] for i in ins}
    assert r["explain"]["title"] and r["explain"]["trust"]


def test_option_equals_black_scholes_and_the_hand_value():
    r = _calc("option_calc", S=100, K=100, T=1, r=0.05, sigma=0.2, option_type="call")["nodes"]["c"]
    ref = FICCEngine.bs_greeks(100, 100, 1, 0.05, 0.2, "call")
    assert {k: r["view"]["result"][k] for k in ref} == ref
    assert r["view"]["result"]["Price"] == pytest.approx(10.4506, abs=1e-4)          # 손으로 푼 값(Hull 예제)
    put = _calc("option_calc", S=100, K=100, T=1, r=0.05, sigma=0.2, option_type="put")["nodes"]["c"]["view"]["result"]
    assert r["view"]["result"]["Price"] - put["Price"] == pytest.approx(100 - 100 * np.exp(-0.05), abs=1e-3)  # 풋-콜 패리티


@pytest.mark.parametrize("bad", [{"T": 0}, {"sigma": 0}, {"S": 0}, {"K": -1}])
def test_option_refuses_zero_or_negative_inputs_instead_of_returning_zero_prices(bad):
    rep = _calc("option_calc", **bad)
    assert rep["ok"] is False and any(e["code"] == "bad_params" and e["node_id"] == "c" for e in rep["errors"])


def test_bond_equals_the_engine():
    r = _calc("bond_calc", face_value=10000, coupon_rate=0.035, ytm=0.04, years_to_maturity=5, freq=4)["nodes"]["c"]
    ref = FICCEngine.bond_analytics(10000, 0.035, 0.04, 5, 4)
    assert {k: r["view"]["result"][k] for k in ref} == ref


def test_bond_refuses_an_unknown_coupon_frequency():
    assert _calc("bond_calc", freq=3)["ok"] is False


def test_hedge_with_an_assumed_beta_equals_the_simulator():
    r = _calc("futures_hedge", portfolio_value=1e9, current_beta=1.2, target_beta=0.5,
              futures_price=340.0, multiplier=250000)["nodes"]["c"]
    ref = HedgingSimulator(340.0, 250000).equity_futures_hedge(1e9, 1.2, 0.5)
    assert {k: r["view"]["result"][k] for k in ref} == ref
    beta = next(i for i in r["view"]["result"]["inputs"] if i["key"] == "beta")
    assert beta["basis"] == "가정"


def test_hedge_with_zero_beta_does_not_claim_a_zero_reduction():
    r = _calc("futures_hedge", current_beta=0.0, target_beta=0.0)["nodes"]["c"]
    res = r["view"]["result"]
    assert res["expected_var_reduction_pct"] is None and res["reduction_reason"]


def test_hedge_without_a_beta_or_ports_fails():
    r = _calc("futures_hedge", current_beta=None)["nodes"]["c"]
    assert r["status"] == "failed" and "β" in r["reason"]


def test_hedge_measures_beta_from_connected_returns_and_weights(market):
    g = chain(risk=False)
    g["nodes"].append(_node("h", "futures_hedge", current_beta=None, portfolio_value=1e9))
    g["edges"] += [_edge("r", "returns", "h", "returns"), _edge("o", "weights", "h", "weights")]
    r = _run(g)["nodes"]["h"]
    assert r["status"] == "ok", r["reason"]
    vals = pg._execute(g, gn.REGISTRY)[1]
    R, bench = vals["r"]["returns"]["returns"], vals["r"]["returns"]["bench"]
    ow = vals["o"]["weights"]
    wd = dict(zip(ow["names"], np.asarray(ow["weights"], dtype=float)))
    w = np.array([wd.get(c, 0.0) for c in R.columns])
    rp = (R @ (w / np.abs(w).sum()))
    both = pd.concat([rp, bench], axis=1).dropna()
    beta = float(np.cov(both.iloc[:, 0], both.iloc[:, 1], ddof=1)[0, 1] / np.var(both.iloc[:, 1], ddof=1))
    assert r["view"]["result"]["current_beta"] == pytest.approx(beta)
    b = next(i for i in r["view"]["result"]["inputs"] if i["key"] == "beta")
    assert b["basis"] == "관측" and str(len(both)) in b["source"]


def test_hedge_with_connected_returns_but_no_benchmark_fails(market):
    g = chain(risk=False)
    g["nodes"].append(_node("h", "futures_hedge", current_beta=None))
    g["edges"] += [_edge("r", "returns", "h", "returns"), _edge("o", "weights", "h", "weights")]
    import src.api.allocation_graph_nodes_risk as rk
    spec = gn.REGISTRY.get("futures_hedge")
    vals = pg._execute(g, gn.REGISTRY)[1]
    inputs = {"returns": {**vals["r"]["returns"], "bench": None}, "weights": vals["o"]["weights"]}
    with pytest.raises(pg.NodeFailure, match="비교 기준"):
        spec.run(inputs, spec.params_model(current_beta=None))
    assert rk  # 모듈 로드 확인


def test_cva_equals_the_engine_without_the_mislabelled_bcva_spread():
    r = _calc("cva_calc", notional=5e9, maturity_years=3, cds_spread_bps=200)["nodes"]["c"]
    ref = CVAEngine(0.03, 0.40).full_cva_report(notional=5e9, maturity_years=3, cds_spread_bps=200, position_type="irs",
                                                volatility=0.02, bank_cds_spread_bps=50, bank_recovery=0.40,
                                                spread_shock_bps=100, cds_term_structure=None)
    got = r["view"]["result"]
    for k in ("unilateral_cva", "bilateral_cva", "stressed_cva", "pd_from_cds", "exposure_profile"):
        assert got[k] == ref[k]
    assert "bcva_spread" not in got                                         # 단위가 맞지 않는 모델 출력은 싣지 않는다
    assert any("스프레드" in t["text"] and t["state"] == "unknown" for t in r["explain"]["trust"])


def test_cva_bootstraps_a_term_structure_only_with_two_or_more_points():
    two = _calc("cva_calc", cds_1y=80, cds_5y=150)["nodes"]["c"]["view"]["result"]
    one = _calc("cva_calc", cds_5y=150)["nodes"]["c"]["view"]["result"]
    assert two["hazard_rate_term_structure"] and one["hazard_rate_term_structure"] is None


def test_irc_equals_the_engine_with_a_fixed_seed():
    pos = [{"name": "회사채A", "rating": "BBB", "notional": 1e9, "modified_duration": 5.0},
           {"name": "회사채B", "rating": "BB", "notional": 5e8, "modified_duration": 3.0}]
    r = _calc("irc_calc", positions=pos, n_simulations=20000)["nodes"]["c"]
    ref = IncrementalRiskCharge().calculate_irc(
        [CreditPosition(p["name"], p["rating"], p["notional"], p["modified_duration"]) for p in pos],
        n_simulations=20000, seed=42)
    got = r["view"]["result"]
    assert got["irc_total"] == ref["irc_total"] and got["spread_var_detail"] == ref["spread_var_detail"]


def test_irc_publishes_literal_default_positions_and_caps_them():
    sch = gn.REGISTRY.get("irc_calc").params_model.model_json_schema()
    assert len(sch["properties"]["positions"]["default"]) == 2                  # 설정 화면에 기본 행이 보인다
    many = [{"name": f"p{i}", "rating": "A", "notional": 1e8, "modified_duration": 2.0} for i in range(21)]
    assert _calc("irc_calc", positions=many)["ok"] is False
    assert _calc("irc_calc", positions=many[:20], n_simulations=2000)["nodes"]["c"]["status"] == "ok"


def test_hedge_reports_the_beta_after_rounding_not_the_target():
    """계약 수는 정수다 — β 0.04 를 0 으로 맞추려면 0.47계약이라 반올림하면 0계약, β 는 그대로다. '목표 달성' 으로 말하지 않는다."""
    small = _calc("futures_hedge", portfolio_value=1e9, current_beta=0.041, target_beta=0.0)["nodes"]["c"]
    r = small["view"]["result"]
    assert r["contracts_to_trade"] == 0
    assert r["beta_after_rounding"] == pytest.approx(0.041) and r["beta_reduction_after_rounding_pct"] == pytest.approx(0.0)
    assert "0.04" in small["explain"]["title"] and "→ 0 " not in small["explain"]["title"]
    big = _calc("futures_hedge", portfolio_value=1e9, current_beta=1.2, target_beta=0.0, futures_price=350.0)["nodes"]["c"]
    b = big["view"]["result"]
    after = 1.2 + b["contracts_to_trade"] * 350.0 * 250000 / 1e9
    assert b["beta_after_rounding"] == pytest.approx(after)
    assert b["beta_reduction_after_rounding_pct"] == pytest.approx(abs(1.2 - after) / 1.2 * 100)
