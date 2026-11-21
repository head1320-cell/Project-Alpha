"""M1 — 군집 팔의 시드 안정성 + k-평균 넷째 팔 (2026-11-16 · 설계 D5 "시드 평균").
==============================================================================
설계 `docs/superpowers/specs/2026-11-16-emeans-gmm-strategy-design.md` §M1 · 계획 §1.

## 답하는 물음 — ② 같은 자료에서 같은 답이 나오는가 (어느 팔이 맞는지는 말하지 않는다)

재 본 것(설계 §2): mock 축 kr 60개월에서 GMM 은 난수 시드 0 이 Goldilocks, 30개 가운데 24개는 Reflation 이었다.
★시드 0 하나의 답은 우연이다★ — 그래서 팔의 답을 시드 평균으로 바꾸고, 시드마다의 답이 얼마나 모이는지를
`stability` 로 함께 낸다.

## 거는 것
1. ★손 계산★ — 가짜 추정기로 시드마다 다른 답을 넣고 평균 · 세기 · 과반을 손으로 맞춘다(시드 0 의 답과 평균의 답이
   다른 경우를 일부러 넣는다).
2. ★과반은 엄격하다★ — 5:5 는 과반이 아니다(`≥` 로 바꾸는 변이를 죽인다) · 동수의 최다 답은 `REGIMES` 순서의 앞.
3. k-평균 팔의 값은 ★확률이 아니라 시드 비율★이다 — `probs_kind` 와 주석이 그렇게 말한다(짝: GMM 팔은 확률).
4. 실제 추정기: 뚜렷이 뭉친 자료에서는 안정 ↔ 답을 흔들기가 정하는 자료(원 위의 점 + 가운데 점을 1e-12 만큼 흔든
   30개)에서는 시드가 갈린다 · ★시드 과반 ≠ 자료에 대한 강건성★ — 판정('과반' / '과반 미만')이 흔들기만으로 오간다
   (M1c · 한계를 건다 — 해설의 '재지 않은 것'이 그 한계를 말한다).
5. 합의는 넷을 센다 · 군집 두 방법이 독립이 아니라는 사실을 말한다(짝: 하나가 빠지면 말하지 않는다).
6. 캔버스 해설이 넷째 팔과 안정성을 말한다.
"""
from __future__ import annotations

import functools
import math
import sys

import numpy as np
import pytest

import src.engine.regime_ensemble as re_mod
from src.engine.regime_ensemble import MIN_OBS, REGIMES, SEEDS

# 성분 중심 — 네 사분면에 하나씩. 지수 0 Goldilocks · 1 Reflation · 2 Stagflation · 3 Disinflation.
# 대역은 시드 s 의 중심을 (1 + s) 배로 늘린다 — 사분면은 같고 값만 달라 "어느 시드의 중심인가" 가 드러난다.
_CENTERS = [(1.0, -1.0), (1.0, 1.0), (-1.0, 1.0), (-1.0, -1.0)]


def _scaled(k: int, seed: int) -> np.ndarray:
    return np.array(_CENTERS[:k], dtype=float) * (1 + seed)
_N = 48            # 성분 수 규칙 min(4, max(2, n // 12)) 이 4 가 되는 표본


def _flat(n: int = _N) -> tuple[list[float], list[float]]:
    """가짜 추정기용 축 — 값은 보지 않는다(결측만 없으면 된다)."""
    return [0.1 * i for i in range(n)], [0.05 * i for i in range(n)]


def _fake_gmm(plan: dict[int, list[float]], *, unconverged: frozenset[int] = frozenset()):
    """시드(`random_state`)마다 정해 둔 마지막 점의 소속 확률을 내는 대역. 만들어진 인자를 센다."""
    calls: list[dict] = []

    class FakeGMM:
        def __init__(self, **kw):
            calls.append(kw)
            self.kw = kw

        def fit(self, X):
            self.means_ = _scaled(self.kw["n_components"], self.kw["random_state"])
            self.converged_ = self.kw["random_state"] not in unconverged
            return self

        def predict_proba(self, x):
            assert len(x) == 1, "마지막 점 하나만 채점한다"
            return np.array([plan[self.kw["random_state"]][: self.kw["n_components"]]], dtype=float)

    return FakeGMM, calls


def _fake_kmeans(plan: dict[int, int]):
    """시드마다 마지막 점이 속할 중심의 지수를 정해 둔 대역."""
    calls: list[dict] = []

    class FakeKMeans:
        def __init__(self, **kw):
            calls.append(kw)
            self.kw = kw

        def fit(self, X):
            self.cluster_centers_ = _scaled(self.kw["n_clusters"], self.kw["random_state"])
            return self

        def predict(self, x):
            assert len(x) == 1, "마지막 점 하나만 묻는다"
            return np.array([plan[self.kw["random_state"]]])

    return FakeKMeans, calls


