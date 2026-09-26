"""BK W2 · 신호·후보 노드 — 스크리너 · 팩터 점수 · 알파 점수 · 점수→비중 · 중립화 · 묶음 합치기
==============================================================================
스펙 `docs/superpowers/specs/2026-09-25-aas-all-tools-nodes-design.md` §2 W2 ·
대상 `src/api/allocation_graph_nodes_signal.py`

## 거는 것
- ★골든★ 팩터 점수 + 점수→비중(균등·틸트) == `/factor-portfolio` · 중립화 == `/neutralize` 의 엔진 ·
  묶음 합치기 == `combine_sleeves` · 수익률 기반 비중 == `_raw_weights_for_model`.
- 스크리너는 `_run_advanced_core` 에 요청을 그대로 넘기고 상위 N 종목만 넘긴다 · 필터 검증 실패는 노드 실패.
- ★오늘 값으로 고른 종목은 과거 검증을 막는다★ — 스크리너 → 수익률 → 비중 → 정책 백테스트 = 거절
  (짝: 같은 종목을 직접 고르면 통과).
- ★조용한 폴백 없음★ — 흔들림을 쓰는 방식에 수익률이 없으면 실패(균등으로 바꾸지 않는다) · 최적화가 안
  풀리면 실패(역변동성으로 바꾸지 않는다).
- 알파: 기준일 없으면 `forward_only`, 있으면 `unknown` · 못 내면 실패 + 사유.
"""
from __future__ import annotations

import os

import numpy as np
import pytest
from fastapi import HTTPException

os.environ.setdefault("KIS_USE_MOCK", "1")

import src.api.allocation_routes as ar  # noqa: E402
from src.api import allocation_graph_nodes as gn  # noqa: E402
from src.api.allocation_routes import FactorPortfolioRequest, FactorSpec, allocation_factor_portfolio  # noqa: E402
from src.engine import portfolio_graph as pg  # noqa: E402
from tests.test_allocation_graph import _edge, _node, chain, market  # noqa: E402,F401
from tests.test_allocation_routes import T3  # noqa: E402
from tests.test_allocation_tools import _fake_rows  # noqa: E402


def _g(nodes, edges):
    return {"format": pg.FORMAT, "version": pg.VERSION, "nodes": nodes, "edges": edges}


def _run(g):
    return pg.run(g, gn.REGISTRY)


def _values(g, nid):
    return pg._execute(g, gn.REGISTRY)[1][nid]


# ── 스크리너 ─────────────────────────────────────────────────────────────────

def _fake_screen(monkeypatch, codes, *, fully_real=False, raises=None):
    seen = {}

    def core(req, progress_cb=None):
        seen["req"] = req
        if raises:
            raise raises
        return {"items": [{"stock_code": c, "corp_name": c, "composite_score": 90 - i} for i, c in enumerate(codes)],
                "total_evaluated": 50, "total_passed": len(codes),
                "data_source": {"fundamentals": "dart_real" if fully_real else "mock",
                                "market_data": "kis_real" if fully_real else "mock", "fully_real": fully_real}}
    monkeypatch.setattr("src.api.screener_routes._run_advanced_core", core)
    return seen


FILTER = {"logic": "AND", "conditions": [{"field": "roe", "op": "gt", "value": 10}], "groups": []}


def test_the_screener_passes_the_request_through_and_keeps_the_top_n(monkeypatch):
    seen = _fake_screen(monkeypatch, [f"{i:06d}" for i in range(1, 13)])
    rep = _run(_g([_node("s", "screener", universe="kospi200", filter_ast=FILTER, top_n=5, sort_by="roe")], []))
    s = rep["nodes"]["s"]
    assert s["status"] == "ok", s["reason"]
    req = seen["req"]
    assert req.universe == "kospi200" and req.custom_tickers is None and req.sort_by == "roe"
    assert req.filter_ast.model_dump()["conditions"][0]["field"] == "roe"
    assert s["view"]["tickers"] == [f"{i:06d}" for i in range(1, 6)]
    assert s["lineage"]["pit"] == "forward_only" and s["lineage"]["practice"] is True


def test_a_real_data_screen_is_not_practice(monkeypatch):
    _fake_screen(monkeypatch, T3, fully_real=True)
    s = _run(_g([_node("s", "screener", top_n=3)], []))["nodes"]["s"]
    assert s["lineage"]["practice"] is False and s["lineage"]["pit"] == "forward_only"


