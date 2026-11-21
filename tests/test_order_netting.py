"""BG3 · 네팅 — ★지어낸 ×1.5 대신 실제 보유로 잰다★ (R3 복원)
==============================================================================
스펙 §4.3 · 대상 `src/execution/order_netting.py` · 배선
`multi_strategy_backtest`·`realism_engine` · 정직 `counterfactual_analyzer`

## 정의

날짜 t 에 전략 s 의 슬리브가 종목 i 에 갖는 노출 `x(s,i,t) = W(s,t) · h(s,i,t)`.

    총거래 G = Σ_s Σ_i |Δx(s,i)|   순거래 N = Σ_i |Σ_s Δx(s,i)|
    절감   S = (G − N) × (수수료 + 슬리피지) × equity(t−1)

## 거는 것

- 손계산 골든 — 반대 방향은 상쇄되고, 같은 방향·다른 종목은 상쇄되지 않는다.
- ★보유를 모르면 `None` + 사유★ — 0 이 아니다(0 은 "상쇄가 없었다" 는 관측이다).
- ★네팅은 보고 전용★ — 켜든 끄든 수익률·Sharpe·MDD 가 같다.
- 반사실의 "중앙 청산의 가치" 는 수익률 차이였다 — 보고 전용이라 **구조적으로 0** 이었다.
  이제 그렇게 말한다(`None` + 사유 + 측정 절감).
"""
from __future__ import annotations

import pytest

from src.execution.order_netting import NETTING_BASIS, OrderNettingEngine
from tests.test_strategy_registry import _registry, _req, _stored_run, db, market  # noqa: F401

RATE = 0.001
EQ = 1_000_000.0


def _s(prev_w, cur_w, h_prev, h_cur):
    holdings = {sid: {"2024-01-02": h_prev.get(sid), "2024-01-03": h_cur.get(sid)}
                for sid in set(prev_w) | set(cur_w)}
    return OrderNettingEngine().savings(
        prev_weights=prev_w, cur_weights=cur_w, holdings=holdings,
        prev_date="2024-01-02", date="2024-01-03", equity=EQ, rate=RATE)


# ── 손계산 골든 ───────────────────────────────────────────────────────

def test_opposite_trades_across_strategies_net_out():
    """s1 은 A→B, s2 는 B→A — 슬리브마다 1.0 씩 거래(G=2.0)하지만 합치면 0(N=0)."""
    v, why = _s({1: .5, 2: .5}, {1: .5, 2: .5},
                {1: {"A": 1.0}, 2: {"B": 1.0}}, {1: {"B": 1.0}, 2: {"A": 1.0}})
    assert why is None
    assert v == pytest.approx(2.0 * RATE * EQ)


def test_same_direction_trades_do_not_net():
    """둘 다 A 를 산다 — G = N 이라 절감 0 (★0 은 관측이다★)."""
    v, why = _s({1: .5, 2: .5}, {1: .5, 2: .5},
                {1: {}, 2: {}}, {1: {"A": 1.0}, 2: {"A": 1.0}})
    assert why is None and v == pytest.approx(0.0)


def test_a_single_strategy_cannot_net():
    v, why = _s({1: 1.0}, {1: 1.0}, {1: {"A": 1.0}}, {1: {"B": 1.0}})
    assert why is None and v == pytest.approx(0.0)


def test_rebalancing_between_sleeves_holding_the_same_stock_nets():
    """둘 다 A 만 들고 비중만 옮긴다 — 슬리브는 0.4 를 거래하지만 합친 A 는 그대로."""
    v, _ = _s({1: .5, 2: .5}, {1: .7, 2: .3}, {1: {"A": 1.0}, 2: {"A": 1.0}},
              {1: {"A": 1.0}, 2: {"A": 1.0}})
    assert v == pytest.approx(0.4 * RATE * EQ)


