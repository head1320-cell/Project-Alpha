"""BS4 골든 — ★방법을 더해도 기존 방법·기본값의 답은 한 자리도 바뀌지 않는다★
==============================================================================
설계 `docs/superpowers/specs/2026-09-29-bs-br-leftovers-design.md` §BS4. 사용자 승인: 기본값(risk_parity)은 그대로,
새 방법은 고를 때만.

방법을 더하기 **전에** 엔진 `combine_sleeves` 의 출력(기존 7 방법 · 입력 있음/없음 · 주기·비용)과 `portfolio_combine` 노드의
몫·비중·view 키를 `tests/golden/sleeve_combine_methods.json` 에 얼렸다. 바뀐 뒤에도 같아야 한다. 더해도 되는 것은
`fallback` 키(엔진 — 대체를 드러낸다)와 view 의 `method_compare`(관측 표)·`market`(위기일 대용)뿐이고, 그 둘은 비교에서 뺀다.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np

os.environ.setdefault("KIS_USE_MOCK", "1")

GOLDEN = Path(__file__).parent / "golden" / "sleeve_combine_methods.json"
#: 방법을 더하면서 새로 생긴 키 — 비교에서 뺀다(그 값은 다른 테스트가 건다).
NEW_ENGINE_KEYS = {"fallback"}
NEW_VIEW_KEYS = {"method_compare", "market"}


def _inputs():
    rng = np.random.default_rng(20260929)
    codes = ["005930", "000660", "035420", "051910", "068270"]
    base = rng.normal(0, 0.01, (300, 1))
    R = base * np.array([1.0, 0.8, 0.3, -0.2, 0.5]) + rng.normal(0, 0.01, (300, 5)) * np.array([1.0, 1.4, 0.7, 1.1, 2.0])
    rm = {c: [float(x) for x in R[:, i]] for i, c in enumerate(codes)}
    sleeves = [{"name": "가", "weights": {"005930": 60.0, "000660": 40.0}},
               {"name": "나", "weights": {"000660": 50.0, "035420": 50.0}},
               {"name": "다", "weights": {"051910": 70.0, "068270": 30.0}}]
    return sleeves, rm


CASES = {
    "equal": {"method": "equal"}, "inverse_vol": {"method": "inverse_vol"}, "risk_parity": {"method": "risk_parity"},
    "default": {}, "min_var": {"method": "min_var"}, "hrp": {"method": "hrp"},
    "score": {"method": "score", "scores": {"가": 3.0, "나": 1.0, "다": 0.0}},
    "score_missing": {"method": "score"},
    "risk_budget": {"method": "risk_budget", "risk_budget": {"가": 50.0, "나": 30.0, "다": 20.0}},
    "risk_budget_missing": {"method": "risk_budget"},
    "rebalance_cost": {"method": "risk_parity", "rebalance_every": {"가": 5, "나": 21}, "rebalance_cost_bps": {"가": 10.0, "나": 10.0, "다": 0.0}},
    "unknown_method": {"method": "whatever"},
}


def engine_case(k: str) -> dict:
    from src.engine.sleeve_combine import combine_sleeves
    sleeves, rm = _inputs()
    out = combine_sleeves(sleeves, ret_matrix=rm, **CASES[k])
    return json.loads(json.dumps({x: v for x, v in out.items() if x not in NEW_ENGINE_KEYS}))


NODE_CASES = {"default": {}, "hrp": {"method": "hrp"}, "equal_rebalance": {"method": "equal", "rebalance": {"s1": "M"}, "cost_bps": 10}}


def node_case(k: str) -> dict:
    from src.api import allocation_graph_nodes as gn
    from src.engine import portfolio_graph as pg
    from tests.test_graph_portfolio_combine import _graph
    r = pg.run(_graph(3, **NODE_CASES[k]), gn.REGISTRY)["nodes"]["p"]
    v = r["view"]
    return json.loads(json.dumps({"status": r["status"], "result": {x: y for x, y in v["result"].items() if x not in NEW_ENGINE_KEYS},
                                  "strategies": v["strategies"], "view_keys": sorted(set(v) - NEW_VIEW_KEYS),
                                  "robustness_available": (v.get("robustness") or {}).get("available")}))


def _want():
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def test_engine_answers_are_unchanged_for_every_existing_method():
    want = _want()["engine"]
    assert set(want) == set(CASES)
    for k in CASES:
        assert engine_case(k) == want[k], k


def test_node_answers_are_unchanged_for_existing_methods_and_the_default(market):  # noqa: F811
    want = _want()["node"]
    for k in NODE_CASES:
        assert node_case(k) == want[k], k


from tests.test_allocation_graph import market  # noqa: E402,F401
