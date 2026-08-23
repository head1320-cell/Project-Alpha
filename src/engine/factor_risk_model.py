"""팩터 리스크 모델 — Σ_asset = B Σ_f B' + D (벤치마크 문서 §13)

지금까지 Σ_asset 은 **표본 공분산**(`_cov(R)*252`)이었다. 그것은 자산이 늘면
추정해야 할 원소가 n²/2 로 늘어 관측수를 금세 넘고, 그때 행렬이 **특이해진다.**
팩터 모형은 그 자리를 구조로 바꾼다:

    Σ_asset = B Σ_f B' + diag(D)

    B  — 자산 × 팩터 노출 (자산마다 **결합** 회귀)
    Σ_f — 팩터 공분산 (`reverse_stress.factor_covariance`, 단위 정규화본)
    D  — 고유분산 (회귀 잔차, 자유도 보정)

★구조적 이점은 해석이 아니라 **양정부호**다★ `BΣ_fB'` 는 언제나 PSD 이고 D 는
양의 대각이므로 합은 **항상 PD** 다 — 자산수가 관측수를 넘어도 그렇다. 표본
공분산은 그 지점에서 특이행렬이 되어 최적화가 불가능해진다.

★단변량이 아니라 결합 베타다★ 팩터끼리 상관될 때 단변량 베타를 쓰면 공통 변동을
중복 흡수한다 — P3-4 에서 그 결과가 설명분산 **103,809%** 였다. 자산별 자유도
49(59관측 − 9팩터 − 절편)로 결합 추정이 가능함을 실측했다.

★단위★ 팩터·자산 수익률이 **월별**이므로 연율화는 **×12** 다(일별 ×252 가 아니다).
`optimize(s_override=…)` 는 연율 Σ 를 요구하므로 여기서 한 번만 환산한다.
"""
from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)

MIN_MONTHS = 24
MONTHS_PER_YEAR = 12          # ★월별 데이터의 연율 계수★ 252 가 아니다
DEFAULT_LOOKBACK_MONTHS = 60


def _asset_monthly_returns(codes: list[str], months: int) -> tuple[dict, list[str]]:
    from src.engine.conditional_market import _month_key
    from src.engine.valuation.macro_sensitivity import _monthly_returns

    series: dict[str, dict[str, float]] = {}
    failed: list[str] = []
    for c in codes:
        r = _monthly_returns(str(c), months=months)
        if r is None or r.empty:
            failed.append(str(c))
            continue
        series[str(c)] = {_month_key(t): float(v) for t, v in r.items()}
    return series, failed


