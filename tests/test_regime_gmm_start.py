"""M3 — 배분의 셋째 국면 가중 'GMM 시작 분포' (2026-11-16 · 계획 §3)
==============================================================================
설계 `docs/superpowers/specs/2026-11-16-emeans-gmm-strategy-design.md` §M3 · 계획 §3.

## 답하는 물음 — ② 전달 (예측력 · 경제적 가치가 아니다)

보유 기간의 국면 분포를 'GMM 시작 분포 × 전이'(π_j = π₀ · P̄^j)로 잡으면 배분 입력 π 가 그렇게 바뀐다.
★출처의 실측 점수(M2 의 워크포워드 점수)가 같은 응답에 실렸을 때만 배분에 닿는다★ — 실측 없는 출처는 계약이 거부한다.

## 거는 것
1. 계약: 점수 없는 GMM 출처는 생성자도 문지기도 거부(손으로 지은 위조 객체 포함) ↔ 점수가 있으면 통과 ·
   π₀ 검사 · π_j = π₀ · P̄^j 손 계산 · 원핫 시작이면 전이 예측과 같은 경로(짝).
2. 엔진(가짜 군집 팔): π₀ · 점수 · 시드 안정성 · 부트스트랩 · 세우지 못하는 경우마다 사유 · 앞보기 0.
3. 파이프라인: 성공 = `gmm` + 출처 블록 ↔ 점수가 없으면 전이 예측으로 ★명시적으로★ 열화(사유) · hard · probabilistic 불변.
4. 백테스트 팔 G: 달마다 그 달까지 자른 경로 · 그 달의 열화 사유 · 다른 팔 불변.
5. 문 · 캔버스: 패턴 · 선택지 이름 · 해설(방식마다의 가정 · 열화 사유 · 점수 줄).
"""
from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from src.engine.regime_probability import (
    SOURCE_FORECAST_MEAN,
    SOURCE_GMM_START,
    USAGE_PORTFOLIO,
    RegimeProbabilities,
    from_gmm_start_path,
    from_posterior_mean_path,
    require_portfolio_source,
)

REGIMES = ["Goldilocks", "Reflation", "Stagflation", "Disinflation"]


def _rows():
    """`transition_posterior` 모양 — 지속 0.7 · 나머지 0.1 씩(행 합 1). 계약 시험(`test_regime_probability_contract`)과 같은 꼴."""
    stay, off = 14, 2
    return [{"from": r, "counts": [(stay if q == r else off) for q in REGIMES], "n": stay + off * 3,
             "mean": {q: ((stay if q == r else off) / 20.0) for q in REGIMES}, "shrunk": False}
            for r in REGIMES]


def _skill(k: int = 1, n_eval: int = 24, **over) -> dict:
    """엔진이 M2 의 결과에서 뽑아 싣는 점수 요약(후보 `gmm_start`)."""
    base = {"available": True, "k": k, "n_eval": n_eval, "scored": {"first": "2024-01", "last": "2026-09"},
            "hits": 20, "hit_rate": 0.833333, "brier": 0.21, "gain": 0.012, "baseline": "persistence",
            "evidence": None, "evidence_reason": None}
    base.update(over)
    return base


PI0 = {"Goldilocks": 0.5, "Reflation": 0.5, "Stagflation": 0.0, "Disinflation": 0.0}


# ══ 1. 계약 ═══════════════════════════════════════════════════════════════════

def test_a_gmm_start_path_with_a_measured_skill_is_a_portfolio_source():
    probs, P = from_gmm_start_path(PI0, _rows(), 1, REGIMES, skill=_skill(k=1), mode="live")
    assert [p.source for p in probs] == [SOURCE_GMM_START]
    assert [p.usage for p in probs] == [USAGE_PORTFOLIO]
    for p in probs:
        assert require_portfolio_source(p) is p
    assert p.detail["skill"]["n_eval"] == 24 and p.detail["pi0"] == PI0, "출처의 점수와 시작 분포가 객체와 함께 간다"
    assert len(P) == 4 and all(abs(sum(r) - 1.0) < 1e-12 for r in P)


def test_without_a_measured_skill_the_contract_refuses():
    """★실측 없는 출처는 계약이 거부한다★ — 사유는 M2 의 사유 그대로 실려 위로 간다."""
    why = "평가 시점이 17개로 최소 20개에 못 미칩니다(경로 53개월 · 준비 구간 36개월 · 예측 1개월). 이 표본의 점수는 한 시점이 크게 움직입니다."
    with pytest.raises(ValueError, match="워크포워드 점수") as e:
        from_gmm_start_path(PI0, _rows(), 1, REGIMES, skill={"available": False, "k": 1, "reason": why})
    assert why in str(e.value)
    with pytest.raises(ValueError, match="워크포워드 점수"):
        from_gmm_start_path(PI0, _rows(), 1, REGIMES, skill=None)


@pytest.mark.parametrize(("over", "why"), [
    ({"n_eval": 19}, "평가 시점"),
    ({"k": 3}, "보유 기간"),
])
def test_a_skill_on_too_few_points_or_another_horizon_is_refused(over, why):
    with pytest.raises(ValueError, match=why):
        from_gmm_start_path(PI0, _rows(), 1, REGIMES, skill=_skill(**over))


def test_the_gate_refuses_a_forged_gmm_object_without_a_skill():
    """생성자를 건너뛰고 손으로 지은 객체도 문지기에서 걸린다 — ★이름이 아니라 값으로 거른다★."""
    forged = RegimeProbabilities(source=SOURCE_GMM_START, step_months=1, probs=dict(PI0),
                                 usage=USAGE_PORTFOLIO, detail={})
    with pytest.raises(ValueError, match="워크포워드 점수"):
        require_portfolio_source(forged)
    # 짝: 같은 모양에 점수가 실려 있으면 통과
    ok = dataclasses.replace(forged, detail={"skill": _skill(k=1)})
    assert require_portfolio_source(ok) is ok
    # 짝: 점수의 k 가 객체의 걸음과 다르지 않아도 — 걸음 2 의 객체도 경로의 점수(k = 보유 기간)를 싣는다
    step2 = dataclasses.replace(forged, step_months=2, detail={"skill": _skill(k=3)})
    assert require_portfolio_source(step2) is step2


def test_the_path_is_pi0_times_the_transition_matrix_to_the_j_by_hand():
    """P̄ 는 지속 0.7 · 나머지 0.1 — π₀ = (½, ½, 0, 0) 이면
    π₁ = (0.4, 0.4, 0.1, 0.1) · π₂ = (0.34, 0.34, 0.16, 0.16) (손 계산)."""
    probs, _ = from_gmm_start_path(PI0, _rows(), 2, REGIMES, skill=_skill(k=2))
    assert [p.step_months for p in probs] == [1, 2]
    want = [(0.4, 0.4, 0.1, 0.1), (0.34, 0.34, 0.16, 0.16)]
    for p, w in zip(probs, want, strict=True):
        assert [round(p.probs[r], 12) for r in REGIMES] == list(w)


def test_a_one_hot_start_is_exactly_the_transition_forecast_path():
    """짝 — 시작 분포만 다르다: 원핫(오늘 국면)에서 출발하면 전이 예측(사후평균 경로)과 같은 π 다."""
    onehot = {r: float(r == "Stagflation") for r in REGIMES}
    g, Pg = from_gmm_start_path(onehot, _rows(), 3, REGIMES, skill=_skill(k=3))
    f, Pf = from_posterior_mean_path(_rows(), "Stagflation", 3, REGIMES)
    assert Pg == Pf
    assert [p.source for p in f] == [SOURCE_FORECAST_MEAN] * 3
    for a, b in zip(g, f, strict=True):
        assert a.probs == pytest.approx(b.probs, abs=1e-15)


