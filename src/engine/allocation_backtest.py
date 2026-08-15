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


def _conformal_block(preds: list[float], at: list[int], eq: np.ndarray,
                     start: int, alpha: float = 0.1) -> dict[str, Any]:
    """리밸런스 예측 vs 실현 → **다음 구간의 분포 무가정 예측 구간** (M2-C).

    ★왜 최적화기가 아니라 백테스트에 붙는가★
    `split_conformal` 은 (실측, 예측) **쌍의 순차 표본**을 요구한다. 최적화 한 번은
    표본 1개라 구간을 낼 수 없다. 배분 경로에서 그런 표본을 만드는 곳은 walk-forward
    리밸런스뿐이다.

    ★단위를 **일평균**으로 맞추는 이유★
    구간 총수익으로 비교하면 예측을 만들 때 "이 구간이 며칠짜리인지" 를 알아야 하는데,
    그건 리밸런스 시점에 알 수 없는 값이다(look-ahead). 그래서 예측은 학습창의 일평균
    기대수익, 실현은 자산곡선 비율의 기하평균 일수익으로 둔다. 둘 다 하루 단위라
    비교가 성립하고 미래를 쓰지 않는다.

    ★적중률은 주장하지 않고 잰다★
    이론 하한 `1-α` 를 그대로 적으면 유한표본에서 거짓이 될 수 있다. 앞 70% 로 보정하고
    뒤 30% 로 **실제 적중률을 세어** 함께 낸다. 잴 표본이 모자라면 숫자 대신 사유다.
    """
    from src.engine.conformal import (
        conformal_quantile,
        measure_coverage,
        required_calibration_size,
        split_conformal,
    )

    need = required_calibration_size(alpha)
    # 마지막 리밸런스는 아직 실현 구간이 없다 — 그것이 **구간을 씌울 대상**이다.
    pairs_n = max(0, len(at) - 1)
    if pairs_n < need:
        return {"available": False, "alpha": alpha, "n_pairs": pairs_n,
                "n_required": need,
                "reason": (f"완료된 리밸런스 구간이 {pairs_n}개로 보정 최소치 {need}개에 "
                           f"미치지 못합니다 (α={alpha}) — 구간을 만들 수 없습니다.")}

    actual: list[float] = []
    for i in range(pairs_n):
        j0, j1 = at[i] - start, at[i + 1] - start
        span = j1 - j0
        if span <= 0 or j0 < 0 or j1 >= eq.size or eq[j0] <= 0:
            return {"available": False, "alpha": alpha, "n_pairs": pairs_n,
                    "reason": "자산곡선에서 리밸런스 구간을 복원할 수 없습니다."}
        # 구간 말일에 부과된 회전율 비용이 이 값에 포함된다 — 비용을 뺀 실현이 사용자가
        # 실제로 얻는 것이므로 그대로 둔다. 다만 예측은 비용을 모르므로 구간은 그만큼
        # 보수적(넓은) 쪽으로 잡힌다. 숨기지 않고 note 에 적는다.
        actual.append(float((eq[j1] / eq[j0]) ** (1.0 / span) - 1.0))

    cal_a = np.asarray(actual, dtype=float)
    cal_p = np.asarray(preds[:pairs_n], dtype=float)

    # 다음 구간의 구간 — 완료된 쌍 전부로 보정한다.
    nxt = split_conformal(cal_a, cal_p, np.array([preds[-1]]), alpha=alpha)
    if not nxt.get("available"):
        return {"available": False, "alpha": alpha, "n_pairs": pairs_n,
                "reason": nxt.get("reason") or "구간을 계산할 수 없습니다."}

    # ★홀드아웃으로 적중률을 실측한다★ 보정에 쓴 표본으로 적중률을 세면 그건 측정이
    # 아니라 자기 확인이다. 앞 70% 보정 · 뒤 30% 검사로 가른다.
    cov: dict[str, Any] = {"available": False,
                           "reason": "적중률을 잴 홀드아웃 표본이 없습니다."}
    k = int(pairs_n * 0.7)
    if k >= need and pairs_n - k >= 1:
        q = conformal_quantile(np.abs(cal_a[:k] - cal_p[:k]), alpha)
        if q.get("available"):
            lo = cal_p[k:] - q["q"]
            hi = cal_p[k:] + q["q"]
            cov = measure_coverage(cal_a[k:], lo, hi)
            if cov.get("available"):
                cov["n_calibration"] = k

    return {
        "available": True,
        "alpha": alpha,
        "unit": "daily_mean_return",
        "n_pairs": pairs_n,
        "n_required": need,
        "next_period": {"point": nxt["point"][0], "lower": nxt["lower"][0],
                        "upper": nxt["upper"][0], "half_width": nxt["q"]},
        # ★이론 하한이 아니라 실측 적중률★ 없으면 없다고 적는다.
        "measured_coverage": cov,
        "note": ("다음 리밸런스 구간의 **일평균** 포트폴리오 수익률 구간입니다. "
                 "교환가능성만 가정하며 분포 가정은 없습니다. 실현값은 구간 말 회전율 "
                 "비용을 반영한 값이라, 비용을 모르는 예측 대비 구간이 다소 넓게 잡힙니다."),
    }


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
    # Conformal 보정셋의 원재료 (M2-C) — 리밸런스 시점 t 와 **그 시점에 알 수 있는**
    # 기대 일수익. 실현값은 루프가 끝난 뒤 자산곡선에서 구한다(구간 길이를 미리 쓰지
    # 않기 위해 총수익이 아니라 **일평균**으로 맞춘다 — 아래 `_conformal_block` 참조).
    rb_at: list[int] = []
    rb_preds: list[float] = []
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
                # ★예측은 그 시점의 학습창만 쓴다★ 앞으로의 구간 길이도 수익도 모른다.
                rb_at.append(t)
                rb_preds.append(float(w_new @ R_win.mean(axis=0)))
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
    conformal = _conformal_block(rb_preds, rb_at, eq, start)
    return {
        "error": False,
        # ★분포 무가정 예측 구간 (M2-C)★ 적중률은 **주장이 아니라 실측**으로 함께 낸다.
        "conformal": conformal,
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
