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
5. **계보는 하류로 흐른다** (BK0). 노드가 단 태그(연습용 합성 · 시점 정합 · 노출을 얹음)는
   모든 하류 결과의 `lineage` 에 합쳐진다 — 직접 부모만이 아니다. 노드는 `admits` 로 받지 않을
   계보를 **거절**할 수 있고(실패 + 사유), 조용히 벗겨 내는 경로는 없다.
6. **계산은 쓰지 않는다** (BK0). `run` 은 어떤 노드의 `save` 도 부르지 않는다. 저장은
   `save_node` 가 그래프를 다시 계산해 **미리보기 해시가 같을 때만** 한 번 부른다.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
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
class Gives:
    """출력 포트가 싣는 값 하나(BT1) — 타입은 같아도 받는 쪽이 요구하는 값(`Port.needs`)이 있다.

    - `Gives("req")` — 늘 준다.
    - `Gives("sigma_annual", when="returns")` — 입력 `returns` 가 이어졌을 때 **줄 수도** 있다(데이터·설정에 따라).
    - `Gives("sigma_annual", from_="weights")` — 입력 `weights` 가 받은 값을 넘긴다.
    """
    key: str
    when: str | None = None
    from_: str | None = None

    def to_dict(self) -> dict:
        return {"key": self.key, **({"when": self.when} if self.when else {}),
                **({"from": self.from_} if self.from_ else {})}


@dataclass(frozen=True)
class Port:
    name: str
    type: str
    required: bool = True
    #: 받는 쪽이 이 입력을 **무엇에 쓰는지** — 캔버스 선 판이 그대로 보인다(BT1). 모르면 비워 둔다(지어내지 않는다).
    role: str = ""
    #: 입력: 보내는 쪽이 꼭 실어야 하는 값 키(`Gives.key`). 안 실리면 계산할 때 실패한다.
    needs: tuple[str, ...] = ()
    #: 출력: 이 포트가 싣는 값(`Gives`).
    gives: tuple[Gives, ...] = ()


@dataclass
class NodeOutput:
    """`values` 는 하류로 넘기는 **내부 값**(배열·프레임 가능), `view` 는 응답에 싣는
    JSON 요약, `provenance` 는 출처·등급·미상 사유, `tags` 는 **하류로 전이되는 계보**
    (`pit` · `practice` · `overlay` · `sources` — `merge_lineage` 참조)."""
    values: dict[str, Any]
    view: dict[str, Any] | None = None
    provenance: dict[str, Any] = field(default_factory=dict)
    tags: dict[str, Any] = field(default_factory=dict)


# ── 계보 (BK0) ───────────────────────────────────────────────────────────────

#: 시점 정합 주장의 강도 — **약한 쪽이 이긴다**. 선언하지 않은 노드(None)는 판정에 끼지 않는다
#: (모른다고 선언한 것은 "unknown" 이다 — 둘을 섞지 않는다).
PIT_ORDER = ("pit", "unknown", "forward_only")


def merge_lineage(*parts: Mapping[str, Any] | None) -> dict:
    """계보 합치기(순수). `pit` 은 가장 약한 값, `practice`·`overlay` 는 OR, `sources` 는 합집합.

    - `practice` — mock 게이트를 지나 **합성값**을 썼다(연습용).
    - `pit` — `pit`(시점 고정) · `unknown`(모름) · `forward_only`(지금 시점 전용 — 과거에 쓰면 룩어헤드).
    - `overlay` — 오늘 계산한 노출 조절을 얹은 비중(과거 전체에 쓰면 룩어헤드).
    """
    pit: str | None = None
    practice = overlay = False
    sources: set[str] = set()
    for part in parts:
        if not part:
            continue
        p = part.get("pit")
        if p in PIT_ORDER and (pit is None or PIT_ORDER.index(p) > PIT_ORDER.index(pit)):
            pit = p
        practice = practice or bool(part.get("practice"))
        overlay = overlay or bool(part.get("overlay"))
        sources.update(str(x) for x in (part.get("sources") or ()))
    return {"pit": pit, "practice": practice, "overlay": overlay, "sources": sorted(sources)}


