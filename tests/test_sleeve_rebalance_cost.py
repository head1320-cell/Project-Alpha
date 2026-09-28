"""BP P2 · 리밸런싱 거래비용 — 되돌릴 때마다 회전율 × 비용(bp)을 슬리브 흐름에서 뺀다 (사용자 승인 배분 동작 변경)
====================================================================================================
BO O2 는 주기만 넣고 거래비용은 "넣지 않았다" 고 말했다(자주 되돌리는 전략이 유리하게 보인다). 여기서 비용을 넣는다.

## 거는 것
- ★기본값 불변★ 비용 0(또는 없음)이면 BO O2 와 비트 단위로 같다 — 매일 주기면 여전히 `R @ w`.
- 손 계산 골든 — 되돌리는 날 회전율(목표와 흘러간 비중의 차의 절댓값 합, 사고판 양쪽) × 비용을 그날 수익에서 뺀다.
  매일 주기라도 비용이 있으면 매일 되돌리는 비용을 낸다(짝: 비용 0 이면 R @ w).
- 비용이 클수록 슬리브 평균 수익이 낮아진다(단조) · 자주 되돌릴수록 비용 총량이 크다.
- 노드: `cost_bps` 범위·프리셋 · 0 이면 설명이 "넣지 않았어요", 양수면 "회전율 × n bp 를 뺐어요" + 재지 않은 것에 슬리피지.
"""
from __future__ import annotations

import os

import numpy as np
import pytest
from pydantic import ValidationError

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.api import allocation_graph_nodes  # noqa: E402,F401 — 노드 모듈은 레지스트리를 거쳐 들여온다
from src.engine import sleeve_combine as sc  # noqa: E402
from tests.test_sleeve_rebalance import SLEEVES, _graph, _ret  # noqa: E402

ONE = [{"name": "s", "weights": {"X": 50, "Y": 50}}]


def test_zero_cost_is_bit_identical():
    ret = _ret()
    every = {"성장": 21, "안정": 1, "혼합": 5}
    _, a = sc._sleeve_return_series(SLEEVES, ret, rebalance_every=every)
    _, b = sc._sleeve_return_series(SLEEVES, ret, rebalance_every=every, cost_bps={"성장": 0, "안정": 0, "혼합": 0})
    _, c = sc._sleeve_return_series(SLEEVES, ret, rebalance_every=every, cost_bps=None)
    assert np.array_equal(a, b) and np.array_equal(a, c)
    _, d = sc._sleeve_return_series(SLEEVES, ret)
    _, e = sc._sleeve_return_series(SLEEVES, ret, cost_bps={})
    assert np.array_equal(d, e)
    base = sc.combine_sleeves(SLEEVES, method="inverse_vol", ret_matrix=ret)
    assert sc.combine_sleeves(SLEEVES, method="inverse_vol", ret_matrix=ret, rebalance_cost_bps=None) == base


def test_hand_computed_cost_on_rebalance_day():
    """50/50, 2일마다 되돌림, 비용 100bp. 1일 X +10% → (0.55, 0.50). 2일 변화 없음 → 되돌림:
    흘러간 비중 (0.5238, 0.4762) vs 목표 (0.5, 0.5) → 회전율 0.047619 → 그날 수익 = 1·(1 − 0.01·0.047619) − 1."""
    ret = {"X": [0.10, 0.00, 0.00], "Y": [0.00, 0.00, 0.00]}
    _, S = sc._sleeve_return_series(ONE, ret, rebalance_every={"s": 2}, cost_bps={"s": 100})
    to = abs(0.55 / 1.05 - 0.5) + abs(0.50 / 1.05 - 0.5)
    assert np.allclose(S[:, 0], [0.05, -0.01 * to, 0.0], atol=1e-12)


def test_daily_cadence_pays_daily_cost_but_zero_cost_is_r_at_w():
    ret = {"X": [0.10, -0.05], "Y": [0.00, 0.02]}
    _, S = sc._sleeve_return_series(ONE, ret, cost_bps={"s": 100})
    to1 = abs(0.55 / 1.05 - 0.5) * 2
    assert S[0, 0] == pytest.approx(1.05 * (1 - 0.01 * to1) - 1, abs=1e-12)
    _, D = sc._sleeve_return_series(ONE, ret)
    assert np.allclose(D[:, 0], [0.05, -0.015], atol=1e-12)          # 짝 — 비용 없음 = R @ w


def test_more_cost_less_return_and_more_frequent_costs_more():
    ret = _ret()
    means = [sc._sleeve_return_series(SLEEVES, ret, rebalance_every={"성장": 5}, cost_bps={"성장": c})[1][:, 0].mean()
             for c in (0, 10, 30, 100)]
    assert all(a > b for a, b in zip(means, means[1:]))
    def drag(k):
        no = sc._sleeve_return_series(SLEEVES, ret, rebalance_every={"성장": k})[1][:, 0].sum()
        yes = sc._sleeve_return_series(SLEEVES, ret, rebalance_every={"성장": k}, cost_bps={"성장": 30})[1][:, 0].sum()
        return no - yes
    assert drag(1) > drag(21) > 0


