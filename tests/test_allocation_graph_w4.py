"""BK W4 · 실행·기록 노드 — 주문 목록 미리보기 · 실행 목표 · 결정 기록
==============================================================================
스펙 `docs/superpowers/specs/2026-09-25-aas-all-tools-nodes-design.md` §2 W4 ·
대상 `src/api/allocation_graph_nodes_act.py`

## 거는 것
- ★계산은 쓰지 않는다★ — 세 노드를 모두 돌려도 `save_target`·`create_plan`·`create_entry` 는 한 번도
  불리지 않는다(런타임 — AST 트립와이어와 별개로 동작으로 확인).
- ★저장은 버튼으로 한 번★ — `/graph/save` 가 미리보기 해시가 같을 때만 저장 함수를 **정확히 한 번**
  부르고, 저장된 목표 == 미리보기 목표. 낡은 미리보기는 쓰지 않는다.
- 주문 미리보기 == `/execution-plan` 미리보기(같은 목표·같은 가격).
- ★연습용 데이터로 만든 비중은 실행 목표가 아니다★ — 상태가 연구용으로 내려가고 사유를 말한다
  (짝: 적재 데이터면 실행 가능). 노출 조절 목표는 다시 만들지 않고 그대로 쓴다. 중립화 비중은 연구용.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.api import allocation_graph_nodes as gn  # noqa: E402
from src.api.execution_routes import ExecPlanRequest, execution_plan_preview  # noqa: E402
from src.engine import portfolio_graph as pg  # noqa: E402
from tests.test_allocation_graph import _edge, _node, chain, client, market  # noqa: E402,F401


@pytest.fixture()
def prices(monkeypatch):
    monkeypatch.setattr("src.engine.execution_plan._last_close", lambda code: 50_000.0)
    monkeypatch.setattr("src.engine.execution_plan._adv_won", lambda code: 5e10)


@pytest.fixture()
def writes(monkeypatch):
    calls: dict[str, list] = {"save_target": [], "create_plan": [], "create_entry": []}

    def rec(name, ret):
        def f(*a, **k):
            calls[name].append((a, k))
            return ret
        return f
    monkeypatch.setattr("src.data.target_versions.save_target", rec("save_target", "tpv_test_1"))
    monkeypatch.setattr("src.data.execution_store.create_plan", rec("create_plan", "plan_test_1"))
    monkeypatch.setattr("src.data.journal_store.create_entry", rec("create_entry", "jr_test_1"))
    return calls


def _run(g):
    return pg.run(g, gn.REGISTRY)


def _values(g, nid):
    return pg._execute(g, gn.REGISTRY)[1][nid]


def _act_graph(**target_params):
    g = chain(risk=False)
    g["nodes"] += [_node("q", "order_preview", portfolio_value=1e8), _node("t", "target_version", **target_params),
                   _node("j", "decision_journal", title="테스트 결정", thesis="분산을 늘리려고", decision="adopt")]
    g["edges"] += [_edge("o", "weights", "q", "weights"), _edge("o", "weights", "t", "weights"),
                   _edge("t", "target", "j", "target"), _edge("q", "trades", "j", "trades")]
    return g


# ── 계산은 쓰지 않는다 ────────────────────────────────────────────────────────

def test_running_every_act_node_writes_nothing(market, prices, writes):
    rep = _run(_act_graph())
    for nid in ("q", "t", "j"):
        assert rep["nodes"][nid]["status"] == "ok", (nid, rep["nodes"][nid]["reason"])
    assert writes == {"save_target": [], "create_plan": [], "create_entry": []}


# ── 주문 목록 == /execution-plan ──────────────────────────────────────────────

def test_the_order_preview_equals_the_execution_plan_route(market, prices):
    g = _act_graph()
    q = _run(g)["nodes"]["q"]
    w = _values(g, "o")["weights"]
    target = {n: float(x) * 100 for n, x in zip(w["names"], w["weights"])}
    route = execution_plan_preview(ExecPlanRequest(target_weights=target, weight_unit="percent", portfolio_value=1e8))
    assert q["view"]["plan"] == route["plan"] and q["view"]["pretrade"] == route["pretrade"]


def test_a_turnover_cap_reaches_the_pre_trade_checks(market, prices):
    g = _act_graph()
    g["nodes"][[n["id"] for n in g["nodes"]].index("q")]["params"]["turnover_cap_pct"] = 5
    checks = _run(g)["nodes"]["q"]["view"]["pretrade"]["checks"]
    assert any("회전" in c["name"] and c["status"] in ("warning", "block") for c in checks)


# ── 실행 목표 ────────────────────────────────────────────────────────────────

def test_loaded_data_makes_an_executable_target(market, prices):
    t = _run(_act_graph())["nodes"]["t"]
    assert t["view"]["target"]["status"] == "executable" and t["view"]["graph_blocks"] == []


def test_practice_data_never_makes_an_executable_target(monkeypatch, prices):
    monkeypatch.setenv("KIS_USE_MOCK", "1")                         # 수익률이 mock 폴백 → 연습용 계보
    t = _run(_act_graph())["nodes"]["t"]
    assert t["lineage"]["practice"] is True
    assert t["view"]["target"]["status"] == "research_only"
    assert "연습용" in t["view"]["target"]["status_reason"]


def test_an_overlay_target_is_reused_not_recompiled(market, prices):
    g = chain(risk=False)
    g["nodes"] += [_node("x", "exposure_overlay", follow="manual", manual_exposure_pct=70), _node("t", "target_version")]
    g["edges"] += [_edge("o", "weights", "x", "weights"), _edge("x", "weights", "t", "weights")]
    rep = _run(g)
    tv = rep["nodes"]["t"]["view"]["target"]
    assert tv["overlay"]["exposure"] == pytest.approx(0.7) and "직접" in tv["overlay"]["source"]
    assert tv["final_weights"] == rep["nodes"]["x"]["view"]["after"]


def test_a_neutralized_portfolio_is_research_only(market, prices, monkeypatch):
    from src.engine import neutralize as nz
    monkeypatch.setattr(nz, "_load_beta", lambda c: {"005930": 1.2, "000660": 1.5, "035420": 0.8}.get(c))
    g = chain(risk=False)
    g["nodes"] += [_node("n", "neutralize"), _node("t", "target_version")]
    g["edges"] += [_edge("o", "weights", "n", "weights"), _edge("n", "weights", "t", "weights")]
    tv = _run(g)["nodes"]["t"]["view"]["target"]
    assert tv["status"] == "research_only" and "중립화" in tv["status_reason"]


# ── 저장은 버튼으로 한 번 ─────────────────────────────────────────────────────

def test_saving_the_target_writes_exactly_the_previewed_target_once(client, market, prices, writes):
    g = _act_graph(note="캔버스 테스트")
    t = _run(g)["nodes"]["t"]
    r = client.post("/api/v1/allocation/graph/save", json={"graph": g, "node_id": "t", "preview_hash": t["view_hash"]})
    assert r.status_code == 200 and r.json()["ok"] is True, r.json()
    assert r.json()["saved_id"] == "tpv_test_1" and "실행할 수 있는" in r.json()["text"]
    assert len(writes["save_target"]) == 1
    (tv,), kw = writes["save_target"][0]
    assert tv == t["view"]["target"] and kw["note"] == "캔버스 테스트"
    assert writes["create_entry"] == [] and writes["create_plan"] == []


def test_a_stale_preview_saves_nothing(client, market, prices, writes):
    """본 미리보기와 지금 계산이 다르면(비중을 만든 방식이 바뀜) 쓰지 않는다."""
    t = _run(_act_graph())["nodes"]["t"]
    g2 = _act_graph()
    g2["nodes"][[n["id"] for n in g2["nodes"]].index("o")]["params"]["model"] = "min_var"
    r = client.post("/api/v1/allocation/graph/save", json={"graph": g2, "node_id": "t", "preview_hash": t["view_hash"]})
    assert r.json()["ok"] is False and r.json()["code"] == "stale"
    assert writes["save_target"] == []


def test_saving_the_journal_calls_create_entry_once_with_the_preview(client, market, prices, writes):
    g = _act_graph()
    j = _run(g)["nodes"]["j"]
    r = client.post("/api/v1/allocation/graph/save", json={"graph": g, "node_id": "j", "preview_hash": j["view_hash"]})
    assert r.json()["ok"] is True and r.json()["saved_id"] == "jr_test_1"
    ((title,), kw) = writes["create_entry"][0]
    assert title == "테스트 결정" and kw["record"]["decision"] == "채택" and kw["record"]["thesis"] == "분산을 늘리려고"
    assert kw["links"]["target"]["status"] == "executable" and "orders" in kw["links"]


def test_a_database_that_cannot_write_is_an_honest_failure(client, market, prices, monkeypatch):
    monkeypatch.setattr("src.data.target_versions.save_target", lambda tv, note=None: None)
    g = _act_graph()
    t = _run(g)["nodes"]["t"]
    r = client.post("/api/v1/allocation/graph/save", json={"graph": g, "node_id": "t", "preview_hash": t["view_hash"]})
    assert r.json()["ok"] is False and r.json()["code"] == "save_failed" and "DB" in r.json()["message"]


def test_the_catalog_marks_only_the_record_nodes_savable():
    cat = {c["type"]: c for c in gn.REGISTRY.catalog()}
    assert {t for t, c in cat.items() if c["savable"]} == {"target_version", "decision_journal"}


# ── 공통 ─────────────────────────────────────────────────────────────────────

def test_every_act_node_speaks_politely_without_overclaiming(market, prices):
    from tests.test_allocation_graph_explain import FORBIDDEN, _texts
    rep = _run(_act_graph())
    for nid in ("q", "t", "j"):
        r = rep["nodes"][nid]
        assert r["explain"]["title"].endswith("요"), (nid, r["explain"]["title"])
        assert not [t for t in _texts(r["explain"]) for w in FORBIDDEN if w in t], nid
        assert gn.REGISTRY.get(r["type"]).stage == "act"


# ★계산 중 DB 쓰기 0★ (BL0) — 이 파일의 모든 그래프 계산이 런타임 쓰기 감시 아래에서 돈다.
from tests.graph_write_guard import graph_write_guard  # noqa: E402,F401

pytestmark = pytest.mark.usefixtures("graph_write_guard")
