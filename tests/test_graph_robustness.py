"""BR R1a — 전략 합치기 노드의 견고성 절(`view.robustness`) · 노드 층 `allocation_graph_robustness`.

거는 것:
- 합치기의 몫·비중은 그대로다(견고성은 관측만 — 기존 골든 테스트가 `combine_sleeves` 와 같음을 지킨다).
- 견고성은 합치기와 **같은 흐름**(`_sleeve_return_series` — 주기·비용 포함)으로 잰다.
- 시장 대용이 없으면 위기일을 전략 평균으로 고르고 라벨과 사유를 단다 · 있으면 라벨 없음(짝).
- 계산이 깨지면 합치기는 성공하고 이 절만 `available: False` + 사유(조용히 비우지 않는다).
- 충격: 지금 상관이 이미 목표 이상이면 올리지 않고 사유 · 아니면 흔들림이 커진다(짝).
- 숏 비중은 흐름에서 빠진다 — 그 수를 밝힌다 · 없으면 0(짝).
- 응답에 날짜 키가 없다 · 이야기에 판정 어휘가 없다.
"""
from __future__ import annotations

import json
import os

import numpy as np
import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.api import allocation_graph_robustness as agr  # noqa: E402
from tests.graph_write_guard import graph_write_guard  # noqa: E402,F401
from tests.test_allocation_graph import market  # noqa: E402,F401
from tests.test_graph_portfolio_combine import A, B, _graph, _run  # noqa: E402

pytestmark = pytest.mark.usefixtures("graph_write_guard")

BANNED = ("견고함", "검증됨", "입증", "투자 우위", "더 나은 전략")


def _keys(obj) -> set[str]:
    if isinstance(obj, dict):
        return set(map(str, obj)) | set().union(*(_keys(v) for v in obj.values()))
    if isinstance(obj, list):
        return set().union(*(_keys(v) for v in obj)) if obj else set()
    return set()


def test_combine_carries_robustness_from_the_same_series(market):
    from src.engine import sleeve_combine as sc
    from src.engine.strategy_robustness import effective_count
    r = _run(_graph(3, labels={"s1": "가", "s2": "나", "s3": "다"}, rebalance={"s2": "M"}, cost_bps=10))["nodes"]["p"]
    assert r["status"] == "ok", r["reason"]
    rob = r["view"]["robustness"]
    assert rob["available"] is True, rob
    assert rob["names"] == ["가", "나", "다"] and rob["shares_basis"] == "given"
    for k in ("rolling", "crisis", "drawdown", "stability", "effective_n", "diversification", "shock", "story"):
        assert k in rob, k
    # 노드가 쓴 것과 같은 입력으로 흐름을 다시 만든다 — 같은 주기(나: 한 달 = 21거래일)·같은 비용.
    g = _graph(3, labels={"s1": "가", "s2": "나", "s3": "다"})
    books = [n["params"]["weights"] for n in g["nodes"] if n["type"] == "universe"]
    sl = [{"name": nm, "weights": b} for nm, b in zip(["가", "나", "다"], books)]
    names, S = sc._sleeve_return_series(sl, sc._load_ret_matrix(sl), {"가": 1, "나": 21, "다": 1},
                                        {"가": 10.0, "나": 10.0, "다": 10.0})
    assert rob["effective_n"]["value"] == effective_count(names, S)["value"]
    assert rob["n_days"] == S.shape[0]
    json.dumps(r, allow_nan=False)


def test_no_dates_and_no_verdict_words(market):
    rob = _run(_graph(2))["nodes"]["p"]["view"]["robustness"]
    assert not any("date" in k.lower() for k in _keys(rob))
    text = " ".join(rob["story"])
    assert rob["story"] and not any(w in text for w in BANNED)


