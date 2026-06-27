"""공용 퀀트 성과지표(QuantStats 표준 부분집합) — 알려진 시계열로 공식 검증 + 빈입력 안전."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.engine.quant_metrics import compute_metrics  # noqa: E402


def _eq_from(rets, base=100.0):
    eq, v = [], base
    for r in rets:
        v *= (1 + r)
        eq.append(v)
    return eq


def test_constant_returns_no_vol_no_dd():
    rets = [0.01] * 10
    m = compute_metrics(rets, _eq_from(rets), periods_per_year=252)
    assert m["volatility_pct"] == 0.0           # 상수 수익 → 변동성 0
    assert m["max_drawdown_days"] == 0          # 낙폭 없음
    assert m["best_period_pct"] == 1.0 and m["worst_period_pct"] == 1.0


def test_var_cvar_tail():
    rets = [-0.05, -0.03, -0.01, 0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.10]
    m = compute_metrics(rets, _eq_from(rets), periods_per_year=252)
    assert m["var_pct"] <= -3.0                 # 5% VaR ~ -4%
    assert m["cvar_pct"] <= m["var_pct"]        # CVaR ≤ VaR (더 극단)
    assert m["skew"] is not None and m["kurtosis"] is not None
    assert m["tail_ratio"] >= 0


def test_drawdown_recovery_ulcer():
    eq = [100.0, 120.0, 90.0, 130.0]
    rets = [eq[i] / eq[i - 1] - 1 for i in range(1, len(eq))]
    m = compute_metrics(rets, eq, periods_per_year=252)
    assert m["ulcer_index"] > 0
    assert m["recovery_factor"] > 0             # total_return>0 / |maxDD|>0


def test_omega_gain_pain():
    rets = [0.02, -0.01, 0.03, -0.02, 0.01]
    m = compute_metrics(rets, _eq_from(rets), periods_per_year=252)
    assert abs(m["omega"] - 2.0) < 0.05         # gains 0.06 / losses 0.03
    assert abs(m["gain_to_pain"] - 1.0) < 0.05  # net 0.03 / losses 0.03


def test_trades_payoff_kelly():
    m = compute_metrics([0.01, 0.02], [100.0, 101.0, 103.0], periods_per_year=252,
                        trades_pnl=[100, 200, -50, -50, 300])
    assert abs(m["payoff_ratio"] - 4.0) < 1e-6  # avg_win 200 / avg_loss 50
    assert m["kelly_pct"] is not None


def test_benchmark_information_ratio():
    rets = [0.02, 0.01, -0.01, 0.03, 0.0]
    bench = [0.01, 0.01, 0.0, 0.01, 0.0]
    m = compute_metrics(rets, _eq_from(rets), periods_per_year=252, benchmark_returns=bench)
    assert "information_ratio" in m


def test_empty_safe():
    m = compute_metrics([], [], periods_per_year=252)
    assert isinstance(m, dict) and m["volatility_pct"] == 0.0
