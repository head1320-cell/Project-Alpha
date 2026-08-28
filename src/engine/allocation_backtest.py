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
                delta: float, tau: float,
                s_override=None, extra_views: list[dict] | None = None) -> np.ndarray:
    """한 시점의 목표 가중치 — /analyze 와 동일 경로(뷰→BL, 제약이면 constrained_solve).

    `s_override`/`extra_views` 는 국면 조건부 훅이 넘긴다(MS1-b0). `None` 이면
    현행과 완전히 같은 계산이다 — B0 팔이 그것이다.
    """
    from src.engine.allocation_studio import optimize
    opt = optimize(model, names, R_win, views=views or None, delta=delta, tau=tau,
                   s_override=s_override, extra_views=extra_views)
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
    # ★롱숏이면 클램프도 넷 정규화도 하지 않는다 (P3)★
    # 넷으로 나누면 달러중립(Σw≈0)에서 0 나눗셈이고, 클램프는 제약 해를 망가뜨린다
    # (`constrained_opt` 의 같은 결함 — 그쪽 주석 참고). 제약이 이미 gross/net 을
    # 규정하고 있으므로 여기서 다시 정규화할 이유가 없다 — 해를 그대로 쓴다.
    if constraints is not None and getattr(constraints, "allows_short", lambda: False)():
        gross = float(np.abs(w).sum())
        return w if gross > 0 else np.zeros(len(names))
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


# ══════════════════════════════════════════════════════════════════════════════
# 국면 조건부 훅 (MS1-b0) — ★백테스트에서 국면을 쓰는 순간 look-ahead 가 생긴다★
# ══════════════════════════════════════════════════════════════════════════════
# `/analyze` 의 조건부 경로는 **오늘** 기준 국면 경로를 쓴다. 그것을 그대로 과거
# 리밸런싱에 쓰면 2020년의 결정이 2026년의 라벨을 보는 것이다. 그래서 이 훅은
# 매 리밸런싱마다 경로를 **그 시점까지 잘라서** 넘기고, 무엇을 봤는지
# `regime_audit` 에 남긴다 — 절단은 주장이 아니라 기록으로 증명한다.
#
# 세 팔:
#   B0  regime=None            국면 배선 없음(사다리의 바닥)
#   B1  weighting="hard"       오늘 라벨 하나 = 확률 1 (현행 프로덕션)
#   N   weighting="probabilistic"  π_1..π_h 혼합 (MS1-a)

_REGIME_ARMS = ("hard", "probabilistic")


def _month_of(d) -> str:
    try:
        return d.strftime("%Y-%m")
    except Exception:                                    # noqa: BLE001
        return str(d)[:7]


def _truncated_points(points: list[dict], month: str) -> list[dict]:
    """`month` **이하**의 달만 남긴다 — 미래를 잘라내는 단 한 곳."""
    from src.engine.conditional_market import _normalize_month
    out = []
    for p in points or []:
        m = _normalize_month(p.get("t"))
        if m and m <= month:
            out.append(p)
    return out


