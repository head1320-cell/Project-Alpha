"""
Regime Drivers — 국면 확률을 **지표별로** 쪼갠다 (A8, 설명가능성)
==========================================================================
"골디락스 91%" 만 보여 주는 화면은 블랙박스다. 포트폴리오 매니저가 이 신호로
비중을 움직이려면 *무엇이* 91% 를 만들었는지 봐야 한다.

★두 층을 따로 보여 준다 — 합치면 거짓말이 된다★
  1. 지표 → 축   : **정확한 가법 분해**. `regime_axes.compute_axis_detail` 이 이미
                   `contribution = sign·blend·weight/Σweight` 를 주고 `축 = Σ기여` 다.
                   근사가 아니라 항등식이다.
  2. 축 → 확률   : **비선형**. `quadrant_probs` 는 Φ(g/se)·Φ(i/se) 의 곱이다.
그래서 "지표가 확률에 얼마나 기여했나" 는 1층의 값을 그대로 쓸 수 없다. 곱을
가법으로 쪼개는 원리가 필요하고, 그것이 Shapley 값이다.

★근사하지 않는다 — 정확히 센다★
SHAP 의 KernelExplainer 는 부분집합을 **표본추출**해 Shapley 값을 근사한다. 특성이
수백 개일 때 이야기다. 여기서 축을 이루는 지표는 시장당 5~6개뿐이라 부분집합이
2^6 = 64개다. 전부 열거하는 편이 **더 싸고 정확**하다 — 근사할 이유가 없다.

★효율성 공리가 화면의 검산식이 된다★
Shapley 값은 `Σφ_i = v(N) − v(∅)` 를 정확히 만족한다. 기저 v(∅) 는 모든 지표를
역사 평균(z=0)에 둔 상태이고, 그러면 두 축이 0 이라 Φ(0)=0.5, 네 사분면이 각각
**정확히 0.25** 다. 따라서 워터폴은 25% 에서 출발해 지표별 막대를 더하면 최종
확률에 **정확히** 도달한다. 테스트가 이 등식을 단언하고, UI 도 잔차를 표시한다 —
화면 스스로 자기를 검산하게 만드는 것이 목적이다.

★se 를 고정하는 이유★
가치함수에서 축 불확실성(se)은 전체 표본 값으로 **고정**한다. 부분집합마다 se 를
다시 계산하면 v(∅) 가 0.25 가 아니게 되어 기저가 흔들리고, "지표를 평균에 둔다" 는
개입의 의미도 흐려진다. se 는 지표 간 불일치의 척도이지 개입 대상이 아니다.
"""

from __future__ import annotations

import logging
from itertools import combinations
from math import factorial

from src.engine.regime_axes import AXES, compute_axis_detail, quadrant_probs

logger = logging.getLogger(__name__)

REGIMES = ["Goldilocks", "Reflation", "Stagflation", "Disinflation"]

# 지표 코드 → 사람이 읽는 이름. 화면이 `KR_LEADING_CYCLE` 를 그대로 뱉지 않게 한다.
LABELS = {
    "KR_LEADING_CYCLE": "경기선행지수", "KR_IP": "산업생산", "KOSPI": "KOSPI",
    "KR_CPI": "소비자물가", "T10YIE": "기대인플레이션",
    "INDPRO": "산업생산", "PAYEMS": "비농업고용", "UNRATE": "실업률",
    "GDPC1": "실질GDP", "CPIAUCSL": "소비자물가",
}


def _shapley_weight(s: int, n: int) -> float:
    """|S|=s, 전체 n 일 때의 Shapley 가중치 s!(n-s-1)!/n!."""
    return factorial(s) * factorial(n - s - 1) / factorial(n)


