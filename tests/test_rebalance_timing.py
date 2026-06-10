"""정기 리밸런싱 + 마켓타이밍 엔진 단위 테스트 (GENPORT_GAP ②).

- 리밸런싱: weekly/monthly 시 신규 매수가 주·월 첫 거래일로 제한되는지
- 마켓타이밍: 지수 조건 OFF 시 신규 매수 차단(block_buy) / 전량 청산(exit_all),
  지수 데이터 부재 시 개입 안 함(fail-open)
ohlcv_loader 를 monkeypatch — DB·네트워크 불필요.
"""
import pandas as pd
import pytest

from src.kis_backtest_engine import BacktestConfig, BacktestEngine
from src.kis_strategies import condition_strategy  # noqa: F401 — "Condition" 레지스트리 등록

START = "2024-04-03"  # 수요일 (주 중간 시작 — 첫 sim일도 해당 주의 첫 거래일)
STOCK = "000111"
INDEX = "KOSPI"

ALWAYS_BUY = [{"factor_token": "{종가}", "function_id": "base", "params": {}, "op": "gte", "rhs": 0}]


def _frame(closes: list[float], end_warmup: str = START, sim_len: int | None = None) -> pd.DataFrame:
    """워밍업 60영업일(START 직전 종료) + START부터 closes 나머지."""
    n = len(closes)
    idx = pd.bdate_range(end=pd.Timestamp(end_warmup) - pd.tseries.offsets.BDay(1), periods=60)
    idx = idx.append(pd.bdate_range(start=end_warmup, periods=n - 60))
    s = pd.Series(closes, index=idx)
    return pd.DataFrame({"open": s, "high": s, "low": s, "close": s, "volume": [10_000] * n}, index=idx)


def rising_stock_df(sim_days: int = 85) -> pd.DataFrame:
    closes = [100.0 + 0.5 * i for i in range(60 + sim_days)]  # 단조 상승 (위험트리거 미발동)
    return _frame(closes)


def rise_fall_index_df(rise: int = 20, fall: int = 65) -> pd.DataFrame:
    """워밍업+상승(ON) → 하락(5일 수익률 음전 시 OFF)."""
    closes = [2000.0 + i for i in range(60 + rise)]
    closes += [closes[-1] - (i + 1) for i in range(fall)]
    return _frame(closes)


def first_off_date(idx_df: pd.DataFrame) -> pd.Timestamp:
    """{종가} pct(5) < 0 이 처음 참이 되는 sim 날짜 (조건식과 동일 공식)."""
    close = idx_df["close"]
    pct5 = close.pct_change(5) * 100.0
    sim = pct5[pct5.index >= pd.Timestamp(START)]
    return sim[sim < 0].index[0]


@pytest.fixture
def loaders(monkeypatch):
    """티커별 디스패치 로더 — STOCK→상승주, INDEX→상승후하락 지수."""
    stock_df = rising_stock_df()
    index_df = rise_fall_index_df()
    import src.data.ohlcv_loader as loader

    def fake(ticker, *a, **k):
        if str(ticker) == INDEX:
            return index_df.copy()
        return stock_df.copy()

    monkeypatch.setattr(loader, "load_ohlcv_unified", fake)
    return {"stock": stock_df, "index": index_df}


def make_cfg(**overrides) -> BacktestConfig:
    base = dict(
        symbols=[STOCK],
        strategy_name="Condition",
        strategy_params={"buy_conditions": list(ALWAYS_BUY)},
        start_date=START,
        end_date="2024-07-31",
        initial_capital=10_000_000,
        commission_rate=0.0,
        slippage_rate=0.0,
    )
    base.update(overrides)
    return BacktestConfig(**base)


def buys(engine):
    return [t for t in engine.trades if t.side == "buy"]


def sim_dates_of(df: pd.DataFrame):
    return [d for d in df.index if d >= pd.Timestamp(START)]


def firsts_of(dates, period: str) -> set:
    out, seen = set(), set()
    for d in dates:
        iso = d.isocalendar()
        key = (iso[0], iso[1]) if period == "weekly" else (d.year, d.month)
        if key not in seen:
            seen.add(key)
            out.add(pd.Timestamp(d).strftime("%Y-%m-%d"))
    return out


# ─── 정기 리밸런싱 ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("period", ["weekly", "monthly"])
def test_rebalance_limits_new_buys_to_period_firsts(loaders, period):
    """max_hold_days=1 로 매일 재진입을 유도 → 신규 매수일이 주·월 첫 거래일로 제한."""
    engine = BacktestEngine(make_cfg(rebalance_period=period, max_hold_days=1))
    result = engine.run()
    assert not result.get("error", False)

    allowed = firsts_of(sim_dates_of(loaders["stock"]), period)
    buy_dates = [t.date for t in buys(engine)]
    assert buy_dates, "리밸런싱일에는 매수가 발생해야 함"
    assert set(buy_dates) <= allowed
    assert len(buy_dates) >= 2  # 여러 주기에 걸쳐 재진입


