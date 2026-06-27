"""공용 퀀트 성과지표 (QuantStats / empyrical 표준 부분집합).

period-agnostic 순수함수 — daily(252)·monthly(12) 양 경로 공용.

- returns:          기간 수익률 시퀀스 (0.01 = +1%)
- equity:           자본곡선 (낙폭·회복·Ulcer 계산용)
- periods_per_year: 연율화 계수 (일봉 252, 월간 12)
- trades_pnl:       라운드트립 손익/수익률 시퀀스 (있으면 거래 통계)
- benchmark_returns:벤치마크 기간 수익률 (있으면 정보비율)

빈 입력·0분모를 전부 방어한다(None/0). 모든 키를 항상 반환하므로
프론트는 옵셔널 렌더(없으면 "—")만 하면 된다.

출처: ranaroussi/quantstats, quantopian/empyrical.
"""
from __future__ import annotations

import math

import numpy as np


def _arr(xs) -> np.ndarray:
    """리스트/pd.Series/None → 유한값만 남긴 1차원 float 배열."""
    if xs is None:
        return np.array([], dtype=float)
    if hasattr(xs, "values"):  # pd.Series / DataFrame 컬럼
        xs = xs.values
    try:
        a = np.asarray(list(xs), dtype=float).ravel()
    except (TypeError, ValueError):
        return np.array([], dtype=float)
    return a[np.isfinite(a)]


def _max_underwater(dd: np.ndarray) -> int:
    """최장 연속 수중(낙폭<0) 구간의 길이(기간 수)."""
    longest = cur = 0
    for x in dd:
        if x < 0:
            cur += 1
            longest = max(longest, cur)
        else:
            cur = 0
    return int(longest)


def compute_metrics(
    returns,
    equity,
    periods_per_year: int = 252,
    trades_pnl=None,
    benchmark_returns=None,
    risk_free: float = 0.035,
) -> dict:
    """QuantStats 표준 지표 묶음을 반환(기존 stats와 병합해 쓰는 보강 지표)."""
    r = _arr(returns)
    eq = _arr(equity)
    ppy = max(int(periods_per_year), 1)
    n = r.size

    out: dict = {
        # ── 위험 ──
        "volatility_pct": 0.0,
        "downside_deviation_pct": None,
        "var_pct": None,
        "cvar_pct": None,
        "ulcer_index": None,
        "max_drawdown_days": 0,
        "avg_drawdown_pct": None,
        # ── 위험조정 ──
        "omega": None,
        "recovery_factor": None,
        "gain_to_pain": None,
        "tail_ratio": None,
        # ── 분포 ──
        "skew": None,
        "kurtosis": None,
        "best_period_pct": None,
        "worst_period_pct": None,
        # ── 거래 ──
        "payoff_ratio": None,
        "avg_win": None,
        "avg_loss": None,
        "expectancy": None,
        "kelly_pct": None,
        # ── 벤치마크 ──
        "information_ratio": None,
    }

    if n == 0:
        return out

    # ── 변동성 / 분포 ──
    sd = float(r.std(ddof=1)) if n > 1 else 0.0
    out["volatility_pct"] = round(sd * math.sqrt(ppy) * 100, 2)

    downside = r[r < 0]
    if downside.size > 1:
        out["downside_deviation_pct"] = round(float(downside.std(ddof=1)) * math.sqrt(ppy) * 100, 2)
    else:
        out["downside_deviation_pct"] = 0.0

    out["best_period_pct"] = round(float(r.max()) * 100, 2)
    out["worst_period_pct"] = round(float(r.min()) * 100, 2)

    mean_r = float(r.mean())
    pop_sd = float(r.std(ddof=0))
    if pop_sd > 0:
        z = (r - mean_r) / pop_sd
        out["skew"] = round(float(np.mean(z ** 3)), 4)
        out["kurtosis"] = round(float(np.mean(z ** 4) - 3.0), 4)  # 초과첨도(정규=0)
    else:
        out["skew"] = 0.0
        out["kurtosis"] = 0.0

    # ── VaR / CVaR (95% 신뢰) ──
    var = float(np.quantile(r, 0.05))
    out["var_pct"] = round(var * 100, 2)
    tail = r[r <= var]
    cvar = float(tail.mean()) if tail.size > 0 else var
    out["cvar_pct"] = round(cvar * 100, 2)

    # ── Tail ratio = |q95 / q05| ──
    q95 = float(np.quantile(r, 0.95))
    q05 = float(np.quantile(r, 0.05))
    out["tail_ratio"] = round(abs(q95 / q05), 3) if q05 != 0 else None

    # ── Omega / Gain-to-Pain ──
    gains = float(r[r > 0].sum())
    losses = float(-r[r < 0].sum())  # 양수로
    out["omega"] = round(gains / losses, 3) if losses > 0 else None
    out["gain_to_pain"] = round(float(r.sum()) / losses, 3) if losses > 0 else None

    # ── 낙폭 계열 (equity 기반) ──
    if eq.size > 0:
        run_max = np.maximum.accumulate(eq)
        run_max[run_max == 0] = np.nan  # 0 분모 방어
        dd = (eq - run_max) / run_max
        dd = np.nan_to_num(dd, nan=0.0)
        dd_pct = dd * 100
        out["ulcer_index"] = round(math.sqrt(float(np.mean(dd_pct ** 2))), 3)
        neg = dd_pct[dd_pct < 0]
        out["avg_drawdown_pct"] = round(float(neg.mean()), 2) if neg.size > 0 else 0.0
        out["max_drawdown_days"] = _max_underwater(dd)
        max_dd = float(dd.min())  # 음수
        total_ret = float(eq[-1] / eq[0] - 1) if eq[0] != 0 else 0.0
        out["recovery_factor"] = round(total_ret / abs(max_dd), 3) if max_dd < 0 else None

    # ── 거래 통계 (trades_pnl 있을 때) ──
    t = _arr(trades_pnl)
    if t.size > 0:
        wins = t[t > 0]
        loss = t[t < 0]
        aw = float(wins.mean()) if wins.size > 0 else 0.0
        al = float(-loss.mean()) if loss.size > 0 else 0.0  # 양수
        out["avg_win"] = round(aw, 2)
        out["avg_loss"] = round(al, 2)
        out["payoff_ratio"] = round(aw / al, 4) if al > 0 else None
        wr = wins.size / t.size
        out["expectancy"] = round(wr * aw - (1 - wr) * al, 2)
        out["kelly_pct"] = round((wr - (1 - wr) / (aw / al)) * 100, 2) if al > 0 else None

    # ── 벤치마크 정보비율 ──
    b = _arr(benchmark_returns)
    if b.size > 0:
        m = min(b.size, n)
        if m > 1:
            active = r[:m] - b[:m]
            te = float(active.std(ddof=1)) * math.sqrt(ppy)
            ann_active = float(active.mean()) * ppy
            out["information_ratio"] = round(ann_active / te, 3) if te > 0 else None

    return out
