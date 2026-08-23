"""분봉 적재·로더 + 하이브리드 체결 ("신호는 일봉, 체결만 분봉").

① 수집기: mock 합성 수집 → 일파일 저장 → 재개(적재 종목 스킵) → 로더 라운드트립
② 하이브리드: 매매 시간 윈도 내 지정가 미도달 → 미체결 (일봉 모델과 결과가 달라짐)
③ TWAP = 윈도 분봉 종가 평균 / 시장가(open) = 윈도 시작 시가
④ 분봉 없는 날 → 일봉 모델과 동일 (폴백) + 결과 intraday 통계 보고
"""
import numpy as np
import pandas as pd
import pytest

from src.data import minute_bars as mb
from src.kis_backtest_engine import BacktestConfig, BacktestEngine
from src.kis_strategies import condition_strategy  # noqa: F401 — 레지스트리

START = "2024-06-03"

BUY = [{"factor_token": "{종가}", "function_id": "pct", "params": {"n": "1"},
        "op": "gte", "rhs": 5}]


# ─── ① 수집기/로더 ───────────────────────────────────────────────────────────
def test_collect_resume_and_load(tmp_path, monkeypatch):
    monkeypatch.setenv("MINUTE_BARS_DIR", str(tmp_path))
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    mb.clear_cache()
    r1 = mb.collect_day(["005930", "000660"], "20240605")
    assert r1["collected"] == 2 and r1["rows_added"] == 780
    r2 = mb.collect_day(["005930", "035720"], "20240605")   # 재개: 기존 종목 스킵
    assert r2["skipped"] == 1 and r2["collected"] == 1
    df = mb.load_minute_bars("005930", "2024-06-05")
    assert len(df) == 390 and list(df["time"])[0] == "090100"
    assert df["time"].is_monotonic_increasing
    assert mb.load_minute_bars("999999", "2024-06-05") is None
    assert mb.load_minute_bars("005930", "2024-06-04") is None  # 미적재 일자


# ─── 엔진 하이브리드 — 분봉을 주입해 정밀 체결 검증 ──────────────────────────
def daily_df():
    # bar1: +10% 점프(매수 신호). 일봉 저가 99 → 일봉 모델로는 지정가 99 도달
    rows = [(100, 100.5, 99.5, 100), (109, 111, 99.0, 110),
            (110, 111, 109, 110), (110, 111, 109, 110)]
    idx = pd.bdate_range(end=pd.Timestamp(START) - pd.tseries.offsets.BDay(1), periods=60)
    idx = idx.append(pd.bdate_range(start=START, periods=len(rows)))
    base = [(100.0, 100.5, 99.5, 100.0)] * 60 + [tuple(map(float, r)) for r in rows]
    df = pd.DataFrame(base, columns=["open", "high", "low", "close"], index=idx)
    df["volume"] = 50_000.0
    return df


def minute_frame(specs):
    """specs: (HHMMSS, o, h, l, c, v)"""
    return pd.DataFrame([dict(zip(["time", "open", "high", "low", "close", "volume"], s))
                         for s in specs])


def run(monkeypatch, bars_by_date: dict | None, **cfg_kw):
    df = daily_df()
    import src.data.ohlcv_loader as loader
    monkeypatch.setattr(loader, "load_ohlcv_unified", lambda ticker, *a, **k: df.copy())
    monkeypatch.setattr(mb, "load_minute_bars",
                        lambda tk, d: (bars_by_date or {}).get(str(d)))
    cfg = BacktestConfig(
        symbols=["000111"], strategy_name="Condition",
        strategy_params={"buy_conditions": BUY},
        start_date=START, end_date=df.index[-1].strftime("%Y-%m-%d"),
        commission_rate=0.0, slippage_rate=0.0, max_positions=1, **cfg_kw)
    engine = BacktestEngine(cfg)
    result = engine.run()
    assert not result.get("error", False)
    return engine, result