def test_rebalancing_between_sleeves_holding_different_stocks_does_not_net():
    """★짝★ — 종목이 다르면 비중 이동은 실제 거래다."""
    v, _ = _s({1: .5, 2: .5}, {1: .7, 2: .3}, {1: {"A": 1.0}, 2: {"B": 1.0}},
              {1: {"A": 1.0}, 2: {"B": 1.0}})
    assert v == pytest.approx(0.0)


def test_savings_are_never_negative():
    """삼각부등식 — G ≥ N."""
    import random
    rnd = random.Random(3)
    for _ in range(50):
        tk = ["A", "B", "C"]
        hp = {s: {t: rnd.random() / 3 for t in tk} for s in (1, 2, 3)}
        hc = {s: {t: rnd.random() / 3 for t in tk} for s in (1, 2, 3)}
        w = {1: .3, 2: .3, 3: .4}
        v, _ = _s(w, w, hp, hc)
        assert v >= -1e-9


# ── ★미상은 0 이 아니다★ ─────────────────────────────────────────────

def test_unknown_holdings_are_unknown_not_zero():
    v, why = _s({1: .5, 2: .5}, {1: .5, 2: .5},
                {1: {"A": 1.0}, 2: None}, {1: {"B": 1.0}, 2: {"A": 1.0}})
    assert v is None and why and "2" in why


def test_a_missing_date_is_unknown():
    holdings = {1: {"2024-01-03": {"A": 1.0}}, 2: {"2024-01-02": {}, "2024-01-03": {}}}
    v, why = OrderNettingEngine().savings(
        prev_weights={1: .5, 2: .5}, cur_weights={1: .5, 2: .5}, holdings=holdings,
        prev_date="2024-01-02", date="2024-01-03", equity=EQ, rate=RATE)
    assert v is None and why


def test_a_strategy_with_zero_weight_on_both_days_is_ignored():
    """비중 0 → 0 인 전략은 거래하지 않는다 — 그 전략의 보유가 미상이어도 판정할 수 있다."""
    v, why = _s({1: 1.0, 2: 0.0}, {1: 1.0, 2: 0.0}, {1: {"A": 1.0}, 2: None},
                {1: {"A": 1.0}, 2: None})
    assert why is None and v == pytest.approx(0.0)


# ── 엔진 배선 ─────────────────────────────────────────────────────────

def _two_strategies(db):
    reg = _registry(db)
    a = reg.register(_stored_run(_req()), "A")["id"]
    b = reg.register(_stored_run(_req(sell_conditions=[
        {"factor_token": "종가", "function_id": "pct", "params": {"n": 5},
         "op": "gte", "rhs": 3}])), "B")["id"]
    return [a, b]


def _run(db, sids, **over):
    from src.engine.multi_strategy_backtest import BacktestConfig, MultiStrategyBacktester
    cfg = BacktestConfig(strategy_ids=sids, start_date="2023-06-01",
                         end_date="2024-03-01", allocation_method="hrp",
                         rebalance_policy="monthly", macro_overlay_enabled=False,
                         lookback_days=60, **over)
    out = MultiStrategyBacktester(db).run(cfg)
    assert out.get("success"), out.get("message")
    return out


def test_the_engine_reports_measured_netting(db, market):
    out = _run(db, _two_strategies(db))
    n = out["summary"]["netting"]
    assert n["basis"] == NETTING_BASIS and n["enabled"] is True
    assert n["n_measured_days"] > 0
    assert len(n["assumptions"]) == 2
    assert n["n_unmeasured_days"] == 0 and n["first_unmeasured_reason"] is None
    # ★공허하지 않다★ — 두 전략이 같은 종목 풀(CODES)을 반대 시점에 사고판다.
    # 0 만 내는 구현(=네팅 없음)이 통과하지 못하게 양수를 요구한다.
    assert out["summary"]["netting_total_savings"] > 0


