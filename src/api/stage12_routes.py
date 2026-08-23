"""
Stage 12 API Routes — Production Realism Engine
==================================================
Stage 11 routes에 5가지 위험 통제 endpoint 추가.

Usage (main_api.py):
  from src.api.stage11_routes import router as stage11_router
  from src.api.stage12_routes import router as stage12_router

  app.include_router(stage11_router)
  app.include_router(stage12_router)
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/realism", tags=["realism"])


# ═══════════════════════════════════════════════════════════════════════════════
# Realistic Backtest 실행
# ═══════════════════════════════════════════════════════════════════════════════

class RealismBacktestRequest(BaseModel):
    # Stage 11 기존
    strategy_ids:          list[int] = Field(..., min_length=1)
    start_date:            str
    end_date:              str
    initial_capital:       float = Field(default=1_000_000, gt=0)
    allocation_method:     str = Field(default="hrp_macro")
    rebalance_policy:      str = Field(default="monthly")
    netting_enabled:       bool = Field(default=True)
    macro_overlay_enabled: bool = Field(default=True)
    commission_rate:       float = Field(default=0.00015, ge=0)
    slippage_rate:         float = Field(default=0.0005, ge=0)
    lookback_days:         int = Field(default=252)
    max_weight:            float = Field(default=0.50, gt=0, le=1)
    min_weight:            float = Field(default=0.02, ge=0, lt=1)
    run_name:              str | None = None

    # ─ Stage 12 신규 토글 ──────────────────────────────────────────────
    enable_market_impact:       bool = Field(default=True)
    enable_cash_yield:          bool = Field(default=True)
    enable_buying_power_check:  bool = Field(default=True)
    enable_capacity_constraint: bool = Field(default=False)
    enable_regime_adaptive:     bool = Field(default=True)

    # 파라미터
    avg_adv_krw:                float = Field(default=50_000_000_000)
    weighted_alpha:             float = Field(default=0.7)
    max_pct_of_adv:             float = Field(default=0.05)
    default_rf_annual:          float = Field(default=0.035)
    cautious_risk_threshold:    float = Field(default=50.0)
    defensive_risk_threshold:   float = Field(default=70.0)
    defensive_hard_cap:         float = Field(default=0.30)
    defensive_cash_buffer:      float = Field(default=0.30)


@router.post("/backtest")
def realism_backtest(req: RealismBacktestRequest):
    """5가지 realism hook 통합 백테스트."""
    try:
        from src.database import get_sync_engine
        from src.engine.realism_engine import RealismConfig, RealisticBacktester

        bt = RealisticBacktester(get_sync_engine())
        config = RealismConfig(**req.model_dump())
        return bt.run(config)
    except Exception as e:
        raise HTTPException(500, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# Market Impact 추정
# ═══════════════════════════════════════════════════════════════════════════════

class MarketImpactRequest(BaseModel):
    order_value_krw:    float = Field(..., gt=0)
    adv_krw:            float = Field(..., gt=0)
    daily_volatility:   float = Field(default=0.018, gt=0)
    asset_class:        str = Field(default="kospi_mid")
    side:               str = Field(default="BUY")


@router.post("/market-impact/estimate")
def realism_market_impact(req: MarketImpactRequest):
    """단일 주문의 시장 충격 추정 (Square Root Law)."""
    try:
        from src.engine.market_impact import MarketImpactModel
        model = MarketImpactModel()
        est = model.estimate_impact(
            order_value_krw=req.order_value_krw,
            adv_krw=req.adv_krw,
            daily_volatility=req.daily_volatility,
            asset_class=req.asset_class,
            side=req.side,
        )
        return est.__dict__
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/market-impact/calibration")
def realism_market_impact_calibration():
    """자산군별 α calibration 카탈로그."""
    try:
        from src.engine.market_impact import ASSET_CLASS_TIERS
        return {
            "asset_classes": [
                {
                    "name": k,
                    "market_cap_threshold_krw": v[0],
                    "alpha": v[1],
                }
                for k, v in ASSET_CLASS_TIERS.items()
            ],
            "formula": "slippage_bps = α × √(Q/ADV) × σ_daily × 10⁴",
            "permanent_temporary_split": "50% / 50%",
        }
    except Exception as e:
        raise HTTPException(500, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# Cash Rate + Yield
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/cash-rate")
def realism_cash_rate(
    as_of_date: str | None = Query(None, description="YYYY-MM-DD (None=today)"),
):
    """PIT-safe 무위험금리 조회."""
    try:
        import pandas as pd

        from src.database import get_sync_engine
        from src.engine.cash_management import CashRateProvider
        provider = CashRateProvider(get_sync_engine())
        ts = pd.to_datetime(as_of_date) if as_of_date else pd.Timestamp.now()
        rate = provider.get_rate(ts)
        return {
            "as_of_date":      str(ts.date()) if hasattr(ts, "date") else str(ts),
            "rf_annual":       round(rate, 5),
            "rf_annual_pct":   round(rate * 100, 3),
            "rf_daily":        round(rate / 252, 8),
        }
    except Exception as e:
        raise HTTPException(500, str(e))


class CashYieldRequest(BaseModel):
    invested_ratio:  float = Field(..., ge=0, le=1)
    as_of_date:      str
    cash_floor:      float = Field(default=0.0, ge=0)


@router.post("/cash-yield/estimate")
def realism_cash_yield(req: CashYieldRequest):
    """주어진 투자 비중에서 유휴 현금 일별 이자 수익."""
    try:
        import pandas as pd

        from src.database import get_sync_engine
        from src.engine.cash_management import CashRateProvider, CashYieldCalculator
        provider = CashRateProvider(get_sync_engine())
        calc = CashYieldCalculator(provider)
        return calc.daily_yield(
            invested_ratio=req.invested_ratio,
            as_of_date=pd.to_datetime(req.as_of_date),
            cash_floor=req.cash_floor,
        )
    except Exception as e:
        raise HTTPException(500, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# Buying Power Validator
# ═══════════════════════════════════════════════════════════════════════════════

class OrderItem(BaseModel):
    ticker:      str
    side:        str
    quantity:    int = Field(..., gt=0)
    price:       float = Field(..., gt=0)
    strategy_id: int | None = None


class BuyingPowerRequest(BaseModel):
    orders:             list[OrderItem]
    available_cash_krw: float = Field(..., ge=0)
    max_leverage:       float = Field(default=1.0, ge=1.0)
    mode:               str = Field(default="prorata",
                                     description="prorata | priority | strict")
    strategy_priorities: dict | None = None


@router.post("/buying-power/validate")
def realism_buying_power(req: BuyingPowerRequest):
    """매수 주문 합산 검증 + 필요 시 자동 축소."""
    try:
        from src.engine.cash_management import BuyingPowerValidator
        orders = [o.model_dump() for o in req.orders]
        return BuyingPowerValidator.validate(
            orders=orders,
            available_cash_krw=req.available_cash_krw,
            strategy_priorities=req.strategy_priorities,
            max_leverage=req.max_leverage,
            mode=req.mode,
        )
    except Exception as e:
        raise HTTPException(500, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# Liquidity Capacity
# ═══════════════════════════════════════════════════════════════════════════════

class CapacityRequest(BaseModel):
    strategy_ids:        list[int] = Field(..., min_length=1)
    as_of_date:          str
    max_pct_of_adv:      float = Field(default=0.05)
    holding_period_days: int = Field(default=5)
    safety_buffer:       float = Field(default=0.7)


@router.post("/capacity/estimate")
def realism_capacity_estimate(req: CapacityRequest):
    """전략별 수용량 추정 (ADV × max_pct × holding_period)."""
    try:
        from src.database import get_sync_engine
        from src.engine.liquidity_capacity import (
            CapacityConfig,
            LiquidityCapacityEstimator,
        )
        config = CapacityConfig(
            max_pct_of_adv=req.max_pct_of_adv,
            holding_period_days=req.holding_period_days,
            safety_buffer=req.safety_buffer,
        )
        estimator = LiquidityCapacityEstimator(get_sync_engine(), config)
        capacities = estimator.estimate_capacities(req.strategy_ids, req.as_of_date)
        return {
            "as_of_date":  req.as_of_date,
            "capacities":  capacities,
            "config":      config.__dict__,
        }
    except Exception as e:
        raise HTTPException(500, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# Correlation Health Check
# ═══════════════════════════════════════════════════════════════════════════════

class CorrelationHealthRequest(BaseModel):
    strategy_ids:   list[int] = Field(..., min_length=2)
    start_date:     str | None = None
    end_date:       str | None = None
    lookback_days:  int = Field(default=60)


@router.post("/correlation-health")
def realism_correlation_health(req: CorrelationHealthRequest):
    """상관관계 매트릭스 건강도 분석 (breakdown 감지)."""
    try:
        from src.database import get_sync_engine
        from src.engine.regime_adaptive_allocator import RegimeAdaptiveAllocator
        from src.engine.strategy_registry import StrategyRegistry

        reg = StrategyRegistry(get_sync_engine())
        matrix = reg.load_returns_matrix(
            strategy_ids=req.strategy_ids,
            start_date=req.start_date, end_date=req.end_date,
        )

        if matrix.empty:
            return {"available": False, "message": "Returns 데이터 부족"}

        # 최근 N일 분석
        recent = matrix.tail(req.lookback_days)
        diagnostics = RegimeAdaptiveAllocator._analyze_correlation_health(recent)

        return {
            "available":     True,
            "n_strategies":  len(req.strategy_ids),
            "lookback_days": req.lookback_days,
            "analysis":      diagnostics,
            "interpretation": _interpret_correlation_health(diagnostics),
        }
    except Exception as e:
        raise HTTPException(500, str(e))


def _interpret_correlation_health(d: dict) -> dict:
    """건강도 분석 결과 해석."""
    avg = d.get("avg_correlation", 0)
    eig = d.get("max_eigenvalue_ratio", 0)

    if d.get("breakdown_detected"):
        if avg > 0.85:
            level = "CRITICAL"; advice = "Defensive 모드 권장 — hard cap + cash buffer"
        elif avg > 0.7:
            level = "WARNING"; advice = "Cautious 모드 권장 — EWMA covariance 활성화"
        else:
            level = "WATCH"; advice = "Single factor dominance 감지 — 분산 효과 약화"
    elif eig > 0.5:
        level = "FAIR"; advice = "Single factor 비중이 높음 — 모니터링 권장"
    elif avg > 0.5:
        level = "FAIR"; advice = "전략 간 상관 보통 — 분산 효과 제한적"
    else:
        level = "HEALTHY"; advice = "분산 효과 양호"

    return {"level": level, "advice": advice}
