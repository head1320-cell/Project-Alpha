"""예측 결합 — ★단일 forecast 를 믿지 않는다★ (Brief §6)

    각 forecast 에 uncertainty 를 붙이고 결합한다.
    단순 평균보다 precision/uncertainty-aware combination 을 우선한다.

★핵심은 결합이 아니라 **독립성**이다★ 실측에서 이 저장소의 두 μ 예측은 독립이
아니었다:

    트레일링 창 36개월 · 국면 표본 24개월 · **겹침 24개월(국면표본의 100%)**

조건부 μ 는 트레일링 μ 가 쓰는 바로 그 데이터의 **부분표본**이다. 이것을 독립
예측처럼 역분산 가중하면 24개월을 "새 정보" 로 두 번 세어 결합 정밀도를 부풀린다.

겹치는 표본평균의 상관은 알려져 있다:

    ρ = n_shared / sqrt(n_a · n_b)        (실측 24/√(36·24) = 0.816)

★그런데 교과서 GLS 는 상관이 높을 때 무너진다★ 실측으로 확인했다 —
ρ=0.99 에서 가중이 **[3.92, −2.92]** 로 갈리며 결합 μ 가 **−7.5%**(두 입력 10%·16%
바깥!)가 되고 결합 SE 가 **10.98%** 로 최선 개별 SE(16.6%)보다 **작아졌다.**
Ω 가 특이행렬에 가까워질 때 GLS 가 두 예측 사이의 롱숏 스프레드 베팅을 하기
때문이고, ρ 를 정확히 알 때만 최적인 해다. 추정한 ρ 로는 재앙이다.

그래서 **가중을 음수로 두지 않는다**(w ≥ 0, 합 1). 그러면 ρ 가 높을수록 결합이
**가장 정밀한 하나로 수렴**한다 — 상관된 예측은 공짜 정밀도를 주지 않는다는
사실이 그대로 드러난다(실측 ρ≥0.9 에서 가중 [1, 0], 결합 SE = 최선 개별 SE).
"""
from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)

# 이 이상이면 사실상 같은 예측으로 보고 결합 이득을 주장하지 않는다.
COLLAPSE_WEIGHT = 0.98


def overlap_correlation(n_a: int, n_b: int, n_shared: int) -> dict:
    """겹치는 표본평균의 상관 `ρ = n_shared / √(n_a·n_b)`.

    ★창을 모르면 상관을 지어내지 않는다★ 0 으로 가정하면 독립이라고 **주장**하는
    것인데, 그것이 정밀도를 부풀리는 바로 그 실수다.
    """
    if min(n_a, n_b) <= 0:
        return {"available": False, "reason": "표본 크기가 0 이하입니다"}
    if n_shared < 0 or n_shared > min(n_a, n_b):
        return {"available": False,
                "reason": f"겹침({n_shared})이 표본 크기 범위를 벗어납니다"}
    rho = float(n_shared) / float(np.sqrt(n_a * n_b))
    return {"available": True, "reason": None,
            "rho": round(min(max(rho, 0.0), 1.0), 4),
            "n_a": int(n_a), "n_b": int(n_b), "n_shared": int(n_shared),
            "note": ("겹치는 표본평균의 상관입니다 — 같은 데이터를 두 번 세지 "
                     "않기 위해 결합에 반드시 넣습니다")}


def _solve_weights(cov: np.ndarray) -> np.ndarray | None:
    """min w'Ωw, w ≥ 0, Σw = 1 — ★음수 가중을 허용하지 않는다★"""
    from scipy.optimize import minimize

    k = cov.shape[0]
    if k == 1:
        return np.ones(1)
    res = minimize(lambda w: float(w @ cov @ w), np.ones(k) / k, method="SLSQP",
                   bounds=[(0.0, 1.0)] * k,
                   constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1.0}],
                   options={"maxiter": 400, "ftol": 1e-12})
    if not res.success:
        return None
    w = np.maximum(np.asarray(res.x, dtype=float), 0.0)
    total = w.sum()
    return w / total if total > 0 else None