def test_bad_cost_is_refused():
    for bad in (-1, float("nan"), 2000):
        with pytest.raises(ValueError):
            sc._sleeve_return_series(SLEEVES, _ret(), cost_bps={"성장": bad})


def test_combine_reports_the_cost_it_used():
    ret = _ret()
    out = sc.combine_sleeves(SLEEVES, method="equal", ret_matrix=ret, rebalance_cost_bps={"성장": 30})
    assert out["rebalance_cost_bps"] == {"성장": 30.0, "안정": 0.0, "혼합": 0.0}


# ── 노드 ───────────────────────────────────────────────────────────────────

def test_params_and_ui():
    from src.api.allocation_graph_nodes_portfolio import PortfolioCombineParams as P
    assert P().cost_bps == 0
    P(cost_bps=200)
    for bad in (-1, 201):
        with pytest.raises(ValidationError):
            P(cost_bps=bad)
    ui = P.model_json_schema()["properties"]["cost_bps"]["x-ui"]
    assert ui["tier"] == "basic" and ui["unit"] == "bp" and ui["question"]
    assert [p["value"] for p in ui["presets"]][0] == 0


def _with_cost(bps, rebalance=None):
    g = _graph(rebalance)
    for n in g["nodes"]:
        if n["id"] == "pc":
            n["params"]["cost_bps"] = bps
    return g


def test_node_zero_cost_equals_before_and_says_no_cost():
    from src.api import allocation_graph_nodes as gn
    from src.engine import portfolio_graph as pg
    a = pg.run(_graph({"s1": "M"}), gn.REGISTRY)["nodes"]["pc"]
    b = pg.run(_with_cost(0, {"s1": "M"}), gn.REGISTRY)["nodes"]["pc"]
    assert a["view"]["result"]["sleeve_allocation"] == b["view"]["result"]["sleeve_allocation"]
    trust = " ".join(t["text"] for t in b["explain"]["trust"])
    assert "거래비용은 넣지 않았어요" in trust
    assert "되돌릴 때 드는 거래비용" in b["explain"]["unmeasured"]


def test_node_cost_moves_numbers_and_explains():
    from src.api import allocation_graph_nodes as gn
    from src.engine import portfolio_graph as pg
    a = pg.run(_graph({"s1": "D", "s2": "W"}), gn.REGISTRY)["nodes"]["pc"]
    c = pg.run(_with_cost(30, {"s1": "D", "s2": "W"}), gn.REGISTRY)["nodes"]["pc"]
    assert c["status"] == "ok", c["reason"]
    assert c["view"]["result"]["sleeve_vol_pct"] != a["view"]["result"]["sleeve_vol_pct"] or \
        c["view"]["result"]["sleeve_allocation"] != a["view"]["result"]["sleeve_allocation"]
    assert c["view"]["cost_bps"] == 30
    trust = " ".join(t["text"] for t in c["explain"]["trust"])
    assert "30bp" in trust and "거래비용은 넣지 않았어요" not in trust
    assert "되돌릴 때 드는 거래비용" not in c["explain"]["unmeasured"]
    assert any("슬리피지" in u for u in c["explain"]["unmeasured"])


def test_analytics_uses_the_costed_series():
    """상관도 비용을 뺀 같은 흐름에서 잰다 — 짝: 비용이 크면 상관이 실제로 달라진다(같은 흐름을 쓰지 않는 구현을 죽인다)."""
    ret = _ret()
    every, cost = {"성장": 1, "안정": 5, "혼합": 1}, {"성장": 1000.0, "안정": 0.0, "혼합": 1000.0}
    _, S = sc._sleeve_return_series(SLEEVES, ret, rebalance_every=every, cost_bps=cost)
    ana = sc.sleeve_analytics(SLEEVES, ret_matrix=ret, rebalance_every=every, rebalance_cost_bps=cost)
    corr = np.corrcoef(S.T)
    assert ana["correlation"]["성장"]["혼합"] == round(float(corr[0, 2]), 3)
    plain = sc.sleeve_analytics(SLEEVES, ret_matrix=ret, rebalance_every=every)
    assert ana["correlation"] != plain["correlation"]


def test_cadence_help_points_to_the_cost_field():
    """주기 칸 도움말이 '거래비용은 넣지 않아요' 라고 말하면 비용 칸이 생긴 지금은 거짓이다(점검 스크린샷에서 찾았다)."""
    from src.api.allocation_graph_nodes_portfolio import PortfolioCombineParams as P
    props = P.model_json_schema()["properties"]
    help_ = props["rebalance"]["x-ui"]["help"]
    assert "넣지 않아요" not in help_ and props["cost_bps"]["x-ui"]["label"] in help_
