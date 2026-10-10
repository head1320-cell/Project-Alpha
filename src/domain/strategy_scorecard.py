"""전략 평가 카드 — ★세 축을 보존하고, 합치지 않는다★ (AE2)
==============================================================================
설계: `docs/plans/2026-09-12-ra-product-roadmap.md` P4 "평가 카드"
재료: `src/data/alpha_registry.py`(생애주기) · `src/engine/strategy_health.py`(건강도)
      · `src/engine/run_evidence.py`(증거) — ★어휘를 새로 만들지 않는다★

## 왜 세 축인가

로드맵이 *"`alpha_registry` 의 승격 사다리와 `strategy_health` 의 5상태가 평가 카드의
재료다"* 라고 적었다. 그 둘은 **다른 질문에 답한다**:

    lifecycle  절차가 어디까지 갔나   draft → experimental → validated → approved
    health     지금 건강한가          healthy · watch · de_risk · paused · retired
    evidence   무엇이 뒷받침하나      run_evidence 의 축 판정

★둘 다 `retired` 를 갖지만 다른 사실이다★ — 등록부의 `retired` 는 "폐기했다"(절차)
이고 건강도의 `retired` 는 "판정"이다. 이름이 같아 합치고 싶어지는데, 합치면 Z 에서
`kind ⟂ data_real` 을, AA 에서 `trigger ⟂ decision reason` 을 가른 규율을 되풀이해
어긴다. **`approved` 이니까 좋은 전략** 같은 추론이 코드에 스며드는 자리다 —
승격은 **절차**이지 성과가 아니고, 건강도는 **측정**이지 승인이 아니다.

## ★★합성 등급을 만들지 않는다★★

`grade`·`score`·`stars` 가 없다. 세 축을 한 글자로 뭉개려면 **가중치**를 정해야 하고,
그 가중치는 이 저장소가 잰 적이 없다. 지어내는 순간 CLAUDE.md §2 의 *"결론은 증거보다
강할 수 없다"* 를 어긴다. 카드는 세 축을 **나란히 보여 줄** 뿐, 종합하지 않는다.

## ★못 잰 것이 사라지지 않는다★

`strategy_health._UNMEASURED` 가 **여섯 가지를 재지 못한다고 스스로 적어 두었다** —
회전율 급등 · 캐파 · 상관 상승 · 차입 · 비용 괴리 · 백테스트 vs 실거래 괴리.
카드가 그것들을 빼면 남은 신호만 보여 주게 되고, 읽는 사람은 "이만큼 확인했다" 로
읽는다. 그래서 `unmeasured` 는 **선택 필드가 아니다**.

## ★유통은 축이 아니라 관문이다★

`distribution` 은 `SCORECARD_AXES` 에 **들어가지 않는다**. 유통 가능 여부는 전략의
품질이 아니라 **업권 상태**이고, 축에 섞으면 "유통 가능" 이 좋은 평가처럼 읽힌다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: 절차가 어디까지 갔나 — `alpha_registry.STATUSES`
AXIS_LIFECYCLE = "lifecycle"
#: 지금 건강한가 — `strategy_health.STATUSES`
AXIS_HEALTH = "health"
#: 무엇이 뒷받침하나 — `run_evidence.rollup`
AXIS_EVIDENCE = "evidence"

#: ★셋뿐이고, 서로 섞이지 않는다★
SCORECARD_AXES = (AXIS_LIFECYCLE, AXIS_HEALTH, AXIS_EVIDENCE)

#: 신호가 "재지 못했다" 를 뜻하는 상태 — `strategy_health` 가 쓰는 값 그대로.
SIGNAL_UNMEASURED = "unmeasured"


def unmeasured_from_signals(signals: list[dict] | None) -> list[dict]:
    """건강도 신호 목록에서 ★재지 못한 것만★ 이름과 함께 뽑는다.

    `strategy_health` 는 측정된 신호와 미측정 신호를 **같은 목록**에 넣는다. 카드는
    미측정을 별도로 세워 눈에 띄게 한다 — 섞여 있으면 스크롤 아래로 사라진다.
    """
    if not signals:
        return []
    return [
        {"key": s.get("key"), "label": s.get("label"),
         "basis": s.get("basis"), "detail": s.get("detail")}
        for s in signals
        if s.get("status") == SIGNAL_UNMEASURED
    ]


@dataclass(frozen=True)
class Scorecard:
    """전략 하나의 카드. ★종합 점수 없음★ — 세 축과 못 잰 것, 그리고 유통 관문."""

    strategy_id: str
    #: {status, reason, usable_for_portfolio}
    lifecycle: dict[str, Any]
    #: {status, signals}
    health: dict[str, Any]
    #: {status, reason, axes} — `run_evidence.rollup` 의 결과
    evidence: dict[str, Any]
    #: ★재지 못한 신호들★ — 비어 있어도 키는 남는다
    unmeasured: list[dict]
    #: `distribution_gate()` 의 결과. 축이 아니다.
    distribution: dict[str, Any]
    as_of: str

    def to_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            AXIS_LIFECYCLE: self.lifecycle,
            AXIS_HEALTH: self.health,
            AXIS_EVIDENCE: self.evidence,
            "unmeasured": self.unmeasured,
            "distribution": self.distribution,
            "as_of": self.as_of,
        }
