"""글라이드패스 — ★곡선은 선언, 지점은 관측★ (AO1)
==============================================================================
설계: `docs/plans` AO · 로드맵 P2 · 관측 구간 `src/engine/risky_share.py`(AD3) ·
기간 입력 `src/domain/investor_profile.py`(AD2) · 롤업 `src/engine/glide_evidence.py`

## 왜 이 모듈이 생겼나

로드맵 P2 가 이 칸을 **"★설계만★ — 코드 없음"** 으로 남기고 사유를 적었다:
*"계좌 유형이 없는 상태에서 만들면 걸 곳이 없다."* AD1(계좌 4종) · AD2(기간 입력) ·
AD3(위험자산 비중 구간)이 생기면서 그 차단이 해소됐다.

## ★AD3 의 규율을 그대로 잇는다★

`risky_share.py` 가 갈라 둔 것과 같은 모양이다:

    ① 잔여 기간은 얼마인가       ← **관측**. 날짜 산수라 결정론적이다.
    ② 어떤 곡선을 그릴 것인가     ← ★투자 판단·상품 설계. 요청이 선언한다★

★이름 있는 프리셋을 코드가 들지 않는다★ — 드는 순간 이 모듈이 "이 곡선이 옳다" 고
**주장**한다. AD3 의 문장 그대로다: *"계산해 놓고 '참고용' 이라고 적는 것보다 아예
내지 않는 것이 정직하다."* 테스트가 이 계약을 AST 로 건다.

## ★보간만 한다. 외삽하지 않는다★

곡선 범위 밖이면 끝점으로 **고정하고 그 사실을 사유에 적는다.** 조용히 직선을
연장하면 운영자가 선언하지 않은 구간을 지어내는 것이다.

## ★목표가 관측 구간 **안**에 있으면 격차는 `0` 이 아니라 미상★

AD3 의 미배정분 때문에 위험자산 비중은 점이 아니라 **구간**이다. 목표가 그 구간
안에 들어오면 우리는 **부호조차 모른다** — 점 하나로 "0 입니다" 라고 말하면
그것이 `CLAUDE.md` §4 의 `미상 ≠ 0` 위반이다.

## ★이 모듈이 주장하지 않는 것★

- **어떤 글라이드패스가 옳은지 말하지 않는다.** 곡선은 입력이다.
- **비중을 바꾸지 않는다.** 격차를 말할 뿐이고 최적화기는 이 목표를 모른다
  (`CLAUDE.md` §3 — 배분 결정 경로는 별도 승인 사항).
- **연금 세제·한도를 알지 않는다.** 그것은 `account_policy`(AD1)의 일이고, 그쪽도
  수치를 들지 않는다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Any

#: 관측 구간 **전체**가 목표보다 위 — 위험자산이 목표보다 많다.
GAP_ABOVE = "above"
#: 관측 구간 **전체**가 목표보다 아래.
GAP_BELOW = "below"
#: ★목표가 구간 안에 있거나 전제가 빠졌다 — 부호를 모른다★
GAP_UNKNOWN = "unknown"

GAP_STATES = (GAP_ABOVE, GAP_BELOW, GAP_UNKNOWN)

_DAYS_PER_YEAR = 365.25
#: 두 입력이 이보다 더 벌어지면 "어긋났다" 고 본다. 관대하게 잡는다 —
#: 목표 연도는 연 단위라 같은 뜻이어도 반년쯤은 차이 난다.
_DISAGREE_YEARS = 1.5

_NO_HORIZON = (
    "투자기간이 선언되지 않았습니다 — `horizon_days` 도 `target_retirement_year` 도 "
    "없습니다. ★기본값으로 채우지 않았습니다.★")
_BAD_HORIZON = "투자기간 입력이 올바르지 않습니다(정수 일수여야 합니다): {!r}"
_PASSED = ("목표 시점이 이미 지났습니다 — 잔여 기간을 0 으로 봅니다. 음수를 곡선에 "
           "넣지 않습니다.")
_DISAGREE = ("`horizon_days`({:.1f}년)와 `target_retirement_year`({:.1f}년)가 "
             "★어긋납니다★ — 어느 쪽이 맞는지 이 저장소가 정하지 않습니다. "
             "하나만 주시거나 둘을 맞춰 주십시오.")

_NO_CURVE = ("글라이드패스 곡선이 선언되지 않았습니다(점 2개 이상 필요) — "
             "★어떤 곡선을 그릴지는 투자 판단이라 이 저장소가 정할 수 없습니다.★")
_DUP_YEAR = ("곡선에 같은 연차가 두 번 있고 목표가 다릅니다: {}년 — 어느 쪽이 "
             "맞는지 정하지 않습니다.")
_CLAMP_HI = ("잔여 {:.1f}년은 선언된 곡선의 범위({:.1f}년) 밖입니다 — 가장 먼 점의 "
             "목표로 **고정**했습니다. ★외삽하지 않습니다.★")
_CLAMP_LO = ("잔여 {:.1f}년은 선언된 곡선의 범위({:.1f}년) 밖입니다 — 가장 가까운 "
             "점의 목표로 **고정**했습니다. ★외삽하지 않습니다.★")

_GAP_MISSING = "목표 또는 관측 비중이 없어 격차를 낼 수 없습니다."
_GAP_INVERTED = "관측 구간이 뒤집혀 있습니다(lo > hi) — 호출부를 확인하십시오."
_GAP_STRADDLE = ("목표가 관측 **구간 안**에 있습니다 — 미배정 자산군 때문에 격차의 "
                 "★부호조차 알 수 없습니다★. 0 이 아니라 미상입니다.")

_NOTE = (
    "이 판정은 **선언된 곡선** 위의 지점과 **관측된 비중 구간**의 격차만 말합니다. "
    "★곡선이 적절한지는 말하지 않습니다★ — 어떤 글라이드패스를 쓸 것인가는 투자 "
    "판단이고 요청이 선언한 것입니다. 그리고 이 값은 관측일 뿐이라 ★최적화기는 이 "
    "목표를 모른 채 해를 냅니다★.")


@dataclass(frozen=True)
class GlidePoint:
    """곡선 위의 한 점 — `잔여 n년일 때 위험자산 목표 p%`. ★동결★"""

    years_to_target: float
    risky_target_pct: float


def _finite(x: Any) -> float | None:
    if x is None or isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    v = float(x)
    return v if math.isfinite(v) else None


def years_remaining(*, horizon_days: Any = None,
                    target_retirement_year: Any = None,
                    today: date | None = None) -> tuple[float | None, str | None]:
    """잔여 기간(년). ★관측이다 — 없으면 지어내지 않는다★

    두 입력은 `InvestorProfile`(AD2)이 이미 갖고 있는 필드다. 둘 다 주면
    **대조**하고, 어긋나면 ★평균 내거나 하나를 조용히 고르지 않는다★.
    """
    day = today or date.today()
    from_days: float | None = None
    from_year: float | None = None
    passed = False

    if horizon_days is not None:
        if isinstance(horizon_days, bool) or not isinstance(horizon_days, int) \
                or horizon_days < 0:
            return None, _BAD_HORIZON.format(horizon_days)
        from_days = horizon_days / _DAYS_PER_YEAR

    if target_retirement_year is not None:
        if isinstance(target_retirement_year, bool) \
                or not isinstance(target_retirement_year, int):
            return None, _BAD_HORIZON.format(target_retirement_year)
        delta = (date(target_retirement_year, 1, 1) - day).days / _DAYS_PER_YEAR
        if delta <= 0:
            from_year, passed = 0.0, True
        else:
            from_year = delta

    if from_days is None and from_year is None:
        return None, _NO_HORIZON
    if from_days is not None and from_year is not None:
        if abs(from_days - from_year) > _DISAGREE_YEARS:
            return None, _DISAGREE.format(from_days, from_year)
        return from_year, (_PASSED if passed else None)
    if from_year is not None:
        return from_year, (_PASSED if passed else None)
    return from_days, None


def target_at(points: Any, years: float | None) -> tuple[float | None, str | None]:
    """곡선 위의 목표 비중. ★보간만 한다 — 외삽하지 않는다★

    선언이 없거나(점 2개 미만) 잔여 기간을 모르면 **값을 내지 않는다**.
    """
    if years is None:
        return None, "잔여 기간을 모르므로 곡선 위의 지점을 정할 수 없습니다."
    if not points or len(list(points)) < 2:
        return None, _NO_CURVE

    pts = sorted(points, key=lambda p: float(p.years_to_target))
    xs = [float(p.years_to_target) for p in pts]
    ys = [float(p.risky_target_pct) for p in pts]

    # ★같은 연차에 다른 목표 — 우리가 고르지 않는다★
    for i in range(1, len(xs)):
        if xs[i] == xs[i - 1] and ys[i] != ys[i - 1]:
            return None, _DUP_YEAR.format(xs[i])

    y = float(years)
    if y <= xs[0]:
        return ys[0], (None if y == xs[0] else _CLAMP_LO.format(y, xs[0]))
    if y >= xs[-1]:
        return ys[-1], (None if y == xs[-1] else _CLAMP_HI.format(y, xs[-1]))

    for i in range(1, len(xs)):
        if y <= xs[i]:
            span = xs[i] - xs[i - 1]
            if span <= 0:                       # ★수치 안전★ 0 나눗셈 가드
                return ys[i], None
            t = (y - xs[i - 1]) / span
            return ys[i - 1] + t * (ys[i] - ys[i - 1]), None
    return ys[-1], None                          # 도달하지 않는다(위 분기가 덮는다)


def gap_interval(target_pct: Any, observed_lo: Any,
                 observed_hi: Any) -> dict[str, Any]:
    """`관측 − 목표` 를 **구간**으로. ★점으로 접지 않는다★

    양수면 위험자산이 목표보다 **많다**(줄여야 한다), 음수면 **적다**.
    ★목표가 구간 안이면 부호조차 모르므로 `unknown` 이고 `0` 이 아니다.★
    """
    t, lo, hi = _finite(target_pct), _finite(observed_lo), _finite(observed_hi)
    if t is None or lo is None or hi is None:
        return {"state": GAP_UNKNOWN, "lo": None, "hi": None, "sign": None,
                "reason": _GAP_MISSING}
    if lo > hi:
        return {"state": GAP_UNKNOWN, "lo": None, "hi": None, "sign": None,
                "reason": _GAP_INVERTED}

    g_lo, g_hi = lo - t, hi - t
    if g_lo > 0:
        state, sign = GAP_ABOVE, 1
    elif g_hi < 0:
        state, sign = GAP_BELOW, -1
    else:
        return {"state": GAP_UNKNOWN, "lo": g_lo, "hi": g_hi, "sign": None,
                "reason": _GAP_STRADDLE}
    return {"state": state, "lo": g_lo, "hi": g_hi, "sign": sign, "reason": None}


def glide_label(*, years: float | None, years_reason: str | None,
                curve: Any, observed_lo: Any,
                observed_hi: Any) -> dict[str, Any]:
    """응답에 싣는 블록 — ★전제와 그 상태를 함께 낸다★"""
    target, curve_reason = target_at(curve, years)
    gap = gap_interval(target, observed_lo, observed_hi)
    return {
        "years_remaining": years,
        "years_reason": years_reason,
        "target_pct": target,
        "curve_reason": curve_reason,
        "observed": {"lo": _finite(observed_lo), "hi": _finite(observed_hi)},
        "gap": gap,
        "note": _NOTE,
    }
