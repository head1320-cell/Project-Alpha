"""하루 유형 모형의 엔진 — 장 시작 N분의 경로를 e-means 로 묶는다 (구현 계획 2026-11-16 §5 · T1).

엔진 `src/engine/intraday/day_types.py` 는 순수 함수다(파일 · DB 를 모른다). 여기서 거는 것:
- 특징 = 첫 봉 시가 대비 첫 N개 종가(bp) · 창은 첫 봉 시각부터 1분마다 하나씩(빠진 분 → 제외) · 가격 가드
- 학습 = e-means(난수 시드 고정) · 번호 = 끝값 오름차순 · 배정 = ★저장한 중심에서 다시 셈★(e-means 의 마지막 회차 라벨이 아니다)
- 같은 자료의 Lloyd 손실 · 난수 시드 다섯의 일치도 · 유형별 표본 수 · 하한 · 열쇠

★증거의 등급★: 심은 자료로 장치가 뜻대로 도는지 본다(`structural` + `synthetic_mechanism`). 유형이 실제 시장에서 뜻이 있는지는 재지 않는다.
부동소수점의 마지막 자리에 기대는 값(중심의 정확한 좌표 · 손실의 정확한 값)은 걸지 않는다 — 다른 기계에서 BLAS 가 다르게 더한다(M1c 의 교훈).
"""
from __future__ import annotations

import numpy as np
import pytest
from sklearn.metrics import adjusted_rand_score

from src.engine.intraday import Day, Session
from src.engine.intraday import day_types as dt

UP = [10.0, 20.0, 30.0, 40.0, 50.0]
DOWN = [-10.0, -20.0, -30.0, -40.0, -50.0]
VEE = [-10.0, -20.0, -30.0, -20.0, -10.0]
HAT = [10.0, 20.0, 30.0, 20.0, 10.0]


def clock(start: str, n: int) -> list[str]:
    h, m = int(start[:2]), int(start[2:4])
    return [f"{(h * 60 + m + i) // 60:02d}{(h * 60 + m + i) % 60:02d}00" for i in range(n)]


def session(day: str, closes, *, ticker="005930", start="090000", times=None, open0=10_000.0, source="kis") -> Session:
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    t = np.asarray(times if times is not None else clock(start, n))
    opens = np.concatenate([[open0], closes[:-1]]) if n else np.asarray([], dtype=float)
    hi = np.maximum(opens, closes)
    lo = np.minimum(opens, closes)
    return Session(ticker, day, t, opens, hi, lo, closes, np.full(n, 1_000.0), source)


def bp_day(day: str, path, **kw) -> Session:
    """bp 경로 → 첫 봉 시가 10,000 의 종가(정수 원). 10bp = 10원이라 손 계산과 같다."""
    return session(day, [10_000.0 + p for p in path], **kw)


def days_of(sessions: list[Session]) -> list[Day]:
    by: dict[str, dict[str, Session]] = {}
    for s in sessions:
        by.setdefault(s.date, {})[s.ticker] = s
    return [Day(d, by[d]) for d in sorted(by)]


def planted(reps: int = 6, paths=(UP, DOWN, VEE, HAT)):
    """유형 넷을 심은 표본들 — 같은 유형의 표본은 바이트로 같다(시드 다섯이 모두 되찾는다 · 계획 §5.0)."""
    out, truth = [], []
    tickers = ["005930", "000660", "035420", "035720", "051910", "068270", "005380", "105560", "055550", "000270"]
    for t, path in enumerate(paths):
        for r in range(reps):
            out.append(bp_day(f"2026-05-{1 + t * reps // 10 + r % 28:02d}", path, ticker=tickers[(t * reps + r) % 10]))
            truth.append(t)
    return out, truth


def unique_days(sessions: list[Session]) -> list[Session]:
    """같은 (날, 종목)이 겹치지 않게 날을 다시 붙인다."""
    out = []
    for i, s in enumerate(sessions):
        out.append(Session(s.ticker, f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}", s.time, s.open, s.high, s.low, s.close,
                           s.volume, s.source))
    return out


# ── 특징 ────────────────────────────────────────────────────────────────────────────────
def test_the_feature_is_the_first_n_closes_in_bp_of_the_first_open():
    got = dt.collect(days_of([bp_day("2026-05-04", UP)]), minutes=5)
    assert got.samples == [("2026-05-04", "005930")]
    np.testing.assert_allclose(got.X[0], UP, atol=1e-9)
    shorter = dt.collect(days_of([bp_day("2026-05-04", UP)]), minutes=3)
    np.testing.assert_allclose(shorter.X[0], UP[:3], atol=1e-9)      # 창 뒤의 봉은 쓰지 않는다


