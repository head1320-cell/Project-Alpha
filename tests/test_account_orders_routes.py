"""BV6b — ★내 계좌로 모의 주문★: 주문 · 주문 목록 · 취소 · 실행 모드 · 비상 정지.

계좌마다 Stage13 실행기 하나(`src/execution/account_executors.py`). 기본은 SHADOW(신호만 기록, 보내지 않음).

  ① SHADOW 기본 — 주문은 기록되고 증권사로 0건 · 짝: PAPER(모의 계좌)면 1건
  ② 모드: SHADOW·PAPER 만 · 실계좌 계좌에 PAPER 는 사유와 함께 거절 · LIVE 는 거절(BV7 관문 뒤)
  ③ 남의 계좌는 모든 경로 404 · 감사 행위자 = 토큰
  ④ 비상 정지 — 내 계좌만 막힘, 해제는 내가 · 기본 청산 방식은 '그대로 둠'(hold)
  ⑤ 계좌를 지우면 실행기도 사라진다 · 실행기 등록부를 비우면(재시작) SHADOW 로 돌아온다
"""
from __future__ import annotations

import os
import tempfile

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

import src.database as dbmod
import src.execution.kis_client as kc
from src.api.protected_routes import PROTECTED
from src.domain.auth_identity import ROLE_ANALYST

