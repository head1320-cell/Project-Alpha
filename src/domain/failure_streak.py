"""연속 실패의 구성 — ★다섯 회가 무엇이었나★ (AT1)
==============================================================================
종류 어휘 `src/domain/kis_failure.py`(AR) · 관측 `src/domain/api_health.py`(AQ)
· 기록하는 곳 `kis_client.CircuitBreaker`(AT2) · 뜻의 표 `kis_rt_cd.py`(AS)

## 왜 이 모듈이 생겼나

`auto_api` 는 *"KIS API 연속 실패 (5회)"* 로 킬스위치를 겨냥한다. AR 이 드러낸
대로 그 5회에는 ★장 종료 같은 정상 업무 응답이 섞여 들어간다★ — `_request` 가
`rt_cd != "0"` 에서도 `record_failure()` 를 부르기 때문이다. 5회가 전부 업무
응답이었다면 그 발동은 틀린 진단이고, ★판정 자리에서는 그것을 알 수 없었다.★

실측(2026-09-21): `record_failure()` 는 인자를 받지 않아 breaker 가 눈먼 채로
세고, 종류는 `last_failure_kind` 한 칸뿐이며, 감사 로그는 `_request` 의 7개
호출부 중 주문·취소 둘만 본다. 그래서 ★구성은 기존 기록으로 재구성할 수 없다.★

## ★이 모듈이 지키는 두 가지★

1. **구성이 그 숫자를 설명하지 못하면 그렇게 말한다.** 기록한 개수와 센 개수가
   다르면 다른 집합을 설명하고 있는 것이고, 조용히 내면 *"5회 중 3회가 업무
   응답"* 이라는 틀린 비율이 만들어진다.
2. **빈 것에 대해 전칭을 주장하지 않는다.** 파이썬에서 `all([])` 은 `True` 라,
   ★0회 중 0회가 업무 응답★ 이 "전부 업무 응답" 으로 읽힌다 — 아무 일도 없는
   상태가 가장 강한 주장이 되어 버린다.

## ★이 모듈이 주장하지 않는 것★

- **책임 소재를 말하지 않는다.** `business` 의 뜻은 여전히 미상이다 — AS 가
  표의 자리를 만들었지만 그 표는 비어 있다(이 환경은 KIS 에 닿지 못한다).
  구성은 *"무엇이 몇 번"* 이지 *"누구 탓"* 이 아니고, 그래서 이 모듈은
  `kis_rt_cd` 를 임포트하지 않는다(AST 테스트가 지킨다).
- **발동해야 하는지 말하지 않는다.** 판정은 `should_auto_trigger` 가 하고,
  여기서 만드는 것은 그 옆에 붙는 문장뿐이다. ★임계값도 세는 것도 건드리지
  않는다★ — 그것은 실거래 호출 경로 동작 변경이라 별도 승인 사항이다.
"""
from __future__ import annotations

from typing import Any

from src.domain.kis_failure import (
    FAILURE_KINDS,
    KIND_BUSINESS,
    KIND_LABELS,
    KIND_UNKNOWN,
    counts_toward_breaker,
)

#: 센 개수를 모를 때. ★미상 ≠ 일치★ — 셀 수 없었던 것을 "맞다" 로 읽지 않는다.
STREAK_UNKNOWN_REASON = (
    "연속 실패 횟수를 읽지 못해 이 구성이 그 숫자를 설명하는지 알 수 "
    "없습니다 — 미상은 일치가 아닙니다.")

_MISMATCH_REASON = (
    "기록한 종류의 개수({recorded})가 센 횟수({count})와 다릅니다 — 이 구성은 "
    "★그 숫자를 설명하지 않습니다★. 링이 넘쳤거나 카운터가 따로 움직였습니다.")

_NOTE = (
    "구성은 ★무엇이 몇 번★ 일어났는지만 말합니다. 업무 응답이 많다는 것이 "
    "곧 주문 거절이라는 뜻은 아닙니다 — 이 저장소에는 rt_cd 를 뜻으로 옮기는 "
    "표가 없습니다. 그리고 이 구성은 발동 여부를 정하지 않습니다.")


def _normalize(kinds: Any) -> list[str]:
    """어휘 밖의 값은 ★버리지도 믿지도 않는다★ — 미상으로 남긴다."""
    return [k if k in FAILURE_KINDS else KIND_UNKNOWN for k in (kinds or [])]


def streak_composition(kinds: Any, *, count: Any = None) -> dict[str, Any]:
    """연속 실패의 구성. ★순수★

    Args:
        kinds: 기록된 종류들(오래된 것부터). 어휘 밖의 값은 미상이 된다.
        count: breaker 가 센 횟수. `None` 이면 ★설명 여부가 미상★이다.
    """
    normalized = _normalize(kinds)
    by_kind: dict[str, int] = {}
    for kind in normalized:
        by_kind[kind] = by_kind.get(kind, 0) + 1

    n = len(normalized)
    business_n = by_kind.get(KIND_BUSINESS, 0)

    # ★빈 것에 전칭을 주장하지 않는다★ — `all([])` 은 True 다.
    all_business = n > 0 and business_n == n

    dominant = None
    if by_kind:
        dominant = max(by_kind, key=lambda k: (by_kind[k], -FAILURE_KINDS.index(k)))

    if count is None:
        describes, reason = None, STREAK_UNKNOWN_REASON
    elif int(count) == n:
        describes, reason = True, None
    else:
        describes = False
        reason = _MISMATCH_REASON.format(recorded=n, count=count)

    return {
        "n_recorded": n,
        "count": None if count is None else int(count),
        "by_kind": by_kind,
        "labels": {k: KIND_LABELS[k] for k in by_kind},
        "dominant": dominant,
        "business_n": business_n,
        "all_business": all_business,
        # ★기술이지 정책이 아니다★ — 토큰 실패는 breaker 를 타지 않는다(AR).
        "counted_n": sum(v for k, v in by_kind.items() if counts_toward_breaker(k)),
        "describes_count": describes,
        "reason": reason,
        "note": _NOTE,
    }


def streak_phrase(composition: dict[str, Any]) -> str:
    """판정 사유 옆에 붙는 한 문장. ★비어 있는 법이 없다★

    `should_auto_trigger` 의 사유는 `live_kill_events` 에 그대로 저장되므로,
    ★여기서 말한 것이 곧 발동 기록에 남는다.★
    """
    describes = composition["describes_count"]
    n = composition["n_recorded"]

    if describes is not True:
        # ★설명하지 못하면 비율을 말하지 않는다★ — 틀린 비율이 만들어진다.
        return f" — 구성 미상({composition['reason']})"

    if n == 0:
        return " — 기록된 종류 없음"

    if composition["all_business"]:
        return (f" — {n}회가 전부 업무 응답(rt_cd 미검증), 뜻은 미상: "
                "이 발동이 옳은 진단인지 저장소는 모릅니다")

    parts = ", ".join(
        f"{composition['labels'][k]} {v}회"
        for k, v in sorted(composition["by_kind"].items(),
                           key=lambda kv: (-kv[1], kv[0])))
    business_n = composition["business_n"]
    if business_n:
        return (f" — {n}회 중 {parts}. 업무 응답 {business_n}회가 섞여 있고 "
                "그 뜻은 미상입니다")
    return f" — {n}회 중 {parts}"
