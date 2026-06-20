"""
FICC Risk Management Platform - FastAPI Backend
Endpoints: VaR, Stress Test, Backtesting, Hedging, FICC Analytics,
           AI Prediction, Broker Sync, Auto-Trading, WebSocket Live Feed
"""
import asyncio
import logging
import random
from datetime import date, datetime

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.api.broker_kis import KoreaInvestmentAPI
from src.data_loader import MarketDataLoader
from src.database import get_trade_history, init_db, log_trade
from src.models.ai_engine import AIVolatilityEngine
from src.models.backtest import VaRBacktester
from src.models.credit_spread_idr import (
    CREDIT_SPREADS_BPS,
    DEFAULT_PROBS,
    RATING_GRADES,
    TRANSITION_MATRIX_1Y,
    CreditPosition,
    IncrementalRiskCharge,
)
from src.models.cva_engine import CVAEngine
from src.models.dcc_garch_wwr import (
    WrongWayRiskDetector,
    dcc_garch_full_report,
)

# LSTM은 torch 선택적 의존성 — 최상단 import 제거, 엔드포인트에서 lazy import
# (torch 미설치 시에도 플랫폼 전체가 정상 기동하도록)
from src.models.feature_engine import MultiFeatureVolatilityEngine
from src.models.ficc_aggregation import FICCRiskAggregator
from src.models.ficc_engine import FICCEngine
from src.models.frtb_es import LIQUIDITY_HORIZON_MAP, FRTBExpectedShortfall
from src.models.garch import VolatilityModelComparison
from src.models.hedging import HedgingSimulator
from src.models.model_monitor import ModelMonitor
from src.models.monte_carlo import MonteCarloVaR
from src.models.parametric import ParametricRiskModel
from src.models.pit_backtest import PITBacktester
from src.models.portfolio_optimizer import (
    efficient_frontier,
    equal_weight_top_n,
    rank_assets,
)
from src.models.portfolio_risk import PortfolioRiskModel
from src.models.risk_analytics import (
    holding_period_var_es,
    mc_path_simulation,
    rolling_sharpe,
)
from src.models.signal_engine import (
    CONDITION_REGISTRY,
    multi_condition_backtest,
)
from src.models.strategy_builder import (
    STRATEGY_REGISTRY,
    compute_performance_metrics,
    compute_trade_metrics,
    grid_search,
    portfolio_backtest,
)
from src.models.stress_test import StressTester
from src.models.var_mapping import (
    Bond,
    VaRMappingEngine,
)

# ─── App Init ────────────────────────────────────────────────────────────────
app = FastAPI(
    title="FICC Risk Management API",
    version="2.0.0",
    description="Full-stack quantitative risk platform: VaR, Greeks, Hedging, AI Forecasting",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",      # Next.js 로컬 개발
        "http://localhost:8000",      # FastAPI 자체 (Swagger UI)
        "http://127.0.0.1:3000",
        "*",                          # 개발/배포 임시 허용
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 관측성: 구조화 로깅 + 요청 추적 ID + 요청 로깅 + 예외 안전망
try:
    from src.observability.logging_config import setup_logging
    from src.observability.middleware import install_observability
    setup_logging()
    install_observability(app)
except Exception as _obs_err:
    logging.getLogger(__name__).warning(f"관측성 설치 실패(계속 진행): {_obs_err}")

# 모듈 레벨 로거 (엔드포인트 에러 로깅용)
logger = logging.getLogger("api.main")

# Initialize DB on startup
@app.on_event("startup")
async def startup():
    import asyncio
    try:
        init_db()
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"init_db failed (DB 준비 전일 수 있음): {e}")

    # Initialize screener tables (legacy sync path)
    try:
        from src.database import get_engine
        from src.screener_models import init_screener_tables
        from src.screener_pipeline import update_market_cache_loop
        engine = get_engine()
        init_screener_tables(engine)
        asyncio.create_task(update_market_cache_loop(engine))
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Screener startup failed: {e}")

    # Initialize KIS-backed async DB and scheduler
    try:
        from src.data_sync import daily_sync_scheduler
        from src.database_async import init_async_db
        ok = await init_async_db()
        if ok:
            asyncio.create_task(daily_sync_scheduler())
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"KIS async DB startup failed: {e}")

    # 실데이터 사전 워밍 (DART 키 있을 때만, 백그라운드 스레드):
    #   ① corp_code 맵을 미리 로드 → 첫 스크린의 corp_code 미스("조회된 데이터 없음") 방지
    #   ② 기본 유니버스 펀더멘털을 미리 계산 → 디스크 캐시 채움 → 사용자 첫 클릭이
    #      44초를 기다리지 않게 함. 재시작 후엔 디스크 캐시 히트로 빠르게 재워밍.
    try:
        import os
        if os.getenv("DART_API_KEY"):
            import threading
            threading.Thread(target=_prewarm_real_data, daemon=True).start()
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"실데이터 사전 워밍 시작 실패: {e}")


def _prewarm_real_data():
    """백그라운드(데몬 스레드): corp_code 맵 준비 + 기본 유니버스 팩터를 DB에 적재.
    이미 DB(factor_snapshot)에 적재돼 있으면 디스크/DB 캐시 히트로 빠르게 끝남."""
    import logging
    log = logging.getLogger("api.main")
    try:
        from src.data.dart_client import _load_full_corp_map
        n = len(_load_full_corp_map())
        log.info(f"사전 워밍: corp_code 맵 {n}개 준비")
    except Exception as e:
        log.warning(f"사전 워밍 corp_code 실패: {e}")
    try:
        from src.data.snapshot_db import ingest_universe
        r = ingest_universe("kospi200")  # 펀더멘털+가격 팩터 → DB 적재(write-through)
        log.info(f"사전 워밍: factor_snapshot 적재 {r}")
    except Exception as e:
        log.warning(f"사전 워밍 적재 실패: {e}")

    # Load symbol master cache (non-blocking)
    try:
        from src.database import get_engine
        from src.kis_master_parser import load_symbol_cache
        engine = get_engine()
        load_symbol_cache(engine)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Symbol cache load skipped: {e}")

# ─── Auto-trading state (in-memory) ─────────────────────────────────────────
trading_config = {"auto_mode": False, "var_limit": 5_000_000, "last_order": None}


# ═══════════════════════════════════════════════════════════════════════════════
# REQUEST MODELS
# ═══════════════════════════════════════════════════════════════════════════════
class VaRRequest(BaseModel):
    ticker: str
    portfolio_value: float
    confidence_level: float = 0.99
    holding_period: int = 1
    use_ewma: bool = True
    start_date: str = "2023-01-01"
    end_date: str = str(date.today())

class PortfolioVaRRequest(BaseModel):
    tickers: list[str]
    weights: list[float]
    portfolio_value: float
    confidence_level: float = 0.99
    use_ewma: bool = True
    start_date: str = "2023-01-01"
    end_date: str = str(date.today())

class StressRequest(BaseModel):
    equity_value: float
    bond_value: float = 0.0
    fx_value: float = 0.0
    portfolio_beta: float = 1.2
    modified_duration: float = 7.0

class OptionRequest(BaseModel):
    S: float; K: float; T: float; r: float; sigma: float
    option_type: str = "call"

class BondRequest(BaseModel):
    face_value: float
    coupon_rate: float
    ytm: float
    years_to_maturity: int
    freq: int = 2

class HedgeRequest(BaseModel):
    portfolio_value: float
    current_beta: float
    target_beta: float = 0.0
    futures_price: float
    multiplier: int = 250000

class AggregateVaRRequest(BaseModel):
    individual_vars: list[float]
    correlation_matrix: list[list[float]]

class AutoTradingConfig(BaseModel):
    auto_mode: bool
    var_limit: float
    username: str = "admin"

class OrderRequest(BaseModel):
    ticker: str
    qty: int
    side: str = "sell"
    username: str = "admin"


# ═══════════════════════════════════════════════════════════════════════════════
# HEALTH CHECK
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/")
def root():
    return {"status": "Risk API is running", "version": "2.0.0",
            "timestamp": datetime.now().isoformat()}

@app.get("/health")
def health():
    return {"status": "ok"}


# ═══════════════════════════════════════════════════════════════════════════════
# VAR ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════
@app.post("/calculate-var")
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


@app.post("/calculate-portfolio-var")
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


@app.post("/aggregate-var")
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


# ═══════════════════════════════════════════════════════════════════════════════
# MONTE CARLO VAR
# ═══════════════════════════════════════════════════════════════════════════════
class MCVaRRequest(BaseModel):
    ticker: str
    portfolio_value: float
    confidence_level: float = 0.99
    holding_period: int = 1
    n_simulations: int = 10000
    use_ewma: bool = True
    ewma_lambda: float = 0.94
    start_date: str = "2023-01-01"
    end_date: str = str(date.today())


class MCPortfolioVaRRequest(BaseModel):
    tickers: list[str]
    weights: list[float]
    portfolio_value: float
    confidence_level: float = 0.99
    holding_period: int = 1
    n_simulations: int = 10000
    use_ewma: bool = True
    ewma_lambda: float = 0.94
    start_date: str = "2023-01-01"
    end_date: str = str(date.today())