def test_connected_candidates_become_custom_tickers(monkeypatch):
    seen = _fake_screen(monkeypatch, T3)
    _run(_g([_node("u", "universe", tickers=T3), _node("s", "screener", top_n=3)],
            [_edge("u", "universe", "s", "universe")]))
    assert seen["req"].custom_tickers == T3


def test_a_filter_the_server_rejects_is_a_node_failure(monkeypatch):
    _fake_screen(monkeypatch, T3, raises=HTTPException(400, "필터 검증 실패: 알 수 없는 필드"))
    s = _run(_g([_node("s", "screener")], []))["nodes"]["s"]
    assert s["status"] == "failed" and "알 수 없는 필드" in s["reason"]


def test_too_few_matches_fail_instead_of_passing_one_stock(monkeypatch):
    _fake_screen(monkeypatch, ["005930"])
    assert _run(_g([_node("s", "screener")], []))["nodes"]["s"]["status"] == "failed"


def test_every_filter_preset_passes_the_real_validator():
    from src.engine.filter_ast import parse_group
    ui = gn.REGISTRY.get("screener").params_model.model_json_schema()["properties"]["filter_ast"]["x-ui"]
    assert len(ui["presets"]) >= 4
    for pr in ui["presets"]:
        assert parse_group(pr["value"]).validate() is None, pr["label"]


def test_a_screened_universe_cannot_be_backtested_but_a_hand_picked_one_can(monkeypatch, market):
    """★BK0 문지기의 끝에서 끝★ 오늘 값으로 고른 종목의 과거 성과는 미래를 본 계산이다."""
    _fake_screen(monkeypatch, T3)
    g = chain(backtest={})
    g["nodes"] = [n for n in g["nodes"] if n["id"] != "u"] + [_node("u", "screener", top_n=3)]
    rep = _run(g)
    assert rep["nodes"]["o"]["status"] == "ok"
    b = rep["nodes"]["b"]
    assert b["status"] == "failed" and "지금 시점" in b["reason"]
    assert _run(chain(backtest={}))["nodes"]["b"]["status"] == "ok"           # 짝


# ── 팩터 점수 → 비중 == /factor-portfolio ────────────────────────────────────

def _factor_graph(weighting="equal", top_k=5):
    return _g([_node("f", "factor_scores", factors=[{"id": "per"}, {"id": "roe"}]),
               _node("w", "scores_to_weights", top_k=top_k, weighting=weighting)],
              [_edge("f", "scores", "w", "scores")])


@pytest.mark.parametrize("weighting", ["equal", "factor_tilt"])
def test_factor_scores_then_weights_equal_the_factor_portfolio_route(monkeypatch, weighting):
    monkeypatch.setattr(ar, "_factor_sample_rows", lambda n: _fake_rows())
    monkeypatch.setattr("src.data.stock_master.get_stock_name", lambda c: c)
    rep = _run(_factor_graph(weighting))
    w = rep["nodes"]["w"]
    assert w["status"] == "ok", w["reason"]
    route = allocation_factor_portfolio(FactorPortfolioRequest(
        factors=[FactorSpec(id="per"), FactorSpec(id="roe")], top_k=5, weighting=weighting))
    want = {h["code"]: h["weight"] for h in route["holdings"]}
    got = w["view"]["weights"]
    assert set(got) == set(want)
    for c in want:
        assert abs(got[c] - want[c]) < 0.02, (c, got[c], want[c])
    assert rep["nodes"]["f"]["lineage"]["pit"] == "forward_only"


def test_too_few_scored_names_fail(monkeypatch):
    monkeypatch.setattr(ar, "_factor_sample_rows", lambda n: [{"stock_code": "A", "per": 1}])
    assert _run(_factor_graph())["nodes"]["f"]["status"] == "failed"


# ── 점수 → 비중: 폴백 없음 ────────────────────────────────────────────────────

def _scores_graph(weighting, *, with_returns):
    nodes = [_node("u", "universe", tickers=T3), _node("a", "alpha_score"),
             _node("w", "scores_to_weights", top_k=3, weighting=weighting)]
    edges = [_edge("u", "universe", "a", "universe"), _edge("a", "scores", "w", "scores")]
    if with_returns:
        nodes.append(_node("r", "returns", lookback_days=756))
        edges += [_edge("u", "universe", "r", "universe"), _edge("r", "returns", "w", "returns")]
    return _g(nodes, edges)


