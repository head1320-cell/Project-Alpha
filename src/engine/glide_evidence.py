"""글라이드패스 증거 롤업 — ★전제 넷이 다 선언돼야 판정이 선다★ (AO3)
==============================================================================
설계: `docs/plans` AO · 롤업 `src/engine/run_evidence.rollup`(★`pit_evidence`·
`decision_evidence`·`estimator_evidence`·`multiplicity_evidence`·
`cost_model_registry`·`attribution_evidence`·`version_registry`·
`allocation_evidence` 와 **같은 함수** — 아홉 번째 호출자★)

## 무엇을 답하나 — *"이 글라이드패스 판정을 믿어도 되나"*

AO1·AO2 가 산수를 하고, 이 모듈은 **그 산수가 어떤 전제 위에 섰는지**를 넷으로
갈라 말한다. 넷은 서로 다른 계층이 만든다:

    horizon        기간     `domain/investor_profile`(AD2) → `glide_path.years_remaining`
    curve          곡선     ★요청이 선언한다★ — 이 저장소는 곡선을 갖지 않는다
    risky_class    분류     `engine/risky_share`(AD3) — 역시 요청이 선언한다
    contribution   적립     `domain/contribution`(AO2) — 계획(실적 아님)

★규칙을 새로 만들지 않는다★ 각 축의 사유는 이미 그 축의 주인이 썼다. 여기서 하는
일은 그것을 **공통 세 상태로 옮겨 하나로 접는 것**뿐이다(`run_evidence` 머리글과
같은 규율).

## ★미상은 통과가 아니다★

축 하나만 미선언이어도 롤업은 `verified` 가 되지 않는다. 곡선을 선언하지 않은
요청에 목표 비중이 나오면 이 저장소가 *"이 곡선이 옳다"* 고 **주장**하는 것이고,
그것이 AD3 이 막은 바로 그 자리다.

## ★`degraded` 와 `unknown` 을 가른다★

| 축 | `degraded` (관측된 결함) | `unknown` (재지 못함) |
|---|---|---|
| `horizon` | 목표 시점이 이미 지났다 | 미선언이거나 두 입력이 어긋난다 |
| `curve` | 잔여 기간이 곡선 범위 밖(끝점 고정) · 같은 연차 중복 | 점이 2개 미만 |
| `risky_class` | 미배정분이 있다 · 모르는 자산군 이름이 섞였다 | 미선언이거나 보유가 없다 |
| `contribution` | 이 적립이 격차를 **벌린다** | 대상 미선언 · 방향 미상 · 전제 부족 |

## ★이 모듈이 주장하지 않는 것★

- **어떤 곡선이 옳은지 말하지 않는다.** 선언됐는지만 본다.
- **비중을 바꾸지 않는다.** 관측·기록만 한다(`CLAUDE.md` §3 — 배분 결정 경로는
  별도 승인 사항이고 이 프로그램은 0줄 건드린다).
- **`verified` 가 도달을 보증하지 않는다.** 넷이 다 선언됐다는 뜻이지, 계획대로
  납입된다거나 시세가 그대로라는 뜻이 아니다.
"""
from __future__ import annotations

from typing import Any

from src.domain.contribution import (
    DIRECTION_CLOSES,
    DIRECTION_WIDENS,
)
from src.engine.run_evidence import (
    AXIS_DEGRADED,
    AXIS_OK,
    AXIS_UNKNOWN,
    rollup,
)

AXIS_HORIZON = "horizon"
AXIS_CURVE = "curve"
AXIS_RISKY_CLASS = "risky_class"
AXIS_CONTRIBUTION = "contribution"

#: ★축은 넷 전부 항상 적용된다★ — 하나라도 빠지면 "문제없다" 로 읽힌다.
GLIDE_AXES = (AXIS_HORIZON, AXIS_CURVE, AXIS_RISKY_CLASS, AXIS_CONTRIBUTION)

