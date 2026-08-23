"""파생상품 — 옵션·채권·헤지 — main_api.py에서 분리(경로·동작 불변).
"""

import logging

from fastapi import APIRouter, HTTPException

from src.api.legacy_schemas import (
    BondRequest,
    HedgeRequest,
    OptionRequest,
)
from src.models.ficc_engine import FICCEngine
from src.models.hedging import HedgingSimulator

logger = logging.getLogger("api.derivatives")
router = APIRouter(tags=["derivatives"])


@router.post("/analyze-option")
def analyze_option(req: OptionRequest):
    try:
        return FICCEngine.bs_greeks(req.S, req.K, req.T, req.r, req.sigma, req.option_type)
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")

@router.post("/analyze-bond")
def analyze_bond(req: BondRequest):
    try:
        return FICCEngine.bond_analytics(
            req.face_value, req.coupon_rate, req.ytm,
            req.years_to_maturity, req.freq
        )
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")

@router.post("/calculate-hedge")
def calculate_hedge(req: HedgeRequest):
    try:
        sim = HedgingSimulator(req.futures_price, req.multiplier)
        return sim.equity_futures_hedge(
            req.portfolio_value, req.current_beta, req.target_beta
        )
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(status_code=500, detail="처리 중 오류가 발생했습니다.")