@app.post("/mc-var")
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


@app.post("/mc-portfolio-var")
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


# ═══════════════════════════════════════════════════════════════════════════════
# GARCH(1,1) VOLATILITY
# ═══════════════════════════════════════════════════════════════════════════════
class GARCHRequest(BaseModel):
    ticker: str
    start_date: str = "2020-01-01"
    end_date: str = str(date.today())
    ewma_lambda: float = 0.94


@app.post("/garch-compare")
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


# ═══════════════════════════════════════════════════════════════════════════════
# FRTB EXPECTED SHORTFALL
# ═══════════════════════════════════════════════════════════════════════════════
class FRTBRequest(BaseModel):
    ticker: str
    portfolio_value: float
    risk_factor_type: str = "large_cap_equity"
    start_date: str = "2018-01-01"
    end_date: str = str(date.today())


@app.post("/frtb-es")
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


@app.get("/frtb-lh-map")
def frtb_lh_map():
    """Return the FRTB risk factor → liquidity horizon mapping table."""
    return {"liquidity_horizon_map": LIQUIDITY_HORIZON_MAP}


# ═══════════════════════════════════════════════════════════════════════════════
# CVA (Credit Valuation Adjustment)
# ═══════════════════════════════════════════════════════════════════════════════
class CVARequest(BaseModel):
    notional: float
    maturity_years: float = 5.0
    cds_spread_bps: float = 150.0
    recovery_rate: float = 0.40
    risk_free_rate: float = 0.03
    position_type: str = "irs"
    volatility: float = 0.02
    bank_cds_spread_bps: float = 50.0
    bank_recovery: float = 0.40
    spread_shock_bps: float = 100.0
    cds_1y: float = 0.0
    cds_3y: float = 0.0
    cds_5y: float = 0.0
    cds_10y: float = 0.0


@app.post("/calculate-cva")
def calculate_cva(req: CVARequest):
    """
    Full CVA analysis: PD from CDS spreads, EE profile, unilateral CVA,
    bilateral CVA (BCVA), CVA spread, stressed CVA, and optional
    hazard rate term structure bootstrap.
    """
    try:
        engine = CVAEngine(req.risk_free_rate, req.recovery_rate)

        # Build CDS term structure if provided
        cds_ts = None
        ts_input = {1: req.cds_1y, 3: req.cds_3y, 5: req.cds_5y, 10: req.cds_10y}
        ts_valid = {k: v for k, v in ts_input.items() if v > 0}
        if len(ts_valid) >= 2:
            cds_ts = ts_valid

        result = engine.full_cva_report(
            notional=req.notional,
            maturity_years=req.maturity_years,
            cds_spread_bps=req.cds_spread_bps,
            position_type=req.position_type,
            volatility=req.volatility,
            bank_cds_spread_bps=req.bank_cds_spread_bps,
            bank_recovery=req.bank_recovery,
            spread_shock_bps=req.spread_shock_bps,
            cds_term_structure=cds_ts,
        )
        return result
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


# ═══════════════════════════════════════════════════════════════════════════════
# CREDIT SPREAD RISK & IDR
# ═══════════════════════════════════════════════════════════════════════════════
class IRCPositionInput(BaseModel):
    name: str
    rating: str = "BBB"
    notional: float = 1_000_000_000
    modified_duration: float = 5.0
    recovery_rate: float = 0.40
    liquidity_horizon_months: int = 3


class IRCRequest(BaseModel):
    positions: list[IRCPositionInput]
    n_simulations: int = 50000


