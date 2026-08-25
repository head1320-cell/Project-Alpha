"""T3 — 매크로 전달 아키텍처 3종 비교 (설계 + 합성 실험 전용)
==============================================================================
전달계층 감사(`docs/specs/2026-08-25-transmission-layer-audit.md`)가 찾은 것:
★국면 신호는 **타이밍**(공통인자의 평균/분산을 바꾼다)인데, 전달은 **자산별 절대
뷰**(단면 장치)다.★ 그 형태 불일치가 존재하지 않는 종목 간 차이를 매달 쫓게 만들고
회전율 32%를 만든다.

이 스크립트는 셋을 나란히 돌린다:

  T3-A  국면 → **자산별 절대 μ 뷰** → BL/EP           ← ★현행(baseline)★
  T3-B  국면 → **자산군 상대 뷰**   → BL/EP
  T3-C  국면 → **팩터 뷰** → 팩터 노출 → 최적화기

★프로덕션 뷰 스키마를 바꾸지 않는다.★ `build_user_views` 와 `entropy_views._pickers`
는 둘 다 `row[idx[a]] = 1/len(assets)` 로 **양수 등가중** 행만 만들고 방향은 스칼라라,
**상대(롱숏) 뷰를 표현할 수 없다.** 어느 아키텍처가 이기는지 모르는 채로 스키마를
넓히지 않기 위해, 여기서는 P/Q/Ω 를 직접 만들어 `bl_posterior` 를 부른다.

★그리고 그 제약 자체가 결과다★ — EP(`ep_posterior_mu`)는 뷰를 부등식 제약으로
푸는데 그 입력도 같은 picker 를 쓴다. 즉 **T3-B/C 는 현재 EP 로 표현 불가**이고,
이것은 실험의 한계가 아니라 **아키텍처 선택에 영향을 주는 사실**이다.

사용:
    python3 scripts/t3_transmission.py
    python3 scripts/t3_transmission.py --report FILE
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.engine.allocation_backtest import (  # noqa: E402
    _month_of,
    _rebalance_indices,
    _truncated_points,
)
from src.engine.allocation_studio import (  # noqa: E402
    DELTA_DEFAULT,
    TAU_DEFAULT,
    bl_posterior,
)
from src.engine.conditional_market import (  # noqa: E402
    conditional_moments,
    implied_confidence,
    regime_by_month_from_path,
    regime_mixture_moments,
    resolve_shrinkage_lambda,
    view_omega_terms,
)
from src.engine.regime_probability import from_posterior_mean_path  # noqa: E402
from src.engine.regime_transitions import (  # noqa: E402
    REGIMES,
    count_transitions,
    transition_posterior,
)

ARCHS = ("T3-A", "T3-B", "T3-C")
COSTS = (0.0, 10.0, 30.0)
RF = 0.035

# ── 합성 패널 ────────────────────────────────────────────────────────────────
# ★국면이 자산군을 가르도록 만든다★ 앞선 패널은 국면이 **공통인자 하나**만 바꿔서
# 자산군 간 차이가 없었고, 그러면 어떤 전달 형태를 써도 같은 결론이 나온다. 여기서는
# 국면이 (i) 공통인자 드리프트·변동성 **그리고** (ii) 두 자산군의 상대 성과를 함께
# 바꾼다 — 실제 매크로 국면이 하는 일에 가깝고, 세 아키텍처를 구분할 수 있다.
CLASSES = {"EQ": [0, 1, 2], "FI": [3, 4, 5]}
_PROF = {  # 국면: (공통 드리프트, 공통 변동성, EQ 틸트, FI 틸트, 특이 변동성)
    "Goldilocks":   (0.00075, 0.010, +0.00040, -0.00020, 0.0035),
    "Reflation":    (0.00035, 0.013, +0.00025, -0.00035, 0.0045),
    "Stagflation":  (-0.00070, 0.017, -0.00055, +0.00030, 0.0060),
    "Disinflation": (0.00020, 0.010, -0.00015, +0.00045, 0.0040),
}
_P_TRUE = np.array([[0.75, 0.10, 0.05, 0.10],
                    [0.15, 0.65, 0.15, 0.05],
                    [0.10, 0.15, 0.65, 0.10],
                    [0.15, 0.05, 0.10, 0.70]])


def build_panel(months: int = 84, seed: int = 20260825):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2018-01-02", periods=months * 21, freq="C")
    names = [f"EQ{i}" for i in range(3)] + [f"FI{i}" for i in range(3)]
    beta = np.array([1.25, 1.00, 0.80, 0.35, 0.25, 0.15])   # 자산군별 공통인자 노출
    seen: list[str] = []
    for ts in idx:
        mo = ts.strftime("%Y-%m")
        if mo not in seen:
            seen.append(mo)
    labels, cur = [], 0
    for _ in seen:
        labels.append(REGIMES[cur])
        cur = int(rng.choice(4, p=_P_TRUE[cur]))
    by_month = dict(zip(seen, labels, strict=True))

    rows = []
    for ts in idx:
        mu_f, sd_f, eq_t, fi_t, iv = _PROF[by_month[ts.strftime("%Y-%m")]]
        f = rng.normal(mu_f, sd_f)
        tilt = np.array([eq_t] * 3 + [fi_t] * 3)
        rows.append(f * beta + tilt + rng.normal(0.0, iv, 6))
    points = [{"t": m, "growth": 0.0, "inflation": 0.0, "regime": by_month[m]}
              for m in seen]
    return names, np.array(rows), list(idx), points, beta


# ── 전달 아키텍처: 조건부 μ/Σ → (P, Q, Ω) ───────────────────────────────────
def _omega(P: np.ndarray, tau_sigma: np.ndarray, conf: float) -> np.ndarray:
    """`build_user_views` 와 **같은 규약** — 규약을 바꿔 이기는 실험이 되지 않게."""
    scale = (100.0 - conf) / max(conf, 1.0)
    base = np.maximum(np.diag(P @ tau_sigma @ P.T), 1e-10)
    return np.diag(base * max(scale, 1e-4)) + np.eye(P.shape[0]) * 1e-10


def views_absolute(mu, sigma, names, beta, conf, tau):
    """★T3-A (현행)★ 자산마다 절대 뷰 — P 행이 `e_i`, 뷰 N개."""
    n = len(names)
    return np.eye(n), np.asarray(mu, float), _omega(np.eye(n), tau * sigma, conf)


def views_relative_class(mu, sigma, names, beta, conf, tau):
    """★T3-B★ 자산군 **상대** 뷰 — P 행이 `(+1/n_EQ … −1/n_FI)`, 뷰 1개.

    공통 수준(타이밍 성분)은 상대 뷰에서 **상쇄**되므로, 이 아키텍처는 국면이
    말하는 **자산군 간 차이만** 전달하고 수준 추정잡음은 흘려보내지 않는다.
    """
    n = len(names)
    idx = {nm: i for i, nm in enumerate(names)}
    eq = [idx[nm] for nm in names if nm.startswith("EQ")]
    fi = [idx[nm] for nm in names if nm.startswith("FI")]
    row = np.zeros(n)
    row[eq] = 1.0 / len(eq)
    row[fi] = -1.0 / len(fi)
    P = row.reshape(1, n)
    return P, np.array([float(row @ np.asarray(mu, float))]), _omega(P, tau * sigma, conf)


def views_factor(mu, sigma, names, beta, conf, tau):
    """★T3-C★ **팩터 뷰** → 노출로 자산에 매핑 — P 행이 정규화된 `βᵀ`, 뷰 1개.

    국면 신호가 공통인자의 평균을 바꾸는 것이라면, 그 주장을 **그 인자 위에서**
    해야 한다. P 행이 β 포트폴리오이므로 뷰는 "β 포트폴리오가 z% 낸다" 가 된다 —
    타이밍 주장을 타이밍 형태로 전달한다.
    """
    n = len(names)
    b = np.asarray(beta, float)
    row = b / max(float(np.abs(b).sum()), 1e-12)
    P = row.reshape(1, n)
    return P, np.array([float(row @ np.asarray(mu, float))]), _omega(P, tau * sigma, conf)


_BUILDERS = {"T3-A": views_absolute, "T3-B": views_relative_class,
             "T3-C": views_factor}


def _equilibrium(sigma: np.ndarray, w_mkt: np.ndarray, delta: float) -> np.ndarray:
    """역최적화 균형 기대수익 `Π = δ Σ w_mkt` — BL 의 사전분포."""
    return delta * sigma @ w_mkt


def _min_var_long_only(S: np.ndarray, mu: np.ndarray, delta: float) -> np.ndarray:
    """평균-분산 롱온리 (합=1). `allocation_studio` 와 같은 SLSQP 규약."""
    from scipy.optimize import minimize
    n = len(mu)
    r = minimize(lambda w: -(w @ mu - 0.5 * delta * w @ S @ w),
                 np.ones(n) / n, method="SLSQP", bounds=[(0.0, 1.0)] * n,
                 constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1.0}])
    w = np.asarray(r.x, float)
    return w / max(w.sum(), 1e-12)


# ── 실행 ────────────────────────────────────────────────────────────────────
def run_arch(arch: str, names, R, dates, points, beta, *, min_train=252,
             delta=DELTA_DEFAULT, tau=TAU_DEFAULT, conf_override=None):
    """한 아키텍처의 walk-forward — 매 리밸런싱에서 절단 경로만 본다."""
    rb = _rebalance_indices(list(dates), "M", min_train)
    n = len(names)
    w_mkt = np.ones(n) / n
    rec = {"w": [], "view_disp": [], "post_disp": [], "conf": [],
           "months": [], "applied": 0, "timing_view": [], "fwd_factor": []}
    for k, t in enumerate(rb):
        R_win = R[:t]
        df = pd.DataFrame(R_win, index=pd.DatetimeIndex(dates[:t]), columns=names)
        pts = _truncated_points(points, _month_of(dates[t]))
        if len(pts) < 2:
            rec["w"].append(None); rec["months"].append(_month_of(dates[t])); continue
        by_month, _ = regime_by_month_from_path(pts)
        cur = pts[-1]["regime"]
        rows = transition_posterior(count_transitions(pts))
        probs, Pm = from_posterior_mean_path(rows, cur, 1, list(REGIMES),
                                             mode="backtest")
        cond = regime_mixture_moments(df, by_month, [p.probs for p in probs], Pm,
                                      list(REGIMES), h_hold=1)
        if not cond.get("available"):
            cond = conditional_moments(df, by_month, cur)
        if not cond.get("available"):
            rec["w"].append(None); rec["months"].append(_month_of(dates[t])); continue

        mu = np.asarray(cond["mu"], float)
        sigma = np.asarray(cond["sigma"], float)
        # ★신뢰도는 분해 Ω 로 — 세 아키텍처에 **같은 규칙**을 적용한다★
        A, W, h = cond.get("A_h"), cond.get("W_h"), int(cond.get("h_hold") or 1)
        if A is not None and W is not None:
            ann = 12.0 / h
            rg = np.maximum(np.diag(np.asarray(A, float) * ann), 0.0)
            wi = np.maximum(np.diag(np.asarray(W, float) * ann), 0.0)
        else:
            rg, wi = np.zeros(n), np.maximum(np.diag(sigma), 0.0)
        months = cond.get("n_months_by_regime") or {}
        nm = max(1, min(months.values(), default=int(cond.get("n_months") or 1)))
        terms = view_omega_terms(regime_diag=rg, sigma_within_diag=wi, n_months=nm)
        conf = float(np.min(implied_confidence(terms["omega_diag"],
                                               np.maximum(np.diag(sigma), 1e-12))))
        if conf_override is not None:
            conf = float(conf_override)
        resolve_shrinkage_lambda(cond)              # 계약 확인(스칼라여야 한다)

        P, Q, Om = _BUILDERS[arch](mu, sigma, names, beta, conf, tau)
        pi_eq = _equilibrium(sigma, w_mkt, delta)
        mu_post = bl_posterior(pi_eq, sigma, P, Q, Om, tau=tau)
        w = _min_var_long_only(sigma, mu_post, delta)

        rec["w"].append(w)
        rec["months"].append(_month_of(dates[t]))
        rec["view_disp"].append(float(np.max(Q) - np.min(Q)) if len(Q) > 1
                                else float(abs(Q[0])))
        rec["post_disp"].append(float(mu_post.max() - mu_post.min()))
        rec["conf"].append(conf)
        rec["applied"] += 1
        # 타이밍 지표: β 포트폴리오에 대한 뷰(사후 기준) vs 실현 β 수익
        rec["timing_view"].append(float((beta / np.abs(beta).sum()) @ mu_post))
        nxt = [i for i in rb if i > t]
        e = nxt[0] if nxt else len(R)
        rec["fwd_factor"].append(float((beta / np.abs(beta).sum())
                                       @ R[t:e].sum(axis=0)) if e > t else np.nan)
    return rec, rb


def simulate(rec, rb, R, dates, cost_bps: float):
    """비중 경로 → 자산곡선·회전율 (walk_forward 와 같은 규약: 편도 회전율·표류)."""
    cost = cost_bps / 1e4
    n = R.shape[1]
    w = np.zeros(n)
    eq, daily, tos, rb_month = 1.0, [], [], []
    at = {t: i for i, t in enumerate(rb)}
    equity_curve = []
    for t in range(rb[0], R.shape[0]):
        if t in at:
            w_new = rec["w"][at[t]]
            if w_new is not None:
                to = 0.5 * float(np.abs(w_new - w).sum())
                eq *= (1.0 - to * cost)
                w = w_new
                tos.append(to)
                rb_month.append(_month_of(dates[t]))
        pr = float(w @ R[t])
        eq *= (1.0 + pr)
        daily.append(pr)
        equity_curve.append(eq)
    return np.array(daily), np.array(equity_curve), np.array(tos), rb_month


def metrics(daily, curve, tos, rb_month, by_month, delta=DELTA_DEFAULT):
    if daily.size < 3:
        return {}
    ann = daily.mean() * 252
    vol = daily.std(ddof=1) * math.sqrt(252)
    dn = daily[daily < 0]
    dvol = dn.std(ddof=1) * math.sqrt(252) if dn.size > 2 else float("nan")
    peak = np.maximum.accumulate(curve)
    mdd = float(((curve - peak) / peak).min())
    q = float(np.percentile(daily, 5))
    cvar = float(daily[daily <= q].mean()) if (daily <= q).any() else float("nan")
    ce = float(ann - (delta / 2.0) * daily.var(ddof=1) * 252)
    # 거짓 트리거: 회전율이 중앙값 초과인데 실현 국면이 직전과 같은 비율
    thr = float(np.median(tos)) if tos.size else 0.0
    ntr = nf = 0
    prev = None
    for to, m in zip(tos, rb_month, strict=True):
        reg = by_month.get(m)
        if to > thr:
            ntr += 1
            if prev is not None and reg == prev:
                nf += 1
        prev = reg
    return {"return_pct": round(ann * 100, 2), "vol_pct": round(vol * 100, 2),
            "sharpe": round((ann - RF) / vol, 3) if vol > 0 else None,
            "sortino": round((ann - RF) / dvol, 3) if dvol == dvol and dvol > 0 else None,
            "mdd_pct": round(mdd * 100, 2), "cvar_pct": round(cvar * 100, 3),
            "turnover_pct": round(float(tos.mean()) * 100, 2) if tos.size else 0.0,
            "n_rebalances": int(tos.size), "ce": round(ce, 6),
            "false_trigger": round(nf / ntr, 4) if ntr else None}


def w_l1(rec):
    ws = [w for w in rec["w"] if w is not None]
    d = [float(np.abs(b - a).sum()) for a, b in zip(ws, ws[1:], strict=False)]
    return (round(float(np.mean(d)), 4), round(float(np.median(d)), 4)) if d else (None, None)


def timing_ic(rec):
    """★타이밍 IC★ — 단면 IC 가 아니라 **β 포트폴리오 뷰 vs 실현 β 수익**."""
    v = np.array(rec["timing_view"], float)
    f = np.array(rec["fwd_factor"], float)
    ok = np.isfinite(v) & np.isfinite(f)
    if ok.sum() < 10 or np.std(v[ok]) < 1e-15:
        return {"ic": None, "t": None, "hit": None, "n": int(ok.sum())}
    ic = float(np.corrcoef(v[ok], f[ok])[0, 1])
    n = int(ok.sum())
    t = ic * math.sqrt(max(n - 2, 1) / max(1 - ic * ic, 1e-12))
    return {"ic": round(ic, 4), "t": round(t, 2),
            "hit": round(float(np.mean(np.sign(v[ok]) == np.sign(f[ok]))), 4), "n": n}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default=None)
    ap.add_argument("--months", type=int, default=84)
    # ★신뢰도를 고정해 아키텍처만 비교할 수 있게 한다★ 분해 Ω 는 이 패널에서
    # conf≈1 까지 내려가 뷰가 거의 무시되는데, 그러면 "전달 형태가 중요한가" 를
    # 묻는 실험이 **뷰가 안 먹는 구간에서** 돌게 된다. 신뢰도를 올려가며 세 형태가
    # 어떻게 갈라지는지 보는 것이 이 연구의 핵심이다.
    ap.add_argument("--conf", type=float, default=None)
    args = ap.parse_args()

    names, R, dates, points, beta = build_panel(months=args.months)
    by_month = {p["t"]: p["regime"] for p in points}
    out: dict[str, dict] = {}
    for arch in ARCHS:
        rec, rb = run_arch(arch, names, R, dates, points, beta,
                           conf_override=args.conf)
        mean_l1, med_l1 = w_l1(rec)
        cells = {}
        for c in COSTS:
            d, curve, tos, rbm = simulate(rec, rb, R, dates, c)
            cells[c] = metrics(d, curve, tos, rbm, by_month)
        out[arch] = {
            "view_disp": round(float(np.mean(rec["view_disp"])), 4),
            "post_disp": round(float(np.mean(rec["post_disp"])), 4),
            "conf": round(float(np.mean(rec["conf"])), 3),
            "w_l1_mean": mean_l1, "w_l1_median": med_l1,
            "applied": rec["applied"], "n_views": {"T3-A": len(names)}.get(arch, 1),
            "timing": timing_ic(rec), "cells": cells,
        }

    hdr = (f"{'arch':>5} {'뷰수':>4} {'뷰산포':>7} {'사후산포':>8} {'conf':>6} "
           f"{'Δw L1':>7} {'중앙':>7} | {'bp':>3} {'ret%':>7} {'vol%':>6} "
           f"{'sharpe':>6} {'sortino':>7} {'mdd%':>7} {'cvar%':>6} {'turn%':>6} "
           f"{'nrb':>4} {'CE':>8} {'FT':>6}")
    print(hdr)
    print("-" * len(hdr))
    for a in ARCHS:
        o = out[a]
        for c in COSTS:
            m = o["cells"][c]
            print(f"{a:>5} {o['n_views']:>4} {o['view_disp']:>7.4f} "
                  f"{o['post_disp']:>8.4f} {o['conf']:>6.2f} {o['w_l1_mean']:>7.4f} "
                  f"{o['w_l1_median']:>7.4f} | {c:>3.0f} {m['return_pct']:>7} "
                  f"{m['vol_pct']:>6} {m['sharpe']:>6} {str(m['sortino']):>7} "
                  f"{m['mdd_pct']:>7} {m['cvar_pct']:>6} {m['turnover_pct']:>6} "
                  f"{m['n_rebalances']:>4} {m['ce']:>8.4f} {str(m['false_trigger']):>6}")
    print()
    print("타이밍 평가 (★단면 IC 가 아니다★ — β 포트폴리오 뷰 vs 실현 β 수익)")
    for a in ARCHS:
        t = out[a]["timing"]
        print(f"  {a}: IC {t['ic']}  t={t['t']}  방향적중 {t['hit']}  n={t['n']}")
    print()
    print("ΔCE (T3-A 대비, 비용별)")
    for a in ("T3-B", "T3-C"):
        for c in COSTS:
            d = out[a]["cells"][c]["ce"] - out["T3-A"]["cells"][c]["ce"]
            print(f"  {a} vs T3-A @{c:>4.0f}bp : {d:+.6f}")
    from src.engine.capability import probe_all
    fs = probe_all().get("frontier_sample", {})
    print()
    print("★증거 등급★", json.dumps(fs.get("detail") or fs.get("reason") or {},
                                 ensure_ascii=False))
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(json.dumps(out, ensure_ascii=False, indent=2, default=str))
        print(f"\nJSON → {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
