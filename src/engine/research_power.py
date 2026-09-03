"""검정력 산출 — ★"무엇을 답할 수 있었나" 를 판정 옆에 싣는다★ (A1)
==============================================================================
감사(`7313371`)가 낸 최상위 통계 부채: **어떤 관문도 MDE·검정력을 보고하지
않는다.** M1~M5 는 심은 효과가 있는 양성 통제에서 검출률이 40% 였는데 리포트에는
"불통과" 만 남았다 — 관문이 고장난 것이 아니라 **찾을 힘이 없었다**는 사실을
담을 자리가 없었다.

★의존성을 뒤집는다★ 이 모듈은 하네스를 import 하지 않는다. `power_curve` 가
**시행 함수를 주입**받으므로 규칙 자체를 합성 시행으로 정확히 검사할 수 있고,
하네스가 바뀌어도 깨지지 않는다. 양성 통제는 이미 저장소에 있다 —
`scripts/t3_transmission.build_panel` 이 `_PROF[regime]` 에서 수익을 만드는
**신호가 심어진** 패널이다.

★"492 자산-월" 은 독립 표본이 아니다★ 실측에서 자산간 상관이 자산 수와 무관하게
~0.58 로 고정이었다. 국면은 **공통인자**라 유효 관측이 월당 ~1개이지 N 개가
아니다. `effective_n` 이 그 사실을 수치로 만든다 — 6자산·84개월·ρ̄=0.58 이면
504 가 아니라 ~129 다.

★미상은 실패가 아니다★ 못 돌린 시행은 분모에서 뺀다. 전부 미상이면 검출률은
`0.0` 이 아니라 `None` + 사유다.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from typing import Any

from src.engine.research_verdict import DEFAULT_TARGET_POWER

#: Wilson 구간의 z (95%).
Z_95 = 1.959963984540054


# ── 유효 표본 ─────────────────────────────────────────────────────────────
def mean_pairwise_correlation(matrix: Any) -> float | None:
    """열(자산) 간 **비대각** 상관의 평균. 열이 2개 미만이면 `None`.

    ★대각선 1.0 을 섞지 않는다★ — 섞으면 자산이 적을수록 상관이 높아 보인다.
    ★짝이 없으면 상관도 없다★ — 1열에서 `1.0` 을 내면 설계효과가 부풀려진다.
    """
    import numpy as np

    a = np.asarray(matrix, dtype=float)
    if a.ndim != 2 or a.shape[1] < 2 or a.shape[0] < 2:
        return None
    c = np.corrcoef(a, rowvar=False)
    if not np.isfinite(c).all():
        return None
    n = c.shape[0]
    off = c[~np.eye(n, dtype=bool)]
    return round(float(off.mean()), 6)


def design_effect(n_assets: int, rho_bar: float | None) -> float | None:
    """Kish 설계효과 `1 + (N−1)·ρ̄`. ρ̄ 가 미상이면 `None`.

    ★1 아래로는 내려가지 않는다★ 설계효과 < 1 은 "N·T 보다 **많은** 독립 관측"
    을 뜻하는데, 음의 평균 상관에서 그것을 주장하면 유리한 쪽으로 표본을 지어내는
    것이다. 미상보다 나쁜 것은 유리하게 지어낸 값이다.
    """
    if rho_bar is None or n_assets is None or int(n_assets) < 1:
        return None
    return max(1.0, 1.0 + (int(n_assets) - 1) * float(rho_bar))


def effective_n(n_obs: int, n_assets: int, rho_bar: float | None) -> float | None:
    """설계효과 보정 유효 표본 `N·T / deff`. ρ̄ 가 미상이면 `None`."""
    deff = design_effect(n_assets, rho_bar)
    if deff is None or n_obs is None or int(n_obs) < 0:
        return None
    return float(int(n_obs) * int(n_assets)) / deff


# ── 검출률과 신뢰구간 ─────────────────────────────────────────────────────
def detection_rate(outcomes: Iterable[bool | None]) -> dict[str, Any]:
    """시행 결과 → `{n, n_resolved, n_unknown, n_detected, rate, ci, reason}`.

    ★미상 ≠ 실패★ `None` 시행은 분모에서 뺀다. 전부 미상이면 `rate=None` + 사유 —
    못 돌린 것과 못 찾은 것은 다른 진술이다.
    """
    xs = list(outcomes)
    resolved = [bool(x) for x in xs if x is not None]
    detected = sum(1 for x in resolved if x)
    out: dict[str, Any] = {
        "n": len(xs), "n_resolved": len(resolved),
        "n_unknown": len(xs) - len(resolved), "n_detected": detected,
    }
    if not resolved:
        out.update({"rate": None, "ci": None,
                    "reason": "해결된 시행이 없습니다 — 미상은 0% 가 아닙니다"})
        return out
    out.update({"rate": detected / len(resolved),
                "ci": wilson_interval(detected, len(resolved)), "reason": None})
    return out


def wilson_interval(k: int, n: int, z: float = Z_95) -> tuple[float, float] | None:
    """비율의 Wilson 점수 구간. 시행이 없으면 `None`.

    ★5시드의 노이즈를 숨기지 않는다★ 검출률 80% 가 5회에서 나온 것과 500회에서
    나온 것은 같은 진술이 아니다. 정규근사(Wald)는 0%·100% 에서 폭 0 을 내므로
    쓰지 않는다.
    """
    if n is None or int(n) <= 0:
        return None
    n_i, k_i = int(n), int(k)
    p = k_i / n_i
    denom = 1.0 + z * z / n_i
    center = (p + z * z / (2 * n_i)) / denom
    half = z * math.sqrt(p * (1 - p) / n_i + z * z / (4 * n_i * n_i)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


# ── 검정력 곡선과 MDE ─────────────────────────────────────────────────────
def power_curve(trial: Callable[[float, int], bool | None],
                scales: Iterable[float],
                seeds: Iterable[int]) -> list[dict[str, Any]]:
    """척도×시드 격자를 돌려 검정력 곡선을 만든다. 척도 오름차순.

    `trial(scale, seed)` 는 "그 척도로 심은 효과를 관문이 **검출했는가**" 를
    `True`/`False`/`None`(못 돌림) 으로 낸다.

    ★예외를 삼키지 않는다★ 시행이 터지면 그대로 전파한다 — 예외를 "못 찾았다"
    로 바꾸면 하네스 고장이 **음성 결과로 위장**된다. 침묵 폴백 금지.
    """
    seed_list = list(seeds)
    curve: list[dict[str, Any]] = []
    for s in sorted(float(x) for x in scales):
        curve.append({"scale": s, "seeds": len(seed_list),
                      **detection_rate([trial(s, sd) for sd in seed_list])})
    return curve


def mde_from_curve(curve: list[dict[str, Any]], *,
                   target_power: float = DEFAULT_TARGET_POWER,
                   key: str = "scale") -> dict[str, Any]:
    """목표 검정력에 처음 도달하는 지점 = MDE.

    ★`key` 로 축을 바꾼다★ "목표 검정력에 처음 도달하는 지점" 은 척도든 개월이든
    **같은 규칙**이다. 개월 축에 새 규칙을 쓰면 두 벌이 갈라지고, 갈라져도 타입
    에러가 나지 않는다 — `null_stats` 를 단일 출처로 만든 것과 같은 이유다.
    기본값이 `"scale"` 이라 기존 호출부는 한 자도 바뀌지 않는다.

    ★도달하지 못하면 "MDE = 탐색 최대 척도" 가 아니라 미상이다★ 탐색 범위를
    MDE 라고 적으면 "이 정도면 찾을 수 있다" 는 하지 않은 주장이 된다
    (만다트 §42 *fallback converted to success*).

    ★격자 사이를 보간하지 않는다★ 검출률 0%(1×)와 100%(2×) 사이를 선형으로
    이어 "MDE = 1.8" 이라고 적으면 **재지 않은 정밀도를 지어내는 것**이다. 격자가
    말해 주는 것은 "1× 에서는 못 찾고 2× 에서는 찾는다" 뿐이므로, MDE 는 목표에
    도달한 **가장 작은 시험 척도**로 적고 참값이 든 구간을 `bracket` 으로 함께
    낸다.

    ★매끈한 척하지 않는다★ 실측 곡선은 40/80/0/80/60 처럼 비단조였다. 비단조면
    `monotone=False` 와 교차 횟수를 함께 적고 **첫 교차**를 쓴다. 최소 척도에서
    이미 도달했으면 `at_search_floor` — 참 MDE 는 더 작을 수 있다는 뜻이다.
    """
    tp = float(target_power)
    # ★없는 키를 0 으로 읽지 않는다★ 정렬이 무너지면 MDE 가 조용히 거짓이 된다.
    pts = [(c[key], c.get("rate")) for c in curve]
    pts.sort(key=lambda t: t[0])
    known = [(s, float(r)) for s, r in pts if r is not None]
    base: dict[str, Any] = {
        "target_power": tp, "convention": True,
        "searched_min": (known[0][0] if known else None),
        "searched_max": (known[-1][0] if known else None),
        "max_rate": (max(r for _, r in known) if known else None),
        "at_search_floor": False, "bracket": None,
    }
    if not known:
        return {**base, "mde": None, "monotone": None, "crossings": 0,
                "reason": "해결된 시행이 없어 검정력 곡선을 만들 수 없습니다"}

    monotone = all(known[i][1] <= known[i + 1][1] + 1e-12
                   for i in range(len(known) - 1))
    crossings = sum(1 for i in range(len(known) - 1)
                    if (known[i][1] < tp) != (known[i + 1][1] < tp))
    base.update({"monotone": monotone, "crossings": crossings})

    for i, (s, r) in enumerate(known):
        if r < tp:
            continue
        if i == 0:
            return {**base, "mde": s, "at_search_floor": True,
                    "bracket": [None, s], "reason": None}
        return {**base, "mde": s, "bracket": [known[i - 1][0], s], "reason": None}

    return {**base, "mde": None,
            "reason": f"탐색 범위({base['searched_min']}~{base['searched_max']})"
                      f"에서 목표 검정력 {tp:.2f} 에 도달하지 못했습니다"}


# ── 리포트 블록 ───────────────────────────────────────────────────────────
def power_report(*, curve: list[dict[str, Any]], observed_scale: float,
                 n_obs: int, n_assets: int, rho_bar: float | None,
                 target_power: float = DEFAULT_TARGET_POWER) -> dict[str, Any]:
    """모든 관문 리포트가 실을 `mde`·`power`·`n_eff` 블록.

    `power` 는 **관측 척도**(보통 1×, 심은 효과를 액면 그대로)에서의 검출률이다.
    ★격자에 없는 척도의 검정력을 지어내지 않는다★ — 없으면 `None` + 사유.

    `research_verdict.require_power_fields` 를 그대로 통과하도록 미상에는 반드시
    사유가 붙는다.
    """
    detail = mde_from_curve(curve, target_power=target_power)
    deff = design_effect(n_assets, rho_bar)
    n_eff = effective_n(n_obs, n_assets, rho_bar)

    hit = next((c for c in curve
                if abs(float(c["scale"]) - float(observed_scale)) <= 1e-12), None)
    power = None if hit is None else hit.get("rate")
    reasons: dict[str, str] = {}
    if detail.get("mde") is None:
        reasons["mde"] = detail.get("reason") or "MDE 를 산출하지 못했습니다"
    if power is None:
        reasons["power"] = (
            f"관측 척도 {observed_scale} 가 검정력 격자에 없습니다"
            if hit is None else
            (hit.get("reason") or "해결된 시행이 없습니다"))
    if n_eff is None:
        reasons["n_eff"] = ("자산간 평균 상관이 미상이라 설계효과를 낼 수 "
                            "없습니다 — 미상은 무상관이 아닙니다")

    return {
        "mde": detail.get("mde"),
        "power": power,
        "power_ci": (None if hit is None else hit.get("ci")),
        "n_eff": (None if n_eff is None else round(n_eff, 4)),
        "design_effect": deff,
        "rho_bar": rho_bar,
        "n_obs": n_obs,
        "n_assets": n_assets,
        "observed_scale": float(observed_scale),
        "target_power": float(target_power),
        "convention": True,
        "mde_detail": detail,
        "curve": curve,
        "reasons": reasons,
    }
