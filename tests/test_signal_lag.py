"""signal_lag (젠포트 Tip 3 '전일 종가 기준') — 신호는 lag봉 이전 데이터, 체결은 당일.

① lag=1이면 진입·청산이 정확히 한 거래일 뒤로 밀리고 체결가는 그날 가격
② lag=1에서 벡터화 on/off 동일 결과
③ 마켓타이밍 판단도 동일 시차 적용
④ 기본값 0 = 기존 동작 불변
"""
import pandas as pd
import pytest

from src.kis_backtest_engine import BacktestConfig, BacktestEngine
from src.kis_strategies import condition_strategy  # noqa: F401 — "Condition" 레지스트리 자기등록

START = "2024-06-03"

# 시뮬 봉 종가: bar5에 +10% 점프(매수 조건), bar15에 -11% 급락(매도 조건)
CLOSES = [100, 100, 100, 100, 100, 110, 111, 112, 112.5,
          112.5, 112.5, 112.5, 112.5, 112.5, 112.5, 100,
          100, 100, 100, 100, 100]

BUY = [{"factor_token": "{종가}", "function_id": "pct", "params": {"n": "1"},
        "op": "gte", "rhs": 5}]
SELL = [{"factor_token": "{종가}", "function_id": "pct", "params": {"n": "1"},
         "op": "lte", "rhs": -5}]


def make_df(closes, warmup: int = 60) -> pd.DataFrame:
    idx = pd.bdate_range(end=pd.Timestamp(START) - pd.tseries.offsets.BDay(1), periods=warmup)
    idx = idx.append(pd.bdate_range(start=START, periods=len(closes)))
    close = pd.Series([100.0] * warmup + [float(c) for c in closes], index=idx)
    return pd.DataFrame({"open": close * 0.999, "high": close * 1.01,
                         "low": close * 0.99, "close": close,
                         "volume": 50_000.0}, index=idx)


def sim_date(bar: int) -> str:
    return pd.bdate_range(start=START, periods=bar + 1)[-1].strftime("%Y-%m-%d")


@pytest.fixture
def loaders(monkeypatch):
    frames = {"000111": make_df(CLOSES)}
    # 마켓타이밍 지수: bar9까지 상승, bar10부터 하락
    idx_closes = []
    v = 2500.0
    for i in range(len(CLOSES)):
        v = v * (1.001 if i < 10 else 0.999)
        idx_closes.append(round(v, 2))
    frames["KOSPI"] = make_df(idx_closes)
    import src.data.ohlcv_loader as loader
    monkeypatch.setattr(loader, "load_ohlcv_unified",
                        lambda ticker, *a, **k: frames.get(str(ticker), pd.DataFrame()).copy())
    return frames


def run(lag: int, vectorize: bool = True, market_timing: dict | None = None) -> list[tuple]:
    cfg = BacktestConfig(
        symbols=["000111"], strategy_name="Condition",
        strategy_params={"buy_conditions": BUY, "sell_conditions": SELL},
        start_date=START, end_date=sim_date(len(CLOSES) - 1),
        commission_rate=0.0, slippage_rate=0.0, max_positions=1,
        vectorize_signals=vectorize, signal_lag=lag, market_timing=market_timing,
    )
    engine = BacktestEngine(cfg)
    result = engine.run()
    assert not result.get("error", False)
    return [(t.date, t.side, round(t.price, 2)) for t in engine.trades]


def test_default_is_zero():
    cfg = BacktestConfig(symbols=["x"], strategy_name="s", strategy_params={},
                         start_date="2024-01-01", end_date="2024-02-01")
    assert cfg.signal_lag == 0


def test_lag_shifts_entry_and_exit_by_one_bar(loaders):
    # lag=0: 점프 봉(bar5)에 매수, 급락 봉(bar15)에 매도 — 당일 종가 체결
    assert run(0) == [(sim_date(5), "buy", 110.0), (sim_date(15), "sell", 100.0)]
    # lag=1: 신호는 같은 봉에서 발생하지만 체결은 다음 거래일 종가
    assert run(1) == [(sim_date(6), "buy", 111.0), (sim_date(16), "sell", 100.0)]


def test_lag_vectorized_equals_per_bar(loaders):
    assert run(1, vectorize=True) == run(1, vectorize=False)


def test_market_timing_respects_lag(loaders):
    # 지수 조건: 전일 대비 상승({종가} pct(1) >= 0). bar10부터 지수 하락 → OFF
    mt = {"index_ticker": "KOSPI", "action": "exit_all",
          "conditions": [{"factor_token": "{종가}", "function_id": "pct",
                          "params": {"n": "1"}, "op": "gte", "rhs": 0}]}
    # lag=0: bar10에 OFF 감지 → 그날 전량 청산
    t0 = run(0, market_timing=mt)
    assert ("buy" in {s for _, s, _ in t0}) and t0[-1][0] == sim_date(10)
    # lag=1: bar10의 판단은 bar9(상승) 기준 → 청산은 bar11로 밀림
    t1 = run(1, market_timing=mt)
    assert t1[-1][0] == sim_date(11) and t1[-1][1] == "sell"
