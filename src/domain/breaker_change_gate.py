"""업무 응답을 breaker 에서 뺄 수 있는가 — ★결정을 산문이 아니라 문으로★ (AU)
==============================================================================
선례 `src/domain/distribution_gate.py`(같은 `state`/`reason` 관용구) · 표
`src/domain/kis_rt_cd.py`(AS) · 종류 `src/domain/kis_failure.py`(AR) ·
구성 `src/domain/failure_streak.py`(AT)

## 왜 이 모듈이 생겼나

AR 이 드러낸 안전 역전이 네 프로그램째 살아 있다: `_request` 가
`rt_cd != "0"` 에서도 `record_failure()` 를 부르므로 정상 업무 응답이 KIS
장애와 **같은 breaker 카운터**에 들어가고, 5회면 `auto_api` 가 킬스위치를
겨냥한다. HISTORY 에 *"바꾸지 않았다"* 고 적은 것이 벌써 네 번이고,
★산문은 내일 누군가 그냥 바꿔도 아무것도 깨지지 않는다.★

그래서 이번에는 **통과해야 하는 문**을 남긴다. 조건을 이름 붙여 재고, 오늘은
막고, ★조건을 채우면 실제로 열린다★(그래야 항상-거부가 아니다).

## ★질문이 잘못 놓여 있었다 — 판정 단위는 코드다★

"업무 응답을 빼자" 는 **종류 단위** 질문인데, `business` 는 의미가 아니라
**모양**(HTTP 200 + `rt_cd != "0"`)이다. 그 안에 장 종료(안전 문제가 아니다)와
KIS 내부 오류(진짜 장애)가 섞여 있을 수 있으므로 ★종류 통째로 빼면 그 안의
진짜 장애까지 같이 빠진다★. 그래서 `(rt_cd, msg_cd)` 하나하나를 본다.

부수효과로 ★AS 의 빈 표가 왜 중요한지가 기계적으로 증명된다★ — 표가 비어
있으면 어느 코드도 이 문을 통과하지 못한다.

## ★어휘가 모자란다는 것도 실측이다 — `outage` 를 따로 쓰는 이유★

AR 의 책임 소재 축은 `provider`·`self`·`unknown` 셋인데, 장 종료의 정직한
답은 **아무의 문제도 아니다** 이고 그런 값이 없다. `self` 로 우겨 넣는 것은
어휘를 비트는 일이라, 증거 파일의 목적 전용 칸 `outage`(이 코드가 KIS 장애를
뜻하는가)를 쓴다. ★`fault` 는 이 판정과 무관하다★ — AR 의 축은 건드리지
않는다(네 번째 값을 더하는 것은 별건이다).

## ★이 모듈이 하지 않는 것★

- **breaker 가 무엇을 세는지 바꾸지 않는다.** 이 문은 `_request` 에도
  `COUNTED_BY_BREAKER` 에도 연결되지 않는다 — 판정을 **말할** 뿐이다.
  실제로 빼는 것은 실거래 호출 경로 동작 변경이라 별도 승인 사항이다(§6).
- **표를 채우지 않는다.** 뜻은 사람이 KIS 문서를 보고 적는다.
- **`msg1` 을 해석하지 않는다.** 문구 패턴 매칭은 어휘로 거는 일이다.
"""
from __future__ import annotations

from typing import Any

from src.domain.kis_rt_cd import code_key, meaning_of

#: 이 코드를 세지 않아도 된다.
CHANGE_ALLOWED = "allowed"
#: 세는 것을 바꿀 수 없다. ★기본값.★
CHANGE_BLOCKED = "blocked"

COND_MEANING = "meaning"
COND_NOT_OUTAGE = "not_outage"
COND_OBSERVED = "observed"
COND_REAL_SOURCE = "real_source"

#: ★넷이 **전부** 충족돼야 한다★ (`distribution_gate.LICENSE_FIELDS` 와 같은 모양)
CONDITIONS = (COND_MEANING, COND_NOT_OUTAGE, COND_OBSERVED, COND_REAL_SOURCE)

