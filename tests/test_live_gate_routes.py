"""BV7 — ★실계좌(LIVE) 관문은 운영자가 이름으로 열고, 그 기록은 지워지지 않는다★ + 계좌별 준비 목록.

사용자 결정(2026-10-09): 관문·준비 목록만. 계좌 LIVE 전환·확인 코드는 계좌별 대조 감시가 생길 때 함께.

  ① 관문 선언·철회는 관리자만 · 선언자는 토큰 · 빠진 항목이 있으면 422(무엇이 빠졌는지) · `*` 로 모두에게 열 수 없다
  ② 이력은 남는다 — 새 선언은 옛 선언을 철회로 닫고, 철회도 누가 했는지 남긴다
  ③ ★운영자 `.env` 계좌의 LIVE 도 관문 뒤★ — 관문이 닫혀 있거나 이름이 없으면 400 + 사유 · 짝: 열려 있고 이름이 있으면 LIVE
  ④ 관문을 바꾸거나 철회하면 LIVE 였던 운영자 실행기는 SHADOW 로
  ⑤ 준비 목록 — 본인 계좌만 · 항목마다 사유 · 대조 감시는 늘 미통과 → ready 는 지금 False
  ⑥ 연결 확인 결과가 감사에 남고(비밀 0), 준비 목록이 그것을 읽는다 · 연습용 확인은 세지 않는다
"""
from __future__ import annotations

import os
import tempfile

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

import src.database as dbmod
import src.execution.kis_client as kc
from src.domain.auth_identity import ROLE_ADMIN, ROLE_ANALYST

_SECRET = "live-gate-routes-secret-0123456789abcdef"
GATE = "/api/v1/admin/live-gate"
BASE = "/api/v1/broker-accounts"
_DECL = dict(basis="본인 계좌만 쓴다", authority="운영자 확인", reference_no="SELF-2026-01",
             verified_at="2026-10-09", scope="운영자 본인 계좌", allowed_users=["admin"])
_KEY = "PSkey-0123456789abcdef"
_SEC = "secret-0123456789abcdefghijklmnop"


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
    monkeypatch.setattr(br, "_inited", False)
    monkeypatch.setattr(kc, "_kis_singleton", None, raising=False)
    monkeypatch.setattr(kc, "_account_clients", {}, raising=False)
    import src.api.stage13_routes as stage13
    import src.execution.account_executors as ae
    monkeypatch.setattr(stage13, "_EXECUTOR", None, raising=False)
    monkeypatch.setattr(ae, "_executors", {}, raising=False)
    dbmod.reset_session()
    dbmod.init_db()
    dbmod.create_user("alice", "alice-pw", role=ROLE_ANALYST)
    dbmod.create_user("minji", "minji-pw", role=ROLE_ADMIN)

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


def _admin(c):
    return _auth(c, "admin", "frm123!")


def _minji(c):
    return _auth(c, "minji", "minji-pw")


def _alice(c):
    return _auth(c, "alice", "alice-pw")


def _live(c, h):
    return c.post("/api/v1/live/mode", json={"mode": "LIVE", "confirm_token": "EXPLICIT_LIVE_CONFIRMED"}, headers=h)


def _mode(c):
    return c.get("/api/v1/live/mode").json()["mode"]


def _connect(c, *, is_paper: bool) -> str:
    r = c.post(BASE, json=dict(label="계좌", app_key=_KEY, app_secret=_SEC, account_no="50123456",
                               is_paper=is_paper), headers=_alice(c))
    assert r.status_code == 201, r.text
    return r.json()["account_id"]


# ── ① 선언·철회 ────────────────────────────────────────────────────────────

def test_only_admins_declare(client):
    assert client.post(GATE, json=_DECL, headers=_alice(client)).status_code == 403
    assert client.get(GATE, headers=_alice(client)).status_code == 403
    assert client.delete(GATE, headers=_alice(client)).status_code == 403


def test_a_declaration_records_who_declared_it(client):
    r = client.post(GATE, json=_DECL, headers=_minji(client))
    assert r.status_code == 201, r.text
    cur = client.get(GATE, headers=_admin(client)).json()["current"]
    assert cur["declared_by"] == "minji"
    assert cur["allowed_users"] == ["admin"]


@pytest.mark.parametrize("field", ["basis", "authority", "reference_no", "verified_at", "scope"])
def test_an_incomplete_declaration_is_refused_and_names_what_is_missing(client, field):
    r = client.post(GATE, json={**_DECL, field: "  "}, headers=_admin(client))
    assert r.status_code == 422
    assert field in r.json()["detail"]
    assert client.get(GATE, headers=_admin(client)).json()["current"] is None