def test_the_base_is_the_first_open_not_the_first_close():
    s = session("2026-05-04", [10_050.0, 10_100.0, 10_150.0, 10_200.0, 10_250.0], open0=10_000.0)
    got = dt.collect(days_of([s]), minutes=5)
    np.testing.assert_allclose(got.X[0], [50.0, 100.0, 150.0, 200.0, 250.0], atol=1e-9)


def test_the_window_starts_at_the_first_bar_of_that_day():
    got = dt.collect(days_of([bp_day("2026-05-04", UP, start="090300")]), minutes=5)
    assert got.starts == ["090300"]
    np.testing.assert_allclose(got.X[0], UP, atol=1e-9)


def test_a_missing_minute_inside_the_window_excludes_the_day():
    times = ["090000", "090100", "090300", "090400", "090500"]       # 09:02 가 빠졌다
    got = dt.collect(days_of([bp_day("2026-05-04", UP, times=times)]), minutes=5)
    assert got.samples == []
    assert got.excluded == [("2026-05-04", "005930", "short_window")]


def test_a_missing_minute_after_the_window_does_not_matter():
    times = ["090000", "090100", "090300", "090400", "090500"]       # 짝: 창(첫 2분)은 온전하다
    got = dt.collect(days_of([bp_day("2026-05-04", UP, times=times)]), minutes=2)
    assert got.samples == [("2026-05-04", "005930")]
    assert got.excluded == []


def test_fewer_bars_than_minutes_excludes_the_day():
    got = dt.collect(days_of([bp_day("2026-05-04", UP[:4])]), minutes=5)
    assert got.samples == [] and got.excluded == [("2026-05-04", "005930", "short_window")]


@pytest.mark.parametrize("open0, closes", [
    (0.0, [10_010.0] * 5),                                           # 0 으로 나누지 않는다
    (-10_000.0, [10_010.0] * 5),                                     # 음수 시가
    (float("nan"), [10_010.0] * 5),
    (10_000.0, [10_010.0, float("nan"), 10_030.0, 10_040.0, 10_050.0]),
    (10_000.0, [10_010.0, 0.0, 10_030.0, 10_040.0, 10_050.0]),
    (10_000.0, [10_010.0, -5.0, 10_030.0, 10_040.0, 10_050.0]),
])
def test_bad_prices_inside_the_window_exclude_the_day(open0, closes):
    got = dt.collect(days_of([session("2026-05-04", closes, open0=open0)]), minutes=5)
    assert got.samples == []
    assert got.excluded == [("2026-05-04", "005930", "bad_price")]
    assert np.isfinite(got.X).all()


def test_a_bad_price_after_the_window_does_not_matter():
    closes = [10_010.0, 10_020.0, 10_030.0, float("nan"), 0.0]      # 짝: 창(첫 3분) 밖
    got = dt.collect(days_of([session("2026-05-04", closes)]), minutes=3)
    assert got.samples == [("2026-05-04", "005930")]


def test_days_the_feed_already_skipped_keep_their_reason():
    day = Day("2026-05-04", {"005930": bp_day("2026-05-04", UP)}, (("000660", "no_bars"), ("035720", "defects")))
    got = dt.collect([day], minutes=5)
    assert got.samples == [("2026-05-04", "005930")]
    assert sorted(got.excluded) == [("2026-05-04", "000660", "no_bars"), ("2026-05-04", "035720", "defects")]


def test_samples_come_out_in_date_then_ticker_order():
    a = bp_day("2026-05-05", UP, ticker="000660")
    b = bp_day("2026-05-04", DOWN, ticker="035720")
    c = bp_day("2026-05-04", VEE, ticker="005930")
    got = dt.collect(days_of([a, b, c]), minutes=5)
    assert got.samples == [("2026-05-04", "005930"), ("2026-05-04", "035720"), ("2026-05-05", "000660")]
    np.testing.assert_allclose(got.X[0], VEE, atol=1e-9)


