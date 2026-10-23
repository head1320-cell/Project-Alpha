"""포트폴리오 리포트 — ★진단·설명·판정을 한 장으로, 그리고 **숫자를 만들지 않는다**★ (AD5)
==============================================================================
설계: `docs/plans` AD · 로드맵 P3 "리포트 — 진단·설명·제안을 한 장으로"

    POST /api/v1/report/portfolio

## ★이 파일의 단 하나의 계약★

**리포트는 값을 옮기기만 한다.** 합계도 평균도 재계산도 없다. 리포트가 숫자를 하나라도
새로 만들면 그 숫자에는 ★출처가 없고★, 출처 없는 수치가 한 장에 정리돼 있으면 그것이
가장 설득력 있는 거짓말이 된다. `tests/test_report_routes.py` 가 **리포트의 모든 수치
리프가 출처 응답에 그대로 존재하는지** 전수로 확인한다.

그래서 이 모듈에는 산술 연산이 없다. 있는 것은 호출과 `dict` 조립뿐이다.

## ★한 블록의 실패가 전체를 삼키지 않는다★

블록 넷은 서로 독립이다. 하나가 막혀도 리포트는 나오고, 막힌 블록은
`available: false` + **사유**로 남는다. 조용히 빠지면 읽는 사람이 "그 진단은 문제가
없었나 보다" 라고 읽는다 — 그것이 CLAUDE.md §4 가 금지하는 침묵이다.

## ★새 사실을 만들지 않으므로 새 판단도 없다★

로드맵의 "제안" 은 **기존 리밸런스 판단**(AA2)이고, 이 리포트는 그것을 부를 뿐
자기 의견을 더하지 않는다. 리밸런스 블록은 **opt-in** 이다 — 유니버스·평가액이
필요한 무거운 호출이라, 받지 못하면 `available: false` 로 남긴다.
★"판단이 없다" 와 "판단을 요청하지 않았다" 를 가른다.★

## ★P-1(인증) 없이 가능한 이유★

AA5·AB4·AD4 와 같은 관용구 — 전부 **요청 본문**으로 돈다. 보호 레지스트리에 사유와
함께 면제로 등록돼 있다.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("api.report")

router = APIRouter(prefix="/api/v1/report", tags=["report"])

BLOCK_DIAGNOSTICS = "diagnostics"
BLOCK_EXPLANATION = "daily_explanation"
BLOCK_ACCOUNT = "account_policy"
BLOCK_REBALANCE = "rebalance"
REPORT_BLOCKS = (BLOCK_DIAGNOSTICS, BLOCK_EXPLANATION, BLOCK_ACCOUNT, BLOCK_REBALANCE)

_NOTE = (
    "이 리포트는 기존 표면들의 조립입니다 — 새로운 수치를 만들지 않았고, 모든 "
    "값은 각 블록의 출처 응답에 그대로 있습니다. 막힌 블록은 빠지지 않고 사유와 "
    "함께 남습니다."
)

#: ★"없음" 과 "묻지 않음" 을 가르는 꼬리말★ — 앞 절이 무엇을 못 받았는지 말하고
#: 이 문장이 그 의미를 확정한다. 앞 절과 동사가 겹치지 않도록 **서술어를 빼** 둔다.
_NOT_REQUESTED = "결과가 없다는 뜻이 아니라 묻지 않았다는 뜻입니다."


def _unavailable(reason: str) -> dict:
    return {"available": False, "reason": reason, "data": None}


def _available(data: Any) -> dict:
    return {"available": True, "reason": None, "data": data}


def _block(name: str, fn) -> dict:
    """블록 하나를 부르고 ★실패를 사유로 바꾼다★ — 예외가 리포트를 삼키지 않는다."""
    try:
        return _available(fn())
    except HTTPException as e:
        return _unavailable(f"{name} 블록이 거부됐습니다: {e.detail}")
    except Exception as e:
        logger.exception("리포트 블록 실패: %s", name)
        return _unavailable(f"{name} 블록에서 오류가 발생했습니다: {type(e).__name__}")


class PortfolioReportRequest(BaseModel):
    holdings: dict[str, float] = Field(..., min_length=1)
    weight_unit: str | None = Field(None, max_length=16)
    as_of: str | None = Field(None, max_length=10)
    lookback_days: int = Field(500, ge=60, le=2000)
    benchmark: str | None = Field(None, max_length=20)

    # ── 일일 설명 ──────────────────────────────────────────────────────────
    trades: list[dict] | None = None
    portfolio_value: float | None = Field(None, gt=0)

    # ── 계좌 판정(AD4) ────────────────────────────────────────────────────
    account_type: str | None = Field(None, max_length=32)
    risky_asset_classes: list[str] | None = None
    limits: list[dict] = Field(default_factory=list)

    # ── 리밸런스 판단(AA2) — ★opt-in★ ────────────────────────────────────
    #: `/api/v1/allocation/rebalance-decision` 의 요청 본문 그대로.
    rebalance: dict | None = None


@router.post("/portfolio")
def portfolio_report(req: PortfolioReportRequest):
    """네 블록을 부르고 묶는다. ★산술 연산 없음★"""
    blocks: dict[str, dict] = {}

    # ① 보유 진단 (AA5)
    def _diagnostics():
        from src.api.diagnostics_routes import (
            HoldingsDiagnosticsRequest,
            holdings_diagnostics,
        )
        return holdings_diagnostics(HoldingsDiagnosticsRequest(
            holdings=req.holdings, weight_unit=req.weight_unit,
            lookback_days=req.lookback_days, as_of=req.as_of,
            benchmark=req.benchmark))

    blocks[BLOCK_DIAGNOSTICS] = _block(BLOCK_DIAGNOSTICS, _diagnostics)

    # ② 하루 설명 (AB4)
    def _explanation():
        from src.api.explain_routes import DailyExplainRequest, explain_daily
        return explain_daily(DailyExplainRequest(
            holdings=req.holdings, weight_unit=req.weight_unit, as_of=req.as_of,
            trades=req.trades, portfolio_value=req.portfolio_value))

    blocks[BLOCK_EXPLANATION] = _block(BLOCK_EXPLANATION, _explanation)

    # ③ 계좌 제약 판정 (AD4)
    if req.account_type is None:
        blocks[BLOCK_ACCOUNT] = _unavailable(
            f"계좌 유형을 받지 못했습니다 — {_NOT_REQUESTED}")
    else:
        def _account():
            from src.api.account_policy_routes import (
                AccountDiagnoseRequest,
                diagnose_account,
            )
            return diagnose_account(AccountDiagnoseRequest(
                account_type=req.account_type, holdings=req.holdings,
                risky_asset_classes=req.risky_asset_classes, limits=req.limits))

        blocks[BLOCK_ACCOUNT] = _block(BLOCK_ACCOUNT, _account)

    # ④ 리밸런스 판단 (AA2) — opt-in
    if req.rebalance is None:
        blocks[BLOCK_REBALANCE] = _unavailable(
            f"리밸런스 판단을 요청하지 않았습니다 — {_NOT_REQUESTED}")
    else:
        def _rebalance():
            from src.api.allocation_routes import (
                RebalanceDecisionRequest,
                rebalance_decision_route,
            )
            return rebalance_decision_route(
                RebalanceDecisionRequest(**req.rebalance))

        blocks[BLOCK_REBALANCE] = _block(BLOCK_REBALANCE, _rebalance)

    unavailable = sorted(k for k, v in blocks.items() if not v["available"])
    return {
        "blocks": blocks,
        # ★무엇이 빠졌는지 한눈에★ — 읽는 사람이 블록을 하나씩 세지 않도록.
        "unavailable_blocks": unavailable,
        "note": _NOTE,
    }
