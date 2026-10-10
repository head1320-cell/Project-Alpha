"""P3-2 — 백테스트 실현수익의 팩터 귀인 (`bt_*` → 무엇이 수익을 만들었나)

P3-4 는 **사전 분산**을 팩터로 쪼갰다. 이 모듈은 **사후 실현수익**을 쪼갠다 —
"이 전략이 번 돈이 매크로 팩터 때문인가, 팩터로 설명되지 않는 α 인가".

    r_t = α + Σᵢ βᵢ·fᵢ,t + ε_t
    팩터 i 의 기여 = βᵢ · Σₜ fᵢ,t        ·        α 기여 = α · T

★단변량이 아니라 결합 회귀다★ 팩터가 서로 상관될 때 단변량 베타를 쓰면 공통
변동을 중복 흡수한다 — P3-4 에서 그 결과가 설명분산 **103,809%** 였다.

★결합이 가능한지 먼저 쟀다★ 59관측·9팩터면 자유도가 위태로울 줄 알았는데
설계행렬이 건강했다: **조건수 3.5 · 최대 VIF 3.55 · 관측/모수 6.56.**
다만 `duration`–`credit` 이 **0.82** 로 붙어 있어(둘 다 10Y 수준을 공유) 실제
귀인에서 **+14.3%p / −8.3%p** 로 크게 상쇄됐다 — 결합 적합은 멀쩡해도 **개별
귀인은 불안정**하다. 그래서 VIF 를 팩터마다 내고 라벨을 단다.

★산술 합과 복리 총수익은 다른 숫자다★ 항등식이 닫히는 것은 월별 수익률의
**산술 합**에 대해서다. 백테스트의 `total_return_pct` 는 복리라 값이 다르다.
둘을 같은 것처럼 내면 거짓이므로 **둘 다 내고 차이가 복리 효과임을 밝힌다.**
"""
from __future__ import annotations

import numpy as np

MIN_MONTHS = 24
VIF_WARN = 5.0          # 다중공선성 경고선 (관례)
_MIN_DOF = 2            # 잔차 자유도 하한 — 이보다 적으면 계수를 내지 않는다


def monthly_returns_from_result(result: dict | None) -> dict:
    """`bt_*` 결과 → `{"YYYY-MM": 수익률(소수)}`.

    ★없으면 빈 dict 가 아니라 사유★ 빈 dict 를 돌려주면 "팩터가 0을 설명했다" 와
    "잴 것이 없었다" 가 같아 보인다.
    """
    if not isinstance(result, dict):
        return {"available": False, "reason": "백테스트 결과가 없습니다"}
    # ★워커가 저장하는 모양을 읽는다 (BL3 W1)★ 백그라운드 워커는 `_screen_to_backtest_core` 의 응답 **전체**를
    # 저장하고, 월별 수익률은 그 안의 `backtest` 에 있다. 예전에는 최상위만 봐서 실제 실행에서는 늘 "없다" 고
    # 답했다(배선 테스트가 `.get("backtest")` 만 저장해 가려졌다). 최상위에 없을 때만 한 단계 내려간다.
    if "monthly_returns" not in result and isinstance(result.get("backtest"), dict):
        result = result["backtest"]
    rows = result.get("monthly_returns")
    if rows is None:
        return {"available": False,
                "reason": ("이 실행에는 월별 수익률이 없습니다 — 아직 끝나지 않았거나 "
                           "옛 스키마일 수 있습니다")}
    if not isinstance(rows, list) or not rows:
        return {"available": False, "reason": "월별 수익률이 비어 있습니다"}

    out: dict[str, float] = {}
    bad = 0
    for r in rows:
        try:
            y, m = int(r["year"]), int(r["month"])
            v = float(r["return_pct"]) / 100.0
        except (KeyError, TypeError, ValueError):
            bad += 1
            continue
        if not (1 <= m <= 12) or not np.isfinite(v):
            bad += 1
            continue
        out[f"{y:04d}-{m:02d}"] = v
    if not out:
        return {"available": False,
                "reason": f"월별 수익률 {len(rows)}행을 하나도 읽지 못했습니다"}
    return {"available": True, "reason": None, "returns": out,
            "n_months": len(out), "skipped_rows": bad}


def _vif(Z: np.ndarray, names: list[str]) -> dict:
    """팩터별 분산팽창계수 — ★상쇄되는 개별 귀인을 그대로 읽게 두지 않는다★"""
    try:
        C = np.corrcoef(Z, rowvar=False)
        inv = np.linalg.inv(C)
    except np.linalg.LinAlgError:
        return {n: None for n in names}
    return {n: round(float(v), 3) for n, v in zip(names, np.diag(inv), strict=True)}


