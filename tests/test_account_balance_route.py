"""BV9a — ★내 계좌 잔고★ `GET /api/v1/broker-accounts/{account_id}/balance` (읽기 전용).

"내 계좌" 화면(BV9b)이 쓴다. 지키는 것:

  ① 연습용(mock)이면 그 계좌의 연습용 클라이언트 값 + `practice: true` — 응답이 자기 출처를 말한다
  ② ★증권사 원문(`raw`)·종목 이름·앱 키·시크릿·전체 계좌번호를 싣지 않는다★ — 가린 칸만
  ③ 빠진 칸은 `None` — 0 으로 메우지 않는다(미상 ≠ 0)
  ④ 운영에서 증권사·네트워크 실패는 `/check` 와 같은 어휘(`state:"failed"` + 사람 말 + 가린 원문),
     프로그램 오류는 잡지 않는다(500) · 금고 키가 바뀌면 503
  ⑤ 남의 계좌는 404 — `tests/test_account_orders_routes.py` 의 전수 훑기가 이 경로도 잡는다(아래에서 확인)

★실제 증권사 잔고는 여기서 관측하지 않는다★ — 실키가 없다. 운영 모드는 `KISClient.get_balance` 를 바꿔 끼운다(네트워크 0).
"""
from __future__ import annotations

import os
import tempfile

import pytest
import requests
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

import src.database as dbmod
import src.execution.kis_client as kc
from src.api.protected_routes import PROTECTED, REQUIRE_LOGIN
from src.domain.auth_identity import ROLE_ANALYST
from src.domain.kis_failure import KIND_TOKEN

_SECRET = "account-balance-route-secret-0123456789ab"
BASE = "/api/v1/broker-accounts"
APP_KEY = "PSkey-0123456789abcdef"
APP_SECRET = "secret-0123456789abcdefghijklmnop"
ACCOUNT_NO = "50123456"
_SIG = {"strategy_id": 1, "ticker": "005930", "side": "BUY", "quantity": 3,
        "price": 71000.0, "order_type": "LIMIT"}