def test_the_grade_is_set_by_the_weakest_source():
    real = dt.collect(days_of([bp_day("2026-05-04", UP)]), minutes=5)
    # 합성 표본이 정렬상 뒤에 온다(035720 > 005930) — 첫 표본만 보는 구현을 가른다
    mixed = dt.collect(days_of([bp_day("2026-05-04", UP), bp_day("2026-05-04", DOWN, ticker="035720", source="synthetic")]),
                       minutes=5)
    assert real.grade == "E3" and mixed.grade == "E0"
    assert mixed.sources == {"kis": 1, "synthetic": 1}


# ── 학습 · 번호 · 배정 ────────────────────────────────────────────────────────────────────
def fit_planted(reps=6, paths=(UP, DOWN, VEE, HAT), k=4):
    sessions, truth = planted(reps, paths)
    got = dt.collect(days_of(unique_days(sessions)), minutes=5)
    return got, dt.fit(got.X, k), truth


def test_planted_types_are_recovered_and_every_seed_agrees():
    got, model, _ = fit_planted()
    labels = np.asarray(model["labels"])
    # 같은 경로의 날은 같은 유형이다(심은 묶음 그대로)
    for path in (UP, DOWN, VEE, HAT):
        rows = [i for i in range(len(got.X)) if np.allclose(got.X[i], path)]
        assert len(set(labels[rows])) == 1
    assert len(set(labels.tolist())) == 4
    assert model["agreement"]["same"] is True
    assert model["agreement"]["min"] == pytest.approx(1.0)
    assert model["agreement"]["seeds"] == [1234, 1235, 1236, 1237, 1238]


def test_noise_days_split_differently_by_seed():
    rng = np.random.default_rng(7)
    X = rng.normal(0.0, 40.0, (120, 10)).cumsum(axis=1)
    model = dt.fit(X, 8)
    assert model["agreement"]["same"] is False
    assert model["agreement"]["min"] < 0.99
    assert len(model["agreement"]["ari"]) == 4


def test_types_are_numbered_by_their_last_value():
    got, model, _ = fit_planted()
    ends = [t["end"] for t in model["types"]]
    assert ends == sorted(ends)
    assert [t["type"] for t in model["types"]] == [1, 2, 3, 4]
    np.testing.assert_allclose(model["types"][0]["path"], DOWN, atol=1e-3)   # 끝값이 가장 낮은 유형이 1
    np.testing.assert_allclose(model["types"][3]["path"], UP, atol=1e-3)


def test_numbering_follows_the_end_not_the_start():
    rise = [-50.0, 0.0, 0.0, 0.0, 50.0]                              # 처음은 가장 낮고 끝은 가장 높다
    fall = [50.0, 0.0, 0.0, 0.0, -50.0]
    C = dt.order_centroids(np.asarray([rise, fall]))
    np.testing.assert_allclose(C[0], fall)                           # 끝값 −50 이 1번
    np.testing.assert_allclose(C[1], rise)


def test_equal_last_values_are_ordered_by_the_whole_path():
    flat = [-10.0, -10.0, -10.0, -10.0, -10.0]                      # VEE 와 끝값이 같다(−10)
    C = dt.order_centroids(np.asarray([flat, VEE, UP]))
    np.testing.assert_allclose(C[0], VEE)                            # 둘째 값 −20 < −10
    np.testing.assert_allclose(C[1], flat)
    np.testing.assert_allclose(C[2], UP)


def test_labels_are_reassigned_from_the_stored_centroids():
    """이 자료에서 e-means 의 마지막 회차 라벨은 최종 중심의 배정과 9곳 다르다(이 기계에서 잰 값 — 계획 §5.0).
    전제는 시험하지 않는다(다른 기계의 BLAS 에서 달라질 수 있다) — 바른 구현이면 어디서나 통과한다."""
    rng = np.random.default_rng(26)
    X = rng.normal(0.0, 30.0, (300, 30)).cumsum(axis=1)
    model = dt.fit(X, 8)
    C = np.asarray([t["path"] for t in model["types"]])
    np.testing.assert_array_equal(np.asarray(model["labels"]) - 1, dt.assign(C, X))


def test_a_tie_goes_to_the_lower_type():
    C = np.asarray([[0.0, 0.0], [0.0, 0.0], [10.0, 10.0]])
    assert dt.assign(C, np.asarray([[0.0, 0.0], [9.0, 9.0]])).tolist() == [0, 2]


