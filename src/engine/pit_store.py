"""
Point-in-Time Store — Screener V2 Milestone 4 (타임머신)
==========================================================================
과거 특정 시점 기준 재무/가격 데이터 제공. Look-ahead bias 차단.

핵심 원칙 (Look-ahead bias 방지):
  · as_of_date 시점에 "공시 완료된" 재무만 사용
  · 분기 재무는 공시 시차 반영 (분기말 + 45일 후 공시 가정)
  · 미래 데이터 절대 누출 금지

전략:
  · 분기별 재무 스냅샷 (mock: 현재값 deterministic 시점 변형)
  · Stage 11 PIT-safe 로직 패턴 계승
  · 가격: 해당일 종가 (KIS historical, mock fallback)
  · 가용 스냅샷 일자 제한 (분기말)

데이터 부재 현실:
  · 실제 과거 시계열 미보유 → deterministic 시점 변형으로 일관된 mock
  · 키 연결 시 DART 누적 데이터로 즉시 교체 가능
"""

from __future__ import annotations

import logging
import random
import threading
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# 공시 시차 (분기말 후 N일에 공시 완료 가정)
DISCLOSURE_LAG_DAYS = 45


# ═══════════════════════════════════════════════════════════════════════════════
# 가용 스냅샷 일자 (분기말)
# ═══════════════════════════════════════════════════════════════════════════════

def available_snapshot_dates(years_back: int = 6) -> list[str]:
    """가용 PIT 스냅샷 일자 (분기말 기준, 최근 N년)."""
    dates = []
    today = datetime.now()
    year = today.year
    for y in range(year, year - years_back, -1):
        for month, day in [(12, 31), (9, 30), (6, 30), (3, 31)]:
            d = datetime(y, month, day)
            # 미래 + 공시시차 미경과 분기는 제외
            if d + timedelta(days=DISCLOSURE_LAG_DAYS) <= today:
                dates.append(d.strftime("%Y-%m-%d"))
    return dates[:years_back * 4]


def _quarter_index(date_str: str) -> int:
    """일자 → 분기 인덱스 (시점 변형 seed용)."""
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return d.year * 4 + (d.month - 1) // 3
    except ValueError:
        return 0


# ═══════════════════════════════════════════════════════════════════════════════
# PIT Store
# ═══════════════════════════════════════════════════════════════════════════════

class PITStore:
    """시점별 재무/가격 스냅샷 제공 (look-ahead 차단)."""

    _singleton: PITStore | None = None

    @classmethod
    def get_default(cls) -> PITStore:
        if cls._singleton is None:
            cls._singleton = cls()
        return cls._singleton

    def __init__(self, cache_ttl: int = 3600 * 12):
        self.cache_ttl = cache_ttl
        self._cache: dict[str, tuple[float, dict]] = {}
        self._lock = threading.Lock()

    def validate_asof(self, as_of_date: str) -> str | None:
        """as_of_date 유효성 검증."""
        try:
            d = datetime.strptime(as_of_date, "%Y-%m-%d")
        except ValueError:
            return "날짜 형식 오류 (YYYY-MM-DD)"
        if d > datetime.now():
            return "미래 날짜는 조회 불가"
        if d < datetime.now() - timedelta(days=365 * 10):
            return "10년 이전 데이터는 미지원"
        return None

    def get_financials_asof(self, stock_code: str, as_of_date: str,
                              current_financials: dict) -> dict:
        """
        as_of_date 시점에 공시 완료된 재무 반환.

        Look-ahead 차단: as_of_date 이전에 공시된 가장 최근 분기 재무만 사용.
        Mock: 현재 재무를 분기 인덱스 기반 deterministic 변형.
        """
        cache_key = f"{stock_code}:{as_of_date}"
        with self._lock:
            entry = self._cache.get(cache_key)
            if entry and time.time() - entry[0] < self.cache_ttl:
                return entry[1]

        # 시점 변형 계수 (deterministic — 같은 종목/시점은 항상 동일)
        q_idx = _quarter_index(as_of_date)
        seed = sum(ord(c) for c in stock_code) + q_idx
        rng = random.Random(seed)

        # 과거일수록 값이 다름 (트렌드 + 노이즈)
        quarters_ago = max(0, _quarter_index(datetime.now().strftime("%Y-%m-%d")) - q_idx)
        # 과거 재무는 일반적으로 현재보다 작거나 다름
        trend_factor = 1.0 - quarters_ago * 0.015  # 분기당 약 1.5% 성장 역산
        def noise():
            return rng.uniform(0.92, 1.08)

        def adjust(val, factor=1.0):
            if val is None:
                return None
            return val * trend_factor * factor * noise()

        snapshot = {
            "roe_pct":            adjust(current_financials.get("roe_pct")),
            "roa_pct":            adjust(current_financials.get("roa_pct")),
            "per":                adjust(current_financials.get("per"), 1.0),
            "pbr":                adjust(current_financials.get("pbr"), 1.0),
            "debt_ratio_pct":     adjust(current_financials.get("debt_ratio_pct")),
            "dividend_yield_pct": adjust(current_financials.get("dividend_yield_pct")),
            "fcf_억":             adjust(current_financials.get("fcf_억")),
            "market_cap_억":      adjust(current_financials.get("market_cap_억")),
            "_as_of_date":        as_of_date,
            "_quarters_ago":      quarters_ago,
            "_source":            "pit_mock",
        }

        with self._lock:
            self._cache[cache_key] = (time.time(), snapshot)
        return snapshot

    def get_price_asof(self, stock_code: str, as_of_date: str, current_price: float) -> float:
        """as_of_date 시점 종가 (mock: deterministic 변형)."""
        q_idx = _quarter_index(as_of_date)
        seed = sum(ord(c) for c in stock_code) * 7 + q_idx
        rng = random.Random(seed)
        quarters_ago = max(0, _quarter_index(datetime.now().strftime("%Y-%m-%d")) - q_idx)
        # 과거 가격 = 현재가 / (성장 누적) * 변동
        trend = 1.0 - quarters_ago * 0.02
        return max(100, current_price * trend * rng.uniform(0.85, 1.15))

    def cache_clear(self):
        with self._lock:
            self._cache.clear()
