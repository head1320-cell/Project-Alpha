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


@router.get("/connection-status")
def macro_connection_status():
    """매크로 실연결 점검 — BOK/FRED 키 설정 + 모드. 운영서 미설정 지표는 unavailable('—')."""
    from src.services.macro_collector import MacroCollector
    return MacroCollector.get_default().connection_status()


@router.get("/regime")
def macro_regime():
    """4-Quadrant 국면 + Stress + Yield Curve + 동적 파라미터.

    최상위 필드 = KR 국면(하위호환). markets.kr / markets.us 로 두 시장 동시 제공.
    """
    try:
        analyzer = _get_analyzer()
        snap = analyzer.collector.collect_all(use_cache=True)
        kr = analyzer.analyze(snap, market="kr")
        us = analyzer.analyze(snap, market="us")
        out = asdict(kr)
        out["markets"] = {"kr": asdict(kr), "us": asdict(us)}
        return out
    except Exception as e:
        logger.error(f"regime 실패: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@router.get("/regime-ensemble")
def macro_regime_ensemble(market: str = "kr", months: int = 60):
    """국면 확률을 **세 도구로 따로** — 축·상태전환(Markov)·군집(GMM).

    합치지 않는다. 세 방법이 갈리면 그 사실이 정보이므로 `agreement` 로 일치 여부만
    돌려주고, 어느 쪽을 믿을지는 사람이 정한다. 표본 부족·미수렴·라이브러리 부재는
    도구별 `available: False` + 사유 — 균등분포로 채우지 않는다.
    """
    try:
        from src.engine.regime_ensemble import regime_ensemble
        analyzer = _get_analyzer()
        snap = analyzer.collector.collect_all(use_cache=True)
        series_map = getattr(snap, "series", None) or {}
        return regime_ensemble(series_map, market=market, months=months)
    except Exception as e:
        logger.error(f"regime-ensemble 실패: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@router.get("/regime-explain")
def macro_regime_explain(market: str = "kr", months: int = 60,
                         regime: str | None = None, forecast_k: int = 3):
    """국면 판정의 **설명·시간맥락·전환위험** (A8).

    A7 의 `/regime-ensemble` 은 결론(확률)만 준다. 여기는 그 결론을 쓸 수 있게 만드는
    세 가지를 준다:

      · `transitions` — 행별 Dirichlet 사후 전이행렬(신용구간 포함) · k개월 사후예측 ·
                        현재 국면 연속 개월 · 역사적 점유율 · 월별 국면 경로(리본용)
      · `drivers`     — 대상 국면 확률의 **정확 Shapley** 분해(2^n 완전열거) +
                        지표 → 축의 정확 가법 기여

    ★`span` 을 반드시 함께 읽을 것★ 요청한 `months` 보다 실제 분류 가능한 달이 적으면
    `span.truncated` 가 True 이고 `span.n_months` 가 진짜 개수다. 화면은 이 값으로
    구간을 적어야 하며, 요청값을 기간인 것처럼 쓰면 안 된다.
    """
    try:
        from src.engine.regime_drivers import regime_drivers
        from src.engine.regime_transitions import regime_transitions
        analyzer = _get_analyzer()
        snap = analyzer.collector.collect_all(use_cache=True)
        series_map = getattr(snap, "series", None) or {}
        tr = regime_transitions(series_map, market=market, months=months,
                                forecast_k=forecast_k)
        # 대상 국면은 인자 > 현재 경로의 마지막 > 드라이버 자체의 argmax 순.
        target = regime or (tr.get("current") if tr.get("available") else None)
        dr = regime_drivers(series_map, market=market, regime=target)
        return {"market": market, "transitions": tr, "drivers": dr,
                "span": tr.get("span")}
    except Exception as e:
        logger.error(f"regime-explain 실패: {e}", exc_info=True)
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
def macro_strategies(market: str = Query("kr", pattern="^(us|kr)$")):
    """13 택티컬 자산배분 전략의 현재 보유자산·비중 + 시그널 (jasan-calc식).
    market='us'(원본 ETF) | 'kr'(국내 ETF 매핑). 데이터 없으면 결정론적 mock으로 산출."""
    try:
        from src.engine.tactical_allocations import compute_strategies
        return compute_strategies(market)
    except Exception:
        logger.exception("매크로 전략 시그널 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/recommend")
def macro_recommend(market: str = Query("kr", pattern="^(us|kr)$")):
    """현 국면에 유리한 자산배분 전략 추천 (규칙+성과+AI 서술 3종 종합).
    국면(regime_analyzer) × 전략 아키타입 적합도 + 트레일링 성과 → composite 랭킹 + 최상위 추천."""
    try:
        from src.engine.macro_recommender import recommend
        return recommend(market)
    except Exception:
        logger.exception("매크로 추천 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


# 6테마 그룹 (지표 id → 테마). 25지표(BOK 6 + FRED 19)를 성장/물가/금리/유동성/심리/한국으로.
# ★BOK 키는 collect_all()의 시맨틱 키(KR_BASE_RATE 등) — stat 코드 아님★
_THEME_MAP: dict[str, list[str]] = {
    "growth": ["GDPC1", "INDPRO", "UNRATE", "PAYEMS"],
    "inflation": ["CPIAUCSL", "T10YIE", "DCOILWTICO", "KR_CPI"],
    "rates": ["FEDFUNDS", "DGS3MO", "DGS2", "DGS10", "DGS30", "T10Y2Y", "DFII10",
              "KR_BASE_RATE", "KR_3Y", "KR_10Y"],
    "liquidity": ["BAMLH0A0HYM2", "M2SL"],
    "sentiment": ["VIXCLS", "UMCSENT", "DTWEXBGS"],
    "korea": ["KOSPI", "USD_KRW"],
}
_THEME_LABEL = {"growth": "성장", "inflation": "물가", "rates": "금리·통화",
                "liquidity": "유동성·신용", "sentiment": "수급·심리", "korea": "한국"}


@router.get("/dashboard")
def macro_dashboard():
    """6테마 매크로 지표 대시보드 — 각 지표 최근값·Δ·z-score(5년)·sparkline. FRED+ECOS 실데이터(키 없으면 mock)."""
    import os
    try:
        from src.services.macro_collector import MacroCollector
        snap = MacroCollector.get_default().collect_all().to_dict()
        series = snap.get("series", {})
        themes = []
        for key, ids in _THEME_MAP.items():
            inds = []
            for sid in ids:
                s = series.get(sid)
                if not s:
                    continue
                vals = [v for v in (s.get("values") or []) if v is not None]
                prev = vals[-2] if len(vals) >= 2 else None
                latest = s.get("latest")
                delta = round(latest - prev, 3) if (latest is not None and prev is not None) else None
                inds.append({
                    "id": sid, "name": s.get("name"), "unit": s.get("unit"),
                    "latest": latest, "z_score": s.get("z_score"), "percentile": s.get("percentile"),
                    "delta": delta, "spark": [round(v, 4) for v in vals[-24:]],
                })
            themes.append({"key": key, "label": _THEME_LABEL[key], "indicators": inds})
        return {
            "as_of": snap.get("timestamp"),
            "themes": themes,
            "sources": {"fred": bool(os.getenv("FRED_API_KEY")), "bok": bool(os.getenv("BOK_API_KEY"))},
        }
    except Exception:
        logger.exception("매크로 대시보드 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/valuation")
def macro_valuation():
    """자산군 밸류에이션 z-score(가격 5년) + 한국 시장 밸류(PER/PBR/배당 분포). 키 없으면 mock."""
    import os
    try:
        from src.data.etf_prices import monthly_closes

        def _zlast(ticker: str):
            c = [v for v in monthly_closes(ticker, "kr", 60) if v]
            if len(c) < 12:
                return None
            mean = sum(c) / len(c)
            var = sum((x - mean) ** 2 for x in c) / len(c)
            sd = var ** 0.5
            return round((c[-1] - mean) / sd, 2) if sd > 0 else 0.0

        assets = [
            {"key": "stock", "label": "주식(SPY)", "z": _zlast("SPY")},
            {"key": "bond", "label": "장기채(TLT)", "z": _zlast("TLT")},
            {"key": "gold", "label": "금(GLD)", "z": _zlast("GLD")},
            {"key": "commodity", "label": "원자재(PDBC)", "z": _zlast("PDBC")},
            {"key": "reit", "label": "리츠(VNQ)", "z": _zlast("VNQ")},
            {"key": "em", "label": "신흥국(EEM)", "z": _zlast("EEM")},
        ]
        # 한국 시장 밸류 — 적재된 factor_snapshot 표본(있으면)
        kr = None
        try:
            from src.data.snapshot_db import sample_factors
            samp = sample_factors(600) or []
            pers = sorted(x for x in (s.get("per") for s in samp) if isinstance(x, (int, float)) and x > 0)
            pbrs = sorted(x for x in (s.get("pbr") for s in samp) if isinstance(x, (int, float)) and x > 0)
            if pers and pbrs:
                kr = {"n": len(samp), "per_median": round(pers[len(pers) // 2], 2),
                      "pbr_median": round(pbrs[len(pbrs) // 2], 2)}
        except Exception:
            kr = None
        return {"assets": assets, "kr_market": kr,
                "sources": {"prices": bool(os.getenv("KIS_APP_KEY")), "fundamentals": bool(os.getenv("DART_API_KEY"))}}
    except Exception:
        logger.exception("매크로 밸류에이션 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/correlations")
def macro_correlations(market: str = Query("kr", pattern="^(us|kr)$")):
    """13자산 상관행렬 + 롤링 주식-채권 상관 추이 + 평균 페어상관(분산 국면). 일간 시세 기반."""
    try:
        from src.engine.macro_analytics import correlation_panel
        return correlation_panel(market)
    except Exception:
        logger.exception("매크로 상관 분석 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/timing")
def macro_timing(market: str = Query("kr", pattern="^(us|kr)$")):
    """마켓타이밍 종합(위험 온/오프) + 5구성요소 + 월별 추이 + 자산별 추세표."""
    try:
        from src.engine.macro_analytics import timing_panel
        return timing_panel(market)
    except Exception:
        logger.exception("매크로 타이밍 분석 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/regime-trajectory")
def macro_regime_trajectory(market: str = Query("kr")):
    """최근 18개월 국면 궤적 — 헤더 국면과 동일한 축 정의(regime_axes) 공유."""
    try:
        from src.engine.macro_analytics import regime_trajectory
        return regime_trajectory(market=market)
    except Exception:
        logger.exception("매크로 국면 궤적 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/strategy/{sid}")
def macro_strategy_detail(sid: str, market: str = Query("kr", pattern="^(us|kr)$")):
    """전략 상세 — 큐레이션 프로파일 + 라이브 보유·시그널 + 국면적합도 + 과거성과 곡선 + 레퍼런스."""
    try:
        from src.engine.strategy_profiles import build_detail
        d = build_detail(sid, market)
        if d is None:
            raise HTTPException(404, "전략을 찾을 수 없습니다.")
        return d
    except HTTPException:
        raise
    except Exception:
        logger.exception("전략 상세 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/strategy/{sid}/backtest-config")
def macro_strategy_backtest_config(sid: str, market: str = Query("kr", pattern="^(us|kr)$")):
    """전략 → 백테스터 셋업 구성(하이브리드): 모멘텀=조건식·정적=asset_alloc·최적화=엔진."""
    try:
        from src.engine.strategy_backtest_map import backtest_config
        c = backtest_config(sid, market)
        if c is None:
            raise HTTPException(404, "전략을 찾을 수 없습니다.")
        return c
    except HTTPException:
        raise
    except Exception:
        logger.exception("전략 백테스트 구성 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.post("/strategy/{sid}/ai")
def macro_strategy_ai(sid: str, market: str = Query("kr", pattern="^(us|kr)$")):
    """전략 AI 심층분석 (온디맨드) — 프로파일+현재 국면+보유 컨텍스트로 Claude 생성. 키 없으면 폴백."""
    try:
        from src.engine.strategy_profiles import build_detail
        d = build_detail(sid, market)
        if d is None:
            raise HTTPException(404, "전략을 찾을 수 없습니다.")
        from src.services.narrative.claude_client import ClaudeClient, NarrativeRequest
        client = ClaudeClient.get_default()
        if not client.is_configured:
            return {"content": "", "tokens": 0, "cost_krw": 0.0, "cached": False,
                    "error": "ANTHROPIC_API_KEY 미설정 — 키 설정 시 AI 심층분석이 활성화됩니다."}
        try:
            from src.engine.regime_analyzer import RegimeAnalyzer
            st = RegimeAnalyzer().analyze()
            regime, stress = st.regime, float(st.stress_score or 50)
        except Exception:
            regime, stress = "—", 50.0
        prof = d["profile"]
        holdings_str = ", ".join(f"{h['us_label']} {h['weight']}%" for h in d["holdings"][:8])
        fit_str = ", ".join(f"{x['quadrant_kr'].split('(')[0]} {int(x['fit'] * 100)}" for x in d["regime_fit"])
        sys_p = "너는 매크로 기반 자산배분 애널리스트다. 한국어로 4~6문장, 과장 없이 균형있게 강점·약점·유의점을 설명한다."
        user_p = (f"전략: {d['name']} ({d['archetype_kr']} 아키타입)\n개념: {prof['concept']}\n"
                  f"작동: {' '.join(prof['mechanism'])}\n"
                  f"현재 시장 국면: {regime} (Stress {stress:.0f})\n국면별 적합도: {fit_str}\n"
                  f"현재 배분: {holdings_str}\n최근 12개월 추정수익(현재비중 기준): {d['recent_return_12m']}%\n"
                  f"이 전략이 '지금 이 국면'에 적합한지 근거와 함께 평가하라.")
        resp = client.invoke(NarrativeRequest(system_prompt=sys_p, user_prompt=user_p, max_tokens=900))
        return {"content": resp.content, "tokens": resp.total_tokens, "cost_krw": resp.cost_krw,
                "cached": resp.cached, "error": resp.error}
    except HTTPException:
        raise
    except Exception:
        logger.exception("전략 AI 분석 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")



# ═══ v2 혁신 — CB 센티먼트 · 그레인저 인과 그래프 (CIO 리팩토링) ═══════════════════

@router.get("/cb-sentiment")
def macro_cb_sentiment():
    """중앙은행(Fed/BOK) 정책문 매파/비둘기 게이지 — 렉시콘 기반, 수집 실패 시 정직 결측."""
    try:
        from src.engine.cb_sentiment import cb_sentiment
        return cb_sentiment()
    except Exception:
        logger.exception("cb-sentiment 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/causal-graph")
def macro_causal_graph():
    """매크로 변수 그레인저(예측적) 인과 그래프 — 방향 엣지(from→to, lag, p)."""
    try:
        from src.engine.causal_graph import granger_edges
        snap = _get_analyzer().collector.collect_all(use_cache=True)
        return granger_edges(snap.series)
    except Exception:
        logger.exception("causal-graph 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


# ═══ v3 시각화 (밸리AI 장점 흡수) — 사이클 스트립·하위요인·자산 스트립·KR/US 비교 ═══

@router.get("/cycle-strips")
def macro_cycle_strips(market: str = Query("kr")):
    """지표×월 사이클 히트 스트립 (변환 z 18개월 타임라인)."""
    try:
        from src.engine.macro_visuals import cycle_strips
        snap = _get_analyzer().collector.collect_all(use_cache=True)
        return cycle_strips(snap.series, market=market)
    except Exception:
        logger.exception("cycle-strips 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/axis-history")
def macro_axis_history(market: str = Query("kr")):
    """성장/물가 축의 월별 하위요인(지표 기여) 분해 — 스택 차트."""
    try:
        from src.engine.macro_visuals import axis_history
        snap = _get_analyzer().collector.collect_all(use_cache=True)
        return axis_history(snap.series, market=market)
    except Exception:
        logger.exception("axis-history 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/asset-strips")
def macro_asset_strips(market: str = Query("kr")):
    """자산군 가격 위치 백분위 스트립 (시세 기반 — 멀티플 아님, 정직 라벨)."""
    try:
        from src.engine.macro_visuals import asset_strips
        return asset_strips(market=market)
    except Exception:
        logger.exception("asset-strips 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/compare-krus")
def macro_compare_krus():
    """KR vs US 핵심 지표 z 나란히 비교."""
    try:
        from src.engine.macro_visuals import kr_us_compare
        snap = _get_analyzer().collector.collect_all(use_cache=True)
        return kr_us_compare(snap.series)
    except Exception:
        logger.exception("compare-krus 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/capability")
def macro_capability():
    """능력 사다리 — 지금 이 시스템이 실제로 도달하는 레벨과 **그 위가 막힌 이유** (M1-C).

    ★이 라우트가 있는 이유★ 요청받은 아키텍처는 Neural SDE·PINN·RL-GNN·Diffusion DRO·
    cvxpylayers SPO 를 상위 티어에 놓는다. 그것들이 지금 왜 돌지 않는지를 화면이 말하지
    못하면, 시스템은 조용히 아래 레벨로 내려가 놓고 위 레벨인 척하게 된다 — 이 저장소가
    금지하는 실패 양식이다.

    프로브는 캐시하지 않는다. 의존성이 설치되면 그 즉시 사다리가 열려야 한다.
    """
    try:
        from src.engine.capability import resolve
        return resolve()
    except Exception:
        logger.exception("capability 판정 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")
