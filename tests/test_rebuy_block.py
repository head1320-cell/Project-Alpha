"""재매수 방지 (rebuy_block_days) — 청산 후 N일(캘린더) 이내 재진입 금지.

매수 신호가 두 번(bar5, bar10) 발생하고 사이(bar7)에 손절 청산되는 시나리오:
  · 미사용(0): 두 번째 신호에 재매수
  · 차단(N 충분): 두 번째 신호 무시 — 거래 수 감소
"""
import pandas as pd

from src.kis_backtest_engine import BacktestConfig, BacktestEngine
from src.kis_strategies import condition_strategy  # noqa: F401 — 레지스트리 자기등록

START = "2024-06-03"

# bar5 +10% (매수), bar7 -8% (매도조건), bar10 +10% (재매수 신호), 이후 평탄
CLOSES = [100, 100, 100, 100, 100, 110, 110, 101.2, 101.2, 101.2,
          111.3, 111.3, 111.3, 111.3, 111.3, 111.3, 111.3, 111.3]

BUY = [{"factor_token": "{종가}", "function_id": "pct", "params": {"n": "1"},
        "op": "gte", "rhs": 5}]
SELL = [{"factor_token": "{종가}", "function_id": "pct", "params": {"n": "1"},
         "op": "lte", "rhs": -5}]


def make_df() -> pd.DataFrame:
    idx = pd.bdate_range(end=pd.Timestamp(START) - pd.tseries.offsets.BDay(1), periods=60)
    idx = idx.append(pd.bdate_range(start=START, periods=len(CLOSES)))
    close = pd.Series([100.0] * 60 + [float(c) for c in CLOSES], index=idx)
    return pd.DataFrame({"open": close * 0.999, "high": close * 1.01,
                         "low": close * 0.99, "close": close,
                         "volume": 50_000.0}, index=idx)


def run(rebuy_block_days: int, monkeypatch) -> list[tuple]:
    df = make_df()
    import src.data.ohlcv_loader as loader
    monkeypatch.setattr(loader, "load_ohlcv_unified",
                        lambda ticker, *a, **k: df.copy())
    cfg = BacktestConfig(
        symbols=["000111"], strategy_name="Condition",
        strategy_params={"buy_conditions": BUY, "sell_conditions": SELL},
        start_date=START, end_date=df.index[-1].strftime("%Y-%m-%d"),
        commission_rate=0.0, slippage_rate=0.0, max_positions=1,
        rebuy_block_days=rebuy_block_days,
    )
    engine = BacktestEngine(cfg)
    result = engine.run()
    assert not result.get("error", False)
    return [(t.date, t.side) for t in engine.trades]


def test_rebuy_allowed_by_default(monkeypatch):
    trades = run(0, monkeypatch)
    assert [s for _, s in trades] == ["buy", "sell", "buy"]   # 청산 후 재매수됨


def test_rebuy_blocked_within_window(monkeypatch):
    # bar7 청산 → bar10 신호는 캘린더 3~5일 후 → 30일 차단이면 재매수 없음
    trades = run(30, monkeypatch)
    assert [s for _, s in trades] == ["buy", "sell"]


def test_rebuy_allowed_after_window(monkeypatch):
    # 차단 1일: bar10 재매수 신호는 청산 3일+ 후 → 허용
    trades = run(1, monkeypatch)
    assert [s for _, s in trades] == ["buy", "sell", "buy"]
