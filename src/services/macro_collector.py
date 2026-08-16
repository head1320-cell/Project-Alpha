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


def _history_years() -> int:
    """매크로 시계열 적재 깊이(년). BOK/FRED는 수십 년 제공(과거 5년 하드코딩 제거).

    ★기본 20년 = 240개월 (P4-D3)★
    `capability.REQUIREMENTS["frontier_sample"]` 이 프론티어 모델 학습에 240관측을
    요구한다. 기본값이 15(180개월)면 **키를 정상적으로 넣어도 사다리가 안 올라간다** —
    설정을 따로 만져야만 열리는 천장은 사실상 닫힌 천장이다. 기본값을 요건에 맞춘다.

    이 값은 mock 길이도 함께 정한다(아래 `_generate_mock_series` 호출부). 합성으로
    사다리가 올라가는 것은 `_min_observations(require_real_source=True)` 가 막는다.
    """
    try:
        return max(1, int(os.getenv("MACRO_HISTORY_YEARS", "20")))
    except ValueError:
        return 20


#: 계열당 저장 하한(개월). YoY(13) 변환 후에도 5년 z-표본이 남는 최소치 —
#: 이 값은 예전 `[-72:]` 상한이 실제로 지키려던 **하한**이다.
_MIN_STORE_MONTHS = 72


def _store_cap() -> int:
    """계열당 저장 개월 상한. 적재 깊이에서 유도하되 z-표본 하한을 지킨다 (P4-D3)."""
    return max(_MIN_STORE_MONTHS, _history_years() * 12)


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

#: z-표본 창(개월). 필드명 `mean_5y`·`std_5y` 가 약속하는 값 — 5년 = 60개월.
_Z_WINDOW_MONTHS = 60


