"""BK W1 · 확인하기 노드 — ★마법사의 스트레스·시나리오 도구와 같은 수를 낸다★
==============================================================================
스펙 `docs/superpowers/specs/2026-09-25-aas-all-tools-nodes-design.md` §2 W1 ·
대상 `src/api/allocation_graph_nodes_check.py`

## 거는 것
- ★골든★ 시나리오 충격(가정 M8 · 역사 리플레이 · 국내 팩) · 상관 스트레스 · 기대수익 민감도 ·
  팩터 성격 노드의 결과 == 같은 입력의 기존 라우트/엔진 함수(사본을 만들지 않는다).
- 역사 리플레이가 mock 폴백을 쓰면 **연습용 계보** — 짝: 적재 시세면 아니다.
- 그 기간 시세가 없으면 **실패 + 사유**(지어내지 않는다).
- 역사 리플레이에는 강도 배율이 적용되지 않는다는 사실을 말한다 — 짝: 가정 충격은 배율을 말한다.
- 민감도는 기대수익을 쓰는 방식 기준이다 — 다른 방식(HRP 등)을 고르면 **가정**으로 말한다(짝: MVO 는 아님).
"""
from __future__ import annotations

import os
import types

import numpy as np
import pandas as pd
import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

import src.api.allocation_stress_routes as sr  # noqa: E402
from src.api import allocation_graph_nodes as gn  # noqa: E402
from src.api.allocation_stress_routes import (  # noqa: E402
    SensitivityRequest,
    StressCorrRequest,
    StressRequest,
    XrayRequest,
    allocation_factor_xray,
    allocation_sensitivity,
    allocation_stress,
    allocation_stress_correlation,
)
from src.engine import portfolio_graph as pg  # noqa: E402
from tests.test_allocation_graph import _edge, _node, chain, market  # noqa: E402,F401
from tests.test_allocation_routes import T3, _patch_xray  # noqa: E402


def _run(g):
    return pg.run(g, gn.REGISTRY)


def _with(g, node, edges):
    g["nodes"].append(node)
    g["edges"] += edges
    return g


def _weights_pct(g) -> dict[str, float]:
    """노드가 실제로 받은 **정밀** 비중(%) — view 의 비중은 표시용으로 반올림돼 있다."""
    w = pg._execute(g, gn.REGISTRY)[1]["o"]["weights"]
    return {n: float(x) * 100.0 for n, x in zip(w["names"], w["weights"])}


def _stress_graph(**params):
    return _with(chain(), _node("s", "scenario_stress", **params), [_edge("o", "weights", "s", "weights")])


@pytest.fixture()
def flat_shock(monkeypatch):
    monkeypatch.setattr(sr, "_shock_inputs", lambda code: types.SimpleNamespace(
        stock_code=code, corp_name=code, debt_ratio_pct=150, per=20,
        dividend_yield_pct=1, roe_pct=6, beta_1y=1.1, composite_score=50))


# ── 시나리오 충격 ─────────────────────────────────────────────────────────────

def test_hypothetical_shock_equals_the_stress_route(market, flat_shock):
    g = _stress_graph(scenario="rate_hike_200bp", severity=1.5)
    s = _run(g)["nodes"]["s"]
    assert s["status"] == "ok", s["reason"]
    want = allocation_stress(StressRequest(holdings=_weights_pct(g), scenario="rate_hike_200bp", severity=1.5))
    assert s["view"]["result"] == want
    assert s["explain"]["headline"]["value"] == want["portfolio_shock_pct"]
    assert any("배율" in f and "1.5" in f for f in s["explain"]["facts"])


def test_historical_replay_equals_the_stress_route_and_is_not_practice(market):
    g = _stress_graph(scenario="hist_2020_covid")
    s = _run(g)["nodes"]["s"]
    assert s["status"] == "ok", s["reason"]
    want = allocation_stress(StressRequest(holdings=_weights_pct(g), scenario="hist_2020_covid"))
    assert s["view"]["result"] == want
    assert s["explain"]["headline"]["value"] == want["max_dd_pct"]
    assert s["lineage"]["practice"] is False
    assert any("배율" in f and "적용하지" in f for f in s["explain"]["facts"]), "역사 리플레이는 배율이 없다"


def test_historical_replay_on_the_mock_fallback_is_practice(market, monkeypatch):
    rep0 = _run(chain())                          # 적재 시세로 비중을 먼저 구한다
    assert rep0["nodes"]["o"]["status"] == "ok"
    calls = {"n": 0}
    real = sr._mock_returns_fallback

    def fallback(*a, **k):
        calls["n"] += 1
        return real(*a, **k)
    import src.kis_portfolio_analyzer as kpa
    df_market = kpa.load_returns(T3, "2019-01-01", "2026-07-15")

    def load(tickers, start, end):                # 리플레이 창만 비어 있다
        return pd.DataFrame() if start.startswith("2020") else df_market
    monkeypatch.setattr("src.kis_portfolio_analyzer.load_returns", load)
    monkeypatch.setattr(sr, "_mock_returns_fallback", fallback)
    s = _run(_stress_graph(scenario="hist_2020_covid"))["nodes"]["s"]
    assert calls["n"] == 1 and s["status"] == "ok", s["reason"]
    assert s["lineage"]["practice"] is True
    assert any("연습용" in t["text"] for t in s["explain"]["trust"] if t["state"] == "unknown")


