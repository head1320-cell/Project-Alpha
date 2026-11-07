"""중립화 + 슬리브 결합 + 슬리브 분석 검증 (Full Expansion P3 잔여)

핵심 주장(지시서 §8):
  · 베타중립 결과가 목표 베타를 허용오차 내로 달성.
  · 섹터중립 결과가 섹터별 목표 비중을 허용오차 내로 달성.
  · 페어/스프레드가 베타중립(net beta≈0).
  · 슬리브 결합 2단계 — 슬리브 배분 × 종목비중, 합=100%.
  · 리스크 예산 — 예산 큰 슬리브가 더 큰 배분/리스크 기여.
  · 슬리브 간 상관·군집·리스크 기여·꼬리의존 계산 가능.
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from src.engine.neutralize import (  # noqa: E402
    beta_neutralize,
    neutralize_portfolio,
    pair_spread,
    sector_neutralize,
)
from src.engine.sleeve_combine import combine_sleeves, sleeve_analytics  # noqa: E402


# ── 중립화 ────────────────────────────────────────────────────────────────────
def test_beta_neutral_hits_target_within_tolerance():
    w = {"A": 40, "B": 30, "C": 30}
    betas = {"A": 1.4, "B": 1.0, "C": 0.6}
    # 달러중립(롱숏 허용) → 베타 정확히 0
    r = beta_neutralize(w, betas, target_beta=0.0, dollar_neutral=True)
    assert not r["error"]
    assert abs(r["achieved_beta"] - 0.0) < 1e-4 and r["beta_hit"] is True
    # 목표 베타 0.5도 정확 달성
    r2 = beta_neutralize(w, betas, target_beta=0.5, dollar_neutral=True)
    assert abs(r2["achieved_beta"] - 0.5) < 1e-4


def test_beta_neutral_long_only_honest_about_feasibility():
    # 전부 고베타 → 롱온리로 베타 0 불가 → 음수 발생·정직 보고
    w = {"A": 50, "B": 50}
    betas = {"A": 1.3, "B": 1.1}
    r = beta_neutralize(w, betas, target_beta=0.0, dollar_neutral=False)
    assert abs(r["achieved_beta"]) < 1e-4          # 제약은 정확히 만족
    assert r["long_only_feasible"] is False        # 그러나 음수 필요 — 정직
    assert "롱숏" in r["note"]


def test_sector_neutral_equalizes_sector_weight():
    w = {"A": 60, "B": 20, "C": 20}   # A=반도체 편중
    sectors = {"A": "반도체", "B": "금융", "C": "금융"}
    r = sector_neutralize(w, sectors)
    assert not r["error"]
    # 두 섹터 균등(각 50%) 달성
    assert abs(r["sector_after_pct"]["반도체"] - 50.0) < 1e-2
    assert abs(r["sector_after_pct"]["금융"] - 50.0) < 1e-2
    assert r["neutral"] is True
    # 섹터 내 상대비중 보존 (B:C = 1:1 유지)
    assert abs(r["weights"]["B"] - r["weights"]["C"]) < 1e-2


def test_pair_spread_beta_neutral():
    betas = {"삼성전자": 1.2, "SK하이닉스": 1.5}
    r = pair_spread("삼성전자", "SK하이닉스", betas)
    assert not r["error"]
    assert abs(r["net_beta"]) < 1e-4 and r["beta_neutral"] is True
    assert r["weights"]["삼성전자"] == 100.0 and r["weights"]["SK하이닉스"] < 0   # 숏


def test_neutralize_both_mode():
    w = {"A": 40, "B": 30, "C": 30}
    r = neutralize_portfolio(
        w, mode="both", target_beta=0.0, dollar_neutral=True,
        beta_of=lambda c: {"A": 1.4, "B": 1.0, "C": 0.6}[c],
        sector_of=lambda c: {"A": "반도체", "B": "금융", "C": "금융"}[c])
    assert "beta" in r and "sector" in r and "weights" in r


# ── 슬리브 결합 ───────────────────────────────────────────────────────────────
def _ret_matrix(seed=0):
    rng = np.random.default_rng(seed)
    # 4종목 일별수익 (슬리브 재료)
    return {c: list(rng.normal(0.0004, 0.015, 260)) for c in ("A", "B", "C", "D")}


def test_combine_two_stage_sums_to_100():
    sleeves = [
        {"name": "모멘텀", "weights": {"A": 0.6, "B": 0.4}},
        {"name": "가치", "weights": {"C": 0.5, "D": 0.5}},
    ]
    r = combine_sleeves(sleeves, method="risk_parity", ret_matrix=_ret_matrix())
    assert not r["error"]
    assert abs(sum(r["combined_weights_pct"].values()) - 100.0) < 1e-2
    assert abs(sum(r["sleeve_allocation"].values()) - 100.0) < 1e-2
    assert set(r["combined_weights_pct"]) == {"A", "B", "C", "D"}   # 2단계 집계


def test_risk_budget_larger_budget_more_allocation():
    sleeves = [
        {"name": "S1", "weights": {"A": 1.0}},
        {"name": "S2", "weights": {"B": 1.0}},
    ]
    rm = _ret_matrix(1)
    r = combine_sleeves(sleeves, method="risk_budget",
                        risk_budget={"S1": 3.0, "S2": 1.0}, ret_matrix=rm)
    assert not r["error"]
    # 예산 큰 S1의 리스크 기여가 더 큼 (예산 3:1 방향)
    assert r["risk_contribution_pct"]["S1"] > r["risk_contribution_pct"]["S2"]


def test_sleeve_analytics_corr_cluster_tail():
    # A,B 강상관 / C 독립 → 군집 A,B 같은 클러스터
    rng = np.random.default_rng(3)
    base = rng.normal(0, 0.015, 260)
    rm = {
        "A": list(base + rng.normal(0, 0.002, 260)),
        "B": list(base + rng.normal(0, 0.002, 260)),
        "C": list(rng.normal(0, 0.015, 260)),
    }
    sleeves = [
        {"name": "S_A", "weights": {"A": 1.0}},
        {"name": "S_B", "weights": {"B": 1.0}},
        {"name": "S_C", "weights": {"C": 1.0}},
    ]
    r = sleeve_analytics(sleeves, ret_matrix=rm)
    assert not r["error"]
    assert r["correlation"]["S_A"]["S_B"] > 0.7          # 강상관
    assert r["clusters"]["S_A"] == r["clusters"]["S_B"]  # 같은 군집
    assert r["tail_dependency"]["basis"] == "real"
    assert set(r["risk_contribution_pct"]) == {"S_A", "S_B", "S_C"}


# ═══════════════════════════════════════════════════════════════════════════
# 리스크 예산 순환 반복 — ★감쇠가 없으면 발산한다★
# ═══════════════════════════════════════════════════════════════════════════

def _uncorrelated_cov(vols_annual):
    """무상관 공분산 — ★이 경우 답이 닫혀 있다★ `w ∝ 1/σ`."""
    import numpy as np
    sd = np.asarray(vols_annual, dtype=float) / np.sqrt(252.0)
    return np.diag(sd ** 2)


def test_risk_parity_matches_the_closed_form_for_uncorrelated_sleeves():
    """★해석해와 맞춘다★ 동어반복이 아니다 — 무상관이면 리스크 패리티가
    `w ∝ 1/σ` 로 닫혀 있어서, 구현과 무관한 정답이 존재한다."""
    import numpy as np

    from src.engine.sleeve_combine import _risk_budget_weights
    vols = [0.10, 0.20, 0.40]
    w = _risk_budget_weights(_uncorrelated_cov(vols), np.ones(3))
    inv = 1.0 / np.asarray(vols)
    assert np.allclose(w, inv / inv.sum(), atol=1e-6), w


def test_the_undamped_step_collapses_risk_parity_into_equal_weight():
    """★짝 — 감쇠가 실제로 필요하다는 것을 값으로 보인다★

    감쇠 1.0(예전 동작)은 같은 입력에서 해석해로 가지 못한다. 이 짝이 없으면
    위 테스트는 "감쇠와 무관하게 통과" 일 수도 있다.

    ★어떻게 틀리는지가 더 말해 준다★ 무상관 2슬리브(연변동성 21.2%·29.0%)에서
    감쇠 없는 반복은 정확히 **[0.5, 0.5]** 로 간다 — 한쪽이 37% 더 변동성이 큰데
    그것을 무시한 **균등가중**이다. 리스크 패리티가 존재 이유를 잃는 지점이다.
    (상관을 넣으면 [0.846, 0.154] 로 반대편으로 튄다 — 진동의 착지점이 입력에
    따라 달라질 뿐, 어느 쪽도 해석해가 아니다.)
    """
    import numpy as np

    from src.engine.sleeve_combine import _risk_budget_weights
    cov = _uncorrelated_cov([0.2123, 0.2902])
    damped = _risk_budget_weights(cov, np.ones(2))
    undamped = _risk_budget_weights(cov, np.ones(2), damping=1.0)
    assert damped[0] == pytest.approx(0.577512, abs=1e-5)
    assert undamped[0] == pytest.approx(0.5, abs=1e-6), \
        "감쇠 없는 반복이 균등가중으로 붕괴하지 않았다 — 짝이 성립하지 않는다"
    assert damped[0] != pytest.approx(undamped[0], abs=1e-3)


def _correlated_cov(vols_annual, rho):
    import numpy as np
    sd = np.asarray(vols_annual, dtype=float) / np.sqrt(252.0)
    c = np.diag(sd ** 2)
    c[0, 1] = c[1, 0] = rho * sd[0] * sd[1]
    return c


def test_the_weight_floor_prevents_an_absorbing_zero():
    """★0 은 곱셈 갱신의 흡수 상태다★ 하한이 없으면 돌아올 수 없다.

    감쇠가 켜진 기본 경로에서는 반복이 수렴해서 하한에 닿지 않는다 — 그래서
    하한만 되돌리는 변이는 기본 경로에서 **green** 이었다(equivalent mutant).
    하지만 `damping` 은 인자이고, 감쇠를 끄면 하한이 결과를 가른다:

        하한 1e-12 → [0.846378, 0.153622]
        하한 0.0   → [1.0, 0.0]          ← 한쪽이 사라지고 못 돌아온다

    그래서 하한이 실제로 무엇을 막는지 **감쇠를 끈 상태에서** 잰다.
    """
    import numpy as np

    from src.engine.sleeve_combine import _risk_budget_weights
    w = _risk_budget_weights(_correlated_cov([0.2123, 0.2902], -0.0582),
                             np.ones(2), damping=1.0)
    assert all(v > 0.0 for v in w), f"슬리브가 흡수 상태 0 으로 사라졌다: {w}"
    assert w[0] == pytest.approx(0.846378, abs=1e-5)


def test_no_sleeve_is_driven_to_exactly_zero():
    """★0 은 곱셈 갱신에서 흡수 상태다★ 한 번 0 이면 영원히 0 이다 —
    그래서 리스크 **패리티**가 `[0, 1]` 을 내고 있었다."""
    import numpy as np

    from src.engine.sleeve_combine import _risk_budget_weights
    w = _risk_budget_weights(_uncorrelated_cov([0.2123, 0.2902]), np.ones(2))
    assert all(v > 1e-6 for v in w), f"슬리브가 0 으로 붕괴했다: {w}"


def test_risk_budget_respects_an_unequal_budget():
    """★짝★ 등예산만 맞추면 `1/σ` 를 하드코딩해도 통과한다.
    예산을 2:1 로 주면 기여도 2:1 이어야 한다."""
    import numpy as np

    from src.engine.sleeve_combine import _risk_budget_weights, _risk_contributions
    cov = _uncorrelated_cov([0.15, 0.30])
    w = _risk_budget_weights(cov, np.array([2.0, 1.0]))
    rc = _risk_contributions(w, cov)
    share = rc / rc.sum()
    assert share[0] == pytest.approx(2 / 3, abs=1e-4), share
