"""시그널 벡터화 등가성 테스트 — 사전계산과 per-bar 평가가 모든 봉에서 동일해야 한다.

① 골드 스위프: 전 종목 × 전 봉, signal_at == generate_signal (엔진 포맷 슬라이스로)
② 엔진 end-to-end: vectorize on/off → 거래·자산곡선 완전 일치
③ 횡단면 as_of 포맷 버그 회귀: 엔진 date 포맷(YYYYMMDD)에서 rank 조건이 평가됨
④ 사전계산 실패 → per-bar 폴백으로 동일 결과
⑤ 성능: 벡터화가 per-bar보다 빨라야 함 (완화 임계)
"""
import time

import numpy as np
import pandas as pd
import pytest

from src import kis_data_fetcher
from src.kis_backtest_engine import BacktestConfig, BacktestEngine
from src.kis_strategies import condition_strategy as cs

START = "2024-04-03"


def make_df(seed: int, n: int = 220) -> pd.DataFrame:
    """다양한 패턴(상승+노이즈+급락 구간) — 매수/매도/HOLD가 골고루 나오게."""
    rng = np.random.RandomState(seed)
    idx = pd.bdate_range(end=pd.Timestamp(START) - pd.tseries.offsets.BDay(1), periods=60)
    idx = idx.append(pd.bdate_range(start=START, periods=n - 60))
    steps = rng.normal(0.1, 1.5, n)
    steps[120:135] -= 3.0  # 급락 구간 (매도 조건 유발)
    close = pd.Series(100 + np.cumsum(steps), index=idx).clip(lower=20)
    spread = close * 0.01
    df = pd.DataFrame({"open": close - spread / 2, "high": close + spread,
                       "low": close - spread, "close": close,
                       "volume": rng.randint(10_000, 90_000, n).astype(float)}, index=idx)
    return df


def engine_format_slice(df: pd.DataFrame, upto: int, ticker: str) -> pd.DataFrame:
    """엔진 _generate_signal_as_of가 만드는 슬라이스 포맷 재현 (date=YYYYMMDD)."""
    s = df.iloc[:upto + 1]
    out = pd.DataFrame({
        "date": s.index.strftime("%Y%m%d"),
        "open": s["open"].values, "high": s["high"].values,
        "low": s["low"].values, "close": s["close"].values,
        "volume": s["volume"].values,
    })
    out.attrs["ticker"] = ticker
    return out


CONDS_BUY = [
    {"factor_token": "{RSI}", "function_id": "base", "params": {},
     "op": "between", "rhs": 0, "rhs2": 65},
    {"factor_token": "{종가}", "function_id": "pct", "params": {"n": "5"},
     "op": "gte", "rhs": 0},
    {"factor_token": "{종가}", "function_id": "rank", "params": {"dir": "DESC"},
     "op": "lte", "rhs": 2},                       # 횡단면 (패널)
    {"factor_token": "{뉴지스코어}", "function_id": "base", "params": {},
     "op": "gte", "rhs": 0},                       # 평가 불가 — 건너뜀
]
CONDS_SELL = [
    {"factor_token": "{종가}", "function_id": "pct", "params": {"n": "5"},
     "op": "lte", "rhs": -4},
]


def make_map() -> dict:
    return {"000111": make_df(1), "000222": make_df(2), "000333": make_df(3)}


# ─── ① 골드 스위프: 전 종목 × 전 봉 일치 ─────────────────────────────────────
def test_equivalence_sweep_all_bars(monkeypatch):
    omap = make_map()
    s = cs.ConditionStrategy(buy_conditions=CONDS_BUY, sell_conditions=CONDS_SELL)
    s.prepare_panel(omap)
    s.precompute_signals(omap)

    mismatches = []
    for tk, df in omap.items():
        for t in range(s.required_days, len(df)):
            sl = engine_format_slice(df, t, tk)
            monkeypatch.setattr(kis_data_fetcher, "get_daily_prices",
                                lambda code, days, _sl=sl: _sl)
            per_bar = s.generate_signal(tk, tk).action
            vec_sig = s.signal_at(tk, df.index[t])
            assert vec_sig is not None
            if vec_sig.action != per_bar:
                mismatches.append((tk, str(df.index[t].date()), per_bar, vec_sig.action))
    assert mismatches == [], f"불일치 {len(mismatches)}건: {mismatches[:5]}"


# ─── ② 엔진 end-to-end: on/off 동일 결과 ─────────────────────────────────────
@pytest.fixture
def loaders(monkeypatch):
    omap = make_map()
    import src.data.ohlcv_loader as loader
    monkeypatch.setattr(loader, "load_ohlcv_unified",
                        lambda ticker, *a, **k: omap.get(str(ticker), make_df(9)).copy())
    return omap