def test_a_window_without_prices_fails_instead_of_inventing(market, monkeypatch):
    import src.kis_portfolio_analyzer as kpa
    df_market = kpa.load_returns(T3, "2019-01-01", "2026-07-15")
    monkeypatch.setattr("src.kis_portfolio_analyzer.load_returns",
                        lambda t, start, end: pd.DataFrame() if start.startswith("2007") else df_market)
    monkeypatch.setattr(sr, "_mock_returns_fallback", lambda *a, **k: None)
    s = _run(_stress_graph(scenario="hist_2008_gfc"))["nodes"]["s"]
    assert s["status"] == "failed" and "시세" in s["reason"]


def test_a_korean_pack_equals_run_scenario(market):
    from src.engine.kr_scenario_pack import run_scenario
    g = _stress_graph(scenario="semi_selloff", severity=2.0)
    s = _run(g)["nodes"]["s"]
    assert s["status"] == "ok", s["reason"]
    h = sr.signed_fractions(_weights_pct(g))
    assert s["view"]["result"] == run_scenario(list(h), h, "semi_selloff", severity=2.0)


def test_the_scenario_choice_lists_every_pack_with_its_label():
    ui = gn.REGISTRY.get("scenario_stress").params_model.model_json_schema()["properties"]["scenario"]["x-ui"]
    from src.engine.scenario_packs import PACKS
    assert set(ui["options"]) == set(PACKS)
    assert ui["options"]["hist_2008_gfc"] == PACKS["hist_2008_gfc"].label


# ── 상관 스트레스 ─────────────────────────────────────────────────────────────

def _corr_graph(**params):
    return _with(chain(), _node("c", "corr_stress", **params),
                 [_edge("r", "returns", "c", "returns"), _edge("o", "weights", "c", "weights")])


def test_correlation_stress_equals_the_route(market):
    g = _corr_graph(target_rho=0.8, intensity=0.5)
    c = _run(g)["nodes"]["c"]
    assert c["status"] == "ok", c["reason"]
    want = allocation_stress_correlation(StressCorrRequest(
        tickers=T3, weights=_weights_pct(g), lookback_days=756, target_rho=0.8, intensity=0.5))
    got = dict(c["view"]["result"])
    for k in ("excluded", "coverage"):
        want.pop(k)
    assert got == want
    assert c["explain"]["headline"]["value"] == want["stressed"]["port_vol_pct"]
    assert any(t["state"] == "assumed" and "0.8" in t["text"] for t in c["explain"]["trust"])


def test_zero_intensity_changes_nothing(market):
    """짝 — 강도 0 이면 변동성이 그대로다(항상-충격 구현 배제)."""
    c = _run(_corr_graph(intensity=0.0))["nodes"]["c"]["view"]["result"]
    assert c["stressed"]["port_vol_pct"] == c["base"]["port_vol_pct"]


# ── 기대수익 민감도 ───────────────────────────────────────────────────────────

def _sens_graph(model="mvo", **params):
    g = chain(model=model)
    return _with(g, _node("m", "sensitivity", **params),
                 [_edge("r", "returns", "m", "returns"), _edge("o", "weights", "m", "weights")])


def test_sensitivity_equals_the_route(market):
    m = _run(_sens_graph(bump_pct=3.0))["nodes"]["m"]
    assert m["status"] == "ok", m["reason"]
    want = allocation_sensitivity(SensitivityRequest(tickers=T3, bump_pct=3.0, lookback_days=756))
    for k in ("error", "labels", "excluded", "coverage"):
        want.pop(k, None)
    got = {k: v for k, v in m["view"]["result"].items() if k in want}
    assert got == want
    assert not any(t["state"] == "assumed" for t in m["explain"].get("trust") or [])


def test_sensitivity_with_a_view_uses_the_same_view_as_the_route(market):
    """★짝★ 뷰가 있으면 BL 사후 μ 기준 — 노드가 뷰를 빠뜨리면 다른 수가 나온다."""
    from tests.test_allocation_graph import VIEW
    g = chain(model="bl", views=[VIEW])
    _with(g, _node("m", "sensitivity"), [_edge("r", "returns", "m", "returns"), _edge("o", "weights", "m", "weights")])
    m = _run(g)["nodes"]["m"]
    assert m["status"] == "ok", m["reason"]
    want = allocation_sensitivity(SensitivityRequest(tickers=T3, views=[VIEW], lookback_days=756))
    assert m["view"]["result"]["matrix"] == want["matrix"]
    assert m["view"]["basis"] == "bl"
    assert not any(t["state"] == "assumed" for t in m["explain"]["trust"]), "BL + 뷰는 같은 기준이다"