def test_the_engine_number_is_the_pure_function_on_its_own_records(db, market):
    """★배선을 못 박는다★ — 엔진 합계 == 엔진이 낸 일별 가중·등록 보유로 다시 잰 합계.

    이전 가중 대신 오늘 가중을 넘기거나, 날짜를 하루 밀거나, 요율을 바꾸면 갈린다.
    """
    from src.engine.strategy_registry import StrategyRegistry
    sids = _two_strategies(db)
    out = _run(db, sids)
    recs = out["daily_records"]
    holdings = StrategyRegistry(db).load_holdings(sids, "2023-06-01", "2024-03-01")
    eng = OrderNettingEngine()
    total, eq = 0.0, 1_000_000.0
    for prev, cur in zip(recs, recs[1:]):
        v, why = eng.savings(
            prev_weights={int(k): w for k, w in prev["weights"].items()},
            cur_weights={int(k): w for k, w in cur["weights"].items()},
            holdings=holdings, prev_date=prev["date"][:10], date=cur["date"][:10],
            equity=eq, rate=0.00015 + 0.0005)
        assert why is None
        total += v
        eq = cur["portfolio_equity"]
    assert out["summary"]["netting_total_savings"] == pytest.approx(total, abs=0.02)


def test_the_engine_helper_compares_yesterday_with_today():
    """★어제 가중 → 오늘 가중★ — 같은 종목을 든 두 슬리브 사이의 비중 이동은 상쇄된다.

    엔진 합계 대조(위)는 월간 리밸런싱이라 가중이 바뀌는 날이 적어 이 배선을 못
    가른다(변이 e 가 거기서 살아남았다). 헬퍼를 직접 부른다.
    """
    from types import SimpleNamespace

    import pandas as pd

    from src.engine.multi_strategy_backtest import BacktestConfig, MultiStrategyBacktester
    me = SimpleNamespace(netting_engine=OrderNettingEngine())
    cfg = BacktestConfig(strategy_ids=[1, 2], start_date="2024-01-02",
                         end_date="2024-01-03", netting_enabled=True,
                         commission_rate=RATE, slippage_rate=0.0)
    prev = SimpleNamespace(weights={1: .5, 2: .5}, date=pd.Timestamp("2024-01-02"))
    same = {"A": 1.0}
    data = {"holdings": {1: {"2024-01-02": same, "2024-01-03": same},
                         2: {"2024-01-02": same, "2024-01-03": same}}}
    v, why = MultiStrategyBacktester._netting(
        me, cfg, data, [prev], {1: .7, 2: .3}, pd.Timestamp("2024-01-03"), EQ)
    assert why is None and v == pytest.approx(0.4 * RATE * EQ)
    # ★짝★ 꺼져 있으면 0(선택) — 첫날도 0.
    cfg_off = BacktestConfig(strategy_ids=[1, 2], start_date="2024-01-02",
                             end_date="2024-01-03", netting_enabled=False)
    assert MultiStrategyBacktester._netting(
        me, cfg_off, data, [prev], {1: .7, 2: .3}, pd.Timestamp("2024-01-03"), EQ) == (0.0, None)
    assert MultiStrategyBacktester._netting(
        me, cfg, data, [], {1: .7, 2: .3}, pd.Timestamp("2024-01-03"), EQ) == (0.0, None)


def test_unknown_holdings_stay_unknown_through_the_engine(db, market, monkeypatch):
    """★미상은 합계에서 0 으로 녹지 않는다★ — 보유를 모르면 그날은 `None`, 합계도 `None`."""
    from src.engine.strategy_registry import StrategyRegistry
    sids = _two_strategies(db)
    real = StrategyRegistry.load_holdings

    def _blind(self, ids, start, end):
        h = real(self, ids, start, end)
        h[sids[1]] = {d: None for d in h[sids[1]]}
        return h

    monkeypatch.setattr(StrategyRegistry, "load_holdings", _blind)
    out = _run(db, sids)
    s = out["summary"]
    assert s["netting_total_savings"] is None
    assert s["attribution"]["netting_effect_pct"] is None
    n = s["netting"]
    assert n["n_measured_days"] == 0 and n["n_unmeasured_days"] > 0
    assert str(sids[1]) in n["first_unmeasured_reason"]
    days = [r for r in out["daily_records"][1:]]
    assert days and all(r["netting_savings"] is None for r in days)
    # ★짝★ 수익률은 보유를 몰라도 그대로다(보고 전용).
    assert s["total_return_pct"] == _run(db, sids, netting_enabled=False)["summary"][
        "total_return_pct"]


