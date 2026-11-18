"""하루 유형 비중(K5) — 구현 계획 §7.6 · 설계 §6.

거는 것: 손 계산(창을 줄여 산수) · 풀링 ↔ 날마다 비율의 평균 · 앞보기 0(t 의 값은 t 까지의 날만 — 그 뒤 날을 바꿔도 불변) ·
미상 전파와 사유의 순서(세지 않은 날이 먼저 — 이어 세면 풀린다) · 고르기 검사(빈 · 범위 밖 · 전부 · 중복) · 어긋난 세기 거절.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from src.engine import day_type_share as ds


def day(by_type: dict[int, int], classified: int | None = None) -> dict:
    by = {int(t): int(n) for t, n in by_type.items()}
    return {"by_type": by, "classified": sum(by.values()) if classified is None else classified}


DATES = [f"2024-01-{i:02d}" for i in range(1, 11)]


# ── 손 계산 ──────────────────────────────────────────────────────────────────────────
def test_the_pooled_share_by_hand_with_a_short_window():
    counts = {DATES[0]: day({1: 1, 2: 1}), DATES[1]: day({2: 2}), DATES[2]: day({1: 3, 2: 1}), DATES[3]: day({2: 4})}
    vals, why, n = ds.window_share(DATES[:4], counts, (1,), window=3)
    assert math.isnan(vals[0]) and math.isnan(vals[1]) and why[:2] == ["short", "short"]
    assert vals[2] == pytest.approx((1 + 0 + 3) / (2 + 2 + 4))            # 0.5
    assert vals[3] == pytest.approx((0 + 3 + 0) / (2 + 4 + 4))            # 0.3
    assert why[2:] == [None, None] and list(n) == [0, 0, 8, 10]           # 창의 분류된 표본 수(미상 창은 0)


def test_pooling_is_not_the_mean_of_daily_shares():
    """표본이 적은 날이 같은 무게를 갖지 않는다 — 위 창 [1, 3] 의 날마다 비율 0 · 0.75 · 0 의 평균은 0.25, 풀링은 0.3."""
    counts = {DATES[0]: day({1: 1, 2: 1}), DATES[1]: day({2: 2}), DATES[2]: day({1: 3, 2: 1}), DATES[3]: day({2: 4})}
    vals, _, _ = ds.window_share(DATES[:4], counts, (1,), window=3)
    assert vals[3] == pytest.approx(0.3) and vals[3] != pytest.approx(0.25)


def test_several_types_are_summed_into_one_share():
    counts = {d: day({1: 1, 2: 2, 3: 3, 4: 4}) for d in DATES[:3]}
    one, _, _ = ds.window_share(DATES[:3], counts, (3,), window=3)
    two, _, _ = ds.window_share(DATES[:3], counts, (1, 3), window=3)
    assert one[2] == pytest.approx(3 / 10) and two[2] == pytest.approx(4 / 10)


def test_the_default_window_is_twenty_trading_days():
    counts = {d: day({1: 1, 2: 1}) for d in DATES}
    dates = [f"2024-02-{i:02d}" for i in range(1, 22)] + DATES        # 31개 — 앞 21개도 세어 둔다
    counts.update({d: day({1: 1, 2: 1}) for d in dates})
    vals, why, _ = ds.window_share(dates, counts, (1,))
    assert ds.WINDOW == 20
    assert all(w == "short" for w in why[:19]) and why[19] is None and vals[19] == pytest.approx(0.5)


# ── 앞보기 0 ──────────────────────────────────────────────────────────────────────────
def test_a_windows_value_sees_no_day_after_it():
    rng = np.random.default_rng(3)
    counts = {d: day({1: int(rng.integers(0, 5)), 2: int(rng.integers(1, 5))}) for d in DATES}
    base, _, _ = ds.window_share(DATES, counts, (1,), window=3)
    for cut in range(len(DATES)):
        moved = dict(counts)
        for d in DATES[cut + 1:]:
            moved[d] = day({1: 9, 2: 0})
        again, _, _ = ds.window_share(DATES, moved, (1,), window=3)
        assert np.array_equal(again[:cut + 1], base[:cut + 1], equal_nan=True), cut
    # 짝 — 그날을 바꾸면 그날의 값이 바뀐다(창에 그날이 든다 · 국면은 이 값을 다음 날에 쓴다)
    moved = {**counts, DATES[5]: day({1: 9, 2: 0})}
    again, _, _ = ds.window_share(DATES, moved, (1,), window=3)
    assert again[5] != base[5]


# ── 미상 ────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("bad, code", [(None, "not_counted"), ({"missing": "no_bars"}, "no_bars"),
                                       ({"missing": "unreadable"}, "unreadable"),
                                       (day({}, classified=0), "no_samples")])
def test_one_unknown_day_leaves_every_window_that_holds_it_unknown(bad, code):
    counts = {d: day({1: 1, 2: 1}) for d in DATES}
    counts[DATES[4]] = bad
    vals, why, n = ds.window_share(DATES, counts, (1,), window=3)
    for t in range(len(DATES)):
        holds = 4 <= t <= 6
        if t < 2:
            continue
        assert math.isnan(vals[t]) is holds and (why[t] == code) is holds, t
        assert bool(n[t] == 0) is holds                                   # 미상 창은 표본 수도 0(지어내지 않는다)


def test_a_day_missing_from_the_counts_is_not_counted():
    counts = {d: day({1: 1, 2: 1}) for d in DATES if d != DATES[6]}
    _, why, _ = ds.window_share(DATES, counts, (1,), window=3)
    assert why[6] == why[7] == why[8] == "not_counted"


def test_the_reason_order_puts_not_counted_first():
    """창에 세지 않은 날과 분봉 없는 날이 함께 있으면 '세지 않은 날' — 이어 세면 풀리는 쪽을 먼저 말한다."""
    counts = {d: day({1: 1, 2: 1}) for d in DATES}
    counts[DATES[3]], counts[DATES[4]], counts[DATES[5]] = {"missing": "no_bars"}, None, day({}, classified=0)
    _, why, _ = ds.window_share(DATES, counts, (1,), window=3)
    assert why[5] == "not_counted" and why[3] == "no_bars" and why[7] == "no_samples"


def test_an_unreadable_file_is_named_before_a_day_without_bars():
    """읽지 못한 파일은 '분봉 없음'이 아니다(미상 ≠ 없음) — 둘이 한 창에 있으면 읽지 못한 쪽을 먼저 말한다."""
    counts = {d: day({1: 1, 2: 1}) for d in DATES}
    counts[DATES[3]], counts[DATES[4]] = {"missing": "no_bars"}, {"missing": "unreadable"}
    _, why, _ = ds.window_share(DATES, counts, (1,), window=3)
    assert why[3] == "no_bars" and why[4] == why[5] == "unreadable" and why[6] == "unreadable"


def test_every_reason_has_a_sentence():
    assert set(ds.REASONS) == {"short", "not_counted", "unreadable", "no_bars", "no_samples"}
    assert all(s.endswith(("다.", "다).")) for s in ds.REASONS.values())   # 합니다체 문장(괄호 풀이가 끝에 붙을 수 있다)
    assert "읽지 못" in ds.REASONS["unreadable"] and "없다는 뜻이 아닙니다" in ds.REASONS["unreadable"]


# ── 바구니의 하루 셈(종목마다의 유형 · 사유 → 그날의 셈) ─────────────────────────────────────────
def test_a_basket_day_pools_the_labels_of_its_tickers():
    got = ds.basket_day([(1, None), (3, None), (1, None)])
    assert got == {"by_type": {1: 2, 3: 1}, "classified": 3, "excluded": {}}


def test_a_basket_day_with_a_ticker_not_counted_is_not_counted():
    assert ds.basket_day([(1, None), None]) is None
    assert ds.basket_day([None, (None, "no_bars")]) is None


def test_some_tickers_without_a_type_leave_the_rest_pooled_and_the_exclusions_counted():
    """바구니의 일부만 유형을 정한 날은 정한 표본만 센다(풀링의 분모) — 뺀 표본은 사유별로 남긴다(조용히 버리지 않는다)."""
    got = ds.basket_day([(2, None), (None, "short_window"), (None, "no_bars")])
    assert got == {"by_type": {2: 1}, "classified": 1, "excluded": {"short_window": 1, "no_bars": 1}}


@pytest.mark.parametrize("missing", ["not_loaded", "no_bars", "synthetic_rows_blocked"])
def test_a_ticker_without_bars_next_to_a_typed_one_leaves_the_day_pooled(missing):
    """봉이 없는 종목이 있어도 유형을 정한 종목이 있으면 그날은 '분봉 없는 날'이 아니다 — 정한 표본만 센다(바구니 전부에 봉이 없을 때만 분봉 없는 날).
    변이('나머지가 모두 봉 없음이면 분봉 없는 날로')가 살아남아 더한 시험이다(위 시험은 봉 없는 종목 곁에 창을 못 쓴 종목이 있어 그 변이를 못 갈랐다)."""
    got = ds.basket_day([(2, None), (None, missing)])
    assert got == {"by_type": {2: 1}, "classified": 1, "excluded": {missing: 1}}


@pytest.mark.parametrize("reasons", [["not_loaded", "not_loaded"], ["synthetic_rows_blocked"] * 2, ["no_bars", "not_loaded"]])
def test_a_basket_day_without_any_bars_is_a_day_without_bars(reasons):
    assert ds.basket_day([(None, r) for r in reasons]) == {"missing": "no_bars"}


def test_a_basket_day_whose_file_was_unreadable_is_unreadable_not_empty():
    assert ds.basket_day([(None, "unreadable"), (None, "unreadable")]) == {"missing": "unreadable"}


def test_bars_without_a_usable_window_are_no_samples_not_no_bars():
    """짝 — 봉은 있었으나 장 시작 구간을 못 쓴 종목이 하나라도 있으면 '분봉 없음'이 아니라 '표본 없음'이다."""
    got = ds.basket_day([(None, "short_window"), (None, "no_bars")])
    assert got == {"by_type": {}, "classified": 0, "excluded": {"short_window": 1, "no_bars": 1}}
    vals, why, _ = ds.window_share(DATES[:1], {DATES[0]: got}, (1,), window=1)
    assert math.isnan(vals[0]) and why == ["no_samples"]


@pytest.mark.parametrize("bad", [[(1, "no_bars")], [(None, None)], [(0, None)], [(True, None)], [(1.5, None)], [], [(None, "")]])
def test_an_inconsistent_basket_row_is_refused(bad):
    with pytest.raises(ValueError):
        ds.basket_day(bad)


# ── 고르기 · 어긋난 세기 ────────────────────────────────────────────────────────────────
def test_the_types_are_checked_and_sorted():
    assert ds.check_types([3, 1], k=4) == (1, 3)
    assert ds.check_types([2], k=2) == (2,)


@pytest.mark.parametrize("types, k, code", [([], 4, "no_types"), ([0], 4, "type_out_of_range"), ([5], 4, "type_out_of_range"),
                                            ([1, 2, 3, 4], 4, "all_types"), ([2, 2], 4, "duplicate_types"),
                                            ([True], 4, "type_out_of_range")])
def test_a_bad_choice_of_types_is_refused(types, k, code):
    with pytest.raises(ds.ShareError) as err:
        ds.check_types(types, k=k)
    assert err.value.code == code and str(err.value) == ds.REFUSALS[code]


@pytest.mark.parametrize("bad", [{"by_type": {1: 3}, "classified": 2}, {"by_type": {1: -1}, "classified": 0},
                                 {"by_type": {1: 1}, "classified": -1}, {"missing": "something_else"}])
def test_inconsistent_counts_are_refused_not_used(bad):
    counts = {d: day({1: 1, 2: 1}) for d in DATES}
    counts[DATES[2]] = bad
    with pytest.raises(ValueError):
        ds.window_share(DATES, counts, (1,), window=3)