def combine_forecasts(forecasts: list[dict], *,
                      correlation: np.ndarray | float | None = None) -> dict:
    """여러 μ 예측을 불확실성 가중으로 결합한다.

    각 예측: `{"name", "mu", "se"}` — `mu`/`se` 는 같은 길이의 자산 벡터.
    """
    live = [f for f in (forecasts or []) if f.get("mu") is not None
            and f.get("se") is not None]
    if not live:
        return {"available": False, "reason": "쓸 수 있는 예측이 없습니다"}

    names = [str(f.get("name") or f"forecast_{i}") for i, f in enumerate(live)]
    try:
        MU = np.array([np.asarray(f["mu"], dtype=float) for f in live])
        SE = np.array([np.asarray(f["se"], dtype=float) for f in live])
    except (TypeError, ValueError) as e:
        return {"available": False, "reason": f"예측을 배열로 읽지 못했습니다: {e}"}
    if MU.ndim != 2 or MU.shape != SE.shape:
        return {"available": False,
                "reason": f"예측 모양이 어긋납니다: mu{MU.shape} se{SE.shape}"}
    if not (np.all(np.isfinite(MU)) and np.all(np.isfinite(SE))):
        return {"available": False, "reason": "예측에 유한하지 않은 값이 있습니다"}
    if np.any(SE <= 0):
        return {"available": False, "reason": "표준오차가 0 이하인 예측이 있습니다"}

    k, n_assets = MU.shape
    if correlation is None:
        C = np.eye(k)
        rho_note = ("상관을 주지 않아 **독립으로 가정**했습니다 — 같은 데이터에서 "
                    "나온 예측이면 결합 정밀도가 부풀려집니다")
        assumed_independent = True
    elif np.isscalar(correlation):
        C = np.full((k, k), float(correlation))
        np.fill_diagonal(C, 1.0)
        rho_note = None
        assumed_independent = False
    else:
        C = np.asarray(correlation, dtype=float)
        if C.shape != (k, k):
            return {"available": False,
                    "reason": f"상관행렬 모양이 예측 수({k})와 다릅니다: {C.shape}"}
        rho_note = None
        assumed_independent = False

    # 자산마다 SE 가 다르므로 자산별로 푼다.
    mu_c = np.zeros(n_assets)
    se_c = np.zeros(n_assets)
    W = np.zeros((k, n_assets))
    for j in range(n_assets):
        D = np.diag(SE[:, j])
        Om = D @ C @ D
        w = _solve_weights(Om)
        if w is None:
            return {"available": False,
                    "reason": f"자산 {j} 의 결합 가중을 풀지 못했습니다"}
        W[:, j] = w
        mu_c[j] = float(w @ MU[:, j])
        se_c[j] = float(np.sqrt(max(w @ Om @ w, 0.0)))

    mean_w = W.mean(axis=1)
    best_se = SE.min(axis=0)
    # ★상관된 예측은 공짜 정밀도를 주지 않는다★ 제약 해가 이것을 보장한다.
    gain = 1.0 - (se_c / np.where(best_se > 0, best_se, 1.0))
    collapsed = [names[i] for i in range(k) if mean_w[i] >= COLLAPSE_WEIGHT]

    return {
        "available": True, "reason": None,
        "names": names, "n_forecasts": k, "n_assets": n_assets,
        "mu": mu_c, "se": se_c,
        "weights": {names[i]: [round(float(x), 4) for x in W[i]] for i in range(k)},
        "mean_weights": {names[i]: round(float(mean_w[i]), 4) for i in range(k)},
        # 유효 독립 예측 수 — 하나로 쏠리면 1 에 가깝다(ENB 와 같은 발상).
        "effective_forecasts": round(float(1.0 / (mean_w ** 2).sum()), 4),
        "precision_gain_pct": [round(float(g) * 100.0, 2) for g in gain],
        "collapsed_to": collapsed or None,
        "assumed_independent": assumed_independent,
        "correlation_note": rho_note,
        "method": "nonnegative_min_variance",
        "note": ("가중을 음수로 두지 않습니다 — 교과서 GLS 는 상관이 높을 때 두 "
                 "예측 사이의 롱숏 베팅으로 갈려 결합값이 입력 범위를 벗어나고 "
                 "결합 SE 가 최선 개별 SE 보다 작아집니다(실측 ρ=0.99 에서 "
                 "가중 [3.92, −2.92]). 제약을 걸면 상관이 높을수록 가장 정밀한 "
                 "하나로 수렴합니다"),
    }


