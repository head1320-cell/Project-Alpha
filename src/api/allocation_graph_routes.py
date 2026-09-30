"""AAS 노드 캔버스의 문 — 카탈로그 · 검증 · 실행 (BI2)
==============================================================================
스펙 `docs/superpowers/specs/2026-09-25-aas-node-canvas-design.md` · ADR 002

★본문을 엄격한 요청 모델로 받지 않는다★ 불러온 파일이 틀렸을 때 422 한 덩어리로
거절하면 캔버스는 **어느 노드가** 왜 틀렸는지 그릴 수 없다. 실행기가 명명된 오류 코드와
노드 id 를 돌려주므로 문은 그 보고를 그대로 200 으로 넘긴다(`ok` 가 판정이다).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Query
from pydantic import BaseModel, Field

from src.api.allocation_graph_nodes import PORT_PLAIN, PORT_TYPES, REGISTRY, STAGES
from src.api.allocation_graph_roles import NEED_PLAIN
from src.domain import design_procedure as proc
from src.domain.workflow_gates import GATES
from src.domain.workflow_gates import evaluate as evaluate_gates
from src.engine import portfolio_graph as pg

router = APIRouter(prefix="/api/v1/allocation/graph", tags=["allocation-graph"])


@router.get("/node-types")
def graph_node_types() -> dict:
    """팔레트의 단일 출처 — 캔버스는 이것만 보고 노드·포트·파라미터 폼을 그린다."""
    return {"format": pg.FORMAT, "version": pg.VERSION, "port_types": list(PORT_TYPES),
            "stages": STAGES, "nodes": REGISTRY.catalog(),
            # BT1 — 화면이 사본을 들지 않게: 포트 쉬운 이름 · 관문 이름(레일의 빈 역).
            "port_plain": PORT_PLAIN, "gates": [{"key": k, "label": lbl} for k, lbl in GATES]}


def _kinds() -> dict[str, dict]:
    """절차 판정이 읽는 종류 표 — 포트·단계·쉬운 이름만(파라미터 스키마는 필요 없다)."""
    out = {}
    for t in REGISTRY.types():
        s = REGISTRY.get(t)
        out[t] = {"stage": s.stage, "plain_label": s.human,
                  "inputs": [{"name": p.name, "type": p.type, "required": p.required, "needs": list(p.needs)}
                             for p in s.inputs],
                  "outputs": [{"name": p.name, "type": p.type, "gives": [g.to_dict() for g in p.gives]}
                              for p in s.outputs]}
    return out


def _needs_errors(nodes: list, edges: list, kinds: dict[str, dict]) -> list[dict]:
    """★타입은 맞지만 계산할 때 실패할 선★ (BT1) — 확실할 때만. 실행 결과는 바꾸지 않는다(`/run` 은 이것을 모른다)."""
    out = []
    for u in proc.unmet_needs(nodes, edges, kinds):
        src, dst = kinds[str(_type_of(nodes, u["source"]))], kinds[str(_type_of(nodes, u["target"]))]
        what = NEED_PLAIN.get(u["key"], u["key"])
        always = sorted({k["plain_label"] for k in kinds.values()
                         for o in k["outputs"] for g in o["gives"] if g["key"] == u["key"]
                         and not g.get("when") and not g.get("from")})
        # 보내는 쪽이 조건부로 줄 수 있으면(입력을 이으면) 그것을 먼저 말한다 — 가장 가까운 고치는 법.
        own_when = next((g["when"] for o in src["outputs"] if o["name"] == u["source_port"]
                         for g in o["gives"] if g["key"] == u["key"] and g.get("when")), None)
        if own_when:
            ptype = next((i["type"] for i in src["inputs"] if i["name"] == own_when), own_when)
            fix = f"‘{src['plain_label']}’에 {proc.quote_obj(PORT_PLAIN.get(ptype, own_when))} 이으면 줄 수 있어요."
        else:
            fix = f"{' · '.join(f'‘{g}’' for g in always)}의 비중을 이어 주세요." if always else None
        edge = next((e for e in edges if isinstance(e, dict) and e.get("source") == u["source"]
                     and e.get("source_port") == u["source_port"] and e.get("target") == u["target"]
                     and e.get("target_port") == u["target_port"]), {})
        out.append({"code": "needs_unmet", "node_id": u["target"], "edge_id": pg._edge_id(edge) if edge else None,
                    "message": f"‘{dst['plain_label']}’에 필요한 {what}이 ‘{src['plain_label']}’의 비중에는 없어요 — "
                               "이대로 계산하면 실패해요.",
                    "fix": fix})
    return out


def _type_of(nodes: list, nid: str) -> str | None:
    return next((n.get("type") for n in nodes if isinstance(n, dict) and n.get("id") == nid), None)


def _procedure(graph: Any, kinds: dict[str, dict]) -> dict | None:
    if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list) \
            or not isinstance(graph.get("edges"), list):
        return None
    return proc.evaluate(graph["nodes"], graph["edges"], kinds, STAGES, PORT_PLAIN)


@router.post("/validate")
def graph_validate(graph: Any = Body(...)) -> dict:
    """검증 + ★절차★(BT1) — 편집마다 불리므로 계산 전에도 절차 탭·다음 한 걸음이 보인다."""
    rep = pg.validate(graph, REGISTRY)
    kinds = _kinds()
    if isinstance(graph, dict) and not any(e.get("code") in pg.FATAL_CODES or e.get("code") == "document"
                                           for e in rep["errors"]):
        extra = _needs_errors(graph["nodes"], graph["edges"], kinds)
        rep = {"ok": rep["ok"] and not extra, "errors": rep["errors"] + extra}
    return {**rep, "procedure": _procedure(graph, kinds)}


@router.post("/run")
def graph_run(graph: Any = Body(...), targets: str | None = Query(None, max_length=2000)) -> dict:
    """위상 순서로 실행. 노드별 `{status, reason, view, provenance}` — 실패는 번지되
    지어내지 않는다(`portfolio_graph` 의 약속).

    `?targets=a,b` 는 ★그 노드들과 조상만★ 계산한다(BL1 "여기까지 계산"). 부분 계산에는 증거 관문 판정을 내지
    않는다 — 관문은 그래프 전체를 보고 판정하는데 계산하지 않은 노드를 "건너뜀" 으로 셀 수 없다(`gates: null` + 사유).
    """
    ids = [t for t in (targets or "").split(",") if t] if targets is not None else None
    report = pg.run(graph, REGISTRY, targets=ids)
    if ids is not None:
        report["gates"] = None
        report["gates_reason"] = "일부만 계산했어요 — 증거 관문은 전체를 계산할 때 판정해요."
        return report
    # ★증거 관문★ (BJ1) — 그래프 구성과 노드 출처로 8 관문을 판정한다. 건너뛴 관문은 건너뜀이다.
    nodes = graph.get("nodes") if isinstance(graph, dict) and isinstance(graph.get("nodes"), list) else []
    stage_of = {t: REGISTRY.get(t).stage for t in REGISTRY.types()}
    history = {t: REGISTRY.get(t).human for t in REGISTRY.types() if REGISTRY.get(t).simulates_history}
    report["gates"] = evaluate_gates([n for n in nodes if isinstance(n, dict)], report["nodes"], stage_of,
                                     history_types=history)
    report["procedure"] = _procedure(graph, _kinds())
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


class BranchSeries(BaseModel):
    label: str = Field(..., min_length=1, max_length=80)
    #: 백테스트 노드가 준 누적 곡선(`equity_curve`) 그대로 — 화면이 수익을 다시 계산하지 않는다.
    equity: list[float] = Field(..., min_length=2, max_length=20_000)


class BranchEvidenceRequest(BaseModel):
    series: list[BranchSeries] = Field(..., min_length=1, max_length=40)


@router.post("/branch-evidence")
def graph_branch_evidence(req: BranchEvidenceRequest) -> dict:
    """갈래 비교의 다중 비교 보정 (BO O3) — 원본 + 갈래들의 과거 성과 곡선 → PSR·DSR. ★표시만★ — 저장하지 않는다.

    곡선이 망가졌으면(0 이하·비유한) 그 행만 사유를 달고 N 에는 넣는다 — 비교한 수를 줄이면 보정이 약해진다.
    """
    from src.engine import deflated_sharpe as ds
    rows, broken = [], {}
    for s in req.series:
        try:
            rows.append({"label": s.label, "returns": ds.returns_from_equity(s.equity)})
        except ValueError as e:
            broken[s.label] = str(e)
            rows.append({"label": s.label, "returns": []})
    out = ds.compare(rows)
    for r in out["rows"]:
        if r["label"] in broken:
            r["reason"] = broken[r["label"]]
    return out
