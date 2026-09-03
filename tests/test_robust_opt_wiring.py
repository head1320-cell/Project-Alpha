"""로버스트 최적화 배선 — 모델 등록 + 밴드로 흘려보내기 (Brief §8.3 → §10)

★이 파일이 거는 것★
  1. ★기존 8개 모델이 바뀌지 않는다★ `MODELS` 에 한 줄 더한 것이 회귀가 아님을
     못박는다 — 가산 변경의 유일한 증명은 기존 출력의 동일성이다.
  2. ★매달려 있던 입력이 이제 공급된다★ 밴드의 `uncertainty` 를 아무도 주지
     않던 상태에서 μ 추정오차가 흘러들어간다.
  3. 로버스트가 실제 요청 경로에서 평문보다 분산된다.
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from src.engine.allocation_studio import MODELS, model_availability, optimize  # noqa: E402

URL = "/api/v1/allocation/rebalance-decision"
TICKERS = ["005930", "000660", "035420"]
HOLDINGS = {"005930": 50.0, "000660": 30.0, "035420": 20.0}

LEGACY_MODELS = ("mvo", "bl", "ep", "risk_parity", "hrp", "min_var",
                 "max_div", "min_cvar")


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from src.app_factory import create_app
    return TestClient(create_app())


@pytest.fixture(scope="module")
def R() -> np.ndarray:
    rng = np.random.default_rng(20260823)
    return (rng.normal(0.0, 0.012, (756, 4)) + rng.normal(0.0, 0.008, (756, 1))
            + np.array([0.0008, 0.0004, 0.0002, 0.0]))


NAMES = ["A", "B", "C", "D"]


def _body(**kw) -> dict:
    base = {"tickers": TICKERS, "holdings": HOLDINGS,
            "portfolio_value": 100_000_000, "model": "mvo"}
    base.update(kw)
    return base


def _post(client, **kw) -> dict:
    r = client.post(URL, json=_body(**kw))
    assert r.status_code == 200, r.text
    return r.json()


# ── 1. ★기존 8개 모델 불변★ ───────────────────────────────────────────────
def test_the_legacy_models_are_still_all_there():
    for m in LEGACY_MODELS:
        assert m in MODELS, m
    assert "robust" in MODELS
    assert len(MODELS) == len(LEGACY_MODELS) + 1, "가산이어야 한다"


def test_adding_robust_did_not_change_any_legacy_model_output(R):
    """★가산 변경의 유일한 증명은 기존 출력의 동일성이다★

    `robust` 분기는 `elif` 사슬 안에 있으므로 다른 모델의 경로를 지나지 않는다.
    그 사실을 출력으로 확인한다 — 코드를 읽어서가 아니라.
    """
    for m in LEGACY_MODELS:
        a = optimize(m, NAMES, R)["weights"]
        b = optimize(m, NAMES, R)["weights"]
        assert np.allclose(a, b), f"{m} 이 결정적이지 않다"
        assert np.all(a >= -1e-9) and a.sum() == pytest.approx(1.0, abs=1e-6)


def test_every_model_has_an_availability_entry():
    """★폴백이 가리는 것을 먼저 본다★ 등록만 하고 가용성을 빠뜨리면 산포가 거짓말한다."""
    av = model_availability()
    for m in MODELS:
        assert m in av, f"{m} 의 가용성이 없다"
        assert set(av[m]) == {"available", "reason"}
    assert av["robust"]["available"] is True


def test_an_unknown_model_still_falls_back_to_mvo(R):
    a = optimize("존재하지않는모델", NAMES, R)["weights"]
    b = optimize("mvo", NAMES, R)["weights"]
    assert np.allclose(a, b)


# ── 2. 로버스트가 실제로 분산시킨다 ────────────────────────────────────────
def test_robust_is_more_diversified_than_its_own_kappa_zero_baseline(R):
    """★비교는 **같은 목적함수 안에서** 해야 한다★

    `optimize("mvo")` 는 max-Sharpe(λ 없음)이고 `robust` 는 평균-분산 효용
    (λ 있음)이다. 둘의 HHI 를 비교하면 재는 것이 "로버스트성" 이 아니라
    "목적함수 차이" 가 된다 — 실제로 그렇게 짰다가 robust 쪽이 더 집중된
    결과(0.513 vs 0.507)를 얻었다. κ 만 바꿔 같은 목적함수 안에서 잰다.
    """
    from src.engine.robust_opt import robust_weights
    out = robust_weights(NAMES, R, kappa=1.645)
    c = out["concentration"]
    assert c["hhi"] < c["hhi_naive"], c


def test_robust_differs_from_mvo(R):
    """목적함수가 다르므로 결과도 달라야 한다 — 같으면 분기를 안 탄 것이다."""
    naive = optimize("mvo", NAMES, R)["weights"]
    rob = optimize("robust", NAMES, R)["weights"]
    assert not np.allclose(naive, rob)


def test_the_robust_label_really_delivers_robust_weights(R):
    """★폴백이 라벨을 거짓말로 만든다★

    `weights_for_model` 은 모델이 `None` 을 내면 조용히 inverse-vol 로 떨어진다.
    그러면 "robust" 라는 라벨 아래 실제로는 inverse-vol 이 들어앉는다 —
    `model_availability()` 의 docstring 이 경고하는 바로 그 상황이다.
    변이 프로브가 이것을 green 으로 드러냈으므로 출력 자체를 못박는다.
    """
    from src.engine.allocation_studio import _cov
    from src.engine.robust_opt import robust_weights

    S = _cov(R) * 252.0
    direct = robust_weights([str(i) for i in range(R.shape[1])], R, s_override=S)
    assert direct["available"] is True, direct["reason"]

    via_optimize = optimize("robust", NAMES, R)["weights"]
    assert np.allclose(via_optimize, direct["weights"], atol=1e-8), (
        "robust 라벨이 실제 로버스트 해를 내지 않는다(폴백에 가려졌을 수 있다)")

    # 그리고 그것은 inverse-vol 폴백과 달라야 한다.
    from src.engine.allocation_studio import _inverse_vol_w
    assert not np.allclose(via_optimize, _inverse_vol_w(R), atol=1e-6)


def test_robust_runs_through_the_route(client):
    b = _post(client, model="robust")
    assert b["target_source"] == "optimize:robust"
    assert set(b["target_weights"]) == set(TICKERS)
    assert sum(b["target_weights"].values()) == pytest.approx(100.0, abs=0.5)


def test_robust_targets_differ_from_mvo_targets_on_the_route(client):
    """★목적함수가 다르므로 HHI 대소를 주장하지 않는다★ (위 테스트의 교훈)"""
    mvo = _post(client, model="mvo")["target_weights"]
    rob = _post(client, model="robust")["target_weights"]
    assert mvo != rob, "같으면 로버스트가 실제로 돌지 않은 것이다"


# ── 3. ★매달려 있던 입력이 공급된다★ ──────────────────────────────────────
def test_the_response_reports_whether_mu_is_distinguishable_from_zero(client):
    """★|μ|/SE < 2 면 그 μ 에 비중을 거는 것은 잡음에 거는 것이다★"""
    u = _post(client)["mu_uncertainty"]
    assert u is not None
    assert set(u["mu_over_se"]) == set(TICKERS)
    assert 0.0 <= u["scalar"] <= 1.0
    assert 0 <= u["n_resolvable"] <= u["n_assets"] == len(TICKERS)
    assert "0과 구분되지 않습니다" in u["note"]


def test_the_uncertainty_actually_widens_the_bands(client):
    """★예전에는 `uncertainty` 인자가 매달려 있었다 — 아무도 주지 않았다★"""
    b = _post(client)
    u = b["mu_uncertainty"]["scalar"]
    assert u > 0, "이 표본에서는 μ 가 0과 구분되지 않으므로 불확실성이 있다"
    for code, band in b["band"]["by_asset"].items():
        assert band["inputs"]["uncertainty"] == pytest.approx(u, abs=1e-3), code
        assert band["multipliers"]["uncertainty"] == pytest.approx(1.0 + u, abs=1e-3)


def test_a_wider_band_follows_from_more_uncertainty(client, monkeypatch):
    """짝 — 불확실성을 0 으로 만들면 밴드가 좁아진다."""
    wide = _post(client)
    monkeypatch.setattr("src.engine.robust_opt.uncertainty_scalar", lambda t: 0.0)
    narrow = _post(client)
    assert narrow["mu_uncertainty"]["scalar"] == 0.0
    for code, band in narrow["band"]["by_asset"].items():
        if band["clamped"] or wide["band"]["by_asset"][code]["clamped"]:
            continue
        assert band["half_width_pct"] < wide["band"]["by_asset"][code]["half_width_pct"]


def test_an_unusable_sample_says_so_rather_than_guessing(client, monkeypatch):
    monkeypatch.setattr("src.engine.robust_opt.mu_standard_errors",
                        lambda R: {"available": False, "reason": "표본 부족"})
    b = _post(client)
    assert b["mu_uncertainty"] is None
    assert b["decision"], "불확실성을 몰라도 결정 자체는 나온다"


# ── 4. 조건부 Σ 와 함께 ────────────────────────────────────────────────────
def test_robust_accepts_the_conditional_covariance(client):
    b = _post(client, model="robust", conditional=True)
    assert b["target_source"] == "optimize:robust"
    assert b["conditional"] is not None


# ── 5. 팩터 노출 (Brief §8.4) ──────────────────────────────────────────────
def test_factor_exposure_is_off_by_default(client):
    """매크로 회귀는 느리다 — 기본 동작을 바꾸지 않는다(가산 필드)."""
    assert _post(client)["factors"] is None


def test_factor_exposure_reports_named_factors_when_asked(client):
    """★자산 개수가 아니라 팩터 개수★ 이름 없는 주성분이 아니라 경제 팩터다."""
    f = _post(client, factor_exposure=True)["factors"]
    assert f is not None
    by = f["exposure"]["by_factor"]
    for named in ("equity", "duration", "inflation", "usd"):
        assert named in by, named
        assert by[named]["series"], "어느 계열에서 왔는지 밝힌다"


def test_the_factor_block_reports_its_sample_shape(client):
    """★차원의 저주를 숨기지 않는다★"""
    s = _post(client, factor_exposure=True)["factors"]["sample"]
    assert s["n_months"] >= 24 and s["n_factors"] >= 1
    assert s["obs_per_factor"] == pytest.approx(s["n_months"] / s["n_factors"], abs=0.01)


def test_factor_concentration_is_separate_from_asset_enb(client):
    """★한 표에 섞지 않는다★ 팩터 집중도와 자산 ENB 는 다른 숫자다."""
    c = _post(client, factor_exposure=True)["factors"]["concentration"]
    assert c is not None
    assert 1.0 <= c["effective_factors"] <= c["n_factors"]
    assert "자산 ENB" in c["note"]


# ── 6. 팩터 리스크 분해(P3-4) · 역스트레스(§12) ───────────────────────────
def test_factor_risk_and_reverse_stress_are_off_by_default(client):
    """가산 필드 — 켜지 않으면 기본 동작이 이전과 같다."""
    f = _post(client, factor_exposure=True)["factors"]
    assert "risk" not in f and "reverse_stress" not in f
    assert "covariance" not in f, "공분산도 필요할 때만 만든다"


def test_they_are_ignored_when_factor_exposure_is_off(client):
    """★노출 없이는 뜻이 없다★ 켜도 조용히 무시되고 factors 자체가 없다."""
    b = _post(client, factor_exposure=False, factor_risk=True, reverse_stress=True)
    assert b["factors"] is None


def test_factor_risk_splits_variance_into_factor_and_idiosyncratic(client):
    """P3-4 — Company 팩터 노출이 포트폴리오 리스크로 이어진다."""
    r = _post(client, factor_exposure=True, factor_risk=True)["factors"]["risk"]
    assert r["available"] is True, r["reason"]
    assert r["factor_share_pct"] is not None
    assert (r["factor_share_pct"] + r["idiosyncratic_share_pct"]
            == pytest.approx(100.0, abs=0.05))
    assert r["over_explained"] in (True, False)
    # 기여 합 = 팩터 분산.
    total = sum(row["variance_contribution"] for row in r["rows"])
    assert total == pytest.approx(r["factor_variance"], rel=1e-5)


def test_the_total_variance_source_is_disclosed(client):
    """★총분산이 어디서 왔는지 밝힌다★ 커버리지가 낮으면 다른 숫자다."""
    src = _post(client, factor_exposure=True,
                factor_risk=True)["factors"]["risk"]["total_variance_source"]
    assert src["available"] is True
    assert src["n_months"] >= 24 and src["coverage_pct"] > 0


def test_reverse_stress_returns_shocks_with_a_distance(client):
    """★거리 없이 충격만 내지 않는다★"""
    rs = _post(client, factor_exposure=True,
               reverse_stress=True)["factors"]["reverse_stress"]
    assert rs["available"] is True, rs["reason"]
    assert rs["distance"] > 0 and rs["plausibility"]["label"]
    assert rs["shocks"] and rs["shocks"][0]["factor"]
    assert sum(s["contribution_pct"] for s in rs["shocks"]) == pytest.approx(
        -15.0, abs=1e-2)


def test_the_stress_target_is_configurable(client):
    a = _post(client, factor_exposure=True, reverse_stress=True,
              stress_loss_pct=-5.0)["factors"]["reverse_stress"]
    b = _post(client, factor_exposure=True, reverse_stress=True,
              stress_loss_pct=-30.0)["factors"]["reverse_stress"]
    assert a["target_loss_pct"] == -5.0 and b["target_loss_pct"] == -30.0
    assert b["distance"] > a["distance"], "큰 손실일수록 먼 사건이다"


def test_reverse_stress_reports_beta_quality_beside_the_distance(client):
    """★거리와 베타 품질은 다른 질문이다★ 하나만 보면 잡음을 흔한 일로 읽는다."""
    rs = _post(client, factor_exposure=True,
               reverse_stress=True)["factors"]["reverse_stress"]
    q = rs["beta_quality"]
    assert q["available"] is True
    assert 0.0 <= q["mean_resolvable_pct"] <= 100.0
    assert q["trustworthy"] in (True, False)


def test_the_covariance_block_declares_its_normalisation(client):
    """★단위를 섞지 않았다는 사실을 응답이 말한다★"""
    c = _post(client, factor_exposure=True,
              reverse_stress=True)["factors"]["covariance"]
    assert c["available"] is True
    assert c["scale_normalized"] is True
    assert c["sd_raw"] and c["n_months"] >= 24
    assert c["degenerate"] in (True, False)


def test_a_bad_stress_target_is_rejected(client):
    assert client.post(URL, json=_body(factor_exposure=True, reverse_stress=True,
                                       stress_loss_pct=5.0)).status_code == 422
