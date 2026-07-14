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
# 연간(사업보고서)은 결산 후 90일 이내 제출 — 보수적으로 90일 시차 적용
ANNUAL_LAG_DAYS = 90

# DART 보고서 코드
REPRT_ANNUAL, REPRT_HALF, REPRT_Q1, REPRT_Q3 = "11011", "11012", "11013", "11014"


def _period_asof(as_of_date: str, annual_only: bool = False) -> tuple[str, str] | None:
    """as_of 시점에 공시 완료된 가장 최근 보고서 → (bsns_year, reprt_code).

    분기말 + 공시시차(분기 45일 / 연간 90일) 경과 여부로 판별 — look-ahead 차단.
    예: 2024-05-20 → 2024 1Q(3/31+45=5/15 공시완료, 11013)
        2024-05-10 → 2023 연간(12/31+90=3/31 공시완료, 11011)

    annual_only=True면 연간(11011) 후보만 고려 — RIM/DCF/DDM처럼 연간 재무 기준
    지표(eps/bps/fcf/dps)를 쓰는 호출부용. 분기 코드를 그대로 넘기면
    get_financial_statement_full이 항상 연간(11011)으로 조회하면서(reprt_code
    미전달) compute_ratios가 분기 누적치를 연환산 없이 그대로 써 밸류에이션이
    왜곡되거나, 아직 미공시 연도라 데이터 없음이 되는 문제를 방지."""
    try:
        d = datetime.strptime(as_of_date, "%Y-%m-%d")
    except ValueError:
        return None
    candidates = []
    for y in range(d.year, d.year - 3, -1):
        candidates += [
            (datetime(y, 12, 31), str(y), REPRT_ANNUAL, ANNUAL_LAG_DAYS),
            (datetime(y, 9, 30), str(y), REPRT_Q3, DISCLOSURE_LAG_DAYS),
            (datetime(y, 6, 30), str(y), REPRT_HALF, DISCLOSURE_LAG_DAYS),
            (datetime(y, 3, 31), str(y), REPRT_Q1, DISCLOSURE_LAG_DAYS),
        ]
    candidates.sort(key=lambda x: x[0], reverse=True)
    for q_end, year, reprt, lag in candidates:
        if annual_only and reprt != REPRT_ANNUAL:
            continue
        if q_end + timedelta(days=lag) <= d:
            return (year, reprt)
    return None


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

        # 실데이터 우선: DART 키 설정 시 해당 시점 공시 재무로 스냅샷 (실패 시 mock 폴백)
        real = self._dart_snapshot(stock_code, as_of_date)
        if real is not None:
            with self._lock:
                self._cache[cache_key] = (time.time(), real)
            return real

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

    def _dart_snapshot(self, stock_code: str, as_of_date: str) -> dict | None:
        """실데이터 PIT 스냅샷 — ① 적재된 financials_history(DB, 키 불필요·즉시)
        ② 실시간 DART(키 필요) 순. 둘 다 실패 시 None(mock 폴백).

        재무제표에서 직접 산출 가능한 비율(ROE/ROA/부채비율)만 실값으로 채운다.
        가격 의존 지표(PER/PBR/배당수익률/시총)는 역사 시세 미연동이라 None —
        소비자(screener._apply_pit)는 None 필드를 교체하지 않으므로 부분 적용된다."""
        period = _period_asof(as_of_date)
        if period is None:
            return None
        year, reprt = period

        def _pack(row: dict, source: str) -> dict | None:
            """재무 행 + as_of 시총([C] KRX 적재) → PIT 스냅샷.

            손익은 연환산(분기 누적 보정) — ROE/PER이 연간 기준과 비교 가능.
            PER/PBR/시총은 시총 시계열이 있을 때만 실값(없으면 None — 부분 적용),
            적자(연환산 순이익 ≤ 0)면 PER은 None(무의미)."""
            from src.data.dart_history import annualized_net_income, ratios_from_row
            ratios = ratios_from_row(row, reprt)
            if ratios.get("roe_pct") is None and ratios.get("debt_ratio_pct") is None:
                return None
            per = pbr = mktcap_억 = None
            try:
                from src.engine.universe_select import mktcap_asof
                mktcap = mktcap_asof(stock_code, as_of_date)  # 원 (KRX)
            except Exception:
                mktcap = None
            if mktcap and mktcap > 0:
                mktcap_억 = mktcap / 1e8
                ni_ann = annualized_net_income(row, reprt)    # 원 (DART)
                equity = row.get("total_equity")
                if ni_ann is not None and ni_ann > 0:
                    per = mktcap / ni_ann
                if equity is not None and equity > 0:
                    pbr = mktcap / equity
            return {
                "roe_pct": ratios.get("roe_pct"),
                "roa_pct": ratios.get("roa_pct"),
                "per": per,
                "pbr": pbr,
                "debt_ratio_pct": ratios.get("debt_ratio_pct"),
                "dividend_yield_pct": None,
                "fcf_억": None,
                "market_cap_억": mktcap_억,
                "_as_of_date": as_of_date,
                "_report": f"{year}/{reprt}",
                "_annualized": reprt != REPRT_ANNUAL,
                "_source": source,
            }

        # ① DB 적재분 (dart_history 백필 후 — DART 키·쿼터 무소모)
        try:
            from src.data.dart_history import history_snapshot
            row = history_snapshot(stock_code, year, reprt)
            if row is not None:
                snap = _pack(row, "pit_db")
                if snap is not None:
                    return snap
        except Exception as e:
            logger.debug(f"PIT DB snapshot 실패 ({stock_code}@{as_of_date}): {e}")

        # ② 실시간 DART 폴백
        try:
            from src.data.dart_client import DARTClient, get_corp_code
            client = DARTClient()
            if not client.is_configured:
                return None
            corp = get_corp_code(stock_code)
            if not corp:
                return None
            fs = client.get_financial_statement_full(corp, year, reprt_code=reprt)
            if fs is None or fs.total_equity is None:
                return None
            row = {"net_income": fs.net_income, "total_equity": fs.total_equity,
                   "total_assets": fs.total_assets, "total_liabilities": fs.total_liabilities}
            return _pack(row, "pit_dart")
        except Exception as e:
            logger.debug(f"PIT DART snapshot 실패 ({stock_code}@{as_of_date}): {e}")
            return None

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
