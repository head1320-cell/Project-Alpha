"""RegimeSnapshot API — 매크로 국면의 불변 스냅샷 생성·조회·비교.

POST   /api/v1/regime-snapshots            — 스냅샷 생성 (as_of + 관측치 + 축/확률)
GET    /api/v1/regime-snapshots            — 목록 (요약, 최신순)
GET    /api/v1/regime-snapshots/{sid}      — 단건 전체 (관측치 신원 포함)
GET    /api/v1/regime-snapshots/compare    — 두 스냅샷 차이
DELETE /api/v1/regime-snapshots/{sid}

AAS 는 이 ID 를 참조한다 — 휘발성 객체를 복사해 가지 않는다.

정직 규약(기존 라우터와 동일):
  · DB 미가용 → 500 이 아니라 recorded=False 로 보고
  · as_of 이후 공표 관측치 → 422 로 **거부**(경고 후 진행 아님)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger("api.regime_snapshot")

router = APIRouter(prefix="/api/v1/regime-snapshots", tags=["regime-snapshots"])


class ObservationIn(BaseModel):
    """관측치는 맨 숫자가 아니라 신원과 함께 받는다 — 없으면 재현이 성립하지 않는다."""
    series_id: str = Field(..., min_length=1, max_length=64)
    observation_period: str = Field(..., max_length=32)
    release_timestamp: str = Field(..., max_length=32)
    value: float
    vintage_id: str = Field("", max_length=64)
    retrieved_at: str = Field("", max_length=40)
    data_status: str = Field("real", max_length=20)


class CreateSnapshotRequest(BaseModel):
    as_of: str = Field(..., max_length=32)
    observations: list[ObservationIn] = Field(default_factory=list)
    growth_axis: float = 0.0
    inflation_axis: float = 0.0
    phase_probabilities: dict[str, float] = Field(default_factory=dict)
    stress_score: float = 0.0
    confidence: float = 0.0
    explanation: str = Field("", max_length=4000)


def _to_domain(items: list[ObservationIn]):
    from src.data.pit_macro import DataStatus, MacroObservation
    out = []
    for o in items:
        try:
            status = DataStatus(o.data_status)
        except ValueError:
            status = DataStatus.UNAVAILABLE
        out.append(MacroObservation(
            series_id=o.series_id, observation_period=o.observation_period,
            release_timestamp=o.release_timestamp, vintage_id=o.vintage_id,
            retrieved_at=o.retrieved_at, value=o.value, data_status=status,
        ))
    return out


@router.post("")
def create(req: CreateSnapshotRequest):
    from src.data.regime_snapshots import LookAheadError, create_snapshot
    try:
        sid = create_snapshot(
            as_of=req.as_of, observations=_to_domain(req.observations),
            growth_axis=req.growth_axis, inflation_axis=req.inflation_axis,
            phase_probabilities=req.phase_probabilities,
            stress_score=req.stress_score, confidence=req.confidence,
            explanation=req.explanation,
        )
    except LookAheadError as e:
        # 데이터 정합성 위반은 조용히 넘기지 않는다.
        raise HTTPException(422, str(e))
    except Exception:
        logger.exception("regime snapshot 생성 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")

    if sid is None:
        return {"recorded": False, "snapshot_id": None,
                "message": "DB 미가용 — 스냅샷이 저장되지 않았습니다."}
    return {"recorded": True, "snapshot_id": sid}


@router.get("")
def list_all(limit: int = Query(50, ge=1, le=200)):
    try:
        from src.data.regime_snapshots import list_snapshots
        return {"snapshots": list_snapshots(limit=limit)}
    except Exception:
        logger.exception("regime snapshot 목록 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.post("/from-current")
def create_from_current(market: str = Query("kr", pattern="^(kr|us)$")):
    """지금 국면 판정을 그대로 스냅샷으로 굳힌다 — Macro 탭의 "Allocation Studio에서 열기".

    주의(정직): 대시보드 수집기는 아직 빈티지를 모르므로(ALFRED 경로는 Phase 7b) 이렇게 만든
    스냅샷은 **forward_only + partial** 로 내려간다. 전방 리서치 맥락으로는 쓸 수 있지만
    과거 시뮬레이션에서는 차단된다. 응답에 그대로 실어 보내 UI 가 숨기지 않게 한다.
    """
    from src.data.regime_snapshots import LookAheadError
    from src.engine.regime_snapshot_builder import build_and_store
    try:
        sid = build_and_store(market=market)
    except LookAheadError as e:
        # 데이터 정합성 위반이지 서버 장애가 아니다 → 422.
        # 실제로 도달 가능하다: 수집기의 last_update 가 분석기 timestamp 보다 뒤면 PIT 게이트가 걸린다.
        raise HTTPException(422, str(e))
    except Exception:
        logger.exception("현재 국면 스냅샷 생성 실패")
        raise HTTPException(500, "국면 수집/판정에 실패했습니다.")

    if sid is None:
        return {"recorded": False, "snapshot_id": None,
                "message": "DB 미가용 — 스냅샷이 저장되지 않았습니다."}

    from src.data.regime_snapshots import get_snapshot
    saved = get_snapshot(sid) or {}
    return {
        "recorded": True,
        "snapshot_id": sid,
        "as_of": saved.get("as_of"),
        "research_usage": saved.get("research_usage"),
        "data_status": saved.get("data_status"),
    }


@router.get("/compare")
def compare(a: str = Query(..., min_length=1), b: str = Query(..., min_length=1)):
    """두 스냅샷의 축·스트레스·확률 차이. 국면이 언제 어떻게 바뀌었는지 보기 위한 것."""
    try:
        from src.data.regime_snapshots import get_snapshot
        sa, sb = get_snapshot(a), get_snapshot(b)
        if sa is None or sb is None:
            missing = a if sa is None else b
            raise HTTPException(404, f"스냅샷을 찾을 수 없습니다: {missing}")

        keys = sorted({*sa["phase_probabilities"], *sb["phase_probabilities"]})
        return {
            "a": {"snapshot_id": a, "as_of": sa["as_of"]},
            "b": {"snapshot_id": b, "as_of": sb["as_of"]},
            "delta": {
                "growth_axis": sb["growth_axis"] - sa["growth_axis"],
                "inflation_axis": sb["inflation_axis"] - sa["inflation_axis"],
                "stress_score": sb["stress_score"] - sa["stress_score"],
                "confidence": sb["confidence"] - sa["confidence"],
                "phase_probabilities": {
                    k: sb["phase_probabilities"].get(k, 0.0) - sa["phase_probabilities"].get(k, 0.0)
                    for k in keys
                },
            },
            # 모델 버전이 다르면 축 값을 직접 비교하는 것이 의미가 없을 수 있다 — 정직하게 노출.
            "model_version_changed": sa["model_version"] != sb["model_version"],
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("regime snapshot 비교 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/{snapshot_id}")
def get_one(snapshot_id: str):
    try:
        from src.data.regime_snapshots import get_snapshot
        d = get_snapshot(snapshot_id)
        if d is None:
            raise HTTPException(404, "스냅샷을 찾을 수 없습니다.")
        return d
    except HTTPException:
        raise
    except Exception:
        logger.exception("regime snapshot 조회 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.delete("/{snapshot_id}")
def delete_one(snapshot_id: str):
    try:
        from src.data.regime_snapshots import delete_snapshot
        if not delete_snapshot(snapshot_id):
            raise HTTPException(404, "스냅샷을 찾을 수 없습니다.")
        return {"deleted": True}
    except HTTPException:
        raise
    except Exception:
        logger.exception("regime snapshot 삭제 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")
