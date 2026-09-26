"""BK W3 · 거시·타이밍 노드 — 경기 국면 · 타이밍 신호 · ★노출 조절(비중에 적용)★ · 시점별 시뮬레이션
==============================================================================
스펙 `docs/superpowers/specs/2026-09-25-aas-all-tools-nodes-design.md` §2 W3 · §3 ·
대상 `src/api/allocation_graph_nodes_macro.py` · Macro→Allocation 승인 범위: ADR 002 §7

## ★노출 조절이 지키는 것★ (사용자 승인 — 기존 함수만, 규칙·임계값 무변경)
- 강도 100% 의 결과 == `timing_rules_v2.combine` / `macro_overlay.three_way` 가 낸 노출로 부른
  `target_versions.compile_target` (골든). 줄인 만큼은 현금이다(재정규화 없음).
- ★한 방향★ 노출은 줄이기만 한다 — 강도를 낮추면 원래 규칙보다 **덜** 줄고, 어떤 경우에도 100%를 넘지 않는다
  (짝: 강도 0 이면 그대로).
- ★모든 신호를 읽지 못했으면 적용하지 않는다★ — 규칙상 전액 위험-오프가 되지만, 읽지 못한 데이터로 비중을
  0 으로 만들지 않는다(짝: 일부만 못 읽으면 적용하고 그 사실을 말한다).
- 결과 비중은 `overlay` 계보 → 정책 백테스트가 거절(짝: 조절 전 비중은 통과) · 리스크 분해는 된다.
"""
from __future__ import annotations

import os

import numpy as np
import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.api import allocation_graph_nodes as gn  # noqa: E402
from src.engine import portfolio_graph as pg  # noqa: E402
from src.engine.timing_rules_v2 import SignalState as S  # noqa: E402
from tests.test_allocation_graph import _edge, _node, chain, market  # noqa: E402,F401

SNAP = {"snapshot_id": "rs_1", "as_of": "2026-09-20", "regime": "Stagflation", "recommended_mode": "CAUTIOUS",
        "confidence": 0.8, "stress_score": 30.0, "data_status": "partial", "research_usage": "forward_only",
        "explanation": "[Stagflation · 권고 CAUTIOUS]", "phase_probabilities": {"Stagflation": 0.6, "Goldilocks": 0.4}}
RULES = [{"factor_id": "abs_mom"}, {"factor_id": "ma_month"}, {"factor_id": "drawdown"}]


@pytest.fixture()
def snaps(monkeypatch):
    store = {"rs_1": dict(SNAP)}
    monkeypatch.setattr("src.data.regime_snapshots.get_snapshot", lambda sid: store.get(sid))
    monkeypatch.setattr("src.data.regime_snapshots.list_snapshots",
                        lambda limit=50: [{"snapshot_id": k, **{kk: v for kk, v in s.items() if kk != "snapshot_id"}}
                                          for k, s in reversed(list(store.items()))])
    return store


@pytest.fixture()
def states(monkeypatch):
    box = {"states": [S.RISK_ON, S.RISK_OFF, S.RISK_ON]}
    monkeypatch.setattr("src.engine.timing_rules_v2.rule_set_states", lambda rs, **k: list(box["states"]))
    return box


def _run(g):
    return pg.run(g, gn.REGISTRY)


def _values(g, nid):
    return pg._execute(g, gn.REGISTRY)[1][nid]


def _overlay_graph(*, follow="timing", regime=True, timing=True, **params):
    g = chain(risk=False)
    edges = [_edge("o", "weights", "x", "weights")]
    if timing:
        g["nodes"].append(_node("t", "timing_signal", rules=RULES, combination="k_of_n", k=2))
        edges.append(_edge("t", "signal", "x", "signal"))
    if regime:
        g["nodes"].append(_node("g", "regime", snapshot_id="rs_1"))
        edges.append(_edge("g", "regime", "x", "regime"))
    g["nodes"].append(_node("x", "exposure_overlay", follow=follow, **params))
    g["edges"] += edges
    return g


# ── 경기 국면 ────────────────────────────────────────────────────────────────

def test_regime_loads_the_named_snapshot_and_marks_it_forward_only(snaps):
    g = {"format": pg.FORMAT, "version": pg.VERSION, "nodes": [_node("g", "regime", snapshot_id="rs_1")], "edges": []}
    r = _run(g)["nodes"]["g"]
    assert r["status"] == "ok", r["reason"]
    assert r["view"]["regime"] == "Stagflation" and r["lineage"]["pit"] == "forward_only"
    assert r["lineage"]["practice"] is False


