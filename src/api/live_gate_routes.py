"""실계좌(LIVE) 관문 선언·철회 — 관리자만 (BV7)
==============================================================================
운영자가 "무슨 근거로·누구에게" 실계좌를 여는지 선언한다. 판정은 `src/domain/live_gate.py`, 기록은
`src/execution/live_gate_store.py`. 선언한 사람은 ★토큰에서만★ 온다.

## ★관문이 바뀌면 LIVE 는 내려온다★

선언을 바꾸거나 철회하면, LIVE 로 돌고 있던 운영자 실행기는 SHADOW 로 돌아간다 — 새 명단에 그 사람이 남아 있어도
다시 확인하고 켜게 한다(보수 쪽). 실행기가 아직 없으면 아무것도 만들지 않는다.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.api.auth import require_admin
from src.domain.auth_identity import Principal
from src.execution import live_gate_store

router = APIRouter(prefix="/api/v1/admin/live-gate", tags=["live-gate"])


class DeclareRequest(BaseModel):
    basis: str
    authority: str
    reference_no: str
    verified_at: str
    scope: str
    allowed_users: list[str]


def _drop_operator_live(actor: str) -> bool:
    import src.api.stage13_routes as stage13
    from src.execution.order_executor import ExecutionMode
    ex = stage13._EXECUTOR
    if ex is not None and ex.state.mode == ExecutionMode.LIVE:
        ex.set_mode(ExecutionMode.SHADOW, actor)
        return True
    return False


@router.get("")
def get_gate(p: Principal = Depends(require_admin)):
    return {"current": live_gate_store.current_record(), "history": live_gate_store.history()}


@router.post("", status_code=201)
def declare_gate(req: DeclareRequest, p: Principal = Depends(require_admin)):
    try:
        rec = live_gate_store.declare(p.username, **req.model_dump())
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return {"current": rec, "live_dropped_to_shadow": _drop_operator_live(p.username)}


@router.delete("")
def revoke_gate(p: Principal = Depends(require_admin)):
    if not live_gate_store.revoke(p.username):
        raise HTTPException(404, "지금 열려 있는 실계좌 관문이 없어요.")
    return {"revoked": True, "revoked_by": p.username, "live_dropped_to_shadow": _drop_operator_live(p.username)}