@pytest.fixture()
def alpha(monkeypatch):
    calls = []

    def score(expr, tickers, as_of=None, price_loader=None):
        calls.append((expr, list(tickers), as_of))
        return {"available": True, "expr": expr, "as_of_requested": as_of, "as_of_effective": as_of or "2026-07-15",
                "scores": {t: float(i) for i, t in enumerate(tickers)}, "n_universe": len(tickers),
                "coverage": len(tickers)}
    monkeypatch.setattr("src.engine.alpha_lab.score_alpha", score)
    return calls


def test_a_return_based_weighting_without_returns_fails_instead_of_equal_weighting(alpha):
    w = _run(_scores_graph("min_var", with_returns=False))["nodes"]["w"]
    assert w["status"] == "failed" and "수익률" in w["reason"] and "균등" in w["reason"]


def test_a_return_based_weighting_uses_the_graph_returns(alpha, market):
    from src.engine.allocation_studio import _cov, _raw_weights_for_model
    g = _scores_graph("min_var", with_returns=True)
    w = _values(g, "w")["weights"]
    r = _values(g, "r")["returns"]["returns"]
    names = w["names"]
    R = r[names].values
    want = _raw_weights_for_model("min_var", R, None, _cov(R) * 252.0)
    np.testing.assert_allclose(w["weights"], np.asarray(want) / np.sum(want), atol=1e-9)
    assert w["sigma_annual"] is not None


def test_an_optimizer_that_does_not_solve_fails_instead_of_inverse_vol(alpha, market, monkeypatch):
    monkeypatch.setattr("src.engine.allocation_studio._raw_weights_for_model", lambda *a, **k: None)
    w = _run(_scores_graph("hrp", with_returns=True))["nodes"]["w"]
    assert w["status"] == "failed" and "역변동성" in w["reason"]


def test_weights_from_scores_feed_the_risk_node_when_returns_are_connected(alpha, market):
    g = _scores_graph("equal", with_returns=True)
    g["nodes"].append(_node("k", "risk"))
    g["edges"].append(_edge("w", "weights", "k", "weights"))
    assert _run(g)["nodes"]["k"]["status"] == "ok"


# ── 알파 ────────────────────────────────────────────────────────────────────

def test_alpha_without_a_date_is_forward_only_and_with_one_is_unknown(alpha):
    today = _run(_scores_graph("equal", with_returns=False))["nodes"]["a"]
    assert today["lineage"]["pit"] == "forward_only"
    g = _scores_graph("equal", with_returns=False)
    g["nodes"][1]["params"] = {"as_of": "2025-06-30"}
    dated = _run(g)["nodes"]["a"]
    assert dated["lineage"]["pit"] == "unknown" and alpha[-1][2] == "2025-06-30"


def test_alpha_that_cannot_score_fails_with_its_reason(monkeypatch):
    monkeypatch.setattr("src.engine.alpha_lab.score_alpha",
                        lambda *a, **k: {"available": False, "reason": "시세 가용 종목 3개 (<8)"})
    a = _run(_scores_graph("equal", with_returns=False))["nodes"]["a"]
    assert a["status"] == "failed" and "(<8)" in a["reason"]


# ── 중립화 · 묶음 합치기 ─────────────────────────────────────────────────────

def test_neutralize_equals_the_engine_and_is_marked_research_only(market, monkeypatch):
    from src.engine import neutralize as nz
    monkeypatch.setattr(nz, "_load_beta", lambda c: {"005930": 1.2, "000660": 1.5, "035420": 0.8}.get(c))
    g = chain(risk=False)
    g["nodes"].append(_node("n", "neutralize", mode="beta"))
    g["edges"].append(_edge("o", "weights", "n", "weights"))
    n = _run(g)["nodes"]["n"]
    assert n["status"] == "ok", n["reason"]
    ow = _values(g, "o")["weights"]
    pct = {k: float(x) * 100 for k, x in zip(ow["names"], ow["weights"])}
    assert n["view"]["result"] == nz.neutralize_portfolio(pct, mode="beta", target_beta=0.0, dollar_neutral=False)
    assert _values(g, "n")["weights"]["neutralized"] is True
    assert any("실행 목표" in t["text"] for t in n["explain"]["trust"])