@pytest.mark.parametrize("users", [["*"], [], ["admin", " "]])
def test_nobody_opens_it_to_everyone(client, users):
    r = client.post(GATE, json={**_DECL, "allowed_users": users}, headers=_admin(client))
    assert r.status_code == 422
    assert "allowed_users" in r.json()["detail"]


# ── ② 이력 ─────────────────────────────────────────────────────────────────

def test_a_new_declaration_closes_the_old_one_and_both_stay(client):
    client.post(GATE, json=_DECL, headers=_admin(client))
    client.post(GATE, json={**_DECL, "allowed_users": ["admin", "minji"]}, headers=_minji(client))
    body = client.get(GATE, headers=_admin(client)).json()
    assert body["current"]["allowed_users"] == ["admin", "minji"]
    old = [h for h in body["history"] if h["allowed_users"] == ["admin"]]
    assert len(old) == 1 and old[0]["revoked_by"] == "minji" and old[0]["revoked_at"]


def test_revoking_closes_it_and_says_who(client):
    client.post(GATE, json=_DECL, headers=_admin(client))
    r = client.delete(GATE, headers=_minji(client))
    assert r.status_code == 200
    body = client.get(GATE, headers=_admin(client)).json()
    assert body["current"] is None
    assert body["history"][0]["revoked_by"] == "minji"


def test_revoking_nothing_is_404(client):
    assert client.delete(GATE, headers=_admin(client)).status_code == 404


# ── ③ 운영자 LIVE 도 관문 뒤 ──────────────────────────────────────────────

def test_operator_live_is_refused_while_the_gate_is_closed(client):
    r = _live(client, _admin(client))
    assert r.status_code == 400
    assert "실계좌" in r.json()["detail"]
    assert _mode(client) == "SHADOW"


def test_operator_live_is_refused_for_an_admin_not_on_the_list(client):
    client.post(GATE, json=_DECL, headers=_admin(client))           # admin 만
    r = _live(client, _minji(client))
    assert r.status_code == 400 and "minji" in r.json()["detail"]
    assert _mode(client) == "SHADOW"


def test_operator_live_opens_for_a_listed_admin(client):
    """★짝★ — 언제나 거절하는 구현을 배제한다."""
    client.post(GATE, json=_DECL, headers=_admin(client))
    r = _live(client, _admin(client))
    assert r.status_code == 200, r.text
    assert _mode(client) == "LIVE"


def test_the_confirm_token_is_still_required(client):
    client.post(GATE, json=_DECL, headers=_admin(client))
    r = client.post("/api/v1/live/mode", json={"mode": "LIVE"}, headers=_admin(client))
    assert r.status_code == 400
    assert _mode(client) == "SHADOW"


# ── ④ 관문이 바뀌면 LIVE 는 내려온다 ─────────────────────────────────────

@pytest.mark.parametrize("change", ["revoke", "redeclare"])
def test_changing_the_gate_drops_operator_live_to_shadow(client, change):
    client.post(GATE, json=_DECL, headers=_admin(client))
    _live(client, _admin(client))
    assert _mode(client) == "LIVE"
    if change == "revoke":
        client.delete(GATE, headers=_admin(client))
    else:
        client.post(GATE, json={**_DECL, "allowed_users": ["minji"]}, headers=_admin(client))
    assert _mode(client) == "SHADOW"


# ── ⑤ 준비 목록 ────────────────────────────────────────────────────────────

def _ready(c, acc, h=None):
    return c.get(f"{BASE}/{acc}/live-readiness", headers=h or _alice(c))


def test_readiness_is_only_for_the_owner(client):
    acc = _connect(client, is_paper=False)
    assert _ready(client, acc, _admin(client)).status_code == 404
    assert _ready(client, acc).status_code == 200


def test_readiness_names_every_unmet_condition_with_a_reason(client):
    acc = _connect(client, is_paper=True)
    body = _ready(client, acc).json()
    assert body["ready"] is False
    items = {i["key"]: i for i in body["items"]}
    assert set(items) == {"gate", "real_account", "connection", "paper_practice", "reconciliation"}
    for i in items.values():
        assert i["ok"] is False and len(i["reason"]) > 10, i


def test_the_gate_item_follows_the_declaration(client):
    """★짝★ — 관문 항목이 상수가 아니다."""
    acc = _connect(client, is_paper=False)
    client.post(GATE, json={**_DECL, "allowed_users": ["alice"]}, headers=_admin(client))
    items = {i["key"]: i for i in _ready(client, acc).json()["items"]}
    assert items["gate"]["ok"] is True
    assert items["real_account"]["ok"] is True


def test_reconciliation_is_never_claimed(client):
    acc = _connect(client, is_paper=False)
    client.post(GATE, json={**_DECL, "allowed_users": ["alice"]}, headers=_admin(client))
    body = _ready(client, acc).json()
    rec = {i["key"]: i for i in body["items"]}["reconciliation"]
    assert rec["ok"] is False and "대조" in rec["reason"]
    assert body["ready"] is False