def regime_drivers(series_map: dict, market: str = "kr",
                   regime: str | None = None) -> dict:
    """대상 국면 확률의 정확 Shapley 분해 + 축 수준 가법 기여.

    `regime` 이 None 이면 현재 argmax 국면을 쓴다.
    """
    g_def, i_def = AXES.get(market, AXES["kr"])
    g = compute_axis_detail(series_map, g_def)
    i = compute_axis_detail(series_map, i_def)

    if not g["components"] and not i["components"]:
        return {"available": False,
                "reason": "성장·물가 축을 만들 지표가 하나도 없어 분해할 것이 없습니다"}

    se_g, se_i = g["se"], i["se"]
    probs = quadrant_probs(g["score"], i["score"], se_g, se_i)
    target = regime or max(probs, key=probs.get)
    if target not in REGIMES:
        return {"available": False, "reason": f"알 수 없는 국면 '{target}'"}

    # 특성 = (축, 지표코드, 그 지표의 축 기여). 기여는 이미 정확 가법이다.
    feats: list[tuple[str, str, float]] = []
    for c in g["components"]:
        feats.append(("growth", c["key"], c["contribution"]))
    for c in i["components"]:
        feats.append(("inflation", c["key"], c["contribution"]))
    n = len(feats)
    if n == 0:
        return {"available": False, "reason": "축 기여를 가진 지표가 없습니다"}

    def value(members: frozenset[int]) -> float:
        """v(S) — S 안의 지표는 실제 값, 밖의 지표는 역사 평균(z=0 → 기여 0)."""
        gs = sum(feats[k][2] for k in members if feats[k][0] == "growth")
        isum = sum(feats[k][2] for k in members if feats[k][0] == "inflation")
        return quadrant_probs(gs, isum, se_g, se_i)[target]

    # 부분집합 값을 한 번만 계산해 재사용 (2^n 회, n<=6 이라 64회 이하).
    idx = list(range(n))
    cache: dict[frozenset[int], float] = {}
    for size in range(n + 1):
        for combo in combinations(idx, size):
            fs = frozenset(combo)
            cache[fs] = value(fs)

    base = cache[frozenset()]          # 정확히 0.25 여야 한다 (두 축 0 → Φ(0)=0.5)
    full = cache[frozenset(idx)]

    phis: list[float] = []
    for f in idx:
        others = [k for k in idx if k != f]
        phi = 0.0
        for size in range(len(others) + 1):
            w = _shapley_weight(size, n)
            for combo in combinations(others, size):
                fs = frozenset(combo)
                phi += w * (cache[fs | {f}] - cache[fs])
        phis.append(phi)

    total = sum(phis)
    residual = full - base - total      # 효율성 공리상 0 (부동소수 오차만)

    drivers = []
    for k, (axis, key, contrib) in enumerate(feats):
        drivers.append({
            "key": key,
            "label": LABELS.get(key, key),
            "axis": axis,
            "axis_contribution": round(contrib, 4),   # 지표 → 축 (정확 가법)
            "phi": round(phis[k], 5),                 # 지표 → 확률 (정확 Shapley)
        })
    drivers.sort(key=lambda d: abs(d["phi"]), reverse=True)

    return {
        "available": True,
        "market": market,
        "regime": target,
        "probability": round(full, 4),
        "baseline": round(base, 4),
        "drivers": drivers,
        "sum_phi": round(total, 5),
        # ★화면이 스스로 검산하게 한다★ |residual| 이 0 이 아니면 어딘가 틀린 것이다.
        "efficiency_residual": round(residual, 9),
        "axes": {
            "growth": {"score": g["score"], "se": se_g,
                       "components": g["components"]},
            "inflation": {"score": i["score"], "se": se_i,
                          "components": i["components"]},
        },
        "n_features": n,
        "n_coalitions": 2 ** n,
        "method": "exact-shapley-enumeration",
        "note": ("모든 지표를 역사 평균(z=0)에 두면 두 축이 0 이라 네 국면이 각각 25% 입니다. "
                 f"여기서 출발해 지표별 기여를 더하면 {round(full * 100, 1)}% 에 정확히 "
                 "도달합니다 — Shapley 효율성 공리이며, 부분집합을 표본추출로 근사하지 않고 "
                 f"{2 ** n}개를 전부 세어 구했습니다."),
    }
