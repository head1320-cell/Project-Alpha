"""Experimental Features API — AutoAlpha 후보 생성 샌드박스 (Full Expansion P6)
==============================================================================
POST /api/v1/experimental/auto-alpha        — 후보 알파 생성·린트 (미저장)
POST /api/v1/experimental/auto-alpha/stage  — 선택 후보를 experimental로 스테이징
GET  /api/v1/experimental/catalog           — 실험 기능 목록(연결/미연결 정직 표기)

지시서: 실험 기능은 자동 채택 금지 — 항상 인간 검증이 필요한 후보 생성기. 어떤 실험도
승인·검증·운영 통제를 우회하지 못한다. 스테이징은 experimental 상태로만.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("api.experimental")

router = APIRouter(prefix="/api/v1/experimental", tags=["experimental"])


class AutoAlphaRequest(BaseModel):
    n: int = Field(12, ge=1, le=50)
    seed: int = Field(0, ge=0, le=10_000_000)
    mode: str = Field("random")                     # random | genetic
    seeds: list[str] = Field(default_factory=list)  # genetic 씨앗 표현식
    universe: str = "kospi200"


class StageRequest(BaseModel):
    exprs: list[str] = Field(..., min_length=1, max_length=50)
    name_prefix: str = Field("AutoAlpha", max_length=60)
    universe: str = "kospi200"


def _existing_exprs() -> list[str]:
    try:
        from src.data.alpha_registry import list_alphas
        return [a.get("expr", "") for a in list_alphas(limit=200)]
    except Exception:
        return []


@router.post("/auto-alpha")
def auto_alpha_generate(req: AutoAlphaRequest):
    """후보 생성 — 저장하지 않음. 인간이 검토 후 stage 호출."""
    try:
        from src.engine.auto_alpha import generate_candidates
        mode = req.mode if req.mode in ("random", "genetic") else "random"
        return generate_candidates(n=req.n, seed=req.seed, mode=mode,
                                   seeds=req.seeds, existing=_existing_exprs())
    except Exception:
        logger.exception("auto-alpha 생성 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.post("/auto-alpha/stage")
def auto_alpha_stage(req: StageRequest):
    """선택 후보를 레지스트리에 experimental로 스테이징(자동 채택 아님 — 검증 필요)."""
    try:
        from src.engine.auto_alpha import stage_candidates
        return stage_candidates(req.exprs, name_prefix=req.name_prefix,
                                universe=req.universe, existing=_existing_exprs())
    except Exception:
        logger.exception("auto-alpha 스테이징 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/catalog")
def experimental_catalog_list():
    try:
        from src.engine.auto_alpha import experimental_catalog
        return {
            "features": experimental_catalog(),
            "note": "실험 기능은 후보 생성기 — 자동 채택·운영 통제 우회 금지. 연결된 것만 실동작, "
                    "나머지는 데이터/인프라 미연동으로 정직하게 표기.",
        }
    except Exception:
        logger.exception("experimental catalog 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")
