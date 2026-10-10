"""BM C1 · 캔버스 위 작은 그림(glance) · 노드별 계산 시간
==============================================================================
설계 `docs/superpowers/specs/2026-09-27-canvas-workspace-design.md` §C1.

## 거는 것
- ★그림은 서버가 만든다★ — 화면은 그리기만 한다(BJ 원칙). 노드 결과에 `glance` 키가 **늘 있다**: 모양이 맞는 dict 이거나 null.
- ★지어내지 않는다★ — 보기가 없거나(막힘·실패) 수가 없으면 null. 점 값은 보기의 값 **그대로**(골든). 수가 아닌 값(NaN·inf)은 null 로
  (모른다는 뜻 — 0 이 아니다). 모양이 틀리면(모르는 종류·점이 너무 많음) 그림 전체를 버린다(부분적으로 지어내지 않는다).
- 그림 함수가 실패해도 **노드 결과는 그대로**(그림만 없다).
- `elapsed_ms` — 실행한 노드(완료·실패)는 0 이상의 수, 실행하지 않은 노드(막힘)는 null.
"""
from __future__ import annotations

import json
import math
import os

import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.api import allocation_graph_nodes as gn  # noqa: E402
from src.engine import portfolio_graph as pg  # noqa: E402
from tests.graph_write_guard import graph_write_guard  # noqa: E402,F401
from tests.test_allocation_graph import T3, _edge, _node, chain, market  # noqa: E402,F401

pytestmark = pytest.mark.usefixtures("graph_write_guard")

P = pg.Port


def _doc(nodes, edges=()):
    return {"format": pg.FORMAT, "version": pg.VERSION, "nodes": list(nodes), "edges": list(edges)}


def _reg(**glances):
    """작은 가짜 레지스트리 — 값 하나를 내는 노드 `src` 와 받는 노드 `dst`."""
    reg = pg.Registry(("Num",))

    def src(inputs, p):
        return pg.NodeOutput(values={"n": 3.0}, view={"xs": {"a": 60.0, "b": 40.0}, "v": 3.0})

    def dst(inputs, p):
        return pg.NodeOutput(values={}, view={"got": inputs["n"]})

    def boom(inputs, p):
        raise pg.NodeFailure("일부러 실패")

    reg.register(pg.NodeSpec("src", "원천", inputs=(), outputs=(P("n", "Num"),), run=src, glance=glances.get("src")))
    reg.register(pg.NodeSpec("dst", "받기", inputs=(P("n", "Num"),), outputs=(), run=dst, glance=glances.get("dst")))
    reg.register(pg.NodeSpec("boom", "실패", inputs=(), outputs=(P("n", "Num"),), run=boom, glance=glances.get("boom")))
    return reg


def _bars(view):
    return {"kind": "bars", "unit": "%", "points": [{"label": k, "value": v} for k, v in view["xs"].items()]}


# ══ 엔진 계약 ═════════════════════════════════════════════════════════════════

def test_every_result_carries_a_glance_key_and_it_is_null_without_a_glance_function():
    rep = pg.run(_doc([_node("s", "src")]), _reg())
    assert "glance" in rep["nodes"]["s"] and rep["nodes"]["s"]["glance"] is None


def test_a_glance_function_draws_from_the_view_as_is():
    rep = pg.run(_doc([_node("s", "src")]), _reg(src=_bars))
    g = rep["nodes"]["s"]["glance"]
    assert g == {"kind": "bars", "unit": "%", "caption": None,
                 "points": [{"label": "a", "value": 60.0}, {"label": "b", "value": 40.0}]}
    json.dumps(rep, allow_nan=False)


def test_non_finite_values_become_null_not_zero():
    def g(v):
        return {"kind": "values", "points": [{"label": "x", "value": math.nan}, {"label": "y", "value": math.inf},
                                             {"label": "z", "value": 1.5}]}
    pts = pg.run(_doc([_node("s", "src")]), _reg(src=g))["nodes"]["s"]["glance"]["points"]
    assert [p["value"] for p in pts] == [None, None, 1.5]


@pytest.mark.parametrize("bad", [
    {"kind": "pie", "points": [{"label": "a", "value": 1}]},                          # 모르는 종류
    {"kind": "bars", "points": [{"label": str(i), "value": i} for i in range(25)]},    # 막대가 너무 많음
    {"kind": "line", "points": [{"label": str(i), "value": i} for i in range(49)]},    # 선이 너무 김
    {"kind": "bars", "points": []},                                                   # 빈 그림
    {"kind": "bars", "points": [{"label": "a", "value": "60"}]},                       # 수가 아닌 값
    {"kind": "bars", "points": [{"label": "a", "value": None}, {"label": "b", "value": None}]},  # 전부 모름
    "not a dict",
])
def test_a_malformed_glance_is_dropped_whole(bad):
    r = pg.run(_doc([_node("s", "src")]), _reg(src=lambda v: bad))["nodes"]["s"]
    assert r["status"] == "ok" and r["glance"] is None


