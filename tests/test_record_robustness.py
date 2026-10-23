"""BS3 — '기록끼리 견고성' 노드(`record_robustness`): 비중이 아니라 ★이미 있는 기록★끼리 같이 무너지는지.

기록은 셋이다 — 등록한 전략(백테스트 재현 검증을 통과한 일별 수익) · 불러온 백테스트 실행(BacktestRun) ·
정책 백테스트 결과(BacktestResult). ★어느 것도 실거래 기록이 아니다★ — 그렇다고 믿음 칸이 말한다.

거는 것:
- 기록마다 곡선을 일별 수익으로 바꾸고 ★날짜 교집합★으로 맞춘다 · 흐름 둘 이상 · 공통 60일 미만이면 실패 + 사유.
- 출처별 라벨: 등록 전략 = "백테스트 재현 기록 — 실거래 아님" · mock 이면 합성 · PIT 여부. 몫은 같다고 둔다(밝힌다).
- 등록한 전략이 없으면 그렇다고 말한다 · 모르는 id 는 이름을 들어 실패(짝: 있는 id 는 된다).
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd
import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.api import allocation_graph_nodes as gn  # noqa: E402
from src.api import allocation_graph_nodes_record as rec  # noqa: E402
from src.engine import portfolio_graph as pg  # noqa: E402
from tests.test_allocation_graph import market  # noqa: E402,F401


def _dates(n: int, start: str = "2025-01-02") -> list[str]:
    return [d.strftime("%Y-%m-%d") for d in pd.bdate_range(start=start, periods=n)]


def _curve(n: int, seed: int, base: float = 1e8) -> list[float]:
    r = np.random.default_rng(seed).normal(0.0003, 0.01, n - 1)
    return (base * np.concatenate([[1.0], np.cumprod(1 + r)])).tolist()


def _run_value(run_id: str, n: int, seed: int, *, mock: bool | None = True, start: str = "2025-01-02") -> dict:
    """`backtest_load` 의 BacktestRun 포트 값 모양 그대로 — {"run_id", "run": 실행 행}."""
    return {"run_id": run_id, "run": {
        "run_id": run_id, "strategy_name": f"실행 {run_id}", "status": "completed",
        "is_mock_data": mock, "is_pit_verified": False,
        "result": {"backtest": {"equity_dates": _dates(n, start), "equity_curve": _curve(n, seed)}}}}


def _result_value(n: int, seed: int, start: str = "2025-01-02") -> dict:
    """`backtest` 노드의 BacktestResult 포트 값 모양 그대로 — 결과 사전 자체."""
    return {"dates": _dates(n, start), "equity_curve": _curve(n, seed, 1.0)}


def test_two_real_policy_backtests_feed_the_node(market):
    """★모양이 어긋나면 곡선이 비어 실패한다★(E2E 가 찾은 결함) — 진짜 `backtest` 노드 둘의 출력을 잇는다."""
    from tests.test_allocation_graph import _edge, _node, chain
    g = chain(backtest={})
    g["nodes"].append(_node("b2", "backtest", rebalance="Q"))
    g["edges"] += [_edge("r", "returns", "b2", "returns"), _edge("o", "weights", "b2", "weights")]
    bt = next(n["id"] for n in g["nodes"] if n["type"] == "backtest" and n["id"] != "b2")
    g["nodes"].append(_node("rr", "record_robustness"))
    g["edges"] += [_edge(bt, "backtest", "rr", "t1"), _edge("b2", "backtest", "rr", "t2")]
    r = pg.run(g, gn.REGISTRY)["nodes"]["rr"]
    assert r["status"] == "ok", r["reason"]
    assert r["view"]["robustness"]["available"] and r["view"]["robustness"]["axis"] == "date"
    assert [x["source"] for x in r["view"]["series"]] == ["backtest_result", "backtest_result"]


def _params(**k):
    return gn.REGISTRY.get("record_robustness").params_model(**k)


def test_the_node_is_registered_with_record_ports():
    spec = gn.REGISTRY.get("record_robustness")
    assert spec.label == "기록끼리 견고성" and "무너지" in spec.plain_label
    kinds = {p.name: p.type for p in spec.inputs}
    assert kinds == {"r1": "BacktestRun", "r2": "BacktestRun", "r3": "BacktestRun", "r4": "BacktestRun",
                     "t1": "BacktestResult", "t2": "BacktestResult"}
    assert all(not p.required for p in spec.inputs)


def test_runs_and_results_are_lined_up_by_date():
    out = rec._record_robustness({"r1": _run_value("bt_a", 200, 1), "t1": _result_value(180, 2, start="2025-01-20")},
                                 _params())
    v = out.view
    rob = v["robustness"]
    assert rob["available"] and rob["axis"] == "date"
    # 공통 날짜만 — 늦게 시작한 쪽의 첫날부터(첫날은 수익이 없어 그다음 날부터).
    assert rob["period"]["start"] == _dates(180, "2025-01-20")[1]
    assert [s["source"] for s in v["series"]] == ["backtest_run", "backtest_result"]
    assert rob["shares_basis"] == "equal"


def test_each_record_says_what_it_is_and_none_is_live_trading():
    out = rec._record_robustness({"r1": _run_value("bt_a", 200, 1, mock=True),
                                  "r2": _run_value("bt_b", 200, 3, mock=False)}, _params())
    s = {x["label"]: x for x in out.view["series"]}
    assert s["실행 bt_a"]["data"] == "synthetic" and s["실행 bt_b"]["data"] == "real"
    ex = gn.REGISTRY.get("record_robustness").explain(out.view, {}, _params())
    text = " ".join(t["text"] for t in ex["trust"])
    assert "실거래 기록이 아니에요" in text and "몫은 똑같이" in text


def test_unknown_mock_state_is_not_called_real_pair():
    """짝 — mock 여부를 모르면 실데이터라고 하지 않는다."""
    out = rec._record_robustness({"r1": _run_value("bt_a", 200, 1, mock=None),
                                  "r2": _run_value("bt_b", 200, 3, mock=False)}, _params())
    s = {x["label"]: x["data"] for x in out.view["series"]}
    assert s["실행 bt_a"] == "unknown" and s["실행 bt_b"] == "real"


def test_one_record_is_not_enough():
    with pytest.raises(pg.NodeFailure) as e:
        rec._record_robustness({"r1": _run_value("bt_a", 200, 1)}, _params())
    assert "둘 이상" in str(e.value)


def test_too_little_overlap_is_a_failure_with_a_reason():
    with pytest.raises(pg.NodeFailure) as e:
        rec._record_robustness({"r1": _run_value("bt_a", 100, 1, start="2025-01-02"),
                                "r2": _run_value("bt_b", 100, 2, start="2025-05-01")}, _params())
    assert "겹치는 날" in str(e.value)


def test_registered_strategies_are_read_with_their_labels(monkeypatch):
    d = pd.to_datetime(_dates(150))
    mat = pd.DataFrame({7: np.random.default_rng(4).normal(0, .01, 150),
                        9: np.random.default_rng(5).normal(0, .01, 150)}, index=d)
    monkeypatch.setattr(rec, "_registry_rows", lambda ids: (
        mat[[i for i in ids]], {7: {"name": "모멘텀", "is_mock_data": True, "is_pit_verified": False},
                                9: {"name": "가치", "is_mock_data": False, "is_pit_verified": True}}))
    out = rec._record_robustness({}, _params(strategy_ids=[7, 9]))
    s = {x["label"]: x for x in out.view["series"]}
    assert s["모멘텀"]["source"] == "registered" and "실거래 아님" in s["모멘텀"]["note"]
    assert s["가치"]["pit"] is True and s["모멘텀"]["pit"] is False
    assert out.view["robustness"]["n_days"] == 150


def test_an_empty_registry_says_so(monkeypatch):
    monkeypatch.setattr(rec, "_registry_rows", lambda ids: (_ for _ in ()).throw(
        pg.NodeFailure("등록한 전략이 없어요 — 백테스트 결과에서 등록하세요")))
    with pytest.raises(pg.NodeFailure) as e:
        rec._record_robustness({"r1": _run_value("bt_a", 200, 1)}, _params(strategy_ids=[1]))
    assert "등록한 전략이 없어요" in str(e.value)


def test_unknown_strategy_ids_are_named_pair(monkeypatch):
    d = pd.to_datetime(_dates(150))
    mat = pd.DataFrame({7: np.random.default_rng(4).normal(0, .01, 150)}, index=d)
    meta = {7: {"name": "모멘텀", "is_mock_data": True, "is_pit_verified": False}}
    monkeypatch.setattr(rec, "_registry_list", lambda: meta)
    monkeypatch.setattr(rec, "_registry_matrix", lambda ids: mat[[i for i in ids if i in mat.columns]])
    with pytest.raises(pg.NodeFailure) as e:
        rec._record_robustness({}, _params(strategy_ids=[7, 42]))
    assert "42" in str(e.value)
    # 짝 — 있는 id 와 실행 하나면 된다.
    out = rec._record_robustness({"r1": _run_value("bt_a", 200, 1, start="2024-12-02")}, _params(strategy_ids=[7]))
    assert out.view["robustness"]["available"]
