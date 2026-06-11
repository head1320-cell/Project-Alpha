"""젠포트 팩터 토큰 → 시리즈 리졸버 (조건식 평가 확장)
==========================================================================
카탈로그(genportFactors.json 344개) 중 종목 자신의 OHLCV에서 파생 가능한
토큰을 실제 시리즈로 해석한다. kis_indicators 기존 함수를 최대 재사용.

  · OHLCV_TOKENS: 토큰명 → df(open/high/low/close/volume) → Series
  · UNSUPPORTED_REASONS: 평가 불가 토큰의 사유 (UI 배지·정직성)
  · token_support(): 픽커/엔드포인트용 지원 맵 (백엔드가 단일 진실 공급원)

설계 노트:
  · 카탈로그의 카테고리 경계가 거칠어(가이드 PDF 병합셀) RSI·볼린저 등이
    '뉴지지표'에 섞여 있음 → 지원 판정은 카테고리가 아닌 토큰 단위.
  · 기간 파라미터가 이름에 없는 토큰은 통상 기본값(괄호 주석) 사용.
  · 후행스팬·패턴류(이중바닥 등)·뉴지 점수류는 정직하게 미지원 표기.
  · 시장 시계열(지수/환율/금리)·수급은 별도 단계(market/macro provider).
"""

from __future__ import annotations

import pandas as pd

from src import kis_indicators as ind


# ── 공통 헬퍼 ────────────────────────────────────────────────────────────────
def _ohlcv(df: pd.DataFrame):
    o = df["open"].astype(float)
    h = df["high"].astype(float)
    low = df["low"].astype(float)
    c = df["close"].astype(float)
    v = df["volume"].astype(float)
    return o, h, low, c, v


def _true_range(df: pd.DataFrame) -> pd.Series:
    _, h, low, c, _ = _ohlcv(df)
    prev_c = c.shift(1)
    return pd.concat([h - low, (h - prev_c).abs(), (low - prev_c).abs()], axis=1).max(axis=1)


def _dm(df: pd.DataFrame):
    """+DM/-DM (calc_adx와 동일 로직)."""
    _, h, low, _, _ = _ohlcv(df)
    up, down = h.diff(), -low.diff()
    plus_dm = ((up > down) & (up > 0)) * up
    minus_dm = ((down > up) & (down > 0)) * down
    return plus_dm.fillna(0.0), minus_dm.fillna(0.0)


def _di(df: pd.DataFrame, period: int = 14):
    plus_dm, minus_dm = _dm(df)
    atr = ind.calc_atr(df, period)
    plus_di = 100 * plus_dm.ewm(span=period, adjust=False).mean() / atr
    minus_di = 100 * minus_dm.ewm(span=period, adjust=False).mean() / atr
    return plus_di, minus_di


def _force_index(df: pd.DataFrame, span: int) -> pd.Series:
    _, _, _, c, v = _ohlcv(df)
    return (c.diff() * v).ewm(span=span, adjust=False).mean()


def _ad_line(df: pd.DataFrame) -> pd.Series:
    _, h, low, c, v = _ohlcv(df)
    rng = (h - low).replace(0, pd.NA)
    mfm = (((c - low) - (h - c)) / rng).fillna(0.0)
    return (mfm * v).cumsum()


def _pivot(df: pd.DataFrame, kind: str) -> pd.Series:
    """전일 HLC 피벗 (fill_price.py와 동일 공식)."""
    _, h, low, c, _ = _ohlcv(df)
    ph, pl, pc = h.shift(1), low.shift(1), c.shift(1)
    p = (ph + pl + pc) / 3.0
    if kind == "P":
        return p
    if kind == "R1":
        return 2 * p - pl
    if kind == "S1":
        return 2 * p - ph
    if kind == "R2":
        return p + (ph - pl)
    return p - (ph - pl)  # S2


def _psych_line(df: pd.DataFrame, period: int = 12) -> pd.Series:
    _, _, _, c, _ = _ohlcv(df)
    return (c.diff() > 0).astype(float).rolling(period).mean() * 100.0


def _vwma(df: pd.DataFrame, period: int = 20) -> pd.Series:
    _, _, _, c, v = _ohlcv(df)
    return (c * v).rolling(period).sum() / v.rolling(period).sum()


def _keltner_mid(df: pd.DataFrame, period: int = 20) -> pd.Series:
    return ind.calc_ema(df, period)


