"""BacktestRun API — create / status / result / cancel / retry (Backtest Run Workflow 5b)
==============================================================================
POST   /api/v1/backtest/runs                 — 실행 생성(queued) + 백그라운드 워커 기동, run_id 즉시 반환
GET    /api/v1/backtest/runs/{run_id}/status  — 폴링용 경량 상태(진행률·단계)
GET    /api/v1/backtest/runs/{run_id}         — 전체(완료 시 result 포함)
POST   /api/v1/backtest/runs/{run_id}/cancel   — 취소(비종료 상태만)
POST   /api/v1/backtest/runs/{run_id}/retry    — 동일 입력으로 새 run 생성(이력 불변)
GET    /api/v1/backtest/runs                   — 최근 실행 목록(비교·이력)

워커는 main_api의 _INGEST_STATUS 스레드 패턴과 동일하게 백그라운드 스레드에서 기존
엔진(_screen_to_backtest_core)을 돌리고, 진행/단계를 backtest_runs(DB)에 영속한다 →
새로고침·직접 URL·네트워크 단절에도 상태 복구.
"""

from __future__ import annotations

import logging
import threading

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

import src.data.backtest_runs as br

logger = logging.getLogger("api.backtest_run")

router = APIRouter(prefix="/api/v1/backtest", tags=["backtest-run"])


class CreateRunRequest(BaseModel):
    # screen-to-backtest 설정 전체를 그대로 담는다(입력 스냅샷 = 재현 단위).
    config: dict = Field(..., description="ScreenToBacktestRequest 페이로드")
    strategy_name: str = Field("백테스트", max_length=120)
    requested_by: str = Field("user", max_length=60)


class _Cancelled(Exception):
    pass


def _worker(run_id: str, config: dict) -> None:
    """백그라운드 실행 — 상태/진행을 DB에 영속. 예외는 failed로 정직 기록(민감정보 제외)."""
    try:
        from src.api.screener_routes import ScreenToBacktestRequest, _screen_to_backtest_core

        br.transition(run_id, "validating")
        try:
            req = ScreenToBacktestRequest(**config)
        except Exception as e:
            br.set_error(run_id, "invalid_config", f"설정 검증 실패: {e}")
            return

        seen = {"stage": "validating"}

        def cb(evt: dict) -> None:
            """진행 보고 + 협조적 취소 감지.

            ★커넥션 1회★: 예전엔 이벤트마다 (취소확인 SELECT + advance의 SELECT + UPDATE)로
            풀(pool_size=5 + overflow=10)에서 3번 체크아웃했다. 같은 단계 안의 세부 진행은
            조건부 UPDATE 한 번(touch_progress)이면 되고, 그 UPDATE가 걸리지 않을 때만
            (= 없거나 종료 상태) 상태를 확인한다. 단계가 바뀔 때만 advance로 전이한다.
            """
            phase = evt.get("phase")
            done, total = evt.get("done"), evt.get("total")
            if phase in ("screening", "screened", "loading"):
                stage = "loading_data"
                pct = 10 + (18 * done / total if done and total else 0)
                msg = f"데이터 로딩 {done}/{total}" if total else None
            elif phase == "simulating":
                stage = "simulating"
                pct = 30 + (55 * done / total if done and total else 0)
                msg = f"시뮬레이션 {done}/{total}일" if total else "주문·체결 시뮬레이션"
            else:
                return

            if seen["stage"] == stage:
                if br.touch_progress(run_id, pct, msg) == "blocked":
                    st = br.get_status(run_id)
                    if st and st["status"] == "cancelled":
                        raise _Cancelled()
                return

            r = br.advance(run_id, stage, message=msg, progress=pct)
            if r.get("cancelled"):
                raise _Cancelled()
            seen["stage"] = stage

        try:
            result = _screen_to_backtest_core(req, progress_cb=cb)
        except _Cancelled:
            logger.info(f"backtest run {run_id} 취소 감지 — 워커 정지")
            return
        except Exception:
            logger.exception(f"backtest run {run_id} 엔진 실패")
            br.set_error(run_id, "engine_error", "백테스트 실행 중 오류가 발생했습니다.")
            return

        # 엔진이 지표까지 계산해 반환 → 마무리 단계 전이 후 결과 저장
        br.advance(run_id, "calculating_metrics", message="성과·리스크 지표 정리", progress=88)
        br.advance(run_id, "persisting_results", message="재현 가능한 결과 저장", progress=96)
        ds = (result or {}).get("data_source") or {}
        is_mock = None
        if isinstance(ds, dict):
            fully_real = ds.get("fully_real")
            is_mock = (not fully_real) if fully_real is not None else None
        # 취소가 그 사이 들어왔으면 저장하지 않음
        st = br.get_status(run_id)
        if st and st["status"] == "cancelled":
            return
        r = br.set_result(run_id, result, is_mock_data=is_mock)
        if not r["ok"]:
            br.set_error(run_id, "persist_error", "결과 저장에 실패했습니다.")
    except Exception:
        logger.exception(f"backtest worker {run_id} 예기치 못한 실패")
        try:
            br.set_error(run_id, "worker_error", "실행 처리 중 오류가 발생했습니다.")
        except Exception:
            pass


