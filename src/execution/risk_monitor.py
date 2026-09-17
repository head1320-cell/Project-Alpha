"""리스크 상시 감시 — ★관측만이 기본★ (P1-b)
==============================================================================
호출부: `src/startup/lifecycle.py::_risk_monitor_bg()`
판정기: `execution/kill_switch.py` · 상태: `execution/order_executor.py::_fetch_account_state`

## 왜 이 모듈이 생겼나 — ★부품은 다 있는데 부르는 곳이 없었다★

`kill_switch.should_auto_trigger()` 의 유일한 호출부는 **클래스 docstring 의 사용
예시**였고, 그 주석은 *"모니터링 루프에서 호출"* 이라고 적혀 있는데 그 루프가
없었다. `apscheduler` 는 requirements 에 선언만 되고 `src/` 안 사용처가 0 이었다.
즉 24시간 감시라고 부를 것이 아무것도 돌지 않았다.

## ★이 감시자는 아무것도 막지 않는다★

기본 동작은 ⑴ 재고 ⑵ 판정하고 ⑶ **기록**하는 것까지다. 자동 발동(청산·주문 취소)은
`RISK_MONITOR_AUTOTRIGGER` 가 **정확히 `"1"`** 일 때만 켜진다 —
`mock_gate.mock_allowed()` 와 같은 엄격 비교 관례다. 느슨하게 비교하면
`"false"`·`"0 "` 같은 값이 실계좌를 청산시킬 수 있다.

## ★"정상" 과 "못 봤다" 를 구분한다★

`should_auto_trigger()` 가 `None` 을 돌려주는 데는 두 이유가 있다 — *한도 안에 있다*
와 *잴 수 없었다*. 후자를 "정상" 으로 적으면, 이 감시자는 **구조적으로 아무것도
볼 수 없으면서 안심을 생산하는 장치**가 된다. 그래서 판정이 셋이다.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

from src.execution.audit_trail import EventCategory, Severity

logger = logging.getLogger(__name__)

#: ★정확히 `"1"` 일 때만★ 자동 발동. 그 외는 전부 관측만.
AUTOTRIGGER_ENV = "RISK_MONITOR_AUTOTRIGGER"

#: 판정 셋. ★`unknown` 을 `ok` 로 접지 않는다.★
VERDICT_OK = "ok"
VERDICT_WOULD_TRIGGER = "would_trigger"
VERDICT_UNKNOWN = "unknown"

#: 감사 이벤트 타입(기존 `EventType` 어휘를 늘리지 않고 여기서 선언).
EVENT_RISK_MONITOR = "RISK_MONITOR_TICK"


def autotrigger_allowed() -> bool:
    """★엄격 비교★ — `mock_gate.mock_allowed()` 와 같은 규약."""
    return os.getenv(AUTOTRIGGER_ENV, "") == "1"


@dataclass(frozen=True)
class MonitorVerdict:
    verdict: str
    source: str | None = None
    reason: str | None = None
    #: 무엇을 보지 못했나. ★비어 있어야만 `ok` 라고 말할 수 있다.★
    unverified: tuple[str, ...] = field(default_factory=tuple)

    @property
    def key(self) -> tuple:
        """중복 억제용 신원 — 같은 판정이 반복되면 기록하지 않는다."""
        return (self.verdict, self.source, self.unverified)


def evaluate(kill_switch, account_state: dict, regime_state: dict | None) -> MonitorVerdict:
    """한 번 재고 판정한다. ★예외를 삼키되 흔적을 남긴다.★"""
    try:
        unverified = tuple(kill_switch.unverified_checks(account_state, regime_state))
        hit = kill_switch.should_auto_trigger(account_state, regime_state)
    except Exception as e:                               # noqa: BLE001
        # 판정기 자체가 실패했다 — ★그것도 "못 봤다" 다★
        return MonitorVerdict(VERDICT_UNKNOWN, unverified=(f"evaluate_failed: {e}",))

    if hit is not None:
        return MonitorVerdict(VERDICT_WOULD_TRIGGER, source=hit[0], reason=hit[1],
                              unverified=unverified)
    if unverified:
        return MonitorVerdict(VERDICT_UNKNOWN, unverified=unverified)
    return MonitorVerdict(VERDICT_OK)


_SEVERITY = {
    VERDICT_OK: Severity.INFO,
    VERDICT_UNKNOWN: Severity.WARN,
    VERDICT_WOULD_TRIGGER: Severity.CRITICAL,
}


def run_once(*, kill_switch, audit, account_state: dict,
             regime_state: dict | None, last: MonitorVerdict | None) -> MonitorVerdict:
    """감시 한 주기. 반환값을 다음 주기의 `last` 로 넘긴다.

    ★기록은 판정이 바뀔 때만★ — 브로커 미연결 환경에서는 `unknown` 이 영원히
    반복되므로, 매 주기 적으면 감사 기록이 소음으로 덮인다.
    """
    v = evaluate(kill_switch, account_state, regime_state)

    if last is None or last.key != v.key:
        try:
            audit.log(
                event_type=EVENT_RISK_MONITOR,
                category=EventCategory.RISK,
                severity=_SEVERITY.get(v.verdict, Severity.INFO),
                decision=v.verdict,
                reason_code=v.verdict,
                context={"source": v.source, "reason": v.reason,
                         "unverified": list(v.unverified),
                         "autotrigger": autotrigger_allowed()},
                actor="risk_monitor",
                message=v.reason or (
                    "감시: 판정 불가 — " + "; ".join(v.unverified) if v.unverified
                    else "감시: 한도 이내"),
            )
        except Exception as e:                           # noqa: BLE001
            # ★기록 실패가 감시를 멈추지 않는다★ — 판정은 그대로 돌려준다.
            logger.warning(f"리스크 감시 기록 실패(판정은 유효): {e}")

    if v.verdict == VERDICT_WOULD_TRIGGER and autotrigger_allowed():
        try:
            kill_switch.trigger(source=v.source, reason=v.reason)
        except Exception as e:                           # noqa: BLE001
            logger.error(f"킬스위치 자동 발동 실패: {e}")

    return v