def _split(groups: list[tuple[int, object]]) -> dict[int, object]:
    """[(시드 수, 답), …] → {시드: 답} — 앞에서부터 시드 번호를 매긴다."""
    out, s = {}, 0
    for count, answer in groups:
        for _ in range(count):
            out[s] = answer
            s += 1
    assert s == SEEDS, f"계획의 시드 수 {s} ≠ SEEDS {SEEDS}"
    return out


# ══ 0. 설정값 ═════════════════════════════════════════════════════════════════

def test_seeds_is_the_declared_setting():
    """시드 수는 재 본 값이 아니라 설정값이다(설계 §M1) — 바뀌면 손 계산 시험을 함께 고쳐야 한다."""
    assert SEEDS == 10


# ══ 1. GMM 팔 — 시드 평균과 안정성(손 계산) ════════════════════════════════════

def test_gmm_answer_is_the_seed_average_not_seed_zero(monkeypatch):
    """★시드 0 은 Goldilocks 라고 하지만 시드 평균은 Reflation 이다★

    시드 0~2: [0.60, 0.40] · 시드 3~9: [0.45, 0.55] →
    평균 Goldilocks (3×0.60 + 7×0.45)/10 = 0.495 · Reflation (3×0.40 + 7×0.55)/10 = 0.505.
    시드 비율(0.3 · 0.7)과도 다르다 — 확률을 비율로 바꾸는 변이를 여기서 잡는다.
    """
    fake, calls = _fake_gmm(_split([(3, [0.60, 0.40, 0.0, 0.0]), (7, [0.45, 0.55, 0.0, 0.0])]))
    monkeypatch.setattr("sklearn.mixture.GaussianMixture", fake)
    out = re_mod._cluster_probs(*_flat())

    assert out["available"] is True, out.get("reason")
    assert out["method"] == "cluster"
    assert out["probs_kind"] == "probability"
    assert out["probs"] == {"Goldilocks": 0.495, "Reflation": 0.505, "Stagflation": 0.0, "Disinflation": 0.0}
    assert out["argmax"] == "Reflation"
    assert out["stability"] == {
        "seeds": 10, "modal": "Reflation", "agree": 7,
        "shares": {"Goldilocks": 0.3, "Reflation": 0.7, "Stagflation": 0.0, "Disinflation": 0.0},
        "stable": True,
    }
    # 시드는 0 … SEEDS−1 · 설정은 지금 그대로(성분 수 규칙 · full · n_init 3)
    assert [c["random_state"] for c in calls] == list(range(SEEDS))
    assert all(c == {"n_components": 4, "covariance_type": "full", "random_state": c["random_state"], "n_init": 3}
               for c in calls), calls


def test_gmm_detail_names_whose_centers_it_shows_and_whether_every_seed_converged(monkeypatch):
    fake, _ = _fake_gmm(_split([(10, [1.0, 0.0, 0.0, 0.0])]), unconverged=frozenset({3}))
    monkeypatch.setattr("sklearn.mixture.GaussianMixture", fake)
    det = re_mod._cluster_probs(*_flat())["detail"]
    assert det["n_components"] == 4 and det["n_obs"] == _N
    assert "centers" not in det, "어느 시드의 중심인지 이름에 적는다"
    assert det["centers_seed0"] == [
        {"growth": 1.0, "inflation": -1.0, "regime": "Goldilocks"},
        {"growth": 1.0, "inflation": 1.0, "regime": "Reflation"},
        {"growth": -1.0, "inflation": 1.0, "regime": "Stagflation"},
        {"growth": -1.0, "inflation": -1.0, "regime": "Disinflation"},
    ]
    assert det["converged"] is False, "시드 하나라도 수렴하지 않았으면 거짓"


def test_gmm_converged_is_true_only_when_every_seed_converged(monkeypatch):
    """짝 — 모두 수렴하면 참."""
    fake, _ = _fake_gmm(_split([(10, [1.0, 0.0, 0.0, 0.0])]))
    monkeypatch.setattr("sklearn.mixture.GaussianMixture", fake)
    assert re_mod._cluster_probs(*_flat())["detail"]["converged"] is True


@pytest.mark.parametrize(("groups", "modal", "agree", "argmax"), [
    # 4 · 4 · 2 — 최다 답이 둘이면 REGIMES 순서의 앞(Goldilocks) · 과반 아님
    ([(4, [1.0, 0.0, 0.0, 0.0]), (4, [0.0, 1.0, 0.0, 0.0]), (2, [0.0, 0.0, 1.0, 0.0])], "Goldilocks", 4, "Goldilocks"),
    # 5 · 5 — ★반은 과반이 아니다★
    ([(5, [0.0, 1.0, 0.0, 0.0]), (5, [0.0, 0.0, 0.0, 1.0])], "Reflation", 5, "Reflation"),
])
def test_gmm_without_a_strict_majority_is_not_stable(monkeypatch, groups, modal, agree, argmax):
    fake, _ = _fake_gmm(_split(groups))
    monkeypatch.setattr("sklearn.mixture.GaussianMixture", fake)
    out = re_mod._cluster_probs(*_flat())
    st = out["stability"]
    assert (st["modal"], st["agree"], st["stable"]) == (modal, agree, False)
    assert out["argmax"] == argmax
    assert abs(sum(st["shares"].values()) - 1.0) < 1e-9


