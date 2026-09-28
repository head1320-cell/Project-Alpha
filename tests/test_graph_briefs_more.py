"""BN N2 · 선 위 요약을 더 많은 포트 타입으로 — ★값 모양은 생산 노드에서 확인한 것만★
==============================================================================
BM C1 은 종목·수익률·비중 세 타입만 선 위에 한 줄을 썼다. 여기서는 생산 노드를 실제로 돌려 **값 모양을 확인한** 타입만 더한다
(생각 · 점수 · 경기 국면 · 타이밍 신호 · 주문 목록 · 실행 목표 · 과거 성과 · 위험 나눔).

## 거는 것
- 골든(실제 실행) — 생산 노드가 낸 포트 값을 엿보아(spy) 테스트가 **값에서 직접** 기대 글을 다시 만든다. 선 요약 = 그 글.
  생산 노드의 모양이 바뀌면 요약이 빠져 이 테스트가 실패한다(조용히 틀린 글을 쓰지 않는다).
- 짝 — 모양이 틀리거나(키 없음·수가 아님·빈 목록) 모르는 상태 값이면 요약하지 않는다(None). 0 으로 채우지 않는다.
- 요약하지 않는 타입(기대 수익 설정 · 시나리오 · 전략 묶음 성과 · 백테스트 실행)은 선 요약 함수가 없다 —
  기본 실행에서 값을 확인하지 못해 쓰지 않았다. 충격 결과는 BO O4 에서 더했다(tests/test_graph_stress_briefs.py).
"""
from __future__ import annotations

import math
import os

import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.api import allocation_graph_glance as gl  # noqa: E402
from src.api import allocation_graph_nodes as gn  # noqa: E402
from src.engine import portfolio_graph as pg  # noqa: E402
from tests.graph_write_guard import graph_write_guard  # noqa: E402,F401
from tests.test_allocation_graph import T3, _edge, _node, chain, market  # noqa: E402,F401

pytestmark = pytest.mark.usefixtures("graph_write_guard")

NEW = ("Views", "Scores", "RegimeState", "TimingSignal", "Trades", "TargetVersion", "BacktestResult", "RiskReport")
# 충격 결과(StressReport)는 BO O4 에서 생산 노드 셋의 모양을 확인해 더했다 — tests/test_graph_stress_briefs.py.
NOT_SUMMARISED = ("Belief", "Scenario", "StrategyResult", "BacktestRun")


def test_the_new_port_types_have_a_brief_and_the_unconfirmed_ones_do_not():
    assert set(NEW) <= set(gl.BRIEFS), sorted(set(NEW) - set(gl.BRIEFS))
    assert not set(NOT_SUMMARISED) & set(gl.BRIEFS)
    assert set(gl.BRIEFS) <= set(gn.PORT_TYPES)


# ══ 기대 글 — 테스트가 값에서 직접 만든다(요약 함수를 부르지 않는다) ══════════════════════════════

_PHASE = {"Goldilocks": "골디락스", "Reflation": "리플레이션", "Stagflation": "스태그플레이션",
          "Deflation": "디플레이션", "Disinflation": "디스인플레이션"}


def _expect(port_type: str, v) -> str:
    if port_type == "Views":
        return f"생각 {len(v)}개"
    if port_type == "Scores":
        s = v["scores"]
        unknown = sum(1 for x in s.values() if not (isinstance(x, (int, float)) and math.isfinite(x)))
        return f"{len(s)}종목 점수" + (f" · {unknown}개 모름" if unknown else "")
    if port_type == "RegimeState":
        p = v["phase_probabilities"]
        top = max(p, key=p.get)
        return f"{_PHASE.get(top, top)} {p[top] * 100:.0f}%"
    if port_type == "TimingSignal":
        vals = [getattr(s, "value", s) for s in v["states"]]
        parts = [f"{name} {vals.count(k)}" for k, name in
                 (("risk_on", "위험-온"), ("risk_off", "위험-오프"), ("unavailable", "판단 불가")) if vals.count(k)]
        return " · ".join([f"신호 {len(vals)}개", *parts])
    if port_type == "Trades":
        s = v["plan"]["summary"]
        return f"주문 {s['n_orders']}건 · 매수 {s['n_buy']} · 매도 {s['n_sell']}"
    if port_type == "TargetVersion":
        tv = v["tv"]
        held = sum(1 for x in tv["final_weights"].values() if abs(x) > 1e-9)
        kind = "실행할 수 있는 목표" if tv["status"] == "executable" else "연구용 목표"
        return f"{kind} · {held}종목 · 현금 {tv['cash_weight']:.0f}%"
    if port_type == "BacktestResult":
        d = v["dates"]
        return f"{len(d)}일 · {d[0]}~{d[-1]}"
    if port_type == "RiskReport":
        return f"연 변동성 {v['risk_contribution_optimized']['portfolio_volatility_pct']:.1f}%"
    raise AssertionError(port_type)


def _spy(monkeypatch):
    seen: dict[str, list[tuple[str, str, object]]] = {}
    orig = pg._briefs_ok

    def spy(spec, values, registry):
        for p in spec.outputs:
            if p.name in values:
                seen.setdefault(p.type, []).append((spec.type, p.name, values[p.name]))
        return orig(spec, values, registry)
    monkeypatch.setattr(pg, "_briefs_ok", spy)
    return seen