def _keltner(df: pd.DataFrame, which: str) -> pd.Series:
    mid = _keltner_mid(df)
    band = 2.0 * ind.calc_atr(df, 10)
    upper, lower = mid + band, mid - band
    if which == "U":
        return upper
    if which == "L":
        return lower
    if which == "W":
        return upper - lower
    _, _, _, c, _ = _ohlcv(df)
    return (c - lower) / (upper - lower).replace(0, pd.NA) * 100.0  # 위치(%)


def _donchian(df: pd.DataFrame, which: str, period: int = 20) -> pd.Series:
    u = ind.calc_donchian_upper(df, period)
    low = ind.calc_donchian_lower(df, period)
    if which == "U":
        return u
    if which == "L":
        return low
    if which == "M":
        return (u + low) / 2.0
    if which == "W":
        return u - low
    _, _, _, c, _ = _ohlcv(df)
    return (c - low) / (u - low).replace(0, pd.NA) * 100.0


def _downside_vol(df: pd.DataFrame, period: int = 20) -> pd.Series:
    _, _, _, c, _ = _ohlcv(df)
    r = c.pct_change()
    return r.where(r < 0, 0.0).rolling(period).std() * 100.0


def _ichimoku(df: pd.DataFrame, which: str) -> pd.Series:
    """일목균형표 — 선행스팬은 26일 전 산출값을 당일 위치로(shift +26 → look-ahead 없음)."""
    _, h, low, c, _ = _ohlcv(df)

    def mid(n):
        return (h.rolling(n).max() + low.rolling(n).min()) / 2.0

    conv, base = mid(9), mid(26)
    if which == "conv":
        return conv
    if which == "base":
        return base
    if which == "span1":
        return ((conv + base) / 2.0).shift(26)
    return mid(52).shift(26)  # span2


def _stoch_slow_d(df: pd.DataFrame) -> pd.Series:
    return ind.calc_stochastic_d(df).rolling(3).mean()


def _trix(df: pd.DataFrame, period: int = 15) -> pd.Series:
    _, _, _, c, _ = _ohlcv(df)
    e3 = c.ewm(span=period, adjust=False).mean().ewm(span=period, adjust=False).mean() \
        .ewm(span=period, adjust=False).mean()
    return e3.pct_change() * 100.0


def _ratio_pct(num: pd.Series, den: pd.Series) -> pd.Series:
    return (num / den.replace(0, pd.NA) - 1.0) * 100.0


def _close(df):
    return df["close"].astype(float)


