"""시행 줄의 설정 사본 → 규칙 · 포지션 · 비용 — 읽는 곳은 여기 하나다(G4 · 구현 계획 §5.2-1).

가동 · 관제(`src.execution.rule_runner.parts_of` 가 감싼다)와 분봉 하루 보기(`/intraday/trials/{trial_key}/day`)가
★그때 돌린 설정★을 같은 함수로 다시 짓는다 — 읽는 길이 둘로 갈리면 같은 시행이 두 가지로 읽힐 수 있다.
분봉 모듈은 주문 경로를 들일 수 없어(정적 시험) 몸을 엔진 쪽에 둔다. 순수 함수다(설정 · 저장소를 읽지 않는다).
"""
from __future__ import annotations

from src.engine.intraday import expr, rules
from src.engine.intraday.simulator import CostAssumptions, PositionRules, RuleSpec, SimError, validate


class SettingUnreadable(ValueError):
    """지금의 틀로 읽히지 않는 설정 사본(없는 종류 · 받지 않는 값 · 없는 칸 · 꼴이 틀린 사본)."""


def parts_of(setting: dict) -> tuple[RuleSpec, PositionRules, CostAssumptions]:
    """설정 사본(시행 줄의 설정 · 가동 줄의 `request`) → 규칙 · 포지션 · 비용. 읽히지 않으면 `SettingUnreadable`."""
    try:
        rule = rules.build(setting["rule"]["kind"], setting["rule"]["params"])
        position = PositionRules(**setting["position"])
        costs = CostAssumptions(**setting["costs"])
        validate(rule, position, costs)
    except (rules.RuleError, SimError, expr.ExprError, KeyError, TypeError) as err:
        raise SettingUnreadable(type(err).__name__) from None
    return rule, position, costs
