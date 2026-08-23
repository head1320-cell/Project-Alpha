"""
Narrative API Routes — Phase 3 AI Intelligence
==================================================
POST /api/v1/narrative/stock              — 종목 분석 narrative
POST /api/v1/narrative/portfolio          — 포트폴리오 보고서
POST /api/v1/narrative/macro              — 매크로 브리핑
POST /api/v1/narrative/operations         — 운영 사건 분석
POST /api/v1/narrative/counterfactual     — What-If 시나리오
POST /api/v1/narrative/daily-summary      — 일일 요약
POST /api/v1/narrative/stream/{domain}    — SSE 스트리밍 (모든 도메인)
GET  /api/v1/narrative/usage              — 토큰 사용량 + 비용
GET  /api/v1/narrative/cache/stats        — 캐시 통계
POST /api/v1/narrative/cache/clear        — 캐시 비우기
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/narrative", tags=["narrative"])


# ═══════════════════════════════════════════════════════════════════════════════
# Request Models
# ═══════════════════════════════════════════════════════════════════════════════

class StockNarrativeRequest(BaseModel):
    stock_item:        dict = Field(..., description="ScreenerItem (gap_pct, scores, etc.)")
    valuation_detail:  dict = Field(default_factory=dict, description="ValuationDetail (모델별 + financial_summary)")
    max_tokens:        int = Field(default=2000, ge=500, le=4000)
    temperature:       float = Field(default=0.3, ge=0, le=1)
    model:             str | None = None


class PortfolioNarrativeRequest(BaseModel):
    backtest_result:   dict = Field(..., description="백테스트 메타 + 성과 지표")
    attribution:       dict = Field(default_factory=dict, description="5-Factor Attribution + Regime Alpha")
    max_tokens:        int = Field(default=2500, ge=500, le=4000)
    temperature:       float = Field(default=0.3, ge=0, le=1)
    model:             str | None = None


class MacroNarrativeRequest(BaseModel):
    regime_state:      dict = Field(..., description="현재 Regime + 5종 매크로 지표")
    max_tokens:        int = Field(default=2000)
    temperature:       float = Field(default=0.3)
    model:             str | None = None


class OperationsNarrativeRequest(BaseModel):
    events:            list[dict] = Field(..., description="발생한 이벤트 목록 (kill switch, drift 등)")
    audit_summary:     dict = Field(default_factory=dict, description="audit 카운트 + severity 분포")
    max_tokens:        int = Field(default=2500)
    temperature:       float = Field(default=0.3)
    model:             str | None = None


class CounterfactualNarrativeRequest(BaseModel):
    actual:            dict = Field(..., description="실제 백테스트 결과")
    scenarios:         list[dict] = Field(..., description="가상 시나리오 N개")
    max_tokens:        int = Field(default=2500)
    temperature:       float = Field(default=0.3)
    model:             str | None = None


class DailySummaryRequest(BaseModel):
    activities:        dict = Field(..., description="operations + market + portfolio + alerts")
    max_tokens:        int = Field(default=2000)
    temperature:       float = Field(default=0.3)
    model:             str | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# Helper — Response 포맷
# ═══════════════════════════════════════════════════════════════════════════════

def _serialize_response(resp) -> dict:
    """NarrativeResponse → JSON-serializable dict."""
    return {
        "content":         resp.content,
        "model":           resp.model,
        "input_tokens":    resp.input_tokens,
        "output_tokens":   resp.output_tokens,
        "total_tokens":    resp.total_tokens,
        "cost_usd":        round(resp.cost_usd, 6),
        "cost_krw":        round(resp.cost_krw, 2),
        "elapsed_seconds": resp.elapsed_seconds,
        "cached":          resp.cached,
        "error":           resp.error,
        "timestamp":       resp.timestamp,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Endpoints — 비스트리밍 (블로킹)
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/stock")
def narrative_stock(req: StockNarrativeRequest):
    """종목 분석 narrative 생성."""
    try:
        from src.services.narrative.narrators import StockNarrator
        narrator = StockNarrator()
        resp = narrator.generate(
            stock_item=req.stock_item,
            valuation_detail=req.valuation_detail,
            max_tokens=req.max_tokens,
            temperature=req.temperature,
            model=req.model,
        )
        return _serialize_response(resp)
    except Exception as e:
        logger.error(f"Stock narrative 실패: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@router.post("/portfolio")
def narrative_portfolio(req: PortfolioNarrativeRequest):
    """포트폴리오 보고서."""
    try:
        from src.services.narrative.narrators import PortfolioNarrator
        narrator = PortfolioNarrator()
        resp = narrator.generate(
            backtest_result=req.backtest_result,
            attribution=req.attribution,
            max_tokens=req.max_tokens,
            temperature=req.temperature,
            model=req.model,
        )
        return _serialize_response(resp)
    except Exception as e:
        logger.error(f"Portfolio narrative 실패: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@router.post("/macro")
def narrative_macro(req: MacroNarrativeRequest):
    """매크로 브리핑."""
    try:
        from src.services.narrative.narrators import MacroNarrator
        narrator = MacroNarrator()
        resp = narrator.generate(
            regime_state=req.regime_state,
            max_tokens=req.max_tokens,
            temperature=req.temperature,
            model=req.model,
        )
        return _serialize_response(resp)
    except Exception as e:
        logger.error(f"Macro narrative 실패: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@router.post("/operations")
def narrative_operations(req: OperationsNarrativeRequest):
    """운영 사건 분석."""
    try:
        from src.services.narrative.narrators import OperationsNarrator
        narrator = OperationsNarrator()
        resp = narrator.generate(
            events=req.events,
            audit_summary=req.audit_summary,
            max_tokens=req.max_tokens,
            temperature=req.temperature,
            model=req.model,
        )
        return _serialize_response(resp)
    except Exception as e:
        logger.error(f"Operations narrative 실패: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@router.post("/counterfactual")
def narrative_counterfactual(req: CounterfactualNarrativeRequest):
    """Counterfactual What-If 분석."""
    try:
        from src.services.narrative.narrators import CounterfactualNarrator
        narrator = CounterfactualNarrator()
        resp = narrator.generate(
            actual=req.actual,
            scenarios=req.scenarios,
            max_tokens=req.max_tokens,
            temperature=req.temperature,
            model=req.model,
        )
        return _serialize_response(resp)
    except Exception as e:
        logger.error(f"Counterfactual narrative 실패: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@router.post("/daily-summary")
def narrative_daily(req: DailySummaryRequest):
    """일일 활동 요약."""
    try:
        from src.services.narrative.narrators import DailyNarrator
        narrator = DailyNarrator()
        resp = narrator.generate(
            activities=req.activities,
            max_tokens=req.max_tokens,
            temperature=req.temperature,
            model=req.model,
        )
        return _serialize_response(resp)
    except Exception as e:
        logger.error(f"Daily narrative 실패: {e}", exc_info=True)
        raise HTTPException(500, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# Streaming Endpoint — 모든 도메인 통합 SSE
# ═══════════════════════════════════════════════════════════════════════════════

class StreamRequest(BaseModel):
    """모든 도메인 통합 스트리밍 요청."""
    inputs:        dict = Field(..., description="도메인별 입력 (stock_item, backtest_result, etc.)")
    max_tokens:    int = Field(default=2500)
    temperature:   float = Field(default=0.3)
    model:         str | None = None


@router.post("/stream/{domain}")
async def narrative_stream(domain: str, req: StreamRequest):
    """
    SSE 스트리밍 narrative 생성.
    domain: stock | portfolio | macro | operations | counterfactual | daily
    """
    try:
        from src.services.narrative.narrators import get_narrator
        narrator = get_narrator(domain)

        def event_stream():
            try:
                gen = narrator.stream(
                    max_tokens=req.max_tokens,
                    temperature=req.temperature,
                    model=req.model,
                    **req.inputs,
                )
                for chunk in gen:
                    if chunk:
                        # SSE 형식: data: {...}\n\n
                        yield f"data: {json.dumps({'chunk': chunk}, ensure_ascii=False)}\n\n"
                # 종료 시그널
                yield f"data: {json.dumps({'done': True})}\n\n"
            except Exception as e:
                logger.error(f"Stream 오류: {e}")
                yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    except Exception as e:
        logger.error(f"Stream init 실패: {e}", exc_info=True)
        raise HTTPException(500, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# Usage / Cache
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/usage")
def narrative_usage():
    """전체 사용량 통계."""
    try:
        from src.services.narrative.claude_client import ANTHROPIC_AVAILABLE, ClaudeClient
        client = ClaudeClient.get_default()
        stats = client.get_usage()

        return {
            "configured":         client.is_configured,
            "sdk_available":      ANTHROPIC_AVAILABLE,
            "model":              client.model,
            "total_calls":        stats.total_calls,
            "total_cached":       stats.total_cached,
            "total_failures":     stats.total_failures,
            "total_input_tokens": stats.total_input_tokens,
            "total_output_tokens": stats.total_output_tokens,
            "total_cost_usd":     round(stats.total_cost_usd, 4),
            "total_cost_krw":     round(stats.total_cost_krw, 2),
            "by_model":           stats.by_model,
            "last_call_at":       stats.last_call_at,
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/cache/stats")
def narrative_cache_stats():
    """캐시 통계."""
    try:
        from src.services.narrative.claude_client import ClaudeClient
        return ClaudeClient.get_default().cache.stats()
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/cache/clear")
def narrative_cache_clear():
    """캐시 비우기."""
    try:
        from src.services.narrative.claude_client import ClaudeClient
        ClaudeClient.get_default().cache.clear()
        return {"status": "cleared"}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/domains")
def narrative_domains():
    """사용 가능한 narrative 도메인 카탈로그."""
    return {
        "domains": [
            {
                "id": "stock",
                "name": "종목 분석",
                "description": "Screener Item + ValuationDetail → 자연어 분석",
                "endpoint": "POST /api/v1/narrative/stock",
            },
            {
                "id": "portfolio",
                "name": "포트폴리오 보고서",
                "description": "백테스트 결과 + 5-Factor Attribution → 보고서",
                "endpoint": "POST /api/v1/narrative/portfolio",
            },
            {
                "id": "macro",
                "name": "매크로 브리핑",
                "description": "현재 Regime + 5종 지표 → 시장 시사점",
                "endpoint": "POST /api/v1/narrative/macro",
            },
            {
                "id": "operations",
                "name": "운영 사건 분석",
                "description": "Kill switch / Audit log → 사후 분석",
                "endpoint": "POST /api/v1/narrative/operations",
            },
            {
                "id": "counterfactual",
                "name": "What-If 시나리오",
                "description": "실제 vs 가상 시나리오 → 의사결정 가치 정량화",
                "endpoint": "POST /api/v1/narrative/counterfactual",
            },
            {
                "id": "daily",
                "name": "일일 요약",
                "description": "모든 활동 통합 요약",
                "endpoint": "POST /api/v1/narrative/daily-summary",
            },
        ],
        "streaming": "POST /api/v1/narrative/stream/{domain} (SSE)",
        "model_default": "claude-sonnet-4-6",
        "differentiators": [
            "백테스트 결과 + Attribution을 자연어로 해설",
            "Kill switch 사후 분석 (밸리AI/젠포트 없음)",
            "Counterfactual 시나리오 (유일)",
            "스크리너 결과 즉시 AI 해석",
            "스트리밍 SSE 지원",
        ],
    }
