"""포트폴리오 분석·리밸런싱·효율적 프론티어 — main_api.py에서 분리(경로·동작 불변).
"""

import logging

from fastapi import APIRouter, HTTPException

from src.api.legacy_schemas import (
    EfficientFrontierRequest,
    PortfolioAnalyzeRequest,
    RankingRequest,
    RebalanceRequest,
)
from src.data_loader import MarketDataLoader
from src.models.portfolio_optimizer import (
    efficient_frontier,
    equal_weight_top_n,
    rank_assets,
)

logger = logging.getLogger("api.portfolio")
router = APIRouter(tags=["portfolio"])


@router.post("/api/v1/portfolio/analyze")
def portfolio_analyze(req: PortfolioAnalyzeRequest):
    """
    포트폴리오 분석:
    상관관계, 분산 비율, 효율적 프론티어, 리스크 기여도.
    """
    try:
        from src.kis_portfolio_analyzer import analyze_portfolio
        return analyze_portfolio(
            tickers=req.tickers,
            start_date=req.start_date,
            end_date=req.end_date,
            weights=req.weights,
            compute_frontier=req.compute_frontier,
            compute_optimal=req.compute_optimal,
        )
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")

@router.post("/api/v1/portfolio/rebalance")
def portfolio_rebalance(req: RebalanceRequest):
    """
    리밸런싱 시뮬레이션:
    주기적 리밸런싱 포트폴리오 vs Buy & Hold 비교.
    """
    try:
        from src.kis_portfolio_analyzer import simulate_rebalancing
        return simulate_rebalancing(
            tickers=req.tickers,
            start_date=req.start_date,
            end_date=req.end_date,
            weights=req.weights,
            frequency=req.frequency,
            initial_capital=req.initial_capital,
            commission_rate=req.commission_rate,
        )
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")

@router.post("/efficient-frontier")
def run_efficient_frontier(req: EfficientFrontierRequest):
    """Compute Markowitz efficient frontier via Monte Carlo."""
    try:
        if len(req.tickers) < 2:
            raise HTTPException(400, "Need at least 2 tickers")

        loader = MarketDataLoader(req.tickers[0], req.start_date, req.end_date)
        returns_df = loader.fetch_multi_returns(req.tickers)

        if len(returns_df) < 60:
            raise HTTPException(400, "Not enough overlapping data (need 60+ days)")

        result = efficient_frontier(
            returns_df,
            n_portfolios=min(req.n_portfolios, 10000),
            risk_free_rate=req.risk_free_rate,
        )
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")

@router.post("/rank-assets")
def run_rank_assets(req: RankingRequest):
    """Rank assets by momentum, Sharpe, or inverse volatility."""
    try:
        loader = MarketDataLoader(req.tickers[0], req.start_date, req.end_date)
        returns_df = loader.fetch_multi_returns(req.tickers)
        rankings = rank_assets(returns_df, method=req.method, top_n=req.top_n)
        weights = equal_weight_top_n(rankings, req.top_n)
        return {"rankings": rankings, "recommended_weights": weights}
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")
