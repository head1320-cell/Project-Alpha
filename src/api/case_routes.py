"""ResearchCase API — 연구 질문 하나를 감싸는 작업 단위 (M1-S)

POST   /api/v1/research-cases            — 생성 (name + question)
GET    /api/v1/research-cases            — 목록 (available 로 장애/빈 목록 구분)
GET    /api/v1/research-cases/{case_id}  — 단건 (404 없음 / 503 장애)
PATCH  /api/v1/research-cases/{case_id}  — active_* 포인터·이름·상태 갱신
GET    /api/v1/research-cases/{case_id}/chain — 증거 사슬 (MES · TPV · Run)

★R0-S 가 세운 분기를 그대로 지킨다★ 빈 목록 ≠ 저장소 장애, 없음(404) ≠ 못 읽음(503).
연구가 사라진 것처럼 보이는 화면은 이 플랫폼에서 가장 겁나는 화면이다.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger("api.case")

router = APIRouter(prefix="/api/v1/research-cases", tags=["research-cases"])


class CreateCaseRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    # ★질문은 필수다★ 질문 없는 Case 는 폴더일 뿐이고, 폴더는 이미 Study 가 한다.
    question: str = Field(..., min_length=1, max_length=2000)
    market: str = Field("kr", max_length=16)
    universe_ref: str | None = Field(None, max_length=80)
    note: str | None = Field(None, max_length=2000)


class UpdateCaseRequest(BaseModel):
    name: str | None = Field(None, max_length=200)
    status: str | None = Field(None, pattern="^(open|archived)$")
    active_mes_id: str | None = Field(None, max_length=60)
    active_tpv_id: str | None = Field(None, max_length=40)
    active_run_id: str | None = Field(None, max_length=40)
    note: str | None = Field(None, max_length=2000)


@router.post("")
def create(req: CreateCaseRequest):
    from src.data.research_cases import create_case
    cid = create_case(req.name, req.question, market=req.market,
                      universe_ref=req.universe_ref, note=req.note)
    if cid is None:
        # 저장 실패를 성공으로 위장하지 않는다 (`recorded:false` 관례와 같다).
        return {"created": False, "case_id": None,
                "message": "연구 케이스 저장소를 쓸 수 없습니다 — 케이스가 저장되지 않았습니다."}
    return {"created": True, "case_id": cid}


@router.get("")
def list_all(status: str | None = Query("open"), limit: int = Query(50, ge=1, le=200)):
    from src.data.research_cases import list_cases
    try:
        return {"available": True, "cases": list_cases(status, limit)}
    except Exception as e:
        logger.warning(f"research case 목록 실패: {e}")
        return {"available": False, "cases": [],
                "reason": "연구 케이스 저장소를 읽을 수 없습니다 — 케이스가 없는 것과 다릅니다."}


@router.get("/{case_id}")
def get_one(case_id: str):
    from src.data.research_cases import get_case
    try:
        case = get_case(case_id)
    except Exception as e:
        logger.warning(f"research case 조회 실패: {e}")
        raise HTTPException(503, "연구 케이스 저장소를 읽을 수 없습니다 — 없는 것과 다릅니다.")
    if case is None:
        raise HTTPException(404, "연구 케이스를 찾을 수 없습니다.")
    return case


@router.patch("/{case_id}")
def update_one(case_id: str, req: UpdateCaseRequest):
    from src.data.research_cases import update_case
    fields = req.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(422, "갱신할 필드가 없습니다.")
    try:
        ok = update_case(case_id, **fields)
    except Exception as e:
        logger.warning(f"research case 갱신 실패: {e}")
        raise HTTPException(503, "연구 케이스 저장소를 쓸 수 없습니다.")
    if not ok:
        raise HTTPException(404, "연구 케이스를 찾을 수 없습니다.")
    return {"updated": True, "case_id": case_id}


@router.get("/{case_id}/chain")
def chain(case_id: str, limit: int = Query(30, ge=1, le=200)):
    """이 Case 의 증거 사슬 — 현재 포인터 + 이 Case 에 속한 런·목표 목록.

    ★각 조각의 가용성을 따로 답한다★ MES 를 못 읽는 것과 TPV 가 없는 것은 다른 사실이고,
    하나가 실패했다고 나머지를 비우면 화면은 "이 연구엔 아무것도 없다" 고 읽는다.
    """
    from src.data.research_cases import get_case
    try:
        case = get_case(case_id)
    except Exception:
        raise HTTPException(503, "연구 케이스 저장소를 읽을 수 없습니다.")
    if case is None:
        raise HTTPException(404, "연구 케이스를 찾을 수 없습니다.")

    out: dict = {"case": case}

    mes_id = case.get("active_mes_id")
    if not mes_id:
        out["mes"] = {"available": False, "reason": "이 케이스에 고정된 매크로 증거가 없습니다."}
    else:
        try:
            from src.data.regime_snapshots import get_snapshot
            snap = get_snapshot(mes_id)
            out["mes"] = ({"available": True, **snap} if snap else
                          {"available": False,
                           "reason": f"고정된 매크로 증거 {mes_id} 를 찾을 수 없습니다 — 삭제되었을 수 있습니다."})
        except Exception:
            out["mes"] = {"available": False, "reason": "매크로 증거 저장소를 읽을 수 없습니다."}

    try:
        from src.data.research_runs import list_runs
        runs = [r for r in list_runs(limit=200) if r.get("case_id") == case_id][:limit]
        out["runs"] = {"available": True, "items": runs}
    except Exception:
        out["runs"] = {"available": False, "items": [],
                       "reason": "연구 기록 저장소를 읽을 수 없습니다 — 런이 없는 것과 다릅니다."}

    try:
        from src.data.target_versions import list_targets
        tpvs = [t for t in list_targets(limit=200) if t.get("case_id") == case_id][:limit]
        out["targets"] = {"available": True, "items": tpvs}
    except Exception:
        out["targets"] = {"available": False, "items": [],
                          "reason": "목표 버전 저장소를 읽을 수 없습니다 — 목표가 없는 것과 다릅니다."}

    return out
