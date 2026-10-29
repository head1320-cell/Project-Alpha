"""캔버스 AI 도우미 — 노드 추천(AI1 `suggest`) · 풀어 쓰기(AI2 `narrate`) · 묻기(AI3 `ask`) · 말로 설계(AI4 `draft`) · 길잡이(AI5 `guide`).
모두 `_ask`: 쓸 수 있나 → 한도 설정 → 캐시 → 한도 → Claude → 검사.

응답은 둘 중 하나다:
- `{available:true, source:"claude", model, …검사를 통과한 것…, rejected, cached, usage}`.
- `{available:false, source:"unavailable", reason_code, reason, …}` — ★AI 글은 없다★(데모 글 금지). suggest 는 `rule`(규칙 대체 —
  `/validate` 절차의 next·by_gate), narrate·ask 는 `dropped`(확인하지 못한 설명·기록과 사유)를 함께 낸다.
- 사용자별 시간당 한도는 ★한 그릇★ — 추천·풀어 쓰기·묻기·말로 설계·길잡이를 합쳐 센다. 캐시 적중은 세지 않는다.
- guide 는 못 보일 때 곁들임이 없다 — 화면의 규칙 길잡이 줄이 그대로 남는다.
- `dropped` 는 요청마다 다르다(캐시는 근거로 찾는다) — 캐시에 적중해도 ★이번 요청의 것★을 붙인다.

`catalog`·`validate`·`key` 는 경로가 넘긴다(`allocation_graph_routes._kinds`·`graph_validate` · `auth.derived_key`) — 서비스가 API 층을 import 하지 않게.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from collections.abc import Callable
from typing import Any

from src.engine.portfolio_graph import FATAL_CODES
from src.services.canvas_assist import ask as ak
from src.services.canvas_assist import check as ck
from src.services.canvas_assist import draft as df
from src.services.canvas_assist import ground as gr
from src.services.canvas_assist import guide as gd
from src.services.canvas_assist import narrate as nr
from src.services.canvas_assist import prompts as pr
from src.services.canvas_assist.limiter import HourlyLimiter
from src.services.narrative.claude_client import ClaudeClient

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_HOURLY_LIMIT = 30
EFFORT = "medium"
MAX_TOKENS = 16000
CACHE_TTL = 3600.0
CACHE_MAX = 256

REASONS = {
    "no_key": "서버에 Claude 키가 없어요",
    "sdk_missing": "서버에 anthropic SDK 가 설치돼 있지 않아요",
    "client_init_failed": "서버가 Claude 클라이언트를 만들지 못했어요",
    "circuit_open": "Claude 호출이 연달아 실패해 잠시 멈췄어요. 1분쯤 뒤에 다시 물어보세요",
    "config": "서버 설정 CANVAS_ASSIST_HOURLY_LIMIT 값이 0 이상의 정수가 아니에요",
    "bad_graph": "그래프 문서를 읽을 수 없어요(형식·버전·순환을 먼저 고쳐 주세요)",
    "no_facts": "지금 그래프의 계산 결과가 없어요. 계산한 뒤에 풀어 쓸 수 있어요",
    "stale_facts": "보낸 계산 결과를 확인하지 못했어요(그래프가 바뀌었거나 서버가 다시 시작했어요). 다시 계산하면 풀어 쓸 수 있어요",
    "no_target": "그래프에 없는 노드·선이에요",
    "no_facts_target": "이 노드·선의 지금 계산 결과가 없어요. 계산한 뒤에 물을 수 있어요",
    "no_tools": "지금 권할 도구가 없어요",
    "rate_limited": "한 시간에 {limit}번까지 물을 수 있어요. 이번 시간에는 다 썼어요",
    "refusal": "Claude 가 이 요청에 답하지 않았어요(분류: {detail})",
    "max_tokens": "Claude 의 답이 길이 한도에서 잘렸어요",
    "incomplete": "Claude 의 답이 끝나지 않았어요({detail})",
    "bad_json": "Claude 의 답을 읽을 수 없었어요(형식이 맞지 않음)",
    "api_rate_limited": "Claude 쪽 호출 한도에 걸렸어요. 잠시 뒤에 다시 물어보세요",
    "api_status": "Claude 가 오류로 답했어요(HTTP {detail})",
    "network": "Claude 에 닿지 못했어요(네트워크)",
    "unexpected": "Claude 를 부르다 예상하지 못한 오류가 났어요",
}

_cache: dict[str, tuple[float, dict]] = {}
_cache_lock = threading.Lock()
_limiter = HourlyLimiter()


def _now() -> float:
    return time.time()


def reset() -> None:
    """캐시·한도를 비운다(테스트·운영 점검용)."""
    with _cache_lock:
        _cache.clear()
    _limiter.reset()


def _unavailable(code: str, extra: dict | None = None, **fmt: Any) -> dict:
    """못 보임 — 사유 문장 + 경로별 곁들임(`extra`: suggest 는 `rule`, narrate 는 `dropped`)."""
    reason = REASONS.get(code, REASONS["unexpected"]).format(**{k: (v if v not in (None, "") else "없음")
                                                                for k, v in fmt.items()})
    return {"available": False, "source": "unavailable", "reason_code": code, "reason": reason, **(extra or {})}


def _limit() -> int | None:
    raw = os.getenv("CANVAS_ASSIST_HOURLY_LIMIT")
    if raw is None or not raw.strip():
        return DEFAULT_HOURLY_LIMIT
    try:
        n = int(raw)
    except ValueError:
        return None
    return n if n >= 0 else None


def _cache_get(key: str) -> dict | None:
    with _cache_lock:
        hit = _cache.get(key)
        if hit and _now() - hit[0] <= CACHE_TTL:
            return hit[1]
        _cache.pop(key, None)
        return None


def _cache_put(key: str, value: dict) -> None:
    with _cache_lock:
        if len(_cache) >= CACHE_MAX:
            _cache.pop(min(_cache, key=lambda k: _cache[k][0]), None)
        _cache[key] = (_now(), value)


def _ask(kind: str, username: str, client: ClaudeClient, extra: dict, *, version: str, grounding: Any,
         system: str, user: str, schema: dict, check: Callable[[Any], dict], key_extra: Any = None) -> dict:
    """쓸 수 있나 → 한도 설정 → 캐시(근거 + 모델 + 프롬프트 판 · `key_extra`) → 한도(한 그릇) → 호출 → 비용 한 줄 → 검사 → 캐시.
    `check(data)` 는 검사를 통과한 칸들을 돌려준다. 실패는 캐시하지 않는다. `key_extra` 는 근거(프롬프트)에 싣지 않지만 검사 결과를
    바꾸는 것(말로 설계의 지금 설정값)이다 — 열쇠에만 넣는다."""
    why = client.unavailable_reason()
    if why:
        return _unavailable(why, extra)
    limit = _limit()
    if limit is None:
        return _unavailable("config", extra)
    model = os.getenv("CLAUDE_MODEL") or DEFAULT_MODEL
    parts = [version, model, grounding] if key_extra is None else [version, model, grounding, key_extra]
    key = hashlib.sha256(json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    hit = _cache_get(key)
    if hit:
        return {**hit, "cached": True}                   # 부르지 않았다 — 한도에 세지 않는다
    if not _limiter.allow(username, limit, _now()):
        return _unavailable("rate_limited", extra, limit=limit)

    r = client.invoke_structured(system, user, schema, model=model, effort=EFFORT, max_tokens=MAX_TOKENS)
    usage = {"input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
             "cost_usd": r.cost_usd, "cost_note": r.cost_note}
    logger.info("canvas-assist %s user=%s model=%s served=%s in=%d out=%d cost_usd=%s error=%s",
                kind, username, model, r.served_model, r.input_tokens, r.output_tokens,
                "미상" if r.cost_usd is None else f"{r.cost_usd:.6f}", r.error)
    if r.error:
        return _unavailable(r.error, extra, detail=r.detail)             # 실패는 캐시하지 않는다
    res = {"available": True, "source": "claude", "model": r.served_model or model, **check(r.data),
           "cached": False, "usage": usage}
    _cache_put(key, res)
    return res


def suggest(graph: Any, username: str, *, catalog: Callable[[], dict], validate: Callable[[Any], dict],
            client: ClaudeClient | None = None) -> dict:
    rep = validate(graph)
    if not isinstance(graph, dict) or any(e.get("code") in FATAL_CODES or e.get("code") == "document"
                                          for e in rep.get("errors") or []):
        return _unavailable("bad_graph", {"rule": None})
    proc = rep.get("procedure") or {}
    rule = {"next": proc.get("next"), "by_gate": proc.get("by_gate")}
    kinds = catalog()
    g = gr.ground(graph, kinds, rep)

    def check(data: Any) -> dict:
        ok, bad = ck.check(data, graph, kinds, gr.numbers_of(g), validate)
        return {"suggestions": ok, "rejected": bad}
    return _ask("suggest", username, client or ClaudeClient.get_default(), {"rule": rule}, version=pr.PROMPT_VERSION,
                grounding=g, system=pr.SYSTEM, user=pr.user_prompt(g), schema=pr.output_schema(kinds), check=check)


def narrate(graph: Any, facts: list[dict], username: str, *, catalog: Callable[[], dict], key: bytes,
            client: ClaudeClient | None = None) -> dict:
    """AI2 — 화면이 돌려보낸 설명 중 ★서버 봉인이 지금 문서로 확인되는 것만★ 근거로 풀어 쓴다. 확인 못 한 것은 `dropped`."""
    if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list) or not isinstance(graph.get("edges"), list):
        return _unavailable("bad_graph", {"dropped": []})
    verified, dropped = nr.verify_facts(graph, facts, key)
    if not verified:                                     # 부르기 전에 — 근거 없는 글은 쓰지 않는다
        return _unavailable("stale_facts" if facts else "no_facts", {"dropped": dropped})
    g = nr.ground(verified, catalog())

    def check(data: Any) -> dict:
        ok, bad = nr.check(data, g)
        return {"paragraphs": ok, "rejected": bad, "dropped": dropped, "notice": nr.NOTICE if g["practice"] else None}
    res = _ask("narrate", username, client or ClaudeClient.get_default(), {"dropped": dropped},
               version=pr.NARRATE_VERSION, grounding=g, system=pr.NARRATE_SYSTEM, user=pr.narrate_user(g),
               schema=pr.narrate_schema([n["id"] for n in g["nodes"]]), check=check)
    return {**res, "dropped": dropped}


def ask(graph: Any, target: dict, question: str, previous: dict | None, facts: list[dict], records: list[dict],
        username: str, *, catalog: Callable[[], dict], relate: Callable[[Any], dict], key: bytes,
        client: ClaudeClient | None = None) -> dict:
    """AI3 — 고른 노드·선의 범위(조상 전부 + 그것 + 바로 아래) 안에서 ★봉인이 지금 문서로 확인되는 설명·기록만★ 근거로 답한다.
    대상 자신의 확인된 결과가 없으면 부르지 않는다. 범위 밖에서 깨진 것은 말하지 않는다(쓰지 않으니까)."""
    if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list) or not isinstance(graph.get("edges"), list):
        return _unavailable("bad_graph", {"dropped": []})
    sc = ak.scope(graph, target)
    if sc is None:
        return _unavailable("no_target", {"dropped": []})
    nodes_in, edges_in = sc
    verified, dropped_n = nr.verify_facts(graph, facts, key)
    records_ok, dropped_e = ak.verify_records(graph, records, key)
    dropped = [d for d in dropped_n if d.get("node_id") in nodes_in] + [d for d in dropped_e if d.get("edge_id") in edges_in]
    has = (target["id"] in {f["node_id"] for f in verified}) if target["kind"] == "node" else target["id"] in records_ok
    if not has:                                          # 부르기 전에 — 대상의 지금 결과 없이 답하지 않는다
        return _unavailable("no_facts_target", {"dropped": dropped})
    g, refs = ak.ground(graph, target, question, previous, verified, records_ok, catalog(), relate(graph))
    res = ask_grounded(g, refs, username, client=client, extra={"dropped": dropped},
                       scope={"nodes": nodes_in, "edges": edges_in})
    return {**res, "dropped": dropped}


def ask_grounded(g: dict, refs: dict, username: str, *, client: ClaudeClient | None = None, extra: dict | None = None,
                 scope: dict | None = None, kind: str = "ask", version: str = pr.ASK_VERSION, system: str = pr.ASK_SYSTEM,
                 cannot: dict | None = None) -> dict:
    """확인된 사실 줄(`g` · `refs` — 줄 id 는 서버가 붙인 것)로 묻기 — AI3 의 뒷부분(봉인 확인 뒤) · PB4 고객 한 장의 미리 묻기.
    문장마다 줄 · 그 줄의 숫자만 · 답할 수 없으면 서버 고정 문장(`cannot` — 기본은 AI3 의 것). 한도는 같은 그릇(사용자별)."""
    def check(data: Any) -> dict:
        answer, bad = ak.check(data, g, cannot or ak.CANNOT)
        cited = {f for s in answer["sentences"] for f in s["fact_ids"]}
        out = {"answer": answer, "facts": {f: refs[f] for f in sorted(cited, key=lambda x: int(x[1:]))}, "rejected": bad,
               "notice": nr.NOTICE if g["practice"] else None}
        return {**out, "scope": scope} if scope is not None else out
    return _ask(kind, username, client or ClaudeClient.get_default(), extra or {},
                version=version, grounding=g, system=system, user=pr.ask_user(g),
                schema=pr.ask_schema([x["id"] for x in g["lines"]]), check=check)


def ask_sheet(sheet: dict, sheet_id: str, question: str, previous: dict | None, username: str, *,
              client: ClaudeClient | None = None) -> dict:
    """PB4 — 서버가 저장한 고객 한 장의 줄만 근거로 묻는다(봉인 확인이 필요 없다 — 서버가 만든 한 장을 서버가 읽는다).
    답할 수 없으면 고객용 고정 문장. 한도는 묻는 사람(PB)의 그릇."""
    from src.services.canvas_assist import sheet_ask as sa
    g, refs = sa.ground_sheet(sheet, sheet_id, question, previous)
    return ask_grounded(g, refs, username, client=client, kind="sheet_ask", version=pr.SHEET_ASK_VERSION,
                        system=pr.SHEET_ASK_SYSTEM, cannot=sa.CANNOT_CLIENT)


def guide(graph: Any, state: dict, applicable: list[str], username: str, *, catalog: Callable[[], dict],
          client: ClaudeClient | None = None) -> dict:
    """AI5 — 화면이 센 상태와 ★지금 적용되는 도구★만 보고 써 볼 도구 1~2 와 이유. 도구 안내만(투자 판단 없음). 적용되는 도구가 없으면 부르지 않는다."""
    if not gd.tools(applicable):
        return _unavailable("no_tools")
    g = gd.ground(graph, state, applicable, catalog())

    def check(data: Any) -> dict:
        ok, bad = gd.check(data, g)
        return {"tips": ok, "rejected": bad}
    return _ask("guide", username, client or ClaudeClient.get_default(), {}, version=pr.GUIDE_VERSION, grounding=g,
                system=pr.GUIDE_SYSTEM, user=pr.guide_user(g), schema=pr.guide_schema([t["id"] for t in g["tools"]]), check=check)


def draft(graph: Any, sentence: str, username: str, *, catalog: Callable[[], dict], validate: Callable[[Any], dict],
          field_errors: Callable[[str, dict], set], resolve_ticker: Callable[[str], dict],
          client: ClaudeClient | None = None) -> dict:
    """AI4 — 말씀을 지금 캔버스를 고치는 초안으로(더하기·잇기·값). ★값은 서버가 말씀 조각에서 읽는다★ — Claude 는 조각과 읽는 법만.
    읽을 수 없는 문서면 부르지 않는다. 캐시 열쇠에 지금 설정값을 더한다(근거에는 싣지 않지만 값 검사·빈 칸 판정이 그것을 본다)."""
    rep = validate(graph)
    if not isinstance(graph, dict) or any(e.get("code") in FATAL_CODES or e.get("code") == "document"
                                          for e in rep.get("errors") or []):
        return _unavailable("bad_graph")
    kinds = catalog()
    g = df.ground(graph, sentence, kinds, rep)
    params = {str(n.get("id")): n.get("params") for n in graph["nodes"] if isinstance(n, dict)}

    def check(data: Any) -> dict:
        return df.check(data, g, graph, kinds, validate, field_errors, resolve_ticker)
    return _ask("draft", username, client or ClaudeClient.get_default(), {}, version=pr.DRAFT_VERSION, grounding=g,
                system=pr.DRAFT_SYSTEM, user=pr.draft_user(g), schema=pr.draft_schema(kinds), check=check, key_extra=params)
