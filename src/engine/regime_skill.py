"""국면 예측 비교 — 워크포워드 (M2 · 설계 `docs/superpowers/specs/2026-11-16-emeans-gmm-strategy-design.md` §M2).
==============================================================================
답하는 물음은 ③ 하나다: ★후보마다 k개월 뒤 국면을 얼마나 맞히는가★ — 같은 시점 · 같은 실현값 · '오늘 국면 유지' 대비.

★고르지 않는다★ 점수를 나란히 보일 뿐 "이 후보를 쓰라"고 하지 않는다. 배분이 받는 국면 확률의 출처는 따로 정한다(M3 · M4).
합성 축(E0) 위의 점수는 장치가 뜻대로 도는지의 증거이지 어느 모형이 실제로 더 맞힌다는 증거가 아니다.

방법
------------------------------------------------------------------------------
입력은 `regime_path` 의 점(축 둘 다 계산된 달만 · 과거 → 현재)이다 — `forecast_coverage` · 앙상블과 같은 입력이다
(앙상블은 성분이 없는 달을 점수 0 으로 채우던 것을 M1b 에서 이 입력으로 바꿨다 · 계산되지 않은 달을 한 국면으로 찍지 않는다).

시점 t(= `min_history` … n − k)마다 ★`points[:t]` 만으로★ 후보 여섯을 세워 `points[t + k − 1]` 의 국면을 예측한다.
`min_history` 는 군집 팔의 표본 하한(36)과 같다 — 모든 후보가 같은 시점에서 채점된다.

    ⓐ persistence  오늘 국면 유지(그 국면에 확률 1) — 기준선
    ⓑ base_rate    그때까지의 국면 빈도
    ⓒ transition   전이 예측(오늘 국면 → 전이 사후평균 행렬^k) — 지금 배분이 받는 출처와 같은 계산
    ⓓ gmm_start    GMM 시작 분포 × 전이(π₀ · P̄^k — π₀ 는 시점 t 의 GMM 시드 평균 소속 확률)
    ⓔ gmm_now      GMM 지금 값 그대로
    ⓕ kmeans_share k-평균 시드 비율(확률이 아니라 비율 — 같은 점수 규칙으로 채점한다)

점수: 적중(가장 높은 확률의 국면 = 실현 · 동률은 `REGIMES` 순서) · 브라이어 점수 Σ(p − o)²(0 ~ 2) · 유지 대비 이득(브라이어 차의 평균).
순차 증거(e-값): d = 브라이어(유지) − 브라이어(후보) 는 늘 [−2, 2] 안이라 G1 의 베팅 e-과정(`evalue.log_path`, 상한 2)이
★상한 가정 없이★ 성립한다. 기준 = 견준 후보 수(다섯) ÷ α. k > 1 이면 앞 예측이 실현되기 전에 다음 예측이 나와 평가 결과가 겹치므로
순차 검정의 전제가 서지 않는다 — 계산하지 않고 사유를 적는다.

한 시점이라도 세우지 못한 후보는 값 없음 + 사유다 — 다른 표본으로 채점한 점수는 나란히 놓을 수 없다.
군집 두 팔은 `arms(g, i)` 자리로 받는다(시험은 가짜를 넣는다). 기본은 축 값의 튜플을 열쇠로 기억하는 `cached_arms` 다 —
시점마다 GMM 10시드 + k-평균 10시드를 다시 적합하므로 첫 계산에 시간이 든다(잰 값 · 구현 계획 §2.0).
"""
from __future__ import annotations

import functools
import math
from collections.abc import Callable, Sequence
from typing import Any

from src.engine import evalue
from src.engine.regime_forecast import MIN_EVAL_POINTS, _marginal_probs, propagate, transition_posterior_mean
from src.engine.regime_transitions import REGIMES

CANDIDATES: tuple[str, ...] = ("persistence", "base_rate", "transition", "gmm_start", "gmm_now", "kmeans_share")
#: 화면 이름표 — 한 곳. 캔버스 해설 · 결과 판 · 매크로 화면이 이 이름을 그대로 쓴다.
CANDIDATE_NAMES: dict[str, str] = {
    "persistence": "오늘 국면 유지", "base_rate": "기저율", "transition": "전이 예측",
    "gmm_start": "GMM 시작 분포 × 전이", "gmm_now": "GMM 지금 값", "kmeans_share": "k-평균 시드 비율",
}
BASELINE = "persistence"
#: 군집 팔의 표본 하한(`regime_ensemble.MIN_OBS`)과 같다 — 모든 후보를 같은 시점에서 채점한다.
MIN_HISTORY = 36
#: 브라이어 차의 범위 [−2, 2] — e-과정의 손실 상한(가정이 아니라 점수 규칙의 성질).
_BRIER_SPAN = 2.0

