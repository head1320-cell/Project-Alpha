"""캔버스 계산의 실행자 — ★누가 했는가★를 선언한 노드까지 (캔버스 분봉 노드 설계 §5)
==============================================================================
캔버스의 계산 문(`/graph/run`)과 저장 문(`/graph/save`)은 열린 연구 문이다 — 로그인하지 않아도 쓴다.
그런데 분봉 백테스트는 실행마다 사용자별 시행 횟수를 세고, 결과는 본인만 읽는다. 그래서 문은 열어 둔 채
★신원을 요구하는 노드가 그래프에 있을 때만★ 요청의 신원을 읽어 엔진에 넘긴다(`NodeSpec.wants_actor`).

- 읽는 길은 잠긴 문과 같다(`get_current_principal` → `require_login` — 서명 · 계정 존재 · 토큰 판 · 임시 비밀번호).
- 신원이 없으면 ★그 까닭★을 싣는다. 로그인하지 않음 · 토큰이 낡음 · 임시 비밀번호 · 계정 저장소 확인 실패는 서로 다른
  문장이다 — "확인하지 못함"을 "로그인 안 함"으로 접지 않는다.
- 주변 상태(컨텍스트 변수 · 스레드)를 쓰지 않는다 — 값은 인자로만 흐른다.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request

from src.api import auth
from src.engine import portfolio_graph as pg

NOT_SIGNED_IN = "로그인하지 않았습니다."
NO_ACTOR = "실행자를 확인하지 않는 경로입니다."


@dataclass(frozen=True)
class Actor:
    """계산을 시킨 사람. `username` 이 없으면 `reason` 이 그 까닭이다."""
    username: str | None
    reason: str | None = None


def actor_of(request: Request | None) -> Actor:
    """요청의 신원 → 실행자. ★문을 잠그지 않는다★ — 실패는 예외가 아니라 사유를 실은 실행자다."""
    if request is None:
        return Actor(None, NO_ACTOR)
    if auth._bearer_token(request) is None:
        return Actor(None, NOT_SIGNED_IN)
    try:
        principal = auth.require_login(request, auth.get_current_principal(request))
    except HTTPException as err:
        return Actor(None, str(err.detail))
    return Actor(principal.username)


def wanted(graph: Any, registry: pg.Registry) -> bool:
    """그래프에 실행자를 받는 노드가 있는가 — 없으면 신원을 읽지 않는다(계정 조회가 늘지 않는다)."""
    nodes = graph.get("nodes") if isinstance(graph, Mapping) else None
    if not isinstance(nodes, list):
        return False
    for node in nodes:
        spec = registry.get(str(node.get("type"))) if isinstance(node, Mapping) else None
        if spec is not None and spec.wants_actor:
            return True
    return False


def require(actor: Any, rule: str) -> str:
    """노드가 쓴다 — 실행자의 사용자 이름. 없으면 `rule`(누구만 쓰는지 한 문장)과 그 까닭으로 실패한다."""
    if isinstance(actor, Actor) and actor.username:
        return actor.username
    why = actor.reason if isinstance(actor, Actor) and actor.reason else NO_ACTOR
    raise pg.NodeFailure(f"{rule} — {why}")
