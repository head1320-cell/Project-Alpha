"""BL2b · 마법사에만 있던 계산을 노드로 — 프런티어 · 국면 앙상블/설명 · 시나리오 둘 · 전략 건강 · 묶음 분석 · 알파 둘
==============================================================================
계획 `happy-percolating-falcon.md` §BL2b. 노드는 **라우트·엔진과 같은 함수**를 부른다 — 여기 골든이 대조한다.

## 거는 것
- **매크로 데이터 경로**(사용자 결정: 저장된 관측 + mock 연습용) — 운영은 `collect_all(store_only=True)`: 외부 호출 0 ·
  캐시 쓰기 0 · 관측 적재 0 · 저장된 것이 없으면 사유 있는 실패(짝: 있으면 계산). 개발은 `/macro` 라우트와 같은 수집기
  출력 + 연습용 계보. 저장된 관측으로 만든 계열은 같은 값을 받아 온 라이브 계열과 **같다**(정규화를 두 벌 두지 않는다).
- 쓰기 끔: 알파 검증·포트폴리오는 `record_run=False` 를 **명시**한다(라우트 기본은 True) — 계산 중 기록 0.
  알파 검증의 '검증 기록 남기기' 는 먼저 기록 없이 대조하고 같을 때만 한 번 기록한다.
"""
from __future__ import annotations

import os

import numpy as np
import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.api import allocation_graph_nodes as gn  # noqa: E402
from src.engine import portfolio_graph as pg  # noqa: E402
from tests.test_allocation_graph import T3, _edge, _node, chain, client, market  # noqa: E402,F401


def _run(g):
    return pg.run(g, gn.REGISTRY)


def _why(rep):
    return {k: (v["status"], v["reason"]) for k, v in rep["nodes"].items()}


def _g(nodes, edges=()):
    return {"format": pg.FORMAT, "version": pg.VERSION, "nodes": list(nodes), "edges": list(edges)}


# ══ 매크로 데이터 경로 ═══════════════════════════════════════════════════════

def _months(n):
    out, y, m = [], 2020, 1
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}-01")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def _vals(key, n):
    seed = sum(map(ord, key))
    return [round(2.0 + ((seed * (i + 7)) % 97) / 25.0 + 0.01 * i, 4) for i in range(n)]


class _Fake:
    """외부 API 대역 — 부르면 센다. 운영 경로에서는 한 번도 불리면 안 된다."""

    def __init__(self):
        self.calls = 0

    def fetch_series(self, *a):
        self.calls += 1
        key = "|".join(map(str, a))
        return _months(72), _vals(key, 72)


@pytest.fixture()
def live_and_store(monkeypatch):
    """같은 관측을 두 길로 — 라이브(가짜 API) · 저장소(그 관측을 적은 행). 저장소에는 **예전 조회분**도 섞는다."""
    from src.data import macro_observation_store as store
    from src.data.pit_macro import MacroObservation
    from src.services.macro_collector import MacroCollector

    monkeypatch.setattr("src.services.macro_collector._from_vintage_store", lambda key, as_of: None)
    recorded = []
    monkeypatch.setattr(store, "record_series", lambda s, **k: recorded.append(s.indicator) or 0)
    bok, fred = _Fake(), _Fake()
    live = MacroCollector(bok_client=bok, fred_client=fred).collect_all(use_cache=False)
    rows = []
    for key, s in live.series.items():
        if s.source not in ("BOK", "FRED"):
            continue
        for t, v in zip(s.timestamps, s.values):
            rows.append(MacroObservation(series_id=key, observation_period=t, release_timestamp="", vintage_id="",
                                         retrieved_at="2026-09-01T00:00:00+00:00", value=v))
            rows.append(MacroObservation(series_id=key, observation_period=t, release_timestamp="", vintage_id="",
                                         retrieved_at="2026-01-01T00:00:00+00:00", value=v + 50.0))   # 낡은 조회
    monkeypatch.setattr(store, "load", lambda series_id=None, **k: [r for r in rows if series_id in (None, r.series_id)])
    recorded.clear()
    return {"live": live, "bok": bok, "fred": fred, "recorded": recorded, "rows": rows}


_SAME = ("timestamps", "values", "latest", "prev", "yoy", "mom_pct", "z_score", "percentile", "mean_5y", "std_5y",
         "trend", "source")


