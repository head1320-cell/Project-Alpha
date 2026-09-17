"""AC5 — ★자칭 행위자가 감사 로그에 도달하지 않는다★.

이 프로그램의 핵심이다. 문을 잠그는 것만으로는 절반이고, `live_audit_log.actor` 가
**요청 본문이 주장한 이름**인 한 감사 로그는 관측이 아니라 주장을 저장한다
(CLAUDE.md §2 `관측 ≠ 가정`, §4 `미검증 ≠ 검증`).
"""
from __future__ import annotations

import os
import tempfile

import pytest
from fastapi.testclient import TestClient

import src.database as dbmod

_SECRET = "actor-wiring-test-secret-0123456789abcd"
_LIAR = "someone_else_entirely"


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

    # ★실행기 싱글턴을 테스트마다 비운다★ — `get_executor()` 가 프로세스 싱글턴이라
    # 앞 테스트의 (이미 삭제된) DB 엔진을 들고 있으면 감사 기록이 빈 파일로 새어
    # 나가 이 파일의 검사가 **아무것도 검사하지 않게** 된다.
    import src.api.stage13_routes as stage13
    monkeypatch.setattr(stage13, "_EXECUTOR", None, raising=False)

    from src.app_factory import create_app
    with TestClient(create_app()) as c:
        c.post("/api/v1/live/init-schema", headers=_admin(c))
        yield c

    dbmod.reset_session()
    try:
        os.unlink(tmp.name)
    except OSError:
        pass


def _admin(client) -> dict[str, str]:
    tok = client.post("/api/v1/auth/login",
                      json={"username": "admin", "password": "frm123!"}
                      ).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


# ── 응답이 관측된 행위자를 말한다 ──────────────────────────────────────────

def test_the_response_reports_the_observed_actor_not_the_claim(client):
    res = client.post("/api/v1/live/mode",
                      json={"mode": "PAPER", "actor": _LIAR},
                      headers=_admin(client))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["actor"] == "admin"
    assert body["actor_source"] == "authenticated"


def test_the_conflicting_claim_is_recorded_side_by_side(client):
    """★거짓말을 지우지 않는다★ — 변이 h(claimed_actor 제거)를 죽인다."""
    body = client.post("/api/v1/live/mode",
                       json={"mode": "PAPER", "actor": _LIAR},
                       headers=_admin(client)).json()
    assert body["claimed_actor"] == _LIAR


def test_an_honest_request_records_no_conflict(client):
    """★짝★ — 언제나 claimed_actor 를 채우는 구현을 배제한다."""
    body = client.post("/api/v1/live/mode",
                       json={"mode": "SHADOW", "actor": "admin"},
                       headers=_admin(client)).json()
    assert body["claimed_actor"] is None


# ── ★감사 로그 자체★ — 변이 g 를 죽인다 ──────────────────────────────────

def test_the_claimed_name_never_reaches_the_audit_log(client):
    """자칭 이름이 `live_audit_log` 어디에도 행위자로 남지 않는다."""
    client.post("/api/v1/live/mode", json={"mode": "PAPER", "actor": _LIAR},
                headers=_admin(client))
    audit = client.get("/api/v1/live/audit", headers=_admin(client))
    assert audit.status_code == 200, audit.text
    rows = audit.json().get("events") or audit.json().get("logs") or []
    assert rows, "감사 행이 없다 — 이 테스트가 아무것도 검사하지 못한다"
    actors = {r.get("actor") for r in rows}
    assert _LIAR not in actors, f"자칭 이름이 감사 로그에 들어갔다: {actors}"
    assert "admin" in actors, f"관측된 이름이 감사 로그에 없다: {actors}"


def test_the_kill_switch_resolution_records_the_observed_actor(client):
    """`resolved_by` 도 같은 규율 — 본문이 주장한 이름을 쓰지 않는다."""
    client.post("/api/v1/live/kill-switch/trigger",
                json={"reason": "테스트 발동입니다", "actor": _LIAR},
                headers=_admin(client))
    res = client.post("/api/v1/live/kill-switch/resolve",
                      json={"resolved_by": _LIAR, "notes": "테스트 해제"},
                      headers=_admin(client))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["actor"] == "admin"
    assert body["claimed_actor"] == _LIAR
    assert body.get("resolved_by") != _LIAR


def test_the_audit_log_after_a_kill_cycle_has_no_claimed_name(client):
    client.post("/api/v1/live/kill-switch/trigger",
                json={"reason": "테스트 발동입니다", "actor": _LIAR},
                headers=_admin(client))
    client.post("/api/v1/live/kill-switch/resolve",
                json={"resolved_by": _LIAR, "notes": "해제"},
                headers=_admin(client))
    rows = client.get("/api/v1/live/audit", headers=_admin(client)).json()
    blob = str(rows)
    assert _LIAR not in blob, "감사 조회 결과에 자칭 이름이 실렸다"


# ── 소스 전수 — ★분기가 다시 자칭을 넘기면 실패★ ─────────────────────────

def test_no_handler_passes_the_request_actor_to_the_execution_layer():
    """★AST 전수★ — `req.actor`/`req.resolved_by` 가 실행 계층 호출의 인자로 쓰이면 실패.

    변이 g 는 한 분기만 되돌려도 통과할 수 있다. 소스를 전수해 그 복원을 막는다.
    """
    import ast
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "api" / "stage13_routes.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))

    banned = {"actor", "resolved_by"}
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = ast.unparse(node.func)
        if not any(k in target for k in ("set_mode", "trigger", "resolve", "cancel_order")):
            continue
        args = list(node.args) + [kw.value for kw in node.keywords]
        for arg in args:
            for sub in ast.walk(arg):
                if (isinstance(sub, ast.Attribute) and sub.attr in banned
                        and isinstance(sub.value, ast.Name) and sub.value.id == "req"):
                    offenders.append(f"{target}({ast.unparse(arg)})")
    assert not offenders, f"실행 계층에 자칭 행위자를 넘기는 호출: {offenders}"


def test_the_ast_detector_actually_detects():
    """★테스트의 테스트★ — 검출기를 항상-빈-목록으로 바꾸면 위 검사가 무력해진다."""
    import ast

    fake = ast.parse("executor.set_mode(req.mode, req.actor, None)")
    found = []
    for node in ast.walk(fake):
        if isinstance(node, ast.Call) and "set_mode" in ast.unparse(node.func):
            for kw in list(node.args):
                for sub in ast.walk(kw):
                    if (isinstance(sub, ast.Attribute) and sub.attr == "actor"
                            and isinstance(sub.value, ast.Name) and sub.value.id == "req"):
                        found.append(ast.unparse(kw))
    assert found, "검출기가 명백한 위반을 놓친다"
