"""하루 유형 비율 × 국면 — 순수 함수 `src.engine.regime_day_types.day_types_by_regime` (구현 계획 §7.3 · K2b).

거는 것: 손 계산(국면 둘 × 유형 셋 · 미상 날 둘(사유 · 지수에 없는 날) · 뺀 표본 · 모형의 학습 날과 겹친 표본) ·
국면들 + 미상 = 전체(표본 · 분류 · 유형별 수 · 표본 안 수 — 무작위 200) · 분류 0 인 묶음의 비율은 0% 가 아니라 `None` ↔ 짝: 분류가 있으면 0 인 유형은 0.0 ·
유형 번호가 1 ~ K 밖이면 지어내지 않고 거절 · 같은 날의 표본은 그날 국면 하나로 · 표본 순서와 무관.
"""
from __future__ import annotations

import random

import pytest

from src.engine import regime_day_types as rdt
from src.engine import regime_split as rs

NOT_FULL = "적합 창이 덜 찼습니다(필요 750 · 있음 700)."
D1, D2, D3, D4, D5 = "2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05", "2026-03-06"


def regime_rows() -> list[dict]:
    """국면 2개 — d1 · d3 은 1 · d2 는 2 · d4 는 확률이 없고(사유) · d5 는 지수 자료에 없다."""
    def row(d, p):
        top = max(range(len(p)), key=lambda i: p[i])
        return {"date": d, "probs": p, "top": top + 1, "top_prob": p[top], "reason": None}
    return [row(D1, [0.8, 0.2]), row(D2, [0.3, 0.7]), row(D3, [0.6, 0.4]),
            {"date": D4, "probs": None, "top": None, "top_prob": None, "reason": NOT_FULL}]


def samples() -> list[tuple]:
    return [(D1, "A", 1, None), (D1, "B", 2, None),
            (D2, "A", 3, None), (D2, "B", None, "short_window"),
            (D3, "A", 1, None), (D3, "B", 1, None),
            (D4, "A", 2, None),
            (D5, "B", 3, None)]


def cells(group: dict) -> list[tuple]:
    return [(t["type"], t["n"], t["in_sample"], t["share"]) for t in group["types"]]


def test_by_hand():
    out = rdt.day_types_by_regime(samples(), regime_rows(), k=2, types_k=3, train_days=[D1, D4])
    s1, s2 = out["states"]
    assert (s1["state"], s1["samples"], s1["classified"], s1["in_sample"]) == (1, 4, 4, 2)
    assert cells(s1) == [(1, 3, 1, pytest.approx(0.75)), (2, 1, 1, pytest.approx(0.25)), (3, 0, 0, 0.0)]
    assert s1["excluded"] == {}
    assert (s2["state"], s2["samples"], s2["classified"], s2["in_sample"]) == (2, 2, 1, 0)
    assert cells(s2) == [(1, 0, 0, 0.0), (2, 0, 0, 0.0), (3, 1, 0, 1.0)]
    assert s2["excluded"] == {"short_window": 1}
    u = out["unknown"]
    assert (u["samples"], u["classified"], u["in_sample"]) == (2, 2, 1)
    assert cells(u) == [(1, 0, 0, 0.0), (2, 1, 1, 0.5), (3, 1, 0, 0.5)]
    assert u["reasons"] == [{"reason": NOT_FULL, "days": 1, "samples": 1},
                            {"reason": rs.REASONS["no_index_day"], "days": 1, "samples": 1}]
    t = out["total"]
    assert (t["samples"], t["classified"], t["in_sample"]) == (8, 7, 3)
    assert cells(t) == [(1, 3, 1, pytest.approx(3 / 7)), (2, 2, 2, pytest.approx(2 / 7)), (3, 2, 0, pytest.approx(2 / 7))]
    assert t["excluded"] == {"short_window": 1}
    assert (out["types_k"], out["k"]) == (3, 2)


def test_a_group_with_samples_but_nothing_classified_has_no_shares_not_zero_percent():
    """날은 있으나 표본을 모두 뺀 국면 — 비율은 없음(`None`)이지 0% 가 아니다 ↔ 짝: 분류가 있는 국면의 0 인 유형은 0.0."""
    rows = [{"date": D1, "probs": [0.9, 0.1], "top": 1, "top_prob": 0.9, "reason": None},
            {"date": D2, "probs": [0.1, 0.9], "top": 2, "top_prob": 0.9, "reason": None}]
    got = [(D1, "A", None, "short_window"), (D2, "A", 2, None)]
    s1, s2 = rdt.day_types_by_regime(got, rows, k=2, types_k=2, train_days=[])["states"]
    assert (s1["samples"], s1["classified"]) == (1, 0) and [t["share"] for t in s1["types"]] == [None, None]
    assert [t["share"] for t in s2["types"]] == [0.0, 1.0]


