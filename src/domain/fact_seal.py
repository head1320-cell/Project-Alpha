"""설명 봉인(AI2) — `/run` 이 낸 노드 설명이 ★그 서버가 지금 그래프에 대해 낸 것★인지 확인한다(순수).
==============================================================================
서버는 계산 결과를 들고 있지 않다(`/run` 은 계산해 돌려주고 끝). 그래서 노드 설명마다 HMAC 을 붙여 내보내고, 화면이 그것을
돌려보내면(AI 풀어 쓰기) ★지금 문서로 다시 셈한 깊은 서명★과 함께 확인한다 — 지어낸 숫자도, 그래프가 바뀐 뒤의 예전 설명도 통과하지 못한다.

- 깊은 서명 = 종류 + 정규 설정 JSON + 들어오는 선(받는 자리 ← 보내는 자리 @ 보낸 노드의 깊은 서명) — 머클 사슬이라 위가 바뀌면 아래도 바뀐다.
  자리·이름·경유점·묶음은 계산에 끼지 않아 넣지 않는다(화면 `entities/portfolio-graph/staleness.ts` 와 같은 범위, 해시는 다르다).
- ★숫자 정규화★ — 정수인 실수는 정수로 셈한다. 파이썬 `25.0` 은 브라우저를 거치면 `25` 로 돌아온다(JSON 왕복) — 이것 없으면 서명이 깨진다.
- 키는 `auth.derived_key(PURPOSE)` — 토큰 서명 키와 용도가 다르다. 이 모듈은 키를 받기만 한다.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

PURPOSE = "canvas-explain-facts/v1"


def _canon(v: Any) -> Any:
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, dict):
        return {str(k): _canon(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_canon(x) for x in v]
    return v


def _dump(v: Any) -> bytes:
    return json.dumps(_canon(v), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def deep_sigs(graph: Any) -> dict[str, str]:
    """노드 id → 깊은 서명(sha256). 고리를 만나면 "cycle" 로 끊는다(무한 재귀 없음 — 고리 자체는 검증이 오류로 말한다)."""
    if not isinstance(graph, dict):
        return {}
    nodes = {n["id"]: n for n in graph.get("nodes") or [] if isinstance(n, dict) and isinstance(n.get("id"), str)}
    inc: dict[str, list[dict]] = {}
    for e in graph.get("edges") or []:
        if isinstance(e, dict) and e.get("target") in nodes:
            inc.setdefault(e["target"], []).append(e)
    memo: dict[str, str] = {}
    visiting: set[str] = set()

    def sig(nid: str) -> str:
        if nid in memo:
            return memo[nid]
        if nid in visiting:
            return "cycle"
        visiting.add(nid)
        ins = sorted(f"{e.get('target_port')}<{e.get('source_port')}@"
                     f"{sig(e['source']) if e.get('source') in nodes else 'missing'}" for e in inc.get(nid, []))
        visiting.discard(nid)
        n = nodes[nid]
        memo[nid] = hashlib.sha256(_dump([n.get("type"), n.get("params") or {}, ins])).hexdigest()
        return memo[nid]

    for nid in nodes:
        sig(nid)
    return memo


def seal(key: bytes, node_id: str, node_type: Any, deep: str, explain: Any) -> str:
    return hmac.new(key, _dump([node_id, node_type, deep, explain]), hashlib.sha256).hexdigest()


def verify(key: bytes, node_id: str, node_type: Any, deep: str, explain: Any, sig: Any) -> bool:
    return isinstance(sig, str) and hmac.compare_digest(seal(key, node_id, node_type, deep, explain), sig)
