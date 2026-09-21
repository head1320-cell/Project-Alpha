"""KIS API 건강 관측 — ★세는 코드는 이미 있다. 없는 것은 통로다★ (AQ1)
==============================================================================
읽는 쪽: `src/execution/api_failure_probe.py` · 소비자: 킬스위치 `auto_api`
선례: `src/domain/equity_observation.py`(AI) — 어휘는 도메인, 읽기는 실행 계층.

## 왜 이 모듈이 생겼나

킬스위치의 네 트리거 중 `auto_api` 는 `account_state["api_failure_count"]` 를 보는데
**그 키를 쓰는 코드가 저장소에 없었다.** 그런데 실측하면 ★연속 실패 횟수 자체는
이미 유지되고 있다★ — `kis_client.CircuitBreaker` 가 `record_failure()` 로 세고
`record_success()` 로 0 으로 되돌린다(연속 의미). 없는 것은 **통로**였다.

## ★그런데 그 값을 그냥 옮기면 네 가지가 거짓이 된다★

    ① `MockKISClient` 에는 breaker 가 **없다** — mock 에서 0 을 실으면 합성 관측이
       되고, 그것이 AI 가 `equity_source` 로 막은 바로 그 자리다.
    ② `HALF_OPEN` 이 30초 뒤 카운트를 **0 으로 되돌린다** — KIS 가 계속 죽어 있어도
       장애 중 0 → 5 → 0 → 5 로 순환한다. ★카운트만 보면 "건강" 으로 읽힌다.★
    ③ 싱글턴이 아직 없으면 잴 대상이 없다 — 0 이 아니라 **미상**이다.
    ④ `OPEN`(호출 차단 중)과 "실패 중" 은 **다른 사실**이다. 차단 중에는
       `record_failure()` 가 불리지 않아 카운트가 얼어붙는다.

그래서 이 모듈은 ⑴ `broker` 출처가 아니면 숫자를 내지 않고 ⑵ breaker 상태를
숫자 옆에 **함께** 싣고 ⑶ `OPEN` 을 `blocking` 이라는 **별도 사실**로 낸다.

## ★이 모듈이 주장하지 않는 것★

- **KIS 가 건강하다고 말하지 않는다.** 연속 실패가 0 이어도 방금 차단이 풀린
  직후일 수 있고, 그 경우 `recently_tripped` 가 참이다.
- **실패의 종류를 가르지 않는다.** 전송 오류·HTTP·`rt_cd`·레이트리밋이 지금
  `_request` 에서 전부 같은 `RuntimeError` 로 뭉개진다 — 이 모듈은 그 뭉개진
  카운트를 옮길 뿐이고, 가르는 것은 별건이다.
- **토큰 실패를 세지 않는다.** `_fetch_token` 이 breaker 를 타지 않는다(실측).
  ★세지 않는다는 사실을 아는 것과 세는 것은 다르고, 여기서는 앞의 것만 한다.★
"""
from __future__ import annotations

from typing import Any

# ── 관측 출처 ──────────────────────────────────────────────────────────────
#: 실 KIS 클라이언트의 circuit breaker 에서 읽었다. ★이것만 재료가 된다★
SOURCE_BROKER = "broker"
#: mock 클라이언트 — breaker 자체가 없고, 합성 호출의 실패는 실패가 아니다.
SOURCE_MOCK = "mock"
#: 아직 클라이언트가 만들어지지 않았다 — 잴 대상이 없다.
SOURCE_NO_CLIENT = "no_client"
#: 출처를 밝히지 못했다.
SOURCE_UNKNOWN = "unknown"

API_SOURCES = (SOURCE_BROKER, SOURCE_MOCK, SOURCE_NO_CLIENT, SOURCE_UNKNOWN)

# ── circuit breaker 상태 ───────────────────────────────────────────────────
BREAKER_CLOSED = "closed"        # 정상 통과
BREAKER_OPEN = "open"            # ★호출 차단 중★ — 실패를 세지도 않는다
BREAKER_HALF_OPEN = "half_open"  # ★카운트가 0 으로 되돌려진 직후★
BREAKER_UNKNOWN = "unknown"

BREAKER_STATES = (BREAKER_CLOSED, BREAKER_OPEN, BREAKER_HALF_OPEN, BREAKER_UNKNOWN)

#: 관측 상태. ★값이 없는 것과 값이 0 인 것은 다르다.★
OBSERVED = "observed"
UNOBSERVED = "unknown"

