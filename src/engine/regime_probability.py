"""국면확률의 출처 계약 — ★배분에 닿을 수 있는 것은 하나뿐★ (MS1-a)
==============================================================================
계획: `docs/plans/2026-08-25-macro-vnext-plan.md` §1.5

★왜 이 모듈이 필요한가★
이 저장소는 같은 4국면 분류체계 위에 확률 객체를 **셋** 갖고 있고, 오늘 실측값이
전부 다르다:

| 출처 | 코드 | 오늘 Goldilocks |
|---|---|---|
| 축 확률 (filtered) | `regime_axes.quadrant_probs(g, i, se_g, se_i)` | 0.535 |
| Markov filtered    | `regime_ensemble._markov_probs`               | 0.964 |
| k단계 예측         | `regime_transitions.k_step_forecast`          | 0.601 |

그런데 포트폴리오에는 **넷째** — `regime_path` 의 하드 라벨, 즉 **1.000** — 이 간다.

셋 중 배분에 쓸 수 있는 것은 **k단계 예측뿐**이다. 보유기간 동안의 수익은 그 기간의
국면이 만들지 오늘의 국면이 만들지 않기 때문이고, 그리고 그 예측만이 워크포워드로
**적중률이 실측돼 있기** 때문이다(`regime_forecast.forecast_coverage`).

★`smoothed` 는 네 번째 후보가 아니라 금지 대상이다★ 마지막 시점에서만 filtered 와
같으므로, 과거 경로를 `smoothed[t]` 로 만들면 look-ahead 다. 그래서 마지막 시점
단건 조회조차 **`filtered_markov` 로 이름 붙인다** — `"smoothed"` 라는 문자열이
배분 근처에 나타나지 않는 것이 이 모듈의 설계 목표 중 하나다.

★이름이 아니라 값으로 거른다★
"이름에 forecast 가 들어가면 통과" 같은 규약은 리팩터 한 번에 조용히 깨지고, 깨진
것이 화면으로는 보이지 않는다. `usage` 는 **생성 함수가 정하며 호출자가 바꿀 수
없고**(frozen dataclass), 우회해 위조하더라도 `source` 가 남아 있어 배분 경로가
다시 거부한다 — 신뢰가 아니라 검사다.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

#: 배분에 쓸 수 있다. `k_step_forecast` 산출물만 받는다.
USAGE_PORTFOLIO = "portfolio"
#: 화면·진단 전용. 배분 경로가 거부한다.
USAGE_DIAGNOSTIC = "diagnostic_only"
#: 백테스트에서 쓰면 look-ahead. 어디서도 배분에 쓰지 않는다.
USAGE_FORBIDDEN = "forbidden_in_backtest"

SOURCE_FORECAST = "k_step_forecast"
SOURCE_AXIS = "filtered_axis"
SOURCE_MARKOV = "filtered_markov"
SOURCE_SMOOTHED = "smoothed_markov"

#: ★배분이 받아들이는 출처의 화이트리스트★ 새 출처를 추가하면 여기에 넣을지
#: **의식적으로** 결정하게 된다. 기본은 거부다.
_PORTFOLIO_SOURCES = frozenset({SOURCE_FORECAST})


def _sharpness(probs: dict[str, float]) -> float | None:
    """`1 − H(π)/ln R` — 1.0 이면 확정, 0.0 이면 완전 균등.

    ★적중률과 함께 읽어야 하는 값이다★ 예측집합을 키우면 적중률은 언제든 오른다.
    실측 k=3 에서 0.206(퍼플렉서티 3.007)이고, 하드 라벨은 1.0 이다.
    """
    vals = [float(v) for v in probs.values() if v is not None]
    n = len(vals)
    if n < 2:
        return None
    total = sum(vals)
    if total <= 0:
        return None
    h = 0.0
    for v in vals:
        p = v / total
        if p > 0:
            h -= p * math.log(p)
    return max(0.0, min(1.0, 1.0 - h / math.log(n)))


@dataclass(frozen=True)
class RegimeProbabilities:
    """국면확률 + **그것을 어디에 쓸 수 있는지**.

    frozen 인 이유는 불변성이 예뻐서가 아니라, `usage` 를 호출부에서 고쳐 배분에
    밀어 넣는 경로를 막기 위해서다.
    """

    source: str
    step_months: int
    probs: dict[str, float]
    usage: str
    mode: str = "live"
    ci90: dict[str, list[float]] | None = None
    coverage: dict[str, Any] | None = None
    note: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def sharpness(self) -> float | None:
        return _sharpness(self.probs)

    @property
    def argmax(self) -> str | None:
        return max(self.probs, key=self.probs.get) if self.probs else None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["sharpness"] = self.sharpness
        d["argmax"] = self.argmax
        return d


def require_portfolio_source(prob: RegimeProbabilities) -> RegimeProbabilities:
    """배분 경로의 문지기. 통과하면 그대로 돌려주고, 아니면 **올린다**.

    ★조용히 폴백하지 않는다★ 잘못된 출처가 배분에 닿는 것은 응답을 조금 다르게
    만드는 정도의 사고가 아니라, look-ahead 이거나 "오늘 국면 = 보유기간 국면" 이라는
    가정을 몰래 되살리는 일이다. 그런 것은 예외로 터뜨려야 한다.
    """
    if not isinstance(prob, RegimeProbabilities):
        raise ValueError("국면확률 객체가 아닙니다 — 배분 경로는 출처가 선언된 "
                         "RegimeProbabilities 만 받습니다.")
    if prob.source not in _PORTFOLIO_SOURCES:
        raise ValueError(
            f"'{prob.source}' 는 배분에 쓸 수 없습니다 — 배분은 보유기간의 국면을 "
            f"묻는데 이 출처는 현재(또는 과거) 국면을 답합니다. "
            f"`k_step_forecast` 산출물만 허용됩니다.")
    if prob.usage != USAGE_PORTFOLIO:
        raise ValueError(
            f"'{prob.source}' 의 usage 가 '{prob.usage}' 입니다 — 배분에 쓸 수 없습니다.")
    return prob


def from_k_step_forecast(rows: list[dict], current: str, k: int, *,
                         mode: str = "live",
                         coverage: dict[str, Any] | None = None
                         ) -> RegimeProbabilities:
    """`regime_transitions.k_step_forecast` → 배분 가능 확률.

    ★이것이 유일하게 `usage = portfolio` 를 받는 생성자다.★ 사후예측 구간(`ci90`)을
    버리지 않고 함께 싣는다 — 얇은 행의 불확실성이 여기까지 전달된 결과물이다.
    """
    from src.engine.regime_transitions import k_step_forecast

    fc = k_step_forecast(rows, current, k=k)
    if not fc.get("available"):
        raise ValueError(f"k단계 국면예측을 만들 수 없습니다: {fc.get('reason')}")
    return RegimeProbabilities(
        source=SOURCE_FORECAST,
        step_months=int(k),
        probs={str(r): float(v) for r, v in fc["mean"].items()},
        usage=USAGE_PORTFOLIO,
        mode=mode,
        ci90=fc.get("ci90"),
        coverage=coverage,
        note=fc.get("note"),
        detail={"from": fc.get("from"), "draws": fc.get("draws")},
    )


def from_axis(block: dict, *, mode: str = "live") -> RegimeProbabilities:
    """`regime_ensemble._axis_probs` → **진단 전용**.

    축 z 와 그 표준오차로 만든 사분면 확률이다. "지금 어디인가" 에는 답하지만
    "보유기간 동안 어디일까" 에는 답하지 않으므로 배분에 쓰지 않는다.
    """
    return RegimeProbabilities(
        source=SOURCE_AXIS, step_months=0,
        probs={str(r): float(v) for r, v in (block.get("probs") or {}).items()},
        usage=USAGE_DIAGNOSTIC, mode=mode,
        note="축 z 와 표준오차 기반 현재 국면 분포 — 화면 전용입니다.",
        detail=dict(block.get("detail") or {}),
    )


def from_markov(block: dict, *, mode: str = "live") -> RegimeProbabilities:
    """`regime_ensemble._markov_probs` → **진단 전용**.

    성장축 2상태 × 물가축 하드 부호이므로 4국면 중 **둘은 구조적으로 정확히 0** 이다.
    그 성질만으로도 배분에 쓸 수 없다 — 없는 국면이 아니라 모형이 표현하지 못하는
    국면이기 때문이다.
    """
    return RegimeProbabilities(
        source=SOURCE_MARKOV, step_months=0,
        probs={str(r): float(v) for r, v in (block.get("probs") or {}).items()},
        usage=USAGE_DIAGNOSTIC, mode=mode,
        note=("Hamilton 상태전환(성장축 2상태) × 물가축 부호 — 4국면 중 둘은 "
              "구조적으로 0입니다. 화면 전용입니다."),
        detail=dict(block.get("detail") or {}),
    )


def from_smoothed(probs: dict[str, float], *, t_index: int,
                  t_last: int | None = None,
                  mode: str = "live") -> RegimeProbabilities:
    """평활확률 → ★금지★ (마지막 시점만 `filtered_markov` 로 개명).

    `smoothed[T−1] == filtered[T−1]` 이므로 마지막 시점은 look-ahead 가 아니다.
    그럴 때는 **filtered 라고 부른다** — 이름이 곧 경고이고, `"smoothed"` 라는
    문자열이 배분 근처에 있으면 다음 사람이 과거 경로에도 쓰게 된다.
    """
    is_last = t_last is not None and int(t_index) == int(t_last)
    return RegimeProbabilities(
        source=SOURCE_MARKOV if is_last else SOURCE_SMOOTHED,
        step_months=0,
        probs={str(r): float(v) for r, v in (probs or {}).items()},
        usage=USAGE_DIAGNOSTIC if is_last else USAGE_FORBIDDEN,
        mode=mode,
        note=("마지막 시점이라 filtered 와 동일합니다." if is_last else
              "전체 표본으로 평활한 과거 확률입니다 — 백테스트에 쓰면 look-ahead 입니다."),
        detail={"t_index": int(t_index)},
    )


def disagreement_block(*, portfolio: RegimeProbabilities,
                       diagnostics: list[RegimeProbabilities]) -> dict[str, Any]:
    """배분에 쓴 확률과 진단 확률들을 **함께** 낸다.

    ★하나를 골라 나머지를 지우지 않는다★ 오늘 실측만 봐도 0.535 · 0.964 · 0.601 로
    갈린다. 그 불일치는 숨길 것이 아니라 사람이 봐야 할 사실이고, 크게 갈릴수록
    확신을 낮출 근거다.
    """
    require_portfolio_source(portfolio)
    keys = set(portfolio.probs)
    gaps = []
    for d in diagnostics:
        common = keys & set(d.probs)
        if common:
            gaps.append(max(abs(portfolio.probs[k] - d.probs[k]) for k in common))
    return {
        "portfolio": portfolio.to_dict(),
        "diagnostics": [d.to_dict() for d in diagnostics],
        "max_abs_gap": round(max(gaps), 6) if gaps else None,
        "note": ("배분에는 k단계 예측만 씁니다. 나머지는 같은 분류체계 위의 다른 "
                 "질문에 대한 답이며, 크게 갈리면 확신을 낮출 근거로 읽으십시오."),
    }
