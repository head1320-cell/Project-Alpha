"""BS1 — 계정: 비밀번호 바꾸기 · 관리자 발급 · 옛 토큰 폐기 · 처음 로그인.

★공개 가입은 없다★ — 로그인만 하면 열리는 곳에 실계좌 잔고·주문 이력이 있다. 계정은 관리자가
설정 화면에서 발급하고(`POST /api/v1/auth/users`), 임시 비밀번호는 응답에 **한 번만** 실린다.

각 단언에는 짝을 붙여 항상-허용·항상-거부 구현을 배제한다(CLAUDE.md §5).
"""
from __future__ import annotations

import logging
import os
import tempfile

import pytest
from fastapi.testclient import TestClient

import src.database as dbmod
from src.domain.auth_identity import ROLE_ADMIN, ROLE_ANALYST

_SECRET = "account-security-test-secret-0123456789ab"
_ME = "/api/v1/auth/me"
_PW = "/api/v1/auth/password"
_USERS = "/api/v1/auth/users"
#: 로그인만 요구하는 보호 라우트 하나 — `must_change` 문을 여기서 본다.
_LOGIN_ONLY = ("GET", "/api/v1/live/audit/summary")


def _store_flags() -> dict[str, bool]:
    """`src.data.*` 저장소들의 "표를 이미 만들었다" 깃발(`_inited`).

    ★이 파일은 알파벳 순으로 맨 앞에 돈다★ — 여기서 앱을 띄우면 저장소들이 임시 DB 에 표를 만들고 깃발을 세운다.
    깃발은 프로세스 전역이라, 임시 DB 를 지운 뒤 다른 테스트가 원래 DB 를 쓸 때 표를 다시 만들지 않아
    `backtest_runs` 가 없는 DB 를 보게 됐다(전체 게이트에서 두 테스트가 실패 · 건너뜀 11 → 24 로 찾았다).
    """
    import sys
    return {name: mod._inited for name, mod in list(sys.modules.items())
            if name.startswith("src.") and isinstance(getattr(mod, "_inited", None), bool)}


@pytest.fixture()
def client(monkeypatch):
    import sys
    flags_before = _store_flags()
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp.name}")
    monkeypatch.setenv("AUTH_SECRET", _SECRET)
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.setattr(dbmod, "DATABASE_URL", f"sqlite:///{tmp.name}", raising=False)
    dbmod.reset_session()
    dbmod.init_db()
    dbmod.create_user("alice", "alice-pw-0001", role=ROLE_ANALYST)

    from src.api import auth_routes
    auth_routes._reset_password_failures()
    from src.app_factory import create_app
    with TestClient(create_app()) as c:
        yield c

    dbmod.reset_session()
    try:
        os.unlink(tmp.name)
    except OSError:
        pass
    # 임시 DB 에서 세운 깃발을 되돌린다 — 이 테스트 중에 처음 불린 저장소는 "아직 안 만듦" 으로.
    for name, now in _store_flags().items():
        sys.modules[name]._inited = flags_before.get(name, False) if now else now


def _login(client, username: str, password: str):
    return client.post("/api/v1/auth/login", json={"username": username, "password": password})


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _tok(client, username: str = "alice", password: str = "alice-pw-0001") -> str:
    r = _login(client, username, password)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _change(client, token: str, current: str, new: str):
    return client.post(_PW, json={"current_password": current, "new_password": new}, headers=_h(token))


# ── 비밀번호 바꾸기 ──────────────────────────────────────────────────────────

def test_changing_the_password_retires_the_old_token_and_hands_back_a_new_one(client):
    old = _tok(client)
    r = _change(client, old, "alice-pw-0001", "new-secret-9876")
    assert r.status_code == 200, r.text
    new = r.json()["access_token"]
    assert new and new != old
    # ★옛 토큰은 죽는다★ — 12시간을 기다리지 않는다.
    dead = client.get(_ME, headers=_h(old))
    assert dead.status_code == 401
    assert "비밀번호" in dead.json()["detail"]
    # 짝 — 새 토큰은 산다(항상-거부 구현 배제).
    assert client.get(_ME, headers=_h(new)).status_code == 200
    # 새 비밀번호로 로그인되고 옛 비밀번호로는 안 된다.
    assert _login(client, "alice", "new-secret-9876").status_code == 200
    assert _login(client, "alice", "alice-pw-0001").status_code == 401


def test_a_token_that_was_never_retired_keeps_working(client):
    """짝 — 비밀번호를 바꾸지 않으면 토큰이 멀쩡하다(항상-폐기 구현 배제)."""
    t = _tok(client)
    assert client.get(_ME, headers=_h(t)).status_code == 200
    assert client.get(_ME, headers=_h(t)).status_code == 200


def test_a_wrong_current_password_is_refused_with_a_reason(client):
    t = _tok(client)
    r = _change(client, t, "not-my-password", "new-secret-9876")
    assert r.status_code == 400
    assert "지금 비밀번호" in r.json()["detail"]
    # 아무것도 바뀌지 않았다.
    assert _login(client, "alice", "alice-pw-0001").status_code == 200


