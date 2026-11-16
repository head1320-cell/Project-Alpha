"""국면 예측 비교 — 워크포워드 (M2 · 구현 계획 §2).

답하는 물음은 ③ 하나다: 후보마다 k개월 뒤 국면을 얼마나 맞히는가(같은 시점 · 같은 실현값 · '오늘 국면 유지' 대비).
★고르지 않는다★ — 점수를 나란히 보일 뿐이다. 합성 축 위의 점수는 장치가 뜻대로 도는지의 증거이지 어느 모형이 실제로 더 맞힌다는 증거가 아니다.

시험은 손 계산(늘 같은 국면 · 교대 경로) · 앞보기 0(시점 t 의 적합이 받은 자료의 길이) · e-값의 짝 · 부분 표본 거절 · 캐시 열쇠를 건다.
군집 두 팔은 가짜(`arms`)로 바꿔 시험한다 — 실제 적합은 느리고(120개월 약 13초) 여기서 재는 것은 채점 장치다.
"""
from __future__ import annotations

import math

import pytest

from src.engine import regime_skill as rs
from src.engine.regime_forecast import (
    _posterior_forecast,
    forecast_coverage,
    propagate,
    transition_posterior_mean,
)

REG = ["Goldilocks", "Reflation", "Stagflation", "Disinflation"]
_XY = {"Goldilocks": (1.0, -1.0), "Reflation": (1.0, 1.0), "Stagflation": (-1.0, 1.0), "Disinflation": (-1.0, -1.0)}


def _pts(regimes: list[str]) -> list[dict]:
    """국면 경로 → `regime_path` 모양의 점. 축 값은 그 사분면에 두고 시점마다 조금씩 달리한다(캐시 열쇠가 시점마다 다르게)."""
    out = []
    for n, r in enumerate(regimes):
        g, i = _XY[r]
        out.append({"t": f"{2010 + n // 12}-{n % 12 + 1:02d}", "growth": g * (1 + n / 1000), "inflation": i * (1 + n / 1000), "regime": r})
    return out


def _onehot(r: str) -> dict:
    return {x: (1.0 if x == r else 0.0) for x in REG}


def _quad(g: float, i: float) -> str:
    return ("Reflation" if i >= 0 else "Goldilocks") if g >= 0 else ("Stagflation" if i >= 0 else "Disinflation")


def _arms_like_now(calls: list | None = None):
    """가짜 군집 두 팔 — 마지막 점의 사분면에 확률 1(=오늘 국면 유지와 같은 예측). 받은 자료의 길이를 센다."""
    def arms(g_hist, i_hist):
        if calls is not None:
            calls.append((len(g_hist), g_hist[-1], i_hist[-1]))
        p = _onehot(_quad(g_hist[-1], i_hist[-1]))
        return {"gmm": {"available": True, "probs": dict(p)}, "kmeans": {"available": True, "probs": dict(p)}}
    return arms


def _cand(out: dict, key: str) -> dict:
    return next(c for c in out["candidates"] if c["key"] == key)


# ── 점수 규칙 ──────────────────────────────────────────────────────────────────

def test_brier_is_zero_for_a_sure_hit_two_for_a_sure_miss_and_three_quarters_for_uniform():
    assert rs.brier(_onehot("Reflation"), "Reflation") == 0.0
    assert rs.brier(_onehot("Reflation"), "Stagflation") == 2.0
    assert rs.brier({r: 0.25 for r in REG}, "Goldilocks") == pytest.approx(0.75)


def test_argmax_ties_follow_the_regime_order():
    assert rs.top({"Goldilocks": 0.0, "Reflation": 0.5, "Stagflation": 0.5, "Disinflation": 0.0}) == "Reflation"
    assert rs.top({r: 0.25 for r in REG}) == "Goldilocks"


# ── 전이 행렬 도우미 — 기존 예측의 동작 불변 ──────────────────────────────────────

@pytest.mark.parametrize("seed", range(6))
@pytest.mark.parametrize("k", [1, 3])
def test_the_matrix_helpers_reproduce_the_existing_posterior_forecast_exactly(seed, k):
    import random
    rnd = random.Random(seed)
    path = [rnd.choice(REG) for _ in range(40)]
    via = propagate(_onehot(path[-1]), transition_posterior_mean(path), k)
    assert via == _posterior_forecast(path, k)


def test_forecast_coverage_is_unchanged_on_a_fixed_path():
    """골든 — 도우미로 나눈 뒤에도 적중률 본문이 같다(손으로 고른 경로 · 값은 나누기 전의 구현에서 뽑아 적은 것 · 2026-11-16)."""
    path = (["Goldilocks"] * 10 + ["Reflation"] * 8 + ["Stagflation"] * 6 + ["Disinflation"] * 6) * 2
    out = forecast_coverage(path, k=1, alpha=0.1, min_history=24)
    assert (out["hits"], out["misses"], out["n_eval"]) == (36, 0, 36)
    assert out["mean_set_size"] == 2.8055555555555554
    assert out["baseline_mean_set_size"] == 3.9166666666666665
    assert out["set_size_skill_pct"] == 28.369