# ── 토큰 레지스트리: 종목 OHLCV 파생 (이름 = 카탈로그 표기 그대로) ───────────
OHLCV_TOKENS: dict = {
    # 기술지표 — DMI/추세
    "DMI(+DI)": lambda df: _di(df)[0],
    "DMI(-DI)": lambda df: _di(df)[1],
    "DMI(+DI)DMI(-DI)대비값": lambda df: _di(df)[0] - _di(df)[1],
    "DMI(ADX)": lambda df: ind.calc_adx(df, 14),
    # 거래량 계열
    "OBV": ind.calc_obv,
    "MFI": lambda df: ind.calc_mfi(df, 14),
    "AD_LINE": _ad_line,
    "FORCE_INDEX(단기)": lambda df: _force_index(df, 2),
    "FORCE_INDEX(장기)": lambda df: _force_index(df, 13),
    "20일평균거래량대비거래량": lambda df: df["volume"].astype(float)
        / ind.calc_volume_ma(df, 20).replace(0, pd.NA) * 100.0,
    # 오실레이터
    "CCI": lambda df: ind.calc_cci(df, 20),
    "RSI": lambda df: ind.calc_rsi(df, 14),
    "스토캐스틱(K)": lambda df: ind.calc_stochastic_k(df, 14),
    "스토캐스틱(D)": lambda df: ind.calc_stochastic_d(df),
    "스토캐스틱(slowD)": _stoch_slow_d,
    "TRIX": _trix,
    "TRIX시그널": lambda df: _trix(df).ewm(span=9, adjust=False).mean(),
    "심리선": _psych_line,
    # MACD
    "MACD": lambda df: ind.calc_macd(df),
    "MACD시그널": lambda df: ind.calc_macd_signal(df),
    "MACD오실레이터": lambda df: ind.calc_macd_histogram(df),
    # 밴드/채널
    "볼린저밴드_상단값": lambda df: ind.calc_bb_upper(df, 20),
    "볼린저밴드_하단값": lambda df: ind.calc_bb_lower(df, 20),
    "볼린저밴드_밴드폭": lambda df: ind.calc_bb_width(df, 20),
    "켈트너_중앙값": _keltner_mid,
    "켈트너_상단값": lambda df: _keltner(df, "U"),
    "켈트너_하단값": lambda df: _keltner(df, "L"),
    "켈트너_밴드폭": lambda df: _keltner(df, "W"),
    "켈트너_위치": lambda df: _keltner(df, "P"),
    "돈치안_상단값": lambda df: _donchian(df, "U"),
    "돈치안_하단값": lambda df: _donchian(df, "L"),
    "돈치안_중앙값": lambda df: _donchian(df, "M"),
    "돈치안_밴드폭": lambda df: _donchian(df, "W"),
    "돈치안_위치": lambda df: _donchian(df, "P"),
    # 변동성/레인지
    "TrueRange": _true_range,
    "하향변동성": _downside_vol,
    "주가중심선": lambda df: (df["high"].astype(float) + df["low"].astype(float)
                              + df["close"].astype(float)) / 3.0,
    # 피벗 (전일 HLC)
    "피벗_기준선": lambda df: _pivot(df, "P"),
    "피벗_1차저항": lambda df: _pivot(df, "R1"),
    "피벗_2차저항": lambda df: _pivot(df, "R2"),
    "피벗_1차지지": lambda df: _pivot(df, "S1"),
    "피벗_2차지지": lambda df: _pivot(df, "S2"),
    # 일목균형표
    "일목균형표전환선": lambda df: _ichimoku(df, "conv"),
    "일목균형표기준선": lambda df: _ichimoku(df, "base"),
    "일목균형표선행스팬1": lambda df: _ichimoku(df, "span1"),
    "일목균형표선행스팬2": lambda df: _ichimoku(df, "span2"),
    "VWMA": _vwma,
    # 가격 — 수익률/이격/꼬리
    "이격도": lambda df: ind.calc_disparity(df, 20),
    "종가시초가대비율": lambda df: _ratio_pct(_close(df), df["open"].astype(float)),
    "일별주가상승률": lambda df: _close(df).pct_change() * 100.0,
    "주간주가상승률1주전": lambda df: _close(df).pct_change(5) * 100.0,
    "월간주가상승률1개월전": lambda df: _close(df).pct_change(21) * 100.0,
    "골든크로스(20일/60일)": lambda df: (ind.calc_ma(df, 20) > ind.calc_ma(df, 60)).astype(float),
    "주가이동평균변화율": lambda df: ind.calc_ma(df, 20).pct_change() * 100.0,
    "신고가갱신(52주)": lambda df: (_close(df) >= _close(df).rolling(252).max()).astype(float),
    "신저가갱신(52주)": lambda df: (_close(df) <= _close(df).rolling(252).min()).astype(float),
    "당일고가대비저가변동비율": lambda df: _ratio_pct(df["high"].astype(float), df["low"].astype(float)),
    "최저가대비상승비율": lambda df: _ratio_pct(_close(df), _close(df).rolling(252).min()),
    "최고가대비하락비율": lambda df: -_ratio_pct(_close(df), _close(df).rolling(252).max()),
    "윗꼬리비율": lambda df: (df["high"].astype(float)
                              - pd.concat([df["open"], df["close"]], axis=1).astype(float).max(axis=1))
        / (df["high"].astype(float) - df["low"].astype(float)).replace(0, pd.NA) * 100.0,
    "아래꼬리비율": lambda df: (pd.concat([df["open"], df["close"]], axis=1).astype(float).min(axis=1)
                                - df["low"].astype(float))
        / (df["high"].astype(float) - df["low"].astype(float)).replace(0, pd.NA) * 100.0,
    "일별주가상승율250일변동성": lambda df: _close(df).pct_change().rolling(250).std() * 100.0,
}

# 기본 가격/거래량 토큰 (condition_strategy._PRICE_COL — 참조용 동기화 목록)
BASE_TOKENS = ["시가", "고가", "저가", "종가", "현재가", "주가", "거래량", "거래대금"]

