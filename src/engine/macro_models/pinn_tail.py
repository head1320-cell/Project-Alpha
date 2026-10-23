"""04 TAIL — 꼬리 위험과 점프 강도 (M1-M)
==============================================================================
프론티어: PINN — 물리정보 신경망으로 점프-확산의 강도 $\\lambda_{jump}$ 를 추정.
대체:     POT/EVT — 임계 초과분에 일반화 파레토(GPD) 적합 + 초과 빈도로 강도 추정.

★POT 는 오래된 방법이지만 여기서는 **더 나은 선택**이다★
꼬리는 정의상 관측이 적다. 60개월 표본에서 신경망은 꼬리를 배울 데이터가 없고,
POT 는 극단값 이론이 보장하는 점근 분포를 쓰므로 표본이 적을수록 오히려 유리하다.
그래서 이것은 "임시방편" 이 아니라 이 표본 크기에서 옳은 도구다 — 다만 GPD 적합에도
초과 관측이 최소 몇 개는 필요하고, 그 수를 채우지 못하면 숫자를 내지 않는다.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from src.engine.macro_models.base import Engine, Studio, load_series, ok, span_of, unavailable

# 꼬리를 볼 대상 — KRX VKOSPI·신용잔고는 M1-I 에서 붙는다(지금은 없다).
_INPUTS = ("KOSPI", "VIXCLS", "USD_KRW")

_MIN_EXCEED = 8            # GPD 모수 2개를 추정하기 위한 최소 초과 관측
_TAIL_Q = 0.90             # 임계값 분위수

STUDIO = Studio(
    id="pinn-tail",
    label="TAIL",
    question="지금 꼬리는 얼마나 두껍고, 급변이 얼마나 자주 오는가?",
    frontier=Engine(
        name="PINN 점프-확산",
        kind="frontier",
        summary="물리정보 신경망 — 점프 강도 λ_jump 와 확산항을 동시 추정",
        requires=("torch", "frontier_sample"),
    ),
    substitute=Engine(
        name="POT / EVT (GPD)",
        kind="substitute",
        summary="임계 초과분 일반화 파레토 적합 + 초과 빈도 — 소표본 꼬리에 적합",
        requires=("term_structure",),      # scipy
    ),
    inputs=_INPUTS,
)


def _returns(levels: list[float]) -> np.ndarray:
    x = np.asarray(levels, dtype=float)
    x = x[np.isfinite(x) & (x > 0)]
    if x.size < 2:
        return np.array([])
    # ★로그에 음수/0 이 들어가지 않게 위에서 걸렀다★ (수치 안전 규칙)
    return np.diff(np.log(x))


def run(months: int = 60, target: str = "KOSPI", **_: Any) -> dict[str, Any]:
    series = load_series(_INPUTS, months)
    if target not in series:
        return unavailable(
            STUDIO.substitute.name,
            f"대상 시리즈가 없습니다: {target} (가용: {', '.join(sorted(series)) or '없음'})")

    r = _returns(series[target])
    if r.size < 24:
        return unavailable(
            STUDIO.substitute.name,
            f"수익률 관측이 {r.size}개뿐입니다 — 꼬리 적합에 최소 24개가 필요합니다.")

    # 하방 꼬리 — 손실을 양수로 본다.
    loss = -r
    u = float(np.quantile(loss, _TAIL_Q))
    exceed = loss[loss > u] - u
    if exceed.size < _MIN_EXCEED:
        return unavailable(
            STUDIO.substitute.name,
            f"임계({_TAIL_Q:.0%}) 초과 관측이 {exceed.size}개뿐입니다 — "
            f"GPD 적합에 최소 {_MIN_EXCEED}개가 필요합니다. 표본을 늘리세요.")

    try:
        from scipy.stats import genpareto
        shape, loc, scale = genpareto.fit(exceed, floc=0.0)
    except Exception as e:  # noqa: BLE001
        return unavailable(STUDIO.substitute.name, f"GPD 적합이 실패했습니다: {e}")

    n = r.size
    n_u = int(exceed.size)
    rate = n_u / n                       # 임계 초과 빈도 = 점프 강도의 대용

    def var_es(p: float) -> tuple[float | None, float | None]:
        """POT VaR/ES. ξ≥1 이면 평균이 발산해 ES 가 정의되지 않는다 — None 을 돌린다."""
        q = 1.0 - p
        if rate <= 0 or q <= 0:
            return None, None
        if abs(shape) < 1e-8:
            v = u + scale * np.log(rate / q)
        else:
            v = u + (scale / shape) * ((rate / q) ** shape - 1.0)
        if shape >= 1.0:
            return float(v), None        # ★발산을 숫자로 내지 않는다★
        es = (v + (scale + shape * (v - u)) / (1.0 - shape)) if shape < 1.0 else None
        return float(v), (float(es) if es is not None else None)

    v95, e95 = var_es(0.95)
    v99, e99 = var_es(0.99)

    heavy = bool(shape > 0)
    es_note = ("" if shape < 1.0 else
               " ★ξ ≥ 1 이라 기대손실(ES)이 발산합니다 — 값을 내지 않았습니다.★")

    return ok(
        STUDIO.substitute.name,
        {
            "target": target,
            "threshold": round(u, 6),
            "threshold_q": _TAIL_Q,
            "n_obs": int(n),
            "n_exceed": n_u,
            "xi": round(float(shape), 4),          # 꼬리지수 — >0 이면 두꺼운 꼬리
            "beta": round(float(scale), 6),
            "jump_intensity_monthly": round(rate, 4),
            "heavy_tail": heavy,
            "var95": (round(v95, 6) if v95 is not None else None),
            "es95": (round(e95, 6) if e95 is not None else None),
            "var99": (round(v99, 6) if v99 is not None else None),
            "es99": (round(e99, 6) if e99 is not None else None),
        },
        note=(f"상위 {1 - _TAIL_Q:.0%} 손실 {n_u}개에 일반화 파레토를 적합했습니다. "
              "점프 강도는 **임계 초과 빈도**이지 점프-확산 모형의 λ_jump 가 아닙니다 — "
              "확산항과 점프항을 분리하지 않았습니다." + es_note),
        span=span_of(int(n), months),
    )
