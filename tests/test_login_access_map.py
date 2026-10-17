"""BU8b · 로그인 화면의 '로그인이 여는 것' 지도는 서버 보호 목록과 같은 말을 한다.

화면(`frontend/src/entities/session/accessMap.json`)이 "로그인하면 열려요 · 거래 권한이 있는 계정만" 을 말하는데,
그 근거는 서버의 단일 레지스트리 `src/api/protected_routes.py::PROTECTED` 다. 화면이 지어내거나 낡지 않게:

  ① 로그인·관리자 층 경로의 합집합 == PROTECTED 키 전부 — ★양방향★: 서버가 새로 잠그면 화면도 말해야 하고,
     화면이 잠겼다고 말한 것은 실제로 잠겨 있어야 한다.
  ② 층 == 요구 수준 — 관리자 층은 REQUIRE_ADMIN 만, 로그인 층은 REQUIRE_LOGIN·REQUIRE_SELF_OR_ADMIN 만.
  ③ 열린 층 화면들이 부르는 API 접두사로 시작하는 보호 경로는 없다("로그인 없이 열려 있어요" 가 참).
  ④ 글자: em-dash·금지 표현 0, 항목은 비어 있지 않다.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.api.protected_routes import (
    PROTECTED,
    REQUIRE_ADMIN,
    REQUIRE_LOGIN,
    REQUIRE_SELF_OR_ADMIN,
)

MAP_PATH = Path(__file__).resolve().parents[1] / "frontend/src/entities/session/accessMap.json"
BANNED = ("검증됨", "입증됨", "견고함", "프로덕션 레디", "투자 우위", "더 나은 전략")


@pytest.fixture(scope="module")
def access_map() -> dict:
    return json.loads(MAP_PATH.read_text(encoding="utf-8"))


def _routes(tier: dict) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for item in tier["items"]:
        for r in item["routes"]:
            method, path = r.split(" ", 1)
            out.append((method, path))
    return out


def test_locked_tiers_cover_exactly_the_protected_registry(access_map):
    shown = _routes(access_map["login"]) + _routes(access_map["admin"])
    assert len(shown) == len(set(shown)), "같은 경로를 두 번 적었다"
    missing = set(PROTECTED) - set(shown)
    extra = set(shown) - set(PROTECTED)
    assert not missing, f"서버가 잠갔는데 로그인 화면이 말하지 않는다: {sorted(missing)}"
    assert not extra, f"로그인 화면은 잠겼다는데 서버 보호 목록에 없다: {sorted(extra)}"


def test_each_tier_matches_the_required_level(access_map):
    for key in _routes(access_map["admin"]):
        assert PROTECTED[key][0] == REQUIRE_ADMIN, f"관리자 층인데 서버 요구 수준은 {PROTECTED[key][0]}: {key}"
    for key in _routes(access_map["login"]):
        assert PROTECTED[key][0] in (REQUIRE_LOGIN, REQUIRE_SELF_OR_ADMIN), \
            f"로그인 층인데 서버 요구 수준은 {PROTECTED[key][0]}: {key}"


def test_open_tier_screens_call_no_protected_route(access_map):
    items = access_map["open"]["items"]
    assert len(items) >= 5
    for item in items:
        assert item["href"].startswith("/") and item["api_prefixes"], item
        for prefix in item["api_prefixes"]:
            locked = [k for k in PROTECTED if k[1].startswith(prefix)]
            assert not locked, f"'{item['label']}' 은 열려 있다고 말하는데 {prefix} 아래가 잠겨 있다: {locked}"


def test_the_pair_a_new_protected_route_would_fail_the_coverage_check(access_map):
    """짝: 비교기가 공허하지 않다 — 보호 목록에 경로 하나가 더 생기면 ①이 실패해야 한다."""
    shown = set(_routes(access_map["login"]) + _routes(access_map["admin"]))
    grown = set(PROTECTED) | {("POST", "/api/v1/live/new-money-route")}
    assert grown - shown == {("POST", "/api/v1/live/new-money-route")}


def test_copy_has_no_em_dash_or_banned_claims(access_map):
    texts: list[str] = []
    for tier in ("open", "login", "admin"):
        texts.append(access_map[tier]["title"])
        texts.extend(i["label"] for i in access_map[tier]["items"])
    texts.append(access_map["admin"]["why"])
    for t in texts:
        assert t.strip(), "빈 글자"
        assert "—" not in t and "–" not in t, t
        for w in BANNED:
            assert w not in t, t