# ── 펀더멘털 별칭: 카탈로그 표기 → fundamentals_store 팩터 id ────────────────
# 의미가 정확히 일치하는 것만 매핑(스냅샷·옵트인 — 펀더멘털 토글 필요).
# 주의: 분기/T-(트레일링) 표기는 스토어의 "최신 스냅샷" 기준 근사다.
# 단위가 다르거나(시가총액(원)) 원천이 없는 항목(분기EPS·NCAV 금액 등)은 정직하게 제외.
FUNDAMENTAL_ALIASES: dict[str, str] = {
    # 밸류에이션
    "주가수익률(PER)": "per", "트레일링PER": "per", "T-PER_종가": "per",
    "분기PBR": "pbr", "트레일링PBR": "pbr", "T-PBR_종가": "pbr",
    "분기PSR": "psr", "트레일링PSR": "psr", "T-PSR_종가": "psr",
    "T-PCR": "pcr", "분기EV/EBITDA": "ev_ebitda", "분기BPS": "bps",
    # 수익성/품질
    "분기ROE": "roe", "T-ROE": "roe", "분기ROA": "roa", "분기ROIC": "roic",
    "T-GP/A": "gp_to_assets", "F-SCORE": "piotroski_f",
    "분기매출총이익률": "gross_margin", "분기자산회전율": "asset_turnover",
    # 성장
    "분기매출성장률(QOQ)": "revenue_qoq", "분기매출액성장률(QOQ)": "revenue_qoq",
    "분기매출성장률(YOY)": "revenue_growth_yoy", "분기매출액성장률(YOY)": "revenue_growth_yoy",
    "분기영업이익성장률(YOY)": "op_growth_yoy", "분기EPS성장률(YOY)": "eps_growth_yoy",
    # 배당/안전성
    "배당수익률": "dividend_yield", "연간배당성향": "payout_ratio",
    "분기부채비율": "debt_to_equity", "분기유동비율": "current_ratio",
}


# ── 미지원 토큰: 사유 (UI 배지 — 정직성) ────────────────────────────────────
REASON_NEWZY = "뉴지스탁 독점 점수 — 원천 비공개라 재현 불가"
REASON_PATTERN = "차트 패턴 인식 — 미지원"
REASON_AMBIGUOUS = "정의 모호(파라미터 불명) — 미지원"
REASON_LOOKAHEAD = "차트 표시용(미래 위치) — 변화율_기간(26)으로 대체 권장"
REASON_MARKET = "시장 시계열(지수) — 연동 단계 예정"
REASON_MACRO = "환율·금리(ECOS/FRED) — 연동 단계 예정"
REASON_FLOW = "투자자별 수급 — KIS 적재 단계 예정"
REASON_CONSENSUS = "컨센서스/유료 데이터 — 미지원"

REASON_FLOW_DETAIL = "KIS 종목별 수급은 개인/외국인/기관계만 제공 — 세부 주체 미지원"
REASON_SHORT = "공매도·신용 데이터 미연동"

UNSUPPORTED_REASONS: dict[str, str] = {
    "후행스팬": REASON_LOOKAHEAD,
    "VPCI": REASON_AMBIGUOUS,
    "상승추세": REASON_PATTERN, "하락추세": REASON_PATTERN,
    "이중바닥": REASON_PATTERN, "이중천정": REASON_PATTERN,
    "역망치": REASON_PATTERN,
    "엔벨위치": REASON_AMBIGUOUS, "볼린저밴드": REASON_AMBIGUOUS,
    "피보나치상승율": REASON_AMBIGUOUS, "피보나치하락율": REASON_AMBIGUOUS,
    # 수급 세부 주체 — KIS 종목별 TR(FHKST01010900)은 개인/외국인/기관계 3주체만
    **{f"{w}순매수{u}": REASON_FLOW_DETAIL
       for w in ("연기금", "투신", "사모펀드", "기타법인") for u in ("량", "금액")},
    **{t: REASON_SHORT for t in ("공매도거래량", "공매도거래대금", "공매도평균가",
                                  "공매도비중", "공매도비중20일평균대비변화량", "신용잔고율")},
}


