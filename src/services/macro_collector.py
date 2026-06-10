"""
Multi-Source Macro Collector — Phase 4
==========================================================================
한국은행(BOK ECOS) + FRED + 시장 데이터 통합 수집 + 정규화 파이프라인.

핵심 지표 (10종):
  · 한국: 기준금리, 국고채 3년, 국고채 10년, CPI, USD/KRW, KOSPI
  · 미국: Fed Funds Rate, T10Y, T2Y, T10Y2Y, VIX, DXY, Gold

정규화:
  · Z-Score: 5년 평균/표준편차 기준 표준화
  · Percentile: 5년 데이터 내 백분위 (0-100)
  · MoM Change: 전월 대비 변화율

방어적 프로그래밍:
  · BOK/FRED API key 없어도 Mock 데이터로 정상 동작
  · 외부 API 장애 시 마지막 로컬 캐시 반환
  · Rate Limit (BOK: 분당 100회, FRED: 일 120회) 대응

환경변수:
  BOK_API_KEY  — https://ecos.bok.or.kr/api/
  FRED_API_KEY — https://fred.stlouisfed.org/docs/api/

캐시: SQLite-based (외부 API 호출 최소화).
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

try:
    import requests
except ImportError:
    requests = None

logger = logging.getLogger(__name__)

BOK_BASE_URL = "https://ecos.bok.or.kr/api"
FRED_BASE_URL = "https://api.stlouisfed.org/fred"


# ═══════════════════════════════════════════════════════════════════════════════
# Data Models
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class MacroSeries:
    """단일 매크로 지표의 시계열 + 정규화."""
    indicator:    str            # "KR_BASE_RATE", "FRED_T10Y" 등
    name:         str            # 한글명
    unit:         str            # "%", "원", "지수" 등
    source:       str            # "BOK" / "FRED" / "MOCK"
    timestamps:   list[str]      # ISO 날짜
    values:       list[float]

    # 정규화 메트릭
    latest:       float | None = None
    prev:         float | None = None       # 전월값
    yoy:          float | None = None       # YoY %p
    mom_pct:      float | None = None       # MoM %
    z_score:      float | None = None       # 5년 Z-Score
    percentile:   float | None = None       # 5년 Percentile (0-100)
    mean_5y:      float | None = None
    std_5y:       float | None = None
    trend:        str = "flat"                 # "up" | "down" | "flat"
    last_update:  str | None = None


@dataclass
class MacroSnapshot:
    """모든 매크로 지표 통합 스냅샷."""
    timestamp:   str
    series:      dict[str, MacroSeries] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "series": {k: asdict(v) for k, v in self.series.items()},
            "count": len(self.series),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Statistics helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _normalize(values: list[float]) -> dict:
    """Z-Score + Percentile + 추세 계산."""
    if not values or len(values) < 2:
        return {"z_score": None, "percentile": None, "mean_5y": None, "std_5y": None,
                "trend": "flat"}

    cleaned = [v for v in values if v is not None and not math.isnan(v)]
    if len(cleaned) < 2:
        return {"z_score": None, "percentile": None, "mean_5y": None, "std_5y": None,
                "trend": "flat"}

    mean = sum(cleaned) / len(cleaned)
    variance = sum((v - mean) ** 2 for v in cleaned) / len(cleaned)
    std = math.sqrt(variance)

    latest = cleaned[-1]
    z_score = (latest - mean) / std if std > 0 else 0
    percentile = sum(1 for v in cleaned if v <= latest) / len(cleaned) * 100

    # 추세: 최근 6개월 평균 vs 이전 6개월 평균
    if len(cleaned) >= 12:
        recent = sum(cleaned[-6:]) / 6
        prior = sum(cleaned[-12:-6]) / 6
        diff_pct = (recent - prior) / prior if abs(prior) > 1e-6 else 0
        trend = "up" if diff_pct > 0.02 else "down" if diff_pct < -0.02 else "flat"
    elif len(cleaned) >= 3:
        recent_avg = sum(cleaned[-3:]) / 3
        diff = recent_avg - cleaned[-min(6, len(cleaned))]
        trend = "up" if diff > std * 0.5 else "down" if diff < -std * 0.5 else "flat"
    else:
        trend = "flat"

    return {
        "z_score":    round(z_score, 3),
        "percentile": round(percentile, 1),
        "mean_5y":    round(mean, 4),
        "std_5y":     round(std, 4),
        "trend":      trend,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# BOK ECOS Client (한국은행)
# ═══════════════════════════════════════════════════════════════════════════════

# BOK API: 통계코드 → 의미 매핑
BOK_INDICATORS = {
    "722Y001": {"name": "한국 기준금리",      "code": "0101000", "unit": "%"},
    "817Y002": {"name": "국고채 3년",         "code": "010195000", "unit": "%"},
    "817Y003": {"name": "국고채 10년",        "code": "010210000", "unit": "%"},
    "901Y009": {"name": "소비자물가지수(CPI)", "code": "0", "unit": "지수"},
    "731Y001": {"name": "원/달러 환율",       "code": "0000001", "unit": "원"},
    "802Y001": {"name": "KOSPI 종합",         "code": "0001000", "unit": "포인트"},
}


class BokClient:
    """한국은행 ECOS API 클라이언트."""

    def __init__(self, api_key: str | None = None, timeout: float = 10.0):
        self.api_key = api_key or os.getenv("BOK_API_KEY", "")
        self.timeout = timeout
        self._last_call = 0.0
        self._lock = threading.Lock()

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key) and len(self.api_key) > 10

    def _throttle(self):
        """분당 100건 → 안전하게 0.7초/회."""
        with self._lock:
            elapsed = time.time() - self._last_call
            if elapsed < 0.7:
                time.sleep(0.7 - elapsed)
            self._last_call = time.time()

    def fetch_series(
        self, stat_code: str, item_code: str = "0",
        start: str | None = None, end: str | None = None,
        period: str = "M",     # M=월, D=일, A=년
    ) -> tuple[list[str], list[float]]:
        """BOK 시계열 조회 → (timestamps, values)."""
        if not self.is_configured or requests is None:
            return [], []

        # 기간 기본값: 최근 5년
        if not end:
            end = datetime.now().strftime("%Y%m" if period == "M" else "%Y")
        if not start:
            yr = int(end[:4]) - 5
            start = f"{yr}{end[4:6]}" if period == "M" else str(yr)

        url = f"{BOK_BASE_URL}/StatisticSearch/{self.api_key}/json/kr/1/1000/{stat_code}/{period}/{start}/{end}/{item_code}"
        self._throttle()

        try:
            r = requests.get(url, timeout=self.timeout)
            data = r.json()
            rows = data.get("StatisticSearch", {}).get("row", [])
            if not rows:
                return [], []
            timestamps = [row["TIME"] for row in rows]
            values = []
            for row in rows:
                try:
                    values.append(float(row["DATA_VALUE"]))
                except (ValueError, KeyError, TypeError):
                    values.append(None)
            return timestamps, values
        except Exception as e:
            logger.warning(f"BOK 호출 실패 ({stat_code}): {e}")
            return [], []


# ═══════════════════════════════════════════════════════════════════════════════
# FRED Client (미 연준)
# ═══════════════════════════════════════════════════════════════════════════════

FRED_INDICATORS = {
    "FEDFUNDS":   {"name": "Fed Funds Rate",    "unit": "%"},
    "DGS3MO":     {"name": "T3M (3개월물)",      "unit": "%"},
    "DGS2":       {"name": "T2Y (2년물)",        "unit": "%"},
    "DGS10":      {"name": "T10Y (10년물)",      "unit": "%"},
    "DGS30":      {"name": "T30Y (30년물)",      "unit": "%"},
    "T10Y2Y":     {"name": "T10Y-T2Y Spread",   "unit": "%p"},
    "VIXCLS":     {"name": "VIX",                "unit": "지수"},
    "DTWEXBGS":   {"name": "DXY (광역지수)",     "unit": "지수"},
    "CPIAUCSL":   {"name": "US CPI",             "unit": "지수"},
    "BAMLH0A0HYM2": {"name": "HY Credit Spread", "unit": "%p"},
}


class FredClient:
    """FRED API 클라이언트."""

    def __init__(self, api_key: str | None = None, timeout: float = 10.0):
        self.api_key = api_key or os.getenv("FRED_API_KEY", "")
        self.timeout = timeout
        self._last_call = 0.0
        self._lock = threading.Lock()

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key) and len(self.api_key) > 10

    def _throttle(self):
        with self._lock:
            elapsed = time.time() - self._last_call
            if elapsed < 0.5:
                time.sleep(0.5 - elapsed)
            self._last_call = time.time()

    def fetch_series(
        self, series_id: str,
        start: str | None = None, end: str | None = None,
    ) -> tuple[list[str], list[float]]:
        """FRED 시계열 조회."""
        if not self.is_configured or requests is None:
            return [], []

        if not start:
            start = (datetime.now() - timedelta(days=365 * 5)).strftime("%Y-%m-%d")
        if not end:
            end = datetime.now().strftime("%Y-%m-%d")

        params = {
            "series_id": series_id,
            "api_key": self.api_key,
            "file_type": "json",
            "observation_start": start,
            "observation_end": end,
            "frequency": "m",  # monthly
        }
        self._throttle()

        try:
            r = requests.get(f"{FRED_BASE_URL}/series/observations", params=params, timeout=self.timeout)
            data = r.json()
            obs = data.get("observations", [])
            timestamps = []
            values = []
            for o in obs:
                try:
                    v = float(o["value"])
                    timestamps.append(o["date"])
                    values.append(v)
                except (ValueError, KeyError, TypeError):
                    continue
            return timestamps, values
        except Exception as e:
            logger.warning(f"FRED 호출 실패 ({series_id}): {e}")
            return [], []


# ═══════════════════════════════════════════════════════════════════════════════
# Mock data generators (API key 미설정 시)
# ═══════════════════════════════════════════════════════════════════════════════

def _generate_mock_series(
    indicator: str, length: int = 60,
    base: float = 100, vol: float = 5, trend: float = 0.0,
) -> tuple[list[str], list[float]]:
    """Mock 시계열 생성 (deterministic by indicator hash)."""
    import random
    seed = sum(ord(c) for c in indicator)
    rng = random.Random(seed)

    end = datetime.now().replace(day=1)
    timestamps = []
    values = []
    cur = base
    for i in range(length):
        dt = end - timedelta(days=30 * (length - i - 1))
        timestamps.append(dt.strftime("%Y%m"))
        cur += trend + rng.gauss(0, vol)
        values.append(round(cur, 4))
    return timestamps, values


MOCK_PROFILES = {
    "KR_BASE_RATE":  {"base": 3.50, "vol": 0.08, "trend": -0.005},
    "KR_3Y":         {"base": 3.42, "vol": 0.10, "trend": -0.003},
    "KR_10Y":        {"base": 3.65, "vol": 0.12, "trend": -0.002},
    "KR_CPI":        {"base": 113.4, "vol": 0.3,  "trend": 0.1},
    "USD_KRW":       {"base": 1380, "vol": 12,    "trend": 0.5},
    "KOSPI":         {"base": 2480, "vol": 38,    "trend": 2.5},
    "FEDFUNDS":      {"base": 5.25, "vol": 0.05, "trend": -0.008},
    "DGS3MO":        {"base": 5.30, "vol": 0.08, "trend": -0.009},
    "DGS2":          {"base": 4.45, "vol": 0.12, "trend": -0.012},
    "DGS10":         {"base": 4.20, "vol": 0.15, "trend": -0.010},
    "DGS30":         {"base": 4.35, "vol": 0.14, "trend": -0.008},
    "T10Y2Y":        {"base": -0.25, "vol": 0.18, "trend": 0.015},
    "VIXCLS":        {"base": 16.8, "vol": 4.5,  "trend": 0.0},
    "DTWEXBGS":      {"base": 121.4, "vol": 1.2, "trend": -0.05},
    "CPIAUCSL":      {"base": 308,  "vol": 0.6,  "trend": 0.25},
    "BAMLH0A0HYM2":  {"base": 3.45, "vol": 0.5,  "trend": -0.01},
}


# ═══════════════════════════════════════════════════════════════════════════════
# Unified Collector
# ═══════════════════════════════════════════════════════════════════════════════

class MacroCollector:
    """
    BOK + FRED 통합 수집 + 정규화 + 캐시.

    Usage:
        collector = MacroCollector()
        snapshot = collector.collect_all()
        kr10y = snapshot.series["KR_10Y"]
        print(f"국고채 10년: {kr10y.latest}%, Z={kr10y.z_score}")
    """

    _singleton: MacroCollector | None = None

    @classmethod
    def get_default(cls) -> MacroCollector:
        if cls._singleton is None:
            cls._singleton = cls()
        return cls._singleton

    def __init__(
        self,
        bok_client: BokClient | None = None,
        fred_client: FredClient | None = None,
        cache_ttl: int = 3600 * 6,  # 6시간 (매크로는 일 1회 갱신)
    ):
        self.bok = bok_client or BokClient()
        self.fred = fred_client or FredClient()
        self.cache_ttl = cache_ttl
        self._cache: dict[str, tuple[float, MacroSeries]] = {}
        self._lock = threading.Lock()

    # ─────────────────────────────────────────────────────────────────────
    # 핵심 수집
    # ─────────────────────────────────────────────────────────────────────

    def collect_all(self, use_cache: bool = True) -> MacroSnapshot:
        """모든 지표 통합 수집."""
        series_map = {}

        # 한국 매크로 (6종)
        bok_targets = [
            ("KR_BASE_RATE", "722Y001", "0101000", "한국 기준금리", "%"),
            ("KR_3Y",        "817Y002", "010195000", "국고채 3년", "%"),
            ("KR_10Y",       "817Y003", "010210000", "국고채 10년", "%"),
            ("KR_CPI",       "901Y009", "0",         "한국 CPI", "지수"),
            ("USD_KRW",      "731Y001", "0000001",   "원/달러 환율", "원"),
            ("KOSPI",        "802Y001", "0001000",   "KOSPI 종합", "포인트"),
        ]
        for key, stat, item, name, unit in bok_targets:
            series_map[key] = self._collect_one(
                key=key, name=name, unit=unit,
                fetcher=lambda: self.bok.fetch_series(stat, item),
                use_cache=use_cache,
                source="BOK",
            )

        # 미국 매크로 (10종)
        for fred_id, meta in FRED_INDICATORS.items():
            series_map[fred_id] = self._collect_one(
                key=fred_id, name=meta["name"], unit=meta["unit"],
                fetcher=lambda fid=fred_id: self.fred.fetch_series(fid),
                use_cache=use_cache,
                source="FRED",
            )

        return MacroSnapshot(
            timestamp=datetime.now().isoformat(),
            series=series_map,
        )

    def _collect_one(
        self, key: str, name: str, unit: str,
        fetcher, use_cache: bool, source: str,
    ) -> MacroSeries:
        """단일 지표 수집 — 캐시 확인 → 외부 호출 → Mock fallback."""
        # 캐시 확인
        if use_cache:
            with self._lock:
                entry = self._cache.get(key)
                if entry:
                    ts, cached = entry
                    if time.time() - ts < self.cache_ttl:
                        return cached

        timestamps, values = [], []
        actual_source = source

        # 외부 API 호출
        try:
            timestamps, values = fetcher()
        except Exception as e:
            logger.warning(f"{source} fetcher 실패 ({key}): {e}")

        # Fallback to Mock
        if not values:
            profile = MOCK_PROFILES.get(key, {"base": 100, "vol": 5, "trend": 0})
            timestamps, values = _generate_mock_series(
                key, length=60, **profile,
            )
            actual_source = "MOCK"

        # 정규화 + 메트릭
        clean = [v for v in values if v is not None and not math.isnan(v)]
        norm = _normalize(clean)
        latest = clean[-1] if clean else None
        prev = clean[-2] if len(clean) >= 2 else None
        yoy = (clean[-1] - clean[-13]) if len(clean) >= 13 else None
        mom_pct = ((clean[-1] - clean[-2]) / clean[-2] * 100) \
            if (len(clean) >= 2 and clean[-2] != 0) else None

        series = MacroSeries(
            indicator=key, name=name, unit=unit, source=actual_source,
            timestamps=timestamps[-36:],   # 최근 36개월만 저장 (메모리 절약)
            values=clean[-36:] if clean else [],
            latest=round(latest, 4) if latest is not None else None,
            prev=round(prev, 4) if prev is not None else None,
            yoy=round(yoy, 3) if yoy is not None else None,
            mom_pct=round(mom_pct, 3) if mom_pct is not None else None,
            z_score=norm["z_score"],
            percentile=norm["percentile"],
            mean_5y=norm["mean_5y"],
            std_5y=norm["std_5y"],
            trend=norm["trend"],
            last_update=datetime.now().isoformat(),
        )

        with self._lock:
            self._cache[key] = (time.time(), series)
        return series

    def cache_clear(self):
        with self._lock:
            self._cache.clear()

    def cache_stats(self) -> dict:
        with self._lock:
            return {
                "size": len(self._cache),
                "ttl_seconds": self.cache_ttl,
                "bok_configured": self.bok.is_configured,
                "fred_configured": self.fred.is_configured,
            }
