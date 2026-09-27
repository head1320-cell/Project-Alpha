"""BM C2 · 여러 전략 → 한 포트폴리오 — `portfolio_combine` 노드
==============================================================================
설계 `docs/superpowers/specs/2026-09-27-canvas-workspace-design.md` §C2.

캔버스는 설계 스튜디오이면서 **여러 퀀트 전략이 합쳐진 전체 포트폴리오의 흐름**을 보는 곳이다. 전략(상자)마다 비중이 나오고,
이 노드가 그것들을 한 포트폴리오로 합친다.

## 거는 것
- ★배분 정책을 새로 만들지 않는다★ — 기존 `sleeve_combine.combine_sleeves` 를 **그대로** 부른다(골든: 같은 입력으로 직접 부른 값과 같다).
  바뀐 것은 입력 수(2~8)와 전략 이름뿐이다.
- 전략 이름은 파라미터 `labels`(포트 → 이름). 없으면 "전략 1"… 이름이 겹치면 사유와 함께 실패한다(겹치면 엔진의 이름 키가 섞인다).
- 두 전략 미만 · 시세 부족은 사유 실패(지어내지 않는다) — 필수 포트 둘은 엔진 검증이 먼저 막는다.
- 흔들림 최소·HRP 는 풀리지 않으면 엔진이 역변동성으로 바꾼다 — 그 경우인지 **모른다**고 말한다(sleeve_combine 과 같은 고지).
- 보기: 전략별 몫·위험 분담·변동성, 전략 사이 상관(같은 수익 행렬로 `sleeve_analytics`). 작은 그림 = 전략별 몫.
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
from tests.test_allocation_graph import T3, _edge, _node, market  # noqa: E402,F401

pytestmark = pytest.mark.usefixtures("graph_write_guard")

A, B, C = T3


def _graph(n_strategies=2, **params):
    """전략마다 '지금 비중' 노드 하나(유니버스 비중을 그대로 Weights 로) — 옵티마이저 없이 결정적인 입력."""
    books = [{A: 60.0, B: 40.0}, {B: 50.0, C: 50.0}, {A: 20.0, C: 80.0}, {A: 100.0}]
    nodes, edges = [], []
    for i in range(n_strategies):
        w = books[i % len(books)]
        nodes += [_node(f"u{i}", "universe", tickers=list(w), weights=w), _node(f"w{i}", "current_weights")]
        edges += [_edge(f"u{i}", "universe", f"w{i}", "universe"), _edge(f"w{i}", "weights", "p", f"s{i + 1}")]
    nodes.append(_node("p", "portfolio_combine", **params))
    return {"format": pg.FORMAT, "version": pg.VERSION, "nodes": nodes, "edges": edges}


def _run(g):
    return pg.run(g, gn.REGISTRY)


def test_the_node_has_eight_weights_inputs_two_required_and_one_weights_output():
    spec = gn.REGISTRY.get("portfolio_combine")
    assert spec is not None
    assert [(p.name, p.type, p.required) for p in spec.inputs] == \
        [(f"s{i}", "Weights", i <= 2) for i in range(1, 9)]
    assert [(p.name, p.type) for p in spec.outputs] == [("weights", "Weights")]
    assert spec.stage == "build" and spec.explain is not None and spec.plain_label and spec.glance is not None


def test_combined_weights_are_exactly_combine_sleeves_on_the_same_inputs(market):
    """골든 — 노드 = 같은 슬리브·같은 방식·같은 수익 행렬로 `combine_sleeves` 를 직접 부른 값."""
    from src.engine.sleeve_combine import _load_ret_matrix, combine_sleeves
    g = _graph(3, method="inverse_vol", labels={"s1": "가치", "s2": "모멘텀", "s3": "배당"})
    r = _run(g)["nodes"]["p"]
    assert r["status"] == "ok", r["reason"]
    sleeves = [{"name": "가치", "weights": {A: 60.0, B: 40.0}}, {"name": "모멘텀", "weights": {B: 50.0, C: 50.0}},
               {"name": "배당", "weights": {A: 20.0, C: 80.0}}]
    want = combine_sleeves(sleeves, method="inverse_vol", ret_matrix=_load_ret_matrix(sleeves))
    got = r["view"]["result"]
    for k in ("sleeve_allocation", "risk_contribution_pct", "sleeve_vol_pct", "combined_weights_pct", "n_sleeves", "method"):
        assert got[k] == want[k], k
    vals = pg._execute(g, gn.REGISTRY)[1]["p"]["weights"]
    assert dict(zip(vals["names"], [round(float(x) * 100, 4) for x in vals["weights"]])) == want["combined_weights_pct"]
    json.dumps(r, allow_nan=False)


def test_a_different_method_gives_a_different_split_pair(market):
    """짝 — 방식을 바꾸면 전략별 몫이 바뀐다(방식 파라미터가 실제로 전달된다)."""
    eq = _run(_graph(2, method="equal"))["nodes"]["p"]["view"]["result"]["sleeve_allocation"]
    iv = _run(_graph(2, method="inverse_vol"))["nodes"]["p"]["view"]["result"]["sleeve_allocation"]
    assert list(eq.values()) == [50.0, 50.0]
    assert eq != iv


def test_default_labels_follow_the_port_and_skipped_ports_keep_their_number(market):
    g = _graph(2)
    # 두 번째 전략을 s3 로 옮긴다(s2 는 비움) — 필수 포트라 검증이 먼저 막는다.
    g["edges"][-1]["target_port"] = "s3"
    rep = _run(g)
    assert rep["nodes"]["p"]["status"] == "blocked"
    ok = _run(_graph(2))["nodes"]["p"]
    assert list(ok["view"]["result"]["sleeve_allocation"]) == ["전략 1", "전략 2"]


def test_duplicate_strategy_names_fail_with_a_reason(market):
    r = _run(_graph(2, labels={"s1": "같은 이름", "s2": "같은 이름"}))["nodes"]["p"]
    assert r["status"] == "failed" and "이름" in r["reason"]


def test_a_label_for_an_unknown_port_is_rejected_by_validation():
    rep = pg.validate(_graph(2, labels={"s9": "없는 포트"}), gn.REGISTRY)
    assert not rep["ok"] and [e["node_id"] for e in rep["errors"]] == ["p"] and "s9" in rep["errors"][0]["message"]
    assert pg.validate(_graph(2, labels={"s1": "가치"}), gn.REGISTRY)["ok"]          # 짝 — 있는 포트는 통과


def test_strategy_view_lists_share_risk_vol_and_correlation(market):
    r = _run(_graph(3, method="risk_parity", labels={"s1": "가", "s2": "나", "s3": "다"}))["nodes"]["p"]
    v = r["view"]
    assert [s["label"] for s in v["strategies"]] == ["가", "나", "다"]
    assert [s["port"] for s in v["strategies"]] == ["s1", "s2", "s3"]
    res = v["result"]
    for s in v["strategies"]:
        assert s["share_pct"] == res["sleeve_allocation"][s["label"]]
        assert s["risk_pct"] == res["risk_contribution_pct"][s["label"]]
    corr = v["correlation"]
    assert corr["labels"] == ["가", "나", "다"] and len(corr["matrix"]) == 3
    assert all(abs(corr["matrix"][i][i] - 1.0) < 1e-9 for i in range(3))
    top = max(v["strategies"], key=lambda x: x["share_pct"])
    assert r["explain"]["headline"]["value"] == top["share_pct"] and top["label"] in r["explain"]["headline"]["label"]
    g = r["glance"]
    assert g["kind"] == "bars" and sorted(p["value"] for p in g["points"]) == sorted(res["sleeve_allocation"].values())


def test_min_var_says_it_does_not_know_whether_the_fallback_was_used(market):
    ex = _run(_graph(2, method="min_var"))["nodes"]["p"]["explain"]
    assert any(t["state"] == "unknown" and "역변동성" in t["text"] for t in ex["trust"])
    ex2 = _run(_graph(2, method="equal"))["nodes"]["p"]["explain"]
    assert not any("역변동성" in t["text"] for t in ex2["trust"])        # 짝 — 그 방식이 아니면 말하지 않는다


def test_no_price_history_fails_with_the_engine_reason(market, monkeypatch):
    from src.engine import sleeve_combine as sc
    monkeypatch.setattr(sc, "_load_ret_matrix", lambda sleeves, **k: {})
    r = _run(_graph(2))["nodes"]["p"]
    assert r["status"] == "failed" and "시세" in r["reason"]


def test_combined_weights_flow_downstream_to_risk(market):
    g = _graph(2)
    g["nodes"].append(_node("r", "returns"))
    g["nodes"].append(_node("k", "risk"))
    g["edges"] += [_edge("u0", "universe", "r", "universe"), _edge("p", "weights", "k", "weights")]
    rep = _run(g)
    assert rep["nodes"]["p"]["status"] == "ok"
    # 합친 비중에는 공분산이 없다 — 위험 분해는 지어내지 않고 사유와 함께 실패한다(Weights 계약).
    assert rep["nodes"]["k"]["status"] == "failed" and rep["nodes"]["k"]["reason"]
    w = pg._execute(g, gn.REGISTRY)[1]["p"]["weights"]
    assert abs(float(np.abs(np.asarray(w["weights"])).sum()) - 1.0) < 1e-6


def test_a_skipped_optional_port_keeps_its_number_in_the_default_name(market):
    """변이 g — 이름은 포트 번호를 따른다(들어온 순서가 아니다). s3 를 비우고 s4 에 이으면 '전략 4'."""
    g = _graph(3)
    g["edges"][-1]["target_port"] = "s4"
    r = _run(g)["nodes"]["p"]
    assert r["status"] == "ok", r["reason"]
    assert list(r["view"]["result"]["sleeve_allocation"]) == ["전략 1", "전략 2", "전략 4"]
    assert [s["port"] for s in r["view"]["strategies"]] == ["s1", "s2", "s4"]


def test_a_short_leg_keeps_its_sign_through_the_combine(market):
    """변이 j — 롱숏 전략의 숏은 합친 비중에서도 음수(엔진이 gross 기준으로 부호를 지킨다 · 버리지 않는다)."""
    g = _graph(2)
    g["nodes"][0]["params"]["weights"] = {A: -50.0, B: 150.0}          # A 는 이 전략에만 있다 — 합친 뒤에도 숏
    r = _run(g)["nodes"]["p"]
    assert r["status"] == "ok", r["reason"]
    cw = r["view"]["result"]["combined_weights_pct"]
    assert cw[A] < 0
    sleeves = [{"name": "전략 1", "weights": {A: -25.0, B: 75.0}}, {"name": "전략 2", "weights": {B: 50.0, C: 50.0}}]
    from src.engine.sleeve_combine import _load_ret_matrix, combine_sleeves
    want = combine_sleeves(sleeves, method="risk_parity", ret_matrix=_load_ret_matrix(sleeves))["combined_weights_pct"]
    assert cw == want