@pytest.mark.parametrize(("new", "needle"), [
    ("short7!", "8자"),
    ("alice-pw-0001", "지금 비밀번호와"),
    ("alice", "8자"),
    ("frm123!frm", None),
    ("changeme", "알려진"),
    ("x" * 73, "72바이트"),
])
def test_the_new_password_rules_each_say_why(client, new, needle):
    t = _tok(client)
    r = _change(client, t, "alice-pw-0001", new)
    if needle is None:  # 기본값을 품은 것은 규칙 위반이 아니다 — 같을 때만 막는다(짝).
        assert r.status_code == 200, r.text
        return
    assert r.status_code == 400
    assert needle in r.json()["detail"]


def test_a_password_equal_to_the_username_is_refused(client):
    dbmod.create_user("longname1", "longname-pw-01", role=ROLE_ANALYST)
    t = _tok(client, "longname1", "longname-pw-01")
    r = _change(client, t, "longname-pw-01", "longname1")
    assert r.status_code == 400
    assert "아이디" in r.json()["detail"]


def test_five_wrong_current_passwords_pause_the_door(client):
    t = _tok(client)
    for _ in range(5):
        assert _change(client, t, "wrong-wrong", "new-secret-9876").status_code == 400
    r = _change(client, t, "alice-pw-0001", "new-secret-9876")
    assert r.status_code == 429
    assert "분" in r.json()["detail"]


def test_four_wrong_then_right_still_works(client):
    """짝 — 문턱 아래에서는 막지 않는다."""
    t = _tok(client)
    for _ in range(4):
        _change(client, t, "wrong-wrong", "new-secret-9876")
    assert _change(client, t, "alice-pw-0001", "new-secret-9876").status_code == 200


def test_changing_the_password_needs_a_token(client):
    r = client.post(_PW, json={"current_password": "a", "new_password": "b"})
    assert r.status_code == 401


# ── 관리자 발급 ──────────────────────────────────────────────────────────────

def _admin(client) -> str:
    return _tok(client, "admin", "frm123!")


def test_an_admin_issues_an_account_and_sees_the_temporary_password_once(client):
    r = client.post(_USERS, json={"username": "bora", "role": ROLE_ANALYST}, headers=_h(_admin(client)))
    assert r.status_code == 201, r.text
    body = r.json()
    temp = body["temporary_password"]
    assert isinstance(temp, str) and len(temp) >= 12
    assert body["must_change_password"] is True
    # 그 임시 비밀번호로 로그인되고, 바꿀 차례라고 말한다.
    login = _login(client, "bora", temp)
    assert login.status_code == 200
    assert login.json()["must_change_password"] is True
    # ★목록은 비밀번호도 해시도 싣지 않는다★.
    listed = client.get(_USERS, headers=_h(_admin(client)))
    assert listed.status_code == 200
    rows = listed.json()["users"]
    bora = next(u for u in rows if u["username"] == "bora")
    assert bora["role"] == ROLE_ANALYST and bora["must_change_password"] is True
    flat = str(listed.json())
    assert temp not in flat and "$2b$" not in flat and "password_hash" not in flat


def test_a_regular_login_does_not_ask_for_a_change(client):
    """짝 — 스스로 만든 계정·바꾼 계정은 `must_change_password=False`."""
    assert _login(client, "alice", "alice-pw-0001").json()["must_change_password"] is False


def test_an_analyst_cannot_issue_accounts(client):
    r = client.post(_USERS, json={"username": "eve", "role": ROLE_ADMIN}, headers=_h(_tok(client)))
    assert r.status_code == 403
    assert _login(client, "eve", "anything-at-all").status_code == 401
    assert client.get(_USERS, headers=_h(_tok(client))).status_code == 403


def test_issuing_needs_a_token(client):
    assert client.post(_USERS, json={"username": "x1", "role": ROLE_ANALYST}).status_code == 401
    assert client.get(_USERS).status_code == 401


def test_a_taken_name_is_refused(client):
    r = client.post(_USERS, json={"username": "alice", "role": ROLE_ANALYST}, headers=_h(_admin(client)))
    assert r.status_code == 409
    assert r.json()["detail"]
    # 기존 계정은 그대로다.
    assert _login(client, "alice", "alice-pw-0001").status_code == 200


@pytest.mark.parametrize("body", [
    {"username": "", "role": ROLE_ANALYST},
    {"username": "has space", "role": ROLE_ANALYST},
    {"username": "x" * 65, "role": ROLE_ANALYST},
    {"username": "ok_name", "role": "superuser"},
])
def test_bad_names_and_roles_outside_the_vocabulary_are_refused(client, body):
    r = client.post(_USERS, json=body, headers=_h(_admin(client)))
    assert r.status_code == 422


