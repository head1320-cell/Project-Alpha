"""노드·선에게 묻기(AI3) — ★봉인한 설명·전달 점검만★ 근거로, 문장마다 사실 줄을 대고 그 줄의 숫자만(순수).
==============================================================================
스펙 §AI3 설계 · 사용자 결정(2026-10-23): 근거 = 고른 것 + 위쪽 전부 + 바로 아래 · 사실 줄마다 칩 · 계산한 뒤에만 · 직전 문답 하나만.

- `scope` — 노드: 조상 전부 + 그 노드 + 바로 아래(먼 아래·다른 갈래·조상에서 자식으로 바로 가는 선은 뺀다) / 선(s→t): s 의 조상 + s + t + 그 선.
- `verify_records` — 전달 점검 기록의 봉인을 ★받는 노드의 깊은 서명★으로 확인한다(그 서명이 보낸 노드와 이 선을 품는다). 깨진 것은 사유와 함께.
- `ground` — 범위 안의 확인된 것만 줄로 편다. 줄 id(`f1…`)는 서버가 붙이고, 줄 이름(part)에는 숫자를 넣지 않는다(숫자 검사가 헷갈리지 않게 —
  화면은 `refs` 의 `index` 로 "사실 2" 를 그린다). 관계 문장은 화면이 보낸 글이 아니라 ★서버가 문서로 다시 만든 구조 문장★이다.
- `check` — 문장마다 줄 ≥1 · 근거에 있는 줄 · ★그 문장이 댄 줄의 숫자만★ · 금지 표현 · 길이 · 최대 4. 답할 수 없으면 ★서버 고정 문장★(`CANNOT`).

한계(적어 둠): 숫자 검사는 아라비아 숫자만 본다 · 문장이 줄을 ★바르게 이었는지★(인과·비교)는 재지 않는다.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.domain import fact_seal as fs
from src.engine.portfolio_graph import _edge_id
from src.services.canvas_assist.check import BANNED
from src.services.canvas_assist.ground import numbers_of
from src.services.canvas_assist.narrate import flow_order

MAX_SENTENCES = 4
MAX_CHARS = 240
WHY_NOT = ("none", "not_in_facts", "judgement", "off_topic")
CANNOT = {
    "not_in_facts": "이 노드·선의 계산 결과로는 답할 수 없어요.",
    "judgement": "투자 판단은 말하지 않아요 — 계산이 무엇을 냈는지만 답해요.",
    "off_topic": "이 노드·선의 계산에 대해 물어 주세요.",
}
_STALE = "서명이 맞지 않아요(그래프가 바뀌었거나 서버가 다시 시작했어요). 다시 계산하면 물을 수 있어요"
_MISSING = "그래프에 없는 선이에요"
_PART = {"title": "제목", "headline": "핵심 값", "fact": "사실", "trust": "믿음", "unmeasured": "재지 않은 것",
         "relation": "관계", "carried": "건너간 것", "issue": "빠지거나 바뀐 것", "checked": "점검"}


def _edges(graph: dict) -> dict[str, dict]:
    return {_edge_id(e): e for e in graph.get("edges") or [] if isinstance(e, dict)}


def _ancestors(edges: dict[str, dict], nid: str) -> set[str]:
    up: dict[str, set[str]] = {}
    for e in edges.values():
        up.setdefault(str(e.get("target")), set()).add(str(e.get("source")))
    seen: set[str] = set()
    todo = [nid]
    while todo:
        for s in up.get(todo.pop(), ()):
            if s not in seen:
                seen.add(s)
                todo.append(s)
    seen.discard(nid)
    return seen


def scope(graph: dict, target: Mapping[str, Any]) -> tuple[list[str], list[str]] | None:
    """`(노드 — 흐름 순서, 선 id — 정렬)` · 모르는 대상이면 None."""
    ids = {n["id"] for n in graph.get("nodes") or [] if isinstance(n, dict) and isinstance(n.get("id"), str)}
    edges = _edges(graph)
    kind, tid = target.get("kind"), target.get("id")
    if kind == "node" and tid in ids:
        upper = _ancestors(edges, tid) | {tid}
        kids = {str(e["target"]) for e in edges.values() if e.get("source") == tid and e.get("target") in ids}
        nodes = upper | kids
        keep = {k for k, e in edges.items()
                if (e.get("source") in upper and e.get("target") in upper) or (e.get("source") == tid and e.get("target") in kids)}
    elif kind == "edge" and tid in edges:
        s, t = str(edges[tid].get("source")), str(edges[tid].get("target"))
        if s not in ids or t not in ids:
            return None
        upper = _ancestors(edges, s) | {s}
        nodes = upper | {t}
        keep = {k for k, e in edges.items() if e.get("source") in upper and e.get("target") in upper} | {tid}
    else:
        return None
    return [n for n in flow_order(graph) if n in nodes], sorted(keep)


def verify_records(graph: dict, records: list[dict], key: bytes) -> tuple[dict[str, dict], list[dict]]:
    """`(확인됨 {선 id: 기록}, 버림 [{edge_id, reason}])`."""
    edges = _edges(graph)
    deep = fs.deep_sigs(graph)
    ok: dict[str, dict] = {}
    dropped: list[dict] = []
    for r in records:
        eid = r.get("edge_id")
        e = edges.get(eid) if isinstance(eid, str) else None
        if e is None or e.get("target") not in deep:
            dropped.append({"edge_id": eid, "reason": _MISSING})
        elif eid in ok:
            continue
        elif not fs.verify(key, eid, fs.EDGE_TYPE, deep[e["target"]], r.get("record"), r.get("sig")):
            dropped.append({"edge_id": eid, "reason": _STALE})
        else:
            ok[eid] = r["record"]
    return ok, dropped


def _node_lines(ex: dict) -> list[tuple[str, int, str]]:
    out: list[tuple[str, int, str]] = []
    if isinstance(ex.get("title"), str) and ex["title"]:
        out.append(("title", 0, ex["title"]))
    head = ex.get("headline") if isinstance(ex.get("headline"), dict) else None
    if head and head.get("text"):
        out.append(("headline", 0, f"{head.get('label') or ''}: {head['text']}".lstrip(": ")))
    out += [("fact", i, str(f)) for i, f in enumerate(ex.get("facts") or [])]
    out += [("trust", i, str(t.get("text"))) for i, t in enumerate(ex.get("trust") or []) if isinstance(t, dict) and t.get("text")]
    out += [("unmeasured", i, str(u)) for i, u in enumerate(ex.get("unmeasured") or [])]
    return out


def _edge_lines(rec: dict) -> list[tuple[str, int, str]]:
    out: list[tuple[str, int, str]] = []
    out += [("carried", i, f"{f.get('label')}: {f.get('text')}") for i, f in enumerate(rec.get("facts") or []) if isinstance(f, dict)]
    issues = rec.get("issues")
    if isinstance(issues, list) and issues:
        out += [("issue", i, str(x.get("text")) + (f" {x['fix']}" if x.get("fix") else "")) for i, x in enumerate(issues)
                if isinstance(x, dict)]
    elif isinstance(issues, list):
        out.append(("checked", 0, f"점검한 것: {' · '.join(map(str, rec.get('checks') or []))} — 잃거나 바뀐 것을 찾지 못했어요."))
    elif rec.get("issues_reason"):
        out.append(("checked", 0, str(rec["issues_reason"])))
    return out


def ground(graph: dict, target: Mapping[str, Any], question: str, previous: Mapping[str, str] | None,
           verified: list[dict], records: Mapping[str, dict], kinds: Mapping[str, Mapping],
           relations: Mapping[str, Mapping]) -> tuple[dict, dict[str, dict]]:
    """`(근거 — 프롬프트·캐시 열쇠, refs {줄 id: {target_kind, target_id, part, index, text}})`. 범위 밖은 줄이 없다."""
    sc = scope(graph, target)
    nodes_in, edges_in = sc if sc else ([], [])
    types = {n["id"]: n.get("type") for n in graph.get("nodes") or [] if isinstance(n, dict)}
    label = {nid: (kinds.get(str(t)) or {}).get("plain_label") or str(t) for nid, t in types.items()}
    edges = _edges(graph)
    ex_of = {f["node_id"]: f["explain"] for f in verified}
    lines: list[dict] = []
    refs: dict[str, dict] = {}
    practice = False

    def add(kind: str, tid: str, where: str, part: str, index: int, text: str) -> None:
        fid = f"f{len(lines) + 1}"
        lines.append({"id": fid, "where": where, "part": _PART[part], "text": text})
        refs[fid] = {"target_kind": kind, "target_id": tid, "part": _PART[part], "index": index, "text": text}

    for nid in nodes_in:                     # 노드 줄 다음에 그 노드로 들어오는 범위 안 선의 줄 — 흐름 순서
        ex = ex_of.get(nid)
        if isinstance(ex, dict):
            practice = practice or any(isinstance(t, dict) and t.get("kind") == "practice" for t in ex.get("trust") or [])
            for part, i, text in _node_lines(ex):
                add("node", nid, label[nid], part, i, text)
        for eid in edges_in:
            if edges[eid].get("target") != nid:
                continue
            where = f"{label.get(str(edges[eid].get('source')), '?')} → {label[nid]}"
            rel = relations.get(eid)
            if isinstance(rel, Mapping) and rel.get("text"):
                add("edge", eid, where, "relation", 0, str(rel["text"]))
            if isinstance(records.get(eid), dict):
                for part, i, text in _edge_lines(records[eid]):
                    add("edge", eid, where, part, i, text)
    if target.get("kind") == "edge":
        tlabel = (f"{label.get(str(edges[target['id']].get('source')), '?')} → "
                  f"{label.get(str(edges[target['id']].get('target')), '?')} 선") if target.get("id") in edges else "?"
    else:
        tlabel = label.get(str(target.get("id")), "?")
    g = {"target": {"kind": target.get("kind"), "id": target.get("id"), "label": tlabel}, "question": question,
         "previous": dict(previous) if previous else None, "lines": lines, "practice": practice}
    return g, refs


def _rej(code: str, reason: str) -> dict:
    return {"code": code, "reason": reason}


def _problem(it: Any, by_id: dict[str, dict]) -> tuple[str, str] | None:
    if not isinstance(it, dict) or set(it) != {"text", "fact_ids"} or not isinstance(it.get("text"), str) \
            or not it["text"].strip() or not isinstance(it.get("fact_ids"), list) \
            or not all(isinstance(i, str) for i in it["fact_ids"]):
        return "shape", "문장의 형식이 맞지 않아요"
    text, ids = it["text"], it["fact_ids"]
    if not ids:
        return "no_source", "근거로 댄 사실 줄이 없어요"
    if any(i not in by_id for i in ids):
        return "unknown_fact", "근거로 댄 사실 줄이 근거에 없어요"
    word = next((w for w in BANNED if w in text), None)
    if word:
        return "banned", f"쓰지 않는 표현 ‘{word}’이 들어 있어요"
    if len(text) > MAX_CHARS:
        return "too_long", f"문장이 {MAX_CHARS}자를 넘어요"
    allowed: set[str] = set()
    for i in ids:
        allowed |= numbers_of(by_id[i]["text"])
    extra = numbers_of(text) - allowed
    if extra:
        return "numbers", f"댄 사실 줄에 없는 숫자 {', '.join(sorted(extra))} 를 썼어요"
    return None


def check(raw: Any, grounding: dict, cannot: Mapping[str, str] = CANNOT) -> tuple[dict, list[dict]]:
    """`(답 {answerable, cannot, sentences}, 탈락 [{code, reason}])` — 통과 문장의 줄 id 는 겹친 것을 하나로.
    `cannot` 은 답할 수 없을 때의 ★서버 고정 문장★ 표(PB4 고객 한 장은 고객용 문장을 쓴다)."""
    if not isinstance(raw, dict) or not isinstance(raw.get("sentences"), list) or not isinstance(raw.get("answerable"), bool):
        return {"answerable": False, "cannot": cannot["not_in_facts"], "sentences": []}, [_rej("shape", "답의 형식이 맞지 않아요")]
    by_id = {x["id"]: x for x in grounding["lines"]}
    ok: list[dict] = []
    bad: list[dict] = []
    for it in raw["sentences"]:
        if len(ok) >= MAX_SENTENCES:
            bad.append(_rej("limit", f"{MAX_SENTENCES}문장을 넘어요"))
            continue
        why = _problem(it, by_id)
        if why:
            bad.append(_rej(*why))
            continue
        ok.append({"text": it["text"].strip(), "fact_ids": list(dict.fromkeys(it["fact_ids"]))})
    if raw["answerable"]:
        return {"answerable": True, "cannot": None, "sentences": ok}, bad
    reason = raw.get("why_not") if raw.get("why_not") in cannot else "not_in_facts"
    return {"answerable": False, "cannot": cannot[reason], "sentences": ok}, bad
