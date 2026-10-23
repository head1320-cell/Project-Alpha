"""P4 매크로 지능 라우트 4종 (P4-U 백엔드).

D1~D5 와 M1~M3 가 엔진을 만들었지만 **화면에서 아무것도 볼 수 없다** — 라우트가
없기 때문이다. 이 파일은 그 네 개를 계약으로 고정한다.

    GET /macro/source-coverage           D5  소스 표 + 키가 여는 것 + 사다리
    GET /macro/long-run                  M1  공적분 → VECM / 차분 VAR (선택 사유)
    GET /macro/regime-forecast-coverage  M2  예측집합의 실측 적중률
    GET /macro/regime-consensus          M3  세 국면 도구의 불일치 (평균 금지)

★라우트는 판정하지 않는다★ 엔진의 답을 그대로 싣기만 한다. 라우트가 다시 판정하면
같은 판단이 두 곳에 생기고 반드시 갈라진다 — 이 저장소가 A1·R0 에서 두 번 겪었다.
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from fastapi.testclient import TestClient  # noqa: E402
from main_api import app  # noqa: E402

client = TestClient(app)


# ─────────────────────────────────────────────────────────────────────────────
# 1. D5 — 소스 커버리지
# ─────────────────────────────────────────────────────────────────────────────
def test_source_coverage_lists_providers_keys_and_the_ladder():
    r = client.get("/api/v1/macro/source-coverage")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["providers"] and body["keys"]
    assert body["ladder"]["level"] in ("L0", "L1", "L2", "L3")


def test_source_coverage_never_ships_a_key_value(monkeypatch):
    """★라우트는 화면과 로그로 나간다 — 값이 실리면 안 된다★"""
    secret = "sk-routelevelsecret-9876543210"
    monkeypatch.setenv("KRX_API_KEY", secret)
    raw = client.get("/api/v1/macro/source-coverage").text
    assert secret not in raw
    assert secret[:8] not in raw


def test_source_coverage_can_skip_the_expensive_ladder():
    """짝 — 사다리 프로브는 매크로를 수집하므로 비싸다(실측 1.1초, 키 있으면 51초).

    키·제공자 표만 필요한 화면이 그 값을 물지 않아도 되게 한다.
    """
    body = client.get("/api/v1/macro/source-coverage?include_ladder=false").json()
    assert body["providers"] and body["keys"]
    assert body["ladder"] is None


# ─────────────────────────────────────────────────────────────────────────────
# 2. M1 — 공적분 분기
# ─────────────────────────────────────────────────────────────────────────────
def test_long_run_answers_with_a_model_choice_and_its_reason():
    r = client.get("/api/v1/macro/long-run")
    assert r.status_code == 200, r.text
    body = r.json()
    if body["available"]:
        assert body["model"] in ("vecm", "diff_var")
        assert body["reason"], "어느 모형을 왜 골랐는지 없다"
        assert body["evidence"]["test"] == "johansen_trace"
    else:
        assert body["reason"], "미가용인데 사유가 없다"


def test_long_run_refuses_more_than_the_core_variable_limit():
    """★리뷰 지적 2 를 라우트에서도 막는다★ 사용자가 40개를 넣을 수 있으면
    안 된다 — 엔진이 예외를 던지는데 라우트가 500 으로 흘리면 사유가 사라진다."""
    from src.engine.cointegration import MAX_CORE_VARS
    keys = ",".join(f"KR_V{i}" for i in range(MAX_CORE_VARS + 1))
    r = client.get(f"/api/v1/macro/long-run?vars={keys}")
    assert r.status_code == 422, r.text
    assert str(MAX_CORE_VARS) in r.text


def test_long_run_reports_which_variables_it_actually_used():
    """요청한 것과 쓴 것이 다를 수 있다(수집 안 된 계열) — 그 사실을 낸다."""
    body = client.get("/api/v1/macro/long-run").json()
    assert "requested" in body and "used" in body
    assert set(body["used"]) <= set(body["requested"])


# ─────────────────────────────────────────────────────────────────────────────
# 3. M2 — 예측 적중률
# ─────────────────────────────────────────────────────────────────────────────
def test_forecast_coverage_reports_measured_and_target_separately():
    r = client.get("/api/v1/macro/regime-forecast-coverage")
    assert r.status_code == 200, r.text
    body = r.json()
    if body["available"]:
        assert body["target"] != body.get("coverage") or body["hits"] >= 0
        assert body["walk_forward"] is True
        assert body["mean_set_size"] >= 1.0
    else:
        assert body["reason"]


def test_forecast_coverage_rejects_a_nonsense_horizon():
    r = client.get("/api/v1/macro/regime-forecast-coverage?k=0")
    assert r.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# 4. M3 — 국면 합의/불일치
# ─────────────────────────────────────────────────────────────────────────────
def test_regime_consensus_reports_disagreement_and_never_averages():
    r = client.get("/api/v1/macro/regime-consensus")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "disagreement" in body
    assert "per_tool" in body, "개별 판정을 숨기면 되짚을 수 없다"
    assert isinstance(body["consensus"], bool)


def test_regime_consensus_names_unavailable_tools_with_reasons():
    """★미가용 도구를 조용히 빼지 않는다★ 어느 도구가 왜 빠졌는지 모르면
    남은 답을 어떻게 읽을지 알 수 없다."""
    body = client.get("/api/v1/macro/regime-consensus").json()
    for name in body["unavailable"]:
        assert body["reasons"].get(name), f"{name}: 미가용 사유가 없다"


def test_regime_consensus_does_not_claim_consensus_from_one_tool():
    """짝 — 도구 하나만 답했으면 합의가 아니다(엔진 계약이 라우트까지 살아 있는지)."""
    body = client.get("/api/v1/macro/regime-consensus").json()
    if body["n_available"] <= 1:
        assert body["consensus"] is False
