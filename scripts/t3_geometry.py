"""Phase 3 — 표현 **기하** 단독 분리 (행합 1 vs 행합 0)
==============================================================================
계획: 매크로 → 포트폴리오 정보 계약 패스 Phase 3.
★증거 등급: `synthetic_mechanism` · `real_share = 0.0`.★

## 무엇을 묻나

`0e655c7` 은 B(자산군 상대)와 C-상대(팩터 상대)가 **같이** 이겼다고 보고했고,
그 둘의 공통점은 축이 아니라 **행합 0** 이었다. 그러면 질문은 하나로 좁혀진다:

    ★행합 0 **자체**가 그 우위를 설명하는가?★

## ★먼저 인정할 교란 — Ω 는 행에서 나온다★

`build_user_views` 규약에서 Ω 의 base 는 `diag(P τΣ Pᵀ)` 다. **행을 바꾸면 Ω 가
따라 바뀐다.** 그리고 스프레드 포트폴리오는 롱 포트폴리오보다 분산이 작으므로
행합 0 행의 Ω 가 **더 작다** = 암묵적으로 **더 확신한다**.

즉 "표현만 바꿨다" 는 엄밀히 거짓이다. 기하를 바꾸면 신뢰도가 딸려 온다.
★그래서 팔이 셋이다.★

| 팔 | P 행 | 행합 | Ω |
|---|---|---|---|
| **A** | `β` 정규화 | ≈ 1 | 자기 행에서 |
| **R** | `β−β̄` 정규화 | = 0 | 자기 행에서 |
| ★**R-Ωmatched**★ | `β−β̄` 정규화 | = 0 | ★**A 의 Ω 를 강제**★ |

읽는 법:

    R ≈ R-Ωmatched   → 우위의 원천은 **기하**
    R-Ωmatched ≈ A   → 우위의 원천은 **암묵 신뢰도**(Ω 축소)
    그 사이           → 둘 다 기여 (분해 비율을 적는다)

★이 배치가 "행합 0 이 본질인가 구현 artifact 인가" 를 답할 수 있는 유일한 형태다.★

## 통제되는 것 (셋이 **완전히** 같다)

국면 경로 · 기대수익 신호(`μ`) · 공분산 · 최적화기 · 거래비용 · 신뢰도(conf) ·
리밸런싱 주기 · 균형 사전분포 `Π` · 뷰 **개수**(1개). ★다른 것은 행 기하뿐이다.★

뷰 개수를 1로 맞춘 것이 중요하다 — 직전 연구의 A(자산별 절대)는 뷰가 6개라
기하와 개수가 뭉쳐 있었다. 여기서는 같은 β 신호를 **한 행**으로만 보낸다.

사용:
    python3 scripts/t3_geometry.py --conf 25
    python3 scripts/t3_geometry.py --conf 10 --report FILE
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

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
    regime_by_month_from_path,
    regime_mixture_moments,
)
from src.engine.regime_probability import from_posterior_mean_path  # noqa: E402
from src.engine.regime_transitions import (  # noqa: E402
    REGIMES,
    count_transitions,
    transition_posterior,
)


def _load_t3():
    """★기하 실험은 전달 실험과 **같은 패널·같은 부품**을 써야 한다★

    패널을 다시 만들면 "기하만 다르다" 가 깨진다. `t3_transmission` 을 그대로
    적재해 `build_panel` · `pq_from_views` · `simulate` · `metrics` 를 재사용한다.
    """
    spec = importlib.util.spec_from_file_location(
        "t3_transmission", os.path.join(_ROOT, "scripts", "t3_transmission.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


t3 = _load_t3()

ARMS = ("A-level", "R-relative", "R-omega-matched")
COSTS = t3.COSTS


def geometry_views(arm: str, mu, names, beta) -> list[dict]:
    """팔 → 뷰 딕셔너리. ★A 와 R 은 같은 β 신호를 다른 기하로 말한다★"""
    if arm == "A-level":
        return t3.views_factor_level(mu, names, beta)
    return t3.views_factor_relative(mu, names, beta)      # R · R-Ωmatched 동일


def run_arm(arm: str, names, R, dates, points, beta, *, conf: float,
            min_train: int = 252, delta=DELTA_DEFAULT, tau=TAU_DEFAULT):
    """한 팔의 walk-forward. `t3_transmission.run_arch` 와 같은 절단 규약."""
    rb = _rebalance_indices(list(dates), "M", min_train)
    n = len(names)
    w_mkt = np.ones(n) / n
    rec: dict = {"w": [], "months": [], "arm": arm, "applied": 0,
                 "row_sum": [], "row_l1": [], "q": [], "omega": [],
                 "post_prior_l1": [], "post_prior_ratio": [], "omega_ratio": [],
                 "evidence_grade": t3.EVIDENCE_SYNTHETIC}

    for t in rb:
        R_win = R[:t]
        df = pd.DataFrame(R_win, index=pd.DatetimeIndex(dates[:t]), columns=names)
        pts = _truncated_points(points, _month_of(dates[t]))
        if len(pts) < 2:
            rec["w"].append(None); rec["months"].append(_month_of(dates[t])); continue
        by_month, _ = regime_by_month_from_path(pts)
        cur = pts[-1]["regime"]
        probs, Pm = from_posterior_mean_path(
            transition_posterior(count_transitions(pts)), cur, 1, list(REGIMES),
            mode="backtest")
        cond = regime_mixture_moments(df, by_month, [p.probs for p in probs], Pm,
                                      list(REGIMES), h_hold=1)
        if not cond.get("available"):
            cond = conditional_moments(df, by_month, cur)
        if not cond.get("available"):
            rec["w"].append(None); rec["months"].append(_month_of(dates[t])); continue

        mu = np.asarray(cond["mu"], float)
        sigma = np.asarray(cond["sigma"], float)

        views = geometry_views(arm, mu, names, beta)
        P, Q, Om, _sk = t3.pq_from_views(views, names, sigma, conf, tau)
        if P is None:
            rec["w"].append(None); rec["months"].append(_month_of(dates[t])); continue

        # ── ★Ω 매칭★ — 기하는 R, 신뢰도는 A 의 것을 강제한다 ─────────────────
        # 이것이 이 스크립트의 유일한 개입이고, 그 개입이 곧 측정하려는 분해다.
        om_own = float(Om[0, 0])
        if arm == "R-omega-matched":
            P_a, _Q_a, Om_a, _ = t3.pq_from_views(
                geometry_views("A-level", mu, names, beta), names, sigma, conf, tau)
            assert P_a is not None
            Om = np.array(Om_a, copy=True)
        rec["omega_ratio"].append(om_own / max(float(Om[0, 0]), 1e-300))

        pi_eq = delta * sigma @ w_mkt
        mu_post = bl_posterior(pi_eq, sigma, P, Q, Om, tau=tau)
        w = t3._min_var_long_only(sigma, mu_post, delta)

        rec["w"].append(w)
        rec["months"].append(_month_of(dates[t]))
        rec["applied"] += 1
        rec["row_sum"].append(float(P[0].sum()))
        rec["row_l1"].append(float(np.abs(P[0]).sum()))
        rec["q"].append(float(Q[0]))
        rec["omega"].append(float(Om[0, 0]))
        d = mu_post - pi_eq
        rec["post_prior_l1"].append(float(np.abs(d).sum()))
        rec["post_prior_ratio"].append(
            float(np.abs(d).sum() / max(np.abs(pi_eq).sum(), 1e-12)))
    return rec, rb


def _concentration(rec) -> float:
    """허핀달 — 비중 집중도. 1/n 이 하한(완전 분산), 1 이 상한(한 종목)."""
    ws = [w for w in rec["w"] if w is not None]
    return float(np.mean([float(np.square(w).sum()) for w in ws])) if ws else float("nan")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--conf", type=float, default=25.0)
    ap.add_argument("--months", type=int, default=84)
    ap.add_argument("--report", default=None)
    args = ap.parse_args()

    names, R, dates, points, beta = t3.build_panel(months=args.months)
    by_month = {p["t"]: p["regime"] for p in points}
    out: dict[str, dict] = {}
    for arm in ARMS:
        rec, rb = run_arm(arm, names, R, dates, points, beta, conf=args.conf)
        cells = {}
        for c in COSTS:
            d, curve, tos, rbm = t3.simulate(rec, rb, R, dates, c)
            cells[c] = t3.metrics(d, curve, tos, rbm, by_month)
        mean_l1, med_l1 = t3.w_l1(rec)
        out[arm] = {
            "arm": arm,
            "row_sum": round(float(np.mean(rec["row_sum"])), 12),
            "row_l1": round(float(np.mean(rec["row_l1"])), 6),
            "q_mean_pct": round(float(np.mean(rec["q"])) * 100, 4),
            "q_abs_mean_pct": round(float(np.mean(np.abs(rec["q"]))) * 100, 4),
            "omega_mean": float(np.mean(rec["omega"])),
            "omega_ratio_to_own": round(float(np.mean(rec["omega_ratio"])), 6),
            "post_prior_l1": round(float(np.mean(rec["post_prior_l1"])), 6),
            "post_prior_ratio": round(float(np.mean(rec["post_prior_ratio"])), 6),
            "w_l1_mean": mean_l1, "w_l1_median": med_l1,
            "dispersion": t3.w_dispersion(rec),
            "concentration": round(_concentration(rec), 6),
            "applied": rec["applied"], "cells": cells,
            "evidence_grade": t3.EVIDENCE_SYNTHETIC,
        }

    print(f"Phase 3 — 표현 기하 단독 분리 (conf={args.conf}, "
          f"{args.months}개월, 뷰 1개 고정)")
    print()
    print("① 정보 표현 (★데이터가 아니라 구조★)")
    h = f"{'arm':>16} {'행합':>10} {'행 L1':>7} {'Q 평균%':>9} {'|Q| 평균%':>9} {'Ω':>12} {'Ω/자기Ω':>9}"
    print(h); print("-" * len(h))
    for a in ARMS:
        o = out[a]
        print(f"{a:>16} {o['row_sum']:>10.2e} {o['row_l1']:>7.4f} "
              f"{o['q_mean_pct']:>9.4f} {o['q_abs_mean_pct']:>9.4f} "
              f"{o['omega_mean']:>12.3e} {o['omega_ratio_to_own']:>9.4f}")

    print()
    print("② 전달 (사후↔사전 거리 · 비중 이동)")
    h = f"{'arm':>16} {'사후-사전L1':>12} {'사후/사전비':>11} {'Δw L1':>8} {'중앙':>8} {'EQ범위':>8} {'회전율%':>8}"
    print(h); print("-" * len(h))
    for a in ARMS:
        o = out[a]
        print(f"{a:>16} {o['post_prior_l1']:>12.6f} {o['post_prior_ratio']:>11.6f} "
              f"{o['w_l1_mean']:>8.4f} {o['w_l1_median']:>8.4f} "
              f"{o['dispersion']['eq_range']:>8.4f} "
              f"{o['cells'][0.0]['turnover_pct']:>8.2f}")

    print()
    print("③ 포트폴리오 기제 (★경제적 성과가 아니다★)")
    h = f"{'arm':>16} {'bp':>3} {'ret%':>7} {'vol%':>6} {'sharpe':>7} {'mdd%':>8} {'cvar%':>7} {'집중도':>7} {'CE':>9} {'nrb':>4}"
    print(h); print("-" * len(h))
    for a in ARMS:
        o = out[a]
        for c in COSTS:
            m = o["cells"][c]
            print(f"{a:>16} {c:>3.0f} {m['return_pct']:>7} {m['vol_pct']:>6} "
                  f"{str(m['sharpe']):>7} {m['mdd_pct']:>8} {m['cvar_pct']:>7} "
                  f"{o['concentration']:>7.4f} {m['ce']:>9.5f} {m['n_rebalances']:>4}")

    # ── ★분해 — 기하 vs 암묵 신뢰도★ ────────────────────────────────────────
    print()
    print("★분해★ R 의 우위는 기하인가, Ω 축소(암묵 신뢰도)인가")
    for c in COSTS:
        ce = {a: out[a]["cells"][c]["ce"] for a in ARMS}
        total = ce["R-relative"] - ce["A-level"]
        geom = ce["R-omega-matched"] - ce["A-level"]     # Ω 를 A 로 묶은 채 기하만
        conf_part = ce["R-relative"] - ce["R-omega-matched"]
        share = (geom / total * 100.0) if abs(total) > 1e-12 else float("nan")
        print(f"  @{c:>4.0f}bp  전체 {total:+.6f} = 기하 {geom:+.6f} + "
              f"Ω축소 {conf_part:+.6f}   (기하 몫 {share:.1f}%)")
    print()
    print("  읽는 법: 기하 몫이 100%에 가까우면 ★행합 0 자체★가 원인이고,")
    print("           0%에 가까우면 원인은 ★Ω 가 작아진 것★(암묵적 확신 상승)이다.")

    print()
    print(f"★증거 등급★ {t3.EVIDENCE_SYNTHETIC} · real_share = 0.0 — "
          f"기제 확인이지 경제적 가치의 증거가 아니다.")

    if args.report:
        payload = {"evidence_grade": t3.EVIDENCE_SYNTHETIC, "real_share": 0.0,
                   "conf": args.conf, "arms": out}
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        print(f"\nJSON → {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
