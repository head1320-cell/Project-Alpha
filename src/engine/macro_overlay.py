"""매크로 오버레이 시맨틱 — 선택적 조정 · 3자 비교 · 평문 충돌 설명 (스펙 §8, Phase 7b).

이 모듈이 답하는 질문은 하나다: **매크로 국면이 타이밍 룰셋의 판단을 어떻게 바꾸는가.**

★오버레이는 한 방향으로만 작동한다 (one-way)★
매크로는 노출을 **줄이기만** 한다. 좋아 보이는 국면이라고 노출을 올려 주면, 국면 모델이
틀렸을 때 손실이 증폭된다 — 그리고 국면 모델은 틀릴 수 있다(Phase 3a 가 기록한 대로
현재 스냅샷은 `forward_only`·`partial` 이다). 줄이는 실수는 기회를 놓치고, 키우는 실수는
자본을 잃는다. 대칭이 아니므로 대칭으로 다루지 않는다.

★대체가 아니라 조정이다★
타이밍이 위험-오프면 매크로가 아무리 좋아도 위험-오프다. 매크로는 타이밍의 결론을
뒤집지 못하고, 보수적인 쪽으로만 당길 수 있다. 그리고 **끌 수 있다**(`enabled=False`) —
끄면 타이밍 단독 결과와 정확히 같아야 한다. 그것이 "조용한 오버라이드가 아니다" 의 실질이다.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.data.pit_macro import DataStatus, ResearchUsage
from src.engine.timing_rules_v2 import CompositeSignal, SignalState, combine

#: 국면 엔진이 권고하는 모드. 노출 상한으로 번역된다(키우지 않고 자른다).
MODE_CAP: dict[str, float] = {
    "risk_on": 1.0,      # 자르지 않음 — 올려 주지도 않음
    "neutral": 0.6,
    "risk_off": 0.0,
}


@dataclass(frozen=True)
class MacroOverlay:
    """타이밍 판단에 얹는 매크로 국면 컨텍스트.

    `enabled=False` 면 아무 영향도 주지 않는다 — 사용자가 룰과 독립적으로 끌 수 있어야 한다는
    스펙 요구를 타입 수준에서 표현한다.
    """
    regime: str
    recommended_mode: str
    confidence: float
    stress_score: float
    data_status: DataStatus = DataStatus.REAL
    research_usage: ResearchUsage = ResearchUsage.UNAVAILABLE
    enabled: bool = True

    @property
    def active(self) -> bool:
        return bool(self.enabled)

    @property
    def usable(self) -> bool:
        """값을 신뢰할 수 있는가. 결측이면 조정에 쓰지 않고 **보수적으로만** 취급한다."""
        return self.data_status is not DataStatus.UNAVAILABLE

    def exposure_cap(self) -> float:
        """이 국면이 허용하는 노출 상한 (0.0~1.0).

        모드 상한 × 신뢰도 × (1 − 스트레스), 0~1 로 클램프.

        ★one-way 불변식을 강제하는 곳은 여기가 아니다★
        실제 보장은 `timing_rules_v2.combine()` 의 `if cap < exposure` 비교다 — 상한이
        원래 노출보다 클 때는 아예 적용하지 않는다. 처음엔 이 주석에 "세 항이 1 을 넘지
        않으니 산술로 보장된다" 고 적었는데, 뮤테이션 프로브로 확인해 보니 **틀렸다**:
        이 함수가 1.8 을 돌려주도록 바꿔도 테스트가 전부 통과했다(combine 이 막고 있었다).
        불변식의 소재를 잘못 적으면 다음 사람이 여기만 보고 안심하게 되므로 바로잡아 둔다.
        """
        cap = MODE_CAP.get(self.recommended_mode.lower(), 0.0)
        if not self.usable:
            # 매크로를 못 읽었다 → 조정하지 않는다(노출을 키우지도, 임의로 깎지도 않는다).
            return 1.0
        conf = min(1.0, max(0.0, float(self.confidence)))
        stress = min(1.0, max(0.0, float(self.stress_score)))
        return max(0.0, min(1.0, cap * conf * (1.0 - stress)))

    def to_dict(self) -> dict:
        return {
            "regime": self.regime, "recommended_mode": self.recommended_mode,
            "confidence": self.confidence, "stress_score": self.stress_score,
            "data_status": self.data_status.value,
            "research_usage": self.research_usage.value,
            "enabled": self.enabled, "exposure_cap": self.exposure_cap(),
        }


def _baseline(n: int) -> CompositeSignal:
    """'타이밍을 하지 않았다면' — 항상 전액 투자. 비교의 기준선이다."""
    return CompositeSignal(
        SignalState.RISK_ON, 1.0, "baseline", n, 0, 0,
        "기준: 타이밍을 적용하지 않은 경우 — 항상 위험자산 100%",
    )


def three_way(
    states: list[SignalState],
    *,
    method: str = "all",
    overlay: MacroOverlay | None = None,
    k: int = 1,
    weights: list[float] | None = None,
) -> dict[str, CompositeSignal]:
    """기준 vs 타이밍만 vs 타이밍+매크로 — 스펙 §8 의 3자 비교.

    매크로가 없으면 세 번째 다리를 **지어내지 않고** unavailable 로 둔다. 없는 비교를
    그럴듯하게 채우면 사용자는 오버레이가 적용된 줄 알게 된다.
    """
    timing_only = combine(states, method=method, k=k, weights=weights)
    if overlay is None:
        macro_leg = CompositeSignal(
            SignalState.UNAVAILABLE, 0.0, method,
            timing_only.on_count, timing_only.off_count, timing_only.unavailable_count,
            "매크로 국면이 연결되지 않아 타이밍+매크로 비교를 만들 수 없습니다 "
            "(비교를 지어내지 않습니다).",
        )
    else:
        macro_leg = combine(states, method=method, k=k, weights=weights, overlay=overlay)
    return {
        "baseline": _baseline(len(states)),
        "timing_only": timing_only,
        "timing_macro": macro_leg,
    }


def conflict_explanation(timing: CompositeSignal, overlay: MacroOverlay | None) -> str | None:
    """타이밍과 매크로가 어긋날 때의 평문 설명. 충돌이 없으면 None.

    스펙은 "모든 위험-온/오프 결정이 이유를 갖는다" 를 요구한다. 숫자를 함께 적는다 —
    "매크로가 부정적" 만으로는 사용자가 무엇을 확인해야 할지 알 수 없다.
    """
    if overlay is None or not overlay.active:
        return None          # 꺼진 오버레이는 판단에 관여하지 않으므로 충돌도 없다
    macro_off = overlay.recommended_mode.lower() != "risk_on"
    timing_on = timing.state is SignalState.RISK_ON
    if not (timing_on and macro_off):
        return None
    return (
        f"타이밍 신호는 **위험-온**({timing.on_count}/{timing.on_count + timing.off_count + timing.unavailable_count} 팩터 통과)"
        f"이지만 매크로 국면은 '{overlay.regime}' 로 {overlay.recommended_mode} 권고입니다 — "
        f"신뢰도 {overlay.confidence:.2f} · 스트레스 {overlay.stress_score:.2f}. "
        f"오버레이가 노출 상한을 {overlay.exposure_cap():.2f} 로 제한합니다. "
        f"오버레이를 끄면 타이밍 단독 판단이 그대로 적용됩니다."
    )
