"""기간종료 청산 — 매도 미발동 전략도 통계(승률/PF/거래수)가 실현 기준으로 채워진다."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from src.kis_backtest_engine import BacktestConfig, BacktestEngine  # noqa: E402
from src.kis_strategies import condition_strategy  # noqa: F401,E402 — "Condition" 등록

START = "2024-04-01"


def make_up_df() -> pd.DataFrame:
    closes = [100.0] * 60 + [100.0 + i for i in range(40)]  # 워밍업 후 지속 상승
    n = len(closes)
    idx = pd.bdate_range(end=pd.Timestamp(START) - pd.tseries.offsets.BDay(1), periods=60)
    idx = idx.append(pd.bdate_range(start=START, periods=n - 60))
    s = pd.Series(closes, index=idx)
    return pd.DataFrame({"open": s, "high": s, "low": s, "close": s, "volume": [10_000] * n}, index=idx)


@pytest.fixture
def up_loader(monkeypatch):
    df = make_up_df()
    import src.data.ohlcv_loader as loader
    monkeypatch.setattr(loader, "load_ohlcv_unified", lambda *a, **k: df.copy())
    return df


BUY_ONLY = {"buy_conditions": [
    {"factor_token": "{종가}", "function_id": "base", "params": {}, "op": "gte", "rhs": 0},
]}  # 항상 매수·매도 조건 없음 → 기간 끝까지 보유


def _cfg(**over) -> BacktestConfig:
    base = dict(symbols=["000111"], strategy_name="Condition", strategy_params=BUY_ONLY,
                start_date=START, end_date="2024-06-28", initial_capital=10_000_000,
                commission_rate=0.001, slippage_rate=0.001)
    base.update(over)
    return BacktestConfig(**base)


def test_no_liquidation_by_default(up_loader):
    e = BacktestEngine(_cfg())
    r = e.run()
    st = r["result"]["statistics"]
    assert st["num_trades"] == 0                      # 청산 없음 → 기존 동작 불변
    assert not [t for t in e.trades if t.side == "sell"]


def test_liquidate_at_end_fills_stats(up_loader):
    e = BacktestEngine(_cfg(liquidate_at_end=True))
    r = e.run()
    st = r["result"]["statistics"]
    sells = [t for t in e.trades if t.side == "sell"]
    assert len(sells) == 1 and sells[0].reason == "기간종료 청산"
    assert st["num_trades"] == 1
    assert st["win_rate"] > 0                          # 상승장 보유 → 승리
    assert st["eod_liquidated"] == 1
    assert r["result"]["round_trips"], "라운드트립도 생성"


def test_final_equity_reflects_liquidation_costs(up_loader):
    e_off = BacktestEngine(_cfg())
    r_off = e_off.run()
    e_on = BacktestEngine(_cfg(liquidate_at_end=True))
    r_on = e_on.run()
    eq_off = r_off["result"]["equity_curve"][-1]
    eq_on = r_on["result"]["equity_curve"][-1]
    assert eq_on < eq_off                              # 청산 수수료·슬리피지 반영(정직)
    assert eq_on > eq_off * 0.99                       # 미세 차이