# ── 손 계산 ────────────────────────────────────────────────────────────────────

def test_a_constant_path_is_hit_every_time_by_persistence_and_the_transition_brier_follows_the_hand_formula():
    """늘 Goldilocks 인 60개월 · k = 1 · 준비 36 → 평가 24점.

    전이 예측: 시점 t 의 경로(길이 t)에는 G→G 가 t−1 번이고 G 행의 사후는 (4 + t − 1, 1, 1, 1) / (t + 6).
    실현이 G 이니 브라이어 = (1 − (t+3)/(t+6))² + 3·(1/(t+6))² = 9/(t+6)² + 3/(t+6)² = 12/(t+6)².
    """
    out = rs.regime_skill(_pts(["Goldilocks"] * 60), k=1, arms=_arms_like_now())
    assert out["available"] and out["n_eval"] == 24
    keep = _cand(out, "persistence")
    assert (keep["hits"], keep["hit_rate"], keep["brier"]) == (24, 1.0, 0.0)
    want = sum(12 / (t + 6) ** 2 for t in range(36, 60)) / 24
    tr = _cand(out, "transition")
    assert tr["hits"] == 24 and tr["brier"] == pytest.approx(want, abs=1e-6)
    assert tr["gain"] == pytest.approx(-want, abs=1e-6)            # 유지보다 확률을 덜 실었다 — 이득은 음수
    base = _cand(out, "base_rate")
    assert (base["hits"], base["brier"], base["gain"]) == (24, 0.0, 0.0)


def test_an_alternating_path_defeats_persistence_and_the_transition_forecast_learns_it():
    """G · R · G · R … — 다음 달은 늘 다른 국면이라 '오늘 국면 유지'는 한 번도 맞지 않는다(브라이어 2).
    전이 예측은 G→R · R→G 를 배워 모두 맞힌다(짝: 유지와 정반대)."""
    out = rs.regime_skill(_pts(["Goldilocks", "Reflation"] * 30), k=1, arms=_arms_like_now())
    keep = _cand(out, "persistence")
    assert (keep["hits"], keep["brier"]) == (0, 2.0)
    tr = _cand(out, "transition")
    assert tr["hits"] == out["n_eval"] == 24
    assert tr["gain"] > 1.0
    # 가짜 군집 팔은 마지막 점의 사분면 = 유지와 같은 예측 → 같은 점수(이득 0)
    now = _cand(out, "gmm_now")
    assert (now["hits"], now["brier"], now["gain"]) == (0, 2.0, 0.0)


def test_gmm_start_is_pi0_times_the_transition_matrix_to_the_k():
    """GMM 시작 분포 × 전이: π₀ · P̄^k — 손으로 곱한 값과 시점마다 같다(`_walk` 의 시점별 예측)."""
    path = (["Goldilocks"] * 5 + ["Reflation"] * 5 + ["Stagflation"] * 5 + ["Disinflation"] * 5) * 3
    pts = _pts(path)
    pi0 = {"Goldilocks": 0.1, "Reflation": 0.2, "Stagflation": 0.3, "Disinflation": 0.4}

    def arms(g, i):
        return {"gmm": {"available": True, "probs": dict(pi0)}, "kmeans": {"available": True, "probs": dict(pi0)}}
    rows = rs._walk(pts, k=2, min_history=36, arms=arms)
    assert rows, "평가 시점이 없다 — 시험이 공허하다"
    for row in rows:
        m = transition_posterior_mean(path[:row["t"]])
        want = [sum(pi0[REG[a]] * m[a][b] for a in range(4)) for b in range(4)]
        want = [sum(want[a] * m[a][b] for a in range(4)) for b in range(4)]
        got = row["probs"]["gmm_start"]
        assert [got[r] for r in REG] == pytest.approx(want, abs=1e-12)
        assert row["probs"]["gmm_now"] == pi0                     # 지금 값은 k 와 무관하게 그대로


# ── 앞보기 0 ───────────────────────────────────────────────────────────────────

def test_each_fit_sees_exactly_the_history_up_to_its_own_time():
    calls: list = []
    pts = _pts((["Goldilocks"] * 7 + ["Stagflation"] * 5) * 5)       # 60개월
    out = rs.regime_skill(pts, k=1, arms=_arms_like_now(calls))
    assert [n for n, _, _ in calls] == list(range(36, 60)) and out["n_eval"] == 24
    for n, g_last, i_last in calls:
        assert (g_last, i_last) == (pts[n - 1]["growth"], pts[n - 1]["inflation"])   # 시점 t 의 마지막 점은 t−1


