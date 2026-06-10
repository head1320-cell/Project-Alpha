"""
Valuation API Routes — 종목 가치평가
==============================================
밸리AI의 '종목 가치평가' 대응 API.

POST /api/v1/valuation/evaluate         — 단일 종목 3-모델 통합 평가
POST /api/v1/valuation/compare          — 다중 종목 비교 평가
GET  /api/v1/valuation/financial/{code}  — 재무제표 조회
GET  /api/v1/valuation/models           — 사용 가능 모델 카탈로그
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/valuation", tags=["valuation"])


# ═══════════════════════════════════════════════════════════════════════════════
# Request/Response Models
# ═══════════════════════════════════════════════════════════════════════════════

class EvaluateRequest(BaseModel):
    stock_code:      str = Field(..., min_length=4, max_length=10,
                                   description="KRX 종목코드 (예: 005930)")
    current_price:   float = Field(..., gt=0, description="현재 주가 (원)")
    bsns_year:       str | None = Field(None, description="사업연도 (기본: 직전)")
    beta:            float = Field(default=1.0, ge=0.1, le=3.0)
    risk_free_rate:  float = Field(default=0.035, ge=0, le=0.15)
    market_premium:  float = Field(default=0.06, ge=0, le=0.15)
    terminal_growth: float = Field(default=0.02, ge=0, le=0.05)
    projection_years: int = Field(default=10, ge=3, le=20)
    weight_rim:      float = Field(default=0.40, ge=0, le=1)
    weight_dcf:      float = Field(default=0.40, ge=0, le=1)
    weight_ddm:      float = Field(default=0.20, ge=0, le=1)


class CompareRequest(BaseModel):
    stocks: list[dict] = Field(
        ..., min_length=1, max_length=20,
        description="[{stock_code, current_price}, ...]",
    )
    beta:            float = Field(default=1.0)
    projection_years: int = Field(default=10)


# ═══════════════════════════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/evaluate")
def valuation_evaluate(req: EvaluateRequest):
    """단일 종목 3-모델 통합 가치평가."""
    try:
        from src.data.dart_client import DARTClient
        from src.engine.valuation.valuation_models import (
            ValuationEngine,
            ValuationParams,
        )

        params = ValuationParams(
            risk_free_rate=req.risk_free_rate,
            market_premium=req.market_premium,
            beta=req.beta,
            terminal_growth_rate=req.terminal_growth,
            projection_years=req.projection_years,
            weight_rim=req.weight_rim,
            weight_dcf=req.weight_dcf,
            weight_ddm=req.weight_ddm,
        )

        engine = ValuationEngine(DARTClient())
        result = engine.evaluate(
            stock_code=req.stock_code,
            current_price=req.current_price,
            params=params,
            bsns_year=req.bsns_year,
        )

        return {
            "ticker":              result.ticker,
            "corp_name":           result.corp_name,
            "current_price":       result.current_price,
            "intrinsic_value":     result.intrinsic_value,
            "gap_pct":             result.gap_pct,
            "verdict":             result.verdict,
            "models": [
                {
                    "model":            m.model,
                    "intrinsic_value":  m.intrinsic_value_per_share,
                    "available":        m.available,
                    "error":            m.error,
                    "components":       m.components,
                    "assumptions":      m.assumptions,
                }
                for m in result.models
            ],
            "financial_summary":   result.financial_summary,
            "params":              result.params,
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/compare")
def valuation_compare(req: CompareRequest):
    """다중 종목 비교 평가."""
    try:
        from src.data.dart_client import DARTClient
        from src.engine.valuation.valuation_models import (
            ValuationEngine,
            ValuationParams,
        )

        params = ValuationParams(
            beta=req.beta,
            projection_years=req.projection_years,
        )
        engine = ValuationEngine(DARTClient())

        results = []
        for stock in req.stocks:
            try:
                r = engine.evaluate(
                    stock_code=stock["stock_code"],
                    current_price=stock["current_price"],
                    params=params,
                )
                results.append({
                    "ticker":          r.ticker,
                    "corp_name":       r.corp_name,
                    "current_price":   r.current_price,
                    "intrinsic_value": r.intrinsic_value,
                    "gap_pct":         r.gap_pct,
                    "verdict":         r.verdict,
                    "roe_pct":         r.financial_summary.get("roe_pct"),
                    "per":             r.financial_summary.get("per"),
                    "pbr":             r.financial_summary.get("pbr"),
                })
            except Exception as e:
                results.append({
                    "ticker": stock.get("stock_code"),
                    "error": str(e),
                })

        # 괴리율 순 정렬 (저평가 → 고평가)
        results.sort(key=lambda x: x.get("gap_pct", 999))

        return {
            "count":   len(results),
            "results": results,
        }
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/financial/{stock_code}")
def valuation_financial(
    stock_code: str,
    years: int = Query(5, ge=1, le=10),
):
    """종목 재무제표 N년 시계열."""
    try:
        from src.data.dart_client import DARTClient, get_corp_code

        client = DARTClient()
        corp_code = get_corp_code(stock_code)
        if not corp_code:
            raise HTTPException(404, f"종목코드 {stock_code} 미등록")

        history = client.get_financial_history(corp_code, years=years)
        corp_info = client.get_corp_info(corp_code)

        return {
            "stock_code":  stock_code,
            "corp_name":   corp_info.corp_name if corp_info else "",
            "sector":      corp_info.sector if corp_info else "",
            "n_years":     len(history),
            "financials": [
                {
                    "year":                fs.bsns_year,
                    "revenue_억":          round(fs.revenue / 1e8, 0) if fs.revenue else None,
                    "operating_profit_억": round(fs.operating_profit / 1e8, 0) if fs.operating_profit else None,
                    "net_income_억":       round(fs.net_income / 1e8, 0) if fs.net_income else None,
                    "total_assets_억":     round(fs.total_assets / 1e8, 0) if fs.total_assets else None,
                    "total_equity_억":     round(fs.total_equity / 1e8, 0) if fs.total_equity else None,
                    "fcf_억":              round(fs.fcf / 1e8, 0) if fs.fcf else None,
                    "roe_pct":             round(fs.roe, 2) if fs.roe else None,
                    "roa_pct":             round(fs.roa, 2) if fs.roa else None,
                    "debt_ratio_pct":      round(fs.debt_ratio, 1) if fs.debt_ratio else None,
                    "eps":                 round(fs.eps, 0) if fs.eps else None,
                    "bps":                 round(fs.bps, 0) if fs.bps else None,
                    "dps":                 round(fs.dps, 0) if fs.dps else None,
                }
                for fs in history
            ],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/models")
def valuation_models_catalog():
    """사용 가능 가치평가 모델 카탈로그."""
    return {
        "models": [
            {
                "id": "RIM",
                "name": "잔여이익모델 (Residual Income Model)",
                "formula": "V₀ = BPS₀ + Σ [(ROEₜ - Kₑ)×BPSₜ₋₁]/(1+Kₑ)ᵗ + TV",
                "best_for": "수익성 높은 기업 (ROE > Kₑ)",
                "limitation": "ROE < Kₑ인 기업은 부정적 잔여이익",
                "default_weight": 0.40,
            },
            {
                "id": "DCF",
                "name": "현금흐름할인법 (Discounted Cash Flow)",
                "formula": "V₀ = Σ FCFₜ/(1+WACC)ᵗ + TV/(1+WACC)ⁿ",
                "best_for": "안정적 현금흐름 기업, 성숙 산업",
                "limitation": "초기 성장기 기업은 FCF<0 가능",
                "default_weight": 0.40,
            },
            {
                "id": "DDM",
                "name": "배당할인법 (Dividend Discount Model)",
                "formula": "V₀ = Σ Dₜ/(1+Kₑ)ᵗ + Pₙ/(1+Kₑ)ⁿ",
                "best_for": "배당주, 금융주, 유틸리티",
                "limitation": "무배당 기업 적용 불가",
                "default_weight": 0.20,
            },
        ],
        "common_params": {
            "risk_free_rate": "한국 국채 10년 (~3.5%)",
            "market_premium": "한국 ERP (~6.0%)",
            "beta": "CAPM 베타 (1.0 기본)",
            "terminal_growth": "영구 성장률 (2.0% = 명목GDP 근사)",
        },
    }