EVIDENCE_K_REASON = ("k개월 앞(k > 1) 예측은 앞 예측이 실현되기 전에 다음 예측이 나와 평가 결과가 겹칩니다 — "
                     "순차 검정의 전제가 서지 않아 1개월 앞(k = 1)에서만 계산합니다.")


def brier(probs: dict[str, float], realized: str) -> float:
    """다범주 브라이어 점수 Σ_r (p_r − 1[r = 실현])² — 0(확신하고 맞힘) ~ 2(확신하고 틀림)."""
    return float(sum((float(probs.get(r, 0.0)) - (1.0 if r == realized else 0.0)) ** 2 for r in REGIMES))


def top(probs: dict[str, float]) -> str:
    """가장 높은 확률의 국면 — 동률이면 `REGIMES` 순서의 앞(앙상블의 `argmax` 와 같은 규칙)."""
    return max(REGIMES, key=lambda r: float(probs.get(r, 0.0)))


def default_arms(g_hist: Sequence[float], i_hist: Sequence[float]) -> dict[str, dict]:
    """군집 두 팔 — 앙상블과 같은 함수(GMM 시드 평균 · k-평균 시드 비율)를 그 시점까지의 축으로 부른다."""
    from src.engine.regime_ensemble import _cluster_probs, _kmeans_probs
    g, i = list(g_hist), list(i_hist)
    return {"gmm": _cluster_probs(g, i), "kmeans": _kmeans_probs(g, i)}


@functools.lru_cache(maxsize=1024)
def cached_arms(g_hist: tuple[float, ...], i_hist: tuple[float, ...]) -> dict[str, dict]:
    """축 값의 튜플을 열쇠로 기억한다 — 같은 축이면 같은 적합(시드 고정 · 한 스레드라 결정적)이고, k 가 달라도 적합은 같다.
    ★열쇠는 축 값 그 자체★ 시점 번호 같은 것으로 지으면 자료가 바뀌어도 옛 적합을 쓴다. 돌려준 사전은 고치지 않는다(공유된다)."""
    return default_arms(g_hist, i_hist)


def _onehot(regime: str) -> dict[str, float]:
    return {r: (1.0 if r == regime else 0.0) for r in REGIMES}


def _walk(points: Sequence[dict], *, k: int, min_history: int,
          arms: Callable[[Sequence[float], Sequence[float]], dict]) -> list[dict]:
    """시점마다의 예측 — `{t, origin, label, realized, probs: {후보: 분포 | None}, fail: {후보: 사유}}`.

    시점 t 의 자료는 `points[:t]` 뿐이다(마지막 점은 t−1). 실현값은 `points[t + k − 1]` — `forecast_coverage` 와 같은 칸 맞춤."""
    path = [p["regime"] for p in points]
    rows: list[dict] = []
    for t in range(min_history, len(points) - k + 1):
        hist = path[:t]
        g = tuple(float(p["growth"]) for p in points[:t])
        i = tuple(float(p["inflation"]) for p in points[:t])
        matrix = transition_posterior_mean(hist)
        probs: dict[str, dict | None] = {
            "persistence": _onehot(hist[-1]),
            "base_rate": _marginal_probs(hist),
            "transition": propagate(_onehot(hist[-1]), matrix, k),
            "gmm_start": None, "gmm_now": None, "kmeans_share": None,
        }
        fail: dict[str, str] = {}
        got = arms(g, i)
        gmm, km = got.get("gmm") or {}, got.get("kmeans") or {}
        if gmm.get("available") and isinstance(gmm.get("probs"), dict):
            pi0 = {r: float(gmm["probs"].get(r, 0.0)) for r in REGIMES}
            probs["gmm_now"] = pi0
            probs["gmm_start"] = propagate(pi0, matrix, k)
        else:
            fail["gmm_now"] = fail["gmm_start"] = str(gmm.get("reason") or "사유 미상")
        if km.get("available") and isinstance(km.get("probs"), dict):
            probs["kmeans_share"] = {r: float(km["probs"].get(r, 0.0)) for r in REGIMES}
        else:
            fail["kmeans_share"] = str(km.get("reason") or "사유 미상")
        rows.append({"t": t, "origin": points[t - 1].get("t"), "label": points[t + k - 1].get("t"),
                     "realized": path[t + k - 1], "probs": probs, "fail": fail})
    return rows


def _shown(log_e: float) -> float:
    return evalue.SATURATION if log_e >= math.log(evalue.SATURATION) else math.exp(log_e)


