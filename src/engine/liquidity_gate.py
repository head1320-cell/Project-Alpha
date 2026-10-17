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
        """★mock 게이트를 통과한다★ — 예전에는 통과하지 않았다.

        운영(`KIS_USE_MOCK != "1"`)에서도 아래 합성 경로를 그대로 타서, **날조된
        거래대금·스프레드로 실제 종목을 유니버스에서 떨어뜨리고 있었다**. 특히
        `tradable = self._uniform(code, "halt") > 0.1` 은 소형주의 10%를 종목코드
        해시로 "거래정지" 판정했다(실측: 시총 300억 200종목 중 13개).

        게이트는 `screener.py` 에서 **모든 필터보다 먼저·기본으로 켜진 채** 돌기
        때문에, 이 합성값이 그 뒤의 모든 분석의 모집단을 정했다.

        ★mock 경로는 한 글자도 바꾸지 않았다★ — 아래 `_mock_liquidity` 는 예전
        `_build_liquidity` 본문 그대로다. 개발 기본값이 `KIS_USE_MOCK=1` 이므로
        기존 테스트·골든이 전부 그 가지를 지나고, 통과 종목 집합이 동일해야 한다.
        """
        from src.data.mock_gate import mock_allowed
        if mock_allowed():
            return self._mock_liquidity(stock_code, market_cap_억)
        return self._real_liquidity(stock_code, market_cap_억)

    def _real_liquidity(self, stock_code: str, market_cap_억: float | None) -> dict:
        """운영 경로 — ★아는 것만 채우고 모르는 것은 `None` 이다★

        `None` 은 `passes_liquidity` 에서 **그 조건을 건너뛴다**는 뜻이다(그 함수는
        이미 그렇게 동작한다). 즉 근거가 없으면 배제하지 않는다 — 없는 근거로
        배제하는 것도 날조이기 때문이다.

        ★스프레드는 항상 `None` 이다★ 이 저장소 어디에도 호가 실데이터 원천이
        없다(모든 `spread` 가 `rng.uniform`). 없는 것을 만들어 내는 대신 조건을
        적용하지 않고, 그 사실을 `apply_liquidity_gate` 가 사유로 노출한다.
        """
        return {
            "adv_value_억": self._real_adv(stock_code),
            # ★합성 폴백을 제거했다★ 예전엔 시총을 모르면 `_normal(...)` 로 지어냈고,
            # 그 값이 곧바로 `min_market_cap_억` 임계와 비교됐다.
            "market_cap_억": (round(market_cap_억, 1)
                              if market_cap_억 and market_cap_억 > 0 else None),
            "spread_pct": None,
            "is_tradable": self._real_tradable(stock_code),
            "_source": "liquidity_real",
        }

    #: `PriceFactorsStore.get_factors` 의 캐시 키 형식. ★조회만 하고 만들지 않는다★
    _PF_CACHE_KEY = "price_factors:{code}"

    @classmethod
    def _real_adv(cls, stock_code: str) -> float | None:
        """20일 평균거래대금(억) — ★이미 계산된 것만 읽는다. 만들지 않는다★

        `price_factors_store.amount_20d_avg` 는 사전적재 일봉에서 계산되고 이미
        mock 게이트를 지킨다(키 없으면 `None`). 게이트는 그것을 무시하고 한 모듈
        옆에서 같은 숫자를 날조하고 있었다.

        ★`get_factors()` 를 부르지 않는 이유★
        ─────────────────────────────────────────────────────────────────────
        처음엔 그냥 불렀다. 그러자 테스트가 잡았다 — 캐시가 비어 있으면
        `_build_factors` → `_fetch_ohlcv` 로 내려가고, 사전적재 `daily_prices` 가
        없으면 **종목당 KIS 를 친다**. 게이트는 모든 필터보다 먼저 **유니버스
        전체**를 도므로 수백~수천 종목 × 1콜이 되고, 이 저장소는 그 사고를 이미
        겪었다(`extended_factors_store` 의 `live=True` 독스트링: *"수백 종목×3콜로
        요청이 프론트 프록시 타임아웃을 넘겨 502가 났다"*).

        그래서 **캐시 히트만** 쓴다. 파이프라인이 가격 팩터를 데워 두었으면 실값을
        얻고, 아니면 `None`(미상) — 그 조건은 적용되지 않는다. ★모르는 것을
        비싸게 알아내려 하지 않는다★.
        """
        try:
            from src.data.price_factors_store import PriceFactorsStore
            store = PriceFactorsStore.get_default()
            # ★네임스페이스 규칙을 복제하지 않는다★ — `_scoped()` 가 단일 출처다.
            # 캐시 키는 `mock`/`real` 로 갈린다(`2aff832` 후속). 여기서 형식을
            # 다시 조립하면 상류가 규칙을 바꿀 때 조용히 어긋난다.
            entry = store._cache.get(
                store._scoped(cls._PF_CACHE_KEY.format(code=stock_code)))
            if not entry or not entry[1]:
                return None
            return entry[1].get("amount_20d_avg")
        except Exception:
            return None

    @staticmethod
    def _real_tradable(stock_code: str) -> bool | None:
        """거래 가능 여부 — KIS 마스터 플래그. ★데이터가 없으면 `None`(미상)★

        `universe_select._status_codes()` 와 **같은 seam** 을 쓴다 — 플래그가
        적재돼 있으면 채워지고, 없으면 빈 집합이라 아무도 배제하지 않는다.
        `False`(거래정지 확인)와 `None`(모름)은 다른 사실이다.
        """
        try:
            from src.data import stock_master as sm
            managed = set(getattr(sm, "MANAGED_CODES", []) or [])
            if not managed and not sm.load_master_flags():
                return None                      # 적재된 근거가 없다
            code = str(stock_code).split(".")[0]
            if code in {str(c).split(".")[0] for c in managed}:
                return False
            flags = sm.load_master_flags().get(code)
            if flags is None:
                return None
            return not (flags.get("is_halted") or flags.get("is_managed"))
        except Exception:
            return None

    def _mock_liquidity(self, stock_code: str, market_cap_억: float | None) -> dict:
        """★예전 `_build_liquidity` 본문 그대로★ — 이름만 옮겼다(값 불변).

        `mock_allowed()` 일 때만 불린다. 개발 화면이 도는 근거이고, 여기서 값을
        바꾸면 기존 테스트·골든이 통째로 달라진다.
        """
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

    # 거래 가능성 — ★`None`(미상)은 배제 사유가 아니다★
    #
    # 예전에는 `not liq_data.get("is_tradable", True)` 였다. 그 관용구는 키가
    # **없을 때만** 기본값을 쓴다 — 키가 있고 값이 `None` 이면 `None` 을 돌려주고
    # `not None` 은 `True` 라 **전부 배제**된다. 아래 세 조건은 전부 `is not None`
    # 으로 미상을 건너뛰는데 여기만 달랐고, 합성 경로에서는 항상 bool 이라
    # 드러나지 않았다. 운영 경로가 정직하게 `None` 을 내자마자 터진다.
    tradable = liq_data.get("is_tradable")
    if floor.require_tradable and tradable is False:
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
    # ★어느 조건이 실제로 검사됐는지 센다★ 값이 `None` 인 조건은 `passes_liquidity`
    # 가 건너뛴다. 그것을 말하지 않으면 침묵이 두 가지를 뜻하게 된다 —
    # "검사했고 통과" 와 "검사하지 못함" 이 화면에서 똑같아 보인다.
    checked = {"adv_value_억": 0, "market_cap_억": 0, "spread_pct": 0, "is_tradable": 0}
    for it in items:
        code = getattr(it, "stock_code", None)
        if not code:
            continue
        mcap = getattr(it, "market_cap_억", None)
        liq = store.get_liquidity(code, mcap)
        for f in checked:
            v = mcap if (f == "market_cap_억" and mcap is not None) else liq.get(f)
            if v is not None:
                checked[f] += 1
        if passes_liquidity(it, floor, liq):
            # 유동성 메트릭을 item에 부착 (UI 표시용). ★`None` 일 수 있다★ —
            # 운영에서 원천이 없으면 지어내지 않으므로, 소비자가 "—" 로 그린다.
            it._adv_value_억 = liq.get("adv_value_억")
            it._spread_pct = liq.get("spread_pct")
            passed.append(it)

    return passed, {
        "applied": True,
        "before": len(items),
        "after": len(passed),
        "filtered_out": len(items) - len(passed),
        "floor": floor.to_dict(),
        "checked_counts": dict(checked),
        "skipped_conditions": _skipped_conditions(checked, len(items)),
    }


