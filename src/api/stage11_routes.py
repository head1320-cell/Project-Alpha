"""
Stage 11 API Routes — Multi-Strategy Unified Backtest
=========================================================
APIRouter 모듈. 기존 main_api.py에서 다음과 같이 통합:

  from fastapi import FastAPI
  from src.api.stage11_routes import router as stage11_router

  app = FastAPI(...)
  app.include_router(stage11_router)

이렇게 두 줄만 추가하면 Stage 11의 10개 endpoint가 자동 등록됨.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/multibacktest", tags=["multibacktest"])


# ═══════════════════════════════════════════════════════════════════════════════
# Schema 초기화
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/init-schema")
def multibacktest_init_schema():
    """multibacktest_runs + daily + strategy_daily 테이블 생성."""
    try:
        from src.database import get_sync_engine
        from src.engine.multibacktest_schema import init_multibacktest_schema
        n = init_multibacktest_schema(get_sync_engine())
        return {"status": "OK", "ddls_executed": n}
    except Exception as e:
        raise HTTPException(500, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# Run + List + Get + Delete
# ═══════════════════════════════════════════════════════════════════════════════

class MultiBacktestRunRequest(BaseModel):
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
    lookback_days:         int = Field(default=252, ge=20)
    max_weight:            float = Field(default=0.50, gt=0, le=1)
    min_weight:            float = Field(default=0.02, ge=0, lt=1)
    run_name:              str | None = None
    save:                  bool = Field(default=True)


@router.post("/run")
def multibacktest_run(req: MultiBacktestRunRequest):
    """멀티 전략 통합 백테스트 실행."""
    try:
        from src.database import get_sync_engine
        from src.engine.multi_strategy_backtest import BacktestConfig, MultiStrategyBacktester
        bt = MultiStrategyBacktester(get_sync_engine())
        config = BacktestConfig(
            strategy_ids=req.strategy_ids,
            start_date=req.start_date, end_date=req.end_date,
            initial_capital=req.initial_capital,
            allocation_method=req.allocation_method,
            rebalance_policy=req.rebalance_policy,
            netting_enabled=req.netting_enabled,
            macro_overlay_enabled=req.macro_overlay_enabled,
            commission_rate=req.commission_rate,
            slippage_rate=req.slippage_rate,
            lookback_days=req.lookback_days,
            max_weight=req.max_weight, min_weight=req.min_weight,
            run_name=req.run_name,
        )
        return bt.run_and_save(config) if req.save else bt.run(config)
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/runs")
def multibacktest_list(limit: int = Query(50, ge=1, le=200)):
    """과거 실행 이력."""
    try:
        from src.database import get_sync_engine
        from src.engine.multi_strategy_backtest import MultiStrategyBacktester
        bt = MultiStrategyBacktester(get_sync_engine())
        runs = bt.list_runs(limit=limit)
        return {"count": len(runs), "runs": runs}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/{run_id}")
def multibacktest_get(run_id: int):
    """단일 실행 상세 (daily + strategy_daily 포함)."""
    try:
        from src.database import get_sync_engine
        from src.engine.multi_strategy_backtest import MultiStrategyBacktester
        bt = MultiStrategyBacktester(get_sync_engine())
        data = bt.load_run(run_id)
        if not data:
            raise HTTPException(404, f"Run {run_id} not found")
        return data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.delete("/{run_id}")
def multibacktest_delete(run_id: int):
    """실행 삭제 (cascade)."""
    try:
        from src.database import get_sync_engine
        from src.engine.multi_strategy_backtest import MultiStrategyBacktester
        bt = MultiStrategyBacktester(get_sync_engine())
        ok = bt.delete_run(run_id)
        return {"status": "OK" if ok else "FAILED", "deleted_id": run_id}
    except Exception as e:
        raise HTTPException(500, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# Attribution
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/{run_id}/attribution")
def multibacktest_attribution(run_id: int, include_daily: bool = Query(False)):
    """5-Factor Attribution 정밀 분해 (월별/분기별/국면별)."""
    try:
        from src.database import get_sync_engine
        from src.engine.attribution_decomposer import AttributionDecomposer
        decomposer = AttributionDecomposer(get_sync_engine())
        result = decomposer.decompose(run_id, include_daily=include_daily)
        if not result.get("available"):
            raise HTTPException(404, result.get("message", "Run not found"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# Counterfactual
# ═══════════════════════════════════════════════════════════════════════════════

class CounterfactualRequest(BaseModel):
    strategy_ids:          list[int] = Field(..., min_length=1)
    start_date:            str
    end_date:              str
    initial_capital:       float = Field(default=1_000_000, gt=0)
    base_allocation_method: str = Field(default="hrp_macro")
    base_rebalance_policy: str = Field(default="monthly")
    commission_rate:       float = Field(default=0.00015)
    slippage_rate:         float = Field(default=0.0005)
    lookback_days:         int = Field(default=252)
    scenarios: list[str] = Field(
        default=["baseline", "no_macro_overlay", "no_netting", "equal_weight"],
    )


@router.post("/counterfactual")
def multibacktest_counterfactual(req: CounterfactualRequest):
    """What-If 시나리오 병렬 실행 + 의사결정 가치 정량화."""
    try:
        from src.database import get_sync_engine
        from src.engine.counterfactual_analyzer import CounterfactualAnalyzer
        from src.engine.multi_strategy_backtest import BacktestConfig

        base_config = BacktestConfig(
            strategy_ids=req.strategy_ids,
            start_date=req.start_date, end_date=req.end_date,
            initial_capital=req.initial_capital,
            allocation_method=req.base_allocation_method,
            rebalance_policy=req.base_rebalance_policy,
            commission_rate=req.commission_rate,
            slippage_rate=req.slippage_rate,
            lookback_days=req.lookback_days,
            run_name="counterfactual",
        )
        analyzer = CounterfactualAnalyzer(get_sync_engine())
        return analyzer.compare(base_config, req.scenarios)
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/counterfactual/scenarios")
def multibacktest_counterfactual_scenarios():
    """사용 가능한 카운터팩추얼 시나리오 카탈로그."""
    try:
        from src.engine.counterfactual_analyzer import PRESET_SCENARIOS
        return {
            "scenarios": [
                {"name": sc.name, "label": sc.label, "description": sc.description}
                for sc in PRESET_SCENARIOS.values()
            ]
        }
    except Exception as e:
        raise HTTPException(500, str(e))
