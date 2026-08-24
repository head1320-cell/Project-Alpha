"""P3-4 — Company 팩터 노출 → **포트폴리오 팩터 리스크**

로드맵 P3-4. `factor_exposure` 가 자산별 팩터 베타를 내고 그것을 비중으로 합쳐
포트폴리오 노출 β 를 만든다. 이 모듈은 그 β 와 팩터 공분산 Σf 로 **포트폴리오
분산을 팩터와 고유로 쪼갠다.**

    총분산 = β'Σfβ (팩터 설명) + 고유분산
    팩터 i 의 기여 = βᵢ · (Σfβ)ᵢ        (합 = β'Σfβ)

★고유분산이 음수로 나올 수 있다★ 베타를 **단변량**으로 추정하기 때문이다 — 팩터가
서로 상관되면 각 베타가 공통 변동을 중복해서 흡수해 설명분산이 총분산을 넘는다.
실측에서 단위 혼재 결함이 있을 때 고유분산이 **−2.43** 이었다. 그때는 0 으로
클램프하지 않고 **초과 설명**이라고 말한다 — 클램프하면 "팩터가 100% 설명한다" 로
읽히는데 그것은 사실이 아니라 추정 방식의 한계다.

★총분산은 실제 포트폴리오 수익률에서 잰다★ 자산 공분산을 여기서 다시 짓지 않는다.
"""
from __future__ import annotations

import numpy as np

MIN_MONTHS = 24


def portfolio_monthly_returns(weights: dict[str, float], *,
                              months: int = 60) -> dict:
    """비중 고정 가정의 포트폴리오 월별 수익률.

    ★비중을 고정으로 본다는 것을 밝힌다★ 실제로는 드리프트하지만, 여기서 재려는
    것은 "지금 이 배분이 갖는 분산" 이다.
    """
    from src.engine.conditional_market import _month_key
    from src.engine.portfolio_weights import signed_fractions
    from src.engine.valuation.macro_sensitivity import _monthly_returns

    # ★숏을 건너뛰지 않는다★ 예전에는 `if max(w,0) <= 0: continue` 라 숏 다리가
    # 계열 수집에서부터 빠졌고, 커버리지는 남은 롱 북만으로 계산돼 높게 나왔다.
    # 중립 북의 분산이 롱 북의 분산으로 보고되던 경로다. gross 로 나눈다.
    fractions = signed_fractions(weights)
    if not fractions:
        return {"available": False, "reason": "비중이 없습니다 (gross = 0)"}

    series: dict[str, dict[str, float]] = {}
    missing: list[str] = []
    for code in fractions:
        r = _monthly_returns(str(code), months=months)
        if r is None or r.empty:
            missing.append(str(code))
            continue
        series[str(code)] = {_month_key(t): float(v) for t, v in r.items()}

    if not series:
        return {"available": False, "reason": "어떤 자산도 월별 수익률을 내지 못했습니다",
                "missing": missing}

    shared = sorted(set.intersection(*[set(v) for v in series.values()]))
    if len(shared) < MIN_MONTHS:
        return {"available": False,
                "reason": (f"자산들이 공통으로 갖는 달이 {len(shared)}개뿐입니다 "
                           f"(최소 {MIN_MONTHS}개)"), "missing": missing}

    # ★커버리지도 gross 기준★ 부호대로 더하면 중립 북에서 상쇄된다.
    covered = sum(abs(fractions[c]) for c in series)
    port = np.array([sum(fractions[c] * series[c][m] for c in series)
                     for m in shared], dtype=float)
    return {
        "available": True, "reason": None,
        "returns": port, "months": shared,
        "variance": float(port.var(ddof=1)),
        "coverage_pct": round(covered * 100.0, 2),
        "missing": missing,
        "note": ("비중을 기간 내내 고정으로 가정합니다 — 재는 것은 '지금 이 배분이 "
                 "갖는 분산' 입니다"),
    }


