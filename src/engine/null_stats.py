"""널 분포 통계 — ★"얼마나 큰가" 가 아니라 "널 안에서 어디인가"★ (M2)
==============================================================================
음성 통제가 묻는 것은 크기가 아니라 **위치**다. 진짜 팔이 무작위 팔들의 분포
안에 있으면, 그 산출은 신호 없이도 나온다는 뜻이다.

★이 모듈이 생긴 이유★ S6(`85a84d1`)이 기업 뷰 통제에서 같은 산수를
`company_view_controls.percentile_of` 와 `scripts/company_view_control._side` 에
두 벌 두고 있었다. 매크로 통제(M1~M5)가 세 번째 벌을 만들면 반드시 갈라지고,
갈라져도 타입 에러가 나지 않는다 — 이 저장소가 여러 번 값을 치른 실수다.
그래서 여기가 **단일 출처**이고 기존 두 이름은 얇은 위임으로 남는다.

★방향과 분위를 **하나의 비교**에서 파생시킨다★ S6 에서 값과 분위수를 따로
비교했다가 동률이 있을 때 `distinguishable=True` 인데 `side="inside"` 인 모순이
났다. 여기서는 `side_of` 가 **분위만** 본다. 값 기준의 독립적 진술은
`beyond_range` 가 따로 맡는다 — 꼬리에 겨우 걸친 것과 널이 아예 도달하지 못한
것은 증거의 세기가 다르다.
"""

from __future__ import annotations

from typing import Any

SIDE_BELOW = "below"
SIDE_INSIDE = "inside"
SIDE_ABOVE = "above"


def percentile_of(value: float, null: list[float] | Any) -> float | None:
    """진짜 팔이 널 분포의 **몇 분위**인가 (0~100). 널이 비면 `None`.

    ★없는 널에서 분위를 지어내지 않는다★ — 표본이 없다는 것과 "0분위" 는 다른
    진술이다.
    """
    xs = [float(x) for x in (null or []) if x is not None]
    if not xs:
        return None
    return round(sum(1 for x in xs if x <= float(value)) / len(xs) * 100.0, 4)


def side_of(pct: float | None, lo: float, hi: float) -> str | None:
    """널의 **어느 쪽**인가 — `below` · `inside` · `above`. 분위가 없으면 `None`.

    ★"구분된다" 가 "좋다" 로 읽히지 않게 한다★ S6 실측에서 진짜 팔은 셔플 팔들보다
    포트폴리오를 **덜** 움직였다(분위 0.0). 방향을 안 적으면 그 사실이 "통제를
    통과했다" 로 둔갑한다.
    """
    if pct is None:
        return None
    if float(pct) < float(lo):
        return SIDE_BELOW
    if float(pct) > float(hi):
        return SIDE_ABOVE
    return SIDE_INSIDE


def beyond_range(value: float | None, xs: list[float] | Any) -> bool | None:
    """값이 널의 **범위 밖**인가 — 분위보다 강한 진술. 널이 비면 `None`."""
    vals = [float(x) for x in (xs or []) if x is not None]
    if not vals or value is None:
        return None
    return bool(float(value) < min(vals) or float(value) > max(vals))


def summarize(xs: list[float] | Any) -> dict[str, Any]:
    """널 분포 요약 — `n` · `min` · `p5` · `p50` · `p95` · `max`. 비면 사유."""
    import numpy as np

    vals = [float(x) for x in (xs or []) if x is not None]
    if not vals:
        return {"n": 0, "reason": "널 표본이 없습니다"}
    a = np.asarray(vals, dtype=float)
    return {"n": int(a.size),
            "min": round(float(a.min()), 6),
            "p5": round(float(np.percentile(a, 5)), 6),
            "p50": round(float(np.median(a)), 6),
            "p95": round(float(np.percentile(a, 95)), 6),
            "max": round(float(a.max()), 6)}
