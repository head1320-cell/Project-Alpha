"""포트폴리오 그래프 실행기 — ★편집기는 캔버스, 계산은 여기★ (BI1)
==============================================================================
스펙 `docs/superpowers/specs/2026-09-25-aas-node-canvas-design.md` · ADR 002

AAS 캔버스가 그린 노드-링크 그래프(파일 포맷 `project-alpha.portfolio-graph` v1)를
검증하고 위상 순서로 실행한다. 이 모듈은 **순수**하다 — 어떤 노드도 알지 못하고, 노드는
`Registry` 에 등록된다(실제 포트폴리오 노드는 `src/api/allocation_graph_nodes.py`).

패턴은 `dag_runner.py`(순환 검증 → 위상 정렬 → 레지스트리)에서 왔지만 스키마를 섞지
않는다 — 저쪽은 단일 종목 신호 전용이고 합성 경로가 있다.

## ★이 실행기가 약속하는 것★

1. **아무 노드도 버리지 않는다.** 모르는 타입·깨진 파라미터·빠진 입력의 노드도 결과에 자기
   자리를 갖고 `blocked` + 사유로 남는다. 캔버스는 그 자리에 빨간 노드를 그린다.
2. **실패는 하류로 번지되 지어내지 않는다.** 상류가 `failed`/`blocked` 면 하류는 호출조차
   되지 않고 `blocked` + *어느 상류 때문인지*. 기본값으로 계속 도는 경로가 없다.
3. **옆 가지는 계속 돈다.** 한 가지의 실패가 관계없는 노드를 멈추지 않는다.
4. 파일 포맷·버전이 다르거나 순환이 있으면 **아무것도 실행하지 않는다** — 순서를 정할 수
   없거나, 이 파일이 무엇을 뜻하는지 모르기 때문이다.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

FORMAT = "project-alpha.portfolio-graph"
VERSION = 1

STATUS_OK = "ok"
STATUS_BLOCKED = "blocked"
STATUS_FAILED = "failed"

#: 그래프 전체를 무효로 만드는 오류 — 하나라도 있으면 실행하지 않는다.
FATAL_CODES = frozenset({"document", "format", "version", "cycle"})


class NodeFailure(Exception):
    """노드가 **아는** 이유로 실패했다 — 사유 문장이 그대로 결과에 실린다."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Port:
    name: str
    type: str
    required: bool = True


@dataclass
class NodeOutput:
    """`values` 는 하류로 넘기는 **내부 값**(배열·프레임 가능), `view` 는 응답에 싣는
    JSON 요약, `provenance` 는 출처·등급·미상 사유."""
    values: dict[str, Any]
    view: dict[str, Any] | None = None
    provenance: dict[str, Any] = field(default_factory=dict)


RunFn = Callable[[dict[str, Any], Any], NodeOutput]


@dataclass(frozen=True)
class NodeSpec:
    type: str
    label: str
    inputs: tuple[Port, ...]
    outputs: tuple[Port, ...]
    run: RunFn
    params_model: type[BaseModel] | None = None
    description: str = ""
    category: str = ""
    #: ★사람이 읽는 층★ (BJ1) — 워크플로우 단계 키, 쉬운 이름·설명, 결과 설명기.
    #: 설명기는 `(view, provenance, params) -> dict` 이고 **결정적**이어야 한다(서버가 문장을
    #: 만들고 화면은 그리기만 한다 — 사용자 결정).
    stage: str = ""
    plain_label: str = ""
    plain_description: str = ""
    explain: Callable[[dict, dict, Any], dict] | None = None

    @property
    def human(self) -> str:
        return self.plain_label or self.label

    def input(self, name: str) -> Port | None:
        return next((p for p in self.inputs if p.name == name), None)

    def output(self, name: str) -> Port | None:
        return next((p for p in self.outputs if p.name == name), None)


