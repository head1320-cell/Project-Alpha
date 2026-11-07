"""BO O2 · 전략별 리밸런싱 주기 — 슬리브 수익 흐름을 k 거래일마다 목표 비중으로 되돌린다
====================================================================================
사용자가 이번 선택으로 **승인**한 배분 동작 변경. 지금까지 슬리브 수익은 "매일 지금 비중으로 되돌린" 흐름
(= `R @ w`)이었고, 캔버스 설명의 "재지 않은 것" 에 "전략마다 다른 리밸런싱 주기" 가 있었다.

## 거는 것

- ★기본값 불변★ 주기를 주지 않거나 매일(1)이면 지금과 **비트 단위로 같은** 흐름·배분(골든).
- 손으로 계산한 3일 드리프트 예제와 같다 — k 일 사이에는 보유량이 가격 따라 흐르고, k 일째 끝에 되돌린다.
- 주기가 다르면 슬리브 흐름과 몫이 달라진다(짝 — 주기를 무시하는 구현을 죽인다).
- 노드: 모르는 주기·없는 포트는 거절(사유) · 보기에 전략마다 주기 · 설명의 "재지 않은 것" 에서 빠지고
  대신 무엇을 가정했는지(드리프트·거래비용 미반영)를 말한다.
"""
from __future__ import annotations

import os

import numpy as np
import pytest
from pydantic import ValidationError

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.api import allocation_graph_nodes  # noqa: E402,F401 — 노드 모듈은 레지스트리를 거쳐 들여온다(앱과 같은 순서)
from src.engine import sleeve_combine as sc  # noqa: E402


def _ret(T: int = 300, seed: int = 3) -> dict[str, list[float]]:
    rng = np.random.default_rng(seed)
    mu = np.array([0.0008, 0.0002, 0.0005, -0.0001])
    vol = np.array([0.025, 0.01, 0.018, 0.014])
    R = mu + rng.standard_normal((T, 4)) * vol
    return {c: list(R[:, i]) for i, c in enumerate(["A", "B", "C", "D"])}


SLEEVES = [{"name": "성장", "weights": {"A": 60, "C": 40}},
           {"name": "안정", "weights": {"B": 70, "D": 30}},
           {"name": "혼합", "weights": {"A": 25, "B": 25, "C": 25, "D": 25}}]


# ── 기본값 불변 ─────────────────────────────────────────────────────────────

def test_default_and_daily_are_bit_identical():
    ret = _ret()
    n0, s0 = sc._sleeve_return_series(SLEEVES, ret)
    n1, s1 = sc._sleeve_return_series(SLEEVES, ret, rebalance_every={"성장": 1, "안정": 1, "혼합": 1})
    n2, s2 = sc._sleeve_return_series(SLEEVES, ret, rebalance_every={})
    assert n0 == n1 == n2
    assert np.array_equal(s0, s1) and np.array_equal(s0, s2)


@pytest.mark.parametrize("method", sc.SLEEVE_METHODS)
def test_combine_default_unchanged(method):
    ret = _ret()
    a = sc.combine_sleeves(SLEEVES, method=method, ret_matrix=ret, scores={"성장": 1, "안정": 2, "혼합": 1})
    b = sc.combine_sleeves(SLEEVES, method=method, ret_matrix=ret, scores={"성장": 1, "안정": 2, "혼합": 1},
                           rebalance_every=None)
    assert a == b
    assert "rebalance_every" not in a


# ── 드리프트 산수 ───────────────────────────────────────────────────────────