def test_real_producers_briefs_equal_the_text_rebuilt_from_their_values(market, monkeypatch):
    seen = _spy(monkeypatch)
    g = chain(risk=True, weights={T3[0]: 50.0, T3[1]: 30.0, T3[2]: 20.0})
    add = [("vw", "views", {}), ("cv", "company_views", {}), ("vs", "valuation_scores", {}), ("rg", "regime", {}),
           ("ts", "timing_signal", {}), ("op", "order_preview", {}), ("tv", "target_version", {}), ("bt", "backtest", {})]
    g["nodes"] += [_node(i, t, **p) for i, t, p in add]
    g["edges"] += [_edge("r", "returns", "cv", "returns"), _edge("u", "universe", "vs", "universe"),
                   _edge("o", "weights", "op", "weights"), _edge("o", "weights", "tv", "weights"),
                   _edge("r", "returns", "bt", "returns"), _edge("o", "weights", "bt", "weights")]
    rep = pg.run(g, gn.REGISTRY)["nodes"]
    port_of = {"vw": "views", "cv": "views", "vs": "scores", "rg": "regime", "ts": "signal", "op": "trades",
               "tv": "target", "bt": "backtest", "k": "risk"}
    checked = set()
    for nid, port in port_of.items():
        r = rep[nid]
        assert r["status"] == "ok", (nid, r["reason"])
        t = next(p.type for p in gn.REGISTRY.get(r["type"]).outputs if p.name == port)
        value = next(v for (st, pn, v) in seen[t] if st == r["type"] and pn == port)
        assert r["briefs"].get(port) == _expect(t, value), (nid, r["briefs"])
        checked.add(t)
    assert checked == set(NEW)


# ══ 짝 — 모양이 틀리면 요약하지 않는다 ═══════════════════════════════════════════════════════

@pytest.mark.parametrize(("port_type", "bad"), [
    ("Views", None), ("Views", {"views": []}),
    ("Scores", {}), ("Scores", {"scores": []}), ("Scores", {"scores": {}}),
    ("RegimeState", {}), ("RegimeState", {"phase_probabilities": {}}),
    ("RegimeState", {"phase_probabilities": {"Goldilocks": None, "Reflation": float("nan")}}),
    ("TimingSignal", {}), ("TimingSignal", {"states": []}), ("TimingSignal", {"states": ["risk_on", "sideways"]}),
    ("Trades", {}), ("Trades", {"plan": {"summary": {"n_orders": None}}}), ("Trades", {"plan": {"summary": {"n_orders": "2"}}}),
    ("TargetVersion", {}), ("TargetVersion", {"tv": {"status": "executable", "final_weights": None, "cash_weight": 0}}),
    ("TargetVersion", {"tv": {"status": "executable", "final_weights": {"A": 100.0}, "cash_weight": float("inf")}}),
    ("BacktestResult", {}), ("BacktestResult", {"dates": ["2024-01-02"]}),
    ("BacktestResult", {"error": True, "dates": ["2024-01-02", "2024-01-03"]}),
    ("RiskReport", {}), ("RiskReport", {"risk_contribution_optimized": {"portfolio_volatility_pct": None}}),
    ("RiskReport", {"risk_contribution_optimized": {"portfolio_volatility_pct": float("nan")}}),
])
def test_a_value_of_the_wrong_shape_is_not_summarised(port_type, bad):
    assert gl.BRIEFS[port_type](bad) is None


def test_pairs_known_values_are_counted_not_invented():
    """짝의 짝 — 모르는 점수는 '모름' 으로 세고(0 으로 치지 않는다), 모르는 국면 이름은 그대로 쓴다."""
    assert gl.BRIEFS["Scores"]({"scores": {"A": 1.0, "B": None, "C": float("nan")}}) == "3종목 점수 · 2개 모름"
    assert gl.BRIEFS["Scores"]({"scores": {"A": 1.0, "B": 2.0}}) == "2종목 점수"
    assert gl.BRIEFS["RegimeState"]({"phase_probabilities": {"Zebra": 0.6, "Goldilocks": 0.4}}) == "Zebra 60%"
    assert gl.BRIEFS["RegimeState"]({"phase_probabilities": {"Goldilocks": 0.4, "Reflation": None}}) == "골디락스 40%"
    assert gl.BRIEFS["Views"]([]) == "생각 0개"
    assert gl.BRIEFS["TimingSignal"]({"states": ["unavailable", "unavailable"]}) == "신호 2개 · 판단 불가 2"
    assert gl.BRIEFS["TargetVersion"]({"tv": {"status": "research", "final_weights": {"A": 60.0, "B": 0.0},
                                               "cash_weight": 40.0}}) == "연구용 목표 · 1종목 · 현금 40%"
    assert gl.BRIEFS["Trades"]({"plan": {"summary": {"n_orders": 0, "n_buy": 0, "n_sell": 0}}}) == "주문 0건 · 매수 0 · 매도 0"


def test_every_new_brief_fits_the_engine_limit():
    long_dates = [f"2020-01-{i:02d}" for i in range(1, 29)]
    samples = {"Views": [{}] * 3, "Scores": {"scores": {str(i): 1.0 for i in range(500)}},
               "RegimeState": {"phase_probabilities": {"Disinflation": 0.51}},
               "TimingSignal": {"states": ["risk_on", "risk_off", "unavailable"] * 30},
               "Trades": {"plan": {"summary": {"n_orders": 9999, "n_buy": 5000, "n_sell": 4999}}},
               "TargetVersion": {"tv": {"status": "executable", "final_weights": {str(i): 0.2 for i in range(500)},
                                        "cash_weight": 0.0}},
               "BacktestResult": {"dates": long_dates}, "RiskReport": {"risk_contribution_optimized": {"portfolio_volatility_pct": 123.456}}}
    for t, v in samples.items():
        s = gl.BRIEFS[t](v)
        assert isinstance(s, str) and 0 < len(s) <= pg.BRIEF_MAX, (t, s)
