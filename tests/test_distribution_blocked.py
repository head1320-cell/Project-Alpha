"""AE3 — ★"유통을 만들지 않았다" 를 주석이 아니라 **검증**으로★.

범위 밖이라고 문서에 적는 것만으로는 6개월 뒤를 지키지 못한다. 이 파일은 유통
표면이 **실제로 없다**는 것을 앱의 라우트 테이블과 소스 전수로 확인하고, 생기는
순간 빨간불을 켠다. 그때 이 파일의 사유를 읽고 **인가를 먼저 확인**하게 된다.

★이 검사가 빨개졌다고 무조건 되돌리라는 뜻은 아니다★ — 인가가 확인됐다면
`docs/plans/2026-09-12-ra-product-roadmap.md` 의 P4 완료 판정을 그 조건에 맞춰 쓴 뒤
이 목록을 함께 고치는 것이 맞다. 막는 것이 아니라 **멈춰 세우는 것**이 목적이다.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from src.domain.distribution_gate import DISTRIBUTION_BLOCKED, distribution_gate

_ROOT = pathlib.Path(__file__).resolve().parents[1]

#: 유통 형태 경로 조각. ★넓게 잡는다★ — 거짓 양성은 면제 한 줄로 끝나지만
#: 거짓 음성은 인가 없이 열린 유통 표면이다.
DISTRIBUTION_PATH_MARKERS = (
    "marketplace", "subscribe", "subscription", "provider",
    "publish", "storefront", "/share", "entitlement", "billing",
)

#: 유통 도메인 타입 이름. 로드맵이 P4 의 재료로 이름 지은 것들.
DISTRIBUTION_TYPE_NAMES = (
    "StrategyProvider", "StrategySubscription", "StrategyEvaluationScorecard",
    "Subscriber", "Entitlement", "Storefront",
)


@pytest.fixture(scope="module")
def app():
    from src.app_factory import create_app
    return create_app()


def _routes(app) -> list[tuple[str, str]]:
    out = []
    for r in app.routes:
        path = getattr(r, "path", "") or ""
        for method in sorted(getattr(r, "methods", None) or []):
            if method not in {"HEAD", "OPTIONS"}:
                out.append((method, path))
    return out


# ── ① 앱에 유통 라우트가 없다 ─────────────────────────────────────────────

def test_no_distribution_route_exists(app):
    """★전수★ — 유통 형태 경로가 앱에 하나도 없다."""
    found = [
        (m, p) for m, p in _routes(app)
        if any(marker in p.lower() for marker in DISTRIBUTION_PATH_MARKERS)
    ]
    assert not found, (
        "유통 형태 라우트가 생겼습니다. P4 는 업권 사항이라 인가 확인 전에는 "
        f"만들지 않기로 했습니다(로드맵 P4): {found}"
    )


def test_the_route_detector_actually_detects():
    """★테스트의 테스트★ — 검출기를 빈 목록으로 바꾸면 ①이 무력해진다."""
    assert DISTRIBUTION_PATH_MARKERS, "마커가 비면 ①은 언제나 통과한다"
    assert any("subscribe" in m for m in DISTRIBUTION_PATH_MARKERS)


def test_a_planted_distribution_route_would_be_caught():
    """가짜 라우트를 심어 ①이 실제로 잡는지 본다."""
    from fastapi import FastAPI

    probe = FastAPI()

    @probe.post("/api/v1/marketplace/subscribe")
    def _sneaky():  # pragma: no cover - 호출하지 않는다
        return {}

    found = [
        (m, p) for m, p in _routes(probe)
        if any(marker in p.lower() for marker in DISTRIBUTION_PATH_MARKERS)
    ]
    assert ("POST", "/api/v1/marketplace/subscribe") in found


# ── ② 소스에 유통 타입이 없다 ─────────────────────────────────────────────

def test_no_distribution_type_is_defined_in_the_source():
    """★전수★ — 로드맵이 P4 의 재료로 이름 지은 타입들이 아직 없다."""
    offenders: list[str] = []
    for path in (_ROOT / "src").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name in DISTRIBUTION_TYPE_NAMES:
                offenders.append(f"{path.relative_to(_ROOT)}:{node.name}")
    assert not offenders, f"유통 도메인 타입이 정의됐습니다: {offenders}"


def test_the_type_detector_actually_detects():
    """★테스트의 테스트★"""
    tree = ast.parse("class StrategySubscription:\n    pass\n")
    found = [n.name for n in ast.walk(tree)
             if isinstance(n, ast.ClassDef) and n.name in DISTRIBUTION_TYPE_NAMES]
    assert found == ["StrategySubscription"]


# ── ③ 관문이 실제로 닫혀 있다 ─────────────────────────────────────────────

def test_the_gate_is_closed_in_this_repository():
    """★이 저장소를 그대로 돌리면 유통은 막혀 있다★."""
    assert distribution_gate()["state"] == DISTRIBUTION_BLOCKED


def test_the_roadmap_still_leaves_the_distribution_verdict_empty():
    """★로드맵이 "지금 적으면 근거 없는 판정이 스펙에 박힌다" 고 한 그 자리★.

    유통에 대한 완료 판정을 쓰지 않았다는 사실을 문서에서 확인한다. 인가가 확인되면
    이 테스트를 함께 고치는 것이 맞고, 그 전에 판정만 먼저 쓰이는 것을 막는다.
    """
    roadmap = (_ROOT / "docs" / "plans" / "2026-09-12-ra-product-roadmap.md"
               ).read_text(encoding="utf-8")
    p4 = roadmap.split("## P4.")[1]
    assert "이번 로드맵에서 정의하지 않는다" in p4, (
        "P4 의 유통 완료 판정이 인가 확인 없이 쓰였습니다.")