class Registry:
    """노드 타입 레지스트리. ★포트 타입은 선언된 것만★ — 오타 난 타입은 연결이 영원히
    안 되는 노드를 조용히 만든다."""

    def __init__(self, port_types: tuple[str, ...]):
        self.port_types = tuple(port_types)
        self._specs: dict[str, NodeSpec] = {}

    def register(self, spec: NodeSpec) -> None:
        if spec.type in self._specs:
            raise ValueError(f"노드 타입 중복 등록: {spec.type}")
        for p in (*spec.inputs, *spec.outputs):
            if p.type not in self.port_types:
                raise ValueError(f"{spec.type}.{p.name}: 선언되지 않은 포트 타입 {p.type}")
        self._specs[spec.type] = spec

    def get(self, type_: str) -> NodeSpec | None:
        return self._specs.get(type_)

    def types(self) -> list[str]:
        return list(self._specs)

    def catalog(self) -> list[dict]:
        """팔레트의 단일 출처 — 캔버스는 이것만 보고 노드를 그린다."""
        return [{
            "type": s.type, "label": s.label, "category": s.category,
            "description": s.description,
            "stage": s.stage, "plain_label": s.human, "plain_description": s.plain_description,
            "inputs": [{"name": p.name, "type": p.type, "required": p.required}
                       for p in s.inputs],
            "outputs": [{"name": p.name, "type": p.type} for p in s.outputs],
            "params_schema": (s.params_model.model_json_schema()
                              if s.params_model is not None else None),
        } for s in self._specs.values()]


# ── 검증 ─────────────────────────────────────────────────────────────────────

def _err(code: str, message: str, *, node_id: str | None = None,
         edge_id: str | None = None) -> dict:
    return {"code": code, "message": message, "node_id": node_id, "edge_id": edge_id}


def _edge_id(e: Mapping) -> str:
    return str(e.get("id") or f"{e.get('source')}.{e.get('source_port')}"
                               f"->{e.get('target')}.{e.get('target_port')}")


def _document_errors(graph: Any) -> list[dict]:
    if not isinstance(graph, Mapping):
        return [_err("document", "그래프 문서가 객체가 아닙니다.")]
    out = []
    if graph.get("format") != FORMAT:
        out.append(_err("format", f"이 파일은 포트폴리오 그래프가 아닙니다 — format="
                                  f"{graph.get('format')!r}, 기대값 {FORMAT!r}."))
    v = graph.get("version")
    if not (isinstance(v, int) and not isinstance(v, bool) and v == VERSION):
        out.append(_err("version", f"지원하지 않는 버전입니다 — version={v!r}, "
                                   f"이 서버는 {VERSION} 만 읽습니다."))
    if not isinstance(graph.get("nodes"), list) or not isinstance(graph.get("edges"), list):
        out.append(_err("document", "nodes·edges 가 목록이 아닙니다."))
    return out


def _parse_params(spec: NodeSpec, raw: Any):
    """`(params, 오류문장|None)`."""
    if spec.params_model is None:
        return None, None
    try:
        return spec.params_model.model_validate(raw or {}), None
    except ValidationError as e:
        parts = [f"{'.'.join(str(x) for x in d['loc']) or '(전체)'}: {d['msg']}"
                 + (f" (받은 값 {d['input']!r})" if d.get("type") != "missing" else "")
                 for d in e.errors()]
        return None, "; ".join(parts)


