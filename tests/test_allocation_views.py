"""Allocation Studio 엔진 — 사용자 뷰 BL + 모델 스위치 검증.

전부 합성 수익률 행렬(실네트워크 0). 핵심 주장:
  1) 뷰 → P/Q/Ω 구성이 그룹 뷰·방향·크기를 정확히 인코딩
  2) 신뢰도 극단: conf→0이면 posterior≈prior(뷰 무시), conf 높으면 Q 방향 이동
  3) 모델 스위치 전부 long-only·합1, 실패 시 inverse-vol 폴백
  4) optimize() flow 3단계 구조 + 시총 결측 정직 보고
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402

from src.engine.allocation_studio import (  # noqa: E402
    bl_posterior,
    build_user_views,
    market_cap_weights,
    optimize,
    weights_for_model,
)

RNG = np.random.default_rng(42)
NAMES = ["005930", "000660", "035420", "069500"]


def _synthetic_returns(n_obs: int = 260, n_assets: int = 4) -> np.ndarray:
    # 상관 있는 합성 일간 수익률 (양의 기대수익, 자산별 상이한 vol)
    base = RNG.normal(0.0004, 0.01, size=(n_obs, 1))
    idio = RNG.normal(0.0002, 0.008, size=(n_obs, n_assets))
    scale = np.array([1.0, 1.4, 0.8, 0.5])
    return base + idio * scale


def _sigma(R):
    return np.cov(R, rowvar=False) * 252.0


# ── 1) P/Q/Ω 구성 ────────────────────────────────────────────────────────────

def test_build_views_single_asset():
    R = _synthetic_returns()
    S = _sigma(R)
    views = [{"assets": ["005930"], "direction": 1, "magnitude_pct": 3.0, "confidence": 50}]
    P, Q, omega, skipped = build_user_views(views, NAMES, S)
    assert P.shape == (1, 4)
    assert P[0, 0] == 1.0 and P[0, 1:].sum() == 0.0
    assert Q[0] == 0.03
    assert omega.shape == (1, 1) and omega[0, 0] > 0
    assert skipped == []


def test_build_views_group_and_negative():
    R = _synthetic_returns()
    S = _sigma(R)
    views = [{"assets": ["000660", "035420"], "direction": -1,
              "magnitude_pct": 2.0, "confidence": 70}]
    P, Q, omega, _ = build_user_views(views, NAMES, S)
    assert abs(P[0, 1] - 0.5) < 1e-12 and abs(P[0, 2] - 0.5) < 1e-12
    assert Q[0] == -0.02


def test_build_views_skips_unknown_assets_honestly():
    R = _synthetic_returns()
    S = _sigma(R)
    views = [{"assets": ["999999"], "direction": 1, "magnitude_pct": 3.0, "confidence": 50},
             {"assets": ["005930"], "direction": 1, "magnitude_pct": 0.0, "confidence": 50}]
    P, Q, omega, skipped = build_user_views(views, NAMES, S)
    assert P is None and Q is None and omega is None
    assert len(skipped) == 2  # 조용히 버리지 않고 보고


def test_omega_scales_with_confidence():
    # 신뢰도가 높을수록 Ω(뷰 불확실성)가 작아져야 함 — 단조성
    R = _synthetic_returns()
    S = _sigma(R)
    omegas = []
    for conf in (10, 50, 90):
        _, _, om, _ = build_user_views(
            [{"assets": ["005930"], "direction": 1, "magnitude_pct": 3.0,
              "confidence": conf}], NAMES, S)
        omegas.append(om[0, 0])
    assert omegas[0] > omegas[1] > omegas[2]


# ── 2) posterior 신뢰도 극단 ─────────────────────────────────────────────────

def _posterior_for_conf(conf: float):
    R = _synthetic_returns()
    S = _sigma(R)
    w_mkt = np.ones(4) / 4
    pi = 2.5 * S @ w_mkt
    views = [{"assets": ["005930"], "direction": 1, "magnitude_pct": 20.0,
              "confidence": conf}]
    P, Q, omega, _ = build_user_views(views, NAMES, S)
    mu = bl_posterior(pi, S, P, Q, omega)
    return pi, mu


def test_posterior_low_confidence_stays_near_prior():
    pi, mu = _posterior_for_conf(1.0)
    # conf→0: Ω가 매우 커서 뷰가 거의 무시 — posterior가 prior에 근접
    assert abs(mu[0] - pi[0]) < abs(0.20 - pi[0]) * 0.2


def test_posterior_high_confidence_moves_toward_view():
    pi, mu = _posterior_for_conf(95.0)
    # conf 95: 대상 자산 기대수익이 뷰 값(+20%) 방향으로 크게 이동
    assert mu[0] > pi[0]
    assert abs(mu[0] - 0.20) < abs(pi[0] - 0.20)


# ── 3) 모델 스위치 ───────────────────────────────────────────────────────────

def test_all_models_long_only_sum_one():
    R = _synthetic_returns()
    for model in ("mvo", "risk_parity", "hrp", "min_var"):
        w = weights_for_model(model, R)
        assert w.shape == (4,)
        assert np.all(w >= -1e-12), model
        assert abs(w.sum() - 1.0) < 1e-9, model


def test_min_var_prefers_low_vol_asset():
    R = _synthetic_returns()
    w = weights_for_model("min_var", R)
    # scale이 가장 작은(0.5) 마지막 자산이 최대 비중이어야 함
    assert int(np.argmax(w)) == 3


# ── 4) optimize 파이프라인 ───────────────────────────────────────────────────

def test_optimize_flow_structure(monkeypatch):
    monkeypatch.setattr("src.data.stock_master.get_market_cap",
                        lambda code: {"005930": 4000000.0, "000660": 1200000.0,
                                      "035420": 300000.0, "069500": 60000.0}.get(code))
    R = _synthetic_returns()
    views = [{"assets": ["005930"], "direction": 1, "magnitude_pct": 5.0, "confidence": 80}]
    out = optimize("bl", NAMES, R, views=views)
    assert out["views_applied"] is True
    assert out["cap_missing"] == []
    for stage in ("market", "view_applied", "optimized"):
        w = out["flow"][stage]
        assert abs(w.sum() - 1.0) < 1e-9
        assert np.all(w >= -1e-12)
    # 시총 캡가중: 삼성전자가 시장열 최대 비중
    assert int(np.argmax(out["flow"]["market"])) == 0
    # BL 모델: 최종 = 뷰 반영 열
    assert np.allclose(out["flow"]["view_applied"], out["flow"]["optimized"])


def test_optimize_no_views_market_equals_view_stage(monkeypatch):
    monkeypatch.setattr("src.data.stock_master.get_market_cap", lambda code: 100000.0)
    R = _synthetic_returns()
    out = optimize("risk_parity", NAMES, R, views=None)
    assert out["views_applied"] is False
    assert np.allclose(out["flow"]["market"], out["flow"]["view_applied"])


def test_market_cap_missing_reported(monkeypatch):
    monkeypatch.setattr("src.data.stock_master.get_market_cap",
                        lambda code: 100000.0 if code == "005930" else None)
    w, missing = market_cap_weights(NAMES)
    assert set(missing) == {"000660", "035420", "069500"}
    assert abs(w.sum() - 1.0) < 1e-9
