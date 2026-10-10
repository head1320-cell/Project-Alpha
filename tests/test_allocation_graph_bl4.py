"""BL4 · 마법사 제거 전에 옮기는 계약 — `current_weights` 노드 (지금 비중 → Weights)
==============================================================================
계획 `happy-percolating-falcon.md` §BL4 B4-1 ④. 대응표 `docs/specs/2026-09-27-bl4-wizard-contract-map.md`.

마법사 STRESS 는 "지금 보유" 와 "목표" 를 나란히 흔들었다(`allocation-stress-basis.spec.ts`). 캔버스에서는 옵티마이저 비중만
충격 노드에 이을 수 있어 **지금 보유의 충격**을 볼 길이 없었다. 이 노드가 그 길이다.

## 거는 것
- 유니버스 노드의 '지금 비중' 을 그대로 Weights 로 — gross(Σ|w|)로 나눠 합 100%(`/analyze` 의 PortfolioAnalyzer 와 같은 규칙).
  ★부호 보존★ 숏은 음수 그대로.
- ★없으면 만들지 않는다★ 지금 비중을 안 적었으면 균등 비중으로 바꿔치기하지 않고 사유와 함께 실패한다(마법사 계약:
  "목표가 없으면 복사하지 않고 미계산"). 모두 0 · 목록에 없는 종목도 사유 실패.
- 공분산·규칙은 싣지 않는다 — 하류 위험 분해·정책 백테스트는 기존 규칙대로 사유와 함께 실패한다(지어내지 않는다).
- 지금 비중의 충격과 목표 비중의 충격은 **다른 수**다(같은 값을 복사하지 않는다 — 짝).
"""
from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.api import allocation_graph_nodes as gn  # noqa: E402
from src.engine import portfolio_graph as pg  # noqa: E402
from tests.graph_write_guard import graph_write_guard  # noqa: E402,F401
from tests.test_allocation_graph import T3, _edge, _node, chain, market  # noqa: E402,F401

pytestmark = pytest.mark.usefixtures("graph_write_guard")


def _run(g):
    return pg.run(g, gn.REGISTRY)


def _cw_graph(weights=None, tickers=T3):
    nodes = [_node("u", "universe", tickers=list(tickers), **({"weights": weights} if weights is not None else {})),
             _node("c", "current_weights")]
    return {"format": pg.FORMAT, "version": pg.VERSION, "nodes": nodes,
            "edges": [_edge("u", "universe", "c", "universe")]}


def test_the_node_is_registered_with_a_universe_input_and_a_weights_output():
    spec = gn.REGISTRY.get("current_weights")
    assert spec is not None
    assert [(p.name, p.type, p.required) for p in spec.inputs] == [("universe", "Universe", True)]
    assert [(p.name, p.type) for p in spec.outputs] == [("weights", "Weights")]
    assert spec.stage in {s["key"] for s in gn.STAGES} and spec.explain is not None and spec.plain_label


def test_current_weights_are_the_universe_weights_divided_by_gross():
    a, b, c = T3
    g = _cw_graph({a: 50.0, b: 30.0, c: 20.0})
    rep = _run(g)
    r = rep["nodes"]["c"]
    assert r["status"] == "ok", r["reason"]
    vals = pg._execute(g, gn.REGISTRY)[1]["c"]["weights"]
    assert vals["names"] == [a, b, c]
    assert [round(float(x), 6) for x in vals["weights"]] == [0.5, 0.3, 0.2]
    # 공분산·규칙은 싣지 않는다 — 없는 것을 지어내지 않는다.
    assert vals["sigma_annual"] is None and vals["req"] is None
    assert r["view"]["weights"] == {a: 50.0, b: 30.0, c: 20.0}
    json.dumps(r["view"], allow_nan=False)


def test_units_do_not_matter_only_proportions():
    a, b, c = T3
    x = pg._execute(_cw_graph({a: 5.0, b: 3.0, c: 2.0}), gn.REGISTRY)[1]["c"]["weights"]
    y = pg._execute(_cw_graph({a: 0.5, b: 0.3, c: 0.2}), gn.REGISTRY)[1]["c"]["weights"]
    assert [round(float(v), 9) for v in x["weights"]] == [round(float(v), 9) for v in y["weights"]]


def test_shorts_keep_their_sign_and_gross_is_the_denominator():
    a, b, c = T3
    vals = pg._execute(_cw_graph({a: 60.0, b: 40.0, c: -20.0}), gn.REGISTRY)[1]["c"]["weights"]
    assert [round(float(x), 6) for x in vals["weights"]] == [0.5, round(40 / 120, 6), round(-20 / 120, 6)]


def test_a_ticker_left_out_of_the_weights_is_zero_not_dropped():
    a, b, c = T3
    vals = pg._execute(_cw_graph({a: 70.0, b: 30.0}), gn.REGISTRY)[1]["c"]["weights"]
    assert vals["names"] == [a, b, c]
    assert [round(float(x), 6) for x in vals["weights"]] == [0.7, 0.3, 0.0]


def test_without_current_weights_it_fails_instead_of_inventing_equal_weights():
    r = _run(_cw_graph(None))["nodes"]["c"]
    assert r["status"] == "failed"
    assert "지금 비중" in r["reason"] and "균등" in r["reason"]        # 무엇을 하지 않았는지까지 말한다


