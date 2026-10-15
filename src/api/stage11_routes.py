"""
Stage 11 API Routes — Multi-Strategy Unified Backtest
=========================================================
APIRouter 모듈. 기존 main_api.py에서 다음과 같이 통합:

  from fastapi import FastAPI
  from src.api.stage11_routes import router as stage11_router

  app = FastAPI(...)
  app.include_router(stage11_router)

(ST2, 2026-10-15) 여러 전략 백테스트 화면을 없애며 경로는 `/run`(현실성 점검이 아직 쓴다 — ST3 에서 정리)과
등록 전략 셋(`/strategies` 목록·등록·비활성 — 캔버스 전략 고르기)만 남겼다. `multibacktest_counterfactual` 은
경로 없이 캔버스 `counterfactual` 노드가 함수로 부른다.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.domain.perf_kind import backtest_label
from src.engine.multistrategy_availability import http_unavailable, http_unsupported

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


def _guard(**requested) -> None:
    """★`try:` 앞에서 부른다★ — 코어가 없으면 503, 요청이 없는 기능을 골랐으면 422.

    뒤의 `except Exception → 500` 이 HTTPException 까지 삼키므로 반드시 앞이다(BF·BG4).
    """
    if (unavailable := http_unavailable()) is not None:
        raise unavailable
    if (unsupported := http_unsupported(**requested)) is not None:
        raise unsupported


def _sources(engine, strategy_ids) -> dict:
    """★결과가 무엇에서 나왔는가★ (BG5) — 전략별 원천 실행 · mock · PIT · 재현.

    레지스트리를 못 읽으면 `available: False` + 사유다 — 빈 목록을 "출처 없음" 으로
    위장하지 않는다. 등록되지 않은 id 는 `registered: False` + 사유(원천 미상).
    """
    try:
        from src.engine.strategy_registry import StrategyRegistry
        reg = StrategyRegistry(engine)
        out = []
        for sid in strategy_ids:
            s = reg.get(sid)
            if s is None:
                out.append({"strategy_id": int(sid), "registered": False,
                            "is_mock_data": None, "is_pit_verified": None,
                            "reason": f"전략 {sid} 가 레지스트리에 없습니다 — 원천을 모릅니다."})
                continue
            repro = s.get("repro") or {}
            out.append({"strategy_id": s["id"], "registered": True, "name": s["name"],
                        "source_run_id": s["source_run_id"], "is_active": s["is_active"],
                        "is_mock_data": s["is_mock_data"],
                        "is_pit_verified": s["is_pit_verified"],
                        "repro_equal": repro.get("equal"),
                        "repro_compared_points": repro.get("compared_points")})
        return {"available": True, "strategies": out, "reason": None}
    except Exception as e:                                    # noqa: BLE001
        return {"available": False, "strategies": [],
                "reason": f"레지스트리를 읽지 못했습니다 — {type(e).__name__}: {e}"}


def _label_from_sources(strategies: list[dict]) -> dict:
    """★원천 실행들의 mock 여부로★ 정한다 (스펙 §4.5).

    멀티전략은 새 데이터를 읽지 않는다 — 등록 때 저장된 수익률만 쓴다. 그러니 이 결과의
    데이터 축은 **지금의** mock 게이트가 아니라 원천 실행이 돌 때의 표시다. 하나라도
    mock 이면 mock, 전부 실데이터면 실데이터, 모르는 것이 섞이면 미상.
    """
    flags = [s.get("is_mock_data") for s in strategies]
    if any(f is True for f in flags):
        mock = True
    elif flags and all(f is False for f in flags):
        mock = False
    else:
        mock = None
    return backtest_label(is_mock_data=mock).to_dict()


def _attach_sources(out: dict, engine, strategy_ids) -> dict:
    src = _sources(engine, strategy_ids)
    out["sources"] = src
    out["perf_label"] = _label_from_sources(src["strategies"])
    return out


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
    #: ★국면 판정 시장★ (BH3) — regime_change 트리거·결과 `regime` 칸. 두 시장 라벨은 늘 실린다.
    regime_market:         Literal["kr", "us"] = Field(default="kr")


def multibacktest_run(req: MultiBacktestRunRequest):
    """멀티 전략 통합 백테스트 실행 — ★경로 없는 함수★(ST3c, 2026-10-15).

    HTTP 경로 `POST /multibacktest/run` 은 지웠다 — 부르던 화면(현실성 점검)은 이상 쪽을
    `/realism/backtest` 현실 조건 전부 끔으로 계산한다(`tests/test_realism_ideal_equivalence.py` 가
    두 엔진의 일별 자산이 같음을 건다). 캔버스 `strategy_backtest` 노드가 이 함수를 그대로 부른다.
    """
    # ★코어가 없으면 503 · 없는 기능을 고르면 422★ (BF·BG4) — `try:` 앞이어야 한다.
    _guard(allocation_method=req.allocation_method, rebalance_policy=req.rebalance_policy)
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
            regime_market=req.regime_market,
        )
        out = bt.run_and_save(config) if req.save else bt.run(config)
        # ★돌지 않은 실행에 "부과했다" 를 붙이지 않는다★
        if isinstance(out, dict) and out.get("success"):
            out["cost_model"] = _cost_block(req, _DOOR_MULTIBACKTEST_RUN)
            _attach_sources(out, get_sync_engine(), req.strategy_ids)
        return out
    except Exception as e:
        raise HTTPException(500, str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# 전략 레지스트리 (BG5) — ★`/{run_id}` 보다 먼저 등록한다★
# `/{run_id}` 가 먼저면 `GET /strategies` 가 거기에 걸려 정수 파싱 422 가 된다.
# ═══════════════════════════════════════════════════════════════════════════════

class RegisterStrategyRequest(BaseModel):
    run_id: str = Field(..., min_length=1, max_length=64)
    name:   str | None = Field(default=None, max_length=200)


@router.get("/strategies")
def multibacktest_strategies(active_only: bool = Query(True)):
    """등록된 전략 — 프런트 `Strategy`(`id`·`name`·`is_active`) + 원천 표시."""
    _guard()
    try:
        from src.database import get_sync_engine
        from src.engine.strategy_registry import StrategyRegistry
        items = StrategyRegistry(get_sync_engine()).list(active_only=active_only)
        return {"count": len(items), "strategies": items}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/strategies")
def multibacktest_register_strategy(req: RegisterStrategyRequest):
    """저장된 백테스트 실행 → 전략. ★다시 돌려 같을 때만★ — 아니면 409 + 사유."""
    _guard()
    from src.engine.strategy_registry import RegistrationRefused
    try:
        from src.database import get_sync_engine
        from src.engine.strategy_registry import StrategyRegistry
        return StrategyRegistry(get_sync_engine()).register(req.run_id, req.name)
    except RegistrationRefused as e:
        # ★409 — 요청은 옳지만 지금 상태로는 받아들일 수 없다★ (재현 불일치 · 중복 ·
        # 미완료 · 재현 불가 설정). 사유와 근거(첫 불일치 등)를 그대로 싣는다.
        raise HTTPException(409, detail={"reason": e.reason, **(e.detail or {})})
    except Exception as e:
        raise HTTPException(500, str(e))


@router.delete("/strategies/{strategy_id}")
def multibacktest_deactivate_strategy(strategy_id: int):
    """비활성 — 지우지 않는다(지난 실행의 출처가 사라지면 안 된다)."""
    _guard()
    try:
        from src.database import get_sync_engine
        from src.engine.strategy_registry import StrategyRegistry
        ok = StrategyRegistry(get_sync_engine()).deactivate(strategy_id)
    except Exception as e:
        raise HTTPException(500, str(e))
    if not ok:
        raise HTTPException(404, f"전략 {strategy_id} 가 없습니다.")
    return {"status": "OK", "deactivated_id": strategy_id}


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
    regime_market:         Literal["kr", "us"] = Field(default="kr")


def multibacktest_counterfactual(req: CounterfactualRequest):
    """What-If 시나리오 병렬 실행 + 의사결정 가치 정량화."""
    # ★코어가 없으면 503 · 없는 기능을 고르면 422★ (BF·BG4) — 시나리오는 배분을
    # hrp·inverse_vol 로만 덮어쓰고 리밸런싱은 그대로 두므로 기준 구성만 보면 된다.
    _guard(allocation_method=req.base_allocation_method,
           rebalance_policy=req.base_rebalance_policy)
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
            regime_market=req.regime_market,
        )
        analyzer = CounterfactualAnalyzer(get_sync_engine())
        out = analyzer.compare(base_config, req.scenarios)
        # ★대안 시나리오도 시뮬레이션이다★ — "what-if" 는 종류를 바꾸지 않는다.
        # 라벨은 원천 실행들의 mock 여부로 정한다(BG5).
        _attach_sources(out, get_sync_engine(), req.strategy_ids)
        # ★모든 시나리오가 같은 요율을 받는다★(counterfactual_analyzer 실측) —
        # 그래서 블록 하나가 시나리오 전부를 말한다.
        out["cost_model"] = _cost_block(req, _DOOR_MULTIBACKTEST_COUNTERFACTUAL)
        return out
    except Exception as e:
        raise HTTPException(500, str(e))
