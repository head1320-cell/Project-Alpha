"""적립 — ★대상을 모르면 방향을 모른다★ (AO2)
==============================================================================
설계: `docs/plans` AO · 격차 어휘 `src/domain/glide_path.py` · 한도 판정은
`src/domain/account_policy.py`(AD1)의 일이고 ★이 모듈은 한도를 모른다★

## 이 모듈이 존재하는 이유는 **두 함정**이다

### 함정 ① 적립 대상을 모르면 방향을 모른다

*"적립하면 목표에 가까워진다"* 는 **틀린 일반화**다. 목표가 현재보다 위험자산을
**줄이는** 방향인데 위험자산에 납입하면 격차는 ★벌어진다★. 그래서
`bucket`(`risky`/`safe`)이 선언되지 않으면 도달 개월 수를 **내지 않는다**.

### 함정 ② 실적과 계획은 다른 축이다

한도 판정에 들어갈 것은 **실적**(올해 얼마 냈나)이고, 도달 계산에 들어갈 것은
**계획**(앞으로 매달 얼마)이다. 계획을 한도 관측으로 넘기면 *"아직 내지 않은 돈"*
으로 한도를 판정하게 되고 그 판정은 거짓이다. ★이 모듈은 계획만 다룬다★ —
실적은 라우트가 따로 받아 `judge_account` 로 보낸다.

## 산수 — ★매도 없이★

기존 보유를 팔지 않는다고 가정한다(연금 계좌에서 비중을 맞추는 표준적인 방법이고
매도에는 세제·수수료가 따로 붙는다). `V` 평가액 · `ρ` 현재 위험자산 비율 ·
`τ` 목표 비율 · `c` 월 적립액일 때:

    안전자산에 적립(비중을 **내린다**)   n = V(ρ−τ) / (τ·c)
    위험자산에 적립(비중을 **올린다**)   n = V(τ−ρ) / ((1−τ)·c)

둘째 식의 분모는 `τ → 1` 에서 0 이 된다 — ★위험자산 100% 는 적립만으로 도달하지
않는다★. `CLAUDE.md` §6 의 수치 안전이 요구하는 가드다.

## ★이 모듈이 주장하지 않는 것★

- **적립이 옳다고 말하지 않는다.** 선언된 계획대로라면 몇 개월인지만 답한다.
- **수익률을 가정하지 않는다.** 평가액이 그대로라는 전제이고, 그 전제를 note 가
  적는다 — 적지 않으면 숫자가 예측처럼 읽힌다.
- **한도를 보지 않는다.** 계획이 한도를 넘는지는 `judge_account` 가 판정한다.
"""
from __future__ import annotations

import math
from typing import Any

from src.domain.glide_path import GAP_ABOVE, GAP_BELOW

#: 위험자산에 납입한다(비중을 올린다).
BUCKET_RISKY = "risky"
#: 안전자산에 납입한다(비중을 내린다).
BUCKET_SAFE = "safe"
BUCKETS = (BUCKET_RISKY, BUCKET_SAFE)

#: 이 적립이 격차를 **좁힌다**.
DIRECTION_CLOSES = "closes"
#: ★벌린다★ — 대상을 잘못 고르면 적립이 목표에서 멀어지게 한다.
DIRECTION_WIDENS = "widens"
#: 방향을 모른다(격차 미상이거나 대상 미선언).
DIRECTION_UNKNOWN = "unknown"
DIRECTIONS = (DIRECTION_CLOSES, DIRECTION_WIDENS, DIRECTION_UNKNOWN)

_NO_BUCKET = ("적립 대상(`risky`/`safe`)이 선언되지 않았습니다 — ★대상을 모르면 "
              "적립이 격차를 좁히는지 벌리는지 알 수 없습니다.★")
_WIDENS = ("이 적립은 격차를 ★벌립니다★ — 목표가 지금보다 위험자산을 "
           "{}는 방향인데 {}자산에 납입하기 때문입니다. 대상을 바꾸지 않으면 "
           "도달하지 않습니다.")
_GAP_UNKNOWN = ("격차의 부호를 모릅니다(목표가 관측 구간 안이거나 전제가 "
                "빠졌습니다) — 방향을 정할 수 없으므로 개월 수를 내지 않습니다.")
