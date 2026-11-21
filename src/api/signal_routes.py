"""신호 카탈로그 API — ★다섯 갈래를 한 번에 묻는 자리★ (P1-c)
==============================================================================
GET /api/v1/signals              — 신호 정의 통합 뷰 (+ 못 읽은 출처)
GET /api/v1/signals/kinds        — 종류 목록

단일 출처는 `src/domain/signal_definition.py` 이고, 그 모듈은 값을 보관하지 않고
조회 시 다섯 카탈로그를 합친다. ★여기서 값을 캐시하지 않는다★ — 캐시하면 원본과
갈라지고, 그것이 이 뷰가 막으려던 바로 그 문제다.

★부분 실패를 감추지 않는다★ — 출처 하나가 죽으면 `unavailable_sources` 에 사유가
실려 나간다. 빈 목록을 200 으로 돌려주는 것이 침묵 폴백이다(CLAUDE.md §4).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query

from src.domain.signal_definition import SIGNAL_KINDS, collect_signals
from src.domain.signal_evidence import grade_catalog

logger = logging.getLogger("api.signals")

router = APIRouter(prefix="/api/v1/signals", tags=["signals"])


@router.get("")
def list_signals(kind: str | None = Query(None, description="종류로 필터")) -> dict:
    cat = collect_signals()
    items = [s for s in cat.signals if kind is None or s.kind == kind]
    by_kind: dict[str, int] = {}
    for s in cat.signals:
        by_kind[s.kind] = by_kind.get(s.kind, 0) + 1
    return {
        "signals": [
            {
                "signal_id": s.signal_id, "kind": s.kind, "label": s.label,
                "category": s.category, "owner_module": s.owner_module,
                "release_lag": s.release_lag, "revision_policy": s.revision_policy,
                "evidence_grade": s.evidence_grade,
                # ★사유 없는 미상은 금지★ — 등급이 없으면 왜 없는지 말한다.
                "evidence_grade_reason": s.evidence_grade_reason,
                "availability": s.availability,
                "unavailable_reason": s.unavailable_reason,
            } for s in items
        ],
        # ★실측값이다★ — 문서에 적는 개수가 아니라 조회 시 센 값이라 낡지 않는다.
        "counts_by_kind": by_kind,
        # ★못 읽은 출처를 그대로 내보낸다★ — 조용히 빠지면 소비자가 속는다.
        "unavailable_sources": cat.unavailable_sources,
        # ★출처를 말할 수 없는 신호의 목록★(AV) — 이것이 산출물이다.
        #   ★`kind` 필터와 무관하게 **전체**를 센다★ — 걸러서 세면 빈틈이
        #   줄어 보이고, 그 숫자는 아무것도 뜻하지 않는다.
        "evidence": grade_catalog(cat),
    }


@router.get("/kinds")
def list_kinds() -> dict:
    return {"kinds": list(SIGNAL_KINDS)}