def test_gmm_answer_follows_the_average_even_when_most_seeds_say_otherwise(monkeypatch):
    """★팔의 답은 평균의 최댓값이고, 시드별 최다 답과 다를 수 있다★ (변이 A09 가 살아남은 자리)

    시드 0~5: [0.51, 0.49] (근소하게 Goldilocks) · 시드 6~9: [0.10, 0.90] (뚜렷이 Reflation) →
    평균 Goldilocks (6×0.51 + 4×0.10)/10 = 0.346 · Reflation (6×0.49 + 4×0.90)/10 = 0.654 → 답 Reflation.
    시드별 최다 답은 Goldilocks 6개(과반) — `stability` 는 그것을 그대로 적는다(답에 맞춰 고치지 않는다).
    """
    fake, _ = _fake_gmm(_split([(6, [0.51, 0.49, 0.0, 0.0]), (4, [0.10, 0.90, 0.0, 0.0])]))
    monkeypatch.setattr("sklearn.mixture.GaussianMixture", fake)
    out = re_mod._cluster_probs(*_flat())
    assert out["probs"]["Goldilocks"] == 0.346 and out["probs"]["Reflation"] == 0.654
    assert out["argmax"] == "Reflation"
    st = out["stability"]
    assert (st["modal"], st["agree"], st["stable"]) == ("Goldilocks", 6, True)


def test_gmm_with_six_of_ten_is_stable(monkeypatch):
    """짝 — 6:4 는 과반이다."""
    fake, _ = _fake_gmm(_split([(6, [0.0, 0.0, 1.0, 0.0]), (4, [0.0, 0.0, 0.0, 1.0])]))
    monkeypatch.setattr("sklearn.mixture.GaussianMixture", fake)
    st = re_mod._cluster_probs(*_flat())["stability"]
    assert (st["modal"], st["agree"], st["stable"]) == ("Stagflation", 6, True)


# ══ 2. k-평균 팔 — 확률이 아니라 시드 비율 ═════════════════════════════════════

def test_kmeans_reports_seed_shares_not_probabilities(monkeypatch):
    fake, calls = _fake_kmeans(_split([(3, 0), (7, 1)]))
    monkeypatch.setattr("sklearn.cluster.KMeans", fake)
    out = re_mod._kmeans_probs(*_flat())

    assert out["available"] is True, out.get("reason")
    assert out["method"] == "kmeans"
    assert out["probs_kind"] == "seed_share"
    assert out["probs"] == {"Goldilocks": 0.3, "Reflation": 0.7, "Stagflation": 0.0, "Disinflation": 0.0}
    assert out["argmax"] == "Reflation"
    assert out["stability"] == {
        "seeds": 10, "modal": "Reflation", "agree": 7,
        "shares": {"Goldilocks": 0.3, "Reflation": 0.7, "Stagflation": 0.0, "Disinflation": 0.0},
        "stable": True,
    }
    assert "확률이 아닙니다" in out["note"], out["note"]
    assert [c["random_state"] for c in calls] == list(range(SEEDS))
    assert all(c == {"n_clusters": 4, "n_init": 10, "random_state": c["random_state"]} for c in calls), calls
    assert out["detail"]["n_clusters"] == 4 and out["detail"]["n_obs"] == _N
    assert out["detail"]["centers_seed0"][1] == {"growth": 1.0, "inflation": 1.0, "regime": "Reflation"}


def test_the_gmm_arm_does_not_call_its_numbers_shares(monkeypatch):
    """짝 — GMM 팔의 주석은 확률을 말하고 '확률이 아니다' 라고 하지 않는다."""
    fake, _ = _fake_gmm(_split([(10, [1.0, 0.0, 0.0, 0.0])]))
    monkeypatch.setattr("sklearn.mixture.GaussianMixture", fake)
    note = re_mod._cluster_probs(*_flat())["note"]
    assert "확률이 아닙니다" not in note and "소속확률" in note and f"{SEEDS}개" in note


def test_kmeans_half_and_half_is_not_stable(monkeypatch):
    fake, _ = _fake_kmeans(_split([(5, 3), (5, 2)]))
    monkeypatch.setattr("sklearn.cluster.KMeans", fake)
    out = re_mod._kmeans_probs(*_flat())
    # 동수 — REGIMES 순서로 Stagflation(2) 이 Disinflation(3) 보다 앞이다
    assert out["argmax"] == "Stagflation"
    assert (out["stability"]["modal"], out["stability"]["agree"], out["stability"]["stable"]) == ("Stagflation", 5, False)


