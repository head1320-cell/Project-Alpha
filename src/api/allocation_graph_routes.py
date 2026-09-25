"""AAS 노드 캔버스의 문 — 카탈로그 · 검증 · 실행 (BI2)
==============================================================================
스펙 `docs/superpowers/specs/2026-09-25-aas-node-canvas-design.md` · ADR 002

★본문을 엄격한 요청 모델로 받지 않는다★ 불러온 파일이 틀렸을 때 422 한 덩어리로
거절하면 캔버스는 **어느 노드가** 왜 틀렸는지 그릴 수 없다. 실행기가 명명된 오류 코드와
노드 id 를 돌려주므로 문은 그 보고를 그대로 200 으로 넘긴다(`ok` 가 판정이다).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body

from src.api.allocation_graph_nodes import PORT_TYPES, REGISTRY
from src.engine import portfolio_graph as pg

router = APIRouter(prefix="/api/v1/allocation/graph", tags=["allocation-graph"])


@router.get("/node-types")
def graph_node_types() -> dict:
    """팔레트의 단일 출처 — 캔버스는 이것만 보고 노드·포트·파라미터 폼을 그린다."""
    return {"format": pg.FORMAT, "version": pg.VERSION, "port_types": list(PORT_TYPES),
            "nodes": REGISTRY.catalog()}


@router.post("/validate")
def graph_validate(graph: Any = Body(...)) -> dict:
    return pg.validate(graph, REGISTRY)


@router.post("/run")
def graph_run(graph: Any = Body(...)) -> dict:
    """위상 순서로 실행. 노드별 `{status, reason, view, provenance}` — 실패는 번지되
    지어내지 않는다(`portfolio_graph` 의 약속)."""
    return pg.run(graph, REGISTRY)
