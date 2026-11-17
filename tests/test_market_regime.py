"""시장 국면(일) 엔진 — 구현 계획 §7.1 · §7.2 (K1).

거는 것: 손 계산 특징 · 창 안의 나쁜 종가 · 앞보기 0(그날 · 그 뒤 종가를 바꿔도 그날 확률 불변) · 변동성 두 단계 되찾기 ↔ 일정한 걸음 ·
번호 = 변동성 낮은 순 · 창이 다 차야 적합(창 − 1 ↔ 창) · 고정 길이 창(읽기 시작점이 달라도 같은 날 같은 값) · 시드 평균 · BIC 는 고르지 않는다.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from src.engine import market_regime as mr


def walk(n: int, vol: float | np.ndarray, seed: int = 0, start: float = 2500.0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = np.broadcast_to(np.asarray(vol, dtype=float), (n,))
    return start * np.exp(np.cumsum(rng.normal(0.0, 1.0, n) * v))


def bdays(n: int, start: str = "2019-01-01") -> list[str]:
    return [d.strftime("%Y-%m-%d") for d in pd.bdate_range(start, periods=n)]


# ── 특징 ─────────────────────────────────────────────────────────────────────────────
def test_features_by_hand():
    rets = [0.02, -0.01] * 10                                            # 일 로그 수익 20개
    closes = 100.0 * np.exp(np.concatenate([[0.0], np.cumsum(rets)]))   # 종가 21개
    r20, s20 = mr.features(closes)
    assert np.isnan(r20[:20]).all() and np.isnan(s20[:20]).all()       # 첫 20거래일은 미상
    assert r20[20] == pytest.approx(0.1)                                # ln(C20 / C0) = Σ = 0.1
    m = sum(rets) / 20
    sd = math.sqrt(sum((x - m) ** 2 for x in rets) / 19)               # 표본 표준편차(ddof 1)
    assert s20[20] == pytest.approx(sd * math.sqrt(252))


@pytest.mark.parametrize("bad", [0.0, -5.0, float("nan"), float("inf")])
def test_a_bad_close_leaves_every_day_whose_window_holds_it_unknown(bad):
    closes = walk(80, 0.01, seed=1)
    closes[30] = bad
    r20, s20 = mr.features(closes)
    assert np.isnan(r20[30:51]).all() and np.isnan(s20[30:51]).all()  # 종가 21개 창이 30 을 품는 날
    assert not np.isnan(s20[29]) and not np.isnan(s20[51])             # 짝 — 창 밖은 값이 있다


# ── 앞보기 0 ──────────────────────────────────────────────────────────────────────────
def test_a_days_probability_sees_neither_that_day_nor_later():
    n = 1100
    closes, dates = walk(n, 0.01, seed=3), bdays(n)
    base = {d["date"]: d["probs"] for d in mr.regime_days(dates, closes, k=2, start=dates[880], end=dates[-1])["days"]}
    for cut in (900, 955, 1010, 1099):
        moved = closes.copy()
        moved[cut:] *= np.exp(np.random.default_rng(cut).normal(0, 0.05, n - cut))
        again = {d["date"]: d["probs"] for d in mr.regime_days(dates, moved, k=2, start=dates[880], end=dates[-1])["days"]}
        for day in dates[880:cut + 1]:                                   # 그날(cut) 까지 — 그날의 종가가 바뀌어도 그날은 같다
            assert again[day] == base[day], (cut, day)
        assert any(again[d] != base[d] for d in dates[cut + 1:]) or cut == n - 1   # 짝 — 그 뒤는 달라진다(장치가 산다)


# ── 국면을 되찾음 · 번호 ────────────────────────────────────────────────────────────────
def two_level(n_blocks: int = 12, size: int = 120, seed: int = 7) -> np.ndarray:
    vols = np.concatenate([np.full(size, 0.005 if b % 2 == 0 else 0.02) for b in range(n_blocks)])
    return walk(len(vols), vols, seed=seed)


def test_two_volatility_levels_are_recovered_and_numbered_low_to_high():
    closes = two_level()
    dates = bdays(len(closes))
    out = mr.regime_days(dates, closes, k=2, start=dates[1000], end=dates[-1])
    hit = seen = 0
    for i, d in enumerate(out["days"], start=1000):
        into = i % 120
        if into < 22 or d["probs"] is None:                               # d−1 의 σ20 창이 블록 안에 다 들어야 한다
            continue
        seen += 1
        hit += (d["top"] == 2) == ((i // 120) % 2 == 1)
    assert seen > 300 and hit / seen > 0.97                               # 잰 값: 초안에서 374/374(자료 시드 셋 모두)
    vols = [s["realized_vol"] for s in out["states"]]
    assert vols == sorted(vols)                                           # 번호 1 = 변동성이 가장 낮다


def test_the_table_volatility_can_leave_the_numbering_order_without_regimes():
    """화면의 한계 문장('국면별 통계의 실현 변동성은 … 번호 순서와 다를 수 있다')의 근거(K1b) — 번호는 적합 창에서 성분의 σ20 평균 순이고,
    표의 실현 변동성은 그 기간 그 국면으로 센 날들의 일 수익으로 잰 값이다. 국면이 없는 걸음(변동성 일정)에서는 두 순서가 어긋난다 ↔
    짝: 두 단계 자료에서는 같은 순서다(바로 위 `test_two_volatility_levels_are_recovered_and_numbered_low_to_high`).
    번호를 그 기간의 결과로 다시 매기는 구현(앞보기)도 이 시험이 잡는다.
    잰 값(커밋한 엔진 · 걸음 씨앗 0 ~ 9): 어긋난 걸음 국면 2 에서 7개 · 국면 3 에서 8개 — 국면 3 의 씨앗 5 는 19.1% · 17.1% · 15.5%(번호와 거꾸로)."""
    closes = walk(1440, 0.0125, seed=5)
    dates = bdays(len(closes))
    vols = [s["realized_vol"] for s in mr.regime_days(dates, closes, k=3, start=dates[1000], end=dates[-1])["states"]]
    assert all(v is not None for v in vols)
    assert vols != sorted(vols)                                           # 번호 1 이 표에서 가장 낮은 변동성이라는 보장은 없다


def test_a_constant_volatility_walk_gives_states_without_a_volatility_gap():
    """짝 — 국면이 없는 자료에서도 k 개를 내지만, 국면 사이 변동성 차이가 두 단계 자료보다 훨씬 작다(말할 것이 없다)."""
    closes = walk(1440, 0.0125, seed=7)
    dates = bdays(len(closes))
    flat = mr.regime_days(dates, closes, k=2, start=dates[1000], end=dates[-1])
    stepped = mr.regime_days(dates, two_level(), k=2, start=dates[1000], end=dates[-1])
    gap = lambda o: o["states"][1]["realized_vol"] - o["states"][0]["realized_vol"]   # noqa: E731
    assert gap(flat) < 0.25 * gap(stepped)


# ── 하한 · 고정 창 ─────────────────────────────────────────────────────────────────────
def test_a_month_whose_window_is_not_full_is_unknown_with_numbers_and_a_full_window_gives_values():
    """창이 다 차야 적합한다 — 짧은 창으로 조용히 적합하지 않는다(뒤에 이력이 적재되면 같은 날의 값이 바뀐다)."""
    dates_all = bdays(400, start="2020-01-01")
    s = [i for i in range(1, 400) if dates_all[i][:7] != dates_all[i - 1][:7] and i >= 250][0]   # 어느 달의 첫 거래일
    fit_days = 200
    closes_all = walk(400, 0.01, seed=5)
    for have, known in ((fit_days - 1, False), (fit_days, True)):
        cut = s - (have + 20)                                             # 특징은 종가 21개부터 — have 개가 s 앞에 남게
        out = mr.regime_days(dates_all[cut:], closes_all[cut:], k=4, start=dates_all[s], end=dates_all[s + 5], fit_days=fit_days)
        first = out["days"][0]
        assert (first["probs"] is not None) is known, have
        if not known:
            assert first["reason"] == mr.REASONS["too_little_history"].format(need=fit_days, have=have)


def test_the_same_day_has_the_same_value_whatever_the_reading_start():
    n = 1500
    closes, dates = walk(n, 0.01, seed=9), bdays(n)
    day = dates[1400]
    a = mr.regime_days(dates, closes, k=3, start=day, end=day)["days"][0]["probs"]
    b = mr.regime_days(dates[200:], closes[200:], k=3, start=day, end=day)["days"][0]["probs"]   # 읽기 시작이 200일 늦다
    assert a is not None and a == b                                      # 창이 고정 길이(750)라 같다


# ── 출력의 모양 · BIC · 일치도 ──────────────────────────────────────────────────────────
def test_the_answer_carries_bic_for_two_to_four_without_choosing_and_seed_agreement():
    closes = two_level()
    dates = bdays(len(closes))
    out = mr.regime_days(dates, closes, k=2, start=dates[1300], end=dates[-1])
    assert set(out["bic"]) == {"2", "3", "4"} and all(math.isfinite(v) for v in out["bic"].values())
    assert "chosen" not in out["bic"] and out["fit"]["seeds"] == mr.SEEDS
    assert 0.0 <= out["agreement"]["min"] <= out["agreement"]["mean"] <= 1.0
    probs = [d["probs"] for d in out["days"] if d["probs"] is not None]
    assert probs and all(len(p) == 2 and abs(sum(p) - 1) < 1e-9 for p in probs)


def test_high_seed_agreement_also_happens_without_regimes():
    """화면의 한계 문장('일치도가 높다고 국면이 있다는 뜻이 아니다')의 근거 — 국면이 없는 걸음(변동성 일정)에서도 시드가 모두 같은 답을 낸다 ↔
    같은 꼴의 다른 걸음은 시드가 갈린다(일치도는 자료에 따라 달라질 뿐 국면의 유무를 말하지 않는다).
    잰 값(커밋한 엔진 · 국면 2 · 3 · 4 × 걸음 씨앗 0 ~ 9 · 서른 개): 최소 일치도 −0.007 ~ 1.000 — 국면 2 의 씨앗 0 은 1.000 · 씨앗 9 는 −0.007."""
    def agreement_min(seed: int) -> float:
        closes = walk(1440, 0.0125, seed=seed)
        dates = bdays(len(closes))
        return mr.regime_days(dates, closes, k=2, start=dates[1000], end=dates[-1])["agreement"]["min"]
    assert agreement_min(0) >= 0.95                                      # 국면이 없는데도 시드 열 개가 같은 답
    assert agreement_min(9) <= 0.35                                      # 짝 — 같은 꼴의 다른 자료는 갈린다(늘 높은 값을 내는 구현을 배제)


@pytest.mark.parametrize("shape", ["flat", "steady_growth", "tiny_but_varying"])
def test_a_window_whose_features_do_not_vary_is_unknown_not_a_made_up_split(shape):
    """특징이 변하지 않는 창(평평한 가격 · 일정한 성장)에는 나눌 것이 없다 — 한쪽 100% 나 반반 같은 지어낸 확률이 아니라 미상 + 사유.
    잰 값(고치기 전): 평평한 가격은 날마다 국면 1 이 100% · 일치도 1 / 일정한 성장은 0.5 · 0.5 근처에서 51 대 49 로 갈림 · 일치도 1
    (표준화가 분산 0 열을 1 로 나누거나 반올림 잡음을 키웠다). 짝: 아주 작아도 변하는 자료는 값을 낸다(늘 미상인 구현을 배제)."""
    n = 400
    if shape == "flat":
        closes = np.full(n, 2500.0)
    elif shape == "steady_growth":
        closes = 2500.0 * np.exp(0.001 * np.arange(n))
    else:
        closes = walk(n, 1e-4, seed=8)
    dates = bdays(n)
    out = mr.regime_days(dates, closes, k=2, start=dates[300], end=dates[-1], fit_days=200, seeds=4)
    assert len(out["days"]) == 100
    if shape == "tiny_but_varying":
        assert all(d["probs"] is not None for d in out["days"]) and out["fit"]["refits"] > 0
        return
    assert all(d["probs"] is None and d["reason"] == mr.REASONS["flat_window"] for d in out["days"])
    assert out["fit"]["refits"] == 0 and out["agreement"] is None and out["bic"] is None


def test_a_month_whose_seeds_all_fail_is_unknown_with_the_reason_and_every_failure_is_counted(monkeypatch):
    """시드가 모두 수렴하지 못한 달은 미상 + 사유 — 균등 확률 · 앞 달의 적합으로 채우지 않는다. 실패는 두 길(예외 · 수렴 못 함)을 모두 센다."""
    import sklearn.mixture

    class Fails:                                                          # 짝수 시드는 예외 · 홀수 시드는 수렴하지 못함
        def __init__(self, *, n_components, covariance_type, random_state):
            self.seed = random_state

        def fit(self, Z):
            if self.seed % 2 == 0:
                raise ValueError("심은 실패")
            self.converged_ = False
            return self

    monkeypatch.setattr(sklearn.mixture, "GaussianMixture", Fails)
    n, fit_days, seeds = 400, 200, 4
    closes, dates = walk(n, 0.01, seed=2), bdays(n)
    out = mr.regime_days(dates, closes, k=2, start=dates[300], end=dates[-1], fit_days=fit_days, seeds=seeds)
    months = {d["date"][:7] for d in out["days"]}
    assert len(out["days"]) == 100 and len(months) >= 4
    assert all(d["probs"] is None and d["top"] is None and d["reason"] == mr.REASONS["fit_failed"] for d in out["days"])
    assert out["fit"]["refits"] == 0 and out["fit"]["failed"] == seeds * len(months)   # 달마다 넷 — 예외 둘 + 수렴 못 함 둘
    assert out["bic"] is None and out["agreement"] is None and out["transitions"] == 0
    assert all(s["days"] == 0 and s["share"] is None and s["mean_return"] is None for s in out["states"])


def test_state_statistics_and_transitions_are_counted_over_the_valued_days_by_hand():
    """국면별 통계(날 수 · 비중 · 일 로그 수익 평균 · 실현 변동성) · 전환 수 = 손으로 센 값. 값이 없는 날(나쁜 종가 뒤)은 세지 않는다 —
    그날들은 0 이나 균등 확률이 아니라 미상 + 사유(직전 거래일의 특징 없음)다."""
    n, fit_days = 520, 200
    closes = walk(n, np.where((np.arange(n) // 60) % 2 == 0, 0.006, 0.02), seed=4)
    closes[450] = 0.0                                                     # 판정 기간 안의 나쁜 종가 — 특징 창(21개)이 그것을 품는 날이 미상
    dates = bdays(n)
    out = mr.regime_days(dates, closes, k=2, start=dates[400], end=dates[-1], fit_days=fit_days)
    days = out["days"]
    unknown = [d["date"] for d in days if d["probs"] is None]
    assert unknown == dates[451:472]                                     # 그날의 입력은 d−1 의 특징 — 451 ~ 471
    assert all(d["reason"] == mr.REASONS["no_feature"] for d in days if d["probs"] is None)
    at = {d: i for i, d in enumerate(dates)}
    with np.errstate(divide="ignore"):
        lc = np.log(np.where(closes > 0, closes, np.nan))
    valued = [d for d in days if d["top"] is not None]
    for st in out["states"]:
        mine = [d for d in valued if d["top"] == st["state"]]
        rets = [lc[at[d["date"]]] - lc[at[d["date"]] - 1] for d in mine]
        rets = [r for r in rets if np.isfinite(r)]                      # 나쁜 종가의 날 · 그 다음 날은 수익이 없다
        assert len(mine) > 10 and len(rets) >= 2
        assert st["days"] == len(mine)
        assert st["share"] == pytest.approx(len(mine) / len(valued))
        assert st["mean_return"] == pytest.approx(float(np.mean(rets)))
        assert st["realized_vol"] == pytest.approx(float(np.std(rets, ddof=1)) * math.sqrt(252))
    assert sum(s["days"] for s in out["states"]) == len(valued)
    assert out["transitions"] == sum(1 for a, b in zip(valued, valued[1:]) if a["top"] != b["top"])
    assert out["transitions"] > 0                                         # 전제 — 두 단계 자료라 국면이 바뀐다(0 이면 이 단언이 공허하다)


def test_bic_and_seed_agreement_are_measured_on_the_last_fitted_window():
    """화면은 BIC 와 일치도를 '마지막 적합 창'의 값이라고 적는다 — 시험이 그 창(판정 기간 마지막 달 첫 거래일 전 fit_days 개)을
    따로 표준화해 sklearn 으로 적합한 값과 같아야 한다. 짝: 첫 달의 창으로 잰 값과는 다르다(어느 창인지가 실제로 갈린다)."""
    from sklearn.metrics import adjusted_rand_score
    from sklearn.mixture import GaussianMixture

    n, fit_days, seeds = 560, 200, 4
    closes = walk(n, np.where((np.arange(n) // 60) % 2 == 0, 0.006, 0.02), seed=6)
    dates = bdays(n)
    out = mr.regime_days(dates, closes, k=3, start=dates[400], end=dates[-1], fit_days=fit_days, seeds=seeds)
    r20, s20 = mr.features(closes)
    X = np.column_stack([r20, s20])
    known = np.isfinite(X).all(axis=1)

    def measured(month_first: int):
        hist = np.flatnonzero(known[:month_first])[-fit_days:]
        mu, sd = X[hist].mean(axis=0), X[hist].std(axis=0)
        Z = (X[hist] - mu) / sd
        bic = {str(kk): min(GaussianMixture(n_components=kk, covariance_type="full", random_state=s).fit(Z).bic(Z)
                            for s in range(seeds)) for kk in (2, 3, 4)}
        labels = []
        for s in range(seeds):
            g = GaussianMixture(n_components=3, covariance_type="full", random_state=s).fit(Z)
            labels.append(np.argsort(g.means_[:, 1], kind="stable").argsort()[g.predict(Z)])
        ari = [adjusted_rand_score(labels[0], other) for other in labels[1:]]
        return bic, min(ari), sum(ari) / len(ari)

    last_first = next(i for i, d in enumerate(dates) if d[:7] == dates[-1][:7])
    first_first = next(i for i, d in enumerate(dates) if d[:7] == dates[400][:7])
    bic, lo, mean = measured(last_first)
    assert out["bic"] == pytest.approx(bic)
    assert out["agreement"]["min"] == pytest.approx(lo) and out["agreement"]["mean"] == pytest.approx(mean)
    assert out["agreement"]["seeds"] == seeds
    bic0, _, _ = measured(first_first)
    assert bic0 != pytest.approx(bic)                                     # 짝 — 첫 달의 창으로 잰 BIC 와는 다르다


def test_a_days_probability_is_the_mean_of_the_seeds_fitted_independently():
    """시드 평균을 직접 건다 — 시험이 sklearn 으로 같은 창 · 같은 표준화 · 같은 시드를 따로 적합해 번호를 맞춘 뒤 평균한 값과 같다.
    짝: 시드 하나(0)의 확률과는 다르다(평균이 실제로 여러 시드를 쓴다는 것 — 변이 '시드 하나만'을 직접 죽인다).
    ★전제를 단언한다★: 이 자료(걸음 씨앗 11 · 국면 4개)에서는 시드들이 실제로 다른 답을 낸다(잰 값: 시드 0 과의 최대 차이 0.85).
    시드들이 같은 답을 내는 자료(예: 같은 걸음의 국면 3개 — 차이 0)에서는 이 시험이 아무것도 가리지 못한다."""
    from sklearn.mixture import GaussianMixture

    n, fit_days, seeds, k = 470, 200, 5, 4
    vol = np.where((np.arange(n) // 60) % 2 == 0, 0.006, 0.02)
    closes = walk(n, vol, seed=11)
    dates = bdays(n)
    out = mr.regime_days(dates, closes, k=k, start=dates[-1], end=dates[-1], fit_days=fit_days, seeds=seeds)
    day = out["days"][0]
    assert day["probs"] is not None
    r20, s20 = mr.features(closes)
    X = np.column_stack([r20, s20])
    known = np.isfinite(X).all(axis=1)
    first = next(i for i, d in enumerate(dates) if d[:7] == dates[-1][:7])
    hist = np.flatnonzero(known[:first])[-fit_days:]
    mu, sd = X[hist].mean(axis=0), X[hist].std(axis=0)
    z = ((X[n - 2] - mu) / sd)[None, :]
    per_seed = []
    for s in range(seeds):
        g = GaussianMixture(n_components=k, covariance_type="full", random_state=s).fit((X[hist] - mu) / sd)
        per_seed.append(g.predict_proba(z)[0][np.argsort(g.means_[:, 1], kind="stable")])
    assert float(np.max(np.abs(np.array(per_seed) - per_seed[0]))) > 0.1        # 전제 — 시드가 갈리는 자료
    want = np.mean(per_seed, axis=0)
    assert np.allclose(day["probs"], want, atol=1e-9)
    assert not np.allclose(day["probs"], per_seed[0], atol=1e-3)                  # 짝 — 시드 0 하나의 답이 아니다
