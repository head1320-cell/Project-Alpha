"""매크로 국면 ★음성 통제 + 경제적 가치 관문★ (M3)
==============================================================================
설계·사전등록: `docs/superpowers/specs/2026-08-29-macro-regime-negative-control-design.md`
변환: `src/engine/regime_surrogates.py` · 널 통계: `src/engine/null_stats.py`

## 무엇을 묻는가

★국면 라벨의 **정렬**이 경제적 가치와 연결되는가?★ 실측(합성 패널 84개월 · BL)에서
국면 팔은 Sharpe 0.420, 국면 없음은 0.200 이었다. 그런데 라벨을 무작위로 다시
붙인 경로가 같은 일을 하는지 아무도 재지 않았다.

S6 이 기업 뷰에 물은 질문과 같지만 **한 칸 더 간다** — 여기서는 `walk_forward` 의
표본외 실현수익이 있으므로 ④ 경제적 가치에 닿는다(S6 은 ② 전달 안정성에서 멈췄다).
T1 의 자기참조 문제도 없다: 결과가 자기 μ 아래 효용이 아니라 **실현 수익**이다.

## ★사전등록 — 돌리기 전에 고정했다★

주 통계는 **비용차감 Sharpe 차**(`on − off`) 하나다. 부 통계는 전부 `decisive:false`
로 보고만 한다. 통과 조건은 ★널 밖(양측 5%) **그리고** SPA p < 0.05 **그리고**
비용 3수준 전부★ 이고, 엇갈리면 보수적으로 불통과다.

★비용 수준 간 **연언**이라 추가 보정이 필요 없다★ — 셋을 모두 요구하는 것은 어느
하나를 요구하는 것보다 **엄격**하다. 다중비교 보정이 필요한 축은 "여러 팔 중 최선"
쪽이고 그것을 `arch.bootstrap.SPA`(Hansen 우위예측력)가 맡는다.

## 왜 순환이동이 주 널인가

실제 경로는 82개월에 런 26개(평균 3.15개월)로 지속성이 있다. 단순 셔플은 런을
61~71개로 쪼개 회전율을 8.5%→11.5~13.1% 로 올린다 → 널 팔이 **비용 때문에**
불리해져 거짓 양성이 난다. 순환이동은 주변분포를 정확히 보존하고 런 수를 최대 1
바꿀 뿐이며, 깨는 것은 **수익과의 정렬**뿐이다.

사용:
    python3 scripts/regime_control.py --report out.json
    python3 scripts/regime_control.py --months 84 --model bl --n-markov 50
"""

from __future__ import annotations

import argparse
import json
import logging
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
from src.engine.research_panel import (  # noqa: E402
    evidence_grade,
    inject_regime_drift,
    panel_for,
)
from src.engine.research_power import mde_from_curve  # noqa: E402
from src.engine.research_verdict import (  # noqa: E402
    DEFAULT_TARGET_POWER,
    REQUIRED_FIELDS,
    classify,
)

logger = logging.getLogger(__name__)

# ── ★사전등록된 값 — 결과를 보고 바꾸지 않는다★ ────────────────────────────
PRIMARY = "sharpe_diff"
SECONDARY = ("cagr_diff", "max_drawdown_pct", "volatility_pct", "avg_turnover_pct")
COST_LEVELS = (5.0, 10.0, 25.0)
THRESHOLD_PCT = (5.0, 95.0)
SPA_ALPHA = 0.05
DECISION_RULE = ("널 밖(양측 5%) **그리고** SPA p < 0.05 **그리고** 비용 3수준 "
                 "전부에서 같은 판정. 엇갈리면 보수적으로 불통과.")

#: 판정에 쓰는 팔(벤치마크 제외) — SPA 의 후보 집합이기도 하다.
CANDIDATE_ARMS = (rs.ARM_ON, rs.ARM_ON_PROB, rs.ARM_CONST)

_REVISION_BIAS = {
    "status": "unmanaged",
    "reason": ("ECOS·KRX 는 빈티지 엔드포인트를 주지 않아 국면 경로가 오늘 데이터로 "
               "재계산됩니다 — 수준 추정치는 개정 편향을 안고 있습니다."),
    "why_null_still_works": ("진짜 팔과 널 팔이 **정확히 같은 편향** 아래 돕니다. "
                             "수준은 못 믿어도 팔 간 비교는 답을 줍니다 — 이 실험이 "
                             "묻는 것이 수준이 아니라 위치이기 때문입니다."),
}


# ── 한 번의 백테스트 ───────────────────────────────────────────────────────
def arm_regime(points: list[dict], arm: str,
               rng=None) -> dict | None:
    """팔 이름 → `walk_forward(regime=…)` 에 넘길 dict. `regime-off` 는 `None`.

    ★조용히 `on` 으로 떨어지지 않는다★ — 모르는 팔은 거부한다. 통제 팔이 진짜 팔이
    되면 리포트는 "구분되지 않는다" 를 당연하게 만든다.
    """
    if arm == rs.ARM_OFF:
        return None
    if arm == rs.ARM_ON:
        return {"points": list(points), "weighting": "hard"}
    if arm == rs.ARM_ON_PROB:
        return {"points": list(points), "weighting": "probabilistic"}
    if arm == rs.ARM_CONST:
        # ★기계는 그대로 돌고 타이밍만 없다★ — 이득이 '국면 타이밍' 인지 그 규칙이
        # 고른 '수준' 인지를 가른다(`t3_transmission` 의 `-const` 와 같은 이유).
        return {"points": rs.constant_path(points), "weighting": "hard"}
    raise ValueError(f"모르는 팔입니다: {arm!r} (가능: {', '.join(rs.ARMS)})")


def _daily_returns(equity: list[float]) -> np.ndarray:
    e = np.asarray(equity, dtype=float)
    if e.size < 2:
        return np.zeros(0)
    return e[1:] / e[:-1] - 1.0


#: ★이 관문의 무위험 관례★ 0 이다 — 팔 사이의 **차이**(`sharpe_diff`)를 주 통계로
#: 쓰므로 공통 무위험은 상쇄된다. 값이 아니라 **차이**를 보는 관문이라 이 선택이
#: 판정을 바꾸지 않는다. 그래도 관례이므로 선언하고 리포트에 싣는다.
GATE_RISK_FREE = 0.0


def _sharpe(daily: np.ndarray) -> float | None:
    """일수익 → 연율 Sharpe, ★전정밀도★. 표본이 없거나 분산이 0 이면 `None`.

    ★단일 출처에 위임한다 (P1)★ 이 함수는 예전에 공식을 직접 들고 있었고, 그것이
    `allocation_backtest`(rf=0.035)·`multi_strategy_backtest`(rf=0.025)와 갈라진
    세 번째 관례였다. 이제 `quant_metrics.risk_adjusted_ratios` 가 계산하고
    여기서는 이 관문의 관례(`GATE_RISK_FREE=0`)만 고른다.
    """
    from src.engine.quant_metrics import risk_adjusted_ratios

    v = risk_adjusted_ratios(daily, [], risk_free=GATE_RISK_FREE,
                             ddof=1, periods_per_year=252)["sharpe_ratio"]
    return None if v is None else round(float(v), 8)


