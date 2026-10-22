"""AI 노드 추천(AI1) — 쓸 수 있나 → 근거 → 캐시 → 한도 → Claude → 검사.

응답은 둘 중 하나다:
- `{available:true, source:"claude", model, suggestions, rejected, cached, usage}` — 검사를 통과한 것만 `suggestions`.
- `{available:false, source:"unavailable", reason_code, reason, rule}` — ★AI 글은 없다★(데모 글 금지). `rule` 은 규칙 대체
  (`/validate` 절차의 next·by_gate — 화면은 규칙 추천을 그대로 보인다).

`catalog`·`validate` 는 경로가 넘긴다(`allocation_graph_routes._kinds`·`graph_validate`) — 서비스가 API 층을 import 하지 않게.
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
from src.services.canvas_assist import check as ck
from src.services.canvas_assist import ground as gr
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


def _unavailable(code: str, rule: dict | None = None, **fmt: Any) -> dict:
    reason = REASONS.get(code, REASONS["unexpected"]).format(**{k: (v if v not in (None, "") else "없음")
                                                                for k, v in fmt.items()})
    return {"available": False, "source": "unavailable", "reason_code": code, "reason": reason, "rule": rule}


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


def suggest(graph: Any, username: str, *, catalog: Callable[[], dict], validate: Callable[[Any], dict],
            client: ClaudeClient | None = None) -> dict:
    rep = validate(graph)
    if not isinstance(graph, dict) or any(e.get("code") in FATAL_CODES or e.get("code") == "document"
                                          for e in rep.get("errors") or []):
        return _unavailable("bad_graph")
    proc = rep.get("procedure") or {}
    rule = {"next": proc.get("next"), "by_gate": proc.get("by_gate")}

    client = client or ClaudeClient.get_default()
    why = client.unavailable_reason()
    if why:
        return _unavailable(why, rule)
    limit = _limit()
    if limit is None:
        return _unavailable("config", rule)

    kinds = catalog()
    model = os.getenv("CLAUDE_MODEL") or DEFAULT_MODEL
    g = gr.ground(graph, kinds, rep)
    key = hashlib.sha256(json.dumps([pr.PROMPT_VERSION, model, g], ensure_ascii=False, sort_keys=True,
                                    default=str).encode("utf-8")).hexdigest()
    hit = _cache_get(key)
    if hit:
        return {**hit, "cached": True}                   # 부르지 않았다 — 한도에 세지 않는다
    if not _limiter.allow(username, limit, _now()):
        return _unavailable("rate_limited", rule, limit=limit)

    r = client.invoke_structured(pr.SYSTEM, pr.user_prompt(g), pr.output_schema(kinds), model=model,
                                 effort=EFFORT, max_tokens=MAX_TOKENS)
    usage = {"input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
             "cost_usd": r.cost_usd, "cost_note": r.cost_note}
    logger.info("canvas-assist suggest user=%s model=%s served=%s in=%d out=%d cost_usd=%s error=%s",
                username, model, r.served_model, r.input_tokens, r.output_tokens,
                "미상" if r.cost_usd is None else f"{r.cost_usd:.6f}", r.error)
    if r.error:
        return _unavailable(r.error, rule, detail=r.detail)              # 실패는 캐시하지 않는다

    ok, bad = ck.check(r.data, graph, kinds, gr.numbers_of(g), validate)
    res = {"available": True, "source": "claude", "model": r.served_model or model,
           "suggestions": ok, "rejected": bad, "cached": False, "usage": usage}
    _cache_put(key, res)
    return res
