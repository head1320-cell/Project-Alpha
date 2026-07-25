"""precompute_signals 종목별 예외 격리 — 실데이터 성능 회귀 방지.

배경: 실 KOSPI200 등 200종목 규모 백테스트에서 "주문·체결 시뮬레이션" 단계가 수분~수십분
멈춘 것처럼 보이는 현상이 보고됨. 원인 확정: precompute_signals()가 전 종목 루프를 단일
try/except로 감싸고 있어, 실데이터 특성상 흔한 종목 1개의 평가 예외(펀더멘털 결측·상장초기
이력부족 등)가 **전체 종목**의 _sig를 비워 나머지 199종목까지 O(종목수×기간)의 비싼 per-bar
폴백(_generate_signal_as_of)으로 떨어뜨렸다. 실측(로컬 벤치, 150종목×700거래일):
정상 37.2s → 종목 1개만 예외 발생 시 200s+(미완료, 5배+ 슬로다운). 수정: 종목별 try/except로
격리 — 문제 종목 1개만 그 종목 한정으로 폴백, 나머지는 벡터화 유지.
"""
import numpy as np
import pandas as pd
import pytest

from src.kis_strategies import condition_strategy as cs

IDX = pd.bdate_range("2024-01-02", periods=120)


def _df(seed=1):
    rng = np.random.RandomState(seed)
    close = pd.Series(1000 + np.cumsum(rng.normal(1, 8, len(IDX))), index=IDX).clip(lower=50)
    return pd.DataFrame({"open": close * 0.998, "high": close * 1.01, "low": close * 0.99,
                        "close": close, "volume": rng.randint(1000, 9000, len(IDX)).astype(float)}, index=IDX)


BUY = {"factor_token": "{종가}", "function_id": "pct", "params": {"n": "3"}, "op": "gte", "rhs": 0.1}
SELL = {"factor_token": "{종가}", "function_id": "pct", "params": {"n": "3"}, "op": "lte", "rhs": -0.1}


def test_one_bad_ticker_does_not_disable_vectorization_for_others(monkeypatch):
    """종목 1개의 _precompute_ticker 예외가 다른 종목의 벡터화를 무효화하면 안 된다."""
    omap = {f"{100000+i:06d}": _df(seed=i) for i in range(6)}
    bad_tk = "100003"

    orig = cs.ConditionStrategy._precompute_ticker

    def boom_for_one(self, tk, df):
        if tk == bad_tk:
            raise ValueError("simulated real-world data quirk")
        return orig(self, tk, df)
    monkeypatch.setattr(cs.ConditionStrategy, "_precompute_ticker", boom_for_one)

    s = cs.ConditionStrategy(buy_conditions=[BUY], sell_conditions=[SELL])
    s.prepare_panel(omap)
    s.precompute_signals(omap)

    # 문제 종목만 _sig에서 빠짐(개별 폴백 대상) — 나머지 5종목은 정상 벡터화 유지
    assert bad_tk not in s._sig
    good_tickers = [tk for tk in omap if tk != bad_tk]
    assert set(good_tickers).issubset(s._sig.keys())
    for tk in good_tickers:
        assert isinstance(s._sig[tk], pd.Series) and len(s._sig[tk]) == len(omap[tk])


def test_precompute_signals_no_exceptions_all_vectorized():
    """정상 데이터에서는 회귀 없이 전 종목이 벡터화된다(기존 동작 불변)."""
    omap = {f"{200000+i:06d}": _df(seed=i + 50) for i in range(5)}
    s = cs.ConditionStrategy(buy_conditions=[BUY], sell_conditions=[SELL])
    s.prepare_panel(omap)
    s.precompute_signals(omap)
    assert set(s._sig.keys()) == set(omap.keys())


def test_empty_conditions_leaves_sig_empty_by_design():
    """조건이 비어있으면 _sig는 의도적으로 빈 채(엔진이 리스크관리만 담당) — 회귀 아님."""
    omap = {"000001": _df()}
    s = cs.ConditionStrategy()  # 조건 없음
    s.prepare_panel(omap)
    s.precompute_signals(omap)
    assert s._sig == {}


def test_fallback_fundamentals_cached_per_ticker(monkeypatch):
    """per-bar 폴백 경로(generate_signal)의 펀더멘털 조회가 종목당 1회만 실제 스토어를 호출."""
    calls = []

    def fake_load(code):
        calls.append(code)
        return {"roe_pct": 10.0}
    monkeypatch.setattr(cs, "_load_fundamentals", fake_load)

    s = cs.ConditionStrategy(buy_conditions=[BUY], allow_snapshot_fundamentals=True)
    df = _df()
    import src.kis_data_fetcher as fetcher
    monkeypatch.setattr(fetcher, "get_daily_prices", lambda *a, **k: pd.DataFrame({
        "date": [d.strftime("%Y%m%d") for d in df.index], "open": df["open"].values,
        "high": df["high"].values, "low": df["low"].values, "close": df["close"].values,
        "volume": df["volume"].values,
    }))
    for _ in range(5):
        s.generate_signal("000009", "000009")
    assert calls == ["000009"]  # 5번 호출했지만 실제 스토어 조회는 1번뿐


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
