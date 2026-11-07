"""신용·거래상대방 리스크 — CVA·IRC·DCC·WWR — main_api.py에서 분리(경로·동작 불변).
"""

import logging

from fastapi import APIRouter, HTTPException

from src.api.legacy_schemas import (
    CVARequest,
    DCCRequest,
    IRCRequest,
    VaRMappingRequest,
)
from src.data_loader import MarketDataLoader
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
from src.models.var_mapping import (
    Bond,
    VaRMappingEngine,
)

logger = logging.getLogger("api.credit")
router = APIRouter(tags=["credit"])


@router.post("/calculate-cva")
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

@router.post("/calculate-irc")
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

@router.get("/credit-transition-matrix")
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

@router.post("/dcc-garch")
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

@router.post("/wwr-classify")
def wwr_classify(transaction_type: str = "put_option"):
    """Classify inherent Wrong-Way Risk for a transaction type."""
    return WrongWayRiskDetector.classify_transaction_wwr(transaction_type)

@router.post("/var-mapping")
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
