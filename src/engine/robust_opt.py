"""로버스트 최적화 — ★μ 를 얼마나 모르는지를 최적화에 넣는다★ (Brief §8.3)

    μ ∈ U_mu  ·  최악조건에서도 유효한 배분

★실측이 이 모듈의 존재 이유다★ `005930`·`000660`·`035420`·`005380` 3년(756일):

    자산       μ(연%)   σ(연%)   SE(연%)   |μ|/SE
    005930     -2.55    28.70    16.57     0.15
    000660     27.62    29.58    17.08     1.62
    035420     13.51    28.18    16.27     0.83
    005380     14.66    29.06    16.78     0.87

연율 평균의 표준오차가 **16~17%p** 로 μ 자체와 맞먹는다. `|μ|/SE` 가 **전부 2 미만**
이라 어느 자산의 기대수익도 0과 구분되지 않는다. 그런데 평문 MVO 는 이 μ 를 그대로
믿고 `000660` 에 76.6% 를 넣는다 — **잡음에 76%를 거는 것**이다.

★불확실성 집합의 모양이 결과를 지배한다 (실측)★

    형태                    HHI: κ=0 → 최대
    박스 (μ̂ − κ)           0.616 → 0.578   거의 안 움직인다
    타원체 (아래)           0.616 → 0.264   등가중(0.250)으로 수렴

박스가 안 듣는 이유는 SE 가 자산마다 비슷해서 κ 를 빼도 **상대 순위가 그대로**이기
때문이다. 타원체는 집중된 w 일수록 페널티가 커져 실제로 분산시킨다:

    worst-case μ'w = μ̂'w − κ·sqrt(w' Σ_μ w),   Σ_μ = Σ / T_years

★첫 시도는 틀렸다★ 처음엔 `μ̂ − κ` 를 `_max_sharpe_w` 에 넣었는데 100% 한 종목으로
**집중**됐다 — 로버스트의 반대다. max-Sharpe 에는 위험 페널티 λ 가 없어 순위만 보기
때문이다. 로버스트는 평균-분산 **효용**을 최대화해야 한다.
"""
from __future__ import annotations

import numpy as np

# 정규분포 분위수 — κ 의 뜻을 신뢰수준으로 읽을 수 있게 한다.
KAPPA_PRESETS: dict[str, float] = {
    "none": 0.0, "low": 1.0, "medium": 1.6448536269514722,   # 90%
    "high": 2.5758293035489004,                              # 99%
}
DEFAULT_KAPPA = KAPPA_PRESETS["medium"]
DEFAULT_DELTA = 2.5
TRADING_DAYS = 252

# |μ|/SE 가 이 값을 넘으면 "0과 구분된다" 고 본다(양측 95% 근사).
_RESOLVABLE_T = 2.0


def mu_standard_errors(R: np.ndarray) -> dict:
    """μ̂ 와 그 **표준오차** — ★얼마나 모르는지를 먼저 잰다★

    `t = |μ̂| / SE` 가 2 를 넘지 못하면 그 자산의 기대수익은 표본상 0과 구분되지
    않는다. 그 사실을 최적화에 넣지 않으면 잡음에 비중을 걸게 된다.
    """
    R = np.asarray(R, dtype=float)
    if R.ndim != 2 or R.shape[0] < 2:
        return {"available": False, "reason": "수익률 표본이 2행 미만입니다"}
    T, n = R.shape
    years = T / TRADING_DAYS
    if years <= 0:
        return {"available": False, "reason": "표본 기간이 0입니다"}

    mu = R.mean(axis=0) * TRADING_DAYS
    sd = R.std(axis=0, ddof=1) * np.sqrt(TRADING_DAYS)
    se = sd / np.sqrt(years)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(se > 0, np.abs(mu) / se, 0.0)

    resolvable = [bool(x >= _RESOLVABLE_T) for x in t]
    return {
        "available": True, "reason": None,
        "mu": mu, "se": se, "t": t,
        "n_obs": int(T), "years": round(years, 3),
        "resolvable": resolvable,
        "n_resolvable": int(sum(resolvable)),
        "note": ("|μ|/SE 가 2 미만이면 그 자산의 기대수익은 표본상 0과 구분되지 "
                 "않습니다 — 그 μ 에 비중을 거는 것은 잡음에 거는 것입니다"),
    }


def uncertainty_scalar(t: np.ndarray) -> float:
    """μ 불확실성을 `[0,1]` 로 — 리밸런싱 밴드가 받는 값.

    전부 `|μ|/SE ≥ 2` 면 0(확신), 전부 0 이면 1(정보 없음). 밴드는 `1+u` 배로
    넓어진다 — ★모르는 목표를 쫓아 거래하지 않기 위해서다.★
    """
    t = np.asarray(t, dtype=float)
    if t.size == 0:
        return 1.0
    resolved = np.clip(t, 0.0, _RESOLVABLE_T) / _RESOLVABLE_T
    return float(np.clip(1.0 - resolved.mean(), 0.0, 1.0))


