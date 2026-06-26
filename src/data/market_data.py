"""
Market Data Layer — Screener V2 Milestone 3
==========================================================================
기술적 지표(RSI/MACD) + 수급(외인/기관) + 이벤트 캘린더 데이터 레이어.

전략:
  · KIS kis_client 재사용하여 OHLCV 수집 (없으면 deterministic mock)
  · 표준 공식: RSI(14), MACD(12,26,9)
  · 수급: foreign_net / institution_net (mock 우선)
  · 6시간 캐시 (macro_collector 패턴 재사용)
  · lazy 계산 — 기술 조건이 있을 때만, 통과 후보에 대해서만

방어적: 모든 데이터 소스 실패 시 deterministic mock → 시스템 무중단
"""

from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# 지표 카탈로그
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class IndicatorMeta:
    id: str
    label: str
    category: str          # technical | supply
    unit: str
    typical_min: float
    typical_max: float
    description: str


INDICATOR_CATALOG: list[IndicatorMeta] = [
    # ── 모멘텀 (Momentum) — 백테스터 공유 지표 ──
    IndicatorMeta("rsi_14",       "RSI(14)",        "momentum", "",   0,    100,  "상대강도지수 — 30 이하 과매도, 70 이상 과매수"),
    IndicatorMeta("rsi_7",        "RSI(7)",         "momentum", "",   0,    100,  "단기 RSI — 빠른 과매수/과매도 신호"),
    IndicatorMeta("stoch_k",      "스토캐스틱 %K",   "momentum", "",   0,    100,  "Fast Stochastic %K — 20 이하 과매도"),
    IndicatorMeta("stoch_d",      "스토캐스틱 %D",   "momentum", "",   0,    100,  "Slow Stochastic %D — %K의 3일 이동평균"),
    IndicatorMeta("stochrsi",     "Stoch RSI",      "momentum", "",   0,    100,  "RSI에 스토캐스틱 적용 — 더 민감한 모멘텀"),
    IndicatorMeta("williams_r",   "Williams %R",    "momentum", "",   -100, 0,    "윌리엄스 %R — -80 이하 과매도, -20 이상 과매수"),
    IndicatorMeta("cci",          "CCI(20)",        "momentum", "",   -250, 250,  "상품채널지수 — +100 이상 강세, -100 이하 약세"),
    IndicatorMeta("mfi",          "MFI(14)",        "momentum", "",   0,    100,  "자금흐름지수 — 거래량 가중 RSI"),
    IndicatorMeta("roc",          "ROC(10)",        "momentum", "%",  -30,  30,   "변화율 — 10일 전 대비 가격 변화율"),
    IndicatorMeta("momentum",     "모멘텀(10)",      "momentum", "%",  -25,  25,   "10일 전 대비 가격 변화율(%)"),
    # ── 추세 (Trend) ──
    IndicatorMeta("macd_hist",    "MACD 히스토그램", "trend", "",   -50,  50,   "MACD - Signal. 양수 전환 = 골든크로스"),
    IndicatorMeta("adx",          "ADX(14)",        "trend", "",   0,    100,  "추세 강도 — 25 이상 강한 추세"),
    IndicatorMeta("aroon_up",     "Aroon Up",       "trend", "",   0,    100,  "상승 추세 강도 — 70 이상 강한 상승"),
    IndicatorMeta("aroon_down",   "Aroon Down",     "trend", "",   0,    100,  "하락 추세 강도 — 70 이상 강한 하락"),
    IndicatorMeta("price_vs_ma20", "20일선 이격도",   "trend", "%",  -30,  30,   "현재가의 20일 이동평균 대비 괴리(%)"),
    IndicatorMeta("price_vs_ma60", "60일선 이격도",   "trend", "%",  -40,  40,   "현재가의 60일 이동평균 대비 괴리(%)"),
    IndicatorMeta("price_vs_ma120", "120일선 이격도",  "trend", "%", -50,  50,   "현재가의 120일 이동평균 대비 괴리(%)"),
    # ── 변동성 (Volatility) ──
    IndicatorMeta("bb_percent",   "볼린저 %B",       "volatility", "",  -0.2, 1.2,  "볼린저밴드 내 위치 — 0 하단, 1 상단"),
    IndicatorMeta("bb_width",     "볼린저 밴드폭",    "volatility", "%",  0,    30,   "밴드 폭 — 좁을수록 변동성 수축(스퀴즈)"),
    IndicatorMeta("atr_pct",      "ATR 비율",        "volatility", "%",  0,    15,   "평균 진폭 / 가격 (%) — 변동성 크기"),
    IndicatorMeta("volatility_10", "변동성(10일)",     "volatility", "%",  0,    80,   "10일 수익률 표준편차 연율화(%)"),
    # ── 거래량/가격 (Volume & Price) ──
    IndicatorMeta("volume_ratio", "거래량 비율",      "volume", "배",  0,    10,   "당일 거래량 / 20일 평균 — 1 이상 거래 급증"),
    IndicatorMeta("return_5d",    "5일 수익률",       "volume", "%",  -30,  30,   "최근 5거래일 누적 수익률"),
    IndicatorMeta("return_20d",   "20일 수익률",      "volume", "%",  -50,  50,   "최근 20거래일 누적 수익률"),
    IndicatorMeta("return_60d",   "60일 수익률",      "volume", "%",  -70,  70,   "최근 60거래일 누적 수익률"),
    IndicatorMeta("vwap_gap",     "VWAP 이격도",      "volume", "%",  -20,  20,   "현재가의 VWAP 대비 괴리(%)"),
    # ── 수급 (Supply) ──
    IndicatorMeta("foreign_net_5d",     "외국인 5일 순매수",  "supply", "억", -5000, 5000, "최근 5거래일 외국인 순매수 누적(억)"),
    IndicatorMeta("institution_net_5d", "기관 5일 순매수",    "supply", "억", -3000, 3000, "최근 5거래일 기관 순매수 누적(억)"),
]

