"""킬스위치 조치 — ★발동했는가 ⟂ 무엇을 했는가★ (AP1)
==============================================================================
소비자: `src/execution/kill_switch.py::trigger()` · 표면
`src/api/stage13_routes.py`(`/kill-switch/status` · `/kill-switch/events`)

## 왜 이 모듈이 생겼나 — ★기록이 하지 않은 일을 했다고 말했다★

`live_kill_events` 한 행이 **두 사실**을 섞고 있었다. *"발동했다"* 와 *"발동해서
정리했다"*. 실측하면 셋이 나온다:

    ① 자동 경로(`risk_monitor.run_once`)는 `kis_client` 를 넘기지 않는다
       → `_cancel_open_orders` 를 **건너뛰는데** `n_orders_cancelled = 0` 이 남는다.
       ★"취소할 주문이 없었다" 와 "취소를 시도하지 않았다" 가 같은 `0`★ 이다.

    ② 청산 결과의 초기값이 `{"complete": True}` 이고 `hold` 모드에서는 교체되지
       않는다 → ★청산을 아예 하지 않고도 `liquidation_complete: True`★.

    ③ `equity`·`dd_pct` 의 기본값이 `0` 이고 **어느 호출부도 `dd_pct` 를 넘기지
       않는다** → `dd_at_trigger` 가 저장소 전체에서 언제나 `0` 이다. 드로다운
       때문에 발동한 사건의 드로다운이 `0` 으로 남는다(AM 의 `"dev"` 와 같은 모양).

## ★`skipped` 와 `done(0건)` 을 가른다★

이 모듈의 존재 이유 한 줄이다. 둘은 **다른 사실**이고 처방이 다르다 — 전자는
*"이 경로는 그 일을 하지 않는다"*(고쳐야 할 배선), 후자는 *"할 일이 없었다"*
(정상). `0` 하나로 적으면 앞의 것이 영원히 보이지 않는다.

## ★`block_new_orders` 만이 언제나 참이다★

이벤트 행이 생기면 `is_active()` 가 참이 되고 `order_executor` 가 **두 지점**에서
주문을 막는다(검증 시점 · 발주 직전 레이스). 나머지 셋은 **경로마다 다르다.**

## ★이 모듈이 주장하지 않는 것★

- **조치가 옳았다고 말하지 않는다.** 무엇을 했고 무엇을 안 했는지만 적는다.
- **`cleared` 가 안전을 뜻하지 않는다.** 넷을 다 했다는 뜻이고, `gradual` 청산은
  넷을 다 해도 ★1/5 만 판다★(AF1).
- **소급하지 않는다.** 이 어휘가 생기기 전 행은 `unknown` 이고 채우지 않는다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

# ── 조치 넷 ────────────────────────────────────────────────────────────────
#: 이후 주문 차단 — ★이벤트 행이 생기는 순간 참★(`is_active()` 가 DB 로 판정).
ACTION_BLOCK_NEW_ORDERS = "block_new_orders"
#: 미체결 주문 취소 — 브로커 클라이언트가 있어야 시도한다.
ACTION_CANCEL_OPEN = "cancel_open_orders"
#: 보유 청산 — `hold` 모드에서는 시도하지 않는다.
ACTION_LIQUIDATE = "liquidate_positions"
#: 통지.
ACTION_NOTIFY = "notify"

KILL_ACTIONS = (ACTION_BLOCK_NEW_ORDERS, ACTION_CANCEL_OPEN,
                ACTION_LIQUIDATE, ACTION_NOTIFY)

ACTION_LABELS = {
    ACTION_BLOCK_NEW_ORDERS: "신규 주문 차단",
    ACTION_CANCEL_OPEN: "미체결 주문 취소",
    ACTION_LIQUIDATE: "보유 청산",
    ACTION_NOTIFY: "통지",
}

# ── 상태 넷 ────────────────────────────────────────────────────────────────
STATE_DONE = "done"        # 했다 (건수 0 일 수도 있다 — 그것도 한 것이다)
STATE_SKIPPED = "skipped"  # ★시도하지 않았다★ — `done(0건)` 과 다른 사실
STATE_FAILED = "failed"    # 시도했고 실패했다
STATE_UNKNOWN = "unknown"  # 무엇을 했는지 기록이 없다 — ★한 것이 아니다★

ACTION_STATES = (STATE_DONE, STATE_SKIPPED, STATE_FAILED, STATE_UNKNOWN)

#: 관측 축의 상태. ★값이 없는 것과 값이 0 인 것은 다르다.★
OBSERVED = "observed"
UNOBSERVED = "unknown"

_NO_REASON = ("조치 {0!r} 의 상태가 {1!r} 인데 사유가 없습니다 — "
              "★하지 않은 일에는 왜 하지 않았는지가 함께 와야 합니다.★")

_SUMMARY_CLEARED = "발동이 조치 넷을 모두 수행했습니다: "
_SUMMARY_NOTE = (
    "이 목록은 ★이 발동이 무엇을 했는가★만 말합니다. ★포지션이 정리됐다는 "
    "뜻이 아닙니다★ — `skipped` 는 그 조치를 ★시도하지 않았다★는 뜻이고, "
    "`done` 이어도 `gradual` 청산은 일부만 팝니다. 신규 주문 차단만이 발동 "
    "즉시 구조적으로 참입니다.")
_EMPTY_SUMMARY = "조치 기록이 없습니다 — ★무엇을 했는지 알 수 없습니다.★"


@dataclass(frozen=True)
class ActionRecord:
    """조치 하나의 결과. ★동결★ — 나중에 상태를 고쳐 기록을 바꾸지 못하게."""

    action: str
    state: str
    reason: str | None = None
    detail: dict | None = None

    def __post_init__(self) -> None:
        if self.action not in KILL_ACTIONS:
            raise ValueError(
                f"알 수 없는 조치 {self.action!r} — 허용: {list(KILL_ACTIONS)}")
        if self.state not in ACTION_STATES:
            raise ValueError(
                f"알 수 없는 조치 상태 {self.state!r} — 허용: {list(ACTION_STATES)}")
        # ★사유 없는 미상·건너뜀·실패는 **생성 자체가 불가능**하다★ (AD1 선례)
        if self.state != STATE_DONE and not self.reason:
            raise ValueError(_NO_REASON.format(self.action, self.state))

    def to_dict(self) -> dict[str, Any]:
        return {"action": self.action, "label": ACTION_LABELS[self.action],
                "state": self.state, "reason": self.reason,
                "detail": self.detail}


def observation_state(value: Any) -> str:
    """이 값이 **관측인가 미상인가**. ★잰 0 은 관측이다★

    문제는 *"안 실은 `0`"* 이지 *"재서 나온 `0`"* 이 아니다. 그래서 `0.0` 은
    `observed` 이고 `None`·`NaN`·`inf`·숫자가 아닌 것이 `unknown` 이다.
    `bool` 은 숫자가 아니다(파이썬에서 `True` 는 `int` 의 하위형이라 명시로 막는다).
    """
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return UNOBSERVED
    return OBSERVED if math.isfinite(float(value)) else UNOBSERVED


def _text_state(value: Any) -> str:
    return OBSERVED if isinstance(value, str) and value.strip() else UNOBSERVED


def observations(*, equity_krw: Any, dd_pct: Any, regime: Any) -> dict[str, Any]:
    """발동 시점의 관측 셋. ★값과 그 값을 어떻게 알았나를 함께 낸다★ (AM 규율)

    호출부가 값을 **안 실었을 때** 그 사실이 남아야 한다 — 남지 않으면 기본값
    `0` 이 관측 행세를 한다.
    """
    axes = {
        "equity_krw": {"value": equity_krw, "state": observation_state(equity_krw)},
        "dd_pct": {"value": dd_pct, "state": observation_state(dd_pct)},
        "regime": {"value": regime, "state": _text_state(regime)},
    }
    return {**axes,
            "any_unobserved": any(a["state"] == UNOBSERVED for a in axes.values())}


def unknown_actions(reason: str) -> list[ActionRecord]:
    """조치 기록이 없는 사건(=이 어휘 이전에 쓰인 행)의 넷. ★소급하지 않는다★"""
    return [ActionRecord(action=a, state=STATE_UNKNOWN, reason=reason)
            for a in KILL_ACTIONS]


def action_rollup(records: list[ActionRecord] | tuple[ActionRecord, ...]
                  ) -> dict[str, Any]:
    """조치들 → 한 판정. ★빠진 조치는 사라지지 않고 `unknown` 이 된다★

    Returns:
        `{done, skipped, failed, unknown, records, cleared, summary, note}`
    """
    by_state: dict[str, list[str]] = {s: [] for s in ACTION_STATES}
    seen: set[str] = set()
    for rec in records:
        by_state[rec.state].append(rec.action)
        seen.add(rec.action)

    # ★적지 않은 조치를 "안 해도 되는 것" 으로 읽지 않는다★
    for action in KILL_ACTIONS:
        if action not in seen:
            by_state[STATE_UNKNOWN].append(action)

    cleared = by_state[STATE_DONE] and not (
        by_state[STATE_SKIPPED] or by_state[STATE_FAILED] or by_state[STATE_UNKNOWN])

    if cleared:
        summary = _SUMMARY_CLEARED + " · ".join(
            ACTION_LABELS[a] for a in by_state[STATE_DONE])
    elif not records:
        summary = _EMPTY_SUMMARY
    else:
        bits = []
        for state, word in ((STATE_SKIPPED, "건너뜀"), (STATE_FAILED, "실패"),
                            (STATE_UNKNOWN, "미상")):
            if by_state[state]:
                bits.append(word + " " + " · ".join(
                    ACTION_LABELS[a] for a in by_state[state]))
        summary = " / ".join(bits)

    return {
        "done": by_state[STATE_DONE],
        "skipped": by_state[STATE_SKIPPED],
        "failed": by_state[STATE_FAILED],
        "unknown": by_state[STATE_UNKNOWN],
        "records": [r.to_dict() for r in records],
        "cleared": bool(cleared),
        "summary": summary,
        "note": _SUMMARY_NOTE,
    }
