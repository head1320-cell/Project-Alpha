"""평가 카드 조립 — ★부르고 묶을 뿐, 새 수치를 만들지 않는다★ (AE4)
==============================================================================
설계: `docs/plans` AE · 타입: `src/domain/strategy_scorecard.py`
재료: `alpha_registry`(생애주기) · `strategy_health`(건강도) · `run_evidence`(증거)

## ★조립기다★

AD5 의 리포트와 같은 규율이다 — 세 재료를 **부르고 묶는다**. 축 점수를 새로
계산하거나 세 축을 가중평균하지 않는다. 그렇게 하는 순간 그 숫자에는 출처가 없다.

## 증거 축을 ★지어내지 않는다★

연결된 검증 리포트(`last_run_id`)가 없으면 증거 축은 `unknown` 이고 **사유**가
"검증 리포트가 연결되지 않았습니다" 다. 리포트가 있어도 그 안에 시점 정합 메타가
없으면 `pit_evidence` 의 필수 축이 `unknown` 으로 남는다 — ★`unknown` 은 통과가
아니다★(`run_evidence` 의 규율 그대로).

## 유통은 ★언제나 관문을 지난다★

카드마다 `distribution_gate()` 를 부른다. 인가 기록을 넘기지 않으므로 답은 항상
`blocked` 이고, 그것이 이 저장소의 사실이다(AE1).
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from src.domain.distribution_gate import distribution_gate
from src.domain.strategy_scorecard import Scorecard, unmeasured_from_signals

logger = logging.getLogger("engine.scorecard")

_NO_RUN_REASON = "검증 리포트가 연결되지 않았습니다 — 먼저 알파를 검증하세요."
_NO_ALPHA_REASON = "알파를 찾을 수 없습니다."


def _evidence_for(run: dict | None) -> dict[str, Any]:
    """검증 리포트 → 시점 정합 판정. ★메타가 없으면 `unknown` 이고 통과가 아니다★"""
    from src.engine.run_evidence import AXIS_UNKNOWN, pit_evidence

    if not run:
        return {"status": AXIS_UNKNOWN, "reason": _NO_RUN_REASON, "axes": {}}

    outputs = run.get("outputs") or {}
    meta = outputs if isinstance(outputs, dict) else {}
    evidence = pit_evidence(
        price_basis=meta.get("price_basis"),
        universe=meta.get("universe"),
        macro_lookahead=meta.get("macro_lookahead"),
        fundamentals_pit=meta.get("fundamentals_pit"),
    )
    return {**evidence, "reason": evidence.get("summary")}


def build_scorecard(alpha_id: str, *, run_getter=None,
                    health_getter=None) -> dict[str, Any]:
    """알파 하나의 카드. ★못 내면 사유를 낸다★ — 조용한 `{}` 금지.

    `run_getter`/`health_getter` 는 테스트 주입 seam 이다(`strategy_health` 가 쓰는
    관용구 그대로).
    """
    from src.data.alpha_registry import get_alpha, usable_for_portfolio

    alpha = get_alpha(alpha_id)
    if alpha is None:
        return {"strategy_id": alpha_id, "available": False,
                "reason": _NO_ALPHA_REASON, "card": None}

    if run_getter is None:
        from src.data.research_runs import get_run as run_getter  # noqa: N806

    # ── 축 ① 생애주기 ─────────────────────────────────────────────────────
    usable, usable_reason = usable_for_portfolio(alpha)
    lifecycle = {
        "status": alpha.get("status"),
        "reason": usable_reason,
        "usable_for_portfolio": usable,
    }

    # ── 축 ② 건강도 ───────────────────────────────────────────────────────
    if health_getter is None:
        from src.engine.strategy_health import strategy_health as health_getter  # noqa: N806
    health_out = health_getter(alphas=[alpha], run_getter=run_getter)
    item = (health_out.get("items") or [{}])[0]
    health = {"status": item.get("status"), "signals": item.get("signals") or []}

    # ── 축 ③ 증거 ─────────────────────────────────────────────────────────
    run = run_getter(alpha.get("last_run_id")) if alpha.get("last_run_id") else None
    evidence = _evidence_for(run)

    card = Scorecard(
        strategy_id=alpha_id,
        lifecycle=lifecycle,
        health=health,
        evidence=evidence,
        # ★못 잰 것이 사라지지 않는다★
        unmeasured=unmeasured_from_signals(health["signals"]),
        # ★유통은 축이 아니라 관문이다★ — 인가 기록을 넘기지 않으므로 항상 blocked.
        distribution=distribution_gate(),
        as_of=dt.date.today().isoformat(),
    )
    return {"strategy_id": alpha_id, "available": True, "reason": None,
            "card": card.to_dict()}


def build_scorecards(alpha_ids: list[str], **kw) -> list[dict[str, Any]]:
    """여러 장. ★한 장이 실패해도 나머지는 나온다★"""
    out = []
    for alpha_id in alpha_ids:
        try:
            out.append(build_scorecard(alpha_id, **kw))
        except Exception as e:
            logger.exception("평가 카드 조립 실패: %s", alpha_id)
            out.append({"strategy_id": alpha_id, "available": False,
                        "reason": f"카드 조립 중 오류: {type(e).__name__}", "card": None})
    return out
