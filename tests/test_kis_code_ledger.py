"""AS4 · ★본 것을 센다 — 새 테이블 0개★
==============================================================================
대상: `AuditTrail.kis_code_rows()` · `GET /kill-switch/kis-codes`

## 왜 새 테이블이 아닌가

AR 이 실패마다 `live_audit_trail.context_json` 에 종류·`rt_cd` 를 남기기
시작했고, AS1 이 거기에 `msg_cd` 와 실행 모드를 더했다. 그러니 ★이미 쌓이고
있다★ — 새 카운터를 만들면 같은 사실이 두 곳에 있게 되고, 둘이 어긋날 때
무엇이 진실인지 정하는 문제가 새로 생긴다.

저장소의 관행도 같다: 집계는 **읽기 시점**에 한다
(`audit_trail.daily_summary` · `order_tracker.state_distribution`).

## ★여기서 재는 것과 재지 않는 것★

- 잰다: SQL 이 실패 행만 집어 오는가 · 모드가 살아 오는가 · 라우트가
  ★빈 표에서 gaps 가 곧 observed★ 라고 말하는가.
- 재지 않는다: 코드의 뜻. 표가 비어 있다.
"""
from __future__ import annotations

import ast
import json
import pathlib

import pytest
from sqlalchemy import create_engine, text

from src.execution.audit_trail import AuditTrail

_AUDIT_SRC = pathlib.Path("src/execution/audit_trail.py")
_ROUTES_SRC = pathlib.Path("src/api/stage13_routes.py")


@pytest.fixture()
def audit(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'a.db'}")
    from src.execution.live_schemas import init_live_trading_schema

    init_live_trading_schema(engine)
    return AuditTrail(engine)


def _insert(audit, *, rt_cd="1", msg_cd="X", mode="paper", kind="business",
            ts="2026-09-01 00:00:00", msg1="장 종료",
            event_type="ORDER_FAILED", context=None):
    if context is None:
        context = {"error": "…", "execution_mode": mode,
                   "failure": {"kind": kind, "rt_cd": rt_cd, "msg_cd": msg_cd,
                               "kis_msg": msg1}}
    with audit.engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO live_audit_trail
                (audit_id, event_type, event_category, reason_code,
                 context_json, timestamp)
            VALUES (:aid, :et, 'EXECUTION', :rc, :ctx, :ts)
        """), {"aid": f"a{_insert.n}", "et": event_type, "rc": kind,
               "ctx": json.dumps(context, ensure_ascii=False), "ts": ts})
    _insert.n += 1


_insert.n = 0


# ── ★SQL 은 실패 행만 집어 온다★ ────────────────────────────────────────

def test_it_returns_rows_that_carry_a_failure_block(audit):
    _insert(audit)
    rows = audit.kis_code_rows()
    assert len(rows) == 1
    assert rows[0]["failure"]["msg_cd"] == "X"


def test_it_keeps_the_execution_mode(audit):
    """★모드가 살아 와야 모의와 실계좌를 가를 수 있다★"""
    _insert(audit, mode="live")
    assert audit.kis_code_rows()[0]["execution_mode"] == "live"


def test_it_keeps_the_timestamp(audit):
    _insert(audit, ts="2026-09-05 12:00:00")
    assert audit.kis_code_rows()[0]["timestamp"] is not None


def test_it_skips_rows_without_a_failure_block(audit):
    """변이 — 필터가 실제로 무언가를 거른다(★공허한 분기 금지★)."""
    _insert(audit, context={"error": "…"})
    _insert(audit)
    assert len(audit.kis_code_rows()) == 1


def test_it_skips_rows_whose_context_is_not_json(audit):
    with audit.engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO live_audit_trail
                (audit_id, event_type, event_category, context_json, timestamp)
            VALUES ('bad', 'ORDER_FAILED', 'EXECUTION', '{{{', '2026-09-01')
        """))
    _insert(audit)
    assert len(audit.kis_code_rows()) == 1


def test_it_skips_other_event_types(audit):
    _insert(audit, event_type="ORDER_SUBMITTED")
    assert audit.kis_code_rows() == []


def test_an_empty_log_is_an_empty_list_not_an_error(audit):
    assert audit.kis_code_rows() == []


def test_a_broken_engine_returns_empty_rather_than_raising(tmp_path):
    """저장소 관행 — 조회 실패는 `[]` 다(`query`·`daily_summary` 와 같다)."""
    engine = create_engine(f"sqlite:///{tmp_path / 'missing.db'}")
    assert AuditTrail(engine).kis_code_rows() == []


def test_the_rows_feed_the_fold_without_translation(audit):
    """★SQL 은 여기, 판단은 도메인★ — 접는 쪽이 이 모양을 그대로 받는다."""
    from src.domain.kis_rt_cd import fold_observations

    _insert(audit, msg_cd="A")
    _insert(audit, msg_cd="A")
    _insert(audit, msg_cd="B", mode="live")
    folded = fold_observations(audit.kis_code_rows())
    assert [(f["msg_cd"], f["count"]) for f in folded] == [("A", 2), ("B", 1)]


# ── ★라우트 — 빈 표에서는 gaps 가 곧 observed 다★ ──────────────────────

