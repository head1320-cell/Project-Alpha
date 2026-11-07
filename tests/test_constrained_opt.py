"""제약 최적화 엔진 검증 (Full Expansion P3)

핵심 주장 (지시서 3분법):
  충족   — 종목상한·그룹상한·회전율·베타·현금밴드가 동시에 걸려도 해가 제약을 만족
  근사   — 불가능한 회전율 상한 → 완화 사다리로 근사해 + relaxed/위반 정직 보고
  불능   — 구조적 infeasible(상한 합 부족)은 사람 언어 사유와 함께 즉시 반환
  투영   — 공분산 전용 모델(risk_parity)은 근사 투영 + 정직 라벨
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402

from src.engine.constrained_opt import (  # noqa: E402
    Constraints,
    asset_betas,
    constrained_solve,
    sector_groups_for,
)

RNG = np.random.default_rng(5)
N = 8
NAMES = [f"{i:06d}" for i in range(1, N + 1)]


def _data(days=500):
    R = RNG.normal(0.0004, 0.012, (days, N))
    R[:, 0] += 0.0008          # 자산0이 뚜렷이 우월 → 무제약 max-sharpe는 집중됨
    mu = R.mean(axis=0) * 252
    S = np.cov(R.T) * 252
    return R, mu, S


def test_unconstrained_concentrates_then_cap_binds():
    R, mu, S = _data()
    free = constrained_solve("mvo", NAMES, R, mu, S, Constraints())
    assert free["status"] == "ok"
    assert free["weights"].max() > 0.25         # 무제약 → 상한(20%)보다 집중됨 (전제 확인)

    capped = constrained_solve("mvo", NAMES, R, mu, S, Constraints(max_weight_pct=20))
    assert capped["status"] == "ok"
    assert capped["weights"].max() <= 0.20 + 0.01
    assert abs(capped["weights"].sum() - 1.0) < 0.01
    assert any("상한" in b for b in capped["binding"])   # 바인딩 보고


def test_group_cap_and_cash_band():
    R, mu, S = _data()
    groups = {NAMES[0]: "반도체", NAMES[1]: "반도체", NAMES[2]: "반도체"}
    sol = constrained_solve("mvo", NAMES, R, mu, S,
                            Constraints(group_caps_pct={"반도체": 30}, cash_min_pct=5, cash_max_pct=15),
                            groups_of=groups)
    assert sol["status"] == "ok"
    w = sol["weights"]
    semi = w[:3].sum()
    assert semi <= 0.30 + 0.01
    cash = 1.0 - w.sum()
    assert 0.05 - 0.01 <= cash <= 0.15 + 0.01
    assert any("현금" in n for n in sol["notes"])        # 현금 수익 0 가정 정직 노트


def test_turnover_cap_respected():
    R, mu, S = _data()
    w_cur = {t: 100.0 / N for t in NAMES}                # 균등 보유에서 출발
    sol = constrained_solve("mvo", NAMES, R, mu, S,
                            Constraints(turnover_cap_pct=10), w_current=w_cur)
    assert sol["status"] == "ok"
    w = sol["weights"]
    t = 0.5 * np.abs(w - 1.0 / N).sum() * 100
    assert t <= 10 + 1.0


def test_beta_cap_with_bench():
    R, mu, S = _data()
    bench = R.mean(axis=1) + RNG.normal(0, 0.002, R.shape[0])
    betas = asset_betas(R, bench)
    assert betas is not None and np.isfinite(betas).all()
    sol = constrained_solve("mvo", NAMES, R, mu, S,
                            Constraints(beta_max=0.8), bench_returns=bench)
    assert sol["status"] in ("ok", "approx")
    if sol["status"] == "ok":
        assert float(sol["weights"] @ betas) <= 0.8 + 0.05


def test_infeasible_honest_reason():
    R, mu, S = _data()
    sol = constrained_solve("mvo", NAMES, R, mu, S, Constraints(max_weight_pct=5))
    assert sol["status"] == "infeasible"
    assert "상한" in sol["reason"] and "채울 수 없습니다" in sol["reason"]
    assert sol["weights"] is None                        # 조용한 대체 해 없음


def test_relax_ladder_reports_relaxed():
    """상한 20%로 재배분이 강제되는데 회전율 0.5%는 불가능 → 완화 사다리 → relaxed 보고."""
    R, mu, S = _data()
    w_cur = {NAMES[0]: 60.0, NAMES[1]: 40.0}             # 집중 보유에서 출발
    sol = constrained_solve("mvo", NAMES, R, mu, S,
                            Constraints(max_weight_pct=20, turnover_cap_pct=0.5),
                            w_current=w_cur)
    assert sol["status"] == "approx"
    assert "turnover" in sol["relaxed"]
    assert any(v["kind"] == "turnover" for v in sol["violations"])   # 위반 정직 목록
    assert sol["weights"].max() <= 0.20 + 0.01           # 유지된 제약은 계속 충족


def test_cov_only_projection_honest_label():
    R, mu, S = _data()
    sol = constrained_solve("risk_parity", NAMES, R, mu, S, Constraints(max_weight_pct=15))
    assert sol["projected"] is True
    assert sol["weights"].max() <= 0.15 + 0.01
    assert any("근사 투영" in n for n in sol["notes"])
    assert abs(sol["weights"].sum() - 1.0) < 0.02


def test_sector_groups_fallback_empty():
    """마스터 미적재 환경 → 빈 dict (제약 미적용, 크래시 없음 — 정직 폴백)."""
    g = sector_groups_for(NAMES)
    assert isinstance(g, dict)
