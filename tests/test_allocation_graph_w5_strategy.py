"""BK W5 · 전략 묶음 돌려 보기 — `/multibacktest/run(save=False)` 와 같은 수 · 기록하지 않는다
==============================================================================
대상 `src/api/allocation_graph_nodes_strategy.py::_strategy_backtest`

## 거는 것
- 노드 == 문(`save=False`) — 요약·출처·라벨·비용·전략 이름. ★실행 기록이 늘지 않는다★(런 목록 0).
- 기간을 비우면 **고른 전략이 함께 기록된 전체** — 명시한 같은 기간의 문과 같은 수이고, 화면이 그렇다고 말한다.
- `hrp_macro` 는 선택지에 없다(배분기 `METHODS` 그대로) · 노드의 리밸런싱 선택지는 엔진이 전부 받는다.
- 없는 전략은 엔진의 사유 그대로 실패한다. 원천이 mock 이면 결과도 연습용.

★숫자는 아무것도 말하지 않는다★ — 결정적 합성 계열이다(`tests/test_strategy_registry.py`).
"""
from __future__ import annotations

import pytest

from src.api import allocation_graph_nodes as gn
from src.engine import portfolio_graph as pg
from tests.test_multistrategy_routes import _RUN, _S, _two_runs, client  # noqa: F401
from tests.test_strategy_registry import db, market  # noqa: F401


def _ids(client):
    return [client.post(f"{_S}/strategies", json={"run_id": r}).json()["id"] for r in _two_runs()]


def _graph(**params):
    return {"format": pg.FORMAT, "version": pg.VERSION,
            "nodes": [{"id": "m", "type": "strategy_backtest", "params": params, "position": {"x": 0, "y": 0}}],
            "edges": []}


def _node(**params):
    return pg.run(_graph(**params), gn.REGISTRY)["nodes"]["m"]


_KNOBS = {k: _RUN[k] for k in ("start_date", "end_date", "allocation_method", "rebalance_policy", "lookback_days")}


@pytest.mark.parametrize("method", ["hrp", "inverse_vol"])
def test_the_node_equals_the_route_and_records_nothing(client, method):
    ids = _ids(client)
    m = _node(strategy_ids=ids, **{**_KNOBS, "allocation_method": method})
    assert m["status"] == "ok", m["reason"]
    ref = client.post(f"{_S}/run", json={**_RUN, "strategy_ids": ids, "allocation_method": method,
                                          "save": False}).json()
    v = m["view"]
    assert v["summary"] == ref["summary"] and v["sources"] == ref["sources"]
    assert v["perf_label"] == ref["perf_label"] and v["cost_model"] == ref["cost_model"]
    assert v["strategy_names"] == {str(k): n for k, n in ref["strategy_names"].items()}
    assert [p["equity"] for p in v["curve"]] == [r["portfolio_equity"] for r in ref["daily_records"]]
    assert client.get(f"{_S}/runs").json()["count"] == 0               # 계산은 기록하지 않는다


def test_an_empty_period_means_the_whole_common_record(client, db):
    from src.engine.strategy_registry import StrategyRegistry
    ids = _ids(client)
    m = _node(strategy_ids=ids, allocation_method="hrp", lookback_days=60)
    assert m["status"] == "ok", m["reason"]
    mat = StrategyRegistry(db).load_returns_matrix(ids, drop_na_rows=True)
    first, last = str(mat.index.min().date()), str(mat.index.max().date())
    assert m["view"]["period"] == {"start": first, "end": last, "whole_record": True}
    ref = client.post(f"{_S}/run", json={**_RUN, "strategy_ids": ids, "start_date": first, "end_date": last,
                                          "save": False}).json()
    assert m["view"]["summary"] == ref["summary"]
    assert "함께 기록된 전체" in " ".join(m["explain"]["facts"])


def test_mock_sources_make_a_practice_result(client):
    m = _node(strategy_ids=_ids(client), **_KNOBS)
    assert m["lineage"]["practice"] is True and m["view"]["perf_label"]["data_real"] is False


def test_an_unknown_strategy_fails_with_the_engine_reason(client):
    m = _node(strategy_ids=[999], **_KNOBS)
    assert m["status"] == "failed" and "999" in m["reason"]


def test_hrp_macro_is_not_offered_and_is_refused():
    from src.engine.allocator import METHODS
    cat = {c["type"]: c for c in gn.REGISTRY.catalog()}
    prop = cat["strategy_backtest"]["params_schema"]["properties"]["allocation_method"]
    assert set(prop["enum"]) == set(METHODS) and "hrp_macro" not in prop["enum"]
    m = _node(strategy_ids=[1], allocation_method="hrp_macro")
    assert m["status"] != "ok" and "allocation_method" in m["reason"]


def test_every_offered_rebalance_policy_is_accepted_by_the_engine():
    from src.engine.multi_strategy_backtest import BacktestConfig, MultiStrategyBacktester
    cat = {c["type"]: c for c in gn.REGISTRY.catalog()}
    offered = cat["strategy_backtest"]["params_schema"]["properties"]["rebalance_policy"]["enum"]

    class _Reg:
        def get(self, sid):
            return {"id": sid}
    bt = MultiStrategyBacktester.__new__(MultiStrategyBacktester)
    bt.registry = _Reg()
    for pol in offered:
        cfg = BacktestConfig(strategy_ids=[1], start_date="2024-01-01", end_date="2024-06-01",
                             allocation_method="hrp", rebalance_policy=pol)
        assert bt._validate_config(cfg)["ok"], pol
    bad = BacktestConfig(strategy_ids=[1], start_date="2024-01-01", end_date="2024-06-01", rebalance_policy="yearly")
    assert not bt._validate_config(bad)["ok"]                          # 짝 — 엔진이 모르는 값은 거절한다


def test_the_strategy_node_speaks_politely_without_overclaiming(client):
    from tests.test_allocation_graph_explain import FORBIDDEN, _texts
    m = _node(strategy_ids=_ids(client), **_KNOBS)
    assert m["explain"]["title"].endswith("요")
    assert not [t for t in _texts(m["explain"]) for w in FORBIDDEN if w in t]
    assert any("기록하지 않고" in t["text"] for t in m["explain"]["trust"])


def test_an_explicit_rate_stays_explicit_and_a_default_stays_default(client):
    """★노드 기본값을 '명시한 요율' 로 넘기지 않는다★ — 짝: 사용자가 정하면 문도 명시로 본다."""
    ids = _ids(client)
    m = _node(strategy_ids=ids, commission_rate=0.0003, **_KNOBS)
    ref = client.post(f"{_S}/run", json={**_RUN, "strategy_ids": ids, "commission_rate": 0.0003,
                                          "save": False}).json()
    assert m["view"]["cost_model"] == ref["cost_model"]
    default = _node(strategy_ids=ids, **_KNOBS)["view"]["cost_model"]
    assert default != m["view"]["cost_model"]
