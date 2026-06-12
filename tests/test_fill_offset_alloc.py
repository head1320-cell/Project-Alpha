"""체결가 오프셋(지정가 도달 검증) + 종목당 최대 금액 + 현금 비중 — 격차 C-6·7·8.

① 매수 지정가(기준가-1%): 당일 저가 미도달 → 그날 미체결 / 도달 → min(지정가,시가)
② 매도 지정가(+%): 고가 미도달 → 보유 지속
③ max_buy_amount: 종목당 투자액 상한
④ cash_reserve_pct: 매수 후에도 평가자산 대비 현금 비중 유지
⑤ 회귀: 오프셋 0 = 기존과 동일
"""
import pandas as pd

from src.kis_backtest_engine import BacktestConfig, BacktestEngine
from src.kis_strategies import condition_strategy  # noqa: F401

START = "2024-06-03"

BUY = [{"factor_token": "{종가}", "function_id": "pct", "params": {"n": "1"},
        "op": "gte", "rhs": 5}]
SELL = [{"factor_token": "{종가}", "function_id": "pct", "params": {"n": "1"},
         "op": "lte", "rhs": -5}]


def make_df(rows: list[tuple]) -> pd.DataFrame:
    """rows: (open, high, low, close) — 워밍업 60봉(평탄) 뒤에 붙임."""
    idx = pd.bdate_range(end=pd.Timestamp(START) - pd.tseries.offsets.BDay(1), periods=60)
    idx = idx.append(pd.bdate_range(start=START, periods=len(rows)))
    base = [(100.0, 100.5, 99.5, 100.0)] * 60 + [tuple(map(float, r)) for r in rows]
    df = pd.DataFrame(base, columns=["open", "high", "low", "close"], index=idx)
    df["volume"] = 50_000.0
    return df


def run(df, monkeypatch, **cfg_kw):
    import src.data.ohlcv_loader as loader
    monkeypatch.setattr(loader, "load_ohlcv_unified", lambda ticker, *a, **k: df.copy())
    cfg = BacktestConfig(
        symbols=["000111"], strategy_name="Condition",
        strategy_params={"buy_conditions": BUY, "sell_conditions": SELL},
        start_date=START, end_date=df.index[-1].strftime("%Y-%m-%d"),
        commission_rate=0.0, slippage_rate=0.0, max_positions=1, **cfg_kw)
    engine = BacktestEngine(cfg)
    result = engine.run()
    assert not result.get("error", False)
    return engine


# 점프 봉(bar1): 시가 109, 저가 108.5, 종가 110 — 전일종가 100
JUMP_NO_DIP = [(100, 100.5, 99.5, 100), (109, 111, 108.5, 110),
               (110, 111, 109, 110), (110, 111, 109, 110)]
# 같은 점프지만 저가가 99 — 전일종가 -1%(=99)에 도달
JUMP_WITH_DIP = [(100, 100.5, 99.5, 100), (109, 111, 99.0, 110),
                 (110, 111, 109, 110), (110, 111, 109, 110)]


def test_buy_offset_unfilled_when_low_above_limit(monkeypatch):
    # 전일종가 100 × (1-1%) = 99 지정가 — 당일 저가 108.5 > 99 → 미체결
    e = run(make_df(JUMP_NO_DIP), monkeypatch,
            buy_fill_type="prev_close", buy_fill_offset_pct=-1.0)
    assert [t.side for t in e.trades] == []


def test_buy_offset_fills_at_limit_when_reached(monkeypatch):
    # 저가 99 ≤ 지정가 99 → 체결가 min(99, 시가 109) = 99
    e = run(make_df(JUMP_WITH_DIP), monkeypatch,
            buy_fill_type="prev_close", buy_fill_offset_pct=-1.0)
    buys = [t for t in e.trades if t.side == "buy"]
    assert len(buys) == 1 and abs(buys[0].price - 99.0) < 1e-9


def test_sell_offset_unfilled_keeps_position(monkeypatch):
    # 매수(기본 종가) 후 급락 봉에서 매도 지정가 +5%: 고가가 못 미침 → 그날 미체결
    rows = [(100, 100.5, 99.5, 100), (109, 111, 99.0, 110),
            (104, 104.5, 100.4, 100.5),   # -8.6% 급락(매도 신호), 고가 104.5
            (100, 101, 99, 100.5)]
    e = run(make_df(rows), monkeypatch,
            sell_fill_type="prev_close", sell_fill_offset_pct=5.0)  # 110×1.05=115.5 미도달
    assert [t.side for t in e.trades] == ["buy"]          # 매도 없음 (보유 지속)


def test_max_buy_amount_caps_position(monkeypatch):
    e = run(make_df(JUMP_NO_DIP), monkeypatch,
            initial_capital=100_000_000, max_buy_amount=5_000_000.0)
    buys = [t for t in e.trades if t.side == "buy"]
    assert len(buys) == 1 and buys[0].value <= 5_000_000.0 + 1e-6


def test_cash_reserve_keeps_cash(monkeypatch):
    e = run(make_df(JUMP_NO_DIP), monkeypatch,
            initial_capital=100_000_000, cash_reserve_pct=30.0)
    # 매수 발생 + 현금이 평가자산 30% 이상 유지 (매수 직후 기준 근사)
    assert any(t.side == "buy" for t in e.trades)
    equity = e.equity_history[-1][1]
    assert e.cash >= equity * 0.30 - 1e-6


def test_offset_zero_is_regression_safe(monkeypatch):
    base = run(make_df(JUMP_WITH_DIP), monkeypatch)
    off0 = run(make_df(JUMP_WITH_DIP), monkeypatch,
               buy_fill_offset_pct=0.0, sell_fill_offset_pct=0.0,
               max_buy_amount=None, cash_reserve_pct=0.0)
    assert [(t.date, t.side, t.price, t.quantity) for t in base.trades] \
        == [(t.date, t.side, t.price, t.quantity) for t in off0.trades]