def test_market_missing_is_labelled_pair(market, monkeypatch):
    monkeypatch.setattr(agr, "market_series", lambda T, market="kr": (None, "시장 대용 시세가 없어요(테스트)"))
    c = _run(_graph(2))["nodes"]["p"]["view"]["robustness"]["crisis"]
    assert c["basis"] == "strategy_mean" and "부풀" in c["note"] and c["market_reason"] == "시장 대용 시세가 없어요(테스트)"
    monkeypatch.setattr(agr, "market_series", lambda T, market="kr": (np.random.default_rng(1).normal(0, .01, T), None))
    c2 = _run(_graph(2))["nodes"]["p"]["view"]["robustness"]["crisis"]
    assert c2["basis"] == "market" and "market_reason" not in c2


def test_a_broken_robustness_keeps_the_combine_and_says_why(market, monkeypatch):
    from src.engine import strategy_robustness as sr

    def boom(*a, **k):
        raise RuntimeError("테스트 고장")
    monkeypatch.setattr(sr, "robustness_report", boom)
    r = _run(_graph(2))["nodes"]["p"]
    assert r["status"] == "ok"
    rob = r["view"]["robustness"]
    assert rob["available"] is False and "테스트 고장" in rob["reason"]


def test_shock_is_not_applied_when_correlation_is_already_higher():
    rng = np.random.default_rng(3)
    x = rng.normal(0, 0.01, 400)
    S = np.column_stack([x, x * 0.9 + rng.normal(0, 0.001, 400)])          # 상관 ≈ 0.99
    s = agr.shock_block(["A", "B"], S, None, 0.8, None)
    assert s["scenarios"][0]["available"] is False and "이미" in s["scenarios"][0]["reason"]
    S2 = np.column_stack([x, rng.normal(0, 0.01, 400)])                     # 짝 — 상관 ≈ 0
    s2 = agr.shock_block(["A", "B"], S2, None, 0.8, 0.3)
    a, o = s2["scenarios"]
    assert (a["kind"], o["kind"]) == ("assumed", "observed")
    assert a["available"] and a["stressed_vol_pct"] > a["base_vol_pct"] and a["delta_vol_pct"] > 0
    assert o["available"] and 0 < o["delta_vol_pct"] < a["delta_vol_pct"]


def test_shorts_dropped_are_counted_pair(market):
    g = _graph(2)
    g["nodes"][0]["params"]["weights"] = {A: -50.0, B: 150.0}
    assert _run(g)["nodes"]["p"]["view"]["robustness"]["shorts_dropped"] == 1
    assert _run(_graph(2))["nodes"]["p"]["view"]["robustness"]["shorts_dropped"] == 0


def test_story_mentions_effective_count_and_shock(market):
    rob = _run(_graph(3))["nodes"]["p"]["view"]["robustness"]
    text = " ".join(rob["story"])
    assert f"약 {rob['effective_n']['value']:.1f}개" in text
    ex = _run(_graph(3))["nodes"]["p"]["explain"]
    assert any("따로 움직였어요" in f for f in ex["facts"])


# ══ R1b · 견고성 비교 노드(`sleeve_analytics` 올림) ═══════════════════════════════

from src.api import allocation_graph_nodes as gn  # noqa: E402
from src.engine import portfolio_graph as pg  # noqa: E402
from tests.test_allocation_graph import _edge, _node  # noqa: E402
from tests.test_graph_portfolio_combine import C  # noqa: E402


def _compare(n=2, **params):
    books = [{A: 60.0, B: 40.0}, {B: 50.0, C: 50.0}, {A: 20.0, C: 80.0}, {A: 100.0}]
    nodes, edges = [], []
    for i in range(n):
        nodes += [_node(f"u{i}", "universe", tickers=list(books[i]), weights=books[i]), _node(f"w{i}", "current_weights")]
        edges += [_edge(f"u{i}", "universe", f"w{i}", "universe"), _edge(f"w{i}", "weights", "s", "abcd"[i])]
    nodes.append(_node("s", "sleeve_analytics", **params))
    return {"format": pg.FORMAT, "version": pg.VERSION, "nodes": nodes, "edges": edges}