class PlanCounter:
    """계획을 몇 번 만들고 몇 번 태웠는가 — ★세지 않으면 재사용은 주장이다★ (P7).

    "비용마다 다시 계산하지 않는다" 는 값으로 확인할 수 없다(빠른지 느린지는
    타이밍이고, 타이밍은 테스트가 아니다). 그래서 구조를 센다.
    """

    __slots__ = ("plans_built", "simulations_run")

    def __init__(self) -> None:
        self.plans_built = 0
        self.simulations_run = 0

    def as_dict(self) -> dict:
        reuse = (self.simulations_run / self.plans_built) if self.plans_built else None
        return {"plans_built": self.plans_built,
                "simulations_run": self.simulations_run,
                "reuse_factor": (None if reuse is None else round(reuse, 4))}


def plan_for(names, R, dates, regime, *, model: str, rebalance: str,
             min_train: int, counter: PlanCounter | None = None):
    """비용을 모르는 계획을 만든다 (P7 ②).

    ★관문이 비용 수준마다 이것을 다시 만들고 있었다★ — P3 이 비중 경로의 비용
    불변성을 증명해 뒀는데도. 이제 팔·널마다 **한 번** 만들고 비용은 그 위에서 돈다.
    """
    from src.engine.allocation_backtest import plan_walk_forward

    plan = plan_walk_forward(names, R, dates, model=model, rebalance=rebalance,
                             min_train=min_train, regime=regime)
    if counter is not None:
        counter.plans_built += 1
    return plan


def evaluate(plan, *, cost_bps: float, impact=None,
             counter: PlanCounter | None = None) -> dict:
    """계획 하나에 비용을 물려 요약 지표 + 일수익 + 국면 계약을 낸다.

    ★`impact` 는 팔에도 널에도 **똑같이** 넘어가야 한다 (P3)★ 널이 정액이고
    팔만 충격을 물면 분위수가 서로 다른 비용 체제를 비교하게 되어 무의미해진다.
    서로게이트마다 회전율이 다르니 널도 각자 다른 충격을 문다 — 그게 옳다.
    """
    from src.engine.allocation_backtest import simulate_walk_forward

    if isinstance(plan, dict):                     # 계획 단계의 명시적 거부
        return {"available": False, "reason": plan.get("message")}
    out = simulate_walk_forward(plan, cost_bps=cost_bps, impact=impact)
    if counter is not None:
        counter.simulations_run += 1
    if out.get("error"):
        return {"available": False, "reason": out.get("message")}
    s = out["summary"]
    tos = [rb["turnover_pct"] for rb in out.get("rebalances") or []]
    aud = out.get("regime_audit") or {}
    det = (aud.get("detail") or [{}])
    last = det[-1] if det else {}
    daily = _daily_returns(out.get("equity_curve") or [])
    return {
        "available": True, "reason": None,
        # ★주 통계는 **일수익에서 전정밀도로** 잰다★
        #   `summary.sharpe_ratio` 는 `round(sharpe, 2)` 라 해상도가 0.01 이고,
        #   실측에서 비용을 5→100bps 로 올려도 **0.42 로 고정**이었다(전정밀도는
        #   0.6706→0.6087 로 움직인다). 그 값을 쓰면 사전등록의 "비용 3수준 전부"
        #   절이 **무의미**해진다 — 통계가 비용을 볼 수 없기 때문이다.
        #   두 값은 정의도 다르므로(요약 0.42 vs 일수익 0.67) 하나만 쓴다.
        "sharpe": _sharpe(daily),
        "sharpe_summary_rounded": s["sharpe_ratio"],
        "cagr_pct": s["cagr_pct"],
        "max_drawdown_pct": s["max_drawdown_pct"],
        "volatility_pct": s["volatility_pct"],
        "avg_turnover_pct": round(float(np.mean(tos)), 4) if tos else 0.0,
        "n_rebalances": out.get("n_rebalances"),
        "arm_label": aud.get("arm"),
        # ★충격을 실제로 얼마나 물었는가★ 가정만 적고 실현값을 안 적으면
        # 규모를 바꿨을 때 무엇이 달라졌는지 리포트에서 확인할 수 없다.
        "impact_bps_mean": (out.get("impact") or {}).get("mean_bps"),
        "max_participation": (out.get("impact") or {}).get("max_participation"),
        "beyond_model_range": (out.get("impact") or {}).get("beyond_model_range"),
        # ★계약 신고를 결과 옆에 붙인다★ 하드 팔은 확률 계약을 통과하지 않는다.
        "prob_source": last.get("prob_source"),
        "prob_usage": last.get("prob_usage"),
        "daily": daily,
    }


def backtest(names, R, dates, regime, *, model: str, cost_bps: float,
             rebalance: str, min_train: int, impact=None) -> dict:
    """`plan_for` → `evaluate` 의 얇은 합성 — 비용 하나짜리 호출부용."""
    return evaluate(plan_for(names, R, dates, regime, model=model,
                             rebalance=rebalance, min_train=min_train),
                    cost_bps=cost_bps, impact=impact)


def _stats(arm: dict, off: dict) -> dict:
    """팔 하나의 통계 — ★주 통계는 차이★ 라 공통 시장움직임이 상쇄된다."""
    if (not arm.get("available") or not off.get("available")
            or arm.get("sharpe") is None or off.get("sharpe") is None):
        return {k: None for k in (PRIMARY, *SECONDARY)}
    return {
        PRIMARY: round(float(arm["sharpe"]) - float(off["sharpe"]), 8),
        "cagr_diff": round(float(arm["cagr_pct"]) - float(off["cagr_pct"]), 6),
        "max_drawdown_pct": arm["max_drawdown_pct"],
        "volatility_pct": arm["volatility_pct"],
        "avg_turnover_pct": arm["avg_turnover_pct"],
    }


