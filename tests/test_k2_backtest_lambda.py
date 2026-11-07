"""K2 · 백테스트가 비중 계산의 위험 회피 λ 를 받는다 (작업 카드 — 백테스트 수치가 바뀌는 승인된 변경)
==============================================================================
정책 백테스트는 받은 비중이 아니라 '비중 계산' 의 규칙을 리밸런싱마다 다시 푼다. 그런데 λ(`risk_aversion`)를 넘기지 않아
λ 1.5 로 고른 위험 성향 효용(mv_utility)이 기본값 λ 4 로 백테스트됐다. 이제 λ 가 끝까지 간다:
`BacktestRequest.risk_aversion` → `_policy_backtest` → `walk_forward` → `plan_walk_forward` → `_weights_at` 이
`optimize(risk_aversion=)` 과 제약이면 `constrained_solve(risk_aversion=)` 에 넘긴다(두 함수는 이미 받는다 — 인자 하나 잇기).

★λ 를 주지 않으면 지금과 한 자리도 같다★(기본 None) — `test_cf3_golden` 의 `bl_backtest` 가 건다.
★회사 관점은 넘기지 않는다★ — 지금 시점 전용(forward_only)이라 과거에 쓰면 룩어헤드다(`test_allocation_graph_w5` 가 막는다).

백테스트는 쓴 λ 를 `config.risk_aversion`(위험 성향 효용일 때만 — 다른 방식의 응답 모양은 그대로)으로 밝히고, 선 점검 R9 는 그 값을
비중 계산의 λ 와 견준다(받지 못했으면 여전히 '바뀜').
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd
import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.api import allocation_graph_handoff as ho  # noqa: E402
from src.api import allocation_graph_nodes as gn  # noqa: E402
from src.api.allocation_routes import (  # noqa: E402
    AnalyzeRequest,
    BacktestRequest,
    _load_clean_returns,
    _policy_backtest,
)
from src.engine import allocation_backtest as ab  # noqa: E402
from src.engine import portfolio_graph as pg  # noqa: E402
from tests.test_cf3_golden import AS_OF, T5, _chain  # noqa: E402
from tests.test_graph_handoff_rules import clean  # noqa: E402, F401

BT = {"rebalance": "Q", "cost_bps": 15}


def _R(seed=7, n=420, k=4):
    rng = np.random.default_rng(seed)
    common = rng.normal(0.0003, 0.009, n)
    R = np.round(np.column_stack([(0.6 + 0.2 * i) * common + rng.normal(0.0002 * (i + 1), 0.011, n)
                                  for i in range(k)]), 6)
    return R, list(pd.bdate_range("2023-01-02", periods=n))


NAMES = ["005930", "000660", "035420", "051910"]


def _curve(out: dict) -> list:
    return [p["value"] if isinstance(p, dict) else p for p in out["equity_curve"]]


# ── 엔진: 인자 하나 잇기 ──────────────────────────────────────────────────────

def test_without_lambda_the_engine_is_unchanged():
    """λ 를 주지 않은 것 = 지금 그대로(None) — 방식마다."""
    R, dates = _R()
    for model in ("mvo", "mv_utility"):
        a = ab.walk_forward(NAMES, R, dates, model=model, rebalance="Q")
        b = ab.walk_forward(NAMES, R, dates, model=model, rebalance="Q", risk_aversion=None)
        assert _curve(a) == _curve(b)


def test_lambda_changes_the_mv_utility_backtest():
    """짝 — λ 가 실제로 닿는다: 1.5 와 기본값의 곡선이 다르다(상수 배제)."""
    R, dates = _R()
    low = ab.walk_forward(NAMES, R, dates, model="mv_utility", rebalance="Q", risk_aversion=1.5)
    base = ab.walk_forward(NAMES, R, dates, model="mv_utility", rebalance="Q")
    assert _curve(low) != _curve(base)


def test_lambda_reaches_the_constrained_solve():
    """제약을 걸어도 λ 가 닿는다 — 제약 해(`constrained_solve`)도 같은 λ 로 푼다."""
    from src.engine.constrained_opt import Constraints
    R, dates = _R()
    c = Constraints(max_weight_pct=40)
    low = ab.walk_forward(NAMES, R, dates, model="mv_utility", constraints=c, rebalance="Q", risk_aversion=1.5)
    base = ab.walk_forward(NAMES, R, dates, model="mv_utility", constraints=c, rebalance="Q")
    assert _curve(low) != _curve(base)


def test_lambda_does_not_touch_other_models():
    """짝 — λ 는 위험 성향 효용만 쓴다: mvo 에 줘도 곡선이 같다."""
    R, dates = _R()
    assert _curve(ab.walk_forward(NAMES, R, dates, model="mvo", rebalance="Q", risk_aversion=1.5)) == \
        _curve(ab.walk_forward(NAMES, R, dates, model="mvo", rebalance="Q"))


@pytest.mark.parametrize("lam,want", [(1.5, {"value": 1.5, "source": "user"}), (None, {"value": 4.0, "source": "default"})])
def test_the_backtest_says_which_lambda_it_used(lam, want):
    R, dates = _R()
    out = ab.walk_forward(NAMES, R, dates, model="mv_utility", rebalance="Q", risk_aversion=lam)
    assert out["config"]["risk_aversion"] == want


def test_other_models_keep_the_config_shape():
    """짝 — 다른 방식의 응답 모양은 그대로(키가 늘지 않는다)."""
    R, dates = _R()
    assert "risk_aversion" not in ab.walk_forward(NAMES, R, dates, model="mvo", rebalance="Q")["config"]


# ── 그래프 노드 = /backtest 라우트 ────────────────────────────────────────────

def _route(clean_lam):
    returns, bench, excluded, coverage = _load_clean_returns(T5, "KOSPI", 756, as_of=AS_OF)
    req = BacktestRequest(tickers=T5, benchmark="KOSPI", lookback_days=756, as_of=AS_OF, model="mv_utility",
                          rebalance="Q", cost_bps=15, risk_aversion=clean_lam)
    return _policy_backtest(req, returns, bench, excluded, coverage)


def test_node_backtest_equals_the_route_with_the_same_lambda(clean):
    rep = pg.run(_chain("mv_utility", opt={"risk_aversion": 1.5}, backtest=BT), gn.REGISTRY)
    b = rep["nodes"]["b"]
    assert b["status"] == "ok", b["reason"]
    assert _curve(b["view"]) == _curve(_route(1.5))
    assert b["view"]["config"]["risk_aversion"] == {"value": 1.5, "source": "user"}


def test_node_backtest_is_not_the_default_lambda_curve(clean):
    """짝 — 기본 λ 의 라우트 곡선과는 다르다(노드가 λ 를 버리면 이 둘이 같아진다)."""
    rep = pg.run(_chain("mv_utility", opt={"risk_aversion": 1.5}, backtest=BT), gn.REGISTRY)
    assert _curve(rep["nodes"]["b"]["view"]) != _curve(_route(None))


def test_route_rejects_a_lambda_out_of_range():
    """`/analyze` 와 같은 범위(0.5~20) — 백테스트만 다른 λ 를 받는 길을 만들지 않는다."""
    with pytest.raises(ValueError):
        BacktestRequest(tickers=T5[:2], risk_aversion=0.1)
    assert BacktestRequest.model_fields["risk_aversion"].metadata == AnalyzeRequest.model_fields["risk_aversion"].metadata


# ── 선 점검 R9 ───────────────────────────────────────────────────────────────

def test_r9_lambda_is_carried(clean):
    rep = pg.run(_chain("mv_utility", opt={"risk_aversion": 1.5}, backtest=BT), gn.REGISTRY)
    issues = rep["edges"]["o.weights->b.weights"]["issues"] or []
    assert "lambda_dropped" not in {i["code"] for i in issues}


def _h(req_lam, used):
    req = AnalyzeRequest(tickers=T5, model="mv_utility", risk_aversion=req_lam)
    view = {"config": {"model": "mv_utility", **({"risk_aversion": used} if used is not None else {})}}
    return pg.Handoff(edge_id="e", source="o", source_kind="optimizer", source_port="weights", target="b",
                      target_kind="backtest", target_port="weights", port_type="Weights",
                      value={"req": req}, source_view={}, view=view, params=None, inputs={})


def test_r9_still_flags_a_backtest_that_used_another_lambda():
    """짝 — 백테스트가 다른 λ 로 풀었거나 밝히지 않았으면 여전히 '바뀜'(규칙이 죽지 않았다)."""
    codes = lambda h: {i["code"] for i in ho.intake_backtest_weights(h)["issues"]}  # noqa: E731
    assert "lambda_dropped" in codes(_h(1.5, {"value": 4.0, "source": "default"}))
    assert "lambda_dropped" in codes(_h(1.5, None))
    assert "lambda_dropped" not in codes(_h(1.5, {"value": 1.5, "source": "user"}))
    assert "lambda_dropped" not in codes(_h(None, {"value": 4.0, "source": "default"}))