def factor_attribution(returns_by_month: dict[str, float], resolved: dict, *,
                       min_months: int = MIN_MONTHS) -> dict:
    """결합 OLS 로 실현수익을 팩터와 α 로 쪼갠다."""
    if not returns_by_month:
        return {"available": False, "reason": "월별 수익률이 없습니다"}
    if not resolved:
        return {"available": False, "reason": "팩터 계열이 없습니다"}

    factors = list(resolved)
    fac_months = [set(resolved[f]["changes"]) for f in factors]
    shared = sorted(set(returns_by_month).intersection(*fac_months))
    if len(shared) < min_months:
        return {"available": False,
                "reason": (f"수익률과 팩터가 공통으로 갖는 달이 {len(shared)}개뿐입니다 "
                           f"(최소 {min_months}개)")}

    n_param = len(factors) + 1          # 팩터 + 절편
    dof = len(shared) - n_param
    if dof < _MIN_DOF:
        return {"available": False,
                "reason": (f"관측 {len(shared)}개로 모수 {n_param}개를 추정하면 잔차 "
                           f"자유도가 {dof} 입니다 — 계수를 내지 않습니다")}

    y = np.array([returns_by_month[m] for m in shared], dtype=float)
    X = np.array([[resolved[f]["changes"][m] for f in factors] for m in shared],
                 dtype=float)
    if not (np.all(np.isfinite(y)) and np.all(np.isfinite(X))):
        return {"available": False, "reason": "수익률 또는 팩터에 유한하지 않은 값이 있습니다"}

    A = np.column_stack([np.ones(len(shared)), X])
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    alpha, beta = float(coef[0]), coef[1:]

    resid = y - A @ coef
    ss_res = float((resid ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else None
    adj = (1.0 - (1.0 - r2) * (len(shared) - 1) / dof) if (r2 is not None and dof > 0) else None

    sd = X.std(axis=0, ddof=1)
    live = sd > 0
    Z = np.zeros_like(X)
    Z[:, live] = (X[:, live] - X[:, live].mean(axis=0)) / sd[live]
    vifs = _vif(Z[:, live], [f for f, ok in zip(factors, live, strict=True) if ok])

    contrib = beta * X.sum(axis=0)
    arithmetic = float(y.sum())
    alpha_total = alpha * len(shared)
    residual = arithmetic - alpha_total - float(contrib.sum())

    rows = []
    for i, f in enumerate(factors):
        v = vifs.get(f)
        rows.append({
            "factor": f,
            "series": resolved[f].get("series"),
            "transform": resolved[f].get("transform"),
            "beta": round(float(beta[i]), 6),
            "factor_sum": round(float(X[:, i].sum()), 6),
            "contribution_pct": round(float(contrib[i]) * 100.0, 4),
            "vif": v,
            # ★VIF 가 높으면 짝과 상쇄되어 개별로 읽으면 안 된다★
            "collinear": bool(v is not None and v > VIF_WARN),
            "collinear_reason": (
                (f"VIF {v} > {VIF_WARN} — 이 기여는 상관된 다른 팩터와 상쇄되므로 "
                 "개별 값으로 읽지 마십시오") if (v is not None and v > VIF_WARN) else None),
        })
    rows.sort(key=lambda r: abs(r["contribution_pct"]), reverse=True)

    # ★복리와 산술 합은 다른 숫자다★ 둘 다 내고 차이를 밝힌다.
    compound = float(np.prod(1.0 + y) - 1.0)

    return {
        "available": True, "reason": None,
        "rows": rows,
        "alpha_monthly": round(alpha, 8),
        "alpha_contribution_pct": round(alpha_total * 100.0, 4),
        "factor_contribution_pct": round(float(contrib.sum()) * 100.0, 4),
        "arithmetic_total_pct": round(arithmetic * 100.0, 4),
        "compound_total_pct": round(compound * 100.0, 4),
        "compounding_gap_pct": round((compound - arithmetic) * 100.0, 4),
        # ★항등식 검산을 출력에 싣는다★ 0 이 아니면 그 자체가 결함 신호다.
        "identity_residual_pct": round(residual * 100.0, 10),
        "diagnostics": {
            "n_months": len(shared), "span": [shared[0], shared[-1]],
            "n_factors": len(factors), "dof": int(dof),
            "obs_per_param": round(len(shared) / n_param, 2),
            "r_squared": (round(r2, 4) if r2 is not None else None),
            "adj_r_squared": (round(adj, 4) if adj is not None else None),
            "condition_number": (round(float(np.linalg.cond(Z[:, live])), 2)
                                 if live.any() else None),
            "max_vif": (max((v for v in vifs.values() if v is not None), default=None)),
            "constant_factors": [f for f, ok in zip(factors, live, strict=True) if not ok],
        },
        "method": "joint_ols_monthly",
        "note": ("결합 회귀입니다 — 단변량 베타는 상관된 팩터의 공통 변동을 중복 "
                 "흡수합니다. 항등식은 월별 수익률의 **산술 합**에 대해 닫히며, "
                 "복리 총수익과의 차이가 `compounding_gap_pct` 입니다"),
        "causality": ("상관·회귀는 인과가 아닙니다 — 이 기여는 동시대 월별 관계이며 "
                      "전략이 그 팩터를 의도했다는 뜻이 아닙니다"),
    }