def view_hash(view: Any) -> str:
    """미리보기 해시 — 같은 view 는 같은 값. 저장 전 "지금 계산 == 본 미리보기" 확인에 쓴다."""
    blob = json.dumps(view, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


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
    #: 받지 않을 입력 계보 — 사유 문장을 돌려주면 노드는 실행되지 않고 **실패**한다 (BK0).
    admits: Callable[[dict], str | None] | None = None
    #: 저장 액션 `(values, view, params) -> {"saved_id", "text"}` — `run` 은 절대 부르지 않는다.
    save: Callable[[dict, dict, Any], dict] | None = None
    #: 저장 버튼에 쓰는 말(BL2) — 버튼은 누르면 일어나는 일을 말한다('연구 기록 남기기'). `save` 가 있으면 반드시 준다.
    save_label: str | None = None
    #: 참이면 `run(inputs, params, lineage)` — 입력 계보를 **읽어야** 판단이 서는 노드(BK W4: 실행 목표는
    #: 연습용 데이터로 만든 비중을 실행 가능으로 두지 않는다). 거절만 할 거라면 `admits` 를 쓴다.
    wants_lineage: bool = False
    #: 캔버스 위 작은 그림(BM C1) `view -> {kind, points, unit?, caption?} | None` — ★보기의 값을 그대로 옮긴다★(새 수를
    #: 만들지 않는다). 엔진이 모양을 검사하고, 틀리거나 실패하면 그림 없이(null) 결과는 그대로 둔다.
    glance: Callable[[dict], dict | None] | None = None
    #: 과거를 시뮬레이션하거나 그 기록을 읽는 노드(BT1) — 증거 관문이 "과거로 돌려 보는 단계가 없어요"라고
    #: 사실과 다르게 말하지 않게 한다(있지만 관문이 아직 그 결과를 읽지 않는다 = 몰라요).
    simulates_history: bool = False

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
        #: 포트 타입 → 값의 한 줄 요약(BM C1 선 위 요약). 없는 타입은 요약하지 않는다.
        self.port_briefs: dict[str, Callable[[Any], str | None]] = {}

    def register(self, spec: NodeSpec) -> None:
        if spec.type in self._specs:
            raise ValueError(f"노드 타입 중복 등록: {spec.type}")
        for p in (*spec.inputs, *spec.outputs):
            if p.type not in self.port_types:
                raise ValueError(f"{spec.type}.{p.name}: 선언되지 않은 포트 타입 {p.type}")
        self._specs[spec.type] = spec

    def get(self, type_: str) -> NodeSpec | None:
        return self._specs.get(type_)

    def set_glance(self, type_: str, fn: Callable[[dict], dict | None]) -> None:
        """이미 등록된 노드에 작은 그림 함수를 붙인다(BM C1) — 노드 모듈을 건드리지 않고 한 곳에서 관리한다."""
        spec = self._specs.get(type_)
        if spec is None:
            raise ValueError(f"그림을 붙일 노드가 없습니다: {type_}")
        self._specs[type_] = replace(spec, glance=fn)

    def set_port_brief(self, port_type: str, fn: Callable[[Any], str | None]) -> None:
        """포트 타입에 값의 한 줄 요약 함수를 붙인다(BM C1) — 캔버스가 선 가운데에 그린다."""
        if port_type not in self.port_types:
            raise ValueError(f"선언되지 않은 포트 타입: {port_type}")
        self.port_briefs[port_type] = fn

    def set_port_meta(self, type_: str, port: str, *, role: str | None = None,
                      needs: tuple[str, ...] | None = None, gives: tuple[Gives, ...] | None = None) -> None:
        """이미 등록된 노드 포트에 사람 말 역할·요구값·싣는 값을 붙인다(BT1) — 노드 모듈을 건드리지 않고 한 곳에서."""
        spec = self._specs.get(type_)
        if spec is None:
            raise ValueError(f"메타를 붙일 노드가 없습니다: {type_}")

        def patch(ports: tuple[Port, ...], side: str) -> tuple[Port, ...]:
            if not any(p.name == port for p in ports):
                raise ValueError(f"{type_}: {side} 포트 {port} 가 없습니다")
            out = []
            for p in ports:
                if p.name == port:
                    p = replace(p, **{k: v for k, v in (("role", role), ("needs", needs), ("gives", gives))
                                      if v is not None})
                out.append(p)
            return tuple(out)

        if gives is not None:
            self._specs[type_] = replace(spec, outputs=patch(spec.outputs, "출력"))
        else:
            self._specs[type_] = replace(spec, inputs=patch(spec.inputs, "입력"))

    def mark_history(self, type_: str) -> None:
        """과거를 시뮬레이션하거나 그 기록을 읽는 노드로 표시한다(BT1 — 증거 관문 문장 정정)."""
        spec = self._specs.get(type_)
        if spec is None:
            raise ValueError(f"표시할 노드가 없습니다: {type_}")
        self._specs[type_] = replace(spec, simulates_history=True)

    def types(self) -> list[str]:
        return list(self._specs)

    def catalog(self) -> list[dict]:
        """팔레트의 단일 출처 — 캔버스는 이것만 보고 노드를 그린다."""
        return [{
            "type": s.type, "label": s.label, "category": s.category,
            "description": s.description,
            "stage": s.stage, "plain_label": s.human, "plain_description": s.plain_description,
            # BT1 — role·needs·gives 는 있을 때만 싣는다(없는 포트의 모양은 그대로).
            "inputs": [{"name": p.name, "type": p.type, "required": p.required,
                        **({"role": p.role} if p.role else {}),
                        **({"needs": list(p.needs)} if p.needs else {})}
                       for p in s.inputs],
            "outputs": [{"name": p.name, "type": p.type,
                         **({"gives": [g.to_dict() for g in p.gives]} if p.gives else {})}
                        for p in s.outputs],
            **({"simulates_history": True} if s.simulates_history else {}),
            "savable": s.save is not None,
            "save_label": s.save_label if s.save is not None else None,
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
            "view": None, "provenance": {}, "explain": explain, "lineage": merge_lineage(),
            "view_hash": None, "glance": None, "elapsed_ms": None, "briefs": {}}


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


# ── 캔버스 위 작은 그림 (BM C1) ────────────────────────────────────────────────

#: 그림 종류 → 점 수 상한. 막대(비중·기여)·값 목록은 카드에 들어갈 만큼, 선은 모양이 보일 만큼.
GLANCE_MAX = {"bars": 24, "values": 24, "hist": 24, "line": 48}
GLANCE_KINDS = tuple(GLANCE_MAX)


def _finite_or_none(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    if not isinstance(v, (int, float)):
        raise TypeError(f"그림 값이 수가 아닙니다: {type(v).__name__}")
    f = float(v)
    return f if math.isfinite(f) else None           # ★모르는 수는 모른다★ — 0 으로 바꾸지 않는다


def _check_glance(g: Any) -> dict | None:
    """그림 모양 검사 — 맞으면 정리한 dict, 틀리면 예외(부르는 쪽이 그림 전체를 버린다)."""
    if g is None:
        return None
    if not isinstance(g, Mapping):
        raise TypeError("그림이 dict 가 아닙니다")
    kind = g.get("kind")
    if kind not in GLANCE_MAX:
        raise ValueError(f"모르는 그림 종류: {kind!r}")
    pts = g.get("points")
    if not isinstance(pts, list) or not pts or len(pts) > GLANCE_MAX[kind]:
        raise ValueError(f"그림 점 수가 맞지 않습니다: {len(pts) if isinstance(pts, list) else pts!r}")
    out = [{"label": str(p.get("label")), "value": _finite_or_none(p.get("value"))} for p in pts]
    if all(p["value"] is None for p in out):
        raise ValueError("그림의 값이 모두 비어 있습니다")
    unit, caption = g.get("unit"), g.get("caption")
    return {"kind": kind, "points": out, "unit": str(unit) if unit is not None else None,
            "caption": str(caption) if caption is not None else None}


def _glance_ok(spec: NodeSpec, view: Any) -> dict | None:
    if spec.glance is None or not isinstance(view, Mapping):
        return None
    try:
        return _check_glance(spec.glance(dict(view)))
    except Exception:                                 # noqa: BLE001
        logger.warning(f"그림을 만들지 못함: {spec.type}", exc_info=True)
        return None


BRIEF_MAX = 80


def _briefs_ok(spec: NodeSpec, values: Mapping, registry: Registry) -> dict[str, str]:
    """출력 포트마다 값의 한 줄 요약 — 요약 함수가 없거나 실패하거나 빈 글이면 그 포트는 빠진다(지어내지 않는다)."""
    out: dict[str, str] = {}
    for p in spec.outputs:
        fn = registry.port_briefs.get(p.type)
        if fn is None or p.name not in values:
            continue
        try:
            text = fn(values[p.name])
        except Exception:                             # noqa: BLE001
            logger.warning(f"선 요약을 만들지 못함: {spec.type}.{p.name}", exc_info=True)
            continue
        if isinstance(text, str) and 0 < len(text) <= BRIEF_MAX:
            out[p.name] = text
    return out


def run(graph: Any, registry: Registry, targets: list[str] | None = None) -> dict:
    """검증 → 위상 순서 실행. 반환:
    `{"ok", "errors", "order", "nodes": {id: {type, status, reason, view, provenance,
    explain, lineage, view_hash}}}`.

    `targets` 를 주면 ★그 노드들과 조상만★ 계산한다(BL1 "여기까지 계산" — n8n 의 Execute step). 나머지 노드는
    결과에 **없다** — 이전 결과를 섞는 것은 화면의 일이고, 화면은 그것을 "이전 계산" 으로 표시한다. 보고서에
    `partial: {targets, computed}` 가 붙는다. 계산한 노드의 값은 전체 계산과 같다(같은 함수·같은 입력).
    """
    return _execute(graph, registry, targets)[0]


def _ms(t0: float) -> float:
    """노드 계산 시간(ms) — 계산기(run)만 잰다. 설명·그림은 넣지 않는다."""
    return round((time.perf_counter() - t0) * 1000.0, 1)


def _ancestors(targets: list[str], incoming: dict[str, dict]) -> set[str]:
    need, stack = set(), list(targets)
    while stack:
        nid = stack.pop()
        if nid in need:
            continue
        need.add(nid)
        stack.extend(src for src, _ in incoming.get(nid, {}).values())
    return need


def _execute(graph: Any, registry: Registry, targets: list[str] | None = None,
             ) -> tuple[dict, dict[str, dict[str, Any]], dict[str, Any]]:
    """`run` 의 본체 — 보고서와 함께 노드별 내부 값·파라미터를 돌려준다(저장 액션 전용)."""
    doc = _document_errors(graph)
    if doc:
        return {"ok": False, "errors": doc, "order": [], "nodes": {}}, {}, {}
    errors, nodes, specs, params, incoming, order = _analyse(graph, registry)
    partial = None
    if targets is not None:
        unknown = [t for t in targets if t not in nodes]
        if unknown or not targets:
            why = (f"계산할 노드가 그래프에 없어요: {', '.join(unknown)}" if unknown else "계산할 노드를 고르지 않았어요.")
            return {"ok": False, "errors": [_err("unknown_target", why)], "order": [], "nodes": {}}, {}, {}
        need = _ancestors(list(targets), incoming)
        edge_target = {_edge_id(e): str(e.get("target")) for e in graph["edges"] if isinstance(e, Mapping)}
        # 이 부분과 무관한 노드·링크의 오류는 이 계산을 막지 않는다(다른 곳의 설정 실수가 여기를 멈추지 않게).
        errors = [e for e in errors if (e.get("node_id") in need) or
                  (e.get("node_id") is None and (e.get("edge_id") is None or edge_target.get(e["edge_id"]) in need))]
        if order is not None:
            order = [n for n in order if n in need]
            partial = {"targets": list(targets), "computed": order}
    if order is None:
        return {"ok": False, "errors": errors, "order": [], "nodes": {}}, {}, {}

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
        # 상류 결과의 lineage 는 이미 그 위의 계보를 품고 있다 — 합치면 전이가 된다.
        in_lineage = merge_lineage(*(results[src]["lineage"] for src, _ in incoming[nid].values()))
        refusal = spec.admits(in_lineage) if spec.admits is not None else None
        if refusal:
            results[nid] = {"type": raw_type, "status": STATUS_FAILED, "reason": refusal,
                            "view": None, "provenance": {}, "explain": _explain_failed(refusal),
                            "lineage": in_lineage, "view_hash": None, "glance": None, "elapsed_ms": None,
                            "briefs": {}}
            continue
        t0 = time.perf_counter()
        try:
            out = (spec.run(inputs, params.get(nid), in_lineage) if spec.wants_lineage
                   else spec.run(inputs, params.get(nid)))
            missing = [p.name for p in spec.outputs if p.name not in (out.values or {})]
            if missing:
                raise NodeFailure(f"노드가 선언한 출력 {', '.join(missing)} 을 내지 않았습니다.")
        except NodeFailure as e:
            results[nid] = {"type": raw_type, "status": STATUS_FAILED, "reason": e.reason,
                            "view": None, "provenance": {}, "explain": _explain_failed(e.reason),
                            "lineage": in_lineage, "view_hash": None, "glance": None,
                            "elapsed_ms": _ms(t0), "briefs": {}}
            continue
        except Exception as e:                        # noqa: BLE001
            logger.exception(f"그래프 노드 {nid}({raw_type}) 처리 실패")
            why = f"처리 중 오류({type(e).__name__}) — 서버 로그를 보세요."
            results[nid] = {"type": raw_type, "status": STATUS_FAILED, "reason": why,
                            "view": None, "provenance": {}, "explain": _explain_failed(why),
                            "lineage": in_lineage, "view_hash": None, "glance": None,
                            "elapsed_ms": _ms(t0), "briefs": {}}
            continue
        elapsed = _ms(t0)
        values[nid] = out.values
        results[nid] = {"type": raw_type, "status": STATUS_OK, "reason": None,
                        "view": out.view, "provenance": dict(out.provenance or {}),
                        "explain": _explain_ok(spec, out, params.get(nid)),
                        "lineage": merge_lineage(in_lineage, out.tags),
                        "view_hash": view_hash(out.view),
                        "glance": _glance_ok(spec, out.view), "elapsed_ms": elapsed,
                        "briefs": _briefs_ok(spec, out.values, registry)}

    ok = not errors and all(r["status"] == STATUS_OK for r in results.values())
    report = {"ok": ok, "errors": errors, "order": order, "nodes": results}
    if partial is not None:
        report["partial"] = partial
    return report, values, params


# ── 저장 액션 (BK0) ───────────────────────────────────────────────────────────

def save_node(graph: Any, node_id: str, preview_hash: str, registry: Registry) -> dict:
    """그래프를 **다시 계산**해 `node_id` 의 view 해시가 사용자가 본 미리보기와 같을 때만
    그 노드의 `save` 를 **한 번** 부른다. 결과 `{"ok": True, saved_id, text, node_id}` 또는
    `{"ok": False, code, message}` — 코드: `no_node` · `not_savable` · `not_ok` · `stale` · `save_failed`.
    """
    report, values, params = _execute(graph, registry)
    res = report["nodes"].get(node_id)
    if res is None:
        return {"ok": False, "code": "no_node", "message": f"그래프에 {node_id} 노드가 없어요."}
    spec = registry.get(str(res.get("type")))
    if spec is None or spec.save is None:
        return {"ok": False, "code": "not_savable", "message": "이 노드는 저장할 것이 없어요."}
    if res["status"] != STATUS_OK:
        return {"ok": False, "code": "not_ok",
                "message": f"이 노드가 계산되지 않아 저장할 수 없어요 — {res.get('reason')}"}
    if res["view_hash"] != preview_hash:
        return {"ok": False, "code": "stale",
                "message": "보신 미리보기와 지금 계산이 달라요. 다시 계산한 뒤 저장해 주세요."}
    try:
        out = spec.save(values[node_id], res["view"] or {}, params.get(node_id))
    except NodeFailure as e:
        return {"ok": False, "code": "save_failed", "message": e.reason}
    except Exception as e:                            # noqa: BLE001
        logger.exception(f"그래프 노드 {node_id} 저장 실패")
        return {"ok": False, "code": "save_failed",
                "message": f"저장하지 못했어요({type(e).__name__}) — 서버 로그를 보세요."}
    return {"ok": True, "saved_id": out.get("saved_id"), "text": out.get("text"), "node_id": node_id}
