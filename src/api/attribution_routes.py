"""Attribution · Journal · Strategy Health API (Full Expansion P5)
==============================================================================
GET  /api/v1/allocation/attribution/{run_id}   — 사전 기대 vs 사후 실측 리포트
POST /api/v1/allocation/journal                 — 의사결정 저널 생성(run_id 연결)
GET  /api/v1/allocation/journal                 — 목록
GET  /api/v1/allocation/journal/{entry_id}
GET  /api/v1/allocation/journal/by-run/{run_id} — run_id로 연결된 저널(Attribution 링크)
PATCH /api/v1/allocation/journal/{entry_id}/review  — 사후 회고·의사결정 품질
DELETE /api/v1/allocation/journal/{entry_id}
GET  /api/v1/allocation/strategy-health         — 알파·슬리브 건강도

Attribution과 Journal은 같은 run_id로 연결(지시서 §8 검증 항목).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger("api.attribution")

router = APIRouter(prefix="/api/v1/allocation", tags=["attribution", "journal"])


class JournalRequest(BaseModel):
    title: str = Field(..., max_length=200)
    run_id: str | None = None
    links: dict = Field(default_factory=dict)      # alpha_version/sleeve_version/opt_settings/scenario_pack/execution_plan_id/approvers
    record: dict = Field(default_factory=dict)     # thesis/data_model_versions/counter_arguments/decision/reason_change/cause/next_experiment/postmortem
    decision_quality: str | None = None
    attach_attribution: bool = True                # run_id 있으면 현재 Attribution 스냅샷 첨부


class ReviewRequest(BaseModel):
    review: str | None = None
    decision_quality: str | None = None


def _attribution_for(run_id: str, as_of: str | None = None) -> dict:
    from src.data.research_runs import get_run
    from src.engine.attribution import compute_attribution
    run = get_run(run_id)
    if run is None:
        raise HTTPException(404, "run을 찾을 수 없습니다 (DB 미가용이거나 없는 run_id).")
    # 연결된 실행계획의 실체결·기대비용 (있으면 슬리피지·비용 실측)
    fills = None
    expected_cost_bp = None
    try:
        from src.data.execution_store import find_by_run
        plan = find_by_run(run_id)
        if plan:
            expected_cost_bp = ((plan.get("plan") or {}).get("summary") or {}).get("est_cost_bp")
            raw_fills = plan.get("fills") or []
            if raw_fills:
                # 체결에 목표가(price_est)를 조인 → 슬리피지 산출
                tgt = {o["stock_code"]: o.get("price_est")
                       for o in (plan.get("plan") or {}).get("orders", [])}
                fills = [{**f, "target_price": tgt.get(f.get("stock_code"), f.get("avg_price"))}
                         for f in raw_fills]
    except Exception:
        logger.debug("execution 링크 조회 실패 — 체결/비용 미연결로 진행", exc_info=True)
    report = compute_attribution(run, as_of=as_of, fills=fills, expected_cost_bp=expected_cost_bp)
    # 저널 연결 (같은 run_id)
    try:
        from src.data.journal_store import get_by_run
        j = get_by_run(run_id)
        report["journal_entry_id"] = j["entry_id"] if j else None
    except Exception:
        report["journal_entry_id"] = None
    return report


@router.get("/attribution/{run_id}")
def get_attribution(run_id: str, as_of: str | None = None):
    """사전 기대 vs 사후 실측.

    ★`as_of` 는 엔진이 처음부터 받고 있었는데 라우트가 넘기지 않았다 (A7)★
    그래서 프론트가 어떤 기준일을 골라도 항상 '오늘' 로 계산됐고, 오늘 만든 런
    (경과 0일)에서는 실현수익이 **구조적으로 계산 불가**라 전부 미측정이었다.
    기준일을 넘길 수 있으면 경과 일수가 있는 결정은 실제로 실측된다.
    """
    try:
        return _attribution_for(run_id, as_of=as_of)
    except HTTPException:
        raise
    except Exception:
        logger.exception("attribution 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.post("/journal")
def create_journal(req: JournalRequest):
    try:
        from src.data.journal_store import create_entry
        attribution = None
        if req.attach_attribution and req.run_id:
            try:
                attribution = _attribution_for(req.run_id)
            except HTTPException:
                attribution = None
        eid = create_entry(req.title, run_id=req.run_id, links=req.links, record=req.record,
                           decision_quality=req.decision_quality, attribution=attribution)
        if eid is None:
            return {"saved": False, "entry_id": None, "message": "DB 미가용 — 저장되지 않음."}
        return {"saved": True, "entry_id": eid}
    except Exception:
        logger.exception("journal 생성 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/journal")
def list_journal(limit: int = Query(50, ge=1, le=200)):
    try:
        from src.data.journal_store import list_entries
        return {"entries": list_entries(limit=limit)}
    except Exception:
        logger.exception("journal 목록 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/journal/by-run/{run_id}")
def journal_by_run(run_id: str):
    try:
        from src.data.journal_store import get_by_run
        e = get_by_run(run_id)
        return {"entry": e}
    except Exception:
        logger.exception("journal by-run 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/journal/{entry_id}")
def get_journal(entry_id: str):
    try:
        from src.data.journal_store import get_entry
        e = get_entry(entry_id)
        if e is None:
            raise HTTPException(404, "저널 항목을 찾을 수 없습니다.")
        return e
    except HTTPException:
        raise
    except Exception:
        logger.exception("journal 조회 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.patch("/journal/{entry_id}/review")
def review_journal(entry_id: str, req: ReviewRequest):
    try:
        from src.data.journal_store import update_review
        return update_review(entry_id, review=req.review, decision_quality=req.decision_quality)
    except Exception:
        logger.exception("journal review 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.delete("/journal/{entry_id}")
def delete_journal(entry_id: str):
    try:
        from src.data.journal_store import delete_entry
        if not delete_entry(entry_id):
            raise HTTPException(404, "저널 항목을 찾을 수 없습니다.")
        return {"deleted": True}
    except HTTPException:
        raise
    except Exception:
        logger.exception("journal 삭제 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/strategy-health")
def get_strategy_health():
    try:
        from src.engine.strategy_health import strategy_health
        return strategy_health()
    except Exception:
        logger.exception("strategy-health 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")