# 토큰별 최소 필요 봉수 — required_days 산정용 (없으면 기본 30).
# 부족하면 롤링 결과가 전부 NaN → 조건이 조용히 무시되므로 워밍업을 충분히 잡는다.
TOKEN_MIN_BARS: dict[str, int] = {
    **{t: 260 for t in ("신고가갱신(52주)", "신저가갱신(52주)", "최저가대비상승비율",
                         "최고가대비하락비율", "일별주가상승율250일변동성")},
    **{t: 90 for t in ("일목균형표선행스팬1", "일목균형표선행스팬2",
                        "일목균형표기준선", "골든크로스(20일/60일)")},
    **{t: 60 for t in ("MACD", "MACD시그널", "MACD오실레이터", "TRIX", "TRIX시그널")},
}


def token_min_bars(token: str) -> int:
    name = (token or "").strip().strip("{}").strip()
    if name in TOKEN_MIN_BARS:
        return TOKEN_MIN_BARS[name]
    if name == "베타":
        return 260  # 252일 롤링 cov/var
    if "_MT_" in name:
        return 15
    for base, n in TOKEN_MIN_BARS.items():  # 지수 파생: DOW_MACD → MACD 룩백
        if name.endswith("_" + base):
            return n
    return 30 if name in OHLCV_TOKENS else 0


def resolve_ohlcv_token(df: pd.DataFrame, token: str) -> pd.Series | None:
    """카탈로그 토큰 → 종목 OHLCV 파생 시리즈. 미지원·계산 실패 시 None(건너뜀)."""
    fn = OHLCV_TOKENS.get((token or "").strip())
    if fn is None:
        return None
    try:
        s = fn(df)
        return s.astype(float) if s is not None else None
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# 시장(지수) 시계열 토큰 — 모든 종목에 동일, 종목 df 날짜에 ffill 정렬
#   국내(KOSPI/KOSDAQ): ohlcv_loader (KRX 백필 후 실데이터, mock 모드는 합성)
#   해외(DOW/NASDAQ/니케이/상해/VIX): yfinance (키 불필요·네트워크 필요, 실패 시 건너뜀)
# ═══════════════════════════════════════════════════════════════════════════════

# 카탈로그 프리픽스 → (ohlcv_loader 심볼, yfinance 심볼)
MARKET_SYMBOLS: dict[str, tuple[str | None, str | None]] = {
    "KOSPI지수": ("KOSPI", None),
    "KOSDAQ지수": ("KOSDAQ", None),
    "DOW지수": (None, "^DJI"),
    "NASDAQ지수": (None, "^IXIC"),
    "니케이225지수": (None, "^N225"),
    "상해종합지수": (None, "000001.SS"),
    "VIX": (None, "^VIX"),
}
# 파생 토큰 프리픽스(DOW_MACD 등) → MARKET_SYMBOLS 키
_DERIVED_PREFIX = {"DOW": "DOW지수", "NASDAQ": "NASDAQ지수",
                   "KOSPI": "KOSPI지수", "KOSDAQ": "KOSDAQ지수"}
_MARKET_FIELDS = {"시가": "open", "고가": "high", "저가": "low", "종가": "close", "거래량": "volume"}
# 지수에 적용 가능한 파생 지표 (OHLCV_TOKENS 재사용)
_MARKET_DERIVED = ("볼린저밴드_상단값", "볼린저밴드_하단값", "볼린저밴드_밴드폭",
                   "MACD", "MACD시그널", "MACD오실레이터",
                   "스토캐스틱(K)", "스토캐스틱(D)", "스토캐스틱(slowD)")

_market_cache: dict[str, pd.DataFrame | None] = {}


def _market_df(prefix: str) -> pd.DataFrame | None:
    """지수 OHLCV 로드(캐시). 실패 시 None 캐시(반복 시도 방지)."""
    if prefix in _market_cache:
        return _market_cache[prefix]
    loader_sym, yf_sym = MARKET_SYMBOLS.get(prefix, (None, None))
    df = None
    try:
        if loader_sym:
            from datetime import datetime

            from src.data.ohlcv_loader import load_ohlcv_unified
            df = load_ohlcv_unified(loader_sym, "2005-01-01",
                                    datetime.now().strftime("%Y-%m-%d"), prefer="auto")
        elif yf_sym:
            import yfinance as yf
            raw = yf.download(yf_sym, start="2005-01-01", progress=False, auto_adjust=False)
            if raw is not None and not raw.empty:
                if isinstance(raw.columns, pd.MultiIndex):
                    raw.columns = raw.columns.get_level_values(0)
                df = raw.rename(columns={"Open": "open", "High": "high", "Low": "low",
                                          "Close": "close", "Volume": "volume"})
                df = df[["open", "high", "low", "close", "volume"]]
    except Exception:
        df = None
    if df is not None and df.empty:
        df = None
    _market_cache[prefix] = df
    return df


