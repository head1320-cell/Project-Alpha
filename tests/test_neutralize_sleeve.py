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