def test_regime_without_an_id_uses_the_latest_and_says_so(snaps):
    g = {"format": pg.FORMAT, "version": pg.VERSION, "nodes": [_node("g", "regime")], "edges": []}
    r = _run(g)["nodes"]["g"]
    assert r["status"] == "ok" and any("가장 최근" in f for f in r["explain"]["facts"])


def test_regime_without_any_snapshot_fails_with_guidance(monkeypatch):
    monkeypatch.setattr("src.data.regime_snapshots.list_snapshots", lambda limit=50: [])
    g = {"format": pg.FORMAT, "version": pg.VERSION, "nodes": [_node("g", "regime")], "edges": []}
    r = _run(g)["nodes"]["g"]
    assert r["status"] == "failed" and "매크로" in r["reason"]


def test_a_mock_snapshot_is_practice(snaps):
    snaps["rs_1"]["data_status"] = "mock"
    g = {"format": pg.FORMAT, "version": pg.VERSION, "nodes": [_node("g", "regime", snapshot_id="rs_1")], "edges": []}
    assert _run(g)["nodes"]["g"]["lineage"]["practice"] is True


# ── 타이밍 신호 ──────────────────────────────────────────────────────────────

def test_timing_signal_equals_combine(states):
    from src.engine.timing_rules_v2 import combine
    g = {"format": pg.FORMAT, "version": pg.VERSION,
         "nodes": [_node("t", "timing_signal", rules=RULES, combination="k_of_n", k=2)], "edges": []}
    t = _run(g)["nodes"]["t"]
    assert t["status"] == "ok", t["reason"]
    want = combine(states["states"], method="k_of_n", k=2, weights=None)
    assert t["view"]["composite"]["exposure"] == want.exposure and t["view"]["composite"]["state"] == want.state.value
    assert [f["state"] for f in t["view"]["factor_states"]] == ["risk_on", "risk_off", "risk_on"]
    assert t["lineage"]["pit"] == "forward_only"


def test_an_engine_refusal_is_a_node_failure(monkeypatch):
    def boom(rs, **k):
        raise ValueError("regime_conditioned 는 매크로 오버레이가 필요합니다")
    monkeypatch.setattr("src.engine.timing_rules_v2.rule_set_states", boom)
    g = {"format": pg.FORMAT, "version": pg.VERSION, "nodes": [_node("t", "timing_signal", rules=RULES)], "edges": []}
    t = _run(g)["nodes"]["t"]
    assert t["status"] == "failed" and "매크로 오버레이" in t["reason"]


def test_every_timing_factor_option_is_in_the_catalog():
    from src.engine.timing_factors import CATALOG
    schema = gn.REGISTRY.get("timing_signal").params_model.model_json_schema()
    item = schema["$defs"]["TimingRuleItem"]["properties"]["factor_id"]["x-ui"]["options"]
    assert set(item) == {c["id"] for c in CATALOG}


# ── ★노출 조절★ ──────────────────────────────────────────────────────────────

def _base_pct(g):
    w = _values(g, "o")["weights"]
    return {n: float(x) * 100 for n, x in zip(w["names"], w["weights"])}


def test_full_strength_timing_equals_compile_target(market, states, snaps):
    from src.data.target_versions import compile_target
    from src.engine.timing_rules_v2 import combine
    g = _overlay_graph(follow="timing")
    x = _run(g)["nodes"]["x"]
    assert x["status"] == "ok", x["reason"]
    e = combine(states["states"], method="k_of_n", k=2, weights=None).exposure
    want = compile_target(_base_pct(g), {"exposure": e, "source": x["view"]["source"]})
    assert x["view"]["exposure"] == pytest.approx(e)
    assert x["view"]["after"] == want["final_weights"] and x["view"]["cash_pct"] == want["cash_weight"]


def test_timing_plus_macro_equals_the_three_way_leg(market, states, snaps):
    from src.engine.macro_overlay import overlay_from_snapshot, three_way
    x = _run(_overlay_graph(follow="timing_macro"))["nodes"]["x"]
    assert x["status"] == "ok", x["reason"]
    legs = three_way(states["states"], method="k_of_n", overlay=overlay_from_snapshot(SNAP, enabled=True), k=2)
    assert x["view"]["exposure"] == pytest.approx(legs["timing_macro"].exposure)
    assert x["view"]["legs"]["timing_only"]["exposure"] == pytest.approx(legs["timing_only"].exposure)


