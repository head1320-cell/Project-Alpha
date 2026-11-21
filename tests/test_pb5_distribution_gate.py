"""CF 3부 PB5 — ★유통 관문은 운영자가 인가 기록 다섯 칸을 이름으로 선언해야 열리고, 그 기록은 지워지지 않는다★ (BV7 과 같은 모양).

사용자 결정(2026-10-23): 고객 화면(PB6)은 '관문 뒤에 만들기' — 코드는 만들고, 여는 것은 운영자가 인가 기록을 선언해야.

  ① 선언·철회는 관리자만 · 선언자는 토큰에서만(본문에 끼울 칸이 없다) · 빠진 항목이 있으면 422(무엇이 빠졌는지) · 저장하지 않는다
  ② 이력은 남는다 — 새 선언은 옛 선언을 철회로 닫고, 철회도 누가 했는지 남긴다 · 지우는 길이 없다
  ③ ★판정은 `distribution_gate` 가 한다★ — 빈 DB 는 막힘(기본 닫힘) · 선언하면 열림(짝) · 철회하면 다시 막힘
  ④ 환경변수 뒷문 없음 · 소스에 인가 기록 리터럴 없음(기존 AE1 테스트) · 보존 ② 감사 · 보호 등록부·로그인 지도
"""
from __future__ import annotations

import ast
import json
import pathlib
import tempfile

import pytest
from fastapi.testclient import TestClient

import src.database as dbmod
from src.domain.auth_identity import ROLE_ADMIN, ROLE_ANALYST
from src.domain.distribution_gate import DISTRIBUTION_ALLOWED, DISTRIBUTION_BLOCKED, LICENSE_FIELDS

ROOT = pathlib.Path(__file__).resolve().parents[1]
GATE = "/api/v1/admin/distribution-gate"
_SECRET = "pb5-distribution-gate-secret-0123456789"
_DECL = dict(authority="운영자가 확인한 기관", license_kind="운영자가 확인한 종류", license_no="TEST-0001",
             verified_at="2026-10-29", scope="PB 고객 한 장을 그 고객에게 보여 주기")


@pytest.fixture()
def client(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp.name}")
    monkeypatch.setenv("AUTH_SECRET", _SECRET)
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    monkeypatch.setattr(dbmod, "DATABASE_URL", f"sqlite:///{tmp.name}", raising=False)
    import src.data.backtest_runs as br
    monkeypatch.setattr(br, "_inited", False)
    dbmod.reset_session()
    dbmod.init_db()
    dbmod.create_user("alice", "alice-pw", role=ROLE_ANALYST)
    dbmod.create_user("minji", "minji-pw", role=ROLE_ADMIN)
    from src.app_factory import create_app
    with TestClient(create_app()) as c:
        yield c
    dbmod.reset_session()
    pathlib.Path(tmp.name).unlink(missing_ok=True)


def _auth(c, username: str, password: str) -> dict[str, str]:
    tok = c.post("/api/v1/auth/login", json={"username": username, "password": password}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def _admin(c):
    return _auth(c, "admin", "frm123!")


def _minji(c):
    return _auth(c, "minji", "minji-pw")


def _alice(c):
    return _auth(c, "alice", "alice-pw")


def _store():
    from src.services import distribution_gate_store
    return distribution_gate_store


# ── ① 선언·철회 ────────────────────────────────────────────────────────────

def test_only_admins_see_declare_and_revoke(client):
    for call in (lambda h: client.get(GATE, headers=h), lambda h: client.post(GATE, json=_DECL, headers=h),
                 lambda h: client.delete(GATE, headers=h)):
        assert call(_alice(client)).status_code == 403
        assert call({}).status_code == 401
    assert _store().current() is None


def test_a_declaration_opens_the_gate_and_records_who(client):
    r = client.post(GATE, json=_DECL, headers=_minji(client))
    assert r.status_code == 201, r.text
    body = client.get(GATE, headers=_admin(client)).json()
    assert body["current"]["declared_by"] == "minji"
    assert {k: body["current"][k] for k in LICENSE_FIELDS} == _DECL
    assert body["gate"]["state"] == DISTRIBUTION_ALLOWED and body["gate"]["missing"] == []


def test_the_declarer_comes_only_from_the_token(client):
    r = client.post(GATE, json={**_DECL, "declared_by": "someone-else"}, headers=_admin(client))
    assert r.status_code == 422
    assert _store().current() is None


@pytest.mark.parametrize("field", LICENSE_FIELDS)
def test_an_incomplete_declaration_is_refused_names_the_field_and_saves_nothing(client, field):
    r = client.post(GATE, json={**_DECL, field: "  "}, headers=_admin(client))
    assert r.status_code == 422
    assert field in r.json()["detail"]
    body = client.get(GATE, headers=_admin(client)).json()
    assert body["current"] is None and body["history"] == []
    assert body["gate"]["state"] == DISTRIBUTION_BLOCKED


# ── ② 이력 ─────────────────────────────────────────────────────────────────

def test_a_new_declaration_closes_the_old_one_and_both_stay(client):
    client.post(GATE, json=_DECL, headers=_admin(client))
    client.post(GATE, json={**_DECL, "scope": "좁힌 범위"}, headers=_minji(client))
    body = client.get(GATE, headers=_admin(client)).json()
    assert body["current"]["scope"] == "좁힌 범위"
    old = [h for h in body["history"] if h["scope"] == _DECL["scope"]]
    assert len(old) == 1 and old[0]["revoked_by"] == "minji" and old[0]["revoked_at"]
    assert len(body["history"]) == 2


def test_revoking_closes_the_gate_says_who_and_keeps_the_row(client):
    client.post(GATE, json=_DECL, headers=_admin(client))
    r = client.delete(GATE, headers=_minji(client))
    assert r.status_code == 200 and r.json()["revoked_by"] == "minji"
    body = client.get(GATE, headers=_admin(client)).json()
    assert body["current"] is None and body["gate"]["state"] == DISTRIBUTION_BLOCKED
    assert len(body["history"]) == 1 and body["history"][0]["revoked_by"] == "minji"


def test_revoking_nothing_is_404_with_the_gate_reason(client):
    r = client.delete(GATE, headers=_admin(client))
    assert r.status_code == 404 and "유통 관문" in r.json()["detail"]   # 경로가 없어서 나는 404 와 구별한다


def test_there_is_no_path_that_deletes_a_declaration_row():
    """지우는 함수가 없다 — 철회는 행을 남긴다(AST: 스토어가 `delete` 를 부르지 않는다)."""
    src = (ROOT / "src" / "services" / "distribution_gate_store.py").read_text(encoding="utf-8")
    calls = {getattr(n.func, "attr", None) for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call)}
    assert "delete" not in calls


