"""보유 진단 표면 — ★이 포트폴리오는 지금 어떤 상태인가★ (AA5)
==============================================================================
설계: `docs/plans` AA · 로드맵 P2 "보유 진단 표면"

    POST /api/v1/diagnostics/holdings

## ★새 계산을 만들지 않는다★

세 진단은 이미 있고 규율도 지킨다 — `portfolio_factor_exposure`(커버리지·부호·
`resolvable_pct` 까지), `factor_concentration`, `_risk_contribution_report`
(어느 포트폴리오·어느 Σ 인지 밝힌다). 이 라우트가 하는 일은 **한 응답으로 모으고
각 블록이 못 낸 이유를 말하게 하는 것**뿐이다. 죽은 `portfolio_manager.py` 의
문구는 되살리지 않는다.

★헬퍼를 복사하지 않는다★ — `_load_clean_returns`·`_risk_contribution_report` 는
`allocation_routes` 에서 가져온다. `allocation_stress_routes` 가 **이미 같은 방식**
으로 앞의 둘을 쓰고 있어 관례가 서 있고, 옮기면 그 import 와 두 테스트의
monkeypatch 대상(`ar._load_clean_returns`)을 함께 흔들게 된다. 이 작업의 가치와
무관한 위험이다.

## ★P-1(인증) 없이 가능한 이유★

보유를 **요청 본문으로** 받는다 — "누구의" 보유인지 묻지 않으므로 계좌 소유권을
판단할 필요가 없다. 계좌에서 읽는 판이 오면 그때가 P-1 이 선행조건이 되는 지점이고,
그 경계를 응답 `note` 가 적는다.

## ★판정하지 않고 관측한다★

유동성은 `LiquidityStore` 가 내는 값을 옮길 뿐 "거래 가능/불가" 를 새로 매기지
않는다. 데이터가 합성이면 그 사실은 `evidence_rollup.price` 가 말한다.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("api.diagnostics")

router = APIRouter(prefix="/api/v1/diagnostics", tags=["diagnostics"])

_NOTE = (
    "이 진단은 **요청 본문으로 받은 보유**에 대한 것입니다 — 누구의 계좌인지 묻지 "
    "않았고, 서버가 계좌를 조회하지도 않았습니다. 각 블록은 못 낸 경우 사유를 "
    "함께 냅니다(미상은 0 이 아닙니다)."
)


class HoldingsDiagnosticsRequest(BaseModel):
    #: 종목코드 → 비중. 단위는 `weight_unit` 이 확정한다.
    holdings: dict[str, float] = Field(..., min_length=1)
    weight_unit: str | None = Field(None, max_length=16)   # percent|fraction
    lookback_days: int = Field(500, ge=60, le=2000)
    as_of: str | None = Field(None, max_length=10)
    benchmark: str | None = Field(None, max_length=20)


def _unavailable(reason: str) -> dict:
    return {"available": False, "reason": reason}


def _factor_blocks(holdings: dict[str, float], as_of: str | None) -> tuple[dict, dict]:
    """(노출, 집중도). ★베타를 못 낸 자산을 0 으로 채우지 않는다★"""
    from src.engine.factor_exposure import (
        asset_factor_betas,
        factor_concentration,
        portfolio_factor_exposure,
    )
    try:
        betas = asset_factor_betas(list(holdings), as_of=as_of)
        expo = portfolio_factor_exposure(holdings, betas)
    except Exception as e:  # noqa: BLE001 — 한 블록의 실패가 나머지를 죽이지 않는다
        logger.warning("팩터 노출 실패: %s: %s", type(e).__name__, e)
        return (_unavailable(f"팩터 노출을 계산하지 못했습니다: {type(e).__name__}"),
                _unavailable("노출이 없어 집중도를 낼 수 없습니다"))
    if not expo.get("available"):
        return expo, _unavailable(expo.get("reason") or "노출이 없습니다")
    return expo, factor_concentration(expo)


def _risk_block(holdings: dict[str, float], req: HoldingsDiagnosticsRequest):
    """(리스크 기여, coverage). ★Σ 를 못 만들면 기여는 0 이 아니라 미상이다★"""
    import numpy as np

    from src.api.allocation_routes import (
        _load_clean_returns,
        _risk_contribution_report,
    )
    codes = list(holdings)
    returns, _bench, _excluded, coverage = _load_clean_returns(
        codes, req.benchmark, req.lookback_days, as_of=req.as_of)
    if returns is None or len(returns.columns) < 2:
        n = 0 if returns is None else len(returns.columns)
        return (_unavailable(
            f"수익률을 얻은 자산이 {n}종이라 공분산을 만들 수 없습니다 — "
            "리스크 기여는 자산 2종 이상에서만 정의됩니다."), coverage)

    names = list(returns.columns)
    w = np.array([float(holdings.get(c, 0.0)) for c in names], dtype=float)
    total = float(np.abs(w).sum())
    if total <= 0:
        return _unavailable("수익률을 얻은 자산의 비중 합이 0 입니다"), coverage
    # ★표본 공분산이라고 밝힌다★ — `sigma_source` 가 그 사실을 응답에 싣는다.
    sigma = np.cov(returns.values, rowvar=False) * 252.0
    report = _risk_contribution_report(
        w / total, sigma, names,
        weights_source="request_holdings", sigma_source="sample")
    return ({"available": report.get("pct") is not None, **report}, coverage)


def _liquidity_block(holdings: dict[str, float]) -> dict:
    """★판정하지 않고 관측한다★ — 게이트가 내는 값을 옮긴다."""
    try:
        from src.engine.liquidity_gate import LiquidityStore
        store = LiquidityStore.get_default()
        by_ticker = {code: store.get_liquidity(code) for code in holdings}
    except Exception as e:  # noqa: BLE001
        logger.warning("유동성 조회 실패: %s: %s", type(e).__name__, e)
        return _unavailable(f"유동성을 조회하지 못했습니다: {type(e).__name__}")
    return {
        "available": True, "reason": None, "by_ticker": by_ticker,
        # ★없는 것을 만들지 않는다★ 이 저장소에 호가 실데이터 원천이 없다.
        "note": ("스프레드는 운영 경로에서 항상 `None` 입니다 — 호가 실데이터 "
                 "원천이 없기 때문이고, 없는 값으로 배제하지 않습니다."),
    }


@router.post("/holdings")
def holdings_diagnostics(req: HoldingsDiagnosticsRequest):
    """임의의 보유 → 팩터 노출 · 집중도 · 리스크 기여 · 유동성 + 증거 판정."""
    try:
        # ★단위를 먼저 확정한다★ 분수를 퍼센트로 읽으면 모든 블록이 조용히 틀린다.
        from src.engine.portfolio_weights import unit_reason
        reason = unit_reason(req.holdings, req.weight_unit)
        if reason:
            raise HTTPException(422, reason)

        holdings = {str(k): float(v) for k, v in req.holdings.items()}
        expo, conc = _factor_blocks(holdings, req.as_of)
        risk, coverage = _risk_block(holdings, req)

        from src.engine.decision_evidence import decision_evidence
        return {
            "holdings": holdings,
            "factor_exposure": expo,
            "factor_concentration": conc,
            "risk_contributions": risk,
            "liquidity": _liquidity_block(holdings),
            # ★이 진단이 무엇 위에 섰는가★ — AA3 의 축을 그대로 쓴다.
            #   `target`·`macro` 는 **넘기지 않는다** — 이 표면은 목표 비중도
            #   국면 경로도 다루지 않는다. 넘기면 "묻지 않은 것을 못 쟀다" 고
            #   적는 셈이고, 그건 없는 결함을 만드는 것이다.
            "evidence_rollup": decision_evidence(
                coverage=coverage, as_of_requested=req.as_of),
            "note": _NOTE,
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("holdings diagnostics 실패")
        raise HTTPException(500, "처리 중 오류가 발생했습니다.")
