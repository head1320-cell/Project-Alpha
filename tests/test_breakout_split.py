"""돌파매수 + 분할매수 엔진 단위 테스트 (GENPORT_GAP 잔여 ㉢).

- 돌파매수: 전일 고가 돌파 전에는 진입하지 않고, 돌파 봉에서 max(시가, 전일고가)로 체결
- 분할매수: buy_divide_pct/max_buy_count — 1회 비중씩 최대 횟수까지 추가 매수
ohlcv_loader monkeypatch — DB 불필요.
"""
import pandas as pd
import pytest

from src.kis_backtest_engine import BacktestConfig, BacktestEngine
from src.kis_strategies import condition_strategy  # noqa: F401 — "Condition" 레지스트리 등록

START = "2024-04-03"
STOCK = "000111"

ALWAYS_BUY = [{"factor_token": "{종가}", "function_id": "base", "params": {}, "op": "gte", "rhs": 0}]


def breakout_df() -> pd.DataFrame:
    """워밍업(고가 100) → 고가가 매일 낮아짐(미돌파) → 5일째 고가 99로 전일 96 돌파."""
    idx = pd.bdate_range(end=pd.Timestamp(START) - pd.tseries.offsets.BDay(1), periods=60)
    rows = [{"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0}] * 60
    sim = [
        {"open": 99.0, "high": 99.0, "low": 98.0, "close": 98.5},   # d1: 99 < 100 미돌파
        {"open": 98.0, "high": 98.0, "low": 97.0, "close": 97.5},   # d2: 98 < 99 미돌파
        {"open": 97.0, "high": 97.0, "low": 96.0, "close": 96.5},   # d3
        {"open": 96.0, "high": 96.0, "low": 95.0, "close": 95.5},   # d4
        {"open": 95.0, "high": 99.0, "low": 94.0, "close": 98.0},   # d5: 99 ≥ 96 돌파 → max(95,96)=96
        {"open": 98.0, "high": 98.0, "low": 97.0, "close": 97.5},   # d6
    ]
    idx = idx.append(pd.bdate_range(start=START, periods=len(sim)))
    rows = rows + sim
    df = pd.DataFrame(rows, index=idx)
    df["volume"] = 10_000
    return df


def rising_df(days: int = 90) -> pd.DataFrame:
    idx = pd.bdate_range(end=pd.Timestamp(START) - pd.tseries.offsets.BDay(1), periods=60)
    idx = idx.append(pd.bdate_range(start=START, periods=days - 60))
    close = pd.Series([100.0 + 0.5 * i for i in range(days)], index=idx)
    return pd.DataFrame({"open": close, "high": close, "low": close, "close": close,
                         "volume": [10_000] * days}, index=idx)


def patch_loader(monkeypatch, df: pd.DataFrame):
    import src.data.ohlcv_loader as loader
    monkeypatch.setattr(loader, "load_ohlcv_unified", lambda *a, **k: df.copy())


def make_cfg(**overrides) -> BacktestConfig:
    base = dict(
        symbols=[STOCK],
        strategy_name="Condition",
        strategy_params={"buy_conditions": list(ALWAYS_BUY)},
        start_date=START,
        end_date="2024-06-28",
        initial_capital=10_000_000,
        commission_rate=0.0,
        slippage_rate=0.0,
    )
    base.update(overrides)
    return BacktestConfig(**base)


def buys(engine):
    return [t for t in engine.trades if t.side == "buy"]


# ─── 돌파매수 ─────────────────────────────────────────────────────────────────
def test_breakthrough_waits_for_breakout_and_fills_at_trigger(monkeypatch):
    df = breakout_df()
    patch_loader(monkeypatch, df)
    engine = BacktestEngine(make_cfg(breakthrough_buy=True))
    result = engine.run()
    assert not result.get("error", False)

    bs = buys(engine)
    breakout_date = df.index[64].strftime("%Y-%m-%d")  # 워밍업 60 + d5(인덱스 64)
    assert bs and bs[0].date == breakout_date           # 미돌파 4일은 진입 없음
    assert bs[0].price == pytest.approx(96.0)           # max(시가 95, 전일고가 96)


def test_breakthrough_off_buys_first_day(monkeypatch):
    """플래그 없으면 첫 신호일에 그대로 진입 (기존 동작 불변)."""
    df = breakout_df()
    patch_loader(monkeypatch, df)
    engine = BacktestEngine(make_cfg(breakthrough_buy=False))
    engine.run()
    bs = buys(engine)
    assert bs and bs[0].date == df.index[60].strftime("%Y-%m-%d")  # d1


def test_breakthrough_gap_up_fills_at_open(monkeypatch):
    """갭상승(시가>전일고가) 돌파 → 시가 체결."""
    df = breakout_df()
    # d5 시가를 전일고가(96)보다 위로: max(97.5, 96) = 97.5
    df.iloc[64, df.columns.get_loc("open")] = 97.5
    patch_loader(monkeypatch, df)
    engine = BacktestEngine(make_cfg(breakthrough_buy=True))
    engine.run()
    bs = buys(engine)
    assert bs and bs[0].price == pytest.approx(97.5)


# ─── 분할매수 ─────────────────────────────────────────────────────────────────
def test_split_buy_adds_on_up_to_max_count(monkeypatch):
    """50%씩 최대 2회 — 같은 종목에 buy 트레이드 정확히 2건(1차 + 분할 2차) 후 중단."""
    patch_loader(monkeypatch, rising_df())
    engine = BacktestEngine(make_cfg(buy_divide_pct=50.0, max_buy_count=2))
    result = engine.run()
    assert not result.get("error", False)

    bs = buys(engine)
    assert len(bs) == 2
    assert "분할매수" in bs[1].reason
    assert engine.positions[STOCK].buy_count == 2


def test_split_buy_off_single_entry(monkeypatch):
    """분할 미설정(기본): 1회 진입 후 중복 매수 없음 (기존 동작 불변)."""
    patch_loader(monkeypatch, rising_df())
    engine = BacktestEngine(make_cfg())
    engine.run()
    assert len(buys(engine)) == 1
