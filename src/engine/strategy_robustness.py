"""전략끼리 견고성 — 관측만 (BR R1).

입력 `S` 는 전략(또는 비교할 비중 묶음)마다 일별 수익을 담은 T×n 행렬이다. 흐름은 `sleeve_combine._sleeve_return_series`
가 만든 것 — **지금 비중을 지난 기간 내내 들고 있었다면**의 흐름이지 실제 운용 기록이 아니다(부르는 쪽이 밝힌다).
로더에 날짜가 없어 가로축은 "n거래일 전"(`ago`, 0 = 가장 최근)이다 — 날짜를 지어내지 않는다.

★모르면 0 이 아니다★ 흔들림이 없어 상관을 잴 수 없는 자리는 `None` + 사유. 이 모듈은 배분을 바꾸지 않는다
(질문 ② 전달 안정성에 대한 관측 — 예측력·경제적 가치의 증거가 아니다).

스펙: docs/superpowers/specs/2026-09-28-br-robustness-profile-design.md
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import numpy as np

#: 분산이 이보다 작으면 "흔들림이 없다"고 본다(일별 수익 기준 — 0.001% 변동보다 작음).
_FLAT_VAR = 1e-16
_FLAT_REASON = "이 구간에 흔들림이 없어 상관을 잴 수 없어요(비중이 비었거나 값이 그대로예요)"
#: 위기일이 이보다 적으면 표본이 작다고 적는다.
SMALL_CRISIS_DAYS = 20


def _r(x: float | None, nd: int = 3) -> float | None:
    return None if x is None or not math.isfinite(x) else round(float(x), nd)


def _pairs(n: int) -> list[tuple[int, int]]:
    return [(i, j) for i in range(n) for j in range(i + 1, n)]


def _corr(x: np.ndarray, y: np.ndarray) -> float | None:
    if x.size < 3 or np.var(x) <= _FLAT_VAR or np.var(y) <= _FLAT_VAR:
        return None
    c = float(np.corrcoef(x, y)[0, 1])
    return c if math.isfinite(c) else None


def _fisher_band(rho: float, n: int, z: float = 1.96) -> tuple[float, float]:
    r = min(max(rho, -0.999999), 0.999999)
    se = 1.0 / math.sqrt(max(n - 3, 1))
    f = math.atanh(r)
    return math.tanh(f - z * se), math.tanh(f + z * se)


# ── 상관 추이 ────────────────────────────────────────────────────────────────

def rolling_correlation(names: Sequence[str], S: np.ndarray, window: int = 60) -> dict[str, Any]:
    """쌍마다 창 `window` 거래일의 상관 흐름 + Fisher z 95% 띠 + 평균 쌍."""
    T, n = S.shape
    if T < window + 10:
        return {"available": False, "window": window,
                "reason": f"흐름이 {T}거래일이라 {window}일 창으로 추이를 볼 수 없어요(적어도 {window + 10}일)"}
    m = T - window + 1
    c = np.vstack([np.zeros((1, n)), np.cumsum(S, axis=0)])
    c2 = np.vstack([np.zeros((1, n)), np.cumsum(S * S, axis=0)])
    mean = (c[window:] - c[:-window]) / window                       # m×n
    var = (c2[window:] - c2[:-window]) / window - mean ** 2
    pairs = []
    per_t: list[list[float]] = [[] for _ in range(m)]
    for i, j in _pairs(n):
        cxy = np.concatenate([[0.0], np.cumsum(S[:, i] * S[:, j])])
        cov = (cxy[window:] - cxy[:-window]) / window - mean[:, i] * mean[:, j]
        vals: list[float | None] = []
        lo: list[float | None] = []
        hi: list[float | None] = []
        for t in range(m):
            if var[t, i] <= _FLAT_VAR or var[t, j] <= _FLAT_VAR:
                vals.append(None); lo.append(None); hi.append(None)
                continue
            rho = float(np.clip(cov[t] / math.sqrt(var[t, i] * var[t, j]), -1.0, 1.0))
            a, b = _fisher_band(rho, window)
            vals.append(round(rho, 3)); lo.append(round(a, 3)); hi.append(round(b, 3))
            per_t[t].append(rho)
        got = [v for v in vals if v is not None]
        pairs.append({"a": names[i], "b": names[j], "values": vals, "lo": lo, "hi": hi,
                      "current": vals[-1], "min": min(got) if got else None, "max": max(got) if got else None,
                      "mean": _r(float(np.mean(got))) if got else None,
                      "n_empty": sum(v is None for v in vals)})
    avg = [round(float(np.mean(v)), 3) if v else None for v in per_t]
    got_avg = [v for v in avg if v is not None]
    return {"available": True, "window": window, "ago": [m - 1 - t for t in range(m)], "pairs": pairs,
            "avg": avg, "avg_current": avg[-1], "avg_max": max(got_avg) if got_avg else None,
            "avg_min": min(got_avg) if got_avg else None,
            "note": f"{window}거래일 창의 상관 · 띠는 표본 오차 95%(Fisher z) — 띠가 넓으면 창 안의 날이 적어 흔들린 값이에요."}


# ── 위기 때 상관 ─────────────────────────────────────────────────────────────

def _normal_scores(x: np.ndarray) -> np.ndarray:
    from scipy.stats import norm, rankdata
    return norm.ppf((rankdata(x) - 0.5) / x.size)


def crisis_correlation(names: Sequence[str], S: np.ndarray, market: np.ndarray | None = None,
                       q: float = 0.1) -> dict[str, Any]:
    """위기일(시장 하위 q) 상관 대 평소 상관 · 같이 떨어진 날 대 평소 관계라면 기대되는 날.

    나쁜 날만 골라 상관을 재면 관계가 그대로여도 상관이 높아 보인다(조건부 상관 치우침). 그래서 순위 기반 '같이
    떨어진 날'을 같은 전체 상관의 정규 관계가 주는 기대와 나란히 둔다 — 이쪽이 치우침 없는 비교다.
    """
    from scipy.stats import multivariate_normal, norm

    T, n = S.shape
    note = None
    if market is not None and np.asarray(market).shape == (T,) and np.var(market) > _FLAT_VAR:
        ref, basis = np.asarray(market, dtype=float), "market"
    else:
        ref, basis = S.mean(axis=1), "strategy_mean"
        note = ("시장 자료가 없어 전략 평균이 가장 나빴던 날을 위기일로 골랐어요 — 전략 스스로 고른 날이라 "
                "위기일 상관이 부풀 수 있어요.")
    crisis = ref <= np.quantile(ref, q)
    m = int(crisis.sum())
    zq = float(norm.ppf(q))
    thr = np.quantile(S, q, axis=0)
    below = S <= thr
    pairs = []
    for i, j in _pairs(n):
        row: dict[str, Any] = {"a": names[i], "b": names[j],
                               "normal_rho": _r(_corr(S[~crisis, i], S[~crisis, j])),
                               "crisis_rho": _r(_corr(S[crisis, i], S[crisis, j]))}
        if np.var(S[:, i]) <= _FLAT_VAR or np.var(S[:, j]) <= _FLAT_VAR:
            row.update(co_drops=None, expected_co_drops=None, reason=_FLAT_REASON)
        else:
            rho = float(np.corrcoef(_normal_scores(S[:, i]), _normal_scores(S[:, j]))[0, 1])
            rho = min(max(rho, -0.999), 0.999)
            p2 = float(multivariate_normal(mean=[0.0, 0.0], cov=[[1.0, rho], [rho, 1.0]]).cdf([zq, zq]))
            row.update(co_drops=int(np.sum(below[:, i] & below[:, j])), expected_co_drops=_r(p2 * T, 1),
                       days_each=int(round(q * T)))
        pairs.append(row)
    return {"available": True, "basis": basis, "q": q, "crisis_days": m, "n_days": T,
            "small_sample": m < SMALL_CRISIS_DAYS, "pairs": pairs, "note": note}


# ── 최악 구간 겹침 ───────────────────────────────────────────────────────────

def _max_drawdown(r: np.ndarray) -> tuple[float, int, int] | None:
    wealth = np.cumprod(1.0 + r)
    peak = np.maximum.accumulate(np.concatenate([[1.0], wealth]))[1:]
    dd = wealth / peak - 1.0
    k = int(np.argmin(dd))
    if dd[k] >= 0:
        return None
    before = np.concatenate([[1.0], wealth[: k + 1]])
    p = int(np.argmax(before))                                     # 0 = 첫날 전(시작 값)
    return float(dd[k]), p, k                                      # 잃은 날 = p .. k (수익 번호)


def _shares(shares: Sequence[float] | None, n: int) -> tuple[np.ndarray, str]:
    if shares is None:
        return np.ones(n) / n, "equal"
    w = np.asarray([float(x) for x in shares], dtype=float)
    g = np.abs(w).sum()
    return (w / g, "given") if g > 0 else (np.ones(n) / n, "equal")


def drawdown_overlap(names: Sequence[str], S: np.ndarray, shares: Sequence[float] | None = None,
                     worst_window: int = 20) -> dict[str, Any]:
    """전략마다 최대 낙폭 구간 · 쌍마다 겹친 거래일 ÷ 합친 거래일 · 합친 흐름의 최악 구간에 각 전략이 낸 수익."""
    T, n = S.shape
    ago = lambda i: T - 1 - i  # noqa: E731
    rows, spans = [], []
    for j in range(n):
        md = _max_drawdown(S[:, j])
        if md is None:
            rows.append({"name": names[j], "max_drawdown_pct": None, "reason": "이 기간에 잃은 적이 없어요"})
            spans.append(None)
            continue
        dd, p, k = md
        rows.append({"name": names[j], "max_drawdown_pct": round(dd * 100, 2), "start_ago": ago(p), "end_ago": ago(k),
                     "days": k - p + 1})
        spans.append(set(range(p, k + 1)))
    pairs = []
    for i, j in _pairs(n):
        if spans[i] is None or spans[j] is None:
            pairs.append({"a": names[i], "b": names[j], "overlap": None,
                          "reason": "잃은 적이 없는 쪽이 있어 겹침을 잴 수 없어요"})
            continue
        inter, union = len(spans[i] & spans[j]), len(spans[i] | spans[j])
        pairs.append({"a": names[i], "b": names[j], "overlap_days": inter, "union_days": union,
                      "overlap": round(inter / union, 3)})
    w, basis = _shares(shares, n)
    out: dict[str, Any] = {"available": True, "strategies": rows, "pairs": pairs, "shares_basis": basis}
    if T < worst_window:
        out["worst_window"] = None
        out["worst_window_reason"] = f"흐름이 {T}거래일이라 {worst_window}일 최악 구간을 볼 수 없어요"
        return out
    P = S @ w
    lp = np.log1p(np.clip(P, -0.999999, None))
    c = np.concatenate([[0.0], np.cumsum(lp)])
    sums = c[worst_window:] - c[:-worst_window]
    s = int(np.argmin(sums))
    e = s + worst_window - 1
    out["worst_window"] = {
        "days": worst_window, "start_ago": ago(s), "end_ago": ago(e),
        "combined_pct": round((math.exp(float(sums[s])) - 1) * 100, 2),
        "returns_pct": {names[j]: round((float(np.prod(1.0 + S[s:e + 1, j])) - 1) * 100, 2) for j in range(n)},
    }
    return out


# ── 안정성 · 실질 개수 · 분산 효과 ───────────────────────────────────────────

def correlation_stability(names: Sequence[str], S: np.ndarray) -> dict[str, Any]:
    """앞 절반 대 뒤 절반 상관 — Fisher z 차이가 1.96 을 넘으면 '우연으로 보기엔 커요'."""
    T, n = S.shape
    h = T // 2
    pairs = []
    for i, j in _pairs(n):
        r1, r2 = _corr(S[:h, i], S[:h, j]), _corr(S[h:, i], S[h:, j])
        if r1 is None or r2 is None or h < 10:
            pairs.append({"a": names[i], "b": names[j], "first": _r(r1), "second": _r(r2), "changed": None,
                          "reason": _FLAT_REASON if h >= 10 else "흐름이 짧아 절반씩 나눠 볼 수 없어요"})
            continue
        f = lambda r: math.atanh(min(max(r, -0.999999), 0.999999))  # noqa: E731
        z = (f(r1) - f(r2)) / math.sqrt(1.0 / max(h - 3, 1) + 1.0 / max(T - h - 3, 1))
        pairs.append({"a": names[i], "b": names[j], "first": _r(r1), "second": _r(r2), "z": _r(z, 2),
                      "changed": bool(abs(z) > 1.96)})
    return {"available": True, "half_days": h, "pairs": pairs,
            "note": "앞 절반과 뒤 절반의 상관 — 차이가 표본 오차로 설명되기 어려우면(|z|>1.96) 관계가 바뀐 거예요."}


def effective_count(names: Sequence[str], S: np.ndarray) -> dict[str, Any]:
    """상관행렬 고유값 참여비 — 같은 흐름 둘이면 1, 서로 독립이면 n."""
    from src.engine.deflated_sharpe import participation_ratio
    n = S.shape[1]
    flat = [names[j] for j in range(n) if np.var(S[:, j]) <= _FLAT_VAR]
    if flat:
        return {"available": False, "value": None, "n": n,
                "reason": f"흔들림이 없는 흐름({', '.join(flat)})이 있어 서로 얼마나 닮았는지 잴 수 없어요"}
    C = np.corrcoef(S.T)
    if not np.all(np.isfinite(C)):
        return {"available": False, "value": None, "n": n, "reason": "상관을 계산하지 못했어요"}
    return {"available": True, "value": round(participation_ratio(C), 3), "n": n}


def diversification(S: np.ndarray, shares: Sequence[float] | None = None) -> dict[str, Any]:
    """분산 효과 Σ|w|σ / σ_p — 1 이면 따로 움직여 줄어든 흔들림이 없다."""
    w, basis = _shares(shares, S.shape[1])
    sig = S.std(axis=0)
    sp = float((S @ w).std())
    if sp <= math.sqrt(_FLAT_VAR):
        return {"available": False, "ratio": None, "shares_basis": basis, "reason": "합친 흐름에 흔들림이 없어요"}
    return {"available": True, "ratio": round(float(np.abs(w) @ sig) / sp, 3), "shares_basis": basis,
            "vol_pct": round(sp * math.sqrt(252) * 100, 2)}


# ── 묶음 보고서 ───────────────────────────────────────────────────────────────

def _attach_dates(rep: dict[str, Any], dates: Sequence[str]) -> None:
    """★로더가 준 날짜만★ 붙인다(BS3) — 'n거래일 전' 번호(`*_ago`)는 그대로 두고 옆에 날짜를 단다."""
    T = len(dates)
    at = lambda ago: dates[T - 1 - ago]  # noqa: E731
    rep["axis"] = "date"
    rep["period"] = {"start": dates[0], "end": dates[-1]}
    roll = rep["rolling"]
    if roll.get("available"):
        roll["end_dates"] = [at(a) for a in roll["ago"]]
    for row in rep["drawdown"].get("strategies") or []:
        if row.get("max_drawdown_pct") is not None:
            row["start_date"], row["end_date"] = at(row["start_ago"]), at(row["end_ago"])
    w = rep["drawdown"].get("worst_window")
    if w:
        w["start_date"], w["end_date"] = at(w["start_ago"]), at(w["end_ago"])


def robustness_report(names: Sequence[str], S: np.ndarray, shares: Sequence[float] | None = None, *,
                      market: np.ndarray | None = None, window: int = 60, q: float = 0.1,
                      worst_window: int = 20, dates: Sequence[str] | None = None) -> dict[str, Any]:
    """위 블록을 한 번에. 상관 급등 충격(`shock`)은 부르는 쪽(노드 층)이 `stress_correlation_report` 로 붙인다.

    `dates` (BS3) — 흐름 행마다의 날짜(로더가 준 것). 주면 `axis="date"` 와 블록마다 날짜가 붙고, 주지 않으면
    예전처럼 'n거래일 전' 만 싣는다(날짜를 지어내지 않는다). 길이가 흐름과 다르면 실패 + 사유.
    """
    names = list(names)
    S = np.asarray(S, dtype=float)
    if S.ndim != 2 or S.shape[1] < 2 or len(names) != S.shape[1]:
        return {"available": False, "reason": "견고성은 흐름이 둘 이상 있어야 볼 수 있어요"}
    if S.shape[0] < 30:
        return {"available": False, "reason": f"흐름이 {S.shape[0]}거래일뿐이라 견고성을 볼 수 없어요(적어도 30일)"}
    if dates is not None and len(dates) != S.shape[0]:
        return {"available": False,
                "reason": f"날짜 수({len(dates)})가 흐름 길이({S.shape[0]})와 달라 어느 날의 값인지 말할 수 없어요"}
    _, basis = _shares(shares, len(names))
    rep = {
        "available": True, "names": names, "n_days": int(S.shape[0]), "axis": "trading_days_ago",
        "shares_basis": basis,
        "rolling": rolling_correlation(names, S, window),
        "crisis": crisis_correlation(names, S, market, q),
        "drawdown": drawdown_overlap(names, S, shares, worst_window),
        "stability": correlation_stability(names, S),
        "effective_n": effective_count(names, S),
        "diversification": diversification(S, shares),
    }
    if dates is not None:
        _attach_dates(rep, list(dates))
    return rep
