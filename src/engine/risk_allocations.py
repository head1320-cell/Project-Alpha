"""리스크·최적화 기반 자산배분 9전략 — 현재 시점 보유자산·비중 (공분산 구동)
==========================================================================
기존 tactical_allocations(모멘텀)와 분리된 "리스크/최적화" 라이브러리.
공통 크로스에셋 8자산의 트레일링 시세 → 공분산/기대수익 → 시점 가중치 벡터.
전부 long-only·합100, market="us"|"kr"(시세 경로). 데이터 부족·라이브러리 부재 시 inverse-vol 폴백.

전략:
  · equal_weight   1/N 동일가중 (DeMiguel 2009 벤치마크)
  · risk_parity    동일 리스크 기여 ERC (Bridgewater All Weather)
  · hrp            계층적 리스크 패리티 (López de Prado 2016)
  · min_var        최소분산 (Markowitz 코너)
  · max_div        최대분산 (Choueifaty/TOBAM)
  · max_sharpe     탄젠시 (Ledoit-Wolf 수축)
  · black_litterman 시장균형 + 국면 뷰 (Goldman; regime_analyzer 연동)
  · managed_futures 시계열 모멘텀 추세추종 (AQR/CTA, long-flat)
  · kelly          성장최적 Σ⁻¹μ (long-only)

공분산은 일간 수익률(~252)로 추정(월간은 ~20개월뿐이라 부족) → 견고. 기대수익은 트레일링 평균.
"""

from __future__ import annotations

import logging

import numpy as np

from src.data.etf_prices import daily_closes, monthly_closes

logger = logging.getLogger(__name__)

# 공통 유니버스 (주식 3·채권 2·금·원자재·리츠)
_UNIVERSE = ["SPY", "EFA", "EEM", "TLT", "IEF", "GLD", "PDBC", "VNQ"]
_COV_LOOKBACK = 252  # 일간 수익률 룩백 (~1년)

# 선택 라이브러리 가드 (없으면 폴백)
try:
    from scipy.optimize import minimize as _scipy_min  # noqa: F401
    _HAS_OPT = True
except Exception:  # pragma: no cover
    _HAS_OPT = False
try:
    from scipy.cluster.hierarchy import linkage as _linkage  # noqa: F401
    from scipy.spatial.distance import squareform as _squareform  # noqa: F401
    _HAS_HCLUST = True
except Exception:  # pragma: no cover
    _HAS_HCLUST = False
try:
    from sklearn.covariance import LedoitWolf as _LedoitWolf  # noqa: F401
    _HAS_LW = True
except Exception:  # pragma: no cover
    _HAS_LW = False


# ── 데이터/수치 헬퍼 ──────────────────────────────────────────────────────────
def _ret(closes: list[float], months: int) -> float | None:
    if len(closes) < months + 1 or closes[-1 - months] <= 0:
        return None
    return closes[-1] / closes[-1 - months] - 1.0


def _daily_returns_matrix(tickers: list[str], mk: str, lookback: int = _COV_LOOKBACK):
    """정렬된 일간 수익률 행렬 [obs, assets]. 히스토리 부족 자산 제외, 공통 최소길이 절단."""
    series: dict[str, list[float]] = {}
    for t in tickers:
        c = daily_closes(t, mk, lookback + 12)
        if len(c) >= 30:
            series[t] = c
    if len(series) < 2:
        return [], None
    names = list(series.keys())
    L = min(len(series[t]) for t in names)
    L = min(L, lookback + 1)
    cols = []
    for t in names:
        c = series[t][-L:]
        arr = np.asarray(c, dtype=float)
        cols.append(arr[1:] / arr[:-1] - 1.0)
    R = np.vstack(cols).T  # [obs, assets]
    return names, R


def _cov(R: np.ndarray) -> np.ndarray:
    """Ledoit-Wolf 수축 공분산 (없으면 샘플 + ridge)."""
    if _HAS_LW:
        try:
            return _LedoitWolf().fit(R).covariance_
        except Exception:  # pragma: no cover
            pass
    S = np.cov(R, rowvar=False)
    return S + np.eye(S.shape[0]) * 1e-6