def test_a_regime_with_no_samples_has_zero_counts_and_no_shares():
    out = rdt.day_types_by_regime(samples(), regime_rows(), k=3, types_k=3, train_days=[])
    s3 = out["states"][2]
    assert (s3["samples"], s3["classified"], s3["in_sample"]) == (0, 0, 0)
    assert [(t["n"], t["share"]) for t in s3["types"]] == [(0, None)] * 3


@pytest.mark.parametrize("bad", [0, 4, -1, True, 2.0])
def test_a_type_outside_the_model_is_refused_not_guessed(bad):
    got = samples()
    got[0] = (D1, "A", bad, None)
    with pytest.raises(ValueError, match="type_out_of_range"):
        rdt.day_types_by_regime(got, regime_rows(), k=2, types_k=3, train_days=[])


def test_a_regime_number_outside_k_is_refused():
    rows = regime_rows()
    rows[0] = {**rows[0], "top": 3}
    with pytest.raises(ValueError, match="state_out_of_range"):
        rdt.day_types_by_regime(samples(), rows, k=2, types_k=3, train_days=[])


def test_the_order_of_samples_does_not_matter():
    got = samples()
    shuffled = list(reversed(got))
    a = rdt.day_types_by_regime(got, regime_rows(), k=2, types_k=3, train_days=[D1, D4])
    b = rdt.day_types_by_regime(shuffled, regime_rows(), k=2, types_k=3, train_days=[D1, D4])
    assert a == b


def test_in_sample_is_the_model_training_days_not_anything_else():
    """표본 안 = 그 표본의 날이 모형의 학습 날 — 학습 날이 없으면 0 ↔ 짝: 모든 날이면 분류된 표본 전부."""
    none = rdt.day_types_by_regime(samples(), regime_rows(), k=2, types_k=3, train_days=[])
    every = rdt.day_types_by_regime(samples(), regime_rows(), k=2, types_k=3, train_days=[D1, D2, D3, D4, D5])
    assert none["total"]["in_sample"] == 0 and every["total"]["in_sample"] == every["total"]["classified"] == 7


def test_the_parts_always_add_up_to_the_whole():
    """국면들 + 미상 = 전체(표본 · 분류 · 표본 안 · 유형별 수 · 뺀 사유) — 무작위 200."""
    rng = random.Random(7)
    for _ in range(200):
        k, types_k = rng.randint(2, 4), rng.randint(4, 8)
        days = [f"2026-05-{i + 1:02d}" for i in range(rng.randint(1, 20))]
        rows = []
        for d in days:
            roll = rng.random()
            if roll < 0.1:
                continue
            if roll < 0.2:
                rows.append({"date": d, "probs": None, "top": None, "top_prob": None, "reason": "사유"})
                continue
            raw = [rng.random() for _ in range(k)]
            p = [x / sum(raw) for x in raw]
            top = max(range(k), key=lambda i: p[i])
            rows.append({"date": d, "probs": p, "top": top + 1, "top_prob": p[top], "reason": None})
        got = []
        for d in days:
            for tk in ("A", "B", "C")[: rng.randint(1, 3)]:
                got.append((d, tk, None, "short_window") if rng.random() < 0.15 else (d, tk, rng.randint(1, types_k), None))
        train = [d for d in days if rng.random() < 0.3]
        out = rdt.day_types_by_regime(got, rows, k=k, types_k=types_k, train_days=train)
        groups = [*out["states"], out["unknown"]]
        for key in ("samples", "classified", "in_sample"):
            assert sum(g[key] for g in groups) == out["total"][key]
        assert out["total"]["samples"] == len(got)
        assert out["total"]["classified"] == sum(1 for s in got if s[2] is not None)
        for j in range(types_k):
            assert sum(g["types"][j]["n"] for g in groups) == out["total"]["types"][j]["n"]
            assert sum(g["types"][j]["in_sample"] for g in groups) == out["total"]["types"][j]["in_sample"]
        for g in [*groups, out["total"]]:
            assert sum(t["n"] for t in g["types"]) == g["classified"]
            if g["classified"]:
                assert sum(t["share"] for t in g["types"]) == pytest.approx(1.0)
        assert sum(r["samples"] for r in out["unknown"]["reasons"]) == out["unknown"]["samples"]


def test_an_excluded_sample_without_a_reason_is_refused_not_counted_as_nothing():
    """유형이 없는 표본은 뺀 사유가 있어야 한다 — 사유 없이 오면 지어내지 않고 거절(빈 사유의 묶음을 만들지 않는다)."""
    got = samples()
    got[3] = (D2, "B", None, None)
    with pytest.raises(ValueError, match="excluded_without_reason"):
        rdt.day_types_by_regime(got, regime_rows(), k=2, types_k=3, train_days=[])
