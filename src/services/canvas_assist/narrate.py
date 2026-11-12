"""AI 풀어 쓰기(AI2) — ★서버가 봉인한 설명만★ 근거로, 문단마다 근거 노드를 대고 그 노드의 숫자만(순수).
==============================================================================
- `verify_facts` — 화면이 돌려보낸 설명을 지금 문서로 확인한다(`fact_seal`). 깨진 것은 버리지 않고 `dropped` 에 사유와 함께.
- `ground` — 확인된 설명을 흐름 순서로(노드 이름·title·headline·facts·trust·unmeasured). 번호는 싣지 않는다(화면 칩이 말한다).
- `check` — 문단 검사: 근거 노드 ≥1 이고 확인된 것 · ★그 문단의 근거 노드 숫자만★ · 금지 표현 · 길이 · 최대 5. 탈락은 사유와 함께.
- 합성 경고는 ★모델이 아니라 서버가★ 붙인다(`NOTICE` — 스펙 검사 ⑤).

한계(적어 둠): 숫자 검사는 아라비아 숫자만 본다("세 개"는 잡지 않는다) · 문장이 사실을 ★바르게 이었는지★(인과·비교)는 재지 않는다.
"""
from __future__ import annotations

from typing import Any

from src.domain import fact_seal as fs
from src.services.canvas_assist.check import BANNED
from src.services.canvas_assist.ground import numbers_of

MAX_PARAGRAPHS = 5
MAX_CHARS = 600
NOTICE = "합성 데이터 결과입니다. 실제 시세가 아니라 합성 데이터로 계산했습니다. 투자 판단에 쓰기 전에 실데이터로 재계산하십시오."
_STALE = "서명이 일치하지 않습니다(그래프가 변경됐거나 서버가 재시작됐습니다). 재계산하면 다시 서술할 수 있습니다"
_MISSING = "그래프에 없는 노드입니다"


def flow_order(graph: dict) -> list[str]:
    """흐름 순서 — 칸 알고리즘, 동률은 문서 순서(`portfolio_graph._topo` · 화면 `topoOrder` 와 같은 규칙). 고리에 걸린 노드는 뒤에."""
    ids = [n["id"] for n in graph.get("nodes") or [] if isinstance(n, dict) and isinstance(n.get("id"), str)]
    rank = {n: i for i, n in enumerate(ids)}
    adj: dict[str, set[str]] = {n: set() for n in ids}
    indeg = {n: 0 for n in ids}
    for e in graph.get("edges") or []:
        if isinstance(e, dict) and e.get("source") in rank and e.get("target") in rank and e["target"] not in adj[e["source"]]:
            adj[e["source"]].add(e["target"])
            indeg[e["target"]] += 1
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
    return out + [n for n in ids if n not in out]


def verify_facts(graph: dict, facts: list[dict], key: bytes) -> tuple[list[dict], list[dict]]:
    """`(확인됨 — 흐름 순서, 버림)`. 확인됨 = `{node_id, type, explain}` · 버림 = `{node_id, reason}`."""
    nodes = {n["id"]: n for n in graph.get("nodes") or [] if isinstance(n, dict) and isinstance(n.get("id"), str)}
    deep = fs.deep_sigs(graph)
    ok: dict[str, dict] = {}
    dropped: list[dict] = []
    for f in facts:
        nid = f.get("node_id")
        if nid not in nodes:
            dropped.append({"node_id": nid, "reason": _MISSING})
        elif nid in ok:
            continue
        elif not fs.verify(key, nid, nodes[nid].get("type"), deep[nid], f.get("explain"), f.get("sig")):
            dropped.append({"node_id": nid, "reason": _STALE})
        else:
            ok[nid] = {"node_id": nid, "type": nodes[nid].get("type"), "explain": f["explain"]}
    return [ok[n] for n in flow_order(graph) if n in ok], dropped


def ground(verified: list[dict], kinds: dict[str, dict]) -> dict:
    nodes, practice = [], False
    for f in verified:
        ex = f["explain"]
        trust = [t for t in ex.get("trust") or [] if isinstance(t, dict)]
        practice = practice or any(t.get("kind") == "practice" for t in trust)
        head = ex.get("headline") if isinstance(ex.get("headline"), dict) else None
        nodes.append({"id": f["node_id"], "label": (kinds.get(f["type"]) or {}).get("plain_label") or f["type"],
                      "title": ex.get("title"), "headline": head.get("text") if head else None,
                      "headline_label": head.get("label") if head else None,
                      "facts": list(ex.get("facts") or []),
                      "trust": [{"state": t.get("state"), "text": t.get("text")} for t in trust],
                      "unmeasured": list(ex.get("unmeasured") or [])})
    return {"nodes": nodes, "practice": practice}


def _rej(code: str, reason: str) -> dict:
    return {"code": code, "reason": reason}


def _problem(it: Any, by_id: dict[str, dict]) -> tuple[str, str] | None:
    if not isinstance(it, dict) or set(it) != {"text", "node_ids"} or not isinstance(it.get("text"), str) \
            or not it["text"].strip() or not isinstance(it.get("node_ids"), list) \
            or not all(isinstance(i, str) for i in it["node_ids"]):
        return "shape", "문단의 형식이 맞지 않습니다"
    text, ids = it["text"], it["node_ids"]
    if not ids:
        return "no_source", "근거로 댄 노드가 없습니다"
    if any(i not in by_id for i in ids):
        return "unknown_node", "근거로 댄 노드가 확인된 계산 결과에 없습니다"
    word = next((w for w in BANNED if w in text), None)
    if word:
        return "banned", f"쓰지 않는 표현 ‘{word}’이 들어 있습니다"
    if len(text) > MAX_CHARS:
        return "too_long", f"문단이 {MAX_CHARS}자를 넘습니다"
    allowed: set[str] = set()
    for i in ids:
        allowed |= numbers_of({k: v for k, v in by_id[i].items() if k != "id"})
    extra = numbers_of(text) - allowed
    if extra:
        return "numbers", f"근거 노드에 없는 숫자 {', '.join(sorted(extra))} 를 썼습니다"
    return None


def check(raw: Any, grounding: dict) -> tuple[list[dict], list[dict]]:
    """`(통과 문단, 탈락)`. 통과 = `{text, node_ids}`(겹친 노드는 하나로), 탈락 = `{code, reason}`."""
    items = raw.get("paragraphs") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        return [], [_rej("shape", "답에 문단 목록이 없습니다")]
    by_id = {n["id"]: n for n in grounding["nodes"]}
    ok: list[dict] = []
    bad: list[dict] = []
    for it in items:
        if len(ok) >= MAX_PARAGRAPHS:
            bad.append(_rej("limit", f"{MAX_PARAGRAPHS}문단을 넘습니다"))
            continue
        why = _problem(it, by_id)
        if why:
            bad.append(_rej(*why))
            continue
        ok.append({"text": it["text"].strip(), "node_ids": list(dict.fromkeys(it["node_ids"]))})
    return ok, bad
