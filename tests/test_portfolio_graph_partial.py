"""BL1 · 여기까지 계산 — 한 노드와 그 조상만 계산한다 (n8n "Execute step" 에서 가져온 패턴)
==============================================================================
대상 `src/engine/portfolio_graph.py::run(targets=)` · 문 `POST /api/v1/allocation/graph/run?targets=`

## 거는 것
- 대상과 그 조상만 계산하고, 나머지 노드는 결과에 **없다**(지어내거나 이전 값을 섞지 않는다 — 섞는 것은 화면의 일이고 표시한다).
- 계산한 노드의 값은 전체 계산과 **같다**(같은 view_hash) — 부분 계산이 다른 수를 내지 않는다.
- 보고서가 부분 계산임을 말한다(`partial.targets`·`partial.computed`) · 전체 계산에는 `partial` 이 없다(짝).
- 모르는 대상은 명명된 오류(`unknown_target`) + 아무것도 계산하지 않음.
- 문: 부분 계산에는 증거 관문 판정을 내지 않는다(`gates: null` + 사유) — 짝: 전체 계산은 관문을 낸다.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.api import allocation_graph_nodes as gn  # noqa: E402
from src.engine import portfolio_graph as pg  # noqa: E402
from tests.test_allocation_graph import chain, client, market  # noqa: E402,F401


def test_only_the_target_and_its_ancestors_are_computed(market):
    g = chain(backtest={})                                              # u r e o k(risk) b(backtest)
    rep = pg.run(g, gn.REGISTRY, targets=["o"])
    assert set(rep["nodes"]) == {"u", "r", "e", "o"}
    assert rep["partial"] == {"targets": ["o"], "computed": ["u", "r", "e", "o"]}


def test_a_partial_value_equals_the_full_value(market):
    g = chain(backtest={})
    full = pg.run(g, gn.REGISTRY)
    part = pg.run(g, gn.REGISTRY, targets=["k"])
    assert set(part["nodes"]) == {"u", "r", "e", "o", "k"}
    for nid in part["nodes"]:
        assert part["nodes"][nid]["view_hash"] == full["nodes"][nid]["view_hash"], nid


def test_a_full_run_has_no_partial_block(market):
    assert "partial" not in pg.run(chain(), gn.REGISTRY)


def test_an_unknown_target_is_a_named_error_and_computes_nothing(market):
    rep = pg.run(chain(), gn.REGISTRY, targets=["nope"])
    assert rep["ok"] is False and rep["nodes"] == {}
    assert [e["code"] for e in rep["errors"]] == ["unknown_target"]


def test_the_route_runs_a_part_without_gates_and_the_full_run_with_gates(client, market):
    g = chain(backtest={})
    part = client.post("/api/v1/allocation/graph/run", params={"targets": "o"}, json=g).json()
    assert set(part["nodes"]) == {"u", "r", "e", "o"} and part["gates"] is None
    assert "전체" in part["gates_reason"]
    full = client.post("/api/v1/allocation/graph/run", json=g).json()
    assert full["gates"] and "partial" not in full


# ★계산 중 DB 쓰기 0★ (BL0)
from tests.graph_write_guard import graph_write_guard  # noqa: E402,F401

pytestmark = pytest.mark.usefixtures("graph_write_guard")
