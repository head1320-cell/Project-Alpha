"""트레일링 스탑(드래깅 청산) 엔진 단위 테스트.

합성 OHLCV(상승 → 하락)로 보유 중 고점 추적 + 고점 대비 N% 하락 청산을 검증.
ohlcv_loader 를 monkeypatch — DB·네트워크 불필요.
"""
import pandas as pd
import pytest

from src.kis_backtest_engine import BacktestConfig, BacktestEngine
from src.kis_strategies import condition_strategy  # noqa: F401 — "Condition" 레지스트리 등록

# ─── 합성 OHLCV: 워밍업(100 고정) → 상승(+5/일, 150까지) → 하락(-5/일) ─────────
START = "2024-04-01"  # 시뮬레이션 시작일 (이전 60영업일은 워밍업)


def make_rise_fall_df() -> pd.DataFrame:
    warmup = [100.0] * 60
    rise = [100.0 + 5 * i for i in range(11)]      # 100 → 150 (peak)
    fall = [150.0 - 5 * i for i in range(1, 9)]    # 145 → 110
    closes = warmup + rise + fall
    n = len(closes)
    # 워밍업 60영업일이 START 직전에 끝나도록 인덱스 구성
    idx = pd.bdate_range(end=pd.Timestamp(START) - pd.tseries.offsets.BDay(1), periods=60)
    idx = idx.append(pd.bdate_range(start=START, periods=n - 60))
    s = pd.Series(closes, index=idx)
    return pd.DataFrame({
        "open": s, "high": s, "low": s, "close": s,
        "volume": [10_000] * n,
    }, index=idx)


@pytest.fixture
def synthetic_loader(monkeypatch):
    df = make_rise_fall_df()
    import src.data.ohlcv_loader as loader
    monkeypatch.setattr(loader, "load_ohlcv_unified", lambda *a, **k: df.copy())
    return df


def make_cfg(**overrides) -> BacktestConfig:
    base = dict(
        symbols=["000111"],
        strategy_name="Condition",
        strategy_params={"buy_conditions": [
            {"factor_token": "{종가}", "function_id": "base", "params": {}, "op": "gte", "rhs": 0},
        ]},
        start_date=START,
        end_date="2024-06-28",
        initial_capital=10_000_000,
        commission_rate=0.0,
        slippage_rate=0.0,
    )
    base.update(overrides)
    return BacktestConfig(**base)


def sells(engine: BacktestEngine):
    return [t for t in engine.trades if t.side == "sell"]


def test_trailing_stop_triggers_on_drawdown_from_peak(synthetic_loader):
    """고점 150 → -10% = 135 도달 시 청산 (진입가 100 대비로는 +35%라 손절과 무관)."""
    engine = BacktestEngine(make_cfg(trailing_stop_pct=10.0))
    result = engine.run()
    assert not result.get("error", False)

    trailing_sells = [t for t in sells(engine) if "Trailing" in t.reason]
    assert trailing_sells, "트레일링 청산이 발생해야 함"
    first = trailing_sells[0]
    # 종가 기준 첫 트리거 봉: 150 → 145 → 140 → 135(=150×0.9) 에서 체결
    assert first.price == pytest.approx(135.0)
    assert first.pnl is not None and first.pnl > 0  # 진입 100 → 청산 135 (이익 보존형 청산)


def test_trailing_not_triggered_without_config(synthetic_loader):
    """trailing_stop_pct=None(기본) → 같은 데이터에서 매도 없음 (기존 동작 불변)."""
    engine = BacktestEngine(make_cfg(trailing_stop_pct=None))
    result = engine.run()
    assert not result.get("error", False)
    assert sells(engine) == []
    assert any(t.side == "buy" for t in engine.trades)


def test_trailing_respects_min_hold_days(synthetic_loader):
    """min_hold_days 이내에는 트레일링 청산 보류 (손익절과 동일 정책)."""
    engine = BacktestEngine(make_cfg(trailing_stop_pct=10.0, min_hold_days=365))
    result = engine.run()
    assert not result.get("error", False)
    assert sells(engine) == []  # 시뮬 기간(약 3개월) < 최소 보유 1년 → 청산 없음


def test_trailing_beats_plain_stop_loss_here(synthetic_loader):
    """동일 시나리오에서 진입가 기준 손절(-10%)은 미발동 — 트레일링과의 차이를 고정."""
    engine = BacktestEngine(make_cfg(stop_loss_pct=10.0))  # 트레일링 없음
    engine.run()
    # 최저 종가 110 > 손절선 90 → 손절 미발동
    assert sells(engine) == []


def test_run_backtest_passes_trailing_through(synthetic_loader):
    """run_backtest 진입점이 trailing_stop_pct 를 엔진까지 전달한다."""
    from src.kis_backtest_engine import run_backtest
    result = run_backtest(
        symbols=["000111"],
        strategy_name="Condition",
        start_date=START,
        end_date="2024-06-28",
        strategy_params={"buy_conditions": [
            {"factor_token": "{종가}", "function_id": "base", "params": {}, "op": "gte", "rhs": 0},
        ]},
        commission_rate=0.0,
        slippage_rate=0.0,
        trailing_stop_pct=10.0,
    )
    assert not result.get("error", False)
    trades = (result.get("result") or {}).get("trades", [])
    reasons = [t.get("reason", "") for t in trades if t.get("side") == "sell"]
    assert any("Trailing" in r for r in reasons)