# ── ③ 판정은 `distribution_gate` 가 한다 ─────────────────────────────────────

def test_an_empty_database_is_blocked_by_default(client):
    g = _store().gate()
    assert g["state"] == DISTRIBUTION_BLOCKED and g["missing"] == list(LICENSE_FIELDS)
    assert g["reason"]


def test_the_store_gate_opens_after_a_declaration_and_closes_after_revoke(client):
    """★짝★ — 늘 막히는 구현도, 늘 열리는 구현도 배제한다."""
    client.post(GATE, json=_DECL, headers=_admin(client))
    assert _store().gate()["state"] == DISTRIBUTION_ALLOWED
    assert _store().gate()["license"] == _DECL
    client.delete(GATE, headers=_admin(client))
    assert _store().gate()["state"] == DISTRIBUTION_BLOCKED


def test_a_row_with_a_blank_field_still_reads_as_blocked(client):
    """저장 길을 우회해 빈 칸이 든 행이 생겨도(손으로 넣음) 판정은 막힘 — 판정은 스토어가 아니라 관문이 한다."""
    import datetime as dt
    with dbmod.session_scope() as s:
        s.add(dbmod.DistributionGateDeclaration(**{**_DECL, "license_no": " "}, declared_by="hand",
                                                declared_at=dt.datetime.now(dt.timezone.utc)))
    g = _store().gate()
    assert g["state"] == DISTRIBUTION_BLOCKED and g["missing"] == ["license_no"]


# ── ④ 뒷문·등록 ────────────────────────────────────────────────────────────

def test_the_store_reads_no_environment_variable():
    src = (ROOT / "src" / "services" / "distribution_gate_store.py").read_text(encoding="utf-8")
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Call):
            assert (getattr(n.func, "attr", None) or getattr(n.func, "id", None)) not in {"getenv", "environ"}
    assert "os.environ" not in src and "import os" not in src


def test_routes_are_in_the_protected_registry_as_admin():
    from src.api.protected_routes import PROTECTED, REQUIRE_ADMIN, looks_like_money_route
    for m in ("GET", "POST", "DELETE"):
        level, why = PROTECTED[(m, GATE)]
        assert level == REQUIRE_ADMIN and why.strip()
    assert looks_like_money_route(GATE)


def test_the_declarations_are_kept_as_audit():
    from src.data.retention import AUDIT
    assert "distribution_gate_declarations" in AUDIT
    doc = (ROOT / "docs" / "specs" / "RETENTION_POLICY.md").read_text(encoding="utf-8")
    listed = doc.split("<!-- PROTECTED-LIST:START -->")[1].split("<!-- PROTECTED-LIST:END -->")[0]
    assert "distribution_gate_declarations" in listed


def test_the_login_map_names_the_gate_for_admins():
    m = json.loads((ROOT / "frontend" / "src" / "entities" / "session" / "accessMap.json").read_text(encoding="utf-8"))
    admin = [r for it in m["admin"]["items"] for r in it.get("routes", [])]
    for meth in ("GET", "POST", "DELETE"):
        assert f"{meth} {GATE}" in admin
