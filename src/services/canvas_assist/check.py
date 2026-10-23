"""출력 검사 — 스펙 §AI0 검사 1~6. ★통과한 것만 화면에 간다★, 탈락은 조용히 버리지 않고 사유와 함께 돌려준다.

① 노드 종류는 카탈로그에 있다 ② 잇는 선은 붙인 문서를 `/validate` 해 ★새 오류가 없다★(타입·찬 입력·없는 포트·
없는 노드·순환·계산 때 실패할 선) — 새 노드 자신의 빈 입력·설정값은 사람이 채울 몫이라 허용한다
③ 이유 속 숫자 ⊆ 근거 숫자 ④ 금지 표현 0 ⑤ 연습용 경고 — suggest 는 결과 글이 없어 해당 없음
⑥ 설정값을 추천하지 않는다(`params` 칸이 있으면 탈락) · 최대 3개 · 같은 추천은 하나.

한계(적어 둠): ③은 아라비아 숫자만 본다 — "세 개" 같은 글 숫자는 잡지 않는다.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.services.canvas_assist.ground import numbers_of

MAX_SUGGESTIONS = 3
NEW = "@new"
BANNED = ("검증됨", "입증됨", "견고함", "프로덕션 레디", "투자 우위", "더 나은 전략", "통과해요", "좋아져요", "보장")

_PORT_KEYS = ("source", "source_port", "target", "target_port")
_ALLOWED_ON_NEW = frozenset({"missing_input", "bad_params"})
_PLAIN = {
    "type_mismatch": "포트 타입이 달라요",
    "multiple_inputs": "받는 자리에 이미 선이 있어요",
    "unknown_port": "카탈로그에 없는 포트예요",
    "dangling_edge": "그래프에 없는 노드를 가리켜요",
    "cycle": "이으면 순환이 생겨요",
    "needs_unmet": "이대로 계산하면 실패할 선이에요",
}


def _rej(kind: Any, code: str, reason: str) -> dict:
    return {"kind": kind if isinstance(kind, str) else None, "code": code, "reason": reason}


def _shape_problem(it: Any) -> str | None:
    if not isinstance(it, dict):
        return "추천이 객체가 아니에요"
    if not isinstance(it.get("kind"), str) or not isinstance(it.get("reason"), str) or not it["reason"].strip():
        return "종류나 이유가 비어 있어요"
    att = it.get("attach")
    if not isinstance(att, list) or not all(isinstance(a, dict) and set(a) == set(_PORT_KEYS)
                                            and all(isinstance(a[k], str) for k in _PORT_KEYS) for a in att):
        return "잇는 선의 형식이 맞지 않아요"
    extra = set(it) - {"kind", "attach", "reason"}
    if extra:
        return f"모르는 칸이 있어요({', '.join(sorted(map(str, extra)))})"
    return None


def _key(e: dict) -> tuple:
    return (e.get("code"), e.get("node_id"), e.get("edge_id"), e.get("port"))


def _connection_problem(kind: str, attach: list[dict], graph: dict, validate: Callable[[Any], dict],
                        before: set[tuple]) -> tuple[str, str] | None:
    ids = {n.get("id") for n in graph["nodes"] if isinstance(n, dict)}
    nid, i = f"ai-{kind}", 2
    while nid in ids:
        nid, i = f"ai-{kind}-{i}", i + 1

    def sub(v: str) -> str:
        return nid if v == NEW else v
    edges = [{"id": f"{sub(a['source'])}.{a['source_port']}->{sub(a['target'])}.{a['target_port']}",
              "source": sub(a["source"]), "source_port": a["source_port"],
              "target": sub(a["target"]), "target_port": a["target_port"]} for a in attach]
    doc = {**graph, "nodes": [*graph["nodes"], {"id": nid, "type": kind, "params": {}}], "edges": [*graph["edges"], *edges]}
    for e in validate(doc)["errors"]:
        if _key(e) in before or (e.get("code") in _ALLOWED_ON_NEW and e.get("node_id") == nid):
            continue
        code = str(e.get("code") or "connection")
        return code, _PLAIN.get(code, "잇는 선이 맞지 않아요")
    return None


def _problem(it: dict, graph: dict, kinds: dict, numbers: set[str], validate, before: set[tuple]) -> tuple[str, str] | None:
    if "params" in it:
        return "settings", "설정값을 담고 있어요(설정은 추천하지 않아요)"
    why = _shape_problem(it)
    if why:
        return "shape", why
    kind, reason, attach = it["kind"], it["reason"], it["attach"]
    if kind not in kinds:
        return "unknown_kind", f"카탈로그에 없는 종류 ‘{kind}’예요"
    word = next((w for w in BANNED if w in reason), None)
    if word:
        return "banned", f"쓰지 않는 표현 ‘{word}’이 들어 있어요"
    extra = numbers_of(reason) - numbers
    if extra:
        return "numbers", f"근거에 없는 숫자 {', '.join(sorted(extra))} 를 썼어요"
    if not attach and any(isinstance(n, dict) for n in graph["nodes"]):
        return "unattached", "지금 그래프의 어느 노드와도 잇지 않아요"
    if any((a["source"] == NEW) == (a["target"] == NEW) for a in attach):
        return "attach_shape", "잇는 선마다 한쪽 끝만 새 노드(@new)여야 해요"
    return _connection_problem(kind, attach, graph, validate, before)


def check(raw: Any, graph: dict, kinds: dict[str, dict], numbers: set[str],
          validate: Callable[[Any], dict]) -> tuple[list[dict], list[dict]]:
    """`(통과, 탈락)`. 통과는 `{action:"add", kind, label(카탈로그 이름), attach, reason}`, 탈락은 `{kind, code, reason}`."""
    items = raw.get("suggestions") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        return [], [_rej(None, "shape", "답에 추천 목록이 없어요")]
    before = {_key(e) for e in validate(graph)["errors"]}
    ok: list[dict] = []
    bad: list[dict] = []
    seen: set = set()
    for it in items:
        kind = it.get("kind") if isinstance(it, dict) else None
        if len(ok) >= MAX_SUGGESTIONS:
            bad.append(_rej(kind, "limit", f"{MAX_SUGGESTIONS}개를 넘어요"))
            continue
        why = _problem(it, graph, kinds, numbers, validate, before)
        if why:
            bad.append(_rej(kind, *why))
            continue
        sig = (kind, frozenset(tuple(a[k] for k in _PORT_KEYS) for a in it["attach"]))
        if sig in seen:
            bad.append(_rej(kind, "duplicate", "앞의 추천과 같아요"))
            continue
        seen.add(sig)
        ok.append({"action": "add", "kind": kind, "label": kinds[kind]["plain_label"],
                   "attach": [{k: a[k] for k in _PORT_KEYS} for a in it["attach"]], "reason": it["reason"].strip()})
    return ok, bad