def jump_date():
    return pd.bdate_range(start=START, periods=2)[-1].strftime("%Y-%m-%d")


# ─── ② 윈도 내 지정가 미도달 → 미체결 ────────────────────────────────────────
def test_intraday_limit_not_reached_in_window(monkeypatch):
    # 분봉: 저가 99는 09:05에만 터치, 매수 윈도는 10:00~15:00 → 윈도 내 미도달
    bars = minute_frame([
        ("090500", 109, 109.5, 99.0, 109, 1000),     # 윈도 밖에서만 터치
        ("100000", 109, 110, 105.0, 109, 1000),
        ("120000", 109, 110, 104.0, 108, 1000),
        ("150000", 108, 111, 105.0, 110, 1000),
    ])
    e, _ = run(monkeypatch, {jump_date(): bars},
               buy_fill_type="prev_close", buy_fill_offset_pct=-1.0,
               intraday_fill=True, buy_time_start="1000", buy_time_end="1500")
    assert [t.side for t in e.trades] == []          # 일봉 모델이면 체결됐을 케이스

    # 같은 설정에서 일봉 모델(intraday off)은 체결 — 차이를 어서트
    e2, _ = run(monkeypatch, None,
                buy_fill_type="prev_close", buy_fill_offset_pct=-1.0)
    assert [t.side for t in e2.trades] == ["buy"]


def test_intraday_limit_reached_fills_at_limit(monkeypatch):
    bars = minute_frame([
        ("100000", 109, 110, 105.0, 109, 1000),
        ("130000", 105, 106, 98.5, 100, 1000),       # 윈도 안에서 99 터치
        ("150000", 100, 111, 99.5, 110, 1000),
    ])
    e, _ = run(monkeypatch, {jump_date(): bars},
               buy_fill_type="prev_close", buy_fill_offset_pct=-1.0,
               intraday_fill=True, buy_time_start="1000", buy_time_end="1500")
    buys = [t for t in e.trades if t.side == "buy"]
    assert len(buys) == 1 and abs(buys[0].price - 99.0) < 1e-9


# ─── ③ TWAP·시장가(윈도 시작 시가) ───────────────────────────────────────────
def test_intraday_twap_and_window_open(monkeypatch):
    bars = minute_frame([
        ("100000", 104.0, 105, 103, 104.0, 1000),
        ("120000", 104, 107, 104, 106.0, 1000),
        ("140000", 106, 109, 106, 108.0, 1000),
    ])
    e, _ = run(monkeypatch, {jump_date(): bars},
               buy_fill_type="twap", intraday_fill=True,
               buy_time_start="1000", buy_time_end="1500")
    buys = [t for t in e.trades if t.side == "buy"]
    assert len(buys) == 1 and abs(buys[0].price - np.mean([104, 106, 108])) < 1e-6

    e2, _ = run(monkeypatch, {jump_date(): bars},
                buy_fill_type="open", intraday_fill=True,
                buy_time_start="1000", buy_time_end="1500")
    b2 = [t for t in e2.trades if t.side == "buy"]
    assert len(b2) == 1 and abs(b2[0].price - 104.0) < 1e-9   # 윈도 시작 시가


# ─── ④ 분봉 없음 → 일봉 폴백 + 통계 보고 ─────────────────────────────────────
def test_intraday_fallback_matches_daily_and_reports(monkeypatch):
    base_e, _ = run(monkeypatch, None, buy_fill_type="open")            # 일봉 모델
    fb_e, r = run(monkeypatch, {}, buy_fill_type="open", intraday_fill=True)  # 분봉 전무
    assert [(t.date, t.side, t.price) for t in base_e.trades] \
        == [(t.date, t.side, t.price) for t in fb_e.trades]
    meta = r.get("intraday")
    assert meta and meta["applied"] == 0 and meta["fallback"] >= 1
    assert meta["applied_pct"] == 0.0


def test_intraday_off_no_meta(monkeypatch):
    _, r = run(monkeypatch, None)
    assert r.get("intraday") is None