@app.post("/calculate-irc")
def calculate_irc(req: IRCRequest):
    """
    Incremental Risk Charge: credit spread VaR (rating migration MC)
    + IDR (Vasicek WCDR 99.9%), with liquidity horizon scaling.
    """
    try:
        positions = [
            CreditPosition(
                name=p.name, rating=p.rating.upper(), notional=p.notional,
                modified_duration=p.modified_duration,
                recovery_rate=p.recovery_rate,
                liquidity_horizon_months=p.liquidity_horizon_months,
            )
            for p in req.positions
        ]
        engine = IncrementalRiskCharge()
        return engine.calculate_irc(positions, n_simulations=req.n_simulations)
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@app.get("/credit-transition-matrix")
def credit_transition_matrix():
    """Return the S&P 1Y rating transition matrix and credit spreads."""
    return {
        "ratings": RATING_GRADES,
        "transition_matrix_1y": [
            [round(float(v), 4) for v in row] for row in TRANSITION_MATRIX_1Y
        ],
        "credit_spreads_bps": CREDIT_SPREADS_BPS,
        "default_probabilities": DEFAULT_PROBS,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# DCC-GARCH & WRONG-WAY RISK
# ═══════════════════════════════════════════════════════════════════════════════
class DCCRequest(BaseModel):
    tickers: list[str]
    start_date: str = "2020-01-01"
    end_date: str = str(date.today())


@app.post("/dcc-garch")
def dcc_garch_analysis(req: DCCRequest):
    """
    DCC-GARCH dynamic correlation analysis.

    Fits univariate GARCH(1,1) per asset, then estimates DCC parameters
    for time-varying correlation. Returns dynamic correlation time series,
    GARCH params per asset, and correlation statistics.
    """
    try:
        loader = MarketDataLoader(req.tickers[0], req.start_date, req.end_date)
        df = loader.fetch_multi_returns(req.tickers)

        if len(df) < 60:
            raise HTTPException(400, "최소 60 관측치 필요")

        result = dcc_garch_full_report(df)
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@app.post("/wwr-classify")
def wwr_classify(transaction_type: str = "put_option"):
    """Classify inherent Wrong-Way Risk for a transaction type."""
    return WrongWayRiskDetector.classify_transaction_wwr(transaction_type)


# ═══════════════════════════════════════════════════════════════════════════════
# VaR MAPPING (Principal / Duration / Cash Flow)
# ═══════════════════════════════════════════════════════════════════════════════
class BondInput(BaseModel):
    name: str
    face_value: float
    coupon_rate: float
    maturity_years: int
    ytm: float = 0.0


class VaRMappingRequest(BaseModel):
    bonds: list[BondInput]
    zero_var_pct: dict[str, float]   # JSON keys must be strings
    spot_rates: dict[str, float] = {}


@app.post("/var-mapping")
def var_mapping(req: VaRMappingRequest):
    """
    Compare Principal, Duration, and Cash Flow mapping methods.
    Returns all three VaRs plus diversification benefit.
    """
    try:
        bonds = [
            Bond(
                name=b.name, face_value=b.face_value,
                coupon_rate=b.coupon_rate, maturity_years=b.maturity_years,
                ytm=b.ytm or b.coupon_rate,
            ) for b in req.bonds
        ]
        # Convert string keys back to int
        zvar = {int(k): v for k, v in req.zero_var_pct.items()}
        sr = {int(k): v for k, v in req.spot_rates.items()} if req.spot_rates else None

        engine = VaRMappingEngine(zvar, spot_rates=sr)
        return engine.compare_methods(bonds)
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


# ═══════════════════════════════════════════════════════════════════════════════
# AI VOLATILITY: RF vs LSTM
# ═══════════════════════════════════════════════════════════════════════════════
class AICompareRequest(BaseModel):
    ticker: str
    window: int = 20
    lstm_epochs: int = 30
    start_date: str = "2020-01-01"
    end_date: str = str(date.today())


@app.post("/ai-vol-compare")
def ai_vol_compare(req: AICompareRequest):
    """
    Head-to-head comparison: Random Forest vs LSTM volatility forecast.
    Returns both models' metrics, predictions, and ensemble.
    """
    try:
        from src.models.lstm_engine import TORCH_AVAILABLE, AIModelComparison
        if not TORCH_AVAILABLE:
            raise HTTPException(503, "LSTM 기능은 torch 설치가 필요합니다. `pip install torch` 후 사용하세요.")
        loader = MarketDataLoader(req.ticker, req.start_date, req.end_date)
        returns = loader.fetch_returns()

        if len(returns) < 120:
            raise HTTPException(400, "최소 120일치 데이터 필요 (LSTM 훈련용)")

        cmp = AIModelComparison(returns, window=req.window)
        result = cmp.compare(lstm_epochs=req.lstm_epochs)
        result["ticker"] = req.ticker
        result["n_observations"] = len(returns)
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


class LSTMForecastRequest(BaseModel):
    ticker: str
    n_steps: int = 5
    window: int = 20
    epochs: int = 30
    start_date: str = "2020-01-01"
    end_date: str = str(date.today())


@app.post("/lstm-forecast")
def lstm_forecast(req: LSTMForecastRequest):
    """Multi-step-ahead LSTM volatility forecast."""
    try:
        from src.models.lstm_engine import TORCH_AVAILABLE, LSTMVolatilityEngine
        if not TORCH_AVAILABLE:
            raise HTTPException(503, "LSTM 기능은 torch 설치가 필요합니다. `pip install torch` 후 사용하세요.")
        loader = MarketDataLoader(req.ticker, req.start_date, req.end_date)
        returns = loader.fetch_returns()

        if len(returns) < 120:
            raise HTTPException(400, "최소 120일치 데이터 필요")

        engine = LSTMVolatilityEngine(returns, window=req.window, epochs=req.epochs)
        train_result = engine.train()
        forecasts = engine.predict_n_step(req.n_steps)

        return {
            "ticker": req.ticker,
            "training": train_result,
            "forecasts_daily": [round(f, 8) for f in forecasts],
            "forecasts_annual": [round(f * (252 ** 0.5), 6) for f in forecasts],
            "n_steps": req.n_steps,
            "regime": engine.volatility_regime(),
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


# ═══════════════════════════════════════════════════════════════════════════════
# MULTI-FEATURE AI (Technical Indicators + Volume + VIX)
# ═══════════════════════════════════════════════════════════════════════════════
class MultiFeatureRequest(BaseModel):
    ticker: str
    model_type: str = "random_forest"   # or "gradient_boosting"
    vol_window: int = 20
    use_vix: bool = True
    start_date: str = "2020-01-01"
    end_date: str = str(date.today())


@app.post("/ai-multi-feature")
def ai_multi_feature(req: MultiFeatureRequest):
    """
    Train a multi-feature AI volatility model (19 features from OHLCV + VIX).

    Features: RSI, MACD, Bollinger position, Stochastic, ATR, realized vol
    (5/20/60d), skewness, kurtosis, return autocorr, volume change/ratio,
    OBV change, VIX level/change/MA-ratio.
    """
    try:
        loader = MarketDataLoader(req.ticker, req.start_date, req.end_date)
        ohlcv = loader.fetch_ohlcv()

        vix = None
        if req.use_vix:
            try:
                vix = loader.fetch_vix()
            except Exception:
                vix = None

        if len(ohlcv) < 120:
            raise HTTPException(400, "최소 120일 데이터 필요")

        engine = MultiFeatureVolatilityEngine(
            ohlcv, vix=vix, vol_window=req.vol_window,
            model_type=req.model_type,
        )
        train_result = engine.train()
        if "error" in train_result:
            raise HTTPException(400, train_result["error"])

        next_vol = engine.predict_next()

        return {
            "ticker": req.ticker,
            "model_type": train_result["model_type"],
            "training": train_result,
            "prediction_next_daily": round(next_vol, 8),
            "prediction_next_annual": round(next_vol * (252 ** 0.5), 6),
            "vix_used": vix is not None and not vix.empty,
            "n_observations": len(ohlcv),
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


# ═══════════════════════════════════════════════════════════════════════════════
# AI MODEL MONITORING
# ═══════════════════════════════════════════════════════════════════════════════
class MonitorRequest(BaseModel):
    ticker: str
    vol_window: int = 20
    initial_train_ratio: float = 0.6
    refit_every: int = 20
    use_vix: bool = True
    start_date: str = "2021-01-01"
    end_date: str = str(date.today())


@app.post("/ai-monitor")
def ai_monitor(req: MonitorRequest):
    """
    Full AI model monitoring report.

    Walk-forward backtest, feature drift (PSI + KS), prediction drift,
    concept drift (error autocorrelation), overall health status.
    """
    try:
        loader = MarketDataLoader(req.ticker, req.start_date, req.end_date)
        ohlcv = loader.fetch_ohlcv()
        returns = np.log(ohlcv["Close"] / ohlcv["Close"].shift(1)).dropna()
        returns.name = req.ticker

        vix = None
        if req.use_vix:
            try:
                vix = loader.fetch_vix()
            except Exception:
                vix = None

        if len(ohlcv) < 200:
            raise HTTPException(400, "모니터링에는 최소 200일 데이터 필요")

        monitor = ModelMonitor(
            ohlcv, returns, vix=vix,
            vol_window=req.vol_window,
            initial_train_ratio=req.initial_train_ratio,
            refit_every=req.refit_every,
        )
        report = monitor.full_report()
        if "error" in report:
            raise HTTPException(400, report["error"])

        report["ticker"] = req.ticker
        return report
    except HTTPException:
        raise
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


# ═══════════════════════════════════════════════════════════════════════════════
# STRATEGY BACKTESTING ENGINE
# ═══════════════════════════════════════════════════════════════════════════════
class StrategyRequest(BaseModel):
    ticker: str
    strategy: str = "SMA Crossover"
    params: dict = {}
    commission: float = 0.001
    slippage: float = 0.0005
    initial_capital: float = 100000000
    start_date: str = "2020-01-01"
    end_date: str = str(date.today())


@app.post("/strategy-backtest")
def strategy_backtest(req: StrategyRequest):
    """Run a single strategy backtest with full performance metrics."""
    try:
        strategy_fn = STRATEGY_REGISTRY.get(req.strategy)
        if not strategy_fn:
            raise HTTPException(400, f"Unknown strategy: {req.strategy}. "
                                f"Available: {list(STRATEGY_REGISTRY.keys())}")

        loader = MarketDataLoader(req.ticker, req.start_date, req.end_date)
        prices = loader.fetch_prices()

        if len(prices) < 60:
            raise HTTPException(400, "Need at least 60 trading days of data")

        # Run strategy
        params = {**req.params, "commission": req.commission, "slippage": req.slippage}
        result = strategy_fn(prices, **params)

        # Compute metrics
        perf = compute_performance_metrics(
            result["equity_curve"],
            result["returns"],
            benchmark_returns=result["benchmark_returns"],
        )
        trade_stats = compute_trade_metrics(result["trades"])

        # Serialize equity curve
        eq = result["equity_curve"] * req.initial_capital
        dates = eq.index.strftime("%Y-%m-%d").tolist() if hasattr(eq.index, "strftime") \
            else list(range(len(eq)))

        # Benchmark equity
        bench_eq = ((1 + result["benchmark_returns"]).cumprod() * req.initial_capital)

        # Drawdown series
        rolling_max = eq.cummax()
        drawdown = ((eq - rolling_max) / rolling_max * 100)

        return {
            "ticker": req.ticker,
            "strategy": req.strategy,
            "params": result.get("params", {}),
            "performance": perf,
            "trades": trade_stats,
            "trade_list": result["trades"][:100],  # limit to 100 trades
            "equity_curve": {
                "dates": dates,
                "strategy": [round(float(v), 0) for v in eq.values],
                "benchmark": [round(float(v), 0) for v in bench_eq.values],
                "drawdown_pct": [round(float(v), 2) for v in drawdown.values],
            },
            "initial_capital": req.initial_capital,
            "n_days": len(prices),
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


# ═══════════════════════════════════════════════════════════════════════════════
# KIS SSoT PIPELINE — .kis.yaml / StrategySchema 통합 파이프라인
# ═══════════════════════════════════════════════════════════════════════════════

class StrategyBuildRequest(BaseModel):
    """전략 빌드 요청 — builder_state JSON → StrategySchema"""
    builder_state: dict             # 프론트엔드 BuilderState
    param_overrides: dict = {}      # 파라미터 오버라이드


class YamlImportRequest(BaseModel):
    content: str                    # .kis.yaml 문자열
    param_overrides: dict = {}


class YamlValidateRequest(BaseModel):
    content: str


class PresetsRequest(BaseModel):
    strategy_id: str
    param_overrides: dict = {}


@app.post("/api/v1/strategies/build")
def kis_build_strategy(req: StrategyBuildRequest):
    """
    BuilderState → StrategySchema 변환.

    프론트엔드의 비주얼 빌더 상태를 SSoT StrategySchema로 변환합니다.
    응답에 YAML 문자열과 Python 미리보기 코드도 함께 반환합니다.
    """
    try:
        from src.kis_converters import from_dict
        from src.kis_yaml_io import StrategyFileSaver

        # BuilderState를 from_dict가 이해하는 형식으로 변환
        schema = from_dict(req.builder_state)

        # YAML 직렬화
        yaml_str = StrategyFileSaver.to_yaml_string(schema)

        return {
            "schema": schema.model_dump(),
            "yaml": yaml_str,
            "id": schema.id,
            "name": schema.name,
        }
    except Exception as e:
        logger.warning(f"입력 검증 실패: {e}")
        raise HTTPException(400, f"입력 오류: {e}")


@app.post("/api/v1/files/validate")
def kis_validate_yaml(req: YamlValidateRequest):
    """.kis.yaml 문자열 검증."""
    try:
        from src.kis_yaml_io import StrategyFileLoader
        errors = StrategyFileLoader.validate_content(req.content)
        return {"valid": len(errors) == 0, "errors": errors}
    except Exception as e:
        return {"valid": False, "errors": [str(e)]}


@app.post("/api/v1/files/import")
def kis_import_yaml(req: YamlImportRequest):
    """
    .kis.yaml 문자열 → StrategySchema.

    YAML을 파싱하여 SSoT 스키마로 변환 + YAML/Python 미리보기 반환.
    """
    try:
        from src.kis_yaml_io import StrategyFileLoader, StrategyFileSaver

        # 먼저 검증
        errors = StrategyFileLoader.validate_content(req.content)
        if errors:
            raise HTTPException(400, f"Invalid YAML: {'; '.join(errors)}")

        schema = StrategyFileLoader.load_schema_with_params(
            req.content, param_overrides=req.param_overrides or None
        )
        yaml_str = StrategyFileSaver.to_yaml_string(schema)

        return {
            "schema": schema.model_dump(),
            "yaml": yaml_str,
            "id": schema.id,
            "name": schema.name,
            "category": schema.category,
            "num_indicators": len(schema.indicators),
            "has_risk": schema.risk is not None,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"입력 검증 실패: {e}")
        raise HTTPException(400, f"입력 오류: {e}")


@app.post("/api/v1/files/export")
def kis_export_yaml(req: StrategyBuildRequest):
    """
    BuilderState → .kis.yaml 문자열 다운로드.

    프론트엔드에서 Export 버튼 클릭 시 호출.
    """
    try:
        from src.kis_converters import from_dict
        from src.kis_yaml_io import StrategyFileSaver

        schema = from_dict(req.builder_state)
        yaml_str = StrategyFileSaver.to_yaml_string(schema)

        return {
            "filename": f"{schema.id}.kis.yaml",
            "content": yaml_str,
            "size": len(yaml_str.encode()),
        }
    except Exception as e:
        logger.warning(f"입력 검증 실패: {e}")
        raise HTTPException(400, f"입력 오류: {e}")


@app.get("/api/v1/strategies/templates")
def kis_list_templates():
    """10개 프리셋 전략의 .kis.yaml 템플릿 반환."""
    from src.kis_strategies.strategies import STRATEGY_REGISTRY, list_strategies
    from src.kis_yaml_io import StrategyFileSaver

    templates = []
    for strat_info in list_strategies():
        name = strat_info["name"]
        cls = STRATEGY_REGISTRY.get(name)
        if cls is None:
            continue
        try:
            instance = cls()
            yaml_str = StrategyFileSaver.to_yaml_string(_strategy_instance_to_schema(instance))
            templates.append({
                "id": strat_info["class"],
                "name": name,
                "required_days": strat_info["required_days"],
                "yaml": yaml_str,
            })
        except Exception:
            continue

    return {"templates": templates}


def _strategy_instance_to_schema(instance):
    """Strategy 인스턴스 → StrategySchema (간단한 변환)."""
    from src.kis_schema import (
        ConditionSchema,
        OperatorType,
        StrategySchema,
    )
    return StrategySchema(
        id=instance.__class__.__name__.lower().replace("strategy", ""),
        name=instance.name,
        category="custom",
        description=str(instance),
        indicators=[],
        entry=ConditionSchema(
            operator=OperatorType.GREATER_THAN, indicator="close", value=0
        ),
        exit=ConditionSchema(
            operator=OperatorType.LESS_THAN, indicator="close", value=99999999
        ),
    )


class ImportAndBacktestRequest(BaseModel):
    yaml_content: str
    symbols: list = ["005930"]
    start_date: str = "2022-01-01"
    end_date: str | None = None
    initial_capital: float = 100_000_000
    param_overrides: dict = {}


@app.post("/api/v1/strategies/import-and-backtest")
def kis_import_and_backtest(req: ImportAndBacktestRequest):
    """
    .kis.yaml Import → 즉시 백테스트 실행.

    Strategy Builder Export → Backtester의 완전한 워크플로우를 단일 API로 지원.
    """
    from src.kis_strategies.strategies import get_strategy
    from src.kis_yaml_io import StrategyFileLoader

    try:
        schema = StrategyFileLoader.load_schema_with_params(
            req.yaml_content, req.param_overrides or None
        )
    except Exception as e:
        raise HTTPException(400, f"Invalid YAML: {e}")

    end = req.end_date or str(date.today())
    strategy = get_strategy(schema.name) or get_strategy(schema.id)

    if strategy is None:
        raise HTTPException(400, f"Strategy '{schema.name}' not found. Use /api/v1/strategies/dsl/backtest for DSL.")

    try:
        from src.kis_backtest_engine import run_backtest
        return run_backtest(
            symbols=req.symbols,
            strategy_name=schema.name,
            start_date=req.start_date,
            end_date=end,
            initial_capital=req.initial_capital,
        )
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


# ═══════════════════════════════════════════════════════════════════════════════
# KIS BACKTEST ENGINE — Pure Python simulation (DB-backed, no Lean/Docker)
# ═══════════════════════════════════════════════════════════════════════════════

class KISBacktestRequest(BaseModel):
    symbols: list[str]
    strategy: str
    params: dict = {}
    start_date: str = "2022-01-01"
    end_date: str = str(date.today())
    initial_capital: float = 100_000_000
    commission_rate: float = 0.0015
    slippage_rate: float = 0.0005
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    max_positions: int = 5


@app.post("/api/v1/strategies/backtest")
def kis_run_backtest(req: KISBacktestRequest):
    """
    KIS 전략 기반 순수 Python 백테스트.
    DB의 daily_prices에서 OHLCV를 읽어 날짜별 시뮬레이션을 수행합니다.
    Lean/Docker 의존성 없이 동작합니다.
    """
    try:
        from src.kis_backtest_engine import run_backtest
        return run_backtest(
            symbols=req.symbols,
            strategy_name=req.strategy,
            start_date=req.start_date,
            end_date=req.end_date,
            strategy_params=req.params,
            initial_capital=req.initial_capital,
            commission_rate=req.commission_rate,
            slippage_rate=req.slippage_rate,
            stop_loss_pct=req.stop_loss_pct,
            take_profit_pct=req.take_profit_pct,
            max_positions=req.max_positions,
        )
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


class OptimizeRequest(BaseModel):
    symbols: list[str]
    strategy: str
    param_ranges: dict   # {"short_period": {"min":2,"max":20,"step":1}, ...}
    start_date: str = "2022-01-01"
    end_date: str = str(date.today())
    initial_capital: float = 100_000_000
    commission_rate: float = 0.0015
    max_combinations: int = 200   # safety cap


@app.post("/api/v1/strategies/optimize")
def kis_optimize(req: OptimizeRequest):
    """
    Grid Search 파라미터 최적화.
    param_ranges의 조합으로 백테스트를 순차 실행하고 Sharpe 최고값을 반환.
    최대 max_combinations 조합으로 제한.
    """
    try:
        import itertools

        from src.kis_backtest_engine import run_backtest

        # Build grid
        param_names = list(req.param_ranges.keys())
        param_values = []
        for _name, rng in req.param_ranges.items():
            mn, mx, step = rng["min"], rng["max"], rng.get("step", 1)
            vals = []
            v = float(mn)
            while v <= float(mx) + 1e-9:
                vals.append(round(v, 6))
                v += float(step)
            param_values.append(vals)

        all_combos = list(itertools.product(*param_values))
        if len(all_combos) > req.max_combinations:
            import random
            random.seed(42)
            all_combos = random.sample(all_combos, req.max_combinations)

        grid_results = []
        best = {"sharpe": -999, "params": {}, "return": 0, "drawdown": 0, "trades": 0}

        for combo in all_combos:
            params = dict(zip(param_names, combo))
            try:
                r = run_backtest(
                    symbols=req.symbols,
                    strategy_name=req.strategy,
                    start_date=req.start_date,
                    end_date=req.end_date,
                    strategy_params=params,
                    initial_capital=req.initial_capital,
                    commission_rate=req.commission_rate,
                )
                if r.get("error"):
                    continue
                stats = r["result"]["statistics"]
                sharpe = stats.get("sharpe_ratio", 0)
                ret    = stats.get("total_return_pct", 0)
                mdd    = stats.get("max_drawdown_pct", 0)
                trades = stats.get("num_trades", 0)

                grid_results.append({
                    "params": params,
                    "sharpe": round(sharpe, 4),
                    "return_pct": round(ret, 3),
                    "max_drawdown": round(mdd, 3),
                    "num_trades": trades,
                })

                if sharpe > best["sharpe"]:
                    best = {"sharpe": sharpe, "params": params,
                            "return": ret, "drawdown": mdd, "trades": trades}
            except Exception:
                continue

        return {
            "best_params":    best["params"],
            "best_sharpe":    round(best["sharpe"], 4),
            "best_return":    round(best["return"], 3),
            "best_drawdown":  round(best["drawdown"], 3),
            "total_tested":   len(grid_results),
            "grid":           grid_results,
        }
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


# ═══════════════════════════════════════════════════════════════════════════════
# KIS STRATEGY ENGINE — Signal-based endpoints (Signal 객체 반환)
# ═══════════════════════════════════════════════════════════════════════════════

class KISSignalRequest(BaseModel):
    stock_code: str           # 종목코드 (6자리)
    stock_name: str = ""
    strategy: str             # 전략명 (STRATEGY_REGISTRY 키)
    params: dict = {}         # 전략 파라미터 (선택)


class KISBatchSignalRequest(BaseModel):
    stocks: list[dict]        # [{"code": "005930", "name": "삼성전자"}, ...]
    strategy: str
    params: dict = {}


@app.post("/api/v1/strategies/signal")
def kis_generate_signal(req: KISSignalRequest):
    """
    단일 종목에 대해 KIS 전략 시그널 생성.

    data_fetcher가 DB의 daily_prices를 읽으므로
    KIS API를 직접 호출하지 않습니다.
    """
    try:
        from src.kis_strategies.strategies import get_strategy
        strategy = get_strategy(req.strategy, **req.params)
        if strategy is None:
            raise HTTPException(400, f"Unknown strategy: {req.strategy}")

        signal = strategy.generate_signal(
            req.stock_code,
            req.stock_name or req.stock_code,
        )
        return {
            "stock_code": signal.stock_code,
            "stock_name": signal.stock_name,
            "action": signal.action.value,
            "strength": signal.strength,
            "reason": signal.reason,
            "is_actionable": signal.is_actionable(),
            "is_strong": signal.is_strong(),
            "strategy": strategy.name,
            "timestamp": signal.timestamp.isoformat(),
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@app.post("/api/v1/strategies/batch-signal")
def kis_batch_signal(req: KISBatchSignalRequest):
    """
    여러 종목에 대해 시그널을 일괄 생성.
    BUY/SELL 시그널만 걸러서 반환합니다.
    """
    try:
        from src.kis_signal import Action
        from src.kis_strategies.strategies import get_strategy

        strategy = get_strategy(req.strategy, **req.params)
        if strategy is None:
            raise HTTPException(400, f"Unknown strategy: {req.strategy}")

        results = []
        for stock in req.stocks:
            code = stock.get("code", stock.get("ticker", ""))
            name = stock.get("name", code)
            if not code:
                continue
            try:
                signal = strategy.generate_signal(code, name)
                if signal.action != Action.HOLD:
                    results.append({
                        "stock_code": signal.stock_code,
                        "stock_name": signal.stock_name,
                        "action": signal.action.value,
                        "strength": signal.strength,
                        "reason": signal.reason,
                    })
            except Exception:
                continue

        # 강도 내림차순 정렬
        results.sort(key=lambda x: x["strength"], reverse=True)
        return {
            "strategy": strategy.name,
            "total_scanned": len(req.stocks),
            "signals": results,
            "buy_count": sum(1 for r in results if r["action"] == "buy"),
            "sell_count": sum(1 for r in results if r["action"] == "sell"),
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@app.get("/api/v1/strategies/list")
def kis_list_strategies():
    """등록된 KIS 전략 목록과 파라미터 정보 반환."""
    from src.kis_strategies.strategies import list_strategies
    return {"strategies": list_strategies()}


# ── DSL-based custom strategy ─────────────────────────────────────────────────

class DSLValidateRequest(BaseModel):
    expression: str


class DSLBacktestRequest(BaseModel):
    name: str = "Custom DSL Strategy"
    buy_condition: str
    sell_condition: str = ""
    symbols: list[str]
    start_date: str = "2022-01-01"
    end_date: str = str(date.today())
    initial_capital: float = 100_000_000
    commission_rate: float = 0.0015
    slippage_rate: float = 0.0005
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    max_positions: int = 5


@app.post("/api/v1/strategies/dsl/validate")
def dsl_validate(req: DSLValidateRequest):
    """DSL 수식 실시간 유효성 검사."""
    from src.kis_dsl_executor import parse_and_validate
    valid, msg = parse_and_validate(req.expression)
    return {"valid": valid, "message": msg}


@app.post("/api/v1/strategies/dsl/backtest")
def dsl_backtest(req: DSLBacktestRequest):
    """
    사용자 정의 DSL 수식으로 백테스트 실행.

    Example buy_condition: "ma(5) crosses_above ma(20)"
    Example sell_condition: "ma(5) crosses_below ma(20)"
    """
    try:
        from src.kis_backtest_engine import BacktestConfig, BacktestEngine
        from src.kis_dsl_executor import dsl_to_strategy

        strategy = dsl_to_strategy(req.name, req.buy_condition, req.sell_condition)

        # BacktestEngine에 DSL 전략 주입
        cfg = BacktestConfig(
            symbols=req.symbols,
            strategy_name="__dsl__",
            strategy_params={},
            start_date=req.start_date,
            end_date=req.end_date,
            initial_capital=req.initial_capital,
            commission_rate=req.commission_rate,
            slippage_rate=req.slippage_rate,
            stop_loss_pct=req.stop_loss_pct,
            take_profit_pct=req.take_profit_pct,
            max_positions=req.max_positions,
        )
        engine = BacktestEngine(cfg)

        # strategy_name을 무시하고 주입된 strategy 객체 사용
        from datetime import datetime as _dt
        from datetime import timedelta

        import pandas as pd

        from src.kis_backtest_engine import load_ohlcv

        warmup_start = (
            _dt.strptime(req.start_date, "%Y-%m-%d")
            - timedelta(days=strategy.required_days + 30)
        ).strftime("%Y-%m-%d")

        ohlcv_map = {}
        for ticker in req.symbols:
            df = load_ohlcv(ticker, warmup_start, req.end_date)
            if not df.empty:
                ohlcv_map[ticker] = df

        if not ohlcv_map:
            raise HTTPException(400, "No OHLCV data found in DB")

        ref_ticker = max(ohlcv_map, key=lambda t: len(ohlcv_map[t]))
        all_dates = ohlcv_map[ref_ticker].index
        sim_dates = all_dates[all_dates >= pd.Timestamp(req.start_date)]

        from src.kis_signal import Action
        for sim_date in sim_dates:
            date_str = sim_date.strftime("%Y-%m-%d")
            for ticker, pos in list(engine.positions.items()):
                if ticker in ohlcv_map:
                    df_to = ohlcv_map[ticker].loc[:sim_date]
                    if not df_to.empty:
                        engine._check_risk_triggers(
                            ticker, pos, float(df_to["close"].iloc[-1]), date_str
                        )
            for ticker in req.symbols:
                if ticker not in ohlcv_map:
                    continue
                df_slice = ohlcv_map[ticker].loc[:sim_date]
                if len(df_slice) < strategy.required_days:
                    continue
                signal = engine._generate_signal_as_of(strategy, ticker, df_slice)
                if signal is None:
                    continue
                curr_price = float(df_slice["close"].iloc[-1])
                if signal.action == Action.BUY and signal.is_actionable():
                    engine._execute_buy(ticker, curr_price, date_str, signal.reason)
                elif signal.action == Action.SELL and signal.is_actionable():
                    engine._execute_sell(ticker, curr_price, date_str, signal.reason)
            equity = engine._calc_equity(ohlcv_map, sim_date)
            engine.equity_history.append((date_str, equity))

        return engine._build_result(0.0, ohlcv_map)

    except HTTPException:
        raise
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


# ── Portfolio Analyzer ────────────────────────────────────────────────────────

class PortfolioAnalyzeRequest(BaseModel):
    tickers: list[str]
    start_date: str = "2022-01-01"
    end_date: str = str(date.today())
    weights: dict | None = None
    compute_frontier: bool = True
    compute_optimal: bool = True


class RebalanceRequest(BaseModel):
    tickers: list[str]
    start_date: str = "2022-01-01"
    end_date: str = str(date.today())
    weights: dict | None = None
    frequency: str = "monthly"   # monthly | quarterly | annually
    initial_capital: float = 100_000_000
    commission_rate: float = 0.0015


@app.post("/api/v1/portfolio/analyze")
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


@app.post("/api/v1/portfolio/rebalance")
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


class GridSearchRequest(BaseModel):
    ticker: str
    strategy: str = "SMA Crossover"
    param_grid: dict = {"fast_period": [10, 20, 30], "slow_period": [40, 50, 60]}
    commission: float = 0.001
    slippage: float = 0.0005
    metric: str = "sharpe_ratio"
    start_date: str = "2020-01-01"
    end_date: str = str(date.today())


@app.post("/strategy-optimize")
def strategy_optimize(req: GridSearchRequest):
    """Grid search parameter optimization for a strategy."""
    try:
        loader = MarketDataLoader(req.ticker, req.start_date, req.end_date)
        prices = loader.fetch_prices()

        if len(prices) < 60:
            raise HTTPException(400, "Need at least 60 trading days of data")

        # Convert param_grid values to proper types
        param_grid = {}
        for k, v in req.param_grid.items():
            if isinstance(v, list):
                param_grid[k] = [int(x) if isinstance(x, float) and x == int(x) else x
                                  for x in v]
            else:
                param_grid[k] = v

        result = grid_search(
            prices, req.strategy, param_grid,
            commission=req.commission, slippage=req.slippage,
            metric=req.metric,
        )

        if "error" in result:
            raise HTTPException(400, result["error"])

        # Don't return the full equity curve from grid search
        if result.get("best_result"):
            del result["best_result"]

        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


class PortfolioBacktestRequest(BaseModel):
    tickers: list[str]
    weights: list[float]
    rebalance_freq: str = "monthly"
    commission: float = 0.001
    initial_capital: float = 100000000
    start_date: str = "2020-01-01"
    end_date: str = str(date.today())


@app.post("/portfolio-backtest")
def run_portfolio_backtest(req: PortfolioBacktestRequest):
    """Multi-asset portfolio backtest with rebalancing."""
    try:
        if len(req.tickers) != len(req.weights):
            raise HTTPException(400, "Tickers and weights must have same length")
        if len(req.tickers) < 2:
            raise HTTPException(400, "Need at least 2 tickers")

        # Fetch prices for each ticker
        price_dict = {}
        for ticker in req.tickers:
            loader = MarketDataLoader(ticker, req.start_date, req.end_date)
            price_dict[ticker] = loader.fetch_prices()

        weights = dict(zip(req.tickers, req.weights))

        result = portfolio_backtest(
            price_dict, weights,
            rebalance_freq=req.rebalance_freq,
            commission=req.commission,
        )

        if "error" in result:
            raise HTTPException(400, result["error"])

        # Scale equity curve by initial capital
        eq = result["equity_curve"]
        eq["portfolio"] = [round(v * req.initial_capital, 0) for v in eq["portfolio"]]
        eq["benchmark"] = [round(v * req.initial_capital, 0) for v in eq["benchmark"]]

        result["initial_capital"] = req.initial_capital
        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


# ═══════════════════════════════════════════════════════════════════════════════
# MULTI-CONDITION SIGNAL ENGINE
# ═══════════════════════════════════════════════════════════════════════════════
class MultiConditionRequest(BaseModel):
    ticker: str
    entry_conditions: list[dict]
    entry_logic: str = "AND"
    exit_conditions: list[dict] = []
    exit_logic: str = "OR"
    trailing_stop_pct: float = 0
    take_profit_pct: float = 0
    stop_loss_pct: float = 0
    time_exit_days: int = 0
    commission: float = 0.001
    slippage: float = 0.0005
    initial_capital: float = 100000000
    start_date: str = "2015-01-01"
    end_date: str = str(date.today())


@app.post("/multi-condition-backtest")
def run_multi_condition(req: MultiConditionRequest):
    """Multi-condition strategy backtest with advanced exit logic."""
    try:
        loader = MarketDataLoader(req.ticker, req.start_date, req.end_date)
        prices = loader.fetch_prices()
        if len(prices) < 60:
            raise HTTPException(400, "Need at least 60 days of data")

        result = multi_condition_backtest(
            prices,
            entry_conditions=req.entry_conditions,
            entry_logic=req.entry_logic,
            exit_conditions=req.exit_conditions or None,
            exit_logic=req.exit_logic,
            trailing_stop_pct=req.trailing_stop_pct or None,
            take_profit_pct=req.take_profit_pct or None,
            stop_loss_pct=req.stop_loss_pct or None,
            time_exit_days=req.time_exit_days or None,
            commission=req.commission,
            slippage=req.slippage,
        )

        perf = compute_performance_metrics(
            result["equity_curve"], result["returns"],
            benchmark_returns=result["benchmark_returns"],
        )
        trade_stats = compute_trade_metrics(result["trades"])

        eq = result["equity_curve"] * req.initial_capital
        bench_eq = (1 + result["benchmark_returns"]).cumprod() * req.initial_capital
        rolling_max = eq.cummax()
        dd = ((eq - rolling_max) / rolling_max * 100)

        dates = eq.index.strftime("%Y-%m-%d").tolist() \
            if hasattr(eq.index, "strftime") else list(range(len(eq)))

        return {
            "ticker": req.ticker,
            "performance": perf,
            "trades": trade_stats,
            "trade_list": result["trades"][:100],
            "equity_curve": {
                "dates": dates,
                "strategy": [round(float(v), 0) for v in eq.values],
                "benchmark": [round(float(v), 0) for v in bench_eq.values],
                "drawdown_pct": [round(float(v), 2) for v in dd.values],
            },
            "entry_conditions": result["entry_conditions"],
            "exit_params": result["exit_params"],
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@app.get("/condition-registry")
def get_condition_registry():
    """Return available conditions with descriptions and recommended tickers."""
    return CONDITION_REGISTRY


# ═══════════════════════════════════════════════════════════════════════════════
# PORTFOLIO OPTIMIZER (MARKOWITZ)
# ═══════════════════════════════════════════════════════════════════════════════
class EfficientFrontierRequest(BaseModel):
    tickers: list[str]
    n_portfolios: int = 3000
    risk_free_rate: float = 0.03
    start_date: str = "2015-01-01"
    end_date: str = str(date.today())


@app.post("/efficient-frontier")
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


class RankingRequest(BaseModel):
    tickers: list[str]
    method: str = "momentum_12m"
    top_n: int = 5
    start_date: str = "2015-01-01"
    end_date: str = str(date.today())


@app.post("/rank-assets")
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


# ═══════════════════════════════════════════════════════════════════════════════
# ADVANCED RISK ANALYTICS
# ═══════════════════════════════════════════════════════════════════════════════
class HoldingPeriodVaRRequest(BaseModel):
    ticker: str
    holding_periods: list[int] = [1, 5, 10, 20]
    confidence_levels: list[float] = [0.95, 0.99]
    portfolio_value: float = 100000000
    method: str = "parametric"
    start_date: str = "2015-01-01"
    end_date: str = str(date.today())


@app.post("/holding-period-var")
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


class MCPathRequest(BaseModel):
    ticker: str
    n_paths: int = 500
    n_days: int = 252
    start_date: str = "2015-01-01"
    end_date: str = str(date.today())


@app.post("/mc-paths")
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


class RollingStatsRequest(BaseModel):
    ticker: str
    window: int = 252
    start_date: str = "2015-01-01"
    end_date: str = str(date.today())


@app.post("/rolling-sharpe")
def run_rolling_sharpe(req: RollingStatsRequest):
    """Rolling Sharpe ratio timeline."""
    try:
        loader = MarketDataLoader(req.ticker, req.start_date, req.end_date)
        returns = loader.fetch_returns()
        return rolling_sharpe(returns, window=req.window)
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


# ═══════════════════════════════════════════════════════════════════════════════
# MARKET SCREENER (PostgreSQL-offloaded)
# ═══════════════════════════════════════════════════════════════════════════════
from sqlalchemy import text as _sql_text

from src.screener_pipeline import refresh_all_snapshots
from src.screener_sql import ALLOWED_FACTORS, build_screener_sql


class ScreenerRequest(BaseModel):
    universe: str  # "equity" or "ficc"
    conditions: dict  # {"A": {"field": "per", "operator": "<", "value": 15}, ...}
    logic_expression: str
    sort_by: str = None
    limit: int = 100


@app.post("/screener")
def run_screener(req: ScreenerRequest):
    """
    Execute a screener query entirely in PostgreSQL.

    The client sends alphabet-labeled conditions and a logic expression like
    `(A AND B) OR C`. The server whitelists fields/operators, builds a
    parameterized WHERE clause, and executes it against the snapshot tables.

    All filtering runs in the DB engine. No Pandas, no in-memory aggregation.
    """
    try:
        sql, params = build_screener_sql(
            universe=req.universe,
            conditions=req.conditions,
            logic_expression=req.logic_expression,
            sort_by=req.sort_by,
            limit=req.limit,
        )
    except ValueError as e:
        logger.warning(f"입력 검증 실패: {e}")
        raise HTTPException(status_code=400, detail=f"입력 오류: {e}")

    try:
        from src.database import get_engine
        engine = get_engine()
        with engine.connect() as conn:
            result = conn.execute(_sql_text(sql), params)
            rows = [dict(r._mapping) for r in result.fetchall()]
            # Serialize datetime fields
            for row in rows:
                for k, v in list(row.items()):
                    if hasattr(v, "isoformat"):
                        row[k] = v.isoformat()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB query failed: {e}")

    return {
        "universe": req.universe,
        "count": len(rows),
        "results": rows,
        "sql": sql,  # for debugging / transparency
    }


@app.get("/screener/factors")
def get_screener_factors():
    """Return allowed factors per universe (whitelist)."""
    return {k: sorted(v) for k, v in ALLOWED_FACTORS.items()}


@app.post("/screener/refresh")
async def manual_refresh_screener():
    """Manually trigger a snapshot refresh (admin endpoint)."""
    try:
        from src.database import get_engine
        engine = get_engine()
        result = await refresh_all_snapshots(engine)
        return result
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@app.get("/screener/status")
def screener_status():
    """Return row counts + latest update timestamps."""
    try:
        from src.database import get_engine
        engine = get_engine()
        with engine.connect() as conn:
            eq_count = conn.execute(
                _sql_text("SELECT COUNT(*) FROM market_snapshot_equity")
            ).scalar()
            ficc_count = conn.execute(
                _sql_text("SELECT COUNT(*) FROM market_snapshot_ficc")
            ).scalar()
            try:
                eq_updated = conn.execute(
                    _sql_text("SELECT MAX(updated_at) FROM market_snapshot_equity")
                ).scalar()
            except Exception:
                eq_updated = None
            try:
                ficc_updated = conn.execute(
                    _sql_text("SELECT MAX(updated_at) FROM market_snapshot_ficc")
                ).scalar()
            except Exception:
                ficc_updated = None
        return {
            "equity_rows": eq_count or 0,
            "ficc_rows": ficc_count or 0,
            "equity_updated_at": eq_updated.isoformat() if eq_updated else None,
            "ficc_updated_at": ficc_updated.isoformat() if ficc_updated else None,
        }
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


# ═══════════════════════════════════════════════════════════════════════════════
# BACKTESTING
# ═══════════════════════════════════════════════════════════════════════════════
@app.post("/backtest-var")
def backtest_var(req: VaRRequest):
    try:
        loader  = MarketDataLoader(req.ticker, req.start_date, req.end_date)
        returns = loader.fetch_returns()

        model   = ParametricRiskModel(req.confidence_level, req.use_ewma)
        var_pct = model.calculate_var(returns)
        var_amt = var_pct * req.portfolio_value

        actual_pnl = returns * req.portfolio_value
        var_series = pd.Series(var_amt, index=returns.index)

        backtester = VaRBacktester(req.confidence_level)
        result     = backtester.run_kupiec_test(actual_pnl, var_series)
        basel      = backtester.basel_zone(result["exceptions"])
        christo    = backtester.christoffersen_test(actual_pnl, var_series)

        exceptions_dates = returns.index[result["exception_series"]].strftime("%Y-%m-%d").tolist()

        return {
            "kupiec":           {k: v for k, v in result.items() if k != "exception_series"},
            "basel":            basel,
            "christoffersen":   christo,
            "exception_dates":  exceptions_dates,
            "pnl_series":       actual_pnl.round(0).tolist(),
            "var_line":         (-var_series).tolist(),
            "dates":            returns.index.strftime("%Y-%m-%d").tolist(),
        }
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


# ═══════════════════════════════════════════════════════════════════════════════
# PIT-BASED BACKTESTING (Full Distribution Validation)
# ═══════════════════════════════════════════════════════════════════════════════
class PITBacktestRequest(BaseModel):
    ticker: str
    confidence_level: float = 0.99
    start_date: str = "2020-01-01"
    end_date: str = str(date.today())
    use_ewma: bool = True
    ewma_lambda: float = 0.94
    rolling_window: int = 60


@app.post("/backtest-pit")
def backtest_pit(req: PITBacktestRequest):
    """
    PIT-based VaR backtest: validates the ENTIRE forecasted distribution.

    Tests performed:
      - Kolmogorov-Smirnov (KS):  max CDF deviation from U[0,1]
      - Anderson-Darling (AD):    tail-weighted GoF (risk manager's choice)
      - Cramér-von Mises (CvM):   mean squared CDF deviation
      - Berkowitz Independence:    AR(1) serial correlation in PIT → N(0,1)

    Returns test results, QQ plot data, and PIT histogram for visualization.
    """
    try:
        loader  = MarketDataLoader(req.ticker, req.start_date, req.end_date)
        returns = loader.fetch_returns()

        pit_tester = PITBacktester(req.confidence_level)
        result = pit_tester.run_full_pit_backtest(
            returns,
            window=req.rolling_window,
            use_ewma=req.use_ewma,
            ewma_lambda=req.ewma_lambda,
        )

        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])

        return result
    except HTTPException:
        raise
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")
# ═══════════════════════════════════════════════════════════════════════════════
@app.post("/stress-test")
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


# ═══════════════════════════════════════════════════════════════════════════════
# FICC ANALYTICS
# ═══════════════════════════════════════════════════════════════════════════════
@app.post("/analyze-option")
def analyze_option(req: OptionRequest):
    try:
        return FICCEngine.bs_greeks(req.S, req.K, req.T, req.r, req.sigma, req.option_type)
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")

@app.post("/analyze-bond")
def analyze_bond(req: BondRequest):
    try:
        return FICCEngine.bond_analytics(
            req.face_value, req.coupon_rate, req.ytm,
            req.years_to_maturity, req.freq
        )
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


# ═══════════════════════════════════════════════════════════════════════════════
# HEDGING
# ═══════════════════════════════════════════════════════════════════════════════
@app.post("/calculate-hedge")
def calculate_hedge(req: HedgeRequest):
    try:
        sim = HedgingSimulator(req.futures_price, req.multiplier)
        return sim.equity_futures_hedge(
            req.portfolio_value, req.current_beta, req.target_beta
        )
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


# ═══════════════════════════════════════════════════════════════════════════════
# BROKER / ACCOUNT
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/sync-broker")
def sync_broker():
    try:
        broker    = KoreaInvestmentAPI()
        holdings  = broker.fetch_portfolio()
        total_val = sum(h["total_value"] for h in holdings)
        return {"status": "success", "total_value": total_val, "holdings": holdings}
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")

@app.post("/place-order")
def place_order(req: OrderRequest):
    try:
        broker = KoreaInvestmentAPI()
        result = broker.place_order(req.ticker, req.qty, req.side)
        log_trade(req.username, req.ticker, req.qty, req.side,
                  result.get("status", "SUBMITTED"))
        return result
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")

@app.get("/trade-history/{username}")
def trade_history(username: str):
    return {"history": get_trade_history(username)}


# ═══════════════════════════════════════════════════════════════════════════════
# AUTO-TRADING
# ═══════════════════════════════════════════════════════════════════════════════
@app.post("/toggle-auto-trading")
def toggle_auto_trading(cfg: AutoTradingConfig):
    trading_config["auto_mode"] = cfg.auto_mode
    trading_config["var_limit"] = cfg.var_limit
    return {
        "auto_mode": trading_config["auto_mode"],
        "var_limit": trading_config["var_limit"],
        "message":   f"Auto-trading {'ENABLED' if cfg.auto_mode else 'DISABLED'}",
    }

@app.get("/trading-status")
def trading_status():
    return trading_config


# ═══════════════════════════════════════════════════════════════════════════════
# WEBSOCKET – LIVE RISK FEED
# ═══════════════════════════════════════════════════════════════════════════════
@app.websocket("/ws/live-risk/{ticker}")
async def live_risk(websocket: WebSocket, ticker: str):
    await websocket.accept()
    price      = 75_000.0
    portfolio_qty = 1_333
    try:
        while True:
            price += random.normalvariate(0, 150)
            price  = max(price, 1000)
            port_val   = price * portfolio_qty
            intra_var  = port_val * 0.01 * random.uniform(0.85, 1.15)
            is_breach  = trading_config["auto_mode"] and intra_var > trading_config["var_limit"]

            payload = {
                "ticker":       ticker,
                "price":        round(price, 0),
                "portfolio_value": round(port_val, 0),
                "intraday_var": round(intra_var, 0),
                "var_limit":    trading_config["var_limit"],
                "breach":       is_breach,
                "timestamp":    datetime.now().strftime("%H:%M:%S"),
            }

            # Auto-hedge trigger
            if is_breach:
                payload["alert"] = "VaR 한도 초과 — 자동 헤지 신호 발생"

            await websocket.send_json(payload)
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"WebSocket error: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# V1 API — KIS-SOURCED DATA (DB-backed, sub-100ms response)
# ═══════════════════════════════════════════════════════════════════════════════
# These endpoints NEVER call the KIS API directly.
# They query the PostgreSQL tables populated by the nightly sync worker.


from fastapi import Query


@app.get("/api/v1/stocks")
async def v1_list_stocks(
    market: str | None = Query(None, description="KOSPI / KOSDAQ"),
    sector: str | None = Query(None),
    search: str | None = Query(None, description="name or ticker substring"),
    limit: int = Query(200, ge=1, le=1000),
):
    """List stocks from the DB. Fast — no external API calls."""
    try:
        from sqlalchemy import or_, select

        from src.database_async import async_session_scope
        from src.kis_models import Stock

        async with async_session_scope() as session:
            stmt = select(Stock).where(Stock.is_active == 1)
            if market:
                stmt = stmt.where(Stock.market == market.upper())
            if sector:
                stmt = stmt.where(Stock.sector == sector)
            if search:
                pat = f"%{search}%"
                stmt = stmt.where(or_(Stock.name.like(pat), Stock.ticker.like(pat)))
            stmt = stmt.limit(limit)

            result = await session.execute(stmt)
            stocks = result.scalars().all()

            return {
                "count": len(stocks),
                "stocks": [
                    {
                        "ticker": s.ticker,
                        "name": s.name,
                        "market": s.market,
                        "sector": s.sector,
                    }
                    for s in stocks
                ],
            }
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@app.get("/api/v1/prices/{ticker}")
async def v1_get_prices(
    ticker: str,
    days: int = Query(60, ge=1, le=500),
):
    """일별 OHLCV — DB→KIS(온디맨드)→mock 통합 로더. KIS 성공 시 DB에 적재(다음부턴 즉시).
    리스크 지표·가격차트가 미적재 종목에서도 동작하게 함."""
    try:
        import asyncio
        from datetime import datetime, timedelta

        from src.data.ohlcv_loader import load_ohlcv_unified

        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=int(days * 1.7) + 40)).strftime("%Y-%m-%d")
        loop = asyncio.get_event_loop()
        df = await loop.run_in_executor(None, lambda: load_ohlcv_unified(ticker, start, end, "auto"))
        if df is None or df.empty:
            return {"ticker": ticker, "count": 0, "prices": []}
        df = df.tail(days)

        def _f(v):
            try:
                return float(v)
            except Exception:
                return None

        prices = []
        for idx, r in df.iterrows():
            dt = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
            prices.append({
                "date": dt,
                "open": _f(r.get("open")), "high": _f(r.get("high")), "low": _f(r.get("low")),
                "close": _f(r.get("close")), "volume": _f(r.get("volume")),
                "trading_value": _f(r.get("trading_value")) if "trading_value" in r else None,
            })
        return {"ticker": ticker, "count": len(prices), "prices": prices}
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@app.get("/api/v1/screener/stocks")
async def v1_screener_stocks(
    min_price: float | None = None,
    max_price: float | None = None,
    min_volume: int | None = None,
    market: str | None = None,
    limit: int = Query(100, ge=1, le=500),
):
    """
    Fast screener query joining stocks with their latest daily price.
    Runs entirely in SQL — no Pandas, no KIS calls.
    """
    try:
        from src.database_async import async_session_scope

        # Raw SQL for a single efficient query with LATERAL JOIN-equivalent
        sql = """
            SELECT s.ticker, s.name, s.market, s.sector,
                   dp.close, dp.volume, dp.trade_date, dp.trading_value
            FROM stocks s
            LEFT JOIN LATERAL (
                SELECT close, volume, trade_date, trading_value
                FROM daily_prices
                WHERE ticker = s.ticker
                ORDER BY trade_date DESC
                LIMIT 1
            ) dp ON TRUE
            WHERE s.is_active = 1
        """
        params = {}
        if market:
            sql += " AND s.market = :market"
            params["market"] = market.upper()
        if min_price is not None:
            sql += " AND dp.close >= :min_price"
            params["min_price"] = min_price
        if max_price is not None:
            sql += " AND dp.close <= :max_price"
            params["max_price"] = max_price
        if min_volume is not None:
            sql += " AND dp.volume >= :min_volume"
            params["min_volume"] = min_volume
        sql += f" ORDER BY dp.trading_value DESC NULLS LAST LIMIT {int(limit)}"

        async with async_session_scope() as session:
            result = await session.execute(_sql_text(sql), params)
            rows = [dict(r._mapping) for r in result.fetchall()]
            for row in rows:
                for k, v in list(row.items()):
                    if hasattr(v, "isoformat"):
                        row[k] = v.isoformat()

        return {"count": len(rows), "results": rows}
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


@app.post("/api/v1/admin/sync")
async def v1_admin_trigger_sync():
    """Manually trigger a full KIS sync. For admin / CLI use."""
    try:
        from src.data_sync import run_full_sync
        result = await run_full_sync()
        return result
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")


# ═══════════════════════════════════════════════════════════════════════════════
# GRAPH BACKTEST — React Flow 노드 그래프 기반 백테스트
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/api/v1/backtest/graph")
def graph_backtest(req: dict):
    """
    React Flow 캔버스의 노드/엣지 JSON을 받아 DAG 백테스트 실행.
    Pipeline: DAG구축 → 순환검증 → 위상정렬 → 팩토리실행 → 벡터화백테스트
    """
    try:
        from src.engine.dag_runner import execute_dag_backtest
        from src.models.graph_schema import GraphBacktestRequest

        parsed_req = GraphBacktestRequest(**req)
        result = execute_dag_backtest(parsed_req)
        return result.model_dump()
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


# ═══════════════════════════════════════════════════════════════════════════════
# PHASE 4: 종목 검색 + 주문 실행 + 계좌 조회
# ═══════════════════════════════════════════════════════════════════════════════

# ── 마스터파일 수집 + 종목 검색 ──────────────────────────────────────────────

@app.post("/api/v1/symbols/collect-master")
async def collect_master():
    """KOSPI/KOSDAQ 마스터파일 다운로드 → DB Upsert (인증 불필요)."""
    try:
        from src.database import get_engine
        from src.kis_master_parser import collect_master_files
        engine = get_engine()
        result = await collect_master_files(engine)
        return result
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@app.get("/api/v1/symbols/search")
async def symbol_search(
    q: str = Query(..., min_length=1, description="종목코드 또는 종목명"),
    market: str | None = Query(None, description="KOSPI / KOSDAQ"),
    limit: int = Query(30, ge=1, le=100),
):
    """인메모리 캐시에서 종목 검색 (즉시 응답)."""
    try:
        from src.kis_master_parser import _symbol_cache, search_symbols
        results = search_symbols(q, market, limit)

        # 캐시 미구축 시 DB fallback
        if not results and not _symbol_cache:
            from src.database import get_engine
            from src.kis_master_parser import load_symbol_cache
            engine = get_engine()
            load_symbol_cache(engine)
            results = search_symbols(q, market, limit)

        return {"query": q, "total": len(results), "items": results}
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@app.get("/api/v1/symbols/status")
def symbol_status():
    """마스터파일 로드 상태 확인."""
    from src.kis_master_parser import _last_fetched, _symbol_cache
    total = sum(len(v) for v in _symbol_cache.values())
    return {
        "loaded": total > 0,
        "total": total,
        "markets": {k: len(v) for k, v in _symbol_cache.items()},
        "last_fetched": _last_fetched.isoformat() if _last_fetched else None,
    }


# ── 계좌 조회 ─────────────────────────────────────────────────────────────────

@app.get("/api/v1/account/holdings")
def get_holdings():
    """KIS API로 현재 보유 종목 조회."""
    try:
        from src.kis_client import KISClient
        from src.kis_order_executor import PositionManager
        client = KISClient()
        pm = PositionManager(client)
        positions = pm.get_positions(refresh=True)
        return {
            "mode": client.mode,
            "count": len(positions),
            "positions": [p.to_dict() for p in positions],
        }
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@app.get("/api/v1/account/balance")
def get_balance():
    """예수금 및 평가금액 조회."""
    try:
        from src.kis_client import KISClient
        client = KISClient()
        balance = client.get_account_balance()
        return {"mode": client.mode, **balance}
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


# ── 주문 실행 ─────────────────────────────────────────────────────────────────

class OrderRequest(BaseModel):
    stock_code: str
    stock_name: str = ""
    action: str           # "buy" | "sell"
    quantity: int | None = None
    target_price: float | None = None
    strength: float = 1.0


class BatchOrderRequest(BaseModel):
    orders: list[OrderRequest]


@app.post("/api/v1/orders/execute")
def execute_order(req: OrderRequest):
    """
    단일 주문 실행.
    KIS_MODE=MOCK이면 실제 주문 없이 로그만 기록.
    KIS_MODE=REAL이면 KIS TR 호출.
    """
    try:
        from src.kis_client import KISClient
        from src.kis_order_executor import OrderExecutor

        client = KISClient()
        executor = OrderExecutor(client)
        result = executor.execute(
            stock_code=req.stock_code,
            stock_name=req.stock_name or req.stock_code,
            action=req.action.lower(),
            strength=req.strength,
            quantity=req.quantity,
            target_price=req.target_price,
        )
        return result.to_dict()
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@app.post("/api/v1/orders/batch")
def batch_execute_orders(req: BatchOrderRequest):
    """시그널 일괄 주문 (batch-signal 결과를 그대로 투입)."""
    try:
        from src.kis_client import KISClient
        from src.kis_order_executor import OrderExecutor

        client = KISClient()
        executor = OrderExecutor(client)
        results = []
        for o in req.orders:
            r = executor.execute(
                stock_code=o.stock_code,
                stock_name=o.stock_name or o.stock_code,
                action=o.action.lower(),
                strength=o.strength,
                quantity=o.quantity,
                target_price=o.target_price,
            )
            results.append(r.to_dict())

        success_count = sum(1 for r in results if r["success"])
        return {
            "total": len(results),
            "success": success_count,
            "failed": len(results) - success_count,
            "orders": results,
        }
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


# ── startup에 마스터파일 캐시 로드 추가 ──────────────────────────────────────

# (startup 함수에 이미 등록된 캐시 로드는 아래 패치로 처리)

# ═══════════════════════════════════════════════════════════════════════════════

# ═══ Stage 11/12/13/Valuation Routers (auto-integrated) ═══════════════════════
try:
    from src.api.macro_routes import router as macro_router
    from src.api.narrative_routes import router as narrative_router
    from src.api.screener_routes import router as screener_router
    from src.api.screener_universe_count import router as universe_count_router
    from src.api.stage11_routes import router as stage11_router
    from src.api.stage12_routes import router as stage12_router
    from src.api.stage13_extensions import router as stage13_ext_router
    from src.api.stage13_routes import router as stage13_router
    from src.api.trading_routes import router as trading_router
    from src.api.valuation_routes import router as valuation_router
    app.include_router(stage11_router)
    app.include_router(stage12_router)
    app.include_router(stage13_router)
    app.include_router(stage13_ext_router)
    app.include_router(valuation_router)
    app.include_router(screener_router)
    app.include_router(universe_count_router)
    app.include_router(narrative_router)
    app.include_router(macro_router)
    app.include_router(trading_router)
    print("✓ Stage 11/12/13/Valuation/Screener/Narrative/Macro/Trading 라우터 등록 완료 (106 endpoints)")
except ImportError as e:
    print(f"⚠ Stage 11+ 라우터 import 실패 (선택적): {e}")
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
