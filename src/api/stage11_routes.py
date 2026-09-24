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

from src.domain.perf_kind import backtest_label

router = APIRouter(prefix="/api/v1/multibacktest", tags=["multibacktest"])

#: 비용 요율의 런타임 출처를 말하는 문 이름 (BB) — ★문마다 달라야 한다★
_DOOR_MULTIBACKTEST_RUN = "multibacktest/run"
_DOOR_MULTIBACKTEST_COUNTERFACTUAL = "multibacktest/counterfactual"
#: 이 엔진에 **있는** 비용 성분. 세금·스프레드·충격은 ★없다★(끈 것이 아니다).
_ENGINE = "multi_strategy_backtest"
_SUPPORTED = ("commission", "slippage")


def _cost_block(req: BaseModel, door: str) -> dict:
    """★엔진에 넘긴 그 요율★로 `cost_model` 블록을 만든다. 엔진 내부는 불변."""
    from src.domain.cost_provenance import door_cost_block
    return door_cost_block(
        commission_rate=req.commission_rate, slippage_rate=req.slippage_rate,
        cost_door=door,
        cost_explicit_fields=frozenset(req.model_fields_set),
        cost_available_fields=frozenset(type(req).model_fields),
        engine=_ENGINE, supported=_SUPPORTED)


def _perf_label() -> dict:
    """이 라우터가 내놓는 수치는 전부 **과거 데이터 위의 시뮬레이션**이다.

    ★데이터 축은 mock 게이트가 유일한 판정 기준이다★ (`CLAUDE.md` §6) — 여기서
    따로 추론하지 않는다. 세 엔드포인트(실행 조회 · 기여도 분해 · 카운터팩추얼)가
    같은 파생을 쓰므로 한 군데에 둔다.
    """
    from src.data.mock_gate import mock_allowed
    return backtest_label(is_mock_data=mock_allowed()).to_dict()


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
        out = bt.run_and_save(config) if req.save else bt.run(config)
        # ★돌지 않은 실행에 "부과했다" 를 붙이지 않는다★
        if isinstance(out, dict) and out.get("success"):
            out["cost_model"] = _cost_block(req, _DOOR_MULTIBACKTEST_RUN)
        return out
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
        data["perf_label"] = _perf_label()
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
        # 국면별 알파 표(`RegimeAttributionTable`)가 이 응답을 그린다 — 라벨이 없었다.
        result["perf_label"] = _perf_label()
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
        out = analyzer.compare(base_config, req.scenarios)
        # ★대안 시나리오도 시뮬레이션이다★ — "what-if" 는 종류를 바꾸지 않는다.
        out["perf_label"] = _perf_label()
        # ★모든 시나리오가 같은 요율을 받는다★(counterfactual_analyzer 실측) —
        # 그래서 블록 하나가 시나리오 전부를 말한다.
        out["cost_model"] = _cost_block(req, _DOOR_MULTIBACKTEST_COUNTERFACTUAL)
        return out
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