def test_a_glance_function_that_raises_leaves_the_result_intact():
    def bad(view):
        raise KeyError("x")
    r = pg.run(_doc([_node("s", "src")]), _reg(src=bad))["nodes"]["s"]
    assert r["status"] == "ok" and r["view"] == {"xs": {"a": 60.0, "b": 40.0}, "v": 3.0} and r["glance"] is None


def test_a_glance_function_returning_none_means_no_picture():
    r = pg.run(_doc([_node("s", "src")]), _reg(src=lambda v: None))["nodes"]["s"]
    assert r["glance"] is None


def test_failed_and_blocked_nodes_have_no_glance():
    reg = _reg(boom=_bars, dst=lambda v: {"kind": "values", "points": [{"label": "n", "value": v["got"]}]})
    rep = pg.run(_doc([_node("b", "boom"), _node("d", "dst")], [_edge("b", "n", "d", "n")]), reg)
    assert rep["nodes"]["b"]["status"] == "failed" and rep["nodes"]["b"]["glance"] is None
    assert rep["nodes"]["d"]["status"] == "blocked" and rep["nodes"]["d"]["glance"] is None


def test_elapsed_ms_is_measured_for_run_nodes_and_null_for_blocked_ones():
    rep = pg.run(_doc([_node("b", "boom"), _node("d", "dst"), _node("s", "src")], [_edge("b", "n", "d", "n")]), _reg())
    n = rep["nodes"]
    assert isinstance(n["s"]["elapsed_ms"], (int, float)) and n["s"]["elapsed_ms"] >= 0
    assert isinstance(n["b"]["elapsed_ms"], (int, float)) and n["b"]["elapsed_ms"] >= 0   # 실패도 돌았다
    assert n["d"]["elapsed_ms"] is None                                                 # 막힘은 돌지 않았다


def test_caption_is_kept_and_label_is_stringified():
    def g(v):
        return {"kind": "values", "caption": "하루 99%", "points": [{"label": 1, "value": 2}]}
    r = pg.run(_doc([_node("s", "src")]), _reg(src=g))["nodes"]["s"]["glance"]
    assert r["caption"] == "하루 99%" and r["points"] == [{"label": "1", "value": 2.0}]


# ══ 실제 노드 — 그림 = 보기의 값 그대로 ══════════════════════════════════════════

def _chain_report(**kw):
    g = chain(**kw)
    return pg.run(g, gn.REGISTRY)


def test_optimizer_glance_is_its_weights_largest_first(market):
    r = _chain_report(risk=True)["nodes"]["o"]
    assert r["status"] == "ok", r["reason"]
    w = r["view"]["weights"]
    g = r["glance"]
    assert g["kind"] == "bars" and g["unit"] == "%"
    assert [p["value"] for p in g["points"]] == [w[k] for k in sorted(w, key=lambda k: -abs(w[k]))][:8]
    labels = r["view"]["labels"]
    assert g["points"][0]["label"] == labels.get(max(w, key=lambda k: abs(w[k])), max(w, key=lambda k: abs(w[k])))


def test_risk_glance_is_the_risk_contribution(market):
    r = _chain_report(risk=True)["nodes"]["k"]
    pct = r["view"]["risk_contribution_optimized"]["pct"]
    assert sorted(p["value"] for p in r["glance"]["points"]) == sorted(pct.values())


def test_backtest_glance_is_the_equity_curve_thinned_but_keeps_both_ends(market):
    g = chain(risk=False)
    g["nodes"].append(_node("bt", "backtest"))
    g["edges"] += [_edge("r", "returns", "bt", "returns"), _edge("o", "weights", "bt", "weights")]
    r = pg.run(g, gn.REGISTRY)["nodes"]["bt"]
    assert r["status"] == "ok", r["reason"]
    eq, dates, pts = r["view"]["equity_curve"], r["view"]["dates"], r["glance"]["points"]
    assert r["glance"]["kind"] == "line" and 2 <= len(pts) <= 48
    assert pts[0] == {"label": dates[0], "value": eq[0]} and pts[-1] == {"label": dates[-1], "value": eq[-1]}
    idx = [dates.index(p["label"]) for p in pts]
    assert idx == sorted(idx) and all(p["value"] == eq[i] for p, i in zip(pts, idx))


def test_an_unknown_value_in_the_view_stays_unknown_in_the_glance(market):
    """짝 — 보기의 수를 지우면 그림에서도 사라진다(그림이 따로 수를 만들지 않는다)."""
    from src.api import allocation_graph_glance as gl
    view = {"weights": {"A": 60.0, "B": None, "C": 40.0}, "labels": {}}
    g = gl.weights_bars(view)
    assert {p["label"]: p["value"] for p in g["points"]} == {"A": 60.0, "C": 40.0, "B": None}
    assert gl.weights_bars({"weights": {}}) is None and gl.weights_bars({}) is None