@pytest.mark.parametrize(("pi0", "why"), [
    ({**PI0, "Goldilocks": -0.1, "Reflation": 1.1}, "음수"),
    ({"Goldilocks": 1.0}, "국면"),
    ({r: 0.0 for r in REGIMES}, "합"),
    ({r: 0.3 for r in REGIMES}, "합"),
    ({**PI0, "Goldilocks": float("nan")}, "숫자"),
])
def test_the_start_distribution_is_checked(pi0, why):
    with pytest.raises(ValueError, match=why):
        from_gmm_start_path(pi0, _rows(), 1, REGIMES, skill=_skill())


def test_a_start_rounded_to_four_digits_is_renormalised_not_refused():
    """GMM 팔은 시드 평균을 4자리로 반올림해 낸다(합 0.9999 ~ 1.0001) — 그만큼은 받고 합을 1 로 되돌린다."""
    rounded = {"Goldilocks": 0.3333, "Reflation": 0.3333, "Stagflation": 0.3333, "Disinflation": 0.0}
    probs, _ = from_gmm_start_path(rounded, _rows(), 1, REGIMES, skill=_skill())
    assert sum(probs[0].probs.values()) == pytest.approx(1.0, abs=1e-12)
    assert probs[0].detail["pi0"] == rounded, "실린 시작 분포는 받은 값 그대로(되돌린 것은 계산에만)"


def test_the_mixture_accepts_the_gmm_path_as_one_chain():
    """혼합 함수의 일관성 검사(π_{j+1} = π_j · P)가 GMM 경로를 받는다 — π 와 P 가 같은 사슬에서 나왔다."""
    from src.engine.conditional_market import _validate_path
    probs, P = from_gmm_start_path(PI0, _rows(), 3, REGIMES, skill=_skill(k=3))
    pis = np.array([[p.probs[r] for r in REGIMES] for p in probs])
    assert _validate_path(pis, np.asarray(P), 3) is None


# ══ 2. 엔진 — `regime_gmm_start.gmm_start_path` (가짜 군집 팔 · 결정적) ═══════════

from src.engine import regime_gmm_start as gs  # noqa: E402
from src.engine import regime_skill as rs  # noqa: E402
from src.engine.regime_axes import quadrant  # noqa: E402


def _long_points(months: int = 120) -> list[dict]:
    """두 축이 다 계산된 달 120개의 합성 경로(M2 의 시험 계열 · 달 이름 YYYY-MM)."""
    from src.engine.regime_transitions import regime_path
    from tests.test_regime_skill_routes import _dated_series
    return regime_path(_dated_series(160), "kr", months=months)["points"]


def _stab(r: str) -> dict:
    return {"seeds": 10, "modal": r, "agree": 9, "shares": {q: (0.9 if q == r else round(0.1 / 3, 4)) for q in REGIMES},
            "stable": True}


def _fake_arms(calls: list | None = None):
    """지금 점(마지막 축)의 사분면에 0.7 · 나머지 0.1 — 받은 자료 길이를 적는다(앞보기 시험)."""
    def arms(g, i):
        if calls is not None:
            calls.append(len(g))
        r = quadrant(float(g[-1]), float(i[-1]))
        return {"gmm": {"available": True, "probs": {q: (0.7 if q == r else 0.1) for q in REGIMES}, "argmax": r,
                        "stability": _stab(r)},
                "kmeans": {"available": True, "probs": {q: float(q == r) for q in REGIMES}}}
    return arms


def _fake_boot(seen: list | None = None):
    def boot(g, i, label):
        if seen is not None:
            seen.append((len(g), label))
        return {"available": True, "method": "bootstrap_months", "resamples": 20, "agree": 17, "share": 0.85,
                "label": label, "note": "가짜"}
    return boot


def test_the_path_starts_from_the_gmm_membership_and_carries_the_skill():
    pts = _long_points()
    arms = _fake_arms()
    out = gs.gmm_start_path(pts, 1, mode="live", arms=arms, bootstrap=_fake_boot())
    assert out["available"] is True, out.get("reason")
    last = quadrant(float(pts[-1]["growth"]), float(pts[-1]["inflation"]))
    assert out["pi0"] == {q: (0.7 if q == last else 0.1) for q in REGIMES}, "π₀ = 그 경로 전체로 적합한 GMM 의 지금 점 소속 확률"
    assert [p.source for p in out["probs"]] == [SOURCE_GMM_START]
    # 점수 = 같은 경로 · 같은 팔 · k = 보유 기간의 M2 후보 gmm_start
    ref = rs.regime_skill(pts, k=1, arms=arms)
    cand = next(c for c in ref["candidates"] if c["key"] == "gmm_start")
    sk = out["skill"]
    assert (sk["k"], sk["n_eval"], sk["hits"], sk["hit_rate"], sk["brier"], sk["gain"]) == (
        1, ref["n_eval"], cand["hits"], cand["hit_rate"], cand["brier"], cand["gain"])
    assert sk["evidence"] == cand["evidence"] and sk["evidence"] is not None, "1개월 앞이면 순차 증거도 함께"
    assert out["stability"] == _stab(last)
    assert out["robustness"]["share"] == 0.85 and out["robustness"]["label"] == last
    assert out["probs"][0].detail["skill"] == sk, "계약 객체가 같은 점수를 싣는다"


def test_three_months_holding_scores_three_months_ahead():
    out = gs.gmm_start_path(_long_points(), 3, arms=_fake_arms(), bootstrap=_fake_boot())
    assert out["available"] is True, out.get("reason")
    assert [p.step_months for p in out["probs"]] == [1, 2, 3]
    assert out["skill"]["k"] == 3 and out["skill"]["evidence"] is None and out["skill"]["evidence_reason"]


def test_every_fit_sees_only_the_path_it_was_given():
    """★앞보기 0★ 팔이 받은 자료는 넘긴 경로의 앞부분뿐 — 가장 긴 것이 그 경로 전체(지금 점)다."""
    pts = _long_points()[:80]
    calls: list[int] = []
    seen: list = []
    out = gs.gmm_start_path(pts, 1, arms=_fake_arms(calls), bootstrap=_fake_boot(seen))
    assert out["available"] is True, out.get("reason")
    assert max(calls) == len(pts) and min(calls) >= rs.MIN_HISTORY
    assert seen == [(len(pts), out["robustness"]["label"])], "부트스트랩도 그 경로만"


def test_the_label_is_the_gmm_answer_not_the_path_label():
    """지금 점의 이름표 = GMM 시작 분포의 최다 국면 — 경로의 하드 라벨(사분면)과 다를 수 있다(경계 근처의 점).
    다시 뽑기도 ★그 답★과 견준다(위 시험들은 둘이 늘 같은 가짜 팔이라 이 차이를 보지 못했다)."""
    pts = _long_points()
    last = str(pts[-1]["regime"])
    other = next(q for q in REGIMES if q != last)

    def arms(g, i):
        return {"gmm": {"available": True, "probs": {q: (0.7 if q == other else 0.1) for q in REGIMES}, "argmax": other,
                        "stability": _stab(other)},
                "kmeans": {"available": True, "probs": {q: float(q == other) for q in REGIMES}}}
    seen: list = []
    out = gs.gmm_start_path(pts, 1, arms=arms, bootstrap=_fake_boot(seen))
    assert out["available"] is True, out.get("reason")
    assert out["label"] == other != last
    assert seen == [(len(pts), other)] and out["robustness"]["label"] == other, "다시 뽑기는 GMM 의 답과 견준다"


def test_without_a_skill_the_path_is_not_built_and_says_why():
    """개발 자료와 같은 길이(53개월) — 평가 시점 17개라 점수가 없다 → 세우지 않고 M2 의 사유를 그대로."""
    out = gs.gmm_start_path(_long_points()[:53], 1, arms=_fake_arms(), bootstrap=_fake_boot())
    assert out["available"] is False
    assert "워크포워드 점수가 없습니다" in out["reason"] and "평가 시점이 17개" in out["reason"]
    assert out["skill"]["available"] is False, "없다는 사실도 싣는다"


def test_a_path_without_axis_values_says_why():
    pts = [dict(p) for p in _long_points()]
    del pts[5]["growth"]
    out = gs.gmm_start_path(pts, 1, arms=_fake_arms(), bootstrap=_fake_boot())
    assert out["available"] is False and "축 값" in out["reason"]