# ── ⑥ 연결 확인 기록 ───────────────────────────────────────────────────────

def test_a_practice_check_is_recorded_but_does_not_count(client):
    acc = _connect(client, is_paper=False)
    assert client.post(f"{BASE}/{acc}/check", headers=_alice(client)).json()["state"] == "practice"
    conn = {i["key"]: i for i in _ready(client, acc).json()["items"]}["connection"]
    assert conn["ok"] is False and "연습용" in conn["reason"]


def test_a_successful_check_counts(client, monkeypatch):
    """★짝★ — 운영 모드에서 증권사가 받아 준 확인은 센다(네트워크 0 — 잔고 조회를 바꿔 끼움)."""
    acc = _connect(client, is_paper=False)
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    monkeypatch.setattr(kc.KISClient, "get_balance", lambda self: {"ok": True})
    assert client.post(f"{BASE}/{acc}/check", headers=_alice(client)).json()["state"] == "ok"
    conn = {i["key"]: i for i in _ready(client, acc).json()["items"]}["connection"]
    assert conn["ok"] is True


def test_the_check_record_carries_no_secrets(client):
    acc = _connect(client, is_paper=False)
    client.post(f"{BASE}/{acc}/check", headers=_alice(client))
    from src.execution.audit_trail import AuditTrail
    rows = AuditTrail(dbmod.get_sync_engine(), account_id=acc).query(event_type="BROKER_CHECK")
    assert len(rows) == 1 and rows[0]["actor"] == "alice"
    assert _KEY not in str(rows) and _SEC not in str(rows) and "50123456" not in str(rows)


# ── 모의 주문 연습 ─────────────────────────────────────────────────────────

def test_mock_paper_orders_do_not_count_as_broker_practice(client):
    """mock 클라이언트로 낸 PAPER 주문은 증권사 모의 서버가 받은 주문이 아니다."""
    real = _connect(client, is_paper=False)
    paper = _connect(client, is_paper=True)
    client.post(f"{BASE}/{paper}/mode", json={"mode": "PAPER"}, headers=_alice(client))
    sig = {"strategy_id": 1, "ticker": "005930", "side": "BUY", "quantity": 1, "price": 71000.0, "order_type": "LIMIT"}
    assert client.post(f"{BASE}/{paper}/orders", json=sig, headers=_alice(client)).json()["status"] == "SUBMITTED"
    item = {i["key"]: i for i in _ready(client, real).json()["items"]}["paper_practice"]
    assert item["ok"] is False


def test_paper_orders_accepted_by_the_broker_practice_server_count(client):
    """★짝★ — 증권사 모의 서버가 받은 주문(감사 행에 `kis_paper_endpoint`)은 센다."""
    real = _connect(client, is_paper=False)
    paper = _connect(client, is_paper=True)
    from src.execution.audit_trail import AuditTrail
    AuditTrail(dbmod.get_sync_engine(), account_id=paper).log_order_submitted(
        "CO-1", {"ticker": "005930", "side": "BUY", "quantity": 1, "price": 71000.0},
        {"odno": "1"}, simulated_by="kis_paper_endpoint")
    item = {i["key"]: i for i in _ready(client, real).json()["items"]}["paper_practice"]
    assert item["ok"] is True


def test_an_account_executor_refuses_live_even_when_the_gate_names_its_owner(client):
    """두 겹 — 경로가 먼저 막지만, 실행기 자체도 계좌 LIVE 를 거절한다(대조 감시가 생기기 전)."""
    acc = _connect(client, is_paper=False)
    client.post(GATE, json={**_DECL, "allowed_users": ["alice"]}, headers=_admin(client))
    from src.execution.account_executors import get_account_executor
    ex = get_account_executor(acc)
    with pytest.raises(ValueError):
        ex.set_mode("LIVE", "alice", "EXPLICIT_LIVE_CONFIRMED")
    assert ex.state.mode == "SHADOW"


def test_a_paper_order_records_which_client_took_it(client):
    paper = _connect(client, is_paper=True)
    client.post(f"{BASE}/{paper}/mode", json={"mode": "PAPER"}, headers=_alice(client))
    sig = {"strategy_id": 1, "ticker": "005930", "side": "BUY", "quantity": 1, "price": 71000.0, "order_type": "LIMIT"}
    client.post(f"{BASE}/{paper}/orders", json=sig, headers=_alice(client))
    from src.execution.audit_trail import AuditTrail
    rows = AuditTrail(dbmod.get_sync_engine(), account_id=paper).query(event_type="ORDER_SUBMITTED")
    assert [r["context"]["simulated_by"] for r in rows] == ["mock_client"]
