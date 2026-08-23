"""regime_transitions — 전이 위험을 베이지안으로, 그리고 모르는 것은 모른다고 (A8).

★이 파일이 지키는 것★
1. 사후평균 행 합 = 1, 신용구간이 평균을 포함한다.
2. **표본이 얇은 행은 구간이 더 넓다** — 수축이 실제로 작동하는지. 이것이
   경험적 MLE 대신 Dirichlet 을 쓴 이유 전부다.
3. 관측이 없는 행은 `shrunk: True` + 사유. 사전분포를 데이터인 척 하지 않는다.
4. **`span` 이 요청보다 짧으면 그 사실이 응답에 있다** — 화면이 "10년" 이라고
   쓰지 못하게 막는 필드다. 이 저장소의 매크로 시계열은 실측 60개월뿐이다.
5. 한쪽 축만 계산된 달은 국면을 찍지 않고 버린다(반대 축을 0 으로 오해 금지).
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402

from src.engine.regime_transitions import (  # noqa: E402
    MIN_ROW_OBS,
    REGIMES,
    count_transitions,
    current_run_length,
    k_step_forecast,
    regime_occupancy,
    regime_path,
    regime_transitions,
    transition_posterior,
)


class _S:
    def __init__(self, values, timestamps=None):
        self.values = values
        self.timestamps = timestamps or []


def _series(n: int = 90) -> dict:
    import math
    g, c = [], []
    for i in range(n):
        cyc = 3.0 * math.sin(i / 9.0)
        g.append(100 * (1 + (0.02 * i + cyc) / 100))
        c.append(100 * (1 + (0.015 * i - cyc * 0.7) / 100))
    ts = [f"20{18 + i // 12:02d}-{i % 12 + 1:02d}" for i in range(n)]
    return {
        "KR_LEADING_CYCLE": _S([x / 100 for x in g], ts),
        "KR_IP": _S(g, ts), "KOSPI": _S(g, ts), "KR_CPI": _S(c, ts),
        "T10YIE": _S([2 + 0.4 * math.sin(i / 7.0) for i in range(n)], ts),
    }


# ── 사후분포의 기본 성질 ──────────────────────────────────────────────────────
def test_posterior_rows_are_probability_distributions():
    counts = [[20, 2, 1, 3], [3, 9, 1, 1], [1, 2, 11, 2], [4, 1, 2, 7]]
    rows = transition_posterior(counts)
    assert len(rows) == 4
    for row in rows:
        total = sum(row["mean"].values())
        # 허용오차는 **반올림에서 유도한 값**이다: 6자리 반올림은 항목당 최대 5e-7 의
        # 오차를 갖고 항목이 4개이므로 합의 오차 한계는 2e-6 이다. 통과할 때까지
        # 느슨하게 만든 숫자가 아니다. (4자리로 냈을 때는 합이 0.9999 였고, 그때는
        # 테스트를 늘리는 대신 엔진의 정밀도를 올렸다 — 불변식은 공개된 값에서
        # 성립해야 하고 화면이 그 값을 그대로 더하기 때문이다.)
        assert total == pytest.approx(1.0, abs=5e-6), row
        for regime, m in row["mean"].items():
            lo, hi = row["ci90"][regime]
            assert lo <= m <= hi, f"{row['from']}→{regime}: 구간이 평균을 포함하지 않는다"
            assert 0.0 <= lo <= hi <= 1.0


def test_thin_row_has_a_wider_interval_than_a_thick_row():
    """★수축이 실제로 작동하는가 — 이 테스트가 Dirichlet 을 쓴 이유다★

    관측이 많은 행은 구간이 좁고, 없는 행은 넓어야 한다. 경험적 MLE 라면 관측
    1개짜리 행이 100% 라는 **좁은 확신**을 내놓는다. 그게 이 화면에서 가장
    위험한 숫자다.
    """
    counts = [[60, 2, 1, 2],      # 두꺼운 행
              [0, 0, 0, 0],       # 관측 없음
              [1, 0, 0, 0],       # 거의 없음
              [10, 3, 2, 5]]
    rows = transition_posterior(counts)
    width = lambda r, j: r["ci90"][REGIMES[j]][1] - r["ci90"][REGIMES[j]][0]  # noqa: E731

    thick = width(rows[0], 0)
    empty = width(rows[1], 1)
    assert empty > thick, (
        f"관측 없는 행의 구간({empty:.3f})이 두꺼운 행({thick:.3f})보다 넓지 않다 — "
        "수축이 작동하지 않는다")


def test_row_without_observations_says_so_instead_of_pretending():
    """★사전분포를 데이터인 척 하지 않는다★"""
    counts = [[0, 0, 0, 0], [30, 2, 1, 2], [0, 0, 0, 0], [0, 0, 0, 0]]
    rows = transition_posterior(counts)

    empty = rows[0]
    assert empty["n"] == 0
    assert empty["shrunk"] is True
    assert empty["reason"], "관측이 0인데 사유가 없다"
    assert str(MIN_ROW_OBS) in empty["reason"] or "0개" in empty["reason"]

    thick = rows[1]
    assert thick["n"] == 35
    assert thick["shrunk"] is False
    assert thick["reason"] is None


def test_single_observation_does_not_become_a_100_percent_point_estimate():
    """★수축이 **실제로 일어나는지**를 재는 유일한 테스트★

    변이 프로브가 이 구멍을 알려 줬다. α 를 0 으로 되돌려 MLE 로 만들었더니 기존
    가드가 전부 초록이었다 — `shrunk` 플래그는 `n < MIN_ROW_OBS` 라는 **개수**만
    보므로 사전분포가 실제로 값을 당겼는지와 무관하게 True 였고, 구간 비교 테스트도
    통과했다. 즉 "관측 1개짜리 행이 100% 를 주장한다" 는 이 설계가 막으려던 바로 그
    상황을 아무도 지키지 않고 있었다.

    관측 [1,0,0,0] 이면 MLE 는 대각 1.0 · 나머지 0.0 을 내놓는다. Dirichlet 사후는
    (4+1)/(7+1) = 0.625 로 당겨지고 나머지도 1/8 = 0.125 씩 남는다. 그 차이를 잰다.
    """
    counts = [[1, 0, 0, 0], [30, 2, 1, 2], [0, 0, 0, 0], [0, 0, 0, 0]]
    row = transition_posterior(counts)[0]

    diag = row["mean"]["Goldilocks"]
    assert diag < 0.9, (
        f"관측 1개로 대각이 {diag:.3f} 다 — 사전분포로 수축하지 않고 MLE 점추정을 "
        "내놓고 있다. 이것이 이 화면에서 가장 위험한 숫자다")
    assert diag == pytest.approx(5 / 8, abs=1e-3), diag

    # 관측이 0인 칸도 0 이 아니라 사전분포의 몫을 갖는다 — "본 적 없다" 가
    # "일어날 수 없다" 로 둔갑하지 않는다.
    for other in ("Reflation", "Stagflation", "Disinflation"):
        assert row["mean"][other] > 0.02, (
            f"{other} 로의 전이가 {row['mean'][other]} 다 — 관측이 없다는 이유로 "
            "불가능으로 단정했다")


def test_expected_duration_matches_the_diagonal():
    """기대 지속기간 = 1/(1−p_ii). 대각과 어긋나면 둘 중 하나가 틀린 것이다."""
    counts = [[30, 1, 1, 1], [2, 20, 1, 1], [1, 1, 15, 1], [1, 1, 1, 10]]
    for row in transition_posterior(counts):
        p_stay = row["mean"][row["from"]]
        assert row["expected_duration_months"] == pytest.approx(
            1.0 / (1.0 - p_stay), abs=0.05), row


# ── 경로·구간 정직성 ─────────────────────────────────────────────────────────
def test_span_reports_the_truth_when_data_is_shorter_than_requested():
    """★요청보다 짧으면 응답이 그 사실을 말한다★

    화면이 "최근 10년" 이라고 쓰려면 실제로 120개월이 있어야 한다. 이 저장소의
    매크로 시계열은 실측 60개월이라 그렇게 쓸 수 없고, 그걸 막는 것이 이 필드다.
    """
    r = regime_path(_series(90), "kr", months=200)
    span = r["span"]
    assert span["requested"] == 200
    assert span["n_months"] == len(r["points"])
    assert span["n_months"] < 200
    assert span["truncated"] is True

    # 넉넉한 표본에서는 truncated 가 아니어야 한다 (가드가 항상 True 면 무의미).
    r2 = regime_path(_series(90), "kr", months=24)
    assert r2["span"]["truncated"] is False, r2["span"]
    assert r2["span"]["n_months"] == 24


def test_months_with_only_one_axis_are_dropped_not_guessed():
    """★한쪽 축만 있는 달을 0 으로 찍지 않는다★

    물가 지표만 주면 성장축은 성분이 없어 score 0.0 이 된다. 그 0 을 그대로 쓰면
    `quadrant(0, i)` 가 "성장 ≥ 0" 으로 읽혀 Goldilocks/Reflation 으로 **찍힌다**.
    계산되지 않은 축을 중립값으로 오해하는 것이고, 그 라벨로 전이를 세면 행렬이
    통째로 오염된다.
    """
    only_inflation = {k: v for k, v in _series(90).items() if k in ("KR_CPI", "T10YIE")}
    r = regime_path(only_inflation, "kr", months=36)
    assert r["points"] == [], "성장축이 없는데 국면을 찍었다"
    assert r["span"]["dropped_incomplete"] == 36


def test_too_few_classifiable_months_is_unavailable_with_a_reason():
    r = regime_transitions({}, "kr", months=36)
    assert r["available"] is False
    assert r["reason"]
    assert "rows" not in r, "미가용인데 전이행렬을 만들었다"


# ── 카운트·경로 보조 ─────────────────────────────────────────────────────────
def test_transition_counts_are_consecutive_pairs():
    pts = [{"regime": r} for r in
           ["Goldilocks", "Goldilocks", "Reflation", "Reflation", "Goldilocks"]]
    counts = count_transitions(pts)
    gi, ri = REGIMES.index("Goldilocks"), REGIMES.index("Reflation")
    assert counts[gi][gi] == 1
    assert counts[gi][ri] == 1
    assert counts[ri][ri] == 1
    assert counts[ri][gi] == 1
    assert sum(sum(r) for r in counts) == len(pts) - 1


def test_run_length_and_occupancy():
    pts = [{"regime": r} for r in
           ["Reflation", "Goldilocks", "Goldilocks", "Goldilocks"]]
    assert current_run_length(pts) == 3
    occ = regime_occupancy(pts)
    assert occ["Goldilocks"] == pytest.approx(0.75)
    assert occ["Reflation"] == pytest.approx(0.25)
    assert sum(occ.values()) == pytest.approx(1.0)


# ── k-step 사후예측 ──────────────────────────────────────────────────────────
def test_forecast_is_a_distribution_and_k1_matches_the_matrix_row():
    """k=1 사후예측의 평균은 그 행의 사후평균과 같아야 한다 (Dirichlet 평균의 선형성)."""
    counts = [[30, 3, 2, 3], [2, 12, 1, 1], [1, 2, 14, 1], [3, 1, 1, 9]]
    rows = transition_posterior(counts)
    f = k_step_forecast(rows, "Goldilocks", k=1, draws=3000)
    assert f["available"] is True
    assert sum(f["mean"].values()) == pytest.approx(1.0, abs=1e-6)

    row0 = rows[REGIMES.index("Goldilocks")]
    for regime in REGIMES:
        assert f["mean"][regime] == pytest.approx(row0["mean"][regime], abs=0.02), (
            f"k=1 예측이 전이행렬 행과 다르다: {regime}")


def test_forecast_is_reproducible():
    """시드가 고정돼 있으므로 같은 입력이면 같은 그림이 나와야 한다."""
    counts = [[20, 2, 2, 2], [2, 10, 1, 1], [1, 1, 9, 1], [2, 1, 1, 8]]
    rows = transition_posterior(counts)
    a = k_step_forecast(rows, "Goldilocks", k=3, draws=1500)
    b = k_step_forecast(rows, "Goldilocks", k=3, draws=1500)
    assert a["mean"] == b["mean"]


def test_forecast_rejects_unknown_regime_and_bad_horizon():
    rows = transition_posterior([[10, 1, 1, 1]] * 4)
    assert k_step_forecast(rows, "없는국면", k=3)["available"] is False
    assert k_step_forecast(rows, "Goldilocks", k=0)["available"] is False


# ── 통합 ─────────────────────────────────────────────────────────────────────
def test_end_to_end_shape():
    r = regime_transitions(_series(90), "kr", months=60, forecast_k=3)
    assert r["available"] is True, r.get("reason")
    assert set(r["regimes"]) == set(REGIMES)
    assert len(r["rows"]) == 4
    assert r["current"] in REGIMES
    assert r["run_length_months"] >= 1
    assert r["n_transitions"] == max(0, r["span"]["n_months"] - 1)
    assert r["forecast"]["available"] is True
    assert r["span"]["n_months"] == len(r["path"])