def test_appending_months_does_not_change_the_earlier_predictions():
    base = (["Goldilocks"] * 4 + ["Reflation"] * 3 + ["Disinflation"] * 5) * 5   # 60
    more = base + ["Stagflation"] * 12
    a = rs._walk(_pts(base), k=1, min_history=36, arms=_arms_like_now())
    b = rs._walk(_pts(more), k=1, min_history=36, arms=_arms_like_now())
    assert [r["t"] for r in a] == [r["t"] for r in b][: len(a)]
    for ra, rb in zip(a, b, strict=False):
        assert ra["probs"] == rb["probs"] and ra["realized"] == rb["realized"]


def test_the_realized_regime_is_k_months_after_the_last_point_of_the_history():
    path = (["Goldilocks", "Reflation", "Stagflation"]) * 20
    rows = rs._walk(_pts(path), k=3, min_history=36, arms=_arms_like_now())
    assert all(r["realized"] == path[r["t"] + 3 - 1] for r in rows)
    assert len(rows) == 60 - 3 - 36 + 1


# ── 순차 증거(e-값) ─────────────────────────────────────────────────────────────

def test_a_candidate_identical_to_persistence_carries_no_evidence():
    out = rs.regime_skill(_pts(["Goldilocks", "Reflation"] * 30), k=1, arms=_arms_like_now())
    ev = _cand(out, "gmm_now")["evidence"]
    assert ev["peak"] == 1.0 and ev["e_value"] == 1.0 and ev["passed"] is False


def test_a_candidate_that_is_always_right_against_a_baseline_that_is_always_wrong_passes_the_threshold():
    out = rs.regime_skill(_pts(["Goldilocks", "Reflation"] * 30), k=1, arms=_arms_like_now())
    ev = _cand(out, "transition")["evidence"]
    assert ev["passed"] is True and ev["peak"] >= out["evidence"]["threshold"]


def test_the_threshold_is_the_number_of_compared_candidates_over_alpha():
    out = rs.regime_skill(_pts(["Goldilocks"] * 60), k=1, arms=_arms_like_now())
    assert out["evidence"]["compared"] == 5 and out["evidence"]["threshold"] == pytest.approx(100.0)
    out = rs.regime_skill(_pts(["Goldilocks"] * 60), k=1, alpha=0.1, arms=_arms_like_now())
    assert out["evidence"]["threshold"] == pytest.approx(50.0)


def test_the_evidence_is_exact_because_a_brier_difference_never_leaves_minus_two_to_two():
    """d = 브라이어(유지) − 브라이어(후보) ∈ [−2, 2] — 상한 2 에서 잘리는 일이 없다(가정 문장이 붙지 않는다)."""
    out = rs.regime_skill(_pts((["Goldilocks"] * 3 + ["Disinflation"] * 2) * 12), k=1, arms=_arms_like_now())
    assert out["evidence"]["computed"] is True and out["evidence"]["reason"] is None
    assert "상한 가정 없이" in out["evidence"]["note"]


def test_no_evidence_for_k_above_one_with_a_reason_and_the_scores_still_stand():
    out = rs.regime_skill(_pts(["Goldilocks", "Reflation"] * 30), k=2, arms=_arms_like_now())
    assert out["evidence"]["computed"] is False and "겹칩니다" in out["evidence"]["reason"]
    assert all(c["evidence"] is None for c in out["candidates"])
    assert _cand(out, "transition")["hits"] == out["n_eval"]        # 짝: 점수는 그대로 낸다


def test_the_baseline_has_no_gain_and_no_evidence():
    out = rs.regime_skill(_pts(["Goldilocks"] * 60), k=1, arms=_arms_like_now())
    keep = _cand(out, "persistence")
    assert keep["gain"] is None and keep["evidence"] is None and out["baseline"] == "persistence"


# ── 값 없음 + 사유 ──────────────────────────────────────────────────────────────

def test_too_few_evaluation_points_gives_no_scores_and_a_reason():
    out = rs.regime_skill(_pts(["Goldilocks"] * 55), k=1, arms=_arms_like_now())    # 평가 19점
    assert out["available"] is False and "19" in out["reason"] and "20" in out["reason"]
    assert "candidates" not in out
    # 노드 · 문이 '… 없습니다 — {사유}' 로 이어 붙인다 — 사유 안에 줄표가 또 있으면 한 문장에 줄표가 둘이 된다(스크린샷 검수에서 찾음).
    assert "—" not in out["reason"] and "(경로 55개월 · 준비 구간 36개월 · 예측 1개월)" in out["reason"]


