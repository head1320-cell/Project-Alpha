"""BL3 M · 모델 결함 8건 — ★틀린 수를 지어내지 않는다★ (계획 happy-percolating-falcon §BL3 M)
==============================================================================
W4 감사는 노드 앞에서 폴백을 막았지만 `/risk-tools`·`/derivatives`·`/calculate-*`·`/realism/*` 라우트는 여전히 틀린 수를 냈다.
이 파일은 **모델에서** 고친 것을 지킨다. 각 결함마다 짝을 붙인다 — 고친 경로는 X 를 하지 않고, 정상 입력의 값은 그대로다(골든).

- M1 CVA — BCVA '스프레드' 가 금액×10⁴ 를 bp 로 표기했다.
- M2 블랙-숄즈 — 0 이하 입력에 모든 값 0 · 만기 T=0 에 내재가치를 버리고 0.
- M3 롤링 샤프 — 창보다 짧으면 `current: 0`.
- M4 FRTB — 스트레스 구간을 못 찾으면 현재 ES 를 그 자리에 두면서 표시는 문자열 'N/A' 뿐.
- M5 선물 헤지 — 감소율이 목표 β 기준(반올림 0계약에도 100%) · β=0 이면 0.
- M6 페어 — 수동 헤지비율에서 모르는 β 를 0 으로 넣어 '베타 중립' 이라 말했다.
- M7 현금 금리 — 저장된 금리가 없으면 조용히 3.5%.
- M8 용량 — 데이터가 없으면 `capacity_krw: inf`(엄격 JSON 이 아니다).
"""
from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd
import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.models.cva_engine import CVAEngine  # noqa: E402
from src.models.ficc_engine import FICCEngine  # noqa: E402
from src.models.frtb_es import FRTBExpectedShortfall  # noqa: E402
from src.models.hedging import HedgingSimulator  # noqa: E402
from src.models.risk_analytics import rolling_sharpe  # noqa: E402


def _series(n, seed=0, scale=0.01):
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(0.0003, scale, n), index=pd.bdate_range(end="2026-07-15", periods=n))


# ══ M1 · CVA 의 BCVA 스프레드 ═══════════════════════════════════════════════

def _cva(**kw):
    base = dict(notional=1e10, maturity_years=5.0, cds_spread_bps=150, position_type="irs")
    return CVAEngine(0.03, 0.40).full_cva_report(**{**base, **kw})


def test_bcva_running_cost_is_an_annual_amount_and_bp_of_notional():
    r = _cva()
    epe = r["exposure_profile"]["epe"]
    b = r["bcva_spread"]
    cva_amt = 150 / 1e4 * epe                                      # s × EPE — 해마다 드는 금액
    assert b["cva_running_annual"] == pytest.approx(cva_amt, rel=1e-6)
    assert b["cva_running_bp_of_notional"] == pytest.approx(cva_amt / 1e10 * 1e4, abs=1e-4)   # 소수 넷째 자리 반올림
    assert b["unit_amount"] == "원/년" and "bp" not in b["unit_amount"]
    assert b["bcva_running_annual"] == pytest.approx(b["dva_running_annual"] - b["cva_running_annual"])
    # 짝: 예전 필드(금액×10⁴ 를 bp 라 부른 것)는 없다 — 1e10 명목에 수백억 'bp' 가 나오지 않는다
    assert "cva_spread_annual" not in b and "unit" not in b
    assert b["cva_running_bp_of_notional"] < 1e4


def test_the_rest_of_the_cva_report_is_unchanged():
    r = _cva(maturity_years=3.0, cds_spread_bps=200, notional=5e9)
    assert r["unilateral_cva"]["cva_amount"] > 0 and r["unilateral_cva"]["cva_spread_bps"] > 0
    assert set(r) >= {"inputs", "pd_from_cds", "exposure_profile", "unilateral_cva", "bilateral_cva", "bcva_spread", "stressed_cva"}


# ══ M2 · 블랙-숄즈 ══════════════════════════════════════════════════════════

@pytest.mark.parametrize("bad", [dict(S=0), dict(S=-1), dict(K=0), dict(sigma=0), dict(sigma=-0.1), dict(T=-0.5)])
def test_black_scholes_refuses_impossible_inputs_instead_of_zero_prices(bad):
    args = {"S": 100.0, "K": 100.0, "T": 1.0, "r": 0.05, "sigma": 0.2, **bad}
    with pytest.raises(ValueError):
        FICCEngine.bs_greeks(args["S"], args["K"], args["T"], args["r"], args["sigma"], "call")


