"""걸음 엔진 — 봉이 닫힐 때마다 그날의 지금까지 봉으로 다시 돌려 ★새로 생긴 체결 줄만★ 낸다 (순수 · 입출력 없음)

규칙 가동(설계 W5 §5.4)의 뼈대다. 규칙 평가 코드를 새로 쓰지 않는다 — 같은 `simulate` 를 `Day(final=False)` 로 부른다.

    ★걸음마다 낸 체결의 이어 붙임 = 그 하루를 한 번에 돌린 체결★

이 성질이 기록 전용 가동의 가상 체결을 백테스트와 같은 것으로 만든다(다르면 결함 — `tests/test_intraday_stepper.py`).

- 받는 하루(`Day`)는 봉을 준비한 쪽이 만든 것 그대로다(건너뛴 종목 · 장 운영 시간이 다른 날 표시 포함). 걸음은 시각(`"HHMMSS"`)만 민다:
  그 시각까지의 봉으로 잘라 다시 돈다. ★앞을 보지 않는다★ — 잘린 뒤쪽 봉은 시뮬레이터에 넘어가지 않는다.
- 하루를 처음부터 다시 도는 셈이라 비싸다(봉 수의 제곱). 느린지 먼저 재고, 증분으로 바꾸는 것은 재서 필요할 때만 한다.
- 다시 돌린 결과의 앞부분이 이미 낸 줄과 다르면 ★조용히 덮지 않는다★(`not_monotone`). 늦게 도착한 앞 시각의 봉 같은 것이 그렇게 드러난다.
- `finish()` 는 하루가 끝났다는 뜻이다 — 마지막 봉의 강제 청산 줄이 그때 나온다. 중간에 멈추는 가동은 `finish` 를 부르지 않는다
  (없는 청산을 지어내지 않는다).
"""
from __future__ import annotations

import numpy as np

from .simulator import CostAssumptions, Day, PositionRules, RuleSpec, simulate, validate
from .types import Session

REASONS = {
    "out_of_order": "봉의 시각이 앞선 걸음보다 늦지 않습니다.",
    "finished": "이미 끝난 하루입니다.",
    "not_monotone": "다시 계산한 체결이 앞에서 낸 체결과 다릅니다. 앞 시각의 봉이 뒤늦게 바뀌었을 수 있습니다.",
}


class StepError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(REASONS[code])
        self.code = code


def _upto(s: Session, label: str) -> Session:
    k = int(np.searchsorted(np.asarray(s.time, dtype=str), label, side="right"))
    return Session(s.ticker, s.date, s.time[:k], s.open[:k], s.high[:k], s.low[:k], s.close[:k], s.volume[:k], s.source,
                   s.prev, s.market, s.instrument, s.name)


class Stepper:
    """하루 하나 · 규칙 하나. `fills` 는 지금까지 낸 줄(낸 순서), `events` 는 줄마다의 종류다."""

    def __init__(self, day: Day, rule: RuleSpec, position: PositionRules, costs: CostAssumptions, *, rules: dict | None = None) -> None:
        validate(rule, position, costs)                           # 틀린 설정은 첫 봉이 아니라 여기서 거절한다
        self._day, self._rule, self._position, self._costs, self._rules = day, rule, position, costs, rules
        self._last: str | None = None
        self._done = False
        self.fills: list[dict] = []
        self.events: list[str] = []

    def step(self, label: str) -> list[dict]:
        """`label` 시각의 봉이 닫혔다 → 그 시각까지의 봉으로 다시 돌려 새로 생긴 줄만."""
        if self._done:
            raise StepError("finished")
        if self._last is not None and label <= self._last:
            raise StepError("out_of_order")
        new = self._rerun(label, final=False)
        self._last = label
        return new

    def finish(self) -> list[dict]:
        """하루가 끝났다 → 마지막 봉의 강제 청산 줄. 한 번도 걷지 않은 하루는 빈 목록이다."""
        if self._done:
            raise StepError("finished")
        new = self._rerun(self._last, final=True) if self._last is not None else []
        self._done = True
        return new

    def _rerun(self, label: str, *, final: bool) -> list[dict]:
        cut = {ticker: _upto(s, label) for ticker, s in self._day.sessions.items()}
        out = simulate([Day(self._day.date, cut, self._day.skipped, self._day.shifted, final)], self._rule, self._position,
                       self._costs, rules=self._rules)
        seen = len(self.fills)
        if out["fills"][:seen] != self.fills:
            raise StepError("not_monotone")
        kinds = {e["row"]: e["kind"] for e in out["events"]}
        new = [dict(f) for f in out["fills"][seen:]]
        self.fills.extend(dict(f) for f in new)
        self.events.extend(kinds[seen + i] for i in range(len(new)))
        return new