def test_compare_node_is_named_for_what_it_does():
    spec = gn.REGISTRY.get("sleeve_analytics")
    assert spec.label == "견고성 비교" and "무너지" in spec.plain_label
    assert spec.params_model is not None
    d = spec.params_model()
    assert (d.period, d.window, d.shock_rho) == ("1y", 60, 0.8)
    assert spec.glance is not None


def test_compare_node_carries_robustness_and_the_old_table(market):
    r = pg.run(_compare(3), gn.REGISTRY)["nodes"]["s"]
    assert r["status"] == "ok", r["reason"]
    v = r["view"]
    assert v["result"]["sleeves"] == ["묶음 1", "묶음 2", "묶음 3"]
    rob = v["robustness"]
    assert rob["available"] and rob["names"] == ["묶음 1", "묶음 2", "묶음 3"] and rob["shares_basis"] == "equal"
    assert v["requested_days"] == 252 and v["ports"] == ["a", "b", "c"]
    assert r["glance"]["kind"] == "bars" and len(r["glance"]["points"]) == 3
    ex = r["explain"]
    assert any(t["state"] == "assumed" and "실제 운용 기록이 아니에요" in t["text"] for t in ex["trust"])
    assert "앞으로도 같을지" in " ".join(ex["unmeasured"])
    json.dumps(r, allow_nan=False)


def test_compare_params_reach_the_report_pair(market):
    a = pg.run(_compare(2, window=20, shock_rho=0.9), gn.REGISTRY)["nodes"]["s"]["view"]["robustness"]
    b = pg.run(_compare(2), gn.REGISTRY)["nodes"]["s"]["view"]["robustness"]
    assert a["rolling"]["window"] == 20 and b["rolling"]["window"] == 60
    assert a["shock"]["scenarios"][0]["rho"] == 0.9 and b["shock"]["scenarios"][0]["rho"] == 0.8


def test_compare_period_three_years_asks_for_more_days(market, monkeypatch):
    from src.engine import sleeve_combine as sc
    seen = []
    real = sc._load_ret_matrix

    def spy(sleeves, market="kr", lookback=252):
        seen.append(lookback)
        return real(sleeves, market=market, lookback=lookback)
    monkeypatch.setattr(sc, "_load_ret_matrix", spy)
    v = pg.run(_compare(2, period="3y"), gn.REGISTRY)["nodes"]["s"]["view"]
    assert seen and seen[-1] == 756 and v["requested_days"] == 756
    assert v["robustness"]["n_days"] <= 756


def test_compare_node_failure_is_a_failure_not_an_empty_ok(market, monkeypatch):
    """예전: 엔진의 {"error": True} 를 `available is False` 로 봐서 '완료 + 빈 표' 였다."""
    from src.engine import sleeve_combine as sc
    monkeypatch.setattr(sc, "_load_ret_matrix", lambda sleeves, **k: {})
    r = pg.run(_compare(2), gn.REGISTRY)["nodes"]["s"]
    assert r["status"] == "failed" and "시세" in r["reason"]


def test_robustness_declares_what_the_numbers_are_pair(market, monkeypatch):
    """낙폭·흔들림은 '지금 비중을 과거에 들고 있었다면'의 과거 데이터 위 시뮬레이션 — 응답이 성과 종류를 선언한다(PerfLabel 계약).
    짝: mock 이면 데이터 축이 합성(False), 아니면 실데이터(True) — 화면이 지어내지 않고 이 값을 그린다."""
    rob = _run(_graph(2))["nodes"]["p"]["view"]["robustness"]
    lab = rob["perf_label"]
    assert lab["kind"] == "backtest" and lab["data_real"] is False and "지금 비중" in lab["kind_reason"]
    monkeypatch.setattr(agr, "mock_allowed", lambda: False)
    assert agr.robustness_view(["A", "B"], np.random.default_rng(1).normal(0, 0.01, (300, 2)), None)["perf_label"]["data_real"] is True
