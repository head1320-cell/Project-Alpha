"""순차 증거(e-값) — 손실 상한을 둔 베팅 e-과정. 순수 함수 · 난수 없음.

답하는 물음은 하나다: ★"기간을 늘려 가며 몇 번을 다시 봐도, 수익이 없는 규칙이 기준을 넘을 확률이 α 이하인가."★
고정 표본의 확률(PSR · DSR)은 '한 번 본다'를 전제로 한다 — 결과를 보고 기간을 늘리거나 좋아 보일 때 멈추면 그 확률은 보장되지 않는다.

정의
    하루 손익 x_i 를 상한 c(> 0)에서 자른다:  r_i = max(x_i, −c) / c  ≥ −1
    E_t = 평균_f ∏_{i ≤ t} (1 + f · r_i),   f ∈ `FRACTIONS` = {0.05 … 0.95}      (E_0 = 1)

    가설 H0: "지난 날들을 알고도, 자른 하루 손익의 기댓값은 0 이하다."
    H0 아래에서 f 마다 ∏(1 + f·r_i) 는 음이 아닌 초마팅게일이고(1 + f·r ≥ 1 − f > 0), 그 평균도 그렇다.
    → Ville 의 부등식: P(어느 날이든 E_t ≥ 1/α) ≤ α.  ★분포의 꼴(꼬리 · 비대칭 · 0 이 많은 날)을 가정하지 않는다.★
    시행이 N 번이면 기준은 N/α 다(합집합 한계 — 시행끼리 닮았든 아니든 성립한다).

★상한이 계약이다★
    손실에 상한이 없으면 유한한 표본으로는 평균이 양이라는 증거를 낼 수 없다(Bahadur–Savage) — 그래서 상한을 ★가정으로 받는다★.
    상한을 넘은 날은 상한에서 잘라 계산하고 ★센다★. 하루라도 넘었으면 그 값은 실제 손익의 증거가 아니다 — `passed` 는 거짓이다.
    ★남는 한계★: 상한을 넘는 손실이 아직 표본에 나타나지 않았다면 이 도구는 알 수 없다(문장 `ASSUMPTION` 이 값마다 붙는 까닭).

대칭 · 정규 근사 위의 e-과정은 쓰지 않는다 — 자주 조금 벌고 드물게 크게 잃는 손익에서 거짓 통과가 22~25% 였다(구현 계획 §2.0 의 재 본 값).

★이 값은 도구의 통계 성질이다.★ 어떤 규칙이 앞으로 수익을 낸다는 주장이 아니고, 합성 봉 위의 값은 실제 시장의 증거가 아니다.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import numpy as np

#: 유의수준 — 관례값이다(재 본 값이 아니다). 답에 함께 싣는다.
ALPHA = 0.05
#: 베팅 비율의 격자. 1 을 넣지 않는다 — 상한만큼 잃은 날에 곱이 0 이 되어 되살아나지 못한다.
FRACTIONS: tuple[float, ...] = tuple(k / 20 for k in range(1, 20))
#: 답에 싣는 값의 천장. 그 위는 이 수로 적고 `saturated` 로 표시한다(JSON 에 inf 를 싣지 않는다).
SATURATION = 1e12
METHOD = "capped_betting_mixture"

REASONS = {
    "no_values": "비용 뒤 일별 손익이 없어 순차 증거를 계산하지 않았습니다.",
    "no_days": "거래일이 없어 순차 증거를 계산하지 않았습니다.",
    "no_cap": "하루 손실의 상한이 없어 순차 증거를 계산하지 않았습니다. 상한이 없으면 유한한 표본으로는 수익의 증거를 낼 수 없습니다.",
    "bad_values": "일별 손익에 수가 아닌 값이 있어 순차 증거를 계산하지 않았습니다.",
    "cap_exceeded": "하루 손실이 가정한 상한을 넘은 날이 있어 이 값을 증거로 읽지 않습니다.",
}
ASSUMPTION = "하루 손실이 상한을 넘지 않는다는 가정 아래의 값입니다. 상한을 넘는 손실이 아직 나타나지 않았을 뿐일 수 있습니다."

_F = np.asarray(FRACTIONS, dtype=float)
_LOG_SATURATION = math.log(SATURATION)


def log_path(values: Sequence[float], cap: float) -> list[float]:
    """날마다의 log E_t. 손실은 −cap 에서 자른다. 로그 영역에서 계산해 넘치지 않는다.

    t 번째 값은 앞 t 날만 쓴다(누적합) — 뒤의 날을 더해도 앞의 값은 바뀌지 않는다."""
    r = np.maximum(np.asarray(values, dtype=float), -cap) / cap      # ≥ −1
    steps = np.log1p(np.outer(r, _F))                                 # 1 + f·r ≥ 1 − max(f) > 0 — 로그의 인수는 늘 양수다
    cum = np.cumsum(steps, axis=0)
    top = cum.max(axis=1)
    return (top + np.log(np.exp(cum - top[:, None]).mean(axis=1))).tolist()


def _shown(log_e: float) -> float:
    return SATURATION if log_e >= _LOG_SATURATION else math.exp(log_e)


def evidence(values: Sequence[float] | None, *, cap: float | None, trials: int = 1, alpha: float = ALPHA) -> dict[str, Any]:
    """일별 손익과 손실 상한 → 순차 증거.

    `e_value` 는 마지막 날의 값, `peak` 는 지나온 날 가운데 가장 컸던 값(시작값 1 포함)이다. 판정은 ★최고값★으로 한다 —
    '어느 날이든 기준을 넘을 확률'이 α 이하이므로, 넘은 적이 있다는 사실은 그 뒤에 내려와도 남는다.
    계산하지 못하면 값은 `None` 이고 `reason` 이 까닭을 말한다(1 이나 0 으로 내지 않는다).
    시행 수가 1 보다 작거나 유의수준이 (0, 1) 밖이면 부르는 쪽의 결함이다 — 고쳐서 계산하지 않고 `ValueError`."""
    if trials < 1 or not 0.0 < alpha < 1.0:
        raise ValueError(f"trials={trials!r} alpha={alpha!r}")
    out: dict[str, Any] = {"method": METHOD, "alpha": alpha, "trials": trials, "threshold": trials / alpha, "cap": None, "days": None,
                           "e_value": None, "peak": None, "saturated": None, "exceeded_days": None, "worst": None,
                           "passed": None, "reason": None, "assumption": None}
    if values is None:
        return {**out, "reason": REASONS["no_values"]}
    if cap is None or not math.isfinite(cap) or cap <= 0:
        return {**out, "reason": REASONS["no_cap"]}
    if not len(values):
        return {**out, "cap": float(cap), "days": 0, "reason": REASONS["no_days"]}
    if not all(math.isfinite(v) for v in values):
        return {**out, "cap": float(cap), "reason": REASONS["bad_values"]}
    path = log_path(values, cap)
    last, top = path[-1], max(0.0, max(path))
    exceeded = sum(v < -cap for v in values)
    return {**out, "cap": float(cap), "days": len(values), "e_value": _shown(last), "peak": _shown(top),
            "saturated": top >= _LOG_SATURATION, "exceeded_days": exceeded, "worst": float(min(values)),
            "passed": exceeded == 0 and top >= math.log(trials / alpha),
            "reason": REASONS["cap_exceeded"] if exceeded else None, "assumption": ASSUMPTION}