def test_the_emeans_loss_is_the_mean_squared_distance_to_the_assigned_centre():
    rng = np.random.default_rng(3)
    X = rng.normal(0.0, 25.0, (60, 6)).cumsum(axis=1)
    model = dt.fit(X, 4)
    C = np.asarray([t["path"] for t in model["types"]])
    labels = np.asarray(model["labels"]) - 1
    want = float(((X - C[labels]) ** 2).sum(axis=1).mean())
    assert model["loss"]["emeans"] == pytest.approx(want, rel=1e-9)


def test_the_lloyd_loss_comes_from_its_own_fit(monkeypatch):
    """e-means 가 엉뚱한 중심을 내도 Lloyd 의 손실은 제 적합에서 나온다(e-means 값을 옮겨 적지 않는다)."""
    sessions, _ = planted()
    got = dt.collect(days_of(unique_days(sessions)), minutes=5)
    monkeypatch.setattr(dt, "train_centroids", lambda X, k, seed: np.repeat(X[:1], k, axis=0).astype(np.float32))
    model = dt.fit(got.X, 4)
    assert model["loss"]["lloyd"] == pytest.approx(0.0, abs=1e-6)     # 심은 넷을 Lloyd 는 되찾는다
    assert model["loss"]["emeans"] > 100.0                            # 한 점에 모인 중심 — 손실이 크다
    assert model["loss"]["lloyd_starts"] == 10
    assert "높습니다" in model["loss"]["note"]


def test_equal_losses_are_said_to_be_equal():
    _, model, _ = fit_planted()
    assert model["loss"]["shown"]["emeans"] == model["loss"]["shown"]["lloyd"]
    assert "같습니다" in model["loss"]["note"]


def test_agreement_uses_four_other_seeds(monkeypatch):
    seen: list[int] = []
    real = dt.train_centroids

    def spy(X, k, seed):
        seen.append(seed)
        return real(X, k, seed)
    monkeypatch.setattr(dt, "train_centroids", spy)
    _, model, _ = fit_planted()
    assert seen == [1234, 1235, 1236, 1237, 1238]


def test_the_note_on_agreement_never_says_stable():
    _, same, _ = fit_planted()
    rng = np.random.default_rng(7)
    differs = dt.fit(rng.normal(0.0, 40.0, (120, 10)).cumsum(axis=1), 8)
    assert same["agreement"]["note"] == "난수 시드 다섯이 같은 배정을 냈습니다."
    assert differs["agreement"]["note"].startswith("난수 시드에 따라 배정이 달라집니다")
    for note in (same["agreement"]["note"], differs["agreement"]["note"]):
        assert "안정" not in note and "신뢰" not in note


def test_a_non_finite_centre_fails_loudly(monkeypatch):
    """중심에 NaN 이 섞이면 거리 · 번호가 조용히 틀어진다 — 학습 실패로 멈춘다(침묵 폴백 금지)."""
    sessions, _ = planted()
    got = dt.collect(days_of(unique_days(sessions)), minutes=5)
    monkeypatch.setattr(dt, "train_centroids", lambda X, k, seed: np.full((k, X.shape[1]), np.nan, dtype=np.float32))
    with pytest.raises(dt.DayTypeError) as err:
        dt.fit(got.X, 4)
    assert err.value.code == "train_failed"


def test_rounding_never_hides_a_disagreement():
    """배정 2,000 개 중 하나만 다르면 조정 랜드 지수는 1 에 아주 가깝다 — 그래도 '1.00' 으로 보이면 같은 배정처럼 읽힌다."""
    a = np.repeat(np.arange(4), 500)
    b = a.copy()
    b[0] = 1                                                         # 한 점만 다른 묶음으로
    block = dt._agreement_block(a, [b, a, a, a])
    assert block["same"] is False
    assert block["shown"][0] != "1.00" and "1.00" not in block["note"]
    assert float(block["shown"][0]) < 1.0
    assert dt._agreement_block(a, [a, a, a, a])["shown"] == ["1.00"] * 4   # 짝: 정말 같으면 두 자리 그대로


@pytest.mark.parametrize("emeans, lloyd, said", [
    (110.0, 100.0, "e-means 가 10.0% 높습니다."),
    (90.0, 100.0, "e-means 가 10.0% 낮습니다."),
    (100.04, 100.0, "표시 자리에서 같습니다."),
    (100.02, 100.04, "표시 자리에서 같습니다."),
    (100.02, 100.06, "e-means 가 0.1% 미만으로 낮습니다."),     # 보이는 글자는 100.0 · 100.1 로 다르다
    (100.1, 100.0, "e-means 가 0.1% 높습니다."),
    (12.0, 0.0, "e-means 가 높습니다."),
])
def test_the_loss_sentence_is_hand_checked(emeans, lloyd, said):
    block = dt._loss_block(emeans, lloyd)
    assert block["note"].endswith(said)
    assert block["shown"] == {"emeans": f"{emeans:,.1f}", "lloyd": f"{lloyd:,.1f}"}


