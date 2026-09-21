"""KIS 연속 실패 프로브 — ★읽기만 한다. 세지도 만들지도 않는다★ (AQ2)
==============================================================================
어휘: `src/domain/api_health.py` · 소비자: `execution/order_executor._fetch_account_state`
      · `startup/lifecycle._monitor_account_state` → 킬스위치 `auto_api`

## 무엇을 하나

`kis_client.CircuitBreaker` 가 이미 유지하는 **연속 실패 횟수**를 읽어
`api_health.api_failure_observation` 이 쓰는 모양으로 옮긴다. ★세는 로직은 0줄★ —
`_request` 도 breaker 도 한 줄 바뀌지 않는다.

## ★`get_kis_client()` 를 부르지 않는 것이 이 모듈의 핵심이다★

부르면 **없던 클라이언트를 만든다.** 감시 루프(`_risk_monitor_bg`)가 그것을 부르면
*"감시는 주문을 내지 않으므로 실행기를 만들지 않는다"* 는 AI 의 경계가 깨진다 —
`_monitor_account_state` 의 docstring 이 그 경계를 적어 두었다. 그래서 여기서는
**이미 만들어진 싱글턴이 있으면 그것을 읽고, 없으면 `no_client` 로 말한다.**

★없는 것을 0 으로 적지 않는다★ — `no_client` 는 *"0 회 실패"* 가 아니라
*"재지 못했다"* 이고, 킬스위치는 그 둘을 다르게 다룬다(`is not None` 계약).

## ★이 모듈이 주장하지 않는 것★

- **KIS 가 건강하다고 말하지 않는다.** 숫자를 옮길 뿐이고, 그 숫자의 한계는
  `api_health` 의 `note` 가 적는다.
- **breaker 를 건드리지 않는다.** `record_*`·`call_allowed` 를 부르지 않는다 —
  읽는 쪽이 상태를 바꾸면 그 관측은 자기가 만든 것이 된다.
"""
from __future__ import annotations

import logging
from typing import Any

from src.domain.api_health import (
    BREAKER_CLOSED,
    BREAKER_HALF_OPEN,
    BREAKER_OPEN,
    BREAKER_UNKNOWN,
    SOURCE_BROKER,
    SOURCE_MOCK,
    SOURCE_NO_CLIENT,
    SOURCE_UNKNOWN,
    api_failure_observation,
)
from src.domain.kis_failure import failure_label
from src.domain.kis_rt_cd import enriched_label

logger = logging.getLogger(__name__)

#: `CircuitBreaker.state` 의 표기 → 이 저장소의 어휘. ★모르는 값은 낙관하지 않는다★
_BREAKER_STATE_MAP = {
    "CLOSED": BREAKER_CLOSED,
    "OPEN": BREAKER_OPEN,
    "HALF_OPEN": BREAKER_HALF_OPEN,
}

_PROBE_FAILED = "KIS 실패 횟수를 읽지 못했습니다: {}"


def _last_failure(target: Any) -> dict | None:
    """마지막 실패의 **종류**. ★없으면 지어내지 않는다★ (AR4)

    두 어휘를 잇는 자리다 — `api_health`(관측 출처)는 도메인이고
    `kis_failure`(실패 종류)도 도메인이라, 둘을 섞지 않고 **실행 계층**이 합친다.
    """
    kind = getattr(target, "last_failure_kind", None)
    if not kind:
        return None
    label = failure_label(kind,
                          rt_cd=getattr(target, "last_failure_rt_cd", None),
                          msg_cd=getattr(target, "last_failure_msg_cd", None),
                          status=getattr(target, "last_failure_status", None))
    # ★표가 표면에 닿는다★(AS) — 오늘은 표가 비어 있어 아무것도 바뀌지 않고,
    # 채워지면 같은 자리가 책임 소재를 말한다. ★아무도 안 부르는 계약은 계약이
    # 아니다★ — 이 저장소에는 배선만 되고 소비되지 않는 모듈 선례가 있다.
    return enriched_label(label)


def _singleton() -> Any:
    """이미 만들어진 클라이언트만 본다. ★만들지 않는다★

    모듈 속성을 직접 읽는 이유가 이것이다 — `get_kis_client()` 는 없으면
    **만들어 준다**(`kis_client.py` 의 싱글턴 팩토리).
    """
    try:
        import src.execution.kis_client as kc
        return getattr(kc, "_kis_singleton", None)
    except Exception as e:                                   # noqa: BLE001
        logger.debug(f"KIS 싱글턴 조회 실패: {e}")
        return None


def probe(client: Any = None) -> dict[str, Any]:
    """KIS 연속 실패 관측. ★못 재면 숫자 대신 사유★

    Args:
        client: 읽을 클라이언트. 생략하면 **이미 만들어진** 싱글턴을 본다.

    Returns:
        `api_health.api_failure_observation(...)` 의 모양.
    """
    target = client if client is not None else _singleton()
    if target is None:
        return {**api_failure_observation(count=None,
                                          breaker_state=BREAKER_UNKNOWN,
                                          source=SOURCE_NO_CLIENT),
                "last_failure": None}
    try:
        breaker = getattr(target, "circuit_breaker", None)
        if breaker is None:
            # ★mock 클라이언트에는 breaker 가 없다★ — 합성 호출의 실패는
            # 실패가 아니므로, 여기서 0 을 만들지 않는다.
            return {**api_failure_observation(count=None,
                                              breaker_state=BREAKER_UNKNOWN,
                                              source=SOURCE_MOCK),
                    "last_failure": _last_failure(target)}
        raw_state = getattr(breaker, "state", None)
        return {**api_failure_observation(
            count=getattr(breaker, "failure_count", None),
            breaker_state=_BREAKER_STATE_MAP.get(str(raw_state), BREAKER_UNKNOWN),
            source=SOURCE_BROKER,
        ), "last_failure": _last_failure(target)}
    except Exception as e:                                   # noqa: BLE001
        # ★삼키되 사유를 남긴다★ — 사유 없는 미상은 금지(CLAUDE.md §4).
        return {**api_failure_observation(count=None,
                                          breaker_state=BREAKER_UNKNOWN,
                                          source=SOURCE_UNKNOWN,
                                          reason=_PROBE_FAILED.format(e)),
                "last_failure": None}


def observe_into(state: dict, client: Any = None) -> dict:
    """관측을 `account_state` 에 싣는다. ★관측일 때만 숫자 키를 만든다★

    두 생산자(`order_executor._fetch_account_state` ·
    `startup/lifecycle._monitor_account_state`)가 **같은 함수**를 쓴다 — 두 벌로
    만들면 한쪽만 고쳐도 아무 테스트가 깨지지 않고, 경로에 따라 다른 사실이 보인다.

    ★미상일 때 `api_failure_count` 를 0 으로 채우지 않는다★ — 킬스위치는 키가
    없는 것(미상)과 측정된 `0` 을 **다르게** 다룬다(`is not None` 계약, AF2).
    채우는 순간 그 계약이 조용히 무너지고, `auto_api` 가 "무장됨" 으로 보인다.
    재지 못했다는 사실 자체는 `api_failure_observation` 블록이 사유와 함께 남긴다.
    """
    obs = probe(client)
    state["api_failure_observation"] = obs
    if obs["count"] is not None:
        state["api_failure_count"] = obs["count"]
    return state
