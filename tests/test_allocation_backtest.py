"""Walk-forward allocation-policy backtest — contract + no-look-ahead guarantee (roadmap 07)."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from src.engine.allocation_backtest import walk_forward  # noqa: E402


def _synthetic(n_assets=3, n_days=520, seed=7):
    rng = np.random.default_rng(seed)
    # 자산별 상이한 drift/vol — 최적화가 실제로 차등 가중을 내도록
    mu = np.array([0.0004, 0.0002, 0.0006])[:n_assets]
    sd = np.array([0.010, 0.008, 0.014])[:n_assets]
    R = rng.standard_normal((n_days, n_assets)) * sd + mu
    dates = list(pd.bdate_range("2021-01-04", periods=n_days))
    names = [f"A{i}" for i in range(n_assets)]
    return names, R, dates


def test_basic_shape_and_rebalances():
    names, R, dates = _synthetic()
    out = walk_forward(names, R, dates, model="mvo", rebalance="M", cost_bps=10)
    assert out["error"] is False
    assert out["n_rebalances"] >= 10
    assert len(out["equity_curve"]) == len(out["dates"]) > 0
    # 각 리밸런싱 비중 합 ≈ 100
    for rb in out["rebalances"]:
        assert abs(sum(rb["weights"].values()) - 100.0) < 1.0
    # 지표 유한
    assert np.isfinite(out["summary"]["sharpe_ratio"])
    assert "cvar_pct" in out["metrics"]


def test_no_look_ahead():
    """리밸런싱 k의 가중치는 오직 k 이전 데이터에만 의존 — 미래 행을 교란해도 불변."""
    names, R, dates = _synthetic()
    base = walk_forward(names, R, dates, model="mvo", rebalance="M", cost_bps=0)
    # 마지막 리밸런싱 직전 이후의 모든 미래 수익률을 크게 교란
    cut = len(dates) - 40
    R2 = R.copy()
    R2[cut:] += 0.05   # 미래에 큰 충격
    perturbed = walk_forward(names, R2, dates, model="mvo", rebalance="M", cost_bps=0)
    # cut 이전에 확정된 리밸런싱 비중은 100% 동일해야 함
    for a, b in zip(base["rebalances"], perturbed["rebalances"]):
        if a["date"] >= str(dates[cut].date()):
            break
        assert a["weights"] == b["weights"], f"look-ahead 누출: {a['date']}"


def test_cost_reduces_equity():
    names, R, dates = _synthetic()
    free = walk_forward(names, R, dates, model="mvo", rebalance="M", cost_bps=0)
    costly = walk_forward(names, R, dates, model="mvo", rebalance="M", cost_bps=100)
    assert costly["equity_curve"][-1] <= free["equity_curve"][-1] + 1e-9
    assert costly["turnover_avg_pct"] >= 0.0


def test_box_constraint_respected():
    from src.engine.constrained_opt import Constraints
    names, R, dates = _synthetic()
    c = Constraints(max_weight_pct=40.0)
    out = walk_forward(names, R, dates, model="mvo", rebalance="M", constraints=c, cost_bps=0)
    for rb in out["rebalances"]:
        for w in rb["weights"].values():
            assert w <= 40.05, f"박스 제약 위반: {w}%"


def test_too_few_assets_errors():
    R = np.random.default_rng(1).standard_normal((300, 1)) * 0.01
    dates = list(pd.bdate_range("2021-01-04", periods=300))
    out = walk_forward(["ONLY"], R, dates)
    assert out["error"] is True


def test_benchmark_active_and_ir():
    names, R, dates = _synthetic()
    bench = R[:, 0] * 0.9 + 0.0001   # 벤치마크 프록시
    out = walk_forward(names, R, dates, model="mvo", rebalance="M", bench=bench, cost_bps=5)
    assert out["bench_curve"] is not None
    assert out["summary"]["information_ratio"] is not None


# ── API 스모크 (/backtest) ────────────────────────────────────────────────────
def test_backtest_endpoint_smoke(monkeypatch):
    from src.api.allocation_routes import BacktestRequest, allocation_backtest
    rng = np.random.default_rng(3)
    idx = pd.bdate_range(end="2026-07-15", periods=760)
    tickers = ["005930", "000660", "035420"]
    cols = {t: rng.normal(0.0004 + 0.0001 * i, 0.012, size=760) for i, t in enumerate(tickers)}
    cols["KOSPI"] = rng.normal(0.0003, 0.008, size=760)
    df = pd.DataFrame(cols, index=idx)
    monkeypatch.setattr("src.kis_portfolio_analyzer.load_returns", lambda t, s, e: df)
    monkeypatch.setattr("src.data.stock_master.get_market_cap", lambda code: 100000.0)

    out = allocation_backtest(BacktestRequest(tickers=tickers, model="mvo", benchmark="KOSPI",
                                              rebalance="M", cost_bps=10))
    assert out["error"] is False
    assert out["n_rebalances"] >= 12
    assert len(out["equity_curve"]) == len(out["dates"]) > 0
    assert out["bench_curve"] is not None and out["benchmark_label"] == "KOSPI"
    assert "sharpe_ratio" in out["summary"] and "cvar_pct" in out["metrics"]
    assert out["coverage"]["source"] in ("db", "mock")
    assert set(out["labels"]) == set(tickers)