@pytest.mark.parametrize("months", [6, MIN_OBS - 1])
def test_kmeans_short_sample_is_unavailable_with_a_reason(months):
    g, i = _flat(months)
    out = re_mod._kmeans_probs(g, i)
    assert out["available"] is False and "probs" not in out
    assert f"{months}개월" in out["reason"] and str(MIN_OBS) in out["reason"]


def test_kmeans_without_scikit_learn_says_so(monkeypatch):
    monkeypatch.setitem(sys.modules, "sklearn.cluster", None)
    out = re_mod._kmeans_probs(*_flat())
    assert out == {"available": False, "reason": "scikit-learn 미설치 — k-평균 군집을 돌릴 수 없습니다"}


def test_gmm_without_scikit_learn_says_so(monkeypatch):
    """짝 — GMM 팔의 같은 사유는 그대로다."""
    monkeypatch.setitem(sys.modules, "sklearn.mixture", None)
    out = re_mod._cluster_probs(*_flat())
    assert out == {"available": False, "reason": "scikit-learn 미설치 — 군집 모형을 돌릴 수 없습니다"}


def test_kmeans_with_missing_axis_values_is_unavailable():
    g, i = _flat()
    g[5] = math.nan
    out = re_mod._kmeans_probs(g, i)
    assert out == {"available": False, "reason": "축 시계열에 결측이 있어 군집화할 수 없습니다"}


def test_a_failing_kmeans_fit_is_unavailable_with_its_type(monkeypatch):
    class Boom:
        def __init__(self, **kw):
            pass

        def fit(self, X):
            raise ValueError("boom")

    monkeypatch.setattr("sklearn.cluster.KMeans", Boom)
    out = re_mod._kmeans_probs(*_flat())
    assert out == {"available": False, "reason": "k-평균 군집 적합 실패 (ValueError)"}


# ══ 3. 실제 추정기 — 뭉친 자료는 안정 ↔ 원 위의 가운데 점은 갈린다 ═══════════════

def _blobs() -> tuple[list[float], list[float]]:
    rng = np.random.default_rng(0)
    X = np.vstack([rng.normal(m, 0.3, size=(15, 2)) for m in [(2, -2), (2, 2), (-2, 2), (-2, -2)]]
                  + [np.array([[2.1, 1.9]])])      # 마지막 점은 Reflation 덩어리 안
    return X[:, 0].tolist(), X[:, 1].tolist()


def _ring(n: int = 96) -> tuple[list[float], list[float]]:
    """원 위에 고르게 놓인 점 + 마지막 점은 원의 가운데 — 어느 성분에 속할지 시드가 정한다."""
    ang = np.linspace(0.0, 2.0 * math.pi, n - 1, endpoint=False)
    X = np.vstack([np.column_stack([np.cos(ang), np.sin(ang)]), [[0.0, 0.0]]])
    return X[:, 0].tolist(), X[:, 1].tolist()


@pytest.mark.parametrize("arm", ["_cluster_probs", "_kmeans_probs"])
def test_clearly_clustered_data_gives_every_seed_the_same_answer(arm):
    out = getattr(re_mod, arm)(*_blobs())
    assert out["available"] is True, out.get("reason")
    assert out["argmax"] == "Reflation"
    assert out["stability"]["agree"] == SEEDS and out["stability"]["stable"] is True


#: 원 자료를 흔드는 크기(소수 열두째 자리)와 사본 수. ★흔들지 않은 원은 답을 기계의 반올림이 정한다★ —
#: GMM 의 최다 답이 OpenBLAS 의 AVX512 커널에서 4/10('과반 미만'), Haswell · Zen · Prescott 커널에서 6/10('과반')이다
#: (잰 것 · 2026-11-16 M1 PR 실행의 Backend 실패가 이것 — 그 실행의 값과 소수점까지 같다). 1e-12 는 반올림보다 네 자리쯤
#: 커서 사본마다의 답을 기계가 아니라 흔들기가 정한다(잰 것: 네 커널에서 30개 사본의 답이 두 팔 모두 같다).
RING_JITTER = 1e-12
RING_COPIES = 30


def _jittered_rings() -> list[tuple[list[float], list[float]]]:
    g, i = _ring()
    base = np.column_stack([g, i])
    out = []
    for s in range(RING_COPIES):
        X = base + np.random.default_rng(s).normal(0.0, RING_JITTER, base.shape)
        out.append((X[:, 0].tolist(), X[:, 1].tolist()))
    return out


@functools.cache
def _ring_stability(arm: str) -> tuple[dict, ...]:
    """흔든 원 30개에 그 팔을 돌린 시드 안정성 — 아래 두 시험이 같은 계산을 나눠 쓴다(GMM 약 5초)."""
    outs = [getattr(re_mod, arm)(g, i) for g, i in _jittered_rings()]
    assert all(o["available"] for o in outs), [o.get("reason") for o in outs if not o["available"]]
    return tuple(o["stability"] for o in outs)


