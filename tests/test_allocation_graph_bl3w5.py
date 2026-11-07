"""BL3 W5 · 배분 추가 노드 — 리밸런싱 판단 · 노출 → 상품 · 페어 · 시장 충격 · 현금 수익 · 전략 용량 · 멀티전략 반사실
==============================================================================
계획 `happy-percolating-falcon.md` §BL3 W5. 대상 `src/api/allocation_graph_nodes_alloc_extra.py`.

## 거는 것
- 골든 — 노드는 라우트 함수를 **같은 요청으로** 부른다(노드 == 라우트).
- ★계산 중 쓰기 0★ — 리밸런싱 판단은 `record_decision=False` 를 명시한다(기본도 거짓이지만 기본에 기대지 않는다).
  기록은 저장 버튼만 — 기록 없이 다시 계산해 미리보기와 같을 때만 기록한다.
- 편익을 모르면 판단 `undetermined` 그대로(거래 안 함으로 바꾸지 않는다) · 편익이 목표를 고른 사후분포로 잰 것이면 그 사실을 설명한다.
- 노출 → 상품: 구현 못 한 노출은 재분배하지 않는다(`unplaced_pct`) · 아무것도 못 놓으면 사유 실패.
- 현금 수익: 금리가 기본값이면 '가정' 으로 말한다(BL3 M7) · 비중을 이으면 투자 비중 = Σ|w|(1 이하).
- 용량·반사실: 멀티전략 문(503·422)의 사유를 그대로 노드 실패로 · 용량을 모르면 무한대가 아니라 '모름'.
"""
from __future__ import annotations

import json
import os

import numpy as np
import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.api import allocation_graph_nodes as gn  # noqa: E402
from src.engine import portfolio_graph as pg  # noqa: E402
from tests.graph_write_guard import graph_write_guard  # noqa: E402,F401
from tests.test_allocation_graph import T3, _edge, _node, chain, market  # noqa: E402,F401

pytestmark = pytest.mark.usefixtures("graph_write_guard")

KINDS = ("rebalance_decision", "implement_exposures", "pair_spread", "market_impact", "cash_yield",
         "strategy_capacity", "counterfactual")
HOLD = [{"code": "005930", "pct": 50.0}, {"code": "000660", "pct": 30.0}, {"code": "035420", "pct": 20.0}]


def _run(g):
    return pg.run(g, gn.REGISTRY)


def _one(kind, **params):
    return _run({"format": pg.FORMAT, "version": pg.VERSION, "nodes": [_node("c", kind, **params)], "edges": []})


def _rebal_graph(**params):
    g = chain(risk=False)
    g["nodes"].append(_node("x", "rebalance_decision", **{"holdings": HOLD, **params}))
    g["edges"].append(_edge("o", "weights", "x", "weights"))
    return g


def _route_req(g, **over):
    """그래프가 만든 비중과 같은 요청 — 노드 코드를 거치지 않고 여기서 조립한다."""
    from src.api.allocation_routes import RebalanceDecisionRequest
    vals = pg._execute(g, gn.REGISTRY)[1]
    w = vals["o"]["weights"]
    target = {n: float(x) * 100 for n, x in zip(w["names"], np.asarray(w["weights"], dtype=float))}
    base = w["req"].model_dump()
    return RebalanceDecisionRequest(**{**base, "holdings": {h["code"]: h["pct"] for h in HOLD}, "weight_unit": "percent",
                                       "portfolio_value": 1e8, "target_weights": target, "horizon_days": 63,
                                       "hysteresis_mult": 0.5, "record_decision": False, **over})


def test_the_seven_nodes_are_registered():
    assert set(KINDS) <= set(gn.REGISTRY.types())


# ══ 리밸런싱 판단 ═══════════════════════════════════════════════════════════

