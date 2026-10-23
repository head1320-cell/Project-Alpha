"""캔버스 AI 도우미 경로(AI0) — ★로그인한 사람만★: Claude 호출은 운영자 비용이고 한도는 사용자별이다.

`/api/v1/allocation` 아래에 두지 않는다 — 로그인 지도에서 '포트폴리오 설계' 화면(그 접두사)은 열려 있다고 말하고,
열린 화면의 접두사 아래는 잠글 수 없다(`tests/test_login_access_map.py` ③). 화면은 열려 있고 AI 만 로그인이다.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel, Field, field_validator

from src.api import allocation_graph_routes as graph_routes
from src.api.auth import derived_key, require_login
from src.domain import fact_seal
from src.domain.auth_identity import Principal
from src.services.canvas_assist import service

#: 풀어 쓰기 요청 상한 — 사실 수·설명 하나의 크기(넘으면 422). 그래프 노드보다 많을 일이 없다.
MAX_FACTS = 120
MAX_EXPLAIN_BYTES = 8 * 1024

router = APIRouter(prefix="/api/v1/assist/canvas", tags=["canvas-assist"])


@router.post("/suggest")
def canvas_suggest(graph: Any = Body(...), p: Principal = Depends(require_login)) -> dict:
    """다음에 붙일 노드 1~3 — 검사를 통과한 것만. 키·한도·거절이면 `available:false` + 사유 + 규칙 대체."""
    return service.suggest(graph, p.username, catalog=graph_routes._kinds, validate=graph_routes.graph_validate)


class NarrateFact(BaseModel):
    """`/run` 이 낸 노드 설명 하나와 그 봉인(`explain_sig`) — 화면이 받은 그대로 돌려보낸다."""
    node_id: str = Field(..., min_length=1, max_length=120)
    explain: dict
    sig: str = Field(..., min_length=1, max_length=128)

    @field_validator("explain")
    @classmethod
    def _small(cls, v: dict) -> dict:
        if len(json.dumps(v, ensure_ascii=False, default=str).encode("utf-8")) > MAX_EXPLAIN_BYTES:
            raise ValueError(f"설명 하나가 {MAX_EXPLAIN_BYTES}바이트를 넘어요")
        return v


class NarrateRequest(BaseModel):
    graph: Any
    facts: list[NarrateFact] = Field(..., max_length=MAX_FACTS)


@router.post("/narrate")
def canvas_narrate(req: NarrateRequest, p: Principal = Depends(require_login)) -> dict:
    """AI2 — 계산 결과를 읽는 순서로 풀어 쓴다. ★서버 봉인이 지금 그래프로 확인되는 설명만★ 근거 · 문단마다 근거 노드 ·
    연습용이면 서버가 경고를 붙인다. 키·한도·거절이면 `available:false` + 사유(확인 못 한 설명은 `dropped`)."""
    return service.narrate(req.graph, [f.model_dump() for f in req.facts], p.username,
                           catalog=graph_routes._kinds, key=derived_key(fact_seal.PURPOSE))