@pytest.mark.parametrize("arm", ["_cluster_probs", "_kmeans_probs"])
def test_seed_sensitive_data_splits_the_seeds(arm):
    """★시드 하나만 돌렸다면 그 답을 단정했을 것이다★ — 같은 자료 · 같은 설정에서 시드마다 답이 갈린다.

    한 자료의 수('10개 중 5개 이하')를 걸지 않는다 — 그 수는 기계마다 다르다(위 `RING_JITTER` 주석).
    흔든 원 30개 전체에서 기계와 무관하게 성립하는 것만 건다.
    """
    sts = _ring_stability(arm)
    # ① 과반 미만이라고 말하는 사본이 있다 — 시드를 하나로 묶으면(변이) 30개 모두 10/10 '과반'이다
    assert any(st["stable"] is False for st in sts)
    # ② 갈린다는 것이 공허하지 않다 — 시드마다의 답이 네 국면 모두에 흩어진다
    pooled = {r: sum(st["shares"][r] for st in sts) for r in REGIMES}
    assert all(v > 0 for v in pooled.values()), pooled


@pytest.mark.parametrize("arm", ["_cluster_probs", "_kmeans_probs"])
def test_a_seed_majority_is_not_robustness_to_the_data(arm):
    """★한계를 건다★ 시드 과반은 '난수 시드를 바꿔도 같은 답인가'만 잰다 — '자료가 조금 달라도 같은 답인가'는 재지 않는다.

    답을 흔들기가 정하는 자료에서 판정이 1e-12 의 차이만으로 '과반'과 '과반 미만'을 오간다
    (잰 것: 흔든 원 30개 중 '과반' — GMM 10개 · k-평균 14개 · OpenBLAS 커널 넷에서 같다).
    이 시험이 깨지면 — 판정이 자료 흔들기에도 견고해지면 — 캔버스 해설의 '재지 않은 것'과 엔진 머리말도 함께 고친다.
    """
    assert {st["stable"] for st in _ring_stability(arm)} == {True, False}


# ══ 4. 앙상블 — 넷을 나란히 · 합치지 않는다 ════════════════════════════════════

def _arm(regime: str | None, method: str) -> dict:
    if regime is None:
        return {"available": False, "reason": f"{method} 시험용 미가용"}
    return {"available": True, "method": method, "probs": {r: float(r == regime) for r in REGIMES},
            "argmax": regime, "detail": {}, "note": ""}


def _patch_arms(monkeypatch, axis, markov, cluster, kmeans):
    monkeypatch.setattr(re_mod, "_axis_probs", lambda *a, **k: _arm(axis, "axis"))
    monkeypatch.setattr(re_mod, "_markov_probs", lambda *a, **k: _arm(markov, "markov"))
    monkeypatch.setattr(re_mod, "_cluster_probs", lambda *a, **k: _arm(cluster, "cluster"))
    monkeypatch.setattr(re_mod, "_kmeans_probs", lambda *a, **k: _arm(kmeans, "kmeans"))


def test_the_ensemble_lists_four_arms_and_counts_all_of_them(monkeypatch):
    _patch_arms(monkeypatch, "Goldilocks", "Goldilocks", "Goldilocks", "Reflation")
    r = re_mod.regime_ensemble({}, "kr", months=60)
    assert list(r["tools"]) == ["axis", "markov", "cluster", "kmeans"]
    assert r["agreement"]["picks"] == {"axis": "Goldilocks", "markov": "Goldilocks",
                                       "cluster": "Goldilocks", "kmeans": "Reflation"}
    assert r["agreement"]["unanimous"] is False, "넷째 팔의 다른 답이 만장일치를 깬다"
    assert r["agreement"]["note"] == "방법마다 다른 국면을 가리킵니다 — 전환 초입일 수 있습니다"


def test_unanimity_says_every_method_not_three(monkeypatch):
    _patch_arms(monkeypatch, "Stagflation", "Stagflation", "Stagflation", "Stagflation")
    r = re_mod.regime_ensemble({}, "kr", months=60)
    assert r["agreement"]["unanimous"] is True
    assert r["agreement"]["note"] == "모든 방법이 같은 국면을 가리킵니다"


def _with_stability(regime: str, method: str, agree: int) -> dict:
    a = _arm(regime, method)
    a["stability"] = {"seeds": SEEDS, "modal": regime, "agree": agree,
                      "shares": {r: (agree / SEEDS if r == regime else 0.0) for r in REGIMES},
                      "stable": agree * 2 > SEEDS}
    return a


