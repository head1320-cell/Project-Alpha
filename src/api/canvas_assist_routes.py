"""캔버스 AI 도우미 경로(AI0) — ★로그인한 사람만★: Claude 호출은 운영자 비용이고 한도는 사용자별이다.

`/api/v1/allocation` 아래에 두지 않는다 — 로그인 지도에서 '포트폴리오 설계' 화면(그 접두사)은 열려 있다고 말하고,
열린 화면의 접두사 아래는 잠글 수 없다(`tests/test_login_access_map.py` ③). 화면은 열려 있고 AI 만 로그인이다.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends

from src.api import allocation_graph_routes as graph_routes
from src.api.auth import require_login
from src.domain.auth_identity import Principal
from src.services.canvas_assist import service

router = APIRouter(prefix="/api/v1/assist/canvas", tags=["canvas-assist"])


@router.post("/suggest")
def canvas_suggest(graph: Any = Body(...), p: Principal = Depends(require_login)) -> dict:
    """다음에 붙일 노드 1~3 — 검사를 통과한 것만. 키·한도·거절이면 `available:false` + 사유 + 규칙 대체."""
    return service.suggest(graph, p.username, catalog=graph_routes._kinds, validate=graph_routes.graph_validate)