def test_twenty_evaluation_points_is_enough():
    out = rs.regime_skill(_pts(["Goldilocks"] * 56), k=1, arms=_arms_like_now())
    assert out["available"] is True and out["n_eval"] == 20


def test_an_unknown_regime_label_is_refused_with_a_reason():
    pts = _pts(["Goldilocks"] * 60)
    pts[40] = {**pts[40], "regime": "Boom"}
    out = rs.regime_skill(pts, k=1, arms=_arms_like_now())
    assert out["available"] is False and "Boom" in out["reason"]


def test_a_candidate_that_cannot_be_built_at_one_time_is_not_scored_on_a_partial_sample():
    pts = _pts(["Goldilocks", "Reflation"] * 30)
    fail_at = 45

    def arms(g, i):
        p = _onehot(_quad(g[-1], i[-1]))
        gmm = {"available": False, "reason": "군집 모형 적합 실패 (LinAlgError)"} if len(g) == fail_at else {"available": True, "probs": p}
        return {"gmm": gmm, "kmeans": {"available": True, "probs": dict(p)}}
    out = rs.regime_skill(pts, k=1, arms=arms)
    for key in ("gmm_now", "gmm_start"):
        c = _cand(out, key)
        assert c["available"] is False and c["hits"] is None and c["brier"] is None and c["evidence"] is None
        assert pts[fail_at - 1]["t"] in c["reason"] and "LinAlgError" in c["reason"]
    k = _cand(out, "kmeans_share")                                  # 짝: 다른 후보는 채점된다
    assert k["available"] is True and k["hits"] is not None


# ── 고르지 않는다 ───────────────────────────────────────────────────────────────

def test_the_answer_names_no_winner_and_keeps_a_fixed_order():
    out = rs.regime_skill(_pts(["Goldilocks", "Reflation"] * 30), k=1, arms=_arms_like_now())
    assert [c["key"] for c in out["candidates"]] == list(rs.CANDIDATES)
    assert [c["key"] for c in out["candidates"]] != [c["key"] for c in sorted(out["candidates"], key=lambda c: c["brier"])]
    flat = repr(out).lower()
    for word in ("best", "winner", "rank", "recommend", "최선", "추천"):
        assert word not in flat
    assert "쓰라고 하지 않습니다" in out["note"]


def test_every_candidate_has_a_korean_name_from_one_table():
    out = rs.regime_skill(_pts(["Goldilocks"] * 60), k=1, arms=_arms_like_now())
    assert {c["key"]: c["name"] for c in out["candidates"]} == rs.CANDIDATE_NAMES
    assert set(rs.CANDIDATE_NAMES) == set(rs.CANDIDATES)


# ── 캐시 — 열쇠는 축 값이다 ──────────────────────────────────────────────────────

def test_cached_arms_returns_the_same_fit_for_the_same_axes_and_refits_when_the_axes_change(monkeypatch):
    seen: list = []

    def fake(g, i):
        seen.append(len(g))
        return {"gmm": {"available": True, "probs": _onehot("Goldilocks")}, "kmeans": {"available": True, "probs": _onehot("Goldilocks")}}
    monkeypatch.setattr(rs, "default_arms", fake)
    rs.cached_arms.cache_clear()
    g, i = [0.1] * 40, [0.2] * 40
    a = rs.cached_arms(tuple(g), tuple(i))
    b = rs.cached_arms(tuple(g), tuple(i))
    assert a is b and seen == [40]
    c = rs.cached_arms(tuple(g[:-1] + [0.3]), tuple(i))              # 같은 길이 · 다른 값 → 다시 적합
    assert c is not a and seen == [40, 40]
    rs.cached_arms.cache_clear()


def test_the_default_arms_are_the_ensemble_cluster_arms(monkeypatch):
    import src.engine.regime_ensemble as ens
    monkeypatch.setattr(ens, "_cluster_probs", lambda g, i: {"available": True, "probs": {"tag": "gmm"}})
    monkeypatch.setattr(ens, "_kmeans_probs", lambda g, i: {"available": True, "probs": {"tag": "km"}})
    out = rs.default_arms([0.0] * 36, [0.0] * 36)
    assert out["gmm"]["probs"] == {"tag": "gmm"} and out["kmeans"]["probs"] == {"tag": "km"}


def test_probabilities_are_finite_and_sum_to_one_for_every_candidate():
    rows = rs._walk(_pts((["Goldilocks"] * 6 + ["Stagflation"] * 6) * 5), k=4, min_history=36, arms=_arms_like_now())
    for row in rows:
        for key, p in row["probs"].items():
            assert p is not None and all(math.isfinite(v) and v >= 0 for v in p.values()), key
            assert sum(p.values()) == pytest.approx(1.0, abs=1e-9), key