# ── ★판정 — 규칙이지 데이터가 아니다★ ─────────────────────────────────────
def decide_verdict(per_cost: dict[str, dict], spa_p: float | None, *,
                   threshold_pct: tuple[float, float] = THRESHOLD_PCT,
                   power_block: dict | None = None) -> dict:
    """비용 수준별 `{percentile, side}` + SPA p → 통과 여부.

    ★순수 함수다★ 판정은 규칙이지 데이터가 아니다. 데이터를 만들어 규칙을
    확인하려 하면 픽스처의 우연을 계약으로 착각한다(S6 에서 치른 값).

    ★미상은 통과가 아니다★ 분위가 없거나 SPA 를 못 돌렸으면 통과시키지 않는다.

    ★A2 — `passed` 옆에 어휘와 검정력을 싣는다★ `passed` 의 규칙은 한 자도
    바뀌지 않았다(`널 밖 and SPA 유의`). 다만 그 불리언 하나로는 M1~M5 를 설명할
    수 없었다 — "SPA p=0.094 로 못 넘었다" 와 "효과가 없다" 가 구별되지 않았다.
    `research_verdict.classify` 가 다섯 분류를 붙이고, `power_block`
    (`research_power.power_report` 의 산출)이 있으면 `mde`·`power`·`n_eff` 를
    함께 싣는다. 없으면 **사유와 함께 미상**으로 싣는다 — 빈칸으로 두지 않는다.
    """
    lo, hi = float(threshold_pct[0]), float(threshold_pct[1])
    why: list[str] = []

    outside_by_cost = {}
    for cost, blk in per_cost.items():
        pct = (blk or {}).get("percentile")
        side = ns.side_of(pct, lo, hi)
        outside_by_cost[cost] = bool(pct is not None and side != ns.SIDE_INSIDE)
    null_outside = bool(outside_by_cost) and all(outside_by_cost.values())
    if not null_outside:
        bad = [c for c, ok in outside_by_cost.items() if not ok]
        why.append(f"비용 수준 {', '.join(sorted(bad))}bps 에서 널 안에 있습니다")

    spa_ok = spa_p is not None and float(spa_p) < SPA_ALPHA
    if spa_p is None:
        why.append("SPA 를 돌리지 못했습니다 — 미상은 유의가 아닙니다")
    elif not spa_ok:
        why.append(f"SPA p={float(spa_p):.4f} 가 {SPA_ALPHA} 이상입니다")

    block = dict(power_block or {})
    reasons = dict(block.get("reasons") or {})
    for f in REQUIRED_FIELDS:
        block.setdefault(f, None)
        if block[f] is None and not (reasons.get(f) or "").strip():
            reasons[f] = ("검정력을 산출하지 않았습니다 — 이 판정은 검출력에 대해 "
                          "아무 주장도 하지 않습니다")

    label = classify(null_outside=null_outside, spa_ok=spa_ok,
                     power=block.get("power"))

    return {"passed": bool(null_outside and spa_ok),
            "null_outside": null_outside, "spa_ok": spa_ok,
            "outside_by_cost": outside_by_cost,
            "threshold_pct": [lo, hi], "convention": True,
            "spa_p": (None if spa_p is None else round(float(spa_p), 6)),
            "verdict": label["verdict"],
            "verdict_why": label["why"],
            "target_power": label["target_power"],
            "mde": block.get("mde"), "power": block.get("power"),
            "n_eff": block.get("n_eff"), "reasons": reasons,
            "power_block": (power_block or None),
            "why": why or ["널 밖이고 SPA 도 유의합니다"]}


def _spa_pvalue(bench: np.ndarray, models: list[np.ndarray], *,
                reps: int, seed: int) -> tuple[float | None, str | None]:
    """Hansen 우위예측력 — ★여러 팔 중 최선이 벤치마크를 이기는가, 탐색 보정 후★.

    손실 = 일수익의 음수. 못 돌리면 **사유와 함께 `None`** 을 낸다(0 이나 1 로
    채우지 않는다 — 미상은 유의도 불유의도 아니다).
    """
    try:
        from arch.bootstrap import SPA
    except Exception as e:  # noqa: BLE001
        return None, f"arch 를 불러오지 못했습니다: {type(e).__name__}: {e}"
    usable = [m for m in models if m.size == bench.size and m.size > 10]
    if bench.size <= 10 or not usable:
        return None, "표본이 너무 짧아 SPA 를 돌릴 수 없습니다"
    try:
        spa = SPA(-bench, -np.column_stack(usable), reps=int(reps), seed=int(seed))
        spa.compute()
        return float(spa.pvalues["consistent"]), None
    except Exception as e:  # noqa: BLE001
        logger.warning("SPA 실패: %s: %s", type(e).__name__, e)
        return None, f"{type(e).__name__}: {e}"


def _mcs_set(by_arm: dict[str, np.ndarray], *, reps: int,
             seed: int) -> dict:
    """모델신뢰집합 — ★서로 구분되지 않는 팔들의 집합★ (Hansen–Lunde–Nason).

    판정에 쓰지 않는다(`decisive: false`). "최선이 무엇인가" 가 아니라 "무엇을
    **버릴 수 없는가**" 를 말해 주는 보조 관측이다. 못 돌리면 사유와 함께 비운다.
    """
    out: dict[str, Any] = {"decisive": False, "included": None,
                           "excluded": None, "reason": None, "alpha": SPA_ALPHA}
    names = [a for a, v in by_arm.items() if v is not None and v.size > 10]
    if len(names) < 2:
        out["reason"] = "비교할 팔이 2개 미만입니다"
        return out
    try:
        from arch.bootstrap import MCS

        losses = -np.column_stack([by_arm[a] for a in names])
        mcs = MCS(losses, size=SPA_ALPHA, reps=int(reps), seed=int(seed))
        mcs.compute()
        keep = {int(i) for i in np.atleast_1d(np.asarray(mcs.included)).ravel()}
        out["included"] = [names[i] for i in sorted(keep) if i < len(names)]
        out["excluded"] = [a for i, a in enumerate(names) if i not in keep]
    except Exception as e:  # noqa: BLE001
        logger.warning("MCS 실패: %s: %s", type(e).__name__, e)
        out["reason"] = f"{type(e).__name__}: {e}"
    return out


