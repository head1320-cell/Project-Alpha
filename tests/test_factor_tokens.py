"""factor_tokens — 젠포트 카탈로그 토큰 리졸버 단위 테스트.

기존 kis_indicators와의 정합, 피벗 공식(fill_price 동일), 0/1 시그널,
캔들 꼬리 정확값, 미지원 토큰 None, _eval_condition 통합, 룩백 보정 검증.
"""
import numpy as np
import pandas as pd
import pytest

from src import kis_indicators as ind
from src.kis_strategies import condition_strategy as cs
from src.kis_strategies.factor_tokens import (
    OHLCV_TOKENS,
    UNSUPPORTED_REASONS,
    resolve_ohlcv_token,
    token_min_bars,
    token_support,
)


def make_df(n: int = 320, seed: int = 7) -> pd.DataFrame:
    rng = np.random.RandomState(seed)
    idx = pd.date_range("2023-01-02", periods=n, freq="B")
    close = pd.Series(100 + np.cumsum(rng.normal(0.05, 1.2, n)), index=idx).clip(lower=10)
    spread = close * 0.01
    return pd.DataFrame({
        "open": close - spread / 2, "high": close + spread,
        "low": close - spread, "close": close,
        "volume": rng.randint(50_000, 200_000, n).astype(float),
    }, index=idx)


DF = make_df()


# ─── 레지스트리 규모 + 전 토큰 무크래시 ──────────────────────────────────────
def test_registry_size_and_support_map():
    assert len(OHLCV_TOKENS) >= 60
    ts = token_support()
    assert len(ts["supported"]) >= 80          # base 8 + ohlcv 62 + fundamental 14
    assert "RSI" in ts["supported"] and ts["supported"]["RSI"] == "ohlcv"
    assert "PER" in ts["supported"] and ts["supported"]["PER"] == "fundamental"
    assert "이중바닥" in ts["unsupported"]


def test_all_registered_tokens_resolve_without_crash():
    """전 토큰이 시리즈를 반환하고 마지막 값이 유한(워밍업 충분 시)."""
    bad = []
    for tok in OHLCV_TOKENS:
        s = resolve_ohlcv_token(DF, tok)
        if s is None or len(s) != len(DF) or not np.isfinite(float(s.iloc[-1])):
            bad.append(tok)
    assert bad == [], f"해석 실패 토큰: {bad}"


# ─── 기존 지표와의 정합 (단일 소스 보증) ─────────────────────────────────────
@pytest.mark.parametrize("token,ref", [
    ("RSI", lambda df: ind.calc_rsi(df, 14)),
    ("CCI", lambda df: ind.calc_cci(df, 20)),
    ("MACD", lambda df: ind.calc_macd(df)),
    ("MACD시그널", lambda df: ind.calc_macd_signal(df)),
    ("볼린저밴드_상단값", lambda df: ind.calc_bb_upper(df, 20)),
    ("이격도", lambda df: ind.calc_disparity(df, 20)),
    ("DMI(ADX)", lambda df: ind.calc_adx(df, 14)),
])
def test_matches_kis_indicators(token, ref):
    got = resolve_ohlcv_token(DF, token)
    assert float(got.iloc[-1]) == pytest.approx(float(ref(DF).iloc[-1]), rel=1e-9)


def test_pivot_matches_fill_price_formula():
    """피벗_기준선 = 전일 (H+L+C)/3 — fill_price.py와 동일 공식."""
    s = resolve_ohlcv_token(DF, "피벗_기준선")
    h, low, c = DF["high"].iloc[-2], DF["low"].iloc[-2], DF["close"].iloc[-2]
    assert float(s.iloc[-1]) == pytest.approx((h + low + c) / 3.0)
    r1 = resolve_ohlcv_token(DF, "피벗_1차저항")
    assert float(r1.iloc[-1]) == pytest.approx(2 * (h + low + c) / 3.0 - low)


# ─── 0/1 시그널 + 정확값 ─────────────────────────────────────────────────────
def test_binary_signals_on_monotonic_series():
    n = 300
    idx = pd.date_range("2023-01-02", periods=n, freq="B")
    c = pd.Series(np.linspace(100, 200, n), index=idx)
    df = pd.DataFrame({"open": c, "high": c, "low": c, "close": c, "volume": [1e5] * n})
    assert float(resolve_ohlcv_token(df, "신고가갱신(52주)").iloc[-1]) == 1.0
    assert float(resolve_ohlcv_token(df, "신저가갱신(52주)").iloc[-1]) == 0.0
    assert float(resolve_ohlcv_token(df, "골든크로스(20일/60일)").iloc[-1]) == 1.0


def test_candle_tail_ratios_exact():
    """윗꼬리 2/(고-저), 아래꼬리: open=10,close=14,high=16,low=9 → 위 2/7, 아래 1/7."""
    idx = pd.date_range("2024-01-02", periods=1)
    df = pd.DataFrame({"open": [10.0], "high": [16.0], "low": [9.0],
                       "close": [14.0], "volume": [1.0]}, index=idx)
    assert float(resolve_ohlcv_token(df, "윗꼬리비율").iloc[-1]) == pytest.approx(2 / 7 * 100)
    assert float(resolve_ohlcv_token(df, "아래꼬리비율").iloc[-1]) == pytest.approx(1 / 7 * 100)
    assert float(resolve_ohlcv_token(df, "종가시초가대비율").iloc[-1]) == pytest.approx(40.0)


# ─── 미지원/실패 → None (건너뜀 정책) ────────────────────────────────────────
def test_unsupported_and_broken_return_none():
    assert resolve_ohlcv_token(DF, "이중바닥") is None          # 패턴 — 미등록
    assert resolve_ohlcv_token(DF, "{뉴지스코어}") is None
    no_high = DF.drop(columns=["high"])
    assert resolve_ohlcv_token(no_high, "CCI") is None          # 계산 실패 → None


# ─── _eval_condition 통합 + 룩백 보정 ────────────────────────────────────────
def test_eval_condition_with_extended_tokens():
    cond = {"factor_token": "{RSI}", "function_id": "base", "params": {},
            "op": "between", "rhs": 0, "rhs2": 100}
    assert cs._eval_condition(DF, cond) is True
    dead = {"factor_token": "{모멘텀점수순위}", "function_id": "base", "params": {},
            "op": "gte", "rhs": 0}
    assert cs._eval_condition(DF, dead) is None                 # 뉴지 점수 — 무시


def test_required_days_covers_token_lookback():
    s52 = cs.ConditionStrategy(buy_conditions=[
        {"factor_token": "{신고가갱신(52주)}", "function_id": "base", "params": {},
         "op": "eq", "rhs": 1}])
    assert s52.required_days >= 260
    s_rsi = cs.ConditionStrategy(buy_conditions=[
        {"factor_token": "{RSI}", "function_id": "base", "params": {}, "op": "lte", "rhs": 30}])
    assert s_rsi.required_days >= 40
    assert token_min_bars("{신고가갱신(52주)}") == 260
    assert token_min_bars("미등록토큰") == 0


def test_unsupported_reasons_are_honest():
    assert "후행스팬" in UNSUPPORTED_REASONS      # look-ahead 사유 명시
    assert "대체" in UNSUPPORTED_REASONS["후행스팬"]