def test_series_rebuilt_from_the_store_equal_the_live_series(live_and_store):
    from src.services.macro_collector import MacroCollector
    bok, fred = _Fake(), _Fake()
    c = MacroCollector(bok_client=bok, fred_client=fred)
    stored = c.collect_all(use_cache=False, store_only=True)
    live = live_and_store["live"]
    n = 0
    for key, s in live.series.items():
        if s.source not in ("BOK", "FRED"):
            continue
        t = stored.series[key]
        assert {f: getattr(t, f) for f in _SAME} == {f: getattr(s, f) for f in _SAME}, key
        n += 1
    assert n >= 10, "★공허 금지★ — 실제로 여러 계열을 대조했다"
    # ★저장소만 읽는다★ 외부 호출 0 · 적재 0 · 캐시 0
    assert bok.calls == 0 and fred.calls == 0
    assert live_and_store["recorded"] == []
    assert c._cache == {}


def test_the_store_path_never_fills_with_mock(monkeypatch):
    """★저장소에 없으면 없다★ — mock 이 허용된 개발 환경에서도 저장소 경로는 합성으로 채우지 않는다."""
    from src.data import macro_observation_store as store
    from src.services.macro_collector import MacroCollector
    monkeypatch.setattr("src.services.macro_collector._from_vintage_store", lambda key, as_of: None)
    monkeypatch.setattr(store, "load", lambda series_id=None, **k: [])
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    snap = MacroCollector(bok_client=_Fake(), fred_client=_Fake()).collect_all(use_cache=False, store_only=True)
    from src.services.macro_collector import REASON_NOT_IN_STORE
    assert all(s.source != "MOCK" and not s.values for s in snap.series.values())
    # 원계열은 '저장소에 없다' 는 사유를 단다(파생 스프레드는 제 사유 — 원계열이 없어 만들지 않았다)
    assert sum(s.reason == REASON_NOT_IN_STORE for s in snap.series.values()) >= 10
    # 짝: 같은 조건의 라이브 경로는 mock 을 쓴다(개발 모드 계약)
    live = MacroCollector(bok_client=_Empty(), fred_client=_Empty()).collect_all(use_cache=False)
    assert any(s.source == "MOCK" for s in live.series.values())


class _Empty:
    def fetch_series(self, *a):
        return [], []


# ══ 국면 앙상블 · 국면 설명 ══════════════════════════════════════════════════

