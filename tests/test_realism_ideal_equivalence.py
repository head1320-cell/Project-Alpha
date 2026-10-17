"""ST3c — 현실 조건을 모두 끈 `/realism/backtest` 가 이상(기본 엔진) 계산과 같은가.

현실성 점검 화면은 이상 쪽을 `/multibacktest/run`(save:false)으로 따로 계산했다. 그 경로를 지우고
같은 `/realism/backtest` 를 현실 조건 전부 끔으로 한 번 더 부르려면, ★두 엔진의 일별 자산이 같아야★ 한다
(`realism_engine._simulate_with_realism` 은 기본 엔진 `_simulate` 를 '모방'한 별도 루프다).
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402

from tests.test_regime_model import _two  # noqa: E402
from tests.test_strategy_registry import db, market  # noqa: E402,F401

OFF = dict(enable_market_impact=False, enable_cash_yield=False, enable_buying_power_check=False,
           enable_capacity_constraint=False, enable_regime_adaptive=False)


def _both(db, **cfg):
    from src.engine.multi_strategy_backtest import BacktestConfig, MultiStrategyBacktester
    from src.engine.realism_engine import RealismConfig, RealisticBacktester
    base = MultiStrategyBacktester(db).run(BacktestConfig(**cfg))
    real = RealisticBacktester(db).run(RealismConfig(**cfg, **OFF))
    assert base.get("success"), base.get("message")
    assert real.get("success"), real.get("message")
    return base, real


@pytest.mark.parametrize("policy", ["monthly", "weekly"])
def test_realism_with_every_condition_off_equals_the_ideal_engine(db, market, policy):
    sids = _two(db)
    base, real = _both(db, strategy_ids=sids, start_date="2023-06-01", end_date="2024-03-01",
                       initial_capital=10_000_000_000, allocation_method="hrp", rebalance_policy=policy,
                       macro_overlay_enabled=False, lookback_days=60, max_weight=0.8, min_weight=0.0)
    # 공허 배제 — 비중이 실제로 움직였다(회전이 있어야 비용 경로까지 같은지 본다).
    assert len({tuple(round(v, 6) for v in x["weights"].values()) for x in base["daily_records"]}) >= 3
    b = {r["date"]: r["portfolio_equity"] for r in base["daily_records"]}
    r = {x["date"]: x["portfolio_equity"] for x in real["daily_records"]}
    assert list(b) == list(r)
    diff = [(d, b[d], r[d]) for d in b if abs(b[d] - r[d]) > 1e-6 * max(1.0, abs(b[d]))]
    assert diff == [], diff[:3]


def test_pair_one_condition_on_makes_it_differ(db, market):
    """짝 — 비교가 공허하지 않다: 시장 충격 하나만 켜도 일별 자산이 달라진다(회전이 실제로 있다)."""
    from src.engine.multi_strategy_backtest import BacktestConfig, MultiStrategyBacktester
    from src.engine.realism_engine import RealismConfig, RealisticBacktester
    sids = _two(db)
    cfg = dict(strategy_ids=sids, start_date="2023-06-01", end_date="2024-03-01", initial_capital=10_000_000_000,
               allocation_method="hrp", rebalance_policy="monthly", macro_overlay_enabled=False,
               lookback_days=60, max_weight=0.8, min_weight=0.0)
    base = MultiStrategyBacktester(db).run(BacktestConfig(**cfg))
    real = RealisticBacktester(db).run(RealismConfig(**cfg, **{**OFF, "enable_market_impact": True}))
    assert base["summary"]["n_rebalances"] >= 2
    assert base["daily_records"][-1]["portfolio_equity"] != pytest.approx(real["daily_records"][-1]["portfolio_equity"], rel=1e-9)
