"""
Liquidity & Tradability Gate — Screener V3 Phase 1.5
==========================================================================
★ 기관급 툴의 핵심 ★ — 모든 필터보다 "먼저, 가장 무겁게" 적용되는 hard gate.

문제 (Gemini 지적):
  화려한 팩터 필터를 통과해도, 시총 500억 소형주에 호가 스프레드 2%면
  백테스트 수익률은 환상. 슬리피지·거래비용으로 실제 계좌는 녹아내림.

해결:
  M1~M6 어떤 필터보다 먼저 유동성 게이트를 통과시킴.
  · adv_value_억   — 20일 평균 거래대금 (억원)
  · market_cap_억  — 시가총액 (이미 ScreenerItem 보유)
  · spread_pct     — 호가 스프레드 (%)
  · is_tradable    — 거래정지/관리종목 여부

레이어 구조 (M0 철학 계승):
  Gate(거래 가능성) → Condition(kind 디스패처) → Analyzer(후처리)

기관급 디폴트: liquidity_floor가 기본 ON. 리테일이 비유동 종목에
물리는 것을 구조적으로 차단.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.data.mock_base import DeterministicMockStore

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# 유동성 프로파일 (기관 등급별 프리셋)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class LiquidityFloor:
    """유동성 하한 기준."""
    min_adv_value_억: float = 10.0      # 20일 평균 거래대금 ≥ 10억
    min_market_cap_억: float = 1000.0   # 시총 ≥ 1000억
    max_spread_pct: float = 0.5         # 호가 스프레드 ≤ 0.5%
    require_tradable: bool = True        # 거래정지/관리종목 제외

    def to_dict(self) -> dict:
        return {
            "min_adv_value_억": self.min_adv_value_억,
            "min_market_cap_억": self.min_market_cap_억,
            "max_spread_pct": self.max_spread_pct,
            "require_tradable": self.require_tradable,
        }


# 기관 등급별 프리셋
LIQUIDITY_PROFILES = {
    "off": None,  # 게이트 비활성 (리테일 — 비권장)
    "relaxed": LiquidityFloor(min_adv_value_억=3, min_market_cap_억=300, max_spread_pct=1.0),
    "standard": LiquidityFloor(min_adv_value_억=10, min_market_cap_억=1000, max_spread_pct=0.5),
    "institutional": LiquidityFloor(min_adv_value_억=50, min_market_cap_억=5000, max_spread_pct=0.3),
}


# ═══════════════════════════════════════════════════════════════════════════════
# 유동성 데이터 (Mock — DeterministicMockStore 상속)
# ═══════════════════════════════════════════════════════════════════════════════

class LiquidityStore(DeterministicMockStore):
    """유동성 메트릭 제공 (Mock + KIS 시세 연결 여지)."""

    _singleton: LiquidityStore | None = None

    @classmethod
    def get_default(cls) -> LiquidityStore:
        if cls._singleton is None:
            cls._singleton = cls()
        return cls._singleton

    def get_liquidity(self, stock_code: str, market_cap_억: float | None = None) -> dict:
        """단일 종목의 유동성 메트릭 (캐시 + 결정론적)."""
        return self.cached(
            f"liq:{stock_code}:{market_cap_억}",
            lambda: self._build_liquidity(stock_code, market_cap_억),
        )

    def _build_liquidity(self, stock_code: str, market_cap_억: float | None) -> dict:
        # 시총이 클수록 거래대금↑·스프레드↓ (현실적 상관)
        mcap = market_cap_억 if market_cap_억 and market_cap_억 > 0 else \
               abs(self._normal(stock_code, "mcap", mu=5000, sigma=8000)) + 200

        # ADV는 시총의 0.1~1.5% 수준 (회전율 변동)
        turnover = self._uniform(stock_code, "turnover", lo=0.001, hi=0.015)
        adv_value = round(mcap * turnover, 1)

        # 스프레드: 시총 클수록 좁음 (역상관). 대형주 0.05%, 소형주 2%+
        if mcap >= 10000:
            spread = self._uniform(stock_code, "spread", lo=0.02, hi=0.15)
        elif mcap >= 1000:
            spread = self._uniform(stock_code, "spread", lo=0.1, hi=0.6)
        else:
            spread = self._uniform(stock_code, "spread", lo=0.5, hi=2.5)

        # 거래정지/관리종목 (소형주에서 드물게)
        tradable = True
        if mcap < 500:
            tradable = self._uniform(stock_code, "halt") > 0.1  # 10% 확률 비거래

        return {
            "adv_value_억":  adv_value,
            "market_cap_억": round(mcap, 1),
            "spread_pct":    round(spread, 3),
            "is_tradable":   tradable,
            "_source":       "liquidity_mock",
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Gate 적용 (모든 필터보다 먼저)
# ═══════════════════════════════════════════════════════════════════════════════

def passes_liquidity(item, floor: LiquidityFloor, liq_data: dict) -> bool:
    """단일 종목이 유동성 게이트를 통과하는지."""
    if floor is None:
        return True

    # 거래 가능성
    if floor.require_tradable and not liq_data.get("is_tradable", True):
        return False

    # 거래대금
    adv = liq_data.get("adv_value_억")
    if adv is not None and adv < floor.min_adv_value_억:
        return False

    # 시총 (ScreenerItem 우선, 없으면 liq_data)
    mcap = getattr(item, "market_cap_억", None) or liq_data.get("market_cap_억")
    if mcap is not None and mcap < floor.min_market_cap_억:
        return False

    # 스프레드
    spread = liq_data.get("spread_pct")
    if spread is not None and spread > floor.max_spread_pct:
        return False

    return True


def apply_liquidity_gate(items: list, floor: LiquidityFloor) -> tuple[list, dict]:
    """
    유동성 게이트 적용. 모든 kind 필터보다 먼저 호출.

    Returns:
        (통과 종목 리스트, 게이트 통계)
    """
    if floor is None:
        return items, {"applied": False, "before": len(items), "after": len(items), "filtered_out": 0}

    store = LiquidityStore.get_default()
    passed = []
    for it in items:
        code = getattr(it, "stock_code", None)
        if not code:
            continue
        mcap = getattr(it, "market_cap_억", None)
        liq = store.get_liquidity(code, mcap)
        if passes_liquidity(it, floor, liq):
            # 유동성 메트릭을 item에 부착 (UI 표시용)
            it._adv_value_억 = liq["adv_value_억"]
            it._spread_pct = liq["spread_pct"]
            passed.append(it)

    return passed, {
        "applied": True,
        "before": len(items),
        "after": len(passed),
        "filtered_out": len(items) - len(passed),
        "floor": floor.to_dict(),
    }


def resolve_floor(profile_or_floor) -> LiquidityFloor | None:
    """문자열 프로파일명 또는 dict → LiquidityFloor."""
    if profile_or_floor is None:
        return None
    if isinstance(profile_or_floor, LiquidityFloor):
        return profile_or_floor
    if isinstance(profile_or_floor, str):
        return LIQUIDITY_PROFILES.get(profile_or_floor, LIQUIDITY_PROFILES["standard"])
    if isinstance(profile_or_floor, dict):
        return LiquidityFloor(**{k: v for k, v in profile_or_floor.items() if k in LiquidityFloor.__dataclass_fields__})
    return LIQUIDITY_PROFILES["standard"]


def liquidity_profiles_catalog() -> dict:
    """API용 유동성 프로파일 카탈로그."""
    return {
        "profiles": [
            {"id": "off", "label": "게이트 끔", "description": "유동성 제약 없음 (비권장 — 소형주 슬리피지 위험)"},
            {"id": "relaxed", "label": "완화", "description": "ADV≥3억·시총≥300억·스프레드≤1%"},
            {"id": "standard", "label": "표준 (권장)", "description": "ADV≥10억·시총≥1000억·스프레드≤0.5%"},
            {"id": "institutional", "label": "기관급", "description": "ADV≥50억·시총≥5000억·스프레드≤0.3%"},
        ],
        "default": "standard",
    }