def test_netting_is_report_only_returns_do_not_move(db, market):
    """★보고 전용★ — 켜든 끄든 수익률·Sharpe·MDD 가 비트 단위로 같다."""
    sids = _two_strategies(db)
    on = _run(db, sids, netting_enabled=True)["summary"]
    off = _run(db, sids, netting_enabled=False)["summary"]
    for k in ("total_return_pct", "sharpe_ratio", "max_drawdown_pct", "final_equity"):
        assert on[k] == off[k], k
    assert off["netting"]["enabled"] is False


def test_realism_netting_is_measured_and_report_only(db, market):
    """realism 엔진도 같은 헬퍼로 잰다 — 켜든 끄든 수익률이 같다."""
    from src.engine.realism_engine import RealismConfig, RealisticBacktester
    sids = _two_strategies(db)

    def _r(on):
        cfg = RealismConfig(strategy_ids=sids, start_date="2023-06-01",
                            end_date="2024-03-01", allocation_method="hrp",
                            macro_overlay_enabled=False, lookback_days=60,
                            enable_cash_yield=False, enable_regime_adaptive=False,
                            netting_enabled=on)
        out = RealisticBacktester(db).run(cfg)
        assert out.get("success"), out.get("message")
        return out["summary"]

    on, off = _r(True), _r(False)
    assert on["netting"]["basis"] == NETTING_BASIS and on["netting"]["n_measured_days"] > 0
    assert on["netting_total_savings"] > 0
    for k in ("total_return_pct", "sharpe_ratio", "max_drawdown_pct", "final_equity"):
        assert on[k] == off[k], k


def test_the_invented_multiplier_is_gone():
    """★×1.5 가 소스에 남지 않는다★ — 두 엔진 모두."""
    import pathlib
    for f in ("src/engine/multi_strategy_backtest.py", "src/engine/realism_engine.py"):
        assert "* 1.5" not in pathlib.Path(f).read_text(encoding="utf-8"), f


# ── 반사실: "중앙 청산의 가치" ────────────────────────────────────────

def test_the_counterfactual_does_not_call_a_structural_zero_a_value():
    """네팅은 수익률에 안 더해지므로 수익률 차이는 **구조적으로 0** 이다 — 가치가 아니다."""
    from src.engine.counterfactual_analyzer import CounterfactualAnalyzer
    base = {"total_return_pct": 10.0, "sharpe_ratio": 1.0,
            "netting_total_savings": 1234.5}
    same = {"total_return_pct": 10.0, "sharpe_ratio": 1.0,
            "netting_total_savings": 0.0}
    out = CounterfactualAnalyzer._compute_decision_values([
        {"name": "baseline", "summary": base, "n_trading_days": 252},
        {"name": "no_netting", "summary": same},
    ])
    assert out["netting_value_pct"] is None
    assert out["netting_value_reason"]
    assert out["netting_measured_savings"] == 1234.5


def test_other_comparisons_still_use_the_return_difference():
    """★짝★ — 수익률에 닿는 결정(HRP vs 역변동)은 여전히 수익률 차이로 잰다."""
    from src.engine.counterfactual_analyzer import CounterfactualAnalyzer
    out = CounterfactualAnalyzer._compute_decision_values([
        {"name": "baseline", "summary": {"total_return_pct": 10.0, "sharpe_ratio": 1.0},
         "n_trading_days": 252},
        {"name": "inverse_vol", "summary": {"total_return_pct": 8.0, "sharpe_ratio": .8}},
    ])
    assert out["hrp_vs_inverse_vol_value_pct"] == pytest.approx(2.0)
