"""③ 신호 수준 관문 — ★국면이 **다음 달** 수익을 설명하는가★ (A4)
==============================================================================
사전등록: `docs/superpowers/specs/2026-08-30-signal-gate-preregistration.md`

감사(`7313371`) §4 의 연구 부채: 신호 수준(③) 관문이 **하중이 아니었다**. 배분
성과(④)로만 판정하면 국면 정보가 하나도 없어도 비용·제약 구조가 Sharpe 를 움직여
통과할 수 있다 — M1~M5 의 널 **중앙값이 양수**(+0.021)였던 것이 그 증거다.

★이 관문이 답하는 것은 ③ 예측 스킬 하나다.★ ①정보 표현력 · ②전달 안정성 ·
④경제적 가치는 다른 질문이고 여기서 답하지 않는다. 통과해도 "예측력이 있다" 가
아니라 **"이 합성 패널(E0)에서 라벨이 다음 달 수익의 분산을 두 널보다 많이
설명한다"** 로만 적는다.

★배분 경로에 연결하지 않는다★ 연구 전용이다. `src/engine` 은 이 모듈을 import
하지 않는다(테스트가 강제).

사용:
    python3 scripts/regime_signal_gate.py --report out.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("KIS_USE_MOCK", "1")

from src.engine import null_stats as ns  # noqa: E402
from src.engine import regime_surrogates as rs  # noqa: E402
from src.engine import research_power as rp  # noqa: E402
from src.engine.regime_signal import (  # noqa: E402
    DECISIVE_HORIZON,
    align,
    eta_squared,
    monthly_matrix,
)
from src.engine.research_verdict import (  # noqa: E402
    DEFAULT_TARGET_POWER,
    REQUIRED_FIELDS,
    classify,
)

# ── ★사전등록된 값 — 결과를 보고 바꾸지 않는다★ ────────────────────────────
PRIMARY = "eta_squared"
THRESHOLD_PCT = (5.0, 95.0)
HORIZONS = (0, 1)
POWER_SCALES = (1.0, 2.0, 3.0, 4.0, 6.0, 8.0)
POWER_SEEDS = (0, 1, 2, 3, 4)
N_MARKOV = 200
BASE_SEED = 20260825
DECISION_RULE = ("순환이동 널과 마르코프 널 **양쪽에서** 분위 95 초과(단측)")

ARM_ON = rs.ARM_ON
ARM_CONST = rs.ARM_CONST

_QUESTION = {0: "① 정보 표현력 — 라벨이 **같은 달** 수익을 설명하는가",
             1: "③ 예측 스킬 — 라벨이 **다음 달** 수익을 설명하는가"}


# ── ★판정 — 규칙이지 데이터가 아니다★ ─────────────────────────────────────
def decide_signal_verdict(pct_by_null: dict[str, float | None],
                          *, power: float | None,
                          threshold_pct: tuple[float, float] = THRESHOLD_PCT,
                          target_power: float = DEFAULT_TARGET_POWER,
                          power_block: dict | None = None) -> dict[str, Any]:
    """두 널의 분위 → 통과 여부 + 다섯 분류.

    ★단측이다★ η² 는 분산 설명 **비율**이라 아래쪽 꼬리(진짜 라벨이 무작위보다
    **덜** 설명함)는 스킬의 증거가 아니다. M1~M5 의 `sharpe_diff` 는 양측이었지만
    통계의 의미가 다르다 — `side != inside` 로 쓰면 정반대 결과가 통과한다.

    ★SPA 인 척하지 않는다★ `classify` 의 두 번째 인자 이름이 `spa_ok` 지만 여기
    들어가는 것은 **마르코프 널**이다. `gate_axes` 로 이름을 밝힌다.
    """
    lo, hi = float(threshold_pct[0]), float(threshold_pct[1])

    def _above(method: str) -> bool | None:
        pct = pct_by_null.get(method)
        side = ns.side_of(pct, lo, hi)
        return None if side is None else (side == ns.SIDE_ABOVE)

    shift_above = _above(rs.NULL_SHIFT)
    markov_above = _above(rs.NULL_MARKOV)

    why: list[str] = []
    for name, method, ok in (("순환이동", rs.NULL_SHIFT, shift_above),
                             ("마르코프", rs.NULL_MARKOV, markov_above)):
        pct = pct_by_null.get(method)
        if ok is None:
            why.append(f"{name} 널의 분위가 없습니다 — 미상은 통과가 아닙니다")
        elif not ok:
            where = "아래" if (pct is not None and pct < lo) else "안"
            why.append(f"{name} 널의 {where}에 있습니다 (분위 {pct})")

    label = classify(null_outside=shift_above, spa_ok=markov_above,
                     power=power, target_power=target_power)

    block = dict(power_block or {})
    reasons = dict(block.get("reasons") or {})
    for f in REQUIRED_FIELDS:
        block.setdefault(f, None)
        if block[f] is None and not (reasons.get(f) or "").strip():
            reasons[f] = ("검정력을 산출하지 않았습니다 — 이 판정은 검출력에 "
                          "대해 아무 주장도 하지 않습니다")

    return {"passed": bool(shift_above and markov_above),
            "verdict": label["verdict"], "verdict_why": label["why"],
            "shift_above": shift_above, "markov_above": markov_above,
            "percentile": {k: pct_by_null.get(k)
                           for k in (rs.NULL_SHIFT, rs.NULL_MARKOV)},
            "threshold_pct": [lo, hi], "one_sided": True, "convention": True,
            "gate_axes": {"primary_null": rs.NULL_SHIFT,
                          "secondary_null": rs.NULL_MARKOV},
            "horizon": DECISIVE_HORIZON,
            "target_power": label["target_power"],
            "mde": block.get("mde"), "power": block.get("power"),
            "n_eff": block.get("n_eff"), "reasons": reasons,
            "power_block": (power_block or None),
            "why": why or ["두 널 모두에서 위에 있습니다"]}


# ── 팔과 널 ────────────────────────────────────────────────────────────────
def eta_by_arm(points: list[dict], monthly: Any, *, horizon: int) -> dict[str, Any]:
    """진짜 팔과 음성 통제 팔의 η². ★음성 통제는 판정에 넣지 않는다★."""
    out: dict[str, Any] = {}
    for arm, pts in ((ARM_ON, points), (ARM_CONST, rs.constant_path(points))):
        lab, m = align(rs.labels_of(pts), monthly, horizon=horizon)
        out[arm] = eta_squared(lab, m)
    return out


def null_draws(points: list[dict], monthly: Any, *, horizon: int, method: str,
               seed: int, n_markov: int) -> tuple[list[float], bool, int]:
    """서로게이트 경로를 진짜 팔과 **같은 방식으로** 돌린다."""
    rng = np.random.default_rng(int(seed))
    if method == rs.NULL_SHIFT:
        ks, enumerated = rs.shifts_for(len(points), 10 ** 9, rng)
    else:
        ks, enumerated = list(range(int(n_markov))), False
    vals: list[float] = []
    for i, k in enumerate(ks):
        sur = rs.surrogate_path(points, method,
                               np.random.default_rng(int(seed) + 1000 * (i + 1)),
                               k=(k if method == rs.NULL_SHIFT else None))
        lab, m = align(rs.labels_of(sur), monthly, horizon=horizon)
        v = eta_squared(lab, m)
        if v is not None:
            vals.append(v)
    return vals, enumerated, len(ks)


def gate_once(points: list[dict], monthly: Any, *, horizon: int, seed: int,
              n_markov: int, threshold_pct=THRESHOLD_PCT) -> dict[str, Any]:
    """한 지평의 팔·널·분위. ★판정은 하지 않는다★ — 규칙은 순수 함수가 맡는다."""
    arms = eta_by_arm(points, monthly, horizon=horizon)
    real = arms[ARM_ON]
    nulls: dict[str, Any] = {}
    pct_by_null: dict[str, float | None] = {}
    for method in (rs.NULL_SHIFT, rs.NULL_MARKOV):
        vals, enumerated, n_draws = null_draws(
            points, monthly, horizon=horizon, method=method, seed=seed,
            n_markov=n_markov)
        pct = ns.percentile_of(real, vals) if real is not None else None
        pct_by_null[method] = pct
        nulls[method] = {
            "n_draws": n_draws, "enumerated": enumerated,
            "decisive": True,          # ★둘 다 판정에 들어간다 (연언)★
            "preserves": ("주변분포 · 런 구조" if method == rs.NULL_SHIFT
                          else "전이확률"),
            "percentile": pct,
            "beyond_range": ns.beyond_range(real, vals),
            "side": ns.side_of(pct, *threshold_pct),
            "stats": ns.summarize(vals),
        }
    return {"horizon": horizon, "question": _QUESTION[horizon],
            "decisive": horizon == DECISIVE_HORIZON,
            "arms": arms, "nulls": nulls, "pct_by_null": pct_by_null}


# ── 검정력 (양성 통제) ─────────────────────────────────────────────────────
def _panel(months: int, seed: int, scale: float):
    from scripts.t3_transmission import build_panel
    names, R, dates, points, _beta = build_panel(months=months, seed=seed,
                                                 scale=scale)
    return names, R, dates, points


def power_trial(months: int, base_seed: int, n_markov: int,
                threshold_pct=THRESHOLD_PCT, horizon: int = DECISIVE_HORIZON):
    """`research_power.power_curve` 에 주입할 시행 — ★예외를 삼키지 않는다★."""
    def trial(scale: float, seed: int) -> bool | None:
        _n, R, dates, points = _panel(months, int(base_seed) + int(seed), scale)
        monthly = monthly_matrix(R, dates)
        blk = gate_once(points, monthly, horizon=int(horizon),
                        seed=int(base_seed) + int(seed), n_markov=n_markov,
                        threshold_pct=threshold_pct)
        v = decide_signal_verdict(blk["pct_by_null"], power=None,
                                  threshold_pct=threshold_pct)
        if v["shift_above"] is None or v["markov_above"] is None:
            return None                       # ★미상 ≠ 못 찾음★
        return bool(v["passed"])
    return trial


# ── 하네스 ─────────────────────────────────────────────────────────────────
def run(*, months: int = 84, seed: int = BASE_SEED,
        power_scales=POWER_SCALES, power_seeds=POWER_SEEDS,
        n_markov: int = N_MARKOV, threshold_pct=THRESHOLD_PCT,
        target_power: float = DEFAULT_TARGET_POWER) -> dict[str, Any]:
    """두 지평을 **둘 다** 돌리고 사전등록된 규칙으로 **선행만** 판정한다."""
    names, R, dates, points = _panel(months, seed, 1.0)
    monthly = monthly_matrix(R, dates)

    horizons = {str(h): gate_once(points, monthly, horizon=h, seed=seed,
                                  n_markov=n_markov,
                                  threshold_pct=threshold_pct)
                for h in HORIZONS}

    # ★두 지평의 검정력을 **둘 다** 낸다★ 사전등록에 "선행의 MDE 가 동시대보다
    # 클 것" 이라고 적었으므로, 그 예측이 맞았는지를 리포트가 스스로 답해야 한다.
    rho = rp.mean_pairwise_correlation(monthly)
    power_by_horizon: dict[str, Any] = {}
    for h in HORIZONS:
        curve = rp.power_curve(
            power_trial(months, seed, n_markov, threshold_pct, horizon=h),
            scales=power_scales, seeds=power_seeds)
        power_by_horizon[str(h)] = rp.power_report(
            curve=curve, observed_scale=1.0, n_obs=len(points),
            n_assets=len(names), rho_bar=rho, target_power=target_power)
        horizons[str(h)]["power"] = power_by_horizon[str(h)]
    block = power_by_horizon[str(DECISIVE_HORIZON)]

    decisive = horizons[str(DECISIVE_HORIZON)]
    verdict = decide_signal_verdict(decisive["pct_by_null"],
                                    power=block.get("power"),
                                    threshold_pct=threshold_pct,
                                    target_power=target_power,
                                    power_block=block)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seed": int(seed), "months": int(months),
        # ★사전등록을 리포트가 스스로 싣는다★ 문서는 코드를 강제하지 못한다.
        "preregistered": {
            "primary_statistic": PRIMARY,
            "decisive_horizon": DECISIVE_HORIZON,
            "threshold_pct": [float(threshold_pct[0]), float(threshold_pct[1])],
            "one_sided": True, "convention": True,
            "decision_rule": DECISION_RULE,
            "power_scales": [float(s) for s in power_scales],
            "power_seeds": [int(s) for s in power_seeds],
            "target_power": float(target_power),
            "negative_control": ARM_CONST,
            "negative_control_in_verdict": False,
        },
        # ★어떤 질문에 답했는지 리포트가 밝힌다★
        "answers_question": "③ 예측 스킬",
        "does_not_answer": ["① 정보 표현력", "② 전달 안정성", "④ 경제적 가치"],
        "evidence_grade": "E0",
        "panel": {"n_assets": len(names), "n_months": len(points),
                  "n_runs": rs.n_runs(points), "marginal": rs.marginal(points),
                  "mean_pairwise_correlation": rho},
        "horizons": horizons, "power": block,
        "power_by_horizon": power_by_horizon, "verdict": verdict,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=84)
    ap.add_argument("--seed", type=int, default=BASE_SEED)
    ap.add_argument("--n-markov", type=int, default=N_MARKOV)
    ap.add_argument("--report", default=None)
    args = ap.parse_args()

    rep = run(months=args.months, seed=args.seed, n_markov=args.n_markov)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=2, default=str)

    v = rep["verdict"]
    print(f"판정: {v['verdict']} (passed={v['passed']}) · 지평={v['horizon']}(선행)")
    for h in ("0", "1"):
        b = rep["horizons"][h]
        p = b["pct_by_null"]
        print(f"  h={h} {'★결정적★' if b['decisive'] else '(보고만)'} "
              f"η²={b['arms'][ARM_ON]} · const={b['arms'][ARM_CONST]} · "
              f"분위 shift={p[rs.NULL_SHIFT]} markov={p[rs.NULL_MARKOV]}")
    for h in ("0", "1"):
        b = rep["power_by_horizon"][h]
        print(f"  h={h} MDE={b['mde']} bracket={b['mde_detail']['bracket']} "
              f"power(1×)={b['power']} n_eff={b['n_eff']}")
    for r in v["why"]:
        print(f"  · {r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
