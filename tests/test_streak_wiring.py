"""AT3·AT4 · ★판정 자리가 구성을 말한다★
==============================================================================
대상: `api_health.api_failure_observation` · `api_failure_probe.probe` ·
`kill_switch.should_auto_trigger` · `GET /kill-switch/readiness`

## 무엇이 달라지나

예전에 `auto_api` 가 발동하면 `live_kill_events` 에 남는 사유는
*"KIS API 연속 실패 (5회)"* 한 줄이었다. 사건 조사를 하러 그 행을 열어도
★그 5회가 무엇이었는지는 사라지고 없다★ — 장 종료 5번이었는지 KIS 가 정말
죽었는지 구별되지 않는다.

이제 그 사유가 구성을 데리고 간다. ★사유 문자열이 그대로 저장되므로 DDL 변경
0줄이다.★

## ★판정은 0줄 바뀐다★

임계값도, 어떤 종류가 카운트되는지도, `should_auto_trigger` 의 **조건**도
그대로다. 바뀌는 것은 **무엇을 말하는가**뿐이다 — 세는 것을 바꾸는 것은
실거래 호출 경로 동작 변경이라 별도 승인 사항이다(CLAUDE.md §6).

## ★mock 을 관측으로 팔지 않는다★

AQ 가 숫자에 대해 세운 규칙을 구성도 그대로 따른다: `broker` 출처가 아니면
숫자를 내지 않듯 구성도 내지 않는다. `MockKISClient` 에는 breaker 가 아예
없으므로 그쪽의 구성은 합성이 된다.
"""
from __future__ import annotations

import pytest

from src.domain.api_health import (
    BREAKER_CLOSED,
    BREAKER_OPEN,
    SOURCE_BROKER,
    SOURCE_MOCK,
    SOURCE_NO_CLIENT,
    api_failure_observation,
)
from src.domain.failure_streak import streak_composition
from src.domain.kis_failure import KIND_BUSINESS, KIND_TRANSPORT
from src.execution.kill_switch import KillSwitch, KillSwitchConfig

# ── AT3 ★관측이 구성을 싣는다★ ────────────────────────────────────────

def test_a_broker_observation_carries_the_streak():
    obs = api_failure_observation(
        count=5, breaker_state=BREAKER_OPEN, source=SOURCE_BROKER,
        streak=streak_composition([KIND_BUSINESS] * 5, count=5))
    assert obs["streak"]["all_business"] is True
    assert obs["streak"]["describes_count"] is True


def test_the_streak_is_always_a_key_even_when_absent():
    """★키가 사라지지 않는다★ — 없는 키는 소비자가 못 보고 지나간다."""
    obs = api_failure_observation(count=0, breaker_state=BREAKER_CLOSED,
                                  source=SOURCE_BROKER)
    assert "streak" in obs


def test_a_mock_source_does_not_report_a_streak():
    """★합성을 관측으로 팔지 않는다★ — 숫자에 건 규칙을 구성에도 건다."""
    obs = api_failure_observation(
        count=5, breaker_state=BREAKER_OPEN, source=SOURCE_MOCK,
        streak=streak_composition([KIND_BUSINESS] * 5, count=5))
    assert obs["count"] is None
    assert obs["streak"] is None


def test_no_client_does_not_report_a_streak():
    obs = api_failure_observation(
        count=None, breaker_state=None, source=SOURCE_NO_CLIENT,
        streak=streak_composition([KIND_BUSINESS], count=1))
    assert obs["streak"] is None


def test_the_streak_is_composed_against_the_observed_count():
    """★구성이 그 숫자를 설명하는지 판정한다★ — 다른 숫자면 그렇게 말한다."""
    obs = api_failure_observation(
        count=5, breaker_state=BREAKER_OPEN, source=SOURCE_BROKER,
        streak=streak_composition([KIND_BUSINESS] * 3, count=5))
    assert obs["streak"]["describes_count"] is False
    assert obs["streak"]["reason"]


# ── AT3 ★프로브가 breaker 에서 읽는다★ ────────────────────────────────

class _Breaker:
    def __init__(self, kinds=(), state="OPEN"):
        self.state = state
        self.failure_count = len(kinds)
        self._kinds = tuple(kinds)

    def streak_kinds(self):
        return self._kinds


class _Client:
    def __init__(self, kinds=(), state="OPEN"):
        self.circuit_breaker = _Breaker(kinds, state)


def _probe(client):
    from src.execution.api_failure_probe import probe

    return probe(client=client)


def test_the_probe_reads_the_streak_from_the_breaker():
    obs = _probe(_Client([KIND_BUSINESS] * 5))
    assert obs["streak"]["by_kind"] == {KIND_BUSINESS: 5}


