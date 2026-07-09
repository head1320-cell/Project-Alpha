"""기업분석 심화 API — 탭당 1콜 (스펙 2026-07-09).

GET /api/v1/company/{code}/valuation-sandbox  — 샌드박스+민감도+풋볼필드+Comps
GET /api/v1/company/{code}/financial-deep     — QoE·NWC·워터폴·듀폰
GET /api/v1/company/{code}/risk-deep          — Altman·Beneish·커버리지·스트레스
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger("api.company")

router = APIRouter(prefix="/api/v1/company", tags=["company-deep"])


@router.get("/{code}/valuation-sandbox")
def company_valuation_sandbox(
    code: str,
    price: float = Query(..., gt=0, description="현재가(원)"),
    rf: float | None = Query(None, ge=0, le=0.15),
    beta: float | None = Query(None, ge=0.1, le=3.0),
    erp: float | None = Query(None, ge=0, le=0.15),
    g: float | None = Query(None, ge=0, le=0.05),
    years: int | None = Query(None, ge=3, le=20),
):
    """가정 샌드박스 + Ke×g 민감도 + Football Field + Comps (Valuation 탭 1콜)."""
    try:
        from src.engine import company_analytics as ca
        overrides = {k: v for k, v in
                     {"rf": rf, "beta": beta, "erp": erp, "g": g, "years": years}.items()
                     if v is not None}
        out = ca.valuation_sandbox(code, price, overrides)
        out["football_field"] = ca.football_field(code, price)
        out["comps"] = ca.comps_table(code)
        return out
    except Exception:
        logger.exception("valuation-sandbox 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/{code}/financial-deep")
def company_financial_deep(code: str):
    """QoE·NWC·자본배치 워터폴·듀폰 (Financials 탭 1콜)."""
    try:
        from src.engine import company_analytics as ca
        return ca.financial_deep(code)
    except Exception:
        logger.exception("financial-deep 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")