def test_sensitivity_says_it_is_measured_on_the_mean_variance_basis_for_other_models(market):
    m = _run(_sens_graph(model="hrp"))["nodes"]["m"]
    assert m["status"] == "ok", m["reason"]
    assumed = [t["text"] for t in m["explain"]["trust"] if t["state"] == "assumed"]
    assert assumed and "기준" in assumed[0]


# ── 팩터 성격 ────────────────────────────────────────────────────────────────

def _xray_graph():
    return _with(chain(), _node("x", "factor_xray"), [_edge("o", "weights", "x", "weights")])


def test_factor_xray_equals_the_route(market, monkeypatch):
    _patch_xray(monkeypatch)
    g = _xray_graph()
    x = _run(g)["nodes"]["x"]
    assert x["status"] == "ok", x["reason"]
    assert x["view"]["result"] == allocation_factor_xray(XrayRequest(holdings=_weights_pct(g)))
    assert x["lineage"]["practice"] is False


def test_factor_xray_on_the_synthetic_sample_is_practice(market, monkeypatch):
    _patch_xray(monkeypatch)
    monkeypatch.setattr("src.data.snapshot_db.sample_factors", lambda limit=500: [])
    x = _run(_xray_graph())["nodes"]["x"]
    assert x["status"] == "ok", x["reason"]
    assert x["lineage"]["practice"] is True


# ── 공통 ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind", ["scenario_stress", "corr_stress", "sensitivity", "factor_xray"])
def test_every_check_node_lives_in_the_check_stage(kind):
    spec = gn.REGISTRY.get(kind)
    assert spec is not None and spec.stage == "check" and spec.explain is not None


def test_check_nodes_never_accept_empty_weights(market):
    """★공허 금지★ 비중 없는 입력은 계산하지 않는다 — 조용한 균등가중 대체가 없다."""
    from src.api.allocation_graph_nodes_check import holdings_pct
    with pytest.raises(pg.NodeFailure):
        holdings_pct({"names": T3, "weights": np.zeros(3)})


def test_every_check_node_speaks_politely_without_overclaiming(market, monkeypatch, flat_shock):
    from tests.test_allocation_graph_explain import FORBIDDEN, _texts
    _patch_xray(monkeypatch)
    g = chain()
    _with(g, _node("s1", "scenario_stress", scenario="rate_hike_200bp"), [_edge("o", "weights", "s1", "weights")])
    _with(g, _node("s2", "scenario_stress", scenario="hist_2020_covid"), [_edge("o", "weights", "s2", "weights")])
    _with(g, _node("s3", "scenario_stress", scenario="semi_selloff"), [_edge("o", "weights", "s3", "weights")])
    _with(g, _node("c", "corr_stress"), [_edge("r", "returns", "c", "returns"), _edge("o", "weights", "c", "weights")])
    _with(g, _node("m", "sensitivity"), [_edge("r", "returns", "m", "returns"), _edge("o", "weights", "m", "weights")])
    _with(g, _node("x", "factor_xray"), [_edge("o", "weights", "x", "weights")])
    rep = _run(g)
    for nid in ("s1", "s2", "s3", "c", "m", "x"):
        r = rep["nodes"][nid]
        assert r["status"] == "ok", (nid, r["reason"])
        assert r["explain"]["title"].endswith("요"), (nid, r["explain"]["title"])
        assert not [t for t in _texts(r["explain"]) for w in FORBIDDEN if w in t], nid


def test_a_historical_replay_says_what_kind_of_performance_it_is(market):
    """★성과 숫자에는 종류 라벨★ (Z4) — 고정 비중 재생 = 백테스트 종류 + 데이터 축. 짝: 가정 충격은 성과가 아니다."""
    s = _run(_stress_graph(scenario="hist_2020_covid"))["nodes"]["s"]
    lab = s["provenance"]["perf_label"]
    assert lab["kind"] == "backtest" and "고정" in lab["kind_reason"] and lab["data_real"] is True
    hypo = _run(_stress_graph(scenario="semi_selloff"))["nodes"]["s"]
    assert "perf_label" not in hypo["provenance"]


# ★계산 중 DB 쓰기 0★ (BL0) — 이 파일의 모든 그래프 계산이 런타임 쓰기 감시 아래에서 돈다.
from tests.graph_write_guard import graph_write_guard  # noqa: E402,F401

pytestmark = pytest.mark.usefixtures("graph_write_guard")
