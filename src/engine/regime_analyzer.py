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
import math
from dataclasses import dataclass, field

from src.services.macro_collector import MacroCollector, MacroSeries, MacroSnapshot

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Regime Models
# ═══════════════════════════════════════════════════════════════════════════════

REGIME_DESCRIPTIONS = {
    "Goldilocks":  "성장↑ + 물가↓ — 위험자산 최적 (성장주 우위)",
    "Reflation":   "성장↑ + 물가↑ — 원자재/금융주 우위, 채권 회피",
    "Stagflation": "성장↓ + 물가↑ — 현금/금/단기채 방어",
    "Deflation":   "성장↓ + 물가↓ — 장기채/방어주 (디플레이션)",
}

REGIME_TILTS = {
    "Goldilocks":  {"growth_stocks": "+", "value_stocks": "-", "bonds": "-", "commodities": "0", "cash": "-"},
    "Reflation":   {"growth_stocks": "0", "value_stocks": "+", "bonds": "--", "commodities": "++", "cash": "0"},
    "Stagflation": {"growth_stocks": "-", "value_stocks": "0", "bonds": "-", "commodities": "+", "cash": "++"},
    "Deflation":   {"growth_stocks": "-", "value_stocks": "0", "bonds": "++", "commodities": "--", "cash": "+"},
}