# ── 하네스 ─────────────────────────────────────────────────────────────────
def run(names, R, dates, points, *, model: str = "bl", rebalance: str = "M",
        min_train: int = 252, cost_levels=COST_LEVELS,
        n_shift: int | None = None, n_markov: int = 50, n_block: int = 50,
        seed: int = 7, threshold_pct=THRESHOLD_PCT, run_spa: bool = True,
        spa_reps: int = 1000, provenance: dict | None = None,
        impact=None) -> dict:
    """팔과 널을 전부 돌리고 사전등록된 규칙으로 판정한다.

    `n_shift=None` 이면 순환이동을 **전수** 돈다(주 널). 보조 널(마르코프·블록)은
    견고성 확인용이고 판정에 쓰지 않는다.

    ★증거 등급은 `provenance` 에서 **파생**한다 (M9)★ 예전에는
    `panel_is_synthetic` 이라는 **검증되지 않은 불리언**을 호출자가 줬고, 합성
    패널에 `False` 를 넘기면 그대로 `E3` 가 찍혔다 — 하지 않은 검증을 주장하는
    경로였다. `provenance` 를 안 주면 출처를 모르는 것이므로 ★등급을 찍지
    않는다★(`None` + 사유). 미상은 E3 가 아니다.
    """
    rng = np.random.default_rng(int(seed))
    # ★`impact` 를 `kw` 에 넣는 것이 계약이다★ 팔·널이 같은 통로로 나가므로
    # 한쪽만 충격을 무는 경로가 구조적으로 생길 수 없다.
    kw = {"model": model, "rebalance": rebalance, "min_train": min_train,
          "impact": impact}

    shift_ks, enumerated = rs.shifts_for(len(points),
                                         10**9 if n_shift is None else int(n_shift),
                                         rng)
    by_cost: dict[str, dict] = {}
    spa_inputs: dict[str, dict] = {}

    # ★계획을 먼저 전부 만든다 — 비용은 그 위에서 돈다 (P7 ②)★
    # 예전에는 `for cost: for arm/null: backtest(...)` 라 같은 비중 경로를 비용
    # 수준마다 처음부터 다시 계산했다(3비용 × 185런 = 555 계획). P3 이 비중 경로의
    # 비용 불변성을 증명해 뒀으므로 계획은 185번이면 충분하다.
    counter = PlanCounter()
    pkw = {k: v for k, v in kw.items() if k != "impact"}
    off_plan = plan_for(names, R, dates, None, counter=counter, **pkw)
    arm_plans = {arm: (off_plan if arm == rs.ARM_OFF
                       else plan_for(names, R, dates, arm_regime(points, arm),
                                     counter=counter, **pkw))
                 for arm in rs.ARMS}
    null_plans: dict[str, list] = {}
    for method, ks in ((rs.NULL_SHIFT, shift_ks),
                       (rs.NULL_MARKOV, list(range(int(n_markov)))),
                       (rs.NULL_BLOCK, list(range(int(n_block))))):
        seq = []
        for i, k in enumerate(ks):
            sur = rs.surrogate_path(points, method, np.random.default_rng(
                int(seed) + 1000 * (i + 1)), k=(k if method == rs.NULL_SHIFT else None))
            seq.append(plan_for(names, R, dates,
                                {"points": sur, "weighting": "hard"},
                                counter=counter, **pkw))
        null_plans[method] = seq

    for cost in cost_levels:
        off = evaluate(off_plan, cost_bps=float(cost), impact=impact,
                       counter=counter)
        arms: dict[str, dict] = {}
        for arm in rs.ARMS:
            bt = (off if arm == rs.ARM_OFF
                  else evaluate(arm_plans[arm], cost_bps=float(cost),
                                impact=impact, counter=counter))
            arms[arm] = {**{k: v for k, v in bt.items() if k != "daily"},
                         **_stats(bt, off)}
            spa_inputs.setdefault(str(cost), {})[arm] = bt.get("daily")

        # ── 널: 서로게이트 경로를 진짜 팔과 **같은 방식으로** 돌린다 ──────
        nulls: dict[str, dict] = {}
        draws: dict[str, list[float]] = {}
        for method, ks in ((rs.NULL_SHIFT, shift_ks),
                           (rs.NULL_MARKOV, list(range(int(n_markov)))),
                           (rs.NULL_BLOCK, list(range(int(n_block))))):
            vals: list[float] = []
            for i, _k in enumerate(ks):
                bt = evaluate(null_plans[method][i], cost_bps=float(cost),
                              impact=impact, counter=counter)
                st = _stats(bt, off)
                if st[PRIMARY] is not None:
                    vals.append(st[PRIMARY])
            draws[method] = vals
            nulls[method] = {
                "n_draws": len(ks),
                "n_possible": (len(points) - 1 if method == rs.NULL_SHIFT else None),
                "enumerated": (enumerated if method == rs.NULL_SHIFT else False),
                "decisive": method == rs.NULL_SHIFT,
                "stats": ns.summarize(vals),
            }

        real = arms[rs.ARM_ON][PRIMARY]
        main = draws.get(rs.NULL_SHIFT) or []
        pct = ns.percentile_of(real, main) if real is not None else None
        by_cost[str(cost)] = {
            "cost_bps": float(cost), "arms": arms, "null": nulls,
            "percentile": {PRIMARY: pct,
                           **{s: None for s in SECONDARY}},   # 부 통계는 판정 밖
            "side": ns.side_of(pct, *threshold_pct),
            "beyond_null_range": ns.beyond_range(real, main),
        }

    # ── SPA: 비용 수준마다 (연언이라 추가 보정 불필요) ──────────────────────
    spa: dict[str, Any] = {"benchmark": rs.ARM_OFF,
                           "candidates": list(CANDIDATE_ARMS),
                           "alpha": SPA_ALPHA, "by_cost": {}, "p_max": None}
    if run_spa:
        ps: list[float] = []
        for cost in cost_levels:
            d = spa_inputs.get(str(cost)) or {}
            bench = d.get(rs.ARM_OFF)
            mods = [d[a] for a in CANDIDATE_ARMS if d.get(a) is not None]
            if bench is None or not mods:
                spa["by_cost"][str(cost)] = {"p": None, "reason": "일수익이 없습니다"}
                continue
            p, why = _spa_pvalue(bench, mods, reps=spa_reps, seed=int(seed))
            spa["by_cost"][str(cost)] = {"p": p, "reason": why}
            if p is not None:
                ps.append(p)
        # ★연언이므로 가장 나쁜 p 가 판정을 지배한다★
        spa["p_max"] = max(ps) if len(ps) == len(cost_levels) else None
        # ★보조 관측★ 가장 낮은 비용에서 어느 팔들이 서로 구분되지 않는가.
        mcs = _mcs_set(spa_inputs.get(str(cost_levels[0])) or {},
                       reps=spa_reps, seed=int(seed))
    else:
        spa["by_cost"] = {str(c): {"p": None, "reason": "요청하지 않았습니다"}
                          for c in cost_levels}
        mcs = {"decisive": False, "included": None, "excluded": None,
               "reason": "요청하지 않았습니다", "alpha": SPA_ALPHA}

    _grade, _grade_why = evidence_grade(provenance)

    verdict = decide_verdict(
        {c: {"percentile": b["percentile"][PRIMARY], "side": b["side"]}
         for c, b in by_cost.items()},
        spa["p_max"], threshold_pct=threshold_pct)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": model, "seed": int(seed),
        # ★사전등록을 리포트가 스스로 싣는다★ 문서는 코드를 강제하지 못한다.
        "preregistered": {
            "primary_statistic": PRIMARY, "secondary": list(SECONDARY),
            "threshold_pct": [float(threshold_pct[0]), float(threshold_pct[1])],
            "convention": True, "cost_levels_bps": [float(c) for c in cost_levels],
            "spa_alpha": SPA_ALPHA, "decision_rule": DECISION_RULE,
            "primary_null": rs.NULL_SHIFT,
            "note": ("비용 수준 간 **연언**이라 그 축에는 추가 보정이 필요 없습니다 "
                     "— 셋을 모두 요구하는 것이 어느 하나보다 엄격합니다."),
        },
        "statistics": {PRIMARY: {"decisive": True},
                       **{s: {"decisive": False} for s in SECONDARY}},
        # ★등급은 파생한다★ 손으로 적지 않는다.
        "evidence_grade": _grade, "evidence_grade_reason": _grade_why,
        "provenance": provenance,
        "revision_bias": dict(_REVISION_BIAS),
        "panel": {"n_assets": len(names), "n_obs": int(np.asarray(R).shape[0]),
                  "n_months": len(points), "n_runs": rs.n_runs(points),
                  "mean_run_length": round(float(np.mean(rs.run_lengths(points))), 4)
                  if points else None,
                  "marginal": rs.marginal(points)},
        "impact": ({"applied": False, "convention": None,
                    "reason": ("규모 가정을 주지 않아 정액 비용만 물렸습니다 "
                               "— 회전율이 큰 팔이 그만큼 유리합니다.")}
                   if impact is None else
                   {"applied": True, "convention": impact.as_convention(),
                    "reason": None}),
        # ★재사용을 세어서 싣는다 (P7)★ 세지 않으면 "비용마다 다시 계산하지
        # 않는다" 는 검증 불가능한 주장이다.
        "plan_reuse": counter.as_dict(),
        "by_cost": by_cost, "spa": spa, "mcs": mcs, "verdict": verdict,
    }


