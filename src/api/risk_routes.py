"""시장 리스크 — VaR·ES·FRTB·스트레스 — main_api.py에서 분리(경로·동작 불변).
"""

import logging

import numpy as np
from fastapi import APIRouter, HTTPException

from src.api.legacy_schemas import (
    AggregateVaRRequest,
    FRTBRequest,
    GARCHRequest,
    HoldingPeriodVaRRequest,
    MCPathRequest,
    MCPortfolioVaRRequest,
    MCVaRRequest,
    PortfolioVaRRequest,
    RollingStatsRequest,
    StressRequest,
    VaRRequest,
)
from src.data_loader import MarketDataLoader
from src.models.ai_engine import AIVolatilityEngine
from src.models.ficc_aggregation import FICCRiskAggregator
from src.models.frtb_es import LIQUIDITY_HORIZON_MAP, FRTBExpectedShortfall
from src.models.garch import VolatilityModelComparison
from src.models.monte_carlo import MonteCarloVaR
from src.models.parametric import ParametricRiskModel
from src.models.portfolio_risk import PortfolioRiskModel
from src.models.risk_analytics import (
    holding_period_var_es,
    mc_path_simulation,
    rolling_sharpe,
)
from src.models.stress_test import StressTester

logger = logging.getLogger("api.risk")
router = APIRouter(tags=["risk"])


@router.post("/calculate-var")
def calculate_var(req: VaRRequest):
    try:
        loader  = MarketDataLoader(req.ticker, req.start_date, req.end_date)
        returns = loader.fetch_returns()

        model    = ParametricRiskModel(req.confidence_level, req.use_ewma)
        var_pct  = model.calculate_var(returns)
        es_pct   = model.calculate_es(returns)
        hist_var = model.historical_var(returns)

        var_amount  = var_pct  * req.portfolio_value
        es_amount   = es_pct   * req.portfolio_value
        hist_amount = hist_var * req.portfolio_value

        # AI prediction
        ai_engine = AIVolatilityEngine(returns)
        ai_var    = ai_engine.predict_var(req.portfolio_value, req.confidence_level)
        regime    = ai_engine.volatility_regime()

        return {
            "ticker":           req.ticker,
            "var_pct":          round(float(var_pct), 6),
            "var_amount":       round(float(var_amount), 0),
            "es_amount":        round(float(es_amount), 0),
            "hist_var_amount":  round(float(hist_amount), 0),
            "ai_var_amount":    round(float(ai_var), 0),
            "volatility_regime": regime,
            "method": "EWMA-Parametric" if req.use_ewma else "Normal-Parametric",
            "obs":    len(returns),
        }
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")

@router.post("/calculate-portfolio-var")
def calculate_portfolio_var(req: PortfolioVaRRequest):
    try:
        loader  = MarketDataLoader(req.tickers[0], req.start_date, req.end_date)
        df      = loader.fetch_multi_returns(req.tickers)
        weights = np.array(req.weights)
        weights = weights / weights.sum()

        model = PortfolioRiskModel(req.confidence_level, req.use_ewma)
        var_amount, port_vol = model.calculate_portfolio_var(df, weights, req.portfolio_value)
        comp_var = model.component_var(df, weights, req.portfolio_value)

        return {
            "portfolio_var":    round(float(var_amount), 0),
            "portfolio_vol":    round(float(port_vol), 6),
            "component_var":    {t: round(float(v), 0) for t, v in zip(req.tickers, comp_var)},
            "weights_used":     {t: round(float(w), 4) for t, w in zip(req.tickers, weights)},
        }
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")

@router.post("/aggregate-var")
def aggregate_var(req: AggregateVaRRequest):
    try:
        vars_arr = np.array(req.individual_vars)
        corr     = np.array(req.correlation_matrix)
        agg      = FICCRiskAggregator()
        result   = agg.diversification_benefit(vars_arr, corr)
        return {k: round(v, 0) if isinstance(v, float) else v for k, v in result.items()}
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")

@router.post("/mc-var")
def mc_var_single(req: MCVaRRequest):
    """Single-asset Monte Carlo VaR using Geometric Brownian Motion."""
    try:
        loader  = MarketDataLoader(req.ticker, req.start_date, req.end_date)
        returns = loader.fetch_returns()

        engine = MonteCarloVaR(
            n_simulations=req.n_simulations,
            holding_period=req.holding_period,
            confidence_level=req.confidence_level,
        )
        result = engine.single_asset_var(
            returns, req.portfolio_value,
            use_ewma=req.use_ewma, ewma_lambda=req.ewma_lambda,
        )
        result["ticker"] = req.ticker
        result["obs"] = len(returns)
        return result
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")

