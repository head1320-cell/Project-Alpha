"""팩터 과거 미리보기 — 값 / 임계 / 3-상태 / 상태전환 횟수 (스펙 §8.1 요구 4, Phase 6b-2).

왜 별도 모듈인가
──────────────────────────────────────────────────────────────────────────────
`timing_factors.evaluate()` 는 **현재값 스칼라 하나**를 준다. 미리보기는 시계열이 필요하고,
그 시계열은 각 점을 **그 시점에 알 수 있었던 데이터만으로** 채점해야 한다. 그러지 않으면
미리보기는 "실제로는 불가능했던 판단" 을 그럴듯하게 보여주는 장치가 된다 — Phase 1 이 매크로
쪽에서 막은 룩어헤드를 UI 에서 되살리는 셈이다.

★새 절단 장치를 만들지 않는다★
`etf_prices.as_of(months_back)` 가 이미 스레드 로컬 시점 절단을 제공한다(월봉은 m개월,
일봉은 m×21봉을 가린다). 여기서는 그것을 감싸 쓰기만 한다.

정직하게 밝히는 한계
──────────────────────────────────────────────────────────────────────────────
· **표본 간격은 월**이다(`as_of` 가 월 단위). 일간 팩터의 상태전환 횟수는 실제보다
  **과소집계**된다 — 그 사실을 `limitations` 에 적어 UI 가 그대로 보여준다.
· 카나리 평가기로 값이 나오지 않는 팩터(`requires_as_of` · 평가 분기 없음)는 빈 그래프가
  아니라 **사유**를 반환한다. 빈 화면은 고장처럼 보이고, 사용자는 이유를 알 수 없다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from src.data.etf_prices import as_of
from src.engine.timing_factors import CATALOG_BY_ID, evaluate
from src.engine.timing_rules_v2 import (
    SignalState,
    direction_for,
    state_from_value,
    threshold_for,
)

logger = logging.getLogger(__name__)

#: 표본 간격 — as_of 가 월 단위 절단만 제공하므로 월이다.
STEP = "month"
MAX_MONTHS = 240


@dataclass(frozen=True)
class HistoryPoint:
    months_back: int
    value: float | None
    state: str

    def to_dict(self) -> dict:
        return {"months_back": self.months_back, "value": self.value, "state": self.state}


@dataclass(frozen=True)
class FactorHistory:
    factor_id: str
    ticker: str
    market: str
    threshold: float
    direction: str
    step: str
    points: list[HistoryPoint] = field(default_factory=list)
    state_changes: int = 0
    available_count: int = 0
    unavailable_count: int = 0
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "factor_id": self.factor_id, "ticker": self.ticker, "market": self.market,
            "threshold": self.threshold, "direction": self.direction, "step": self.step,
            "points": [p.to_dict() for p in self.points],
            "state_changes": self.state_changes,
            "available_count": self.available_count,
            "unavailable_count": self.unavailable_count,
            "limitations": list(self.limitations),
        }


def _empty(factor_id: str, ticker: str, market: str, reason: str) -> FactorHistory:
    """값을 만들 수 없을 때 — 빈 점 목록 + **사유**. 0 으로 채운 그래프를 그리지 않는다."""
    return FactorHistory(
        factor_id=factor_id, ticker=ticker, market=market,
        threshold=0.0, direction="above", step=STEP, limitations=[reason])


def count_state_flips(states: list[str]) -> int:
    """★결측을 건너뛰고 센다★

    결측을 하나의 상태로 취급하면 데이터 구멍 하나가 전환 2회로 집계되어, "신호가
    요동쳤다" 는 잘못된 인상을 준다. 결측은 신호가 뒤집힌 것이 아니라 알 수 없는 것이다.
    """
    seq = [s for s in states if s != SignalState.UNAVAILABLE.value]
    return sum(1 for a, b in zip(seq, seq[1:]) if a != b)


def factor_history(
    factor_id: str,
    ticker: str = "SPY",
    market: str = "kr",
    *,
    months: int = 24,
    params: dict | None = None,
    threshold: float | None = None,
    direction: str | None = None,
) -> FactorHistory:
    """`months` 개월 전부터 현재까지, 월 간격으로 팩터를 재평가한다.

    각 점은 `as_of(m)` 안에서 평가되므로 그 시점 이후의 시세를 보지 못한다.
    threshold/direction 을 넘기면 그 값으로 채점한다(창에서 사용자가 바꾼 설정 반영).
    """
    meta = CATALOG_BY_ID.get(factor_id)
    if meta is None:
        return _empty(factor_id, ticker, market,
                      f"카탈로그에 없는 팩터입니다: {factor_id}. 방향·임계를 추측하지 않습니다.")
    if meta.get("requires_as_of"):
        return _empty(
            factor_id, ticker, market,
            "이 팩터는 시점(as_of) 기준 매크로 빈티지로 평가합니다 — 카나리 평가기로는 "
            "값을 만들 수 없어 미리보기를 그리지 않습니다(빈 그래프 대신 사유를 표시).")

    thr = threshold if threshold is not None else (threshold_for(factor_id) or 0.0)
    dirn = direction or direction_for(factor_id) or "above"
    p = dict(params or meta.get("params") or {})
    span = max(1, min(int(months), MAX_MONTHS))

    limitations = [
        f"표본 간격은 **월**입니다(as_of 절단이 월 단위). {span}개월 구간을 월 1점으로 표본합니다.",
    ]
    freq = str(meta.get("evaluation_frequency") or "").lower()
    if freq in ("day", "overnight"):
        limitations.append(
            "이 팩터는 일간으로 갱신되는데 미리보기는 월 표본이라, 상태전환 횟수가 실제보다 "
            "**과소집계**됩니다(월 사이의 전환은 보이지 않습니다).")

    points: list[HistoryPoint] = []
    for m in range(span, -1, -1):          # 오래된 → 최신, 마지막은 현재(0)
        try:
            with as_of(m):
                value = evaluate(factor_id, ticker, market, p)
        except Exception as e:             # noqa: BLE001 — 한 점의 실패가 전체를 깨지 않는다
            logger.debug(f"factor_history 평가 실패 [{factor_id}/{ticker}/-{m}m]: {e}")
            value = None
        state = state_from_value(value, thr, dirn)
        points.append(HistoryPoint(m, value, state.value))

    states = [pt.state for pt in points]
    unavailable = sum(1 for s in states if s == SignalState.UNAVAILABLE.value)
    if unavailable == len(points):
        limitations.append(
            "요청 구간에서 값을 얻지 못했습니다 — 시세 이력이 짧거나 조회에 실패했습니다. "
            "0 으로 채우지 않습니다.")

    return FactorHistory(
        factor_id=factor_id, ticker=ticker, market=market,
        threshold=float(thr), direction=dirn, step=STEP,
        points=points,
        state_changes=count_state_flips(states),
        available_count=len(points) - unavailable,
        unavailable_count=unavailable,
        limitations=limitations,
    )