def test_a_gmm_that_cannot_be_fit_says_why():
    def arms(g, i):
        return {"gmm": {"available": False, "reason": "군집 모형 적합 실패 (ValueError)"},
                "kmeans": {"available": False, "reason": "x"}}
    out = gs.gmm_start_path(_long_points(), 1, arms=arms, bootstrap=_fake_boot())
    assert out["available"] is False
    assert out["reason"] == "GMM 을 세우지 못했습니다 — 군집 모형 적합 실패 (ValueError)"


class _FakeGM:
    """부트스트랩 시험용 — 성분 넷의 중심은 늘 네 사분면 · 지금 점은 random_state 가 짝수면 Reflation 성분에, 홀수면 Stagflation 성분에."""

    fail_on: set[int] = set()

    def __init__(self, n_components, covariance_type, random_state, n_init):
        self.k, self.s = n_components, random_state

    def fit(self, X):
        if self.s in self.fail_on:
            raise ValueError("boom")
        self.means_ = np.array([(1.0, -1.0), (1.0, 1.0), (-1.0, 1.0), (-1.0, -1.0)][: self.k])
        return self

    def predict_proba(self, X):
        hot = 1 if self.s % 2 == 0 else 2
        return np.array([[float(c == hot) for c in range(self.k)]])


def test_the_bootstrap_counts_resamples_whose_answer_matches(monkeypatch):
    monkeypatch.setattr("sklearn.mixture.GaussianMixture", _FakeGM)
    monkeypatch.setattr(_FakeGM, "fail_on", set())
    g, i = [0.5] * 60, [0.5] * 60
    out = gs.bootstrap_agreement(g, i, "Reflation", resamples=20)
    assert (out["available"], out["resamples"], out["agree"], out["share"], out["label"]) == (True, 20, 10, 0.5, "Reflation")
    assert "π 를 바꾸지 않습니다" in out["note"]


def test_failed_resamples_are_counted_out_not_faked(monkeypatch):
    monkeypatch.setattr("sklearn.mixture.GaussianMixture", _FakeGM)
    monkeypatch.setattr(_FakeGM, "fail_on", {0, 2, 4})
    out = gs.bootstrap_agreement([0.5] * 60, [0.5] * 60, "Reflation", resamples=20)
    assert (out["requested"], out["resamples"], out["agree"], out["failed"]) == (20, 17, 7, 3), "실패한 다시 뽑기는 세지 않고 그 수를 적는다"
    assert out["share"] == round(7 / 17, 4), "비율의 분모는 끝난 다시 뽑기 수다 — 실패를 '다른 답'으로 세지 않는다"
    monkeypatch.setattr(_FakeGM, "fail_on", set(range(20)))
    out = gs.bootstrap_agreement([0.5] * 60, [0.5] * 60, "Reflation", resamples=20)
    assert out["available"] is False and "모두 실패" in out["reason"]


def test_each_resample_draws_months_with_replacement_and_reads_the_real_now(monkeypatch):
    """다시 뽑기 = 달의 복원 추출 — 적합마다 표본이 다르고 · 같은 달이 거듭 나오며 · 원래 달의 행만 쓴다. 답은 ★실제 지금 점★
    (마지막 달)에서 읽는다(뽑힌 표본의 끝이 아니다). 같은 시드면 같은 뽑기(재현) ↔ 다른 시드면 다른 뽑기(짝)."""
    fits: list = []
    asked: list = []

    class Rec(_FakeGM):
        def fit(self, X):
            fits.append(np.array(X, copy=True))
            return super().fit(X)

        def predict_proba(self, X):
            asked.append(np.array(X, copy=True))
            return super().predict_proba(X)

    monkeypatch.setattr("sklearn.mixture.GaussianMixture", Rec)
    monkeypatch.setattr(_FakeGM, "fail_on", set())
    g = [float(t) for t in range(60)]          # 달마다 다른 값 — 뽑힌 행으로 어느 달인지 안다
    i = [float(-t) for t in range(60)]
    orig = np.column_stack([g, i])
    gs.bootstrap_agreement(g, i, "Reflation", resamples=5)
    assert len(fits) == 5 and len(asked) == 5
    for X in fits:
        months = X[:, 0].astype(int)
        assert X.shape == orig.shape and (X == orig[months]).all(), "원래 달의 행만 뽑는다"
        assert len(set(months.tolist())) < len(months), "복원 추출 — 같은 달이 거듭 뽑힌다"
    assert len({tuple(X[:, 0]) for X in fits}) == 5, "다시 뽑기마다 다른 표본"
    assert all(a.shape == (1, 2) and (a == orig[-1:]).all() for a in asked), "답은 실제 지금 점에서 읽는다"
    first = [X.copy() for X in fits]
    fits.clear()
    gs.bootstrap_agreement(g, i, "Reflation", resamples=5)
    assert all((a == b).all() for a, b in zip(first, fits, strict=True)), "같은 시드 → 같은 뽑기"
    fits.clear()
    gs.bootstrap_agreement(g, i, "Reflation", resamples=5, seed=gs.BOOT_SEED + 1)
    assert not (first[0] == fits[0]).all(), "짝 — 다른 시드면 다른 뽑기"


def test_the_bootstrap_on_clearly_clustered_data_always_agrees():
    """실제 추정기 — 뚜렷이 뭉친 자료(시드 안정 시험의 네 덩어리)에서는 다시 뽑아도 같은 답(기계와 무관하게 성립하는 경우)."""
    from tests.test_regime_seed_stability import _blobs
    g, i = _blobs()
    out = gs.bootstrap_agreement(g, i, "Reflation", resamples=20)
    assert (out["available"], out["resamples"], out["agree"]) == (True, 20, 20)


def test_a_short_path_says_why():
    out = gs.gmm_start_path(_long_points()[:30], 1, arms=_fake_arms(), bootstrap=_fake_boot())
    assert out["available"] is False and "30개월" in out["reason"] and "36개월" in out["reason"]


def test_an_unknown_label_says_why():
    pts = [dict(p) for p in _long_points()]
    pts[3]["regime"] = "Boom"
    out = gs.gmm_start_path(pts, 1, arms=_fake_arms(), bootstrap=_fake_boot())
    assert out["available"] is False and "Boom" in out["reason"]


def test_a_reason_never_puts_two_dashes_in_one_sentence():
    """평가 구간의 한 시점에서만 GMM 이 실패 — 점수가 없다는 머리와 M2 의 사유(줄표 하나)가 두 문장으로 이어진다."""
    ok = _fake_arms()

    def arms(g, i):
        if len(g) == 40:
            return {"gmm": {"available": False, "reason": "군집 모형 적합 실패 (LinAlgError)"},
                    "kmeans": {"available": False, "reason": "x"}}
        return ok(g, i)

    out = gs.gmm_start_path(_long_points(), 1, arms=arms, bootstrap=_fake_boot())
    assert out["available"] is False
    assert out["reason"].startswith("같은 경로의 워크포워드 점수가 없습니다. ")
    assert "시점에 세우지 못했습니다 — 군집 모형 적합 실패 (LinAlgError)" in out["reason"]
    assert all(s.count(" — ") <= 1 for s in out["reason"].split(". ")), out["reason"]
    # 짝: 사유에 줄표가 없으면 한 문장('머리 — 사유')
    assert gs._why("머리", "사유") == "머리 — 사유" and gs._why("머리", "가 — 나") == "머리. 가 — 나"


def test_the_backtest_skips_the_bootstrap_and_says_so():
    seen: list = []
    out = gs.gmm_start_path(_long_points(), 1, arms=_fake_arms(), bootstrap=_fake_boot(seen), with_robustness=False)
    assert out["available"] is True and seen == [], "다시 뽑기를 부르지 않는다"
    assert out["robustness"]["available"] is False and "재조정 달마다" in out["robustness"]["reason"]
    assert out["probs"][0].detail["robustness"] == out["robustness"], "없다는 사실도 계약 객체에 실린다"