def portfolio_factor_risk(exposure: dict, cov: dict, *,
                          total_variance: float | None = None) -> dict:
    """β'Σfβ 로 팩터 분산을 내고 총분산에서 고유분산을 뺀다."""
    if not exposure.get("available"):
        return {"available": False,
                "reason": exposure.get("reason") or "팩터 노출이 없습니다"}
    if not cov.get("available"):
        return {"available": False, "reason": cov.get("reason")}

    factors = cov["factors"]
    by = exposure["by_factor"]
    used = [f for f in factors
            if by.get(f, {}).get("available") and by[f].get("exposure") is not None]
    if not used:
        return {"available": False, "reason": "노출을 가진 팩터가 없습니다"}

    idx = [factors.index(f) for f in used]
    S = np.asarray(cov["cov"], dtype=float)[np.ix_(idx, idx)]
    beta = np.array([float(by[f]["exposure"]) for f in used], dtype=float)

    Sb = S @ beta
    factor_var = float(beta @ Sb)
    if not np.isfinite(factor_var) or factor_var < 0:
        return {"available": False,
                "reason": f"팩터 분산이 유효하지 않습니다: {factor_var}"}

    contrib = beta * Sb
    rows = [{
        "factor": f,
        "series": by[f].get("series"),
        "exposure": round(float(beta[i]), 4),
        "variance_contribution": round(float(contrib[i]), 10),
        "share_of_factor_pct": (round(float(contrib[i]) / factor_var * 100.0, 2)
                                if factor_var > 0 else None),
        "coverage_pct": by[f].get("coverage_pct"),
        "resolvable_pct": by[f].get("resolvable_pct"),
    } for i, f in enumerate(used)]
    rows.sort(key=lambda r: abs(r["variance_contribution"]), reverse=True)

    out: dict = {
        "available": True, "reason": None,
        "factor_variance": round(factor_var, 10),
        "factor_volatility": round(float(np.sqrt(max(factor_var, 0.0))), 6),
        "rows": rows,
        "factors_used": used,
        "factors_unused": [f for f in factors if f not in used],
        "beta_quality": _quality(rows),
        "method": "univariate_beta_factor_model",
        "note": ("베타가 **단변량**이라 팩터끼리 상관되면 공통 변동을 중복 흡수해 "
                 "설명분산이 총분산을 넘을 수 있습니다 — 그때는 초과 설명이라고 "
                 "말하지 0 으로 자르지 않습니다"),
    }

    if total_variance is None:
        out.update(total_variance=None, idiosyncratic_variance=None,
                   factor_share_pct=None, over_explained=None,
                   share_reason="총분산을 주지 않아 설명 비율을 계산하지 않았습니다")
        return out

    tv = float(total_variance)
    if not np.isfinite(tv) or tv <= 0:
        out.update(total_variance=tv, idiosyncratic_variance=None,
                   factor_share_pct=None, over_explained=None,
                   share_reason="총분산이 0 이하라 비율을 낼 수 없습니다")
        return out

    idio = tv - factor_var
    over = bool(idio < 0)
    out.update(
        total_variance=round(tv, 10),
        total_volatility=round(float(np.sqrt(tv)), 6),
        idiosyncratic_variance=round(float(idio), 10),
        factor_share_pct=round(factor_var / tv * 100.0, 2),
        idiosyncratic_share_pct=round(idio / tv * 100.0, 2),
        # ★자르지 않는다★ 초과 설명은 사실이고, 그 사실이 추정 한계를 말해 준다.
        over_explained=over,
        share_reason=(("팩터 설명분산이 총분산을 넘었습니다 — 단변량 베타가 공통 "
                       "변동을 중복 흡수한 결과이지 팩터가 전부를 설명한다는 뜻이 "
                       "아닙니다") if over else None),
    )
    return out


def _quality(rows: list[dict]) -> dict:
    """분해가 **통계적으로 구분되는** 베타 위에 서 있는가."""
    vals = [r.get("resolvable_pct") for r in rows if r.get("resolvable_pct") is not None]
    if not vals:
        return {"available": False, "reason": "베타의 유의성을 확인할 수 없습니다"}
    mean_res = sum(vals) / len(vals)
    return {"available": True,
            "mean_resolvable_pct": round(mean_res, 2),
            "trustworthy": bool(mean_res >= 50.0),
            "note": ("|t| ≥ 2 인 베타가 차지하는 평균 비중입니다. 낮으면 이 분해는 "
                     "구분되지 않는 노출 위에 서 있습니다")}
