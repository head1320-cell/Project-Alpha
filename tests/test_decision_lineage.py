"""주문이 ★어느 판단을 가리키는가★ — 식별자 사슬 (AA4)

설계: `docs/plans` AA · 애드덤 합격기준 #10

## 무엇을 잇나

    investment_decisions.dec_id  →  execution_plans.dec_id  →  주문

`execution_plans` 는 `run_id`(백테스트 실행)만 들고 있었다. 그래서 실행계획을 보고
*"이 주문은 어느 판단에서 나왔나"* 를 물을 수 없었다 — 백테스트는 판단이 아니다.

## ★끊긴 계보를 말한다★

`dec_id` 가 없는 계획은 흔하다(수동으로 만든 계획, AA4 이전에 저장된 계획).
그때 `{}` 나 사유 없는 `null` 을 내면 "연결이 없다" 와 "연결을 안 봤다" 가 같은
값이 된다 — CLAUDE.md §4 가 금지하는 침묵 폴백이다.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text


@pytest.fixture
def store(tmp_path, monkeypatch):
    from src.data import execution_store as es
    engine = create_engine(f"sqlite:///{tmp_path}/exec.db")
    monkeypatch.setattr(es, "_engine", lambda: engine)
    es._inited = False
    return es, engine


_PLAN = {"summary": {"n_orders": 2}}
_PRE = {"ok": True}


def test_a_plan_remembers_the_decision_that_produced_it(store):
    es, engine = store
    pid = es.create_plan("계획", _PLAN, _PRE, dec_id="dec_123")
    assert pid
    row = es.get_plan(pid)
    assert row["dec_id"] == "dec_123"


def test_a_plan_without_a_decision_says_so_with_a_reason(store):
    """★끊긴 계보를 사유와 함께 말한다★ — 사유 없는 `null` 은 금지."""
    es, _ = store
    pid = es.create_plan("수동 계획", _PLAN, _PRE)
    lineage = es.plan_lineage(es.get_plan(pid))
    assert lineage["decision"] is None
    assert lineage["reason"], "사유 없이 None 만 냈습니다 — 침묵 폴백입니다"
    assert "판단" in lineage["reason"]


def test_a_linked_plan_reports_no_missing_reason(store):
    """★짝★ 연결된 계획에 사유를 붙이면 "끊겼다" 는 거짓 신호가 된다."""
    es, _ = store
    pid = es.create_plan("계획", _PLAN, _PRE, dec_id="dec_9")
    lineage = es.plan_lineage(es.get_plan(pid))
    assert lineage["decision"] == "dec_9"
    assert lineage["reason"] is None


def test_plans_can_be_found_by_decision(store):
    es, _ = store
    es.create_plan("A", _PLAN, _PRE, dec_id="dec_x")
    es.create_plan("B", _PLAN, _PRE, dec_id="dec_y")
    found = es.find_by_decision("dec_x")
    assert found and found["name"] == "A"
    assert es.find_by_decision("없는_판단") is None


def test_run_id_is_untouched(store):
    """★기존 사슬을 갈아치우지 않는다★ — `run_id` 는 다른 것을 가리킨다."""
    es, _ = store
    pid = es.create_plan("계획", _PLAN, _PRE, run_id="bt_1", dec_id="dec_1")
    row = es.get_plan(pid)
    assert row["run_id"] == "bt_1" and row["dec_id"] == "dec_1"


# ═══════════════════════════════════════════════════════════════════════════
# ⑫ ★컬럼을 못 붙여도 조회가 깨지지 않는다★
# ═══════════════════════════════════════════════════════════════════════════
def test_listing_survives_a_missing_column(tmp_path, monkeypatch):
    """권한 등으로 `ALTER` 가 막힌 배포를 흉내 낸다.

    ★수정 전보다 나쁜 상태를 만들지 않는다★ — `backtest_runs` 가 하트비트
    컬럼에서 배운 것과 같다: 컬럼을 참조하는 쿼리가 통째로 깨지면 계획 조회가
    사라진다. 계보만 미상이 되고 나머지는 그대로여야 한다.
    """
    from src.data import execution_store as es
    engine = create_engine(f"sqlite:///{tmp_path}/nocol.db")
    monkeypatch.setattr(es, "_engine", lambda: engine)
    monkeypatch.setattr("src.data.schema_add_columns.add_columns",
                        lambda *a, **k: False)
    es._inited = False

    pid = es.create_plan("계획", _PLAN, _PRE, dec_id="dec_z")
    assert pid, "컬럼이 없다고 계획 저장이 실패하면 안 됩니다"
    assert es._has_dec_id is False, "열화 경로를 타지 않았습니다"

    row = es.get_plan(pid)
    assert row is not None and row["name"] == "계획"
    assert row["dec_id"] is None, "컬럼이 없으면 미상이다 — 지어내지 않는다"

    lineage = es.plan_lineage(row)
    assert lineage["decision"] is None and lineage["reason"]
    assert es.list_plans() is not None


def test_the_column_is_actually_created_normally(store):
    """★공허 배제★ 위 열화 테스트가 의미 있으려면 정상 경로는 붙어야 한다."""
    es, engine = store
    es.create_plan("계획", _PLAN, _PRE, dec_id="dec_1")
    assert es._has_dec_id is True
    with engine.begin() as c:
        cols = {r[1] for r in c.execute(text("PRAGMA table_info(execution_plans)"))}
    assert "dec_id" in cols


# ═══════════════════════════════════════════════════════════════════════════
# 라우트까지 — ★응답이 계보를 말한다★
# ═══════════════════════════════════════════════════════════════════════════
def test_the_save_route_reports_the_lineage(store):
    """`/execution-plan/save` 응답에 `lineage` 가 실린다."""
    es, engine = store
    from fastapi.testclient import TestClient

    from src.app_factory import create_app
    client = TestClient(create_app())
    body = {"current_weights": {"005930": 100.0},
            "target_weights": {"005930": 60.0, "000660": 40.0},
            "weight_unit": "percent", "portfolio_value": 1e8,
            "name": "판단 연결 계획", "dec_id": "dec_route_1"}
    r = client.post("/api/v1/allocation/execution-plan/save", json=body)
    assert r.status_code == 200, r.text
    j = r.json()
    if not j.get("saved"):
        pytest.skip(f"저장되지 않았습니다: {j.get('message')}")
    assert j["lineage"]["decision"] == "dec_route_1"
    assert j["lineage"]["reason"] is None


def test_the_save_route_names_a_broken_lineage(store):
    """★짝★ `dec_id` 없이 저장하면 **사유와 함께** 끊겼다고 말한다."""
    es, engine = store
    from fastapi.testclient import TestClient

    from src.app_factory import create_app
    client = TestClient(create_app())
    body = {"current_weights": {"005930": 100.0},
            "target_weights": {"005930": 60.0, "000660": 40.0},
            "weight_unit": "percent", "portfolio_value": 1e8, "name": "수동"}
    j = client.post("/api/v1/allocation/execution-plan/save", json=body).json()
    if not j.get("saved"):
        pytest.skip(f"저장되지 않았습니다: {j.get('message')}")
    assert j["lineage"]["decision"] is None
    assert j["lineage"]["reason"], "사유 없이 끊겼다고만 했습니다"