def _patch_seeded(monkeypatch, regime: str, cluster_agree: int, kmeans_agree: int):
    monkeypatch.setattr(re_mod, "_axis_probs", lambda *a, **k: _arm(regime, "axis"))
    monkeypatch.setattr(re_mod, "_markov_probs", lambda *a, **k: _arm(regime, "markov"))
    monkeypatch.setattr(re_mod, "_cluster_probs", lambda *a, **k: _with_stability(regime, "cluster", cluster_agree))
    monkeypatch.setattr(re_mod, "_kmeans_probs", lambda *a, **k: _with_stability(regime, "kmeans", kmeans_agree))


def test_unanimity_resting_on_a_seed_unstable_arm_is_qualified(monkeypatch):
    """★흔들리는 팔 위의 만장일치는 그렇게 적는다★ (개발 자료 us 60개월: 네 방법 모두 Stagflation · GMM 최다 답 3/10)

    `unanimous` 는 그대로 참이다 — 답이 같다는 사실은 사실이다. 문장이 단서를 단다.
    """
    _patch_seeded(monkeypatch, "Stagflation", cluster_agree=3, kmeans_agree=7)
    ag = re_mod.regime_ensemble({}, "kr", months=60)["agreement"]
    assert ag["unanimous"] is True
    assert ag["note"] == "모든 방법이 같은 국면을 가리킵니다 — 다만 난수 시드에 따라 답이 갈리는 방법이 있습니다"


def test_unanimity_on_stable_arms_has_no_qualifier(monkeypatch):
    """짝 — 시드로 다시 적합한 팔이 모두 과반이면 단서가 없다."""
    _patch_seeded(monkeypatch, "Stagflation", cluster_agree=6, kmeans_agree=10)
    ag = re_mod.regime_ensemble({}, "kr", months=60)["agreement"]
    assert ag["note"] == "모든 방법이 같은 국면을 가리킵니다"


def test_the_tool_names_cover_every_arm():
    """서버 문장의 팔 이름은 엔진의 표 하나 — 캔버스 두 노드가 같은 표를 쓴다."""
    assert set(re_mod.TOOL_NAMES) == {"axis", "markov", "cluster", "kmeans"}
    _canvas()
    from src.api import allocation_graph_nodes_bl2 as bl2
    from src.api import allocation_graph_nodes_macro_w2 as w2
    assert bl2.ENSEMBLE_TOOL_NAMES is re_mod.TOOL_NAMES and w2._TOOLS is re_mod.TOOL_NAMES


def test_the_ensemble_never_averages_across_methods_and_says_so(monkeypatch):
    _patch_arms(monkeypatch, "Goldilocks", None, "Reflation", "Reflation")
    r = re_mod.regime_ensemble({}, "kr", months=60)
    assert "probs" not in r and "consensus" not in r
    assert r["note"].startswith("방법끼리는 평균하지 않습니다.")
    assert "세 방법" not in r["note"] and "세 방법" not in r["agreement"]["note"]
    assert "k-평균" in r["usage_note"], "진단 전용이라는 선언이 넷째 팔도 덮는다"


# ══ 5. 합의 — 넷을 센다 · 군집 둘은 독립이 아니다 ══════════════════════════════

def test_the_consensus_counts_the_fourth_arm(monkeypatch):
    from src.api.macro_routes import regime_consensus_view
    _patch_arms(monkeypatch, "Goldilocks", "Goldilocks", "Reflation", "Reflation")
    out = regime_consensus_view({}, market="kr", months=60)
    assert out["per_tool"] == {"axis": "Goldilocks", "markov": "Goldilocks",
                               "cluster": "Reflation", "kmeans": "Reflation"}
    assert out["n_available"] == 4
    assert out["tie"] is True and out["verdict"] is None, "2:2 는 결론이 아니다(합의 규칙 그대로)"


def test_the_consensus_says_the_two_clustering_arms_are_not_independent(monkeypatch):
    from src.api.macro_routes import regime_consensus_view
    _patch_arms(monkeypatch, "Goldilocks", "Reflation", "Reflation", "Reflation")
    note = regime_consensus_view({}, market="kr", months=60)["note"]
    assert "군집 두 방법(GMM · k-평균)은 같은 좌표를 묶는 방법이라 서로 독립이 아닙니다." in note, note


def test_the_consensus_names_the_seed_unstable_arms(monkeypatch):
    """합의가 '모두 같다'고 말해도 시드에 따라 갈리는 팔이 있으면 그 이름을 적는다."""
    from src.api.macro_routes import regime_consensus_view
    _patch_seeded(monkeypatch, "Stagflation", cluster_agree=3, kmeans_agree=5)
    out = regime_consensus_view({}, market="kr", months=60)
    assert out["consensus"] is True, "합의 규칙은 그대로다"
    assert ("군집 모형(GMM) · 군집 모형(k-평균)의 답은 난수 시드에 따라 갈립니다(시드별 최다 답이 과반이 아닙니다)."
            in out["note"]), out["note"]
    assert out["seed_unstable"] == ["cluster", "kmeans"], "화면이 색을 고를 수 있게 키로도 낸다"


