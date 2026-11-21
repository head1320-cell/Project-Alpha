"""라우트 표를 훑는 한 곳(`tests/route_walk.py::flat_routes`)이 ★빠짐없이★ 보는가.

## 왜 (2026-11-08 · 기술 스택 6단계)

FastAPI 0.16x 부터 `include_router` 는 라우트를 앱에 복사하지 않고 `_IncludedRouter` 하나를 끼운다. 예전처럼 `app.routes` 를
그대로 돌면 `APIRoute` 를 **0개** 본다(실측: 0.111 에서 390개 → 0.162 에서 0개). 그러면 라우트 표에 기대는 안전 계약 시험 —
잠금 등록부(`test_protected_routes`) · 유통 관문(`test_distribution_blocked`) · 그림자 경로(`test_routes_not_shadowed`) — 가
★아무것도 안 보고 통과★한다. 예전 고정 사유("상위에서 include_router 가 깨짐")의 실체가 이것이었다.

그래서 시험들은 이제 `flat_routes()` 하나로만 훑고, 이 파일은 그 훑기가 비어 있지 않고 빠짐이 없음을 FastAPI 자신의 목록(OpenAPI)과
중첩 라우터로 건다.
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from fastapi import APIRouter, FastAPI  # noqa: E402

from tests.route_walk import flat_routes  # noqa: E402

AUTO = {"HEAD", "OPTIONS"}


def _pairs(routes) -> set[tuple[str, str]]:
    return {(m, r.path) for r in routes for m in (getattr(r, "methods", None) or ()) if m not in AUTO and getattr(r, "path", None)}


def test_the_walk_sees_every_route_fastapi_itself_documents():
    """★FastAPI 가 OpenAPI 로 내보내는 모든 (메서드, 경로)★ 가 훑기에 있어야 한다 — FastAPI 자신의 목록과 견준다."""
    from src.app_factory import create_app
    app = create_app()
    documented = {(m.upper(), p) for p, ops in app.openapi()["paths"].items() for m in ops if m.upper() not in AUTO}
    walked = _pairs(flat_routes(app))
    assert len(documented) > 100, f"OpenAPI 에 경로가 너무 적다({len(documented)}) — 앱이 라우터를 등록하지 못했다"
    missing = sorted(documented - walked)
    assert not missing, f"훑기가 FastAPI 문서에 있는 라우트를 못 봤다({len(missing)}): {missing[:5]}"


def test_the_walk_sees_a_route_inside_nested_routers():
    """★짝★ 라우터 안의 라우터(접두어 둘)까지 — 전체 경로로 보인다. 평평한 `app.routes` 만 보면 0개다."""
    inner = APIRouter(prefix="/inner")

    @inner.get("/leaf")
    def leaf():  # pragma: no cover - 부르지 않는다
        return {}

    outer = APIRouter(prefix="/outer")
    outer.include_router(inner)
    app = FastAPI()
    app.include_router(outer)
    assert ("GET", "/outer/inner/leaf") in _pairs(flat_routes(app))


def test_the_walk_accepts_a_plain_route_list_too():
    """`create_app().routes` 처럼 목록을 넘겨도 같은 답 — 기존 시험의 호출 모양을 바꾸지 않게."""
    r = APIRouter()

    @r.get("/x")
    def x():  # pragma: no cover
        return {}

    app = FastAPI()
    app.include_router(r)
    walked = _pairs(flat_routes(app))
    assert _pairs(flat_routes(app.routes)) == walked
    assert ("GET", "/x") in walked      # 앱 기본 경로(/docs·/openapi.json 등)도 함께 보인다