_SECRET = "account-orders-routes-secret-0123456789ab"
BASE = "/api/v1/broker-accounts"
_SIG = {"strategy_id": 1, "ticker": "005930", "side": "BUY", "quantity": 1,
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


def _bob(c):
    return _auth(c, "bob", "bob-pw")


def _connect(client, *, is_paper=True) -> str:
    res = client.post(BASE, json=dict(label="내 계좌", app_key="PSkey-0123456789abcdef",
                                      app_secret="secret-0123456789abcdefghijklmnop",
                                      account_no="50123456", is_paper=is_paper), headers=_alice(client))
    assert res.status_code == 201, res.text
    return res.json()["account_id"]


def _mock_orders(account_id: str) -> list:
    return kc.get_kis_client(account_id=account_id).fills


# ── ① SHADOW 기본 · PAPER 면 보낸다 ────────────────────────────────────────

def test_the_default_mode_records_but_sends_nothing(client):
    acc = _connect(client)
    assert client.get(f"{BASE}/{acc}/mode", headers=_alice(client)).json()["mode"] == "SHADOW"
    res = client.post(f"{BASE}/{acc}/orders", json=_SIG, headers=_alice(client))
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "SHADOW_LOGGED"
    assert _mock_orders(acc) == [], "SHADOW 인데 증권사로 보냈다"
    orders = client.get(f"{BASE}/{acc}/orders", headers=_alice(client)).json()["orders"]
    assert [o["client_order_id"] for o in orders] == [res.json()["client_order_id"]]


def test_paper_mode_on_a_paper_account_sends_the_order(client):
    """★짝★ — 언제나 보내지 않는 구현을 배제한다."""
    acc = _connect(client, is_paper=True)
    r = client.post(f"{BASE}/{acc}/mode", json={"mode": "PAPER"}, headers=_alice(client))
    assert r.status_code == 200, r.text
    res = client.post(f"{BASE}/{acc}/orders", json=_SIG, headers=_alice(client))
    assert res.json()["status"] == "SUBMITTED", res.text
    assert len(_mock_orders(acc)) == 1


# ── ② 모드 ─────────────────────────────────────────────────────────────────

def test_paper_mode_on_a_real_account_is_refused_with_a_reason(client):
    acc = _connect(client, is_paper=False)
    r = client.post(f"{BASE}/{acc}/mode", json={"mode": "PAPER"}, headers=_alice(client))
    assert r.status_code == 400
    assert "실계좌" in r.json()["detail"]
    assert client.get(f"{BASE}/{acc}/mode", headers=_alice(client)).json()["mode"] == "SHADOW"


@pytest.mark.parametrize("is_paper", [True, False])
def test_live_mode_is_refused_for_now(client, is_paper):
    acc = _connect(client, is_paper=is_paper)
    r = client.post(f"{BASE}/{acc}/mode", json={"mode": "LIVE", "confirm_token": "EXPLICIT_LIVE_CONFIRMED"},
                    headers=_alice(client))
    assert r.status_code == 400
    assert client.get(f"{BASE}/{acc}/mode", headers=_alice(client)).json()["mode"] == "SHADOW"


# ── ③ 남의 계좌 · 감사 행위자 ──────────────────────────────────────────────

_ACCOUNT_ROUTES = sorted(k for k in PROTECTED if k[1].startswith(BASE + "/{account_id}/")
                         and k[1] != BASE + "/{account_id}/check")


def test_the_order_routes_are_registered():
    assert len(_ACCOUNT_ROUTES) >= 8, _ACCOUNT_ROUTES


@pytest.mark.parametrize(("method", "path"), _ACCOUNT_ROUTES)
def test_someone_else_gets_404_on_every_order_route(client, method, path):
    acc = _connect(client)
    url = path.replace("{account_id}", acc).replace("{client_order_id}", "CO-x")
    res = client.request(method, url, json={"mode": "SHADOW", "reason": "남의 계좌 멈춤", **_SIG},
                         headers=_bob(client))
    assert res.status_code == 404, f"{method} {path} → {res.status_code}"
    assert acc not in str(kc._account_clients), "남의 계좌 자격으로 클라이언트를 만들었다"


def test_the_audit_names_the_token_user(client):
    acc = _connect(client)
    client.post(f"{BASE}/{acc}/orders", json=_SIG, headers=_alice(client))
    from src.execution.account_executors import get_account_executor
    rows = get_account_executor(acc).audit.query(event_type="SIGNAL_RECEIVED")
    assert {r["actor"] for r in rows} == {"alice"}


# ── ④ 비상 정지 ────────────────────────────────────────────────────────────

def test_my_stop_blocks_my_orders_and_i_can_lift_it(client):
    acc = _connect(client)
    t = client.post(f"{BASE}/{acc}/kill-switch/trigger", json={"reason": "잠깐 멈춤"}, headers=_alice(client))
    assert t.status_code == 200, t.text
    st = client.get(f"{BASE}/{acc}/kill-switch", headers=_alice(client)).json()
    assert st["active"] is True and st["event"]["liquidation_mode"] == "hold"
    assert client.post(f"{BASE}/{acc}/orders", json=_SIG, headers=_alice(client)).json()["status"] == "REJECTED"
    r = client.post(f"{BASE}/{acc}/kill-switch/resolve", json={"notes": "다시 시작"}, headers=_alice(client))
    assert r.json()["status"] == "resolved" and r.json()["resolved_by"] == "alice"
    assert client.get(f"{BASE}/{acc}/kill-switch", headers=_alice(client)).json()["active"] is False


def test_my_stop_does_not_stop_the_operator_or_my_other_account(client):
    """내 계좌 정지가 운영자(전역) 정지가 되면 모든 사용자의 주문이 막힌다."""
    import src.api.stage13_routes as stage13
    acc, other = _connect(client), _connect(client)
    client.post(f"{BASE}/{acc}/kill-switch/trigger", json={"reason": "잠깐 멈춤"}, headers=_alice(client))
    assert stage13.get_executor().kill_switch.is_active() is False, "계좌 정지가 운영자 정지가 됐다"
    assert client.get(f"{BASE}/{other}/kill-switch", headers=_alice(client)).json()["active"] is False
    assert client.post(f"{BASE}/{other}/orders", json=_SIG, headers=_alice(client)).json()["status"] == "SHADOW_LOGGED"


def test_cancelling_my_own_order_is_not_404(client):
    """★짝★ — 취소 경로가 언제나 404 인 구현을 배제한다(SHADOW 기록은 취소할 미체결이 아니라 not_cancellable)."""
    acc = _connect(client)
    coid = client.post(f"{BASE}/{acc}/orders", json=_SIG, headers=_alice(client)).json()["client_order_id"]
    r = client.delete(f"{BASE}/{acc}/orders/{coid}", headers=_alice(client))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "not_cancellable"


def test_cancelling_an_unknown_order_is_404(client):
    acc = _connect(client)
    assert client.delete(f"{BASE}/{acc}/orders/CO-nope", headers=_alice(client)).status_code == 404


# ── ⑤ 실행기 생명주기 ──────────────────────────────────────────────────────

def test_deleting_the_account_drops_its_executor(client):
    import src.execution.account_executors as ae
    acc = _connect(client)
    client.get(f"{BASE}/{acc}/mode", headers=_alice(client))
    assert acc in ae._executors
    client.delete(f"{BASE}/{acc}", headers=_alice(client))
    assert acc not in ae._executors


def test_a_restart_comes_back_in_shadow(client, monkeypatch):
    import src.execution.account_executors as ae
    acc = _connect(client, is_paper=True)
    client.post(f"{BASE}/{acc}/mode", json={"mode": "PAPER"}, headers=_alice(client))
    monkeypatch.setattr(ae, "_executors", {}, raising=False)   # 프로세스 재시작과 같다
    assert client.get(f"{BASE}/{acc}/mode", headers=_alice(client)).json()["mode"] == "SHADOW"
