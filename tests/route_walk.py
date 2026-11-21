"""라우트 표를 ★평평하게★ 훑는 한 곳 — 라우트 표를 보는 시험은 모두 이것만 쓴다(`app.routes` 를 직접 돌지 않는다).

FastAPI 0.16x 의 `include_router` 는 라우트를 앱에 복사하지 않고 `_IncludedRouter` 하나를 끼운다. `app.routes` 를 그대로 돌면
`APIRoute` 를 0개 보고, 그 표에 기대는 안전 계약 시험이 아무것도 안 보고 통과한다(`tests/test_route_walk.py`).
FastAPI 가 OpenAPI 를 만들 때 쓰는 `iter_route_contexts` 로 훑는다 — 돌려받는 것은 `path`·`methods`·`endpoint`·`matches()` 를
가진 라우트 문맥이다(접두어가 붙은 전체 경로).
"""
from __future__ import annotations

from fastapi.routing import iter_route_contexts


def flat_routes(app_or_routes) -> list:
    """앱이나 라우트 목록(`app.routes`)을 받아 중첩 라우터까지 펼친 라우트 문맥 목록을 돌려준다."""
    routes = getattr(app_or_routes, "routes", app_or_routes)
    return list(iter_route_contexts(routes))
