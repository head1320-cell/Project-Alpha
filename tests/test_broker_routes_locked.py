"""BV0a — ★계좌에 닿는데 열려 있던 경로를 잠근다★ (BV0 읽기 전용 감사, 2026-10-08).

감사가 찾은 것:
  · `GET /api/v1/trading/status` 가 로그인 없이 브로커의 예수금·보유 종목 전체를 줬다. 면제 사유
    ("프로세스 로컬 설정값 — 계좌 자료가 아니다")는 이 경로가 아니라 `/trading-status` 를 설명한 글이었다.
  · `stage13_extensions.py`(`/api/v1/live`)의 대조·알림·게이트웨이·종합 상태 10 경로에 인증이 없었다 —
    `POST /reconcile/sync` 는 차이가 크면 킬스위치를 당겨 미체결 주문을 실제로 취소한다.
  · 전수 검사(`test_protected_routes` ③)가 못 본 이유: 돈 경로 검출 조각에 이 경로들이 걸리지 않았다.

여기서 고정하는 것:
  ① 감사가 찾은 11 경로의 요구 수준(표) — 되돌리면 빨갛다(일반 전수 검사는 "레지스트리와 실제가 같은가" 만 보므로
     둘을 함께 되돌리는 변이를 잡지 못한다).
  ② 동작: 토큰 없는 계좌 조회는 401 이고 계좌 자료가 본문에 없다 · 짝: 로그인하면 자료가 온다.
  ③ 검출기가 실거래 표면(`/api/v1/live/`) 전체를 본다 · 짝: 연구 경로는 보지 않는다.
"""
from __future__ import annotations

import os
import tempfile

import pytest
from fastapi.testclient import TestClient

import src.database as dbmod
from src.api.protected_routes import (
    PROTECTED,
    REQUIRE_ADMIN,
    REQUIRE_LOGIN,
    looks_like_money_route,
)
from src.domain.auth_identity import ROLE_ANALYST

_SECRET = "broker-routes-test-secret-0123456789abcdef"

#: ★감사가 찾은 것 그대로★ — (METHOD, 경로) → 요구 수준.
AUDIT_2026_10_08: dict[tuple[str, str], str] = {
    ("GET", "/api/v1/trading/status"): REQUIRE_LOGIN,
    ("POST", "/api/v1/live/reconcile/sync"): REQUIRE_ADMIN,
    ("POST", "/api/v1/live/reconcile/periodic/start"): REQUIRE_ADMIN,
    ("POST", "/api/v1/live/reconcile/periodic/stop"): REQUIRE_ADMIN,
    ("GET", "/api/v1/live/reconcile/status"): REQUIRE_LOGIN,
    ("GET", "/api/v1/live/reconcile/history"): REQUIRE_LOGIN,
    ("POST", "/api/v1/live/notifier/test"): REQUIRE_ADMIN,
    ("GET", "/api/v1/live/notifier/stats"): REQUIRE_LOGIN,
    ("GET", "/api/v1/live/gateway/stats"): REQUIRE_LOGIN,
    ("GET", "/api/v1/live/health"): REQUIRE_LOGIN,
}


@pytest.fixture()
def client(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp.name}")
    monkeypatch.setenv("AUTH_SECRET", _SECRET)
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    monkeypatch.setattr(dbmod, "DATABASE_URL", f"sqlite:///{tmp.name}", raising=False)
    dbmod.reset_session()
    dbmod.init_db()
    dbmod.create_user("alice", "alice-pw", role=ROLE_ANALYST)

    from src.app_factory import create_app
    with TestClient(create_app()) as c:
        yield c

    dbmod.reset_session()
    try:
        os.unlink(tmp.name)
    except OSError:
        pass


def _auth(client, username: str, password: str) -> dict[str, str]:
    tok = client.post("/api/v1/auth/login",
                      json={"username": username, "password": password}
                      ).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


# ── ① 감사가 찾은 경로는 그 수준으로 잠겨 있다 ─────────────────────────────

@pytest.mark.parametrize(("key", "level"), sorted(AUDIT_2026_10_08.items()))
def test_routes_found_by_the_audit_are_registered_at_their_level(key, level):
    assert key in PROTECTED, f"{key} 가 보호 목록에 없다"
    assert PROTECTED[key][0] == level, f"{key} 의 요구 수준이 {PROTECTED[key][0]} 이다(기대 {level})"


def test_the_audit_table_is_not_empty():
    """★짝★ — 표가 비면 ①은 언제나 통과한다."""
    assert len(AUDIT_2026_10_08) == 10
    assert set(AUDIT_2026_10_08.values()) == {REQUIRE_ADMIN, REQUIRE_LOGIN}


# ── ② 동작 — 토큰 없으면 계좌 자료가 나가지 않는다, 그리고 ★짝★ ─────────────

def test_account_status_without_a_token_is_401_and_carries_no_account_data(client):
    res = client.get("/api/v1/trading/status")
    assert res.status_code == 401
    body = res.text
    assert "cash_krw" not in body and "positions" not in body


def test_account_status_with_a_login_returns_the_account(client):
    """★짝★ — 항상-거부 구현을 배제한다. 로그인한 분석가는 지금처럼 자료를 받는다."""
    res = client.get("/api/v1/trading/status", headers=_auth(client, "alice", "alice-pw"))
    assert res.status_code == 200
    assert "cash_krw" in res.json()


def test_broker_sync_without_a_token_does_not_reach_the_broker(client, monkeypatch):
    """인증 문이 대조기보다 먼저 선다 — 토큰 없는 요청은 대조기를 한 번도 부르지 않는다."""
    import src.api.stage13_extensions as ext

    calls: list[str] = []
    monkeypatch.setattr(ext, "get_production_modules", lambda: calls.append("modules") or {})
    res = client.post("/api/v1/live/reconcile/sync", json={})
    assert res.status_code == 401
    assert calls == []


# ── ③ 검출기가 실거래 표면 전체를 본다 ─────────────────────────────────────

def test_the_detector_sees_every_live_trading_route():
    from src.app_factory import create_app

    live = sorted({
        getattr(r, "path", "") for r in create_app().routes
        if getattr(r, "path", "").startswith("/api/v1/live/")
    })
    assert len(live) >= 20, f"실거래 경로가 너무 적다 — 앱 구성이 바뀌었나: {live}"
    unseen = [p for p in live if not looks_like_money_route(p)]
    assert not unseen, f"검출기가 보지 못하는 실거래 경로: {unseen}"


def test_the_detector_does_not_flag_research_routes():
    """★짝★ — 모든 경로를 돈 후보로 보는 검출기를 배제한다."""
    for path in ["/api/v1/macro/regime", "/api/v1/screener/run-advanced", "/health"]:
        assert looks_like_money_route(path) is False, path
