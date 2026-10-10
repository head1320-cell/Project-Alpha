"""역스트레스 — ★−15% 손실을 보려면 무엇이 일어나야 하는가★ (Brief §12)

    "포트폴리오가 -15% 손실을 보려면 어떤 macro shock 조합이 필요한가?"

정스트레스는 "이 충격이 오면 얼마 잃나" 를 묻는다. 역스트레스는 **거꾸로** 묻는다 —
손실을 고정하고 그것을 만드는 충격을 찾는다. 답이 하나가 아니므로(무수한 조합이
같은 손실을 낸다) **가장 그럴듯한 조합**을 고른다:

    min  s' Σf⁻¹ s        (마할라노비스 거리 = 그럴듯함의 반대)
    s.t. β' s = L         (팩터 노출 × 충격 = 목표 손실)

닫힌 해가 있다:

    s* = L · Σf β / (β' Σf β)
    거리 d = |L| / sqrt(β' Σf β)     ← 이 시나리오가 몇 σ 짜리인가

★거리를 반드시 함께 낸다★ 충격 벡터만 내면 "이게 현실적인가" 를 알 수 없다.
d=1 이면 흔한 달이고 d=6 이면 표본에 없던 사건이다 — 같은 −15% 라도 완전히 다른
이야기다.

★재사용★ 팩터 노출 β 는 `factor_exposure`, 축소 공분산은 P2.5 의 `_shrunk_cov`.
여기서 새로 짓는 것은 역산뿐이다.
"""
from __future__ import annotations

import numpy as np

DEFAULT_LOSS_PCT = -15.0
MIN_MONTHS = 24


def factor_covariance(resolved: dict, *, shrinkage="lw") -> dict:
    """팩터 월별 변화의 공분산 — ★공통 월만 쓴다★

    계열마다 관측 구간이 달라 그냥 붙이면 서로 다른 달을 비교하게 된다.
    """
    from src.engine.conditional_market import _shrunk_cov

    factors = list(resolved)
    if len(factors) < 2:
        return {"available": False, "reason": "팩터가 2개 미만입니다"}

    months: set[str] | None = None
    for f in factors:
        m = set(resolved[f]["changes"])
        months = m if months is None else (months & m)
    shared = sorted(months or [])
    if len(shared) < MIN_MONTHS:
        return {"available": False,
                "reason": (f"팩터가 공통으로 갖는 달이 {len(shared)}개뿐입니다 "
                           f"(최소 {MIN_MONTHS}개)")}

    X = np.array([[resolved[f]["changes"][m] for f in factors] for m in shared],
                 dtype=float)
    if not np.all(np.isfinite(X)):
        return {"available": False, "reason": "팩터 변화에 유한하지 않은 값이 있습니다"}

    # ★단위를 섞은 채 수축하지 않는다★ `pct` 팩터는 분수(σ≈0.003)이고 `diff`
    # 팩터는 지수 포인트(σ≈4.5)라 원자료 σ 가 **1750배** 벌어져 있다. Ledoit-Wolf
    # 는 공통 분산 목표로 수축하는데 그 목표를 큰 팩터가 지배해, 작은 팩터의 σ 가
    # 통째로 부풀려진다(실측: inflation 0.00257 → 0.43957, **171배**).
    # 그래서 **표준화 → 상관에 수축 → 스케일 복원** 순서로 간다.
    sd_raw = X.std(axis=0, ddof=1)
    live = [i for i, v in enumerate(sd_raw) if np.isfinite(v) and v > 0]
    excluded = {factors[i]: "이 팩터의 변화가 상수라 표준화할 수 없습니다"
                for i in range(len(factors)) if i not in live}
    if len(live) < 2:
        return {"available": False,
                "reason": "변동이 있는 팩터가 2개 미만입니다", "excluded": excluded}

    factors = [factors[i] for i in live]
    X = X[:, live]
    sd_raw = sd_raw[live]

    Z = (X - X.mean(axis=0)) / sd_raw          # 무차원 — 0 나눗셈은 위에서 배제
    Sz, lam, method = _shrunk_cov(Z, shrinkage)
    D = np.diag(sd_raw)
    S = D @ Sz @ D                              # 상관만 수축하고 σ 는 보존
    sd = np.sqrt(np.maximum(np.diag(S), 0.0))
    return {
        "available": True, "reason": None,
        "factors": factors, "cov": S, "sd": sd,
        # ★무엇을 했는지 숨기지 않는다★
        "scale_normalized": True,
        "sd_raw": {f: round(float(v), 8) for f, v in zip(factors, sd_raw, strict=True)},
        "excluded": excluded,
        "n_months": len(shared), "span": [shared[0], shared[-1]],
        "shrinkage_lambda": (round(float(lam), 4) if lam is not None else None),
        "method": method,
        # ★λ 가 1 이면 상관구조가 지워진 것이다★ 숫자는 나오지만 뜻이 다르다.
        "degenerate": bool(lam is not None and lam >= 0.99),
        "note": ("공통 월만 사용합니다 — 계열마다 구간이 다른데 그냥 붙이면 "
                 "서로 다른 달을 비교하게 됩니다. 수축은 **상관**에만 걸고 각 "
                 "팩터의 σ 는 원자료 그대로 보존합니다(단위가 섞여 있기 때문)"),
    }