def _view_confidence(cond: dict, kind: str) -> tuple[float, str]:
    """뷰 신뢰도 — ★분해 Ω 가 기본이고 legacy 스칼라는 명시적으로 골라야 한다★.

    MS1-a 가 만든 분해 Ω(`view_omega_terms` + `implied_confidence`)가 라우트에만
    배선돼 있어 **평가에서는 한 번도 시험되지 않았다**(전달계층 감사 §3). 여기서
    잇는다 — 그리고 두 방식을 나란히 돌릴 수 있게 `kind` 로 고른다.

    반사실 실측: 이 패널에서 legacy 는 `conf ≈ 50`(최대), 분해는 `≈ 8` 이고
    회전율이 32.42% → 7.71% 로 갈린다. 즉 어느 쪽을 쓰느냐가 결과를 지배한다.
    """
    from src.engine.conditional_market import (
        implied_confidence,
        resolve_shrinkage_lambda,
        view_omega_terms,
    )

    if kind == "legacy":
        lam = resolve_shrinkage_lambda(cond)     # ★dict 면 올린다 — 0.0 금지★
        return round(max(0.0, min(50.0 * (1.0 - lam), 50.0)), 2), "legacy_scalar"

    sig = np.asarray(cond["sigma"], dtype=float)
    # 국면 간 항이 있으면(혼합) 그것이 국면 불확실성이고, 없으면(하드) 0 이다 —
    # 하드 라벨은 "국면을 확실히 안다" 고 주장하는 것이므로 그 항이 0인 것이 맞다.
    A = cond.get("A_h")
    W = cond.get("W_h")
    h = int(cond.get("h_hold") or 1)
    if A is not None and W is not None:
        ann = 12.0 / h
        regime_diag = np.maximum(np.diag(np.asarray(A, dtype=float) * ann), 0.0)
        within_diag = np.maximum(np.diag(np.asarray(W, dtype=float) * ann), 0.0)
    else:
        regime_diag = np.zeros(sig.shape[0])
        within_diag = np.maximum(np.diag(sig), 0.0)
    months = cond.get("n_months_by_regime") or {}
    n_months = max(1, min(months.values(), default=int(cond.get("n_months") or 1)))
    terms = view_omega_terms(regime_diag=regime_diag,
                             sigma_within_diag=within_diag, n_months=n_months)
    conf = implied_confidence(terms["omega_diag"], np.maximum(np.diag(sig), 1e-12))
    # ★가장 약한 자산을 따른다★ 한 자산의 뷰만 강해도 최적화기는 그쪽으로 쏠린다.
    return round(float(np.min(conf)), 2), "decomposed_omega"