def _analyse(graph: Mapping, registry: Registry):
    """노드·링크 수준 검사. `(errors, nodes, specs, params, incoming, order|None)`."""
    errors: list[dict] = []
    nodes: dict[str, Mapping] = {}
    for raw in graph["nodes"]:
        nid = str((raw or {}).get("id") or "") if isinstance(raw, Mapping) else ""
        if not nid:
            errors.append(_err("document", "id 가 없는 노드가 있습니다."))
            continue
        if nid in nodes:
            errors.append(_err("duplicate_node", f"노드 id 중복: {nid}", node_id=nid))
            continue
        nodes[nid] = raw

    specs: dict[str, NodeSpec | None] = {}
    params: dict[str, Any] = {}
    for nid, raw in nodes.items():
        spec = registry.get(str(raw.get("type")))
        specs[nid] = spec
        if spec is None:
            errors.append(_err("unknown_type",
                               f"모르는 노드 타입 {raw.get('type')!r} — 이 서버에 없는 노드입니다"
                               "(다른 버전에서 만든 파일일 수 있습니다).", node_id=nid))
            continue
        params[nid], why = _parse_params(spec, raw.get("params"))
        if why:
            errors.append(_err("bad_params", f"파라미터 오류 — {why}", node_id=nid))

    # incoming[target][port] = (source, source_port)
    incoming: dict[str, dict[str, tuple[str, str]]] = {nid: {} for nid in nodes}
    adj: dict[str, set[str]] = {nid: set() for nid in nodes}
    for e in graph["edges"]:
        if not isinstance(e, Mapping):
            errors.append(_err("document", "링크가 객체가 아닙니다."))
            continue
        eid = _edge_id(e)
        s, sp, t, tp = (str(e.get(k) or "") for k in
                        ("source", "source_port", "target", "target_port"))
        if s not in nodes or t not in nodes:
            errors.append(_err("dangling_edge",
                               f"없는 노드를 잇는 링크입니다 ({s or '?'} → {t or '?'}).",
                               edge_id=eid))
            continue
        ss, ts = specs.get(s), specs.get(t)
        if ss is None or ts is None:
            # 모르는 노드에 닿은 링크 — 그 노드가 이미 오류로 보고됐다. 순서에는 넣는다.
            adj[s].add(t)
            incoming[t].setdefault(tp, (s, sp))
            continue
        op, ip = ss.output(sp), ts.input(tp)
        if op is None or ip is None:
            which = f"{s}.{sp}" if op is None else f"{t}.{tp}"
            errors.append(_err("unknown_port", f"없는 포트 {which}", edge_id=eid,
                               node_id=s if op is None else t))
            continue
        if op.type != ip.type:
            errors.append(_err("type_mismatch",
                               f"타입이 맞지 않습니다 — {s}.{sp}({op.type}) → {t}.{tp}({ip.type}).",
                               edge_id=eid, node_id=t))
            continue
        if tp in incoming[t]:
            errors.append(_err("multiple_inputs",
                               f"입력 {t}.{tp} 에 링크가 둘 이상입니다 — 입력 하나에는 하나만.",
                               edge_id=eid, node_id=t))
            continue
        incoming[t][tp] = (s, sp)
        adj[s].add(t)

    for nid, spec in specs.items():
        if spec is None:
            continue
        for p in spec.inputs:
            if p.required and p.name not in incoming[nid]:
                errors.append(_err("missing_input",
                                   f"필수 입력 {p.name}({p.type}) 이 연결되지 않았습니다.",
                                   node_id=nid))

    order = _topo(list(nodes), adj)
    if order is None:
        errors.append(_err("cycle", "그래프에 순환이 있습니다 — 실행 순서를 정할 수 없습니다."))
    return errors, nodes, specs, params, incoming, order


def _topo(ids: list[str], adj: dict[str, set[str]]) -> list[str] | None:
    """칸 알고리즘 — 동률은 **파일 순서**대로(같은 파일은 늘 같은 순서)."""
    rank = {n: i for i, n in enumerate(ids)}
    indeg = {n: 0 for n in ids}
    for s in ids:
        for t in adj[s]:
            indeg[t] += 1
    ready = sorted((n for n in ids if indeg[n] == 0), key=rank.__getitem__)
    out: list[str] = []
    while ready:
        n = ready.pop(0)
        out.append(n)
        for t in sorted(adj[n], key=rank.__getitem__):
            indeg[t] -= 1
            if indeg[t] == 0:
                ready.append(t)
        ready.sort(key=rank.__getitem__)
    return out if len(out) == len(ids) else None


def validate(graph: Any, registry: Registry) -> dict:
    """`{"ok": bool, "errors": [{code, message, node_id, edge_id}]}`."""
    doc = _document_errors(graph)
    if doc:
        return {"ok": False, "errors": doc}
    errors = _analyse(graph, registry)[0]
    return {"ok": not errors, "errors": errors}


# ── 실행 ─────────────────────────────────────────────────────────────────────

def _blocked(spec_type: str | None, reason: str, explain: dict | None = None) -> dict:
    return {"type": spec_type, "status": STATUS_BLOCKED, "reason": reason,
            "view": None, "provenance": {}, "explain": explain}


# ── 쉬운 말 설명 (BJ1) ────────────────────────────────────────────────────────

def _explain_failed(reason: str) -> dict:
    return {"title": "계산하지 못했어요", "trust": [{"state": STATUS_FAILED, "text": reason}]}


