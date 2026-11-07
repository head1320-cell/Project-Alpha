"""국면 예측의 **실측 적중률** (P4-M2).

왜 이 파일이 있는가
------------------------------------------------------------------------------
A8 의 `k_step_forecast` 는 이미 k개월 뒤 국면 분포와 신용구간을 낸다. 그런데
"90% 구간" 이라고 적혀 있을 뿐 **그 구간이 실제로 90% 를 맞히는지는 아무도 재지
않았다.** 유한표본에서 베이지안 신용구간은 목표를 밑돌 수 있고, 그 사실은 재 봐야만
알 수 있다.

★적중률은 주장이 아니라 실측이다★ M1-T 가 conformal 에 세운 원칙 그대로다.
`1-α` 를 그대로 적으면 그건 이론값을 실측인 척하는 것이다.

방법 — 범주형이라 구간이 아니라 **예측집합**이다:
    각 시점 t 에서 t 까지의 경로만으로 사후를 세우고 k개월 뒤를 예측한 뒤,
    확률 높은 순으로 담아 질량 1-α 를 덮는 **최소 집합**을 만든다.
    그 집합이 실현 국면을 담았는지 세면 그것이 적중률이다.
    (walk-forward 라 미래를 쓰지 않는다 — 이게 없으면 적중률이 부풀려진다.)
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.engine.regime_forecast import (  # noqa: E402
    MIN_EVAL_POINTS,
    forecast_coverage,
    prediction_set,
)


def _persistent_path(n: int = 120) -> list[str]:
    """★거의 안 바뀌는 경로★ — 예측이 쉬우므로 집합이 작아야 한다."""
    out: list[str] = []
    for i in range(n):
        out.append("Goldilocks" if (i // 30) % 2 == 0 else "Stagflation")
    return out


def _churning_path(n: int = 120) -> list[str]:
    """짝 — 매달 도는 경로. 예측이 어려우므로 집합이 커야 한다."""
    reg = ["Goldilocks", "Reflation", "Stagflation", "Disinflation"]
    return [reg[i % 4] for i in range(n)]


# ─────────────────────────────────────────────────────────────────────────────
# 1. 예측집합 — 질량을 덮되 필요 이상으로 크지 않다
# ─────────────────────────────────────────────────────────────────────────────
def test_the_prediction_set_covers_the_target_mass():
    probs = {"Goldilocks": 0.55, "Reflation": 0.30, "Stagflation": 0.10,
             "Disinflation": 0.05}
    s = prediction_set(probs, alpha=0.1)
    assert sum(probs[r] for r in s) >= 0.9 - 1e-9


def test_the_prediction_set_is_the_smallest_one_that_does():
    """★짝★ 없으면 항상 4개 국면을 다 담아도 위 테스트가 통과한다.

    전부 담는 집합은 100% 적중하지만 아무것도 말하지 않는다.
    """
    probs = {"Goldilocks": 0.55, "Reflation": 0.30, "Stagflation": 0.10,
             "Disinflation": 0.05}
    s = prediction_set(probs, alpha=0.1)
    assert set(s) == {"Goldilocks", "Reflation", "Stagflation"}
    assert len(s) == 3


def test_a_confident_forecast_yields_a_single_regime_set():
    probs = {"Goldilocks": 0.95, "Reflation": 0.03, "Stagflation": 0.01,
             "Disinflation": 0.01}
    assert prediction_set(probs, alpha=0.1) == ["Goldilocks"]


# ─────────────────────────────────────────────────────────────────────────────
# 2. ★적중률은 실측이다 — 1-α 를 베끼지 않는다★
# ─────────────────────────────────────────────────────────────────────────────
def test_coverage_is_measured_and_reported_separately_from_the_target():
    """목표와 실측을 **다른 필드**로 낸다. 같은 자리에 넣으면 구분이 사라진다."""
    out = forecast_coverage(_persistent_path(), k=1, alpha=0.1)
    assert out["available"] is True, out.get("reason")
    assert out["target"] == 0.9
    assert 0.0 <= out["coverage"] <= 1.0
    assert out["hits"] + out["misses"] == out["n_eval"]
    assert out["coverage"] == out["hits"] / out["n_eval"]


def test_coverage_actually_differs_from_the_target_on_a_hard_path():
    """★짝 — 실측이 늘 1-α 로 나오면 그건 베낀 것이다★

    두 경로의 실측이 서로 달라야 "재고 있다" 가 증명된다.
    """
    easy = forecast_coverage(_persistent_path(), k=1, alpha=0.1)
    hard = forecast_coverage(_churning_path(), k=1, alpha=0.1)
    assert easy["available"] and hard["available"]
    assert easy["coverage"] != hard["coverage"] or \
        easy["mean_set_size"] != hard["mean_set_size"], \
        "쉬운 경로와 어려운 경로가 같은 값을 낸다 — 실측이 아니다"


def test_the_easy_path_needs_smaller_sets_than_the_churning_one():
    """예측집합 크기가 난이도를 반영한다 — 적중률만 보면 크기를 숨길 수 있다."""
    easy = forecast_coverage(_persistent_path(), k=1, alpha=0.1)
    hard = forecast_coverage(_churning_path(), k=1, alpha=0.1)
    assert easy["mean_set_size"] < hard["mean_set_size"]


def test_the_evaluation_is_walk_forward_and_says_so():
    """미래를 쓰면 적중률이 부풀려진다 — 그 사실을 응답이 밝힌다."""
    out = forecast_coverage(_persistent_path(), k=1, alpha=0.1)
    assert out["walk_forward"] is True
    assert out["note"]


# ─────────────────────────────────────────────────────────────────────────────
# 3. 표본이 모자라면 숫자를 내지 않는다
# ─────────────────────────────────────────────────────────────────────────────
def test_a_short_path_is_refused_with_a_reason_not_a_number():
    out = forecast_coverage(_persistent_path(n=MIN_EVAL_POINTS), k=1, alpha=0.1)
    assert out["available"] is False
    assert out["reason"]
    assert "coverage" not in out


def test_a_long_horizon_that_leaves_no_evaluation_points_is_refused():
    """짝 — k 가 커지면 평가 가능한 시점이 줄어든다. 0개가 되면 거부한다."""
    out = forecast_coverage(_persistent_path(n=80), k=200, alpha=0.1)
    assert out["available"] is False
    assert out["reason"]