def _align(s: pd.Series, df: pd.DataFrame) -> pd.Series:
    """시장 시계열을 종목 df 날짜에 정렬 — 당일 없으면 직전값(ffill, look-ahead 없음)."""
    return s.reindex(pd.DatetimeIndex(df.index), method="ffill")


def _mt_signal(mdf: pd.DataFrame, mode: str) -> pd.Series:
    """MT(3_5_10): 종가>MA3>MA5>MA10 정배열 — and=전부 / or=하나라도 (0/1)."""
    c = mdf["close"].astype(float)
    ma3, ma5, ma10 = c.rolling(3).mean(), c.rolling(5).mean(), c.rolling(10).mean()
    conds = [(c > ma3), (ma3 > ma5), (ma5 > ma10)]
    out = conds[0] & conds[1] & conds[2] if mode == "and" else conds[0] | conds[1] | conds[2]
    return out.astype(float)


def resolve_market_token(df: pd.DataFrame, token: str) -> pd.Series | None:
    """시장(지수) 토큰 해석 — 데이터 없으면 None(건너뜀)."""
    import re
    name = (token or "").strip()

    # 베타: 종목 일수익률 vs KOSPI 일수익률, 252일 롤링 cov/var
    if name == "베타":
        mdf = _market_df("KOSPI지수")
        if mdf is None:
            return None
        mret = _align(mdf["close"].astype(float), df).pct_change()
        sret = df["close"].astype(float).pct_change()
        var = mret.rolling(252).var()
        return (sret.rolling(252).cov(mret) / var.replace(0, pd.NA)).astype(float)

    # MT 시그널: DOW_MT_or(3_5_10) 등
    m = re.match(r"^(DOW|NASDAQ|KOSPI|KOSDAQ)_MT_(or|and)\(3_5_10\)$", name)
    if m:
        mdf = _market_df(_DERIVED_PREFIX[m.group(1)])
        return _align(_mt_signal(mdf, m.group(2)), df) if mdf is not None else None

    # 프리픽스_필드 / 프리픽스_파생지표
    for prefix in MARKET_SYMBOLS:
        if not name.startswith(prefix + "_"):
            continue
        field = name[len(prefix) + 1:]
        mdf = _market_df(prefix)
        if mdf is None:
            return None
        col = _MARKET_FIELDS.get(field)
        if col is not None:
            return _align(mdf[col].astype(float), df)
        if field == "거래대금":
            return _align(mdf["close"].astype(float) * mdf["volume"].astype(float), df)
        return None
    # 지수 파생: DOW_볼린저밴드_상단값 / DOW_MACD 등 (OHLCV_TOKENS를 지수 df에 적용)
    m = re.match(r"^(DOW|NASDAQ|KOSPI|KOSDAQ)_(.+)$", name)
    if m and m.group(2) in _MARKET_DERIVED:
        mdf = _market_df(_DERIVED_PREFIX[m.group(1)])
        if mdf is None:
            return None
        s = resolve_ohlcv_token(mdf, m.group(2))
        return _align(s, df) if s is not None else None
    return None


def market_tokens() -> list[str]:
    """지원하는 시장 토큰 전체 목록 (카탈로그 존재분 기준)."""
    out = ["베타"]
    for prefix in MARKET_SYMBOLS:
        fields = ["시가", "고가", "저가", "종가"] + (["거래량", "거래대금"] if prefix == "DOW지수" else [])
        out += [f"{prefix}_{f}" for f in fields]
    for p in ("DOW", "NASDAQ"):
        out += [f"{p}_MT_or(3_5_10)", f"{p}_MT_and(3_5_10)"]
    out += [f"DOW_{d}" for d in _MARKET_DERIVED]
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# 매크로(ECOS) 토큰 — 환율·국고채 금리. BOK_API_KEY 필요(무료), 일 주기.
#   통계/항목 코드는 ECOS 코드표 기준 상수 — 실계정 첫 호출은 verify_connection
#   【6】 sanity(값 범위)로 정합 확인. 코드 불일치 시 빈 응답 → 토큰 건너뜀(안전).
# ═══════════════════════════════════════════════════════════════════════════════