CONDITION_LABELS = {
    COND_MEANING: "뜻이 표에 있고 적용 등급 이상",
    COND_NOT_OUTAGE: "KIS 장애를 뜻하지 않는다고 표가 말한다",
    COND_OBSERVED: "실제로 충분히 관측됐다",
    COND_REAL_SOURCE: "그 관측이 합성이 아니다",
}

#: 관측 최소 횟수. ★기술이지 진리가 아니다★ — 한두 번 본 코드를 면제하면
#: 표본이 없는 판단이 된다. 바꾸려면 근거를 함께 적을 것.
MIN_OBSERVATIONS = 20

#: 합성으로 보는 실행 모드. ★모르는 모드도 합성으로 친다★ — 실제라고 확인한
#: 적이 없는 것을 실제로 세면 mock 관측이 증거 행세를 한다.
REAL_MODES = ("live", "paper")

_NO_MEANING = (
    "이 코드의 뜻이 표에 없거나 증거 등급이 적용선에 못 미칩니다 — 무엇을 "
    "빼는지 모르는 채로 뺄 수는 없습니다. 표를 채우려면 KIS 문서나 실계좌 "
    "응답이 필요하고, 그것은 코드로 답할 수 없습니다.")

_OUTAGE_UNKNOWN = (
    "이 코드가 KIS 장애를 뜻하는지 표가 말하지 않습니다(outage 미상). "
    "★미상은 통과가 아닙니다★ — 장애를 뜻하는 코드를 세지 않으면 안전장치를 "
    "끄는 것이 됩니다.")

_OUTAGE_TRUE = (
    "표가 이 코드를 KIS 장애로 적었습니다 — ★세는 것이 이 코드의 목적입니다★. "
    "빼면 진짜 장애를 놓칩니다.")

_TOO_FEW = (
    "관측이 모자랍니다(최소 {need}회). 한두 번 본 코드를 면제하면 표본이 없는 "
    "판단이 됩니다.")

_NOT_REAL = (
    "이 관측이 실계좌·모의계좌에서 온 것이라고 확인되지 않았습니다 — "
    "합성 관측은 증거가 아닙니다. 참고로 MockKISClient 에는 circuit breaker 가 "
    "아예 없어 mock 에서는 이 조건을 채울 수 없습니다.")

_LEDGER_LIMIT = (
    "관측은 감사 로그에서 옵니다. ★그 원장은 KIS 호출 7개 자리 중 주문·취소 "
    "둘만 봅니다★ — 잔고·시세에서만 나오는 코드는 이 조건을 채울 수 없고, "
    "그것은 코드가 안전하다는 뜻이 아니라 재지 못했다는 뜻입니다.")

_SUMMARY_BLOCKED = (
    "업무 응답을 breaker 카운트에서 빼는 변경은 막혀 있습니다. 통과한 코드가 "
    "하나도 없거나 일부뿐입니다 — ★일부만 통과한 것은 통과가 아닙니다★.")

_NOTE = (
    "이 문은 ★말할 뿐 막지 않습니다★ — breaker 는 지금도 업무 응답을 세고 "
    "있고, 실제로 빼는 것은 실거래 호출 경로 동작 변경이라 별도 승인 "
    "사항입니다. 판정 단위가 코드 하나하나인 이유는 business 가 의미가 아니라 "
    "모양이기 때문입니다 — 종류 통째로 빼면 그 안의 진짜 장애까지 빠집니다.")


def _condition(met: bool, reason: str | None) -> dict[str, Any]:
    return {"met": met, "reason": None if met else reason}


def _observed_count(observation: Any) -> int:
    if not isinstance(observation, dict):
        return 0
    try:
        return max(0, int(observation.get("count") or 0))
    except (TypeError, ValueError):
        return 0


