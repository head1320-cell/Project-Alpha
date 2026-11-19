"""Conformal Prediction — 분포 가정 없이 커버리지를 **보장**한다 (M1-T)
==============================================================================
Split conformal: 모델을 학습셋에 맞추고, **보정셋**의 잔차 분위수로 예측 구간을 만든다.
잔차가 교환가능(exchangeable)하기만 하면 분포 가정 없이

    P( y ∈ Ĉ(x) ) ≥ 1 − α

가 **유한표본에서** 성립한다. 정규성도, 등분산도 필요 없다.

★왜 이 플랫폼에 필요한가★
------------------------------------------------------------------------------
지금 최적화는 점추정 μ 하나를 받아 비중을 낸다. μ 가 얼마나 불확실한지는 어디에도
들어가지 않으므로, 표본이 얇거나 국면이 바뀌어도 배분은 똑같이 자신 있게 나온다.
Conformal 구간은 그 불확실성을 **주장이 아니라 계산**으로 만든다.

★유한표본 한계를 숨기지 않는다★
------------------------------------------------------------------------------
보정 표본 n 개로 (1−α) 커버리지를 얻으려면 분위수 순위가
`ceil((n+1)(1−α))` 이고, 이 값이 n 을 넘으면 **유한한 구간을 만들 수 없다**
(가장 넓은 잔차로도 부족하다). 필요 표본은 `n ≥ ceil(1/α) − 1`.
예: α=0.05 → n ≥ 19, α=0.01 → n ≥ 99.

그럴 때 조용히 최대 잔차를 쓰면 "95% 구간" 이라고 적힌 구간이 실제로는 그보다 낮은
커버리지를 갖는다. 여기서는 `available: false` + 필요한 표본 수를 답한다.

★커버리지는 주장하지 않고 잰다★ `measure_coverage()` 가 실제 적중률을 세어 돌려준다.
이론값은 하한이고, 재 보는 것이 이 저장소의 규칙이다.

★시계열용 — 적응형 등각 추론(ACI · Gibbs & Candès 2021) (G7 ② · 2026-11-19)★
------------------------------------------------------------------------------
split 의 보장은 점수가 교환가능할 때만 선다. 시간 순서가 있는 쌍(리밸런스 예측 · 실현)은 국면이 바뀌면 그 가정이
깨진다. `adaptive_conformal()` 은 걸음마다 목표 놓침률을 고친다(놓치면 넓히고 덮으면 좁힌다):

    α_{t+1} = α_t + γ (α − err_t)

α_1 = α 이면 ★어떤 수열에서도 결정적으로★  |(1/T) Σ err_t − α| ≤ (max(α, 1 − α) + γ) / (γ T).
대가: 장기 평균 놓침률만 말한다(구간 하나하나의 적중이 아니다) · T 가 짧으면 상한이 자명한 폭 max(α, 1 − α) 를 넘어
공허하다 — 그 사실을 `bound.informative` 와 문장으로 함께 낸다. 유도는 계획 문서
`docs/superpowers/plans/2026-11-16-evidence-and-trader-ux.md` §7.2a · 시험은 `tests/test_conformal_adaptive.py`.
위의 split 함수 넷은 바꾸지 않았다(변경 전 동작 사진 `tests/golden/conformal_split_g7.json`).
"""

from __future__ import annotations

import bisect
import logging
import math
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


def required_calibration_size(alpha: float) -> int:
    """(1−α) 구간에 필요한 최소 보정 표본 수 — `ceil(1/α) − 1`."""
    if not (0.0 < alpha < 1.0):
        raise ValueError(f"alpha 는 0 과 1 사이여야 합니다: {alpha}")
    return math.ceil(1.0 / alpha) - 1


