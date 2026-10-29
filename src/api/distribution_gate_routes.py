"""유통 관문 선언·철회 — 관리자만 (CF 3부 PB5 · BV7 `live_gate_routes` 와 같은 모양)
==============================================================================
운영자가 인가 기록 다섯 칸(기관·종류·번호·확인일·범위)을 선언하면 유통 관문이 열린다. 판정은 `src/domain/distribution_gate.py`,
기록은 `src/services/distribution_gate_store.py`. 선언한 사람은 ★토큰에서만★ 온다(본문에 그 칸이 없다 — 끼우면 422).
화면은 만들지 않는다(BV7 과 같다 — API 로).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from src.api.auth import require_admin
from src.domain.auth_identity import Principal
from src.services import distribution_gate_store

router = APIRouter(prefix="/api/v1/admin/distribution-gate", tags=["distribution-gate"])


class DeclareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authority: str
    license_kind: str
    license_no: str
    verified_at: str
    scope: str


@router.get("")
def get_gate(p: Principal = Depends(require_admin)):
    return {"current": distribution_gate_store.current_record(), "gate": distribution_gate_store.gate(),
            "history": distribution_gate_store.history()}


@router.post("", status_code=201)
def declare_gate(req: DeclareRequest, p: Principal = Depends(require_admin)):
    try:
        rec = distribution_gate_store.declare(p.username, **req.model_dump())
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return {"current": rec, "gate": distribution_gate_store.gate()}


@router.delete("")
def revoke_gate(p: Principal = Depends(require_admin)):
    if not distribution_gate_store.revoke(p.username):
        raise HTTPException(404, "지금 열려 있는 유통 관문이 없어요.")
    return {"revoked": True, "revoked_by": p.username, "gate": distribution_gate_store.gate()}
