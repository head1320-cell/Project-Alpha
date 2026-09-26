"""BK W5 · 기업·가치평가·되짚기 노드 — 기존 문과 같은 수 · 지금 시점 전용은 과거로 가지 않는다
==============================================================================
스펙 `docs/superpowers/specs/2026-09-25-aas-all-tools-nodes-design.md` §2 W5 ·
대상 `src/api/allocation_graph_nodes_strategy.py` (전략 묶음은 `test_allocation_graph_w5_strategy.py`)

## 거는 것
- 기업 전망 → 비중 == `/analyze(use_company_views=True)` — 같은 가중·같은 블록. 옵티마이저는 회사 뷰를
  사용자 뷰와 섞지 않고 `company_views=` 로 넘긴다(공시 `company_views_used` 가 제 몫만 센다).
- 기업 전망·가치평가 점수는 **지금 시점 전용** — 하류 정책 백테스트가 거절한다(짝: 없으면 통과).
- 가치평가 점수 == `/valuation/compare` 행 · 점수 = −괴리율 · ★적정가를 못 낸 종목은 점수에 없다★(미상 ≠ 0).
- 결정 되짚기 == `/attribution/{run_id}` · 없는 기록은 실패 + 사유.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.api import allocation_graph_nodes as gn  # noqa: E402
from src.api.allocation_routes import AnalyzeRequest, run_analyze  # noqa: E402
from src.engine import portfolio_graph as pg  # noqa: E402
from tests.test_allocation_graph import T3, VIEW, _edge, _node, chain, client, market  # noqa: E402,F401

CO_SOURCE = "company_valuation"


def _run(g):
    return pg.run(g, gn.REGISTRY)


def _why(rep):
    return {k: (v["status"], v["reason"]) for k, v in rep["nodes"].items()}


@pytest.fixture()
def co(monkeypatch):
    """결정적 회사 뷰 — 문과 노드가 **같은 함수**를 부르는지(배선)를 본다. 숫자는 아무것도 말하지 않는다."""
    import src.engine.company_views as cv
    calls = []

    def fake_views(codes, prices, *, as_of=None, convergence_years=None, n=None, seed=None):
        calls.append({"codes": list(codes), "as_of": as_of, "years": convergence_years})
        vs = [{"assets": [c], "direction": 1 if i % 2 == 0 else -1, "magnitude_pct": 3.0 + i,
               "confidence": 30.0, "source": cv.SOURCE, "label": f"{c} 밸류에이션 갭",
               "is_mock": True, "confidence_saturated": False, "research_usage": cv._usage()}
              for i, c in enumerate(codes[:2])]
        return vs, {c: {"kind": cv.KIND_NO_PRICE, "reason": "현재가가 없어 갭을 잴 수 없습니다"} for c in codes[2:]}
    monkeypatch.setattr(cv, "company_views", fake_views)
    monkeypatch.setattr(cv, "prices_for", lambda codes: ({c: 50_000.0 for c in codes}, {c: "caller" for c in codes}))
    return calls


def _co_graph(model="bl", views=None, backtest=False):
    g = chain(model=model, views=views, risk=False)
    ids = [n["id"] for n in g["nodes"]]
    g["nodes"].append(_node("c", "company_views"))
    g["edges"] = [e for e in g["edges"] if e["target"] != "o" or e["target_port"] != "views"]
    g["edges"].append(_edge("r", "returns", "c", "returns"))
    if "v" in ids:
        g["edges"].append(_edge("v", "views", "c", "views"))
    g["edges"].append(_edge("c", "views", "o", "views"))
    if backtest:
        g["nodes"].append(_node("b", "backtest"))
        g["edges"] += [_edge("r", "returns", "b", "returns"), _edge("o", "weights", "b", "weights")]
    return g


# ── 기업 전망 ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("model,views", [("bl", None), ("bl", [VIEW]), ("mvo", None)])
def test_company_views_reach_the_optimizer_like_analyze(market, co, model, views):
    rep = _run(_co_graph(model=model, views=views))
    assert rep["ok"], _why(rep)
    ref = run_analyze(AnalyzeRequest(tickers=T3, model=model, views=views, use_company_views=True))
    o, c = rep["nodes"]["o"]["view"], rep["nodes"]["c"]["view"]
    assert o["weights"] == ref["weights"]["optimized"] and o["flow"] == ref["flow"]
    assert o["views_applied"] == ref["views_applied"] and o["skipped_views"] == ref["skipped_views"]
    assert c["views"] == ref["company_views"]["views"] and c["reasons"] == ref["company_views"]["reasons"]
    assert o["company_views_used"] == ref["company_views"]["applied"] == 2


def test_company_views_are_counted_apart_from_my_views(market, co):
    """★섞지 않는다★ 회사 뷰가 사용자 뷰로 넘어가면 공시가 0 이 된다. 짝: 회사 노드 없으면 0."""
    with_co = _run(_co_graph(views=[VIEW]))["nodes"]["o"]["view"]
    without = _run(chain(model="bl", views=[VIEW], risk=False))["nodes"]["o"]["view"]
    assert with_co["company_views_used"] == 2 and without["company_views_used"] == 0
    assert with_co["weights"] != without["weights"]


def test_company_views_use_the_returns_as_of(market, co):
    g = _co_graph()
    g["nodes"][[n["id"] for n in g["nodes"]].index("r")]["params"]["as_of"] = "2024-06-28"
    _run(g)
    assert co[-1]["as_of"] == "2024-06-28" and co[-1]["codes"] == T3


def test_company_views_are_today_only_and_the_backtest_refuses(market, co):
    rep = _run(_co_graph(backtest=True))
    assert rep["nodes"]["c"]["lineage"]["pit"] == "forward_only"
    assert rep["nodes"]["o"]["lineage"]["pit"] == "forward_only"
    assert rep["nodes"]["b"]["status"] == "failed" and "지금 시점" in rep["nodes"]["b"]["reason"]


def test_without_company_views_the_backtest_still_runs(market):
    rep = _run(chain(model="bl", views=[VIEW], risk=False, backtest={}))
    assert rep["nodes"]["b"]["status"] == "ok", _why(rep)


def test_no_company_view_at_all_is_an_honest_failure(market, monkeypatch):
    import src.engine.company_views as cv
    monkeypatch.setattr(cv, "prices_for", lambda codes: ({}, {c: "unavailable" for c in codes}))
    rep = _run(_co_graph())
    assert rep["nodes"]["c"]["status"] == "failed" and "하나도" in rep["nodes"]["c"]["reason"]
    assert "현재가" in rep["nodes"]["c"]["reason"]


# ── 가치평가 점수 ────────────────────────────────────────────────────────────

@pytest.fixture()
def valuation(monkeypatch):
    """세 종목: 싼 것 · 비싼 것 · 재무 없음(엔진이 괴리율 0 · '데이터 없음' 을 낸다)."""
    from src.engine.valuation import valuation_models as vm

    def fake_eval(self, stock_code, current_price, params=None, bsns_year=None, market_cap=None, statement=None):
        gap = {"005930": -20.0, "000660": 12.5}.get(stock_code)
        if gap is None:
            return vm.UnifiedValuation(ticker=stock_code, corp_name=stock_code, current_price=current_price,
                                       intrinsic_value=0, gap_pct=0, verdict="데이터 없음", models=[], is_mock=True)
        iv = current_price / (1 + gap / 100)
        return vm.UnifiedValuation(ticker=stock_code, corp_name=stock_code, current_price=current_price,
                                   intrinsic_value=iv, gap_pct=gap, verdict=vm.gap_pct_to_verdict(gap),
                                   models=[], is_mock=True, financial_summary={"roe_pct": 10.0})
    monkeypatch.setattr(vm.ValuationEngine, "evaluate", fake_eval)
    monkeypatch.setattr(vm.ValuationEngine, "__init__", lambda self, *a, **k: None)
    monkeypatch.setattr("src.engine.company_views.prices_for",
                        lambda codes: ({c: 50_000.0 for c in codes if c != "999999"}, {}))


def _val_graph(tickers=T3, downstream=None):
    g = {"format": pg.FORMAT, "version": pg.VERSION,
         "nodes": [_node("u", "universe", tickers=list(tickers)), _node("s", "valuation_scores")],
         "edges": [_edge("u", "universe", "s", "universe")]}
    if downstream:
        g["nodes"].append(_node("w", "scores_to_weights", top_k=5))
        g["edges"].append(_edge("s", "scores", "w", "scores"))
    return g


def test_valuation_rows_equal_the_compare_route(client, valuation):
    rep = _run(_val_graph())
    assert rep["nodes"]["s"]["status"] == "ok", _why(rep)
    body = client.post("/api/v1/valuation/compare", json={"stocks": [
        {"stock_code": c, "current_price": 50_000.0} for c in T3]}).json()
    assert rep["nodes"]["s"]["view"]["rows"] == body["results"]


def test_the_score_is_minus_the_gap_and_unknown_is_not_zero(valuation):
    s = _run(_val_graph())["nodes"]["s"]["view"]
    assert s["scores"] == {"005930": 20.0, "000660": -12.5}                # 싼 쪽이 높다
    missing = [c for c in T3 if c not in ("005930", "000660")]
    assert all(c not in s["scores"] and "괴리율 0" in s["reasons"][c] for c in missing)


def test_a_stock_without_a_price_is_a_reason_not_a_score(valuation):
    s = _run(_val_graph(tickers=["005930", "999999"]))["nodes"]["s"]["view"]
    assert "999999" not in s["scores"] and "현재가" in s["reasons"]["999999"]


def test_valuation_scores_are_today_only_and_feed_weights(valuation):
    rep = _run(_val_graph(downstream=True))
    assert rep["nodes"]["s"]["lineage"]["pit"] == "forward_only"
    w = rep["nodes"]["w"]
    assert w["status"] == "ok", _why(rep)
    assert list(w["view"]["weights"]) == ["005930", "000660"] and w["lineage"]["pit"] == "forward_only"


def test_valuation_with_no_intrinsic_value_anywhere_fails(valuation):
    rep = _run(_val_graph(tickers=["035420"]))
    assert rep["nodes"]["s"]["status"] == "failed" and "적정가" in rep["nodes"]["s"]["reason"]


# ── 결정 되짚기 ──────────────────────────────────────────────────────────────

@pytest.fixture()
def stored_run(monkeypatch):
    import time

    import src.data.research_runs as rr
    run = {"run_id": "rr_test_1", "kind": "analyze", "name": "테스트 결정", "created_at": time.time() - 40 * 86400,
           "inputs": {}, "outputs": {"weights": {"optimized": {"005930": 60.0, "000660": 40.0}},
                                     "summary": {"portfolio": {"expected_return_pct": 8.0, "volatility_pct": 20.0}}}}
    monkeypatch.setattr(rr, "get_run", lambda rid: run if rid == "rr_test_1" else None)
    return run


def _attr_graph(**params):
    return {"format": pg.FORMAT, "version": pg.VERSION, "nodes": [_node("a", "attribution_review", **params)], "edges": []}


def test_the_review_equals_the_attribution_route(client, stored_run):
    rep = _run(_attr_graph(run_id="rr_test_1", as_of="2026-09-01"))
    a = rep["nodes"]["a"]
    assert a["status"] == "ok", _why(rep)
    body = client.get("/api/v1/allocation/attribution/rr_test_1", params={"as_of": "2026-09-01"}).json()
    got = {k: v for k, v in a["view"].items() if k != "labels"}
    assert got == body and got["as_of"] == "2026-09-01"


def test_an_unknown_record_is_an_honest_failure(stored_run):
    a = _run(_attr_graph(run_id="nope"))["nodes"]["a"]
    assert a["status"] == "failed" and "찾을 수 없습니다" in a["reason"]


# ── 카탈로그 · 말투 ──────────────────────────────────────────────────────────

def test_the_w5_nodes_are_in_the_catalog_with_their_pickers():
    cat = {c["type"]: c for c in gn.REGISTRY.catalog()}
    for t in ("strategy_backtest", "company_views", "valuation_scores", "attribution_review"):
        assert t in cat and cat[t]["savable"] is False
    assert cat["strategy_backtest"]["params_schema"]["properties"]["strategy_ids"]["x-ui"]["source"] == "strategies"
    assert cat["attribution_review"]["params_schema"]["properties"]["run_id"]["x-ui"]["source"] == "research_runs"
    assert cat["company_views"]["stage"] == "belief" and cat["valuation_scores"]["stage"] == "signal"


def test_every_w5_node_speaks_politely_without_overclaiming(market, co, valuation, stored_run):
    from tests.test_allocation_graph_explain import FORBIDDEN, _texts
    reps = [_run(_co_graph())["nodes"]["c"], _run(_val_graph())["nodes"]["s"],
            _run(_attr_graph(run_id="rr_test_1"))["nodes"]["a"]]
    for r in reps:
        assert r["status"] == "ok", r["reason"]
        assert r["explain"]["title"].endswith("요"), r["explain"]["title"]
        assert not [t for t in _texts(r["explain"]) for w in FORBIDDEN if w in t], r["type"]