@dataclass
class RegimeState:
    """현재 매크로 국면 + 시장 스트레스."""
    timestamp:           str
    regime:              str                    # Goldilocks/Reflation/Stagflation/Deflation
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

    # 동적 파라미터 (다른 모듈에 주입할 값)
    dynamic_risk_free_rate:  float | None = None
    dynamic_kill_dd_threshold: float | None = None


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

    def analyze(self, snapshot: MacroSnapshot | None = None) -> RegimeState:
        snapshot = snapshot or self.collector.collect_all()
        s = snapshot.series

        # 실데이터 부족 점검 — 운영서 매크로가 전부 unavailable이면 허위 국면 분류 금지(정직).
        real_count = sum(1 for v in s.values()
                         if getattr(v, "source", "") != "unavailable" and v.latest is not None)
        insufficient = real_count < 3

        # 1. Growth Axis (Z-Score 가중 평균)
        growth_axis = self._compute_growth_axis(s)

        # 2. Inflation Axis
        inflation_axis = self._compute_inflation_axis(s)

        # 3. Regime 판별 — 데이터 부족 시 허위 국면(Reflation 등) 대신 '데이터 부족'
        if insufficient:
            regime, confidence = "데이터 부족", 0.0
        else:
            regime, confidence = self._classify_regime(growth_axis, inflation_axis)

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
        )

    # ─────────────────────────────────────────────────────────────────────
    # Growth / Inflation 축 계산
    # ─────────────────────────────────────────────────────────────────────

    def _compute_growth_axis(self, s: dict[str, MacroSeries]) -> float:
        """
        Growth Axis: 양수일수록 성장 강함.
        가중치: KOSPI(0.3) + T10Y2Y(-0.3, 역수) + VIX(-0.2, 역수) + DXY(-0.2, 역수)
        """
        signals = []
        weights = []

        # KOSPI 추세 (Z-Score 양수 = 성장)
        kospi = s.get("KOSPI")
        if kospi and kospi.z_score is not None:
            signals.append(kospi.z_score)
            weights.append(0.3)

        # T10Y2Y (양수 = 정상 = 성장 기대)
        t10y2y = s.get("T10Y2Y")
        if t10y2y and t10y2y.z_score is not None:
            signals.append(t10y2y.z_score)
            weights.append(0.3)

        # VIX (낮을수록 = 성장 = 양수 axis)
        vix = s.get("VIXCLS")
        if vix and vix.z_score is not None:
            signals.append(-vix.z_score)
            weights.append(0.2)

        # DXY (강달러 = 미국 매력도 높음 but EM 압박)
        dxy = s.get("DTWEXBGS")
        if dxy and dxy.z_score is not None:
            signals.append(-dxy.z_score)
            weights.append(0.2)

        if not signals:
            return 0.0
        total_w = sum(weights)
        return sum(sig * w for sig, w in zip(signals, weights)) / total_w if total_w > 0 else 0.0

    def _compute_inflation_axis(self, s: dict[str, MacroSeries]) -> float:
        """
        Inflation Axis: 양수일수록 인플레이션 강함.
        가중치: KR_CPI(0.3) + US_CPI(0.3) + KR_10Y(0.2) + Credit_Spread(-0.2)
        """
        signals = []
        weights = []

        kr_cpi = s.get("KR_CPI")
        if kr_cpi and kr_cpi.z_score is not None:
            signals.append(kr_cpi.z_score)
            weights.append(0.3)

        us_cpi = s.get("CPIAUCSL")
        if us_cpi and us_cpi.z_score is not None:
            signals.append(us_cpi.z_score)
            weights.append(0.3)

        kr_10y = s.get("KR_10Y")
        if kr_10y and kr_10y.z_score is not None:
            signals.append(kr_10y.z_score)
            weights.append(0.2)

        # Credit spread 확대 = 디스인플레이션/위험 회피
        credit = s.get("BAMLH0A0HYM2")
        if credit and credit.z_score is not None:
            signals.append(-credit.z_score * 0.5)
            weights.append(0.2)

        if not signals:
            return 0.0
        total_w = sum(weights)
        return sum(sig * w for sig, w in zip(signals, weights)) / total_w if total_w > 0 else 0.0

    # ─────────────────────────────────────────────────────────────────────
    # Regime 분류
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def _classify_regime(growth: float, inflation: float) -> tuple[str, float]:
        """
        4-Quadrant 분류 + 신뢰도.
            성장↑ + 물가↓ → Goldilocks
            성장↑ + 물가↑ → Reflation
            성장↓ + 물가↑ → Stagflation
            성장↓ + 물가↓ → Deflation
        """
        if growth >= 0 and inflation < 0:
            regime = "Goldilocks"
        elif growth >= 0 and inflation >= 0:
            regime = "Reflation"
        elif growth < 0 and inflation >= 0:
            regime = "Stagflation"
        else:
            regime = "Deflation"

        # 신뢰도: 두 축의 절댓값 평균 → tanh
        confidence = math.tanh((abs(growth) + abs(inflation)) / 2)
        return regime, max(0.1, confidence)

    # ─────────────────────────────────────────────────────────────────────
    # Market Stress Index
    # ─────────────────────────────────────────────────────────────────────

    def _compute_stress(self, s: dict[str, MacroSeries]) -> tuple[float, dict]:
        """
        스트레스 지수 0-100.
        구성: VIX(30%) + Credit Spread(25%) + USD/KRW 변동성(20%) + Yield 변동성(15%) + DXY(10%)
        """
        components = {}
        total_score = 0.0
        total_weight = 0.0

        def score_z(z: float | None) -> float:
            """Z-Score → 0-100 (높을수록 스트레스). z=0 → 50, z=2 → 90."""
            if z is None:
                return 50.0
            return max(0, min(100, 50 + z * 20))

        # 1. VIX (높을수록 스트레스)
        vix = s.get("VIXCLS")
        if vix and vix.z_score is not None:
            v_score = score_z(vix.z_score)
            components["vix"] = round(v_score, 1)
            total_score += v_score * 0.30
            total_weight += 0.30

        # 2. Credit Spread
        credit = s.get("BAMLH0A0HYM2")
        if credit and credit.z_score is not None:
            c_score = score_z(credit.z_score)
            components["credit_spread"] = round(c_score, 1)
            total_score += c_score * 0.25
            total_weight += 0.25

        # 3. USD/KRW 변동성 (Z-Score)
        usdkrw = s.get("USD_KRW")
        if usdkrw and usdkrw.z_score is not None:
            fx_score = score_z(abs(usdkrw.z_score))  # 양/음 모두 변동성
            components["fx_volatility"] = round(fx_score, 1)
            total_score += fx_score * 0.20
            total_weight += 0.20

        # 4. 금리 변동성 (KR_10Y mom_pct)
        kr_10y = s.get("KR_10Y")
        if kr_10y and kr_10y.mom_pct is not None:
            r_score = max(0, min(100, abs(kr_10y.mom_pct) * 8 + 40))
            components["rate_volatility"] = round(r_score, 1)
            total_score += r_score * 0.15
            total_weight += 0.15

        # 5. DXY (강달러 = EM 스트레스)
        dxy = s.get("DTWEXBGS")
        if dxy and dxy.z_score is not None:
            d_score = score_z(max(0, dxy.z_score))
            components["dxy_strength"] = round(d_score, 1)
            total_score += d_score * 0.10
            total_weight += 0.10

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