TRADING_DAYS = 252


def asset_forecasts(returns_df, *, regime_by_month: dict | None = None,
                    current_regime: str | None = None) -> dict:
    """이 저장소가 실제로 낼 수 있는 μ 예측들을 모은다.

    ★두 예측은 독립이 아니다★ 조건부 μ 는 트레일링 μ 가 쓰는 데이터의 **부분표본**
    이다(실측 겹침 100%). 그래서 창 크기를 함께 모아 `overlap_correlation` 으로
    ρ 를 계산하고 결합에 넣는다 — 독립으로 두면 같은 데이터를 두 번 센다.
    """
    from src.engine.conditional_market import _month_key
    from src.engine.robust_opt import mu_standard_errors

    if returns_df is None or len(returns_df) == 0:
        return {"available": False, "reason": "수익률이 비어 있습니다"}

    names = list(returns_df.columns)
    R = returns_df.values
    est = mu_standard_errors(R)
    if not est["available"]:
        return {"available": False, "reason": est["reason"]}

    months = {_month_key(t) for t in returns_df.index}
    out: list[dict] = []
    out.append({"name": "trailing", "mu": est["mu"], "se": est["se"],
                "n_months": len(months), "months": months,
                "note": "전체 창의 표본평균"})

    unavailable: dict[str, str] = {}
    if regime_by_month and current_regime:
        from src.engine.conditional_market import conditional_moments
        cond = conditional_moments(returns_df, regime_by_month, current_regime)
        if cond.get("available"):
            reg_months = {m for m, g in regime_by_month.items() if g == current_regime}
            years = max(len(reg_months), 1) / 12.0
            sd = np.sqrt(np.maximum(np.diag(np.asarray(cond["sigma"], dtype=float)), 0.0))
            out.append({"name": "conditional", "mu": np.asarray(cond["mu"], dtype=float),
                        "se": sd / np.sqrt(years),
                        "n_months": len(reg_months), "months": reg_months,
                        "regime": cond.get("regime"),
                        "note": f"국면 '{cond.get('regime')}' 표본의 평균"})
        else:
            unavailable["conditional"] = cond.get("reason") or "조건부 μ 를 낼 수 없습니다"
    else:
        unavailable["conditional"] = "국면 라벨이 없어 조건부 μ 를 낼 수 없습니다"

    return {"available": True, "reason": None, "names": names,
            "forecasts": out, "unavailable": unavailable,
            "note": ("예측마다 창(months)을 함께 모읍니다 — 겹침을 모르면 상관을 "
                     "계산할 수 없고, 독립으로 가정하면 정밀도가 부풀려집니다")}


def correlation_from_windows(forecasts: list[dict]) -> dict:
    """예측들의 창 겹침 → 상관행렬."""
    k = len(forecasts)
    C = np.eye(k)
    pairs = []
    for i in range(k):
        for j in range(i + 1, k):
            a, b = forecasts[i].get("months"), forecasts[j].get("months")
            if not a or not b:
                pairs.append({"pair": [forecasts[i]["name"], forecasts[j]["name"]],
                              "available": False,
                              "reason": "창을 알 수 없어 상관을 계산하지 못했습니다"})
                continue
            ov = overlap_correlation(len(a), len(b), len(a & b))
            if ov["available"]:
                C[i, j] = C[j, i] = ov["rho"]
            pairs.append({"pair": [forecasts[i]["name"], forecasts[j]["name"]], **ov})
    return {"available": True, "matrix": C, "pairs": pairs}