def _pct(weights, names: list[str]) -> dict:
    """가중치 벡터 → {ticker: %} (long-only, 합 정확히 100, <0.05% 절사)."""
    w = np.maximum(np.asarray(weights, dtype=float), 0.0)
    s = w.sum()
    if not np.isfinite(s) or s <= 0:
        return {"BIL": 100.0}
    w = w / s * 100.0
    out = {names[i]: round(float(w[i]), 1) for i in range(len(names)) if w[i] > 0.05}
    if not out:
        return {"BIL": 100.0}
    resid = round(100.0 - sum(out.values()), 1)
    if abs(resid) >= 0.1:
        k = max(out, key=lambda x: out[x])
        out[k] = round(out[k] + resid, 1)
    return out


def _inverse_vol(names: list[str], R: np.ndarray) -> dict:
    vol = R.std(axis=0)
    vol = np.where(vol > 1e-9, vol, 1e-9)
    return _pct(1.0 / vol, names)


def _opt(objective, n: int):
    """long-only(합1) SLSQP 최적화. 실패/부재 시 None."""
    if not _HAS_OPT:
        return None
    x0 = np.ones(n) / n
    cons = ({"type": "eq", "fun": lambda w: w.sum() - 1.0},)
    bnds = [(0.0, 1.0)] * n
    try:
        res = _scipy_min(objective, x0, method="SLSQP", bounds=bnds, constraints=cons,
                         options={"maxiter": 200, "ftol": 1e-9})
        return res.x if res.success else None
    except Exception:  # pragma: no cover
        return None


# ── HRP (López de Prado) ──────────────────────────────────────────────────────
def _cov_to_corr(cov: np.ndarray) -> np.ndarray:
    d = np.sqrt(np.diag(cov))
    d = np.where(d > 1e-12, d, 1e-12)
    return np.clip(cov / np.outer(d, d), -1.0, 1.0)


def _cluster_var(cov: np.ndarray, idx: list[int]) -> float:
    sub = cov[np.ix_(idx, idx)]
    ivp = 1.0 / np.diag(sub)
    ivp = ivp / ivp.sum()
    return float(ivp @ sub @ ivp)


def _quasi_diag(link: np.ndarray, n: int) -> list[int]:
    link = link.astype(int)
    sort_ix = [int(link[-1, 0]), int(link[-1, 1])]
    while max(sort_ix) >= n:
        nxt = []
        for i in sort_ix:
            if i < n:
                nxt.append(i)
            else:
                row = link[i - n]
                nxt.append(int(row[0]))
                nxt.append(int(row[1]))
        sort_ix = nxt
    return sort_ix


def _hrp_weights(cov: np.ndarray) -> np.ndarray:
    corr = _cov_to_corr(cov)
    dist = np.sqrt(np.clip((1.0 - corr) / 2.0, 0.0, None))
    link = _linkage(_squareform(dist, checks=False), method="single")
    order = _quasi_diag(link, cov.shape[0])
    w_ord = np.ones(len(order))
    clusters = [list(range(len(order)))]
    while clusters:
        nxt = []
        for cl in clusters:
            if len(cl) <= 1:
                continue
            half = len(cl) // 2
            c1, c2 = cl[:half], cl[half:]
            v1 = _cluster_var(cov, [order[i] for i in c1])
            v2 = _cluster_var(cov, [order[i] for i in c2])
            alpha = 1.0 - v1 / (v1 + v2)
            for i in c1:
                w_ord[i] *= alpha
            for i in c2:
                w_ord[i] *= (1.0 - alpha)
            nxt.append(c1)
            nxt.append(c2)
        clusters = nxt
    w = np.zeros(len(order))
    for pos, asset_idx in enumerate(order):
        w[asset_idx] = w_ord[pos]
    return w


# ── 9 전략 ────────────────────────────────────────────────────────────────────
def s_equal_weight(mk: str) -> dict:
    names, R = _daily_returns_matrix(_UNIVERSE, mk)
    if not names:
        return _pct(np.ones(len(_UNIVERSE)), _UNIVERSE)
    return _pct(np.ones(len(names)), names)


