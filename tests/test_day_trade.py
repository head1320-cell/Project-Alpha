"""당일 매매 (day_trade) — 당일 진입을 같은 봉 종가에 전량 청산 (격차 C-10).

시가 매수 체결과 결합: 시가 진입 → 당일 종가 청산 = 데이트레이딩 근사.
"""
import pandas as pd

from src.kis_backtest_engine import BacktestConfig, BacktestEngine
from src.kis_strategies import condition_strategy  # noqa: F401

START = "2024-06-03"

BUY = [{"factor_token": "{종가}", "function_id": "pct", "params": {"n": "1"},
        "op": "gte", "rhs": 5}]


def make_df() -> pd.DataFrame:
    # bar1: 시가 104, 종가 110 (+10% — 매수 신호) / bar5: 또 한 번 점프
    rows = [(100, 100.5, 99.5, 100), (104, 111, 103, 110), (110, 111, 109, 110),
            (110, 111, 109, 110), (110, 111, 109, 110), (112, 118, 111, 117),
            (117, 118, 116, 117), (117, 118, 116, 117)]
    idx = pd.bdate_range(end=pd.Timestamp(START) - pd.tseries.offsets.BDay(1), periods=60)
    idx = idx.append(pd.bdate_range(start=START, periods=len(rows)))
    base = [(100.0, 100.5, 99.5, 100.0)] * 60 + [tuple(map(float, r)) for r in rows]
    df = pd.DataFrame(base, columns=["open", "high", "low", "close"], index=idx)
    df["volume"] = 50_000.0
    return df


def run(monkeypatch, **kw):
    df = make_df()
    import src.data.ohlcv_loader as loader
    monkeypatch.setattr(loader, "load_ohlcv_unified", lambda ticker, *a, **k: df.copy())
    cfg = BacktestConfig(
        symbols=["000111"], strategy_name="Condition",
        strategy_params={"buy_conditions": BUY},
        start_date=START, end_date=df.index[-1].strftime("%Y-%m-%d"),
        commission_rate=0.0, slippage_rate=0.0, max_positions=1, **kw)
    engine = BacktestEngine(cfg)
    result = engine.run()
    assert not result.get("error", False)
    return engine


def test_day_trade_exits_same_bar_at_close(monkeypatch):
    e = run(monkeypatch, day_trade=True, buy_fill_type="open", signal_lag=1)
    # 신호(bar1) → lag=1로 다음날 시가 진입 + 같은 날 종가 청산: 매수/매도가 같은 날짜 쌍
    assert len(e.trades) >= 2
    for buy, sell in zip(e.trades[0::2], e.trades[1::2]):
        assert buy.side == "buy" and sell.side == "sell"
        assert buy.date == sell.date                      # 같은 날 진입·청산
        assert sell.reason == "당일 매매 청산"
    assert e.positions == {}                              # 종료 시 보유 없음


def test_day_trade_off_holds_position(monkeypatch):
    e = run(monkeypatch, day_trade=False, buy_fill_type="open", signal_lag=1)
    sells = [t for t in e.trades if t.side == "sell"]
    assert all(t.reason != "당일 매매 청산" for t in sells)
    assert len(e.positions) >= 1                          # 청산룰 없으니 보유 지속
