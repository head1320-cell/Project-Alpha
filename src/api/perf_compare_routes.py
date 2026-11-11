"""POST /api/v1/perf/compare — 두 곡선을 맞추고 차이를 낸다 (순수 · 저장소 없음 · 2026-11-09 성과 그림 문법 ③ §3.1).

비교 화면과 현실성 탭이 제 손으로 두 곡선을 빼지 않고 이 문을 부른다 — 정렬의 의미(`src/engine/perf_compare.py`)가 캔버스 비교
노드와 같아진다. 상태를 읽지도 쓰지도 않으므로 mock 게이트·DB 와 무관하다. E2E 는 이 문을 스텁하지 않는다(진짜 정렬이 시험된다).
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.engine.perf_compare import METRIC_SPECS, align_curves, metric_rows, yearly_diff

router = APIRouter(prefix="/api/v1/perf", tags=["perf"])


class Side(BaseModel):
    label: str = ""
    dates: list[str] = Field(default_factory=list)
    equity: list[float | None] = Field(default_factory=list)
    stats: dict | None = None
    periods: dict | None = None


class CompareBody(BaseModel):
    a: Side
    b: Side
    base: Literal[1, 100] = 1
    metrics: Literal["page", "node"] | None = None


def _check(side: Side, name: str) -> None:
    if len(side.dates) != len(side.equity):
        raise HTTPException(422, f"{name} 의 날짜 {len(side.dates)}개와 값 {len(side.equity)}개가 맞지 않습니다.")
    if len(side.dates) < 2:
        raise HTTPException(422, f"{name} 의 점이 {len(side.dates)}개라 곡선이 아닙니다(2개 이상).")


@router.post("/compare")
def perf_compare(body: CompareBody):
    _check(body.a, "A")
    _check(body.b, "B")
    curves = align_curves(body.a.dates, body.a.equity, body.b.dates, body.b.equity, base=float(body.base))
    yearly = (yearly_diff(body.a.periods, body.b.periods)
              if (body.a.periods is not None or body.b.periods is not None) else None)
    rows = metric_rows(body.a.stats, body.b.stats, METRIC_SPECS[body.metrics]) if body.metrics else None
    return {"curves": curves, "yearly": yearly, "rows": rows}