def test_the_planned_node_types_have_a_glance_function():
    planned = {"optimizer", "current_weights", "risk", "backtest", "scenario_stress", "custom_scenario", "var_es",
               "mc_var", "frontier", "rolling_sharpe", "company_valuation", "valuation_scores", "screener",
               "corr_stress", "factor_xray", "implement_exposures", "company_driver_mc", "valuation_distribution",
               "exposure_overlay", "alpha_portfolio", "scores_to_weights", "sleeve_combine", "holding_var",
               "yield_curve", "regime", "backtest_load", "strategy_backtest"}
    have = {t for t in gn.REGISTRY.types() if gn.REGISTRY.get(t).glance is not None}
    assert planned <= have, sorted(planned - have)


def test_every_glance_in_a_real_run_is_well_formed_and_json_strict(market):
    g = chain(risk=True)
    extra = [("st", "scenario_stress", {"scenario": "rate_hike_200bp"}), ("ve", "var_es", {}), ("fr", "frontier", {}),
             ("cw", "current_weights", {}), ("cs", "corr_stress", {})]
    for nid, t, p in extra:
        g["nodes"].append(_node(nid, t, **p))
    g["nodes"][0]["params"]["weights"] = {T3[0]: 70.0, T3[1]: 30.0}
    g["edges"] += [_edge("o", "weights", "st", "weights"), _edge("o", "weights", "ve", "weights"),
                   _edge("r", "returns", "ve", "returns"), _edge("r", "returns", "fr", "returns"),
                   _edge("u", "universe", "cw", "universe"), _edge("o", "weights", "cs", "weights"),
                   _edge("r", "returns", "cs", "returns")]
    rep = pg.run(g, gn.REGISTRY)
    json.dumps(rep, allow_nan=False)
    drawn = 0
    for nid, r in rep["nodes"].items():
        gl = r["glance"]
        if gl is None:
            continue
        drawn += 1
        assert gl["kind"] in pg.GLANCE_KINDS
        assert 1 <= len(gl["points"]) <= pg.GLANCE_MAX[gl["kind"]]
        assert any(p["value"] is not None for p in gl["points"])
    assert drawn >= 6


# ══ 선 위 요약(briefs) — 포트 값의 한 줄 ═══════════════════════════════════════
# ★선 라벨도 서버가 쓴다★ — 화면은 `briefs[출력 포트]` 를 선 가운데에 그리기만 한다. 요약 함수가 없는 포트
# 타입은 키가 없다(지어내지 않는다). 요약이 실패하면 그 포트만 빠진다.

def _reg_briefs(**briefs):
    reg = _reg()
    for t, fn in briefs.items():
        reg.set_port_brief(t, fn)
    return reg


def test_every_result_carries_a_briefs_key_empty_without_brief_functions():
    r = pg.run(_doc([_node("s", "src")]), _reg())["nodes"]["s"]
    assert r["briefs"] == {}


def test_a_brief_describes_the_port_value_as_is():
    r = pg.run(_doc([_node("s", "src")]), _reg_briefs(Num=lambda v: f"수 {v:.0f}"))["nodes"]["s"]
    assert r["briefs"] == {"n": "수 3"}


@pytest.mark.parametrize("bad", [lambda v: None, lambda v: "", lambda v: 3, lambda v: 1 / 0, lambda v: "x" * 81])
def test_a_brief_that_is_empty_not_text_too_long_or_raises_is_dropped(bad):
    r = pg.run(_doc([_node("s", "src")]), _reg_briefs(Num=bad))["nodes"]["s"]
    assert r["status"] == "ok" and r["briefs"] == {}


def test_failed_and_blocked_nodes_have_no_briefs():
    reg = _reg_briefs(Num=lambda v: "수")
    rep = pg.run(_doc([_node("b", "boom"), _node("d", "dst")], [_edge("b", "n", "d", "n")]), reg)
    assert rep["nodes"]["b"]["briefs"] == {} and rep["nodes"]["d"]["briefs"] == {}


def test_set_port_brief_refuses_an_undeclared_port_type():
    with pytest.raises(ValueError):
        _reg().set_port_brief("Nope", lambda v: "x")


def test_real_chain_briefs_count_what_flows(market):
    rep = pg.run(chain(risk=True), gn.REGISTRY)
    n = rep["nodes"]
    assert n["u"]["briefs"] == {"universe": f"{len(n['u']['view']['tickers'])}종목"}
    r = n["r"]
    assert r["briefs"]["returns"] == f"{r['view']['n_assets']}종목 · {r['view']['coverage']['n_obs']}일"
    w = n["o"]["view"]["weights"]
    assert n["o"]["briefs"]["weights"] == f"{len(w)}종목 · 합 {sum(w.values()):.0f}%"


def test_weights_brief_says_unknown_sum_instead_of_inventing_one():
    from src.api import allocation_graph_glance as gl
    assert gl.brief_weights({"names": ["A", "B"], "weights": [0.5, float("nan")]}) == "2종목 · 합 모름"
    assert gl.brief_weights({"names": ["A", "B"], "weights": [0.6, 0.4]}) == "2종목 · 합 100%"
    assert gl.brief_weights({"names": [], "weights": []}) is None
    # 0 비중(잡음)은 보유로 세지 않는다 — 카드 막대 수와 같다.
    assert gl.brief_weights({"names": ["A", "B", "C"], "weights": [0.6, 0.4, 0.0]}) == "2종목 · 합 100%"
