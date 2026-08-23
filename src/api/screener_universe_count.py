# 대상 경로: src/api/screener_universe_count.py
#
# 매매 대상(유니버스) 실시간 종목 수 엔드포인트.
#   POST /api/v1/screener/universe-count  ->  { "matched": int, "total": int }
#
# 실데이터 기반 — engine/universe_select.select_universe 를 그대로 사용(스텁 없음).
# main_api.py 등록:
#   from src.api.screener_universe_count import router as universe_count_router
#   app.include_router(universe_count_router)

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/screener", tags=["screener"])


class WatchGroup(BaseModel):
    mode: Literal["none", "include", "exclude"] = "none"
    tickers: list[str] = Field(default_factory=list)


class UniverseCountRequest(BaseModel):
    caps: list[str] = Field(default_factory=list)        # 시총군 id (kospi_l …)
    sectors: list[str] = Field(default_factory=list)     # 실제 업종명 (/sectors)
    etf: bool = False
    managed: bool = False
    supervised: bool = False
    groups: list[WatchGroup] = Field(default_factory=list)


class UniverseCountResponse(BaseModel):
    matched: int
    total: int


@router.post("/universe-count", response_model=UniverseCountResponse)
def universe_count(req: UniverseCountRequest) -> UniverseCountResponse:
    try:
        from src.engine.universe_select import select_universe
        tickers, total = select_universe(
            caps=req.caps, sectors=req.sectors, etf=req.etf,
            managed=req.managed, supervised=req.supervised,
            groups=[g.model_dump() for g in req.groups],
        )
        return UniverseCountResponse(matched=len(tickers), total=total)
    except Exception as e:
        raise HTTPException(500, f"universe-count 실패: {e}")
