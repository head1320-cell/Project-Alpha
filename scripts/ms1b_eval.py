"""MS1-b0 평가 하네스 — B0/B1/N × BL/EP × 0/10/30bp = 18회 (기제 검증)
==============================================================================
계획: `docs/plans/2026-08-25-macro-vnext-plan.md` §1.13

★이 스크립트가 내는 것은 "경제적 증거" 가 아니다.★
`probe_all()['frontier_sample']['real_share']` 가 0인 동안 — 즉 61개 매크로 계열이
전부 mock 인 동안 — 여기서 나오는 표는 **배선이 도는가**에 대한 답이지 **모델이
맞는가**에 대한 답이 아니다. 승격 판정은 실계열이 붙은 뒤 같은 명령을 다시 돌려서
한다(감사 §4.5 · 계획 §8 승격기준 6·8).

그래서 출력의 제목과 결론에 항상 `real_share` 를 함께 찍는다 — 표만 잘라서
"이겼다" 로 읽히는 것을 막는 유일한 방법이다.

사용:
    python3 scripts/ms1b_eval.py                 # 표만
    python3 scripts/ms1b_eval.py --report FILE   # 마크다운 보고서까지
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

from src.engine.allocation_backtest import walk_forward  # noqa: E402
from src.engine.allocation_studio import DELTA_DEFAULT  # noqa: E402

ARMS = ("B0", "B1", "N")
MODELS = ("bl", "ep")
COSTS = (0.0, 10.0, 30.0)
REGIMES4 = ["Goldilocks", "Reflation", "Stagflation", "Disinflation"]

_ARM_REGIME = {"B0": None,
               "B1": {"weighting": "hard"},
               "N": {"weighting": "probabilistic", "h_hold": 1}}


# ── 합성 패널 ────────────────────────────────────────────────────────────────
def build_panel(months: int = 84, n_assets: int = 4, seed: int = 20260825):
    """국면이 실제로 수익을 가르는 통제 패널 + 그 국면 경로.

    ★mock 시세를 그대로 쓰지 않는 이유★ 이 컨테이너의 mock 은 종목별로 독립
    생성돼 무상관·등분산이고, 그러면 Ledoit-Wolf 목표가 정확히 맞아 λ→1.0 이 된다.
    Σ 가 스케일 단위행렬이면 스케일 불변 모델의 비중은 국면과 무관하게 같아지므로
    **어떤 팔도 서로 달라질 수 없다.** 배선을 우회하는 것이 아니라, 배선이 구분할
    수 있는 데이터를 준다 — 그리고 그렇기 때문에 결과가 기제 검증에 머문다.
    """
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2018-01-02", periods=months * 21, freq="C")
    names = [f"A{i}" for i in range(n_assets)]
    beta = np.linspace(1.3, 0.5, n_assets)

    seen: list[str] = []
    for ts in idx:
        mo = ts.strftime("%Y-%m")
        if mo not in seen:
            seen.append(mo)

    # 국면은 지속성 있는 마르코프 사슬로 만든다(교대보다 현실적이고 전이가 세어진다).
    P = np.array([[0.75, 0.10, 0.05, 0.10],
                  [0.15, 0.65, 0.15, 0.05],
                  [0.10, 0.15, 0.65, 0.10],
                  [0.15, 0.05, 0.10, 0.70]])
    labels, cur = [], 0
    for _ in seen:
        labels.append(REGIMES4[cur])
        cur = int(rng.choice(4, p=P[cur]))
    by_month = dict(zip(seen, labels, strict=True))

    # 국면별 (드리프트, 공통인자 변동성, 특이 변동성)
    prof = {"Goldilocks":   (0.0008, 0.011, 0.0035),
            "Reflation":    (0.0004, 0.013, 0.0045),
            "Stagflation":  (-0.0007, 0.017, 0.0060),
            "Disinflation": (0.0002, 0.010, 0.0040)}
    rows = []
    for ts in idx:
        mu, fv, iv = prof[by_month[ts.strftime("%Y-%m")]]
        f = rng.normal(mu, fv)
        rows.append(f * beta + rng.normal(0.0, iv, n_assets))

    points = [{"t": mo, "growth": 0.0, "inflation": 0.0, "regime": by_month[mo]}
              for mo in seen]
    return names, np.array(rows), list(idx), points


# ── 지표 ────────────────────────────────────────────────────────────────────
def daily_returns_from_equity(eq: list[float]) -> np.ndarray:
    e = np.asarray(eq, dtype=float)
    return np.diff(e) / e[:-1] if e.size > 1 else np.array([])


def certainty_equivalent(r: np.ndarray, delta: float = DELTA_DEFAULT) -> float:
    """실현 확실성등가 (연율) — ★사후 Σ 를 쓰지 않는다★.

    최적화에 쓴 공분산으로 효용을 재면 자기 채점이 된다. 실현 OOS 수익률 계열에서
    직접 잰다: `CE = E[r] − (δ/2)·Var(r)`, 둘 다 연율.
    """
    if r.size < 2:
        return float("nan")
    return float(r.mean() * 252.0 - (delta / 2.0) * r.var(ddof=1) * 252.0)


def forecast_concentration(audit: dict) -> dict:
    """예측 집중도 — 국면 분포가 얼마나 날카로운가.

    ★적중률만 보면 "다 담아서 맞혔다" 를 구분할 수 없다★ 그래서 유효 국면 수
    (퍼플렉서티)를 함께 낸다. 하드 라벨은 1.0, 완전 균등이면 국면 수와 같다.
    """
    sharp, perp = [], []
    for d in audit.get("detail", []):
        pi = d.get("pi_bar")
        if not pi:
            continue
        vals = [float(v) for v in pi.values() if v and v > 0]
        if len(vals) < 2:
            sharp.append(1.0)
            perp.append(1.0)
            continue
        tot = sum(vals)
        h = -sum((v / tot) * math.log(v / tot) for v in vals)
        sharp.append(1.0 - h / math.log(len(vals)))
        perp.append(math.exp(h))
    if not sharp:
        return {"sharpness": None, "perplexity": None, "n": 0}
    return {"sharpness": round(float(np.mean(sharp)), 4),
            "perplexity": round(float(np.mean(perp)), 4), "n": len(sharp)}


def false_trigger_rate(out: dict, by_month: dict[str, str]) -> dict:
    """거짓 트리거율 — 비중을 크게 움직였는데 **국면은 그대로**였던 비율.

    ★정의를 좁게 잡는다★ "회전율이 중앙값보다 컸다" 를 트리거로 보고, 그 시점의
    실현 국면이 직전 리밸런싱과 같으면 거짓으로 센다. 국면이 안 바뀌었는데 크게
    움직였다면 그 거래는 국면 신호가 아니라 잡음이 시킨 것이다.
    """
    rbs = out.get("rebalances") or []
    if len(rbs) < 4:
        return {"rate": None, "n_triggers": 0, "n_false": 0}
    tos = np.array([r["turnover_pct"] for r in rbs], dtype=float)
    thr = float(np.median(tos))
    n_trig = n_false = 0
    prev_reg = None
    for r, to in zip(rbs, tos, strict=True):
        reg = by_month.get(str(r["date"])[:7])
        if to > thr:
            n_trig += 1
            if prev_reg is not None and reg == prev_reg:
                n_false += 1
        prev_reg = reg
    return {"rate": (round(n_false / n_trig, 4) if n_trig else None),
            "n_triggers": n_trig, "n_false": n_false,
            "turnover_threshold_pct": round(thr, 3)}


def regime_conditioned(out: dict, dates: list, by_month: dict[str, str]) -> dict:
    """국면조건부 성과 — ★`n_rebalances` 를 반드시 함께 낸다★.

    표본 수 없이 보면 얇은 국면의 Sharpe 가 거짓말을 한다.
    """
    eq = np.asarray(out["equity_curve"], dtype=float)
    ds = out["dates"]
    if eq.size < 3:
        return {}
    r = np.diff(eq) / eq[:-1]
    months = [str(d)[:7] for d in ds[1:]]
    rb_months = [str(x["date"])[:7] for x in out.get("rebalances", [])]

    acc: dict[str, list[float]] = {}
    for m, x in zip(months, r, strict=True):
        acc.setdefault(by_month.get(m, "?"), []).append(float(x))

    res = {}
    for reg, xs in sorted(acc.items()):
        a = np.asarray(xs)
        vol = a.std(ddof=1) * math.sqrt(252) if a.size > 2 else float("nan")
        ann = a.mean() * 252
        curve = np.cumprod(1 + a)
        peak = np.maximum.accumulate(curve)
        res[reg] = {
            "n_days": int(a.size),
            "n_rebalances": sum(1 for m in rb_months if by_month.get(m) == reg),
            "ann_return_pct": round(ann * 100, 2),
            "vol_pct": round(vol * 100, 2) if vol == vol else None,
            "sharpe": round(float((ann - 0.035) / vol), 3) if vol and vol == vol else None,
            "mdd_pct": round(float(((curve - peak) / peak).min()) * 100, 2),
        }
    return res


# ── 실행 ────────────────────────────────────────────────────────────────────
def run_cell(arm: str, model: str, cost: float, names, R, dates, points):
    # ★국면 경로를 함께 실어야 한다★ 처음에 `_ARM_REGIME[arm]` 만 넘겼더니
    # `points` 가 비어 절단 경로가 늘 0개가 됐고, 세 팔이 소수점까지 같아졌다.
    # `regime_audit` 이 70개 리밸런싱 전부에 사유를 남겨 그것을 잡았다.
    reg = _ARM_REGIME[arm]
    if reg is not None:
        reg = {"points": points, **reg}
    out = walk_forward(names, R, dates, model=model, rebalance="M",
                       cost_bps=cost, regime=reg, min_train=252)
    if out.get("error"):
        return {"arm": arm, "model": model, "cost_bps": cost,
                "error": out["message"]}
    by_month = {p["t"]: p["regime"] for p in points}
    r = daily_returns_from_equity(out["equity_curve"])
    # ★키를 추측하지 않는다★ 수익·Sharpe·Sortino·MDD 는 `summary` 에, CVaR 은
    # `metrics` 에 있다. 처음에 `metrics.annual_return_pct` 를 가정했다가 None 이
    # 나와 포맷에서 터졌고, 실제 페이로드를 읽어 고쳤다.
    m, sm = out["metrics"], out["summary"]
    return {
        "arm": arm, "model": model, "cost_bps": cost, "error": None,
        "return_pct": sm.get("cagr_pct"),
        "vol_pct": sm.get("volatility_pct"),
        "sharpe": sm.get("sharpe_ratio"),
        "sortino": sm.get("sortino_ratio"),
        "mdd_pct": sm.get("max_drawdown_pct"),
        "cvar_pct": m.get("cvar_pct"),
        "turnover_avg_pct": out.get("turnover_avg_pct"),
        "n_rebalances": out.get("n_rebalances"),
        "ce": round(certainty_equivalent(r), 6),
        "regime_audit": {k: v for k, v in out["regime_audit"].items()
                         if k != "detail"},
        "concentration": forecast_concentration(out["regime_audit"]),
        "false_trigger": false_trigger_rate(out, by_month),
        "by_regime": regime_conditioned(out, dates, by_month),
    }


def real_share() -> dict:
    from src.engine.capability import probe_all
    fs = probe_all().get("frontier_sample", {})
    return fs.get("detail") or fs.get("reason") or {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", nargs="?", const="-", default=None)
    ap.add_argument("--months", type=int, default=84)
    args = ap.parse_args()

    names, R, dates, points = build_panel(months=args.months)
    cells = [run_cell(a, m, c, names, R, dates, points)
             for a in ARMS for m in MODELS for c in COSTS]

    # ★공허한 결과를 표로 내지 않는다★ 조건부가 한 번도 적용되지 않았다면 세 팔이
    # 같아지는데, 그 표는 "차이가 없다" 가 아니라 "재지 못했다" 를 뜻한다.
    for c in cells:
        if c["error"] or c["arm"] == "B0":
            continue
        aud = c["regime_audit"]
        if aud.get("weights_infeasible", 0) >= aud["n_rebalances"]:
            print(f"★평가 중단★ {c['arm']}/{c['model']} 은 모든 리밸런싱에서 배분이 "
                  f"거부됐습니다 — 한 번도 거래하지 않은 곡선입니다.", file=sys.stderr)
            return 2
        used = aud["s_override_used"]
        if used == 0:
            print(f"★평가 중단★ {c['arm']}/{c['model']} 에서 조건부가 한 번도 "
                  f"적용되지 않았습니다 — 이 표는 '차이가 없다' 가 아니라 "
                  f"'재지 못했다' 입니다.", file=sys.stderr)
            return 2

    hdr = (f"{'arm':>3} {'model':>5} {'bp':>4} | {'ret%':>7} {'vol%':>6} "
           f"{'sharpe':>6} {'sortino':>7} {'mdd%':>7} {'cvar%':>6} "
           f"{'turn%':>6} {'nrb':>4} {'CE':>8} | {'sharp':>6} {'perp':>5} {'FT':>6} {'inf':>4}")
    print(hdr)
    print("-" * len(hdr))
    for c in cells:
        if c["error"]:
            print(f"{c['arm']:>3} {c['model']:>5} {c['cost_bps']:>4.0f} | ERROR {c['error']}")
            continue
        k, ft = c["concentration"], c["false_trigger"]
        def _f(v, w):
            return f"{v:>{w}}" if v is not None else f"{'-':>{w}}"
        print(f"{c['arm']:>3} {c['model']:>5} {c['cost_bps']:>4.0f} | "
              f"{_f(c['return_pct'],7)} {_f(c['vol_pct'],6)} {_f(c['sharpe'],6)} "
              f"{_f(c['sortino'],7)} {_f(c['mdd_pct'],7)} {_f(c['cvar_pct'],6)} "
              f"{_f(c['turnover_avg_pct'],6)} {_f(c['n_rebalances'],4)} "
              f"{c['ce']:>8.4f} | "
              f"{str(k['sharpness']):>6} {str(k['perplexity']):>5} "
              f"{str(ft['rate']):>6} {c['regime_audit'].get('weights_infeasible', 0):>4}")

    print()
    print("ΔCE (비용 수준별)")
    by = {(c["arm"], c["model"], c["cost_bps"]): c for c in cells if not c["error"]}
    for model in MODELS:
        for cost in COSTS:
            b0, b1, nn = (by.get((a, model, cost)) for a in ARMS)
            if not (b0 and b1 and nn):
                continue
            print(f"  {model:>3} {cost:>4.0f}bp   ΔCE₀ (B1−B0) = {b1['ce'] - b0['ce']:+.6f}"
                  f"   ΔCE₁ (N−B1) = {nn['ce'] - b1['ce']:+.6f}")

    print()
    print("★증거 등급★", json.dumps(real_share(), ensure_ascii=False))

    if args.report:
        md = render_report(cells, real_share())
        if args.report == "-":
            print()
            print(md)
        else:
            with open(args.report, "w", encoding="utf-8") as f:
                f.write(md)
            print(f"\n보고서 → {args.report}")
    return 0


def render_report(cells: list[dict], rs: dict) -> str:
    lines = ["# MS1-b0 기제 검증 보고서 (경제적 증거 아님)", ""]
    lines.append(f"> ★증거 등급★ `frontier_sample` = `{json.dumps(rs, ensure_ascii=False)}`")
    lines.append("> `real_share = 0` 인 동안 아래 표는 **배선이 도는가**에 대한 답이지")
    lines.append("> **모델이 맞는가**에 대한 답이 아니다. 승격 근거로 쓰지 말 것.")
    lines.append("")
    lines.append("| arm | model | bp | ret% | vol% | sharpe | sortino | mdd% | cvar% | turn% | nrb | CE | sharpness | perplexity | false-trigger |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for c in cells:
        if c["error"]:
            lines.append(f"| {c['arm']} | {c['model']} | {c['cost_bps']:.0f} | ERROR: {c['error']} |")
            continue
        k, ft = c["concentration"], c["false_trigger"]
        lines.append(
            f"| {c['arm']} | {c['model']} | {c['cost_bps']:.0f} | {c['return_pct']} | "
            f"{c['vol_pct']} | {c['sharpe']} | {c['sortino']} | {c['mdd_pct']} | "
            f"{c['cvar_pct']} | {c['turnover_avg_pct']} | {c['n_rebalances']} | "
            f"{c['ce']:.4f} | {k['sharpness']} | {k['perplexity']} | {ft['rate']} |")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