# ── ★검정력 — 세 성분을 한 번의 격자에서★ (A3) ────────────────────────────
#: 사전등록된 격자. 결과를 보고 바꾸지 않는다.
POWER_SCALES = (1.0, 2.0, 3.0, 4.0)
POWER_SEEDS = (0, 1, 2, 3, 4)
COMPONENTS = ("conjunction", "null_only", "spa_only")


def power_curves(runner, scales, seeds) -> dict[str, list[dict]]:
    """척도×시드 격자를 **한 번** 돌려 세 성분의 검정력 곡선을 만든다.

    `runner(scale, seed)` 는 `{"null_outside": bool|None, "spa_ok": bool|None}`
    을 낸다. 세 곡선을 따로 돌리면 3배 비용인데다 시드가 갈라져 **같은 실행의
    성분 비교**가 아니게 된다 — 어느 성분이 병목인지가 이 측정의 목적이므로
    그것이 깨지면 답을 못 얻는다.

    ★미상 ≠ 실패★ 어느 성분이 `None` 이면 연언도 `None` 이다. 못 돌린 것을
    "못 찾았다" 로 세면 검정력이 실제보다 낮아 보인다.

    ★예외를 삼키지 않는다★ 시행이 터지면 전파한다 — 하네스 고장이 음성 결과로
    위장되면 안 된다.
    """
    seed_list = list(seeds)
    out: dict[str, list[dict]] = {c: [] for c in COMPONENTS}
    for sc in sorted(float(x) for x in scales):
        got = [runner(sc, sd) for sd in seed_list]
        n = [r.get("null_outside") for r in got]
        p = [r.get("spa_ok") for r in got]
        conj = [None if (a is None or b is None) else bool(a and b)
                for a, b in zip(n, p, strict=True)]
        for name, outcomes in (("conjunction", conj), ("null_only", n),
                               ("spa_only", p)):
            out[name].append({"scale": sc, "seeds": len(seed_list),
                              **rp.detection_rate(outcomes)})
    return out


def gate_runner(*, months: int, base_seed: int, model: str = "bl",
                rebalance: str = "M", min_train: int = 252,
                cost_levels=COST_LEVELS, spa_reps: int = 1000,
                threshold_pct=THRESHOLD_PCT, base_panel=None,
                n_shift: int | None = None):
    """실제 관문을 한 번 돌려 두 성분을 낸다 — `power_curves` 에 주입한다.

    ★보조 널을 뺀다★ 마르코프·블록은 `decisive: false` 라 **판정에 들어가지
    않는다**. 검정력 시행에서 빼면 564 → 264 백테스트로 줄어 1시행 ≈ 172초다.
    판정에 쓰이는 순환이동 전수와 SPA 는 그대로 둔다.
    """
    def runner(scale: float, seed: int) -> dict:
        sd = int(base_seed) + int(seed)
        if base_panel is None:
            p, why = panel_for(real=False, months=months, seed=sd,
                               scale=float(scale))
            if p is None:
                raise RuntimeError(f"합성 패널을 만들 수 없습니다: {why}")
        else:
            # ★실 패널은 반합성 주입으로 척도를 만든다★ 실 공분산·꼬리·자기상관을
            # 그대로 두고 국면 드리프트만 배율한다 — 합성에서 `scaled_profiles`
            # 가 하는 일과 같은 계약이라 `research_power` 가 양쪽에서 돈다.
            p = inject_regime_drift(base_panel, float(scale))
        names, R, dates, points = p.names, p.returns, p.dates, p.points
        rep = run(names, R, dates, points, model=model, rebalance=rebalance,
                  min_train=min_train, cost_levels=cost_levels,
                  n_markov=0, n_block=0, seed=sd, threshold_pct=threshold_pct,
                  spa_reps=spa_reps, provenance=p.provenance, n_shift=n_shift)
        v = rep["verdict"]
        return {"null_outside": v["null_outside"], "spa_ok": v["spa_ok"]}
    return runner


# ── ★개월 축 — 표본 길이가 관문을 구제하는가★ (M7-개월) ────────────────────
#: 사전등록된 개월 격자. 84 는 A3(`4279f1e`)에서 이미 쟀고, 전수=81 ≤ 83 이라
#: 널 상한 83 과 **비트 동일**하므로 그 셀을 그대로 재사용한다.
POWER_MONTHS = (120, 180, 240, 360)
#: ★널을 개월과 무관하게 고정한다★ 전수면 개월이 늘 때 널 해상도(1/(n+1))도 함께
#: 좋아져서 "개월 효과" 와 "널이 정밀해진 효과" 가 섞인다. 83 은 84개월의 전수(81)
#: 를 담을 수 있는 가장 작은 관례값이라 그 셀이 A3 와 같아진다.
POWER_N_SHIFT = 83