@router.post("/runs")
def create_run(req: CreateRunRequest):
    """실행 생성 + 백그라운드 워커 기동. run_id 즉시 반환(결과 대기 없음)."""
    try:
        run_id = br.create_run(req.strategy_name, req.config, requested_by=req.requested_by)
        if run_id is None:
            raise HTTPException(503, "실행 저장소(DB)를 사용할 수 없어 백테스트를 생성할 수 없습니다.")
        t = threading.Thread(target=_worker, args=(run_id, req.config), daemon=True)
        t.start()
        return {"run_id": run_id, "status": "queued"}
    except HTTPException:
        raise
    except Exception:
        logger.exception("backtest run 생성 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/runs")
def list_runs(limit: int = Query(30, ge=1, le=100)):
    try:
        return {"runs": br.list_runs(limit=limit)}
    except Exception:
        logger.exception("backtest runs 목록 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/runs/{run_id}/status")
def run_status(run_id: str):
    # strict=True → DB 오류는 503(일시적, 프론트가 재시도), 진짜 없음만 404
    try:
        st = br.get_status(run_id, strict=True)
    except br.BacktestStoreError:
        raise HTTPException(503, "실행 저장소를 일시적으로 사용할 수 없습니다 — 잠시 후 재시도하세요.")
    if st is None:
        raise HTTPException(404, "실행을 찾을 수 없습니다.")
    return st


@router.get("/runs/{run_id}")
def run_full(run_id: str):
    try:
        r = br.get_run(run_id, strict=True)
    except br.BacktestStoreError:
        raise HTTPException(503, "실행 저장소를 일시적으로 사용할 수 없습니다 — 잠시 후 재시도하세요.")
    if r is None:
        raise HTTPException(404, "실행을 찾을 수 없습니다.")
    return r


@router.post("/runs/{run_id}/cancel")
def run_cancel(run_id: str):
    r = br.cancel(run_id)
    if not r["ok"]:
        # 사유별로 정직하게 구분 — 예전엔 '없음'과 'DB 오류'까지 409로 나가 프론트가
        # "이미 끝난 실행"으로 오해했다. run_status와 같은 매핑을 쓴다.
        if r.get("missing"):
            raise HTTPException(404, r["reason"])
        if r.get("store_error"):
            raise HTTPException(503, r["reason"])
        raise HTTPException(409, r["reason"])
    return {"ok": True, "status": "cancelled"}


@router.post("/runs/{run_id}/retry")
def run_retry(run_id: str):
    """동일 입력으로 새 실행 생성(이력 불변 — 원 실행은 그대로)."""
    src = br.get_run(run_id)
    if src is None:
        raise HTTPException(404, "실행을 찾을 수 없습니다.")
    config = src.get("input_snapshot") or {}
    new_id = br.create_run(src.get("strategy_name") or "백테스트", config,
                           requested_by=src.get("requested_by") or "user")
    if new_id is None:
        raise HTTPException(503, "실행 저장소(DB)를 사용할 수 없습니다.")
    threading.Thread(target=_worker, args=(new_id, config), daemon=True).start()
    return {"run_id": new_id, "status": "queued", "retried_from": run_id}


@router.delete("/runs/{run_id}")
def run_delete(run_id: str):
    if not br.delete_run(run_id):
        raise HTTPException(404, "실행을 찾을 수 없습니다.")
    return {"deleted": True}