GLIDE_AXIS_LABELS = {
    AXIS_HORIZON: "잔여 기간",
    AXIS_CURVE: "선언된 곡선",
    AXIS_RISKY_CLASS: "위험자산 분류",
    AXIS_CONTRIBUTION: "적립 계획",
}

_HORIZON_UNKNOWN = ("잔여 기간을 정하지 못했습니다 — ★미상은 0 이 아닙니다.★")
_CURVE_NONE = ("글라이드패스 곡선이 선언되지 않았습니다(점 {}개, 2개 이상 필요) — "
               "★어떤 곡선을 그릴지는 투자 판단이라 이 저장소가 정할 수 없습니다.★")
_CURVE_DUP = ("곡선에 같은 연차가 두 번 있고 목표가 다릅니다: {}년 — 선언 자체가 "
              "자기모순이라 지점을 정할 수 없습니다.")
_CURVE_CLAMP = ("잔여 {:.1f}년이 선언된 곡선의 범위({:.1f}~{:.1f}년) 밖입니다 — "
                "끝점 목표로 **고정**했습니다. ★외삽하지 않았고, 고정한 값은 "
                "선언된 값이 아닙니다.★")
_RISKY_NONE = ("위험자산 비중 관측이 없습니다 — 분류가 선언되지 않았거나 잴 보유가 "
               "없습니다.")
_RISKY_UNASSIGNED = ("보유의 {:.1f}% 가 자산군 미배정이라 위험자산 비중이 점이 "
                     "아니라 **구간**입니다 — ★미배정을 0 으로 접지 않았습니다.★")
_RISKY_UNKNOWN_NAMES = ("선언에 알 수 없는 자산군 이름이 있습니다: {} — 그 이름은 "
                        "비중에 반영되지 않았습니다.")
_CONTRIB_NONE = ("적립 계획이 선언되지 않았습니다 — 적립액·대상이 없으면 도달을 "
                 "잴 수 없습니다.")

_NOTE = (
    "이 판정은 **이 요청이 어떤 전제를 선언했는가**만 말합니다. ★목표에 도달한다는 "
    "뜻도, 이 곡선이 적절하다는 뜻도 아닙니다★ — 곡선과 위험자산 분류는 요청이 "
    "선언한 것이고 이 저장소는 그것이 옳은지 판정하지 않습니다. 개월 수는 매도 "
    "없이·수익률 없이 계산한 산수이며, ★최적화기는 이 목표를 모른 채 해를 냅니다★ "
    "— 비중을 바꾸는 경로는 이 판정을 읽지 않습니다.")


def _axis(state: str, reason: str | None, **detail: Any) -> dict[str, Any]:
    return {"state": state, "reason": reason, **detail}


def horizon_axis(years: Any, reason: str | None) -> dict[str, Any]:
    """기간 축 — `glide_path.years_remaining` 의 두 값을 그대로 옮긴다.

    ★값과 사유가 함께 온다★ 값이 있는데 사유도 있는 경우는 하나뿐이다 —
    목표 시점이 이미 지나 0 으로 본 경우. 그것은 미상이 아니라 **관측된 결함**이다.
    """
    if years is None:
        return _axis(AXIS_UNKNOWN, reason or _HORIZON_UNKNOWN, years=None)
    if reason:
        return _axis(AXIS_DEGRADED, reason, years=float(years))
    return _axis(AXIS_OK, None, years=float(years))