def test_a_reset_retires_that_persons_tokens_and_asks_for_a_change(client):
    victim = _tok(client)
    r = client.post(f"{_USERS}/alice/reset-password", headers=_h(_admin(client)))
    assert r.status_code == 200, r.text
    temp = r.json()["temporary_password"]
    assert client.get(_ME, headers=_h(victim)).status_code == 401
    assert _login(client, "alice", "alice-pw-0001").status_code == 401
    login = _login(client, "alice", temp)
    assert login.status_code == 200 and login.json()["must_change_password"] is True


def test_resetting_an_unknown_account_says_so(client):
    r = client.post(f"{_USERS}/nobody/reset-password", headers=_h(_admin(client)))
    assert r.status_code == 404
    assert r.json()["detail"]


# ── 처음 로그인 — 바꾸기 전에는 보호 라우트가 열리지 않는다 ─────────────────

def test_an_issued_account_must_change_before_protected_routes_open(client):
    temp = client.post(_USERS, json={"username": "bora", "role": ROLE_ANALYST},
                       headers=_h(_admin(client))).json()["temporary_password"]
    t = _tok(client, "bora", temp)
    m, p = _LOGIN_ONLY
    blocked = client.request(m, p, headers=_h(t))
    assert blocked.status_code == 403
    assert "비밀번호를 먼저" in blocked.json()["detail"]
    # 자기 확인은 열려 있다 — 화면이 "바꿀 차례" 를 알아야 한다.
    me = client.get(_ME, headers=_h(t))
    assert me.status_code == 200 and me.json()["must_change_password"] is True
    # 바꾼 뒤에는 열린다(짝).
    new = _change(client, t, temp, "bora-new-secret-1").json()["access_token"]
    opened = client.request(m, p, headers=_h(new))
    assert opened.status_code not in (401, 403), opened.text
    assert client.get(_ME, headers=_h(new)).json()["must_change_password"] is False


def test_a_token_for_an_account_that_no_longer_exists_is_refused(client):
    t = _tok(client)
    with dbmod.session_scope() as s:
        s.query(dbmod.User).filter_by(username="alice").delete()
    r = client.get(_ME, headers=_h(t))
    assert r.status_code == 401
    assert "계정" in r.json()["detail"]


# ── 공개 가입은 없다 ─────────────────────────────────────────────────────────

def test_there_is_no_public_sign_up_route(client):
    paths = {getattr(r, "path", "") for r in client.app.routes}
    assert not any(k in p for p in paths for k in ("signup", "sign-up", "register"))
    assert client.post("/api/v1/auth/signup", json={"username": "z", "password": "zzzzzzzz"}).status_code in (404, 405)


# ── admin 기본 비밀번호 상태는 DB 가 말한다 ──────────────────────────────────

def test_admin_password_state_follows_the_account_not_the_environment(client, monkeypatch):
    """★환경변수를 설정해도 admin 이 아직 기본값을 받으면 'default'★ — 환경변수는 처음 만들 때만 쓰인다."""
    monkeypatch.setenv("ADMIN_PASSWORD", "a-real-operator-password")
    body = client.get(_ME, headers=_h(_admin(client))).json()
    assert body["admin_password_state"] == "default"
    assert "기본" in (body["admin_password_reason"] or "")


def test_admin_password_state_turns_configured_once_the_admin_changes_it(client):
    """짝 — 바꾸고 나면 'configured'(항상-default 구현 배제)."""
    new = _change(client, _admin(client), "frm123!", "operator-chosen-1").json()["access_token"]
    body = client.get(_ME, headers=_h(new)).json()
    assert body["admin_password_state"] == "configured"
    assert body["admin_password_reason"] is None


# ── 알려진 비밀번호로 계정을 만들지 않는다 ───────────────────────────────────

def test_side_door_accounts_cannot_log_in_with_a_known_password(client):
    dbmod.update_user_portfolio("ghost1", "005930", 1_000_000)
    dbmod.log_trade("ghost2", "005930", 1, "BUY", "FILLED")
    for name in ("ghost1", "ghost2"):
        assert _login(client, name, "temp").status_code == 401


# ── 로그에 비밀번호가 남지 않는다 ────────────────────────────────────────────

def test_no_password_or_token_reaches_the_log(client, caplog):
    caplog.set_level(logging.DEBUG)
    admin = _admin(client)
    temp = client.post(_USERS, json={"username": "bora", "role": ROLE_ANALYST},
                       headers=_h(admin)).json()["temporary_password"]
    t = _tok(client, "bora", temp)
    new = _change(client, t, temp, "bora-new-secret-1").json()["access_token"]
    temp2 = client.post(f"{_USERS}/bora/reset-password", headers=_h(admin)).json()["temporary_password"]
    _change(client, t, "wrong-wrong", "whatever-12345")
    text = caplog.text
    for secret in (temp, temp2, "bora-new-secret-1", "frm123!", t, new, admin):
        assert secret not in text
