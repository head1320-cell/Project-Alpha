"""기업분석 심화 API — 탭당 1콜 (스펙 2026-07-09).

GET /api/v1/company/{code}/valuation-sandbox  — 샌드박스+민감도+풋볼필드+Comps
GET /api/v1/company/{code}/financial-deep     — QoE·NWC·워터폴·듀폰
GET /api/v1/company/{code}/risk-deep          — Altman·Beneish·커버리지·스트레스
GET /api/v1/company/{code}/reverse-dcf       — 역DCF: 시장이 믿고 있는 가정 (P2-2)
GET /api/v1/company/{code}/valuation-distribution — 적정가 P10~P90 (P2-3)
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


@router.get("/{code}/risk-deep")
def company_risk_deep(code: str, price: float = Query(..., gt=0)):
    """Altman 분해·Beneish 8지수·커버리지·금리 스트레스 (Risk 탭 1콜)."""
    try:
        from src.engine import company_analytics as ca
        return ca.risk_deep(code, price)
    except Exception:
        logger.exception("risk-deep 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/{code}/reverse-dcf")
def company_reverse_dcf(
    code: str,
    price: float = Query(..., gt=0, description="현재가(원)"),
    market_cap: float | None = Query(None, gt=0, description="시총(억) — 발행주식수 보강용"),
    bracket_lo: float = Query(-0.50, gt=-1.0, le=1.0),
    bracket_hi: float = Query(0.50, gt=-1.0, le=5.0),
):
    """★값이 아니라 **가정**을 되짚는다★ 시장가를 정당화하는 FCF 성장률 (P2-2).

    "적정가 83,000원" 은 우리 가정의 결과일 뿐이다. "시장은 향후 10년 FCF 연 11.4%
    성장을 믿고 있다" 는 **반증 가능한 명제**이고, 그것이 언더라이팅의 출발점이다.

    산출 불가는 200 + `{available:false, reason}` 이다 — 적자·마이너스 FCF 기업에서
    근이 존재하지 않는 것은 서버 장애가 아니라 **그 기업에 대한 사실**이므로 500 이나
    422 로 뭉개지 않는다. 근이 브래킷 밖이면 `direction` 이 어느 쪽인지 말한다.
    """
    try:
        from src.engine.valuation.reverse_dcf import reverse_dcf_for
        return reverse_dcf_for(code, price, market_cap=market_cap,
                               bracket=(bracket_lo, bracket_hi))
    except Exception:
        logger.exception("reverse-dcf 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/{code}/valuation-distribution")
def company_valuation_distribution(
    code: str,
    price: float = Query(..., gt=0, description="현재가(원)"),
    n: int = Query(2000, ge=100, le=20000, description="표본 수"),
):
    """★점 하나를 확률 진술로★ 적정가 P10~P90 + **현재 주가의 분위** (P2-3).

    통합값만이 아니라 **모델별 분포**와 모델 불일치를 함께 낸다 — 실측에서 모델
    불일치(2.94배)가 파라미터 불확실성(P90/P10 = 1.36)보다 크므로, 통합값 하나만
    내면 더 큰 쪽이 평균에 지워진다.

    ★폭 중 측정된 것은 하나도 없다★ `widths[*].measured` 가 전부 false 이고, 지배
    파라미터(`dominant_driver`)는 실측에서 β 였다 — 폭이 순수한 가정인 바로 그 항목.
    둘을 함께 읽어야 분포의 의미를 오해하지 않는다.

    표본 부족·TV 발산 기각은 200 + `{available:false, reason}` 이다.
    """
    try:
        from src.engine.valuation.valuation_distribution import valuation_distribution_for
        return valuation_distribution_for(code, price, n=n)
    except Exception:
        logger.exception("valuation-distribution 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")