def _normalize(values: list[float]) -> dict:
    """Z-Score + Percentile + 추세 계산.

    z·percentile 은 **최근 5년 창**으로 낸다(`_Z_WINDOW_MONTHS`). 추세는 최근
    6개월 vs 이전 6개월이라 창과 무관하다.
    """
    if not values or len(values) < 2:
        return {"z_score": None, "percentile": None, "mean_5y": None, "std_5y": None,
                "trend": "flat"}

    cleaned = [v for v in values if v is not None and not math.isnan(v)]
    if len(cleaned) < 2:
        return {"z_score": None, "percentile": None, "mean_5y": None, "std_5y": None,
                "trend": "flat"}

    # ★z-표본 창을 5년으로 고정한다 (P4-D3)★
    #
    # 이 함수는 `mean_5y`·`std_5y` 라는 이름으로 값을 내면서 실제로는 **받은 구간
    # 전부**로 계산하고 있었다. 저장이 72개월이던 시절에는 "대략 5년" 이라 티가 나지
    # 않았지만, 이름이 약속한 것과 다른 값이었다.
    #
    # P4-D3 이 깊이를 240개월로 열자 이 불일치가 **동작으로 터졌다.** mock 은 드리프트
    # 있는 랜덤워크라 구간이 길어질수록 최신값이 전체 평균에서 멀어지고(z ∝ n),
    # 그 결과 국면이 DEFENSIVE·고스트레스로 뒤집혀 타이밍 노출이 0 이 됐다
    # (`test_three_way_endpoint::test_a_real_snapshot_does_not_zero_out_exposure`).
    #
    # 즉 깊이 확장이 만든 새 버그가 아니라 **원래 있던 이름-구현 불일치**가 드러난
    # 것이다. 이름이 약속한 대로 고친다 — 창을 고정하면 z 는 적재 깊이와 무관해지고,
    # 그것이 하류 국면 로직이 처음부터 가정하던 바다.
    window = cleaned[-_Z_WINDOW_MONTHS:]
    mean = sum(window) / len(window)
    variance = sum((v - mean) ** 2 for v in window) / len(window)
    std = math.sqrt(variance)

    latest = cleaned[-1]
    z_score = (latest - mean) / std if std > 0 else 0
    percentile = sum(1 for v in window if v <= latest) / len(window) * 100

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
            yr = int(end[:4]) - _history_years()
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
    # Phase 8b — 스펙 §6.1/§6.2
    "VXVCLS":     {"name": "VIX 3개월(VXV)",     "unit": "지수"},
    "NFCI":       {"name": "금융환경지수(NFCI)", "unit": "지수"},
    "DTWEXBGS":   {"name": "DXY (광역지수)",     "unit": "지수"},
    "CPIAUCSL":   {"name": "US CPI",             "unit": "지수"},
    "BAMLH0A0HYM2": {"name": "HY Credit Spread", "unit": "%p"},
    # 성장·물가·유동성·심리 확장 (5 API 최대 활용 — 키 없으면 결정론적 mock)
    "GDPC1":      {"name": "US 실질GDP",          "unit": "지수"},
    "INDPRO":     {"name": "산업생산",            "unit": "지수"},
    "UNRATE":     {"name": "실업률",              "unit": "%"},
    "PAYEMS":     {"name": "비농업고용",          "unit": "천명"},
    "UMCSENT":    {"name": "소비자심리",          "unit": "지수"},
    "T10YIE":     {"name": "기대인플레(10Y)",     "unit": "%"},
    "DFII10":     {"name": "실질금리(10Y)",       "unit": "%"},
    "M2SL":       {"name": "M2 통화량",           "unit": "지수"},
    "DCOILWTICO": {"name": "WTI 유가",            "unit": "$"},
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
            start = (datetime.now() - timedelta(days=365 * _history_years())).strftime("%Y-%m-%d")
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
    indicator: str, length: int = 84,
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
    # 국면 축 실물 지표 — mock도 현실적 스케일 (기본 {base:100,vol:5}는 실업률 100% 같은 왜곡 유발)
    "KR_LEADING_CYCLE": {"base": 100.2, "vol": 0.35, "trend": -0.02},
    "KR_IP":         {"base": 112.5, "vol": 1.1,  "trend": 0.12},
    "INDPRO":        {"base": 103.2, "vol": 0.5,  "trend": 0.06},
    "UNRATE":        {"base": 4.0,  "vol": 0.12, "trend": 0.008},
    "PAYEMS":        {"base": 158_000, "vol": 250, "trend": 130},
    "GDPC1":         {"base": 22_700, "vol": 70,  "trend": 38},
    "T10YIE":        {"base": 2.30, "vol": 0.07, "trend": 0.001},
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
            # 국면 성장축(실물) — ECOS 코드는 GCP 실호출로 검증, 실패 시 unavailable → 축에서 자동 제외
            ("KR_LEADING_CYCLE", "901Y067", "I16E", "경기선행지수 순환변동치", "지수"),
            ("KR_IP",            "901Y033", "A00",  "산업생산지수", "지수"),
            # ── M1-I 신규 3종 ────────────────────────────────────────────────
            # ★이 셋은 실호출로 검증된 적이 없다★ 통계표/항목 코드가 틀리면 시리즈가
            # 예외 없이 조용히 빈다. `source_registry` 가 mock 폴백을 막으므로
            # 빈 값이 그럴듯한 숫자로 덮이지 않는다 — 그래야 코드가 틀렸다는 것을
            # 알 수 있다. 검증은 `verify_connection.py::check_ecos`.
            ("KR_M2",      "101Y003", "BBHA00", "M2 통화량(평잔)", "십억원"),
            ("KR_GDP",     "200Y002", "1400",   "실질 GDP", "십억원"),
            ("KR_CORP3Y",  "817Y002", "010200000", "회사채 3년(AA-)", "%"),
        ]
        for key, stat, item, name, unit in bok_targets:
            series_map[key] = self._collect_one(
                key=key, name=name, unit=unit,
                # ★기본인자 바인딩★ 바로 아래 FRED 루프는 `lambda fid=fred_id:` 인데
                # 여기만 `lambda: ...(stat, item)` 이라 **늦은 바인딩**이었다. 지금은
                # `_collect_one` 이 같은 반복 안에서 동기로 부르므로 값이 맞아
                # 살아 있는 버그는 아니었지만, 누군가 스레드풀·async 로 바꾸는 순간
                # 11개 시리즈가 전부 마지막 stat 코드를 조회한다. 두 루프의 관례를 맞춘다.
                fetcher=lambda s=stat, i=item: self.bok.fetch_series(s, i),
                use_cache=use_cache,
                source="BOK",
            )

        # ── 파생: 신용스프레드 = 회사채3Y − 국고3Y (M1-I) ────────────────────
        # ★원계열 둘이 다 있을 때만 계산한다★ 하나라도 없으면 사유를 남기고 값을 내지
        # 않는다 — 한쪽만으로 스프레드를 만드는 것은 합성이다.
        series_map["KR_CREDIT_SPREAD"] = self._derive_spread(
            series_map.get("KR_CORP3Y"), series_map.get("KR_3Y"))

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

    def _derive_spread(self, corp: MacroSeries | None,
                       govt: MacroSeries | None) -> MacroSeries:
        """신용스프레드 = 회사채3Y − 국고3Y (M1-I).

        ★한쪽만으로 만들지 않는다★ 둘 중 하나라도 없거나 겹치는 관측이 없으면 값 없이
        `source="unavailable"` 로 돌려준다. 한쪽 값을 스프레드처럼 쓰면 그건 합성이고,
        화면은 그것을 실측 스프레드로 읽는다.
        """
        key, name, unit = "KR_CREDIT_SPREAD", "신용스프레드(회사채3Y − 국고3Y)", "%p"
        cv = list(corp.values) if corp and corp.values else []
        gv = list(govt.values) if govt and govt.values else []
        n = min(len(cv), len(gv))
        if n == 0:
            return MacroSeries(indicator=key, name=name, unit=unit,
                               source="unavailable", timestamps=[], values=[])

        vals = [round(float(c) - float(g), 4) for c, g in zip(cv[-n:], gv[-n:], strict=False)]
        ts = list(corp.timestamps)[-n:] if corp and corp.timestamps else []
        norm = _normalize(vals)
        latest = vals[-1]
        prev = vals[-2] if len(vals) >= 2 else None
        yoy = (vals[-1] - vals[-13]) if len(vals) >= 13 else None   # %p 단위 → 차이
        return MacroSeries(
            indicator=key, name=name, unit=unit,
            # 원계열이 mock 이면 파생도 mock 이다 — 출처를 승격시키지 않는다.
            source=(corp.source if corp else "unavailable"),
            timestamps=ts, values=vals,
            latest=round(latest, 4), prev=(round(prev, 4) if prev is not None else None),
            yoy=(round(yoy, 3) if yoy is not None else None),
            mom_pct=None,
            z_score=norm["z_score"], percentile=norm["percentile"],
            mean_5y=norm["mean_5y"], std_5y=norm["std_5y"], trend=norm["trend"],
        )

    def _collect_one(
        self, key: str, name: str, unit: str,
        fetcher, use_cache: bool, source: str,
    ) -> MacroSeries:
        """단일 지표 수집 — 캐시 확인 → 외부 호출 → Mock fallback.

        ★신규 미검증 소스는 mock 으로 채우지 않는다 (M1-I)★
        `source_registry.new_source_mock_allowed()` 가 판정한다. 기존 지표는 영향 없다.
        """
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

        # Fallback to Mock — mock 모드만. 운영(KIS_USE_MOCK=0)선 합성 금지 → 정직 unavailable.
        if not values:
            from src.data.mock_gate import mock_allowed
            from src.data.source_registry import new_source_mock_allowed
            if mock_allowed() and new_source_mock_allowed(key):
                profile = MOCK_PROFILES.get(key, {"base": 100, "vol": 5, "trend": 0})
                # ★mock 길이는 깊이를 따라가지 **않는다** (P4-D3 에서 시도했다 되돌림)★
                #
                # 처음엔 `length=_history_years() * 12` 로 바꿔 mock 도 240개월을 내게
                # 했다. 파이프라인이 20년치를 감당하는지 개발 환경에서 확인하려는
                # 의도였고, D4 의 출처 조건이 있으니 합성으로 프론티어가 열릴 위험도
                # 없었다. 그런데 **실측해 보니 값이 비쌌다.**
                #
                # mock 은 드리프트 있는 랜덤워크(`cur += trend + gauss(0, vol)`)라
                # 구간이 3배가 되면 합성 국면이 DEFENSIVE·고스트레스로 치우치고,
                # 타이밍 노출이 0 으로 떨어져 `test_three_way_endpoint::
                # test_a_real_snapshot_does_not_zero_out_exposure` 를 깨뜨렸다.
                # 그 테스트는 과거 실제 사고(단위/어휘 불일치로 포트폴리오가 전액
                # 위험-오프로 떨어진 것)를 막는 가드라 약화시킬 수 없다.
                #
                # 얻는 것과 잃는 것을 견줬다 — 얻는 것은 "mock 으로도 240 경로를
                # 밟아 본다" 뿐이고, 잃는 것은 합성 국면 상태의 안정성이다.
                # **깊이가 실제로 필요한 곳은 실 데이터 경로다**(키가 들어오면
                # BOK/FRED 가 수십 년을 준다). mock 은 그대로 둔다.
                timestamps, values = _generate_mock_series(
                    key, length=60, **profile,
                )
                actual_source = "MOCK"
            else:
                actual_source = "unavailable"   # 운영 — 실 BOK/FRED 미수신(키 미설정/실패) → "—"

        # 정규화 + 메트릭
        clean = [v for v in values if v is not None and not math.isnan(v)]
        norm = _normalize(clean)
        latest = clean[-1] if clean else None
        prev = clean[-2] if len(clean) >= 2 else None
        # YoY: 금리 등 %단위는 %p 차이, 지수/레벨형은 % 변화 (이전엔 지수도 점차로 빼던 버그)
        if len(clean) >= 13:
            yoy = (clean[-1] - clean[-13]) if unit == "%" \
                else ((clean[-1] / clean[-13] - 1) * 100 if clean[-13] > 0 else None)
        else:
            yoy = None
        mom_pct = ((clean[-1] - clean[-2]) / clean[-2] * 100) \
            if (len(clean) >= 2 and clean[-2] != 0) else None

        series = MacroSeries(
            indicator=key, name=name, unit=unit, source=actual_source,
            # ★저장 상한을 적재 깊이에 맞춘다 (P4-D3)★
            # 예전에는 `[-72:]` 하드코딩이었다. 사유("YoY 변환 후에도 5년 z-표본 확보")는
            # **하한**의 근거지 상한의 근거가 아닌데 상한으로 쓰이고 있었다. 그 결과
            # `MACRO_HISTORY_YEARS` 를 20으로 올려도 저장 단계에서 72로 잘려,
            # `frontier_sample`(240) 은 **어떤 설정으로도 열릴 수 없었다.**
            # 깊이에서 유도하되 72 아래로는 내려가지 않게 해 기존 z-표본 가정을 지킨다.
            timestamps=timestamps[-_store_cap():],
            values=clean[-_store_cap():] if clean else [],
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

    def connection_status(self) -> dict:
        """매크로 실연결 점검 — 소스별 키 설정 + 모드. 운영서 키 없으면 지표 'unavailable'."""
        from src.data.mock_gate import mock_allowed
        allow = mock_allowed()
        return {
            "mock_allowed": allow,
            "real_mode": not allow,
            "bok_configured": self.bok.is_configured,
            "fred_configured": self.fred.is_configured,
            "note": ("mock 모드 — 키 없으면 합성 MOCK 서빙"
                     if allow else
                     "운영 모드 — 실 BOK/FRED만, 미설정 지표는 unavailable(정직 '—')"),
        }