def test_the_consensus_is_silent_about_seeds_when_every_arm_is_stable(monkeypatch):
    """짝 — 모두 과반이면 그 문장이 없다."""
    from src.api.macro_routes import regime_consensus_view
    _patch_seeded(monkeypatch, "Stagflation", cluster_agree=6, kmeans_agree=10)
    out = regime_consensus_view({}, market="kr", months=60)
    assert "난수 시드에 따라" not in out["note"]
    assert out["seed_unstable"] == [], "★키는 늘 실린다★ — 없으면 빈 목록이지 키가 빠지지 않는다"


@pytest.mark.parametrize("missing", ["cluster", "kmeans"])
def test_the_dependence_sentence_needs_both_clustering_arms(monkeypatch, missing):
    """짝 — 군집 팔 하나가 답하지 못했으면 그 문장을 붙이지 않는다."""
    from src.api.macro_routes import regime_consensus_view
    arms = {"axis": "Goldilocks", "markov": "Reflation", "cluster": "Reflation", "kmeans": "Reflation"}
    arms[missing] = None
    _patch_arms(monkeypatch, **arms)
    out = regime_consensus_view({}, market="kr", months=60)
    assert missing in out["unavailable"]
    assert "서로 독립이 아닙니다" not in out["note"]


# ══ 6. 캔버스 해설 ════════════════════════════════════════════════════════════

def _canvas():
    """노드 레지스트리를 먼저 올린다 — 하위 노드 모듈을 먼저 부르면 순환 import 로 멈춘다."""
    from src.api import allocation_graph_nodes  # noqa: F401
    from src.api import allocation_graph_nodes_bl2 as bl2
    from src.api import allocation_graph_nodes_macro_w2 as w2
    return bl2, w2


def _seeded(regime: str, method: str, agree: int, kind: str) -> dict:
    shares = {r: 0.0 for r in REGIMES}
    shares[regime] = agree / SEEDS
    other = next(r for r in REGIMES if r != regime)
    shares[other] = (SEEDS - agree) / SEEDS
    return {"available": True, "method": method, "probs": shares, "probs_kind": kind, "argmax": regime,
            "detail": {}, "note": "",
            "stability": {"seeds": SEEDS, "modal": regime, "agree": agree, "shares": shares,
                          "stable": agree * 2 > SEEDS}}


def _view(cluster: dict, kmeans: dict) -> dict:
    tools = {"axis": _arm("Reflation", "axis"), "markov": _arm(None, "markov"), "cluster": cluster, "kmeans": kmeans}
    picks = {k: v["argmax"] for k, v in tools.items() if v.get("available")}
    return {"result": {"tools": tools, "regimes": REGIMES,
                       "agreement": {"unanimous": len(set(picks.values())) == 1, "picks": picks, "note": ""}}}


def test_the_canvas_explain_names_the_fourth_arm_and_each_arms_seed_count():
    _explain_ensemble = _canvas()[0]._explain_ensemble
    ex = _explain_ensemble(_view(_seeded("Reflation", "cluster", 7, "probability"),
                                 _seeded("Reflation", "kmeans", 4, "seed_share")), {}, None)
    facts = ex["facts"]
    assert "군집 모형(k-평균): Reflation" in facts
    assert "군집 모형(GMM): 난수 시드 10개 중 7개가 Reflation입니다(과반)." in facts
    assert "군집 모형(k-평균): 난수 시드 10개 중 4개가 Reflation입니다(과반 미만)." in facts
    assert ("군집 모형(k-평균)의 값은 확률이 아니라 난수 시드 10개 가운데 그 국면을 고른 비율입니다." in facts)
    assert not any(f.startswith("군집 모형(GMM)의 값은") for f in facts), "짝 — GMM 팔의 값은 확률이다"
    assert "방법끼리 평균하지 않습니다 — 불일치 자체가 정보입니다." in facts
    assert not any("세 방법" in f for f in facts) and "세 방법" not in ex["title"]
    # 과반 미만인 팔은 '미상' 으로 알린다 — 과반인 팔은 알리지 않는다(짝)
    unstable = [t["text"] for t in ex["trust"] if "시드에 따라" in t["text"]]
    assert unstable == ["군집 모형(k-평균)의 답이 난수 시드에 따라 갈립니다 — 시드 10개 중 최다 답이 4개입니다."]
    assert all(t["state"] == "unknown" for t in ex["trust"] if "시드에 따라" in t["text"])


