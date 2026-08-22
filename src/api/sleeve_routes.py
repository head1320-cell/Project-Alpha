"""Neutralization · Sleeve Combination · Sleeve Analytics API (Full Expansion P3 잔여)
==============================================================================
POST /api/v1/allocation/neutralize       — 베타/섹터 중립화 (목표 노출 허용오차 내)
POST /api/v1/allocation/pair-spread      — 베타중립 페어/스프레드
POST /api/v1/allocation/combine-sleeves  — 슬리브 결합(2단계) + 리스크 예산
POST /api/v1/allocation/sleeve-analytics — 슬리브 간 상관·군집·리스크기여·꼬리의존

지시서 §8: 베타중립·섹터중립·페어스프레드가 목표 노출을 허용오차 내로 달성. 슬리브 간
상관·군집·리스크 기여 계산 가능.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("api.sleeve")

router = APIRouter(prefix="/api/v1/allocation", tags=["neutralize", "sleeve"])


class NeutralizeRequest(BaseModel):
    weights: dict[str, float] = Field(..., min_length=2)   # %
    mode: str = Field("beta")                               # beta | sector | both
    target_beta: float = Field(0.0, ge=-2.0, le=2.0)
    dollar_neutral: bool = False
    sector_target: dict[str, float] | None = None


class PairSpreadRequest(BaseModel):
    long_code: str
    short_code: str
    hedge_ratio: float | None = None


class Sleeve(BaseModel):
    name: str = Field(..., max_length=80)
    weights: dict[str, float] = Field(..., min_length=1)    # code -> weight(비율 또는 %)


class CombineRequest(BaseModel):
    sleeves: list[Sleeve] = Field(..., min_length=1, max_length=20)
    method: str = Field("risk_parity")
    risk_budget: dict[str, float] | None = None
    scores: dict[str, float] | None = None


class AnalyticsRequest(BaseModel):
    sleeves: list[Sleeve] = Field(..., min_length=2, max_length=20)
    weights: dict[str, float] | None = None


@router.post("/neutralize")
def neutralize(req: NeutralizeRequest):
    try:
        from src.engine.neutralize import neutralize_portfolio
        mode = req.mode if req.mode in ("beta", "sector", "both") else "beta"
        return neutralize_portfolio(req.weights, mode=mode, target_beta=req.target_beta,
                                    dollar_neutral=req.dollar_neutral, sector_target=req.sector_target)
    except Exception:
        logger.exception("neutralize 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.post("/pair-spread")
def pair_spread(req: PairSpreadRequest):
    try:
        from src.engine.neutralize import _load_beta, pair_spread
        betas = {req.long_code: _load_beta(req.long_code), req.short_code: _load_beta(req.short_code)}
        return pair_spread(req.long_code, req.short_code, betas, hedge_ratio=req.hedge_ratio)
    except Exception:
        logger.exception("pair-spread 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.post("/combine-sleeves")
def combine_sleeves(req: CombineRequest):
    try:
        from src.engine.sleeve_combine import combine_sleeves
        sleeves = [{"name": s.name, "weights": s.weights} for s in req.sleeves]
        return combine_sleeves(sleeves, method=req.method, risk_budget=req.risk_budget,
                               scores=req.scores)
    except Exception:
        logger.exception("combine-sleeves 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.post("/sleeve-analytics")
def sleeve_analytics(req: AnalyticsRequest):
    try:
        from src.engine.sleeve_combine import sleeve_analytics
        sleeves = [{"name": s.name, "weights": s.weights} for s in req.sleeves]
        return sleeve_analytics(sleeves, weights=req.weights)
    except Exception:
        logger.exception("sleeve-analytics 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")
