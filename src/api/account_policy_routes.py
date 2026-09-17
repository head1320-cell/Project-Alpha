"""계좌 제약 진단 표면 — ★이 계좌는 무엇을 만족하는가, 그리고 **무엇을 모르는가**★ (AD4)
==============================================================================
설계: `docs/plans` AD · 로드맵 P3 "멀티계좌 허브"

    POST /api/v1/accounts/diagnose

## ★판정하되 해를 바꾸지 않는다★

로드맵은 *"계좌별 제약을 `Constraints` 로 옮긴다"* 고 적었지만 이번에는 **관측만**
한다(사용자 결정, 2026-09-13). `constrained_opt.py` 와 배분 결정 경로는 한 줄도
바뀌지 않는다 — CLAUDE.md §3 의 별도 승인 사항이다. 즉 이 표면은 **사후 관측**이고
★최적화기는 여전히 계좌를 모른다★. 그 사실을 `note` 가 적는다.

## ★법규 수치를 서버가 들고 있지 않다★

한도는 요청이 **출처·기준일과 함께** 선언한다. 선언하지 않으면 `undetermined` 이고,
그것은 통과가 아니다. 이 저장소는 IRP 70%·ISA 납입한도 같은 수치를 검증할 수 없다.

## ★P-1(인증) 없이 가능한 이유★

AA5·AB4 와 같은 관용구다 — 보유·계좌유형·한도를 **요청 본문으로** 받고 저장된
계좌를 읽지 않는다. 보호 레지스트리에 **사유와 함께 면제**로 등록돼 있다
(`src/api/protected_routes.py`). 계좌를 DB 에서 읽는 판이 오면 그때 잠근다.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.domain.account_policy import (
    ACCOUNT_TYPES,
    LIMIT_KINDS,
    LIMIT_RISKY_ASSET_MAX_PCT,
    UNDECLARED_REASON,
    AccountLimit,
    judge_account,
)
from src.engine.risky_share import risky_share_interval

logger = logging.getLogger("api.account_policy")

router = APIRouter(prefix="/api/v1/accounts", tags=["accounts"])

_NOTE = (
    "이 판정은 요청 본문으로 받은 보유와 한도에 대한 것입니다 — 서버가 계좌를 "
    "조회하지 않았고, 법규 수치를 들고 있지도 않습니다. 선언되지 않은 한도는 "
    "undetermined 이며 통과가 아닙니다."
)

_OPTIMIZER_NOTE = (
    "이 판정은 사후 관측입니다 — 최적화기는 계좌 제약을 모른 채 해를 냅니다. "
    "제약을 배분에 반영하는 것은 별도 승인 사항입니다."
)


class DeclaredLimit(BaseModel):
    """운영자가 선언하는 한도 하나. ★값만 받지 않는다★ — 출처와 기준일을 함께."""

    kind: str = Field(..., max_length=64)
    value: float | None = None
    source: str | None = Field(None, max_length=500)
    as_of: str | None = Field(None, max_length=10)


class AccountDiagnoseRequest(BaseModel):
    account_type: str = Field(..., max_length=32)
    #: 종목코드 → 비중(양수). 단위 무관 — 내부에서 정규화한다.
    holdings: dict[str, float] = Field(default_factory=dict)
    #: ★`None` 은 "선언하지 않았다", `[]` 는 "위험자산이 없다고 선언했다"★
    risky_asset_classes: list[str] | None = None
    limits: list[DeclaredLimit] = Field(default_factory=list)


@router.post("/diagnose")
def diagnose_account(req: AccountDiagnoseRequest):
    if req.account_type not in ACCOUNT_TYPES:
        raise HTTPException(
            400, f"알 수 없는 계좌 유형 {req.account_type!r} — 허용: {list(ACCOUNT_TYPES)}")

    unknown_kinds = sorted({d.kind for d in req.limits} - set(LIMIT_KINDS))
    if unknown_kinds:
        raise HTTPException(
            400, f"알 수 없는 한도 종류 {unknown_kinds} — 허용: {list(LIMIT_KINDS)}")

    try:
        limits = tuple(
            AccountLimit(
                kind=d.kind, value=d.value, source=d.source, as_of=d.as_of,
                reason=None if d.value is not None else UNDECLARED_REASON,
            )
            for d in req.limits
        )

        # ★관측★ — 위험자산 비중은 구간이고, 분류가 선언되지 않았으면 재지 않는다.
        risky = risky_share_interval(req.holdings, req.risky_asset_classes)
        observations: dict[str, object] = {}
        if risky["available"] and risky["interval"] is not None:
            observations[LIMIT_RISKY_ASSET_MAX_PCT] = (
                risky["interval"]["lo"], risky["interval"]["hi"])

        judged = judge_account(req.account_type, limits, observations)

        return {
            **judged,
            "risky_share": risky,
            "note": judged.get("note"),
            "scope_note": _NOTE,
            "optimizer_note": _OPTIMIZER_NOTE,
        }
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")
