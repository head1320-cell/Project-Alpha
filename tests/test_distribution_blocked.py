"""AE3 → PB6 — ★유통 표면은 관문 뒤에만 있다★ 를 주석이 아니라 **검증**으로.

AE3 는 "유통 표면이 없다" 를 지켰다. 사용자 결정(2026-10-23)으로 PB6 고객 주소·고객 화면·고객 AI 가 ★관문 뒤에★ 생겼다 —
코드는 있고, 여는 것은 운영자가 인가 기록을 선언해야(PB5). 그래서 이 파일이 지키는 것도 바뀌었다:

  ① 유통 형태 경로는 ★전부★ 등록부(`src/api/distribution_surface.py`)에 있다 — 여는 것(관문 뒤)과 닫는 것(늘 됨), 사유와 함께.
     등록부에 없는 유통 형태 경로가 생기면 빨간불(심은 경로로 확인).
  ② 여는 것은 관문을 닫은 채 부르면 ★실제로★ 403 `distribution_blocked` 다(선언이 아니라 동작 — 없는 고객·주소로 불러도
     조회보다 먼저 막힌다). 닫는 것은 토큰·한 장을 내지 않는다.
  ③ 이 저장소를 그대로 돌리면 관문은 닫혀 있다 · P4 유통 완료 판정은 여전히 비어 있다 · 로드맵이 이름 지은 유통 타입은 없다.

★이 검사가 빨개졌다고 무조건 되돌리라는 뜻은 아니다★ — 새 유통 경로라면 등록부에 여는 것/닫는 것과 사유를 적고, 여는 것이면
관문을 맨 앞에 건다. 막는 것이 아니라 **멈춰 세우는 것**이 목적이다.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from src.api.distribution_surface import CLOSES, DISTRIBUTION_SURFACE, OPENS
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


# ── ① 유통 형태 경로는 전부 등록부에 ─────────────────────────────────────

def _marked(routes) -> list[tuple[str, str]]:
    return [(m, p) for m, p in routes if any(marker in p.lower() for marker in DISTRIBUTION_PATH_MARKERS)]


def test_every_distribution_shaped_route_is_registered(app):
    """★전수★ — 유통 형태 경로가 앱에 있으면 등록부에 있어야 한다(여는 것·닫는 것 · 사유)."""
    unregistered = sorted(set(_marked(_routes(app))) - set(DISTRIBUTION_SURFACE))
    assert not unregistered, (
        "등록부에 없는 유통 형태 라우트가 생겼습니다. 유통은 업권 사항이라 여는 경로는 관문 뒤에만 둡니다 — "
        f"`src/api/distribution_surface.py` 에 여는 것/닫는 것과 사유를 적고 관문을 맨 앞에 거세요: {unregistered}"
    )


def test_every_registered_route_exists_and_says_why(app):
    routes = set(_routes(app))
    assert DISTRIBUTION_SURFACE, "등록부가 비면 ①은 언제나 통과한다"
    for key, (kind, why) in DISTRIBUTION_SURFACE.items():
        assert key in routes, f"등록부에 있지만 앱에 없는 경로: {key}"
        assert kind in (OPENS, CLOSES) and why.strip(), key
    assert {k for k, (kind, _) in DISTRIBUTION_SURFACE.items() if kind == OPENS}, "여는 것이 없으면 ②가 공허하다"


def test_the_route_detector_actually_detects():
    """★테스트의 테스트★ — 검출기를 빈 목록으로 바꾸면 ①이 무력해진다."""
    assert DISTRIBUTION_PATH_MARKERS, "마커가 비면 ①은 언제나 통과한다"
    assert any("subscribe" in m for m in DISTRIBUTION_PATH_MARKERS)


def test_a_planted_distribution_route_would_be_caught():
    """가짜 라우트를 심어 ①이 실제로 잡는지 본다 — 마커에 걸리고, 등록부에 없다."""
    from fastapi import FastAPI

    probe = FastAPI()

    @probe.post("/api/v1/marketplace/subscribe")
    def _sneaky():  # pragma: no cover - 호출하지 않는다
        return {}

    @probe.post("/api/v1/share/publish-everything")
    def _sneaky_share():  # pragma: no cover - 호출하지 않는다
        return {}

    unregistered = set(_marked(_routes(probe))) - set(DISTRIBUTION_SURFACE)
    assert {("POST", "/api/v1/marketplace/subscribe"), ("POST", "/api/v1/share/publish-everything")} <= unregistered


# ── ② 여는 것은 관문을 닫은 채 부르면 실제로 403 · 닫는 것은 토큰·한 장을 내지 않는다 ─────────

_IDS = {"cid": "cl_0000000000000000", "lid": "ln_0000000000000000"}
#: 경로마다 모양이 맞는 본문 — 본문 검사(422)가 관문보다 먼저 나와 공허하게 통과하지 않게.
_BODIES = {
    ("POST", "/api/v1/pb/clients/{cid}/share-links"): {"sheet_id": "sh_0000000000000000", "pin": "382915", "days": 30},
    ("PATCH", "/api/v1/pb/clients/{cid}/share-links/{lid}"): {"sheet_id": "sh_0000000000000000"},
    ("POST", "/api/v1/share/open"): {"token": "x" * 43, "pin": "382915"},
    ("POST", "/api/v1/share/ask"): {"question": "비중은요?"},
}


@pytest.fixture()
def live(monkeypatch):
    import os
    import tempfile

    from fastapi.testclient import TestClient

    import src.database as dbmod
    from src.domain.auth_identity import ROLE_ANALYST
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp.name}")
    monkeypatch.setenv("AUTH_SECRET", "distribution-blocked-secret-0123456789")
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    monkeypatch.setattr(dbmod, "DATABASE_URL", f"sqlite:///{tmp.name}", raising=False)
    dbmod.reset_session()
    dbmod.init_db()
    dbmod.create_user("alice", "alice-pw", role=ROLE_ANALYST)
    from src.app_factory import create_app
    with TestClient(create_app()) as c:
        tok = c.post("/api/v1/auth/login", json={"username": "alice", "password": "alice-pw"}).json()["access_token"]
        yield c, {"Authorization": f"Bearer {tok}"}
    dbmod.reset_session()
    os.unlink(tmp.name)


def test_every_opening_route_is_refused_while_the_gate_is_closed(live):
    """★동작★ — 등록부의 여는 것을 하나씩 실제로 부른다(로그인한 채 · 세션 머리글까지 붙여도). 없는 고객·주소라도 404 가 아니라 403."""
    c, h = live
    opened = [k for k, (kind, _) in DISTRIBUTION_SURFACE.items() if kind == OPENS]
    for method, path in opened:
        r = c.request(method, path.format(**_IDS), json=_BODIES.get((method, path)),
                      headers={**h, "X-Share-Session": "x"})
        assert r.status_code == 403, (method, path, r.status_code, r.text)
        d = r.json()["detail"]
        assert d["code"] == "distribution_blocked" and d["reason"] and d["missing"], (method, path)


def test_closing_routes_answer_with_the_gate_closed_and_hand_out_no_token_or_sheet(live):
    """닫는 것은 관문과 무관하게 늘 된다 — 그리고 토큰·한 장(내용)을 내지 않는다(고객 주소를 끄는 길이 막히면 안 된다)."""
    c, h = live
    cid = c.post("/api/v1/pb/clients", json={"alias": "고객 Z"}, headers=h).json()["client_id"]
    closing = [k for k, (kind, _) in DISTRIBUTION_SURFACE.items() if kind == CLOSES]
    assert closing
    for method, path in closing:
        r = c.request(method, path.format(**{**_IDS, "cid": cid}), json=_BODIES.get((method, path)), headers=h)
        assert r.status_code in (200, 404), (method, path, r.status_code, r.text)      # 없는 주소는 404 — 관문 403 이 아니다
        text = r.text
        assert "distribution_blocked" not in text and '"token"' not in text and '"sheet"' not in text, (method, path)


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