def _regime_override_at(regime: dict, month: str, R_win: np.ndarray,
                        dates_win: list, names: list[str], model: str):
    """한 리밸런싱 시점의 `(s_override, extra_views, audit)`.

    실패는 조용히 넘기지 않는다 — 조건부를 못 만들면 무조건부로 계산하되
    `applied: False` 와 사유가 `regime_audit` 에 남는다.
    """
    import pandas as pd

    from src.engine.conditional_market import (
        conditional_moments,
        regime_by_month_from_path,
        regime_mixture_moments,
    )
    from src.engine.regime_probability import (
        ASSUMPTION_NOTE,
        SOURCE_FORECAST_MEAN,
        SOURCE_HARD_LABEL,
        USAGE_ASSUMPTION,
        USAGE_PORTFOLIO,
    )

    # ★`prob_*` 는 **모든 분기가 낸다**★ 어떤 응답에만 있으면 소비자가 `.get()` 으로
    # 읽다가 `None` 을 거짓으로 취급한다(`source_registry.not_ingested` 와 같은 규율).
    #
    # ★무엇을 신고하는가★ `regime_probability` 의 계약은 "배분에 닿을 수 있는 것은
    # `k_step_forecast` 하나뿐" 인데, `weighting` 기본값 `"hard"` 는 확률 객체를
    # 거치지 않으므로 `require_portfolio_source` 를 통과하지 않는다. 그 사실이
    # 어디에도 남지 않아, 기본 경로가 계약을 통과한 것처럼 읽혔다.
    # ★신고만 한다 — 막지 않는다★ 막는 것은 배분 정책 변경이라 별도 승인 사항이다.
    audit = {"month": month, "applied": False, "reason": None,
             "path_len": 0, "last_path_month": "", "regime": None,
             "h_hold": None, "pi_bar": None, "a_contribution_pct": None,
             "confidence": None, "confidence_model": None,
             "prob_source": None, "prob_usage": None, "prob_note": None}
    pts = _truncated_points(regime.get("points") or [], month)
    audit["path_len"] = len(pts)
    audit["last_path_month"] = _month_of_point(pts[-1]) if pts else ""
    if len(pts) < 2:
        audit["reason"] = "그 시점까지의 국면 경로가 2개월 미만입니다."
        return None, None, audit

    by_month, _dropped = regime_by_month_from_path(pts)
    current = pts[-1].get("regime")
    audit["regime"] = current
    df = pd.DataFrame(R_win, index=pd.DatetimeIndex(dates_win), columns=names)

    weighting = regime.get("weighting", "hard")
    if weighting == "hard":
        # ★계약을 통과하지 않는 경로다★ 하드 라벨은 확률 1.000 이고, 그것은
        # 예측이 아니라 "오늘 국면이 보유기간 동안 지속된다" 는 가정이다.
        audit["prob_source"] = SOURCE_HARD_LABEL
        audit["prob_usage"] = USAGE_ASSUMPTION
        audit["prob_note"] = ASSUMPTION_NOTE
        cond = conditional_moments(df, by_month, current)
    else:
        from src.engine.regime_probability import (
            from_posterior_mean_path,
            require_portfolio_source,
        )
        from src.engine.regime_transitions import (
            REGIMES,
            count_transitions,
            transition_posterior,
        )
        h_hold = int(regime.get("h_hold") or 1)
        audit["h_hold"] = h_hold
        try:
            rows = transition_posterior(count_transitions(pts))
            probs, P = from_posterior_mean_path(rows, current, h_hold,
                                                list(REGIMES), mode="backtest")
            for pr in probs:
                require_portfolio_source(pr)
            # ★검사를 통과한 뒤에 적는다★ 먼저 적으면 통과 여부와 무관한 선언이 된다.
            audit["prob_source"] = SOURCE_FORECAST_MEAN
            audit["prob_usage"] = USAGE_PORTFOLIO
            cond = regime_mixture_moments(df, by_month, [p.probs for p in probs],
                                          P, list(REGIMES), h_hold=h_hold)
        except Exception as e:                            # noqa: BLE001
            audit["reason"] = f"{type(e).__name__}: {e}"
            return None, None, audit

    if not cond.get("available"):
        audit["reason"] = cond.get("reason")
        return None, None, audit

    audit["applied"] = True
    # ★예측 집중도를 재려면 π̄ 가 감사에 남아야 한다★ 남기지 않으면 소비자가
    # 읽을 필드가 없어 지표가 조용히 None 이 된다(실제로 그렇게 한 번 헛돌았다).
    audit["pi_bar"] = cond.get("pi_bar")
    audit["a_contribution_pct"] = cond.get("A_contribution_pct")
    extra_views = None
    if model in ("bl", "ep"):
        # `/analyze` 의 `_conditional_views` 와 같은 규약 — μ 를 최적화기에 직접
        # 대입하지 않고 자산별 절대 뷰로 태운다(불확실성을 Ω 에 남기기 위해서).
        conf, cmodel = _view_confidence(cond, regime.get("confidence", "decomposed"))
        audit["confidence"] = conf
        audit["confidence_model"] = cmodel
        extra_views = [
            {"assets": [nm], "direction": 1 if float(m) >= 0 else -1,
             "magnitude_pct": abs(float(m)) * 100.0, "confidence": conf,
             "source": "conditional", "regime": cond.get("regime")}
            for nm, m in zip(names, cond["mu"], strict=False) if float(m) != 0.0
        ] or None
    return cond["sigma"], extra_views, audit


def _month_of_point(p: dict) -> str:
    from src.engine.conditional_market import _normalize_month
    return _normalize_month(p.get("t")) or ""