def reverse_stress(exposure: dict, cov: dict, *,
                   loss_pct: float = DEFAULT_LOSS_PCT) -> dict:
    """목표 손실을 만드는 **가장 그럴듯한** 팩터 충격 조합.

    ★답이 하나가 아니다★ 무수한 조합이 같은 손실을 낸다. 그중 마할라노비스 거리가
    최소인 것을 고르고, **그 거리를 함께 낸다** — 충격만 내면 현실성을 알 수 없다.
    """
    if not exposure.get("available"):
        return {"available": False,
                "reason": exposure.get("reason") or "팩터 노출이 없습니다"}
    if not cov.get("available"):
        return {"available": False, "reason": cov.get("reason")}
    if loss_pct == 0:
        return {"available": False, "reason": "목표 손실이 0 이면 충격이 필요 없습니다"}

    factors = cov["factors"]
    by = exposure["by_factor"]
    usable = [f for f in factors
              if by.get(f, {}).get("available") and by[f].get("exposure") is not None]
    if len(usable) < 1:
        return {"available": False, "reason": "노출을 가진 팩터가 없습니다"}

    idx = [factors.index(f) for f in usable]
    S = np.asarray(cov["cov"], dtype=float)[np.ix_(idx, idx)]
    beta = np.array([float(by[f]["exposure"]) for f in usable], dtype=float)

    Sb = S @ beta
    denom = float(beta @ Sb)
    if not np.isfinite(denom) or denom <= 0:
        # ★분모가 0 이면 이 노출로는 어떤 충격도 손실을 만들지 못한다★
        return {"available": False,
                "reason": ("팩터 노출이 사실상 0 이라 어떤 충격 조합으로도 목표 손실을 "
                           "만들 수 없습니다 (β'Σβ ≤ 0)")}

    L = float(loss_pct) / 100.0
    s = L * Sb / denom
    distance = abs(L) / float(np.sqrt(denom))

    sd = np.asarray(cov["sd"], dtype=float)[idx]
    with np.errstate(divide="ignore", invalid="ignore"):
        in_sd = np.where(sd > 0, s / sd, np.nan)

    shocks = []
    for i, f in enumerate(usable):
        row = by[f]
        shocks.append({
            "factor": f, "series": row.get("series"),
            "transform": row.get("transform"),
            "shock": round(float(s[i]), 6),
            "shock_in_sd": (round(float(in_sd[i]), 3)
                            if np.isfinite(in_sd[i]) else None),
            "exposure": round(float(beta[i]), 4),
            "contribution_pct": round(float(beta[i] * s[i]) * 100.0, 4),
            "coverage_pct": row.get("coverage_pct"),
            "resolvable_pct": row.get("resolvable_pct"),
        })
    shocks.sort(key=lambda r: abs(r["contribution_pct"]), reverse=True)

    return {
        "available": True, "reason": None,
        "target_loss_pct": float(loss_pct),
        "shocks": shocks,
        "factors_used": usable,
        "factors_unused": [f for f in factors if f not in usable],
        # ★몇 σ 짜리 시나리오인가★ 이것 없이 충격만 보면 현실성을 알 수 없다.
        "distance": round(distance, 3),
        "plausibility": _plausibility(distance),
        "sample": {"n_months": cov["n_months"], "span": cov["span"],
                   "shrinkage_lambda": cov["shrinkage_lambda"]},
        "degenerate_covariance": cov["degenerate"],
        "method": "min_mahalanobis_shock",
        # ★베타가 잡음이면 시나리오도 잡음이다★ 거리만 보고 "흔하다" 고 읽지 않도록.
        "beta_quality": _beta_quality(shocks),
        "note": ("같은 손실을 내는 충격 조합은 무수히 많습니다 — 그중 마할라노비스 "
                 "거리가 최소인 것, 곧 **가장 그럴듯한** 조합입니다. 유일한 답이 "
                 "아니라 가장 가까운 답입니다"),
    }


def _beta_quality(shocks: list[dict]) -> dict:
    """이 시나리오가 **통계적으로 구분되는** 베타 위에 서 있는가.

    `|t| < 2` 인 베타로 만든 충격은 잡음이다. 거리가 작다고 "흔한 시나리오" 로
    읽으면 안 되는 경우가 여기다 — 애초에 노출 자체를 못 믿는다.
    """
    vals = [s.get("resolvable_pct") for s in shocks if s.get("resolvable_pct") is not None]
    if not vals:
        return {"available": False,
                "reason": "베타의 통계적 유의성을 확인할 수 없습니다"}
    mean_res = sum(vals) / len(vals)
    return {
        "available": True,
        "mean_resolvable_pct": round(mean_res, 2),
        "trustworthy": bool(mean_res >= 50.0),
        "note": ("|t| ≥ 2 인 베타가 차지하는 평균 비중입니다. 낮으면 이 시나리오는 "
                 "구분되지 않는 노출 위에 서 있으므로 거리(σ)를 액면대로 읽지 "
                 "마십시오 — 잡음으로 만든 충격은 잡음입니다"),
    }


def _plausibility(d: float) -> dict:
    """거리 → 읽을 수 있는 말. ★숫자를 말로 바꾸되 숫자를 지우지 않는다★"""
    if d < 1.0:
        label, text = "routine", "흔한 달 수준입니다 — 이 손실은 특별한 사건을 필요로 하지 않습니다"
    elif d < 2.0:
        label, text = "plausible", "표본에서 드물지 않게 보이는 크기입니다"
    elif d < 3.0:
        label, text = "severe", "표본에서 드문 크기입니다"
    else:
        label, text = "extreme", "표본 안에서 사실상 관측되지 않은 크기입니다"
    return {"label": label, "sigma": round(d, 3), "text": text}
