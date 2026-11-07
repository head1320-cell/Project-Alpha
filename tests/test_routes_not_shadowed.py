"""가려진 경로 0 — 앞에 등록된 `{변수}` 경로가 뒤의 고정 경로를 삼키지 않는다.

발견(BV6a, 2026-10-09): `GET /api/v1/live/orders/active`·`/orders/state-distribution`(`stage13_extensions`)이
먼저 붙은 `GET /api/v1/live/orders/{client_order_id}`(`stage13_routes`)에 잡혀 "주문 없음" 404 를 냈다.
두 경로는 한 번도 닿은 적이 없었다.
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from fastapi.testclient import TestClient  # noqa: E402
from starlette.routing import Match  # noqa: E402

from src.app_factory import create_app  # noqa: E402


def _shadowed(routes) -> list[tuple[str, str, str]]:
    """(방법, 가려진 경로, 가린 경로). 경로 순서대로 첫 FULL 매치가 이긴다."""
    out = []
    api = [r for r in routes if hasattr(r, "methods") and r.methods]
    for i, r in enumerate(api):
        for m in r.methods:
            scope = {"type": "http", "path": r.path, "method": m}
            for q in api[:i]:
                if m in q.methods and q.path != r.path and q.matches(scope)[0] == Match.FULL:
                    out.append((m, r.path, q.path))
                    break
    return out


def test_no_route_is_swallowed_by_an_earlier_path_parameter():
    assert _shadowed(create_app().routes) == []


def test_the_detector_sees_a_swallowed_route():
    """★짝★ — 검출기가 언제나 빈 목록이면 위 검사는 공허하다."""
    from fastapi import APIRouter
    r = APIRouter()
    r.get("/x/{id}")(lambda id: id)
    r.get("/x/active")(lambda: 1)
    assert _shadowed(r.routes) == [("GET", "/x/active", "/x/{id}")]

