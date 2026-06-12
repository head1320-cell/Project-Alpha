"""체결 가격 기준 확장 — 이동평균 6종·피벗 기준선·수식입력·만기 매도 정밀화 (Phase 1).

① ma20 = 전일까지 20일 종가 평균 (당일 제외 — 주문가 가용성) / 봉 부족 시 종가 폴백
② pivot_mid = (전일고가+전일저가)/2 — 보수적 해석 문서화
③ 수식입력 기준가: expr "과거값({종가},{1일})" ≡ prev_close 체결
④ 만기 매도 가격 기준: 지정가 도달 시 그 가격, 미도달 시 종가 폴백(반드시 청산)
"""
import numpy as np
import pandas as pd

from src.engine.fill_price import resolve_from_slice
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


# ─── ① ② resolve_from_slice 단위 ─────────────────────────────────────────────
def test_ma_fill_excludes_today():
    rows = [(100, 101, 99, 100)] * 25
    df = make_df(rows, warmup=0)
    df.iloc[-1, df.columns.get_loc("close")] = 999.0   # 당일 종가 급변
    got = resolve_from_slice("ma20", df)
    expect = float(df["close"].iloc[-21:-1].mean())    # 전일까지 20일
    assert abs(got - expect) < 1e-9 and abs(got - 100.0) < 1e-6


def test_ma_fill_falls_back_when_short():
    df = make_df([(100, 101, 99, 100)] * 3, warmup=0)
    assert resolve_from_slice("ma200", df) == 100.0    # 봉 부족 → 당일 종가


def test_pivot_mid_is_prev_hl_half():
    df = make_df([(100, 110, 90, 105), (100, 101, 99, 100)], warmup=0)
    assert abs(resolve_from_slice("pivot_mid", df) - (110 + 90) / 2) < 1e-9


# ─── ③ ④ 엔진 통합 ───────────────────────────────────────────────────────────
CLOSES = [(100, 100.5, 99.5, 100), (109, 111, 108, 110),
          (110, 111, 109, 110), (110, 113, 109, 112), (112, 113, 111, 112)]


def run(monkeypatch, **kw):
    df = make_df(CLOSES)
    import src.data.ohlcv_loader as loader
    monkeypatch.setattr(loader, "load_ohlcv_unified", lambda ticker, *a, **k: df.copy())
    cfg = BacktestConfig(symbols=["000111"], strategy_name="Condition",
                         strategy_params={"buy_conditions": BUY},
                         start_date=START, end_date=df.index[-1].strftime("%Y-%m-%d"),
                         commission_rate=0.0, slippage_rate=0.0, max_positions=1, **kw)
    e = BacktestEngine(cfg)
    r = e.run()
    assert not r.get("error", False)
    return e


def test_expr_fill_equals_prev_close(monkeypatch):
    a = run(monkeypatch, buy_fill_type="expr", buy_fill_expr="과거값({종가},{1일})")
    b = run(monkeypatch, buy_fill_type="prev_close")
    pa = [t.price for t in a.trades if t.side == "buy"]
    pb = [t.price for t in b.trades if t.side == "buy"]
    assert pa and np.allclose(pa, pb)


def test_expr_fill_rejects_cross(monkeypatch):
    import pytest
    with pytest.raises(ValueError, match="횡단면"):
        run(monkeypatch, buy_fill_type="expr", buy_fill_expr="비율내림차순({종가})")


def test_expiry_fill_reached_uses_limit(monkeypatch):
    # 만기일(bar3): 전일종가 110×1.02=112.2 ≤ 고가 113 → 도달, 체결 max(112.2, 시가110)=112.2
    e = run(monkeypatch, max_hold_days=2,
            expiry_fill_type="prev_close", expiry_fill_offset_pct=2.0)
    sells = [t for t in e.trades if t.side == "sell"]
    assert len(sells) == 1 and abs(sells[0].price - 110 * 1.02) < 1e-9
    assert "보유기간" in sells[0].reason


def test_expiry_fill_missed_falls_back_to_close(monkeypatch):
    # +5% 지정가(115.5)는 만기일 고가 113 미도달 → 종가(112) 폴백 — 반드시 청산
    e = run(monkeypatch, max_hold_days=2,
            expiry_fill_type="prev_close", expiry_fill_offset_pct=5.0)
    sells = [t for t in e.trades if t.side == "sell"]
    assert len(sells) == 1 and abs(sells[0].price - 112.0) < 1e-9


def test_expiry_default_unchanged(monkeypatch):
    base = run(monkeypatch, max_hold_days=2)
    new = run(monkeypatch, max_hold_days=2, expiry_fill_type="close", expiry_fill_offset_pct=0.0)
    assert [(t.date, t.side, t.price) for t in base.trades] \
        == [(t.date, t.side, t.price) for t in new.trades]
