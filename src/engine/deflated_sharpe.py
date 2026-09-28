"""갈래 비교의 다중 비교 보정 — Probabilistic / Deflated Sharpe (BO O3)
==============================================================================
Bailey & López de Prado (2012 "The Sharpe Ratio Efficient Frontier", 2014 "The Deflated Sharpe
Ratio"). 순수 함수 — 입력은 수익 흐름(일별), 출력은 값 + 사유. 저장·유통 없음.

## 무엇을 재나

같은 사람이 설정을 바꿔 가며 N 개의 후보(원본 + 갈래)를 만들고 **가장 좋아 보이는 것**을 고르면,
그 샤프는 운으로도 커진다. DSR 은 "N 번 시도했을 때 운으로 기대되는 최대 샤프(SR₀)" 를 넘을 확률이다.

- `SR` 는 **기간당**(연율 아님) 표본 샤프 = 평균 / 표준편차(ddof=1). 무위험 수익은 빼지 않는다(0 기준).
- `PSR(SR*) = Φ( (SR − SR*)·√(T−1) / √(1 − γ₃·SR + (γ₄−1)/4·SR²) )` — γ₃ 왜도, γ₄ 첨도(초과 아님).
- `SR₀ = √V · ((1−γ)·Φ⁻¹(1 − 1/N) + γ·Φ⁻¹(1 − 1/(N·e)))` — V 는 N 개 후보 SR 의 분산, γ 는 오일러–마스케로니.
- `DSR = PSR(SR₀)`.

## ★N 은 하한이다★ — `multiplicity_evidence` 와의 차이

`multiplicity_evidence` 는 "시행 횟수를 세는 자리가 없어 DSR 을 만들지 않는다" 고 적었다. 여기서 N 은
**이 캔버스에 지금 남아 있는 갈래 수 + 원본**으로 셀 수 있다. 그러나 그 전에 바꿔 보고 버린 설정은
세지 않으므로 ★실제 시도 수보다 작을 수 있다 — 보정이 약한 쪽으로 틀린다.★ 응답이 그 사실을 함께 말한다.

## 주장하지 않는 것

- 과최적화가 없다고 말하지 않는다. 표본외 검증도 아니다(같은 과거 위의 비교다).
- 높은 DSR 이 경제적 가치라는 뜻이 아니다(CLAUDE.md §2 — 예측 스킬 ≠ 경제적 가치).
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

EULER_GAMMA = 0.5772156649015329
#: 표본이 이보다 짧으면 왜도·첨도 추정이 너무 흔들려 값을 내지 않는다(사유와 함께).
MIN_OBS = 60
#: 이보다 작은 표준편차는 흔들림이 없는 것으로 본다 — 상수 흐름도 부동소수 잡음으로 1e-19 쯤의 표준편차가 나와
#: 샤프가 10¹⁵ 로 튄다(테스트가 찾았다). 일별 수익의 실제 표준편차는 이보다 수만 배 크다.
FLAT_SD = 1e-10

NOTE_N_LOWER_BOUND = ("N 은 이 캔버스에 남아 있는 비교 대상 수예요 — 그 전에 바꿔 보고 지운 설정은 세지 않아 "
                      "실제로 시도한 수보다 작을 수 있고, 그만큼 보정이 약해요.")


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    from scipy.stats import norm
    return float(norm.ppf(p))


def returns_from_equity(equity: list[float] | np.ndarray) -> np.ndarray:
    """누적 곡선 → 기간 수익. 0 이하·비유한 값이 있으면 ValueError(지어내지 않는다)."""
    eq = np.asarray(equity, dtype=float)
    if eq.ndim != 1 or eq.size < 2:
        raise ValueError("곡선에 점이 두 개 이상 있어야 해요")
    if not np.all(np.isfinite(eq)) or np.any(eq <= 0):
        raise ValueError("곡선에 0 이하이거나 숫자가 아닌 값이 있어요")
    return eq[1:] / eq[:-1] - 1.0


def moments(r: np.ndarray) -> dict[str, Any]:
    """기간당 SR · 왜도 · 첨도(초과 아님) · T. 쓸 수 없으면 `sr=None` + 사유."""
    r = np.asarray(r, dtype=float)
    T = int(r.size)
    if T < MIN_OBS:
        return {"t": T, "sr": None, "skew": None, "kurt": None,
                "reason": f"수익이 {T}개뿐이에요 — {MIN_OBS}개 이상이어야 분포 모양을 믿을 만하게 재요"}
    sd = float(r.std(ddof=1))
    if not math.isfinite(sd) or sd <= FLAT_SD:
        return {"t": T, "sr": None, "skew": None, "kurt": None, "reason": "수익이 흔들리지 않아(표준편차 0) 샤프를 정의할 수 없어요"}
    mu = float(r.mean())
    z = (r - mu) / float(r.std(ddof=0))
    return {"t": T, "sr": mu / sd, "skew": float(np.mean(z ** 3)), "kurt": float(np.mean(z ** 4)), "reason": None}


def psr(sr: float, sr_star: float, t: int, skew: float, kurt: float) -> float | None:
    """확률적 샤프 — 참 SR 이 `sr_star` 를 넘을 확률. 분모가 양이 아니면 None."""
    den = 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr
    if den <= 0 or t < 2:
        return None
    return _norm_cdf((sr - sr_star) * math.sqrt(t - 1) / math.sqrt(den))


def expected_max_sr(n: int, var_sr: float) -> float:
    """N 번 독립 시도에서 운으로 기대되는 최대 SR(기간당) — 참 SR 이 모두 0 일 때."""
    if n < 2:
        raise ValueError("N 은 2 이상이어야 해요")
    return math.sqrt(max(var_sr, 0.0)) * ((1 - EULER_GAMMA) * _norm_ppf(1 - 1 / n)
                                          + EULER_GAMMA * _norm_ppf(1 - 1 / (n * math.e)))


def compare(series: list[dict]) -> dict[str, Any]:
    """[{label, returns}] → 후보별 SR·PSR(0)·DSR + N·SR₀. 값을 못 내면 None + 사유(0 으로 채우지 않는다).

    N = 입력 후보 수(값을 낸 것만이 아니라 **비교한 전부**). SR 분산은 값을 낸 후보들의 표본 분산.
    """
    rows = []
    for s in series:
        m = moments(np.asarray(s["returns"], dtype=float))
        row = {"label": s["label"], "t": m["t"], "sr": m["sr"], "skew": m["skew"], "kurt": m["kurt"],
               "psr0": None, "dsr": None, "reason": m["reason"]}
        if m["sr"] is not None:
            row["psr0"] = psr(m["sr"], 0.0, m["t"], m["skew"], m["kurt"])
            if row["psr0"] is None:
                row["reason"] = "왜도·첨도가 극단적이라 샤프의 표준오차를 정의할 수 없어요"
        rows.append(row)
    n = len(series)
    srs = [r["sr"] for r in rows if r["sr"] is not None]
    out: dict[str, Any] = {"n": n, "sr0": None, "var_sr": None, "rows": rows, "reason": None,
                           "note": NOTE_N_LOWER_BOUND}
    if n < 2:
        out["reason"] = "비교할 대상이 둘 이상이어야 보정할 수 있어요"
        return out
    if len(srs) < 2:
        out["reason"] = "샤프를 잰 대상이 둘 미만이라 시도 사이의 흩어짐을 잴 수 없어요"
        return out
    var = float(np.var(srs, ddof=1))
    if var <= 0:
        out["reason"] = "모든 대상의 샤프가 같아 시도 사이의 흩어짐이 0 이에요 — 보정 기준을 정할 수 없어요"
        return out
    sr0 = expected_max_sr(n, var)
    out["var_sr"], out["sr0"] = var, sr0
    for r in rows:
        if r["sr"] is not None and r["psr0"] is not None:
            r["dsr"] = psr(r["sr"], sr0, r["t"], r["skew"], r["kurt"])
    return out