def test_regime_ensemble_in_production_reads_only_the_store(live_and_store, monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    import src.services.macro_collector as mc
    calls = []
    monkeypatch.setattr(mc.BokClient, "fetch_series", lambda self, *a: calls.append(a) or ([], []))
    monkeypatch.setattr(mc.FredClient, "fetch_series", lambda self, *a: calls.append(a) or ([], []))
    monkeypatch.setattr("src.data.macro_observation_store.coverage",
                        lambda *a, **k: {"available": True, "rows": len(live_and_store["rows"])})
    rep = _run(_g([_node("e", "regime_ensemble", market="us", months=36)]))
    r = rep["nodes"]["e"]
    assert r["status"] == "ok", r["reason"]
    assert calls == [] and live_and_store["recorded"] == []
    assert r["lineage"]["practice"] is False
    from src.engine.regime_ensemble import regime_ensemble
    ref = regime_ensemble(mc.MacroCollector().collect_all(use_cache=False, store_only=True).series, market="us", months=36)
    assert r["view"]["result"] == ref


def test_regime_ensemble_in_production_without_stored_observations_fails_with_guidance(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    monkeypatch.setattr("src.data.macro_observation_store.coverage", lambda *a, **k: {"available": True, "rows": 0})
    r = _run(_g([_node("e", "regime_ensemble")]))["nodes"]["e"]
    assert r["status"] == "failed" and "매크로" in r["reason"] and "수집" in r["reason"]
    monkeypatch.setattr("src.data.macro_observation_store.coverage",
                        lambda *a, **k: {"available": False, "reason": "DB 엔진이 없습니다"})
    r = _run(_g([_node("e", "regime_ensemble")]))["nodes"]["e"]
    assert r["status"] == "failed" and "읽을 수 없" in r["reason"]


def test_regime_ensemble_in_development_equals_the_route_and_is_practice(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    from src.api.macro_routes import macro_regime_ensemble
    r = _run(_g([_node("e", "regime_ensemble", market="kr", months=48)]))["nodes"]["e"]
    assert r["status"] == "ok", r["reason"]
    assert r["view"]["result"] == macro_regime_ensemble(market="kr", months=48)
    assert r["lineage"]["practice"] is True
    assert any("연습용" in t["text"] for t in r["explain"]["trust"])


def test_regime_explain_in_development_equals_the_route(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    from src.api.macro_routes import macro_regime_explain
    r = _run(_g([_node("x", "regime_explain", market="kr", months=48, forecast_k=3)]))["nodes"]["x"]
    assert r["status"] == "ok", r["reason"]
    assert r["view"]["result"] == macro_regime_explain(market="kr", months=48, regime=None, forecast_k=3)


# ══ 효율적 프런티어 ══════════════════════════════════════════════════════════

def _frontier_graph(with_weights):
    g = chain(risk=False)
    g["nodes"].append(_node("f", "frontier"))
    g["edges"].append(_edge("r", "returns", "f", "returns"))
    if with_weights:
        g["edges"].append(_edge("o", "weights", "f", "weights"))
    return g


def test_the_frontier_curve_equals_analyze(market):
    from src.api.allocation_routes import AnalyzeRequest, run_analyze
    r = _run(_frontier_graph(False))["nodes"]["f"]
    assert r["status"] == "ok", r["reason"]
    ref = run_analyze(AnalyzeRequest(tickers=T3, model="mvo"))
    assert r["view"]["curve"] == ref["frontier"]["curve"] and len(r["view"]["curve"]) >= 5
    assert r["view"]["point"] is None                                   # 비중을 잇지 않으면 점이 없다


def test_the_frontier_marks_the_connected_weights_on_the_same_basis(market):
    rep = _run(_frontier_graph(True))
    f = rep["nodes"]["f"]
    assert f["status"] == "ok", f["reason"]
    vals = pg._execute(_frontier_graph(True), gn.REGISTRY)[1]
    df = vals["r"]["returns"]["returns"]                         # 곡선과 같은 표본(수익률 노드의 기간)
    ow = vals["o"]["weights"]
    w = np.array([float(dict(zip(ow["names"], ow["weights"]))[c]) for c in df.columns])
    ret = float(w @ (df.mean().values * 252)) * 100
    vol = float(np.sqrt(w @ (df.cov().values * 252) @ w)) * 100
    assert f["view"]["point"] == {"return": round(ret, 3), "volatility": round(vol, 3)}


# ══ 전략 건강 · 묶음 분석 ════════════════════════════════════════════════════

def test_strategy_health_equals_the_route():
    from src.api.attribution_routes import get_strategy_health
    r = _run(_g([_node("h", "strategy_health")]))["nodes"]["h"]
    assert r["status"] == "ok", r["reason"]
    assert r["view"]["result"] == get_strategy_health()


def test_sleeve_analytics_equals_the_engine(market):
    from src.engine.sleeve_combine import sleeve_analytics
    g = chain(risk=False)
    g["nodes"] += [_node("o2", "optimizer", model="hrp"), _node("s", "sleeve_analytics")]
    g["edges"] += [_edge("r", "returns", "o2", "returns"), _edge("e", "belief", "o2", "belief"),
                   _edge("o", "weights", "s", "a"), _edge("o2", "weights", "s", "b")]
    rep = _run(g)
    s = rep["nodes"]["s"]
    assert s["status"] == "ok", _why(rep)
    from src.api.allocation_graph_nodes_check import holdings_pct
    vals = pg._execute(g, gn.REGISTRY)[1]
    ref = sleeve_analytics([{"name": "묶음 1", "weights": holdings_pct(vals["o"]["weights"])},
                            {"name": "묶음 2", "weights": holdings_pct(vals["o2"]["weights"])}])
    assert s["view"]["result"] == ref


def test_sleeve_analytics_needs_two_sleeves():
    spec = gn.REGISTRY.get("sleeve_analytics")
    req = {p.name for p in spec.inputs if p.required}
    assert req == {"a", "b"} and {p.name for p in spec.inputs} == {"a", "b", "c", "d"}


# ══ 시나리오 둘 ══════════════════════════════════════════════════════════════

def test_a_custom_scenario_equals_scenario_run(market):
    from src.api.scenario_routes import InlinePack, ScenarioRunRequest, scenario_run
    g = chain(risk=False)
    g["nodes"].append(_node("c", "custom_scenario", label="내 충격", market_shock=-8.0, momentum=-3.0, value=2.0))
    g["edges"].append(_edge("o", "weights", "c", "weights"))
    rep = _run(g)
    c = rep["nodes"]["c"]
    assert c["status"] == "ok", _why(rep)
    from src.api.allocation_graph_nodes_check import holdings_pct
    pct = holdings_pct(pg._execute(g, gn.REGISTRY)[1]["o"]["weights"])
    ref = scenario_run(ScenarioRunRequest(holdings=pct, pack=InlinePack(
        label="내 충격", market=-8.0, factors={"momentum": -3.0, "value": 2.0})))
    assert c["view"]["result"]["shock_pct"] == ref["shock_pct"]
    assert c["view"]["result"]["model_type"] == "hypothetical" == ref["model_type"]


def test_a_custom_scenario_without_any_factor_fails_instead_of_inventing_one(market):
    g = chain(risk=False)
    g["nodes"].append(_node("c", "custom_scenario", market_shock=-8.0))
    g["edges"].append(_edge("o", "weights", "c", "weights"))
    c = _run(g)["nodes"]["c"]
    assert c["status"] == "failed" and "팩터" in c["reason"]


def test_the_three_way_scenario_equals_the_route(market, monkeypatch):
    from src.api.scenario_routes import ScenarioThreeWayRequest, scenario_three_way
    from src.engine.timing_rules_v2 import SignalState as S
    monkeypatch.setattr("src.engine.timing_rules_v2.rule_set_states",
                        lambda rs, **k: [S.RISK_ON, S.RISK_OFF, S.RISK_ON])
    rules = [{"factor_id": "abs_mom"}, {"factor_id": "ma_month"}, {"factor_id": "drawdown"}]
    g = chain(risk=False)
    g["nodes"] += [_node("t", "timing_signal", rules=rules, combination="k_of_n", k=2),
                   _node("w", "scenario_three_way", scenario="rate_hike_200bp", severity=1.0)]
    g["edges"] += [_edge("o", "weights", "w", "weights"), _edge("t", "signal", "w", "signal")]
    rep = _run(g)
    w = rep["nodes"]["w"]
    assert w["status"] == "ok", _why(rep)
    from src.api.allocation_graph_nodes_check import holdings_pct
    pct = holdings_pct(pg._execute(g, gn.REGISTRY)[1]["o"]["weights"])
    ref = scenario_three_way(ScenarioThreeWayRequest(
        holdings=pct, pack_id="rate_hike_200bp", severity=1.0, market="kr", combination="k_of_n", k=2, rules=rules))
    assert w["view"]["result"] == ref
    # 이야기: 판정한 다리는 손실을 말하고(충격이 있으니까), 판정 못 한 다리(국면 미연결)는 '미계산'
    facts = w["explain"]["facts"]
    assert any(f.startswith("그대로 두기") and "손실 " in f and "미계산" not in f for f in facts), facts
    assert any(f.startswith("타이밍 + 국면") and "미계산" in f for f in facts), facts


# ══ 알파 검증 · 알파 포트폴리오 · 레지스트리에서 고르기 ══════════════════════

@pytest.fixture()
def no_record(monkeypatch):
    calls = []
    monkeypatch.setattr("src.data.research_runs.record_run", lambda *a, **k: calls.append(a) or "rr_x")
    return calls


def test_alpha_validate_equals_the_route_and_records_nothing(no_record):
    from src.api.alpha_routes import ValidateRequest, alpha_validate
    g = _g([_node("v", "alpha_validate", expr="zscore(mom_6m)", universe="kospi50", months=12, quantiles=5)])
    r = _run(g)["nodes"]["v"]
    assert r["status"] == "ok", r["reason"]
    assert no_record == []                                                # ★계산은 기록하지 않는다★
    ref = alpha_validate(ValidateRequest(expr="zscore(mom_6m)", universe="kospi50", months=12, quantiles=5,
                                         record_run=False))
    assert r["view"]["result"] == ref
    # 롱숏 성과 숫자에는 무슨 성과인지 라벨이 붙는다(과거 시뮬레이션 · 개발 모드면 합성 데이터)
    lab = r["provenance"]["perf_label"]
    assert lab["kind"] == "backtest" and lab["data_real"] is False and "비용" in lab["kind_reason"]


def test_saving_an_alpha_validation_attaches_it_to_the_registry_alpha(client, no_record, monkeypatch):
    attached = []
    monkeypatch.setattr("src.data.alpha_registry.attach_validation", lambda aid, rid: attached.append((aid, rid)))
    monkeypatch.setattr("src.data.alpha_registry.get_alpha",
                        lambda aid: {"alpha_id": aid, "name": "a", "expr": "zscore(mom_6m)", "version": 1,
                                     "status": "experimental"} if aid == "al_1" else None)
    g = _g([_node("v", "alpha_validate", alpha_id="al_1", universe="kospi50", months=12)])
    rep = _run(g)
    assert rep["nodes"]["v"]["status"] == "ok", _why(rep)
    out = client.post("/api/v1/allocation/graph/save",
                      json={"graph": g, "node_id": "v", "preview_hash": rep["nodes"]["v"]["view_hash"]}).json()
    assert out["ok"] is True and out["saved_id"] == "rr_x", out
    assert len(no_record) == 1 and attached == [("al_1", "rr_x")]
    assert "검증 기록" in out["text"]


def test_an_unwritable_store_does_not_claim_a_validation_record(client, monkeypatch):
    monkeypatch.setattr("src.data.research_runs.record_run", lambda *a, **k: None)
    g = _g([_node("v", "alpha_validate", expr="zscore(mom_6m)", universe="kospi50", months=12)])
    rep = _run(g)
    assert rep["nodes"]["v"]["status"] == "ok", _why(rep)
    out = client.post("/api/v1/allocation/graph/save",
                      json={"graph": g, "node_id": "v", "preview_hash": rep["nodes"]["v"]["view_hash"]}).json()
    assert out["ok"] is False and "DB" in out["message"], out


def test_an_alpha_node_with_an_unknown_registry_id_fails(monkeypatch):
    monkeypatch.setattr("src.data.alpha_registry.get_alpha", lambda aid: None)
    r = _run(_g([_node("v", "alpha_validate", alpha_id="nope")]))["nodes"]["v"]
    assert r["status"] == "failed" and "nope" in r["reason"]


def test_alpha_score_can_take_its_formula_from_the_registry(monkeypatch):
    from src.engine import alpha_lab
    seen = []
    monkeypatch.setattr("src.data.alpha_registry.get_alpha",
                        lambda aid: {"alpha_id": aid, "name": "레지", "expr": "zscore(roe)", "version": 3,
                                     "status": "approved"})
    monkeypatch.setattr(alpha_lab, "score_alpha", lambda expr, tickers, **k: seen.append(expr) or {
        "available": True, "scores": {t: float(i) for i, t in enumerate(tickers)}, "expr": expr,
        "as_of_effective": "2026-09-01", "coverage": len(tickers), "n_universe": len(tickers)})
    g = chain(risk=False)
    g["nodes"].append(_node("s", "alpha_score", alpha_id="al_9", expr="zscore(mom_6m)"))
    g["edges"].append(_edge("u", "universe", "s", "universe"))
    r = _run(g)["nodes"]["s"]
    assert r["status"] == "ok", r["reason"]
    assert seen == ["zscore(roe)"], "레지스트리 식이 이긴다"
    assert r["view"]["expr_source"] == {"alpha_id": "al_9", "name": "레지", "version": 3}
    # 짝: 고르지 않으면 식 칸을 쓰고 출처가 없다
    g["nodes"][-1]["params"] = {"expr": "zscore(mom_6m)"}
    r2 = _run(g)["nodes"]["s"]
    assert seen[-1] == "zscore(mom_6m)" and r2["view"]["expr_source"] is None


def test_alpha_portfolio_passes_the_server_block_through(monkeypatch, no_record):
    monkeypatch.setattr("src.data.alpha_registry.get_alpha",
                        lambda aid: {"alpha_id": aid, "name": "초안", "expr": "zscore(roe)", "status": "draft"})
    r = _run(_g([_node("p", "alpha_portfolio", alpha_ids=["al_1"])]))["nodes"]["p"]
    assert r["status"] == "failed" and "초안" in r["reason"]
    assert no_record == []


def test_alpha_portfolio_equals_the_route_and_records_nothing(monkeypatch, no_record):
    from src.api.alpha_routes import AlphaPortfolioRequest, AlphaWeightSpec, alpha_portfolio
    fake = {"available": True, "base_weights": {"005930": 60.0, "000660": 40.0},
            "holdings": [], "used": [], "excluded": [], "pairwise": [], "effective_n": 1.0, "warnings": [],
            "weighting": "equal", "top_k": 10, "universe_resolved_n": 50, "note": "n", "as_of_effective": None}
    seen = []
    monkeypatch.setattr("src.api.alpha_routes.alpha_portfolio", lambda req: seen.append(req) or dict(fake))
    r = _run(_g([_node("p", "alpha_portfolio", alpha_ids=["al_1", "al_2"], top_k=10)]))["nodes"]["p"]
    assert r["status"] == "ok", r["reason"]
    assert seen[0].record_run is False and [a.alpha_id for a in seen[0].alphas] == ["al_1", "al_2"]
    assert r["view"]["weights"] == {"005930": 60.0, "000660": 40.0}
    assert AlphaPortfolioRequest and AlphaWeightSpec and alpha_portfolio


# ★계산 중 DB 쓰기 0★ (BL0)
from tests.graph_write_guard import graph_write_guard  # noqa: E402,F401

pytestmark = pytest.mark.usefixtures("graph_write_guard")