def s_risk_parity(mk: str) -> dict:
    names, R = _daily_returns_matrix(_UNIVERSE, mk)
    if not names:
        return {"BIL": 100.0}
    S = _cov(R)
    n = len(names)
    w = 1.0 / np.sqrt(np.diag(S))
    w = w / w.sum()
    for _ in range(200):  # ERC 반복 (risk-budgeting)
        mrc = S @ w
        rc = w * mrc
        target = (w @ S @ w) / n
        w = w * np.sqrt(target / (rc + 1e-12))
        w = np.maximum(w, 0.0)
        tot = w.sum()
        if tot <= 0:
            break
        w = w / tot
    return _pct(w, names)


def s_hrp(mk: str) -> dict:
    names, R = _daily_returns_matrix(_UNIVERSE, mk)
    if not names:
        return {"BIL": 100.0}
    S = _cov(R)
    if not _HAS_HCLUST:
        return _inverse_vol(names, R)
    try:
        return _pct(_hrp_weights(S), names)
    except Exception:  # pragma: no cover
        return _inverse_vol(names, R)


def s_min_var(mk: str) -> dict:
    names, R = _daily_returns_matrix(_UNIVERSE, mk)
    if not names:
        return {"BIL": 100.0}
    S = _cov(R)
    w = _opt(lambda x: float(x @ S @ x), len(names))
    return _pct(w, names) if w is not None else _inverse_vol(names, R)


def s_max_div(mk: str) -> dict:
    names, R = _daily_returns_matrix(_UNIVERSE, mk)
    if not names:
        return {"BIL": 100.0}
    S = _cov(R)
    sig = np.sqrt(np.diag(S))

    def neg_dr(x):
        pv = np.sqrt(x @ S @ x)
        return -(x @ sig) / (pv + 1e-12)

    w = _opt(neg_dr, len(names))
    return _pct(w, names) if w is not None else _inverse_vol(names, R)


def s_max_sharpe(mk: str) -> dict:
    names, R = _daily_returns_matrix(_UNIVERSE, mk)
    if not names:
        return {"BIL": 100.0}
    S = _cov(R)
    mu = R.mean(axis=0)

    def neg_sharpe(x):
        pv = np.sqrt(x @ S @ x)
        return -(x @ mu) / (pv + 1e-12)

    w = _opt(neg_sharpe, len(names))
    return _pct(w, names) if w is not None else _inverse_vol(names, R)


# 블랙-리터만: 시장 프록시 prior + 국면 틸트 뷰
_MKT_PRIOR = {"SPY": 0.40, "EFA": 0.13, "EEM": 0.07, "TLT": 0.12,
              "IEF": 0.08, "GLD": 0.06, "PDBC": 0.06, "VNQ": 0.08}
_TILT_TO_ASSETS = {
    "growth_stocks": ["SPY", "EEM"], "value_stocks": ["EFA", "VNQ"],
    "bonds": ["TLT", "IEF"], "commodities": ["PDBC", "GLD"],
}
_TILT_Q = {"++": 0.03, "+": 0.015, "0": 0.0, "-": -0.015, "--": -0.03}


def _regime_tilts():
    """regime_analyzer의 asset_tilts (없으면 None — prior 폴백)."""
    try:
        from src.engine.regime_analyzer import RegimeAnalyzer
        return RegimeAnalyzer().analyze().asset_tilts
    except Exception:
        return None


