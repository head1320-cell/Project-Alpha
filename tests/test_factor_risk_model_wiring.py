"""팩터 리스크 모델 배선 — optimizer 가 Σ = BΣ_fB' + D 를 쓴다 (§13)

★이 파일이 거는 것★
  1. 가산 필드 — 켜지 않으면 기존 동작이 **바이트 그대로**.
  2. ★새 주입점을 뚫지 않았다★ P2.5 가 만든 `optimize(s_override=…)` 를 쓴다 —
     스파이로 **실제로 모델 Σ 가 넘어가는지** 확인한다.
  3. ★조용한 폴백 금지★ 모델을 못 만들면 표본으로 계산하되 그 사실을 말한다.
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

URL = "/api/v1/allocation/rebalance-decision"
TICKERS = ["005930", "000660", "035420"]
HOLDINGS = {"005930": 50.0, "000660": 30.0, "035420": 20.0}


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from src.app_factory import create_app
    return TestClient(create_app())


def _body(**kw) -> dict:
    base = {"tickers": TICKERS, "holdings": HOLDINGS,
            "portfolio_value": 100_000_000, "model": "mvo"}
    base.update(kw)
    return base


def _post(client, **kw) -> dict:
    r = client.post(URL, json=_body(**kw))
    assert r.status_code == 200, r.text
    return r.json()


# ── 1. ★가산★ ─────────────────────────────────────────────────────────────
def test_it_is_off_by_default(client):
    assert _post(client)["risk_model"] is None


def test_turning_it_off_leaves_the_targets_unchanged(client):
    """켜지 않으면 기존 결과가 그대로다 — 가산 변경의 증명은 동일성이다."""
    a = _post(client)["target_weights"]
    b = _post(client, factor_risk_model=False)["target_weights"]
    assert a == b


# ── 2. ★있는 주입점을 쓴다★ ──────────────────────────────────────────────
def test_the_model_covariance_actually_reaches_the_optimizer(client, monkeypatch):
    """★스파이★ `s_override` 로 **모델 Σ** 가 넘어가는지 직접 본다."""
    seen = {}
    import src.api.allocation_routes as ar
    real = ar.optimize if hasattr(ar, "optimize") else None
    from src.engine import allocation_studio as als
    real = als.optimize

    def _spy(model, names, R, **kw):
        seen["s_override"] = kw.get("s_override")
        return real(model, names, R, **kw)
    monkeypatch.setattr(als, "optimize", _spy)

    b = _post(client, factor_risk_model=True)
    assert b["risk_model"]["applied"] is True, b["risk_model"].get("reason")
    S = seen.get("s_override")
    assert S is not None, "s_override 가 넘어가지 않았다"
    S = np.asarray(S, dtype=float)
    assert S.shape == (len(TICKERS), len(TICKERS))
    assert np.linalg.eigvalsh(S).min() > 0, "넘어간 Σ 가 양정부호여야 한다"


def test_the_model_changes_the_optimizer_answer(client):
    """같은 결과면 Σ 가 실제로 쓰이지 않은 것이다."""
    base = _post(client)["target_weights"]
    with_model = _post(client, factor_risk_model=True)["target_weights"]
    assert base != with_model


def test_the_supplied_covariance_is_annual(client, monkeypatch):
    """★단위★ `s_override` 는 연율 계약이다(P2.5). 월 Σ 를 넘기면 12배 어긋난다."""
    seen = {}
    from src.engine import allocation_studio as als
    real = als.optimize

    def _spy(model, names, R, **kw):
        seen["s"] = kw.get("s_override")
        return real(model, names, R, **kw)
    monkeypatch.setattr(als, "optimize", _spy)
    _post(client, factor_risk_model=True)

    from src.engine.factor_risk_model import MONTHS_PER_YEAR, build_factor_risk_model
    frm = build_factor_risk_model(TICKERS)
    if not frm["available"]:
        pytest.skip(f"이 환경에서 모델을 만들 수 없다: {frm['reason']}")
    monthly = np.asarray(frm["cov_monthly"], dtype=float)
    assert np.allclose(np.asarray(seen["s"]), monthly * MONTHS_PER_YEAR, rtol=1e-6)


# ── 3. ★조용한 폴백 금지★ ───────────────────────────────────────────────
def test_a_failed_model_says_so_and_the_calculation_continues(client, monkeypatch):
    monkeypatch.setattr("src.engine.factor_risk_model.build_factor_risk_model",
                        lambda codes, **kw: {"available": False,
                                             "reason": "표본 부족", "excluded": {}})
    b = _post(client, factor_risk_model=True)
    rm = b["risk_model"]
    assert rm["applied"] is False
    assert rm["reason"] == "표본 부족"
    assert "그 사실을 말합니다" in rm["note"]
    # 계산 자체는 계속된다 — 표본 공분산으로.
    assert b["decision"] and b["target_weights"]


def test_a_partial_model_is_not_silently_applied(client, monkeypatch):
    """★자산 순서가 어긋나면 Σ 가 다른 자산의 것이 된다★ 그것이 조용하면 위험하다."""
    real_build = None
    from src.engine import factor_risk_model as frm_mod
    real_build = frm_mod.build_factor_risk_model

    def _partial(codes, **kw):
        out = real_build(codes, **kw)
        if out.get("available"):
            out["codes"] = out["codes"][:-1]      # 한 자산이 빠진 상태를 흉내
        return out
    monkeypatch.setattr(frm_mod, "build_factor_risk_model", _partial)
    rm = _post(client, factor_risk_model=True)["risk_model"]
    assert rm["applied"] is False and rm["reason"]


# ── 4. 진단이 함께 나온다 ───────────────────────────────────────────────
def test_the_diagnostics_travel_with_the_answer(client):
    rm = _post(client, factor_risk_model=True)["risk_model"]
    d = rm["diagnostics"]
    assert d["positive_definite"] is True
    assert d["min_eigenvalue"] > 0
    assert d["n_assets"] == len(TICKERS) and d["n_factors"] >= 3
    assert d["n_months"] >= 24
    assert rm["units"] == "annual"


def test_each_asset_reports_its_own_dof_and_factor_share(client):
    rm = _post(client, factor_risk_model=True)["risk_model"]
    codes = {a["code"] for a in rm["assets"]}
    assert codes == set(TICKERS)
    for a in rm["assets"]:
        assert a["dof"] > 0
        assert 0.0 <= a["factor_share_pct"] <= 100.0
        assert a["specific_variance"] > 0


def test_the_neighbours_are_untouched(client):
    paths = {r.path for r in client.app.routes}
    for p in ("/api/v1/allocation/analyze", "/api/v1/allocation/exposures",
              "/api/v1/allocation/implement", URL):
        assert p in paths, p