@pytest.fixture()
def client(monkeypatch, audit, tmp_path):
    from fastapi.testclient import TestClient

    from src.api import stage13_routes as routes

    ev = tmp_path / "ev.json"
    ev.write_text(json.dumps({"schema": 1, "min_grade_to_apply": "K2",
                              "why_empty": "테스트", "codes": {}}),
                  encoding="utf-8")
    monkeypatch.setenv("KIS_RT_CD_EVIDENCE_PATH", str(ev))

    class _Executor:
        def __init__(self):
            self.audit = audit

    monkeypatch.setattr(routes, "get_executor", lambda: _Executor())
    from fastapi import FastAPI

    app = FastAPI()
    app.dependency_overrides[routes.require_login] = lambda: None
    app.include_router(routes.router)
    return TestClient(app), ev


def test_the_route_reports_observed_and_gaps(client, audit):
    c, _ = client
    _insert(audit, msg_cd="A")
    _insert(audit, msg_cd="B")
    body = c.get("/api/v1/live/kill-switch/kis-codes").json()
    assert {o["msg_cd"] for o in body["observed"]} == {"A", "B"}
    assert {g["msg_cd"] for g in body["gaps"]} == {"A", "B"}


def test_the_route_says_the_table_is_empty_and_why(client):
    c, _ = client
    body = c.get("/api/v1/live/kill-switch/kis-codes").json()
    assert body["table"]["size"] == 0
    assert body["table"]["why_empty"]
    assert body["note"]


def test_a_documented_code_leaves_the_gap_list(client, audit):
    """★짝★ — 표가 채워지면 목록이 실제로 줄어든다(공허한 분기가 아니다)."""
    c, ev = client
    _insert(audit, msg_cd="A")
    _insert(audit, msg_cd="B")
    ev.write_text(json.dumps({
        "schema": 1, "min_grade_to_apply": "K2", "why_empty": "테스트",
        "codes": {"1/A": {"rt_cd": "1", "msg_cd": "A", "meaning": "장 종료",
                          "fault": "self", "grade": "K2",
                          "evidence_source": "KIS 문서"}},
    }, ensure_ascii=False), encoding="utf-8")
    body = c.get("/api/v1/live/kill-switch/kis-codes").json()
    assert {o["msg_cd"] for o in body["observed"]} == {"A", "B"}
    assert [g["msg_cd"] for g in body["gaps"]] == ["B"]
    assert body["table"]["size"] == 1


def test_the_route_does_not_claim_a_fault_from_counts(client, audit):
    """★관측 횟수는 뜻의 증거가 아니다★ — 99번 봐도 미상이다."""
    c, _ = client
    for _ in range(99):
        _insert(audit, msg_cd="A")
    body = c.get("/api/v1/live/kill-switch/kis-codes").json()
    assert body["observed"][0]["count"] == 99
    assert body["gaps"][0]["msg_cd"] == "A"
    assert body["gaps"][0]["reason"]


def test_the_route_requires_login():
    """저장소 관행 — 이 라우트는 계좌 이력에서 파생된다."""
    src = _ROUTES_SRC.read_text(encoding="utf-8")
    block = src.split('@router.get("/kill-switch/kis-codes"', 1)[1].split(")", 1)[0]
    assert "require_login" in block


# ── ★문이 표면에 보인다★ (AU) ────────────────────────────────────────

def test_the_route_reports_the_change_gate(client, audit):
    """★이 코드를 카운트에서 뺄 수 있는가★ — 오늘은 전부 막혀 있다."""
    from src.domain.breaker_change_gate import CHANGE_BLOCKED

    c, _ = client
    _insert(audit, msg_cd="A")
    body = c.get("/api/v1/live/kill-switch/kis-codes").json()
    assert body["gate"]["state"] == CHANGE_BLOCKED
    assert body["gate"]["n_allowed"] == 0
    assert body["gate"]["blocked_codes"][0]["unmet"]


def test_the_route_gate_opens_for_a_fully_satisfied_code(client, audit):
    """★짝★ — 조건을 갖추면 표면도 실제로 열린다(항상-거부가 아니다)."""
    from src.domain.breaker_change_gate import (
        CHANGE_ALLOWED,
        MIN_OBSERVATIONS,
    )

    c, ev = client
    for _ in range(MIN_OBSERVATIONS):
        _insert(audit, msg_cd="A", mode="live")
    ev.write_text(json.dumps({
        "schema": 1, "min_grade_to_apply": "K2", "why_empty": "테스트",
        "codes": {"1/A": {"rt_cd": "1", "msg_cd": "A", "meaning": "장 종료",
                          "outage": False, "grade": "K2",
                          "evidence_source": "KIS 문서"}},
    }, ensure_ascii=False), encoding="utf-8")
    body = c.get("/api/v1/live/kill-switch/kis-codes").json()
    assert body["gate"]["state"] == CHANGE_ALLOWED
    assert [x["key"] for x in body["gate"]["allowed_codes"]] == ["1/A"]


# ── ★새 테이블을 만들지 않았다★ ────────────────────────────────────────

def test_no_new_table_was_added_for_this():
    """변이 — 쓰기 경로가 생기면 죽는다. AR 의 '새 카운터 금지' 를 잇는다."""
    ddl = pathlib.Path("src/execution/live_schemas.py").read_text(encoding="utf-8")
    for banned in ("kis_code", "rt_cd", "msg_cd"):
        assert banned not in ddl, f"DDL 에 {banned} 가 생겼다"


def test_the_reader_only_reads():
    """`kis_code_rows` 안에 쓰기 SQL 이 없다."""
    tree = ast.parse(_AUDIT_SRC.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "kis_code_rows")
    body = ast.dump(fn)
    for banned in ("INSERT", "UPDATE", "DELETE", "CREATE", "DROP"):
        assert banned not in body, banned
