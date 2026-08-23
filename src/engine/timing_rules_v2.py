"""TimingRuleSetV2 — 3-상태 시그널 + 조합/히스테리시스/쿨다운 (AAS Phase 7).

왜 새 모듈인가 (Drift D7-1)
──────────────────────────────────────────────────────────────────────────────
기존 `timing_factors.passes(value, threshold, direction) -> bool` 은 **라이브 카나리
엔드포인트가 쓰고 있다**. 동작은 이미 보수적(None→False)이지만 스펙 §3.3 이 문제 삼는 것은
**타입**이다 — bool 은 결측이 참으로 떨어질 수 있는 형태를 허용한다.
그래서 `passes()` 를 건드리지 않고 여기에 V2 를 따로 둔다. 이 모듈은 `passes()` 를
import 하지 않는다. 라이브 경로 회귀 위험 0이고, bool 은 마지막 호출자가 이전할 때 은퇴한다.

핵심 불변식
──────────────────────────────────────────────────────────────────────────────
1. **3-상태** — risk_on | risk_off | **unavailable**. 결측은 risk_off 와 다른 사실이다
   (합치면 "왜 위험-오프인지"를 알 수 없게 된다).
2. **조합에서 unavailable → risk_off.** 어떤 조합 방식에서도 결측이 위험-온을 만들 수 없다.
3. **방향은 카탈로그가 진실.** defense_first 는 값이 **음수일 때 위험-온**이고 그 사실이
   함수가 아니라 카탈로그 `default_direction="below"` 에 있다. 여기서 direction 을 읽지
   않으면 신호가 **에러 없이 뒤집힌다** — 이 모듈에서 가장 위험한 실패 양상이다.
4. **쿨다운은 대칭이되 결측은 우회한다.** 신호 전환(위험-온 ↔ 위험-오프)은 양방향으로
   늦추지만(한쪽만 막으면 휩쏘 방지가 성립하지 않는다), **결측으로 가는 전환은 막지 않는다** —
   데이터가 사라진 것은 신호가 뒤집힌 것이 아니라 알 수 없게 된 것이다.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any

from src.data.mock_gate import mock_allowed
from src.data.pit_macro import (
    DataStatus,
    MacroObservation,
    ResearchUsage,
    assert_backtest_eligible,
    derive_usage,
    fetch_observations,
    latest_vintage_per_period,
)

# `passes()` 는 의도적으로 import 하지 않는다 (Drift D7-1) — 라이브 카나리 경로 불변.
from src.engine.timing_factors import CATALOG_BY_ID, evaluate, rule_from_spec

# 스펙 §3.3 이 나열한 6종. regime_conditioned 는 매크로 오버레이(Phase 7b) 가 필요해서
# 여기서는 **명시적으로 거부**한다 — 다른 방식으로 조용히 대치하면 사용자는 자기가
# 요청하지 않은 조합으로 판단이 내려진 것을 모른다.
COMBINATION_METHODS: tuple[str, ...] = (
    "all", "any", "k_of_n", "weighted", "regime_conditioned", "continuous",
)
_IMPLEMENTED: frozenset[str] = frozenset(
    {"all", "any", "k_of_n", "weighted", "continuous", "regime_conditioned"})


class NotYetImplementedError(NotImplementedError):
    """스펙에는 있지만 아직 이 단계에서 구현되지 않은 기능 — 어느 단계에서 오는지 알린다."""


class SignalState(str, Enum):
    RISK_ON = "risk_on"
    RISK_OFF = "risk_off"
    #: 값을 얻지 못했다 — "판정상 위험-오프" 와 **다른 사실**이다.
    UNAVAILABLE = "unavailable"


# ═══════════════════════════════════════════════════════════════════════════════
# 단일 팩터 판정
# ═══════════════════════════════════════════════════════════════════════════════
def state_from_value(
    value: float | None,
    threshold: float,
    direction: str,
    *,
    hysteresis: float = 0.0,
    previous: SignalState | None = None,
) -> SignalState:
    """값 → 3-상태.

    direction: "above" 면 value > threshold 가 위험-온, "below" 면 value < threshold 가 위험-온.
    경계값(==)은 통과가 아니다.

    hysteresis: 임계 ±band 안에서는 **직전 상태를 유지**해 휩쏘를 억제한다.
      단 ★결측은 히스테리시스로 살아나지 않는다★ — 값이 없으면 직전이 위험-온이었어도
      unavailable 이다. 안 그러면 데이터가 끊긴 뒤에도 위험에 노출된 채 남는다.
    """
    if value is None:
        return SignalState.UNAVAILABLE

    on = value > threshold if direction == "above" else value < threshold

    if hysteresis > 0.0 and previous in (SignalState.RISK_ON, SignalState.RISK_OFF):
        if abs(value - threshold) <= hysteresis:
            return previous     # 밴드 안 — 직전 유지

    return SignalState.RISK_ON if on else SignalState.RISK_OFF


def direction_for(factor_id: str) -> str | None:
    """카탈로그가 규정한 방향. 모르는 팩터는 None (추측하지 않는다)."""
    meta = CATALOG_BY_ID.get(factor_id)
    if not meta:
        return None
    return str(meta.get("default_direction") or "above")


def threshold_for(factor_id: str) -> float | None:
    meta = CATALOG_BY_ID.get(factor_id)
    if not meta:
        return None
    return float(meta.get("default_threshold") or 0.0)


def state_for_factor(
    factor_id: str,
    value: float | None,
    *,
    threshold: float | None = None,
    hysteresis: float = 0.0,
    previous: SignalState | None = None,
) -> SignalState:
    """팩터 id 로 판정 — **방향/임계를 카탈로그에서 읽는다**.

    ★defense_first 같은 역방향 팩터가 여기서 갈린다★
    그 팩터는 음수일 때 위험-온이고, 그 사실은 카탈로그 default_direction="below" 에만 있다.
    호출자가 direction 을 직접 넘기게 두면 언젠가 누군가 "above" 로 넘겨 신호를 뒤집는다.

    모르는 팩터는 값이 있어도 **unavailable** — 기본 방향을 추측하면 절반의 확률로 반대다.
    """
    d = direction_for(factor_id)
    if d is None:
        return SignalState.UNAVAILABLE
    t = threshold if threshold is not None else (threshold_for(factor_id) or 0.0)
    return state_from_value(value, t, d, hysteresis=hysteresis, previous=previous)


# ═══════════════════════════════════════════════════════════════════════════════
# 조합
# ═══════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class CompositeSignal:
    state: SignalState
    #: 0.0~1.0 위험자산 노출. continuous 가 아니면 0/1 에 수렴하되 항상 범위 안.
    exposure: float
    method: str
    on_count: int
    off_count: int
    unavailable_count: int
    #: 왜 이 판정인지 — 스펙은 모든 위험-온/오프 결정에 설명을 요구한다.
    explanation: str


def combine(
    states: list[SignalState],
    *,
    method: str = "all",
    k: int = 1,
    weights: list[float] | None = None,
    overlay: Any = None,
) -> CompositeSignal:
    """여러 팩터 상태 → 하나의 복합 신호.

    ★unavailable 은 risk_off 로 떨어진다★ (스펙 §3.3). 다만 **개수는 따로 센다** —
    "3개 중 2개가 결측이라 위험-오프" 와 "3개 다 판정상 위험-오프" 는 다른 이야기이고,
    설명에 그 차이가 남아야 한다.
    """
    if method not in COMBINATION_METHODS:
        raise ValueError(
            f"알 수 없는 조합 방식: {method!r}. 가능한 값: {', '.join(COMBINATION_METHODS)}"
        )
    # regime_conditioned 는 Phase 7b 에서 구현됐다. 다만 **매크로 없이는 성립하지 않는다** —
    # 오버레이가 없으면 조용히 다른 방식으로 대치하지 말고 거부한다.
    if method == "regime_conditioned" and overlay is None:
        raise ValueError(
            "regime_conditioned 는 매크로 오버레이(overlay=)가 필요합니다. "
            "오버레이 없이 다른 방식으로 대치하지 않습니다 — 요청하지 않은 조합으로 판단이 "
            "내려지면 안 되기 때문입니다."
        )
    if method not in _IMPLEMENTED:      # 방어 — 위 두 검사를 지나쳤다면 목록이 어긋난 것
        raise NotYetImplementedError(f"{method} 는 아직 구현되지 않았습니다.")

    n = len(states)
    unavailable = sum(1 for s in states if s is SignalState.UNAVAILABLE)
    on = sum(1 for s in states if s is SignalState.RISK_ON)
    off = n - on - unavailable

    # ★결측 → 위험-오프★ 로 접은 뒤 판정한다. 접기 전 개수는 위에서 이미 보존했다.
    folded_off = off + unavailable

    def _explain(verdict: str) -> str:
        base = f"{method}: 위험-온 {on}/{n}"
        if unavailable:
            base += f" · 결측(unavailable) {unavailable}건은 보수적으로 위험-오프로 처리"
        return f"{base} → {verdict}"

    if n == 0:
        return CompositeSignal(SignalState.UNAVAILABLE, 0.0, method, 0, 0, 0,
                               "평가할 팩터가 없습니다 → unavailable")

    if method == "all":
        state = SignalState.RISK_ON if on == n else SignalState.RISK_OFF
        exposure = 1.0 if state is SignalState.RISK_ON else 0.0
    elif method == "any":
        state = SignalState.RISK_ON if on >= 1 else SignalState.RISK_OFF
        exposure = 1.0 if state is SignalState.RISK_ON else 0.0
    elif method == "k_of_n":
        state = SignalState.RISK_ON if on >= max(1, k) else SignalState.RISK_OFF
        exposure = 1.0 if state is SignalState.RISK_ON else 0.0
    elif method == "weighted":
        w = weights or [1.0] * n
        if len(w) != n:
            raise ValueError(f"weights 길이({len(w)})가 상태 개수({n})와 다릅니다.")
        total = sum(abs(x) for x in w) or 1.0
        # 결측 가중치는 위험-온 쪽에 더하지 않는다(=위험-오프로 접힌다)
        on_w = sum(wi for wi, s in zip(w, states) if s is SignalState.RISK_ON)
        frac = on_w / total
        state = SignalState.RISK_ON if frac > 0.5 else SignalState.RISK_OFF
        exposure = max(0.0, min(1.0, frac))
    else:  # continuous · regime_conditioned (둘 다 비례 노출을 기반으로 한다)
        frac = on / n           # 결측은 분자에 들어가지 않는다 → 노출을 키우지 못한다
        exposure = max(0.0, min(1.0, frac))
        state = SignalState.RISK_ON if frac > 0.0 else SignalState.RISK_OFF

    # 전부 결측이면 판정이 아니라 "알 수 없음" 이 정직하다 — 노출은 0.
    if unavailable == n:
        return CompositeSignal(SignalState.RISK_OFF, 0.0, method, on, off, unavailable,
                               _explain("위험-오프(전부 결측 — 보수적 폴백)"))

    verdict = "위험-온" if state is SignalState.RISK_ON else "위험-오프"
    note = ""

    # ── 매크로 오버레이 (Phase 7b) ───────────────────────────────────────────
    # ★조정이지 대체가 아니다★ 노출 상한을 곱해 **줄이기만** 한다. 상한이 1 을 넘지 않으므로
    # 오버레이가 노출을 키우는 일은 산술적으로 불가능하다. 타이밍이 위험-오프면 그대로 오프다.
    if overlay is not None and getattr(overlay, "active", False):
        cap = float(overlay.exposure_cap())
        if cap < exposure:
            exposure = cap
            note = (f" · 매크로 오버레이('{overlay.regime}' {overlay.recommended_mode}, "
                    f"신뢰도 {overlay.confidence:.2f} · 스트레스 {overlay.stress_score:.2f})가 "
                    f"노출을 {cap:.2f} 로 제한")
        else:
            note = (f" · 매크로 오버레이('{overlay.regime}')는 이 판단을 더 보수적으로 "
                    f"만들지 않았다(상한 {cap:.2f})")
        if exposure <= 0.0:
            state = SignalState.RISK_OFF
            verdict = "위험-오프"

    return CompositeSignal(state, exposure, method, on, folded_off - unavailable, unavailable,
                           _explain(verdict) + note)


# ═══════════════════════════════════════════════════════════════════════════════
# 쿨다운
# ═══════════════════════════════════════════════════════════════════════════════
def apply_cooldown(
    proposed: SignalState,
    *,
    previous: SignalState | None,
    bars_since_flip: int,
    cooldown: int,
) -> SignalState:
    """전환 직후 재전환을 늦춘다 — 거래비용을 태우는 휩쏘 방지.

    쿨다운은 **신호가 뒤집힌 것**(위험-온 ↔ 위험-오프)에만, 그리고 **양방향 대칭으로**
    걸린다. 한쪽만 막으면 휩쏘 방지가 성립하지 않는다 — 진입만 늦추면 잡음 스파이크마다
    이탈은 그대로 일어나고, 왕복 비용의 절반은 여전히 태운다.

    ★단 결측(unavailable)으로 가는 전환은 절대 막지 않는다★
    데이터가 사라진 것은 신호가 뒤집힌 것이 아니라 **알 수 없게 된 것**이다. "최근에
    전환했으니 유지"라며 위험-온을 붙들면, 이미 우리 손에 없는 값을 근거로 위험에
    노출된 채 남는다. 이 phase 전체가 세운 구분(결측 ≠ 위험-오프)이 여기서도 적용된다.
    """
    if previous is None or cooldown <= 0 or proposed is previous:
        return proposed
    # 결측은 신호 전환이 아니라 지식의 소실 — 쿨다운을 우회한다
    if proposed is SignalState.UNAVAILABLE:
        return proposed
    # 신호 전환(위험-온 ↔ 위험-오프)에는 대칭으로 쿨다운 적용
    if bars_since_flip < cooldown:
        return previous
    return proposed


# ═══════════════════════════════════════════════════════════════════════════════
# 빈도 정렬
# ═══════════════════════════════════════════════════════════════════════════════
#: 주기 등급 — 같은 등급이면 충돌 아님. 카탈로그 응답으로 UI 에 그대로 내려간다
#: (프론트에 복제하면 두 진실이 생기고 조용히 어긋난다).
FREQUENCY_RANKS = {"day": 1, "overnight": 1, "week": 2, "month": 3, "month_end": 3, "quarter": 4}


def frequency_conflicts(factor_freq: str, rebalance: str) -> bool:
    """팩터 샘플링 주기와 리밸런싱 주기가 어긋나는가.

    · 팩터가 더 잦으면 → 신호 대부분이 버려진다(일간 신호를 월말에만 반영)
    · 리밸런싱이 더 잦으면 → 같은 값을 반복 적용한다(월간 신호를 일간 리밸런싱)
    둘 다 사용자가 알아야 하는 어긋남이다. 같은 등급이면 충돌 아님.
    """
    a = FREQUENCY_RANKS.get(factor_freq.lower())
    b = FREQUENCY_RANKS.get(rebalance.lower())
    if a is None or b is None:
        return False        # 모르는 주기는 경고를 지어내지 않는다
    return a != b


# ═══════════════════════════════════════════════════════════════════════════════
# TimingRuleSetV2 — 기존 TimingRule 을 감싸는 버전화된 집합
# ═══════════════════════════════════════════════════════════════════════════════
@dataclass
class TimingRuleV2:
    """기존 TimingRule(14필드) + 스펙 §3.3 이 요구한 9필드."""
    factor_id: str
    #: 기존 TimingRule 을 그대로 품는다 — 재구현하지 않는다.
    base: Any = None
    version: int = 1
    provenance: str = "user_defined"
    benchmark_series: str | None = None
    normalization: str = "none"          # none | zscore | percentile
    hysteresis: float = 0.0
    cooldown: int = 0
    conflict_policy: str = "conservative"   # conservative | latest | weighted
    use_mode: str = "gate"               # gate | ranking | sizing | tilt | risk_off_trigger
    data_status: str = "real"
    #: 사용자가 고른 임계. None 이면 카탈로그 기본값.
    #: ★방향(direction)은 여기 없다★ 그건 카탈로그만 아는 사실이다(defense_first 는 음수가
    #: 위험-온). 호출자가 방향을 넘기게 두면 언젠가 누군가 반대로 넘겨 신호를 뒤집는다.
    #: 임계는 반대로 사용자 손에 있는 값이고, 과거 미리보기
    #: (`timing_factor_history`)도 사용자 임계로 채점한다 — 같은 노브가 두 화면에서 다른
    #: 뜻이 되지 않도록 여기서도 존중한다.
    threshold: float | None = None

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "base"}
        if self.base is not None and hasattr(self.base, "to_dict"):
            d["base"] = self.base.to_dict()
        return d


@dataclass
class TimingRuleSetV2:
    set_id: str
    name: str = ""
    market: str = "kr"
    version: int = 1
    combination: str = "all"
    k: int = 1
    weights: list[float] = field(default_factory=list)
    rules: list[TimingRuleV2] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "set_id": self.set_id, "name": self.name, "market": self.market,
            "version": self.version, "combination": self.combination,
            "k": self.k, "weights": list(self.weights),
            "rules": [r.to_dict() for r in self.rules],
        }


# ═══════════════════════════════════════════════════════════════════════════════
# 팩터 값 읽기 — 값과 함께 **어디까지 쓸 수 있는지**를 돌려준다
#
# Phase 1 이 ALFRED 빈티지 경로(`fetch_observations`)와 백테스트 게이트
# (`assert_backtest_eligible`)를 만들었지만 **여기까지 호출자가 없었다**. 이 절이 그 배선이다.
# 값만 돌려주면 호출자는 "이 값을 과거 시뮬레이션에 써도 되는가"를 알 수 없고, 모르면 쓴다.
# ═══════════════════════════════════════════════════════════════════════════════
CURVE_SLOPE_FACTOR_ID = "curve_slope"
CURVE_SLOPE_SERIES = "T10Y2Y"
EVALUATION_MODES: tuple[str, ...] = ("forward", "backtest")


@dataclass(frozen=True)
class FactorReading:
    """팩터 1건의 값 + 출처 등급 + 연구 용도. 세 가지는 서로 독립이다."""
    factor_id: str
    value: float | None
    usage: ResearchUsage
    data_status: DataStatus
    observation: MacroObservation | None = None
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "factor_id": self.factor_id, "value": self.value,
            "usage": self.usage.value, "data_status": self.data_status.value,
            "observation": self.observation.to_dict() if self.observation else None,
            "detail": self.detail,
        }


def _unavailable(factor_id: str, detail: str) -> FactorReading:
    """값이 없을 때의 유일한 표현 — 0 이나 합성값으로 채우지 않는다."""
    return FactorReading(factor_id, None, ResearchUsage.UNAVAILABLE,
                         DataStatus.UNAVAILABLE, None, detail)


def _read_macro_series(
    factor_id: str,
    series_id: str,
    as_of: str,
    *,
    api_key: str | None = None,
    start: str | None = None,
) -> FactorReading:
    """시점 기반 매크로 시리즈 1건 읽기 — 개정되는 시리즈의 **공용** 리더.

    `curve_slope`(Phase 7) · `indicator` · `financial_conditions`(Phase 8b) 가 공유한다.
    세 벌로 복제하면 그중 하나만 고쳐지는 날이 오고, 그 하나는 조용히 오늘 개정판을 읽는다.

    ★usage 는 손으로 지정하지 않고 관측치에서 파생한다★
      · has_vintage — 모든 관측치가 빈티지 식별자를 갖는가
      · depth_ok    — 요청한 start 를 이력이 덮는가
      · lag_known   — 공표시각이 관측기간 이후인가(=공표지연이 실제로 관측되었는가)
    손으로 `backtest_eligible` 을 넣으면 게이트가 거짓말을 한다.

    키가 없거나 호출이 실패하면 **unavailable**. 0 으로 대체하지 않는다 — 0 은 값이 없다는
    뜻이 아니라 "지표가 0" 이라는 판단이 된다.
    """
    try:
        obs = fetch_observations(series_id, as_of, api_key=api_key, start=start)
    except Exception as e:
        # 레이트리밋·네트워크 오류가 예외로 새어나가면 팩터 하나 때문에 창 전체가 죽는다.
        return _unavailable(factor_id, f"{series_id} 조회 실패({e.__class__.__name__}). "
                                       f"as_of={as_of}. 0 으로 대체하지 않습니다.")
    if not obs:
        return _unavailable(
            factor_id,
            f"{series_id} 관측치를 얻지 못했습니다(키 미설정·구간 내 값 없음·호출 실패). "
            f"as_of={as_of}. 0 으로 대체하지 않습니다 — 0 은 '지표가 0' 이라는 판단이 됩니다.",
        )

    latest = latest_vintage_per_period(obs)
    if not latest:
        return _unavailable(factor_id, f"{series_id} 빈티지 정리 후 남은 관측치가 없습니다.")
    current = max(latest, key=lambda o: o.observation_period)

    has_vintage = all(bool(o.vintage_id) for o in obs)
    # 공표시각이 관측기간보다 앞서면 공표지연이 모델링된 것이 아니다(그런 값은 신뢰할 수 없다).
    lag_known = all(
        bool(o.release_timestamp) and o.release_timestamp >= o.observation_period for o in obs)
    earliest = min(o.observation_period for o in obs)
    depth_ok = (earliest <= start) if start else True

    usage = derive_usage(has_vintage=has_vintage, depth_ok=depth_ok, lag_known=lag_known)
    detail = (f"{series_id} {current.observation_period} = {current.value} "
              f"(빈티지 {current.vintage_id}, 공표 {current.release_timestamp})")
    if usage is not ResearchUsage.BACKTEST_ELIGIBLE:
        missing = [n for n, ok in (("빈티지", has_vintage), ("이력 길이", depth_ok),
                                   ("공표지연", lag_known)) if not ok]
        detail += f" · 과거 시뮬레이션 부적격: {', '.join(missing)} 미충족"

    return FactorReading(factor_id, current.value, usage, current.data_status, current, detail)


#: `indicator` 가 시리즈를 지정하지 않았을 때의 기본값. VIX 는 개정되지 않지만 경로는 같다.
DEFAULT_INDICATOR_SERIES = "VIXCLS"
#: 금융환경지수 — **주간이고 개정된다**(스펙 §6.1). 빈티지 경로가 아니면 쓸 수 없다.
FINANCIAL_CONDITIONS_FACTOR_ID = "financial_conditions"
FINANCIAL_CONDITIONS_SERIES = "NFCI"


def read_macro_indicator(
    as_of: str,
    *,
    series_id: str | None = None,
    api_key: str | None = None,
    start: str | None = None,
) -> FactorReading:
    """매크로 지표 임계 팩터(`indicator`) — 시리즈를 파라미터로 받는 범용 읽기.

    ★이 리더가 없던 동안 `indicator` 는 V2 경로에서 영원히 unavailable 이었다★
    카탈로그에는 있는데 `evaluate()` 분기도 리더도 없어서, 사용자에겐 "데이터가 없다" 로
    보였지만 실제로는 배선이 없는 것이었다(Phase 8 의 무결성 테스트가 발견). 레거시 카나리
    경로에서만 동작했고, 그 경로는 지금도 그대로다.
    """
    return _read_macro_series(
        "indicator", series_id or DEFAULT_INDICATOR_SERIES, as_of,
        api_key=api_key, start=start)


def read_financial_conditions(
    as_of: str,
    *,
    api_key: str | None = None,
    start: str | None = None,
) -> FactorReading:
    """금융환경지수(NFCI) — 양수면 긴축, 음수면 완화. 완화 쪽이 위험-온.

    ★주간이고 **개정된다**★ 스펙 §6.1 이 이 시리즈에 빈티지를 요구하는 이유이고,
    오늘 개정판으로 과거를 채점하면 그 시점에 알 수 없던 정보를 쓰는 것이 된다.
    """
    return _read_macro_series(
        FINANCIAL_CONDITIONS_FACTOR_ID, FINANCIAL_CONDITIONS_SERIES, as_of,
        api_key=api_key, start=start)


#: VIX 텀 스트럭처 (스펙 §6.2). 30일 IV ÷ 3개월 IV.
VIX_SHORT_SERIES = "VIXCLS"
VIX_LONG_SERIES = "VXVCLS"
VIX_TERM_FACTOR_ID = "vix_term_structure"
VIX_SPREAD_FACTOR_ID = "vix_term_spread"


def _prev_day(d: str) -> str:
    from datetime import date, timedelta
    y, m, dd = (int(x) for x in d[:10].split("-"))
    return (date(y, m, dd) - timedelta(days=1)).isoformat()


def read_vix_term_structure(
    as_of: str,
    *,
    form: str = "ratio",
    market: str = "kr",
    api_key: str | None = None,
) -> FactorReading:
    """VIX 텀 스트럭처 — 스펙 §6.2 의 **정의**대로. 시리즈 추가가 아니라 팩터 정의다.

    ★형태는 비율이다★ `VIXCLS / VXVCLS`. 단위가 없어 변동성 수준이 달라도 비교할 수 있다 —
    2포인트 스프레드는 VIX 12 일 때와 45 일 때 뜻이 다르다. 비율 < 1 이면 콘탱고(평온)라
    위험-온 쪽이고, 그래서 카탈로그 방향이 `below` 다. 스프레드를 원하는 사용자를 위해
    `form="spread"` 를 **별도 팩터로 명시적으로 라벨링해** 제공한다(§6.2 요구).

    ★시차가 룩어헤드 벡터다★
    둘 다 **미국 종가**다. 한국에서 D 일에 내리는 결정은 D 의 미국 종가를 쓸 수 없다 —
    그 값은 KRX 장이 끝난 뒤에 나온다. 그래서 KR 결정은 **D−1** 의 미국 종가를 쓴다.
    미국 시장 결정에는 이 시프트가 필요 없다(시차 때문이지 관례가 아니다).
    그 근거를 `market_cutoff`/`execution_timestamp` 에 **기록한다** — §6.2 가 그렇게 하라고
    적어 두었는데 Phase 8b 전까지 두 필드는 어디서도 채워지지 않았다.

    ★결측은 전진 채움하지 않는다★
    한·미 휴장일이 다르므로 D−1 이 미국 휴장일 수 있다. 그때 더 뒤로 거슬러 올라가면
    "낡았지만 자신만만한" 신호가 만들어진다 — 없으면 unavailable 이고, 그건 위험-오프로 접힌다.
    """
    fid = VIX_SPREAD_FACTOR_ID if form == "spread" else VIX_TERM_FACTOR_ID
    # KR 결정은 전날 미국 종가까지만 볼 수 있다. US 결정은 당일 종가를 쓴다.
    target = _prev_day(as_of) if market == "kr" else as_of[:10]

    def _pick(series_id: str) -> MacroObservation | None:
        obs = fetch_observations(series_id, as_of, api_key=api_key)
        latest = latest_vintage_per_period(obs)
        # ★정확히 그 날짜만★ 없으면 없는 것이다(가장 가까운 이전 값으로 대체하지 않는다).
        for o in latest:
            if o.observation_period[:10] == target:
                return o
        return None

    short, long = _pick(VIX_SHORT_SERIES), _pick(VIX_LONG_SERIES)
    if short is None or long is None:
        missing = " · ".join(
            s for s, o in ((VIX_SHORT_SERIES, short), (VIX_LONG_SERIES, long)) if o is None)
        return _unavailable(
            fid, f"{target} 의 {missing} 값이 없습니다(미국 휴장·키 미설정·구간 밖). "
                 "가장 가까운 이전 값으로 **전진 채움하지 않습니다** — 낡은 값을 "
                 "자신만만한 신호로 만들지 않기 위해서입니다.")

    if form == "spread":
        value = short.value - long.value
    else:
        if long.value <= 0:
            return _unavailable(fid, f"{VIX_LONG_SERIES} 가 {long.value} 라 비율을 낼 수 없습니다.")
        value = short.value / long.value

    has_vintage = bool(short.vintage_id) and bool(long.vintage_id)
    lag_known = all(
        bool(o.release_timestamp) and o.release_timestamp >= o.observation_period
        for o in (short, long))
    usage = derive_usage(has_vintage=has_vintage, depth_ok=True, lag_known=lag_known)

    # ★정렬 근거를 관측치에 기록한다★ (§6.2 · Drift 8b-1)
    obs_out = replace(
        short,
        value=value,
        market_cutoff=f"{target} US close",
        execution_timestamp=f"{as_of[:10]} {'KRX' if market == 'kr' else 'US'} session",
    )
    detail = (f"{VIX_SHORT_SERIES}({short.value}) / {VIX_LONG_SERIES}({long.value}) "
              if form != "spread" else
              f"{VIX_SHORT_SERIES}({short.value}) − {VIX_LONG_SERIES}({long.value}) ")
    detail += f"@ {target} 미국 종가 → {as_of[:10]} 결정에 사용"
    if market == "kr":
        detail += " (KR 결정이므로 D−1 종가)"
    return FactorReading(fid, value, usage, short.data_status, obs_out, detail)


def read_curve_slope(
    as_of: str,
    *,
    series_id: str | None = None,
    api_key: str | None = None,
    start: str | None = None,
) -> FactorReading:
    """장단기 금리차 — **as_of 시점에 알 수 있었던 빈티지만** 본다.

    이 팩터가 Phase 1 의 `fetch_observations` 첫 생산 소비자였다. 개정 이력이 있는 시리즈라서
    `realtime_start=realtime_end=as_of` 로 고정하지 않으면 오늘 개정판이 새고, 그러면
    과거 성과가 "그때는 알 수 없던 값" 으로 부풀려진다.

    Phase 8b 에서 읽기 본체를 `_read_macro_series` 로 올렸다 — `indicator`·NFCI 가 같은
    의미론을 필요로 하는데, 세 벌로 복제하면 그중 하나만 고쳐지는 날이 온다.
    """
    sid = series_id or str(
        (CATALOG_BY_ID.get(CURVE_SLOPE_FACTOR_ID, {}).get("params") or {}).get(
            "series_id") or CURVE_SLOPE_SERIES)
    return _read_macro_series(CURVE_SLOPE_FACTOR_ID, sid, as_of, api_key=api_key, start=start)


def read_price_factor(
    factor_id: str,
    ticker: str,
    market: str = "kr",
    params: dict | None = None,
) -> FactorReading:
    """가격 기반 팩터 — 기존 `timing_factors.evaluate()` 를 그대로 쓴다(수식 재구현 금지).

    ★mock 이 허용된 환경에서는 백테스트 적격을 줄 수 없다★
    `mock_allowed()` 가 True 면 값이 합성일 수 있고, 우리는 이 값이 실데이터라고 **증명할 수
    없다**. 증명할 수 없는 것을 적격으로 통과시키면 게이트가 거짓말을 한다. `DataStatus.MOCK`
    은 여기서 "합성이다" 가 아니라 "합성일 수 있어 실데이터로 인증하지 않는다" 를 뜻한다.

    실데이터 환경에서 값이 나오면 적격으로 본다 — 일봉 OHLCV 는 매크로처럼 개정되지 않는다.
    (수정주가는 분할·배당에서 소급 조정되므로, 그 경로를 쓰게 되면 이 판단을 다시 봐야 한다.)
    """
    value = evaluate(factor_id, ticker, market, params or {})
    if mock_allowed():
        usage = ResearchUsage.FORWARD_ONLY if value is not None else ResearchUsage.UNAVAILABLE
        return FactorReading(
            factor_id, value, usage, DataStatus.MOCK, None,
            "KIS_USE_MOCK=1 — 값이 합성일 수 있어 실데이터로 인증하지 않습니다"
            "(과거 시뮬레이션 부적격).")
    if value is None:
        return _unavailable(factor_id, f"{factor_id}({ticker}) 평가 실패 또는 데이터 부족.")
    return FactorReading(factor_id, value, ResearchUsage.BACKTEST_ELIGIBLE,
                         DataStatus.REAL, None, f"{factor_id}({ticker}) = {value}")


def requires_as_of(factor_id: str) -> bool:
    """이 팩터가 시점(as_of)을 필요로 하는가 — 카탈로그가 표시한다."""
    return bool(CATALOG_BY_ID.get(factor_id, {}).get("requires_as_of"))


def read_factor(
    factor_id: str,
    *,
    as_of: str | None = None,
    ticker: str | None = None,
    market: str = "kr",
    params: dict | None = None,
) -> FactorReading:
    """팩터 id → 읽기. as_of 가 필요한 팩터와 티커가 필요한 팩터를 카탈로그로 갈라 보낸다."""
    if factor_id not in CATALOG_BY_ID:
        return _unavailable(factor_id, f"카탈로그에 없는 팩터: {factor_id!r}. 방향을 추측하지 않습니다.")
    if requires_as_of(factor_id):
        if not as_of:
            return _unavailable(factor_id, f"{factor_id} 는 as_of 시점이 필요합니다.")
        p = params or {}
        if factor_id == CURVE_SLOPE_FACTOR_ID:
            return read_curve_slope(as_of, start=p.get("start"),
                                    series_id=p.get("series_id"))
        if factor_id == FINANCIAL_CONDITIONS_FACTOR_ID:
            return read_financial_conditions(as_of, start=p.get("start"))
        if factor_id in (VIX_TERM_FACTOR_ID, VIX_SPREAD_FACTOR_ID):
            return read_vix_term_structure(
                as_of, form="spread" if factor_id == VIX_SPREAD_FACTOR_ID else "ratio",
                market=market)
        return _unavailable(factor_id, f"{factor_id} 의 시점 기반 읽기가 아직 구현되지 않았습니다.")
    # ★`indicator` 는 as_of 가 있을 때만 시점 기반으로 읽는다★
    # `requires_as_of` 를 붙이면 팩터 창이 "추가 불가" 로 막아 기존 흐름이 사라지므로
    # 플래그 대신 여기서 분기한다. as_of 가 없으면 값을 지어내지 않고 사유와 함께 결측이다
    # (레거시 카나리 경로는 이 함수를 지나지 않으므로 영향받지 않는다).
    if factor_id == "indicator":
        pp = params or {}
        if as_of:
            return read_macro_indicator(as_of, start=pp.get("start"),
                                        series_id=pp.get("series_id"))
        return _unavailable(
            factor_id, "indicator 는 시점(as_of)이 있어야 빈티지 기준으로 읽을 수 있습니다. "
                       "0 으로 대체하지 않습니다.")

    if not ticker:
        return _unavailable(factor_id, f"{factor_id} 는 평가 대상 티커가 필요합니다.")
    return read_price_factor(factor_id, ticker, market, params)


def assert_readings_backtest_eligible(readings: list[FactorReading]) -> None:
    """과거 시뮬레이션 진입 게이트 — Phase 1 의 `assert_backtest_eligible` 을 여기서 호출한다.

    경고가 아니라 **거부**다. forward_only 팩터로 백테스트를 돌리면 결과가 조용히 낙관적으로
    나오고, 그 숫자는 어디에도 "믿을 수 없음" 이라고 적혀 있지 않다.
    """
    assert_backtest_eligible({r.factor_id: r.usage for r in readings})


# ═══════════════════════════════════════════════════════════════════════════════
# 룰셋 평가 — 읽기 → (백테스트면 게이트) → 판정 → 조합
# ═══════════════════════════════════════════════════════════════════════════════
def rule_set_from_specs(
    specs: list[dict],
    *,
    market: str = "kr",
    combination: str = "all",
    k: int = 1,
    weights: list[float] | None = None,
    set_id: str = "ad_hoc",
    name: str = "",
) -> TimingRuleSetV2:
    """UI/API 스펙 리스트 → `TimingRuleSetV2`.

    각 룰의 `base` 는 `timing_factors.rule_from_spec()` 이 만든다 — 카탈로그 기본값 보강을
    여기서 다시 구현하지 않는다. `hysteresis` 처럼 V2 에만 있는 필드는 스펙에서 직접 읽는다.
    """
    rules = [
        TimingRuleV2(
            factor_id=str(s.get("factor_id") or s.get("id") or ""),
            base=rule_from_spec(s),
            hysteresis=float(s.get("hysteresis", 0.0) or 0.0),
            cooldown=int(s.get("cooldown", 0) or 0),
            threshold=None if s.get("threshold") is None else float(s["threshold"]),
        )
        for s in (specs or [])
    ]
    return TimingRuleSetV2(
        set_id=set_id, name=name, market=market, combination=combination,
        k=k, weights=list(weights or []), rules=rules,
    )


def rule_set_states(
    rule_set: TimingRuleSetV2,
    *,
    as_of: str | None = None,
    mode: str = "forward",
    market: str | None = None,
    previous: SignalState | None = None,
) -> list[SignalState]:
    """룰셋의 팩터별 3-상태 판정. 룰 하나당 정확히 하나.

    ★조합(`combine`) 이전까지의 파생을 여기 한 곳에 모아 둔다★
    `evaluate_rule_set`(단독 평가)과 `macro_overlay.three_way`(3자 비교)가 **같은** 상태
    배열을 써야 한다. Phase 7b 전까지 이 계산은 `evaluate_rule_set` 안에 인라인되어 있었고,
    3자 비교는 `states` 를 인자로 받기만 했으므로 호출자가 그 파생을 각자 재현해야 했다 —
    두 경로가 갈라지면 "타이밍 단독" 과 "타이밍+매크로" 가 서로 다른 신호를 비교하게 되는데,
    그건 비교가 아니다.
    """
    if mode not in EVALUATION_MODES:
        raise ValueError(
            f"알 수 없는 평가 모드: {mode!r}. 가능한 값: {', '.join(EVALUATION_MODES)}")

    mkt = market or rule_set.market
    readings: list[FactorReading] = []
    for rule in rule_set.rules:
        base = rule.base
        universe = list(getattr(base, "universe", []) or [])
        readings.append(read_factor(
            rule.factor_id,
            as_of=as_of,
            ticker=universe[0] if universe else None,
            market=mkt,
            params=dict(getattr(base, "params", {}) or {}),
        ))

    if mode == "backtest":
        # 판정 전에 거부한다 — 부적격 데이터로 만든 숫자가 남는 것 자체가 오염이다.
        assert_readings_backtest_eligible(readings)

    return [
        state_for_factor(r.factor_id, r.value, threshold=rule.threshold,
                         hysteresis=rule.hysteresis, previous=previous)
        for rule, r in zip(rule_set.rules, readings)
    ]


def evaluate_rule_set(
    rule_set: TimingRuleSetV2,
    *,
    as_of: str | None = None,
    mode: str = "forward",
    market: str | None = None,
    previous: SignalState | None = None,
) -> CompositeSignal:
    """룰셋 하나를 평가한다.

    mode="backtest" 면 **판정 전에** 게이트를 통과해야 한다 — 값을 계산한 뒤 거부해도
    늦지 않지만, 부적격 데이터로 만든 숫자가 로그·캐시에 남는 것 자체가 오염이다.
    mode="forward" 는 거부하지 않는다(실시간 판단은 결측을 안고 가야 한다) — 대신 결측은
    보수적으로 위험-오프로 접힌다.

    팩터별 판정은 `rule_set_states()` 가 담당한다 — 3자 비교와 같은 파생을 쓰기 위한 것이다.
    """
    states = rule_set_states(
        rule_set, as_of=as_of, mode=mode, market=market, previous=previous)
    return combine(states, method=rule_set.combination, k=rule_set.k,
                   weights=list(rule_set.weights) or None)
