"""자산배분 ETF 바스켓 — 주식 슬리브와 병행하는 ETF 보유 + 주기 리밸런싱.

① 미사용 = 기존 동작 불변 (회귀)
② ETF 슬리브: 시작 시점 바스켓 목표 비중 매수, equity에 포함
③ 주식 슬리브 = equity×stock_pct/100 한도 (현금 비중 일반화)
④ 주기 리밸런싱: N개월마다 목표 비중 재정렬
⑤ 결과 asset_alloc 메타 보고
"""
import pandas as pd

from src.kis_backtest_engine import BacktestConfig, BacktestEngine
from src.kis_strategies import condition_strategy  # noqa: F401

START = "2024-01-02"
BUY = [{"factor_token": "{종가}", "function_id": "pct", "params": {"n": "1"},
        "op": "gte", "rhs": 2}]


def make_df(seed, n=180, drift=0.0005):
    import numpy as np
    rng = np.random.RandomState(seed)
    idx = pd.bdate_range(end=pd.Timestamp(START) - pd.tseries.offsets.BDay(1), periods=40)
    idx = idx.append(pd.bdate_range(start=START, periods=n))
    steps = (1 + drift + rng.normal(0, 0.01, len(idx)))
    close = pd.Series(10000 * np.cumprod(steps), index=idx).clip(lower=1000)
    return pd.DataFrame({"open": close * 0.999, "high": close * 1.01,
                         "low": close * 0.99, "close": close, "volume": 1e6}, index=idx)


def run(monkeypatch, frames, **kw):
    import src.data.ohlcv_loader as loader
    monkeypatch.setattr(loader, "load_ohlcv_unified",
                        lambda ticker, *a, **k: frames.get(str(ticker), make_df(99)).copy())
    cfg = BacktestConfig(symbols=["000111"], strategy_name="Condition",
                         strategy_params={"buy_conditions": BUY},
                         start_date=START, end_date=frames["000111"].index[-1].strftime("%Y-%m-%d"),
                         commission_rate=0.0, slippage_rate=0.0, max_positions=1,
                         initial_capital=100_000_000, **kw)
    e = BacktestEngine(cfg)
    r = e.run()
    assert not r.get("error", False)
    return e, r


def frames():
    return {"000111": make_df(1), "069500": make_df(2, drift=0.0003),
            "122630": make_df(3, drift=0.0008), "273130": make_df(4, drift=0.0001)}


BASKET = {"etf_pct": 30, "stock_pct": 60, "rebalance_months": 3, "fill_type": "close",
          "basket": [{"ticker": "069500", "weight_pct": 60},
                     {"ticker": "122630", "weight_pct": 30},
                     {"ticker": "273130", "weight_pct": 10}]}


def test_no_alloc_unchanged(monkeypatch):
    f = frames()
    base, _ = run(monkeypatch, f)
    new, _ = run(monkeypatch, {k: v.copy() for k, v in f.items()}, asset_alloc=None)
    assert [(t.date, t.side, t.ticker, t.quantity) for t in base.trades] \
        == [(t.date, t.side, t.ticker, t.quantity) for t in new.trades]


def test_etf_sleeve_buys_basket_at_start(monkeypatch):
    e, r = run(monkeypatch, frames(), asset_alloc=BASKET)
    etf_buys = [t for t in e.trades if t.reason == "ETF 자산배분 리밸런싱" and t.side == "buy"]
    tickers = {t.ticker for t in etf_buys}
    assert tickers == {"069500", "122630", "273130"}    # 바스켓 3종 매수
    # ETF 평가액이 총자산의 ~30% (시작 직후 근사)
    meta = r.get("asset_alloc")
    assert meta and 20 <= meta["etf_pct_actual"] <= 40


def test_etf_value_in_equity(monkeypatch):
    e, _ = run(monkeypatch, frames(), asset_alloc=BASKET)
    # 최종 equity = 현금 + 주식 + ETF — ETF 보유가 있으면 _etf_value > 0
    assert e._etf_value() > 0
    assert sum(h["qty"] for h in e._etf_pos.values()) > 0


def test_stock_sleeve_capped(monkeypatch):
    # stock_pct=60 → 주식 매수 가용은 자산의 60% 한도. ETF 없는 경우 대비 주식 투자액 작아야
    e_alloc, _ = run(monkeypatch, frames(), asset_alloc=BASKET)
    e_full, _ = run(monkeypatch, frames())
    stock_val_alloc = sum(p.quantity * p.avg_price for p in e_alloc.positions.values())
    stock_val_full = sum(p.quantity * p.avg_price for p in e_full.positions.values())
    assert stock_val_alloc <= stock_val_full + 1   # 슬리브 제한으로 주식 비중 작거나 같음


def test_rebalance_recurs(monkeypatch):
    # 180거래일 ≈ 9개월, 3개월 주기 → 리밸런싱 여러 번 (시작 + 추가 주기)
    e, _ = run(monkeypatch, frames(), asset_alloc=BASKET)
    rebal_dates = {t.date for t in e.trades if t.reason == "ETF 자산배분 리밸런싱"}
    assert len(rebal_dates) >= 2   # 최소 시작 + 1회 이상 추가 리밸런싱