def test_the_probe_survives_a_breaker_without_a_ring():
    """★없으면 지어내지 않는다★ — 옛 객체·테스트 더블도 죽지 않는다."""
    class _Old:
        state = "CLOSED"
        failure_count = 2

    class _C:
        circuit_breaker = _Old()

    obs = _probe(_C())
    assert obs["streak"] is None or obs["streak"]["n_recorded"] == 0


def test_a_mixed_streak_is_not_reported_as_all_business():
    obs = _probe(_Client([KIND_BUSINESS] * 4 + [KIND_TRANSPORT]))
    assert obs["streak"]["all_business"] is False
    assert obs["streak"]["business_n"] == 4


# ── AT4 ★사유가 구성을 데리고 간다★ ──────────────────────────────────

@pytest.fixture()
def ks(monkeypatch):
    """★`is_active()` 를 False 로 고정한다★

    `engine=None` 이면 조회가 실패해 페일세이프로 `True` 가 나오고(의도된
    동작), 그러면 `should_auto_trigger` 가 *"이미 발동 중"* 으로 **무조건
    `None`** 을 돌려준다. 그대로 두면 "발동하지 않는다" 계열 테스트가
    ★엉뚱한 이유로 통과한다★ — `test_kill_switch_honesty.py` 가 같은 함정을
    적어 두었고, 이 파일도 처음에 그대로 빠졌다.
    """
    switch = KillSwitch(engine=None, audit_trail=None, config=KillSwitchConfig())
    monkeypatch.setattr(switch, "is_active", lambda: False)
    return switch


def _state(count, streak_kinds=None, **extra):
    obs = api_failure_observation(
        count=count, breaker_state=BREAKER_OPEN, source=SOURCE_BROKER,
        streak=streak_composition(streak_kinds, count=count))
    state = {"api_failure_count": count, "api_failure_observation": obs}
    state.update(extra)
    return state


def test_the_trigger_reason_names_the_composition(ks):
    out = ks.should_auto_trigger(_state(5, [KIND_BUSINESS] * 5), None)
    assert out is not None and out[0] == "auto_api"
    assert "5" in out[1]
    assert "업무 응답" in out[1]


def test_the_reason_says_the_meaning_is_unknown(ks):
    """★AS 의 표가 비어 있다★ — 업무 응답이라고 거절이라 단정하지 않는다."""
    out = ks.should_auto_trigger(_state(5, [KIND_BUSINESS] * 5), None)
    assert "미상" in out[1]


def test_the_reason_keeps_its_old_shape(ks):
    """★문구 계약은 없지만 앞부분은 그대로 둔다★ — 구성은 뒤에 붙는다."""
    out = ks.should_auto_trigger(_state(5, [KIND_BUSINESS] * 5), None)
    assert out[1].startswith("KIS API 연속 실패 (5회")


def test_a_mixed_streak_reason_does_not_say_all(ks):
    """변이 — 짝. 섞여 있으면 전칭을 말하지 않는다."""
    out = ks.should_auto_trigger(
        _state(5, [KIND_BUSINESS] * 3 + [KIND_TRANSPORT] * 2), None)
    assert "전부" not in out[1]
    assert "업무 응답" in out[1]


def test_a_reason_without_an_observation_still_works(ks):
    """★구성이 없어도 판정은 그대로다★ — 관측이 판정의 조건이 아니다."""
    out = ks.should_auto_trigger({"api_failure_count": 5}, None)
    assert out is not None and out[0] == "auto_api"
    assert out[1].startswith("KIS API 연속 실패 (5회")


# ── AT4 ★판정은 0줄 바뀐다★ ──────────────────────────────────────────

def test_below_the_threshold_still_does_not_trigger(ks):
    """변이 f — 구성이 판정 **조건**에 들어가면 죽는다."""
    assert ks.should_auto_trigger(_state(4, [KIND_BUSINESS] * 4), None) is None


def test_an_all_business_streak_still_triggers(ks):
    """★재는 것과 막는 것은 다르다★

    5회가 전부 업무 응답이어도 **여전히 발동한다** — AT 는 그것을 고치지 않고
    보이게만 한다. 고치는 것은 실거래 호출 경로 동작 변경이라 별도 승인
    사항이고, 그 전에 근거가 되는 수치가 있어야 한다. 이것이 그 수치다.
    """
    out = ks.should_auto_trigger(_state(5, [KIND_BUSINESS] * 5), None)
    assert out is not None and out[0] == "auto_api"


def test_an_unknown_count_still_does_not_trigger(ks):
    """AF2 의 `is not None` 계약은 그대로다."""
    state = {"api_failure_observation": api_failure_observation(
        count=None, breaker_state=None, source=SOURCE_NO_CLIENT)}
    assert ks.should_auto_trigger(state, None) is None


def test_the_threshold_is_untouched():
    assert KillSwitchConfig().api_failure_threshold == 5