@pytest.mark.parametrize("S,K,kind,price,delta", [
    (120, 100, "call", 20.0, 1.0), (80, 100, "call", 0.0, 0.0),
    (80, 100, "put", 20.0, -1.0), (120, 100, "put", 0.0, 0.0),
])
def test_at_expiry_the_price_is_intrinsic_value(S, K, kind, price, delta):
    g = FICCEngine.bs_greeks(S, K, 0.0, 0.05, 0.2, kind)
    assert g["Price"] == pytest.approx(price) and g["Delta"] == delta
    assert g["at_expiry"] is True and g["Gamma"] == 0 and g["Vega"] == 0


def test_at_the_money_expiry_delta_is_undefined_not_zero():
    g = FICCEngine.bs_greeks(100, 100, 0.0, 0.05, 0.2, "call")
    assert g["Price"] == 0 and g["Delta"] is None


def test_black_scholes_value_is_unchanged_for_valid_inputs():
    g = FICCEngine.bs_greeks(100, 100, 1.0, 0.05, 0.2, "call")
    assert g["Price"] == pytest.approx(10.4506, abs=1e-4) and "at_expiry" not in g


def test_analyze_option_answers_422_with_a_reason_for_impossible_inputs():
    from fastapi.testclient import TestClient
    from main_api import app
    c = TestClient(app)
    bad = c.post("/analyze-option", json={"S": 100, "K": 100, "T": 1, "r": 0.05, "sigma": 0, "option_type": "call"})
    assert bad.status_code == 422 and "변동성" in bad.json()["detail"]
    ok = c.post("/analyze-option", json={"S": 100, "K": 100, "T": 1, "r": 0.05, "sigma": 0.2, "option_type": "call"})
    assert ok.status_code == 200 and ok.json()["Price"] == pytest.approx(10.4506, abs=1e-4)


# ══ M3 · 롤링 샤프 ══════════════════════════════════════════════════════════

def test_rolling_sharpe_on_a_series_shorter_than_the_window_reports_nothing_with_a_reason():
    out = rolling_sharpe(_series(100), window=252)
    assert out["values"] == [] and out["current"] is None and out["mean"] is None and out["reason"]
    json.dumps(out, allow_nan=False)


def test_rolling_sharpe_with_zero_volatility_windows_does_not_emit_infinity():
    r = pd.Series([0.001] * 300, index=pd.bdate_range(end="2026-07-15", periods=300))
    out = rolling_sharpe(r, window=60)
    json.dumps(out, allow_nan=False)
    assert out["current"] is None and out["reason"]


def test_rolling_sharpe_values_are_unchanged_for_a_normal_series():
    out = rolling_sharpe(_series(400), window=126, risk_free_rate=0.02)
    assert len(out["values"]) == 400 - 125 and isinstance(out["current"], float) and out.get("reason") is None


# ══ M4 · FRTB 스트레스 구간 ═════════════════════════════════════════════════

def test_frtb_says_whether_it_found_a_stress_window():
    short = FRTBExpectedShortfall().stressed_es(_series(100), 1e9)
    assert short["stress_window_found"] is False and short["reason"]
    long = FRTBExpectedShortfall().stressed_es(_series(600), 1e9)
    assert long["stress_window_found"] is True and long.get("reason") is None


def test_frtb_capital_is_unchanged_by_the_flag():
    rep = FRTBExpectedShortfall().single_ticker_report(_series(600, seed=3), 1e8, "large_cap_equity")
    rep_short = FRTBExpectedShortfall().single_ticker_report(_series(100, seed=3), 1e8, "large_cap_equity")
    assert rep["stressed_es"]["stress_window_found"] is True
    # 폴백의 값은 문서화된 대로 현재 ES(자본 공식이 그대로 쓴다) — 값을 바꾸지 않고 드러내기만 한다
    assert rep_short["stressed_es"]["stressed_es_975"] == rep_short["stressed_es"]["current_es_975"]


# ══ M5 · 선물 헤지 ══════════════════════════════════════════════════════════

def test_hedge_reduction_is_measured_after_rounding():
    r = HedgingSimulator(350.0).equity_futures_hedge(1e9, 0.041, 0.0)
    assert r["contracts_to_trade"] == 0
    assert r["beta_after_rounding"] == pytest.approx(0.041)
    assert r["expected_var_reduction_pct"] == pytest.approx(0.0)          # 0계약이면 줄지 않았다(예전 100%)
    assert "반올림" in r["reduction_basis"]


def test_hedge_reduction_matches_the_traded_contracts():
    r = HedgingSimulator(360.0).equity_futures_hedge(1e8, 1.2, 0.0)
    after = 1.2 + r["contracts_to_trade"] * 360.0 * 250000 / 1e8
    assert r["beta_after_rounding"] == pytest.approx(after)
    assert r["expected_var_reduction_pct"] == pytest.approx(round(abs(1.2 - after) / 1.2 * 100, 1))
    assert r["raw_contracts"] == pytest.approx(round(-1.2 * 1e8 / (360.0 * 250000), 2))   # 계약 수는 그대로