def summarize_months(by_months: dict[int, dict], *,
                     target_power: float = DEFAULT_TARGET_POWER) -> dict[str, Any]:
    """개월별 검정력 블록 → **개월 축 요약**. ★순수 함수다★.

    "목표 검정력에 처음 도달하는 지점" 규칙은 척도든 개월이든 같으므로
    `research_power.mde_from_curve` 를 `key="months"` 로 그대로 쓴다 — 새 판정
    규칙을 만들지 않는다.

    ★성분을 갈라 둔다★ A3 이 ④ 관문의 병목을 SPA 로 특정했으므로, 개월이 **어느
    성분을 움직이는지**가 이 측정의 요점이다. 셋을 뭉치면 그 답이 사라진다.

    ★개월마다 `n_eff` 가 다르다★ 패널이 달라지면 자산간 상관도 달라진다 —
    84개월 값을 재사용하면 유효 표본을 지어내는 것이다.
    """
    levels = sorted(int(m) for m in by_months)
    out_months: dict[str, Any] = {}
    for m in levels:
        blk = by_months[m] or {}
        comps = blk.get("by_component") or {}
        row: dict[str, Any] = {
            "months": m,
            "mde": blk.get("mde"), "power": blk.get("power"),
            "n_eff": blk.get("n_eff"),
            "reasons": dict(blk.get("reasons") or {}),
            **{c: {"power": (comps.get(c) or {}).get("power"),
                   "mde": (comps.get(c) or {}).get("mde")}
               for c in COMPONENTS},
        }
        # ★관문 결과를 지어내지 않는다★ 이것은 검정력 측정이지 판정이 아니다.
        # 그래서 묻는 것은 "이 표본 길이에서 관문이 **못 넘었다면** 그 실패가
        # 무엇을 뜻했겠는가" 다 — 그 답은 오직 검정력에만 달려 있다
        # (`underpowered` 인가 `evidence_of_no_effect` 인가). 이름에 `if_failed`
        # 를 박아 실제 판정으로 오독되지 않게 한다.
        p = (comps.get("conjunction") or {}).get("power", blk.get("power"))
        row["if_failed_verdict"] = classify(
            null_outside=False, spa_ok=False, power=p,
            target_power=target_power)["verdict"]
        for f in REQUIRED_FIELDS:
            row.setdefault(f, None)
            if row[f] is None and not (row["reasons"].get(f) or "").strip():
                row["reasons"][f] = ("이 개월 수준에서 산출하지 않았습니다")
        out_months[str(m)] = row

    def _curve(comp: str | None) -> list[dict]:
        return [{"months": m,
                 "rate": ((by_months[m].get("by_component") or {}).get(comp) or {}
                          ).get("power") if comp else by_months[m].get("power")}
                for m in levels]

    return {
        "target_power": float(target_power), "convention": True,
        "months_tested": levels,
        "minimum_detectable_months": mde_from_curve(
            _curve("conjunction"), target_power=target_power, key="months"),
        "minimum_detectable_months_by_component": {
            c: mde_from_curve(_curve(c), target_power=target_power, key="months")
            for c in COMPONENTS},
        "by_months": out_months,
    }


def measure_power_by_months(*, months_list=POWER_MONTHS, base_seed: int,
                            scales=(1.0,), seeds=POWER_SEEDS,
                            n_shift: int | None = POWER_N_SHIFT,
                            **kw) -> dict[str, Any]:
    """개월마다 `measure_power` 를 돌리고 개월 축 요약을 얹는다 (M7-개월)."""
    by: dict[int, dict] = {}
    for m in sorted(int(x) for x in months_list):
        by[m] = measure_power(months=m, base_seed=base_seed, scales=scales,
                              seeds=seeds, n_shift=n_shift, **kw)
        logger.info("개월 %d 완료: 검정력 %s", m, by[m].get("power"))
    out = summarize_months(by)
    out["blocks"] = {str(m): b for m, b in by.items()}
    out["preregistered"] = {
        "scales": [float(s) for s in scales], "seeds": list(seeds),
        "months": sorted(int(x) for x in months_list), "n_shift": n_shift,
        "note": ("널을 개월과 무관하게 고정한다 — 전수면 '개월 효과' 와 '널이 "
                 "정밀해진 효과' 가 섞인다. 84개월은 전수=81 ≤ 83 이라 A3 와 "
                 "비트 동일이다."),
    }
    return out


# ── CLI ────────────────────────────────────────────────────────────────────
def measure_power(*, months: int, base_seed: int, scales=POWER_SCALES,
                  seeds=POWER_SEEDS, spa_reps: int = 1000,
                  threshold_pct=THRESHOLD_PCT, base_panel=None,
                  n_shift: int | None = None, **kw) -> dict[str, Any]:
    """사전등록된 격자로 세 성분의 검정력을 재고 `power_report` 블록을 만든다.

    `n_eff` 는 **패널에서 측정한** 자산간 상관으로 낸다 — 순진한 자산×개월이
    독립 표본이 아니라는 사실을 수치로 만든다.
    """
    from scripts.t3_transmission import build_panel

    runner = gate_runner(months=months, base_seed=base_seed, base_panel=base_panel,
                         spa_reps=spa_reps, threshold_pct=threshold_pct,
                         n_shift=n_shift, **kw)
    curves = power_curves(runner, scales, seeds)

    if base_panel is None:
        names, R, dates, points, _b = build_panel(months=months, seed=base_seed)
    else:
        names, R, dates, points = (base_panel.names, base_panel.returns,
                                   base_panel.dates, base_panel.points)
    monthly = _monthly(R, dates)
    rho = rp.mean_pairwise_correlation(monthly)

    blocks = {c: rp.power_report(curve=curves[c], observed_scale=1.0,
                                 n_obs=len(points), n_assets=len(names),
                                 rho_bar=rho)
              for c in COMPONENTS}
    out = dict(blocks["conjunction"])
    out["by_component"] = blocks
    out["decisive_component"] = "conjunction"
    return out


# ── ★전략 용량 — 얼마까지 태울 수 있는가★ (P3) ────────────────────────────
#: 사전등록된 규모 격자(KRW). ★결과를 보고 바꾸지 않는다★ 위로 더 늘리면 √법칙의
#: 검량 범위 밖(참여율 > 1)을 답으로 적게 된다 — 1조에서 이미 최대 참여율 10.0 이다.
CAPACITY_SIZES = (1e9, 1e10, 1e11, 1e12)

#: 우위가 사라졌다고 부르는 기준. 주 통계가 0 이하 = 국면 팔이 정액 팔을 못 이긴다.
CAPACITY_RULE = "sharpe_diff <= 0"


def decisive_diff(diffs: dict[str, float | None]) -> float | None:
    """비용 수준별 주 통계 → ★우위를 대표하는 하나★. ★순수 함수다★.

    이 관문은 비용 수준을 **연언**으로 다룬다(팔이 통과하려면 셋 **모두**에서
    널을 넘어야 한다). 그 부정은 "어느 하나에서 무너진다" 이므로 우위가
    사라졌다고 부르는 기준도 **최솟값**이다. 하나를 골라 쓰면 그 선택이 용량을
    좌우한다 — 가장 낮은 비용만 보면 용량이 과대평가된다.

    ★미상은 0 도 최솟값도 아니다★ 한 수준이라도 미상이면 최솟값을 주장할 수
    없다(미상이 실은 그보다 작았을 수 있다). `None` 을 돌려준다.
    """
    if not diffs:
        return None
    vals = list(diffs.values())
    if any(v is None for v in vals):
        return None
    return min(float(v) for v in vals)


