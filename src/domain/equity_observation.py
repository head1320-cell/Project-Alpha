"""에쿼티 관측 — ★이 숫자가 시장에서 왔나 지어낸 것인가★ (AI1)
==============================================================================
설계: `docs/plans` AI · 소비자 `src/execution/equity_history.py` ·
판정 `src/execution/drawdown.py::drawdown_from_history`

## 왜 이 모듈이 생겼나 — ★표도 리더도 있고 쓰는 코드만 없었다★

킬스위치의 자동 트리거 넷 중 둘(`auto_dd` 누적 -10% · `auto_cb` 일중 -5%)이
발동할 수 없는 이유는 하나였다: **에쿼티 이력이 비어 있다.**
`live_daily_pnl` 표도, `drawdown_from_history` 리더도, 보존정책도 다 있는데
★그 표에 쓰는 코드가 저장소에 없었다★(`drawdown.py:18` 이 스스로 그렇게 적어 뒀다).

## ★그런데 순진하게 쓰면 더 나빠진다★

`MockKISClient.get_balance()` 는 `self.cash` 와 mock 가격으로 만든 **완전 합성**
값이다(`kis_client.py:804`). 그것을 그대로 이력에 적으면 킬스위치가 **합성 숫자로
발동**한다 — CLAUDE.md §6 의 *"운영에서는 합성값을 만들지 않습니다"* 를 가장 위험한
자리에서 어기는 것이다. ★틀린 숫자는 `unknown` 보다 나쁘다.★

## ★두 축을 섞지 않는다★

    실행 모드(SHADOW/PAPER/LIVE)  ⟂  잔고 출처(브로커 조회 / mock 합성)

표에는 `execution_mode` 칸만 있었다. 그런데 SHADOW 로 돌면서 실제 잔고를 읽을 수도,
PAPER 로 돌면서 mock 을 읽을 수도 있다 — 모드만 보면 그 수치가 시장에서 온 것인지
알 수 없다. Z 의 `kind ⟂ data_real`, AA 의 `trigger ⟂ reason`, AG 의
`signal_lag ⟂ fill_type`, AH 의 `window ⟂ vintage` 와 같은 규율이다.

## ★기록 가능성 ≠ 사용 가능성★

mock 으로 돈 날도 **기록은 한다**. 안 쓰는 것이 아니라 라벨해서 쓴다 — 기록하지
않으면 *"그날 감시가 돌았는데 mock 이었다"* 는 사실 자체가 사라진다. 다만 그 행은
드로다운 **계열에는 들어가지 않는다**.

## ★이 모듈이 주장하지 않는 것★

- **브로커 값이 옳다고 말하지 않는다.** `broker` 는 *"브로커에서 조회했다"* 는
  출처 표기이지 평가액의 정확성에 대한 판단이 아니다.
- **킬스위치가 작동한다고 말하지 않는다** — 재는 것과 막는 것은 다르다.
"""
from __future__ import annotations

from dataclasses import dataclass

#: 브로커에서 **실제로 조회한** 잔고. ★드로다운 계열에 들어갈 수 있는 유일한 출처★
SOURCE_BROKER = "broker"
#: mock 클라이언트가 만든 합성 잔고. 기록은 하되 계열에는 못 들어간다.
SOURCE_MOCK = "mock"
#: 출처를 밝히지 못했다. ★통과가 아니다★ — `mock` 과도 다른 사실이다.
SOURCE_UNKNOWN = "unknown"

EQUITY_SOURCES = (SOURCE_BROKER, SOURCE_MOCK, SOURCE_UNKNOWN)

_MOCK_REASON = ("합성 잔고입니다(mock 클라이언트) — 시장에서 온 수치가 아니므로 "
                "드로다운 계열에 넣지 않습니다.")
_UNKNOWN_REASON = ("잔고 출처가 선언되지 않았습니다 — 브로커 조회인지 아닌지 알 수 "
                   "없어 드로다운 계열에 넣지 않습니다.")


@dataclass(frozen=True)
class EquityObservation:
    """하루 한 번의 에쿼티 관측. ★`None` 은 미상이지 0 이 아니다★"""

    trade_date: str | None = None
    execution_mode: str | None = None
    source: str | None = None
    starting_krw: float | None = None
    ending_krw: float | None = None
    reason: str | None = None

    def to_dict(self) -> dict:
        return {"trade_date": self.trade_date,
                "execution_mode": self.execution_mode,
                "source": self.source,
                "starting_krw": self.starting_krw,
                "ending_krw": self.ending_krw}


def usable_for_drawdown(source: str | None) -> bool:
    """이 출처의 행을 드로다운 계열에 넣어도 되나. ★`broker` 만 참★

    ★관대하게 보지 않는다★ — `"BROKER"`·`"broker "`·`"real"` 은 전부 거짓이다.
    출처는 이 저장소가 직접 찍는 값이라 표기가 흔들릴 이유가 없고, 흔들린다면
    그것 자체가 조사할 일이지 통과시킬 일이 아니다.
    """
    return source == SOURCE_BROKER


def source_reason(source: str | None) -> str | None:
    """왜 계열에 못 넣는가. ★`mock` 과 `unknown` 을 같은 문장으로 적지 않는다★"""
    if source == SOURCE_BROKER:
        return None
    if source == SOURCE_MOCK:
        return _MOCK_REASON
    return _UNKNOWN_REASON


def observation_label(obs: EquityObservation) -> dict:
    """관측 → 출처 판정과 사유. ★수치는 출처와 무관하게 실린다★"""
    return {
        "usable": usable_for_drawdown(obs.source),
        "reason": obs.reason or source_reason(obs.source),
        **obs.to_dict(),
    }
