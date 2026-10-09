"""BV4 — ★내 증권 계좌 경로 넷★: 목록 · 연결 · 지우기 · 연결 확인.

BV3 가 금고·계좌 표·계좌별 클라이언트를 만들었다. 여기서는 사용자가 그것을 부르는 문을 고정한다.

  ① 목록은 본인 것만, 가려서
  ② 연결 — 소유자는 ★토큰에서만★ · 틀린 입력은 422 · 금고 키가 없으면 503 이고 아무것도 쓰지 않는다
  ③ 지우기 — 남의 계좌는 404(없는 계좌와 같은 답 — 있는지조차 드러내지 않는다; 관리자도 같다)
  ④ 연결 확인 — ★소유 확인이 클라이언트 생성보다 먼저★ · 연습용 모드는 '연결됨' 이라 말하지 않는다 ·
     실패 사유는 사람 말 + 원문(비밀은 가림) · 프로그램 오류를 '연결 실패' 로 꾸미지 않는다
  ⑤ 전수 — 계좌 id 가 든 모든 보호 경로는 남의 계좌에 404

★실제 증권사 확인은 여기서 관측하지 않는다★ — 실키가 없다. 운영 모드는 `KISClient.get_balance` 를 바꿔 끼워
본다(네트워크 0).
"""
from __future__ import annotations

import logging
import os
import tempfile

import pytest
import requests
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

import src.database as dbmod
import src.execution.kis_client as kc
from src.api.protected_routes import PROTECTED, looks_like_money_route
from src.domain.auth_identity import ROLE_ANALYST
from src.domain.kis_failure import KIND_TOKEN

_SECRET = "broker-account-routes-secret-0123456789abcdef"
APP_KEY = "PSappkey-ROUTES-0123456789abcdef"
APP_SECRET = "secret-ROUTES-zyxwvutsrqponmlkjihgfedcba9876543210"
ACCOUNT_NO = "50123456"
SECRETS = (APP_KEY, APP_SECRET, ACCOUNT_NO)
BASE = "/api/v1/broker-accounts"