def test_the_canvas_explain_says_when_the_answer_differs_from_the_seed_majority():
    """GMM 팔의 답(평균의 최댓값)이 시드별 최다 답과 다르면 해설이 그 사실을 '미상' 으로 적는다."""
    _explain_ensemble = _canvas()[0]._explain_ensemble
    gmm = _seeded("Goldilocks", "cluster", 6, "probability")
    gmm["argmax"] = "Reflation"                       # 평균은 Reflation · 시드 6개는 Goldilocks
    ex = _explain_ensemble(_view(gmm, _seeded("Reflation", "kmeans", 10, "seed_share")), {}, None)
    lines = [t["text"] for t in ex["trust"] if "최다 답(" in t["text"]]
    assert lines == ["군집 모형(GMM)의 답(Reflation)이 난수 시드별 최다 답(Goldilocks)과 다릅니다 — 시드 평균의 답입니다."]


def test_the_canvas_explain_is_silent_when_the_answer_is_the_seed_majority():
    """짝 — 답과 최다 답이 같으면 그 줄이 없다."""
    _explain_ensemble = _canvas()[0]._explain_ensemble
    ex = _explain_ensemble(_view(_seeded("Reflation", "cluster", 6, "probability"),
                                 _seeded("Reflation", "kmeans", 10, "seed_share")), {}, None)
    assert not any("최다 답(" in t["text"] for t in ex["trust"])


#: 해설의 '재지 않은 것' — 시드 과반이 무엇을 재지 않는지(M1c · 위 `test_a_seed_majority_is_not_robustness_to_the_data`).
DATA_ROBUSTNESS_UNMEASURED = "자료가 조금 달라져도 같은 국면이 나오는지(시드 과반은 난수 시드만 바꿔 본 값)"


def test_the_canvas_explain_says_a_seed_majority_does_not_measure_the_data():
    """시드 줄('과반' / '과반 미만')이 있으면 '재지 않은 것'에 자료 흔들기를 적는다 — '과반'이 견고함으로 읽히지 않게."""
    _explain_ensemble = _canvas()[0]._explain_ensemble
    ex = _explain_ensemble(_view(_seeded("Reflation", "cluster", 9, "probability"),
                                 _seeded("Reflation", "kmeans", 10, "seed_share")), {}, None)
    assert ex["unmeasured"] == ["국면 판정의 향후 수익률 예측력", DATA_ROBUSTNESS_UNMEASURED]


def test_the_canvas_explain_is_silent_about_seeds_when_no_arm_was_reseeded():
    """짝 — 군집 두 팔이 모두 계산되지 않아 시드 줄이 없으면 그 문장도 없다(말할 '과반'이 없다)."""
    _explain_ensemble = _canvas()[0]._explain_ensemble
    ex = _explain_ensemble(_view(_arm(None, "cluster"), _arm(None, "kmeans")), {}, None)
    assert not any("난수 시드" in f for f in ex["facts"])
    assert ex["unmeasured"] == ["국면 판정의 향후 수익률 예측력"]


def test_the_canvas_explain_title_qualifies_unanimity_on_an_unstable_arm():
    _explain_ensemble = _canvas()[0]._explain_ensemble
    view = _view(_seeded("Reflation", "cluster", 3, "probability"), _seeded("Reflation", "kmeans", 10, "seed_share"))
    ex = _explain_ensemble(view, {}, None)
    assert ex["title"] == "모든 방법이 같은 국면을 가리킵니다 — 다만 난수 시드에 따라 답이 갈리는 방법이 있습니다"


def test_the_canvas_explain_title_says_every_method_when_unanimous():
    _explain_ensemble = _canvas()[0]._explain_ensemble
    view = _view(_seeded("Reflation", "cluster", 9, "probability"), _seeded("Reflation", "kmeans", 10, "seed_share"))
    ex = _explain_ensemble(view, {}, None)
    assert ex["title"] == "모든 방법이 같은 국면을 가리킵니다"
    assert not any("시드에 따라" in t["text"] for t in ex["trust"]), "모두 과반이면 시드 경고가 없다"


def test_the_canvas_consensus_explain_does_not_say_three_methods():
    _explain_consensus = _canvas()[1]._explain_consensus
    ex = _explain_consensus({"result": {"verdict": "Reflation", "consensus": True, "tie": False, "n_available": 4,
                                        "per_tool": {"axis": "Reflation", "kmeans": "Reflation"}, "reasons": {}}},
                            {}, None)
    assert "군집 모형(k-평균): Reflation" in ex["facts"]
    texts = [t["text"] for t in ex["trust"]]
    assert "방법끼리 평균하지 않습니다 — 불일치 자체가 정보입니다." in texts
    assert not any("세 방법" in t for t in texts)


def test_the_node_descriptions_name_four_methods():
    from src.api import allocation_graph_nodes as gn
    assert (gn.REGISTRY.get("regime_ensemble").plain_description
            == "축 판정·상태 전환·군집(GMM·k-평균) 네 방법의 국면 판정을 비교합니다.")
    assert gn.REGISTRY.get("regime_consensus").plain_description == "네 방법의 국면 판정 일치 여부를 표시합니다."