@pytest.fixture()
def client(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp.name}")
    monkeypatch.setenv("AUTH_SECRET", _SECRET)
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    monkeypatch.setenv("BROKER_CRED_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(dbmod, "DATABASE_URL", f"sqlite:///{tmp.name}", raising=False)
    import src.data.backtest_runs as br
    monkeypatch.setattr(br, "_inited", False)   # 임시 DB 에서 만든 표 메모가 뒤 테스트로 새지 않게
    monkeypatch.setattr(kc, "_kis_singleton", None, raising=False)
    monkeypatch.setattr(kc, "_account_clients", {}, raising=False)
    import src.api.stage13_routes as stage13
    import src.execution.account_executors as ae
    monkeypatch.setattr(stage13, "_EXECUTOR", None, raising=False)
    monkeypatch.setattr(ae, "_executors", {}, raising=False)
    dbmod.reset_session()
    dbmod.init_db()
    dbmod.create_user("alice", "alice-pw", role=ROLE_ANALYST)
    dbmod.create_user("bob", "bob-pw", role=ROLE_ANALYST)

    from src.app_factory import create_app
    with TestClient(create_app()) as c:
        c.post("/api/v1/live/init-schema", headers=_auth(c, "admin", "frm123!"))
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


def _alice(c):
    return _auth(c, "alice", "alice-pw")


def _connect(client, *, is_paper=True) -> str:
    res = client.post(BASE, json=dict(label="내 계좌", app_key=APP_KEY, app_secret=APP_SECRET,
                                      account_no=ACCOUNT_NO, is_paper=is_paper), headers=_alice(client))
    assert res.status_code == 201, res.text
    return res.json()["account_id"]


def _balance(client, acc):
    return client.get(f"{BASE}/{acc}/balance", headers=_alice(client))


def _no_secret(text: str) -> None:
    for secret in (APP_KEY, APP_SECRET, ACCOUNT_NO):
        assert secret not in text, f"{secret} 가 보인다"


def _production(monkeypatch, behaviour):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    monkeypatch.setattr(kc.KISClient, "get_balance", behaviour)


# ── 등록 ──────────────────────────────────────────────────────────────────

def test_the_balance_route_is_login_protected():
    assert PROTECTED[("GET", f"{BASE}/{{account_id}}/balance")][0] == REQUIRE_LOGIN


def test_the_ownership_sweep_covers_the_balance_route():
    """남의 계좌 404 는 BV6 의 전수 훑기가 맡는다 — 그 목록에 이 경로가 있어야 한다(빠지면 훑기가 공허)."""
    from tests.test_account_orders_routes import _ACCOUNT_ROUTES
    assert ("GET", f"{BASE}/{{account_id}}/balance") in _ACCOUNT_ROUTES


# ── ① 연습용 ──────────────────────────────────────────────────────────────

def test_practice_balance_is_the_accounts_own_practice_client(client):
    acc = _connect(client)
    res = _balance(client, acc)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["state"] == "ok"
    assert body["practice"] is True, "연습용 잔고인데 그렇다고 말하지 않았다"
    assert body["account_id"] == acc
    mock = kc.get_kis_client(account_id=acc)
    assert body["cash_krw"] == mock.cash
    assert body["evaluated_total"] == mock.get_balance()["evaluated_total"]
    assert body["positions"] == []
    assert body["as_of"]


def test_a_filled_practice_order_shows_up_as_a_position(client):
    """★짝★ — 늘 빈 보유를 돌려주는 구현을 배제한다."""
    acc = _connect(client)
    assert client.post(f"{BASE}/{acc}/mode", json={"mode": "PAPER"}, headers=_alice(client)).status_code == 200
    assert client.post(f"{BASE}/{acc}/orders", json=_SIG, headers=_alice(client)).json()["status"] == "SUBMITTED"
    pos = _balance(client, acc).json()["positions"]
    assert [(p["ticker"], p["quantity"]) for p in pos] == [("005930", 3)]
    assert set(pos[0]) == {"ticker", "quantity", "avg_price", "current_price", "eval_amount", "pnl_pct"}


def test_the_balance_carries_no_raw_names_or_secrets(client):
    acc = _connect(client)
    res = _balance(client, acc)
    body = res.json()
    assert "raw" not in body, "증권사 원문을 넘겼다"
    assert all("name" not in p for p in body["positions"])
    _no_secret(res.text)


# ── ③ 빠진 칸 = None ──────────────────────────────────────────────────────

def test_missing_balance_fields_stay_unknown(client, monkeypatch):
    acc = _connect(client)
    _production(monkeypatch, lambda self: {"positions": [{"ticker": "005930"}]})
    body = _balance(client, acc).json()
    assert body["state"] == "ok"
    assert body["cash_krw"] is None and body["evaluated_total"] is None, "모르는 잔고를 0 으로 메웠다"
    assert body["positions"][0]["quantity"] is None and body["positions"][0]["pnl_pct"] is None


def test_present_balance_fields_are_passed_through(client, monkeypatch):
    """★짝★ — 언제나 None 인 구현을 배제한다."""
    acc = _connect(client)
    _production(monkeypatch, lambda self: {"cash_krw": 1234, "evaluated_total": 5678, "positions": [
        {"ticker": "000660", "name": "SK하이닉스", "quantity": 2, "avg_price": 120000, "current_price": 130000,
         "eval_amount": 260000, "pnl_pct": 8.33}], "raw": {"output2": [{"cano": ACCOUNT_NO}]}})
    res = _balance(client, acc)
    body = res.json()
    assert body["practice"] is False
    assert (body["cash_krw"], body["evaluated_total"]) == (1234, 5678)
    assert body["positions"] == [{"ticker": "000660", "quantity": 2, "avg_price": 120000, "current_price": 130000,
                                  "eval_amount": 260000, "pnl_pct": 8.33}]
    _no_secret(res.text)


# ── ④ 운영 실패 ───────────────────────────────────────────────────────────

def test_a_refused_token_is_a_failure_with_a_human_reason(client, monkeypatch):
    acc = _connect(client)

    def refuse(self):
        raise kc.KISCallError(f"토큰 발급 실패: 403 appkey={APP_KEY} secret={APP_SECRET} cano={ACCOUNT_NO}",
                              kind=KIND_TOKEN, status=403)

    _production(monkeypatch, refuse)
    res = _balance(client, acc)
    assert res.status_code == 200
    body = res.json()
    assert body["state"] == "failed"
    assert "앱 키" in body["reason"]
    assert "토큰 발급 실패" in body["detail"], "원문을 지웠다"
    assert "cash_krw" not in body, "실패한 잔고에 숫자 칸을 실었다"
    _no_secret(res.text)


def test_an_unreachable_broker_is_a_failure(client, monkeypatch):
    acc = _connect(client)

    def down(self):
        raise requests.ConnectionError("connection refused")

    _production(monkeypatch, down)
    body = _balance(client, acc).json()
    assert body["state"] == "failed"
    assert "닿지" in body["reason"]


def test_a_programming_error_is_not_dressed_up_as_a_broker_failure(client, monkeypatch):
    """★짝★ — 아무 예외나 '실패' 로 삼키는 구현을 배제한다."""
    acc = _connect(client)

    def bug(self):
        raise ValueError("프로그램 오류")

    _production(monkeypatch, bug)
    res = _balance(client, acc)
    assert res.status_code == 500
    assert "failed" not in res.text


def test_a_changed_vault_key_makes_the_balance_503(client, monkeypatch):
    acc = _connect(client)
    monkeypatch.setenv("BROKER_CRED_KEY", Fernet.generate_key().decode())
    res = _balance(client, acc)
    assert res.status_code == 503
    _no_secret(res.text)


def test_someone_elses_balance_is_404_and_builds_no_client(client):
    acc = _connect(client)
    res = client.get(f"{BASE}/{acc}/balance", headers=_auth(client, "bob", "bob-pw"))
    assert res.status_code == 404
    assert acc not in kc._account_clients, "남의 계좌 자격으로 클라이언트를 만들었다"
