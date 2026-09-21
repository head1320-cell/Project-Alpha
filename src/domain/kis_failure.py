"""KIS 호출 실패의 종류 — ★차단 ≠ 실패 · 거절 ≠ 장애★ (AR1)
==============================================================================
소비자: `src/execution/kis_client.py`(`KISCallError`) ·
`src/execution/order_executor.py::_fail_order`(`reason_code`) ·
`src/execution/api_failure_probe.py`(관측 블록)
선례: `src/domain/rebalance_reason.py`(AA, 두 축) · `src/domain/api_health.py`(AQ)

## 왜 이 모듈이 생겼나

`KISClient._request` 는 실패를 **전부 같은 `RuntimeError`** 로 뭉갠다 — 예외
하위형이 하나도 없고, 메시지 문자열만 다르다. 그 결과:

    · `live_orders.reason_code` 가 무엇이 일어났든 언제나 `"api_error"` 다
      (★상수가 관측 행세를 한다★ — AL 의 `selection_effect=0`, AM 의 `"dev"`,
       AP 의 `dd_at_trigger=0` 과 같은 모양)
    · 정상 업무 응답(장 종료·잔고 부족)이 KIS 장애와 **같은 카운터**에 들어간다
    · breaker 가 스스로 막은 것(`OPEN`)도 "실패" 처럼 읽힌다

`api_health.py`(AQ)의 docstring 이 이 공백을 스스로 적어 두었다 — 이 모듈이 그
"별건" 이다.

## ★두 축을 섞지 않는다★

    kind   무엇이 일어났나   전송 · 비-2xx · 본문 깨짐 · 업무 응답 · 토큰 · 차단
    fault  누구의 문제인가   provider(KIS) · self(우리가 막았다) · unknown

## ★`rt_cd` 의 뜻을 이 저장소는 모른다★ — 이 모듈의 정직성 핵심

`rt_cd`/`msg_cd` 를 의미로 옮기는 표가 저장소 어디에도 없다(실측). 그러니
`"장 종료"` 같은 문구를 패턴 매칭해 *"이건 업무 거절이니 장애가 아니다"* 라고
단정하면, 확인한 적 없는 것을 주장하는 것이다. 그래서 `business` 의 책임 소재는
★`unknown`★ 이고 사유가 왜인지 적는다.

## ★이 모듈이 주장하지 않는 것★

- **어떤 실패를 세어야 하는지 말하지 않는다.** `COUNTED_BY_BREAKER` 는 지금
  `_request` 가 **실제로 세는 것의 기술**이지 그래야 한다는 주장이 아니다.
  바꾸는 것은 실거래 호출 경로 동작 변경이라 별도 승인 사항이다.
- **KIS 가 건강한지 말하지 않는다.** 종류에 이름을 줄 뿐이다.
"""
from __future__ import annotations

from typing import Any

# ── 축 ① — 무엇이 일어났나 (kind) ──────────────────────────────────────────
#: ★우리가 막았다★ — circuit breaker 가 `OPEN` 이라 호출 자체를 하지 않았다.
KIND_BLOCKED = "blocked"
#: 전송 계층 — 타임아웃 · 연결 실패 · SSL.
KIND_TRANSPORT = "transport"
#: 비-2xx 응답.
KIND_HTTP_STATUS = "http_status"
#: 본문이 JSON 이 아니다(게이트웨이 오류 페이지 등).
KIND_MALFORMED = "malformed"
#: HTTP 200 + `rt_cd != "0"` — ★업무 응답이고, 뜻은 이 저장소가 모른다★
KIND_BUSINESS = "business"
#: 토큰 발급 실패(`_fetch_token` — `_request` 를 타지 않는다).
KIND_TOKEN = "token"
#: 단서가 없다. ★모르는 것을 정상으로 읽지 않는다★
KIND_UNKNOWN = "unknown"

FAILURE_KINDS = (KIND_BLOCKED, KIND_TRANSPORT, KIND_HTTP_STATUS, KIND_MALFORMED,
                 KIND_BUSINESS, KIND_TOKEN, KIND_UNKNOWN)

KIND_LABELS = {
    KIND_BLOCKED: "차단 중(호출하지 않음)",
    KIND_TRANSPORT: "전송 오류",
    KIND_HTTP_STATUS: "비정상 HTTP 상태",
    KIND_MALFORMED: "응답 본문이 JSON 이 아님",
    KIND_BUSINESS: "업무 응답(rt_cd ≠ 0)",
    KIND_TOKEN: "토큰 발급 실패",
    KIND_UNKNOWN: "미상",
}

# ── 축 ② — 누구의 문제인가 (fault) ─────────────────────────────────────────
FAULT_PROVIDER = "provider"   # KIS 쪽
FAULT_SELF = "self"           # 우리가 스스로 막았다
FAULT_UNKNOWN = "unknown"     # ★단정하지 않는다★

FAULTS = (FAULT_PROVIDER, FAULT_SELF, FAULT_UNKNOWN)

