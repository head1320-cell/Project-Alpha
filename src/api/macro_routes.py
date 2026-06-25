"""
Macro API Routes — Phase 4
==================================================
POST /api/v1/macro/snapshot           — 전체 매크로 스냅샷 (16 지표)
GET  /api/v1/macro/regime             — 현재 국면 + Stress + Yield Curve
GET  /api/v1/macro/yield-curve        — US Treasury Curve 단독
GET  /api/v1/macro/stress             — Market Stress Index 단독
GET  /api/v1/macro/heatmap            — 히트맵 데이터 (전일 대비)
GET  /api/v1/macro/series/{indicator} — 단일 지표 시계열
GET  /api/v1/macro/dynamic-params     — Valuation/KillSwitch가 사용할 동적 파라미터
POST /api/v1/macro/refresh            — 캐시 비우고 강제 새로고침
"""

from __future__ import annotations

import logging
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/macro", tags=["macro"])


# 싱글톤
def _get_analyzer():
    from src.engine.regime_analyzer import RegimeAnalyzer
    return RegimeAnalyzer()


# ═══════════════════════════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/snapshot")
def macro_snapshot(use_cache: bool = Query(True)):
    """전체 16개 지표 스냅샷 + 정규화."""
    try:
        from src.services.macro_collector import MacroCollector
        snap = MacroCollector.get_default().collect_all(use_cache=use_cache)
        return snap.to_dict()
    except Exception as e:
        logger.error(f"snapshot 실패: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@router.get("/regime")
def macro_regime():
    """4-Quadrant 국면 + Stress + Yield Curve + 동적 파라미터."""
    try:
        analyzer = _get_analyzer()
        state = analyzer.analyze()
        return asdict(state)
    except Exception as e:
        logger.error(f"regime 실패: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@router.get("/yield-curve")
def macro_yield_curve():
    """US Treasury Yield Curve (3M~30Y) + 역전 분석."""
    try:
        from src.services.macro_collector import MacroCollector
        snap = MacroCollector.get_default().collect_all()
        analyzer = _get_analyzer()
        curve, inversion, severity = analyzer._analyze_yield_curve(snap.series)
        return {
            "points":            curve["points"],
            "spread_2y10y_bp":   curve["spread_2y10y_bp"],
            "inversion":         inversion,
            "inversion_severity": severity,
            "interpretation":    _interpret_curve(curve, inversion, severity),
            "timestamp":         snap.timestamp,
        }
    except Exception as e:
        raise HTTPException(500, str(e))


def _interpret_curve(curve: dict, inversion: bool, severity: float | None) -> str:
    if inversion:
        if severity is not None and severity < -50:
            return f"심각한 역전 ({severity:.0f}bp). 12-18개월 내 침체 가능성 시사."
        return f"역전 ({severity:.0f}bp). 침체 신호. 주의 관찰 필요."
    points = curve.get("points", [])
    if points:
        latest = points[-1].get("yield_pct", 0)
        if latest < 3.5:
            return "완만한 정상 곡선. 저금리 환경 지속."
        return "정상 곡선. 성장 기대 안정적."
    return "데이터 부족."


@router.get("/stress")
def macro_stress():
    """Market Stress Index 단독."""
    try:
        state = _get_analyzer().analyze()
        return {
            "stress_score":      state.stress_score,
            "components":        state.stress_components,
            "recommended_mode":  state.recommended_mode,
            "interpretation":    _interpret_stress(state.stress_score),
            "timestamp":         state.timestamp,
        }
    except Exception as e:
        raise HTTPException(500, str(e))


def _interpret_stress(score: float) -> str:
    if score >= 80:
        return "극심한 스트레스. 방어 자산 즉시 확대 권고."
    if score >= 60:
        return "높은 스트레스. 포지션 축소 검토."
    if score >= 40:
        return "중간 스트레스. 정상 모니터링."
    return "낮은 스트레스. 위험자산 확대 가능."


@router.get("/heatmap")
def macro_heatmap():
    """히트맵 데이터 — 모든 지표 × 정규화 메트릭."""
    try:
        from src.services.macro_collector import MacroCollector
        snap = MacroCollector.get_default().collect_all()

        rows = []
        for _key, series in snap.series.items():
            rows.append({
                "indicator":  series.indicator,
                "name":       series.name,
                "unit":       series.unit,
                "source":     series.source,
                "latest":     series.latest,
                "mom_pct":    series.mom_pct,
                "yoy":        series.yoy,
                "z_score":    series.z_score,
                "percentile": series.percentile,
                "trend":      series.trend,
            })

        # Z-Score 절댓값으로 정렬 (극단치 우선)
        rows.sort(key=lambda r: abs(r.get("z_score") or 0), reverse=True)

        return {
            "indicators":  rows,
            "count":       len(rows),
            "timestamp":   snap.timestamp,
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/series/{indicator}")
def macro_series_detail(indicator: str):
    """단일 지표의 36개월 시계열 + 정규화."""
    try:
        from src.services.macro_collector import MacroCollector
        snap = MacroCollector.get_default().collect_all()
        series = snap.series.get(indicator)
        if not series:
            raise HTTPException(404, f"Indicator '{indicator}' not found")
        return asdict(series)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/dynamic-params")
def macro_dynamic_params():
    """
    Valuation 엔진 / Kill Switch가 사용할 동적 파라미터.
    이 endpoint를 통해 외부 모듈은 항상 최신 macro 기반 파라미터를 얻음.
    """
    try:
        from src.engine.regime_analyzer import get_regime_state
        state = get_regime_state()
        return {
            "risk_free_rate":         state.dynamic_risk_free_rate,
            "kill_dd_threshold":      state.dynamic_kill_dd_threshold,
            "regime":                 state.regime,
            "stress_score":           state.stress_score,
            "recommended_mode":       state.recommended_mode,
            "source":                 "macro_regime_analyzer",
            "timestamp":              state.timestamp,
            "explanation": {
                "risk_free_rate":     "현재 국고채 10년물 금리 (Valuation Ke 자동 주입용)",
                "kill_dd_threshold":  "Stress Index 기반 동적 Kill Switch DD 임계값 (높을수록 더 민감)",
            },
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/refresh")
def macro_refresh():
    """캐시 비우고 모든 지표 강제 새로고침."""
    try:
        from src.services.macro_collector import MacroCollector
        c = MacroCollector.get_default()
        c.cache_clear()
        snap = c.collect_all(use_cache=False)
        return {
            "status":     "refreshed",
            "indicators": len(snap.series),
            "timestamp":  snap.timestamp,
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/health")
def macro_health():
    """매크로 시스템 상태."""
    try:
        from src.services.macro_collector import MacroCollector
        c = MacroCollector.get_default()
        return c.cache_stats()
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/strategies")
def macro_strategies(market: str = Query("us", pattern="^(us|kr)$")):
    """13 택티컬 자산배분 전략의 현재 보유자산·비중 + 시그널 (jasan-calc식).
    market='us'(원본 ETF) | 'kr'(국내 ETF 매핑). 데이터 없으면 결정론적 mock으로 산출."""
    try:
        from src.engine.tactical_allocations import compute_strategies
        return compute_strategies(market)
    except Exception:
        logger.exception("매크로 전략 시그널 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")