def test_hand_computed_three_day_drift():
    """두 종목 50/50, 3일마다 되돌림. 1일째 +10%/0%, 2일째 0%/+10%, 3일째 -10%/0%, 4일째(되돌린 뒤) +10%/0%."""
    ret = {"X": [0.10, 0.00, -0.10, 0.10], "Y": [0.00, 0.10, 0.00, 0.00]}
    _, S = sc._sleeve_return_series([{"name": "s", "weights": {"X": 50, "Y": 50}}], ret,
                                    rebalance_every={"s": 3})
    # 1일: 0.5·0.10 = 0.05 → 보유 (0.55, 0.50)
    # 2일: (0.55·0 + 0.50·0.10) / 1.05 = 0.05/1.05 → 보유 (0.55, 0.55)
    # 3일: (0.55·-0.10) / 1.10 = -0.05 → 3일째 끝에 되돌림 → (0.5, 0.5)
    # 4일: 0.5·0.10 = 0.05
    want = [0.05, 0.05 / 1.05, -0.05, 0.05]
    assert np.allclose(S[:, 0], want, atol=1e-12)
    # 짝 — 매일 되돌림이면 2일째는 0.05, 3일째는 -0.05 (드리프트 없음)
    _, D = sc._sleeve_return_series([{"name": "s", "weights": {"X": 50, "Y": 50}}], ret)
    assert np.allclose(D[:, 0], [0.05, 0.05, -0.05, 0.05], atol=1e-12)
    assert not np.isclose(S[1, 0], D[1, 0])


def test_cadence_changes_series_and_shares():
    ret = _ret()
    base = sc.combine_sleeves(SLEEVES, method="inverse_vol", ret_matrix=ret)
    slow = sc.combine_sleeves(SLEEVES, method="inverse_vol", ret_matrix=ret,
                              rebalance_every={"성장": 63, "안정": 1, "혼합": 21})
    assert slow["sleeve_vol_pct"]["성장"] != base["sleeve_vol_pct"]["성장"]
    assert slow["sleeve_vol_pct"]["안정"] == base["sleeve_vol_pct"]["안정"]   # 매일인 전략은 그대로
    assert slow["sleeve_allocation"] != base["sleeve_allocation"]
    assert slow["rebalance_every"] == {"성장": 63, "안정": 1, "혼합": 21}


def test_analytics_uses_the_same_series():
    ret = _ret()
    every = {"성장": 63, "안정": 5, "혼합": 21}
    _, S = sc._sleeve_return_series(SLEEVES, ret, rebalance_every=every)
    ana = sc.sleeve_analytics(SLEEVES, ret_matrix=ret, rebalance_every=every)
    corr = np.corrcoef(S.T)
    assert ana["correlation"]["성장"]["안정"] == round(float(corr[0, 1]), 3)
    assert ana != sc.sleeve_analytics(SLEEVES, ret_matrix=ret)


def test_bad_cadence_is_refused():
    with pytest.raises(ValueError):
        sc._sleeve_return_series(SLEEVES, _ret(), rebalance_every={"성장": 0})


# ── 노드 ───────────────────────────────────────────────────────────────────

def test_params_validate_ports_and_codes():
    from src.api.allocation_graph_nodes_portfolio import PortfolioCombineParams as P
    assert P().rebalance == {}
    assert P(rebalance={"s1": "M", "s3": "Q"}).rebalance == {"s1": "M", "s3": "Q"}
    for bad in ({"s9": "M"}, {"s1": "Y"}, {"s1": "m"}):
        with pytest.raises(ValidationError):
            P(rebalance=bad)


def test_ui_is_per_strategy_choice():
    from src.api.allocation_graph_nodes_portfolio import REBALANCE
    from src.api.allocation_graph_nodes_portfolio import PortfolioCombineParams as P
    ui = P.model_json_schema()["properties"]["rebalance"]["x-ui"]
    assert ui["widget"] == "per_port"
    assert ui["options"] == {k: v[1] for k, v in REBALANCE.items()}
    assert ui["tier"] == "basic" and ui["question"]
    assert ui["empty_value"] == "D"
    assert ui["order"] == ["D", "W", "M", "Q"]      # 짧은 주기부터 — 화면이 이 순서로 그린다                 # 비운 포트 = 매일(지금까지의 흐름)
    assert REBALANCE["D"][0] == 1 and REBALANCE["W"][0] == 5 and REBALANCE["M"][0] == 21 and REBALANCE["Q"][0] == 63