def conformal_quantile(residuals: np.ndarray, alpha: float = 0.1) -> dict[str, Any]:
    """보정 잔차 → 구간 반폭 `q̂`.

    잔차는 **부호 없는 크기**여야 한다(|y − ŷ|). 부호를 남기면 이 분위수는 대칭
    구간의 반폭이 아니라 한쪽 꼬리를 잰 값이 된다.

    Returns:
        `{available, q, n, rank, alpha}` 또는 `{available:false, reason, required_n}`.
    """
    r = np.asarray(residuals, dtype=float).ravel()
    r = r[np.isfinite(r)]
    n = r.size
    if n == 0:
        return {"available": False, "reason": "보정 잔차가 없습니다.", "n": 0}
    if np.any(r < 0):
        return {"available": False,
                "reason": "잔차에 음수가 있습니다 — |y − ŷ| 를 넣어야 합니다.", "n": n}

    need = required_calibration_size(alpha)
    rank = math.ceil((n + 1) * (1.0 - alpha))
    if rank > n:
        # ★조용히 최댓값으로 때우지 않는다★ 그러면 "90% 구간" 이 90% 를 못 준다.
        return {
            "available": False, "n": n, "required_n": need, "alpha": alpha,
            "reason": (f"보정 표본이 부족합니다 — {n}개로는 {1 - alpha:.0%} 커버리지를 "
                       f"유한한 구간으로 보장할 수 없습니다 (최소 {need}개 필요)."),
        }

    q = float(np.sort(r)[rank - 1])
    return {"available": True, "q": q, "n": n, "rank": rank, "alpha": alpha}


def split_conformal(
    cal_actual: np.ndarray, cal_pred: np.ndarray,
    test_pred: np.ndarray, alpha: float = 0.1,
) -> dict[str, Any]:
    """보정셋으로 반폭을 정하고 테스트 예측에 구간을 씌운다."""
    a = np.asarray(cal_actual, dtype=float).ravel()
    p = np.asarray(cal_pred, dtype=float).ravel()
    if a.size != p.size:
        return {"available": False,
                "reason": f"보정 실측/예측 길이가 다릅니다: {a.size} vs {p.size}"}

    qq = conformal_quantile(np.abs(a - p), alpha)
    if not qq["available"]:
        return qq

    tp = np.asarray(test_pred, dtype=float).ravel()
    q = qq["q"]
    return {
        "available": True, "alpha": alpha, "q": q, "n_cal": qq["n"], "rank": qq["rank"],
        "lower": (tp - q).tolist(), "upper": (tp + q).tolist(), "point": tp.tolist(),
        "note": (f"보정 {qq['n']}개의 절대잔차 {qq['rank']}번째 순위값 ±{q:.4g}. "
                 "교환가능성만 가정하며 분포 가정은 없습니다."),
    }


