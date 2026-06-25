"""매크로 추천 엔진 — 현 국면에 유리한 자산배분 전략 추천 (규칙 + 성과 + AI 서술)
==========================================================================
3종 종합:
  ① 규칙: regime_analyzer 4국면 + Stress → 전략 아키타입 적합도(RegimeAdaptiveAllocator 사상).
  ② 성과: 각 전략의 현 배분을 트레일링 12개월 수익률에 적용(실 ETF 시세 — GCP, 샌드박스 mock).
  ③ AI 서술: ANTHROPIC_API_KEY 있으면 Claude로 근거 설명, 없으면 규칙 기반 요약(정직).
산출: 국면·사이클·stress + 13전략 랭킹(composite) + 최상위 추천 + 서술 + 백테스터 이식 힌트.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# 전략 → 아키타입
_ARCHETYPE: dict[str, str] = {
    # 모멘텀 13
    "classic_dm": "aggressive", "accel_dm": "aggressive", "vaa": "aggressive", "daa": "aggressive",
    "permanent": "defensive", "laa": "defensive", "gtaa": "defensive", "paa": "defensive",
    "bond_dynamic": "income", "raa": "income",
    "composite_dm": "diversified", "faa": "diversified", "aaa": "diversified",
    # 리스크·최적화 9
    "min_var": "defensive",
    "max_sharpe": "aggressive", "kelly": "aggressive",
    "risk_parity": "diversified", "hrp": "diversified", "max_div": "diversified",
    "black_litterman": "diversified", "managed_futures": "diversified", "equal_weight": "diversified",
}
# 4국면 × 아키타입 적합도(0~1)
_FIT: dict[str, dict[str, float]] = {
    "Reflation":    {"aggressive": 1.0, "diversified": 0.75, "income": 0.45, "defensive": 0.30},
    "Overheating":  {"aggressive": 0.70, "diversified": 0.80, "income": 0.55, "defensive": 0.60},
    "Stagflation":  {"aggressive": 0.20, "diversified": 0.60, "income": 0.70, "defensive": 1.00},
    "Disinflation": {"aggressive": 0.45, "diversified": 0.70, "income": 1.00, "defensive": 0.85},
}
_QUAD_KR = {"Reflation": "리플레이션(성장↑·물가↓)", "Overheating": "과열(성장↑·물가↑)",
            "Stagflation": "스태그플레이션(성장↓·물가↑)", "Disinflation": "디스인플레이션(성장↓·물가↓)"}


def _quadrant(state) -> str:
    name = (getattr(state, "regime", "") or "").lower()
    for q in ("reflation", "overheating", "stagflation", "disinflation"):
        if q in name:
            return q.capitalize()
    g = getattr(state, "growth_axis", 0) or 0
    i = getattr(state, "inflation_axis", 0) or 0
    if g >= 0:
        return "Overheating" if i >= 0 else "Reflation"
    return "Stagflation" if i >= 0 else "Disinflation"


def _strategy_return_12m(strat: dict, mk: str) -> float | None:
    from src.data.etf_prices import monthly_closes
    from src.engine.tactical_allocations import _ret
    tot = 0.0
    wsum = 0.0
    for h in strat["holdings"]:
        r = _ret(monthly_closes(h["us_ticker"], mk), 12)
        if r is not None:
            tot += h["weight"] / 100.0 * r
            wsum += h["weight"] / 100.0
    return round(tot / wsum * 100, 2) if wsum > 0 else None


def _ai_narrative(quad: str, stress: float, top: dict) -> tuple[str, str]:
    """Claude 근거 서술 (키 있으면) → (text, source). 없으면 규칙 요약."""
    rule = (f"현재 국면은 {_QUAD_KR.get(quad, quad)}이고 Stress {stress:.0f}입니다. "
            f"이 국면에선 '{top['name']}'({top['archetype_kr']}) 전략의 적합도가 가장 높습니다 — "
            f"{top['rationale']}. 현 배분: "
            + ", ".join(f"{h['us_label']} {h['weight']}%" for h in top["holdings"][:4]) + ".")
    if not os.getenv("ANTHROPIC_API_KEY"):
        return rule, "rule"
    try:
        from src.services.narrative.claude_client import get_client  # 기존 클라이언트 재사용
        client = get_client()
        msg = client.complete(
            system="너는 매크로 기반 자산배분 애널리스트다. 한국어로 3~4문장, 과장 없이.",
            prompt=f"국면 {quad}, Stress {stress:.0f}. 추천 전략 {top['name']} ({top['signal']}). "
                   f"배분 {[ (h['us_label'], h['weight']) for h in top['holdings'] ]}. 근거를 설명하라.",
        )
        return (msg or rule), ("claude" if msg else "rule")
    except Exception as e:
        logger.debug(f"AI 서술 폴백: {e}")
        return rule, "rule"


def recommend(market: str = "us") -> dict:
    """현 국면 유리 전략 추천 (3종 종합)."""
    from src.engine.tactical_allocations import compute_strategies
    mk = "kr" if market == "kr" else "us"

    # 국면
    try:
        from src.engine.regime_analyzer import RegimeAnalyzer
        state = RegimeAnalyzer().analyze()
        quad = _quadrant(state)
        stress = float(getattr(state, "stress_score", 50) or 50)
        cycle = getattr(state, "cycle_phase", None) or getattr(state, "regime", quad)
    except Exception as e:
        logger.debug(f"regime 분석 폴백: {e}")
        quad, stress, cycle = "Disinflation", 50.0, "—"

    fit_map = _FIT.get(quad, _FIT["Disinflation"])
    sig = compute_strategies(mk)

    ranked = []
    perfs = []
    for s in sig["strategies"]:
        perf = _strategy_return_12m(s, mk)
        perfs.append(perf if perf is not None else 0.0)
        ranked.append({**s, "_perf": perf})
    pmin, pmax = (min(perfs), max(perfs)) if perfs else (0, 1)
    prange = (pmax - pmin) or 1.0

    for s in ranked:
        arch = _ARCHETYPE.get(s["id"], "diversified")
        fit = fit_map.get(arch, 0.5)
        # Stress 보정: 고스트레스 → 방어/인컴 가산, 공격 감산
        if stress >= 60:
            fit += 0.15 if arch in ("defensive", "income") else (-0.15 if arch == "aggressive" else 0)
        fit = max(0.0, min(1.0, fit))
        perf_norm = ((s["_perf"] or pmin) - pmin) / prange
        s["fit_score"] = round(fit * 100, 0)
        s["recent_return_12m"] = s["_perf"]
        s["archetype"] = arch
        s["archetype_kr"] = {"aggressive": "공격", "defensive": "방어",
                             "income": "인컴", "diversified": "분산"}[arch]
        s["composite"] = round((0.62 * fit + 0.38 * perf_norm) * 100, 1)
        s["rationale"] = f"{_QUAD_KR.get(quad, quad)} 국면 {s['archetype_kr']} 적합도 {fit*100:.0f}" \
                         + (f", 최근 12개월 {s['_perf']:+.1f}%" if s["_perf"] is not None else "")
        s.pop("_perf", None)

    ranked.sort(key=lambda x: x["composite"], reverse=True)
    top = ranked[0]
    narrative, nsrc = _ai_narrative(quad, stress, top)

    return {
        "market": mk, "as_of": sig["as_of"],
        "regime": {"quadrant": quad, "quadrant_kr": _QUAD_KR.get(quad, quad),
                   "stress": round(stress, 0), "cycle": cycle},
        "top": {"id": top["id"], "name": top["name"], "signal": top["signal"],
                "fit_score": top["fit_score"], "composite": top["composite"],
                "holdings": top["holdings"]},
        "narrative": narrative, "narrative_source": nsrc,
        "ranking": [{"id": s["id"], "name": s["name"], "composite": s["composite"],
                     "fit_score": s["fit_score"], "recent_return_12m": s["recent_return_12m"],
                     "archetype_kr": s["archetype_kr"], "signal": s["signal"]} for s in ranked],
    }
