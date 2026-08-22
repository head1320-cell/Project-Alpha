"""Execution Readiness API — 오더 diff·비용·pre-trade·승인 워크플로 (Full Expansion P4)

POST /api/v1/allocation/execution-plan       — 오더 diff + 비용 + pre-trade (미저장 미리보기)
POST /api/v1/allocation/execution-plan/save   — 계획 영속(draft) + 감사 로그
GET  /api/v1/allocation/execution-plans       — 목록
GET  /api/v1/allocation/execution-plan/{id}
POST /api/v1/allocation/execution-plan/{id}/transition  — 상태 전이(승인 등, block 시 거부)
POST /api/v1/allocation/execution-plan/{id}/fills        — 수동 체결 입력
DELETE /api/v1/allocation/execution-plan/{id}

v1은 실행 준비실 — 실 주문·자동매매 없음. paper_submitted 이후 자동 시뮬 없음.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("api.execution")

router = APIRouter(prefix="/api/v1/allocation", tags=["execution"])


class ExecPlanRequest(BaseModel):
    current_weights: dict[str, float] = Field(default_factory=dict)   # % (없으면 전량 신규매수)
    # ★R0: 목표는 `tpv_id` 로 지정하는 것이 정본이다★
    # `target_weights` 직접 전달은 배선 전 화면을 위해 남겨 둔 호환 경로다. 둘 다 오면
    # 서버가 대조해서 다르면 거부한다 — 감사 기록과 실제 주문이 갈라지면 안 된다.
    tpv_id: str | None = None
    target_weights: dict[str, float] = Field(default_factory=dict)    # %
    portfolio_value: float = Field(1e8, gt=0)
    restricted: list[str] = Field(default_factory=list)
    limits: dict = Field(default_factory=dict)                        # turnover_cap_pct 등
    data_fresh: bool = True


class SavePlanRequest(ExecPlanRequest):
    name: str = Field("실행 계획", max_length=200)
    run_id: str | None = None


class TransitionRequest(BaseModel):
    to_status: str
    note: str = Field("", max_length=1000)
    actor: str = Field("user", max_length=60)


class FillsRequest(BaseModel):
    fills: list[dict] = Field(..., min_length=1)
    actor: str = Field("user", max_length=60)


def _resolve_target(req: ExecPlanRequest) -> tuple[dict[str, float] | None, dict | None]:
    """(목표 비중, 차단 응답). 차단이면 **계획을 만들지 않는다.**

    ★이 함수가 R0 의 차단선이다★ 화면이 무엇을 보내든 주문 목표는 승인된
    `TargetPortfolioVersion` 에서만 나온다. 막을 때는 반드시 사유를 함께 낸다.
    """
    if not req.tpv_id:
        if req.target_weights:
            return dict(req.target_weights), None          # 호환 경로 (배선 전 화면)
        return None, {"blocked": True, "reason": "목표 포트폴리오가 없습니다 — "
                      "tpv_id 또는 target_weights 중 하나가 필요합니다."}

    from src.data.target_versions import STATUS_EXECUTABLE, get_target
    tv = get_target(req.tpv_id)
    if tv is None:
        # ★조용히 요청 비중으로 진행하지 않는다★ 모르는 목표를 받았다는 사실이 결론이다.
        return None, {"blocked": True,
                      "reason": f"목표 버전을 찾을 수 없습니다: {req.tpv_id}"}
    if tv["status"] != STATUS_EXECUTABLE:
        return None, {"blocked": True, "tpv_id": req.tpv_id,
                      "reason": tv.get("status_reason") or "실행할 수 없는 목표입니다."}

    final = {c: float(v) for c, v in tv["final_weights"].items()}
    if req.target_weights:
        same = (set(req.target_weights) == set(final)
                and all(abs(float(req.target_weights[c]) - final[c]) < 1e-6 for c in final))
        if not same:
            return None, {"blocked": True, "tpv_id": req.tpv_id,
                          "reason": "요청한 비중이 목표 버전과 일치하지 않습니다 — "
                                    "감사 기록과 실제 주문이 갈라집니다."}
    return final, None


def _compute(req: ExecPlanRequest, target: dict[str, float]) -> tuple[dict, dict]:
    from src.engine.execution_plan import build_plan, pre_trade_checks
    plan = build_plan(req.current_weights, target, req.portfolio_value,
                      restricted=set(req.restricted))
    # 현금 잔량 힌트 (매수 총액 > PV면 음수 — pre-trade가 block)
    limits = dict(req.limits)
    buy = plan["summary"]["buy_notional"] + plan["summary"]["est_cost"]
    cur_cash = req.portfolio_value * (1 - sum(max(v, 0) for v in req.current_weights.values()) / 100.0)
    limits.setdefault("cash_after_pct", round((cur_cash + plan["summary"]["sell_notional"] - buy)
                                              / req.portfolio_value * 100, 2))
    pretrade = pre_trade_checks(plan, limits=limits, data_fresh=req.data_fresh)
    return plan, pretrade


@router.post("/execution-plan")
def execution_plan_preview(req: ExecPlanRequest):
    """미저장 미리보기 — 오더 diff·비용·pre-trade."""
    try:
        target, blocked = _resolve_target(req)
        if blocked:
            return {"error": False, **blocked}      # 차단은 오류가 아니라 정책 결과다
        plan, pretrade = _compute(req, target or {})
        return {"error": False, "blocked": False, "tpv_id": req.tpv_id,
                "plan": plan, "pretrade": pretrade}
    except Exception:
        logger.exception("execution-plan 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.post("/execution-plan/save")
def execution_plan_save(req: SavePlanRequest):
    """계획 영속(draft) — 감사 로그 시작."""
    try:
        from src.data.execution_store import create_plan
        target, blocked = _resolve_target(req)
        if blocked:
            # ★미리보기만 막고 저장을 열어 두면 게이트가 아니다★
            return {"saved": False, "plan_id": None, **blocked}
        plan, pretrade = _compute(req, target or {})
        pid = create_plan(req.name, plan, pretrade, run_id=req.run_id)
        if pid is None:
            return {"saved": False, "plan_id": None, "message": "DB 미가용 — 저장되지 않음.",
                    "plan": plan, "pretrade": pretrade}
        return {"saved": True, "plan_id": pid, "plan": plan, "pretrade": pretrade}
    except Exception:
        logger.exception("execution-plan/save 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/execution-plans")
def execution_plans_list():
    try:
        from src.data.execution_store import list_plans
        return {"plans": list_plans()}
    except Exception:
        logger.exception("execution-plans 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/execution-plan/{plan_id}")
def execution_plan_get(plan_id: str):
    try:
        from src.data.execution_store import get_plan
        p = get_plan(plan_id)
        if p is None:
            raise HTTPException(404, "계획을 찾을 수 없습니다.")
        return p
    except HTTPException:
        raise
    except Exception:
        logger.exception("execution-plan get 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.post("/execution-plan/{plan_id}/transition")
def execution_plan_transition(plan_id: str, req: TransitionRequest):
    try:
        from src.data.execution_store import transition
        return transition(plan_id, req.to_status, actor=req.actor, note=req.note)
    except Exception:
        logger.exception("execution transition 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.post("/execution-plan/{plan_id}/fills")
def execution_plan_fills(plan_id: str, req: FillsRequest):
    try:
        from src.data.execution_store import record_fills
        return record_fills(plan_id, req.fills, actor=req.actor)
    except Exception:
        logger.exception("execution fills 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.delete("/execution-plan/{plan_id}")
def execution_plan_delete(plan_id: str):
    try:
        from src.data.execution_store import delete_plan
        if not delete_plan(plan_id):
            raise HTTPException(404, "계획을 찾을 수 없습니다.")
        return {"deleted": True}
    except HTTPException:
        raise
    except Exception:
        logger.exception("execution delete 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")
