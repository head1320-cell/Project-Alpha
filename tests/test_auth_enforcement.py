"""AC4 — ★로드맵의 완료 판정을 직접 고정한다★.

> 인증 없는 요청이 보호 라우트에서 `401` 을 받고, 남의 `username` 으로
> `/trade-history/{username}` 을 불렀을 때 `403` 이며, 그 둘을 고정하는 테스트가 있다.

401 과 403 을 **가른다** — 전자는 "누구인지 모른다", 후자는 "누구인지 알지만 안 된다".
각 단언에는 짝을 붙여 항상-거부·항상-허용 구현을 배제한다.
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
    REQUIRE_SELF_OR_ADMIN,
)
from src.domain.auth_identity import ROLE_ADMIN, ROLE_ANALYST

_SECRET = "enforcement-test-secret-0123456789abcdef"

#: 경로 파라미터를 가진 라우트에 넣을 구체값.
_PATH_FILLERS = {"{client_order_id}": "COID-TEST-1", "{username}": "alice",
                 "{account_id}": "ba_0000000000000000"}


def _concrete(path: str) -> str:
    for token, value in _PATH_FILLERS.items():
        path = path.replace(token, value)
    return path


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
    dbmod.create_user("bob", "bob-pw", role=ROLE_ANALYST)

    from src.app_factory import create_app
    with TestClient(create_app()) as c:
        yield c

    # BV0a — 관리자 통과 테스트는 `POST /live/reconcile/periodic/start` 를 실제로 부른다.
    # 자동 대조 스레드를 다음 테스트로 남기지 않는다.
    from src.api import stage13_extensions as ext
    reconciler = ext._PRODUCTION_MODULES.get("reconciler")
    if reconciler is not None:
        reconciler.stop_periodic_sync()

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


def _call(client, method: str, path: str, **kw):
    return client.request(method, _concrete(path), json={}, **kw)


# ── ① 완료 판정 — 토큰 없으면 401 (전수) ──────────────────────────────────

@pytest.mark.parametrize(("method", "path"), sorted(PROTECTED))
def test_an_unauthenticated_request_is_refused_with_401(client, method, path):
    """★보호 라우트 전수★ — 하나라도 열려 있으면 실패한다."""
    res = _call(client, method, path)
    assert res.status_code == 401, f"{method} {path} 가 401 이 아니다({res.status_code})"


@pytest.mark.parametrize(("method", "path"), sorted(PROTECTED))
def test_the_refusal_names_the_scheme_and_a_reason(client, method, path):
    res = _call(client, method, path)
    assert res.headers.get("WWW-Authenticate") == "Bearer"
    assert res.json().get("detail"), "사유 없는 401"


def test_a_malformed_authorization_header_is_also_401(client):
    for header in ["", "Bearer", "Bearer    ", "Basic abc", "abc"]:
        res = client.post("/api/v1/live/mode", json={"mode": "PAPER"},
                          headers={"Authorization": header})
        assert res.status_code == 401, header


# ── ② 완료 판정 — 남의 username 은 403, 그리고 ★짝★ ─────────────────────

def test_reading_someone_elses_trade_history_is_403(client):
    res = client.get("/trade-history/bob", headers=_auth(client, "alice", "alice-pw"))
    assert res.status_code == 403


def test_reading_ones_own_trade_history_is_allowed(client):
    """★짝★ — 항상-403 구현을 배제한다."""
    res = client.get("/trade-history/alice", headers=_auth(client, "alice", "alice-pw"))
    assert res.status_code == 200


def test_an_admin_may_read_someone_elses_trade_history(client):
    """★짝★ — 항상-403 을 배제하고 admin 우회로가 실제로 있는지 본다."""
    res = client.get("/trade-history/bob", headers=_auth(client, "admin", "frm123!"))
    assert res.status_code == 200


# ── ⑤ 역할 부족은 401 이 아니라 403 ───────────────────────────────────────

_ADMIN_ONLY = sorted(k for k, v in PROTECTED.items() if v[0] == REQUIRE_ADMIN)


@pytest.mark.parametrize(("method", "path"), _ADMIN_ONLY)
def test_an_analyst_is_refused_from_admin_routes_with_403(client, method, path):
    """★401 과 403 을 가른다★ — 신원은 확인됐으니 401 이 아니다."""
    res = _call(client, method, path, headers=_auth(client, "alice", "alice-pw"))
    assert res.status_code == 403, f"{method} {path} → {res.status_code}"


@pytest.mark.parametrize(("method", "path"), _ADMIN_ONLY)
def test_an_admin_gets_past_the_gate(client, method, path):
    """★짝★ — 항상-403 구현을 배제한다. 문을 지난 뒤의 결과는 이 테스트의 관심이 아니다."""
    res = _call(client, method, path, headers=_auth(client, "admin", "frm123!"))
    assert res.status_code not in (401, 403), f"{method} {path} → {res.status_code}"


# ── 로그인만 요구하는 표면 ────────────────────────────────────────────────

_LOGIN_ONLY = sorted(k for k, v in PROTECTED.items() if v[0] == REQUIRE_LOGIN)


@pytest.mark.parametrize(("method", "path"), _LOGIN_ONLY)
def test_any_logged_in_role_passes_the_login_only_gate(client, method, path):
    """★짝★ — 로그인 표면을 admin 전용으로 좁히지 않았는지 본다."""
    res = _call(client, method, path, headers=_auth(client, "alice", "alice-pw"))
    assert res.status_code != 403, f"{method} {path} 가 analyst 를 막는다"


# ── ⑲ 과잉 차단 배제 ──────────────────────────────────────────────────────

def test_open_surfaces_still_answer_without_a_token(client):
    """면제한 라우트는 토큰 없이 동작해야 한다 — 전부 잠그는 구현을 배제한다."""
    for path in ["/health", "/api/v1/live/mode", "/api/v1/live/kill-switch/status",
                 "/trading-status"]:
        res = client.get(path)
        assert res.status_code != 401, f"{path} 가 토큰을 요구한다"


def test_a_forged_token_does_not_open_the_admin_gate(client):
    """★다른 비밀키로 만든 admin 토큰은 통하지 않는다★."""
    import datetime as dt

    import jwt
    forged = jwt.encode(
        {"sub": "alice", "role": ROLE_ADMIN,
         "iat": dt.datetime.now(dt.timezone.utc),
         "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)},
        "some-other-secret-0123456789abcdefgh", algorithm="HS256")
    res = client.post("/api/v1/live/mode", json={"mode": "PAPER"},
                      headers={"Authorization": f"Bearer {forged}"})
    assert res.status_code == 401


def test_the_registry_covers_all_three_requirement_kinds():
    """세 수준이 모두 실제로 쓰이는지 — 어휘만 있고 소비자가 없는 상태를 배제한다."""
    levels = {v[0] for v in PROTECTED.values()}
    assert levels == {REQUIRE_ADMIN, REQUIRE_LOGIN, REQUIRE_SELF_OR_ADMIN}