def walk_forward(names: list[str], R: np.ndarray, dates: list,
                 model: str = "mvo", views: list[dict] | None = None,
                 constraints=None, rebalance: str = "M",
                 window_days: int | None = None, cost_bps: float = 10.0,
                 bench: np.ndarray | None = None,
                 min_train: int = 63, delta: float = 2.5, tau: float = 0.05,
                 regime: dict | None = None) -> dict:
    """정책 walk-forward 백테스트.

    R: T×N 일별 수익률 · dates: 길이 T date-like · window_days: rolling(None=expanding).
    반환: equity_curve/bench_curve/drawdown_curve/rebalances/metrics/summary (전부 OOS).
    """
    R = np.asarray(R, dtype=float)
    n = len(names)
    if n < 2 or R.ndim != 2 or R.shape[1] != n or R.shape[0] < min_train + 5:
        return {"error": True, "message": "백테스트에는 자산 2개 이상과 충분한 시계열이 필요합니다."}

    arm = "B0"
    infeasible: list[dict] = []
    if regime is not None:
        weighting = regime.get("weighting", "hard")
        if weighting not in _REGIME_ARMS:
            return {"error": True,
                    "message": (f"'{weighting}' 은 지원하는 국면 가중 방식이 아닙니다 — "
                                f"{' 또는 '.join(_REGIME_ARMS)} 만 됩니다.")}
        ckind = regime.get("confidence", "decomposed")
        if ckind not in ("decomposed", "legacy"):
            return {"error": True,
                    "message": (f"'{ckind}' 은 지원하는 신뢰도 방식이 아닙니다 — "
                                "decomposed 또는 legacy 만 됩니다.")}
        arm = "B1" if weighting == "hard" else "N"
    regime_detail: list[dict] = []

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
                s_override = xviews = None
                if regime is not None:
                    # ★그 시점까지로 자른 경로만 넘긴다★ (모듈 상단 주석 참조)
                    s_override, xviews, aud = _regime_override_at(
                        regime, _month_of(dates[t]), R_win, list(dates[lo:t]),
                        names, model)
                    regime_detail.append(aud)
                w_new = None
                try:
                    w_new = _weights_at(model, names, R_win, views, constraints,
                                        w_prev_target, bench_win, delta, tau,
                                        s_override=s_override, extra_views=xviews)
                except Exception as e:                        # noqa: BLE001
                    # ★거부는 사고가 아니라 정보다★ 엔트로피 풀링은 뷰를 동시에
                    # 만족시키는 분포가 없으면 배분을 거부한다(`EPUnavailable`).
                    # 그때 무조건부로 몰래 떨어지면 그 팔이 오염되므로, **거래하지
                    # 않고**(직전 비중 유지) 그 사실을 센다. 전체를 죽이지도 않는다.
                    #
                    # ★`continue` 로 넘기면 안 된다★ 그날의 수익 적용까지 건너뛰어
                    # 곡선에서 하루가 사라진다 — 거래를 안 했을 뿐 포지션은 그대로
                    # 들고 있다. 아래 `if w_new is not None:` 로 리밸런싱만 건너뛴다.
                    infeasible.append({"month": _month_of(dates[t]),
                                       "error": f"{type(e).__name__}: {e}"})
                    logger.info("리밸런싱 %s 배분 거부: %s", dates[t], e)
                if w_new is None:
                    w_new = w                                  # 거래하지 않는다
                turnover = 0.5 * float(np.abs(w_new - w).sum())   # 편도 회전율
                equity *= (1.0 - turnover * cost)
                w = w_new
                w_prev_target = {names[i]: float(w[i]) for i in range(n)}
                # ★예측은 그 시점의 학습창만 쓴다★ 앞으로의 구간 길이도 수익도 모른다.
                rb_at.append(t)
                rb_preds.append(float(w_new @ R_win.mean(axis=0)))
                rebalances.append({
                    "date": str(getattr(dates[t], "date", lambda: dates[t])()),
                    # `abs()` — 부호가 아니라 잡음만 거른다 (P3, `_w_dict` 와 같은 이유)
                    "weights": {names[i]: round(float(w[i]) * 100, 2)
                                for i in range(n) if abs(w[i]) > 5e-4},
                    "turnover_pct": round(turnover * 100, 2),
                    # 롱숏에서는 넷 하나로 포지션 크기를 말할 수 없다
                    "gross_pct": round(float(np.abs(w).sum()) * 100, 2),
                    "net_pct": round(float(w.sum()) * 100, 2),
                })
        r_t = R[t]
        pr = float(w @ r_t)                        # 당일 포트 수익(장초 비중 기준)
        equity *= (1.0 + pr)
        # 비중 표류 — 포트폴리오 가치 대비로 나눈다: wᵢ(1+rᵢ) / (1+r_p)
        #
        # ★예전에는 Σ 로 나눴다 (P3 에서 고침)★ 롱온리 완전투자에서는 Σwᵢ(1+rᵢ)
        # = 넷(=1) + r_p = 1+r_p 라 **두 식이 완전히 같다** — 그래서 롱온리 결과는
        # 한 자리도 안 바뀐다. 하지만 넷이 1 이 아닌 롱숏에서는 Σ 로 나누는 순간
        # 넷이 매일 강제로 1 로 되돌려진다(= 매일 공짜 리밸런싱). 달러중립(넷≈0)
        # 에서는 0 나눗셈으로 폭발한다.
        denom = 1.0 + pr
        if denom > 0:
            w = w * (1.0 + r_t) / denom
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

    # ★롱숏 백테스트의 비용은 이 엔진이 모델하지 않는다 — 값으로 채우지 말고 적는다★
    # `cost_bps` 는 거래비용(수수료·세금·스프레드)만 본다. 숏 포지션에는 그 밖에
    # **차입수수료(대차/대주 이자) · 숏 배당지급 · 증거금 이자**가 붙는데 전부
    # 미반영이다. 이걸 적지 않으면 롱숏이 롱온리보다 좋아 보이는 것이 **모델 때문인지
    # 누락 때문인지 구분할 수 없다.** 데이터가 없으므로 추정치를 지어내지 않는다.
    short_notes: list[str] = []
    is_long_short = bool(constraints is not None
                         and getattr(constraints, "allows_short", lambda: False)())
    if is_long_short:
        gross_hist = [rb_.get("gross_pct") for rb_ in rebalances if rb_.get("gross_pct")]
        short_notes.append(
            "숏 비용 미반영 — 차입수수료·숏 배당지급·증거금 이자가 이 곡선에 없습니다. "
            "롱온리와의 비교는 그만큼 롱숏에 유리하게 기울어 있습니다.")
        short_notes.append(
            "실행 불가 — 이 목표는 연구·백테스트 전용입니다(차입 가능여부 미연동 · "
            "KIS 주문 유형에 공매도 없음).")
        if gross_hist:
            short_notes.append(
                f"평균 gross 노출 {round(float(np.mean(gross_hist)), 1)}% — "
                f"거래비용 {cost_bps}bp 는 회전율에만 적용됐습니다.")

    return {
        "error": False,
        "long_short": is_long_short,
        "notes": short_notes,
        # ★분포 무가정 예측 구간 (M2-C)★ 적중률은 **주장이 아니라 실측**으로 함께 낸다.
        "conformal": conformal,
        "dates": [str(getattr(dates[i], "date", lambda i=i: dates[i])()) for i in sim_dates],
        "equity_curve": list(np.round(eq, 5)),
        "bench_curve": bench_curve,
        "drawdown_curve": list(np.round(dd * 100, 3)),
        "rebalances": rebalances,
        "n_rebalances": len(rebalances),
        # ★절단을 주장이 아니라 기록으로 증명한다★ 각 리밸런싱이 **그 시점까지의**
        # 경로 몇 개를 봤는지, 마지막으로 본 달이 언제인지, 조건부가 실제로
        # 적용됐는지(안 됐으면 왜)를 남긴다. 이것이 없으면 "walk-forward 인 척하는
        # in-sample" 을 나중에 구분할 방법이 없다.
        "regime_audit": {
            "arm": arm,
            "n_rebalances": len(rebalances),
            "s_override_used": sum(1 for d in regime_detail if d["applied"]),
            "path_len_at_rebalance": [d["path_len"] for d in regime_detail],
            # ★배분이 거부된 시점★ 무조건부로 몰래 떨어지지 않고 거래를 건너뛴 횟수.
            "confidence_model": next((d["confidence_model"] for d in regime_detail
                                      if d.get("confidence_model")), None),
            "confidence_mean": (round(float(np.mean(
                [d["confidence"] for d in regime_detail
                 if d.get("confidence") is not None])), 3)
                if any(d.get("confidence") is not None for d in regime_detail) else None),
            "weights_infeasible": len(infeasible),
            "infeasible_detail": infeasible[:20],
            "detail": regime_detail,
        },
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
