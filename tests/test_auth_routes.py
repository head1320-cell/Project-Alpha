"""AC3 — 로그인 표면의 계약.

★계정 열거를 막는다★ — "없는 사용자" 와 "비밀번호 틀림" 이 구분되면 공격자가
사용자 목록을 만들 수 있다. 두 경우가 **같은 응답**이어야 하고, 그것이 조용한
폴백이 아니라 **의도된 무차별 거부**라는 사실을 이 파일이 적는다.
"""
from __future__ import annotations

import os
import tempfile

import pytest
from fastapi.testclient import TestClient

import src.database as dbmod
from src.domain.auth_identity import (
    ROLE_ADMIN,
    ROLE_ANALYST,
    SECRET_CONFIGURED,
    SECRET_EPHEMERAL,
    SOURCE_TOKEN,
)

_SECRET = "auth-routes-test-secret-0123456789abcdef"


@pytest.fixture()
def client(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp.name}")
    monkeypatch.setenv("AUTH_SECRET", _SECRET)
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


def _login(client, username: str, password: str):
    return client.post("/api/v1/auth/login",
                       json={"username": username, "password": password})


# ── 로그인 ──────────────────────────────────────────────────────────────────

def test_correct_credentials_yield_a_token(client):
    res = _login(client, "alice", "alice-pw")
    assert res.status_code == 200
    body = res.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["role"] == ROLE_ANALYST
    assert body["expires_at"]


def test_the_bootstrapped_admin_can_log_in(client):
    res = _login(client, "admin", "frm123!")
    assert res.status_code == 200
    assert res.json()["role"] == ROLE_ADMIN


def test_a_wrong_password_is_refused(client):
    assert _login(client, "alice", "wrong").status_code == 401


def test_an_unknown_user_is_refused(client):
    assert _login(client, "nobody", "whatever").status_code == 401


def test_the_two_refusals_are_indistinguishable(client):
    """★계정 열거 방지★ — 응답 본문과 상태가 **완전히 같아야** 한다."""
    wrong_pw = _login(client, "alice", "wrong")
    no_user = _login(client, "nobody", "wrong")
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json() == no_user.json()


def test_the_refusal_still_says_something(client):
    """구분하지 않는 것과 ★사유 없이 침묵하는 것★은 다르다(CLAUDE.md §4)."""
    body = _login(client, "alice", "wrong").json()
    assert body.get("detail"), "사유 없는 거절"


def test_an_empty_password_is_refused(client):
    assert _login(client, "alice", "").status_code in (401, 422)


# ── /auth/me ────────────────────────────────────────────────────────────────

def _token(client, username="alice", password="alice-pw") -> str:
    return _login(client, username, password).json()["access_token"]


def test_me_requires_a_token(client):
    assert client.get("/api/v1/auth/me").status_code == 401


def test_me_reports_the_observed_identity(client):
    tok = _token(client)
    res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert res.status_code == 200
    body = res.json()
    assert body["principal"]["username"] == "alice"
    assert body["principal"]["role"] == ROLE_ANALYST
    assert body["principal"]["source"] == SOURCE_TOKEN


def test_me_declares_the_secret_state(client):
    tok = _token(client)
    body = client.get("/api/v1/auth/me",
                      headers={"Authorization": f"Bearer {tok}"}).json()
    assert body["secret_state"] == SECRET_CONFIGURED
    assert body["secret_reason"] is None


def test_me_makes_a_degraded_secret_visible(client, monkeypatch):
    """★열화를 숨기지 않는다★ — 비밀키가 없으면 응답이 그렇게 말한다."""
    tok = _token(client)
    monkeypatch.delenv("AUTH_SECRET", raising=False)
    # 토큰은 옛 비밀키로 서명됐으므로 인증은 실패한다 — 그 자체가 열화의 관측이다.
    res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert res.status_code == 401
    # 상태 자체는 로그인 없이도 읽히는 값이어야 한다.
    from src.api.auth import auth_secret_state
    assert auth_secret_state() == SECRET_EPHEMERAL


def test_me_declares_whether_the_admin_password_is_still_the_default(client):
    """★기본 비밀번호를 몰래 바꾸지 않는 대신 **보이게** 한다★."""
    tok = _token(client, "admin", "frm123!")
    body = client.get("/api/v1/auth/me",
                      headers={"Authorization": f"Bearer {tok}"}).json()
    assert body["admin_password_state"] == "default"


def test_a_configured_admin_password_is_reported_as_configured(client):
    """★짝★ — 항상-default 구현을 배제한다.

    BS1 에서 판정이 **계정**을 보게 됐다: 예전에는 환경변수 `ADMIN_PASSWORD` 만 봤는데, 그 값은 admin 행을
    처음 만들 때만 쓰여서 "설정했지만 계정은 아직 `frm123!` 를 받는" 배포를 configured 라고 말했다(이 테스트가
    바로 그 상황을 configured 로 고정하고 있었다). 이제 admin 이 기본값을 더는 받지 않을 때만 configured 다 —
    환경변수만 설정한 경우는 `test_account_security.py` 가 default 로 본다.
    """
    dbmod.set_password("admin", "a-real-operator-password", must_change=False)
    tok = _token(client, "admin", "a-real-operator-password")
    body = client.get("/api/v1/auth/me",
                      headers={"Authorization": f"Bearer {tok}"}).json()
    assert body["admin_password_state"] == "configured"


# ── 권한 상승 시도 ──────────────────────────────────────────────────────────

def test_a_role_in_the_request_body_does_not_grant_it(client):
    """★본문으로 역할을 올릴 수 없다★ — 역할은 DB 에서 읽고 토큰이 나른다."""
    res = client.post("/api/v1/auth/login",
                      json={"username": "alice", "password": "alice-pw",
                            "role": ROLE_ADMIN})
    assert res.status_code == 200
    assert res.json()["role"] == ROLE_ANALYST