def test_rebalance_decision_equals_the_route_without_recording(market):
    from src.api.allocation_routes import rebalance_decision_route
    g = _rebal_graph()
    r = _run(g)["nodes"]["x"]
    assert r["status"] == "ok", r["reason"]
    ref = rebalance_decision_route(_route_req(g))
    got = r["view"]["result"]
    assert got["decision"] == ref["decision"] and got["benefit"] == ref["benefit"] and got["cost"] == ref["cost"]
    assert got["persisted"] is False and got["dec_id"] is None                  # 계산은 기록하지 않는다
    json.dumps(r["view"], allow_nan=False)


@pytest.mark.parametrize("self_ref", [True, False])
def test_rebalance_decision_says_the_benefit_is_self_referential_only_when_it_is(market, monkeypatch, self_ref):
    import src.api.allocation_routes as ar
    real = ar.rebalance_decision_route

    def fake(req):
        out = real(req)
        b = dict(out.get("benefit") or {})
        b["provenance"] = {"self_referential": self_ref}
        return {**out, "benefit": b}
    monkeypatch.setattr(ar, "rebalance_decision_route", fake)
    r = _run(_rebal_graph())["nodes"]["x"]
    said = any("고른" in t["text"] for t in r["explain"]["trust"])
    assert said is self_ref                                                  # 짝: 자기 참조가 아니면 말하지 않는다


def test_rebalance_decision_needs_weights_that_carry_a_rule():
    spec = gn.REGISTRY.get("rebalance_decision")
    inputs = {"weights": {"names": ["005930"], "weights": np.array([1.0]), "req": None}}
    with pytest.raises(pg.NodeFailure, match="비중 계산"):
        spec.run(inputs, spec.params_model(holdings=HOLD))


def test_rebalance_decision_without_holdings_fails_with_a_reason(market):
    r = _run(_rebal_graph(holdings=[]))["nodes"]["x"]
    assert r["status"] == "failed" and "지금 들고" in r["reason"]


def test_undetermined_is_kept_not_turned_into_hold(market, monkeypatch):
    import src.api.allocation_routes as ar
    real = ar.rebalance_decision_route

    def fake(req):
        out = real(req)
        return {**out, "decision": "undetermined", "benefit": {"available": False, "reason": "편익 모름"}}
    monkeypatch.setattr(ar, "rebalance_decision_route", fake)
    r = _run(_rebal_graph())["nodes"]["x"]
    assert r["view"]["result"]["decision"] == "undetermined"
    assert "판단할 수 없어요" in r["explain"]["title"]


def test_saving_records_once_after_matching_the_preview(market, monkeypatch):
    import src.api.allocation_routes as ar
    calls = []
    real = ar.rebalance_decision_route

    def spy(req):
        calls.append(req.record_decision)
        out = real(req.model_copy(update={"record_decision": False}))
        return {**out, "dec_id": "dec_test" if req.record_decision else None, "persisted": bool(req.record_decision)}
    monkeypatch.setattr(ar, "rebalance_decision_route", spy)
    g = _rebal_graph()
    rep = _run(g)
    assert calls == [False]
    spec = gn.REGISTRY.get("rebalance_decision")
    vals = pg._execute(g, gn.REGISTRY)[1]
    params = spec.params_model(holdings=HOLD)
    saved = spec.save({"weights": vals["o"]["weights"]}, rep["nodes"]["x"]["view"], params)
    assert saved["saved_id"] == "dec_test" and calls[-2:] == [False, True]


def test_saving_refuses_when_the_route_disagrees_with_the_preview(market, monkeypatch):
    import src.api.allocation_routes as ar
    real = ar.rebalance_decision_route
    g = _rebal_graph()
    view = _run(g)["nodes"]["x"]["view"]
    monkeypatch.setattr(ar, "rebalance_decision_route",
                        lambda req: {**real(req.model_copy(update={"record_decision": False})), "decision": "hold"}
                        if view["result"]["decision"] != "hold" else {**real(req), "decision": "trade"})
    spec = gn.REGISTRY.get("rebalance_decision")
    vals = pg._execute(g, gn.REGISTRY)[1]
    with pytest.raises(pg.NodeFailure, match="다른"):
        spec.save({"weights": vals["o"]["weights"]}, view, spec.params_model(holdings=HOLD))


# ══ 노출 → 상품 ═════════════════════════════════════════════════════════════

