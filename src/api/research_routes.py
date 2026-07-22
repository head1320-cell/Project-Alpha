"""ResearchRun API — 연구 실행 저장·조회·비교 (Full Expansion Directive P1)

POST /api/v1/research-runs           — 실행 기록 (kind·inputs·outputs·snapshot)
GET  /api/v1/research-runs           — 목록 (kind 필터·limit, 요약)
GET  /api/v1/research-runs/{run_id}  — 단건 전체 (inputs/outputs 포함)
DELETE /api/v1/research-runs/{run_id}

기록 실패(DB 미가용)는 조용히 성공으로 위장하지 않고 recorded=False 로 정직 보고.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger("api.research")

router = APIRouter(prefix="/api/v1/research-runs", tags=["research-runs"])


class RecordRunRequest(BaseModel):
    kind: str = Field(..., min_length=1, max_length=40)
    name: str | None = Field(None, max_length=200)
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    snapshot: dict[str, Any] | None = None
    parent_run_id: str | None = None
    note: str | None = Field(None, max_length=2000)


@router.post("")
def create_run(req: RecordRunRequest):
    try:
        from src.data.research_runs import record_run
        rid = record_run(req.kind, req.inputs, req.outputs, snapshot=req.snapshot,
                         name=req.name, parent_run_id=req.parent_run_id, note=req.note)
        if rid is None:
            return {"recorded": False, "run_id": None,
                    "message": "DB 미가용 — 런이 저장되지 않았습니다."}
        return {"recorded": True, "run_id": rid}
    except Exception:
        logger.exception("research run 생성 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("")
def list_all(kind: str | None = Query(None), limit: int = Query(50, ge=1, le=200)):
    try:
        from src.data.research_runs import list_runs
        return {"runs": list_runs(kind=kind, limit=limit)}
    except Exception:
        logger.exception("research run 목록 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/{run_id}")
def get_one(run_id: str):
    try:
        from src.data.research_runs import get_run
        d = get_run(run_id)
        if d is None:
            raise HTTPException(404, "런을 찾을 수 없습니다.")
        return d
    except HTTPException:
        raise
    except Exception:
        logger.exception("research run 조회 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.delete("/{run_id}")
def delete_one(run_id: str):
    try:
        from src.data.research_runs import delete_run
        if not delete_run(run_id):
            raise HTTPException(404, "런을 찾을 수 없습니다.")
        return {"deleted": True}
    except HTTPException:
        raise
    except Exception:
        logger.exception("research run 삭제 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")
