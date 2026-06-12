"""돌파 매수 확장 (기준가·±%·양방) + 매수 시점 (장 시작 전|장중) — Phase 3.

① 기본(전일고가·0%·상방) = 기존 동작과 동일 (회귀)
② 기준가 변경: 전일종가 +2% 돌파 라인
③ 양방: 하방 라인 도달 시 낙폭 진입
④ 장중 주문: 지정가류 매수에서 시가 갭 혜택 배제
"""
import pandas as pd

from src.kis_backtest_engine import BacktestConfig, BacktestEngine
from src.kis_strategies import condition_strategy  # noqa: F401

START = "2024-06-03"
BUY = [{"factor_token": "{종가}", "function_id": "pct", "params": {"n": "1"},
        "op": "gte", "rhs": 5}]


def make_df(rows, warmup=60):
    idx = pd.bdate_range(end=pd.Timestamp(START) - pd.tseries.offsets.BDay(1), periods=warmup)
    idx = idx.append(pd.bdate_range(start=START, periods=len(rows)))
    base = [(100.0, 100.5, 99.5, 100.0)] * warmup + [tuple(map(float, r)) for r in rows]
    df = pd.DataFrame(base, columns=["open", "high", "low", "close"], index=idx)
    df["volume"] = 50_000.0
    return df


def run(monkeypatch, rows, **kw):
    df = make_df(rows)
    import src.data.ohlcv_loader as loader
    monkeypatch.setattr(loader, "load_ohlcv_unified", lambda ticker, *a, **k: df.copy())
    cfg = BacktestConfig(symbols=["000111"], strategy_name="Condition",
                         strategy_params={"buy_conditions": BUY},
                         start_date=START, end_date=df.index[-1].strftime("%Y-%m-%d"),
                         commission_rate=0.0, slippage_rate=0.0, max_positions=1, **kw)
    e = BacktestEngine(cfg)
    r = e.run()
    assert not r.get("error", False)
    return [(t.side, round(t.price, 4)) for t in e.trades]


# 신호봉: 전일(고가 100.5, 종가 100) → 당일 시가 101, 고가 111, 저가 100.2, 종가 110
ROWS = [(100, 100.5, 99.5, 100), (101, 111, 100.2, 110), (110, 111, 109, 110)]


def test_default_equals_legacy(monkeypatch):
    # 전일고가 100.5 상방 돌파 — 시가 101 > 100.5 → 시가 체결 (기존 max(시가, 전일고가))
    t = run(monkeypatch, ROWS, breakthrough_buy=True)
    assert t and t[0] == ("buy", 101.0)


def test_base_type_and_offset(monkeypatch):
    # 전일종가 100 × 1.02 = 102 라인 — 고가 111 ≥ 102, 시가 101 < 102 → 라인 102 체결
    t = run(monkeypatch, ROWS, breakthrough_buy=True,
            breakthrough_base_type="prev_close", breakthrough_offset_pct=2.0)
    assert t and t[0] == ("buy", 102.0)


def test_both_direction_buys_on_drop(monkeypatch):
    # 라인 ±5%: 상방 105 미도달(고가 104), 하방 95 도달(저가 94.5) → 95 체결 (낙폭 진입)
    rows = [(100, 100.5, 99.5, 100), (101, 104, 94.5, 110), (110, 111, 109, 110)]
    t = run(monkeypatch, rows, breakthrough_buy=True,
            breakthrough_base_type="prev_close", breakthrough_offset_pct=5.0,
            breakthrough_direction="both")
    assert t and t[0] == ("buy", 95.0)
    # 상방 전용이면 미진입
    t2 = run(monkeypatch, rows, breakthrough_buy=True,
             breakthrough_base_type="prev_close", breakthrough_offset_pct=5.0,
             breakthrough_direction="up")
    assert all(s != "buy" for s, _ in t2)


def test_intraday_timing_removes_open_gap(monkeypatch):
    # 매수 지정가 전일종가 -1% = 99: 시가 98(갭하락), 저가 97 → 도달
    rows = [(100, 100.5, 99.5, 100), (98, 111, 97, 110), (110, 111, 109, 110)]
    pre = run(monkeypatch, rows, buy_fill_type="prev_close", buy_fill_offset_pct=-1.0)
    intra = run(monkeypatch, rows, buy_fill_type="prev_close", buy_fill_offset_pct=-1.0,
                buy_timing="intraday")
    assert pre[0] == ("buy", 98.0)     # 장 시작 전: min(99, 시가98)=98 — 갭 혜택
    assert intra[0] == ("buy", 99.0)   # 장중 주문: 지정가 99 그대로 (보수)