def curve_axis(curve: Any, years: Any = None) -> dict[str, Any]:
    """곡선 축 — ★선언을 본다. 기간을 모르는 것은 기간 축의 결함이다★

    `years` 를 주면 **이 요청의 잔여 기간을 곡선이 덮는지**까지 본다. 덮지 못하면
    `target_at` 이 끝점으로 고정했다는 뜻이고, 고정한 값은 선언된 값이 아니므로
    `degraded` 다.
    """
    pts = list(curve or [])
    if len(pts) < 2:
        return _axis(AXIS_UNKNOWN, _CURVE_NONE.format(len(pts)),
                     points=len(pts), range=None, clamped=False)

    ordered = sorted(pts, key=lambda p: float(p.years_to_target))
    xs = [float(p.years_to_target) for p in ordered]
    ys = [float(p.risky_target_pct) for p in ordered]
    span = {"lo": xs[0], "hi": xs[-1]}

    for i in range(1, len(xs)):
        if xs[i] == xs[i - 1] and ys[i] != ys[i - 1]:
            return _axis(AXIS_DEGRADED, _CURVE_DUP.format(xs[i]),
                         points=len(pts), range=span, clamped=False)

    if years is not None and not (xs[0] <= float(years) <= xs[-1]):
        return _axis(AXIS_DEGRADED,
                     _CURVE_CLAMP.format(float(years), xs[0], xs[-1]),
                     points=len(pts), range=span, clamped=True)

    return _axis(AXIS_OK, None, points=len(pts), range=span, clamped=False)


def risky_class_axis(risky: Any) -> dict[str, Any]:
    """분류 축 — `risky_share.risky_share_interval` 의 결과를 옮긴다(AD3).

    ★판정하지 않고 번역한다★ 사유는 AD3 이 쓴 것을 그대로 싣는다 — 여기서 다시
    쓰면 같은 사실에 두 문장이 생기고, 한쪽만 고쳐도 아무 테스트가 깨지지 않는다.
    """
    if not isinstance(risky, dict) or not risky.get("available") \
            or risky.get("interval") is None:
        reason = (risky or {}).get("reason") if isinstance(risky, dict) else None
        return _axis(AXIS_UNKNOWN, reason or _RISKY_NONE,
                     unassigned_pct=None, unknown_classes=[])

    unknown_names = list(risky.get("unknown_classes") or [])
    unassigned = float(risky.get("unassigned_pct") or 0.0)
    detail = {"unassigned_pct": unassigned, "unknown_classes": unknown_names}

    if unknown_names:
        return _axis(AXIS_DEGRADED,
                     risky.get("reason") or _RISKY_UNKNOWN_NAMES.format(unknown_names),
                     **detail)
    if unassigned > 0:
        return _axis(AXIS_DEGRADED, _RISKY_UNASSIGNED.format(unassigned), **detail)
    return _axis(AXIS_OK, risky.get("reason"), **detail)


def contribution_axis(contribution: Any) -> dict[str, Any]:
    """적립 축 — `contribution.months_to_close` 의 결과를 옮긴다(AO2).

    ★`widens` 는 미상이 아니라 결함이다★ 방향이 반대라는 것은 **관측된 사실**이고,
    미상으로 접으면 "재지 못했다" 와 구별되지 않는다.
    """
    if not isinstance(contribution, dict):
        return _axis(AXIS_UNKNOWN, _CONTRIB_NONE, direction=None, months=None)

    direction = contribution.get("direction")
    detail = {"direction": direction, "months": contribution.get("months")}
    if contribution.get("available") and direction == DIRECTION_CLOSES:
        return _axis(AXIS_OK, None, **detail)
    if direction == DIRECTION_WIDENS:
        return _axis(AXIS_DEGRADED, contribution.get("reason"), **detail)
    return _axis(AXIS_UNKNOWN, contribution.get("reason") or _CONTRIB_NONE, **detail)


def glide_evidence(*, years: Any = None, years_reason: str | None = None,
                   curve: Any = None, risky: Any = None,
                   contribution: Any = None) -> dict[str, Any]:
    """전제 넷 → 하나의 판정. ★축은 절대 사라지지 않는다★

    Returns:
        `{status, axes, applicable, ok_axes, broken_axes, unknown_axes,
          summary, note}` — `run_evidence.rollup` 과 **같은 모양**이다.
    """
    axes: dict[str, dict | None] = {
        AXIS_HORIZON: horizon_axis(years, years_reason),
        AXIS_CURVE: curve_axis(curve, years),
        AXIS_RISKY_CLASS: risky_class_axis(risky),
        AXIS_CONTRIBUTION: contribution_axis(contribution),
    }
    return {**rollup(axes, GLIDE_AXIS_LABELS), "note": _NOTE}
