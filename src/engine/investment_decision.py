"""결정 합성 — ★원시함수 8개가 전부 호출부 1개였다★ (S2)
==============================================================================
설계: [`투자 결정 계층`](../../docs/superpowers/specs/2026-08-28-investment-decision-layer-design.md)
선행: S1 결정 스토어(`data/investment_decisions.py`)

## 왜 이 모듈이 생겼나

Phase 0 감사의 **M3**: 결정 원시함수가 전부 **호출부 1개 = API 라우트**였다.
사람이 라우트를 올바른 순서로 눌러야만 결정이 성립하고, 도메인 계층에서 합성하는
코드가 **없었다**. 그래서 판단이 응답과 함께 사라졌다.

## ★이 모듈은 계산하지 않는다★

세 가지를 **절대** 하지 않는다 — 하는 순간 두 번째 진실 공급원이 생긴다:

    포트폴리오 구성   `allocation_studio` 의 일이다. 구성은 결정이 아니다.
    거래비용         `rebalance_policy._cost_block` 이 이미 실행계획 엔진을
                     재사용한다("비용 산수를 두 곳에 두지 않는다").
    효용·밴드 산수    `rebalance_policy` 안에 있다.

하는 일은 넷이다 — **판단 호출 · 상류→스토어 매핑 · leg 유도 · 영속**.
`tests/test_investment_decision_compose.py` 가 금지 식별자를 토큰 단위로 검사한다.

## ★매핑이 이 모듈에서 가장 위험한 부분이다★

설계 초안은 `benefit_bps`·`cost_bps`·`hysteresis_bps` 라고 적었는데 상류는
`benefit.gain_pct`·`cost.cost_pct`·`hysteresis_mult`(**배수**)를 준다. 단위가
**percent** 다. 초안대로 만들었으면 **100배 오류**가 조용히 들어갔다.
★상류 이름을 그대로 쓰고, 어떤 변환도 하지 않는다.★

회전율도 마찬가지다 — `cost.turnover_pct` 를 그대로 쓴다. 따로 계산하면 비용
블록과 갈라지고, 갈라져도 타입 에러가 나지 않는다.

## ★제약 구속은 포트폴리오 수준이다★

`constrained_solve` 의 구속 목록은 `"종목 상한 40%"` 같은 **포트폴리오 수준**
문자열이다. 어느 **종목**이 그 구속을 유발했는지는 재유도해야 알 수 있고 그것은
지어내기다. 그래서 호출자가 준 목록은 부모의 `evidence` 에 그대로 담고,
leg 의 구속 칸은 **빈 채로 둔다**(Phase 0 귀속 표: *동시 구속은 분해 불가*).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

#: leg 별 기여도는 지금 대부분 식별 불가다. ★칸을 비워 두는 것이 없는 분해를
#: 지어내는 것보다 낫다★ — `null` 옆에 항상 사유를 둔다(Phase 0 §7).
_CONTRIBUTION_UNKNOWN = {
    "macro": None, "company": None, "risk_model": None, "constraint": None,
    "reason": ("성분별 기여는 아직 식별할 수 없습니다 — 국면·Ω·공분산이 동시에 "
               "움직이고, 제약 구속은 포트폴리오 수준입니다."),
}


def _legs_from(current: dict[str, float], target: dict[str, float],
               band: dict[str, Any] | None) -> list[dict[str, Any]]:
    """자산별 leg. ★밴드를 모르면 밴드 칸은 `None` — 지어내지 않는다★

    밴드가 없어도 **무엇을 얼마나 바꾸려 했는지**는 남아야 한다. 그것이 없으면
    `undetermined` 결정에서 사후에 물을 수 있는 것이 사라진다.
    """
    by_asset = (band or {}).get("by_asset") or {}
    outside = set((band or {}).get("outside") or [])
    out: list[dict[str, Any]] = []
    for ticker in sorted(set(current) | set(target)):
        cur = float(current.get(ticker, 0.0))
        tgt = float(target.get(ticker, 0.0))
        b = by_asset.get(ticker) or {}
        out.append({
            "ticker": ticker,
            "current_w": cur, "target_w": tgt, "delta_w": round(tgt - cur, 6),
            "half_width_pct": b.get("half_width_pct"),
            "low_pct": b.get("low_pct"), "high_pct": b.get("high_pct"),
            "outside_band": ticker in outside,
            # ★포트폴리오 수준 구속을 종목에 배분하지 않는다★
            "constraint_binding": [],
            "view_refs": [],
            "contribution": dict(_CONTRIBUTION_UNKNOWN),
        })
    return out


def decide(current_weights: dict[str, float], target_weights: dict[str, float], *,
           portfolio_value: float,
           names: list[str] | None = None, mu=None, sigma=None,
           risk_aversion: float | None = None,
           horizon_days: int | None = None,
           hysteresis_mult: float | None = None,
           uncertainty: float | None = None,
           confidence: float | None = None,
           triggers: dict | None = None,
           price_of=None, adv_of=None,
           as_of: str | None = None, case_id: str | None = None,
           scope: str = "portfolio",
           belief: dict[str, Any] | None = None,
           evidence: dict[str, Any] | None = None,
           note: str | None = None,
           persist: bool = True, engine=None) -> dict[str, Any]:
    """증거 → 판단 → 기록. ★계산은 전부 기존 것을 부른다.★

    Args:
        mu, sigma: 없으면 편익을 계산할 수 없어 `undetermined` 가 된다 —
            ★그것이 실패가 아니라 답이다.★ 트리거가 울려도 편익을 모르면 거래를
            권하지 않는다.
        triggers: **왜 검토했는가**. 이 모듈이 만들지 않는다(상류가 안다).
        evidence: 증거 참조(`mes_id`·`run_id`·`tpv_id`·`thesis_ids`·
            `constraints_binding`). 그대로 담는다.
        persist: 거짓이면 저장하지 않고 `dec_id=None`·`persisted=False` 를 낸다 —
            ★저장한 척하지 않는다.★

    Returns:
        상류 판단 결과에 `legs`·`dec_id`·`persisted`·`persist_reason` 을 더한 것.
        ★상류 키는 하나도 바꾸지 않는다★ — 호출자가 이미 읽던 모양이 유지된다.
    """
    from src.engine import rebalance_policy as rp

    kwargs: dict[str, Any] = {
        "portfolio_value": portfolio_value, "names": names,
        "mu": mu, "sigma": sigma, "uncertainty": uncertainty,
        "confidence": confidence, "triggers": triggers,
        "price_of": price_of, "adv_of": adv_of,
    }
    # ★기본값을 여기서 다시 정하지 않는다★ 상류가 이미 갖고 있다. 두 곳에 두면
    # 갈라지고, 갈라져도 타입 에러가 나지 않는다.
    if risk_aversion is not None:
        kwargs["risk_aversion"] = risk_aversion
    if horizon_days is not None:
        kwargs["horizon_days"] = horizon_days
    if hysteresis_mult is not None:
        kwargs["hysteresis_mult"] = hysteresis_mult

    result = dict(rp.rebalance_decision(current_weights, target_weights, **kwargs))

    legs = _legs_from(current_weights, target_weights, result.get("band"))
    result["legs"] = legs
    result["dec_id"] = None
    result["persisted"] = False
    result["persist_reason"] = None

    if not persist:
        result["persist_reason"] = "호출자가 저장을 요청하지 않았습니다(persist=False)."
        return result

    cost = result.get("cost") or {}
    benefit = result.get("benefit") or {}
    record = {
        "as_of": as_of, "scope": scope,
        "decision_status": result.get("decision"),
        "reason": result.get("reason"),
        # ★상류 이름·단위를 그대로★ percent 이지 bps 가 아니다.
        "gain_pct": benefit.get("gain_pct"),
        "cost_pct": cost.get("cost_pct"),
        "turnover_pct": cost.get("turnover_pct"),
        "hysteresis_mult": result.get("hysteresis_mult"),
        "threshold_pct": result.get("threshold_pct"),
        "net_pct": result.get("net_pct"),
        "max_gap_pct": result.get("max_gap_pct"),
        "portfolio_value": portfolio_value,
        "belief": belief, "evidence": evidence,
        "gradual": result.get("gradual"), "triggers": result.get("triggers"),
    }

    # ★저장 실패가 계산을 되돌리지 않는다★ 판단은 이미 났고, 그 사실은 남아야 한다.
    try:
        from src.data.investment_decisions import save_decision
        dec_id = save_decision(record, legs, case_id=case_id, note=note,
                               engine=engine)
    except Exception as e:  # noqa: BLE001
        logger.warning("결정 저장 중 예외: %s: %s", type(e).__name__, e)
        result["persist_reason"] = f"{type(e).__name__}: {e}"
        return result

    if dec_id is None:
        result["persist_reason"] = (
            "결정을 저장하지 못했습니다 — 저장소가 없거나 상태·사유가 계약을 "
            "만족하지 않습니다(로그 참조).")
        return result
    result["dec_id"] = dec_id
    result["persisted"] = True
    return result