@pytest.fixture
def _fresh_cache():
    rs.cached_arms.cache_clear()
    yield
    rs.cached_arms.cache_clear()


def test_the_default_arms_are_the_shared_cache(monkeypatch, _fresh_cache):
    """기본 팔 = M2 · 앙상블과 같은 기억(`cached_arms`) — 같은 축이면 한 번만 적합한다."""
    calls: list[int] = []
    monkeypatch.setattr(rs, "default_arms", _fake_arms(calls))
    pts = _long_points()[:80]
    out = gs.gmm_start_path(pts, 1, bootstrap=_fake_boot())
    assert out["available"] is True, out.get("reason")
    first = len(calls)
    assert first == 80 - rs.MIN_HISTORY + 1, "시점마다 한 번 + 지금 한 번 — 지금 점의 적합도 기억에 남는다"
    again = gs.gmm_start_path(pts, 3, bootstrap=_fake_boot())
    assert again["available"] is True and len(calls) == first, "k 가 달라도 같은 축이면 다시 적합하지 않는다"


def test_the_sampled_forecast_from_a_one_hot_start_is_the_transition_one():
    """표집 구간(전이행렬 파라미터의 불확실성) — 원핫에서 출발하면 `k_step_forecast` 와 ★값까지 같다★(같은 씨앗 · 같은 뽑기)."""
    from src.engine.regime_transitions import count_transitions, k_step_forecast, transition_posterior

    pts = _long_points()
    rows = transition_posterior(count_transitions(pts))
    for k in (1, 3):
        ref = k_step_forecast(rows, "Reflation", k=k)
        got = gs.sampled_forecast(rows, {"Goldilocks": 0.0, "Reflation": 1.0, "Stagflation": 0.0, "Disinflation": 0.0}, k)
        assert (got["mean"], got["ci90"], got["draws"]) == (ref["mean"], ref["ci90"], ref["draws"])
    # 짝: 섞인 출발이면 평균은 출발 분포로 가중한 평균(선형) · 구간은 따로 뽑은 값이다(구간의 가중 평균이 아니다)
    mix = gs.sampled_forecast(rows, PI0, 1)
    parts = {r: k_step_forecast(rows, r, k=1)["mean"] for r in ("Goldilocks", "Reflation")}
    for q in REGIMES:
        assert mix["mean"][q] == pytest.approx(0.5 * parts["Goldilocks"][q] + 0.5 * parts["Reflation"][q], abs=2e-6)
    assert "GMM 시작 분포" in mix["note"]


# ══ 3. 파이프라인 — `allocation_pipeline._conditional_stack` 의 `gmm` 분기 ═══════════════

from types import SimpleNamespace  # noqa: E402

from tests.test_regime_weighting_golden import _jsonable  # noqa: E402
from tests.test_regime_weighting_golden import _path as _golden_path  # noqa: E402
from tests.test_regime_weighting_golden import _returns as _golden_returns  # noqa: E402


@pytest.fixture
def stack(monkeypatch, _fresh_cache):
    """가짜 군집 팔(기본 팔 자리) + 고정 경로 · 수익률 → `_conditional_stack` 를 부르는 함수."""
    from src.api import allocation_pipeline as ap

    monkeypatch.setattr(rs, "default_arms", _fake_arms())

    def run(weighting: str, *, months: int = 60, rebalance: str = "M", model: str = "bl"):
        path = _golden_path()[-months:]
        monkeypatch.setattr("src.data.regime_snapshots.get_snapshot",
                            lambda sid: {"as_of": "2025-10-31", "regime_path": [dict(p) for p in path]})
        req = SimpleNamespace(mes_id="rgs_m3", regime_snapshot_id=None, regime_weighting=weighting,
                              regime_mode="live", rebalance=rebalance, model=model)
        return ap._conditional_stack(req, _golden_returns(_golden_path())), path
    return run


def _expected_pi(path, pi0, h):
    from src.engine.regime_probability import _normalized_transition
    from src.engine.regime_transitions import count_transitions, transition_posterior

    P = _normalized_transition(transition_posterior(count_transitions(path)), REGIMES)
    return [dict(zip(REGIMES, np.asarray([pi0[r] for r in REGIMES]) @ np.linalg.matrix_power(P, j), strict=True))
            for j in range(1, h + 1)]


@pytest.mark.parametrize("rebalance,h", [("M", 1), ("Q", 3)])
def test_gmm_mixes_from_the_gmm_start_and_carries_the_score(stack, rebalance, h):
    out, path = stack("gmm", rebalance=rebalance)
    meta = out["meta"]
    assert (meta["regime_weighting"], meta["requested_weighting"], meta["gmm_fallback"]) == ("gmm", "gmm", None)
    assert out["cond"]["available"] is True and meta["h_hold"] == h
    src = meta["probability_source"]
    last = quadrant(float(path[-1]["growth"]), float(path[-1]["inflation"]))
    pi0 = {q: (0.7 if q == last else 0.1) for q in REGIMES}
    assert (src["source"], src["usage"], src["pi0"], src["label"]) == (SOURCE_GMM_START, USAGE_PORTFOLIO, pi0, last)
    assert src["skill"]["available"] is True and src["skill"]["k"] == h and src["skill"]["n_eval"] == 60 - h + 1 - 36
    assert src["stability"]["modal"] == last and src["robustness"]["method"] == "bootstrap_months"
    assert src["sampled_forecast"]["ci90"] is not None and "전파되지 않" in src["uncertainty_note"]
    # ★π_j = π₀ · P̄^j★ — 혼합이 받은 π 가 그 경로다
    for got, want in zip(meta["pi_path"], _expected_pi(path, pi0, h), strict=True):
        assert got == pytest.approx(want, abs=1e-9)
    assert out["extra_views"], "bl 이면 조건부 뷰가 실린다"


def test_gmm_moves_pi_away_from_the_transition_forecast(stack):
    """짝 — 같은 경로에서 전이 예측(원핫 출발)과 π 가 다르다(시작 분포가 실제로 쓰인다)."""
    g, _ = stack("gmm")
    p, _ = stack("probabilistic")
    assert p["meta"]["regime_weighting"] == "probabilistic"
    d = max(abs(g["meta"]["pi_path"][0][q] - p["meta"]["pi_path"][0][q]) for q in REGIMES)
    assert d > 0.05, (g["meta"]["pi_path"], p["meta"]["pi_path"])
    assert "requested_weighting" not in p["meta"] and "gmm_fallback" not in p["meta"], "전이 예측의 응답에는 새 키가 없다(골든)"


def _drop(meta: dict) -> dict:
    return {k: v for k, v in meta.items() if k not in ("requested_weighting", "gmm_fallback")}


def test_without_a_score_gmm_falls_back_to_the_transition_forecast_and_says_why(stack):
    """개발 자료와 같은 53개월 — 점수가 없어 ★명시적으로★ 전이 예측으로 계산한다 · 나머지는 전이 예측의 스택과 같다."""
    g, _ = stack("gmm", months=53)
    p, _ = stack("probabilistic", months=53)
    meta = g["meta"]
    assert (meta["requested_weighting"], meta["regime_weighting"]) == ("gmm", "probabilistic")
    assert "워크포워드 점수가 없습니다" in meta["gmm_fallback"] and "평가 시점이 17개" in meta["gmm_fallback"]
    assert meta["probability_source"]["source"] == SOURCE_FORECAST_MEAN, "쓴 출처를 그대로 적는다(GMM 인 척하지 않는다)"
    assert _drop(meta) == p["meta"] and _jsonable(g["cond"]) == _jsonable(p["cond"])
    assert g["extra_views"] == p["extra_views"] and g["view_conf"] == p["view_conf"]