def test_the_same_input_gives_the_same_centroids():
    rng = np.random.default_rng(5)
    X = rng.normal(0.0, 30.0, (80, 7)).cumsum(axis=1)
    a, b = dt.fit(X, 5), dt.fit(X, 5)
    assert [t["path"] for t in a["types"]] == [t["path"] for t in b["types"]]
    assert a["labels"] == b["labels"]


# ── 유형별 · 하한 · 범위 ─────────────────────────────────────────────────────────────────
def test_type_stats_count_days_and_spread():
    C = np.asarray([[0.0, 0.0], [10.0, 20.0], [50.0, 50.0]])
    X = np.asarray([[0.0, 0.0], [2.0, 0.0], [10.0, 20.0], [10.0, 20.0]])
    labels = dt.assign(C, X)
    stats = dt.type_stats(C, X, labels)
    assert [s["samples"] for s in stats] == [2, 2, 0]               # 표본이 없는 유형도 0 으로 싣는다
    assert [s["share"] for s in stats] == [0.5, 0.5, 0.0]
    assert stats[0]["spread"] == pytest.approx(1.0)                  # RMS: √((2² + 0 + 0 + 0) ÷ 4)
    assert stats[1]["spread"] == pytest.approx(0.0)
    assert stats[2]["spread"] is None                                # 표본이 없으면 흩어짐은 미상
    assert (stats[1]["end"], stats[1]["low"], stats[1]["high"]) == (20.0, 10.0, 20.0)


def test_too_few_samples_are_refused_before_training():
    rng = np.random.default_rng(2)
    X = rng.normal(0.0, 30.0, (19, 5))
    with pytest.raises(dt.DayTypeError) as err:
        dt.fit(X, 4)
    assert err.value.code == "too_few_samples"
    assert err.value.detail == {"samples": 19, "needed": 20, "k": 4}
    assert len(dt.fit(rng.normal(0.0, 30.0, (20, 5)), 4)["labels"]) == 20   # 짝: 5k 이면 학습한다


@pytest.mark.parametrize("minutes, k, code", [(4, 6, "bad_minutes"), (121, 6, "bad_minutes"), (30, 3, "bad_k"), (30, 17, "bad_k")])
def test_out_of_range_settings_are_refused(minutes, k, code):
    with pytest.raises(dt.DayTypeError) as err:
        dt.check_setting(minutes, k)
    assert err.value.code == code


@pytest.mark.parametrize("minutes, k", [(5, 4), (120, 16)])
def test_the_range_ends_are_accepted(minutes, k):
    dt.check_setting(minutes, k)


# ── 열쇠 ────────────────────────────────────────────────────────────────────────────────
def test_the_key_ignores_the_order_days_arrive_in():
    a = bp_day("2026-05-04", UP)
    b = bp_day("2026-05-05", DOWN, ticker="000660")
    one = dt.collect([Day("2026-05-04", {"005930": a}), Day("2026-05-05", {"000660": b})], minutes=5)
    two = dt.collect([Day("2026-05-05", {"000660": b}), Day("2026-05-04", {"005930": a})], minutes=5)
    assert dt.model_key(one, minutes=5, k=4) == dt.model_key(two, minutes=5, k=4)


def test_a_changed_bar_or_setting_changes_the_key():
    base = dt.collect(days_of([bp_day("2026-05-04", UP)]), minutes=5)
    moved = dt.collect(days_of([bp_day("2026-05-04", [10.0, 20.0, 30.0, 40.0, 51.0])]), minutes=5)
    key = dt.model_key(base, minutes=5, k=4)
    assert dt.model_key(moved, minutes=5, k=4) != key                # 봉이 바뀌면 다른 모형
    assert dt.model_key(base, minutes=5, k=5) != key
    assert dt.model_key(base, minutes=4, k=4) != key
    assert len(key) == 64


def test_planted_types_score_one_against_the_truth():
    got, model, truth = fit_planted()
    # 표본 순서(날 · 종목)로 다시 붙인 날이라 심은 순서와 같다
    assert adjusted_rand_score(truth, model["labels"]) == pytest.approx(1.0)