ECOS_BASE_URL = "https://ecos.bok.or.kr/api"

# 토큰 → (통계표코드, 항목코드) — 731Y001 환율(매매기준율), 817Y002 시장금리(일별)
ECOS_TOKENS: dict[str, tuple[str, str]] = {
    "US달러환율": ("731Y001", "0000001"),
    "엔환율": ("731Y001", "0000002"),      # 원/100엔
    "국고채(1년)": ("817Y002", "010190000"),
    "국고채(2년)": ("817Y002", "010195000"),
    "국고채(3년)": ("817Y002", "010200000"),
    "국고채(5년)": ("817Y002", "010210000"),
    "국고채(10년)": ("817Y002", "010210001"),
    "국고채(20년)": ("817Y002", "010220000"),
    "국고채(30년)": ("817Y002", "010230000"),
}

_ecos_cache: dict[str, pd.Series | None] = {}


def parse_ecos_rows(payload: dict) -> pd.Series | None:
    """ECOS StatisticSearch 응답 → 날짜 인덱스 시리즈 (테스트 가능한 순수 파서)."""
    try:
        rows = (payload or {}).get("StatisticSearch", {}).get("row", []) or []
        dates, vals = [], []
        for r in rows:
            t, v = str(r.get("TIME", "")).strip(), r.get("DATA_VALUE")
            if len(t) != 8 or v in (None, ""):
                continue
            try:
                vals.append(float(v))
                dates.append(pd.Timestamp(f"{t[:4]}-{t[4:6]}-{t[6:]}"))
            except (ValueError, TypeError):
                continue
        if not dates:
            return None
        return pd.Series(vals, index=pd.DatetimeIndex(dates)).sort_index()
    except Exception:
        return None


def _ecos_series(token: str) -> pd.Series | None:
    """ECOS 일별 시계열 (캐시). 키 없음·실패 시 None."""
    import os
    if token in _ecos_cache:
        return _ecos_cache[token]
    key = os.getenv("BOK_API_KEY", "")
    spec = ECOS_TOKENS.get(token)
    s = None
    if key and spec:
        try:
            from datetime import datetime

            import httpx
            stat, item = spec
            end = datetime.now().strftime("%Y%m%d")
            url = (f"{ECOS_BASE_URL}/StatisticSearch/{key}/json/kr/1/50000/"
                   f"{stat}/D/20050101/{end}/{item}")
            r = httpx.get(url, timeout=15)
            s = parse_ecos_rows(r.json())
        except Exception:
            s = None
    _ecos_cache[token] = s
    return s


# ── FRED (미국 국채금리) — FRED_API_KEY 필요(무료, fred.stlouisfed.org) ──────
FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

FRED_TOKENS: dict[str, str] = {f"US국채({n}년)": f"DGS{n}" for n in (1, 2, 3, 5, 7, 10, 20, 30)}

_fred_cache: dict[str, pd.Series | None] = {}


def parse_fred_rows(payload: dict) -> pd.Series | None:
    """FRED observations 응답 → 날짜 인덱스 시리즈 (결측 '.' 제외)."""
    try:
        rows = (payload or {}).get("observations", []) or []
        dates, vals = [], []
        for r in rows:
            v = r.get("value")
            if v in (None, "", "."):
                continue
            try:
                vals.append(float(v))
                dates.append(pd.Timestamp(r.get("date")))
            except (ValueError, TypeError):
                continue
        if not dates:
            return None
        return pd.Series(vals, index=pd.DatetimeIndex(dates)).sort_index()
    except Exception:
        return None


def _fred_series(token: str) -> pd.Series | None:
    """FRED 일별 시계열 (캐시). 키 없음·실패 시 None."""
    import os
    if token in _fred_cache:
        return _fred_cache[token]
    key = os.getenv("FRED_API_KEY", "")
    series_id = FRED_TOKENS.get(token)
    s = None
    if key and series_id:
        try:
            import httpx
            r = httpx.get(FRED_BASE_URL, params={
                "series_id": series_id, "api_key": key, "file_type": "json",
                "observation_start": "2005-01-01",
            }, timeout=15)
            s = parse_fred_rows(r.json())
        except Exception:
            s = None
    _fred_cache[token] = s
    return s