def test_hedge_with_zero_beta_does_not_claim_a_reduction():
    r = HedgingSimulator(350.0).equity_futures_hedge(1e9, 0.0, 0.0)
    assert r["expected_var_reduction_pct"] is None and r["reduction_reason"]


# ══ M6 · 페어 스프레드 ══════════════════════════════════════════════════════

def test_pair_with_a_manual_ratio_and_unknown_beta_does_not_claim_neutrality():
    from src.engine.neutralize import pair_spread
    r = pair_spread("A", "B", {"A": 1.1, "B": None}, hedge_ratio=0.8)
    assert r["error"] is False and r["hedge_ratio"] == 0.8
    assert r["net_beta"] is None and r["beta_neutral"] is None and "B" in r["beta_reason"]
    assert r["basis"] == "manual"


def test_pair_with_both_betas_is_unchanged():
    from src.engine.neutralize import pair_spread
    r = pair_spread("A", "B", {"A": 1.2, "B": 0.8})
    assert r["hedge_ratio"] == pytest.approx(1.5) and r["beta_neutral"] is True and r["basis"] == "beta"
    m = pair_spread("A", "B", {"A": 1.2, "B": 0.8}, hedge_ratio=1.0)
    assert m["basis"] == "manual" and m["net_beta"] == pytest.approx(0.4) and m["beta_neutral"] is False


# ══ M7 · 현금 금리 ══════════════════════════════════════════════════════════

class _Conn:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, q, params):
        v = self.rows.get(params["s"])

        class R:
            def fetchone(self_inner):
                if v is None:
                    return None

                class Row:
                    _mapping = {"value": v}
                return Row()
        return R()


class _Engine:
    def __init__(self, rows=None, boom=False):
        self.rows, self.boom = rows or {}, boom

    def connect(self):
        if self.boom:
            raise RuntimeError("db down")
        return _Conn(self.rows)


@pytest.mark.parametrize("engine,source", [
    (_Engine({"CD91": 3.4}), "CD91"), (_Engine({"BASE_RATE": 2.5}), "BASE_RATE"),
    (_Engine({}), "default"), (_Engine(boom=True), "error"), (None, "default"),
])
def test_cash_rate_names_where_it_came_from(engine, source):
    from src.engine.cash_management import DEFAULT_RF_ANNUAL, CashRateProvider
    p = CashRateProvider(engine)
    rate, src = p.get_rate_with_source(pd.Timestamp("2026-07-01"))
    assert src == source
    assert rate == CashRateProvider(engine).get_rate(pd.Timestamp("2026-07-01"))   # 값은 그대로(백테스트가 쓴다)
    if source in ("default", "error"):
        assert rate == DEFAULT_RF_ANNUAL


def test_daily_yield_carries_the_rate_source():
    from src.engine.cash_management import CashRateProvider, CashYieldCalculator
    out = CashYieldCalculator(CashRateProvider(_Engine({}))).daily_yield(0.7, pd.Timestamp("2026-07-01"))
    assert out["rf_source"] == "default" and out["rf_is_assumed"] is True
    got = CashYieldCalculator(CashRateProvider(_Engine({"CD91": 3.4}))).daily_yield(0.7, pd.Timestamp("2026-07-01"))
    assert got["rf_source"] == "CD91" and got["rf_is_assumed"] is False


# ══ M8 · 용량 ═══════════════════════════════════════════════════════════════

def test_unknown_capacity_is_none_with_a_reason_not_infinity():
    from src.engine.liquidity_capacity import LiquidityCapacityEstimator
    fb = LiquidityCapacityEstimator._fallback_capacity(7)
    assert fb["available"] is False and fb["capacity_krw"] is None and fb["reason"]
    json.dumps(fb, allow_nan=False)


def test_capacity_adjustment_still_skips_unknown_strategies():
    from src.engine.liquidity_capacity import LiquidityCapacityEstimator
    est = LiquidityCapacityEstimator.__new__(LiquidityCapacityEstimator)
    caps = {1: LiquidityCapacityEstimator._fallback_capacity(1),
            2: {"strategy_id": 2, "capacity_krw": 1e9, "available": True}}
    out = est.apply_capacity_to_weights({1: 0.5, 2: 0.5}, caps, 1e9)
    assert out["adjusted_weights"][1] == pytest.approx(0.5)             # 모르는 전략은 제약하지 않고 그대로(예전과 같다)
    json.dumps(out, allow_nan=False)
