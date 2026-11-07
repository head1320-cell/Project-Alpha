"""실행 가정 — ★이 백테스트의 결정을 장 시작 전에 계산할 수 있었나★ (AG1)
==============================================================================
설계: `docs/plans` AG · 채점표 `docs/specs/2026-09-12-addendum-scorecard.md` #4

## 왜 이 모듈이 생겼나 — ★저장소가 자기 기준을 어기고 있었다★

`src/engine/fill_price.py:166` 이 이동평균 체결가에서 당일을 빼며 이유를 적어 뒀다:

    이동평균류 — 전일까지 N일 종가 평균
    (당일 제외: **주문가는 장 시작 전 계산 가능해야**).

그런데 백테스트 엔진의 기본값은 그 원칙을 깼다:

    signal_lag: int = 0        # 신호가 **당일 봉**(종가 포함)에서 나온다
    buy_fill_type = "close"    # 체결도 **당일 종가**

오늘의 종가를 보고 판단해서 그 종가에 체결한다 — ★종가가 확정되기 전에는 그 신호를
계산할 수 없으므로 그 주문은 낼 수 없다.★ 한 봉치 정보의 룩어헤드이고, 그만큼
성과가 좋게 나온다.

## ★불변식은 하나다★

    signal_lag >= 1  ⟺  결정이 장 시작 전 계산 가능

체결가 유형은 **별개 축**이라 판정에 넣지 않는다. `lag=0` 이면 체결가가 `prev_close`
여도 **결정 자체**가 계산되지 않는다(신호가 당일 종가를 쓴다). 둘을 섞으면 Z 에서
`kind ⟂ data_real` 을, AA 에서 `trigger ⟂ decision reason` 을 가른 규율을 어긴다.

## ★`lag=0` 을 금지하지 않는다★

연구 목적으로 당일 봉 신호를 보고 싶을 수 있다. 막지 않고 **결과가 `same_bar` 라고
말하게** 한다 — CLAUDE.md §5 의 *"금지가 아니라 순서입니다"*.

## ★미상을 0 으로 적지 않는다★

`signal_lag` 이 실행 기록에 남기 시작한 것은 AG 부터다. 그 이전 런은 0 이었는지 더
컸는지 **알 수 없다**(스크리너 라우트가 그 값을 요청 필드로 받아 왔다). 그래서
`None` 은 `STATE_UNRECORDED` 이고, `decision_precomputable(None)` 은 `None` 이다 —
`False` 로 접으면 "룩어헤드가 있었다" 는 없는 사실이 생기고, `True` 로 접으면
"깨끗했다" 는 없는 사실이 생긴다.
"""
from __future__ import annotations

from dataclasses import dataclass

#: ★기본 신호 시차 — 단일 출처★
#: 엔진·라우트의 선언 지점이 전부 이 상수를 읽는다. 예전에는 세 곳에 `0` 이 따로
#: 박혀 있어 서로 갈릴 수 있었다.
SIGNAL_LAG_DEFAULT = 1

#: 결정이 장 시작 전에 계산 가능하다(`signal_lag >= 1`).
STATE_PRECOMPUTABLE = "precomputable"
#: 당일 봉으로 판단하고 당일 체결한다(`signal_lag == 0`). 금지는 아니지만 룩어헤드다.
STATE_SAME_BAR = "same_bar"
#: 기록이 없다. ★통과가 아니다★
STATE_UNRECORDED = "unrecorded"

ASSUMPTION_STATES = (STATE_PRECOMPUTABLE, STATE_SAME_BAR, STATE_UNRECORDED)

UNRECORDED_REASON = (
    "이 실행에는 signal_lag 이 기록되지 않았습니다 — 0(당일 봉 신호)이었는지 "
    "그보다 컸는지 알 수 없습니다. 실행 가정을 기록하기 이전의 런입니다."
)

SAME_BAR_REASON = (
    "신호가 당일 봉(종가 포함)에서 나오고 체결도 당일입니다 — 종가가 확정되기 "
    "전에는 이 신호를 계산할 수 없으므로 장 시작 전에 낼 수 있는 주문이 아닙니다."
)


@dataclass(frozen=True)
class ExecutionAssumption:
    """한 실행의 체결 가정. ★`signal_lag=None` 은 미상이다★"""

    signal_lag: int | None = None
    buy_fill_type: str | None = None
    sell_fill_type: str | None = None

    def to_dict(self) -> dict:
        return {"signal_lag": self.signal_lag,
                "buy_fill_type": self.buy_fill_type,
                "sell_fill_type": self.sell_fill_type}


def decision_precomputable(signal_lag: int | None) -> bool | None:
    """결정이 장 시작 전에 계산 가능한가. ★모르면 `None`★

    `True`/`False`/`None` 셋이고 마지막은 "재지 못했다" 다 — `run_evidence` 의
    `AXIS_UNKNOWN` 이 통과가 아닌 것과 같은 규율이다.
    """
    if signal_lag is None:
        return None
    return int(signal_lag) >= 1


def assumption_label(assumption: ExecutionAssumption) -> dict:
    """실행 가정 → 상태와 사유. ★체결가 유형은 실리되 판정을 바꾸지 않는다★"""
    verdict = decision_precomputable(assumption.signal_lag)
    if verdict is None:
        state, reason = STATE_UNRECORDED, UNRECORDED_REASON
    elif verdict:
        state, reason = STATE_PRECOMPUTABLE, None
    else:
        state, reason = STATE_SAME_BAR, SAME_BAR_REASON
    return {
        "state": state,
        "reason": reason,
        "precomputable_before_open": verdict,
        **assumption.to_dict(),
    }


def assumption_from_result(result: dict | None) -> dict:
    """저장된 실행 결과 → 실행 가정 라벨. ★블록이 없으면 미상이다★

    `backtest_runs.set_result()` 가 엔진 결과 dict 를 통째로 JSON 으로 넣으므로
    기록은 이 블록 하나로 끝난다 — 컬럼을 새로 붙이지 않았다. ★그리고 요청
    설정이 아니라 **엔진이 실제로 쓴 값**을 읽는다★: 클라이언트가 `signal_lag`
    을 안 보내면 요청 스냅샷에는 그 키가 아예 없고, 그것을 기록으로 삼았다면
    기본값으로 돈 런이 전부 미상이 되었을 것이다.

    블록이 없거나 `signal_lag` 이 비어 있으면 `STATE_UNRECORDED` 다 — ★`0` 으로
    읽으면 "당일 봉 신호였다" 는 없는 사실이 생긴다.★
    """
    block = (result or {}).get("execution_assumption")
    if not isinstance(block, dict):
        block = {}
    return assumption_label(ExecutionAssumption(
        signal_lag=block.get("signal_lag"),
        buy_fill_type=block.get("buy_fill_type"),
        sell_fill_type=block.get("sell_fill_type")))
