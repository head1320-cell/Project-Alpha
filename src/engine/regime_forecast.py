"""국면 예측의 **실측 적중률** (P4-M2)
==============================================================================
왜 필요한가
------------------------------------------------------------------------------
A8 의 `k_step_forecast` 는 k개월 뒤 국면 분포와 90% 신용구간을 이미 낸다. 그런데
**그 구간이 실제로 90% 를 맞히는지는 아무도 재지 않았다.** 유한표본에서 베이지안
신용구간은 목표를 밑돌 수 있고, 그 사실은 재 봐야만 알 수 있다.

★적중률은 주장이 아니라 실측이다★ M1-T 가 conformal 에 세운 원칙 그대로다.
`1-α` 를 그대로 적으면 이론값을 실측인 척하는 것이고, 그 숫자를 보고 사람이 비중을
움직인다.

방법 — 국면은 범주라서 구간이 아니라 **예측집합**이다
------------------------------------------------------------------------------
확률 높은 순으로 담아 질량 `1-α` 를 덮는 **최소 집합**을 만든다. 전부 담으면 100%
적중하지만 아무것도 말하지 않으므로, 최소성이 지표의 핵심이다 — 그래서 적중률과
**평균 집합 크기**를 항상 함께 낸다. 적중률만 보면 "다 담아서 맞혔다" 를 구분할 수 없다.

★walk-forward 로만 평가한다★ 각 시점 t 에서 **t 까지의 경로만으로** 전이 사후를
세우고 t+k 를 예측한 뒤 실현 국면과 대조한다. 전체 경로로 세운 행렬로 과거를
평가하면 미래를 쓰는 것이고 적중률이 부풀려진다.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from src.engine.regime_transitions import ALPHA_DIAG, ALPHA_OFF, REGIMES

logger = logging.getLogger(__name__)

#: 평가 시점이 이보다 적으면 적중률을 내지 않는다. 20개 미만의 비율은 한 건이
#: 5%p 를 움직여 "재 봤다" 고 말할 수 있는 정밀도가 아니다.
MIN_EVAL_POINTS = 20


def prediction_set(probs: dict[str, float], *, alpha: float = 0.1) -> list[str]:
    """질량 `1-α` 를 덮는 **최소** 국면 집합 (확률 내림차순으로 담는다).

    ★최소성이 핵심이다★ 4개를 다 담으면 반드시 맞지만 아무 정보가 없다. 집합이
    작을수록 예측이 날카롭다는 뜻이고, 그래서 적중률과 크기를 함께 봐야 한다.
    """
    target = 1.0 - alpha
    chosen: list[str] = []
    mass = 0.0
    for regime, p in sorted(probs.items(), key=lambda kv: (-kv[1], kv[0])):
        chosen.append(regime)
        mass += float(p)
        if mass >= target - 1e-9:
            break
    return chosen


def _posterior_forecast(path: list[str], k: int) -> dict[str, float]:
    """경로 → 전이 사후평균 행렬 → k단계 뒤 분포.

    사후평균 한 번으로 거듭제곱한다(A8 의 사후예측 표집이 아니라). 여기서 필요한
    것은 구간이 아니라 **점 분포**이고, walk-forward 로 수십 번 돌리므로 표집은
    비용만 크다. 구간이 필요한 화면 경로는 `k_step_forecast` 가 그대로 담당한다.
    """
    idx = {r: i for i, r in enumerate(REGIMES)}
    counts = [[0] * len(REGIMES) for _ in REGIMES]
    for a, b in zip(path, path[1:], strict=False):
        if a in idx and b in idx:
            counts[idx[a]][idx[b]] += 1

    # Dirichlet 사후평균 — 관측이 없는 행은 사전분포 그대로다(지속성 선호).
    matrix = []
    for i in range(len(REGIMES)):
        alphas = [(ALPHA_DIAG if j == i else ALPHA_OFF) + counts[i][j]
                  for j in range(len(REGIMES))]
        total = sum(alphas)
        matrix.append([a / total for a in alphas])

    vec = [0.0] * len(REGIMES)
    vec[idx[path[-1]]] = 1.0
    for _ in range(k):
        vec = [sum(vec[i] * matrix[i][j] for i in range(len(REGIMES)))
               for j in range(len(REGIMES))]
    return {REGIMES[j]: vec[j] for j in range(len(REGIMES))}


def forecast_coverage(path: list[str], *, k: int = 1, alpha: float = 0.1,
                      min_history: int = 24) -> dict[str, Any]:
    """국면 예측집합의 **실측 적중률** — walk-forward.

    각 시점 t(>= `min_history`)에서 `path[:t]` 만으로 사후를 세우고 t+k 를 예측한 뒤,
    예측집합이 `path[t+k-1]` 을 담았는지 센다. 미래를 쓰지 않는다.

    ★목표(1-α)와 실측을 다른 필드로 낸다★ 같은 자리에 넣으면 이론과 측정의 구분이
    사라지고, 그 구분이 이 함수의 존재 이유다.
    """
    clean = [r for r in path if r in set(REGIMES)]
    if len(clean) != len(path):
        return {"available": False,
                "reason": f"알 수 없는 국면 라벨이 있습니다 — 알려진 값: {REGIMES}"}
    if k < 1:
        return {"available": False, "reason": "예측 기간은 1개월 이상이어야 합니다."}

    hits = misses = 0
    sizes: list[int] = []
    for t in range(min_history, len(clean) - k + 1):
        history = clean[:t]
        realized = clean[t + k - 1]
        probs = _posterior_forecast(history, k)
        chosen = prediction_set(probs, alpha=alpha)
        sizes.append(len(chosen))
        if realized in chosen:
            hits += 1
        else:
            misses += 1

    n_eval = hits + misses
    if n_eval < MIN_EVAL_POINTS:
        return {"available": False,
                "reason": (f"평가 시점이 {n_eval}개로 최소 {MIN_EVAL_POINTS}개에 못 "
                           f"미칩니다 — 경로 {len(clean)}개월, 준비구간 {min_history}, "
                           f"예측 {k}개월. 이 표본으로 낸 적중률은 한 건이 크게 "
                           "움직여 '재 봤다' 고 말할 정밀도가 아닙니다.")}

    return {
        "available": True,
        "target": round(1.0 - alpha, 6),
        "coverage": hits / n_eval,
        "hits": hits,
        "misses": misses,
        "n_eval": n_eval,
        "mean_set_size": sum(sizes) / len(sizes),
        "k": k,
        "walk_forward": True,
        "note": (f"각 시점에서 그 이전 경로만으로 사후를 세워 {k}개월 뒤를 예측한 "
                 f"실측 적중률입니다(목표 {1 - alpha:.0%}). 전체 경로로 세운 행렬로 "
                 "과거를 채점하면 미래를 쓰는 것이라 적중률이 부풀려집니다. "
                 "적중률은 평균 집합 크기와 함께 읽어야 합니다 — 집합을 키우면 "
                 "적중률은 언제든 올라갑니다."),
    }


def regime_occupancy_counts(path: list[str]) -> dict[str, int]:
    """경로의 국면 점유 횟수 — 적중률을 읽을 때의 기저(base rate)."""
    return dict(Counter(r for r in path if r in set(REGIMES)))