@pytest.mark.parametrize("follow,regime,timing,missing", [
    ("timing", True, False, "타이밍 신호"), ("timing_macro", False, True, "경기 국면")])
def test_the_chosen_judgement_needs_its_input(market, states, snaps, follow, regime, timing, missing):
    x = _run(_overlay_graph(follow=follow, regime=regime, timing=timing))["nodes"]["x"]
    assert x["status"] == "failed" and missing in x["reason"]


@pytest.mark.parametrize("strength", [0, 25, 50, 100])
def test_exposure_only_ever_goes_down_and_strength_softens_it(market, states, snaps, strength):
    states["states"] = [S.RISK_OFF, S.RISK_OFF, S.RISK_ON]             # 규칙상 줄인다
    x = _run(_overlay_graph(follow="timing", strength_pct=strength))["nodes"]["x"]["view"]
    base = x["legs"]["timing_only"]["exposure"]
    assert base < 1.0
    assert x["exposure"] == pytest.approx(1 - strength / 100 * (1 - base))
    assert base - 1e-12 <= x["exposure"] <= 1.0
    assert sum(x["after"].values()) + (x["cash_pct"] or 0) == pytest.approx(100.0, abs=0.01)


def test_all_unreadable_signals_do_not_empty_the_portfolio(market, states, snaps):
    states["states"] = [S.UNAVAILABLE] * 3
    x = _run(_overlay_graph(follow="timing"))["nodes"]["x"]
    assert x["status"] == "failed" and "읽지 못" in x["reason"]


def test_some_unreadable_signals_are_applied_and_said(market, states, snaps):
    states["states"] = [S.UNAVAILABLE, S.RISK_ON, S.RISK_ON]
    x = _run(_overlay_graph(follow="timing"))["nodes"]["x"]
    assert x["status"] == "ok"
    assert any("읽지 못한 신호 1개" in t["text"] for t in x["explain"]["trust"])


def test_manual_exposure_is_labelled_as_an_assumption(market, states, snaps):
    x = _run(_overlay_graph(follow="manual", regime=False, timing=False, manual_exposure_pct=70))["nodes"]["x"]
    assert x["status"] == "ok", x["reason"]
    assert x["view"]["exposure"] == pytest.approx(0.7) and "직접" in x["view"]["source"]
    assert any(t["state"] == "assumed" and "근거" in t["text"] for t in x["explain"]["trust"])


def test_an_overlaid_portfolio_cannot_be_backtested_but_its_risk_can_be_split(market, states, snaps):
    g = _overlay_graph(follow="timing")
    g["nodes"] += [_node("k", "risk"), _node("b", "backtest")]
    g["edges"] += [_edge("x", "weights", "k", "weights"), _edge("r", "returns", "b", "returns"),
                   _edge("x", "weights", "b", "weights")]
    rep = _run(g)
    assert rep["nodes"]["x"]["lineage"]["overlay"] is True
    assert rep["nodes"]["k"]["status"] == "ok"
    assert rep["nodes"]["b"]["status"] == "failed" and "노출" in rep["nodes"]["b"]["reason"]
    g2 = chain(backtest={})                                           # 짝 — 조절 전 비중은 통과
    assert _run(g2)["nodes"]["b"]["status"] == "ok"


def test_the_target_status_is_carried_for_execution(market, states, snaps):
    x = _values(_overlay_graph(follow="timing"), "x")["weights"]
    assert x["target"]["status"] in ("executable", "research_only") and x["target"]["overlay"]["source"]


# ── 시점별 시뮬레이션 ─────────────────────────────────────────────────────────

def test_backtest_mode_refuses_forward_only_factors(monkeypatch, states):
    from src.data.pit_macro import ForwardOnlyError

    def sim(rule_set, **k):
        raise ForwardOnlyError("forward_only 팩터: vix_term_structure")
    monkeypatch.setattr("src.engine.timing_simulation.simulate_rule_set", sim)
    g = {"format": pg.FORMAT, "version": pg.VERSION,
         "nodes": [_node("t", "timing_signal", rules=RULES), _node("s", "timing_simulation", mode="backtest")],
         "edges": [_edge("t", "signal", "s", "signal")]}
    s = _run(g)["nodes"]["s"]
    assert s["status"] == "failed" and "vix_term_structure" in s["reason"]


