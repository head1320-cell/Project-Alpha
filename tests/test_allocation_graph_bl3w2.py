"""BL3 W2 · 매크로 웨이브 — 수익률 곡선 · 지표 대시보드 · 국면 합의 · 국면 예측 적중률 · 장기 관계 · 스튜디오 모델
==============================================================================
계획 `happy-percolating-falcon.md` §BL3 매크로. 노드는 **라우트와 같은 함수**를 부른다(골든) — 라우트 본문을 꺼낸
공용 함수를 라우트·노드가 함께 쓰고, 데이터만 BL2b `macro_series_map()` 으로 받는다.

## 거는 것
- **운영 = 저장된 관측만** — 여섯 노드 모두 외부 호출 0 · 관측 적재 0. 저장된 것이 없으면 사유 있는 실패(짝: 있으면 계산).
- **개발 = `/macro` 라우트와 같은 수집기 출력 + 연습용 계보**.
- 장기 관계·스튜디오는 엔진 안의 `load_series` 가 수집기를 직접 부른다 — 노드는 그 자리에 저장된 계열을 **주입**하고,
  계산이 끝나면 주입을 거둔다(짝: 노드 밖의 `load_series` 는 원래대로 수집기를 부른다).
- 코어 변수 상한(7)은 **요청** 개수로 잰다 — 라우트의 422 와 같은 문장으로 실패(짝: 7개는 통과).
- 스튜디오 노드는 대체 엔진만 돌린다 — 프런티어 가용성 프로브(관측 수를 세느라 수집한다)를 부르지 않는다.
- 상관 패널(`/macro/correlations`)은 **노드로 만들지 않는다** — 가격 적재가 DB → KIS → mock 사슬이라 운영에서 외부를 부를
  수 있다(캔버스 계산은 외부를 부르지 않는다). 카탈로그에 없음을 못 박는다.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.api import allocation_graph_nodes as gn  # noqa: E402
from src.engine import portfolio_graph as pg  # noqa: E402
from tests.graph_write_guard import graph_write_guard  # noqa: E402,F401
from tests.test_allocation_graph import _node  # noqa: E402
from tests.test_allocation_graph_bl2b import live_and_store  # noqa: E402,F401

pytestmark = pytest.mark.usefixtures("graph_write_guard")

KINDS = ("yield_curve", "macro_dashboard", "regime_consensus", "regime_forecast_coverage", "long_run", "macro_studio")


def _run(g):
    return pg.run(g, gn.REGISTRY)


def _g(nodes, edges=()):
    return {"format": pg.FORMAT, "version": pg.VERSION, "nodes": list(nodes), "edges": list(edges)}


def _one(kind, **params):
    r = _run(_g([_node("m", kind, **params)]))["nodes"]["m"]
    return r


def _strip(d, *keys):
    return {k: v for k, v in d.items() if k not in keys}


# ══ 카탈로그 ═════════════════════════════════════════════════════════════════

def test_all_six_macro_nodes_are_registered_and_the_correlation_panel_is_not():
    kinds = set(gn.REGISTRY.types())
    assert set(KINDS) <= kinds
    assert not any("correlation_panel" in k or k == "macro_correlations" for k in kinds)


# ══ 개발 경로 = 라우트 골든 · 연습용 계보 ═════════════════════════════════════

def test_yield_curve_equals_the_route_and_is_practice(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    from src.api.macro_routes import macro_yield_curve
    r = _one("yield_curve")
    assert r["status"] == "ok", r["reason"]
    assert r["view"]["result"] == _strip(macro_yield_curve(), "timestamp")
    # 공용 함수라 골든은 양쪽이 같이 빠뜨려도 통과한다 — 해석 문장이 실제로 실리는지 따로 본다
    assert r["view"]["result"]["interpretation"] and len(r["view"]["result"]["points"]) >= 3
    assert r["lineage"]["practice"] is True
    assert any("연습용" in t["text"] for t in r["explain"]["trust"])
    # 해석 문장은 경험칙이다 — 예측이라고 쓰지 않는다
    assert any("경험칙" in t["text"] for t in r["explain"]["trust"])


def test_macro_dashboard_equals_the_route_themes(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    from src.api.macro_routes import macro_dashboard
    r = _one("macro_dashboard")
    assert r["status"] == "ok", r["reason"]
    ref = macro_dashboard()["themes"]
    assert r["view"]["themes"] == ref
    assert sum(len(t["indicators"]) for t in ref) >= 10, "★공허 금지★"


def test_macro_dashboard_can_keep_one_theme(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    r = _one("macro_dashboard", theme="growth")
    assert r["status"] == "ok", r["reason"]
    assert [t["key"] for t in r["view"]["themes"]] == ["growth"]
    # 짝: 비우면 전부
    assert len(_one("macro_dashboard")["view"]["themes"]) > 1


def test_regime_consensus_equals_the_route(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    from src.api.macro_routes import macro_regime_consensus
    r = _one("regime_consensus", market="kr", months=48)
    assert r["status"] == "ok", r["reason"]
    assert r["view"]["result"] == macro_regime_consensus(market="kr", months=48)


def test_regime_forecast_coverage_equals_the_route(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    from src.api.macro_routes import macro_regime_forecast_coverage
    r = _one("regime_forecast_coverage", market="kr", months=120, k=2, alpha=0.2)
    assert r["status"] == "ok", r["reason"]
    assert r["view"]["result"] == macro_regime_forecast_coverage(market="kr", months=120, k=2, alpha=0.2)


def test_long_run_equals_the_route_with_the_default_core(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    from src.api.macro_routes import macro_long_run
    r = _one("long_run", months=120)
    assert r["status"] == "ok", r["reason"]
    assert r["view"]["result"] == macro_long_run(vars=None, months=120)


def test_long_run_rejects_more_than_seven_requested_variables():
    from src.engine.cointegration import MAX_CORE_VARS
    eight = "KR_BASE_RATE,KR_TERM_SPREAD,KR_CPI,USD_KRW,KOSPI,KR_CREDIT_SPREAD,KR_IP,KR_10Y"
    r = _one("long_run", vars=eight)
    assert r["status"] == "failed" and f"최대 {MAX_CORE_VARS}개" in r["reason"]
    # 짝: 7개는 계산한다(상한은 요청 개수로 잰다)
    seven = ",".join(eight.split(",")[:7])
    assert _one("long_run", vars=seven)["status"] == "ok"


@pytest.mark.parametrize("sid", ["tsfm-latent", "neural-sde", "causal-deepm", "pinn-tail"])
def test_macro_studio_equals_the_route(monkeypatch, sid):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    from src.api.macro_routes import macro_studio_run
    r = _one("macro_studio", studio=sid, months=60)
    ref = macro_studio_run(sid, months=60, target="KOSPI")
    if ref.get("available"):
        assert r["status"] == "ok", r["reason"]
        assert r["view"]["result"] == ref
    else:
        # ★대체 엔진이 못 돌면 숫자 대신 사유★ — 엔진 사유를 그대로 싣고 실패
        assert r["status"] == "failed" and ref["reason"] in r["reason"]


def test_macro_studio_does_not_offer_the_view_compiler():
    from src.api.allocation_graph_nodes_macro_w2 import StudioParams
    with pytest.raises(Exception):
        StudioParams(studio="agentic-mcp")


def test_macro_studio_never_probes_the_frontier(monkeypatch):
    """프런티어 프로브는 관측 수를 세느라 수집기를 부른다 — 노드는 부르지 않는다."""
    import src.engine.macro_models.base as base
    monkeypatch.setattr(base, "frontier_block", lambda *a, **k: pytest.fail("frontier probe called"))
    monkeypatch.setattr(base, "describe_all", lambda *a, **k: pytest.fail("describe_all called"))
    r = _one("macro_studio", studio="neural-sde")
    assert r["status"] in ("ok", "failed")
    assert "프런티어" in " ".join(t["text"] for t in r["explain"]["trust"])


# ══ 주입은 노드 안에서만 ═════════════════════════════════════════════════════

def test_injected_series_are_withdrawn_after_the_node(monkeypatch):
    from src.engine.macro_models import base
    seen = []

    class _Snap:
        series: dict = {}

    import src.services.macro_collector as mc
    monkeypatch.setattr(mc.MacroCollector, "collect_all",
                        lambda self, **k: seen.append(k) or _Snap())
    with base.series_source({"KOSPI": type("S", (), {"values": [1.0, 2.0, 3.0]})()}):
        assert base.load_series(("KOSPI",), 2) == {"KOSPI": [2.0, 3.0]}
    assert seen == [], "주입 중에는 수집기를 부르지 않는다"
    # 짝: 주입을 거두면 원래대로 수집기를 부른다
    assert base.load_series(("KOSPI",), 2) == {}
    assert len(seen) == 1


def test_injection_is_withdrawn_even_when_the_engine_raises():
    from src.engine.macro_models import base
    with pytest.raises(RuntimeError):
        with base.series_source({}):
            raise RuntimeError("boom")
    assert base._SERIES_SOURCE.get() is None


# ══ 운영 경로 = 저장소만 ═════════════════════════════════════════════════════

def _prod(monkeypatch, rows):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    import src.services.macro_collector as mc
    calls = []
    monkeypatch.setattr(mc.BokClient, "fetch_series", lambda self, *a: calls.append(a) or ([], []))
    monkeypatch.setattr(mc.FredClient, "fetch_series", lambda self, *a: calls.append(a) or ([], []))
    monkeypatch.setattr("src.data.macro_observation_store.coverage",
                        lambda *a, **k: {"available": True, "rows": rows})
    return calls


@pytest.mark.parametrize("kind", KINDS)
def test_in_production_every_macro_node_reads_only_the_store(live_and_store, monkeypatch, kind):
    calls = _prod(monkeypatch, len(live_and_store["rows"]))
    r = _one(kind)
    # ★공허 금지★ 모르는 노드의 실패로 통과하지 않는다 — 저장된 관측으로 실제로 계산했어야 한다
    assert r["status"] == "ok", r["reason"]
    assert calls == [] and live_and_store["recorded"] == []
    assert r["lineage"]["practice"] is False
    assert "macro_observation_store" in r["lineage"]["sources"]


def test_in_production_the_yield_curve_is_computed_from_the_store(live_and_store, monkeypatch):
    _prod(monkeypatch, len(live_and_store["rows"]))
    from src.api.macro_routes import yield_curve_view
    from src.services.macro_collector import MacroCollector
    r = _one("yield_curve")
    assert r["status"] == "ok", r["reason"]
    ref = yield_curve_view(MacroCollector().collect_all(use_cache=False, store_only=True).series)
    assert r["view"]["result"] == ref
    assert len(ref["points"]) >= 3, "★공허 금지★"


def test_in_production_long_run_uses_the_stored_series(live_and_store, monkeypatch):
    _prod(monkeypatch, len(live_and_store["rows"]))
    import src.engine.macro_models.base as base
    real = base.load_series
    got = []
    monkeypatch.setattr(base, "load_series", lambda keys, months: got.append(real(keys, months)) or got[-1])
    r = _one("long_run", vars="DGS10,DGS2,T10YIE", months=60)
    assert got and all(got[-1].values()), "저장된 계열이 엔진에 들어갔다"
    assert r["status"] in ("ok", "failed")


@pytest.mark.parametrize("kind", KINDS)
def test_in_production_without_stored_observations_every_node_fails_with_guidance(monkeypatch, kind):
    _prod(monkeypatch, 0)
    r = _one(kind)
    assert r["status"] == "failed" and "매크로" in r["reason"] and "수집" in r["reason"], r["reason"]


# ══ 설명·과장어 ═════════════════════════════════════════════════════════════

@pytest.mark.parametrize("kind", KINDS)
def test_each_node_explains_itself(monkeypatch, kind):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    r = _one(kind)
    assert r["status"] == "ok", r["reason"]
    ex = r["explain"]
    assert ex["title"] and ex["trust"]


# ══ 못 돌면 숫자 대신 사유 (엔진이 비었다고 답할 때) ═══════════════════════════

def test_a_consensus_with_no_available_tool_fails_with_each_reason(monkeypatch):
    monkeypatch.setattr("src.api.macro_routes.regime_consensus_view", lambda *a, **k: {
        "n_available": 0, "reasons": {"markov": "표본 부족", "cluster": "수렴 실패"}, "per_tool": {}})
    r = _one("regime_consensus")
    assert r["status"] == "failed" and "표본 부족" in r["reason"] and "수렴 실패" in r["reason"]


def test_an_unavailable_forecast_coverage_fails_with_the_engine_reason(monkeypatch):
    monkeypatch.setattr("src.api.macro_routes.forecast_coverage_view",
                        lambda *a, **k: {"available": False, "reason": "국면 경로가 24개월보다 짧습니다"})
    r = _one("regime_forecast_coverage")
    assert r["status"] == "failed" and "24개월보다 짧" in r["reason"]


def test_a_yield_curve_without_any_tenor_fails_instead_of_drawing_nothing(monkeypatch):
    monkeypatch.setattr("src.api.macro_routes.yield_curve_view", lambda s: {"points": [], "spread_2y10y_bp": None})
    r = _one("yield_curve")
    assert r["status"] == "failed" and "금리" in r["reason"]


def test_a_dashboard_without_any_indicator_fails(monkeypatch):
    monkeypatch.setattr("src.api.macro_routes.dashboard_themes",
                        lambda s: [{"key": "growth", "label": "성장", "indicators": []}])
    r = _one("macro_dashboard")
    assert r["status"] == "failed" and "지표" in r["reason"]


def test_an_unavailable_long_run_fails_with_the_engine_reason(monkeypatch):
    monkeypatch.setattr("src.api.macro_routes.long_run_view",
                        lambda *a, **k: {"available": False, "reason": "관측이 60개월보다 적습니다"})
    r = _one("long_run")
    assert r["status"] == "failed" and "60개월보다 적" in r["reason"]