def build_factor_risk_model(codes: list[str], *, series_map: dict | None = None,
                            min_months: int = MIN_MONTHS,
                            months: int = DEFAULT_LOOKBACK_MONTHS) -> dict:
    """자산별 결합 회귀로 B·D 를 얻고 Σ_f 와 조립한다."""
    if not codes:
        return {"available": False, "reason": "자산이 비어 있습니다"}

    from src.engine.factor_exposure import resolve_proxies
    from src.engine.reverse_stress import factor_covariance

    prox = resolve_proxies(series_map, min_months)
    if not prox["available"]:
        return {"available": False, "reason": prox["reason"]}
    cov = factor_covariance(prox["resolved"])
    if not cov["available"]:
        return {"available": False, "reason": cov["reason"]}

    factors = cov["factors"]
    Sf = np.asarray(cov["cov"], dtype=float)
    fac_months = {f: prox["resolved"][f]["changes"] for f in factors}

    series, no_price = _asset_monthly_returns(list(codes), months)
    excluded: dict[str, str] = {c: "월별 수익률을 만들 수 없습니다" for c in no_price}
    if not series:
        return {"available": False, "reason": "어떤 자산도 월별 수익률을 내지 못했습니다",
                "excluded": excluded}

    common_fac = set.intersection(*[set(v) for v in fac_months.values()])
    n_param = len(factors) + 1

    kept: list[str] = []
    rows_B: list[np.ndarray] = []
    d_vals: list[float] = []
    diag_rows: list[dict] = []
    for code in [c for c in codes if str(c) in series]:
        code = str(code)
        shared = sorted(set(series[code]) & common_fac)
        dof = len(shared) - n_param
        if len(shared) < min_months or dof < 2:
            excluded[code] = (f"공통 달 {len(shared)}개 · 잔차 자유도 {dof} — "
                              f"결합 추정을 하지 않습니다")
            continue
        y = np.array([series[code][m] for m in shared], dtype=float)
        X = np.array([[fac_months[f][m] for f in factors] for m in shared], dtype=float)
        A = np.column_stack([np.ones(len(shared)), X])
        try:
            coef, *_ = np.linalg.lstsq(A, y, rcond=None)
        except np.linalg.LinAlgError as e:  # noqa: BLE001
            excluded[code] = f"회귀가 풀리지 않았습니다: {type(e).__name__}"
            continue
        beta = coef[1:]
        resid = y - A @ coef
        # ★자유도 보정★ 모수 수만큼 나눈다 — 보정 없이는 D 가 체계적으로 작아진다.
        d = float((resid ** 2).sum() / dof)
        if not np.isfinite(d) or d <= 0:
            excluded[code] = "잔차분산이 유효하지 않습니다"
            continue

        kept.append(code)
        rows_B.append(beta)
        d_vals.append(d)
        fac_var = float(beta @ Sf @ beta)
        total = fac_var + d
        diag_rows.append({
            "code": code, "n_months": len(shared), "dof": int(dof),
            "factor_variance": round(fac_var, 10),
            "specific_variance": round(d, 10),
            "factor_share_pct": (round(fac_var / total * 100.0, 2) if total > 0 else None),
            "monthly_vol_model": round(float(np.sqrt(max(total, 0.0))), 6),
        })

    if not kept:
        return {"available": False,
                "reason": "결합 추정을 통과한 자산이 없습니다", "excluded": excluded}

    B = np.array(rows_B, dtype=float)
    D = np.array(d_vals, dtype=float)
    S = B @ Sf @ B.T + np.diag(D)
    eig = np.linalg.eigvalsh(S)

    return {
        "available": True, "reason": None,
        "codes": kept, "factors": factors,
        "B": B, "factor_cov": Sf, "D": D, "cov_monthly": S,
        "excluded": excluded,
        "assets": diag_rows,
        "diagnostics": {
            "n_assets": len(kept), "n_factors": len(factors),
            "n_months": cov["n_months"], "span": cov["span"],
            "min_eigenvalue": float(eig.min()),
            # ★구조적으로 PD 다★ 그래도 확인해서 보고한다.
            "positive_definite": bool(eig.min() > 0),
            "condition_number": (float(eig.max() / eig.min()) if eig.min() > 0 else None),
            "factor_cov_shrinkage": cov.get("shrinkage_lambda"),
            "factor_cov_degenerate": cov.get("degenerate"),
        },
        "units": "monthly",
        "method": "joint_ols_factor_model",
        "note": ("Σ = BΣ_fB' + diag(D) 입니다. BΣ_fB' 는 항상 PSD 이고 D 는 양의 "
                 "대각이라 합은 자산수가 관측수를 넘어도 양정부호입니다 — 표본 "
                 "공분산이 특이해지는 지점에서도 최적화가 가능합니다"),
    }


def asset_covariance(model: dict, *, annualize: bool = True) -> np.ndarray | None:
    """모델 → Σ_asset. ★연율화는 ×12★ (월별 데이터이므로 252 가 아니다).

    `optimize(s_override=…)` 는 **연율 Σ** 를 요구한다(P2.5 의 계약).
    """
    if not model.get("available"):
        return None
    S = np.asarray(model["cov_monthly"], dtype=float)
    return S * MONTHS_PER_YEAR if annualize else S


def compare_to_sample(model: dict, sample_cov_monthly) -> dict:
    """표본 공분산과의 차이를 **보고**한다 — 우월하다고 주장하지 않는다."""
    if not model.get("available"):
        return {"available": False, "reason": model.get("reason")}
    S = np.asarray(model["cov_monthly"], dtype=float)
    Q = np.asarray(sample_cov_monthly, dtype=float)
    if Q.shape != S.shape:
        return {"available": False,
                "reason": f"표본 공분산 모양이 다릅니다: {Q.shape} vs {S.shape}"}
    eq = np.linalg.eigvalsh(Q)
    return {
        "available": True, "reason": None,
        "model_vol": [round(float(v), 6) for v in np.sqrt(np.maximum(np.diag(S), 0))],
        "sample_vol": [round(float(v), 6) for v in np.sqrt(np.maximum(np.diag(Q), 0))],
        "sample_min_eigenvalue": float(eq.min()),
        "sample_positive_definite": bool(eq.min() > 0),
        "max_abs_diff": round(float(np.abs(S - Q).max()), 10),
        "note": ("두 추정의 차이를 보여줄 뿐 어느 쪽이 옳다고 말하지 않습니다 — "
                 "팩터 모형의 이점은 정확도가 아니라 **항상 양정부호**라는 구조입니다"),
    }
