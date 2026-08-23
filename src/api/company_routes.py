"""기업분석 심화 API — 탭당 1콜 (스펙 2026-07-09).

GET /api/v1/company/{code}/valuation-sandbox  — 샌드박스+민감도+풋볼필드+Comps
GET /api/v1/company/{code}/financial-deep     — QoE·NWC·워터폴·듀폰
GET /api/v1/company/{code}/risk-deep          — Altman·Beneish·커버리지·스트레스
GET /api/v1/company/{code}/reverse-dcf       — 역DCF: 시장이 믿고 있는 가정 (P2-2)
GET /api/v1/company/{code}/valuation-distribution — 적정가 P10~P90 (P2-3)
GET /api/v1/company/{code}/macro-sensitivity — 금리 충격 → 적정가치 (P2-4)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

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


@router.get("/{code}/macro-sensitivity")
def company_macro_sensitivity(
    code: str,
    price: float = Query(..., gt=0, description="현재가(원)"),
    statistical: bool = Query(True, description="매크로 계열 회귀도 함께 낼지"),
):
    """★서술이 아니라 수치★ `+100bp 10Y → 적정가치 −9.5%` (P2-4).

    ★두 블록은 섞이지 않는다★
      · `structural` — rf → ke/kd 채널의 **항등식**. 표본도 표준오차도 없다.
        양방향을 따로 내고(비대칭은 실측 1.22배) 모델별 반응을 함께 낸다.
      · `statistical` — 코어 5계열과의 월별 회귀. **유의한 것만 고르지 않고**
        전부 보고하며, 다중검정과 "상관은 인과가 아니다" 를 라벨로 단다.

    설계 문서가 예로 든 GDP→EPS · USD→EPS · Oil→EBIT 는 `structural.unavailable`
    에서 **사유와 함께** 나간다 — 채널이 없거나(EPS 는 모델의 입력이다) 계열 자체가
    없다(유가). 빈칸이 아니라 왜 없는지가 언더라이팅의 정보다.
    """
    try:
        from src.engine.valuation.macro_sensitivity import (
            macro_sensitivity_for,
            statistical_sensitivity,
        )
        out = macro_sensitivity_for(code, price)
        if statistical:
            out["statistical"] = statistical_sensitivity(code)
        return out
    except Exception:
        logger.exception("macro-sensitivity 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


class ThesisCheckRequest(BaseModel):
    """논지 원문 — ★자유 텍스트가 아니라 구조★ 그래야 검증할 수 있다."""
    claim: str = Field("", max_length=4000)
    evidence: list[dict] = Field(default_factory=list)
    catalysts: list[dict] = Field(default_factory=list)
    kill_conditions: list[dict] = Field(default_factory=list)


@router.post("/{code}/thesis-check")
def company_thesis_check(code: str, req: ThesisCheckRequest):
    """★굳히기 전에★ 논지를 검증하고 kill 조건을 3단으로 분류한다 (P2-5).

    논지를 다듬는 반복이 스냅샷을 더럽히지 않게 하는 것이 이 엔드포인트의 목적이다
    — 저장하지 않는다.

    kill 조건은 `filter_ast` 의 `FIELD_BY_ID` 로 검증한다(**새 DSL 이 없다**).
    분류 3단은 다리의 폭을 정직하게 말한다:
      · `backtestable` — PIT 토큰 + 재무 시계열 적재 → 룩어헤드 없이 백테스트 가능
      · `screen_only_backtest_lookahead` — 스냅샷 상수 폴백이라 **룩어헤드 근사**
      · `screen_only` — 조건식 토큰이 없어 백테스트에 못 올린다

    검증 실패는 500 이 아니라 200 + `{available:false, reason, errors}` 다.
    """
    try:
        from src.engine.company_thesis import (
            thesis_to_sell_conditions,
            validate_thesis,
        )
        thesis = req.model_dump()
        out = validate_thesis(thesis, code=code)
        out["sell_conditions"] = thesis_to_sell_conditions(thesis, code=code)
        return out
    except Exception:
        logger.exception("thesis-check 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")
