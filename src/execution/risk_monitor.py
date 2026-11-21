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

#: ★어느 트리거가 **어느 드로다운**을 봤나★ (AP3)
#:
#: `kill_switch.should_auto_trigger()` 는 둘을 **다른 임계값**으로 비교한다 —
#: `auto_dd` 는 누적(-10%), `auto_cb` 는 일중(-5%). 발동 기록에 남길 값은
#: ★그 트리거가 실제로 비교한 값★이고, 둘을 바꿔 실으면 다른 사실이 된다.
DD_AXIS_BY_SOURCE = {"auto_dd": "cumulative_dd_pct",
                     "auto_cb": "current_drawdown_pct"}


def dd_for_source(source: str | None, account_state: dict) -> float | None:
    """이 트리거를 **일으킨** 드로다운. ★원인이 아니면 싣지 않는다★

    `auto_risk`(국면)·`auto_api`(연속 실패)는 드로다운과 무관하므로 `None` 이다 —
    마침 손에 있는 숫자를 실으면 기록이 *"이 드로다운 때문에 발동했다"* 는
    **없는 사실**을 말하게 된다(CLAUDE.md §2 — 어떤 질문에 답한 것인지 밝힌다).
    """
    axis = DD_AXIS_BY_SOURCE.get(source or "")
    if axis is None:
        return None
    value = (account_state or {}).get(axis)
    return None if value is None else float(value)


def current_regime_state() -> dict | None:
    """감시용 국면 상태. ★못 읽으면 `None` — 0 으로 만들지 않는다.★

    ★감시 데몬(`lifecycle._risk_monitor_bg`)과 readiness 라우트가 같은 함수를 쓴다★
    (BH1) — 예전에는 라우트가 `regime_state=None` 을 하드코딩해 데몬이 무엇을 보든
    `auto_risk` 를 불능으로 보고했다.

    ★`systemic_risk_score` 를 싣지 않는다 — 지어낼 수 없기 때문이다.★

    킬스위치의 `auto_risk` 는 `systemic_risk_score`(0~100)를 본다. 그런데 실측하면:

      · 이 값의 생산자로 지목됐던 `src/engine/regime_model.MultiRegimeModel` 은
        BH3 에서 복원됐지만 ★백테스트 사분면만 판정하고 이 점수는 생산하지 않는다★
        (늘 `None` + 사유 — 킬스위치 재료라 별도 승인, 사용자가 D 를 제외했다).
      · `regime_analyzer.RegimeState` 가 드는 것은 `stress_score`(0~100)이고,
        두 이름을 잇는 코드는 저장소 어디에도 없다.

    둘이 같은 양인지 **확인된 적이 없다**. 파이프라인을 돌리려고 이름을 바꿔 끼우는
    것은 CLAUDE.md §4 가 금지한 일이므로, 여기서는 국면 정보를 그대로 싣고
    `systemic_risk_score` 는 **비워 둔다** → `auto_risk` 가 `unverified` 로 기록된다.
    ★그 기록이 이 미상을 다음 사람에게 넘기는 방법이다.★
    """
    try:
        from src.engine.regime_analyzer import get_regime_state
        st = get_regime_state()
        return {"regime": st.regime, "stress_score": st.stress_score,
                "recommended_mode": st.recommended_mode}
    except Exception as e:                      # noqa: BLE001
        logger.debug(f"국면 상태 조회 불가(미상으로 기록): {e}")
        return None


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
            # ★관측을 실어 보낸다★ (AP3) — 예전에는 `source`·`reason` 만 넘겨
            # 기본값 `0` 이 `equity_at_trigger`·`dd_at_trigger` 에 관측인 척
            # 기록됐다. ★`kis_client` 는 여전히 넘기지 않는다 — 동작 0줄★이고,
            # 그 사실은 발동 기록의 `actions` 가 `skipped` + 사유로 말한다.
            kill_switch.trigger(
                source=v.source, reason=v.reason,
                # 감시는 브로커를 부르지 않는다(AI 가 세운 경계) → 미상 그대로.
                equity=(account_state or {}).get("equity_krw"),
                dd_pct=dd_for_source(v.source, account_state),
                regime=(regime_state or {}).get("regime"),
            )
        except Exception as e:                           # noqa: BLE001
            logger.error(f"킬스위치 자동 발동 실패: {e}")

    return v