@router.post("/mc-portfolio-var")
def mc_portfolio_var(req: MCPortfolioVaRRequest):
    """
    Multi-asset Monte Carlo VaR with Cholesky-decomposed correlation structure.

    Simulates correlated GBM paths for each asset, applies portfolio weights,
    and extracts VaR/ES from the resulting P&L distribution.
    """
    try:
        loader  = MarketDataLoader(req.tickers[0], req.start_date, req.end_date)
        df      = loader.fetch_multi_returns(req.tickers)
        weights = np.array(req.weights)
        weights = weights / weights.sum()

        engine = MonteCarloVaR(
            n_simulations=req.n_simulations,
            holding_period=req.holding_period,
            confidence_level=req.confidence_level,
        )
        result = engine.multi_asset_var(
            df, weights, req.portfolio_value,
            use_ewma=req.use_ewma, ewma_lambda=req.ewma_lambda,
        )
        result["obs"] = len(df)
        return result
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")

@router.post("/garch-compare")
def garch_compare(req: GARCHRequest):
    """
    Fit GARCH(1,1) via MLE and compare head-to-head with EWMA.

    Returns: parameter estimates, AIC/BIC comparison, current & forecast
    volatility, standardised residual diagnostics, and time series data.
    """
    try:
        loader = MarketDataLoader(req.ticker, req.start_date, req.end_date)
        returns = loader.fetch_returns()

        if len(returns) < 60:
            raise HTTPException(status_code=400,
                                detail="최소 60 관측치 필요 (현재 데이터 부족)")

        comparison = VolatilityModelComparison(returns, req.ewma_lambda)
        result = comparison.compare()
        result["ticker"] = req.ticker
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")

@router.post("/frtb-es")
def frtb_es(req: FRTBRequest):
    """
    FRTB-aligned Expected Shortfall calculation.

    Computes: ES 97.5% (parametric + historical), Stressed ES (250-day worst window),
    Liquidity-adjusted ES with IMA waterfall, and IMCC capital charge.
    """
    try:
        loader = MarketDataLoader(req.ticker, req.start_date, req.end_date)
        returns = loader.fetch_returns()

        engine = FRTBExpectedShortfall()
        result = engine.single_ticker_report(
            returns, req.portfolio_value, req.risk_factor_type,
        )
        result["ticker"] = req.ticker
        return result
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")

@router.get("/frtb-lh-map")
def frtb_lh_map():
    """Return the FRTB risk factor → liquidity horizon mapping table."""
    return {"liquidity_horizon_map": LIQUIDITY_HORIZON_MAP}

@router.post("/holding-period-var")
def run_holding_period_var(req: HoldingPeriodVaRRequest):
    """Holding-period scaled VaR and ES using sqrt(T) rule."""
    try:
        loader = MarketDataLoader(req.ticker, req.start_date, req.end_date)
        returns = loader.fetch_returns()
        return holding_period_var_es(
            returns,
            holding_periods=req.holding_periods,
            confidence_levels=req.confidence_levels,
            portfolio_value=req.portfolio_value,
            method=req.method,
        )
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")

@router.post("/mc-paths")
def run_mc_paths(req: MCPathRequest):
    """Monte Carlo GBM path simulation for spaghetti plot."""
    try:
        loader = MarketDataLoader(req.ticker, req.start_date, req.end_date)
        prices = loader.fetch_prices()
        returns = loader.fetch_returns()
        result = mc_path_simulation(
            returns,
            n_paths=min(req.n_paths, 1000),
            n_days=req.n_days,
            initial_price=float(prices.iloc[-1]),
        )
        result["ticker"] = req.ticker
        return result
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")

@router.post("/rolling-sharpe")
def run_rolling_sharpe(req: RollingStatsRequest):
    """Rolling Sharpe ratio timeline."""
    try:
        loader = MarketDataLoader(req.ticker, req.start_date, req.end_date)
        returns = loader.fetch_returns()
        return rolling_sharpe(returns, window=req.window)
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")

@router.post("/stress-test")
def stress_test(req: StressRequest):
    try:
        tester  = StressTester()
        results = tester.apply_scenarios(
            req.equity_value, req.bond_value, req.fx_value,
            req.portfolio_beta, req.modified_duration
        )
        return {"scenarios": results}
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")
