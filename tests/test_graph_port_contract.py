"""BT1 · 노드 링크의 관계 — 포트 역할 · 요구값(needs) · 싣는 값(gives) · 과거 시뮬레이션 표시
==============================================================================
스펙 `docs/superpowers/specs/2026-09-30-bt-canvas-procedure-node-link-design.md` §1 ·
대상 `src/api/allocation_graph_roles.py` · `src/engine/portfolio_graph.py`(`Port`·`Gives`) ·
`POST /api/v1/allocation/graph/validate` 의 `needs_unmet` · `src/domain/workflow_gates.py`(`history_types`)

## 거는 것
- ★선언이 참이다★ — 싣는다고 선언한 값은 노드를 실제로 돌리면 실린다. 선언하지 않은 값은 실리지 않는다(짝).
  조건부(`when`)는 입력이 있을 때·없을 때 둘 다 본다.
- `needs_unmet` 은 실패가 **확실할 때만** 나온다(점수→비중 · 수익률 없음 → 흔들림 나눠 보기). 조건부로 줄 수
  있으면 나오지 않는다(짝). 이 판정은 `/validate` 에만 있고 `/run` 결과를 바꾸지 않는다.
- 템플릿이 쓰는 모양(스크리너 → 점수→비중 + 수익률 → 흔들림 나눠 보기)은 오류가 아니다.
- 과거를 돌려 보는 다른 노드가 있으면 거래비용·처음 보는 기간은 "단계가 없어요"(건너뜀)가 아니라 몰라요다(짝).
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.api import allocation_graph_nodes as gn  # noqa: E402
from src.api import allocation_graph_roles as roles  # noqa: E402
from src.api import allocation_graph_routes as routes  # noqa: E402
from src.domain import workflow_gates as wg  # noqa: E402
from src.engine import portfolio_graph as pg  # noqa: E402
from tests.test_allocation_graph import _edge, _node, chain, market  # noqa: E402,F401
from tests.test_allocation_graph_w3 import _overlay_graph, snaps, states  # noqa: E402,F401

F = {"format": pg.FORMAT, "version": pg.VERSION}
KEYS = ("req", "sigma_annual")


def _declared(kind: str, port: str = "weights") -> dict[str, dict]:
    out = gn.REGISTRY.get(kind).output(port)
    return {g.key: g.to_dict() for g in out.gives}


def _values(g, nid):
    return pg._execute(g, gn.REGISTRY)[1][nid]


# ── 선언이 참인가 ────────────────────────────────────────────────────────────

def test_the_optimizer_carries_exactly_what_it_declares(market):
    w = _values(chain(risk=False), "o")["weights"]
    declared = _declared("optimizer")
    assert set(declared) == set(KEYS)
    assert all(w.get(k) is not None for k in declared)


def _scores_weights(returns_value, weighting="equal"):
    spec = gn.REGISTRY.get("scores_to_weights")
    inputs = {"scores": {"scores": {"005930": 2.0, "000660": 1.0, "035420": 0.5}}}
    if returns_value is not None:
        inputs["returns"] = returns_value
    return spec.run(inputs, spec.params_model(top_k=3, weighting=weighting)).values["weights"]


def test_scores_to_weights_carries_the_covariance_only_when_returns_are_wired(market):
    assert _declared("scores_to_weights") == {"sigma_annual": {"key": "sigma_annual", "when": "returns"}}
    ret = _values(chain(risk=False), "r")["returns"]
    assert _scores_weights(ret)["sigma_annual"] is not None
    assert _scores_weights(None)["sigma_annual"] is None                          # ★짝★
    assert _scores_weights(ret)["req"] is None and _scores_weights(None)["req"] is None


def test_the_overlay_passes_the_covariance_through_and_drops_the_rule(market, states, snaps):
    assert _declared("exposure_overlay") == {"sigma_annual": {"key": "sigma_annual", "from": "weights"}}
    g = _overlay_graph(follow="manual", regime=False, timing=False, manual_exposure_pct=70)
    vals = pg._execute(g, gn.REGISTRY)[1]
    assert vals["x"]["weights"]["sigma_annual"] is vals["o"]["weights"]["sigma_annual"]
    assert vals["x"]["weights"]["req"] is None                                    # 선언하지 않은 값은 없다


@pytest.mark.parametrize("kind,wire", [
    ("neutralize", [("o", "weights", "k", "weights")]),
    ("sleeve_combine", [("o", "weights", "k", "a"), ("o2", "weights", "k", "b")]),
    ("portfolio_combine", [("o", "weights", "k", "s1"), ("o2", "weights", "k", "s2")]),
])
def test_producers_that_declare_nothing_carry_nothing(market, kind, wire):
    assert _declared(kind) == {}
    g = chain(risk=False)
    g["nodes"] += [_node("o2", "optimizer", model="min_var"), _node("k", kind)]
    g["edges"] += [_edge("r", "returns", "o2", "returns"), _edge("e", "belief", "o2", "belief")]
    g["edges"] += [_edge(*w) for w in wire]
    rep, vals = pg._execute({**g}, gn.REGISTRY)[:2]
    assert rep["nodes"]["k"]["status"] == "ok", rep["nodes"]["k"]["reason"]
    assert all(vals["k"]["weights"].get(key) is None for key in KEYS)


def test_current_weights_declares_and_carries_nothing(market):
    g = chain(risk=False)
    g["nodes"][0]["params"]["weights"] = {c: 100 / len(g["nodes"][0]["params"]["tickers"])
                                          for c in g["nodes"][0]["params"]["tickers"]}
    g["nodes"].append(_node("c", "current_weights"))
    g["edges"].append(_edge("u", "universe", "c", "universe"))
    w = _values(g, "c")["weights"]
    assert _declared("current_weights") == {} and all(w.get(k) is None for k in KEYS)


def test_every_declared_need_is_given_somewhere():
    given = {g.key for t in gn.REGISTRY.types() for o in gn.REGISTRY.get(t).outputs for g in o.gives}
    needed = {k for t in gn.REGISTRY.types() for i in gn.REGISTRY.get(t).inputs for k in i.needs}
    assert needed and needed <= given


def test_the_needs_match_the_runtime_refusals(market):
    # 각 요구값은 실제 거절과 짝을 이룬다 — 비워 보내면 그 노드가 실패한다.
    assert {(k, p) for (k, p) in roles.NEEDS} == {("backtest", "weights"), ("rebalance_decision", "weights"),
                                                   ("sensitivity", "weights"), ("risk", "weights")}
    spec = gn.REGISTRY.get("risk")
    with pytest.raises(pg.NodeFailure):
        spec.run({"weights": gn.weights_value(["a"], [1.0])}, None)


# ── 편집 순간의 연결 설명 ────────────────────────────────────────────────────

def _g(nodes, edges):
    return {**F, "nodes": nodes, "edges": edges}


SCORE_CHAIN = [_node("u", "universe", tickers=["005930", "000660"]), _node("f", "factor_scores"),
               _node("s", "scores_to_weights"), _node("k", "risk")]
SCORE_EDGES = [_edge("u", "universe", "f", "universe"), _edge("f", "scores", "s", "scores"),
               _edge("s", "weights", "k", "weights")]


def _unmet(rep):
    return [e for e in rep["errors"] if e["code"] == "needs_unmet"]


def test_needs_unmet_speaks_when_failure_is_certain_and_names_the_fix():
    rep = routes.graph_validate(_g(SCORE_CHAIN, SCORE_EDGES))
    [err] = _unmet(rep)
    assert rep["ok"] is False and err["node_id"] == "k" and err["edge_id"] == "s.weights->k.weights"
    assert "공분산" in err["message"] and "실패" in err["message"]
    assert err["fix"] == "‘점수로 비중 정하기’에 ‘수익률’을 이으면 줄 수 있어요."


def test_needs_unmet_is_silent_when_the_value_may_be_given():
    nodes = SCORE_CHAIN + [_node("r", "returns")]
    edges = SCORE_EDGES + [_edge("u", "universe", "r", "universe"), _edge("r", "returns", "s", "returns")]
    rep = routes.graph_validate(_g(nodes, edges))
    assert _unmet(rep) == [] and rep["ok"] is True                                   # ★짝★


def test_a_backtest_needs_the_optimizers_rule():
    nodes = SCORE_CHAIN[:3] + [_node("r", "returns"), _node("b", "backtest")]
    edges = SCORE_EDGES[:2] + [_edge("u", "universe", "r", "universe"), _edge("r", "returns", "s", "returns"),
                               _edge("s", "weights", "b", "weights"), _edge("r", "returns", "b", "returns")]
    [err] = _unmet(routes.graph_validate(_g(nodes, edges)))
    assert err["node_id"] == "b" and "규칙" in err["message"] and err["fix"] == "‘비중 계산’의 비중을 이어 주세요."
    ok = chain(backtest={})
    assert _unmet(routes.graph_validate(ok)) == []                                   # ★짝★ 옵티마이저 비중


def test_the_overlay_forwards_the_covariance_so_its_risk_is_fine():
    g = _overlay_graph(follow="manual", regime=False, timing=False, manual_exposure_pct=70)
    g["nodes"].append(_node("k2", "risk"))
    g["edges"].append(_edge("x", "weights", "k2", "weights"))
    assert _unmet(routes.graph_validate(g)) == []
    g["nodes"].append(_node("nz", "neutralize"))                                      # ★짝★ 중립화는 싣지 않는다
    g["edges"] += [_edge("o", "weights", "nz", "weights")]
    g["nodes"].append(_node("k3", "risk"))
    g["edges"].append(_edge("nz", "weights", "k3", "weights"))
    assert [e["node_id"] for e in _unmet(routes.graph_validate(g))] == ["k3"]


def test_needs_unmet_does_not_change_what_run_reports(market):
    g = _g(SCORE_CHAIN, SCORE_EDGES)
    rep = pg.run(g, gn.REGISTRY)
    assert not any(e.get("code") == "needs_unmet" for e in rep.get("errors") or [])
    assert rep["nodes"]["k"]["status"] in {"failed", "blocked"}                       # 실행의 거절은 그대로


# ── 카탈로그 ─────────────────────────────────────────────────────────────────

def test_the_catalog_carries_roles_needs_and_gives_only_where_declared():
    cat = {c["type"]: c for c in gn.REGISTRY.catalog()}
    risk_in = cat["risk"]["inputs"][0]
    assert risk_in["needs"] == ["sigma_annual"] and risk_in["role"]
    assert cat["optimizer"]["outputs"][0]["gives"] == [{"key": "req"}, {"key": "sigma_annual"}]
    assert "gives" not in cat["neutralize"]["outputs"][0]                              # 없으면 키도 없다
    assert "role" not in next(i for i in cat["estimate"]["inputs"])                    # 확인 못 한 역할은 비운다


def test_every_role_is_a_polite_korean_sentence():
    for (kind, port), role in roles.ROLES.items():
        assert gn.REGISTRY.get(kind).input(port) is not None, (kind, port)
        assert role.endswith(("요.", "요")) and len(role) <= 80, (kind, port, role)


def test_node_types_serves_port_names_and_gate_names():
    body = routes.graph_node_types()
    assert body["port_plain"]["Weights"] == "비중"
    assert [g["key"] for g in body["gates"]] == [k for k, _ in wg.GATES]


# ── 과거 시뮬레이션 표시 · 관문 ─────────────────────────────────────────────

def test_the_history_list_is_fixed_until_a_person_decides():
    flagged = {t for t in gn.REGISTRY.types() if gn.REGISTRY.get(t).simulates_history}
    assert flagged == set(roles.HISTORY)


STAGE = {t: gn.REGISTRY.get(t).stage for t in gn.REGISTRY.types()}
HIST = {t: gn.REGISTRY.get(t).human for t in roles.HISTORY}


def _gate(rep, key):
    return next(g for g in rep["gates"] if g["key"] == key)


def test_a_history_node_turns_cost_and_oos_into_unknown_not_skipped():
    nodes = [{"id": "sb", "type": "strategy_backtest"}]
    rep = wg.evaluate(nodes, {"sb": {"status": "ok"}}, STAGE, history_types=HIST)
    for key in ("cost", "oos"):
        g = _gate(rep, key)
        assert g["state"] == "unknown" and "‘전략 묶음 돌려 보기’가 있지만" in g["reasons"][0]["text"]
        assert g["node_ids"] == ["sb"]
    bare = wg.evaluate([], {}, STAGE, history_types=HIST)                              # ★짝★
    assert _gate(bare, "cost")["state"] == "skipped" and _gate(bare, "cost")["node_ids"] == []


def test_the_policy_backtest_keeps_its_own_verdict_next_to_a_history_node():
    nodes = [{"id": "b", "type": "backtest"}, {"id": "sb", "type": "strategy_backtest"}]
    bt = {"status": "ok", "view": {"config": {"cost_bps": 10.0}}, "provenance": {}}
    rep = wg.evaluate(nodes, {"b": bt, "sb": {"status": "ok"}}, STAGE, history_types=HIST)
    assert _gate(rep, "cost")["state"] == "assumed" and _gate(rep, "cost")["node_ids"] == ["b"]


def test_gates_name_the_nodes_that_fed_them():
    nodes = [{"id": "r", "type": "returns"}, {"id": "o", "type": "optimizer"}]
    res = {"r": {"status": "ok", "view": {}, "provenance": {"source": "mock", "data_grade": "E0"}},
           "o": {"status": "ok", "view": {"constraints_report": None}, "provenance": {}}}
    rep = wg.evaluate(nodes, res, STAGE)
    assert _gate(rep, "data")["node_ids"] == ["r"] and _gate(rep, "build")["node_ids"] == ["o"]
    assert _gate(rep, "economic")["node_ids"] == []
