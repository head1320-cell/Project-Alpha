"""AC4 — ★레지스트리와 실제 라우트 테이블을 양방향으로 대조한다★.

잠근 것만 검사하면 **빠뜨린 것을 영원히 모른다**. 그래서 세 방향으로 본다:
① 적어 둔 것이 실제로 잠겼나  ② 잠긴 것이 적혀 있나  ③ 키워드에 걸리는데
양쪽 어디에도 없는 것이 있나. ③ 이 새 라우트가 조용히 열리는 것을 막는다.
"""
from __future__ import annotations

import pytest

from src.api.protected_routes import (
    MONEY_PATH_MARKERS,
    OPEN_WITH_REASON,
    PROTECTED,
    REQUIREMENTS,
    auth_requirement_of_route,
    looks_like_money_route,
)


@pytest.fixture(scope="module")
def app():
    from src.app_factory import create_app
    return create_app()


def _real_routes(app) -> dict[tuple[str, str], object]:
    out: dict[tuple[str, str], object] = {}
    for r in app.routes:
        path = getattr(r, "path", None)
        for method in sorted(getattr(r, "methods", None) or []):
            if method in {"HEAD", "OPTIONS"}:
                continue
            out[(method, path)] = r
    return out


# ── 레지스트리 자체의 위생 ─────────────────────────────────────────────────

def test_every_protected_entry_has_a_known_requirement_and_a_reason():
    for key, (level, why) in PROTECTED.items():
        assert level in REQUIREMENTS, f"{key} 의 요구 수준이 어휘 밖: {level}"
        assert why and why.strip(), f"{key} 에 사유가 없다"


def test_every_exemption_has_a_reason():
    """★사유 없는 면제는 면제가 아니라 누락이다★."""
    for key, why in OPEN_WITH_REASON.items():
        assert why and why.strip(), f"{key} 를 사유 없이 열어 두었다"


def test_the_two_lists_do_not_overlap():
    assert not (set(PROTECTED) & set(OPEN_WITH_REASON))


# ── ① 적어 둔 것이 실제로 존재하고 잠겼나 ─────────────────────────────────

def test_every_registered_route_actually_exists(app):
    """오타·경로 변경이면 여기서 걸린다 — 존재하지 않는 라우트를 잠갔다고 믿지 않는다."""
    real = _real_routes(app)
    missing = [k for k in PROTECTED if k not in real]
    assert not missing, f"레지스트리에 있으나 앱에 없는 라우트: {missing}"


def test_every_registered_route_carries_the_requirement_it_declares(app):
    """★완료 판정의 뼈대★ — 적어 둔 수준이 실제 의존성 그래프에 붙어 있나."""
    real = _real_routes(app)
    wrong = []
    for key, (level, _why) in PROTECTED.items():
        actual = auth_requirement_of_route(real[key])
        if actual != level:
            wrong.append((key, level, actual))
    assert not wrong, f"선언과 실제가 다른 라우트: {wrong}"


# ── ② 잠긴 것이 적혀 있나 ─────────────────────────────────────────────────

def test_no_route_is_locked_without_being_registered(app):
    """몰래 붙인 인증도 기록되지 않은 정책이다."""
    stray = [
        key for key, route in _real_routes(app).items()
        if auth_requirement_of_route(route) is not None and key not in PROTECTED
    ]
    assert not stray, f"잠겨 있으나 레지스트리에 없는 라우트: {stray}"


# ── ③ ★전수★ — 키워드에 걸리는데 양쪽 어디에도 없는 것 ───────────────────

def test_no_money_shaped_route_is_silently_open(app):
    """새 주문·킬스위치 라우트가 조용히 열리면 실패한다."""
    unaccounted = [
        key for key in _real_routes(app)
        if looks_like_money_route(key[1])
        and key not in PROTECTED and key not in OPEN_WITH_REASON
    ]
    assert not unaccounted, (
        "돈·PII 후보인데 보호도 면제도 선언되지 않은 라우트:\n  "
        + "\n  ".join(f"{m} {p}" for m, p in sorted(unaccounted))
    )


def test_the_detector_actually_detects(app):
    """★테스트의 테스트★ — 검출기를 항상-빈-목록으로 바꾸면 ③이 무력해진다."""
    assert looks_like_money_route("/api/v1/live/orders/submit") is True
    assert looks_like_money_route("/api/v1/health") is False
    assert MONEY_PATH_MARKERS, "마커가 비면 ③은 언제나 통과한다"


def test_a_newly_added_money_route_would_be_caught(app):
    """가짜 라우트를 심어 ③이 실제로 잡는지 본다."""
    from fastapi import FastAPI

    probe = FastAPI()

    @probe.post("/api/v1/live/orders/sneaky")
    def _sneaky():  # pragma: no cover - 호출하지 않는다
        return {}

    unaccounted = [
        key for key in _real_routes(probe)
        if looks_like_money_route(key[1])
        and key not in PROTECTED and key not in OPEN_WITH_REASON
    ]
    assert ("POST", "/api/v1/live/orders/sneaky") in unaccounted


# ── 과잉 차단 배제 ────────────────────────────────────────────────────────

def test_exempted_routes_stay_open(app):
    """★짝★ — 전부 잠그는 구현을 배제한다. 면제한 것은 실제로 열려 있어야 한다."""
    real = _real_routes(app)
    wrongly_locked = [
        key for key in OPEN_WITH_REASON
        if key in real and auth_requirement_of_route(real[key]) is not None
    ]
    assert not wrongly_locked, f"면제한다고 적고 잠근 라우트: {wrongly_locked}"


def test_the_research_surface_is_untouched(app):
    """범위는 돈·PII 다 — 연구 라우트까지 잠그지 않았는지 표본으로 확인한다."""
    real = _real_routes(app)
    for key in [("GET", "/health"), ("GET", "/")]:
        if key in real:
            assert auth_requirement_of_route(real[key]) is None