def _graph(rebalance=None):
    from src.engine import portfolio_graph as pg

    def n(id_, t, **p):
        return {"id": id_, "type": t, "params": p, "position": {"x": 0, "y": 0}}

    def e(s, sp, t, tp):
        return {"id": f"{s}.{sp}->{t}.{tp}", "source": s, "source_port": sp, "target": t, "target_port": tp}
    nodes, edges = [], []
    for i, tick in enumerate([["005930", "000660"], ["035420", "051910"], ["005380", "000270"]], start=1):
        nodes += [n(f"u{i}", "universe", tickers=tick), n(f"r{i}", "returns"), n(f"e{i}", "estimate"),
                  n(f"o{i}", "optimizer", model="min_var")]
        edges += [e(f"u{i}", "universe", f"r{i}", "universe"), e(f"r{i}", "returns", f"e{i}", "returns"),
                  e(f"r{i}", "returns", f"o{i}", "returns"), e(f"e{i}", "belief", f"o{i}", "belief"),
                  e(f"o{i}", "weights", "pc", f"s{i}")]
    params = {"method": "inverse_vol", "labels": {"s1": "가", "s2": "나", "s3": "다"}}
    if rebalance is not None:
        params["rebalance"] = rebalance
    nodes.append(n("pc", "portfolio_combine", **params))
    return {"format": pg.FORMAT, "version": pg.VERSION, "nodes": nodes, "edges": edges}


def test_node_default_equals_before_and_explains():
    from src.api import allocation_graph_nodes as gn
    from src.engine import portfolio_graph as pg
    a = pg.run(_graph(), gn.REGISTRY)["nodes"]["pc"]
    b = pg.run(_graph({"s1": "D", "s2": "D", "s3": "D"}), gn.REGISTRY)["nodes"]["pc"]
    assert a["status"] == "ok", a["reason"]
    assert a["view"]["result"]["sleeve_allocation"] == b["view"]["result"]["sleeve_allocation"]
    assert [s["rebalance"] for s in a["view"]["strategies"]] == ["D", "D", "D"]
    assert "전략마다 다른 리밸런싱 주기" not in a["explain"]["unmeasured"]
    trust = " ".join(t["text"] for t in a["explain"]["trust"])
    assert "매일" in trust
    assert "거래비용" in trust


def test_node_cadence_moves_shares_and_says_drift():
    from src.api import allocation_graph_nodes as gn
    from src.engine import portfolio_graph as pg
    a = pg.run(_graph(), gn.REGISTRY)["nodes"]["pc"]
    q = pg.run(_graph({"s1": "Q", "s3": "M"}), gn.REGISTRY)["nodes"]["pc"]
    assert q["status"] == "ok", q["reason"]
    assert [s["rebalance"] for s in q["view"]["strategies"]] == ["Q", "D", "M"]
    assert q["view"]["result"]["sleeve_vol_pct"]["가"] != a["view"]["result"]["sleeve_vol_pct"]["가"]
    trust = " ".join(t["text"] for t in q["explain"]["trust"])
    assert "가: 한 분기" in trust and "다: 한 달" in trust
    assert "가격 따라" in trust
    assert any("리밸런싱" in f for f in q["explain"]["facts"])


def test_rebalance_for_unlinked_port_is_inert_like_labels():
    """이어지지 않은 포트의 주기는 이름(labels)처럼 쓰이지 않는다 — 선을 뺐다고 노드가 실패하지 않는다.
    짝: 결과는 그 칸이 없을 때와 같다(엉뚱한 전략에 옮겨 붙지 않는다)."""
    from src.api import allocation_graph_nodes as gn
    from src.engine import portfolio_graph as pg
    a = pg.run(_graph(), gn.REGISTRY)["nodes"]["pc"]
    r = pg.run(_graph({"s5": "Q"}), gn.REGISTRY)["nodes"]["pc"]
    assert r["status"] == "ok", r["reason"]
    assert r["view"]["result"]["sleeve_allocation"] == a["view"]["result"]["sleeve_allocation"]
    assert [s["rebalance"] for s in r["view"]["strategies"]] == ["D", "D", "D"]
