"""매크로 임베딩 자산배분 (Macro-Embedded TAA) — CIO 리팩토링 §3.

문제: 매크로 탭이 가격 추세 기반 듀얼모멘텀(S&P 88%)을 표시 → 매크로 환경(성장↓·물가↓)과
충돌. 해법: 성장/물가 축 스코어를 '입력'으로 받는 4계절(All-Weather 사상) 룰베이스 틸트.

구조 (선형 룰 → 기여 분해가 정확·투명, XAI):
  최종비중 = base(전천후 중립) + 성장 틸트·g + 물가 틸트·i + 스트레스 디리스킹
  · 기여 분해(attribution): 자산별 base/성장/물가/스트레스 항 — 합=최종 (SHAP식 워터폴 UI용)
  · MC 신뢰구간(bands): (g,i) ~ N(score, se) 400 드로우(시드 고정) → 비중 p10/p50/p90
    — "S&P 88%" 단일 점추정 대신 불확실성 밴드 제시 (CIO 확률적 비중).

자산 유니버스는 tactical_allocations와 동일 미국 상장 ETF (KR 매핑은 프론트 관례 재사용).
"""

from __future__ import annotations

import random

# (ticker, label, base %, 성장 감도 %/σ, 물가 감도 %/σ) — 선형 틸트 계수.
# base = 전천후 중립(주식 30 / 채권 40 / 실물 15 / 현금 15).
# 감도 부호는 4계절 표준: 성장↑ → 주식+·채권−, 물가↑ → 실물+·명목채−·성장주−.
_UNIVERSE = [
    ("SPY", "S&P500",          18.0, +6.0, -1.5),
    ("QQQ", "나스닥100(성장)",  12.0, +5.0, -3.0),
    ("TLT", "미 장기채(20Y+)",  22.0, -5.0, -4.5),
    ("IEF", "미 중기채(7-10Y)", 18.0, -3.0, -2.5),
    ("GLD", "금",               8.0, -1.5, +4.0),
    ("DBC", "원자재",           7.0, +1.5, +5.0),
    ("BIL", "현금성(1-3M)",    15.0, -2.5, +2.5),
]
_TILT_CLAMP = 2.0          # 축 스코어 클램프(±2σ) — 극단값의 선형 폭주 방지
_STRESS_MAX_DERISK = 0.35  # 스트레스 100일 때 위험자산의 35%를 현금성으로
_MC_DRAWS = 400
_MC_SEED = 20260710


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _raw_weights(growth: float, inflation: float) -> dict[str, dict]:
    """선형 틸트 원시 비중 + 항별 기여 (정규화 전, 음수는 0 클립 후 비례 재정규화)."""
    g = _clamp(growth, -_TILT_CLAMP, _TILT_CLAMP)
    i = _clamp(inflation, -_TILT_CLAMP, _TILT_CLAMP)
    out: dict[str, dict] = {}
    for tk, label, base, sg, si in _UNIVERSE:
        raw = base + sg * g + si * i
        out[tk] = {"label": label, "base": base, "growth": sg * g, "inflation": si * i,
                   "raw": raw}
    return out


def macro_embedded_allocation(growth: float, inflation: float, stress: float = 50.0,
                              se_g: float = 0.3, se_i: float = 0.3) -> dict:
    """국면 스코어 → 비중 + 기여 분해 + MC 신뢰구간.

    반환: {holdings, attribution, bands, inputs} — holdings 합 100.
    기여 분해 항등: base + growth + inflation + stress ≈ final (반올림 ±0.5)."""
    def solve(g: float, i: float, st: float) -> dict[str, float]:
        raw = _raw_weights(g, i)
        clipped = {tk: max(0.0, v["raw"]) for tk, v in raw.items()}
        tot = sum(clipped.values()) or 1.0
        w = {tk: v / tot * 100.0 for tk, v in clipped.items()}
        # 스트레스 디리스킹: 위험자산(BIL 제외)을 비례 축소 → BIL로
        derisk = _clamp((st - 50.0) / 50.0, 0.0, 1.0) * _STRESS_MAX_DERISK
        if derisk > 0:
            moved = 0.0
            for tk in w:
                if tk == "BIL":
                    continue
                cut = w[tk] * derisk
                w[tk] -= cut
                moved += cut
            w["BIL"] += moved
        return w

    final = solve(growth, inflation, stress)
    no_stress = solve(growth, inflation, 50.0)
    base_only = solve(0.0, 0.0, 50.0)
    g_only = solve(growth, 0.0, 50.0)

    holdings = []
    attribution = []
    labels = {tk: lb for tk, lb, *_ in _UNIVERSE}
    for tk in final:
        fw = round(final[tk], 1)
        holdings.append({"ticker": tk, "us_ticker": tk, "label": labels[tk],
                         "us_label": labels[tk], "weight": fw})
        g_contrib = g_only[tk] - base_only[tk]                    # 성장 축 기여
        i_contrib = no_stress[tk] - g_only[tk]                    # 물가 축 기여 (증분)
        s_contrib = final[tk] - no_stress[tk]                     # 스트레스 기여
        attribution.append({"ticker": tk, "label": labels[tk],
                            "base": round(base_only[tk], 1),
                            "growth": round(g_contrib, 1),
                            "inflation": round(i_contrib, 1),
                            "stress": round(s_contrib, 1),
                            "final": fw})
    # 반올림 잔차 정규화 (합 100)
    tot = sum(h["weight"] for h in holdings)
    if tot > 0 and abs(tot - 100.0) > 1e-6:
        holdings[0]["weight"] = round(holdings[0]["weight"] + (100.0 - tot), 1)

    # MC 신뢰구간 — (g,i) 불확실성 하에서 비중 분포 (시드 고정 → 재현)
    rng = random.Random(_MC_SEED)
    samples: dict[str, list[float]] = {tk: [] for tk in final}
    for _ in range(_MC_DRAWS):
        gs = rng.gauss(growth, max(1e-6, se_g))
        is_ = rng.gauss(inflation, max(1e-6, se_i))
        w = solve(gs, is_, stress)
        for tk, v in w.items():
            samples[tk].append(v)
    bands = []
    for tk, xs in samples.items():
        xs.sort()
        n = len(xs)
        bands.append({"ticker": tk, "label": labels[tk],
                      "p10": round(xs[int(n * 0.10)], 1),
                      "p50": round(xs[int(n * 0.50)], 1),
                      "p90": round(xs[int(n * 0.90)], 1)})

    return {"holdings": holdings, "attribution": attribution, "bands": bands,
            "inputs": {"growth": round(growth, 3), "inflation": round(inflation, 3),
                       "stress": round(stress, 1), "se_g": se_g, "se_i": se_i},
            "method": "4계절 선형 틸트 (base+성장·g+물가·i+스트레스 디리스킹) · MC 400 드로우",
            "note": "룰베이스 — 기여 분해는 룰 항의 정확 분해(근사 SHAP 아님, 그보다 강함)"}