def s_black_litterman(mk: str) -> dict:
    names, R = _daily_returns_matrix(_UNIVERSE, mk)
    if not names:
        return {"BIL": 100.0}
    S = _cov(R) * 252.0  # 연율화 공분산 (뷰가 연율 수익 단위)
    n = len(names)
    idx = {t: i for i, t in enumerate(names)}
    w_mkt = np.array([_MKT_PRIOR.get(t, 0.0) for t in names])
    if w_mkt.sum() <= 0:
        w_mkt = np.ones(n)
    w_mkt = w_mkt / w_mkt.sum()
    delta = 2.5
    pi = delta * S @ w_mkt  # 균형 기대수익

    tilts = _regime_tilts()
    if not tilts:
        return _pct(w_mkt, names)
    rows, q = [], []
    for cat, sym in tilts.items():
        view = _TILT_Q.get(str(sym), 0.0)
        if view == 0.0 or cat not in _TILT_TO_ASSETS:
            continue
        assets = [a for a in _TILT_TO_ASSETS[cat] if a in idx]
        if not assets:
            continue
        row = np.zeros(n)
        for a in assets:
            row[idx[a]] = 1.0 / len(assets)
        rows.append(row)
        q.append(view)
    if not rows:
        return _pct(w_mkt, names)

    P = np.array(rows)
    Q = np.array(q)
    tau = 0.05
    try:
        tauS = tau * S
        omega = np.diag(np.diag(P @ tauS @ P.T)) + np.eye(len(Q)) * 1e-8
        inv_tauS = np.linalg.inv(tauS)
        inv_om = np.linalg.inv(omega)
        mu_bl = np.linalg.solve(inv_tauS + P.T @ inv_om @ P,
                                inv_tauS @ pi + P.T @ inv_om @ Q)
    except Exception:  # pragma: no cover
        return _pct(w_mkt, names)

    def neg_sharpe(x):
        pv = np.sqrt(x @ S @ x)
        return -(x @ mu_bl) / (pv + 1e-12)

    w = _opt(neg_sharpe, n)
    return _pct(w, names) if w is not None else _pct(w_mkt, names)


def _mf_return(t: str, mk: str) -> float | None:
    """매니지드 퓨처스 추세 신호용 12개월 수익률 (monkeypatch 지점)."""
    return _ret(monthly_closes(t, mk, 14), 12)


def s_managed_futures(mk: str) -> dict:
    """TSMOM long-flat: 자산별 12M 추세>0 시 역변동성 long, 전부 음수면 현금."""
    on: dict[str, float] = {}
    for t in _UNIVERSE:
        r = _mf_return(t, mk)
        if r is not None and r > 0:
            c = daily_closes(t, mk, 130)
            if len(c) >= 30:
                arr = np.asarray(c, dtype=float)
                vol = float(np.std(arr[1:] / arr[:-1] - 1.0)) or 1e-6
            else:
                vol = 1.0
            on[t] = 1.0 / max(vol, 1e-6)
    if not on:
        return {"BIL": 100.0}
    names = list(on.keys())
    return _pct(np.array([on[t] for t in names]), names)


def s_kelly(mk: str) -> dict:
    """성장최적: w ∝ Σ⁻¹μ, long-only 클립 (완전투자형에서 풀/하프켈리는 정규화로 동치)."""
    names, R = _daily_returns_matrix(_UNIVERSE, mk)
    if not names:
        return {"BIL": 100.0}
    S = _cov(R)
    mu = R.mean(axis=0)
    try:
        f = np.linalg.solve(S, mu)
    except Exception:  # pragma: no cover
        return _inverse_vol(names, R)
    f = np.maximum(f, 0.0)
    if f.sum() <= 0:
        return {"BIL": 100.0}
    return _pct(f, names)


RISK_STRATEGIES: list[tuple] = [
    ("equal_weight", "동일가중 1/N", "8자산 균등 — 최적화 비교 벤치마크", "benchmark", s_equal_weight),
    ("risk_parity", "리스크 패리티", "각 자산 동일 리스크 기여 (Bridgewater All Weather)", "risk", s_risk_parity),
    ("hrp", "계층적 리스크 패리티", "상관 클러스터링 + 재귀이분 (López de Prado)", "risk", s_hrp),
    ("min_var", "최소분산", "포트폴리오 분산 최소화 (저변동성)", "risk", s_min_var),
    ("max_div", "최대분산", "분산비율 최대화 (Choueifaty/TOBAM)", "risk", s_max_div),
    ("max_sharpe", "최대 샤프", "탄젠시 포트폴리오 (Ledoit-Wolf 수축)", "optim", s_max_sharpe),
    ("black_litterman", "블랙-리터만", "시장균형 + 국면 뷰 결합 (Goldman)", "optim", s_black_litterman),
    ("managed_futures", "매니지드 퓨처스", "시계열 모멘텀 추세추종 (AQR/CTA, long-flat)", "trend", s_managed_futures),
    ("kelly", "켈리 성장최적", "Σ⁻¹μ 성장최적 비중 (long-only)", "sizing", s_kelly),
]
