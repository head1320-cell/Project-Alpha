"""일일 설명 표면 — ★하루를 설명하되 설명하지 못한 몫을 숨기지 않는다★ (AB4)
==============================================================================
설계: `docs/plans` AB · 로드맵 P3

    POST /api/v1/explain/daily

## ★P-1(인증) 없이 가능한 이유★

보유를 **요청 본문으로** 받는다 — "누구의" 보유인지 묻지 않으므로 계좌 소유권을
판단할 필요가 없다. 로드맵이 "P3 는 P-1 이후" 라고 적은 근거는 **멀티계좌·구독·
파트너**가 *"누가 보느냐"* 를 요구하기 때문이고, 설명 엔진은 그 목록에 없다.
계좌에서 읽는 판이 오면 그때가 P-1 이 선행조건이 되는 지점이고, 그 경계를 `note`
가 적는다(AA5 진단 표면과 같은 관례).

## ★이 응답이 주장하지 않는 것★

가격 기여는 **총합이 아니다**. 이 저장소에 체결·예수금 기록이 없어 실제 총변동을
관측할 길이 없고, 그래서 잔차가 0 이 아니라 **계산 불가**다 — 그 사실이
`residual_reason` 과 문장에 모두 있다.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("api.explain")

router = APIRouter(prefix="/api/v1/explain", tags=["explain"])

_NOTE = (
    "이 설명은 **요청 본문으로 받은 보유**에 대한 것입니다 — 누구의 계좌인지 묻지 "
    "않았고 서버가 계좌를 조회하지도 않았습니다. 문장은 결정론적 템플릿이 만들며 "
    "LLM 이 아닙니다(같은 입력에 같은 문장)."
)


class DailyExplainRequest(BaseModel):
    holdings: dict[str, float] = Field(..., min_length=1)
    weight_unit: str | None = Field(None, max_length=16)   # percent|fraction
    as_of: str | None = Field(None, max_length=10)
    #: 그날의 매매. ★`None`(못 받음)과 `[]`(없었음)은 다른 사실이다★ — 전자는
    #: `missing_drivers` 로, 후자는 관측된 0 으로 나간다.
    trades: list[dict] | None = None
    portfolio_value: float | None = Field(None, gt=0)


@router.post("/daily")
def explain_daily(req: DailyExplainRequest):
    """임의의 보유 + 하루 → 드라이버 분해 + 한국어 한 문단."""
    try:
        # ★단위를 먼저 확정한다★ 분수를 퍼센트로 읽으면 기여가 100배 틀린다.
        from src.engine.portfolio_weights import unit_reason
        reason = unit_reason(req.holdings, req.weight_unit)
        if reason:
            raise HTTPException(422, reason)

        from src.engine.daily_explain_holdings import explain_holdings_day
        exp = explain_holdings_day(
            {str(k): float(v) for k, v in req.holdings.items()},
            as_of=req.as_of, trades=req.trades,
            portfolio_value=req.portfolio_value)

        # ★이 설명이 무엇 위에 섰는가★ — AA3 의 축을 그대로 쓴다.
        #   `target`·`macro` 는 **넘기지 않는다**(이 표면이 다루지 않는다).
        from src.engine.decision_evidence import decision_evidence
        basis = exp.price_basis or {}
        coverage = {"source": basis.get("source"),
                    "as_of_effective": basis.get("as_of_effective")}
        return {
            "explanation": exp.to_dict(),
            "evidence_rollup": decision_evidence(
                coverage=coverage, as_of_requested=req.as_of),
            "note": _NOTE,
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("explain/daily 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")