def summarize_capacity(by_size: dict[float, dict]) -> dict[str, Any]:
    """규모별 관문 결과 → ★용량 요약★. ★순수 함수다★.

    ★새 판정 규칙을 만들지 않는다★ "어떤 축에서 처음 기준을 넘는 지점" 은 척도
    (A3)·개월(M7)과 같은 문제이므로 `research_power.mde_from_curve` 를
    `key="portfolio_krw"` 로 그대로 쓴다. 우위 소멸을 도달로 부호화하면
    (`rate = 1.0 if sharpe_diff <= 0 else 0.0`, 목표 1.0) 미도달 시 `None` + 사유 ·
    `bracket` · `monotone` · `at_search_floor` 계약을 공짜로 얻는다.

    ★미상은 0 이 아니다★ 어느 규모에서 팔이 해결되지 않아 `sharpe_diff` 가
    `None` 이면 `rate` 도 `None` 이다 — 0 으로 읽으면 "우위가 살아 있다" 는
    하지 않은 관측이 되고, 1 로 읽으면 없는 한계를 만든다.
    """
    levels = sorted(float(k) for k in by_size)
    rows: dict[str, Any] = {}
    curve: list[dict[str, Any]] = []
    for size in levels:
        blk = by_size[size] or {}
        diff = blk.get("sharpe_diff")
        rows[repr(size)] = {
            "portfolio_krw": size,
            "sharpe_diff": diff,
            "sharpe_diff_by_cost": blk.get("sharpe_diff_by_cost"),
            "passed": blk.get("passed"),
            "verdict": blk.get("verdict"),
            "spa_p": blk.get("spa_p"),
            "percentile": blk.get("percentile"),
            "impact_bps_on": blk.get("impact_bps_on"),
            "impact_bps_off": blk.get("impact_bps_off"),
            "max_participation": blk.get("max_participation"),
            "beyond_model_range": blk.get("beyond_model_range"),
            "reason": blk.get("reason"),
        }
        curve.append({"portfolio_krw": size,
                      "rate": (None if diff is None else
                               (1.0 if float(diff) <= 0.0 else 0.0))})

    raw = mde_from_curve(curve, target_power=1.0, key="portfolio_krw")
    # `mde` 라는 이름은 이 축에서 오해를 부른다 — 뜻은 그대로 두고 이름만 바꾼다.
    limit = {k: v for k, v in raw.items() if k not in ("mde", "target_power")}
    limit["portfolio_krw"] = raw["mde"]
    limit["rule"] = CAPACITY_RULE
    # ★규칙은 빌려오되 어휘까지 빌려오지는 않는다★ `mde_from_curve` 의 미도달
    # 사유는 "목표 검정력에 도달하지 못했다" 라고 말한다 — 이 축에서는 검정력을
    # 잰 적이 없으므로 그대로 실으면 하지 않은 측정을 주장하는 문장이 된다.
    if limit["portfolio_krw"] is None and limit.get("searched_min") is not None:
        limit["reason"] = (
            f"탐색 범위({limit['searched_min']:.3g}~{limit['searched_max']:.3g} KRW)"
            f"에서 {CAPACITY_RULE} 이 되는 규모가 없습니다 — 이 범위 안에서는 "
            "우위가 사라지지 않습니다. ★탐색 범위를 답으로 쓰지 않습니다.★")

    # ★범위 밖을 결과 옆에 붙인다★ 참여율 > 1 인 규모의 충격 추정은 외삽이다.
    outside = [s for s in levels if rows[repr(s)]["beyond_model_range"]]
    return {
        "convention": True, "rule": CAPACITY_RULE,
        "sizes_tested": levels,
        "capacity_limit": limit,
        "beyond_model_range_sizes": outside,
        "beyond_model_range_note": (
            "이 규모들은 최대 참여율이 하루치 ADV 를 넘습니다 — √법칙이 검량되지 "
            "않은 영역이라 충격 추정이 외삽입니다." if outside else None),
        "by_size": rows,
    }


def measure_capacity(names, R, dates, points, *, sizes=CAPACITY_SIZES,
                     **kw) -> dict[str, Any]:
    """규모마다 **전체 관문**을 돌린다 — 규모당 ≈3분 (P3).

    ★규모를 가정하지 않고 쓸어서 측정값으로 바꾼다★ 임의의 기본값 하나가 주
    통계를 5~17% 움직이므로, 답해야 할 질문은 "얼마로 놓을까" 가 아니라
    "얼마까지 태울 수 있는가" 다(M7 이 개월 축에 한 것과 같은 규율).
    """
    from src.engine.market_impact import ImpactAssumptions

    by: dict[float, dict] = {}
    for size in sorted(float(x) for x in sizes):
        rep = run(names, R, dates, points,
                  impact=ImpactAssumptions(portfolio_krw=size), **kw)
        # ★규칙은 순수 함수에 있다★ (`decisive_diff`)
        diffs = {c: b["arms"][rs.ARM_ON].get(PRIMARY)
                 for c, b in rep["by_cost"].items()}
        decisive = decisive_diff(diffs)
        first = next(iter(rep["by_cost"].values()))
        on = first["arms"][rs.ARM_ON]
        off = first["arms"][rs.ARM_OFF]
        by[size] = {
            "sharpe_diff": decisive,
            "sharpe_diff_by_cost": diffs,
            "passed": rep["verdict"]["passed"],
            "verdict": rep["verdict"].get("verdict"),
            "spa_p": rep["spa"]["p_max"],
            "percentile": first["percentile"][PRIMARY],
            "impact_bps_on": on.get("impact_bps_mean"),
            "impact_bps_off": off.get("impact_bps_mean"),
            "max_participation": on.get("max_participation"),
            "beyond_model_range": on.get("beyond_model_range"),
            "reason": (None if decisive is not None else
                       "일부 비용 수준에서 주 통계가 미상입니다"),
        }
        logger.info("규모 %.0e 완료: %s=%s 통과=%s", size, PRIMARY,
                    by[size]["sharpe_diff"], by[size]["passed"])
    out = summarize_capacity(by)
    out["preregistered"] = {
        "sizes": [float(x) for x in sorted(sizes)], "rule": CAPACITY_RULE,
        "note": ("규모는 가정하지 않고 쓸어서 잰다 — 임의의 기본값 하나가 주 "
                 "통계를 5~17% 움직인다. 우위 소멸은 비용 수준을 가로지르는 "
                 "주 통계의 **최솟값**으로 읽는다(이 관문이 비용 수준을 연언으로 "
                 "다루므로 그 부정은 '어느 하나에서 무너진다' 이다). ★관문 통과 "
                 "여부로 한계를 정의하지 않는다★ — A3 에서 84개월 관문은 규모와 "
                 "무관하게 이미 통과하지 못하므로(병목은 SPA) 그 기준은 공허하다."),
    }
    return out


