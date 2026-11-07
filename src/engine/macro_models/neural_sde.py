"""02 TERM — 수익률 곡선 상태와 위험가격 (M1-M)
==============================================================================
프론티어: 무차익 Neural SDE — $dX_t = \\mu\\,dt + \\sigma\\,dW_t$ 를 학습하고
          $\\lambda_t = \\sigma^{-1}(\\mu - r\\mathbf{1})$ 로 순간 위험가격 벡터를 낸다.
대체:     Nelson-Siegel 3요인 적합 (수준 · 기울기 · 곡률) + 기간프리미엄 **대용**.

★"위험가격" 이라고 부르지 않는다★
Nelson-Siegel 은 **곡선의 모양을 기술**할 뿐 무차익 조건을 걸지 않는다. 여기서 나오는
기울기·기간프리미엄 대용을 $\\lambda_t$ 라고 이름 붙이면, 무차익 모형이 준 것과 같은
무게로 읽힌다. 그래서 필드 이름을 `slope`·`term_premium_proxy` 로 두고 노트에
"대용" 이라고 적는다. 이름이 곧 주장이다.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from src.engine.macro_models.base import Engine, Studio, load_series, ok, span_of, unavailable

# 만기(년) ↔ FRED 시리즈
_TENORS: tuple[tuple[float, str], ...] = (
    (0.25, "DGS3MO"), (2.0, "DGS2"), (10.0, "DGS10"), (30.0, "DGS30"),
)
_INPUTS = tuple(k for _, k in _TENORS) + ("T10Y2Y", "T10YIE", "DFII10")

STUDIO = Studio(
    id="neural-sde",
    label="TERM",
    question="수익률 곡선은 지금 어떤 상태이고, 무엇을 보상하고 있는가?",
    frontier=Engine(
        name="무차익 Neural SDE",
        kind="frontier",
        summary="연속시간 곡선 동학 + 순간 위험가격 벡터 λ_t (무차익 제약 학습)",
        requires=("torch", "frontier_sample"),
    ),
    substitute=Engine(
        name="Nelson-Siegel 3요인",
        kind="substitute",
        summary="수준·기울기·곡률 적합 + 기간프리미엄 대용 (무차익 조건 없음)",
        requires=("term_structure",),
    ),
    inputs=_INPUTS,
)


def _ns_basis(tau: np.ndarray, lam: float) -> np.ndarray:
    """Nelson-Siegel 기저 — [1, (1−e^{−λτ})/(λτ), 그 값 − e^{−λτ}]."""
    x = lam * tau
    # τ→0 에서 (1−e^{−x})/x → 1. 0 나눗셈을 가드한다(수치 안전 규칙).
    b1 = np.where(x > 1e-8, (1.0 - np.exp(-x)) / np.where(x > 1e-8, x, 1.0), 1.0)
    b2 = b1 - np.exp(-x)
    return np.column_stack([np.ones_like(tau), b1, b2])


def run(months: int = 60, **_: Any) -> dict[str, Any]:
    series = load_series(_INPUTS, months)
    have = [(t, k) for t, k in _TENORS if k in series]
    if len(have) < 3:
        missing = [k for _, k in _TENORS if k not in series]
        return unavailable(
            STUDIO.substitute.name,
            f"곡선 적합에 만기 3개 이상이 필요합니다 — 없는 시리즈: {', '.join(missing)}.")

    n = min(len(series[k]) for _, k in have)
    tau = np.array([t for t, _ in have], dtype=float)
    Y = np.column_stack([np.asarray(series[k][-n:], dtype=float) for _, k in have])  # (n, m)

    try:
        from scipy.optimize import least_squares
    except Exception as e:  # noqa: BLE001
        return unavailable(STUDIO.substitute.name, f"scipy.optimize 를 쓸 수 없습니다: {e}")

    # λ 는 전체 표본에 하나 — 시점마다 다르게 두면 요인이 시점 간 비교 불가능해진다.
    def resid(p: np.ndarray) -> np.ndarray:
        lam = float(p[0])
        if lam <= 0:
            return np.full(Y.size, 1e6)
        B = _ns_basis(tau, lam)
        # 각 시점의 β 는 최소제곱 해 — λ 만 비선형이다.
        beta, *_ = np.linalg.lstsq(B, Y.T, rcond=None)
        return (Y.T - B @ beta).ravel()

    try:
        sol = least_squares(resid, x0=np.array([0.6]), bounds=([1e-3], [3.0]))
        lam = float(sol.x[0])
    except Exception as e:  # noqa: BLE001
        return unavailable(STUDIO.substitute.name, f"곡선 적합이 실패했습니다: {e}")

    B = _ns_basis(tau, lam)
    beta, *_ = np.linalg.lstsq(B, Y.T, rcond=None)      # (3, n)
    fitted = (B @ beta).T
    rmse = float(np.sqrt(np.mean((Y - fitted) ** 2)))

    level, slope, curv = (beta[0], beta[1], beta[2])

    # 기간프리미엄 **대용** — 실질금리(DFII10)와 기대인플레(T10YIE) 가 있으면
    # 10Y − (실질 + 기대인플레) 로 잔차를 본다. 없으면 내지 않는다(지어내지 않는다).
    tp = None
    tp_reason = None
    if "DGS10" in series and "DFII10" in series and "T10YIE" in series:
        m = min(len(series["DGS10"]), len(series["DFII10"]), len(series["T10YIE"]))
        tp = [round(float(series["DGS10"][-m:][i]
                         - series["DFII10"][-m:][i] - series["T10YIE"][-m:][i]), 4)
              for i in range(m)]
    else:
        miss = [k for k in ("DGS10", "DFII10", "T10YIE") if k not in series]
        tp_reason = f"기간프리미엄 대용을 계산할 시리즈가 없습니다: {', '.join(miss)}"

    inverted = bool(slope[-1] < 0) if slope.size else None

    return ok(
        STUDIO.substitute.name,
        {
            "lambda": round(lam, 4),
            "tenors": [t for t, _ in have],
            "series_used": [k for _, k in have],
            "level": [round(float(v), 4) for v in level],
            "slope": [round(float(v), 4) for v in slope],
            "curvature": [round(float(v), 4) for v in curv],
            "latest": {"level": round(float(level[-1]), 4),
                       "slope": round(float(slope[-1]), 4),
                       "curvature": round(float(curv[-1]), 4)},
            "inverted": inverted,
            "rmse_pp": round(rmse, 4),
            "term_premium_proxy": tp,
            "term_premium_reason": tp_reason,
        },
        note=("Nelson-Siegel 3요인 적합입니다(λ 는 전 표본 공통). ★무차익 조건을 걸지 "
              "않으므로 여기서 나오는 값은 위험가격 λ_t 가 아닙니다★ — 기울기는 곡선 "
              "모양의 기술이고, 기간프리미엄은 실질금리·기대인플레를 뺀 **대용**입니다. "
              f"적합 RMSE {rmse:.3f}%p."),
        span=span_of(n, months),
    )
