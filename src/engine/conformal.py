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
"""

from __future__ import annotations

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
        return {"available": False, "reason": "잴 표본이 없습니다."}
    inside = (y >= lo) & (y <= hi)
    return {
        "available": True,
        "coverage": float(inside.mean()),
        "n": int(y.size),
        "hits": int(inside.sum()),
        "mean_width": float(np.mean(hi - lo)),
    }
