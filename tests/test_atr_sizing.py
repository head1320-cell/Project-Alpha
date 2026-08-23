"""ATR 비중(역변동성 사이징) 엔진 단위 테스트.

저변동 종목이 고변동 종목보다 큰 배분을 받는지(NATR 2% 기준 0.5~1.5 클램프),
equal 모드는 기존 동작 그대로인지 검증. ohlcv_loader monkeypatch — DB 불필요.
"""
import pandas as pd
import pytest

from src.kis_backtest_engine import BacktestConfig, BacktestEngine
from src.kis_strategies import condition_strategy  # noqa: F401 — "Condition" 레지스트리 등록

START = "2024-04-03"
LOW_VOL = "000111"   # 일중 변동 ±0.5% 수준
HIGH_VOL = "000222"  # 일중 변동 ±5% 수준

ALWAYS_BUY = [{"factor_token": "{종가}", "function_id": "base", "params": {}, "op": "gte", "rhs": 0}]


def make_vol_df(base: float, range_pct: float, days: int = 120) -> pd.DataFrame:
    """종가 일정(추세 없음), 고가/저가 폭만 다른 합성 OHLCV — NATR 차이를 만든다."""
    idx = pd.bdate_range(end=pd.Timestamp(START) - pd.tseries.offsets.BDay(1), periods=60)
    idx = idx.append(pd.bdate_range(start=START, periods=days - 60))
    close = pd.Series([base] * days, index=idx)
    spread = base * range_pct / 100.0
    return pd.DataFrame({
        "open": close, "high": close + spread, "low": close - spread, "close": close,
        "volume": [10_000] * days,
    }, index=idx)


@pytest.fixture
def vol_loaders(monkeypatch):
    dfs = {LOW_VOL: make_vol_df(100.0, 0.5), HIGH_VOL: make_vol_df(100.0, 5.0)}
    import src.data.ohlcv_loader as loader
    monkeypatch.setattr(loader, "load_ohlcv_unified",
                        lambda ticker, *a, **k: dfs.get(str(ticker), dfs[LOW_VOL]).copy())
    return dfs


def make_cfg(**overrides) -> BacktestConfig:
    base = dict(
        symbols=[LOW_VOL, HIGH_VOL],
        strategy_name="Condition",
        strategy_params={"buy_conditions": list(ALWAYS_BUY)},
        start_date=START,
        end_date="2024-06-28",
        initial_capital=100_000_000,
        commission_rate=0.0,
        slippage_rate=0.0,
        max_positions=2,
    )
    base.update(overrides)
    return BacktestConfig(**base)


def first_buy_value(engine: BacktestEngine, ticker: str) -> float | None:
    for t in engine.trades:
        if t.side == "buy" and t.ticker == ticker:
            return t.value
    return None


def test_atr_mode_overweights_low_volatility(vol_loaders):
    """ATR 모드: NATR이 낮은 종목(저변동)이 더 큰 금액으로 진입."""
    engine = BacktestEngine(make_cfg(buy_weight_mode="atr"))
    result = engine.run()
    assert not result.get("error", False)
    low_v, high_v = first_buy_value(engine, LOW_VOL), first_buy_value(engine, HIGH_VOL)
    assert low_v is not None and high_v is not None
    # 저변동(NATR≈0.5~1%) → 1.5배 클램프 / 고변동(NATR≈5~10%) → 0.5배 클램프 → 약 3배 차이
    assert low_v > high_v * 1.5


def test_equal_mode_sizes_similarly(vol_loaders):
    """equal 모드(기본): 변동성과 무관하게 비슷한 배분 (기존 동작 불변)."""
    engine = BacktestEngine(make_cfg(buy_weight_mode="equal"))
    result = engine.run()
    assert not result.get("error", False)
    low_v, high_v = first_buy_value(engine, LOW_VOL), first_buy_value(engine, HIGH_VOL)
    assert low_v is not None and high_v is not None
    # 동일가중: 첫 매수는 잔여 슬롯 균등 — 두 종목 배분이 ±25% 이내
    assert abs(low_v - high_v) / max(low_v, high_v) < 0.25


def test_natr_helper_values(vol_loaders):
    """_natr_pct가 합성 변동폭과 정합 — 저변동 < 고변동, 데이터 부족 시 None."""
    engine = BacktestEngine(make_cfg(buy_weight_mode="atr"))
    low = engine._natr_pct(vol_loaders[LOW_VOL])
    high = engine._natr_pct(vol_loaders[HIGH_VOL])
    assert low is not None and high is not None and low < high
    assert engine._natr_pct(vol_loaders[LOW_VOL].head(5)) is None  # 15봉 미만 → None
