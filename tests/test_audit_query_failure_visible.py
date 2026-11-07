"""R1 — ★감사 기록을 읽지 못한 것을 '기록 0건'으로 답하지 않는다★.

`AuditTrail.query` 는 읽기에 실패하면 로그만 남기고 `[]` 를 돌려준다. 그래서 `GET /api/v1/live/audit` 은
표가 없거나 DB 가 끊겨도 `200 {"count": 0}` 이었고, 화면은 "정말 기록이 없는지 가를 수 없어요"라고 말할 수밖에 없었다
(CLAUDE.md §4 침묵 폴백 금지 · 미상 ≠ 0).

고친 것은 키워드 하나다 — `query(..., raise_on_error=True)` 를 ★그 경로만★ 넘긴다. 기본값은 그대로 `[]`:
`broker_account_routes` 의 두 소비자는 실패를 '확인 기록 없음 = 미통과'로 읽어 보수 쪽이라 손대지 않는다.
"""
from __future__ import annotations

import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

import src.database as dbmod
from src.execution.audit_trail import AuditTrail

_SECRET = "audit-failure-test-secret-0123456789abcd"


def _app_client(monkeypatch, *, with_live_schema: bool):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp.name}")
    monkeypatch.setenv("AUTH_SECRET", _SECRET)
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    monkeypatch.setattr(dbmod, "DATABASE_URL", f"sqlite:///{tmp.name}", raising=False)
    dbmod.reset_session()
    dbmod.init_db()
    import src.api.stage13_routes as stage13
    monkeypatch.setattr(stage13, "_EXECUTOR", None, raising=False)
    import src.execution.kis_client as kc
    monkeypatch.setattr(kc, "_kis_singleton", None, raising=False)
    from src.app_factory import create_app
    return tmp.name, TestClient(create_app()), with_live_schema


@pytest.fixture()
def no_table(monkeypatch):
    """실거래 표를 만들지 않은 DB — 감사 표 읽기가 실제로 실패한다."""
    path, tc, _ = _app_client(monkeypatch, with_live_schema=False)
    with tc as c:
        yield c
    dbmod.reset_session()
    os.unlink(path)


@pytest.fixture()
def empty_table(monkeypatch):
    """표는 있고 행만 없는 DB — 진짜 0건."""
    path, tc, _ = _app_client(monkeypatch, with_live_schema=True)
    with tc as c:
        assert c.post("/api/v1/live/init-schema", headers=_admin(c)).status_code == 200
        yield c
    dbmod.reset_session()
    os.unlink(path)


def _admin(client) -> dict[str, str]:
    tok = client.post("/api/v1/auth/login",
                      json={"username": "admin", "password": "frm123!"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


# ── 경로: 읽지 못함 ≠ 0건 ────────────────────────────────────────────────────

def test_an_unreadable_audit_table_is_a_500_with_a_reason(no_table):
    res = no_table.get("/api/v1/live/audit", headers=_admin(no_table))
    assert res.status_code == 500, res.text
    detail = res.json()["detail"]
    assert "live_audit_trail" in detail          # 무엇을 못 읽었는지 사유에 있다
    assert "count" not in res.json()             # 0건 모양으로 답하지 않는다


def test_an_empty_audit_table_is_a_real_zero(empty_table):
    """짝 — 표가 있고 비어 있으면 그대로 200 · 0건(늘-실패 구현 배제)."""
    res = empty_table.get("/api/v1/live/audit", headers=_admin(empty_table))
    assert res.status_code == 200, res.text
    assert res.json() == {"count": 0, "events": []}


def test_a_written_row_comes_back(empty_table):
    """짝 — 기록이 있으면 보인다(늘-0건 구현 배제)."""
    h = _admin(empty_table)
    assert empty_table.post("/api/v1/live/mode", json={"mode": "PAPER"}, headers=h).status_code == 200
    body = empty_table.get("/api/v1/live/audit", headers=h).json()
    assert body["count"] >= 1 and any(e["event_type"] == "MODE_CHANGED" for e in body["events"])


# ── 함수: 기본 호출자는 그대로, 묻는 쪽만 실패를 받는다 ──────────────────────────

@pytest.fixture()
def bare_engine():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    eng = create_engine(f"sqlite:///{tmp.name}")
    yield eng
    eng.dispose()
    os.unlink(tmp.name)


def test_default_callers_still_get_an_empty_list(bare_engine):
    """`broker_account_routes` 의 두 소비자(확인 기록 · 모의 주문 기록)는 실패를 '없음 = 미통과'로 읽는다 — 불변."""
    assert AuditTrail(bare_engine).query() == []
    assert AuditTrail(bare_engine, account_id="ba_x").query(event_type="BROKER_CHECK", limit=1) == []


def test_raise_on_error_surfaces_the_failure(bare_engine):
    with pytest.raises(Exception, match="live_audit_trail"):
        AuditTrail(bare_engine).query(raise_on_error=True)


def test_raise_on_error_does_not_raise_when_the_read_works(bare_engine):
    """짝 — 키워드가 성공한 읽기까지 실패로 바꾸지 않는다."""
    from src.execution.live_schemas import init_live_trading_schema
    init_live_trading_schema(bare_engine)
    assert AuditTrail(bare_engine).query(raise_on_error=True) == []