def test_sleeve_combine_equals_the_engine(market, monkeypatch):
    from src.engine import sleeve_combine as sc
    rng = np.random.default_rng(3)
    ret = {c: list(rng.normal(0.0004, 0.01 + 0.002 * i, 300)) for i, c in enumerate(T3)}
    monkeypatch.setattr(sc, "_load_ret_matrix", lambda sleeves: ret)
    g = chain(risk=False, model="mvo")
    g["nodes"] += [_node("o2", "optimizer", model="min_var"), _node("m", "sleeve_combine", method="inverse_vol")]
    g["edges"] += [_edge("r", "returns", "o2", "returns"), _edge("e", "belief", "o2", "belief"),
                   _edge("o", "weights", "m", "a"), _edge("o2", "weights", "m", "b")]
    m = _run(g)["nodes"]["m"]
    assert m["status"] == "ok", m["reason"]
    sleeves = [{"name": f"묶음 {k}", "weights": {n: float(x) * 100 for n, x in zip(w["names"], w["weights"])}}
               for k, w in (("A", _values(g, "o")["weights"]), ("B", _values(g, "o2")["weights"]))]
    assert m["view"]["result"] == sc.combine_sleeves(sleeves, method="inverse_vol", ret_matrix=ret)


# ── 공통 ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind,stage", [("screener", "signal"), ("factor_scores", "signal"), ("alpha_score", "signal"),
                                        ("scores_to_weights", "build"), ("neutralize", "build"),
                                        ("sleeve_combine", "build")])
def test_every_w2_node_has_its_stage_and_explainer(kind, stage):
    spec = gn.REGISTRY.get(kind)
    assert spec.stage == stage and spec.explain is not None


def test_w2_nodes_never_produce_a_backtestable_policy(alpha, market):
    """점수·중립화·묶음 비중에는 규칙(req)이 없다 — 정책 백테스트는 거절한다(짝은 BK0 테스트)."""
    g = _scores_graph("equal", with_returns=True)
    g["nodes"].append(_node("b", "backtest"))
    g["edges"] += [_edge("r", "returns", "b", "returns"), _edge("w", "weights", "b", "weights")]
    b = _run(g)["nodes"]["b"]
    assert b["status"] == "failed"


def test_every_w2_node_speaks_politely_without_overclaiming(monkeypatch, alpha, market):
    from src.engine import neutralize as nz
    from src.engine import sleeve_combine as sc
    from tests.test_allocation_graph_explain import FORBIDDEN, _texts
    _fake_screen(monkeypatch, T3)
    monkeypatch.setattr(ar, "_factor_sample_rows", lambda n: _fake_rows())
    monkeypatch.setattr(nz, "_load_beta", lambda c: {"005930": 1.2, "000660": 1.5, "035420": 0.8}.get(c))
    rng = np.random.default_rng(3)
    monkeypatch.setattr(sc, "_load_ret_matrix", lambda sleeves: {c: list(rng.normal(0, 0.01, 300)) for c in T3})
    g = _scores_graph("equal", with_returns=True)
    g["nodes"] += [_node("s", "screener", top_n=3), _node("f", "factor_scores"),
                   _node("n", "neutralize"), _node("m", "sleeve_combine")]
    g["edges"] += [_edge("w", "weights", "n", "weights"), _edge("w", "weights", "m", "a"),
                   _edge("n", "weights", "m", "b")]
    rep = _run(g)
    for nid in ("s", "f", "a", "w", "n", "m"):
        r = rep["nodes"][nid]
        assert r["status"] == "ok", (nid, r["reason"])
        assert r["explain"]["title"].endswith("요"), (nid, r["explain"]["title"])
        assert not [t for t in _texts(r["explain"]) for w in FORBIDDEN if w in t], nid


# ★계산 중 DB 쓰기 0★ (BL0) — 이 파일의 모든 그래프 계산이 런타임 쓰기 감시 아래에서 돈다.
from tests.graph_write_guard import graph_write_guard  # noqa: E402,F401

pytestmark = pytest.mark.usefixtures("graph_write_guard")