def test_forward_mode_walks_and_says_it_is_not_a_backtest(monkeypatch, states):
    from src.engine.timing_simulation import RuleSetSimulation, SimulationPoint
    pts = [SimulationPoint(months_back=m, as_of=f"2026-0{9 - m}-01", state="risk_on", exposure=1.0, on_count=2,
                           off_count=1, unavailable_count=0, explanation="") for m in range(3)]
    monkeypatch.setattr("src.engine.timing_simulation.simulate_rule_set",
                        lambda rs, **k: RuleSetSimulation(set_id="x", market="kr", combination="all", mode="forward",
                                                          step="month", backtest_eligible=False,
                                                          warning="백테스트가 아닙니다", points=pts))
    g = {"format": pg.FORMAT, "version": pg.VERSION,
         "nodes": [_node("t", "timing_signal", rules=RULES), _node("s", "timing_simulation", mode="forward")],
         "edges": [_edge("t", "signal", "s", "signal")]}
    s = _run(g)["nodes"]["s"]
    assert s["status"] == "ok", s["reason"]
    assert len(s["view"]["result"]["points"]) == 3
    assert any(t["state"] == "unknown" and "백테스트가 아닙니다" in t["text"] for t in s["explain"]["trust"])


# ── 공통 ─────────────────────────────────────────────────────────────────────

def test_every_w3_node_speaks_politely_without_overclaiming(market, states, snaps):
    from tests.test_allocation_graph_explain import FORBIDDEN, _texts
    for follow in ("timing", "timing_macro"):
        rep = _run(_overlay_graph(follow=follow))
        for nid in ("g", "t", "x"):
            r = rep["nodes"][nid]
            assert r["status"] == "ok", (nid, r["reason"])
            assert r["explain"]["title"].endswith("요"), (nid, r["explain"]["title"])
            assert not [t for t in _texts(r["explain"]) for w in FORBIDDEN if w in t], nid


def test_the_overlay_node_never_imports_policy_tables_it_could_change():
    """★승인 범위★ 노출 조절은 `MODE_CAP`·`REGIME_TILTS`·`exposure_cap`·`constrained_solve` 를 **이름으로 쓰지
    않는다**(import·참조·호출 0) — 기존 함수(`three_way`·`compile_target`)만 부른다. 문서 문자열은 세지 않는다."""
    import ast
    import pathlib
    tree = ast.parse(pathlib.Path("src/api/allocation_graph_nodes_macro.py").read_text(encoding="utf-8"))
    banned = {"MODE_CAP", "REGIME_TILTS", "exposure_cap", "constrained_solve"}
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    used |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    used |= {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert not (used & banned), used & banned
    assert {"three_way", "compile_target"} <= used, "짝 — 기존 함수를 실제로 부른다"


@pytest.mark.parametrize("sts,title", [
    ([S.RISK_OFF, S.RISK_OFF, S.RISK_ON], "타이밍 신호는 ‘위험-오프’예요"),
    ([S.RISK_ON, S.RISK_ON, S.RISK_ON], "타이밍 신호는 ‘위험-온’이에요"),
    ([S.UNAVAILABLE] * 3, "신호를 하나도 읽지 못해 규칙상 ‘위험-오프’로 셌어요"),
])
def test_the_timing_title_is_grammatical_and_does_not_hide_unreadable_signals(states, sts, title):
    states["states"] = sts
    g = {"format": pg.FORMAT, "version": pg.VERSION,
         "nodes": [_node("t", "timing_signal", rules=RULES, combination="k_of_n", k=2)], "edges": []}
    assert _run(g)["nodes"]["t"]["explain"]["title"] == title


@pytest.mark.parametrize("regime,title", [("Stagflation", "‘스태그플레이션’으로"), ("Goldilocks", "‘골디락스’로")])
def test_the_regime_title_uses_the_right_particle(snaps, regime, title):
    snaps["rs_1"]["regime"] = regime
    g = {"format": pg.FORMAT, "version": pg.VERSION, "nodes": [_node("g", "regime", snapshot_id="rs_1")], "edges": []}
    assert title in _run(g)["nodes"]["g"]["explain"]["title"]