def measure_coverage(actual: np.ndarray, lower: np.ndarray,
                     upper: np.ndarray) -> dict[str, Any]:
    """★실제 적중률을 센다★ 이론 하한을 주장으로 쓰지 않는다.

    유한표본에서는 목표를 밑돌 수도 있고, 그 사실은 재 봐야만 알 수 있다.
    """
    y = np.asarray(actual, dtype=float).ravel()
    lo = np.asarray(lower, dtype=float).ravel()
    hi = np.asarray(upper, dtype=float).ravel()
    if not (y.size == lo.size == hi.size):
        return {"available": False, "reason": "실측/하한/상한 길이가 다릅니다."}
    if y.size == 0:
        return {"available": False, "reason": "측정할 표본이 없습니다."}
    inside = (y >= lo) & (y <= hi)
    return {
        "available": True,
        "coverage": float(inside.mean()),
        "n": int(y.size),
        "hits": int(inside.sum()),
        "mean_width": float(np.mean(hi - lo)),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 시계열용 등각 — 적응형 등각 추론(ACI) (G7 ② · 2026-11-19)
# ══════════════════════════════════════════════════════════════════════════════

#: 걸음 γ — 원 논문의 실험값(검색 요약으로 확인 · 본문 미독). ★결과를 보고 고르지 않는다★ — 사용자 칸이 없고,
#: 바꾸려면 코드와 HISTORY 에 까닭을 남긴다(γ 는 자유 손잡이라 결과를 보고 고르면 숨은 시행이 된다).
ACI_GAMMA: float = 0.005


def _bad_alpha_gamma(alpha: float, gamma: float) -> str | None:
    """α · γ 범위 검사 — 어긋나면 사유, 맞으면 None."""
    ok_a = isinstance(alpha, (int, float)) and math.isfinite(alpha) and 0.0 < alpha < 1.0
    if not ok_a:
        return f"목표 놓침률 α 는 0 과 1 사이여야 합니다: {alpha}"
    ok_g = isinstance(gamma, (int, float)) and math.isfinite(gamma) and 0.0 < gamma < 1.0
    if not ok_g:
        return f"걸음 γ 는 0 과 1 사이여야 합니다: {gamma}"
    return None


def aci_rank(m: int, alpha_t: float) -> tuple[str, int]:
    """유한표본 순위 하나가 세 경우를 가른다 → (종류, 순위).

    순위 r = ⌈(m+1)(1 − α_t)⌉ — split 의 `conformal_quantile` 과 같은 식(m = 앞 점수의 수).
    r > m 이면 `infinite`(실수 전체 · 덮음): α_t ≤ 0 이면 늘 여기다. r ≤ 0 이면 `empty`(빈 집합 · 놓침): α_t ≥ 1 이면
    늘 여기다. 그 밖은 `finite`(앞 점수의 r 번째로 작은 값이 반폭). ★자르지 않는다★ — 무한을 가장 큰 점수로 자르거나
    빈 집합을 덮음으로 세면 아래 보장이 깨진다.
    """
    rank = math.ceil((m + 1) * (1.0 - alpha_t))
    if rank > m:
        return "infinite", rank
    if rank <= 0:
        return "empty", rank
    return "finite", rank


def aci_steps(scores: Any, *, alpha: float, gamma: float) -> tuple[list[dict[str, Any]], float]:
    """점수 열 → (걸음마다의 기록, 마지막 갱신 뒤의 α = 다음 걸음의 α).

    걸음 t(1부터)는 앞 점수 s_1 … s_{t−1}(m = t − 1개)과 α_t 로 구간을 정하고 그 걸음의 점수 s_t 로 놓침을 센다 —
    유한 구간은 s_t > q_t 일 때 놓침(경계는 덮음 · `measure_coverage` 와 같다) · 실수 전체는 덮음 · 빈 집합은 놓침.
    그다음 α_{t+1} = α_t + γ(α − err_t). 점수는 유한한 0 이상의 크기(|y − ŷ|)여야 한다 — 아니면 ValueError
    (빼고 이어 가면 시간 순서가 어긋난다).
    """
    bad = _bad_alpha_gamma(alpha, gamma)
    if bad:
        raise ValueError(bad)
    s = [float(x) for x in scores]
    if any((not math.isfinite(x)) or x < 0 for x in s):
        raise ValueError("점수는 유한한 0 이상의 크기(|y − ŷ|)여야 합니다.")
    past: list[float] = []          # 앞 점수 — 정렬해 둔다(순위값을 바로 읽는다)
    a = float(alpha)
    steps: list[dict[str, Any]] = []
    for t, score in enumerate(s, start=1):
        m = len(past)
        kind, rank = aci_rank(m, a)
        q = past[rank - 1] if kind == "finite" else None
        err = 1 if (kind == "empty" or (q is not None and score > q)) else 0
        steps.append({"t": t, "alpha_t": a, "m": m, "kind": kind, "rank": rank, "q": q,
                      "score": score, "err": err})
        a = a + gamma * (alpha - err)
        bisect.insort(past, score)
    return steps, a


def aci_bound(n: int, *, alpha: float, gamma: float) -> float:
    """|(1/n) Σ err_t − α| 의 결정적 상한(α_1 = α) — (max(α, 1 − α) + γ) / (γ n).

    유도: α_t 는 늘 [−γ, 1 + γ] 안(α_t ≤ 0 이면 덮어 오르기만 · α_t ≥ 1 이면 놓쳐 내리기만) → 망원 합
    α_{n+1} − α_1 = γ Σ (α − err_t) 를 n 으로 나눈다. 교환가능성 · 정상성 가정이 없다.
    """
    if n < 1:
        raise ValueError(f"걸음 수는 1 이상이어야 합니다: {n}")
    return (max(alpha, 1.0 - alpha) + gamma) / (gamma * n)


def adaptive_conformal(actual: Any, pred: Any, test_pred: float, *,
                       alpha: float = 0.1, gamma: float = ACI_GAMMA) -> dict[str, Any]:
    """시간 순서의 (실현, 예측) 쌍 → 온라인 적중 · 보장 상한 · 다음 한 걸음의 구간 (교환가능성 가정 없음).

    `test_pred` 는 다음 한 걸음의 예측(점 하나). 구간은 그 예측 ± 반폭(앞 점수 전부와 마지막 갱신 뒤의 α 로).
    잘못된 입력(길이 · 빈 입력 · 유한하지 않은 값 · α · γ 범위)은 `available: false` + 사유 — 숫자를 지어내지 않는다.
    """
    base: dict[str, Any] = {"available": False, "method": "aci", "alpha": alpha, "gamma": gamma}
    bad = _bad_alpha_gamma(alpha, gamma)
    if bad:
        return {**base, "reason": bad}
    y = np.asarray(actual, dtype=float).ravel()
    yhat = np.asarray(pred, dtype=float).ravel()
    if y.size != yhat.size:
        return {**base, "reason": f"실측 · 예측 길이가 다릅니다: {y.size} vs {yhat.size}"}
    if y.size == 0:
        return {**base, "n": 0, "reason": "쌍이 없습니다. 걸음을 셀 수 없습니다."}
    nonfinite = int((~np.isfinite(y)).sum() + (~np.isfinite(yhat)).sum())
    if nonfinite:
        return {**base, "n": int(y.size),
                "reason": (f"실측 · 예측에 유한하지 않은 값이 {nonfinite}개 있습니다. "
                           "시간 순서를 지키려고 빼지 않고 계산하지 않습니다.")}
    try:
        tp = float(test_pred)
    except (TypeError, ValueError):
        tp = float("nan")
    if not math.isfinite(tp):
        return {**base, "n": int(y.size), "reason": "다음 구간의 예측이 유한한 수가 아닙니다."}

    scores = [float(x) for x in np.abs(y - yhat)]
    steps, a_next = aci_steps(scores, alpha=alpha, gamma=gamma)
    n = len(steps)
    misses = sum(st["err"] for st in steps)
    widths = [2.0 * st["q"] for st in steps if st["kind"] == "finite"]
    online = {
        "n": n, "hits": n - misses, "misses": misses, "coverage": (n - misses) / n,
        "n_infinite": sum(1 for st in steps if st["kind"] == "infinite"),
        "n_empty": sum(1 for st in steps if st["kind"] == "empty"),
        "n_finite": len(widths),
        # 너비 평균은 유한한 구간만(그 수 `n_finite` 와 함께) — 무한 구간을 평균에 넣으면 값이 없다.
        "mean_width": (float(np.mean(widths)) if widths else None),
    }

    kind, rank = aci_rank(n, a_next)
    nxt: dict[str, Any] = {"kind": kind, "point": tp, "lower": None, "upper": None, "half_width": None,
                           "rank": rank, "m": n, "sentence": None}
    if kind == "finite":
        q = float(sorted(scores)[rank - 1])
        nxt.update(lower=tp - q, upper=tp + q, half_width=q)
    elif kind == "infinite":
        nxt["sentence"] = ("다음 구간은 무한 구간(실수 전체)입니다. 지금까지의 점수로는 목표 적중률을 지키는 "
                           "유한한 구간을 만들 수 없습니다.")
    else:
        nxt["sentence"] = ("다음 구간은 비어 있습니다(빈 구간). 덮은 걸음이 목표보다 많아 적중률을 목표로 "
                           "되돌리는 걸음입니다.")

    b = aci_bound(n, alpha=alpha, gamma=gamma)
    trivial = max(alpha, 1.0 - alpha)
    informative = b < trivial
    sentence = (f"놓친 비율의 장기 평균은 목표 {alpha:.0%}에서 ±{b:.3f} 안입니다. "
                f"어떤 수열에서도 서는 결정적 상한입니다({n}쌍)." if informative else
                f"놓친 비율이 목표 {alpha:.0%}에서 벗어나는 폭의 상한은 {b:.2f}입니다. 어떤 결과로도 넘을 수 없는 "
                f"폭 {trivial:.2f} 이상이라 이 길이({n}쌍)로는 보장이 서지 않습니다.")
    return {
        "available": True, "method": "aci", "alpha": alpha, "gamma": gamma, "n": n,
        "alpha_next": float(a_next),
        "online": online,
        "bound": {"value": b, "trivial": trivial, "informative": informative, "sentence": sentence},
        "next": nxt,
        "note": ("교환가능성을 가정하지 않는 적응형 등각(ACI)입니다. 걸음마다 앞의 점수로 구간을 정하고, "
                 f"놓치면 다음 구간을 넓히고 덮으면 좁힙니다(걸음 γ = {gamma:g}). 보장은 놓친 비율의 "
                 "장기 평균에 대한 것이며 구간 하나하나의 적중을 약속하지 않습니다."),
    }
