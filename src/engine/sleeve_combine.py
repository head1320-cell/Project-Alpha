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

SLEEVE_METHODS = ("equal", "inverse_vol", "risk_parity", "risk_budget", "min_var", "hrp", "score")


def _sleeve_return_series(sleeves: list[dict], ret_matrix: dict[str, list[float]]) -> tuple[list[str], np.ndarray]:
    """슬리브별 일별수익 행렬 (T×S). ret_matrix: code -> 일별수익 리스트(정렬 동일 길이)."""
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
        S[:, j] = R @ w
    return names, S


def _cov_local(S: np.ndarray) -> np.ndarray:
    try:
        from src.engine.risk_allocations import _cov
        return _cov(S)
    except Exception:
        c = np.cov(S.T)
        return np.atleast_2d(c) + np.eye(S.shape[1]) * 1e-8


def _risk_budget_weights(cov: np.ndarray, budget: np.ndarray, iters: int = 200) -> np.ndarray:
    """리스크 예산 배분 — RC_i ∝ budget_i (등예산이면 리스크 패리티). 순환 반복."""
    b = budget / budget.sum()
    w = b.copy()
    for _ in range(iters):
        sigma = float(np.sqrt(w @ cov @ w))
        if sigma <= 0:
            break
        mrc = cov @ w / sigma
        rc = w * mrc
        rc_sum = rc.sum() or 1.0
        # 목표 예산 대비 기여 비율로 조정
        w = w * (b / (rc / rc_sum + 1e-12))
        w = np.clip(w, 0, None)
        w = w / w.sum()
    return w


def _risk_contributions(w: np.ndarray, cov: np.ndarray) -> np.ndarray:
    sigma = float(np.sqrt(w @ cov @ w))
    if sigma <= 0:
        return np.zeros_like(w)
    rc = w * (cov @ w) / sigma
    tot = rc.sum() or 1.0
    return rc / tot


def combine_sleeves(sleeves: list[dict], method: str = "risk_parity",
                    risk_budget: dict[str, float] | None = None,
                    scores: dict[str, float] | None = None,
                    ret_matrix: dict[str, list[float]] | None = None) -> dict[str, Any]:
    """슬리브 결합(2단계) — 슬리브 레벨 배분 + 종목 레벨 집계."""
    if len(sleeves) < 1:
        return {"error": True, "message": "슬리브가 없습니다."}
    if ret_matrix is None:
        ret_matrix = _load_ret_matrix(sleeves)
    names, S = _sleeve_return_series(sleeves, ret_matrix)
    if S.size == 0 or S.shape[1] < 1:
        return {"error": True, "message": "슬리브 수익 시계열을 만들 수 없습니다 (시세 부족)."}

    n = len(sleeves)
    cov = _cov_local(S) if n >= 2 else np.array([[max(np.var(S[:, 0]), 1e-8)]])
    vols = np.sqrt(np.clip(np.diag(cov), 1e-12, None))

    if method == "equal" or n == 1:
        alloc = np.ones(n) / n
    elif method == "inverse_vol":
        inv = 1.0 / vols
        alloc = inv / inv.sum()
    elif method == "score" and scores:
        sc = np.array([max(scores.get(s["name"], 0.0), 0.0) for s in sleeves])
        alloc = sc / sc.sum() if sc.sum() > 0 else np.ones(n) / n
    elif method == "min_var":
        try:
            from src.engine.risk_allocations import _opt
            alloc = _opt(lambda w: w @ cov @ w, n)
        except Exception:
            inv = 1.0 / vols
            alloc = inv / inv.sum()
    elif method == "hrp":
        try:
            from src.engine.risk_allocations import _hrp_weights
            alloc = _hrp_weights(cov)
        except Exception:
            inv = 1.0 / vols
            alloc = inv / inv.sum()
    elif method == "risk_budget" and risk_budget:
        b = np.array([max(risk_budget.get(s["name"], 1.0), 1e-6) for s in sleeves])
        alloc = _risk_budget_weights(cov, b)
    else:  # risk_parity (등예산)
        alloc = _risk_budget_weights(cov, np.ones(n))

    rc = _risk_contributions(alloc, cov)

    # 2단계: 종목 레벨 집계 (슬리브 배분 × 슬리브 내 종목비중)
    combined: dict[str, float] = {}
    for j, s in enumerate(sleeves):
        w = s.get("weights", {})
        wsum = sum(max(v, 0.0) for v in w.values()) or 1.0
        for c, v in w.items():
            combined[c] = combined.get(c, 0.0) + alloc[j] * max(v, 0.0) / wsum
    csum = sum(combined.values()) or 1.0
    combined = {c: round(v / csum * 100, 4) for c, v in combined.items()}

    return {
        "error": False,
        "method": method,
        "sleeve_allocation": {names[j]: round(float(alloc[j]) * 100, 2) for j in range(n)},
        "risk_contribution_pct": {names[j]: round(float(rc[j]) * 100, 2) for j in range(n)},
        "sleeve_vol_pct": {names[j]: round(float(vols[j]) * np.sqrt(252) * 100, 2) for j in range(n)},
        "combined_weights_pct": combined,
        "n_sleeves": n, "n_stocks": len(combined),
        "note": "2단계 결합 — 슬리브 레벨 배분 × 슬리브 내 종목비중. 리스크 기여는 슬리브 공분산 기준.",
    }


def sleeve_analytics(sleeves: list[dict], ret_matrix: dict[str, list[float]] | None = None,
                     weights: dict[str, float] | None = None) -> dict[str, Any]:
    """슬리브 간 상관·군집·리스크 기여·꼬리의존 (§8 검증)."""
    if ret_matrix is None:
        ret_matrix = _load_ret_matrix(sleeves)
    names, S = _sleeve_return_series(sleeves, ret_matrix)
    n = len(names)
    if S.size == 0 or n < 2:
        return {"error": True, "message": "분석에 슬리브 2개 이상·시세가 필요합니다."}

    corr = np.corrcoef(S.T)
    corr = np.nan_to_num(corr, nan=0.0)

    # 계층 군집 (scipy linkage; 없으면 상관 임계 그룹핑)
    clusters = _cluster_labels(corr)
    # 꼬리 의존: 하위 10% 동시초과 빈도 / 0.1 (>1이면 꼬리 동반 하락 경향)
    tail = _tail_dependency(S)
    # 리스크 기여 (weights 주어지면 그 배분, 아니면 등가중)
    w = np.array([max(weights.get(names[j], 0.0), 0.0) for j in range(n)]) if weights else np.ones(n) / n
    if w.sum() > 0:
        w = w / w.sum()
    cov = _cov_local(S)
    rc = _risk_contributions(w, cov)

    return {
        "error": False,
        "sleeves": names,
        "correlation": {names[i]: {names[j]: round(float(corr[i, j]), 3) for j in range(n)} for i in range(n)},
        "clusters": {names[j]: int(clusters[j]) for j in range(n)},
        "n_clusters": int(max(clusters) + 1) if len(clusters) else 0,
        "risk_contribution_pct": {names[j]: round(float(rc[j]) * 100, 2) for j in range(n)},
        "tail_dependency": tail,
        "avg_correlation": round(float((corr.sum() - n) / (n * (n - 1))), 3) if n > 1 else 0.0,
        "note": "상관·계층군집·리스크 기여·하위꼬리 동반(10% 동시초과). 상관·꼬리의존이 높은 "
                "슬리브는 분산효과가 작아 함께 무너지기 쉬움 — 중복 알파 점검.",
    }


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
