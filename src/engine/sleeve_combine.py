"""전략 슬리브 결합 + 리스크 예산 + 상관/군집/꼬리 분석 (Full Expansion P3 잔여)
==============================================================================
지시서: "포트폴리오 매니저는 여러 전략 슬리브를 결합하고 리스크 예산을 배분한다."
2단계 최적화(슬리브 레벨 배분 → 종목 레벨 배분), 슬리브별 리스크 예산, 슬리브/알파 간
상관·군집·리스크 기여, 꼬리 의존(§8: "상관·꼬리의존·군집 결과를 계산할 수 있다").

슬리브 = {name, weights:{code:frac}}. 슬리브 수익 = Σ w_i·r_i (종목 수익에서 유도).
returns 주입 가능(테스트) — 미주입 시 risk_allocations의 일별수익 행렬 로더 재사용.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

SLEEVE_METHODS = ("equal", "inverse_vol", "risk_parity", "risk_budget", "min_var", "hrp", "score",
                  # BS4 — 사용자 승인(2026-09-29): 고를 때만 쓰인다. 기본값(risk_parity)은 그대로.
                  "manual", "crisis_risk_parity", "max_diversification")
#: 입력이 없어도 되는 방법 — 방법 비교표가 같은 흐름에서 나란히 잰다.
INPUT_FREE_METHODS = ("risk_parity", "equal", "inverse_vol", "min_var", "hrp", "max_diversification", "crisis_risk_parity")
#: 위기일 — 시장 대용이 가장 나빴던 이 비율의 날(견고성 절 `crisis_correlation` 과 같은 선택).
CRISIS_Q = 0.1
#: 위기일이 이보다 적으면 위기 공분산을 믿을 수 없어 실패한다(평소 공분산으로 가지 않는다).
CRISIS_MIN_DAYS = 20
#: 몫 직접 정하기 — 합 100 에서 이만큼까지 허용(반올림).
MANUAL_SUM_TOL = 0.01
_NO_FALLBACK = {"used": False, "from": None, "reason": None}


def _drift_returns(R: np.ndarray, w: np.ndarray, every: int, cost_bps: float = 0.0) -> np.ndarray:
    """k 거래일마다 목표 비중으로 되돌리는 슬리브의 일별 수익 (BO O2 — 사용자 승인 배분 동작 변경).

    되돌린 날 사이에는 보유량이 종목 수익만큼 흘러간다(드리프트). k 일째 **끝에** 목표 비중으로 되돌린다.
    `cost_bps`(BP P2 — 사용자 승인): 되돌리는 날 회전율(흘러간 비중과 목표의 차의 절댓값 합 — 사고판 양쪽) × 비용을
    그날 가치에서 뺀다. 0 이면 BO O2 와 같다. 슬리피지·시장 충격은 넣지 않는다 — 호출부가 그 사실을 말한다.
    """
    T = R.shape[0]
    out = np.empty(T)
    c = cost_bps / 1e4
    v = w.copy()                                  # 합 1 로 정규화된 보유 가치
    for t in range(T):
        grown = v * (1.0 + R[t])
        tot = float(grown.sum())
        if (t + 1) % every == 0:
            turnover = float(np.abs(grown / tot - w).sum()) if c > 0 else 0.0
            out[t] = tot * (1.0 - c * turnover) - 1.0
            v = w.copy()
        else:
            out[t] = tot - 1.0
            v = grown / tot
    return out


#: 거래비용 상한(bp) — 이보다 크면 입력 실수로 본다(10%).
COST_BPS_MAX = 1000.0


def _sleeve_return_series(sleeves: list[dict], ret_matrix: dict[str, list[float]],
                          rebalance_every: dict[str, int] | None = None,
                          cost_bps: dict[str, float] | None = None) -> tuple[list[str], np.ndarray]:
    """슬리브별 일별수익 행렬 (T×S). ret_matrix: code -> 일별수익 리스트(정렬 동일 길이).

    `rebalance_every` (BO O2): 슬리브 이름 → 되돌리는 주기(거래일). 없거나 1 이면 **지금과 같은 식**
    `R @ w`(매일 목표 비중으로 되돌린 흐름)를 그대로 쓴다 — 기본 동작은 비트 단위로 같다.
    """
    every_of = dict(rebalance_every or {})
    bad = {k: v for k, v in every_of.items() if not isinstance(v, int) or isinstance(v, bool) or v < 1}
    if bad:
        raise ValueError(f"리밸런싱 주기는 1 이상의 거래일 수여야 해요: {bad}")
    cost_of = dict(cost_bps or {})
    bad_cost = {k: v for k, v in cost_of.items()
                if not isinstance(v, (int, float)) or isinstance(v, bool) or not np.isfinite(v) or not 0 <= v <= COST_BPS_MAX}
    if bad_cost:
        raise ValueError(f"거래비용은 0~{COST_BPS_MAX:g}bp 의 숫자여야 해요: {bad_cost}")
    codes = sorted({c for s in sleeves for c in s.get("weights", {})})
    codes = [c for c in codes if c in ret_matrix and len(ret_matrix[c]) >= 2]
    if not codes:
        return [], np.empty((0, 0))
    T = min(len(ret_matrix[c]) for c in codes)
    R = np.array([ret_matrix[c][-T:] for c in codes]).T   # T×N
    names = [s["name"] for s in sleeves]
    S = np.zeros((T, len(sleeves)))
    for j, s in enumerate(sleeves):
        w = np.array([max(s.get("weights", {}).get(c, 0.0), 0.0) for c in codes])
        wsum = w.sum()
        if wsum > 0:
            w = w / wsum
        k = every_of.get(s["name"], 1)
        cb = float(cost_of.get(s["name"], 0.0))
        # 주기 1·비용 0 이면 지금까지의 식 그대로. 비용이 있으면 매일 주기라도 매일 되돌리는 비용을 낸다.
        S[:, j] = (R @ w if wsum <= 0 or (k <= 1 and cb <= 0)
                   else _drift_returns(R, w, max(k, 1), cb))
    return names, S


def _cov_local(S: np.ndarray) -> np.ndarray:
    try:
        from src.engine.risk_allocations import _cov
        return _cov(S)
    except Exception:
        c = np.cov(S.T)
        return np.atleast_2d(c) + np.eye(S.shape[1]) * 1e-8


#: 순환 반복의 감쇠 지수. ★1.0(전 스텝)은 발산한다★ — 아래 주석의 실측 참조.
RISK_BUDGET_DAMPING = 0.5
#: 비중 하한. `0` 으로 자르면 한 번 0 이 된 자산이 **영원히 돌아오지 못한다**.
_W_FLOOR = 1e-12


def _risk_budget_weights(cov: np.ndarray, budget: np.ndarray, iters: int = 200,
                         damping: float = RISK_BUDGET_DAMPING) -> np.ndarray:
    """리스크 예산 배분 — RC_i ∝ budget_i (등예산이면 리스크 패리티). 순환 반복.

    ★감쇠가 없으면 발산한다 (실측)★ 예전에는 `w ← w·(b/rc_share)` 로 **전 스텝**을
    밟았다. 2슬리브(연변동성 21.2%·29.0%, ρ=−0.06)에서 기여 비율이 진동하며 커졌다:

        0.340 → 0.679 → 0.301 → 0.721 → 0.255 → 0.771 → …

    결국 한쪽이 `np.clip(w, 0, None)` 으로 **정확히 0** 이 되고, 0 은 곱셈 갱신에서
    영원히 0 이라 돌아오지 못한다. 결과가 리스크 **패리티**인데 `[0, 1]` 이었다.

    ★감쇠 0.5 는 해석해와 일치한다★ 무상관이면 답이 `w ∝ 1/σ` 로 닫혀 있다:

        2자산 → [0.577512, 0.422488]   (해석해와 소수 6자리까지 동일)
        3자산 → [0.571429, 0.285714, 0.142857]

    감쇠 1.0 은 같은 입력에서 [0.846, 0.154] 를 낸다 — 이 함수의 회귀 가드가
    그 두 값을 가른다.
    """
    b = budget / budget.sum()
    w = b.copy()
    for _ in range(iters):
        sigma = float(np.sqrt(w @ cov @ w))
        if sigma <= 0:
            break
        mrc = cov @ w / sigma
        rc = w * mrc
        rc_sum = rc.sum() or 1.0
        # 목표 예산 대비 기여 비율로 조정 — ★부분 스텝★
        w = w * np.power(b / (rc / rc_sum + 1e-12), damping)
        w = np.clip(w, _W_FLOOR, None)
        w = w / w.sum()
    return w


def _risk_contributions(w: np.ndarray, cov: np.ndarray) -> np.ndarray:
    sigma = float(np.sqrt(w @ cov @ w))
    if sigma <= 0:
        return np.zeros_like(w)
    rc = w * (cov @ w) / sigma
    tot = rc.sum() or 1.0
    return rc / tot


class _MethodFailure(ValueError):
    """고른 방법을 이 입력으로 계산할 수 없다 — 다른 방법으로 대신하지 않고 사유와 함께 실패한다."""


def _inverse_vol(vols: np.ndarray) -> np.ndarray:
    inv = 1.0 / vols
    return inv / inv.sum()


def _fb(method: str, reason: str) -> dict[str, Any]:
    return {"used": True, "from": method, "reason": reason}


def _crisis_rows(market_returns: list[float] | None, T: int) -> np.ndarray:
    """시장 대용의 가장 나빴던 `CRISIS_Q` 날 — 흐름과 **끝을 맞춘다**(합치기가 종목을 줄 세우는 방식과 같다)."""
    if market_returns is None:
        raise _MethodFailure("위기 때 위험 균형에는 시장 대용 흐름이 필요해요 — 시장을 정할 수 없어 계산하지 않았어요.")
    m = np.asarray(market_returns, dtype=float)
    if m.size < T:
        raise _MethodFailure(f"시장 대용 흐름({m.size}일)이 전략 흐름({T}일)보다 짧아 위기일을 맞출 수 없어요.")
    m = m[-T:]
    if not np.all(np.isfinite(m)) or float(np.var(m)) <= 0:
        raise _MethodFailure("시장 대용 흐름에 빈 값이 있거나 흔들림이 없어 위기일을 고를 수 없어요.")
    crisis = m <= np.quantile(m, CRISIS_Q)
    if int(crisis.sum()) < CRISIS_MIN_DAYS:
        raise _MethodFailure(f"위기일이 {int(crisis.sum())}일뿐이라(최소 {CRISIS_MIN_DAYS}일) 위기 때 공분산을 믿을 수 없어요 — "
                             "기간을 늘려 주세요.")
    return crisis


def _crisis_moment(Sc: np.ndarray) -> np.ndarray:
    """위기일 2차 적률 E[r rᵀ] — ★평균을 빼지 않는다★.

    공분산은 평균을 뺀다. 위기일에 늘 같이 크게 떨어지는 전략은 그 하락이 **평균**으로 빠져 공분산에 거의 남지 않는다
    (실측: 위기일마다 시장의 3배로 떨어지는 전략에 수축 공분산 위험 균형이 33.3% 를 줬다 — 평소 위험 균형은 20.3%).
    같이 잃은 크기 자체를 보려고 평균을 빼지 않은 적률을 쓴다. 대각에 아주 작은 값을 더해 풀이를 안정시킨다.
    """
    m = Sc.shape[0]
    return Sc.T @ Sc / m + np.eye(Sc.shape[1]) * 1e-12


def _max_diversification(cov: np.ndarray, vols: np.ndarray) -> np.ndarray:
    """분산 효과 Σwσ/σ_p 최대(롱온리·합 1). 못 풀면 실패 — 다른 방법으로 대신하지 않는다."""
    from src.engine.risk_allocations import _opt
    w = _opt(lambda w: -float(w @ vols) / float(np.sqrt(max(w @ cov @ w, 1e-18))), len(vols))
    if w is None:
        raise _MethodFailure("분산 효과 최대 계산이 풀리지 않았어요 — 다른 방법을 골라 주세요.")
    w = np.clip(np.asarray(w, dtype=float), 0.0, None)
    return w / w.sum()


def _allocate(method: str, S: np.ndarray, cov: np.ndarray, vols: np.ndarray, names: list[str], *,
              risk_budget: dict[str, float] | None = None, scores: dict[str, float] | None = None,
              shares: dict[str, float] | None = None,
              market_returns: list[float] | None = None) -> tuple[np.ndarray, dict[str, Any], dict[str, Any] | None]:
    """슬리브 몫 · 대체 여부 · 위기일 정보. ★기존 방법의 식·분기는 예전 그대로다★(골든) — 대체한 경우를 말할 뿐이다."""
    n = len(names)
    fallback: dict[str, Any] = dict(_NO_FALLBACK)
    crisis = None
    if method == "equal" or n == 1:
        alloc = np.ones(n) / n
    elif method == "inverse_vol":
        alloc = _inverse_vol(vols)
    elif method == "score" and scores:
        sc_ = np.array([max(scores.get(nm, 0.0), 0.0) for nm in names])
        if sc_.sum() > 0:
            alloc = sc_ / sc_.sum()
        else:
            alloc = np.ones(n) / n
            fallback = _fb(method, "점수가 모두 0 이라 똑같이 나눴어요.")
    elif method == "min_var":
        alloc = None
        try:
            from src.engine.risk_allocations import _opt
            alloc = _opt(lambda w: w @ cov @ w, n)
        except Exception:
            alloc = None
        if alloc is None:
            # 예전에는 `_opt` 가 None 을 내면(풀리지 않음) 다음 줄에서 터졌고, 예외일 때만 조용히 역변동성으로 갔다.
            alloc = _inverse_vol(vols)
            fallback = _fb(method, "흔들림 최소 계산이 풀리지 않아 역변동성(덜 흔들리는 쪽에 더)으로 계산했어요.")
    elif method == "hrp":
        try:
            from src.engine.risk_allocations import _hrp_weights
            alloc = _hrp_weights(cov)
        except Exception:
            alloc = _inverse_vol(vols)
            fallback = _fb(method, "계층 위험 균형 계산이 풀리지 않아 역변동성(덜 흔들리는 쪽에 더)으로 계산했어요.")
    elif method == "risk_budget" and risk_budget:
        b = np.array([max(risk_budget.get(nm, 1.0), 1e-6) for nm in names])
        alloc = _risk_budget_weights(cov, b)
    elif method == "manual":
        alloc = _manual_shares(shares, names)
    elif method == "crisis_risk_parity":
        rows = _crisis_rows(market_returns, S.shape[0])
        alloc = _risk_budget_weights(_crisis_moment(S[rows]), np.ones(n))
        crisis = {"days": int(rows.sum()), "q": CRISIS_Q, "n_days": int(S.shape[0])}
    elif method == "max_diversification":
        alloc = _max_diversification(cov, vols)
    else:  # risk_parity (등예산)
        alloc = _risk_budget_weights(cov, np.ones(n))
        if method != "risk_parity":
            why = {"score": "점수를 주지 않아", "risk_budget": "위험 예산을 주지 않아"}.get(method, f"모르는 방식({method})이라")
            fallback = _fb(method, f"{why} 위험 똑같이로 계산했어요.")
    return alloc, fallback, crisis


def _manual_shares(shares: dict[str, float] | None, names: list[str]) -> np.ndarray:
    if not shares:
        raise _MethodFailure("몫 직접 정하기에는 전략마다 몫(%)이 필요해요.")
    missing = [nm for nm in names if nm not in shares]
    if missing:
        raise _MethodFailure(f"몫을 정하지 않은 전략이 있어요: {', '.join(missing)}")
    v = np.array([float(shares[nm]) for nm in names])
    if not np.all(np.isfinite(v)) or (v < 0).any():
        raise _MethodFailure("몫에 음수나 빈 값이 있어요 — 0 이상으로 정해 주세요.")
    if abs(float(v.sum()) - 100.0) > MANUAL_SUM_TOL:
        raise _MethodFailure(f"몫의 합이 {float(v.sum()):g}% 예요 — 100% 가 되게 맞춰 주세요.")
    return v / 100.0


def combine_sleeves(sleeves: list[dict], method: str = "risk_parity",
                    risk_budget: dict[str, float] | None = None,
                    scores: dict[str, float] | None = None,
                    ret_matrix: dict[str, list[float]] | None = None,
                    rebalance_every: dict[str, int] | None = None,
                    rebalance_cost_bps: dict[str, float] | None = None,
                    shares: dict[str, float] | None = None,
                    market_returns: list[float] | None = None) -> dict[str, Any]:
    """슬리브 결합(2단계) — 슬리브 레벨 배분 + 종목 레벨 집계.

    BS4 — `shares`(몫 직접, %) · `market_returns`(위기 때 위험 균형의 시장 대용 일별 수익 — 끝을 맞춘다) 는 그 방법을
    고를 때만 쓰인다. `fallback` 은 엔진이 다른 방법으로 대신 계산했는지 말한다(값은 예전과 같다).

    `rebalance_every` — 슬리브별 되돌림 주기(거래일, `_sleeve_return_series`). 없으면 기존과 같고 응답 키도 같다.
    """
    if len(sleeves) < 1:
        return {"error": True, "message": "슬리브가 없습니다."}
    if ret_matrix is None:
        ret_matrix = _load_ret_matrix(sleeves)
    names, S = _sleeve_return_series(sleeves, ret_matrix, rebalance_every, rebalance_cost_bps)
    if S.size == 0 or S.shape[1] < 1:
        return {"error": True, "message": "슬리브 수익 시계열을 만들 수 없습니다 (시세 부족)."}

    n = len(sleeves)
    cov = _cov_local(S) if n >= 2 else np.array([[max(np.var(S[:, 0]), 1e-8)]])
    vols = np.sqrt(np.clip(np.diag(cov), 1e-12, None))
    try:
        alloc, fallback, crisis = _allocate(method, S, cov, vols, names, risk_budget=risk_budget, scores=scores,
                                            shares=shares, market_returns=market_returns)
    except _MethodFailure as e:
        return {"error": True, "message": str(e), "method": method}

    rc = _risk_contributions(alloc, cov)

    # 2단계: 종목 레벨 집계 (슬리브 배분 × 슬리브 내 종목비중)
    combined: dict[str, float] = {}
    # ★슬리브 안의 숏을 버리지 않는다★ 이 모듈에는 PairSpreadRequest(long/short)가
    # 있다 — 페어 트레이딩용으로 설계돼 있으면서 결합 단계에서 숏을 지우고 있었다.
    # 슬리브 내 상대비중도 집계도 gross 기준이다(net 은 페어 슬리브에서 0).
    for j, s in enumerate(sleeves):
        w = s.get("weights", {})
        wsum = sum(abs(float(v)) for v in w.values()) or 1.0
        for c, v in w.items():
            combined[c] = combined.get(c, 0.0) + alloc[j] * float(v) / wsum
    csum = sum(abs(v) for v in combined.values()) or 1.0
    combined = {c: round(v / csum * 100, 4) for c, v in combined.items()}

    out = {
        "error": False,
        "method": method,
        "sleeve_allocation": {names[j]: round(float(alloc[j]) * 100, 2) for j in range(n)},
        "risk_contribution_pct": {names[j]: round(float(rc[j]) * 100, 2) for j in range(n)},
        "sleeve_vol_pct": {names[j]: round(float(vols[j]) * np.sqrt(252) * 100, 2) for j in range(n)},
        "combined_weights_pct": combined,
        "n_sleeves": n, "n_stocks": len(combined),
        "note": "2단계 결합 — 슬리브 레벨 배분 × 슬리브 내 종목비중. 리스크 기여는 슬리브 공분산 기준.",
        "fallback": fallback,
    }
    if crisis is not None:
        out["crisis"] = crisis
    if rebalance_every is not None:
        # 쓴 주기를 그대로 돌려준다(주지 않은 슬리브는 1 = 매일). 주지 않았으면 키도 없다.
        out["rebalance_every"] = {nm: int(rebalance_every.get(nm, 1)) for nm in names}
    if rebalance_cost_bps is not None:
        out["rebalance_cost_bps"] = {nm: float(rebalance_cost_bps.get(nm, 0.0)) for nm in names}
    return out


def compare_sleeve_methods(sleeves: list[dict], ret_matrix: dict[str, list[float]] | None = None,
                           rebalance_every: dict[str, int] | None = None,
                           rebalance_cost_bps: dict[str, float] | None = None,
                           market_returns: list[float] | None = None) -> dict[str, Any]:
    """방법 비교표 (BS4, 관측) — 입력이 필요 없는 방법마다 **같은 흐름·같은 공분산**에서 몫·합친 흔들림·분산 효과·실질 개수.

    ★어느 방법이 낫다는 판정이 아니다★ 과거 흐름 위에서 각 방법이 무엇을 하는지 나란히 보일 뿐이다. 분산 효과는 몫을 정한
    공분산(수축) 기준이라 견고성 절(표본 표준편차)의 값과 조금 다를 수 있다.
    """
    if ret_matrix is None:
        ret_matrix = _load_ret_matrix(sleeves)
    names, S = _sleeve_return_series(sleeves, ret_matrix, rebalance_every, rebalance_cost_bps)
    if S.size == 0 or S.shape[1] < 2:
        return {"available": False, "rows": [], "reason": "전략 둘 이상의 흐름이 있어야 방법을 비교할 수 있어요."}
    cov = _cov_local(S)
    vols = np.sqrt(np.clip(np.diag(cov), 1e-12, None))
    rows = []
    for m in INPUT_FREE_METHODS:
        try:
            w, fb, _ = _allocate(m, S, cov, vols, names, market_returns=market_returns)
        except _MethodFailure as e:
            rows.append({"method": m, "available": False, "reason": str(e)})
            continue
        sp = float(np.sqrt(max(w @ cov @ w, 0.0)))
        rows.append({"method": m, "available": True,
                     "shares": {names[j]: round(float(w[j]) * 100, 2) for j in range(len(names))},
                     "vol_pct": round(sp * np.sqrt(252) * 100, 2),
                     "div_ratio": round(float(w @ vols) / sp, 3) if sp > 0 else None,
                     "effective_n": round(1.0 / float(np.sum(w ** 2)), 3),
                     "fallback": fb})
    return {"available": True, "rows": rows, "n_days": int(S.shape[0]),
            "note": "같은 과거 흐름 위에서 방법마다 몫을 나란히 본 거예요 — 어느 방법이 낫다는 뜻이 아니에요. "
                    "분산 효과는 몫을 정한 공분산 기준이에요."}


def sleeve_analytics(sleeves: list[dict], ret_matrix: dict[str, list[float]] | None = None,
                     weights: dict[str, float] | None = None,
                     rebalance_every: dict[str, int] | None = None,
                     rebalance_cost_bps: dict[str, float] | None = None) -> dict[str, Any]:
    """슬리브 간 상관·군집·리스크 기여·꼬리의존 (§8 검증). 주기·비용은 `combine_sleeves` 와 같은 흐름을 쓰려고 받는다."""
    if ret_matrix is None:
        ret_matrix = _load_ret_matrix(sleeves)
    names, S = _sleeve_return_series(sleeves, ret_matrix, rebalance_every, rebalance_cost_bps)
    n = len(names)
    if S.size == 0 or n < 2:
        return {"error": True, "message": "분석에 슬리브 2개 이상·시세가 필요합니다."}

    # BR R1a — 흔들림 없는 슬리브(비중이 비었거나 숏만 있어 흐름이 0)의 상관은 **모름**이다. 예전에는
    # `nan_to_num(…, 0)` 으로 "서로 무관(0)" 이라고 보고했다 — 조용한 폴백. 잰 쌍만 쓰고 나머지는 None + 사유.
    flat = [j for j in range(n) if float(np.var(S[:, j])) <= 1e-16]
    ok = [j for j in range(n) if j not in flat]
    with np.errstate(invalid="ignore", divide="ignore"):
        corr = np.corrcoef(S.T)
    corr[flat, :] = np.nan
    corr[:, flat] = np.nan
    for j in ok:
        corr[j, j] = 1.0
    for j in flat:
        corr[j, j] = 1.0

    # 계층 군집 (scipy linkage; 없으면 상관 임계 그룹핑) — 잰 슬리브끼리만. 흔들림 없는 슬리브는 군집 모름.
    clusters: list[int | None] = [None] * n
    if len(ok) >= 2:
        for j, lab in zip(ok, _cluster_labels(corr[np.ix_(ok, ok)])):
            clusters[j] = lab
    elif len(ok) == 1:
        clusters[ok[0]] = 0
    # 꼬리 의존: 하위 10% 동시초과 빈도 / 0.1 (>1이면 꼬리 동반 하락 경향)
    tail = _tail_dependency(S)
    # 리스크 기여 (weights 주어지면 그 배분, 아니면 등가중)
    # 슬리브 배분도 같은 규칙 — 사용자가 준 값이므로 부호가 미지수다.
    w = (np.array([float(weights.get(names[j], 0.0)) for j in range(n)])
         if weights else np.ones(n) / n)
    if np.abs(w).sum() > 0:
        w = w / np.abs(w).sum()
    cov = _cov_local(S)
    rc = _risk_contributions(w, cov)

    measured = [float(corr[i, j]) for i in range(n) for j in range(i + 1, n) if np.isfinite(corr[i, j])]
    known = [c for c in clusters if c is not None]
    out = {
        "error": False,
        "sleeves": names,
        "correlation": {names[i]: {names[j]: (round(float(corr[i, j]), 3) if np.isfinite(corr[i, j]) else None)
                                   for j in range(n)} for i in range(n)},
        "clusters": {names[j]: (int(clusters[j]) if clusters[j] is not None else None) for j in range(n)},
        "n_clusters": int(max(known) + 1) if known and len(ok) >= 2 else None,
        "risk_contribution_pct": {names[j]: round(float(rc[j]) * 100, 2) for j in range(n)},
        "tail_dependency": tail,
        "avg_correlation": round(float(np.mean(measured)), 3) if measured else None,
        "note": "상관·계층군집·리스크 기여·하위꼬리 동반(10% 동시초과). 상관·꼬리의존이 높은 "
                "슬리브는 분산효과가 작아 함께 무너지기 쉬움 — 중복 알파 점검.",
    }
    if flat:
        out["correlation_reasons"] = {names[j]: "흔들림이 없어 상관을 잴 수 없어요(비중이 비었거나 숏만 있어 흐름이 0 이에요)"
                                      for j in flat}
    return out


def _cluster_labels(corr: np.ndarray, threshold: float = 0.5) -> list[int]:
    """상관 → 거리 → 계층군집 flat 라벨. scipy 없으면 상관 임계 union-find."""
    n = corr.shape[0]
    try:
        from scipy.cluster.hierarchy import fcluster, linkage
        from scipy.spatial.distance import squareform
        dist = np.sqrt(np.clip(0.5 * (1 - corr), 0, None))
        np.fill_diagonal(dist, 0.0)
        link = linkage(squareform(dist, checks=False), method="average")
        labels = fcluster(link, t=1 - threshold, criterion="distance")
        return [int(x - 1) for x in labels]
    except Exception:
        parent = list(range(n))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        for i in range(n):
            for j in range(i + 1, n):
                if corr[i, j] >= threshold:
                    parent[find(i)] = find(j)
        roots = {}
        return [roots.setdefault(find(i), len(roots)) for i in range(n)]


def _tail_dependency(S: np.ndarray, q: float = 0.1) -> dict[str, Any]:
    """하위 꼬리 동반 — 각 슬리브 하위 q분위 동시 발생 빈도(평균 pairwise / q)."""
    T, n = S.shape
    if T < 10 or n < 2:
        return {"lower_tail_coexceedance": None, "basis": "unavailable"}
    thr = np.quantile(S, q, axis=0)
    below = S <= thr                                   # T×n bool
    pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            both = float(np.mean(below[:, i] & below[:, j]))
            pairs.append(both / q if q > 0 else 0.0)   # 1=독립, >1=꼬리 동반
    return {"lower_tail_coexceedance": round(float(np.mean(pairs)), 2),
            "interpretation": "1=독립 · >1=하위꼬리 동반하락 경향(분산효과 약화)",
            "basis": "real"}


def _load_ret_matrix(sleeves: list[dict], market: str = "kr", lookback: int = 252) -> dict[str, list[float]]:
    """종목 union의 일별수익 — ohlcv 로더(DB→KIS→mock). risk_allocations 관례 재사용."""
    codes = sorted({c for s in sleeves for c in s.get("weights", {})})
    out: dict[str, list[float]] = {}
    try:
        from src.engine.risk_allocations import _daily_returns_matrix
        names, R = _daily_returns_matrix(codes, market, lookback=lookback)
        if R is not None and len(names):
            for i, c in enumerate(names):
                out[c] = list(R[:, i])
    except Exception:
        logger.debug("일별수익 행렬 로드 실패", exc_info=True)
    return out
