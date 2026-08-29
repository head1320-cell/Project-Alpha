"""기업 뷰 ★음성 통제 하네스★ — 파이프라인이 도는 것과 신호가 있는 것은 다르다 (S6)
==============================================================================
설계: `docs/superpowers/specs/2026-08-28-investment-decision-layer-design.md` §2.3
변환: `src/engine/company_view_controls.py`

S1~S5 의 증거는 전부 **파이프라인이 돈다**는 것이었다. 이 하네스가 그 다음 질문을
연다 — ★뷰의 내용을 지우거나 뒤섞어도 같은 일이 일어나는가?★

## ★이 하네스가 답할 수 없는 것★

CLAUDE.md 의 네 질문 중 **② 전달 안정성**만 답한다. ③ 예측 스킬과 ④ 경제적 가치는
**표본외 수익이 있어야** 답할 수 있는데, 기업 뷰는 `research_usage: forward_only`
(빈티지 재무 없음)라 과거 시뮬레이션에 넣을 수 없다. 그래서 보고서의 `claims` 는
그 둘을 `None` + 사유로 **구조적으로** 비워 둔다 — 산문이 아니라 값으로.

## 팔

`off` 하나로는 부족하다(`t3_transmission` 의 `-open`/`-const` 와 같은 이유):
`neutral` 은 **단면 변동만** 지우고, `shuffled` 는 **자산↔내용 짝짓기만** 지우며,
`evidence-stripped` 는 **Ω 채널만** 지운다. 셋이 서로 다른 것을 가른다.

## 실측이 예고하는 결과 (mock 8종목, BL)

`corr(Q, Δw)`: 진짜 팔 **0.808** vs 셔플 널 **min 0.244 · p50 0.721 · max 0.821**.
★무작위로 재배치한 뷰도 거의 같은 강도로 전달된다★ — 전달이 잘 된다는 것은 신호가
있다는 증거가 아니다. 그리고 신뢰도가 전부 포화(50.0)해 `evidence-stripped` 가
`company-on` 과 **바이트 동일**하다. 두 사실 모두 보고서가 **신고**한다.

사용:
    python3 scripts/company_view_control.py --report out.json
    python3 scripts/company_view_control.py --tickers 005930,000660 --n-perm 500
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("KIS_USE_MOCK", "1")

from src.engine import company_view_controls as cvc  # noqa: E402

#: 기본 유니버스 — 실측에 쓴 것과 같다(mock 은 어떤 코드에도 재무를 합성한다).
DEFAULT_TICKERS = ("005930", "000660", "035420", "051910",
                   "005380", "012330", "068270", "105560")

#: 기준선이 균등가중에서 이만큼도 안 떨어져 있으면 **퇴화**로 본다. 무뷰 해가
#: 균등이면 "뷰가 움직였다" 는 거리가 전부 균등 대비 거리라 약한 증거다.
DEGENERATE_TOL = 1e-6

#: ★관례이지 측정치가 아니다★ 진짜 팔이 널의 이 바깥에 있으면 "구분된다" 고 적는다.
DEFAULT_THRESHOLD = (5.0, 95.0)

#: 널에서 분위를 매기는 통계들.
NULL_STATS = ("w_l1_vs_off", "max_weight", "enb", "corr_q_dw", "turnover_pct")

_BENEFIT_NOTE = (
    "★편익은 자기 사후분포 아래서 측정된다★ `utility(w_target, μ) − "
    "utility(w_current, μ)` 의 μ 가 바로 그 목표를 고른 μ 이므로 이득이 구조적으로 "
    "보장된다. 그래서 셔플한 팔도 거의 언제나 `trade` 를 낸다 — 판단이 갈리지 "
    "않는다는 사실을 신호 부재의 증거로 읽기 전에 이 구조를 먼저 보십시오.")

_CLAIM_REASON = ("표본외 수익이 없습니다 — 기업 뷰는 research_usage:forward_only"
                 "(빈티지 재무 없음)라 과거 시뮬레이션에 넣을 수 없고, 이 하네스는 "
                 "전달 안정성(②)만 잽니다.")


# ── 통계 ────────────────────────────────────────────────────────────────────
def _corr(x: list[float], y: list[float]) -> float | None:
    """★상관을 지어내지 않는다★ 한쪽이라도 상수면 정의되지 않는다 → `None`."""
    if len(x) < 2 or len(x) != len(y):
        return None
    a, b = np.asarray(x, float), np.asarray(y, float)
    if a.std() <= 1e-12 or b.std() <= 1e-12:
        return None
    return round(float(np.corrcoef(a, b)[0, 1]), 6)


def baseline_block(w_off: np.ndarray) -> dict:
    """무뷰 해가 쓸 만한 기준선인가 — ★퇴화를 숨기지 않는다★"""
    n = len(w_off)
    dev = float(np.abs(np.asarray(w_off, float) - 1.0 / n).max()) if n else 0.0
    degenerate = dev <= DEGENERATE_TOL
    return {
        "weights": [round(float(x), 6) for x in w_off],
        "max_dev_from_equal": round(dev, 8),
        "degenerate": degenerate,
        "reason": ("무뷰 해가 균등가중과 사실상 같습니다 — 대칭적인 합성 수익률에서 "
                   "흔히 일어납니다. 이 기준선 대비 거리는 약한 증거입니다."
                   if degenerate else None),
    }


def weight_stats(w: np.ndarray, w_off: np.ndarray, S: np.ndarray,
                 views: list[dict] | None) -> dict:
    """가중치 기하 — 팔이 포트폴리오를 **어디로** 옮겼는가."""
    from src.engine.allocation_studio import effective_number_of_bets

    d = np.asarray(w, float) - np.asarray(w_off, float)
    return {
        "w_l1_vs_off": round(float(np.abs(d).sum()), 6),
        "max_weight": round(float(np.max(w)), 6),
        "n_nonzero": int((np.asarray(w, float) > 1e-6).sum()),
        "enb": round(float(effective_number_of_bets(np.asarray(w, float), S)), 6),
        # ★전달 식별성★ 뷰의 부호 있는 크기가 실제로 그 자산의 비중을 움직였는가.
        "corr_q_dw": _corr(cvc.signed_q(views), [float(x) for x in d]),
    }


def decision_stats(names: list[str], w_cur: np.ndarray, w_arm: np.ndarray,
                   mu: np.ndarray, sigma: np.ndarray,
                   portfolio_value: float, model: str = "bl") -> dict:
    """★판단 층★ — 가중치가 아니라 **결정**이 팔에 따라 달라지는가.

    셔플해도 `trade`/`hold` 가 같다면 결정 계층이 신호에 무등감하다는 뜻이고,
    그것은 가중치 거리로는 보이지 않는다. ★저장하지 않는다★(`persist=False`) —
    연구 하네스가 결정 테이블을 채우면 안 된다.
    """
    from src.engine.investment_decision import decide

    cur = {n: round(float(x) * 100.0, 6) for n, x in zip(names, w_cur, strict=True)}
    tgt = {n: round(float(x) * 100.0, 6) for n, x in zip(names, w_arm, strict=True)}
    # ★목표 출처를 선언한다★ 이 하네스의 목표는 `optimize` 가 고른 해이고, 편익은
    # **그 해를 고른 바로 그 μ** 로 잰다. 선언하지 않으면 결정 계층이 판정할 수
    # 없어 `None`(미상)이 되고, "모든 팔이 trade" 의 이유가 리포트에서 사라진다.
    d = decide(cur, tgt, portfolio_value=portfolio_value, names=names,
               mu=np.asarray(mu, float), sigma=np.asarray(sigma, float),
               evidence={"target_source": f"optimize:{model}"}, persist=False)
    band = d.get("band") or {}
    cost = d.get("cost") or {}
    prov = (d.get("benefit") or {}).get("provenance") or {}
    return {
        "decision": d.get("decision"),
        "reason": d.get("reason"),
        # ★셔플 팔이 전부 trade 인 이유★ — 편익이 자기 사후분포 아래서 측정된다.
        "self_referential": prov.get("self_referential"),
        "turnover_pct": cost.get("turnover_pct"),
        "net_pct": d.get("net_pct"),
        "max_gap_pct": d.get("max_gap_pct"),
        "n_outside_band": len(band.get("outside") or []),
    }


def _flat(stats: dict) -> dict:
    """팔 통계에서 널에 쓸 스칼라만 뽑는다."""
    out = dict(stats.get("weights") or {})
    dec = stats.get("decision") or {}
    out["turnover_pct"] = dec.get("turnover_pct")
    return out


def _side(pct: float, lo: float, hi: float) -> str:
    """진짜 팔이 널의 **어느 쪽**에 있는가 — `below` · `inside` · `above`.

    ★"구분된다" 가 "좋다" 로 읽히지 않게 한다.★ 실측에서 진짜 팔은 셔플 팔들보다
    포트폴리오를 **덜** 움직였다(분위 0.0). 방향을 안 적으면 그 사실이 "통제를
    통과했다" 로 둔갑한다.

    ★분위로 판정한다 — 값과 p5/p95 를 따로 비교하지 않는다★ 처음에는 값을
    분위수와 비교했는데, **동률이 있으면 둘이 어긋난다**: 분위가 5 미만인데 값은
    p5 와 정확히 같을 수 있다(작은 유니버스에서 실제로 일어났다). 그러면 같은
    보고서 안에서 `distinguishable=True` 인데 `side="inside"` 가 된다. 하나의
    비교에서 둘 다 파생시켜 어긋날 수 없게 한다. 값 기준의 독립적인 진술은
    `beyond_null_range` 가 따로 맡는다.
    """
    from src.engine.null_stats import side_of
    return side_of(pct, lo, hi)


# ── 하네스 ──────────────────────────────────────────────────────────────────
def run(names: list[str], R: np.ndarray, views: list[dict], *,
        model: str = "bl", w_current: np.ndarray | None = None,
        portfolio_value: float = 1e8, n_perm: int = 200, seed: int = 7,
        threshold_pct: tuple[float, float] = DEFAULT_THRESHOLD,
        delta: float = 2.5, tau: float = 0.05) -> dict:
    """팔을 전부 돌리고 널 분포와 분위를 낸다. ★I/O 없음★ — 입력을 그대로 받는다."""
    from src.engine.allocation_studio import optimize

    rng = np.random.default_rng(int(seed))
    n = len(names)
    w_cur = (np.full(n, 1.0 / n) if w_current is None
             else np.asarray(w_current, float))

    def solve(arm_v):
        o = optimize(model, names, R, delta=delta, tau=tau, company_views=arm_v)
        return (np.asarray(o["weights"], float), np.asarray(o["sigma_annual"], float),
                np.asarray(o["mu_used"], float))

    w_off, S, mu_off = solve(None)

    arms: dict[str, dict] = {}
    for arm in (cvc.ARM_OFF, cvc.ARM_ON, cvc.ARM_NEUTRAL, cvc.ARM_STRIPPED):
        av = cvc.arm_views(views, arm)
        w, _, mu = solve(av)
        arms[arm] = {
            "n_views": len(av or []),
            "weights": weight_stats(w, w_off, S, av),
            "decision": decision_stats(names, w_cur, w, mu, S, portfolio_value,
                                       model),
        }

    # ── 널: 셔플 팔 ────────────────────────────────────────────────────────
    perms, enumerated = cvc.permutations_for(len(views), n_perm, rng)
    draws: list[dict] = []
    # ★판단도 널에서 센다★ 셔플 팔이 몇 번이나 `trade` 를 냈는지가, 결정 계층이
    # 신호에 반응하는지에 대한 **직접적인** 답이다 — 가중치 거리로는 안 보인다.
    null_decisions: dict[str, int] = {}
    for p in perms:
        av = cvc.arm_views(views, cvc.ARM_SHUFFLED, p)
        w, _, mu = solve(av)
        dec = decision_stats(names, w_cur, w, mu, S, portfolio_value)
        draws.append(_flat({"weights": weight_stats(w, w_off, S, av),
                            "decision": dec}))
        null_decisions[str(dec.get("decision"))] = (
            null_decisions.get(str(dec.get("decision")), 0) + 1)

    null: dict[str, dict] = {}
    pct: dict[str, float | None] = {}
    real = _flat(arms[cvc.ARM_ON])
    for stat in NULL_STATS:
        xs = [d[stat] for d in draws if d.get(stat) is not None]
        if not xs:
            null[stat] = {"n": 0, "reason": "널 표본이 없습니다"}
            pct[stat] = None
            continue
        a = np.asarray(xs, float)
        null[stat] = {"n": int(a.size),
                      "min": round(float(a.min()), 6),
                      "p5": round(float(np.percentile(a, 5)), 6),
                      "p50": round(float(np.median(a)), 6),
                      "p95": round(float(np.percentile(a, 95)), 6),
                      "max": round(float(a.max()), 6)}
        pct[stat] = (cvc.percentile_of(real[stat], xs)
                     if real.get(stat) is not None else None)

    lo, hi = float(threshold_pct[0]), float(threshold_pct[1])
    by_stat: dict[str, dict | None] = {}
    for st in NULL_STATS:
        if pct.get(st) is None or real.get(st) is None or not null[st].get("n"):
            by_stat[st] = None
            continue
        v = float(real[st])
        by_stat[st] = {
            "distinguishable": bool(pct[st] < lo or pct[st] > hi),
            # ★방향을 적는다★ 덜 움직인 것과 더 움직인 것은 다른 사실이다.
            "side": _side(float(pct[st]), lo, hi),
            # ★분위보다 강한 진술★ 널의 **범위 밖**인가. 꼬리에 겨우 걸친 것과
            # 아예 널이 도달하지 못한 것은 증거의 세기가 다르다.
            "beyond_null_range": bool(v < float(null[st]["min"])
                                      or v > float(null[st]["max"])),
        }

    # ── 무등가 채널 ────────────────────────────────────────────────────────
    inert = []
    if cvc.is_inert(cvc.arm_views(views, cvc.ARM_ON),
                    cvc.arm_views(views, cvc.ARM_STRIPPED)):
        inert.append({
            "arm": cvc.ARM_STRIPPED,
            "reason": ("신뢰도가 이미 전부 중립값과 같아 이 팔이 company-on 과 "
                       "동일한 입력입니다 — Ω 채널이 이 표본에서 아무 일도 하지 "
                       "않습니다(S4 가 예고한 포화)."),
        })

    any_mock = any(bool(v.get("is_mock")) for v in views)
    decisions = {a: (b["decision"] or {}).get("decision") for a, b in arms.items()}

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": model, "seed": int(seed), "n_assets": n, "universe": list(names),
        "n_views": len(views),
        # ★어느 질문에 답했는지 밝힌다★ (CLAUDE.md §2)
        "question_answered": "transmission_stability",
        "claims": {"predictive_skill": None, "economic_value": None,
                   "reason": _CLAIM_REASON},
        # ★등급은 파생한다★ 손으로 적지 않는다.
        "evidence_grade": "E0" if any_mock else "E3",
        "baseline": baseline_block(w_off),
        "arms": arms,
        "arm_decisions": decisions,
        # ★가능한 치환 수를 함께 싣는다★ 5개뿐인 널에서 나온 분위와 40,319개에서
        # 나온 분위는 같은 숫자라도 뜻이 다르다.
        "null": {"arm": cvc.ARM_SHUFFLED, "n_permutations": len(perms),
                 "n_distinct_possible": (0 if len(views) < 2
                                         else math.factorial(len(views)) - 1),
                 "enumerated": enumerated, "stats": null},
        "percentile_of_real": pct,
        "null_decisions": null_decisions,
        "real_decision": (arms[cvc.ARM_ON]["decision"] or {}).get("decision"),
        # ★"모든 팔이 trade" 를 리포트가 스스로 설명한다★
        "benefit_self_referential": (arms[cvc.ARM_ON]["decision"] or {}).get(
            "self_referential"),
        "benefit_note": _BENEFIT_NOTE,
        "verdict": {"threshold_pct": [lo, hi], "convention": True,
                    "by_stat": by_stat,
                    "note": ("임계치는 **관례**이지 측정치가 아닙니다. 분위가 "
                             "관측값이고 판정은 임계치를 바꾸면 뒤집힙니다.")},
        "inert_channels": inert,
    }


def _load(tickers: list[str], lookback: int, n_mc: int):
    """유니버스와 뷰 — ★프로덕션 로더를 그대로 탄다★"""
    from src.api.allocation_routes import _load_clean_returns
    from src.engine.company_views import company_views, prices_for

    returns, _bench, _excl, _cov = _load_clean_returns(tickers, "KOSPI", lookback)
    if returns is None or len(returns.columns) < 2:
        return None, None, None, {"reason": "분석 가능한 자산이 2개 미만입니다"}
    names = list(returns.columns)
    prices, _src = prices_for(names)
    views, reasons = company_views(names, prices, n=n_mc)
    return names, returns.values, views, reasons


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", default=",".join(DEFAULT_TICKERS))
    ap.add_argument("--model", default="bl")
    ap.add_argument("--lookback", type=int, default=400)
    ap.add_argument("--n-mc", type=int, default=500, help="밸류에이션 표본 수")
    ap.add_argument("--n-perm", type=int, default=200)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--low", type=float, default=DEFAULT_THRESHOLD[0])
    ap.add_argument("--high", type=float, default=DEFAULT_THRESHOLD[1])
    ap.add_argument("--report", default=None)
    args = ap.parse_args()

    names, R, views, reasons = _load(
        [t.strip() for t in args.tickers.split(",") if t.strip()],
        args.lookback, args.n_mc)
    if names is None:
        print(json.dumps(reasons, ensure_ascii=False))
        return 1
    if len(views) < 2:
        print(json.dumps({"error": True, "n_views": len(views or []),
                          "reason": "뷰가 2개 미만이라 셔플 널을 만들 수 없습니다",
                          "view_reasons": reasons}, ensure_ascii=False))
        return 1

    rep = run(names, R, views, model=args.model, n_perm=args.n_perm,
              seed=args.seed, threshold_pct=(args.low, args.high))
    rep["view_reasons"] = {k: v.get("kind") for k, v in (reasons or {}).items()}

    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=2, sort_keys=True)
        print(f"리포트: {args.report}")

    print(f"등급 {rep['evidence_grade']} · 뷰 {rep['n_views']}개 · "
          f"널 {rep['null']['n_permutations']}회"
          f"{' (전수)' if rep['null']['enumerated'] else ''}")
    if rep["baseline"]["degenerate"]:
        print("★기준선 퇴화★", rep["baseline"]["reason"])
    for ch in rep["inert_channels"]:
        print(f"★무등가 채널★ {ch['arm']} — {ch['reason']}")
    print("팔별 판단:", rep["arm_decisions"])
    print("셔플 널의 판단 분포:", rep["null_decisions"],
          "· 진짜 팔:", rep["real_decision"])
    for stat in NULL_STATS:
        p = rep["percentile_of_real"].get(stat)
        v = rep["verdict"]["by_stat"].get(stat) or {}
        print(f"  {stat:<14} 분위={p!s:>8}  구분={v.get('distinguishable')}"
              f"  방향={v.get('side')}  널범위밖={v.get('beyond_null_range')}")
    print("★이 하네스는 예측 스킬·경제적 가치에 답하지 않는다★", _CLAIM_REASON)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
