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
from src.engine.research_verdict import (  # noqa: E402
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


def _sharpe(daily: np.ndarray) -> float | None:
    """일수익 → 연율 Sharpe, ★전정밀도★. 표본이 없거나 분산이 0 이면 `None`."""
    if daily.size < 2:
        return None
    sd = float(daily.std(ddof=1))
    if not np.isfinite(sd) or sd <= 0:
        return None
    return round(float(daily.mean() / sd * np.sqrt(252.0)), 8)


def backtest(names, R, dates, regime, *, model: str, cost_bps: float,
             rebalance: str, min_train: int) -> dict:
    """`walk_forward` 한 번 — 요약 지표 + 일수익 + 국면 계약 신고."""
    from src.engine.allocation_backtest import walk_forward

    out = walk_forward(names, R, dates, model=model, rebalance=rebalance,
                       min_train=min_train, cost_bps=cost_bps, regime=regime)
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
        # ★계약 신고를 결과 옆에 붙인다★ 하드 팔은 확률 계약을 통과하지 않는다.
        "prob_source": last.get("prob_source"),
        "prob_usage": last.get("prob_usage"),
        "daily": daily,
    }


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
        spa_reps: int = 1000, panel_is_synthetic: bool = True) -> dict:
    """팔과 널을 전부 돌리고 사전등록된 규칙으로 판정한다.

    `n_shift=None` 이면 순환이동을 **전수** 돈다(주 널). 보조 널(마르코프·블록)은
    견고성 확인용이고 판정에 쓰지 않는다.
    """
    rng = np.random.default_rng(int(seed))
    kw = {"model": model, "rebalance": rebalance, "min_train": min_train}

    shift_ks, enumerated = rs.shifts_for(len(points),
                                         10**9 if n_shift is None else int(n_shift),
                                         rng)
    by_cost: dict[str, dict] = {}
    spa_inputs: dict[str, dict] = {}

    for cost in cost_levels:
        off = backtest(names, R, dates, None, cost_bps=float(cost), **kw)
        arms: dict[str, dict] = {}
        for arm in rs.ARMS:
            bt = (off if arm == rs.ARM_OFF
                  else backtest(names, R, dates, arm_regime(points, arm),
                                cost_bps=float(cost), **kw))
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
            for i, k in enumerate(ks):
                sur = rs.surrogate_path(points, method, np.random.default_rng(
                    int(seed) + 1000 * (i + 1)), k=(k if method == rs.NULL_SHIFT else None))
                bt = backtest(names, R, dates,
                              {"points": sur, "weighting": "hard"},
                              cost_bps=float(cost), **kw)
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
        "evidence_grade": "E0" if panel_is_synthetic else "E3",
        "revision_bias": dict(_REVISION_BIAS),
        "panel": {"n_assets": len(names), "n_obs": int(np.asarray(R).shape[0]),
                  "n_months": len(points), "n_runs": rs.n_runs(points),
                  "mean_run_length": round(float(np.mean(rs.run_lengths(points))), 4)
                  if points else None,
                  "marginal": rs.marginal(points)},
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
                threshold_pct=THRESHOLD_PCT):
    """실제 관문을 한 번 돌려 두 성분을 낸다 — `power_curves` 에 주입한다.

    ★보조 널을 뺀다★ 마르코프·블록은 `decisive: false` 라 **판정에 들어가지
    않는다**. 검정력 시행에서 빼면 564 → 264 백테스트로 줄어 1시행 ≈ 172초다.
    판정에 쓰이는 순환이동 전수와 SPA 는 그대로 둔다.
    """
    from scripts.t3_transmission import build_panel

    def runner(scale: float, seed: int) -> dict:
        sd = int(base_seed) + int(seed)
        names, R, dates, points, _b = build_panel(months=months, seed=sd,
                                                  scale=float(scale))
        rep = run(names, R, dates, points, model=model, rebalance=rebalance,
                  min_train=min_train, cost_levels=cost_levels,
                  n_markov=0, n_block=0, seed=sd, threshold_pct=threshold_pct,
                  spa_reps=spa_reps)
        v = rep["verdict"]
        return {"null_outside": v["null_outside"], "spa_ok": v["spa_ok"]}
    return runner


# ── CLI ────────────────────────────────────────────────────────────────────
def _panel(months: int):
    from scripts.t3_transmission import build_panel
    names, R, dates, points, _beta = build_panel(months=months)
    return names, R, dates, points


def measure_power(*, months: int, base_seed: int, scales=POWER_SCALES,
                  seeds=POWER_SEEDS, spa_reps: int = 1000,
                  threshold_pct=THRESHOLD_PCT, **kw) -> dict[str, Any]:
    """사전등록된 격자로 세 성분의 검정력을 재고 `power_report` 블록을 만든다.

    `n_eff` 는 **패널에서 측정한** 자산간 상관으로 낸다 — 순진한 자산×개월이
    독립 표본이 아니라는 사실을 수치로 만든다.
    """
    from scripts.t3_transmission import build_panel

    runner = gate_runner(months=months, base_seed=base_seed,
                         spa_reps=spa_reps, threshold_pct=threshold_pct, **kw)
    curves = power_curves(runner, scales, seeds)

    names, R, dates, points, _b = build_panel(months=months, seed=base_seed)
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
    args = ap.parse_args()

    names, R, dates, points = _panel(args.months)
    rep = run(names, R, dates, points, model=args.model, rebalance=args.rebalance,
              min_train=args.min_train, n_shift=args.n_shift,
              n_markov=args.n_markov, n_block=args.n_block, seed=args.seed,
              run_spa=not args.no_spa, spa_reps=args.spa_reps)

    if args.power:
        block = measure_power(months=args.months, base_seed=20260825,
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
    print(f"등급 {rep['evidence_grade']} · 패널 {p['n_assets']}자산 {p['n_months']}개월 "
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