def test_rebalance_default_buys_more_often_than_weekly(loaders):
    """기본(None)은 매일 재진입 가능 → weekly보다 매수 횟수가 많아야 함(기존 동작 불변)."""
    daily = BacktestEngine(make_cfg(max_hold_days=1))
    daily.run()
    weekly = BacktestEngine(make_cfg(rebalance_period="weekly", max_hold_days=1))
    weekly.run()
    assert len(buys(daily)) > len(buys(weekly)) >= 2


# ─── 마켓타이밍 ───────────────────────────────────────────────────────────────
MT_COND = [{"factor_token": "{종가}", "function_id": "pct", "params": {"n": "5"}, "op": "gte", "rhs": 0}]


def test_market_timing_exit_all(loaders):
    """지수 5일 수익률 음전(OFF) → 전량 청산 + 이후 신규 매수 없음."""
    engine = BacktestEngine(make_cfg(
        market_timing={"index_ticker": INDEX, "action": "exit_all", "conditions": list(MT_COND)},
    ))
    result = engine.run()
    assert not result.get("error", False)

    off = first_off_date(loaders["index"]).strftime("%Y-%m-%d")
    mt_exits = [t for t in engine.trades if t.side == "sell" and "Market-timing" in t.reason]
    assert mt_exits and mt_exits[0].date == off  # OFF 첫날 청산
    assert all(t.date < off for t in buys(engine))  # OFF 이후 신규 매수 없음
    assert STOCK not in engine.positions  # 포지션 비움


def test_market_timing_block_buy_keeps_position(loaders):
    """block_buy: OFF에도 보유분은 유지(청산 없음), 신규 매수만 차단."""
    engine = BacktestEngine(make_cfg(
        market_timing={"index_ticker": INDEX, "action": "block_buy", "conditions": list(MT_COND)},
    ))
    engine.run()
    assert [t for t in engine.trades if t.side == "sell"] == []  # 강제 청산 없음
    assert STOCK in engine.positions

    # 재진입 유도(max_hold=1) 시에도 OFF 구간엔 매수 없음
    engine2 = BacktestEngine(make_cfg(
        max_hold_days=1,
        market_timing={"index_ticker": INDEX, "action": "block_buy", "conditions": list(MT_COND)},
    ))
    engine2.run()
    off = first_off_date(loaders["index"]).strftime("%Y-%m-%d")
    assert buys(engine2) and all(t.date < off for t in buys(engine2))


def test_market_timing_fail_open_without_index_data(monkeypatch):
    """지수 데이터 부재 → 게이트 비활성(fail-open): 정상 매수."""
    stock_df = rising_stock_df()
    import src.data.ohlcv_loader as loader
    monkeypatch.setattr(
        loader, "load_ohlcv_unified",
        lambda ticker, *a, **k: pd.DataFrame() if str(ticker) == "NODATA" else stock_df.copy(),
    )
    engine = BacktestEngine(make_cfg(
        market_timing={"index_ticker": "NODATA", "action": "exit_all", "conditions": list(MT_COND)},
    ))
    result = engine.run()
    assert not result.get("error", False)
    assert buys(engine)  # 차단 없이 진입
    assert [t for t in engine.trades if "Market-timing" in t.reason] == []


def test_run_backtest_passes_rebalance_and_timing_through(loaders):
    """run_backtest 진입점이 rebalance_period·market_timing 을 엔진까지 전달."""
    from src.kis_backtest_engine import run_backtest
    result = run_backtest(
        symbols=[STOCK],
        strategy_name="Condition",
        start_date=START,
        end_date="2024-07-31",
        strategy_params={"buy_conditions": list(ALWAYS_BUY)},
        commission_rate=0.0,
        slippage_rate=0.0,
        max_hold_days=1,
        rebalance_period="monthly",
        market_timing={"index_ticker": INDEX, "action": "block_buy", "conditions": list(MT_COND)},
    )
    assert not result.get("error", False)
    trades = (result.get("result") or {}).get("trades", [])
    buy_dates = [t["date"] for t in trades if t.get("side") == "buy"]
    allowed = firsts_of(sim_dates_of(loaders["stock"]), "monthly")
    off = first_off_date(loaders["index"]).strftime("%Y-%m-%d")
    assert buy_dates and set(buy_dates) <= allowed  # 월 첫 거래일로 제한
    assert all(d < off for d in buy_dates)          # 마켓타이밍 OFF 이후 매수 없음