def test_implement_exposures_equals_the_route_and_outputs_weights():
    from src.api.allocation_routes import ImplementExposuresRequest, implement_exposures_route
    rows = [{"exposure": "equity", "pct": 60.0}, {"exposure": "duration", "pct": 30.0}]
    rep = _one("implement_exposures", exposures=rows)
    r = rep["nodes"]["c"]
    assert r["status"] == "ok", r["reason"]
    ref = implement_exposures_route(ImplementExposuresRequest(exposures={"equity": 60.0, "duration": 30.0}))
    assert r["view"]["result"] == json.loads(json.dumps(ref, default=str))
    vals = pg._execute({"format": pg.FORMAT, "version": pg.VERSION,
                        "nodes": [_node("c", "implement_exposures", exposures=rows)], "edges": []}, gn.REGISTRY)[1]
    w = vals["c"]["weights"]
    assert dict(zip(w["names"], [round(float(x) * 100, 6) for x in w["weights"]])) == ref["holdings"]
    assert w["sigma_annual"] is None                                            # 지어내지 않는다 — 하류 위험 분해는 사유로 실패
    assert r["view"]["result"]["unplaced_pct"] == ref["unplaced_pct"]           # 놓지 못한 비중은 라우트 규칙 그대로(재분배 없음)


def test_implement_exposures_with_nothing_placed_fails():
    r = _one("implement_exposures", exposures=[{"exposure": "equity", "pct": 0.0}])
    assert r["nodes"]["c"]["status"] == "failed"


def test_implement_exposures_publishes_literal_default_rows():
    sch = gn.REGISTRY.get("implement_exposures").params_model.model_json_schema()
    assert len(sch["properties"]["exposures"]["default"]) >= 2


# ══ 페어 · 시장 충격 · 현금 ═════════════════════════════════════════════════

def test_pair_spread_equals_the_route():
    from src.api.sleeve_routes import PairSpreadRequest, pair_spread
    r = _one("pair_spread", long_code="005930", short_code="000660")["nodes"]["c"]
    ref = pair_spread(PairSpreadRequest(long_code="005930", short_code="000660"))
    if ref.get("error"):
        assert r["status"] == "failed" and ref["message"] in r["reason"]
    else:
        assert r["status"] == "ok" and {k: v for k, v in r["view"]["result"].items() if k != "inputs"} == ref


def test_pair_spread_with_a_manual_ratio_is_labelled_assumed():
    r = _one("pair_spread", long_code="005930", short_code="000660", hedge_ratio=0.8)["nodes"]["c"]
    assert r["status"] == "ok", r["reason"]
    hr = next(i for i in r["view"]["result"]["inputs"] if i["key"] == "hedge_ratio")
    assert hr["basis"] == "가정"


def test_market_impact_equals_the_route():
    from src.api.stage12_routes import MarketImpactRequest, realism_market_impact
    r = _one("market_impact", order_value_krw=5e8, adv_krw=2e10, daily_volatility=0.02)["nodes"]["c"]
    ref = realism_market_impact(MarketImpactRequest(order_value_krw=5e8, adv_krw=2e10, daily_volatility=0.02))
    assert r["status"] == "ok", r["reason"]
    assert r["view"]["result"]["total_impact_bps"] == ref["total_impact_bps"]
    assert {i["basis"] for i in r["view"]["result"]["inputs"]} == {"가정"}


def test_cash_yield_labels_a_default_rate_as_assumed(monkeypatch):
    from src.engine import cash_management as cm
    monkeypatch.setattr(cm.CashRateProvider, "get_rate_with_source", lambda self, ts: (0.035, "default"))
    r = _one("cash_yield", invested_ratio=0.7)["nodes"]["c"]
    assert r["status"] == "ok", r["reason"]
    rf = next(i for i in r["view"]["result"]["inputs"] if i["key"] == "rf")
    assert rf["basis"] == "가정" and "저장된 금리" in rf["source"]
    # 짝: 관측 금리면 관측
    monkeypatch.setattr(cm.CashRateProvider, "get_rate_with_source", lambda self, ts: (0.034, "CD91"))
    r2 = _one("cash_yield", invested_ratio=0.7)["nodes"]["c"]
    assert next(i for i in r2["view"]["result"]["inputs"] if i["key"] == "rf")["basis"] == "관측"


