"""CF 3부 PB2 — 정기 점검 흐름 · 주문 목록이 '지금 비중' 두 곳을 견준다 (★관측만 — 주문은 그대로★)
==============================================================================
스펙 `docs/superpowers/specs/2026-10-16-cf-comfy-canvas-claude-design.md` §8.2 · 계획 PB2.

정기 점검 템플릿에서 '지금 들고 있는 비중' 은 유니버스 노드 한 곳에 적는다 — 지금 비중·계좌 점검·보유 진단·리밸런싱 판단
(설정을 비우면 유니버스 쪽을 쓴다)이 모두 그것을 읽는다. 주문 목록만 제 칸(`current_weights`)을 따로 갖는다(이 노드를 고치지
않는다 — 실행 층). 그래서 주문 목록이 ★두 값이 같은지 말한다★: 같음(확인) · 다름(종목과 두 값) · 주문 쪽을 비워 새로 사는 주문.
유니버스에 지금 비중이 없으면 견주지 않는다(말하지 않는다). ★주문 계산은 바꾸지 않는다★ — 견주기만.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.api import allocation_graph_nodes as gn  # noqa: E402
from src.engine import portfolio_graph as pg  # noqa: E402
from tests.graph_write_guard import graph_write_guard  # noqa: E402,F401
from tests.test_allocation_graph import _edge, _node, chain, market  # noqa: E402,F401

pytestmark = pytest.mark.usefixtures("graph_write_guard")

HOLD = {"005930": 50.0, "000660": 30.0, "035420": 20.0}
MOVED = {"005930": 40.0, "000660": 40.0, "035420": 20.0}


def _graph(universe_w, order_w):
    g = chain(weights=universe_w, model="risk_parity", risk=False)
    g["nodes"].append(_node("p", "order_preview", **({"current_weights": order_w} if order_w is not None else {})))
    g["edges"].append(_edge("o", "weights", "p", "weights"))
    return g


def _orders(universe_w, order_w):
    out = pg.run(_graph(universe_w, order_w), gn.REGISTRY)["nodes"]["p"]
    assert out["status"] == "ok", out["reason"]
    return out


def _lines(out, state=None):
    return [t["text"] for t in out["explain"]["trust"] if state is None or t["state"] == state]


def test_same_holdings_are_confirmed(market):
    out = _orders(HOLD, HOLD)
    assert out["view"]["holdings_vs_universe"]["state"] == "same"
    same = [t for t in _lines(out, "confirmed") if "유니버스 노드의 ‘지금 비중’과 같아요" in t]
    assert len(same) == 1
    assert not any("달라요" in t for t in _lines(out))                       # 짝 — 같은데 다르다고 하지 않는다


def test_differing_holdings_name_each_code_with_both_values(market):
    out = _orders(HOLD, MOVED)
    cmp_ = out["view"]["holdings_vs_universe"]
    assert cmp_["state"] == "differs"
    assert [d["code"] for d in cmp_["differs"]] == ["000660", "005930"]      # 다른 종목만 — 035420 은 같다
    lines = [t for t in _lines(out, "assumed") if "달라요" in t]
    assert len(lines) == 1
    assert "005930" in lines[0] and "40" in lines[0] and "50" in lines[0] and "000660" in lines[0]
    assert "035420" not in lines[0]
    assert not any("같아요" in t for t in _lines(out))                       # 짝 — 다른데 같다고 하지 않는다


def test_code_missing_on_one_side_counts_as_zero_there(market):
    out = _orders(HOLD, {"005930": 50.0, "000660": 30.0})
    d = {x["code"]: x for x in out["view"]["holdings_vs_universe"]["differs"]}
    assert list(d) == ["035420"] and d["035420"]["order_pct"] == 0.0 and d["035420"]["universe_pct"] == 20.0


def test_empty_order_holdings_say_new_buy_while_universe_has_holdings(market):
    out = _orders(HOLD, {})
    assert out["view"]["holdings_vs_universe"]["state"] == "order_empty"
    lines = [t for t in _lines(out, "assumed") if "새로 사는 주문" in t]
    assert len(lines) == 1 and "3종목" in lines[0]


def test_no_universe_holdings_means_no_comparison(market):
    out = _orders(None, HOLD)
    assert "holdings_vs_universe" not in out["view"]
    assert not any("유니버스 노드의 ‘지금 비중’" in t for t in _lines(out))   # 견줄 것이 없으면 말하지 않는다


def test_comparison_never_changes_the_orders(market):
    """관측만 — 유니버스에 지금 비중이 있든 없든, 같은 주문 칸이면 주문 목록·사전 점검이 같다."""
    g_with, g_without = _graph(HOLD, MOVED), _graph(None, MOVED)
    a, b = pg.run(g_with, gn.REGISTRY)["nodes"], pg.run(g_without, gn.REGISTRY)["nodes"]
    assert a["o"]["view"]["weights"] == b["o"]["view"]["weights"]            # 전제 — 목표 비중이 같다
    assert a["p"]["view"]["plan"] == b["p"]["view"]["plan"]
    assert a["p"]["view"]["pretrade"] == b["p"]["view"]["pretrade"]
    assert a["p"]["view"]["plan"]["orders"]                                  # 공허하지 않다 — 주문이 실제로 있다
    # 주문 칸을 비웠을 때도 — 유니버스 쪽 보유로 몰래 채우지 않는다(비우면 새로 사는 주문, 말은 따로 한다)
    a, b = pg.run(_graph(HOLD, {}), gn.REGISTRY)["nodes"], pg.run(_graph(None, {}), gn.REGISTRY)["nodes"]
    assert a["p"]["view"]["plan"] == b["p"]["view"]["plan"]
    assert all(o["side"] == "buy" for o in a["p"]["view"]["plan"]["orders"])


def test_tiny_rounding_is_not_a_difference(market):
    out = _orders(HOLD, {**HOLD, "005930": 50.004})
    assert out["view"]["holdings_vs_universe"]["state"] == "same"
    out = _orders(HOLD, {**HOLD, "005930": 50.02})                          # 짝 — 0.01%p 를 넘으면 다르다
    assert out["view"]["holdings_vs_universe"]["state"] == "differs"