def resolve_macro_token(df: pd.DataFrame, token: str) -> pd.Series | None:
    """환율·금리 토큰 → 종목 날짜 정렬 시리즈. 키 없음·실패 시 None(건너뜀)."""
    name = (token or "").strip()
    if name in ECOS_TOKENS:
        s = _ecos_series(name)
        return _align(s, df) if s is not None else None
    if name in FRED_TOKENS:
        s = _fred_series(name)
        return _align(s, df) if s is not None else None
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# 수급(투자자별) 토큰 — KIS 종목별 투자자 TR을 일별 적재(kis_flows)한 DB에서 조회
#   종목 식별: 엔진이 ohlcv df.attrs["ticker"]에 심어줌 (슬라이스에도 보존됨)
#   주의: KIS TR은 최근 ~30영업일만 제공 → 매일 적재해 누적하는 구조.
#         적재 안 된 날짜는 NaN → 그 봉의 조건은 건너뜀(정직).
# ═══════════════════════════════════════════════════════════════════════════════

FLOW_TOKENS: dict[str, str] = {
    "외국인순매수량": "frgn_qty", "기관순매수량": "orgn_qty", "개인순매수량": "prsn_qty",
    "외국인순매수금액": "frgn_amt", "기관순매수금액": "orgn_amt", "개인순매수금액": "prsn_amt",
}


def resolve_flow_token(df: pd.DataFrame, token: str) -> pd.Series | None:
    """수급 토큰 → 적재된 investor_flows에서 종목 시리즈. 미적재·식별 불가 시 None."""
    name = (token or "").strip()
    field = FLOW_TOKENS.get(name)
    if field is None:
        return None
    ticker = (df.attrs or {}).get("ticker")
    if not ticker:
        return None  # 엔진 외 호출 경로(실시간 등) — 종목 식별 불가 → 건너뜀
    try:
        from src.data.kis_flows import load_flows_series
        s = load_flows_series(str(ticker), field)
    except Exception:
        return None
    if s is None or s.empty:
        return None
    # 수급은 일별 사실값 — ffill 하지 않음(미적재일은 NaN → 해당 봉 건너뜀)
    return s.reindex(pd.DatetimeIndex(df.index))


def token_support() -> dict:
    """픽커/엔드포인트용 지원 맵 — 백엔드가 단일 진실 공급원.

    supported: 토큰 → 그룹("base"|"ohlcv"|"fundamental")
    unsupported: 토큰 → 사유 (명시된 것만 — 나머지 미등록 토큰은 프론트가 기본 사유 표시)
    """
    from src.kis_strategies.condition_strategy import _FUND_TOKENS
    supported: dict[str, str] = {}
    for t in BASE_TOKENS:
        supported[t] = "base"
    for t in OHLCV_TOKENS:
        supported[t] = "ohlcv"
    for t in _FUND_TOKENS:
        supported[t] = "fundamental"  # 옵트인(스냅샷) — 펀더멘털 토글 필요
    for t in FUNDAMENTAL_ALIASES:
        supported[t] = "fundamental"
    for t in market_tokens():
        supported[t] = "market"
    for t in ECOS_TOKENS:
        supported[t] = "macro"
    for t in FRED_TOKENS:
        supported[t] = "macro"
    for t in FLOW_TOKENS:
        supported[t] = "flow"
    return {
        "supported": supported,
        "unsupported": dict(UNSUPPORTED_REASONS),
        "default_reason": "미지원 — 평가 시 무시됨 (데이터/매핑 없음)",
        "fundamental_note": "fundamental 그룹은 '펀더멘털 조건 평가' 토글 필요 — 최신 스냅샷 근사"
                            "(분기/트레일링 구분 없음 · look-ahead 주의)",
        "market_note": "시장(지수) 시계열 — 국내는 KRX 적재(mock 모드는 합성), "
                       "해외(DOW 등)는 yfinance 네트워크 필요. 데이터 없으면 평가 시 건너뜀",
        "macro_note": "환율·국고채(ECOS — BOK_API_KEY) · 미국채(FRED — FRED_API_KEY). "
                      "무료 키, 없으면 평가 시 건너뜀",
        "flow_note": "투자자별 수급(개인/외국인/기관) — KIS 일별 적재 필요"
                     "(python -m src.data.kis_flows). KIS TR이 최근 ~30영업일만 제공하므로 "
                     "매일 적재해 누적 — 적재 기간만 평가 가능",
    }
