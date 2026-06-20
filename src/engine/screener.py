"""
Multi-Model Stock Screener — 전 종목 가치평가 + 저평가 우량주 자동 추출
==========================================================================
RIM + DCF + DDM 통합 가치평가를 전 종목에 병렬 적용 → 정량 점수화 → 필터링.

핵심 컴포넌트:
  · Universe 관리 — KOSPI50/KOSPI200/KOSDAQ150 + 커스텀
  · 병렬 평가 — ThreadPool (DART rate limit 고려, max_workers=4)
  · Composite Score — 저평가 60% + 수익성 20% + 안정성 20%
  · LRU + TTL 캐싱 — 동일 종목 재평가 방지 (1시간)
  · 필터 — 시총/업종/괴리율/배당/ROE/PBR 등

스코어링 공식:
  gap_score    = clamp(-gap_pct × 2, 0, 100)   # -50% → 100점, +50% → 0점
  roe_score    = clamp(roe_pct × 3.33, 0, 100) # ROE 0~30% → 0~100
  stability    = avg(debt_score, fcf_score)    # 부채/잉여현금흐름
  composite    = gap × 0.6 + roe × 0.2 + stab × 0.2

방어적 프로그래밍:
  · 단일 종목 평가 실패 → 결과에서 제외 (전체 중단 X)
  · DART API 실패 → MockClient 자동 fallback
  · 캐시 무한 증가 방지 (max 500개)
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime

from src.data.dart_client import STOCK_TO_CORP, DARTClient, get_corp_code
from src.engine.valuation.valuation_models import (
    UnifiedValuation,
    ValuationEngine,
    ValuationParams,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Universe Presets
# ═══════════════════════════════════════════════════════════════════════════════

# Mock universes — 실거래시 KRX/Tinkoff API에서 동적 수집 가능
KOSPI50_TICKERS = [
    "005930", "000660", "035420", "035720", "373220", "051910", "006400",
    "207940", "005380", "068270", "323410", "000270", "105560", "055550",
    "035250", "012330", "066570", "003670", "005490", "017670", "030200",
    "086790", "032830", "316140", "024110", "138040", "138930", "036570",
    "010130", "402340", "267260", "011200", "078930", "010950", "267250",
    "047050", "009150", "028260", "034730", "032640", "010140", "086280",
    "018260", "036460", "008770", "071050", "009830", "139480", "021240", "047810",
]

# KOSPI 200 = 중앙 종목 마스터의 실제 종목코드 (Unknown Corp 박멸)
def _build_kospi200():
    try:
        from src.data.stock_master import REAL_KOSPI_TICKERS
        # KOSPI50 + 마스터의 나머지 실제 종목 (중복 제거, 200개 목표)
        seen = set(KOSPI50_TICKERS)
        extra = [t for t in REAL_KOSPI_TICKERS if t not in seen]
        return KOSPI50_TICKERS + extra
    except Exception:
        return KOSPI50_TICKERS
KOSPI200_TICKERS = _build_kospi200()

KOSDAQ150_TICKERS = [
    "247540", "086520", "091990", "066970", "022100", "035900",
    "263750", "041510", "112040", "196170", "067310", "095660",
    "293490", "240810", "058470", "121600", "078340", "215000",
] + [f"{i:06d}" for i in range(200000, 200132)]

# 주요 ETF (지수·섹터·테마·채권·원자재) — DART 재무 없음(가격·수급 팩터로 스크리닝).
# 종목명 단일 소스(stock_master.ETF_NAMES)에서 코드 목록 도출 → 이름 100% 해소.
def _build_etf_tickers() -> list[str]:
    try:
        from src.data.stock_master import ETF_NAMES
        return list(ETF_NAMES.keys())
    except Exception:
        return []
ETF_TICKERS = _build_etf_tickers()

UNIVERSE_PRESETS: dict[str, list[str]] = {
    "kospi50":    KOSPI50_TICKERS,
    "kospi200":   KOSPI200_TICKERS,
    "kosdaq150":  KOSDAQ150_TICKERS,
    "etf":        ETF_TICKERS,
    "mapped":     list(STOCK_TO_CORP.keys()),    # DART corp_code 매핑된 종목만
}


def get_sector_universe() -> dict[str, list[str]]:
    """업종별 종목 매핑 {업종명: [종목코드]} 반환 (stock_master 기반)."""
    from src.data.stock_master import STOCK_SECTOR
    out: dict[str, list[str]] = {}
    for code, sector in STOCK_SECTOR.items():
        out.setdefault(sector, []).append(code)
    return out


def resolve_universe(universe: str | list[str]) -> list[str]:
    """universe 식별자를 종목 리스트로 해석.

    · 리스트 → 그대로
    · "sector:반도체" → 해당 업종 종목
    · "kospi200" 등 프리셋 → 프리셋 종목
    """
    if isinstance(universe, list):
        return universe
    if isinstance(universe, str) and universe.startswith("sector:"):
        sector = universe.split(":", 1)[1]
        return get_sector_universe().get(sector, [])
    if isinstance(universe, str) and universe in ("all", "all_listed"):
        # 전체 상장 종목: DART corpCode 매핑(~3,970, 디스크 캐시) 우선 →
        # KIS 마스터 ST 플래그 → kospi200 폴백.
        try:
            from src.data.dart_client import _load_full_corp_map
            codes = list(_load_full_corp_map().keys())
            if len(codes) >= 200:
                return codes
        except Exception:
            pass
        try:
            from src.data.stock_master import load_master_flags
            flags = load_master_flags()
            if flags:
                st = [c for c, f in flags.items() if (f.get("group_code") or "ST") == "ST"]
                if st:
                    return st
        except Exception:
            pass
        return UNIVERSE_PRESETS.get("kospi200", KOSPI200_TICKERS)
    return UNIVERSE_PRESETS.get(universe, KOSPI200_TICKERS)


# ═══════════════════════════════════════════════════════════════════════════════
# Filter + Result Models
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ScreenerFilters:
    """필터 조건. None = 무제한."""
    min_market_cap_억:   float | None = None
    max_market_cap_억:   float | None = None
    min_roe_pct:         float | None = None
    max_roe_pct:         float | None = None
    min_gap_pct:         float | None = None         # 음수 = 저평가
    max_gap_pct:         float | None = None
    min_per:             float | None = None
    max_per:             float | None = None
    min_pbr:             float | None = None
    max_pbr:             float | None = None
    min_dividend_yield:  float | None = None
    max_debt_ratio:      float | None = None
    sectors:             list[str] | None = None     # ["반도체", "인터넷"]
    require_positive_fcf: bool = False
    verdicts:            list[str] | None = None     # ["저평가", "극심한 저평가"]


@dataclass
class ScreenerItem:
    """단일 종목 스크리닝 결과."""
    stock_code:        str
    corp_name:         str
    sector:            str | None

    current_price:     float
    intrinsic_value:   float
    gap_pct:           float
    verdict:           str

    composite_score:   float
    gap_score:         float
    roe_score:         float
    stability_score:   float

    # 핵심 재무 지표
    roe_pct:           float | None
    roa_pct:           float | None
    per:               float | None
    pbr:               float | None
    debt_ratio_pct:    float | None
    dividend_yield_pct: float | None
    market_cap_억:     float | None
    fcf_억:            float | None

    # 3-모델 적정가 (Price-Value Band 차트용)
    rim_value:         float | None = None
    dcf_value:         float | None = None
    ddm_value:         float | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        # FFL: 동적 부착된 펀더멘털 팩터도 포함 (dataclass 필드 외 속성)
        try:
            from src.data.fundamentals_store import FACTOR_BY_ID
            for fid in FACTOR_BY_ID:
                if hasattr(self, fid):
                    d[fid] = getattr(self, fid)
        except Exception:
            pass
        # 가격·수급 팩터도 포함
        try:
            from src.data.price_factors_store import PRICE_FACTOR_BY_ID
            for fid in PRICE_FACTOR_BY_ID:
                if hasattr(self, fid):
                    d[fid] = getattr(self, fid)
        except Exception:
            pass
        return d


@dataclass
class ScreenerResult:
    """스크리닝 전체 결과."""
    universe:           str
    total_evaluated:    int
    total_passed:       int
    items:              list[ScreenerItem]
    elapsed_seconds:    float
    cache_hits:         int
    cache_misses:       int
    failures:           int
    timestamp:          str = field(default_factory=lambda: datetime.now().isoformat())


def sort_screener_items(
    items: list,
    sort_by: str,
    ascending: bool = False,
    sort_by_secondary: str | None = None,
    sort_secondary_ascending: bool = False,
) -> None:
    """스크리닝 결과 제자리 정렬 — 1차/2차 키 + 동점 시 stock_code(결정적).

    안정 정렬을 역순으로 3회 적용: stock_code → 2차 키 → 1차 키.
    방향(asc/desc)을 키별로 독립 지정할 수 있다 (매수 우선순위 1차/2차 정렬).
    """
    if not items or not sort_by:
        return
    items.sort(key=lambda x: x.stock_code)
    if sort_by_secondary:
        items.sort(
            key=lambda x: getattr(x, sort_by_secondary, 0) or 0,
            reverse=not sort_secondary_ascending,
        )
    items.sort(
        key=lambda x: getattr(x, sort_by, 0) or 0,
        reverse=not ascending,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# LRU + TTL Cache
# ═══════════════════════════════════════════════════════════════════════════════

class _ValuationCache:
    """종목별 평가 결과 캐시 (메모리, TTL + LRU)."""

    def __init__(self, max_size: int = 500, ttl_seconds: int = 3600):
        self.max_size = max_size
        self.ttl = ttl_seconds
        self._data: dict[str, tuple[float, UnifiedValuation]] = {}
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> UnifiedValuation | None:
        with self._lock:
            entry = self._data.get(key)
            if not entry:
                self.misses += 1
                return None
            ts, value = entry
            if time.time() - ts > self.ttl:
                self._data.pop(key, None)
                self.misses += 1
                return None
            self.hits += 1
            return value

    def set(self, key: str, value: UnifiedValuation):
        with self._lock:
            # LRU eviction
            if len(self._data) >= self.max_size:
                oldest_key = min(self._data, key=lambda k: self._data[k][0])
                self._data.pop(oldest_key, None)
            self._data[key] = (time.time(), value)

    def stats(self) -> dict:
        with self._lock:
            total = self.hits + self.misses
            return {
                "size": len(self._data),
                "max_size": self.max_size,
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": self.hits / total if total > 0 else 0,
                "ttl_seconds": self.ttl,
            }

    def clear(self):
        with self._lock:
            self._data.clear()
            self.hits = 0
            self.misses = 0


# ═══════════════════════════════════════════════════════════════════════════════
# Multi-Model Stock Screener
# ═══════════════════════════════════════════════════════════════════════════════

class ValuationScreener:
    """
    전 종목 가치평가 기반 스크리너.

    Usage:
        screener = ValuationScreener(
            dart_client=DARTClient(),
            valuation_engine=ValuationEngine(),
        )

        result = screener.run(
            universe="kospi50",
            filters=ScreenerFilters(min_roe_pct=5, max_gap_pct=0),
            sort_by="composite_score",
            limit=30,
        )

        for item in result.items:
            print(f"{item.corp_name}: {item.composite_score:.1f}점, "
                  f"괴리율 {item.gap_pct:+.1f}%")
    """

    def __init__(
        self,
        dart_client: DARTClient | None = None,
        valuation_engine: ValuationEngine | None = None,
        price_provider: Callable[[str], float] | None = None,
        cache_ttl: int = 3600,
        max_workers: int = 4,
    ):
        self.dart = dart_client or DARTClient()
        self.engine = valuation_engine or ValuationEngine(self.dart)
        self.price_provider = price_provider or self._mock_price
        self.cache = _ValuationCache(ttl_seconds=cache_ttl)
        self.max_workers = max_workers

    # ─────────────────────────────────────────────────────────────────────
    # 핵심: run
    # ─────────────────────────────────────────────────────────────────────

    def run(
        self,
        universe: str | list[str] = "kospi50",
        filters: ScreenerFilters | None = None,
        sort_by: str = "composite_score",
        ascending: bool = False,
        sort_by_secondary: str | None = None,       # 2차 정렬 키 (동점 타이브레이크)
        sort_secondary_ascending: bool = False,
        limit: int = 50,
        params: ValuationParams | None = None,
        filter_ast=None,            # M1: FilterGroup (있으면 우선, ScreenerFilters와 병행 — 하위호환)
        use_macro: bool = False,    # M3: 현재 국면 기반 동적 Composite 가중치
        as_of_date: str | None = None,  # V2-M4: PIT 스크리닝 기준일 (look-ahead 차단)
        liquidity_floor=None,       # V3-P1.5: 유동성 게이트 ("standard"|"off"|dict, 기본 standard)
        progress_cb=None,           # 진행 콜백 (done, total, misses) — SSE 스트리밍 진행표시용
    ) -> ScreenerResult:
        """
        전체 파이프라인:
          1. Universe 결정
          2. 병렬 평가 (RIM + DCF + DDM)
          3. Composite Score 계산
          4. 필터 적용
          5. 정렬 + 제한
        """
        start_ts = time.time()
        filters = filters or ScreenerFilters()
        params = params or ValuationParams()

        # M3: Regime-Aware 가중치 설정
        self._active_regime = None
        if use_macro:
            try:
                from src.engine.regime_analyzer import get_regime_state
                state = get_regime_state()
                self._active_weights = self._regime_weights(state.regime)
                self._active_regime = state.regime
            except Exception as e:
                logger.warning(f"Macro 가중치 조회 실패, 기본값 사용: {e}")
                self._active_weights = (0.6, 0.2, 0.2)
        else:
            self._active_weights = (0.6, 0.2, 0.2)

        # V2-M4: PIT 기준일 설정 (look-ahead 차단)
        self._active_asof = as_of_date

        # 1. Universe
        tickers = self._resolve_universe(universe)
        if not tickers:
            return ScreenerResult(
                universe=str(universe), total_evaluated=0, total_passed=0,
                items=[], elapsed_seconds=0,
                cache_hits=0, cache_misses=0, failures=0,
            )

        # 2. 병렬 평가
        cache_start = self.cache.hits
        miss_start = self.cache.misses
        items: list[ScreenerItem] = []
        failures = 0

        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            future_to_ticker = {
                ex.submit(self._evaluate_one_safe, ticker, params): ticker
                for ticker in tickers
            }
            done = 0
            total = len(tickers)
            step = max(1, total // 100)   # 진행 이벤트 최대 ~100개로 throttle
            for future in as_completed(future_to_ticker):
                ticker = future_to_ticker[future]
                try:
                    item = future.result()
                    if item:
                        items.append(item)
                    else:
                        failures += 1
                except Exception as e:
                    logger.error(f"종목 {ticker} 평가 실패: {e}")
                    failures += 1
                done += 1
                if progress_cb is not None and (done % step == 0 or done == total):
                    try:
                        progress_cb(done, total, self.cache.misses - miss_start)
                    except Exception:
                        pass

        cache_hits = self.cache.hits - cache_start
        cache_misses = self.cache.misses - miss_start

        # 3. 필터 적용
        # ★ V3-P1.5: 유동성 게이트 — 모든 필터보다 먼저, 가장 무겁게 (기관급 디폴트)
        #   기본값 standard. 명시적 "off"일 때만 비활성.
        from src.engine.liquidity_gate import apply_liquidity_gate, resolve_floor
        floor = resolve_floor(liquidity_floor if liquidity_floor is not None else "standard")
        items, self._liquidity_stats = apply_liquidity_gate(items, floor)

        # ★ 실데이터: KIS 실시세로 시총·PER·PBR 보강 (KIS_USE_MOCK=0 + 키 설정 시)
        #   시총이 펀더멘털 팩터(EV/EBITDA, FCF Yield 등) 계산의 입력이므로 먼저 주입
        try:
            self._enrich_kis_quotes(items)
        except Exception as e:
            logger.debug(f"KIS 시세 보강 실패 (mock 유지): {e}")

        # ★ FFL: 펀더멘털 팩터 주입 (게이트 통과 종목에만 — lazy 효율)
        #   50+ 학술 팩터를 ScreenerItem에 동적 속성으로 부착 → field kind가 getattr로 접근
        try:
            from src.data.fundamentals_store import attach_fundamentals
            attach_fundamentals(items)
            from src.data.price_factors_store import attach_price_factors
            attach_price_factors(items)
        except Exception as e:
            logger.debug(f"펀더멘털 주입 실패: {e}")

        # 4. 필터 적용 — filter_ast(M1) 우선, 없으면 기존 ScreenerFilters (하위호환)
        if filter_ast is not None and not filter_ast.is_empty():
            from src.engine.filter_ast import apply_filter_ast
            filtered = apply_filter_ast(items, filter_ast)
        else:
            filtered = [it for it in items if self._matches_filters(it, filters)]

        # 4. 정렬
        if sort_by and filtered:
            try:
                sort_screener_items(filtered, sort_by, ascending,
                                    sort_by_secondary, sort_secondary_ascending)
            except Exception as e:
                logger.warning(f"정렬 실패 ({sort_by}): {e}")

        # 5. 제한
        return ScreenerResult(
            universe=str(universe) if isinstance(universe, str) else f"custom({len(tickers)})",
            total_evaluated=len(tickers),
            total_passed=len(filtered),
            items=filtered[:limit],
            elapsed_seconds=round(time.time() - start_ts, 3),
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            failures=failures,
        )

    # ─────────────────────────────────────────────────────────────────────
    # 캐싱 + 안전 평가
    # ─────────────────────────────────────────────────────────────────────

    def _evaluate_one_safe(
        self, stock_code: str, params: ValuationParams,
    ) -> ScreenerItem | None:
        """단일 종목 평가 — 예외 전파 X. V2-M4: as_of_date면 PIT 평가."""
        try:
            asof = getattr(self, "_active_asof", None)
            # cache_key에 as_of 포함 (PIT/현재 캐시 혼선 방지)
            cache_key = f"{stock_code}:{params.beta}:{params.projection_years}:{asof or 'now'}"
            uv = self.cache.get(cache_key)
            if uv is None:
                price = self._get_price_safe(stock_code)
                if asof:
                    # PIT: 해당 시점 가격으로 변환
                    try:
                        from src.engine.pit_store import PITStore
                        price = PITStore.get_default().get_price_asof(stock_code, asof, price)
                    except Exception:
                        pass
                uv = self.engine.evaluate(stock_code, price, params)
                self.cache.set(cache_key, uv)

            item = self._to_item(uv, stock_code)
            # V2-M4: PIT 시점 재무로 ScreenerItem 필드 후처리
            if asof and item is not None:
                item = self._apply_pit_financials(item, stock_code, asof)
            return item
        except Exception as e:
            logger.debug(f"평가 실패 ({stock_code}): {e}")
            return None

    def _apply_pit_financials(self, item: ScreenerItem, stock_code: str, asof: str) -> ScreenerItem:
        """V2-M4: ScreenerItem의 재무 지표를 PIT 시점값으로 교체 (look-ahead 차단)."""
        try:
            from src.engine.pit_store import PITStore
            cur = {
                "roe_pct": item.roe_pct, "roa_pct": item.roa_pct,
                "per": item.per, "pbr": item.pbr,
                "debt_ratio_pct": item.debt_ratio_pct,
                "dividend_yield_pct": item.dividend_yield_pct,
                "fcf_억": item.fcf_억, "market_cap_억": item.market_cap_억,
            }
            snap = PITStore.get_default().get_financials_asof(stock_code, asof, cur)
            for f in ["roe_pct","roa_pct","per","pbr","debt_ratio_pct","dividend_yield_pct","fcf_억","market_cap_억"]:
                if snap.get(f) is not None:
                    setattr(item, f, round(snap[f], 2))
        except Exception:
            pass
        return item

    def _get_price_safe(self, stock_code: str) -> float:
        try:
            return self.price_provider(stock_code)
        except Exception:
            return self._mock_price(stock_code)

    # ─────────────────────────────────────────────────────────────────────
    # Composite Score (60/20/20)
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def _regime_weights(regime: str) -> tuple[float, float, float]:
        """
        국면별 Composite 가중치 (gap, roe, stability).
          Goldilocks  — 성장주 유리: ROE 가중↑
          Reflation   — 가치/경기민감: gap 가중↑
          Stagflation — 방어/배당: stability 가중↑
          Deflation   — 안정성 최우선: stability 가중↑
        """
        WEIGHTS = {
            "Goldilocks":  (0.50, 0.35, 0.15),
            "Reflation":   (0.60, 0.25, 0.15),
            "Stagflation": (0.55, 0.15, 0.30),
            "Deflation":   (0.50, 0.20, 0.30),
        }
        return WEIGHTS.get(regime, (0.60, 0.20, 0.20))

    def _compute_scores(self, uv: UnifiedValuation) -> tuple[float, float, float, float]:
        """
        (composite, gap_score, roe_score, stability_score)
        모두 0~100 스케일.
        """
        fin = uv.financial_summary

        # 1. Gap Score: 저평가일수록 점수 高
        # gap_pct -50% → 100점, 0% → 50점, +50% → 0점
        gap_pct = uv.gap_pct or 0
        gap_score = max(0.0, min(100.0, 50 - gap_pct))
        # 포화(100) 시 gap_pct 깊이를 미세 반영 — 동일점수 붕괴 방지(mock에서도 종목 변별)
        # -50%→+0, -100%→+5 가산 (순위 보존, 상한 살짝 초과 허용 후 합산서 정규화)
        gap_depth_bonus = max(0.0, (-gap_pct - 50.0)) * 0.1 if gap_pct < -50 else 0.0

        # 2. ROE Score: 0~30% → 0~100
        roe = fin.get("roe_pct") or 0
        roe_score = max(0.0, min(100.0, roe * 3.33))

        # 3. Stability Score
        # · Debt ratio: 0% → 100점, 200%+ → 0점
        debt = fin.get("debt_ratio_pct")
        if debt is not None:
            debt_score = max(0.0, min(100.0, 100 - debt / 2))
        else:
            debt_score = 50.0

        # · FCF positive 보너스
        fcf = fin.get("fcf_억")
        fcf_score = 80.0 if (fcf is not None and fcf > 0) else 30.0

        stability_score = (debt_score + fcf_score) / 2

        # 4. Composite (60/20/20)
        # M3: Regime-Aware 동적 가중치 (없으면 기본 60/20/20)
        w_gap, w_roe, w_stab = getattr(self, "_active_weights", (0.6, 0.2, 0.2))
        composite = (gap_score + gap_depth_bonus) * w_gap + roe_score * w_roe + stability_score * w_stab

        return (
            round(composite, 2),
            round(gap_score, 2),
            round(roe_score, 2),
            round(stability_score, 2),
        )

    # ─────────────────────────────────────────────────────────────────────
    # Item 변환
    # ─────────────────────────────────────────────────────────────────────

    def _enrich_kis_quotes(self, items: list) -> int:
        """
        KIS 실시세로 시총·PER·PBR·현재가 보강 (KIS_USE_MOCK=0 + 키 설정 시).
        시총은 펀더멘털 팩터 계산의 입력이므로 fundamentals 주입 전에 호출.
        mock 모드면 즉시 반환 (외부 호출 없음).
        Returns: 보강된 종목 수
        """
        import os
        if os.getenv("KIS_USE_MOCK", "1") == "1":
            return 0
        try:
            from src.execution.kis_client import get_kis_client
        except Exception:
            return 0
        client = get_kis_client()
        # MockKISClient면 보강 의미 없음
        if type(client).__name__ == "MockKISClient":
            return 0

        # 대용량 유니버스(전종목) 보호: 실시세 보강은 요청당 상한까지만 (KIS 폭주 방지).
        max_enrich = int(os.getenv("SCREENER_MAX_LIVE_COMPUTE", "400"))
        n = 0
        for it in items[:max_enrich]:
            code = getattr(it, "stock_code", None)
            if not code:
                continue
            try:
                q = client.get_price(code)
                cp = q.get("current_price")
                if cp and cp > 0:
                    it.current_price = cp
                mc = q.get("market_cap_억")
                if mc and mc > 0:
                    it.market_cap_억 = mc
                if q.get("per") is not None:
                    it.per = q["per"]
                if q.get("pbr") is not None:
                    it.pbr = q["pbr"]
                n += 1
            except Exception:
                continue
        if n:
            logger.info(f"KIS 실시세 보강: {n}종목")
        return n

    def _to_item(self, uv: UnifiedValuation, stock_code: str) -> ScreenerItem:
        composite, gap, roe_s, stab = self._compute_scores(uv)
        fin = uv.financial_summary

        # 3-모델 적정가
        rim_val = dcf_val = ddm_val = None
        for m in uv.models:
            if m.available and m.intrinsic_value_per_share > 0:
                if m.model == "RIM":
                    rim_val = m.intrinsic_value_per_share
                elif m.model == "DCF":
                    dcf_val = m.intrinsic_value_per_share
                elif m.model == "DDM":
                    ddm_val = m.intrinsic_value_per_share

        # Market cap (= 발행주식수 × 현재가)
        market_cap = None
        # 발행주식수는 financial_statement에 있지만 summary에 없으므로 추정 생략

        # Sector — DART corp_info에서
        sector = None
        try:
            corp_code = get_corp_code(stock_code)
            if corp_code:
                info = self.dart.get_corp_info(corp_code)
                sector = info.sector if info else None
        except Exception:
            pass

        # 종목명 해소: 마스터 우선 → uv.corp_name → fallback (Unknown Corp 박멸)
        from src.data.stock_master import get_stock_name, get_stock_sector
        resolved_name = (get_stock_name(stock_code)
                         or (uv.corp_name if uv.corp_name and uv.corp_name != "Unknown Corp" else None)
                         or f"종목 {stock_code}")
        resolved_sector = sector or get_stock_sector(stock_code)

        return ScreenerItem(
            stock_code=stock_code,
            corp_name=resolved_name,
            sector=resolved_sector,
            current_price=uv.current_price,
            intrinsic_value=uv.intrinsic_value,
            gap_pct=uv.gap_pct,
            verdict=uv.verdict,
            composite_score=composite,
            gap_score=gap,
            roe_score=roe_s,
            stability_score=stab,
            roe_pct=fin.get("roe_pct"),
            roa_pct=fin.get("roa_pct"),
            per=fin.get("per"),
            pbr=fin.get("pbr"),
            debt_ratio_pct=fin.get("debt_ratio_pct"),
            dividend_yield_pct=fin.get("dividend_yield_pct"),
            market_cap_억=market_cap,
            fcf_억=fin.get("fcf_억"),
            rim_value=rim_val,
            dcf_value=dcf_val,
            ddm_value=ddm_val,
        )

    # ─────────────────────────────────────────────────────────────────────
    # Filter
    # ─────────────────────────────────────────────────────────────────────

    def _matches_filters(self, item: ScreenerItem, f: ScreenerFilters) -> bool:
        # ROE
        if f.min_roe_pct is not None and (item.roe_pct or -999) < f.min_roe_pct:
            return False
        if f.max_roe_pct is not None and (item.roe_pct or 999) > f.max_roe_pct:
            return False

        # Gap
        if f.min_gap_pct is not None and item.gap_pct < f.min_gap_pct:
            return False
        if f.max_gap_pct is not None and item.gap_pct > f.max_gap_pct:
            return False

        # PER
        if f.min_per is not None and (item.per or 0) < f.min_per:
            return False
        if f.max_per is not None and (item.per or 9999) > f.max_per:
            return False

        # PBR
        if f.min_pbr is not None and (item.pbr or 0) < f.min_pbr:
            return False
        if f.max_pbr is not None and (item.pbr or 9999) > f.max_pbr:
            return False

        # Dividend yield
        if f.min_dividend_yield is not None and \
            (item.dividend_yield_pct or 0) < f.min_dividend_yield:
            return False

        # Debt ratio
        if f.max_debt_ratio is not None and \
            (item.debt_ratio_pct or 0) > f.max_debt_ratio:
            return False

        # Sectors
        if f.sectors and item.sector not in f.sectors:
            return False

        # FCF positive
        if f.require_positive_fcf and (item.fcf_억 or 0) <= 0:
            return False

        # Verdicts
        if f.verdicts and item.verdict not in f.verdicts:
            return False

        return True

    # ─────────────────────────────────────────────────────────────────────
    # Universe
    # ─────────────────────────────────────────────────────────────────────

    def _resolve_universe(self, universe: str | list[str]) -> list[str]:
        if isinstance(universe, list):
            return universe[:5000]  # 안전 제한 (관심그룹/커스텀)
        # 전종목: 적재된 DB 종목과 연동 — 적재(ingest)가 늘면 유니버스도 자동 확장.
        #   (적재 종목은 디스크/DB 캐시라 빠르게 평가 / 미적재 실시간 폭주 방지)
        if isinstance(universe, str) and universe in ("all", "all_listed"):
            try:
                from src.data.snapshot_db import enabled, ingested_codes
                if enabled():
                    codes = ingested_codes()
                    if len(codes) >= 30:
                        return codes
            except Exception:
                pass
        # sector:, etf, 프리셋, (적재 전)all_listed → DART corpCode 전체 등 일관 처리
        return resolve_universe(universe)

    # ─────────────────────────────────────────────────────────────────────
    # Mock price provider
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def _mock_price(stock_code: str) -> float:
        """현재가 데이터 — 실제 운영 시 KIS API 또는 외부 시세 사용."""
        MOCK_PRICES: dict[str, float] = {
            "005930": 71000,    "000660": 200000,
            "035420": 175000,   "035720": 42000,
            "373220": 380000,   "051910": 380000,
            "006400": 280000,   "207940": 850000,
            "005380": 230000,   "068270": 165000,
        }
        if stock_code in MOCK_PRICES:
            return MOCK_PRICES[stock_code]
        # Random 안정적 fallback (deterministic by hash)
        h = sum(ord(c) for c in stock_code)
        return float(10_000 + (h * 137) % 200_000)

    # ─────────────────────────────────────────────────────────────────────
    # 캐시 관리
    # ─────────────────────────────────────────────────────────────────────

    def cache_stats(self) -> dict:
        return self.cache.stats()

    def cache_clear(self):
        self.cache.clear()