_BAD_MONTHLY = "월 적립액이 없거나 0 이하입니다 — 도달 개월 수를 낼 수 없습니다."
_BAD_VALUE = "포트폴리오 평가액이 없거나 0 이하입니다 — 비율 산수를 할 수 없습니다."
_BAD_TARGET = ("목표 비중이 없거나 (0, 100) 범위 밖입니다 — 그 목표로는 적립 산수가 "
               "성립하지 않습니다.")
_UNREACHABLE = ("목표가 위험자산 100% 라 적립만으로는 ★도달하지 않습니다★ — "
                "안전자산이 남아 있는 한 비중은 100% 에 닿지 않습니다.")

_NOTE = (
    "이 개월 수는 **선언된 적립 계획**대로 냈을 때의 산수입니다 — ★계획이지 실적이 "
    "아닙니다.★ 그리고 ★기존 보유를 매도하지 않는다★ 는 전제이며, 평가액이 그대로"
    "라고 봅니다(수익률을 가정하지 않습니다). 시세가 움직이면 실제 개월 수는 "
    "달라집니다.")


def _positive(x: Any) -> float | None:
    if x is None or isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    v = float(x)
    return v if math.isfinite(v) and v > 0 else None


def contribution_direction(gap_state: Any, bucket: Any) -> str:
    """이 적립이 격차를 좁히는가 벌리는가. ★대상이 없으면 모른다★"""
    if bucket not in BUCKETS:
        return DIRECTION_UNKNOWN
    if gap_state == GAP_ABOVE:       # 위험자산이 목표보다 많다 → 내려야 한다
        return DIRECTION_CLOSES if bucket == BUCKET_SAFE else DIRECTION_WIDENS
    if gap_state == GAP_BELOW:       # 적다 → 올려야 한다
        return DIRECTION_CLOSES if bucket == BUCKET_RISKY else DIRECTION_WIDENS
    return DIRECTION_UNKNOWN


def _months_one(observed_pct: float, target_pct: float, value: float,
                monthly: float, bucket: str) -> float | None:
    """한 점에 대한 개월 수. ★분모 가드는 호출부가 아니라 여기★"""
    rho, tau = observed_pct / 100.0, target_pct / 100.0
    if bucket == BUCKET_SAFE:
        if tau <= 0:
            return None
        return value * (rho - tau) / (tau * monthly)
    denom = (1.0 - tau) * monthly
    if denom <= 0:
        return None
    return value * (tau - rho) / denom


def months_to_close(*, target_pct: Any, observed_lo: Any, observed_hi: Any,
                    monthly_krw: Any, portfolio_value_krw: Any,
                    bucket: Any) -> dict[str, Any]:
    """매도 없이 적립만으로 목표에 닿기까지 몇 개월인가. ★구간이다★

    전제가 하나라도 빠지거나 방향이 반대면 **숫자 대신 사유**를 낸다.
    """
    from src.domain.glide_path import gap_interval

    gap = gap_interval(target_pct, observed_lo, observed_hi)
    direction = contribution_direction(gap["state"], bucket)
    base = {"available": False, "months": None, "direction": direction,
            "gap": gap, "note": _NOTE}

    if bucket not in BUCKETS:
        return {**base, "reason": _NO_BUCKET}
    if direction == DIRECTION_UNKNOWN:
        return {**base, "reason": _GAP_UNKNOWN}
    if direction == DIRECTION_WIDENS:
        lowering = gap["state"] == GAP_ABOVE
        return {**base, "reason": _WIDENS.format(
            "줄이" if lowering else "늘리", "위험" if bucket == BUCKET_RISKY else "안전")}

    monthly = _positive(monthly_krw)
    value = _positive(portfolio_value_krw)
    tgt = _positive(target_pct)
    if monthly is None:
        return {**base, "reason": _BAD_MONTHLY}
    if value is None:
        return {**base, "reason": _BAD_VALUE}
    if tgt is None or tgt >= 100.0:
        return {**base, "reason": _BAD_TARGET if tgt is None or tgt <= 0
                else _UNREACHABLE if bucket == BUCKET_RISKY else _BAD_TARGET}

    ns = [_months_one(float(obs), tgt, value, monthly, bucket)
          for obs in (float(observed_lo), float(observed_hi))]
    if any(n is None or not math.isfinite(n) or n < 0 for n in ns):
        return {**base, "reason": _UNREACHABLE}

    lo, hi = sorted(float(n) for n in ns)  # type: ignore[arg-type]
    return {"available": True, "direction": direction, "gap": gap,
            "months": {"lo": lo, "hi": hi}, "reason": None, "note": _NOTE}