def _observed_mode(observation: Any) -> str | None:
    if not isinstance(observation, dict):
        return None
    mode = observation.get("execution_mode")
    return str(mode).strip() if mode else None


def may_stop_counting(rt_cd: Any, msg_cd: Any, *,
                      observation: Any = None) -> dict[str, Any]:
    """이 코드를 breaker 카운트에서 빼도 되는가. ★기본은 언제나 막힘★

    Args:
        rt_cd: KIS 응답의 `rt_cd`.
        msg_cd: KIS 응답의 `msg_cd`. ★없으면 어느 코드인지 모른다★.
        observation: `kis_rt_cd.fold_observations` 가 낸 관측 하나
            (`count`·`execution_mode`). 없으면 관측 조건이 미충족이다.

    Returns:
        `state` (allowed|blocked) · `reason` · `unmet`(못 채운 조건 이름) ·
        `conditions`(조건별 충족 여부와 사유) · `key` · `note`.
    """
    known = meaning_of(rt_cd, msg_cd)
    outage = known.get("outage") if isinstance(known, dict) else None
    count = _observed_count(observation)
    mode = _observed_mode(observation)

    conditions = {
        COND_MEANING: _condition(known is not None, _NO_MEANING),
        # ★`False` 여야 한다 — `None`(미상)도 `True`(장애)도 막는다★
        COND_NOT_OUTAGE: _condition(
            outage is False,
            _OUTAGE_TRUE if outage is True else _OUTAGE_UNKNOWN),
        COND_OBSERVED: _condition(
            count >= MIN_OBSERVATIONS,
            _TOO_FEW.format(need=MIN_OBSERVATIONS) + " " + _LEDGER_LIMIT),
        COND_REAL_SOURCE: _condition(mode in REAL_MODES, _NOT_REAL),
    }

    unmet = [name for name in CONDITIONS if not conditions[name]["met"]]
    key = code_key(rt_cd, msg_cd)
    if unmet:
        # ★무엇이 빠졌는지 말한다★ — 막힌 사람이 무엇을 해야 하는지 모르면
        #   그 거부는 절반만 정직하다(`distribution_gate` 의 관용구).
        missing = ", ".join(CONDITION_LABELS[name] for name in unmet)
        return {
            "state": CHANGE_BLOCKED,
            "reason": f"{key}: 충족되지 않은 조건 — {missing}",
            "unmet": unmet,
            "conditions": conditions,
            "key": key,
            "note": _NOTE,
        }

    return {
        "state": CHANGE_ALLOWED,
        "reason": None,
        "unmet": [],
        "conditions": conditions,
        "key": key,
        "note": _NOTE,
    }


def gate_summary(observations: Any = None) -> dict[str, Any]:
    """관측된 코드 전체에 대한 판정. ★일부만 통과한 것은 통과가 아니다★

    ★빈 표에서 전칭을 주장하지 않는다★ — 파이썬에서 `all([])` 은 `True` 라,
    아무 코드도 없는 상태가 "전부 통과" 로 읽히면 아무 일도 없는 것이 가장
    강한 주장이 된다(AT 에서 같은 함정을 만났다).
    """
    allowed: list[dict] = []
    blocked: list[dict] = []
    for item in observations or []:
        if not isinstance(item, dict):
            continue
        verdict = may_stop_counting(item.get("rt_cd"), item.get("msg_cd"),
                                    observation=item)
        (allowed if verdict["state"] == CHANGE_ALLOWED else blocked).append(verdict)

    everything_passed = bool(allowed) and not blocked
    return {
        "state": CHANGE_ALLOWED if everything_passed else CHANGE_BLOCKED,
        "reason": None if everything_passed else _SUMMARY_BLOCKED,
        "n_allowed": len(allowed),
        "n_blocked": len(blocked),
        "allowed_codes": allowed,
        "blocked_codes": blocked,
        "conditions": list(CONDITIONS),
        "min_observations": MIN_OBSERVATIONS,
        "note": _NOTE,
    }
