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
from pydantic import BaseModel, Field

from src.api.allocation_graph_nodes import PORT_TYPES, REGISTRY, STAGES
from src.domain.workflow_gates import evaluate as evaluate_gates
from src.engine import portfolio_graph as pg

router = APIRouter(prefix="/api/v1/allocation/graph", tags=["allocation-graph"])


@router.get("/node-types")
def graph_node_types() -> dict:
    """팔레트의 단일 출처 — 캔버스는 이것만 보고 노드·포트·파라미터 폼을 그린다."""
    return {"format": pg.FORMAT, "version": pg.VERSION, "port_types": list(PORT_TYPES),
            "stages": STAGES, "nodes": REGISTRY.catalog()}


@router.post("/validate")
def graph_validate(graph: Any = Body(...)) -> dict:
    return pg.validate(graph, REGISTRY)


@router.post("/run")
def graph_run(graph: Any = Body(...)) -> dict:
    """위상 순서로 실행. 노드별 `{status, reason, view, provenance}` — 실패는 번지되
    지어내지 않는다(`portfolio_graph` 의 약속)."""
    report = pg.run(graph, REGISTRY)
    # ★증거 관문★ (BJ1) — 그래프 구성과 노드 출처로 8 관문을 판정한다. 건너뛴 관문은 건너뜀이다.
    nodes = graph.get("nodes") if isinstance(graph, dict) and isinstance(graph.get("nodes"), list) else []
    stage_of = {t: REGISTRY.get(t).stage for t in REGISTRY.types()}
    report["gates"] = evaluate_gates([n for n in nodes if isinstance(n, dict)], report["nodes"], stage_of)
    return report


class GraphSaveRequest(BaseModel):
    graph: Any
    node_id: str = Field(..., min_length=1, max_length=120)
    #: 사용자가 본 미리보기의 `view_hash` — 지금 계산과 같을 때만 저장한다.
    preview_hash: str = Field(..., min_length=1, max_length=64)


@router.post("/save")
def graph_save(req: GraphSaveRequest) -> dict:
    """★저장은 여기서만★ (BK0) — `/run` 은 어떤 노드도 DB 에 쓰지 않는다(사용자 결정).

    그래프를 다시 계산해 그 노드의 미리보기 해시가 같을 때만 노드의 저장 함수를 **한 번** 부른다.
    거절(`ok: false` + `code`)은 200 으로 — 캔버스가 사유를 그 노드 옆에 그린다.
    """
    return pg.save_node(req.graph, req.node_id, req.preview_hash, REGISTRY)