def test_cash_yield_from_connected_weights_uses_gross_capped_at_one(market):
    g = chain(risk=False)
    g["nodes"].append(_node("y", "cash_yield"))
    g["edges"].append(_edge("o", "weights", "y", "weights"))
    r = _run(g)["nodes"]["y"]
    assert r["status"] == "ok", r["reason"]
    vals = pg._execute(g, gn.REGISTRY)[1]
    gross = min(1.0, float(np.abs(np.asarray(vals["o"]["weights"]["weights"], dtype=float)).sum()))
    assert r["view"]["result"]["cash_ratio"] == pytest.approx(round(1 - gross, 4))


# ══ 멀티전략 — 용량 · 반사실 ════════════════════════════════════════════════

def test_capacity_without_strategies_fails():
    r = _one("strategy_capacity", strategy_ids=[])["nodes"]["c"]
    assert r["status"] == "failed" and "전략" in r["reason"]


def test_capacity_of_an_unknown_strategy_is_unknown_not_infinite():
    r = _one("strategy_capacity", strategy_ids=[987654])["nodes"]["c"]
    assert r["status"] == "ok", r["reason"]
    cap = r["view"]["result"]["capacities"]
    row = cap.get("987654") or cap.get(987654)
    assert row["available"] is False and row["capacity_krw"] is None
    json.dumps(r["view"], allow_nan=False)


def test_counterfactual_passes_the_multistrategy_door_reason_through(monkeypatch):
    from fastapi import HTTPException

    import src.api.stage11_routes as s11

    def closed(**kw):
        raise HTTPException(503, detail={"available": False, "reason": "멀티전략 코어가 없어요(테스트)"})
    monkeypatch.setattr(s11, "_guard", closed)
    r = _one("counterfactual", strategy_ids=[1, 2])["nodes"]["c"]
    assert r["status"] == "failed" and "멀티전략 코어가 없어요" in r["reason"]


def test_counterfactual_does_not_persist_runs():
    """반사실은 `bt.run` 만 부른다 — 실행을 저장하는 `run_and_save` 를 부르지 않는다(구조 확인: 이 환경엔 등록된 전략이 없어
    실제 실행으로는 저장 경로까지 가지 못한다 — 그래서 호출 자체를 소스에서 본다)."""
    import ast
    import inspect

    from src.engine.counterfactual_analyzer import CounterfactualAnalyzer
    tree = ast.parse(inspect.getsource(CounterfactualAnalyzer.compare).lstrip())
    called = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert "run" in called and "run_and_save" not in called and "_persist" not in called


def test_counterfactual_with_every_scenario_failing_is_a_failure_not_a_result():
    """전략이 없으면 시나리오마다 '미존재' 로 실패한다 — 그런 비교를 '완료' 로 보이지 않는다."""
    r = _one("counterfactual", strategy_ids=[987654])["nodes"]["c"]
    assert r["status"] == "failed" and "하나도" in r["reason"]


@pytest.mark.parametrize("weights,cash", [([0.6, -0.2], 0.2), ([0.9, 0.4], 0.0)])
def test_cash_yield_invested_share_is_gross_and_capped(weights, cash, monkeypatch):
    """롱숏이면 절댓값 합(0.6 + 0.2 → 현금 0.2 · 순합 0.4 가 아니다) · 합이 1 을 넘으면 1(현금 0)."""
    from src.engine import cash_management as cm
    monkeypatch.setattr(cm.CashRateProvider, "get_rate_with_source", lambda self, ts: (0.03, "CD91"))
    spec = gn.REGISTRY.get("cash_yield")
    out = spec.run({"weights": {"names": ["A", "B"], "weights": np.array(weights)}}, spec.params_model())
    assert out.view["result"]["cash_ratio"] == pytest.approx(cash)