_MOCK_REASON = (
    "mock 클라이언트에는 실패 카운터가 없습니다 — 합성 호출의 실패를 세면 "
    "★합성값으로 킬스위치를 켜는 것★이 됩니다. 브로커가 붙으면 잴 수 있습니다."
)
_NO_CLIENT_REASON = (
    "KIS 클라이언트가 아직 만들어지지 않아 잴 대상이 없습니다 — ★0 회 실패가 "
    "아니라 재지 못한 것★입니다."
)
_UNKNOWN_REASON = (
    "KIS 호출 실패 횟수의 출처를 밝히지 못했습니다 — 미상은 브로커가 아닙니다."
)
_NO_NUMBER_REASON = (
    "브로커 클라이언트는 있으나 연속 실패 횟수를 숫자로 읽지 못했습니다."
)

_NOTE = (
    "이 값은 KIS 호출의 ★연속★ 실패 횟수입니다 — 성공 한 번이 0 으로 되돌립니다. "
    "★0 이 '정상' 을 뜻하지는 않습니다★: circuit breaker 가 열렸다가 대기시간이 "
    "지나면 카운트가 0 으로 되돌려지므로, 장애가 이어지는 동안에도 0 이 관측될 수 "
    "있습니다. 그래서 상태(closed/open/half_open)를 숫자와 함께 싣습니다. "
    "또한 토큰 발급 실패는 이 카운트에 들어가지 않습니다."
)


def usable_for_kill_switch(source: Any) -> bool:
    """이 출처의 숫자를 킬스위치 재료로 써도 되나. ★`broker` 만 참★

    ★관대하게 보지 않는다★ — `"BROKER"`·`"broker "`·`"real"` 은 전부 거짓이다.
    출처는 이 저장소가 직접 찍는 값이라 표기가 흔들릴 이유가 없다(AI 의
    `usable_for_drawdown` 과 같은 규율).
    """
    return source == SOURCE_BROKER


def source_reason(source: Any) -> str | None:
    """왜 재료가 못 되는가. ★셋을 같은 문장으로 적지 않는다★ — 처방이 다르다."""
    if source == SOURCE_BROKER:
        return None
    if source == SOURCE_MOCK:
        return _MOCK_REASON
    if source == SOURCE_NO_CLIENT:
        return _NO_CLIENT_REASON
    return _UNKNOWN_REASON


def _whole_count(value: Any) -> int | None:
    """연속 실패 횟수는 **정수**다. ★모양이 다르면 지어내지 않는다★"""
    if value is None or isinstance(value, bool) or not isinstance(value, int):
        return None
    # ★음수는 카운터가 아니다★ — `math.isfinite` 는 `int` 에서 언제나 참이라
    # 여기 두면 공허한 분기가 된다(CLAUDE.md §5).
    return value if value >= 0 else None


def api_failure_observation(*, count: Any, breaker_state: Any,
                            source: Any, reason: str | None = None
                            ) -> dict[str, Any]:
    """KIS 연속 실패 관측 하나. ★숫자와 그 숫자를 어떻게 알았나를 함께 낸다★

    Returns:
        `{count, state, source, breaker_state, blocking, recently_tripped,
          reason, note}` — `count` 는 ★`broker` 출처에서 정수를 읽었을 때만★
        숫자이고, 그 외에는 `None` 이며 `reason` 이 왜인지 말한다.
    """
    src = source if source in API_SOURCES else SOURCE_UNKNOWN
    state = breaker_state if breaker_state in BREAKER_STATES else BREAKER_UNKNOWN

    number = _whole_count(count) if usable_for_kill_switch(src) else None
    if number is None:
        why = reason or source_reason(src) or _NO_NUMBER_REASON
    else:
        why = reason

    return {
        "count": number,
        "state": OBSERVED if number is not None else UNOBSERVED,
        "source": src,
        "breaker_state": state,
        # ★차단 중은 실패 중과 다른 사실★ — 카운트로 계산하지 않는다.
        "blocking": None if state == BREAKER_UNKNOWN else state == BREAKER_OPEN,
        # ★방금 열렸다 풀린 직후의 0 을 건강으로 읽지 않게★
        "recently_tripped": None if state == BREAKER_UNKNOWN
        else state in (BREAKER_OPEN, BREAKER_HALF_OPEN),
        "reason": why,
        "note": _NOTE,
    }