def run_engine(vectorize: bool) -> BacktestEngine:
    cfg = BacktestConfig(
        symbols=["000111", "000222", "000333"],
        strategy_name="Condition",
        strategy_params={"buy_conditions": CONDS_BUY, "sell_conditions": CONDS_SELL},
        start_date=START, end_date="2024-11-29",
        commission_rate=0.0, slippage_rate=0.0,
        stop_loss_pct=8.0, max_hold_days=20,        # 상태 의존 로직도 함께 검증
        vectorize_signals=vectorize,
    )
    engine = BacktestEngine(cfg)
    result = engine.run()
    assert not result.get("error", False)
    return engine


def test_engine_identical_with_and_without_vectorization(loaders):
    fast, slow = run_engine(True), run_engine(False)
    t_fast = [(t.date, t.ticker, t.side, t.price, t.quantity, t.reason) for t in fast.trades]
    t_slow = [(t.date, t.ticker, t.side, t.price, t.quantity, t.reason) for t in slow.trades]
    assert t_fast == t_slow                          # 거래 완전 일치
    assert fast.equity_history == slow.equity_history  # 자산곡선 완전 일치
    assert len(t_fast) > 4                           # 의미 있는 표본 (매수+매도 다수)


# ─── ③ 횡단면 as_of 포맷 버그 회귀 (per-bar 경로) ────────────────────────────
def test_cross_condition_works_with_engine_date_format(monkeypatch):
    """엔진 슬라이스(date=YYYYMMDD)에서 rank 조건이 무시되던 버그 — 수정 검증."""
    omap = {"000111": make_df(11), "000222": make_df(12)}
    # 000111이 종가 1위가 되도록 보정
    omap["000111"]["close"] += 1000
    only_rank = [{"factor_token": "{종가}", "function_id": "rank",
                  "params": {"dir": "DESC"}, "op": "lte", "rhs": 1}]
    s = cs.ConditionStrategy(buy_conditions=only_rank)
    s.prepare_panel(omap)

    t = len(omap["000111"]) - 1
    sl = engine_format_slice(omap["000111"], t, "000111")
    monkeypatch.setattr(kis_data_fetcher, "get_daily_prices",
                        lambda code, days, _sl=sl: _sl)
    from src.kis_signal import Action
    assert s.generate_signal("000111", "000111").action == Action.BUY  # 수정 전엔 HOLD


# ─── ④ 사전계산 실패 → 폴백 동일 결과 ────────────────────────────────────────
def test_precompute_failure_falls_back(loaders, monkeypatch):
    baseline = run_engine(False)
    monkeypatch.setattr(cs.ConditionStrategy, "_precompute_ticker",
                        lambda self, tk, df: (_ for _ in ()).throw(RuntimeError("boom")))
    broken = run_engine(True)                        # 사전계산 실패 → per-bar 폴백
    assert [(t.date, t.ticker, t.side) for t in broken.trades] \
        == [(t.date, t.ticker, t.side) for t in baseline.trades]


# ─── ⑤ 성능 — 벡터화가 빨라야 함 (완화 임계: CI 변동 흡수) ───────────────────
def test_vectorized_is_faster(monkeypatch):
    omap = {f"{i:06d}": make_df(i + 100, n=320) for i in range(1, 21)}  # 20종목
    conds = [{"factor_token": "{RSI}", "function_id": "base", "params": {},
              "op": "between", "rhs": 0, "rhs2": 100},
             {"factor_token": "{종가}", "function_id": "ma", "params": {"n": "20"},
              "op": "gte", "rhs": 0}]
    s = cs.ConditionStrategy(buy_conditions=conds)

    t0 = time.perf_counter()
    s.precompute_signals(omap)
    lookups = sum(s.signal_at(tk, ts) is not None
                  for tk, df in omap.items() for ts in df.index[60:])
    vec_elapsed = time.perf_counter() - t0
    assert lookups > 4000

    t0 = time.perf_counter()
    for tk, df in omap.items():
        for t in range(60, len(df), 4):              # per-bar는 1/4만 표본 측정
            sl = engine_format_slice(df, t, tk)
            monkeypatch.setattr(kis_data_fetcher, "get_daily_prices",
                                lambda code, days, _sl=sl: _sl)
            s.generate_signal(tk, tk)
    per_bar_elapsed = (time.perf_counter() - t0) * 4  # 전수 환산

    assert vec_elapsed < per_bar_elapsed * 0.5, \
        f"벡터화 {vec_elapsed:.2f}s vs per-bar 환산 {per_bar_elapsed:.2f}s"