#: 조건별 미적용 사유 — ★"검사하지 못함" 을 "통과" 처럼 보이게 두지 않는다★
_SKIP_REASONS = {
    "spread_pct": ("호가 스프레드 실데이터 원천이 없습니다 — 이 조건을 적용하지 "
                   "않았습니다. 게이트가 스프레드를 검사했다고 오해하지 마십시오."),
    "adv_value_억": ("거래대금을 얻지 못했습니다(사전적재 일봉 없음) — 이 조건을 "
                     "적용하지 않았습니다."),
    "market_cap_억": "시가총액을 얻지 못했습니다 — 이 조건을 적용하지 않았습니다.",
    "is_tradable": ("거래정지·관리종목 플래그가 적재되지 않았습니다 — 이 조건을 "
                    "적용하지 않았습니다."),
}


def _skipped_conditions(checked: dict, total: int) -> dict:
    """한 종목도 검사하지 못한 조건 → 사유. ★부분적으로라도 검사했으면 넣지 않는다★

    "일부만 값이 있었다" 와 "아예 검사하지 못했다" 는 다른 상태다. 전자까지 여기
    넣으면 사유가 늘 떠 있어서 아무도 읽지 않게 된다.
    """
    if not total:
        return {}
    return {f: r for f, r in _SKIP_REASONS.items() if checked.get(f, 0) == 0}


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
