"""룰셋 과거 시뮬레이션 — 시점별 합성 신호 walk (스펙 §7 "historical simulation").

`timing_factor_history` 와 무엇이 다른가
──────────────────────────────────────────────────────────────────────────────
저쪽은 **팩터 하나**의 값·상태를 그린다(창의 미리보기). 이쪽은 **룰셋 하나**를 매 시점
재평가해 조합까지 마친 합성 상태·노출을 낸다 — 외부 파이프라인이 `set_id` 로 붙잡고 돌릴 수
있는 표면이다. 조합 로직은 여기서 다시 만들지 않고 `rule_set_states()` + `combine()` 을
그대로 쓴다(3자 비교·단독 평가와 같은 파생).

★절단이 **두 겹**이다★
`factor_history` 는 `requires_as_of` 팩터를 아예 건너뛰므로 `etf_prices.as_of(m)` 하나면
충분했다. 룰셋은 가격 팩터와 매크로 팩터를 **섞는다.** 그래서 각 시점마다

  · `etf_prices.as_of(m)` — 시세 시계열의 끝을 가린다 (가격 팩터)
  · `as_of="YYYY-MM-DD"` 문자열 — ALFRED 빈티지를 그 시점으로 고정한다 (매크로 팩터)

를 **둘 다** 걸어야 한다. 하나만 걸면 카탈로그의 나머지 절반에서 룩어헤드가 조용히 되살아난다.

★히스테리시스는 walk 를 타고 흐른다★
`state_from_value` 의 밴드는 "직전 상태"가 있어야 작동한다. 시점마다 previous 를 비워서
평가하면 히스테리시스가 **없는** 룰셋을 시뮬레이션하는 셈이고, 전환 횟수는 규칙에 유리한
방향으로 틀린다.

★적격성은 walk **전에** 판정한다★
`mode="backtest"` 는 가장 최신 시점에서 한 번 읽어 게이트를 통과시키고, 실패하면 걷기 전에
거부한다. 부적격 데이터로 만든 숫자가 로그·캐시에 남는 것 자체가 오염이라는
`evaluate_rule_set` 의 규칙을 그대로 따른다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from src.data.etf_prices import as_of as price_as_of
from src.engine.timing_factor_history import STEP, count_state_flips
from src.engine.timing_rules_v2 import (
    SignalState,
    TimingRuleSetV2,
    combine,
    read_factor,
    rule_set_states,
)

logger = logging.getLogger(__name__)

MAX_MONTHS = 240


def _shift_months(anchor: date, months_back: int) -> str:
    """anchor 에서 months_back 개월 전 같은 날 (말일은 그 달의 마지막 날로 클램프)."""
    total = anchor.year * 12 + (anchor.month - 1) - months_back
    y, m = divmod(total, 12)
    m += 1
    # 다음 달 1일에서 하루 빼면 그 달의 말일 — calendar 를 새로 끌어오지 않는다.
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    last = (date(ny, nm, 1) - date(y, m, 1)).days
    return date(y, m, min(anchor.day, last)).isoformat()


@dataclass(frozen=True)
class SimulationPoint:
    months_back: int
    as_of: str
    state: str
    exposure: float
    on_count: int
    off_count: int
    unavailable_count: int
    explanation: str

    def to_dict(self) -> dict:
        return {
            "months_back": self.months_back, "as_of": self.as_of,
            "state": self.state, "exposure": self.exposure,
            "on_count": self.on_count, "off_count": self.off_count,
            "unavailable_count": self.unavailable_count,
            "explanation": self.explanation,
        }


@dataclass(frozen=True)
class RuleSetSimulation:
    set_id: str
    market: str
    combination: str
    mode: str
    step: str
    backtest_eligible: bool
    points: list[SimulationPoint] = field(default_factory=list)
    state_changes: int = 0
    available_count: int = 0
    unavailable_count: int = 0
    #: 부적격 팩터 — mode="forward" 에서도 **가려지지 않는다**.
    ineligible_factors: list[dict] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "set_id": self.set_id, "market": self.market,
            "combination": self.combination, "mode": self.mode, "step": self.step,
            "backtest_eligible": self.backtest_eligible,
            "points": [p.to_dict() for p in self.points],
            "state_changes": self.state_changes,
            "available_count": self.available_count,
            "unavailable_count": self.unavailable_count,
            "ineligible_factors": list(self.ineligible_factors),
            "limitations": list(self.limitations),
        }


def eligibility_report(
    rule_set: TimingRuleSetV2,
    *,
    as_of: str,
    market: str | None = None,
) -> list[dict]:
    """룰셋의 팩터별 연구 등급 — 백테스트 부적격인 것만 사유와 함께.

    `assert_readings_backtest_eligible` 은 **예외**로 막는다(backtest 모드의 게이트).
    이 함수는 같은 판정을 **보고**로 낸다 — forward 모드에서도 "이 결과는 백테스트가 아니다"
    를 팩터 이름과 사유까지 붙여 내려보내기 위한 것이다. 등급 판정 자체는
    `read_factor` 한 곳에서만 나온다(여기서 다시 정하지 않는다).
    """
    from src.data.pit_macro import ResearchUsage

    mkt = market or rule_set.market
    bad: list[dict] = []
    for rule in rule_set.rules:
        universe = list(getattr(rule.base, "universe", []) or [])
        r = read_factor(
            rule.factor_id, as_of=as_of,
            ticker=universe[0] if universe else None, market=mkt,
            params=dict(getattr(rule.base, "params", {}) or {}))
        if r.usage is not ResearchUsage.BACKTEST_ELIGIBLE:
            bad.append({"factor_id": r.factor_id, "usage": r.usage.value,
                        "data_status": r.data_status.value, "reason": r.detail})
    return bad


def simulate_rule_set(
    rule_set: TimingRuleSetV2,
    *,
    months: int = 24,
    mode: str = "backtest",
    market: str | None = None,
    anchor: str | None = None,
) -> RuleSetSimulation:
    """`months` 개월 전부터 현재까지 월 간격으로 룰셋을 재평가한다.

    mode="backtest" 면 걷기 전에 `rule_set_states(mode="backtest")` 가 게이트를 걸고,
    부적격 팩터가 있으면 `ForwardOnlyError` 가 그대로 올라간다(호출자가 422 로 옮긴다).
    mode="forward" 는 걷되 `backtest_eligible=False` 와 부적격 팩터 목록을 함께 낸다.
    """
    mkt = market or rule_set.market
    span = max(1, min(int(months), MAX_MONTHS))
    anchor_date = (datetime.fromisoformat(anchor).date() if anchor
                   else datetime.now(timezone.utc).date())

    newest = _shift_months(anchor_date, 0)
    if mode == "backtest":
        # ★걷기 전에 거부한다★ 실패하면 여기서 예외가 나가고 어떤 점도 계산되지 않는다.
        with price_as_of(0):
            rule_set_states(rule_set, as_of=newest, mode="backtest", market=mkt)
        ineligible: list[dict] = []
    else:
        ineligible = eligibility_report(rule_set, as_of=newest, market=mkt)

    limitations = [
        f"표본 간격은 **월**입니다(as_of 절단이 월 단위). {span}개월 구간을 월 1점으로 표본합니다.",
        "각 점은 시세 절단(etf_prices.as_of)과 매크로 빈티지 고정(as_of 날짜)을 **함께** "
        "적용해 그 시점 이후의 정보를 보지 않습니다.",
    ]
    if mode != "backtest":
        limitations.append(
            "mode=forward 입니다 — 이 결과는 **백테스트가 아닙니다.** 부적격 팩터가 포함될 수 "
            "있으므로 성과 주장에 쓰지 마십시오(ineligible_factors 참조).")

    points: list[SimulationPoint] = []
    previous: SignalState | None = None
    for m in range(span, -1, -1):          # 오래된 → 최신
        stamp = _shift_months(anchor_date, m)
        try:
            with price_as_of(m):
                states = rule_set_states(rule_set, as_of=stamp, mode="forward",
                                         market=mkt, previous=previous)
            sig = combine(states, method=rule_set.combination, k=rule_set.k,
                          weights=list(rule_set.weights) or None)
            state, exposure = sig.state, sig.exposure
            counts = (sig.on_count, sig.off_count, sig.unavailable_count)
            explanation = sig.explanation
        except Exception as e:             # noqa: BLE001 — 한 점의 실패가 walk 를 깨지 않는다
            # ★`combine` 에 맡기지 않는다★ 전부 결측일 때 combine 은 보수적으로 위험-오프를
            # 돌려주는데, 그건 "신호가 위험-오프였다" 로 읽힌다. 평가 자체가 실패한 시점은
            # 판정이 아니라 **알 수 없음**이다 — 전환 집계에서도 건너뛰어야 한다.
            logger.debug(f"simulate_rule_set 실패 [{rule_set.set_id}/-{m}m]: {e}")
            state, exposure = SignalState.UNAVAILABLE, 0.0
            counts = (0, 0, len(rule_set.rules))
            explanation = f"이 시점의 평가에 실패했습니다: {e}"
        points.append(SimulationPoint(
            months_back=m, as_of=stamp, state=state.value, exposure=exposure,
            on_count=counts[0], off_count=counts[1], unavailable_count=counts[2],
            explanation=explanation))
        # ★결측은 직전 상태를 덮어쓰지 않는다★ 데이터 구멍 하나가 히스테리시스의 기억을
        # 지우면, 구멍 다음 점이 밴드 안에서도 새로 판정되어 없던 전환이 생긴다.
        if state is not SignalState.UNAVAILABLE:
            previous = state

    states_seq = [p.state for p in points]
    unavailable = sum(1 for s in states_seq if s == SignalState.UNAVAILABLE.value)
    if unavailable == len(points):
        limitations.append(
            "요청 구간에서 어떤 시점도 판정되지 않았습니다 — 시세 이력이 짧거나 조회에 "
            "실패했습니다. 0 으로 채우지 않습니다.")

    return RuleSetSimulation(
        set_id=rule_set.set_id, market=mkt, combination=rule_set.combination,
        mode=mode, step=STEP, backtest_eligible=(mode == "backtest"),
        points=points,
        state_changes=count_state_flips(states_seq),
        available_count=len(points) - unavailable,
        unavailable_count=unavailable,
        ineligible_factors=ineligible,
        limitations=limitations,
    )