#: 종류 → 책임 소재. ★총함수★ — 빠진 종류가 조용히 사라지지 않게.
KIND_FAULT = {
    KIND_BLOCKED: FAULT_SELF,
    KIND_TRANSPORT: FAULT_PROVIDER,
    KIND_HTTP_STATUS: FAULT_PROVIDER,
    KIND_MALFORMED: FAULT_PROVIDER,
    KIND_TOKEN: FAULT_PROVIDER,
    KIND_BUSINESS: FAULT_UNKNOWN,
    KIND_UNKNOWN: FAULT_UNKNOWN,
}

#: ★지금 `_request` 가 breaker 에 기록하는 종류★ — **기술이지 정책이 아니다.**
#: 실제 코드와의 대조는 `tests/test_kis_failure_wiring.py` 의 AST 검사가 한다.
COUNTED_BY_BREAKER = frozenset({KIND_TRANSPORT, KIND_BUSINESS})

_BUSINESS_FAULT_REASON = (
    "rt_cd 가 0 이 아니라는 것만 압니다 — 이 저장소에는 rt_cd 를 뜻으로 옮기는 "
    "표가 없어서, 주문 거절 같은 정상 업무 응답인지 KIS 쪽 장애인지 ★가릴 수 "
    "없습니다★. 문구를 보고 짐작하지 않습니다."
)
_UNKNOWN_FAULT_REASON = (
    "실패의 단서가 없어 책임 소재를 가릴 수 없습니다."
)
_SELF_FAULT_REASON = (
    "circuit breaker 가 열려 있어 호출 자체를 하지 않았습니다 — ★KIS 의 실패가 "
    "아니라 우리 쪽 차단입니다.★"
)

_NOTE = (
    "종류는 이 호출에서 무엇이 일어났는지만 말합니다. ★지금 circuit breaker 는 "
    "종류를 가리지 않습니다★ — 전송 오류와 업무 응답이 같은 카운터에 들어가므로, "
    "연속 실패 횟수가 임계에 닿았다고 해서 KIS 가 장애라는 뜻은 아닙니다. "
    "무엇을 셀지 바꾸는 것은 호출 경로 동작 변경이라 별도 승인 사항입니다."
)


def fault_of(kind: Any) -> str:
    """이 종류의 책임 소재. ★모르는 종류를 낙관하지 않는다★"""
    return KIND_FAULT.get(kind, FAULT_UNKNOWN)


def counts_toward_breaker(kind: Any) -> bool:
    """지금 이 종류가 breaker 카운터에 들어가는가. ★기술이다★"""
    return kind in COUNTED_BY_BREAKER


def fault_reason(kind: Any) -> str | None:
    """왜 책임 소재를 단정하지 않는가. ★단정할 수 있으면 `None`★"""
    fault = fault_of(kind)
    if fault == FAULT_PROVIDER:
        return None
    if fault == FAULT_SELF:
        return _SELF_FAULT_REASON
    return _BUSINESS_FAULT_REASON if kind == KIND_BUSINESS else _UNKNOWN_FAULT_REASON


def classify(*, blocked: bool = False, exception_name: str | None = None,
             status: Any = None, rt_cd: Any = None,
             json_ok: bool = True, token: bool = False) -> str:
    """단서 → 종류. ★호출 자체가 없었던 경우가 먼저다★

    Args:
        blocked: circuit breaker 가 거부했다 — 호출이 일어나지 않았다.
        exception_name: 전송 예외의 클래스 이름(`requests` 를 import 하지 않기
            위해 **이름만** 받는다 — 이 계층은 HTTP 를 알지 못한다).
        status: HTTP 상태 코드.
        rt_cd: KIS 업무 코드.
        json_ok: 본문을 JSON 으로 읽을 수 있었나.
        token: 토큰 발급 경로에서 난 실패인가.
    """
    if blocked:
        # ★차단이 다른 단서를 이긴다★ — 호출이 없었으므로 나머지는 의미가 없다.
        return KIND_BLOCKED
    if token:
        return KIND_TOKEN
    if exception_name:
        return KIND_TRANSPORT
    if not json_ok:
        return KIND_MALFORMED
    if rt_cd is not None and str(rt_cd) != "0":
        return KIND_BUSINESS
    if isinstance(status, int) and not 200 <= status < 300:
        return KIND_HTTP_STATUS
    return KIND_UNKNOWN


def failure_label(kind: Any, *, rt_cd: Any = None, status: Any = None,
                  msg: Any = None) -> dict[str, Any]:
    """종류 → 응답·기록에 싣는 블록. ★원자료를 함께 남긴다★"""
    k = kind if kind in FAILURE_KINDS else KIND_UNKNOWN
    return {
        "kind": k,
        "label": KIND_LABELS[k],
        "fault": fault_of(k),
        "fault_reason": fault_reason(k),
        "counted_by_breaker": counts_toward_breaker(k),
        "rt_cd": rt_cd,
        "status": status,
        "kis_msg": msg,
        "note": _NOTE,
    }
