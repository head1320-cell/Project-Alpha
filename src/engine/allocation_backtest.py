"""Allocation-Policy Walk-Forward Backtest (AAS roadmap 07 — the OOS credibility keystone).
==============================================================================
정책(모델+뷰+제약+리밸런싱+비용)을 **시점 밖(out-of-sample)** 으로 재현한다. 각 리밸런싱
시점 k의 가중치는 **오직 k 이전 데이터**(rolling window 또는 expanding)로만 계산 → look-ahead
없음. 리밸런싱 사이에는 실현수익으로 비중이 표류(drift)하고, 리밸런싱마다 회전율 비용을 차감한다.

재사용:
  · optimize()/constrained_solve() — /analyze 와 동일 경로(실제 정책을 검증)
  · compute_metrics() — OOS Sharpe/Sortino/Calmar/MDD/VaR/CVaR/IR
정직: 뷰는 사용자의 지속 테제로 매 시점 적용(미래 데이터 아님). 비용은 편도 회전율 기준.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

_RF = 0.035


def _period_key(d: Any, rebalance: str) -> tuple[int, int]:
    """date-like(pandas Timestamp/datetime) → 기간 키. 키가 바뀌는 첫 거래일이 리밸런싱일."""
    y, m = int(d.year), int(d.month)
    return (y, (m - 1) // 3) if rebalance == "Q" else (y, m)


def _rebalance_indices(dates: list, rebalance: str, min_train: int) -> list[int]:
    """기간 경계(월/분기)의 첫 거래일 인덱스 중, 앞에 학습데이터가 min_train 이상인 것."""
    idxs: list[int] = []
    prev = None
    for i, d in enumerate(dates):
        key = _period_key(d, rebalance)
        if key != prev and i >= min_train:
            idxs.append(i)
        prev = key
    return idxs


def _weights_at(model: str, names: list[str], R_win: np.ndarray,
                views: list[dict] | None, constraints,
                w_prev: dict[str, float] | None,
                bench_win: np.ndarray | None,
                delta: float, tau: float) -> np.ndarray:
    """한 시점의 목표 가중치 — /analyze 와 동일 경로(뷰→BL, 제약이면 constrained_solve)."""
    from src.engine.allocation_studio import optimize
    opt = optimize(model, names, R_win, views=views or None, delta=delta, tau=tau)
    w = np.asarray(opt["weights"], dtype=float)
    if constraints is not None and getattr(constraints, "any_active", lambda: False)():
        try:
            from src.engine.constrained_opt import constrained_solve, sector_groups_for
            sol = constrained_solve(
                model, names, R_win,
                mu=np.asarray(opt["mu_used"], dtype=float),
                S=np.asarray(opt["sigma_annual"], dtype=float),
                constraints=constraints, w_current=w_prev,
                groups_of=sector_groups_for(names),
                bench_returns=bench_win,
            )
            if sol.get("status") != "infeasible" and sol.get("weights") is not None:
                w = np.asarray(sol["weights"], dtype=float)
        except Exception as e:  # 제약 해 실패 — 무제약 해 유지(정직 폴백)
            logger.warning(f"walk-forward 제약 해 실패, 무제약 유지: {e}")
    w = np.maximum(w, 0.0)
    s = w.sum()
    return (w / s) if s > 0 else np.ones(len(names)) / len(names)


def walk_forward(names: list[str], R: np.ndarray, dates: list,
                 model: str = "mvo", views: list[dict] | None = None,
                 constraints=None, rebalance: str = "M",
                 window_days: int | None = None, cost_bps: float = 10.0,
                 bench: np.ndarray | None = None,
                 min_train: int = 63, delta: float = 2.5, tau: float = 0.05) -> dict:
    """정책 walk-forward 백테스트.

    R: T×N 일별 수익률 · dates: 길이 T date-like · window_days: rolling(None=expanding).
    반환: equity_curve/bench_curve/drawdown_curve/rebalances/metrics/summary (전부 OOS).
    """
    R = np.asarray(R, dtype=float)
    n = len(names)
    if n < 2 or R.ndim != 2 or R.shape[1] != n or R.shape[0] < min_train + 5:
        return {"error": True, "message": "백테스트에는 자산 2개 이상과 충분한 시계열이 필요합니다."}

    rb = _rebalance_indices(list(dates), rebalance, min_train)
    if len(rb) < 2:
        return {"error": True, "message": "리밸런싱 구간이 부족합니다 — 기간을 늘리거나 리밸런싱 주기를 줄이세요."}

    start = rb[0]                                  # 시뮬레이션 시작(첫 리밸런싱)
    T = R.shape[0]
    cost = float(cost_bps) / 1e4

    equity = 1.0
    eq_curve: list[float] = []
    port_daily: list[float] = []
    sim_dates: list = []
    rebalances: list[dict] = []
    w = np.zeros(n)                                # 현재 보유(표류) 비중
    w_prev_target: dict[str, float] | None = None
    rb_set = set(rb)

    for t in range(start, T):
        if t in rb_set:
            lo = max(0, t - window_days) if window_days else 0
            R_win = R[lo:t]
            bench_win = bench[lo:t] if bench is not None and len(bench) >= t else None
            if R_win.shape[0] >= min_train:
                w_new = _weights_at(model, names, R_win, views, constraints,
                                    w_prev_target, bench_win, delta, tau)
                turnover = 0.5 * float(np.abs(w_new - w).sum())   # 편도 회전율
                equity *= (1.0 - turnover * cost)
                w = w_new
                w_prev_target = {names[i]: float(w[i]) for i in range(n)}
                rebalances.append({
                    "date": str(getattr(dates[t], "date", lambda: dates[t])()),
                    "weights": {names[i]: round(float(w[i]) * 100, 2) for i in range(n) if w[i] > 5e-4},
                    "turnover_pct": round(turnover * 100, 2),
                })
        r_t = R[t]
        pr = float(w @ r_t)                        # 당일 포트 수익(장초 비중 기준)
        equity *= (1.0 + pr)
        # 비중 표류
        growth = w * (1.0 + r_t)
        gs = growth.sum()
        if gs > 0:
            w = growth / gs
        port_daily.append(pr)
        eq_curve.append(equity)
        sim_dates.append(t)

    port = np.asarray(port_daily, dtype=float)
    eq = np.asarray(eq_curve, dtype=float)
    peak = np.maximum.accumulate(eq)
    dd = (eq / peak - 1.0)

    # 벤치마크(매수보유) 정렬 — 시뮬 구간
    bench_curve = None
    bench_aligned = None
    if bench is not None and len(bench) >= T:
        b = np.asarray(bench[start:T], dtype=float)
        if b.shape[0] == port.shape[0]:
            bench_aligned = b
            bench_curve = list(np.round(np.cumprod(1.0 + b), 5))

    from src.engine.quant_metrics import compute_metrics
    metrics = compute_metrics(port, eq, periods_per_year=252,
                              benchmark_returns=bench_aligned, risk_free=_RF)

    total_ret = float(eq[-1] - 1.0)
    years = max(port.shape[0] / 252.0, 1e-9)
    cagr = float(eq[-1] ** (1.0 / years) - 1.0) if eq[-1] > 0 else -1.0
    ann = float(port.mean() * 252)
    vol = float(port.std(ddof=1) * np.sqrt(252)) if port.size > 1 else 0.0
    sharpe = (ann - _RF) / vol if vol > 0 else 0.0
    mdd = float(dd.min()) if dd.size else 0.0
    downside = port[port < 0]
    dvol = float(downside.std(ddof=1) * np.sqrt(252)) if downside.size > 1 else 0.0
    sortino = (ann - _RF) / dvol if dvol > 0 else 0.0
    calmar = ann / abs(mdd) if mdd < 0 else 0.0
    active_ret = None
    info_ratio = None
    if bench_aligned is not None and bench_aligned.size > 1:
        active = port - bench_aligned
        active_ret = float(active.mean() * 252)
        te = float(active.std(ddof=1) * np.sqrt(252))
        info_ratio = (active_ret / te) if te > 0 else 0.0

    turnovers = [rb_["turnover_pct"] for rb_ in rebalances]
    return {
        "error": False,
        "dates": [str(getattr(dates[i], "date", lambda i=i: dates[i])()) for i in sim_dates],
        "equity_curve": list(np.round(eq, 5)),
        "bench_curve": bench_curve,
        "drawdown_curve": list(np.round(dd * 100, 3)),
        "rebalances": rebalances,
        "n_rebalances": len(rebalances),
        "turnover_avg_pct": round(float(np.mean(turnovers)), 2) if turnovers else 0.0,
        "metrics": metrics,
        "summary": {
            "total_return_pct": round(total_ret * 100, 2),
            "cagr_pct": round(cagr * 100, 2),
            "volatility_pct": round(vol * 100, 2),
            "sharpe_ratio": round(sharpe, 2),
            "sortino_ratio": round(sortino, 2),
            "calmar_ratio": round(calmar, 2),
            "max_drawdown_pct": round(mdd * 100, 2),
            "active_return_pct": round(active_ret * 100, 2) if active_ret is not None else None,
            "information_ratio": round(info_ratio, 2) if info_ratio is not None else None,
        },
        "config": {
            "model": model, "rebalance": rebalance,
            "window": (f"rolling {window_days}d" if window_days else "expanding"),
            "cost_bps": cost_bps, "n_obs": int(T),
        },
    }
