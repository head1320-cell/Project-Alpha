"""CompanySnapshot API — 언더라이팅 판단을 ID 로 참조 (P2-1)

POST   /api/v1/company-snapshots        — 지금 기업 상태를 스냅샷으로 굳힌다
GET    /api/v1/company-snapshots        — 목록 (요약, 최신순, code 로 한정 가능)
GET    /api/v1/company-snapshots/{sid}  — 단건 전체 (섹션 포함)
DELETE /api/v1/company-snapshots/{sid}  — 오기재 정리 (수정 경로는 없다)

★저장소만 만들고 소비자를 안 만들면 감사가 지목한 그 결함을 새로 만드는 것★
이 저장소의 재발 패턴이다 — `attach_evidence` 는 M1-S 가 만들었지만 M1-V 전까지
호출자가 0 이었고, `src/engine/portfolio_rebalancer.py`(341줄)는 **오늘도** 호출자가
0 이다. 그래서 저장소·빌더·라우트를 같은 슬라이스에서 함께 낸다.

기존 `/api/v1/company/*` 세 엔드포인트는 건드리지 않는다 — 이 라우터는 가산이다.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger("api.company_snapshot")

router = APIRouter(prefix="/api/v1/company-snapshots", tags=["company-snapshots"])


class CreateCompanySnapshotRequest(BaseModel):
    code: str = Field(..., min_length=4, max_length=20)
    # 없으면 서버가 시세에서 해석하고 **그 출처를 스탬프한다**. 클라이언트가 출처를
    # 주장할 수 있으면, 쓰지 않은 가격 출처가 적힌 스냅샷이 만들어진다.
    price: float | None = Field(None, gt=0)
    as_of: str | None = Field(None, max_length=32)


@router.post("")
def create(req: CreateCompanySnapshotRequest):
    """지금 기업 상태를 굳힌다.

    ★정직 라벨을 응답에 그대로 실어 보낸다★ 재무의 실제 공표일과 정정 이력을 이
    저장소가 갖고 있지 않으므로 이렇게 만든 스냅샷은 **forward_only + partial(또는
    mock)** 로 내려간다. UI 가 그 사실을 숨기지 못하도록 서버가 먼저 말한다.
    """
    from src.engine.company_snapshot_builder import build_and_store
    try:
        sid = build_and_store(req.code, price=req.price, as_of=req.as_of)
    except Exception:
        logger.exception("company snapshot 생성 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")

    if sid is None:
        return {"recorded": False, "snapshot_id": None,
                "message": "DB 미가용 — 스냅샷이 저장되지 않았습니다."}

    from src.data.company_snapshots import get_snapshot
    snap = get_snapshot(sid) or {}
    return {
        "recorded": True, "snapshot_id": sid,
        "data_status": snap.get("data_status"),
        "research_usage": snap.get("research_usage"),
        "price_source": snap.get("price_source"),
        "unavailable_sections": (snap.get("provenance") or {}).get("unavailable_sections", []),
        "note": ("재무의 실제 공표일과 정정 이력이 없어 이 스냅샷은 과거 시뮬레이션에 "
                 "쓸 수 없습니다(forward_only). publication_dates.warning 을 보십시오."),
    }


@router.get("")
def list_all(code: str | None = Query(None, max_length=20),
             limit: int = Query(50, ge=1, le=200)):
    try:
        from src.data.company_snapshots import list_snapshots
        return {"snapshots": list_snapshots(code=code, limit=limit)}
    except Exception:
        logger.exception("company snapshot 목록 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")


@router.get("/{snapshot_id}")
def get_one(snapshot_id: str):
    try:
        from src.data.company_snapshots import get_snapshot
        snap = get_snapshot(snapshot_id)
    except Exception:
        logger.exception("company snapshot 조회 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")
    if snap is None:
        raise HTTPException(
            404, f"기업 스냅샷을 찾을 수 없습니다: {snapshot_id}. "
                 "삭제되었거나 다른 환경의 ID 일 수 있습니다.")
    return snap


@router.delete("/{snapshot_id}")
def remove(snapshot_id: str):
    """오기재 정리용. **수정 경로는 제공하지 않는다**(스냅샷 불변식)."""
    try:
        from src.data.company_snapshots import delete_snapshot
        deleted = delete_snapshot(snapshot_id)
    except Exception:
        logger.exception("company snapshot 삭제 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")
    if not deleted:
        raise HTTPException(404, f"기업 스냅샷을 찾을 수 없습니다: {snapshot_id}.")
    return {"deleted": True, "snapshot_id": snapshot_id}