def _explain_ok(spec: NodeSpec, out: NodeOutput, params: Any) -> dict:
    """노드 설명기를 부른다. ★설명이 실패해도 결과를 지우지 않고, 문장을 지어내지 않는다★ —
    "설명을 만들지 못했어요" + 예외 종류를 몰라요(unknown)로 싣는다."""
    if spec.explain is None:
        return {"title": f"‘{spec.human}’를 계산했어요"}
    try:
        ex = spec.explain(out.view or {}, dict(out.provenance or {}), params)
        if not isinstance(ex, dict) or not ex.get("title"):
            raise TypeError("설명기가 title 을 가진 dict 를 돌려주지 않았습니다")
        return ex
    except Exception as e:                            # noqa: BLE001
        logger.exception(f"설명기 실패: {spec.type}")
        return {"title": f"‘{spec.human}’를 계산했어요",
                "trust": [{"state": "unknown",
                           "text": f"설명을 만들지 못했어요({type(e).__name__}) — 결과 숫자는 자세히 탭에 있어요."}]}


def run(graph: Any, registry: Registry) -> dict:
    """검증 → 위상 순서 실행. 반환:
    `{"ok", "errors", "order", "nodes": {id: {type, status, reason, view, provenance}}}`.
    """
    doc = _document_errors(graph)
    if doc:
        return {"ok": False, "errors": doc, "order": [], "nodes": {}}
    errors, nodes, specs, params, incoming, order = _analyse(graph, registry)
    if order is None:
        return {"ok": False, "errors": errors, "order": [], "nodes": {}}

    own_error: dict[str, str] = {}
    for e in errors:
        nid = e.get("node_id")
        if nid and nid not in own_error:
            own_error[nid] = e["message"]

    results: dict[str, dict] = {}
    values: dict[str, dict[str, Any]] = {}
    for nid in order:
        raw_type = str(nodes[nid].get("type"))
        spec = specs[nid]
        if nid in own_error:
            ex = ({"title": "모르는 노드예요",
                   "facts": [f"‘{raw_type}’는 이 서버에 없는 노드예요. 설정은 그대로 남아 있어요."]}
                  if spec is None else
                  {"title": "설정을 확인해 주세요", "facts": [own_error[nid]]})
            results[nid] = _blocked(raw_type, own_error[nid], ex)
            continue
        bad_up = [(src, results[src]) for src, _ in incoming[nid].values()
                  if results.get(src, {}).get("status") != STATUS_OK]
        if bad_up:
            src, r = bad_up[0]
            up = registry.get(str(r.get("type")))
            up_name = up.human if up else str(r.get("type"))
            results[nid] = _blocked(
                raw_type, f"상류 {src}({r.get('type')}) 가 {r.get('status')} 입니다 — {r.get('reason')}",
                {"title": "계산하지 못했어요",
                 "facts": [f"앞 단계 ‘{up_name}’에서 멈춰서 이 단계는 계산하지 않았어요."]})
            continue
        assert spec is not None                       # 모르는 타입은 own_error 에 있다
        inputs = {p.name: None for p in spec.inputs}
        for port, (src, sport) in incoming[nid].items():
            inputs[port] = values[src][sport]
        try:
            out = spec.run(inputs, params.get(nid))
            missing = [p.name for p in spec.outputs if p.name not in (out.values or {})]
            if missing:
                raise NodeFailure(f"노드가 선언한 출력 {', '.join(missing)} 을 내지 않았습니다.")
        except NodeFailure as e:
            results[nid] = {"type": raw_type, "status": STATUS_FAILED, "reason": e.reason,
                            "view": None, "provenance": {}, "explain": _explain_failed(e.reason)}
            continue
        except Exception as e:                        # noqa: BLE001
            logger.exception(f"그래프 노드 {nid}({raw_type}) 처리 실패")
            why = f"처리 중 오류({type(e).__name__}) — 서버 로그를 보세요."
            results[nid] = {"type": raw_type, "status": STATUS_FAILED, "reason": why,
                            "view": None, "provenance": {}, "explain": _explain_failed(why)}
            continue
        values[nid] = out.values
        results[nid] = {"type": raw_type, "status": STATUS_OK, "reason": None,
                        "view": out.view, "provenance": dict(out.provenance or {}),
                        "explain": _explain_ok(spec, out, params.get(nid))}

    ok = not errors and all(r["status"] == STATUS_OK for r in results.values())
    return {"ok": ok, "errors": errors, "order": order, "nodes": results}