def test_all_zero_weights_fail_with_a_reason():
    a, b, c = T3
    r = _run(_cw_graph({a: 0.0, b: 0.0, c: 0.0}))["nodes"]["c"]
    assert r["status"] == "failed" and "0" in r["reason"]


def test_a_weight_for_a_ticker_outside_the_list_fails_with_its_name():
    a, b, _ = T3
    r = _run(_cw_graph({a: 50.0, b: 30.0, "999999": 20.0}))["nodes"]["c"]
    assert r["status"] == "failed" and "999999" in r["reason"]


def test_risk_and_policy_backtest_downstream_fail_honestly():
    a, b, c = T3
    g = _cw_graph({a: 50.0, b: 30.0, c: 20.0})
    g["nodes"] += [_node("r", "returns", lookback_days=756), _node("k", "risk"), _node("bt", "backtest")]
    g["edges"] += [_edge("u", "universe", "r", "universe"), _edge("c", "weights", "k", "weights"),
                   _edge("r", "returns", "bt", "returns"), _edge("c", "weights", "bt", "weights")]
    rep = _run(g)["nodes"]
    assert rep["k"]["status"] == "failed" and "공분산" in rep["k"]["reason"]
    assert rep["bt"]["status"] == "failed" and "규칙" in rep["bt"]["reason"]


def test_stress_on_current_and_on_target_are_two_different_numbers(market):
    """★마법사 계약 — 지금 보유와 목표를 나란히★ 두 충격이 같은 값이면 한쪽을 복사한 것이다(짝)."""
    a, b, c = T3
    g = chain(weights={a: 80.0, b: 10.0, c: 10.0}, risk=False)
    g["nodes"] += [_node("c", "current_weights"),
                   _node("sc", "scenario_stress", scenario="rate_hike_200bp"),
                   _node("st", "scenario_stress", scenario="rate_hike_200bp")]
    g["edges"] += [_edge("u", "universe", "c", "universe"),
                   _edge("c", "weights", "sc", "weights"), _edge("o", "weights", "st", "weights")]
    rep = _run(g)["nodes"]
    for k in ("c", "sc", "st", "o"):
        assert rep[k]["status"] == "ok", (k, rep[k]["reason"])
    cur, tgt = rep["sc"]["view"]["result"], rep["st"]["view"]["result"]
    assert json.dumps(cur, sort_keys=True) != json.dumps(tgt, sort_keys=True)


def test_the_explainer_names_the_source_and_what_it_does_not_carry():
    a, b, c = T3
    r = _run(_cw_graph({a: 50.0, b: 30.0, c: 20.0}))["nodes"]["c"]
    text = json.dumps(r["explain"], ensure_ascii=False)
    assert "지금 비중" in text and "공분산" in text


# ══ 타이밍 신호 — 쓸 수 없는 팩터는 위험-오프로 조용히 세지 않는다 (마법사 팩터 창의 계약) ═════════════
# 마법사 창은 소스 없는 팩터 · 시점(as_of)이 필요한 팩터를 "추가할 수 없습니다 + 사유" 로 막았다. 캔버스의 규칙 칸은
# 문자열이라 무엇이든 들어가고, 읽지 못한 팩터는 결합 규칙이 **위험-오프로 접는다** — 소스가 없어서 영원히 못 읽는
# 팩터가 노출을 조용히 깎는다. 노드가 먼저 막는다(엔진·결합 규칙은 그대로).

def _timing(rules, **params):
    g = {"format": pg.FORMAT, "version": pg.VERSION,
         "nodes": [_node("t", "timing_signal", rules=rules, **params)], "edges": []}
    return _run(g)["nodes"]["t"]


def _catalog(pred):
    from src.engine.timing_factors import CATALOG
    return next(c for c in CATALOG if pred(c))


def test_a_factor_without_a_data_source_is_refused_with_the_catalog_reason():
    c = _catalog(lambda c: c.get("availability") == "unavailable")
    r = _timing([{"factor_id": "abs_mom"}, {"factor_id": c["id"]}])
    assert r["status"] == "failed"
    assert c["label"] in r["reason"] and c["unavailable_reason"] in r["reason"]


def test_an_unknown_factor_is_refused_not_folded_into_risk_off():
    r = _timing([{"factor_id": "abs_mom"}, {"factor_id": "no_such_factor"}])
    assert r["status"] == "failed" and "no_such_factor" in r["reason"]


def test_an_as_of_factor_needs_a_date_and_says_so():
    c = _catalog(lambda c: c.get("requires_as_of") and c.get("availability") != "unavailable")
    r = _timing([{"factor_id": c["id"]}])
    assert r["status"] == "failed" and "기준일" in r["reason"] and c["label"] in r["reason"]


def test_an_as_of_factor_with_a_date_is_not_refused_by_the_node():
    """짝 — 기준일을 넣으면 노드가 막지 않는다(읽기 결과는 데이터에 달렸다 — 막는 것은 '영원히 못 읽음' 뿐)."""
    c = _catalog(lambda c: c.get("requires_as_of") and c.get("availability") != "unavailable")
    r = _timing([{"factor_id": c["id"]}], as_of="2024-06-28")
    assert "기준일" not in (r["reason"] or "")


def test_available_factors_still_run():
    """짝 — 카탈로그에서 쓸 수 있는 팩터는 그대로 계산한다(항상-거부 구현을 배제)."""
    r = _timing([{"factor_id": "abs_mom"}, {"factor_id": "ma_month"}])
    assert r["status"] == "ok", r["reason"]
