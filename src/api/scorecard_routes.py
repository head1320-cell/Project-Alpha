"""전략 평가 카드 표면 — ★세 축과 못 잰 것, 그리고 닫힌 유통 관문★ (AE4)
==============================================================================
설계: `docs/plans` AE · 로드맵 P4 "평가 카드"

    POST /api/v1/strategies/scorecard

## ★이것은 마켓플레이스가 아니다★

로드맵의 P4 는 마켓플레이스·구독·B2B 어드바이저 API 인데, 그중 **유통**은 업권
사항이라 만들지 않았다(사용자 결정: 인가 미확인, 2026-09-13). 이 표면은 **자기
전략을 측정**할 뿐이고, 각 카드의 `distribution` 이 **막힘 + 사유**를 싣는다.

유통 표면이 몰래 생기는 것은 `tests/test_distribution_blocked.py` 가 전수로 막는다.

## ★P-1(인증) 경계★

알파 등록부는 연구 자료이고 계좌·주문을 건드리지 않는다 — 보호 레지스트리에 사유와
함께 면제로 등록돼 있다(`src/api/protected_routes.py`).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("api.scorecard")

router = APIRouter(prefix="/api/v1/strategies", tags=["strategies"])

_NOTE = (
    "이 카드는 세 축을 나란히 보여 줄 뿐 종합 등급을 만들지 않습니다 — 승격은 절차, "
    "건강도는 측정, 증거는 시점 정합이고 서로 다른 질문입니다. unmeasured 는 이 "
    "저장소가 재지 못한다고 스스로 적어 둔 신호들입니다."
)

_DISTRIBUTION_NOTE = (
    "외부 유통 표면은 만들지 않았습니다 — 업권 사항이고 인가가 확인된 적이 "
    "없습니다. 각 카드의 distribution 이 그 상태를 싣습니다."
)


class ScorecardRequest(BaseModel):
    alpha_ids: list[str] = Field(..., min_length=1, max_length=50)


@router.post("/scorecard")
def strategy_scorecards(req: ScorecardRequest):
    try:
        from src.engine.scorecard_builder import build_scorecards
        cards = build_scorecards(list(req.alpha_ids))
        return {
            "cards": cards,
            "unavailable": sorted(c["strategy_id"] for c in cards if not c["available"]),
            "note": _NOTE,
            "distribution_note": _DISTRIBUTION_NOTE,
        }
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")