def test_when_the_transition_forecast_also_fails_it_falls_to_hard_with_both_reasons(stack, monkeypatch):
    def boom(*a, **k):
        raise ValueError("시험: 예측 불가")
    monkeypatch.setattr("src.engine.regime_probability.from_k_step_forecast", boom)
    g, _ = stack("gmm", months=53)
    meta = g["meta"]
    assert (meta["requested_weighting"], meta["regime_weighting"]) == ("gmm", "hard")
    assert "평가 시점이 17개" in meta["gmm_fallback"] and "시험: 예측 불가" in meta["mixture_note"]


def test_a_gmm_mixture_that_cannot_be_formed_falls_back_with_its_reason(stack, monkeypatch):
    """GMM 경로는 섰으나 혼합이 안 되면(첫 부름만 실패) — 전이 예측으로 · 사유는 혼합의 것."""
    import src.engine.conditional_market as cm

    real, calls = cm.regime_mixture_moments, []

    def flaky(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            return {"available": False, "reason": "시험: 국면 하나의 표본이 모자랍니다"}
        return real(*a, **k)
    monkeypatch.setattr(cm, "regime_mixture_moments", flaky)
    g, _ = stack("gmm")
    meta = g["meta"]
    assert (meta["requested_weighting"], meta["regime_weighting"]) == ("gmm", "probabilistic") and len(calls) == 2
    assert meta["gmm_fallback"] == "GMM 시작 분포로 혼합하지 못했습니다 — 시험: 국면 하나의 표본이 모자랍니다"


def test_the_pipeline_still_asks_the_gatekeeper(stack, monkeypatch):
    """엔진이 점수 없는 객체를 내도(위조 · 회귀) 파이프라인의 문지기가 거부하고 ★사유와 함께★ 열화한다."""
    forged = RegimeProbabilities(source=SOURCE_GMM_START, step_months=1, probs=dict(PI0),
                                 usage=USAGE_PORTFOLIO, mode="live", detail={})
    monkeypatch.setattr(gs, "gmm_start_path", lambda *a, **k: {
        "available": True, "probs": [forged], "P": _rows_matrix(), "pi0": dict(PI0), "label": "Goldilocks",
        "skill": {"available": True}, "stability": None, "robustness": None})
    g, _ = stack("gmm")
    meta = g["meta"]
    assert meta["regime_weighting"] == "probabilistic" and "워크포워드 점수" in meta["gmm_fallback"]


def _rows_matrix():
    from src.engine.regime_probability import _normalized_transition
    return _normalized_transition(_rows(), REGIMES).tolist()


def test_backtest_mode_stays_closed_for_gmm_too(stack, monkeypatch):
    from src.api import allocation_pipeline as ap

    path = _golden_path()
    monkeypatch.setattr("src.data.regime_snapshots.get_snapshot", lambda sid: {"regime_path": [dict(p) for p in path]})
    req = SimpleNamespace(mes_id="rgs_m3", regime_snapshot_id=None, regime_weighting="gmm",
                          regime_mode="backtest", rebalance="M", model="bl")
    out = ap._conditional_stack(req, _golden_returns(path))
    assert out["cond"]["available"] is False and out["meta"]["requested_weighting"] == "gmm"
    assert out["meta"]["regime_weighting"] == "hard", "쓴 방식은 없다 — 막힌 기본값 그대로"


# ══ 4. 문 — `POST /api/v1/allocation/analyze` 의 `regime_weighting` ════════════════════

@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from src.app_factory import create_app
    return TestClient(create_app())


@pytest.fixture
def wired_route(monkeypatch, _fresh_cache):
    monkeypatch.setattr(rs, "default_arms", _fake_arms())
    path = _golden_path()
    monkeypatch.setattr("src.data.regime_snapshots.get_snapshot",
                        lambda sid: {"as_of": "2025-10-31", "regime_path": [dict(p) for p in path]})
    df = _golden_returns(path)
    cov = {"start": str(df.index.min().date()), "end": str(df.index.max().date()),
           "n_obs": len(df), "as_of": None, "source": "test"}
    monkeypatch.setattr("src.api.allocation_routes._load_clean_returns", lambda *a, **k: (df, None, [], cov))
    return list(df.columns)


def _analyze(client, tickers, weighting):
    return client.post("/api/v1/allocation/analyze", json={
        "tickers": tickers, "lookback_days": 500, "mc_paths": 100, "record_run": False,
        "conditional": True, "model": "bl", "mes_id": "rgs_m3", "regime_weighting": weighting})


def test_the_route_takes_gmm_and_the_decision_moves(client, wired_route):
    r = _analyze(client, wired_route, "gmm")
    assert r.status_code == 200, r.text
    cond = r.json()["conditional"]
    assert (cond["regime_weighting"], cond["requested_weighting"], cond["gmm_fallback"]) == ("gmm", "gmm", None)
    assert cond["probability_source"]["source"] == SOURCE_GMM_START and cond["probability_source"]["skill"]["available"]
    # ② 전달 — π 가 바뀌면 bl 의 최적 비중도 바뀐다(응답만 바뀌고 비중이 그대로면 아무것도 전달하지 않은 것)
    gmm_w = r.json()["weights"]["optimized"]
    prob_w = _analyze(client, wired_route, "probabilistic").json()["weights"]["optimized"]
    assert sum(abs(gmm_w[t] - prob_w.get(t, 0.0)) for t in gmm_w) > 1e-6, (gmm_w, prob_w)


@pytest.mark.parametrize("bad", ["foo", "GMM", "gmm_start", ""])
def test_the_route_still_rejects_unknown_weightings(client, wired_route, bad):
    assert _analyze(client, wired_route, bad).status_code == 422


# ══ 5. 백테스트 팔 G — `allocation_backtest` (달마다 그 달까지 자른 경로) ═════════════

from src.engine.allocation_backtest import walk_forward  # noqa: E402
from tests.test_regime_weighting_golden import arm_panel  # noqa: E402


@pytest.fixture
def g_walk(monkeypatch, _fresh_cache):
    """84개월 패널 · 가짜 군집 팔(받은 자료 길이를 적는다) → 팔 G 의 워크포워드."""
    calls: list[int] = []
    monkeypatch.setattr(rs, "default_arms", _fake_arms(calls))

    def run(points=None, *, rebalance="M", **regime):
        path, df = arm_panel()
        pts = [dict(p) for p in (points if points is not None else path)]
        out = walk_forward(list(df.columns), df.to_numpy(), list(df.index), model="bl", rebalance=rebalance,
                           cost_bps=10.0, regime={"points": pts, "weighting": "gmm", **regime})
        assert not out.get("error"), out.get("message")
        return out
    run.calls = calls
    return run


def test_the_g_arm_rebuilds_the_gmm_start_every_month_and_falls_back_month_by_month(g_walk):
    aud = g_walk()["regime_audit"]
    assert aud["arm"] == "G"
    rows = aud["detail"]
    used = [d for d in rows if d["prob_source"] == SOURCE_GMM_START]
    fell = [d for d in rows if d["gmm_fallback"]]
    assert used and fell, "뒤쪽 달은 GMM · 앞쪽 달은 열화 — 둘 다 있어야 공허하지 않다"
    assert all(d["applied"] and d["prob_usage"] == USAGE_PORTFOLIO for d in used)
    # 점수가 서는 첫 달 = 경로 36(준비) + 20(평가 시점) 개월 · 그 전은 모두 열화(사유가 그 달의 것)
    assert min(d["path_len"] for d in used) == 56 and all(d["path_len"] < 56 for d in fell)
    assert {d["prob_source"] for d in fell} == {SOURCE_FORECAST_MEAN}, "그 달만 전이 예측 — 쓴 출처를 그대로 적는다"
    short = [d for d in fell if d["path_len"] < 36]
    thin = [d for d in fell if d["path_len"] >= 36]
    assert short and all("36개월에 못 미칩니다" in d["gmm_fallback"] for d in short)
    assert thin and all("워크포워드 점수가 없습니다" in d["gmm_fallback"] for d in thin)
    # ★점수도 그 달까지의 경로로★ — 평가 시점 = 경로 − 36(1개월 앞) · 전체 경로로 채점하면 상수가 된다
    assert [d["gmm"]["skill"]["n_eval"] for d in used] == [d["path_len"] - 36 for d in used]
    assert all(d["gmm"]["pi0"][d["gmm"]["label"]] == 0.7 for d in used)
    assert (aud["gmm_months"], aud["gmm_fallback_months"]) == (len(used), len(fell))


def test_the_g_arm_never_fits_on_the_future(g_walk):
    """★앞보기 0★ 경로 뒤에 미래 달을 덧붙여도 비중이 같고, 군집 팔이 받은 자료는 전체 경로(84개월)를 넘지 않는다."""
    path, _ = arm_panel()
    base = g_walk()
    future = path + [{"t": "2099-01", "growth": 9.0, "inflation": -9.0, "regime": "Goldilocks"},
                     {"t": "2099-02", "growth": -9.0, "inflation": 9.0, "regime": "Stagflation"}]
    with_future = g_walk(future)
    assert [r["weights"] for r in base["rebalances"]] == [r["weights"] for r in with_future["rebalances"]]
    assert max(g_walk.calls) <= len(path), "미래 달까지 넣어 적합했다"
    for d in with_future["regime_audit"]["detail"]:
        assert d["last_path_month"] <= d["month"]


def test_the_g_arm_differs_from_the_transition_arm_where_it_is_used(g_walk):
    from src.engine.allocation_backtest import walk_forward as wf

    g = g_walk()
    path, df = arm_panel()
    n = wf(list(df.columns), df.to_numpy(), list(df.index), model="bl", rebalance="M", cost_bps=10.0,
           regime={"points": [dict(p) for p in path], "weighting": "probabilistic"})
    used = {d["month"] for d in g["regime_audit"]["detail"] if d["prob_source"] == SOURCE_GMM_START}
    gw = {r["date"][:7]: r["weights"] for r in g["rebalances"]}
    nw = {r["date"][:7]: r["weights"] for r in n["rebalances"]}
    assert any(gw[m] != nw[m] for m in used), "GMM 을 쓴 달의 비중이 전이 예측과 모두 같다"
    fell = {d["month"] for d in g["regime_audit"]["detail"] if d["gmm_fallback"]}
    first_used = min(used)
    assert all(gw[m] == nw[m] for m in fell if m < first_used), "열화한 앞쪽 달은 전이 예측과 같은 계산"


def test_the_g_arm_does_not_bootstrap_every_month(g_walk, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("백테스트의 달마다 다시 뽑기를 돌렸다")
    monkeypatch.setattr(gs, "bootstrap_agreement", boom)
    aud = g_walk()["regime_audit"]
    assert aud["gmm_months"] > 0


def test_the_g_arm_scores_the_holding_period(g_walk):
    """분기 리밸런싱(보유 3개월) — 점수는 3개월 앞 · 서는 첫 달은 경로 36 + 20 + 2 = 58개월."""
    aud = g_walk(rebalance="Q", h_hold=3)["regime_audit"]
    used = [d for d in aud["detail"] if d["prob_source"] == SOURCE_GMM_START]
    assert used and all(d["gmm"]["skill"]["k"] == 3 and d["h_hold"] == 3 for d in used)
    assert min(d["path_len"] for d in used) >= 58
    assert all(d["path_len"] < 58 for d in aud["detail"] if d["gmm_fallback"])


# ══ 6. 캔버스 — 추정 설정의 선택지 · 방식별 해설 · 최적화 노드의 국면 가중 블록 ═════════════

from src.api import allocation_graph_explain as gx  # noqa: E402
from src.api import allocation_graph_nodes as gn  # noqa: E402
from src.engine import portfolio_graph as pg  # noqa: E402
from tests.test_allocation_graph import chain  # noqa: E402
from tests.test_allocation_routes import T3, _fake_returns_df, _patch_caps, _patch_returns  # noqa: E402

NAMES = {"hard": "오늘 국면 유지", "probabilistic": "전이 예측", "gmm": "GMM 시작 분포 × 전이"}


@pytest.fixture
def canvas_market(monkeypatch):
    _patch_returns(monkeypatch, _fake_returns_df(T3, n=1100))
    _patch_caps(monkeypatch)


def _canvas(weighting: str | None, **est):
    estimate = {"conditional": True, "regime_weighting": weighting, **est} if weighting else {}
    out = pg.run(chain(model="bl", estimate=estimate), gn.REGISTRY)
    assert out["nodes"]["o"]["status"] == "ok", out["nodes"]["o"]["reason"]
    return out


def test_the_estimate_options_are_the_names_of_the_skill_table():
    """선택지 이름 = 국면 예측 비교(M2)의 후보 이름 — 한 곳(`regime_skill.CANDIDATE_NAMES`)에서 온다.
    M4 — 맨 앞에 기본값 '근거 관문'(고르는 규칙의 이름 · `regime_gmm_start.GATE_NAME`)이 더해졌다(의도한 변화)."""
    opts = gn.EstimateParams.model_json_schema()["properties"]["regime_weighting"]["x-ui"]["options"]
    assert opts == {"evidence": gs.GATE_NAME, **NAMES}
    assert opts == {"evidence": gs.GATE_NAME, "hard": rs.CANDIDATE_NAMES["persistence"],
                    "probabilistic": rs.CANDIDATE_NAMES["transition"], "gmm": rs.CANDIDATE_NAMES["gmm_start"]} == gx.WEIGHTING_PLAIN
    pattern = gn.EstimateParams.model_json_schema()["properties"]["regime_weighting"]["pattern"]
    assert pattern == "^(evidence|hard|probabilistic|gmm)$", "선택지와 받는 값이 같다"


@pytest.mark.parametrize("w", ["hard", "probabilistic", "gmm"])
def test_the_estimate_explain_states_the_assumption_of_the_chosen_method(w):
    """★해설이 고른 방식의 가정을 말한다★ — 전에는 무엇을 골라도 '현재 국면이 지속된다고 가정합니다'였다."""
    ex = gx.explain_estimate({"settings": {"conditional": True, "regime_weighting": w}}, {}, None)
    said = " ".join(t["text"] for t in ex["trust"])
    assert f"국면 가중 방식: {NAMES[w]}" in ex["facts"]
    if w == "hard":
        assert "현재 국면이 보유 기간 내내 지속된다고 가정합니다" in said
    else:
        assert "지속된다고 가정" not in said, said
        assert NAMES[w] in said
    if w == "gmm":
        assert "워크포워드 점수" in said and "전이 예측으로 계산" in said


def test_the_estimate_result_shows_method_names_not_codes(canvas_market):
    v = _canvas("gmm")["nodes"]["e"]["view"]
    assert v["value_labels"] == {"regime_weighting": "GMM 시작 분포 × 전이", "regime_mode": "오늘 기준", "rebalance": "한 달"}


def _fallback_lines(explain: dict) -> list[dict]:
    return [t for t in explain["trust"] if t.get("kind") == "fallback"]


def test_dev_data_gmm_falls_back_on_the_canvas_and_says_why(canvas_market):
    """개발 자료(53개월 · 점수 없음) — 최적화 노드가 요청 · 쓴 방식 · 사유를 싣고 해설의 대체 줄이 말한다."""
    o = _canvas("gmm")["nodes"]["o"]
    reg = o["view"]["belief"]["regime"]
    assert (reg["available"], reg["requested"], reg["used"]) == (True, "gmm", "probabilistic")
    assert (reg["requested_name"], reg["used_name"]) == (NAMES["gmm"], NAMES["probabilistic"])
    assert len(reg["fallbacks"]) == 1 and "워크포워드 점수가 없습니다" in reg["fallbacks"][0]
    assert reg["source"] == SOURCE_FORECAST_MEAN and reg["skill"] is None and reg["pi_bar"]
    lines = _fallback_lines(o["explain"])
    assert len(lines) == 1 and lines[0]["state"] == "assumed"
    assert lines[0]["text"].startswith("‘GMM 시작 분포 × 전이’를 쓰지 못해 ‘전이 예측’으로 산출했습니다.")
    assert "워크포워드 점수가 없습니다" in lines[0]["text"]
    assert [t["text"] for t in lines] == reg["fallbacks"], "결과 판의 사유 줄 = 해설의 대체 줄(한 문장 · 두 자리)"
    assert "국면 가중 방식: 전이 예측(요청: GMM 시작 분포 × 전이)" in o["explain"]["facts"]
    assert any("경제적 가치" in u for u in o["explain"]["unmeasured"])
    # 이 표본(756거래일)에는 스태그플레이션 달이 없다 — 혼합이 그 국면을 빼고 재정규화한 사실도 같은 글로 말한다
    assert list(reg["dropped_regimes"]) == ["Stagflation"] and "Stagflation" not in reg["pi_bar"]
    assert [t["text"] for t in o["explain"]["trust"] if "재정규화" in t["text"]] == reg["dropped_notes"]


def test_a_failed_transition_forecast_falls_to_hard_and_each_hop_is_said(canvas_market, monkeypatch):
    """전이 예측도 못 하면 오늘 국면 유지로 — 열화 한 걸음마다 ★그 걸음의 두 방식★을 적는다.
    GMM 요청(개발 자료 · 점수 없음)이면 두 걸음: GMM → 전이 예측(넘어감) → 오늘 국면 유지(산출). 전에는 두 줄 모두
    'GMM … 을 쓰지 못해 오늘 국면 유지로' 라고 적어 가운데 걸음이 사라졌다."""
    def boom(*a, **k):
        raise ValueError("시험: 예측 불가")
    monkeypatch.setattr("src.engine.regime_probability.from_k_step_forecast", boom)
    o = _canvas("probabilistic")["nodes"]["o"]
    reg = o["view"]["belief"]["regime"]
    assert (reg["requested"], reg["used"], reg["source"], reg["pi_bar"]) == ("probabilistic", "hard", None, None)
    assert reg["fallbacks"] == ["‘전이 예측’을 쓰지 못해 ‘오늘 국면 유지’로 산출했습니다. "
                                "국면 예측을 만들지 못해 하드 라벨로 계산했습니다 (ValueError: 시험: 예측 불가)."]
    assert [t["text"] for t in _fallback_lines(o["explain"])] == reg["fallbacks"]
    assert "국면 가중 방식: 오늘 국면 유지(요청: 전이 예측)" in o["explain"]["facts"]
    said = " ".join(t["text"] for t in o["explain"]["trust"])
    assert "오늘 국면이 보유 기간 내내 지속된다고 가정했습니다" in said and "전이행렬 파라미터" not in said

    o = _canvas("gmm")["nodes"]["o"]
    reg = o["view"]["belief"]["regime"]
    assert (reg["requested"], reg["used"]) == ("gmm", "hard") and len(reg["fallbacks"]) == 2
    hop1, hop2 = reg["fallbacks"]
    assert hop1.startswith("‘GMM 시작 분포 × 전이’를 쓰지 못해 ‘전이 예측’으로 넘어갔습니다. 같은 경로의 워크포워드 점수가 없습니다")
    assert hop2.startswith("‘전이 예측’을 쓰지 못해 ‘오늘 국면 유지’로 산출했습니다. 국면 예측을 만들지 못해")
    assert [t["text"] for t in _fallback_lines(o["explain"])] == [hop1, hop2]
    assert "국면 가중 방식: 오늘 국면 유지(요청: GMM 시작 분포 × 전이)" in o["explain"]["facts"]


def test_a_blocked_conditional_states_only_the_block(canvas_market):
    """확인된 국면 판정만 쓰기 — 판정이 미검증이면 관문이 막는다: 블록은 '계산은 했으나 쓰지 않았다'(applied 거짓)이고
    해설은 차단 줄 하나만(쓰지 않은 방식을 '국면 가중 방식' 사실로 적지 않는다 · 대체 줄 · 가정 줄도 없다)."""
    o = _canvas("gmm", require_verified_macro=True)["nodes"]["o"]
    belief = o["view"]["belief"]
    reg = belief["regime"]
    assert belief["blocked"] is True and belief["blocked_reason"], "전제 — 시험 자료의 판정은 미검증이라 막힌다"
    assert (reg["available"], reg["applied"], reg["used"]) == (True, False, "probabilistic")
    ex = o["explain"]
    assert not any(f.startswith("국면 가중 방식:") for f in ex["facts"])
    assert not _fallback_lines(ex) and "unmeasured" not in ex
    said = [t["text"] for t in ex["trust"]]
    assert [t for t in said if t.startswith("경기 국면 반영이 차단돼")] and not [t for t in said if "지속된다고 가정" in t
                                                                              or "전이행렬 파라미터" in t]
    # 짝 — 같은 요청에서 관문을 켜지 않으면 사실 줄과 대체 줄이 있다
    o = _canvas("gmm")["nodes"]["o"]
    assert o["view"]["belief"]["regime"]["applied"] is True and _fallback_lines(o["explain"])
    assert any(f.startswith("국면 가중 방식:") for f in o["explain"]["facts"])


def test_a_bootstrap_that_could_not_run_is_said_as_unmeasured(canvas_market, monkeypatch, _fresh_cache):
    """GMM 을 썼으나 다시 뽑기가 모두 실패 — 사실 줄이 아니라 '재지 못했다'(미상) 줄 + 사유. 결과 판도 그 사유를 그대로."""
    monkeypatch.setattr(rs, "default_arms", _fake_arms())
    monkeypatch.setattr(gs, "bootstrap_agreement", lambda g, i, label: gs._no(
        "다시 뽑기 20회가 모두 실패했습니다.", method=gs.BOOT_METHOD, failed=20))
    path = _golden_path(60, (2021, 8))
    monkeypatch.setattr("src.api.allocation_pipeline._regime_path_for", lambda req: {
        "points": [dict(p) for p in path], "path_source": "regime_snapshot", "path_note": None, "reason": None})
    o = _canvas("gmm")["nodes"]["o"]
    reg = o["view"]["belief"]["regime"]
    assert reg["used"] == "gmm" and reg["robustness"]["available"] is False
    ex = o["explain"]
    assert not any("달을 다시 뽑아 적합한" in f for f in ex["facts"])
    unknown = [t for t in ex["trust"] if t["state"] == "unknown" and "다시 뽑아 본 안정성" in t["text"]]
    assert [t["text"] for t in unknown] == ["자료를 다시 뽑아 본 안정성은 재지 못했습니다. 다시 뽑기 20회가 모두 실패했습니다."]


def test_a_transition_request_has_no_fallback_line(canvas_market):
    """짝 — 요청한 방식을 그대로 쓰면 대체 줄이 없다(항상 대체 줄을 다는 구현을 배제)."""
    o = _canvas("probabilistic")["nodes"]["o"]
    reg = o["view"]["belief"]["regime"]
    assert (reg["requested"], reg["used"], reg["fallbacks"]) == ("probabilistic", "probabilistic", [])
    assert not _fallback_lines(o["explain"])
    assert "국면 가중 방식: 전이 예측" in o["explain"]["facts"]
    said = " ".join(t["text"] for t in o["explain"]["trust"])
    assert "전이행렬 파라미터의 불확실성" in said


def test_a_hard_request_states_the_persistence_assumption(canvas_market):
    o = _canvas("hard")["nodes"]["o"]
    reg = o["view"]["belief"]["regime"]
    assert (reg["used"], reg["source"], reg["fallbacks"]) == ("hard", None, [])
    said = " ".join(t["text"] for t in o["explain"]["trust"])
    assert "오늘 국면이 보유 기간 내내 지속된다고 가정했습니다" in said


def test_without_conditional_there_is_no_regime_block(canvas_market):
    """★묻지 않은 실행의 출력은 M3 전과 같다★ — 키를 `None` 으로 두는 것도 모양이 바뀐 것이다(CF3 골든 `tests/golden/cf3_weights.json` 이 잡는다)."""
    o = _canvas(None)["nodes"]["o"]
    assert set(o["view"]["belief"]) == {"conditional", "blocked", "blocked_reason"}
    assert not any("국면 가중" in f for f in o["explain"]["facts"])
    assert not any("경제적 가치" in u for u in o["explain"].get("unmeasured") or [])


def test_an_unavailable_conditional_is_said_on_the_canvas(canvas_market, monkeypatch):
    """조건부를 못 만들면(경로 없음) 캔버스도 말한다 — 전에는 최적화 노드가 아무 말 없이 과거 표본으로 냈다."""
    monkeypatch.setattr("src.api.allocation_pipeline._regime_path_for", lambda req: {
        "points": [], "path_source": None, "path_note": None,
        "reason": "성장·물가 축이 둘 다 산출된 달이 없어 국면 경로가 비었습니다 — 무조건부 추정으로 계산했습니다."})
    o = _canvas("gmm")["nodes"]["o"]
    reg = o["view"]["belief"]["regime"]
    assert reg["available"] is False and reg["used"] is None and "국면 경로가 비었습니다" in reg["reason"]
    said = [t for t in o["explain"]["trust"] if "국면 조건부 추정을 쓰지 못해" in t["text"]]
    assert len(said) == 1 and said[0]["state"] == "assumed" and "국면 경로가 비었습니다" in said[0]["text"]
    assert not any(f.startswith("국면 가중 방식:") for f in o["explain"]["facts"]), "쓰지 않은 방식을 쓴 것처럼 적지 않는다"


def test_a_gmm_success_shows_the_score_the_seed_stability_and_the_bootstrap(canvas_market, monkeypatch, _fresh_cache):
    """가짜 군집 팔 + 수익률 달과 맞춘 60개월 경로 — 점수 · 시드 안정성 · 부트스트랩이 사실 줄로 나온다."""
    monkeypatch.setattr(rs, "default_arms", _fake_arms())
    path = _golden_path(60, (2021, 8))
    monkeypatch.setattr("src.api.allocation_pipeline._regime_path_for", lambda req: {
        "points": [dict(p) for p in path], "path_source": "regime_snapshot", "path_note": None, "reason": None})
    o = _canvas("gmm")["nodes"]["o"]
    reg = o["view"]["belief"]["regime"]
    assert (reg["used"], reg["fallbacks"], reg["source"]) == ("gmm", [], SOURCE_GMM_START)
    assert reg["skill"]["n_eval"] == 24 and reg["robustness"]["method"] == "bootstrap_months"
    assert reg["pi0"][reg["label"]] == 0.7
    facts = o["explain"]["facts"]
    sk = reg["skill"]
    assert (f"같은 경로의 워크포워드 점수(1개월 앞 · 평가 시점 24개) — 적중 {sk['hits']}/24회 · 브라이어 {sk['brier']:.3f} · "
            f"‘오늘 국면 유지’ 대비 {sk['gain']:+.3f}") in " ".join(facts)
    rb = reg["robustness"]
    assert any(f"달을 다시 뽑아 적합한 {rb['resamples']}번 가운데 {rb['agree']}번" in f for f in facts)
    assert any("난수 시드 10개 가운데 9개" in f for f in facts)
    assert not _fallback_lines(o["explain"])
    assert not [t for t in o["explain"]["trust"] if "재지 못했습니다" in t["text"]], "짝 — 잰 다시 뽑기에는 미상 줄이 없다"


# ══ 7. 화면 고정물 — E2E 의 'GMM 을 쓴 최적화 결과' = 지금 서버의 출력 ══════════════════════

import json  # noqa: E402
import os  # noqa: E402
import pathlib  # noqa: E402

M3_FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "frontend" / "e2e" / "fixtures" / "regime-weighting-optimizer.json"


def test_the_screen_fixture_is_what_the_optimizer_produces(canvas_market, monkeypatch, _fresh_cache):
    """★손으로 지은 응답이 아니다★ 가짜 군집 팔 · 가짜 다시 뽑기(기계마다 반올림이 답을 정하지 않게 — M1c) · 수익률 달과 맞춘 경로로
    서버의 최적화 노드를 돌린 출력 중 국면 가중 블록과 해설(비중 머리말은 풀이기 끝자리에 기대므로 뺀다). 다시 짓기: `REGEN_SCREEN_FIXTURES=1`."""
    from tests.test_regime_skill_routes import _close

    monkeypatch.setattr(rs, "default_arms", _fake_arms())
    monkeypatch.setattr(gs, "bootstrap_agreement", _fake_boot())
    path = _golden_path(60, (2021, 8))
    monkeypatch.setattr("src.api.allocation_pipeline._regime_path_for", lambda req: {
        "points": [dict(p) for p in path], "path_source": "regime_snapshot", "path_note": None, "reason": None})
    o = _canvas("gmm")["nodes"]["o"]
    ex = o["explain"]
    got = json.loads(json.dumps({"belief": o["view"]["belief"],
                                 "explain": {k: ex[k] for k in ("title", "facts", "trust", "unmeasured")}},
                                ensure_ascii=False))
    assert got["belief"]["regime"]["used"] == "gmm" and got["belief"]["regime"]["skill"]["available"]
    if os.environ.get("REGEN_SCREEN_FIXTURES") == "1":
        M3_FIXTURE.write_text(json.dumps(got, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    assert M3_FIXTURE.exists(), f"고정물이 없습니다 — REGEN_SCREEN_FIXTURES=1 로 짓습니다: {M3_FIXTURE}"
    _close(got, json.loads(M3_FIXTURE.read_text(encoding="utf-8")))


def test_a_regime_dropped_from_the_mixture_is_said_with_its_reason(canvas_market, monkeypatch):
    """혼합이 추정하지 못한 국면을 빼고 재정규화하면 — 블록과 해설이 그 국면 · 사유 · 뺀 질량을 말한다(전에는 캔버스가 말하지 않았다)."""
    import src.engine.conditional_market as cm

    real = cm.conditional_moments

    def thin(returns_df, by_month, regime, **kw):
        if regime == "Stagflation":
            return cm._unavailable("시험: 표본이 모자랍니다")
        return real(returns_df, by_month, regime, **kw)
    monkeypatch.setattr(cm, "conditional_moments", thin)
    o = _canvas("probabilistic")["nodes"]["o"]
    reg = o["view"]["belief"]["regime"]
    assert reg["used"] == "probabilistic" and reg["dropped_regimes"] == {"Stagflation": "시험: 표본이 모자랍니다"}
    assert "Stagflation" not in reg["pi_bar"], "뺀 국면은 분포에 없다(0 으로 채우지 않는다)"
    assert len(reg["dropped_notes"]) == 1
    note = reg["dropped_notes"][0]
    assert note.startswith("‘스태그플레이션’ 국면은 조건부 적률을 추정하지 못해 혼합에서 빼고 남은 국면으로 재정규화했습니다")
    assert "시험: 표본이 모자랍니다" in note and "뺀 확률 질량 최대" in note
    assert [t for t in o["explain"]["trust"] if t["text"] == note and t["state"] == "assumed"], "해설에도 같은 문장"


def test_nothing_dropped_means_no_dropped_line(canvas_market, monkeypatch):
    """짝 — 모든 국면을 추정했으면(수익률 달과 맞춘 60개월 경로) 뺀 국면 문장이 없다.
    (위 고정물 없이 기본 캔버스 표본은 756거래일 창에 스태그플레이션 달이 없어 실제로 뺀다 — 그것이 위 시험의 실제 경우다.)"""
    path = _golden_path(60, (2021, 8))
    monkeypatch.setattr("src.api.allocation_pipeline._regime_path_for", lambda req: {
        "points": [dict(p) for p in path], "path_source": "regime_snapshot", "path_note": None, "reason": None})
    o = _canvas("probabilistic")["nodes"]["o"]
    reg = o["view"]["belief"]["regime"]
    assert (reg["dropped_regimes"], reg["dropped_notes"]) == ({}, [])
    assert not [t for t in o["explain"]["trust"] if "재정규화" in t["text"]]
