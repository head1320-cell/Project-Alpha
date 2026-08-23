"""
Macro Regime Analyzer — Phase 4
==========================================================================
4-Quadrant 국면 판별 + Market Stress Index + Yield Curve 분석.

핵심 컴포넌트:
  · GrowthInflationQuadrant — 성장 × 물가 축으로 4국면 판별
  · MarketStressIndex (0-100) — 환율 변동성 + 신용 스프레드 + 금리 급변
  · YieldCurveAnalyzer — 3M ~ 30Y 곡선 + 역전 감지
  · RegimeTransition — 국면 전이 추적

연동:
  · ValuationParams: risk_free_rate 자동 갱신 (KR_10Y)
  · KillSwitch: Adaptive threshold (stress index 높을 때 더 민감)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from src.services.macro_collector import MacroCollector, MacroSeries, MacroSnapshot

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Regime Models
# ═══════════════════════════════════════════════════════════════════════════════

REGIME_DESCRIPTIONS = {
    "Goldilocks":   "성장↑ + 물가↓ — 위험자산 최적 (성장주 우위)",
    "Reflation":    "성장↑ + 물가↑ — 원자재/금융주 우위, 채권 회피",
    "Stagflation":  "성장↓ + 물가↑ — 현금/금/단기채 방어",
    "Disinflation": "성장↓ + 물가↓(상승 둔화) — 장기채/방어주 우위",
}

REGIME_TILTS = {
    "Goldilocks":   {"growth_stocks": "+", "value_stocks": "-", "bonds": "-", "commodities": "0", "cash": "-"},
    "Reflation":    {"growth_stocks": "0", "value_stocks": "+", "bonds": "--", "commodities": "++", "cash": "0"},
    "Stagflation":  {"growth_stocks": "-", "value_stocks": "0", "bonds": "-", "commodities": "+", "cash": "++"},
    "Disinflation": {"growth_stocks": "-", "value_stocks": "0", "bonds": "++", "commodities": "--", "cash": "+"},
}


@dataclass
class RegimeState:
    """현재 매크로 국면 + 시장 스트레스."""
    timestamp:           str
    regime:              str                    # Goldilocks/Reflation/Stagflation/Disinflation
    growth_axis:         float                  # -3.0 ~ +3.0 (Z-Score)
    inflation_axis:      float                  # -3.0 ~ +3.0
    confidence:          float                  # 0-1 (분류 신뢰도)

    # Stress Index
    stress_score:        float                  # 0-100
    stress_components:   dict = field(default_factory=dict)

    # Yield Curve
    yield_curve:         dict = field(default_factory=dict)
    yield_inversion:     bool = False
    inversion_severity:  float | None = None  # spread bp

    # Risk mode 권고
    recommended_mode:    str = "NORMAL"          # NORMAL/CAUTIOUS/DEFENSIVE
    asset_tilts:         dict = field(default_factory=dict)
    description:         str = ""
    market:              str = "kr"              # 분석 대상 시장 (kr | us)

    # 동적 파라미터 (다른 모듈에 주입할 값)
    dynamic_risk_free_rate:  float | None = None
    dynamic_kill_dd_threshold: float | None = None

    # v2: 축 분해(지표별 변환 z·가중·기여 — "CPI 레벨 z vs 축" 표시 모순의 투명화) + 확률
    axis_detail:         dict = field(default_factory=dict)   # {"growth": {...}, "inflation": {...}}
    regime_probs:        dict = field(default_factory=dict)   # {사분면: P} 합=1


# ═══════════════════════════════════════════════════════════════════════════════
# Regime Analyzer
# ═══════════════════════════════════════════════════════════════════════════════

class RegimeAnalyzer:
    """
    4-Quadrant 매크로 국면 판별기.

    Usage:
        analyzer = RegimeAnalyzer()
        state = analyzer.analyze()    # 자동으로 collector에서 최신 데이터 수집
        print(f"현재 국면: {state.regime}, 스트레스: {state.stress_score}")
    """

    def __init__(self, collector: MacroCollector | None = None):
        self.collector = collector or MacroCollector.get_default()

    # ─────────────────────────────────────────────────────────────────────
    # 메인 분석
    # ─────────────────────────────────────────────────────────────────────

    def analyze(self, snapshot: MacroSnapshot | None = None, market: str = "kr") -> RegimeState:
        snapshot = snapshot or self.collector.collect_all()
        s = snapshot.series

        # 실데이터 부족 점검 — 운영서 매크로가 전부 unavailable이면 허위 국면 분류 금지(정직).
        real_count = sum(1 for v in s.values()
                         if getattr(v, "source", "") != "unavailable" and v.latest is not None)
        insufficient = real_count < 3

        # 1-2. Growth/Inflation Axis — regime_axes 단일 정의 (지수형은 YoY 변환 후 z,
        #      레벨+3개월 모멘텀 블렌드). 지표별 분해·불확실성(se)까지 수집(투명화).
        from src.engine.regime_axes import AXES, compute_axis_detail, quadrant_probs
        g_def, i_def = AXES.get(market, AXES["kr"])
        g_detail = compute_axis_detail(s, g_def)
        i_detail = compute_axis_detail(s, i_def)
        growth_axis = g_detail["score"]
        inflation_axis = i_detail["score"]

        # 3. Regime 판별 — 데이터 부족 시 허위 국면 대신 '데이터 부족'.
        #    신뢰도 = 최대 사분면 확률(축 불확실성 기반 — 정적 tanh 대체).
        probs = quadrant_probs(growth_axis, inflation_axis, g_detail["se"], i_detail["se"])
        if insufficient:
            regime, confidence = "데이터 부족", 0.0
        else:
            regime = self._classify_regime(growth_axis, inflation_axis)
            confidence = max(probs.values())

        # 4. Market Stress Index
        stress_score, stress_components = self._compute_stress(s)

        # 5. Yield Curve
        yield_curve, inversion, inversion_severity = self._analyze_yield_curve(s)

        # 6. 권고 모드
        if stress_score >= 70 or regime == "Stagflation":
            mode = "DEFENSIVE"
        elif stress_score >= 50 or inversion:
            mode = "CAUTIOUS"
        else:
            mode = "NORMAL"

        # 7. 동적 파라미터
        kr_10y = s.get("KR_10Y")
        dynamic_rf = (kr_10y.latest / 100) if kr_10y and kr_10y.latest else 0.035

        # Adaptive Kill Switch DD threshold (스트레스 ↑ → 더 민감하게)
        # 기본 -10% → stress 100일 때 -5%
        base_dd = 0.10
        adaptive_dd = base_dd - (stress_score / 100) * 0.05
        dynamic_dd = round(adaptive_dd, 4)

        return RegimeState(
            timestamp=snapshot.timestamp,
            regime=regime,
            growth_axis=round(growth_axis, 3),
            inflation_axis=round(inflation_axis, 3),
            confidence=round(confidence, 3),
            market=market,
            stress_score=round(stress_score, 2),
            stress_components=stress_components,
            yield_curve=yield_curve,
            yield_inversion=inversion,
            inversion_severity=inversion_severity,
            recommended_mode=mode,
            asset_tilts=REGIME_TILTS.get(regime, {}),
            description=("실 매크로 데이터 부족 — BOK/FRED 키 설정 후 국면 분류 (현재 지표 unavailable)"
                        if insufficient else REGIME_DESCRIPTIONS.get(regime, "")),
            dynamic_risk_free_rate=dynamic_rf,
            dynamic_kill_dd_threshold=dynamic_dd,
            axis_detail={"growth": g_detail, "inflation": i_detail},
            regime_probs=probs,
        )

    # ─────────────────────────────────────────────────────────────────────
    # Regime 분류 — 축 계산은 regime_axes(단일 정의)에서 수행
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def _classify_regime(growth: float, inflation: float) -> str:
        """4-Quadrant 분류 — 사분면 명칭은 regime_axes.quadrant 공용."""
        from src.engine.regime_axes import quadrant
        return quadrant(growth, inflation)

    # ─────────────────────────────────────────────────────────────────────
    # Market Stress Index
    # ─────────────────────────────────────────────────────────────────────

    def _compute_stress(self, s: dict[str, MacroSeries]) -> tuple[float, dict]:
        """
        스트레스 지수 0-100 (v2 — CIO 리팩토링).
        구성: VIX(25%) + Credit(20%) + FX변동성(15%) + 금리변동성(10%) + DXY(5%)
              + ★수익률곡선 10Y-2Y(15%, 역전 패널티) + ★실질금리 z(10%)
        v1은 곡선·실질금리 항이 없어 '실질금리 +1.7σ 긴축인데 Normal 44'가 났음 —
        시장가 기반 선행 리스크(커브·실질금리)를 합성 지수에 내재화.
        """
        components = {}
        total_score = 0.0
        total_weight = 0.0

        def score_z(z: float | None) -> float:
            """Z-Score → 0-100 (높을수록 스트레스). z=0 → 50, z=2 → 90."""
            if z is None:
                return 50.0
            return max(0, min(100, 50 + z * 20))

        def add(name: str, score: float | None, weight: float):
            nonlocal total_score, total_weight
            if score is None:
                return
            components[name] = round(score, 1)
            total_score += score * weight
            total_weight += weight

        # 1. VIX (높을수록 스트레스)
        vix = s.get("VIXCLS")
        if vix and vix.z_score is not None:
            add("vix", score_z(vix.z_score), 0.25)

        # 2. Credit Spread
        credit = s.get("BAMLH0A0HYM2")
        if credit and credit.z_score is not None:
            add("credit_spread", score_z(credit.z_score), 0.20)

        # 3. USD/KRW 변동성 (Z-Score)
        usdkrw = s.get("USD_KRW")
        if usdkrw and usdkrw.z_score is not None:
            add("fx_volatility", score_z(abs(usdkrw.z_score)), 0.15)

        # 4. 금리 변동성 (KR_10Y mom_pct)
        kr_10y = s.get("KR_10Y")
        if kr_10y and kr_10y.mom_pct is not None:
            add("rate_volatility", max(0, min(100, abs(kr_10y.mom_pct) * 8 + 40)), 0.10)

        # 5. DXY (강달러 = EM 스트레스)
        dxy = s.get("DTWEXBGS")
        if dxy and dxy.z_score is not None:
            add("dxy_strength", score_z(max(0, dxy.z_score)), 0.05)

        # 6. ★수익률곡선(10Y-2Y): 평탄/역전 = 침체 선행 신호. spread +1.5% → ~20(완화),
        #    0% → 58, 역전(-0.6%) → 58+15+13 ≈ 86 상한 100.
        t2, t10 = s.get("DGS2"), s.get("DGS10")
        if t2 and t10 and t2.latest is not None and t10.latest is not None:
            spread = t10.latest - t2.latest
            curve_score = max(0.0, min(100.0, 58 - spread * 25 + (15 if spread < 0 else 0)))
            add("yield_curve", curve_score, 0.15)

        # 7. ★실질금리(10Y − 기대인플레) 레벨 z: 급긴축(실질금리 급등)이 숨은 리스크.
        if t10 and s.get("T10YIE"):
            from src.engine.regime_axes import zscore_at
            t10_vals = list(getattr(t10, "values", None) or [])
            tie_vals = list(getattr(s["T10YIE"], "values", None) or [])
            n = min(len(t10_vals), len(tie_vals))
            real = [(a - b) if (a is not None and b is not None) else None
                    for a, b in zip(t10_vals[-n:], tie_vals[-n:])]
            rz = zscore_at(real)
            if rz is not None:
                add("real_rate", score_z(rz), 0.10)

        final = total_score / total_weight if total_weight > 0 else 50.0
        return final, components

    # ─────────────────────────────────────────────────────────────────────
    # Yield Curve (3M ~ 30Y)
    # ─────────────────────────────────────────────────────────────────────

    def _analyze_yield_curve(self, s: dict[str, MacroSeries]) -> tuple[dict, bool, float | None]:
        """
        US Treasury Yield Curve + 역전 감지.
        """
        curve_points = []
        maturity_map = [
            ("3M",  "DGS3MO",  0.25),
            ("2Y",  "DGS2",    2.0),
            ("10Y", "DGS10",   10.0),
            ("30Y", "DGS30",   30.0),
        ]

        for label, key, years in maturity_map:
            series = s.get(key)
            if series and series.latest is not None:
                curve_points.append({
                    "label": label,
                    "years": years,
                    "yield_pct": series.latest,
                    "trend": series.trend,
                })

        # 역전 감지 (2Y-10Y)
        t2y = s.get("DGS2")
        t10y = s.get("DGS10")
        inversion = False
        severity = None
        if t2y and t10y and t2y.latest is not None and t10y.latest is not None:
            spread = t10y.latest - t2y.latest
            severity = spread * 100  # bp
            inversion = spread < 0

        return {
            "points":   curve_points,
            "spread_2y10y_bp":  severity,
        }, inversion, severity


# ═══════════════════════════════════════════════════════════════════════════════
# Convenience Singleton
# ═══════════════════════════════════════════════════════════════════════════════

_ANALYZER_INSTANCE: RegimeAnalyzer | None = None


def get_regime_state(use_cache: bool = True) -> RegimeState:
    """현재 매크로 국면 — 외부 모듈에서 간편 호출."""
    global _ANALYZER_INSTANCE
    if _ANALYZER_INSTANCE is None:
        _ANALYZER_INSTANCE = RegimeAnalyzer()
    snapshot = _ANALYZER_INSTANCE.collector.collect_all(use_cache=use_cache)
    return _ANALYZER_INSTANCE.analyze(snapshot)


def get_regime_states() -> dict:
    """KR/US 국면 동시 — 콕핏 두 카드용 (스냅샷 1회 수집 공유)."""
    global _ANALYZER_INSTANCE
    if _ANALYZER_INSTANCE is None:
        _ANALYZER_INSTANCE = RegimeAnalyzer()
    snap = _ANALYZER_INSTANCE.collector.collect_all(use_cache=True)
    return {"kr": _ANALYZER_INSTANCE.analyze(snap, market="kr"),
            "us": _ANALYZER_INSTANCE.analyze(snap, market="us")}


def get_dynamic_risk_free_rate() -> float:
    """Valuation 엔진이 호출할 함수 — 실시간 국고채 10년."""
    try:
        state = get_regime_state()
        return state.dynamic_risk_free_rate or 0.035
    except Exception as e:
        logger.warning(f"동적 RF 조회 실패: {e}, 기본값 사용")
        return 0.035


def get_adaptive_kill_threshold() -> float:
    """Kill Switch가 호출할 함수 — adaptive DD threshold."""
    try:
        state = get_regime_state()
        return state.dynamic_kill_dd_threshold or 0.10
    except Exception as e:
        logger.warning(f"동적 Kill threshold 조회 실패: {e}, 기본값 사용")
        return 0.10