def _monthly(R, dates):
    """월 합계 — `regime_signal.monthly_matrix` 를 재사용한다(단일 출처)."""
    from src.engine.regime_signal import monthly_matrix
    return monthly_matrix(R, dates)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=84)
    ap.add_argument("--model", default="bl")
    ap.add_argument("--rebalance", default="M")
    ap.add_argument("--min-train", type=int, default=252)
    ap.add_argument("--n-shift", type=int, default=None, help="기본: 전수")
    ap.add_argument("--n-markov", type=int, default=50)
    ap.add_argument("--n-block", type=int, default=50)
    ap.add_argument("--spa-reps", type=int, default=1000)
    ap.add_argument("--no-spa", action="store_true")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--report", default=None)
    ap.add_argument("--power", action="store_true",
                    help="사전등록된 격자로 세 성분의 검정력을 잰다 (A3, 오래 걸린다)")
    ap.add_argument("--power-months", default=None,
                    help="개월 축 검정력 (M7). 예: 120,180,240,360 (오래 걸린다)")
    ap.add_argument("--real", action="store_true",
                    help="실 패널로 돌린다 (M9). 실데이터가 없으면 ★거부★한다")
    ap.add_argument("--codes", default="", help="--real 일 때 쓸 종목코드(쉼표 구분)")
    ap.add_argument("--as-of", default=None)
    ap.add_argument("--capacity", default=None,
                    help="전략 용량 곡선 (P3). 예: 1e9,1e10,1e11,1e12 (규모당 ≈3분)")
    args = ap.parse_args()

    base, why = panel_for(real=args.real, months=args.months,
                          codes=[c for c in args.codes.split(",") if c],
                          as_of=args.as_of)
    if base is None:
        # ★합성으로 대체하지 않는다★ 빈 결과보다 나쁜 것은 지어낸 결과다.
        print("패널을 만들 수 없어 중단합니다 — 합성으로 대체하지 않습니다:")
        for r in why:
            print(f"  · {r}")
        return 2
    names, R, dates, points = base.names, base.returns, base.dates, base.points
    rep = run(names, R, dates, points, model=args.model, rebalance=args.rebalance,
              min_train=args.min_train, n_shift=args.n_shift,
              n_markov=args.n_markov, n_block=args.n_block, seed=args.seed,
              run_spa=not args.no_spa, spa_reps=args.spa_reps,
              provenance=base.provenance)

    if args.capacity:
        rep["capacity"] = measure_capacity(
            names, R, dates, points, model=args.model, rebalance=args.rebalance,
            min_train=args.min_train, n_shift=args.n_shift,
            n_markov=args.n_markov, n_block=args.n_block, seed=args.seed,
            run_spa=not args.no_spa, spa_reps=args.spa_reps,
            provenance=base.provenance,
            sizes=[float(x) for x in args.capacity.split(",") if x.strip()])

    if args.power_months:
        months_list = [int(x) for x in args.power_months.split(",") if x.strip()]
        rep["power_by_months"] = measure_power_by_months(
            months_list=months_list, base_seed=20260825, model=args.model,
            rebalance=args.rebalance, min_train=args.min_train,
            spa_reps=args.spa_reps)

    if args.power:
        block = measure_power(months=args.months, base_seed=20260825,
                              base_panel=(base if args.real else None),
                              model=args.model, rebalance=args.rebalance,
                              min_train=args.min_train, spa_reps=args.spa_reps)
        rep["power"] = block
        rep["verdict"] = decide_verdict(
            {c: {"percentile": b["percentile"][PRIMARY], "side": b["side"]}
             for c, b in rep["by_cost"].items()},
            rep["spa"]["p_max"], power_block=block)

    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=2, sort_keys=True,
                      default=str)
        print(f"리포트: {args.report}")

    p = rep["panel"]
    print(f"등급 {rep['evidence_grade']} ({rep['evidence_grade_reason']}) · 패널 {p['n_assets']}자산 {p['n_months']}개월 "
          f"· 런 {p['n_runs']}개(평균 {p['mean_run_length']})")
    print(f"★주 통계★ {PRIMARY} · 주 널 {rep['preregistered']['primary_null']} "
          f"· 임계 {rep['preregistered']['threshold_pct']}(관례)")
    for c, b in rep["by_cost"].items():
        a = b["arms"]
        print(f"\n── 비용 {c}bps ──")
        for arm in rs.ARMS:
            st = a[arm]
            print(f"  {arm:<16} sharpe={str(st.get('sharpe')):>7} "
                  f"{PRIMARY}={str(st.get(PRIMARY)):>9} "
                  f"turnover={str(st.get('avg_turnover_pct')):>7} "
                  f"prob_source={st.get('prob_source')}")
        n = b["null"][rs.NULL_SHIFT]["stats"]
        print(f"  널({rs.NULL_SHIFT}, n={n.get('n')}): min={n.get('min')} "
              f"p50={n.get('p50')} max={n.get('max')} → 분위={b['percentile'][PRIMARY]} "
              f"방향={b['side']} 널밖={b['beyond_null_range']}")
    print(f"\nSPA p(비용별) = "
          f"{ {k: v['p'] for k, v in rep['spa']['by_cost'].items()} } "
          f"· 최대 {rep['spa']['p_max']}")
    m = rep["mcs"]
    print(f"MCS(보조·판정 아님): 포함={m['included']} 제외={m['excluded']} "
          f"{m['reason'] or ''}")
    v = rep["verdict"]
    print(f"★판정★ 통과={v['passed']} · 널밖={v['null_outside']} · SPA={v['spa_ok']}")
    for w in v["why"]:
        print("   ·", w)

    cap = rep.get("capacity")
    if cap:
        print(f"\n★전략 용량★ 규칙 {cap['rule']} · 규모 {len(cap['sizes_tested'])}개")
        print(f"{'규모(KRW)':>12} {'sharpe_diff':>12} {'통과':>5} {'충격on':>8} "
              f"{'충격off':>8} {'최대참여율':>9}  범위밖")
        for s_ in cap["sizes_tested"]:
            r = cap["by_size"][repr(s_)]
            print(f"{s_:>12.0e} {str(r['sharpe_diff']):>12} "
                  f"{str(r['passed']):>5} {str(r['impact_bps_on']):>8} "
                  f"{str(r['impact_bps_off']):>8} "
                  f"{str(r['max_participation']):>9}  {r['beyond_model_range']}")
        lim = cap["capacity_limit"]
        print(f"  ★용량 한계★ = {lim['portfolio_krw']} · bracket={lim['bracket']} "
              f"· 단조={lim['monotone']}")
        if lim["portfolio_krw"] is None:
            print(f"  사유: {lim['reason']}")
        if cap["beyond_model_range_sizes"]:
            print(f"  ★범위 밖★ {cap['beyond_model_range_sizes']} — "
                  f"{cap['beyond_model_range_note']}")

    pbm = rep.get("power_by_months")
    if pbm:
        print(f"\n★개월 축★ 목표 검정력 {pbm['target_power']} (관례) · "
              f"널 {pbm['preregistered']['n_shift']}개 고정")
        print(f"{'개월':>5} {'conj':>6} {'null':>6} {'spa':>6} {'n_eff':>8}  실패했다면")
        for k in sorted(pbm["by_months"], key=int):
            r = pbm["by_months"][k]
            print(f"{k:>5} {str(r['conjunction']['power']):>6} "
                  f"{str(r['null_only']['power']):>6} "
                  f"{str(r['spa_only']['power']):>6} "
                  f"{str(r['n_eff']):>8}  {r['if_failed_verdict']}")
        m = pbm["minimum_detectable_months"]
        print(f"  ★최소 검출 기간★ = {m['mde']} 개월 · bracket={m['bracket']} "
              f"· 단조={m['monotone']}")
        if m["mde"] is None:
            print(f"  사유: {m['reason']}")
        for c, mm in pbm["minimum_detectable_months_by_component"].items():
            print(f"    {c:>12}: {mm['mde']} (bracket={mm['bracket']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
