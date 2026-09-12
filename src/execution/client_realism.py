"""브로커 클라이언트가 ★모의인가 실거래인가★ (Y1-①)
==============================================================================
소비자: `src/execution/order_executor.py::_execute_paper`

## 왜 이 모듈이 생겼나

`ExecutionMode.PAPER` 는 **이름이 보장하는 것이 아무것도 없었다**. `_execute_paper`
가 클라이언트를 확인하지 않고 `place_order` 를 불렀기 때문에, 세 가지 중 어느
클라이언트가 꽂혀 있느냐에 따라 결과가 갈렸다:

    MockKISClient                      가상 — 안전
    KISClient(creds.is_paper=True)     KIS 모의투자 엔드포인트 — 안전
    KISClient(creds.is_paper=False)    ★실거래 엔드포인트★

즉 `KIS_USE_MOCK=0` + `KIS_IS_PAPER=0` 이면 **PAPER 모드가 실주문을 냈다**.
CLAUDE.md §6 최우선 불변식(실거래 안전)과 정면으로 어긋난다.

## ★모르면 거부로 기운다★

판정할 수 없는 클라이언트를 "모의겠지" 로 읽지 않는다. 안전 판정에서 미상은
통과가 아니다(CLAUDE.md §4 `미상 ≠ 검증`). 새 어댑터가 생기면 **여기서 막히고**,
그것이 이 모듈이 원하는 동작이다 — 조용히 실주문이 나가는 것보다 낫다.

★이 모듈은 `LIVE` 를 건드리지 않는다★ — 그쪽은 `set_mode` 의 확인 토큰이 지킨다.
여기에 가드를 더하면 실거래가 영영 막힌다.
"""
from __future__ import annotations

#: 가상 클라이언트 — 브로커에 닿지 않는다.
REASON_MOCK = "mock_client"
#: 실 클라이언트지만 KIS **모의투자** 엔드포인트를 쓴다. PAPER 의 본래 뜻.
REASON_KIS_PAPER = "kis_paper_endpoint"
#: ★실거래 엔드포인트★ — PAPER 모드에서 부르면 진짜 돈이 나간다.
REASON_KIS_REAL = "kis_real_endpoint"
#: 판정 불가. ★거부로 기운다.★
REASON_UNKNOWN = "unknown_client"


def client_is_simulated(client) -> tuple[bool, str]:
    """`(모의인가, 사유)`. ★판정 불가는 `False`★ — 미상은 통과가 아니다."""
    if client is None:
        return False, f"{REASON_UNKNOWN}: None"

    # ① 가상 클라이언트 — 클래스 이름으로 본다(임포트 순환을 만들지 않는다).
    if type(client).__name__ == "MockKISClient":
        return True, REASON_MOCK

    # ② 실 클라이언트면 어느 엔드포인트인지가 유일한 판정 근거다.
    creds = getattr(client, "creds", None)
    is_paper = getattr(creds, "is_paper", None)
    if is_paper is True:
        return True, REASON_KIS_PAPER
    if is_paper is False:
        return False, REASON_KIS_REAL

    # ③ 둘 다 아니다 — ★무엇을 못 알아봤는지 말하고 거부한다★
    return False, f"{REASON_UNKNOWN}: {type(client).__name__}"