def _evidence(gains: list[float], threshold: float) -> dict[str, Any]:
    """유지 대비 브라이어 이득의 베팅 e-과정 — 최고값으로 기준과 견준다(지나온 시점 가운데 넘은 적이 있으면 남는다)."""
    path = evalue.log_path(gains, _BRIER_SPAN)
    top_log = max(0.0, max(path))
    return {"e_value": _shown(path[-1]), "peak": _shown(top_log),
            "saturated": top_log >= math.log(evalue.SATURATION), "passed": top_log >= math.log(threshold)}


def _no(reason: str, k: int) -> dict[str, Any]:
    return {"available": False, "reason": reason, "k": k}


def regime_skill(points: Sequence[dict], *, k: int = 1, min_history: int = MIN_HISTORY, alpha: float = evalue.ALPHA,
                 arms: Callable[[Sequence[float], Sequence[float]], dict] | None = None) -> dict[str, Any]:
    """국면 예측 비교의 본문. 계산하지 못하면 `available: False` + 사유(0 이나 빈 표로 내지 않는다)."""
    if k < 1:
        return _no("예측 기간은 1개월 이상이어야 합니다.", k)
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha={alpha!r}")
    unknown = sorted({str(p.get("regime")) for p in points} - set(REGIMES))
    if unknown:
        return _no(f"알 수 없는 국면 라벨이 있습니다({', '.join(unknown)}) — 알려진 값: {', '.join(REGIMES)}", k)
    n_eval = max(0, len(points) - k + 1 - min_history)
    if n_eval < MIN_EVAL_POINTS:
        # 줄표 없이 — 문 · 노드가 '… 없습니다 — {사유}' 로 이어 붙이므로 사유 안의 줄표는 한 문장에 둘째 줄표가 된다.
        return _no(f"평가 시점이 {n_eval}개로 최소 {MIN_EVAL_POINTS}개에 못 미칩니다(경로 {len(points)}개월 · "
                   f"준비 구간 {min_history}개월 · 예측 {k}개월). 이 표본의 점수는 한 시점이 크게 움직입니다.", k)

    rows = _walk(points, k=k, min_history=min_history, arms=arms or cached_arms)
    compared = len(CANDIDATES) - 1
    threshold = compared / alpha
    with_evidence = k == 1
    base_brier = [brier(r["probs"][BASELINE], r["realized"]) for r in rows]

    candidates: list[dict[str, Any]] = []
    for key in CANDIDATES:
        first_fail = next((r for r in rows if key in r["fail"]), None)
        row: dict[str, Any] = {"key": key, "name": CANDIDATE_NAMES[key], "available": first_fail is None,
                               "hits": None, "hit_rate": None, "brier": None, "gain": None, "evidence": None, "reason": None}
        if first_fail is not None:
            row["reason"] = f"{first_fail['origin']} 시점에 세우지 못했습니다 — {first_fail['fail'][key]}"
            candidates.append(row)
            continue
        scores = [brier(r["probs"][key], r["realized"]) for r in rows]
        hits = sum(top(r["probs"][key]) == r["realized"] for r in rows)
        row.update(hits=hits, hit_rate=round(hits / len(rows), 6), brier=round(sum(scores) / len(scores), 6))
        if key != BASELINE:
            gains = [b - s for b, s in zip(base_brier, scores, strict=True)]
            row["gain"] = round(sum(gains) / len(gains), 6)
            if with_evidence:
                row["evidence"] = _evidence(gains, threshold)
        candidates.append(row)

    return {
        "available": True,
        "k": k, "min_history": min_history, "n_eval": len(rows),
        "scored": {"first": rows[0]["label"], "last": rows[-1]["label"]},
        "baseline": BASELINE,
        "candidates": candidates,
        "evidence": {
            "method": evalue.METHOD, "alpha": alpha, "compared": compared, "threshold": threshold,
            "computed": with_evidence, "reason": None if with_evidence else EVIDENCE_K_REASON,
            "note": (f"브라이어 차(유지 − 후보)는 늘 −2 ~ 2 안이라 상한 가정 없이 성립하는 값입니다. 기준은 견준 후보 수 {compared} ÷ α "
                     f"{alpha:g} = {threshold:g}이고 지나온 시점의 최고값으로 견줍니다. 후보를 고르라는 뜻이 아니라 '유지보다 확률을 잘 맞혔다'는 증거의 크기입니다."),
        },
        "walk_forward": True,
        "note": (f"각 시점에서 그때까지의 국면 경로와 성장·물가 축만으로 후보를 세워 {k}개월 뒤의 국면을 예측하고 실현된 국면과 견준 점수입니다(워크포워드). "
                 "모든 후보가 같은 시점 · 같은 실현값으로 채점됩니다. 점수를 나란히 보일 뿐 어느 후보를 쓰라고 하지 않습니다 — 배분이 받는 출처는 따로 정합니다."),
        "not_measured": ["국면을 맞히는 것이 배분의 수익 · 위험으로 이어지는지(경제적 가치)"],
    }
