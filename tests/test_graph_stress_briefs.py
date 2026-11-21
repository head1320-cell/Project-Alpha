"""BO O4 · 충격 결과(StressReport) 선 요약 — 생산 노드 셋의 모양을 실제로 돌려 확인한 것만
==============================================================================
BN N2 는 "모양이 둘이고 단위가 분명하지 않다" 며 충격 결과를 요약하지 않았다. 여기서 생산 노드(시나리오 충격 ·
상관 스트레스 · 직접 만든 시나리오)를 실제로 돌려 값을 엿보고, 각 노드의 설명(explain)이 쓰는 키·단위와 같은 글을 쓴다.

## 거는 것
- 골든(실제 실행) — 엿본 값에서 테스트가 직접 기대 글을 만들고, 선 요약 = 그 글 · 선 요약의 숫자 = 그 노드 설명의 헤드라인 숫자.
- 짝 — 모양이 틀리면(결과 없음·숫자 아님·모르는 모양) 요약하지 않는다 · 상관 스트레스의 `delta_vol_pct` 는 쓰지 않는다.
- 길이 한도 안 · 긴 시나리오 이름은 빼고 숫자만.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.api import allocation_graph_glance as gl  # noqa: E402
from src.api import allocation_graph_nodes as gn  # noqa: E402
from src.engine import portfolio_graph as pg  # noqa: E402
from tests.graph_write_guard import graph_write_guard  # noqa: E402,F401
from tests.test_allocation_graph import T3, _edge, _node, chain, market  # noqa: E402,F401
from tests.test_graph_briefs_more import _spy  # noqa: E402

pytestmark = pytest.mark.usefixtures("graph_write_guard")


def _signed(x: float) -> str:
    return ("+" if x >= 0 else "−") + f"{abs(x):.1f}%"


def _expect(v) -> str:
    r = v["result"]
    label = (v.get("pack") or r.get("pack") or {}).get("label")
    head = f"{label} · " if label and len(label) <= 28 else ""
    if r.get("mode") == "historical":
        return f"{head}최대 낙폭 {_signed(r['max_dd_pct'])}"
    if "portfolio_shock_pct" in r:
        return f"{head}추정 충격 {_signed(r['portfolio_shock_pct'])}"
    if "shock_pct" in r:
        return f"{head}예상 충격 {_signed(r['shock_pct'])}"
    return f"위기 때 연 변동성 {r['stressed']['port_vol_pct']:.1f}%"


def test_the_three_producers_briefs_equal_the_text_rebuilt_from_their_values(market, monkeypatch):
    seen = _spy(monkeypatch)
    g = chain(risk=False)
    add = [("sh", "scenario_stress", {"scenario": "rate_hike_200bp"}), ("cr", "corr_stress", {}),
           ("cu", "custom_scenario", {"label": "내 충격", "market_shock": -5.0, "value": -3.0})]
    g["nodes"] += [_node(i, t, **p) for i, t, p in add]
    g["edges"] += [_edge("o", "weights", "sh", "weights"), _edge("o", "weights", "cr", "weights"),
                   _edge("r", "returns", "cr", "returns"), _edge("o", "weights", "cu", "weights")]
    rep = pg.run(g, gn.REGISTRY)["nodes"]
    checked = 0
    for nid in ("sh", "cr", "cu"):
        r = rep[nid]
        if r["status"] != "ok":
            pytest.fail(f"{nid}: {r['reason']}")
        value = next(v for (st, pn, v) in seen["StressReport"] if st == r["type"] and pn == "stress")
        assert r["briefs"].get("stress") == _expect(value), (nid, r["briefs"])
        # 선 요약의 숫자 = 그 노드 설명의 헤드라인 숫자(같은 키·같은 단위)
        head = r["explain"]["headline"]
        assert f"{abs(float(head['value'])):.1f}%" in r["briefs"]["stress"], (nid, head, r["briefs"])
        checked += 1
    assert checked == 3


@pytest.mark.parametrize("bad", [
    None, {}, {"result": None}, {"result": {}},
    {"result": {"mode": "historical", "max_dd_pct": None}},
    {"result": {"portfolio_shock_pct": "3"}},
    {"result": {"shock_pct": float("nan")}},
    {"result": {"stressed": {"port_vol_pct": None}, "delta_vol_pct": 5.0}},
    {"result": {"delta_vol_pct": 5.0}},                    # ★단위가 분명하지 않은 값만 있으면 쓰지 않는다★
])
def test_a_value_of_the_wrong_shape_is_not_summarised(bad):
    assert gl.BRIEFS["StressReport"](bad) is None


def test_label_is_dropped_when_too_long_and_every_brief_fits():
    long = "아주 긴 시나리오 이름 " * 6
    assert gl.BRIEFS["StressReport"]({"pack": {"label": long}, "result": {"portfolio_shock_pct": -12.345}}) == "추정 충격 −12.3%"
    assert gl.BRIEFS["StressReport"]({"pack": {"label": "금리 +200bp"}, "result": {"portfolio_shock_pct": 0.0}}) == "금리 +200bp · 추정 충격 +0.0%"
    for v in ({"pack": {"label": "가" * 28}, "result": {"mode": "historical", "max_dd_pct": -99.99}},
              {"result": {"stressed": {"port_vol_pct": 123.456}}},
              {"result": {"pack": {"label": "나" * 28}, "shock_pct": -1000.0}}):
        s = gl.BRIEFS["StressReport"](v)
        assert isinstance(s, str) and 0 < len(s) <= pg.BRIEF_MAX, s