@pytest.fixture()
def client(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp.name}")
    monkeypatch.setenv("AUTH_SECRET", _SECRET)
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    monkeypatch.setenv("BROKER_CRED_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(dbmod, "DATABASE_URL", f"sqlite:///{tmp.name}", raising=False)
    monkeypatch.setattr(kc, "_kis_singleton", None, raising=False)
    monkeypatch.setattr(kc, "_account_clients", {}, raising=False)
    dbmod.reset_session()
    dbmod.init_db()
    dbmod.create_user("alice", "alice-pw", role=ROLE_ANALYST)
    dbmod.create_user("bob", "bob-pw", role=ROLE_ANALYST)

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
                      json={"username": username, "password": password}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def _alice(client):
    return _auth(client, "alice", "alice-pw")


def _bob(client):
    return _auth(client, "bob", "bob-pw")


def _admin(client):
    return _auth(client, "admin", "frm123!")


def _body(**kw):
    return {**dict(label="내 모의 계좌", app_key=APP_KEY, app_secret=APP_SECRET,
                   account_no=ACCOUNT_NO, is_paper=True), **kw}


def _connect(client, headers, **kw) -> dict:
    res = client.post(BASE, json=_body(**kw), headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


def _rows() -> list[tuple[str, str]]:
    with dbmod.session_scope() as s:
        return [(r.account_id, r.owner_username) for r in s.query(dbmod.BrokerAccount).all()]


def _no_secret(text: str) -> None:
    for secret in SECRETS:
        assert secret not in text, f"{secret} 가 보인다"


# ── ① 목록 ────────────────────────────────────────────────────────────────

def test_the_owner_lists_their_account_masked(client):
    acc = _connect(client, _alice(client))
    res = client.get(BASE, headers=_alice(client))
    assert res.status_code == 200
    assert [a["account_id"] for a in res.json()["accounts"]] == [acc["account_id"]]
    assert res.json()["accounts"][0]["account_no_masked"] == "****" + ACCOUNT_NO[-4:]
    _no_secret(res.text)


def test_another_user_lists_nothing(client):
    """★짝★ — bob 은 alice 계좌를 보지 못한다."""
    _connect(client, _alice(client))
    res = client.get(BASE, headers=_bob(client))
    assert res.status_code == 200 and res.json()["accounts"] == []


# ── ② 연결 ────────────────────────────────────────────────────────────────

def test_connecting_returns_the_masked_row_and_hides_the_secrets(client):
    res = client.post(BASE, json=_body(), headers=_alice(client))
    assert res.status_code == 201
    assert res.json()["account_id"].startswith("ba_")
    _no_secret(res.text)


def test_the_owner_comes_from_the_token_not_the_body(client):
    acc = _connect(client, _alice(client), owner="bob", owner_username="bob", username="bob")
    assert _rows() == [(acc["account_id"], "alice")]


def test_bad_input_is_422_with_a_reason_and_nothing_is_stored(client):
    res = client.post(BASE, json=_body(account_no="5012345"), headers=_alice(client))
    assert res.status_code == 422
    assert "8자리" in res.json()["detail"]
    assert _rows() == []


def test_a_string_is_not_a_paper_or_real_choice(client):
    res = client.post(BASE, json=_body(is_paper="false"), headers=_alice(client))
    assert res.status_code == 422
    assert _rows() == []


def test_the_paper_or_real_choice_is_required(client):
    body = _body()
    del body["is_paper"]
    res = client.post(BASE, json=body, headers=_alice(client))
    assert res.status_code == 422
    assert _rows() == []


def test_without_a_vault_key_connecting_is_503_and_nothing_is_stored(client, monkeypatch):
    monkeypatch.delenv("BROKER_CRED_KEY", raising=False)
    res = client.post(BASE, json=_body(), headers=_alice(client))
    assert res.status_code == 503
    assert "BROKER_CRED_KEY" in res.json()["detail"]
    assert _rows() == []
    _no_secret(res.text)


def test_connecting_writes_no_secret_to_the_logs(client, caplog):
    caplog.set_level(logging.DEBUG)
    acc = _connect(client, _alice(client))
    client.post(f"{BASE}/{acc['account_id']}/check", headers=_alice(client))
    assert caplog.records, "로그를 하나도 잡지 못했다 — 검사가 공허하다"
    _no_secret("\n".join(r.getMessage() for r in caplog.records))


# ── ③ 지우기 ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("who", ["bob", "admin"])
def test_someone_else_cannot_delete_the_account(client, who):
    acc = _connect(client, _alice(client))
    headers = _bob(client) if who == "bob" else _admin(client)
    res = client.delete(f"{BASE}/{acc['account_id']}", headers=headers)
    assert res.status_code == 404
    assert len(_rows()) == 1


def test_the_owner_deletes_the_account(client):
    """★짝★ — 언제나 404 인 구현을 배제한다."""
    acc = _connect(client, _alice(client))
    res = client.delete(f"{BASE}/{acc['account_id']}", headers=_alice(client))
    assert res.status_code == 200 and res.json() == {"deleted": acc["account_id"]}
    assert _rows() == []


def test_deleting_an_unknown_account_is_404(client):
    res = client.delete(f"{BASE}/ba_0000000000000000", headers=_alice(client))
    assert res.status_code == 404


# ── ④ 연결 확인 ───────────────────────────────────────────────────────────

def _check(client, account_id, headers):
    return client.post(f"{BASE}/{account_id}/check", headers=headers)


def test_in_practice_mode_the_check_does_not_claim_a_connection(client):
    acc = _connect(client, _alice(client))
    res = _check(client, acc["account_id"], _alice(client))
    assert res.status_code == 200
    body = res.json()
    assert body["state"] == "practice"
    assert body["state"] != "ok"
    assert "연습용" in body["reason"] and "몰라요" in body["reason"]


def test_checking_someone_elses_account_is_404_and_builds_no_client(client):
    """★소유 확인이 클라이언트 생성보다 먼저★ — 남의 자격을 풀지조차 않는다."""
    acc = _connect(client, _alice(client))
    res = _check(client, acc["account_id"], _bob(client))
    assert res.status_code == 404
    assert kc._account_clients == {}


def test_checking_ones_own_account_builds_its_client(client):
    """★짝★ — 위 검사가 공허하지 않다(주인이 부르면 클라이언트가 생긴다)."""
    acc = _connect(client, _alice(client))
    _check(client, acc["account_id"], _alice(client))
    assert acc["account_id"] in kc._account_clients


def _production(monkeypatch, behaviour):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    monkeypatch.setattr(kc.KISClient, "get_balance", behaviour)


def test_in_production_a_successful_balance_query_is_ok(client, monkeypatch):
    acc = _connect(client, _alice(client))
    _production(monkeypatch, lambda self: {"cash_krw": 0, "positions": []})
    res = _check(client, acc["account_id"], _alice(client))
    assert res.status_code == 200 and res.json()["state"] == "ok"
    _no_secret(res.text)


def test_in_production_a_refused_token_is_a_failure_with_a_human_reason(client, monkeypatch):
    acc = _connect(client, _alice(client))

    def refuse(self):
        raise kc.KISCallError(f"토큰 발급 실패: 403 appkey={APP_KEY} secret={APP_SECRET} cano={ACCOUNT_NO}",
                              kind=KIND_TOKEN, status=403)

    _production(monkeypatch, refuse)
    res = _check(client, acc["account_id"], _alice(client))
    assert res.status_code == 200
    body = res.json()
    assert body["state"] == "failed"
    assert "앱 키" in body["reason"]
    assert "토큰 발급 실패" in body["detail"], "원문을 지웠다"
    _no_secret(res.text)


def test_in_production_an_unreachable_broker_is_a_failure(client, monkeypatch):
    acc = _connect(client, _alice(client))

    def down(self):
        raise requests.ConnectionError("connection refused")

    _production(monkeypatch, down)
    body = _check(client, acc["account_id"], _alice(client)).json()
    assert body["state"] == "failed"
    assert "닿지" in body["reason"]


def test_a_programming_error_is_not_dressed_up_as_a_connection_failure(client, monkeypatch):
    """★짝★ — 아무 예외나 '연결 실패' 로 삼키는 구현을 배제한다."""
    acc = _connect(client, _alice(client))

    def bug(self):
        raise ValueError("프로그램 오류")

    _production(monkeypatch, bug)
    res = _check(client, acc["account_id"], _alice(client))
    assert res.status_code == 500, "프로그램 오류를 200 '연결 실패' 로 바꿨다"
    assert "failed" not in res.text


def test_a_changed_vault_key_makes_the_check_503(client, monkeypatch):
    acc = _connect(client, _alice(client))
    monkeypatch.setenv("BROKER_CRED_KEY", Fernet.generate_key().decode())
    res = _check(client, acc["account_id"], _alice(client))
    assert res.status_code == 503
    _no_secret(res.text)


# ── ⑤ 전수 ────────────────────────────────────────────────────────────────

_ACCOUNT_ROUTES = sorted(k for k in PROTECTED if "{account_id}" in k[1])


def test_there_are_account_routes_to_check():
    """★짝★ — 목록이 비면 아래 전수 검사가 언제나 통과한다."""
    assert len(_ACCOUNT_ROUTES) >= 2


@pytest.mark.parametrize(("method", "path"), _ACCOUNT_ROUTES)
def test_every_account_route_refuses_someone_elses_account(client, method, path):
    acc = _connect(client, _alice(client))
    url = path.replace("{account_id}", acc["account_id"])
    res = client.request(method, url, json={}, headers=_bob(client))
    assert res.status_code == 404, f"{method} {path} → {res.status_code}"
    assert len(_rows()) == 1


@pytest.mark.parametrize(("method", "path"), _ACCOUNT_ROUTES)
def test_every_account_route_answers_its_owner(client, method, path):
    """★짝★ — 언제나 404 인 구현을 배제한다."""
    acc = _connect(client, _alice(client))
    url = path.replace("{account_id}", acc["account_id"])
    res = client.request(method, url, json={}, headers=_alice(client))
    assert res.status_code == 200, f"{method} {path} → {res.status_code}"


def test_the_detector_sees_the_broker_account_routes():
    for path in [BASE, f"{BASE}/{{account_id}}", f"{BASE}/{{account_id}}/check"]:
        assert looks_like_money_route(path), path