INDICATOR_BY_ID = {i.id: i for i in INDICATOR_CATALOG}

INDICATOR_CATEGORY_LABELS = {
    "momentum":   "모멘텀",
    "trend":      "추세",
    "volatility": "변동성",
    "volume":     "거래량·가격",
    "supply":     "수급",
}


# ═══════════════════════════════════════════════════════════════════════════════
# 표준 지표 공식
# ═══════════════════════════════════════════════════════════════════════════════

def compute_rsi(prices: list[float], period: int = 14) -> float | None:
    """RSI = 100 - 100/(1+RS), RS = 평균상승/평균하락."""
    if len(prices) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(prices)):
        diff = prices[i] - prices[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss < 1e-9:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 2)


def _ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    k = 2 / (period + 1)
    ema = [values[0]]
    for v in values[1:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema


def compute_macd_hist(prices: list[float], fast: int = 12, slow: int = 26, signal: int = 9) -> float | None:
    """MACD 히스토그램 = MACD선 - 시그널선."""
    if len(prices) < slow + signal:
        return None
    ema_fast = _ema(prices, fast)
    ema_slow = _ema(prices, slow)
    macd_line = [f - s for f, s in zip(ema_fast[-len(ema_slow):], ema_slow)]
    signal_line = _ema(macd_line, signal)
    return round(macd_line[-1] - signal_line[-1], 3)


def compute_ma_disparity(prices: list[float], period: int) -> float | None:
    """이격도 = (현재가 - MA) / MA * 100."""
    if len(prices) < period:
        return None
    ma = sum(prices[-period:]) / period
    if ma < 1e-9:
        return None
    return round((prices[-1] - ma) / ma * 100, 2)


# ═══════════════════════════════════════════════════════════════════════════════
# Mock 가격 시계열 + 수급
# ═══════════════════════════════════════════════════════════════════════════════

def _mock_prices(stock_code: str, days: int = 90) -> list[float]:
    """deterministic mock 종가 (종목코드 seed)."""
    seed = sum(ord(c) for c in stock_code)
    rng = random.Random(seed)
    base = 10000 + (seed % 90) * 1000
    prices = [base]
    drift = rng.uniform(-0.001, 0.0015)
    for _ in range(days - 1):
        ret = drift + rng.gauss(0, 0.018)
        prices.append(max(100, prices[-1] * (1 + ret)))
    return prices


def _mock_ohlcv(stock_code: str, days: int = 150):
    """
    deterministic mock OHLCV DataFrame — 백테스터 kis_indicators 호출용.
    close 시계열에서 high/low/open/volume을 일관되게 생성.
    """
    import pandas as pd
    closes = _mock_prices(stock_code, days)
    seed = sum(ord(c) for c in stock_code)
    rng = random.Random(seed * 3 + 7)
    rows = {"open": [], "high": [], "low": [], "close": closes, "volume": []}
    base_vol = 100000 + (seed % 50) * 50000
    prev = closes[0]
    for px in closes:
        # 일중 변동폭 (close 기준 ±1.5%)
        spread = px * rng.uniform(0.005, 0.02)
        hi = px + spread * rng.uniform(0.3, 1.0)
        lo = px - spread * rng.uniform(0.3, 1.0)
        op = lo + (hi - lo) * rng.uniform(0.2, 0.8)
        rows["open"].append(op)
        rows["high"].append(max(hi, px, op))
        rows["low"].append(min(lo, px, op))
        # 거래량: 변동 클수록 증가
        vol = base_vol * (1 + abs(px / prev - 1) * 8) * rng.uniform(0.6, 1.5)
        rows["volume"].append(vol)
        prev = px
    return pd.DataFrame(rows)


def _safe_last(series, default=None):
    """Series의 마지막 유효값 추출 (NaN 방어)."""
    try:
        import math
        v = float(series.iloc[-1])
        return None if math.isnan(v) or math.isinf(v) else round(v, 3)
    except Exception:
        return default


def _mock_supply(stock_code: str, indicator: str) -> float:
    seed = sum(ord(c) for c in stock_code) + sum(ord(c) for c in indicator)
    rng = random.Random(seed)
    scale = 5000 if "foreign" in indicator else 3000
    return round(rng.gauss(0, scale * 0.35), 1)


def _real_kis_ohlcv(stock_code: str, days: int = 150):
    """
    실제 KIS 일봉 → OHLCV DataFrame (기술지표 계산용).
    KIS_USE_MOCK=0 + 키 설정 시 실제 시세, 아니면 None 반환 → mock fallback.
    """
    try:
        import os
        if os.getenv("KIS_USE_MOCK", "1") == "1":
            return None  # mock 모드 → fallback
        import pandas as pd

        from src.execution.kis_client import get_kis_client
        client = get_kis_client()
        rows = client.get_daily_ohlcv(stock_code, days=days)
        if not rows or len(rows) < 30:
            return None
        df = pd.DataFrame(rows)
        # 컬럼 보장
        for col in ("open", "high", "low", "close", "volume"):
            if col not in df.columns:
                return None
        return df
    except Exception as e:
        logger.debug(f"KIS 실시세 조회 실패 ({stock_code}), mock fallback: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# Market Data Provider (캐시)
# ═══════════════════════════════════════════════════════════════════════════════

class MarketDataProvider:
    """기술지표 + 수급 데이터 제공 (KIS 우선, Mock fallback)."""

    _singleton: MarketDataProvider | None = None

    @classmethod
    def get_default(cls) -> MarketDataProvider:
        if cls._singleton is None:
            cls._singleton = cls()
        return cls._singleton

    def __init__(self, cache_ttl: int = 3600 * 6):
        self.cache_ttl = cache_ttl
        self._cache: dict[str, tuple[float, dict]] = {}
        self._lock = threading.Lock()
        # KIS 시세는 _real_kis_ohlcv()가 호출 시점에 get_kis_client()로 연동
        # (KIS_USE_MOCK=0 + 키 설정 시 실제, 아니면 deterministic mock)

    def get_indicators(self, stock_code: str) -> dict:
        """단일 종목의 모든 기술지표 + 수급 (캐시). 백테스터 kis_indicators 재사용."""
        with self._lock:
            entry = self._cache.get(stock_code)
            if entry and time.time() - entry[0] < self.cache_ttl:
                return entry[1]

        data = self._compute_all_indicators(stock_code)

        with self._lock:
            self._cache[stock_code] = (time.time(), data)
        return data

    def _compute_all_indicators(self, stock_code: str) -> dict:
        """백테스터 kis_indicators 함수로 전 지표 계산 (동일 공식 보장)."""
        from src.data.mock_gate import mock_allowed
        allow = mock_allowed()
        # 수급: mock 모드서만 합성. 운영(실키)선 None — 실 수급 미연동 시 합성 대신 정직 None.
        data = {
            "foreign_net_5d":     _mock_supply(stock_code, "foreign_net") if allow else None,
            "institution_net_5d": _mock_supply(stock_code, "institution_net") if allow else None,
            "insider_net_20d":    (_mock_supply(stock_code, "insider_net") * 0.3) if allow else None,
            "retail_net_5d":      _mock_supply(stock_code, "retail_net") if allow else None,
            "_source": "mock_kis_indicators" if allow else "unavailable",
        }
        try:
            import src.kis_indicators as ki
            # 실제 KIS 일봉 우선. 없으면: mock 모드만 합성, 운영선 지표 미산출(정직 "—").
            df = _real_kis_ohlcv(stock_code, days=150)
            if df is None:
                if not allow:
                    data["_source"] = "unavailable"
                    return data  # 운영 — 실 OHLCV 없음 → 합성 금지
                df = _mock_ohlcv(stock_code, days=150)
                data["_source"] = "mock_kis_indicators"
            else:
                data["_source"] = "kis_real"
            close = df["close"].iloc[-1]

            # 모멘텀
            data["rsi_14"]    = _safe_last(ki.calc_rsi(df, 14))
            data["rsi_7"]     = _safe_last(ki.calc_rsi(df, 7))
            data["stoch_k"]   = _safe_last(ki.calc_stochastic_k(df, 14))
            data["stoch_d"]   = _safe_last(ki.calc_stochastic_d(df, 14, 3))
            data["stochrsi"]  = _safe_last(ki.calc_stochrsi(df))
            data["williams_r"] = _safe_last(ki.calc_williams_r(df, 14))
            data["cci"]       = _safe_last(ki.calc_cci(df, 20))
            data["mfi"]       = _safe_last(ki.calc_mfi(df, 14))
            data["roc"]       = _safe_last(ki.calc_roc(df, 10))
            mom = _safe_last(ki.calc_momentum(df, 10))
            data["momentum"] = round(mom / close * 100, 2) if (mom is not None and close) else None
            # 추세
            data["macd_hist"] = _safe_last(ki.calc_macd_histogram(df))
            data["adx"]       = _safe_last(ki.calc_adx(df, 14))
            data["aroon_up"]  = _safe_last(ki.calc_aroon_up(df, 25))
            data["aroon_down"] = _safe_last(ki.calc_aroon_down(df, 25))
            # 이격도: calc_disparity가 (price/ma*100) 반환 → -100 변환하여 괴리율(%)
            d20 = _safe_last(ki.calc_disparity(df, 20)); data["price_vs_ma20"] = round(d20 - 100, 2) if d20 else None
            d60 = _safe_last(ki.calc_disparity(df, 60)); data["price_vs_ma60"] = round(d60 - 100, 2) if d60 else None
            d120 = _safe_last(ki.calc_disparity(df, 120)); data["price_vs_ma120"] = round(d120 - 100, 2) if d120 else None
            # 변동성
            data["bb_percent"] = _safe_last(ki.calc_bb_percent(df, 20, 2.0))
            bbw = _safe_last(ki.calc_bb_width(df, 20, 2.0))
            bbm = _safe_last(ki.calc_bb_middle(df, 20))
            data["bb_width"] = round(bbw / bbm * 100, 2) if (bbw and bbm) else None
            atr = _safe_last(ki.calc_atr(df, 14))
            data["atr_pct"]    = round(atr / close * 100, 2) if atr and close else None
            vol = _safe_last(ki.calc_volatility(df, 10))
            data["volatility_10"] = round(vol * 100, 2) if vol else None
            # 거래량/가격
            vma = _safe_last(ki.calc_volume_ma(df, 20))
            cur_vol = float(df["volume"].iloc[-1])
            data["volume_ratio"] = round(cur_vol / vma, 2) if vma else None
            r5 = _safe_last(ki.calc_returns(df, 5));  data["return_5d"]  = round(r5 * 100, 2) if r5 else None
            r20 = _safe_last(ki.calc_returns(df, 20)); data["return_20d"] = round(r20 * 100, 2) if r20 else None
            r60 = _safe_last(ki.calc_returns(df, 60)); data["return_60d"] = round(r60 * 100, 2) if r60 else None
            vwap = _safe_last(ki.calc_vwap(df))
            data["vwap_gap"]   = round((close - vwap) / vwap * 100, 2) if vwap else None
        except Exception as e:
            logger.debug(f"지표 계산 실패 ({stock_code}), fallback: {e}")
            # fallback: 핵심 지표만 자체 계산 — mock 모드서만(운영선 합성 금지, 미산출 "—")
            if allow:
                prices = _mock_prices(stock_code, 90)
                data.setdefault("rsi_14", compute_rsi(prices, 14))
                data.setdefault("macd_hist", compute_macd_hist(prices))
                data.setdefault("price_vs_ma20", compute_ma_disparity(prices, 20))
                data.setdefault("price_vs_ma60", compute_ma_disparity(prices, 60))
        return data

    def cache_clear(self):
        with self._lock:
            self._cache.clear()


def indicators_catalog() -> dict:
    """API용 지표 카탈로그."""
    by_cat: dict[str, list] = {}
    for ind in INDICATOR_CATALOG:
        by_cat.setdefault(ind.category, []).append({
            "id": ind.id, "label": ind.label, "unit": ind.unit,
            "typical_min": ind.typical_min, "typical_max": ind.typical_max,
            "description": ind.description,
        })
    return {
        "categories": [
            {"id": cat, "label": INDICATOR_CATEGORY_LABELS.get(cat, cat), "indicators": inds}
            for cat, inds in by_cat.items()
        ],
    }



# ═══════════════════════════════════════════════════════════════════════════════
# V3-M3: Behavioral Signals (Smart Money & Insider Divergence)
# ═══════════════════════════════════════════════════════════════════════════════
#
# 개인 투매와 스마트머니(내부자/기관/외국인) 매수의 교차점 포착.
# 행동재무학: 개인은 고점 매수·저점 매도 경향, 내부자는 정보 우위.

BEHAVIOR_SIGNALS = {
    "insider_buy_retail_sell": {
        "label": "내부자 매수 + 개인 매도",
        "description": "내부자는 사들이는데 개인이 투매 — 정보 비대칭 역발상",
    },
    "smart_divergence": {
        "label": "스마트머니 괴리",
        "description": "외국인·기관 순매수 + 개인 순매도 (수급 주체 괴리)",
    },
    "institutional_accumulation": {
        "label": "기관 집중 매집",
        "description": "기관이 지속 순매수하며 물량 확보",
    },
    "capitulation_reversal": {
        "label": "개인 투매 + 외국인 매수",
        "description": "개인 패닉셀에 외국인이 받아내는 반전 신호",
    },
}


def eval_behavioral_signal(indicators: dict, signal: str) -> bool:
    """행동 신호 평가 — 복합 수급 조건."""
    foreign = indicators.get("foreign_net_5d") or 0
    inst = indicators.get("institution_net_5d") or 0
    insider = indicators.get("insider_net_20d") or 0
    retail = indicators.get("retail_net_5d") or 0

    if signal == "insider_buy_retail_sell":
        return insider > 0 and retail < 0
    if signal == "smart_divergence":
        return (foreign > 0 or inst > 0) and retail < 0
    if signal == "institutional_accumulation":
        return inst > 0 and foreign >= 0
    if signal == "capitulation_reversal":
        return retail < 0 and foreign > 0
    return False


def behavior_signals_catalog() -> dict:
    """API용 행동 신호 카탈로그."""
    return {
        "signals": [
            {"id": k, "label": v["label"], "description": v["description"]}
            for k, v in BEHAVIOR_SIGNALS.items()
        ],
    }