def _solve_robust(mu: np.ndarray, S: np.ndarray, S_mu: np.ndarray,
                  kappa: float, delta: float) -> tuple[np.ndarray | None, str | None]:
    """max_w  μ̂'w − κ·sqrt(w'Σ_μw) − (δ/2)·w'Σw,  w ≥ 0, Σw = 1.

    ★평균-분산 효용을 최대화한다 (max-Sharpe 가 아니다)★ 위험 페널티가 없으면
    최악조건 μ 의 **순위**만 보게 되어 오히려 한 종목으로 집중된다(실측).
    """
    from scipy.optimize import minimize

    n = len(mu)

    def neg_utility(w: np.ndarray) -> float:
        quad = float(w @ S_mu @ w)
        pen = kappa * np.sqrt(quad) if quad > 0 else 0.0
        return -(float(mu @ w) - pen) + 0.5 * delta * float(w @ S @ w)

    res = minimize(neg_utility, np.ones(n) / n, method="SLSQP",
                   bounds=[(0.0, 1.0)] * n,
                   constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1.0}],
                   options={"maxiter": 400, "ftol": 1e-10})
    if not res.success:
        return None, f"최적화가 수렴하지 않았습니다: {res.message}"
    w = np.maximum(np.asarray(res.x, dtype=float), 0.0)
    total = w.sum()
    if not np.isfinite(total) or total <= 0:
        return None, "해가 유효하지 않습니다(합이 0 이하)"
    return w / total, None


def robust_weights(names: list[str], R: np.ndarray, *,
                   kappa: float = DEFAULT_KAPPA,
                   delta: float = DEFAULT_DELTA,
                   s_override: np.ndarray | None = None) -> dict:
    """타원체 불확실성 집합 위의 로버스트 평균-분산 배분.

    ★κ 가 커질수록 등가중으로 수렴한다★ 이것이 로버스트의 정의다 — μ 를 못 믿을수록
    μ 에 기대지 않는 배분으로 간다. 실측 HHI 0.616 → 0.264(등가중 0.250).
    """
    R = np.asarray(R, dtype=float)
    n = len(names)
    if R.ndim != 2 or R.shape[1] != n:
        return {"available": False,
                "reason": f"수익률 모양이 자산 수({n})와 맞지 않습니다: {R.shape}"}
    if kappa < 0:
        return {"available": False, "reason": "κ 는 0 이상이어야 합니다"}
    if delta <= 0:
        return {"available": False, "reason": "위험회피 δ 는 0보다 커야 합니다"}

    est = mu_standard_errors(R)
    if not est["available"]:
        return {"available": False, "reason": est["reason"]}

    from src.engine.allocation_studio import _cov, effective_number_of_bets
    S = (np.asarray(s_override, dtype=float) if s_override is not None
         else _cov(R) * TRADING_DAYS)
    if S.shape != (n, n) or not np.all(np.isfinite(S)):
        return {"available": False, "reason": "공분산이 유효하지 않습니다"}

    mu = est["mu"]
    # 평균 추정량의 공분산 — 표본이 길수록 작아진다(불확실성이 준다).
    S_mu = S / max(est["years"], 1e-9)

    w, err = _solve_robust(mu, S, S_mu, float(kappa), float(delta))
    if w is None:
        return {"available": False, "reason": err}
    w0, err0 = _solve_robust(mu, S, S_mu, 0.0, float(delta))

    hhi = float((w ** 2).sum())
    equal_hhi = 1.0 / n
    # ★κ 가 지배하면 μ 가 무시된 것이다★ 그 사실을 말한다 — 숫자만 보면 "최적화했다"
    # 로 읽히지만 실제로는 "기대수익을 쓰지 않기로 했다" 이다.
    collapsed = bool(abs(hhi - equal_hhi) < 0.02 and kappa > 0)

    return {
        "available": True, "reason": None,
        "weights": w, "names": list(names),
        "weights_pct": {nm: round(float(v) * 100.0, 4)
                        for nm, v in zip(names, w, strict=False)},
        "kappa": float(kappa), "delta": float(delta),
        "mu_annual": {nm: round(float(v), 6)
                      for nm, v in zip(names, mu, strict=False)},
        "se_annual": {nm: round(float(v), 6)
                      for nm, v in zip(names, est["se"], strict=False)},
        # ★어느 자산의 μ 가 0과 구분되는가★ 실측에서는 넷 다 구분되지 않았다.
        "mu_over_se": {nm: round(float(v), 4)
                       for nm, v in zip(names, est["t"], strict=False)},
        "n_resolvable": est["n_resolvable"], "n_assets": n,
        "uncertainty": round(uncertainty_scalar(est["t"]), 4),
        "concentration": {
            "hhi": round(hhi, 4),
            "hhi_naive": round(float((w0 ** 2).sum()), 4) if w0 is not None else None,
            "hhi_equal_weight": round(equal_hhi, 4),
            "enb": round(float(effective_number_of_bets(w, S)), 4),
        },
        "collapsed_to_equal_weight": collapsed,
        "note": ("불확실성 집합은 타원체입니다 — 집중된 배분일수록 최악조건 페널티가 "
                 "커집니다. κ 가 커질수록 등가중으로 수렴하는 것이 로버스트의 정의입니다"),
        "naive_reason": err0,
    }
