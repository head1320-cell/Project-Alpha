"""설정 읽기 한 곳(G4 · 계획 문서 §5.2-1) — 시행 줄의 설정 사본 → 규칙 · 포지션 · 비용.

분봉 하루 보기(`/trials/{trial_key}/day`)와 가동 · 관제(`rule_runner.parts_of`)가 ★같은 함수★로 읽는다 — 읽는 길이 둘로 갈리지 않는다.
분봉 모듈은 `execution` 을 들일 수 없어(정적 시험) 몸이 엔진 쪽(`src/engine/intraday/setting.py`)에 있다."""
from __future__ import annotations

import pytest

import src.execution.rule_runner as runner
from src.api.intraday_routes import CostsBody, PositionBody
from src.engine.intraday import rules as templates
from src.engine.intraday import setting
from src.engine.intraday.simulator import CostAssumptions, PositionRules, RuleSpec

POSITION = PositionBody(amount=1_000_000).model_dump()
COSTS = CostsBody(commission_bp=1.5, slippage_ticks=1).model_dump()


def _setting(kind="opening_range_breakout", params=None, position=None, costs=None) -> dict:
    return {"rule": {"kind": kind, "params": templates.resolve(kind, {"minutes": 1} if params is None else params)},
            "position": {**POSITION, **(position or {})}, "costs": {**COSTS, **(costs or {})}}


def test_a_readable_setting_becomes_the_rule_the_position_and_the_costs():
    rule, position, costs = setting.parts_of(_setting(position={"stop_pct": 1.5}))
    want = templates.build("opening_range_breakout", templates.resolve("opening_range_breakout", {"minutes": 1}))
    assert isinstance(rule, RuleSpec) and rule == want
    assert position == PositionRules(**{**POSITION, "stop_pct": 1.5})
    assert costs == CostAssumptions(**COSTS)


@pytest.mark.parametrize("broken", [
    {"rule": {"kind": "no_such_template", "params": {}}},                       # 지금의 틀에 없는 종류
    {"rule": {"kind": "opening_range_breakout", "params": {"minutes": 0}}},     # 틀이 받지 않는 값
    {"position": {"amount": 1_000_000, "no_such_field": 1}},                    # 포지션에 없는 칸
    {"costs": {**COSTS, "slippage_ticks": -1}},                                 # 엔진 검사가 거절하는 값
    {"rule": None},                                                             # 꼴이 틀린 사본
])
def test_an_unreadable_setting_is_refused_with_its_own_error(broken):
    with pytest.raises(setting.SettingUnreadable):
        setting.parts_of({**_setting(), **broken})


def test_a_setting_without_one_of_its_three_parts_is_refused():
    for part in ("rule", "position", "costs"):
        stripped = {k: v for k, v in _setting().items() if k != part}
        with pytest.raises(setting.SettingUnreadable):
            setting.parts_of(stripped)


def test_the_runner_reads_settings_through_the_same_function(monkeypatch):
    """가동 · 관제의 `parts_of` 는 감싸기만 한다 — 같은 답 · 못 읽으면 그대로 `bad_setting`."""
    good = _setting()
    assert runner.parts_of(good) == setting.parts_of(good)
    seen: list[dict] = []
    real = setting.parts_of
    monkeypatch.setattr(setting, "parts_of", lambda s: seen.append(s) or real(s))
    runner.parts_of(good)
    assert seen == [good]
    with pytest.raises(runner.RunRefused) as err:
        runner.parts_of({**good, "rule": {"kind": "no_such_template", "params": {}}})
    assert err.value.code == "bad_setting"
