"""
Valuation Screener API Routes
==============================
POST /api/v1/screener/run            — 전 종목 스캔 + 필터 + 정렬
GET  /api/v1/screener/universes      — Universe 카탈로그
GET  /api/v1/screener/cache/stats    — 캐시 통계
POST /api/v1/screener/cache/clear    — 캐시 비우기
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.observability.logging_config import get_logger

logger = get_logger("api.screener")

router = APIRouter(prefix="/api/v1/screener", tags=["screener"])


def _detect_data_source(items: list) -> dict:
    """결과 종목의 데이터 출처 판별 (실데이터/mock 표시용)."""
    import os
    fund_real = False
    try:
        from src.data.fundamentals_store import FundamentalsStore
        store = FundamentalsStore.get_default()
        if items:
            code = getattr(items[0], "stock_code", None)
            if code:
                f = store.get_factors(code)
                fund_real = (f.get("_source") == "dart_real")
    except Exception:
        pass
    kis_real = (os.getenv("KIS_USE_MOCK", "1") == "0" and bool(os.getenv("KIS_APP_KEY")))
    return {
        "fundamentals": "dart_real" if fund_real else "mock",
        "market_data":  "kis_real" if kis_real else "mock",
        "fully_real":   fund_real and kis_real,
    }


# 싱글톤 (lazy)
_SCREENER = None


def get_screener():
    global _SCREENER
    if _SCREENER is None:
        from src.data.dart_client import DARTClient
        from src.engine.screener import ValuationScreener
        from src.engine.valuation.valuation_models import ValuationEngine
        client = DARTClient()
        _SCREENER = ValuationScreener(
            dart_client=client,
            valuation_engine=ValuationEngine(client),
        )
    return _SCREENER


# ═══════════════════════════════════════════════════════════════════════════════
# Models
# ═══════════════════════════════════════════════════════════════════════════════

class FilterRequest(BaseModel):
    min_market_cap_억:    float | None = None
    max_market_cap_억:    float | None = None
    min_roe_pct:          float | None = None
    max_roe_pct:          float | None = None
    min_gap_pct:          float | None = None
    max_gap_pct:          float | None = None
    min_per:              float | None = None
    max_per:              float | None = None
    min_pbr:              float | None = None
    max_pbr:              float | None = None
    min_dividend_yield:   float | None = None
    max_debt_ratio:       float | None = None
    sectors:              list[str] | None = None
    require_positive_fcf: bool = False
    verdicts:             list[str] | None = None


class ScreenerRunRequest(BaseModel):
    universe:        str = Field(default="kospi50",
                                  description="kospi50 | kospi200 | kosdaq150 | mapped")
    custom_tickers:  list[str] | None = None
    filters:         FilterRequest = Field(default_factory=FilterRequest)
    sort_by:         str = Field(default="composite_score",
                                  description="composite_score | gap_pct | roe_pct | per | pbr")
    ascending:       bool = False
    limit:           int = Field(default=50, ge=1, le=200)
    beta:            float = Field(default=1.0, ge=0.1, le=3.0)
    projection_years: int = Field(default=10, ge=3, le=20)


# ═══════════════════════════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/run")
def screener_run(req: ScreenerRunRequest):
    """전 종목 가치평가 스크리닝 실행."""
    try:
        from src.engine.screener import ScreenerFilters
        from src.engine.valuation.valuation_models import ValuationParams

        screener = get_screener()

        # 필터 변환
        filters = ScreenerFilters(**req.filters.model_dump())

        # Universe (custom 우선)
        universe = req.custom_tickers if req.custom_tickers else req.universe

        # Params
        params = ValuationParams(
            beta=req.beta,
            projection_years=req.projection_years,
        )

        result = screener.run(
            universe=universe,
            filters=filters,
            sort_by=req.sort_by,
            ascending=req.ascending,
            limit=req.limit,
            params=params,
        )

        return {
            "universe":         result.universe,
            "total_evaluated":  result.total_evaluated,
            "total_passed":     result.total_passed,
            "elapsed_seconds":  result.elapsed_seconds,
            "cache_hits":       result.cache_hits,
            "cache_misses":     result.cache_misses,
            "failures":         result.failures,
            "timestamp":        result.timestamp,
            "items":            [it.to_dict() for it in result.items],
        }
    except Exception:
        logger.exception("스크리너 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/universes")
def screener_universes():
    """사용 가능한 universe 카탈로그."""
    try:
        from src.engine.screener import UNIVERSE_PRESETS
        return {
            "presets": [
                {"id": k, "size": len(v), "sample": v[:5]}
                for k, v in UNIVERSE_PRESETS.items()
            ],
            "filter_dimensions": [
                "min_market_cap_억", "max_market_cap_억",
                "min_roe_pct", "max_roe_pct",
                "min_gap_pct (음수=저평가)", "max_gap_pct",
                "min_per", "max_per", "min_pbr", "max_pbr",
                "min_dividend_yield", "max_debt_ratio",
                "sectors[]", "require_positive_fcf", "verdicts[]",
            ],
            "sort_fields": [
                "composite_score", "gap_pct", "roe_pct",
                "per", "pbr", "dividend_yield_pct",
            ],
            "scoring_formula": {
                "composite": "gap × 0.6 + roe × 0.2 + stability × 0.2",
                "gap_score":     "clamp(50 - gap_pct, 0, 100)",
                "roe_score":     "clamp(roe_pct × 3.33, 0, 100)",
                "stability":     "(100 - debt_ratio/2 + (fcf>0 ? 80 : 30)) / 2",
            },
            "valuation_models": {
                "RIM": "V = BPS + Σ (ROE - Ke) × BPS / (1 + Ke)^t",
                "DCF": "V = Σ FCF / (1 + WACC)^t + TV / (1 + WACC)^n",
                "DDM": "V = Σ D / (1 + Ke)^t + Pn / (1 + Ke)^n",
            },
        }
    except Exception:
        logger.exception("스크리너 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/sectors")
def screener_sectors():
    """업종(테마) 카탈로그 — 종목 선택용. {id, label, size, sample}."""
    try:
        from src.engine.screener import get_sector_universe
        sectors = get_sector_universe()
        return {
            "sectors": [
                {"id": f"sector:{name}", "label": name, "size": len(codes), "sample": codes[:5]}
                for name, codes in sorted(sectors.items(), key=lambda x: -len(x[1]))
            ]
        }
    except Exception:
        logger.exception("업종 카탈로그 조회 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/cache/stats")
def screener_cache_stats():
    """캐시 통계 (hit rate 등)."""
    try:
        return get_screener().cache_stats()
    except Exception:
        logger.exception("스크리너 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.post("/cache/clear")
def screener_cache_clear():
    """캐시 비우기 (DART 데이터 갱신 후 등)."""
    try:
        get_screener().cache_clear()
        return {"status": "cleared"}
    except Exception:
        logger.exception("스크리너 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


# ═══════════════════════════════════════════════════════════════════════════════
# Milestone 1 — Advanced Filter AST Endpoints
# ═══════════════════════════════════════════════════════════════════════════════

class ConditionModel(BaseModel):
    field: str
    op: str = "lt"
    value: float | None = None
    value2: float | None = None
    rank_mode: str | None = None
    rank_value: float | None = None
    # V2 확장
    kind: str = "field"
    formula: str | None = None
    peer_scope: str | None = None
    peer_stat: str | None = None
    indicator: str | None = None
    event_type: str | None = None
    within_days: int | None = None
    estimate_field: str | None = None
    z_field: str | None = None
    z_window: int | None = None
    behavior_signal: str | None = None
    graph_target: str | None = None
    graph_relation: str | None = None
    graph_depth: int | None = None
    sentiment_source: str | None = None
    vector_ticker: str | None = None
    vector_threshold: float | None = None


class FilterGroupModel(BaseModel):
    logic: str = "AND"
    conditions: list[ConditionModel] = []
    groups: list[FilterGroupModel] = []


FilterGroupModel.model_rebuild()


class AdvancedRunRequest(BaseModel):
    universe: str = "kospi50"
    custom_tickers: list[str] | None = None
    filter_ast: FilterGroupModel
    sort_by: str = "composite_score"
    ascending: bool = False
    limit: int = Field(default=50, ge=1, le=200)
    beta: float = Field(default=1.0, ge=0.1, le=3.0)
    projection_years: int = Field(default=10, ge=3, le=20)
    use_macro: bool = False    # M3: 현재 국면 기반 동적 Composite 가중치
    analyzers: list[str] = []  # V3 M0: 후처리 analyzer (collinearity/stress_test)
    analyzer_params: dict = {}  # V3-M8: analyzer별 파라미터 (예: {"stress_test": {"scenario": "rate_hike_200bp"}})
    liquidity_floor: str = "standard"  # V3-P1.5: 유동성 게이트 (off|relaxed|standard|institutional)


@router.get("/fields")
def screener_fields():
    """필터 가능 필드 카탈로그 (카테고리 + 연산자 + 랭킹 모드)."""
    try:
        from src.engine.filter_ast import fields_catalog
        return fields_catalog()
    except Exception:
        logger.exception("스크리너 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.post("/run-advanced")
def screener_run_advanced(req: AdvancedRunRequest):
    """AST 기반 고급 스크리닝 (AND/OR 중첩 + 절대값 + 상대 랭킹)."""
    try:
        from src.engine.filter_ast import parse_group
        from src.engine.valuation.valuation_models import ValuationParams

        screener = get_screener()
        ast = parse_group(req.filter_ast.model_dump())

        err = ast.validate()
        if err:
            raise HTTPException(400, f"필터 검증 실패: {err}")

        universe = req.custom_tickers if req.custom_tickers else req.universe
        params = ValuationParams(beta=req.beta, projection_years=req.projection_years)

        result = screener.run(
            universe=universe,
            sort_by=req.sort_by,
            ascending=req.ascending,
            limit=req.limit,
            params=params,
            filter_ast=ast,
            use_macro=req.use_macro,
            liquidity_floor=req.liquidity_floor,
        )

        # V3-P1.5: 유동성 게이트 통계
        liq_stats = getattr(screener, "_liquidity_stats", {})

        # V3 M0: 후처리 analyzer 실행 (요청 시)
        analyzer_results = {}
        if req.analyzers:
            from src.engine.analyzers import run_analyzers
            analyzer_results = run_analyzers(result.items, req.analyzers, req.analyzer_params)

        return {
            "universe":        result.universe,
            "total_evaluated": result.total_evaluated,
            "total_passed":    result.total_passed,
            "elapsed_seconds": result.elapsed_seconds,
            "cache_hits":      result.cache_hits,
            "cache_misses":    result.cache_misses,
            "failures":        result.failures,
            "timestamp":       result.timestamp,
            "items":           [it.to_dict() for it in result.items],
            "analyzers":       analyzer_results,
            "liquidity_gate":  liq_stats,
            "data_source":     _detect_data_source(result.items),
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("스크리너 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.post("/count")
def screener_count(req: AdvancedRunRequest):
    """통과 종목 수만 반환 (Visual Builder 디바운스용 경량 엔드포인트)."""
    try:
        from src.engine.filter_ast import parse_group
        from src.engine.valuation.valuation_models import ValuationParams

        screener = get_screener()
        ast = parse_group(req.filter_ast.model_dump())
        err = ast.validate()
        if err:
            raise HTTPException(400, f"필터 검증 실패: {err}")

        universe = req.custom_tickers if req.custom_tickers else req.universe
        params = ValuationParams(beta=req.beta, projection_years=req.projection_years)

        result = screener.run(
            universe=universe, limit=1, params=params, filter_ast=ast,
        )
        return {
            "total_evaluated": result.total_evaluated,
            "total_passed":    result.total_passed,
            "elapsed_seconds": result.elapsed_seconds,
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("스크리너 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


# ═══════════════════════════════════════════════════════════════════════════════
# Milestone 3 — Macro-Adaptive Guidance
# ═══════════════════════════════════════════════════════════════════════════════

# 국면별 추천 팩터 + 가이드 텍스트
_REGIME_GUIDANCE = {
    "Goldilocks": {
        "text": "골디락스 국면 (성장↑·물가↓) — 성장주에 유리합니다. 높은 ROE·수익성 팩터 가중을 높이세요.",
        "filters": [
            {"field": "roe_pct", "rank_mode": "top_pct", "rank_value": 30, "label": "ROE 상위 30%"},
            {"field": "composite_score", "op": "gte", "value": 60, "label": "종합 점수 ≥ 60"},
        ],
    },
    "Reflation": {
        "text": "리플레이션 국면 (성장↑·물가↑) — 경기민감·가치주에 유리합니다. 저PER·저PBR 팩터를 강화하세요.",
        "filters": [
            {"field": "per", "op": "lt", "value": 12, "label": "PER < 12"},
            {"field": "pbr", "op": "lt", "value": 1.5, "label": "PBR < 1.5"},
        ],
    },
    "Stagflation": {
        "text": "스태그플레이션 국면 (성장↓·물가↑) — 방어주·배당주에 유리합니다. 고배당·저부채·FCF 흑자 팩터 가중을 높이세요.",
        "filters": [
            {"field": "dividend_yield_pct", "rank_mode": "top_pct", "rank_value": 30, "label": "배당수익률 상위 30%"},
            {"field": "debt_ratio_pct", "op": "lt", "value": 100, "label": "부채비율 < 100%"},
        ],
    },
    "Deflation": {
        "text": "디플레이션 국면 (성장↓·물가↓) — 안정성·대형 우량주에 유리합니다. 저부채·고FCF·대형주 팩터를 강화하세요.",
        "filters": [
            {"field": "debt_ratio_pct", "op": "lt", "value": 80, "label": "부채비율 < 80%"},
            {"field": "market_cap_억", "rank_mode": "top_pct", "rank_value": 40, "label": "시가총액 상위 40%"},
        ],
    },
}


@router.get("/macro-guidance")
def screener_macro_guidance():
    """현재 매크로 국면 기반 스크리닝 가이드 + 추천 팩터 + 동적 가중치."""
    try:
        from src.engine.regime_analyzer import get_regime_state
        from src.engine.screener import ValuationScreener

        state = get_regime_state()
        guidance = _REGIME_GUIDANCE.get(state.regime, {
            "text": "현재 국면 정보를 분석 중입니다.",
            "filters": [],
        })
        w_gap, w_roe, w_stab = ValuationScreener._regime_weights(state.regime)

        return {
            "regime":             state.regime,
            "stress_score":       state.stress_score,
            "recommended_mode":   state.recommended_mode,
            "description":        state.description,
            "guidance_text":      guidance["text"],
            "recommended_filters": guidance["filters"],
            "recommended_weights": {
                "gap": w_gap, "roe": w_roe, "stability": w_stab,
            },
            "asset_tilts":        state.asset_tilts,
            "dynamic_risk_free_rate": state.dynamic_risk_free_rate,
            "timestamp":          state.timestamp,
        }
    except Exception:
        logger.exception("스크리너 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


# ═══════════════════════════════════════════════════════════════════════════════
# Milestone 4 — Master Presets
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/presets")
def screener_presets():
    """거장 + 국면 + 테마 프리셋 카탈로그."""
    try:
        from src.engine.screener_presets import list_presets
        return list_presets()
    except Exception:
        logger.exception("스크리너 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/presets/{preset_id}")
def screener_preset_detail(preset_id: str):
    """단일 프리셋 상세 (filter_ast 포함 — FilterBuilder 로드용)."""
    try:
        from src.engine.screener_presets import get_preset
        p = get_preset(preset_id)
        if not p:
            raise HTTPException(404, f"Preset '{preset_id}' not found")
        return {"id": preset_id, **p}
    except HTTPException:
        raise
    except Exception:
        logger.exception("스크리너 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


class PresetRunRequest(BaseModel):
    universe: str = "kospi50"
    limit: int = Field(default=50, ge=1, le=200)


@router.post("/presets/{preset_id}/run")
def screener_preset_run(preset_id: str, req: PresetRunRequest):
    """프리셋 원클릭 실행."""
    try:
        from src.engine.filter_ast import parse_group
        from src.engine.screener_presets import get_preset
        from src.engine.valuation.valuation_models import ValuationParams

        preset = get_preset(preset_id)
        if not preset:
            raise HTTPException(404, f"Preset '{preset_id}' not found")

        screener = get_screener()
        ast = parse_group(preset["filter_ast"])

        result = screener.run(
            universe=req.universe,
            sort_by="composite_score",
            limit=req.limit,
            params=ValuationParams(),
            filter_ast=ast,
            use_macro=preset.get("use_macro", False),
        )

        return {
            "preset_id":       preset_id,
            "preset_name":     preset["name"],
            "master":          preset["master"],
            "universe":        result.universe,
            "total_evaluated": result.total_evaluated,
            "total_passed":    result.total_passed,
            "elapsed_seconds": result.elapsed_seconds,
            "timestamp":       result.timestamp,
            "items":           [it.to_dict() for it in result.items],
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("스크리너 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")



# ═══════════════════════════════════════════════════════════════════════════════
# Screener V2 — Milestone 1: Formula + Peer
# ═══════════════════════════════════════════════════════════════════════════════

class FormulaValidateRequest(BaseModel):
    formula: str


@router.post("/validate-formula")
def screener_validate_formula(req: FormulaValidateRequest):
    """수식 사전 검증 + 사용 필드 추출 (FormulaEditor 실시간 검증용)."""
    try:
        from src.engine.filter_ast import FIELD_BY_ID
        from src.engine.formula_parser import validate_formula
        ok, err, used = validate_formula(req.formula, set(FIELD_BY_ID.keys()))
        return {
            "valid": ok,
            "error": err,
            "used_fields": sorted(used),
        }
    except Exception:
        logger.exception("스크리너 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/peer-groups")
def screener_peer_groups(universe: str = "kospi50"):
    """가용 Peer 그룹(섹터) 목록 + 종목 수 (PeerConditionEditor용)."""
    try:
        screener = get_screener()
        result = screener.run(universe=universe, limit=300)
        sectors: dict = {}
        for it in result.items:
            sec = it.sector or "기타"
            sectors[sec] = sectors.get(sec, 0) + 1
        return {
            "scopes": [
                {"id": "sector", "label": "동일 섹터", "groups": [{"name": k, "count": v} for k, v in sorted(sectors.items(), key=lambda x: -x[1])]},
                {"id": "market", "label": "전체 시장", "groups": [{"name": "전체", "count": result.total_evaluated}]},
            ],
            "stats": [
                {"id": "mean", "label": "평균"},
                {"id": "median", "label": "중앙값"},
                {"id": "rank_pct", "label": "그룹 내 상위 %"},
            ],
        }
    except Exception:
        logger.exception("스크리너 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


# ═══════════════════════════════════════════════════════════════════════════════
# Screener V2 — Milestone 2: AI NL2AST Copilot
# ═══════════════════════════════════════════════════════════════════════════════

class NL2ASTRequest(BaseModel):
    query: str


@router.post("/nl2ast")
def screener_nl2ast(req: NL2ASTRequest):
    """자연어 → FilterGroup AST 변환 (Claude + Mock fallback)."""
    try:
        from src.services.screener_copilot import nl_to_ast
        result = nl_to_ast(req.query)
        return result
    except Exception:
        logger.exception("스크리너 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/nl2ast/examples")
def screener_nl2ast_examples():
    """추천 자연어 예시."""
    try:
        from src.services.screener_copilot import EXAMPLE_QUERIES
        return {"examples": EXAMPLE_QUERIES}
    except Exception:
        logger.exception("스크리너 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")



# ═══════════════════════════════════════════════════════════════════════════════
# Screener V2 — Milestone 3: Technical/Event Catalogs
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/indicators")
def screener_indicators():
    """기술지표 + 수급 카탈로그 (기술적 지표, 수급)."""
    try:
        from src.data.market_data import indicators_catalog
        return indicators_catalog()
    except Exception:
        logger.exception("스크리너 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/fill-price-types")
def screener_fill_price_types():
    """체결가 유형 카탈로그 (백테스터 매수/매도 체결가 선택용)."""
    try:
        from src.engine.fill_price import FILL_PRICE_GROUPS, FILL_PRICE_LABELS
        return {
            "groups": [
                {
                    "id": g["id"], "label": g["label"],
                    "types": [{"id": t, "label": FILL_PRICE_LABELS[t]} for t in g["types"]],
                }
                for g in FILL_PRICE_GROUPS
            ]
        }
    except Exception:
        logger.exception("체결가 유형 조회 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/condition-tokens")
def screener_condition_tokens():
    """백테스터 조건식 팩터 토큰 지원 맵 — 픽커의 지원/미지원 배지용 (백엔드 단일 소스).

    supported: {토큰: 그룹(base|ohlcv|fundamental)} / unsupported: {토큰: 사유}"""
    try:
        from src.kis_strategies.factor_tokens import token_support
        return token_support()
    except Exception:
        logger.exception("조건식 토큰 지원 맵 조회 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


class ExprValidateRequest(BaseModel):
    expr: str = ""


@router.post("/factor-expr/validate")
def validate_factor_expr(req: ExprValidateRequest):
    """자유 산술 팩터식 검증 — 파서가 단일 진실 공급원.

    ok=True면 lookback·사용 토큰·미지원 토큰 경고(평가 시 건너뜀) 포함."""
    from src.kis_strategies.factor_expr import expr_lookback, expr_tokens, parse_expr
    from src.kis_strategies.factor_tokens import token_support
    expr = (req.expr or "").strip()
    if not expr:
        return {"ok": True, "empty": True, "lookback": 0, "tokens": [], "unknown_tokens": []}
    try:
        ast = parse_expr(expr)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    tokens = sorted(expr_tokens(ast))
    try:
        supported = set(token_support()["supported"])
    except Exception:
        supported = set()
    unknown = [t for t in tokens if supported and t not in supported]
    return {"ok": True, "empty": False, "lookback": expr_lookback(ast),
            "tokens": tokens, "unknown_tokens": unknown}


class ConditionNLRequest(BaseModel):
    query: str


@router.post("/condition-nl")
def condition_from_nl(req: ConditionNLRequest):
    """자연어 → 백테스터 조건식 (젠포트 AI 버튼) — nl2ast 재사용 후 조건 매핑.

    field 조건 → 펀더멘털 토큰 조건, rank_mode → 비율내림차순/순위내림차순 산술식.
    매핑 불가 항목은 skipped에 사유와 함께 — 조용히 버리지 않음."""
    try:
        from src.services.screener_copilot import nl_to_ast
        result = nl_to_ast(req.query)
        ast = result.get("ast") or {}
        # 필드 id → 한글 라벨 (조건식 토큰으로 해석 가능한 이름)
        id_to_label: dict[str, str] = {}
        try:
            from src.kis_strategies.factor_tokens import _label_aliases
            for label, fid in _label_aliases().items():
                id_to_label.setdefault(fid, label)
        except Exception:
            pass
        try:
            from src.engine.filter_ast import FIELD_BY_ID
            for fid, f in FIELD_BY_ID.items():
                id_to_label.setdefault(fid, getattr(f, "label", fid))
        except Exception:
            pass
        _OP = {"gt": "gte", "gte": "gte", "lt": "lte", "lte": "lte", "eq": "eq"}
        conds, skipped = [], []
        for c in (ast.get("conditions") or []):
            if c.get("kind") != "field":
                skipped.append({"field": str(c.get("kind")), "reason": "필드 조건만 변환 가능"})
                continue
            fid = str(c.get("field") or "")
            label = id_to_label.get(fid)
            if not label:
                skipped.append({"field": fid, "reason": "백테스터 토큰 매핑 없음"})
                continue
            rank_mode = c.get("rank_mode")
            if rank_mode:
                rv = float(c.get("rank_value") or 30)
                if rank_mode == "top_pct":
                    conds.append({"expr": f"비율내림차순({{{label}}})", "op": "gte", "rhs": 100 - rv})
                elif rank_mode == "bottom_pct":
                    conds.append({"expr": f"비율내림차순({{{label}}})", "op": "lte", "rhs": rv})
                elif rank_mode == "top_n":
                    conds.append({"expr": f"순위내림차순({{{label}}})", "op": "lte", "rhs": rv})
                else:
                    skipped.append({"field": fid, "reason": f"rank_mode {rank_mode} 미지원"})
                continue
            op = _OP.get(str(c.get("op") or "").lower())
            if op is None or c.get("value") is None:
                skipped.append({"field": fid, "reason": "연산자/값 없음"})
                continue
            conds.append({"factor_token": f"{{{label}}}", "function_id": "base",
                          "params": {}, "op": op, "rhs": float(c["value"])})
        return {"conditions": conds, "skipped": skipped,
                "explanation": result.get("explanation"), "source": result.get("source"),
                "note": "펀더멘털 토큰은 '펀더멘털 조건 평가' 토글이 켜져 있어야 평가됩니다 (스냅샷 근사)"}
    except Exception:
        logger.exception("condition-nl 변환 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


class LogicValidateRequest(BaseModel):
    expr: str = ""
    n_conditions: int = Field(default=0, ge=0, le=26)


@router.post("/condition-logic/validate")
def validate_condition_logic(req: LogicValidateRequest):
    """논리 조건식 검증 (젠포트 '조건식 검증하기') — 파서가 단일 진실 공급원.

    ok=True면 lookback(시간 한정사 추가 룩백 봉 수) 포함. 오류는 한국어 메시지."""
    from src.kis_strategies.condition_logic import max_lookback, parse_logic
    expr = (req.expr or "").strip()
    if not expr:
        return {"ok": True, "lookback": 0, "empty": True}
    try:
        ast = parse_logic(expr, req.n_conditions)
        return {"ok": True, "lookback": max_lookback(ast), "empty": False}
    except ValueError as e:
        return {"ok": False, "error": str(e)}


@router.get("/events-catalog")
def screener_events_catalog():
    """이벤트 카탈로그 (실적 발표, 배당락)."""
    try:
        from src.data.event_calendar import events_catalog
        return events_catalog()
    except Exception:
        logger.exception("스크리너 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


# ═══════════════════════════════════════════════════════════════════════════════
# Screener V2 — Milestone 4: Point-in-Time Screening (타임머신)
# ═══════════════════════════════════════════════════════════════════════════════

class PITRunRequest(BaseModel):
    universe: str = "kospi50"
    custom_tickers: list[str] | None = None
    filter_ast: FilterGroupModel
    as_of_date: str
    sort_by: str = "composite_score"
    limit: int = Field(default=50, ge=1, le=200)


@router.get("/pit-dates")
def screener_pit_dates():
    """가용 PIT 스냅샷 일자 (분기말, look-ahead 차단)."""
    try:
        from src.engine.pit_store import DISCLOSURE_LAG_DAYS, available_snapshot_dates
        return {
            "dates": available_snapshot_dates(years_back=6),
            "disclosure_lag_days": DISCLOSURE_LAG_DAYS,
            "note": "분기말 기준. 공시 시차(45일) 경과분만 제공하여 look-ahead bias 차단.",
        }
    except Exception:
        logger.exception("스크리너 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.post("/run-pit")
def screener_run_pit(req: PITRunRequest):
    """과거 시점 기준 스크리닝 (타임머신). Look-ahead bias 차단."""
    try:
        from src.engine.filter_ast import parse_group
        from src.engine.pit_store import PITStore
        from src.engine.valuation.valuation_models import ValuationParams

        # as_of_date 검증
        err = PITStore.get_default().validate_asof(req.as_of_date)
        if err:
            raise HTTPException(400, f"기준일 오류: {err}")

        screener = get_screener()
        ast = parse_group(req.filter_ast.model_dump())
        verr = ast.validate()
        if verr:
            raise HTTPException(400, f"필터 검증 실패: {verr}")

        universe = req.custom_tickers if req.custom_tickers else req.universe
        result = screener.run(
            universe=universe,
            sort_by=req.sort_by,
            limit=req.limit,
            params=ValuationParams(),
            filter_ast=ast,
            as_of_date=req.as_of_date,
        )

        return {
            "as_of_date":      req.as_of_date,
            "universe":        result.universe,
            "total_evaluated": result.total_evaluated,
            "total_passed":    result.total_passed,
            "elapsed_seconds": result.elapsed_seconds,
            "timestamp":       result.timestamp,
            "items":           [it.to_dict() for it in result.items],
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("스크리너 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")



# ═══════════════════════════════════════════════════════════════════════════════
# Screener V3 — Phase 0: Analyzer Catalog
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/analyzers")
def screener_analyzers():
    """가용 후처리 analyzer 카탈로그 (M7/M8)."""
    try:
        from src.engine.analyzers import analyzer_catalog
        return analyzer_catalog()
    except Exception:
        logger.exception("스크리너 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")



# ═══════════════════════════════════════════════════════════════════════════════
# Screener V3 — Phase 1: Estimates Catalog (M1)
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/estimates-catalog")
def screener_estimates_catalog():
    """Forward-looking 추정치 카탈로그 (M1)."""
    try:
        from src.data.consensus_store import estimates_catalog
        return estimates_catalog()
    except Exception:
        logger.exception("스크리너 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")



# ═══════════════════════════════════════════════════════════════════════════════
# Screener V3 — Phase 1.5: Liquidity Gate
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/liquidity-profiles")
def screener_liquidity_profiles():
    """유동성 게이트 프로파일 카탈로그 (off/relaxed/standard/institutional)."""
    try:
        from src.engine.liquidity_gate import liquidity_profiles_catalog
        return liquidity_profiles_catalog()
    except Exception:
        logger.exception("스크리너 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")



# ═══════════════════════════════════════════════════════════════════════════════
# Screener V3 — Phase 2: Behavioral (M3) + Graph (M4)
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/behavior-signals")
def screener_behavior_signals():
    """행동재무 신호 카탈로그 (M3)."""
    try:
        from src.data.market_data import behavior_signals_catalog
        return behavior_signals_catalog()
    except Exception:
        logger.exception("스크리너 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/graph-meta")
def screener_graph_meta():
    """지식 그래프 메타 — 관계 유형 + 노드 목록 (M4)."""
    try:
        from src.engine.graph_store import graph_meta_catalog
        return graph_meta_catalog()
    except Exception:
        logger.exception("스크리너 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/graph-search")
def screener_graph_search(q: str = ""):
    """그래프 타겟 종목 검색 (M4)."""
    try:
        from src.engine.graph_store import GraphStore
        return {"results": GraphStore.get_default().search_stocks(q)}
    except Exception:
        logger.exception("스크리너 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/graph-relations/{stock_code}")
def screener_graph_relations(stock_code: str):
    """종목의 직접 밸류체인 관계 (M4)."""
    try:
        from src.engine.graph_store import GraphStore
        return GraphStore.get_default().get_relations(stock_code)
    except Exception:
        logger.exception("스크리너 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")



# ═══════════════════════════════════════════════════════════════════════════════
# Screener V3 — Phase 3: Sentiment (M5) + Vector (M6)
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/sentiment-catalog")
def screener_sentiment_catalog():
    """NLP 센티먼트 소스 카탈로그 (M5)."""
    try:
        from src.services.sentiment_worker import sentiment_catalog
        return sentiment_catalog()
    except Exception:
        logger.exception("스크리너 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/vector-meta")
def screener_vector_meta():
    """벡터 유사도 메타 — 임베딩 차원 + 검색 가능 종목 (M6)."""
    try:
        from src.engine.vector_store import vector_meta_catalog
        return vector_meta_catalog()
    except Exception:
        logger.exception("스크리너 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")



# ═══════════════════════════════════════════════════════════════════════════════
# Screener V3 — Phase 4: Stress-Test Scenarios (M8)
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/stress-scenarios")
def screener_stress_scenarios():
    """매크로 스트레스 테스트 시나리오 카탈로그 (M8)."""
    try:
        from src.engine.stress_test_analyzer import stress_scenarios_catalog
        return stress_scenarios_catalog()
    except Exception:
        logger.exception("스크리너 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")



# ═══════════════════════════════════════════════════════════════════════════════
# Screener V3 — Fundamental Factor Library (FFL)
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/fundamentals-catalog")
def screener_fundamentals_catalog():
    """학술 펀더멘털 팩터 카탈로그 (50+ 팩터, 카테고리별)."""
    try:
        from src.data.fundamentals_store import fundamentals_catalog
        return fundamentals_catalog()
    except Exception:
        logger.exception("스크리너 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


# ═══════════════════════════════════════════════════════════════════════════════
# Screener → Backtester Bridge (스크리너 통과 종목 원클릭 백테스트)
# ═══════════════════════════════════════════════════════════════════════════════

class ScreenToBacktestRequest(BaseModel):
    # 스크리닝 조건
    universe: str = "kospi200"
    custom_tickers: list[str] | None = None  # 관심그룹 종목 직접 지정 (있으면 universe 무시)
    filter_ast: FilterGroupModel
    liquidity_floor: str = "standard"
    max_tickers: int = Field(default=10, ge=1, le=30)  # 백테스트할 상위 종목 수
    sort_by: str = "composite_score"
    sort_dir: str = "desc"                       # 매수 우선순위 1차 방향 (desc|asc)
    sort_by_secondary: str | None = None         # 2차 정렬 키 (동점 타이브레이크)
    sort_secondary_dir: str = "desc"
    # 백테스트 설정
    strategy_name: str = "GoldenCross"
    strategy_params: dict = {}
    start_date: str = "2023-01-01"
    end_date: str = "2024-12-31"
    initial_capital: float = 100_000_000
    commission_rate: float = 0.0015
    slippage_rate: float = 0.0005
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    trailing_stop_pct: float | None = None  # 트레일링 스탑(드래깅 청산): 고점 대비 하락 %
    max_positions: int = 5
    # 체결가 유형 (Phase 1). 기본 close = 종가 체결
    buy_fill_type: str = "close"
    sell_fill_type: str = "close"
    # 매도 정밀화 (Phase 2)
    max_hold_days: int | None = None
    min_hold_days: int = 0
    day_trade: bool = False  # 당일 매매: 당일 진입을 같은 봉 종가에 전량 청산
    sell_divide_pct: float = 100.0
    max_sell_divisions: int | None = None
    # 매수 정밀화 (Phase 3)
    breakthrough_buy: bool = False  # 돌파매수: 당일 고가가 전일 고가 돌파 시에만 진입
    buy_weight_mode: str = "equal"
    buy_divide_pct: float = 100.0
    max_buy_per_day: int | None = None
    max_buy_count: int | None = None
    # 조건식 기반 진입/청산 (Genport식). 있으면 strategy_name 무시하고 조건식 전략 사용.
    # 각 조건 dict: {factor_token, function_id, params{n,v,dir}, op(gte|lte|eq|between), rhs, rhs2?,
    #   inner_function_id?, inner_params?,                  ← 중첩(순위/비율 랭킹 대상)
    #   factor_token2?, inner2_function_id?, inner2_params?} ← 두 팩터(비교/큰값/작은값/변화율_팩터)
    buy_conditions: list[dict] | None = None
    sell_conditions: list[dict] | None = None
    # 논리 조건식 (젠포트 논리 레이어): 조건 라벨 A,B,C…를 and/or/not/before/any/every로
    # 결합 — 예: "every(A,3) and (B or C)". 비우면 기존(매수=AND, 매도=OR).
    buy_logic: str | None = None
    sell_logic: str | None = None
    # 정기 리밸런싱 + 마켓타이밍 (GENPORT_GAP ②)
    rebalance_period: str | None = None  # None·"daily"=매일 | "weekly"|"monthly"=주·월 첫 거래일에만 신규 매수
    market_timing: dict | None = None    # {"index_ticker","action"("block_buy"|"exit_all"),"conditions":[조건식]}
    # 신호 기준일 (젠포트 Tip 3): 0=당일 봉(기존), 1=전일 봉 기준 신호→당일 체결(시가류 체결 look-ahead 제거)
    signal_lag: int = Field(default=0, ge=0, le=5)
    # 재매수 방지: 청산 후 N일(캘린더) 이내 재매수 금지 (0=미사용)
    rebuy_block_days: int = Field(default=0, ge=0, le=120)
    # 체결 가격 기준 ± 오프셋% (지정가 모델 — 도달 검증, 미도달 시 그날 미체결)
    buy_fill_offset_pct: float = Field(default=0.0, ge=-10.0, le=10.0)
    sell_fill_offset_pct: float = Field(default=0.0, ge=-10.0, le=10.0)
    # 종목당 최대 매수 금액(원, None=무제한) + 자산배분 현금 비중 %
    max_buy_amount: float | None = Field(default=None, ge=0)
    cash_reserve_pct: float = Field(default=0.0, ge=0.0, le=90.0)
    # 매수 우선순위식 (일별) — 봉마다 후보들의 식 값으로 매수 순서 정렬
    buy_sort_expr: str | None = None
    buy_sort_desc: bool = True
    # granular 유니버스 (시총군/업종/ETF/관심그룹) — 있으면 후보 종목을 직접 구성해 universe 대체
    caps: list[str] | None = None
    sectors: list[str] | None = None        # 실제 업종명 (/sectors)
    etf: bool = False
    managed: bool = False
    supervised: bool = False
    groups: list[dict] | None = None
    # 전체 유니버스 일별 평가 (Genport식): 조건식이 후보 풀 전체를 매 봉 평가하도록 풀 확대
    # 상한 4000 = 코스피+코스닥 전 주권(~2,700) 커버 — 시그널 벡터화로 실용 시간 확보
    full_universe_eval: bool = False
    universe_eval_cap: int = Field(default=200, ge=1, le=4000)
    # #4: 펀더멘털 토큰(스냅샷)을 봉별 조건 평가에 포함. 기본 False (look-ahead 근사라 옵트인)
    allow_snapshot_fundamentals: bool = False


@router.post("/screen-to-backtest")
def screen_to_backtest(req: ScreenToBacktestRequest):
    """
    원클릭 워크플로우: 스크리닝 → 통과 종목을 그대로 백테스트.

    1) filter_ast로 스크리닝 (유동성 게이트 + 펀더멘털 주입 포함)
    2) 통과 종목 상위 max_tickers개 추출
    3) 해당 종목들로 백테스트 실행 (DB → KIS → mock 자동)

    스크리너와 백테스터를 잇는 핵심 연결 — 별도 입력 없이 흐름 완성.
    """
    try:
        from src.engine.filter_ast import parse_group
        from src.kis_backtest_engine import run_backtest

        # 1) 스크리닝 (custom_tickers 있으면 관심그룹 종목을 유니버스로)
        screener = get_screener()
        ast = parse_group(req.filter_ast.model_dump())
        # granular 유니버스: caps/sectors/etf/groups 제공 시 후보 종목을 직접 구성
        gran_tickers = None
        if any([req.caps, req.sectors, req.etf, req.managed, req.supervised, req.groups]):
            try:
                from src.engine.universe_select import select_universe
                gran_tickers, _gran_total = select_universe(
                    caps=req.caps or [], sectors=req.sectors or [], etf=bool(req.etf),
                    managed=bool(req.managed), supervised=bool(req.supervised),
                    groups=req.groups or [],
                )
            except Exception:
                gran_tickers = None
        if req.custom_tickers:
            _universe = req.custom_tickers
        elif gran_tickers:
            _universe = gran_tickers
        elif req.universe == "all_asof":
            # 시점 유니버스: 백테스트 시작일 당시 거래 종목 (KRX 백필 후 상폐 포함 — 생존편향 보정)
            from src.engine.universe_select import tickers_asof
            _asof = tickers_asof(req.start_date)
            _universe = _asof if _asof else "all_listed"  # 데이터 없으면 전종목→프리셋 폴백
        elif req.universe == "top200_asof":
            # 시작일 당시 시총 상위 200 — KOSPI200 편입의 근사 재구성 (mktcap 시계열 필요)
            from src.engine.universe_select import top_mktcap_asof
            _asof = top_mktcap_asof(req.start_date, 200)
            _universe = _asof if _asof else "kospi200"
        else:
            _universe = req.universe
        # 후보 풀 크기: 전체 유니버스 일별 평가 시 확대(조건식이 매 봉 풀 전체를 평가, max_positions가 보유 한도)
        eval_cap = req.universe_eval_cap if (req.full_universe_eval and (req.buy_conditions or req.sell_conditions)) else req.max_tickers
        eval_cap = max(1, min(int(eval_cap), 4000))  # 벡터화로 전 주권(~2,700) 실용화
        result = screener.run(
            universe=_universe,
            filter_ast=ast,
            sort_by=req.sort_by,
            ascending=(req.sort_dir == "asc"),
            sort_by_secondary=req.sort_by_secondary,
            sort_secondary_ascending=(req.sort_secondary_dir == "asc"),
            limit=eval_cap,
            liquidity_floor=req.liquidity_floor,
        )
        screened = result.items[:eval_cap]
        tickers = [it.stock_code for it in screened if getattr(it, "stock_code", None)]

        if not tickers:
            return {
                "error": True,
                "message": "스크리닝 통과 종목이 없습니다. 필터를 완화하세요.",
                "screened_count": 0,
            }

        # 팩터가중 모드: 종목별 점수를 0~1로 정규화한 가중치 맵 생성
        factor_weights = None
        if req.buy_weight_mode == "factor":
            scores = {it.stock_code: float(getattr(it, "composite_score", 0) or 0)
                      for it in screened if getattr(it, "stock_code", None)}
            if scores:
                lo, hi = min(scores.values()), max(scores.values())
                rng = hi - lo
                # 점수가 높을수록 가중치↑ (0~1). 전부 같으면 0.5(동일가중)
                factor_weights = {
                    t: ((s - lo) / rng if rng > 0 else 0.5) for t, s in scores.items()
                }

        # 조건식 전략 분기 (Genport식 진입/청산)
        eff_strategy = req.strategy_name
        eff_params = dict(req.strategy_params or {})
        if req.buy_conditions or req.sell_conditions:
            from src.kis_strategies import condition_strategy  # noqa: F401 (레지스트리 자기등록)
            _ = condition_strategy
            eff_strategy = "Condition"
            eff_params = {
                "buy_conditions": req.buy_conditions or [],
                "sell_conditions": req.sell_conditions or [],
                "allow_snapshot_fundamentals": bool(req.allow_snapshot_fundamentals),
                "buy_logic": req.buy_logic,
                "sell_logic": req.sell_logic,
            }

        # 2) 백테스트
        bt = run_backtest(
            symbols=tickers,
            strategy_name=eff_strategy,
            start_date=req.start_date,
            end_date=req.end_date,
            strategy_params=eff_params,
            initial_capital=req.initial_capital,
            commission_rate=req.commission_rate,
            slippage_rate=req.slippage_rate,
            stop_loss_pct=req.stop_loss_pct,
            take_profit_pct=req.take_profit_pct,
            trailing_stop_pct=req.trailing_stop_pct,
            max_positions=req.max_positions,
            buy_fill_type=req.buy_fill_type,
            sell_fill_type=req.sell_fill_type,
            max_hold_days=req.max_hold_days,
            min_hold_days=req.min_hold_days,
            day_trade=req.day_trade,
            sell_divide_pct=req.sell_divide_pct,
            max_sell_divisions=req.max_sell_divisions,
            buy_weight_mode=req.buy_weight_mode,
            buy_divide_pct=req.buy_divide_pct,
            max_buy_per_day=req.max_buy_per_day,
            max_buy_count=req.max_buy_count,
            factor_weights=factor_weights,
            breakthrough_buy=req.breakthrough_buy,
            rebalance_period=req.rebalance_period,
            market_timing=req.market_timing,
            signal_lag=req.signal_lag,
            rebuy_block_days=req.rebuy_block_days,
            buy_fill_offset_pct=req.buy_fill_offset_pct,
            sell_fill_offset_pct=req.sell_fill_offset_pct,
            max_buy_amount=req.max_buy_amount,
            cash_reserve_pct=req.cash_reserve_pct,
            buy_sort_expr=req.buy_sort_expr,
            buy_sort_desc=req.buy_sort_desc,
        )

        # 3) 통합 응답
        return {
            "error": bt.get("error", False),
            "screened_tickers": [
                {"stock_code": it.stock_code, "corp_name": getattr(it, "corp_name", ""),
                 "composite_score": getattr(it, "composite_score", None)}
                for it in screened
            ],
            "screened_count": len(tickers),
            "backtest": bt.get("result", bt),
            "backtest_config": {
                "strategy": eff_strategy,
                "period": f"{req.start_date} ~ {req.end_date}",
                "initial_capital": req.initial_capital,
            },
            "data_source": _detect_data_source(screened),
        }
    except HTTPException:
        raise
    except ValueError as e:
        # 논리 조건식 문법·라벨 오류 등 — 사용자가 고칠 수 있는 입력 오류
        logger.warning(f"screen-to-backtest 입력 오류: {e}")
        raise HTTPException(400, f"입력 오류: {e}")
    except Exception:
        logger.exception("screen-to-backtest 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/backtest-strategies")
def backtest_strategies():
    """백테스트 가능 전략 목록 (스크리너 UI 드롭다운용)."""
    try:
        from src.kis_strategies.strategies import STRATEGY_REGISTRY
        # 영문 키만 (한글 중복 제거)
        seen, out = set(), []
        labels = {
            "GoldenCross": "골든크로스", "Momentum": "모멘텀", "Week52High": "52주 신고가",
            "Consecutive": "연속 상승/하락", "Disparity": "이격도", "BreakoutFail": "돌파 실패",
            "StrongClose": "강한 종가", "Volatility": "변동성 확장", "MeanReversion": "평균회귀",
            "TrendFilter": "추세 필터",
        }
        for key in STRATEGY_REGISTRY:
            if key in labels and key not in seen:
                seen.add(key)
                out.append({"id": key, "label": labels[key]})
        return {"strategies": out}
    except Exception:
        logger.exception("스크리너 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


# ═══════════════════════════════════════════════════════════════════════════════
# Data Quality QA (데이터 인프라 품질)
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/data-quality")
def data_quality_check(req: AdvancedRunRequest):
    """
    스크리닝 결과의 데이터 품질 리포트.
    종목명 해소율, 이상치, 결측, 품질 점수 산출.
    """
    try:
        from src.data.stock_master import validate_dataset
        from src.engine.filter_ast import parse_group
        screener = get_screener()
        ast = parse_group(req.filter_ast.model_dump())
        result = screener.run(
            universe=req.universe, filter_ast=ast,
            limit=req.limit, liquidity_floor=req.liquidity_floor,
        )
        report = validate_dataset(result.items)
        report["data_source"] = _detect_data_source(result.items)
        return report
    except Exception as e:
        raise HTTPException(500, f"데이터 품질 검사 실패: {e}")


@router.get("/stock-master/stats")
def stock_master_stats():
    """종목 마스터 현황 (커버리지)."""
    try:
        import os

        from src.data.stock_master import STOCK_MASTER, STOCK_SECTOR
        # DART 캐시 여부
        cache_path = os.path.join(os.path.dirname(__file__), "..", "data", "corp_name_cache.json")
        dart_cached = os.path.exists(cache_path)
        dart_count = 0
        if dart_cached:
            import json
            try:
                with open(cache_path) as f:
                    dart_count = len(json.load(f))
            except Exception:
                pass
        return {
            "builtin_stocks": len(STOCK_MASTER),
            "sector_mapped": len(STOCK_SECTOR),
            "dart_cache_available": dart_cached,
            "dart_cached_stocks": dart_count,
            "total_resolvable": max(len(STOCK_MASTER), dart_count),
        }
    except Exception:
        logger.exception("스크리너 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")
