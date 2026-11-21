"""글라이드패스 표면 — ★목표까지 얼마나 남았고, 적립만으로 좁히려면 얼마나 걸리나★ (AO4)
==============================================================================
설계: `docs/plans` AO · 로드맵 P2 "라이프사이클 글라이드패스"
응답 타입: `frontend/src/entities/glidepath/types.ts` (AO5 — ★타입만, 화면 없음★)

    POST /api/v1/accounts/glidepath

## ★`/diagnose` 에 합치지 않는다★

AD4 의 `/diagnose` 는 *"이 계좌가 한도를 만족하는가"* 를 답하고, 이 표면은
*"목표까지 얼마나 남았는가"* 를 답한다. **두 질문을 섞지 않는다**(CLAUDE.md §2).
다만 한도 판정은 AD1 의 `judge_account` 를 **그대로 부른다** — 같은 질문에 두 벌의
판정을 만들지 않는다.

## ★도달할 수 없던 가드가 여기서 처음 살아난다★

`/diagnose` 는 관측을 **하나만**(위험자산 비중) 넘긴다. 그래서
`annual_contribution_krw`·`total_contribution_krw` 는 한도를 선언해도 영원히
`undetermined` 였다 — AM 의 `"dev"`, AL 의 상수 `0` 과 같은 모양이다. 이 표면은
요청이 주는 **실적**(`contributed_ytd_krw`·`total_contributed_krw`)을 관측으로
넘겨 그 둘을 처음으로 `pass`/`breach` 가 되게 한다.

★실적 ⟂ 계획★ — 한도 판정에 들어가는 것은 **이미 낸 돈**이고, 도달 개월 수에
들어가는 것은 **앞으로 낼 계획**이다. 계획을 한도 관측으로 넘기면 *"아직 내지 않은
돈"* 으로 한도를 판정하게 되고 그 판정은 거짓이다. 그래서 두 값은 요청에서도
**다른 필드**이고, 이 모듈은 둘을 절대 같은 자리에 넣지 않는다.

## ★관측만 한다 — 비중을 바꾸지 않는다★

AD4 와 같은 선택이다(사용자 결정, 2026-09-19). `constrained_opt`·
`constrained_solve`·`rebalance_decision` 은 **0줄** 바뀌지 않는다 — CLAUDE.md §3 의
별도 승인 사항이다. ★최적화기는 이 목표를 모른 채 해를 낸다★ 는 사실을
`optimizer_note` 가 적는다.

## ★P-1(인증) 없이 가능한 이유★

AA5·AB4·AD4 와 같은 관용구다 — 보유·계좌유형·한도·곡선·적립 계획을 **요청 본문으로**
받고 저장된 계좌를 읽지 않으며 아무것도 저장하지 않는다. 보호 레지스트리에 **사유와
함께** 면제로 등록돼 있다(`src/api/protected_routes.py`).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.api.account_policy_routes import DeclaredLimit
from src.domain.account_policy import (
    ACCOUNT_TYPES,
    LIMIT_ANNUAL_CONTRIB_KRW,
    LIMIT_KINDS,
    LIMIT_RISKY_ASSET_MAX_PCT,
    LIMIT_TOTAL_CONTRIB_KRW,
    UNDECLARED_REASON,
    AccountLimit,
    judge_account,
)
from src.domain.contribution import BUCKETS, months_to_close
from src.domain.glide_path import GlidePoint, glide_label, years_remaining
from src.engine.glide_evidence import glide_evidence
from src.engine.risky_share import risky_share_interval

logger = logging.getLogger("api.glidepath")

router = APIRouter(prefix="/api/v1/accounts", tags=["accounts"])

_SCOPE_NOTE = (
    "이 판정은 요청 본문으로 받은 보유·기간·곡선·적립 계획에 대한 것입니다 — 서버가 "
    "계좌를 조회하지 않았고 아무것도 저장하지 않았습니다. 글라이드패스 곡선과 "
    "위험자산 분류는 ★요청이 선언한 것★이며, 이 저장소는 그것이 옳은지 판정하지 "
    "않습니다."
)

_OPTIMIZER_NOTE = (
    "이 표면은 사후 관측입니다 — 최적화기는 이 목표 비중을 모른 채 해를 냅니다. "
    "격차를 배분에 반영하는 것은 별도 승인 사항이며, 이 요청은 어떤 주문도 내지 "
    "않고 어떤 비중도 바꾸지 않습니다."
)


class CurvePoint(BaseModel):
    """곡선 위의 한 점. ★이름 있는 프리셋을 서버가 들고 있지 않다★"""

    years_to_target: float
    risky_target_pct: float


class ContributionPlan(BaseModel):
    """앞으로의 적립 **계획**. ★실적이 아니다★ — 실적은 아래 두 필드다."""

    monthly_krw: float | None = None
    #: `risky` | `safe`. ★미선언이면 도달 개월 수를 내지 않는다★
    bucket: str | None = Field(None, max_length=16)
    portfolio_value_krw: float | None = None


class GlidePathRequest(BaseModel):
    account_type: str = Field(..., max_length=32)
    #: 종목코드 → 비중(양수). 단위 무관 — 내부에서 정규화한다.
    holdings: dict[str, float] = Field(default_factory=dict)
    #: ★`None` 은 "선언하지 않았다", `[]` 는 "위험자산이 없다고 선언했다"★
    risky_asset_classes: list[str] | None = None
    horizon_days: int | None = None
    target_retirement_year: int | None = None
    #: ★2점 미만이면 목표를 내지 않는다★ — 곡선은 투자 판단이다.
    curve: list[CurvePoint] | None = None
    contribution: ContributionPlan | None = None
    limits: list[DeclaredLimit] = Field(default_factory=list)
    #: ★실적★ — 올해 이미 납입한 금액(원). 연간 한도 판정의 **관측값**이다.
    contributed_ytd_krw: float | None = None
    #: ★실적★ — 누적 납입액(원). 총 납입 한도 판정의 관측값이다.
    total_contributed_krw: float | None = None


def _limits(req: GlidePathRequest) -> tuple[AccountLimit, ...]:
    return tuple(
        AccountLimit(kind=d.kind, value=d.value, source=d.source, as_of=d.as_of,
                     reason=None if d.value is not None else UNDECLARED_REASON)
        for d in req.limits
    )


def _observations(req: GlidePathRequest, risky: dict) -> dict[str, object]:
    """한도 판정에 넘길 **관측**. ★계획은 여기 절대 들어가지 않는다★

    들어가는 것은 셋뿐이다 — 위험자산 비중(구간)과 **이미 낸 돈** 둘. 월 적립
    계획을 여기 넣으면 아직 내지 않은 돈으로 한도를 판정하게 된다.
    """
    observations: dict[str, object] = {}
    if risky["available"] and risky["interval"] is not None:
        observations[LIMIT_RISKY_ASSET_MAX_PCT] = (
            risky["interval"]["lo"], risky["interval"]["hi"])
    if req.contributed_ytd_krw is not None:
        observations[LIMIT_ANNUAL_CONTRIB_KRW] = float(req.contributed_ytd_krw)
    if req.total_contributed_krw is not None:
        observations[LIMIT_TOTAL_CONTRIB_KRW] = float(req.total_contributed_krw)
    return observations


@router.post("/glidepath")
def glidepath_account(req: GlidePathRequest):
    if req.account_type not in ACCOUNT_TYPES:
        raise HTTPException(
            400, f"알 수 없는 계좌 유형 {req.account_type!r} — 허용: {list(ACCOUNT_TYPES)}")

    plan = req.contribution or ContributionPlan()
    if plan.bucket is not None and plan.bucket not in BUCKETS:
        raise HTTPException(
            400, f"알 수 없는 적립 대상 {plan.bucket!r} — 허용: {list(BUCKETS)}")

    unknown_kinds = sorted({d.kind for d in req.limits} - set(LIMIT_KINDS))
    if unknown_kinds:
        raise HTTPException(
            400, f"알 수 없는 한도 종류 {unknown_kinds} — 허용: {list(LIMIT_KINDS)}")

    try:
        # ① 기간 — ★관측★. 둘 다 없거나 서로 어긋나면 값이 없다.
        years, years_reason = years_remaining(
            horizon_days=req.horizon_days,
            target_retirement_year=req.target_retirement_year)

        # ② 곡선 — ★선언★. 서버는 곡선을 갖지 않는다.
        curve = ([GlidePoint(years_to_target=p.years_to_target,
                             risky_target_pct=p.risky_target_pct)
                  for p in req.curve] if req.curve else None)

        # ③ 비중 — ★관측 구간★(AD3). 분류가 선언되지 않으면 재지 않는다.
        risky = risky_share_interval(req.holdings, req.risky_asset_classes)
        interval = risky.get("interval") or {}
        lo, hi = interval.get("lo"), interval.get("hi")

        glide = glide_label(years=years, years_reason=years_reason, curve=curve,
                            observed_lo=lo, observed_hi=hi)

        # ④ 적립 — ★계획★. 대상이 없으면 개월 수를 내지 않는다.
        contribution = months_to_close(
            target_pct=glide["target_pct"], observed_lo=lo, observed_hi=hi,
            monthly_krw=plan.monthly_krw,
            portfolio_value_krw=plan.portfolio_value_krw, bucket=plan.bucket)

        judged = judge_account(req.account_type, _limits(req),
                               _observations(req, risky))

        return {
            "account_type": req.account_type,
            "glide": glide,
            "contribution": contribution,
            "risky_share": risky,
            "evidence": glide_evidence(years=years, years_reason=years_reason,
                                       curve=curve, risky=risky,
                                       contribution=contribution),
            "limits": judged,
            "scope_note": _SCOPE_NOTE,
            "optimizer_note": _OPTIMIZER_NOTE,
        }
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    except Exception:
        logger.exception("요청 처리 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")
