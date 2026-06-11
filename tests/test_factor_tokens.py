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
    assert "US국채(10년)" not in UNSUPPORTED_REASONS  # FRED 연동으로 지원 전환
    assert "연기금순매수량" in UNSUPPORTED_REASONS    # KIS 3주체 한계 명시


# ─── ③ 펀더멘털 별칭 (카탈로그 표기 → fundamentals_store id) ─────────────────
def test_fundamental_aliases_map_to_real_store_ids():
    """별칭이 가리키는 id가 전부 실재하는 스토어 팩터인지 (오타·드리프트 가드)."""
    from src.data.fundamentals_store import FUNDAMENTAL_FACTORS
    from src.kis_strategies.factor_tokens import FUNDAMENTAL_ALIASES
    valid = {m.id for m in FUNDAMENTAL_FACTORS}
    bad = {k: v for k, v in FUNDAMENTAL_ALIASES.items() if v not in valid}
    assert bad == {}, f"존재하지 않는 스토어 id: {bad}"


def test_fundamental_alias_evaluates():
    f = {"pbr": 1.25, "per": 8.0, "piotroski_f": 7}
    assert cs._fundamental_value("{분기PBR}", f) == pytest.approx(1.25)
    assert cs._fundamental_value("{트레일링PER}", f) == pytest.approx(8.0)
    assert cs._fundamental_value("{F-SCORE}", f) == pytest.approx(7)
    assert cs._fundamental_value("{없는별칭}", f) is None
    ts = token_support()
    assert ts["supported"].get("트레일링PER") == "fundamental"


# ─── ④ 시장(지수) 토큰 ───────────────────────────────────────────────────────
def market_df(n: int = 320, base: float = 2500.0) -> pd.DataFrame:
    idx = pd.date_range("2023-01-02", periods=n, freq="B")
    c = pd.Series(np.linspace(base, base * 1.2, n), index=idx)
    return pd.DataFrame({"open": c, "high": c * 1.005, "low": c * 0.995,
                         "close": c, "volume": [4e5] * n})


def test_market_token_aligns_to_stock_dates(monkeypatch):
    import src.kis_strategies.factor_tokens as ft
    mdf = market_df()
    monkeypatch.setattr(ft, "_market_df", lambda prefix: mdf if prefix == "KOSPI지수" else None)
    s = ft.resolve_market_token(DF, "KOSPI지수_종가")
    assert s is not None and len(s) == len(DF)
    # 같은 날짜는 같은 값 (정렬 정합)
    common = DF.index[5]
    assert float(s.loc[common]) == pytest.approx(float(mdf["close"].loc[common]))
    # _base_series 체인 통합
    assert cs._base_series(DF, "{KOSPI지수_종가}") is not None
    assert ft.resolve_market_token(DF, "DOW지수_종가") is None  # 데이터 없음 → 건너뜀


def test_beta_of_market_itself_is_one(monkeypatch):
    import src.kis_strategies.factor_tokens as ft
    mdf = market_df()
    monkeypatch.setattr(ft, "_market_df", lambda prefix: mdf if prefix == "KOSPI지수" else None)
    stock = mdf.copy()  # 시장과 동일한 종목 → 베타 1
    beta = ft.resolve_market_token(stock, "베타")
    assert float(beta.iloc[-1]) == pytest.approx(1.0, abs=1e-6)


def test_market_mt_signal_and_derived(monkeypatch):
    import src.kis_strategies.factor_tokens as ft
    mdf = market_df()
    monkeypatch.setattr(ft, "_market_df", lambda prefix: mdf)
    mt = ft.resolve_market_token(DF, "DOW_MT_and(3_5_10)")
    assert float(mt.iloc[-1]) == 1.0          # 단조 상승 → 정배열
    macd = ft.resolve_market_token(DF, "DOW_MACD")
    assert macd is not None and np.isfinite(float(macd.iloc[-1]))


# ─── ⑤ ECOS (환율·금리) ──────────────────────────────────────────────────────
def test_parse_ecos_rows():
    from src.kis_strategies.factor_tokens import parse_ecos_rows
    payload = {"StatisticSearch": {"row": [
        {"TIME": "20240104", "DATA_VALUE": "1310.5"},
        {"TIME": "20240105", "DATA_VALUE": "1,315.2".replace(",", "")},
        {"TIME": "bad", "DATA_VALUE": "1"},
        {"TIME": "20240108", "DATA_VALUE": ""},
    ]}}
    s = parse_ecos_rows(payload)
    assert len(s) == 2 and float(s.iloc[-1]) == pytest.approx(1315.2)
    assert parse_ecos_rows({}) is None


def test_macro_token_skips_without_key(monkeypatch):
    import src.kis_strategies.factor_tokens as ft
    monkeypatch.delenv("BOK_API_KEY", raising=False)
    ft._ecos_cache.clear()
    assert ft.resolve_macro_token(DF, "US달러환율") is None     # 키 없음 → 건너뜀
    assert ft.resolve_macro_token(DF, "미등록환율") is None
    ft._ecos_cache.clear()


def test_macro_token_aligns_when_series_available(monkeypatch):
    import src.kis_strategies.factor_tokens as ft
    fx = pd.Series([1300.0, 1310.0], index=pd.DatetimeIndex([DF.index[0], DF.index[1]]))
    monkeypatch.setattr(ft, "_ecos_series", lambda token: fx if token == "US달러환율" else None)
    s = ft.resolve_macro_token(DF, "US달러환율")
    assert float(s.iloc[1]) == pytest.approx(1310.0)
    assert float(s.iloc[-1]) == pytest.approx(1310.0)  # 이후 날짜 ffill


def test_token_min_bars_market_macro():
    assert token_min_bars("베타") == 260
    assert token_min_bars("DOW_MT_and(3_5_10)") == 15
    assert token_min_bars("DOW_MACD") >= 60


# ─── FRED (미국 국채금리) ────────────────────────────────────────────────────
def test_parse_fred_rows():
    from src.kis_strategies.factor_tokens import parse_fred_rows
    payload = {"observations": [
        {"date": "2024-01-04", "value": "4.00"},
        {"date": "2024-01-05", "value": "."},      # FRED 결측 표기 — skip
        {"date": "2024-01-08", "value": "4.05"},
    ]}
    s = parse_fred_rows(payload)
    assert len(s) == 2 and float(s.iloc[-1]) == pytest.approx(4.05)
    assert parse_fred_rows({"observations": []}) is None


def test_fred_token_skips_without_key(monkeypatch):
    import src.kis_strategies.factor_tokens as ft
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    ft._fred_cache.clear()
    assert ft.resolve_macro_token(DF, "US국채(10년)") is None
    ft._fred_cache.clear()


def test_fred_token_aligns_when_available(monkeypatch):
    import src.kis_strategies.factor_tokens as ft
    rate = pd.Series([4.0, 4.05], index=pd.DatetimeIndex([DF.index[0], DF.index[1]]))
    monkeypatch.setattr(ft, "_fred_series", lambda token: rate if token == "US국채(10년)" else None)
    s = ft.resolve_macro_token(DF, "US국채(10년)")
    assert float(s.iloc[1]) == pytest.approx(4.05)
    assert float(s.iloc[-1]) == pytest.approx(4.05)  # 이후 날짜 ffill (금리는 상태값)
