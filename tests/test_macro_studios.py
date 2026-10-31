"""5개 서브스튜디오 — 프론티어 계약 + 정직한 대체 엔진 (M1-M)
==============================================================================
요청받은 아키텍처의 Tier 2 모델(TSFM · Neural SDE · DeePM · PINN · Agentic CLQT)은
torch·LLM·트렌드 API 가 없고 표본이 60개월 mock 이라 지금 지을 수 없다. 대신 각
스튜디오가 **두 엔진**을 선언한다 — 프론티어는 계약만, 대체는 실제로 돈다.

★이 파일이 잠그는 것 넷★
  1. **미가용 엔진은 숫자를 내지 않는다** — 사유만 낸다.
  2. **어느 엔진이 냈는지 항상 밝힌다** — `engine` 필드가 비면 두 값이 섞인다.
  3. 프론티어 가용성은 **능력 사다리와 한 판정을 쓴다** — 두 곳이 갈라지면 화면이
     "사다리는 L1 인데 스튜디오는 프론티어가 된다" 고 말하게 된다.
  4. **표본이 모자라면 적합하지 않고 거부한다** — 6개 초과관측에 GPD 를 맞추면
     숫자는 나오지만 그 숫자는 아무 뜻도 없다.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.engine.macro_models import describe_all, run_studio
from src.engine.macro_models.base import STUDIOS

STUDIO_IDS = ("tsfm-latent", "neural-sde", "causal-deepm", "pinn-tail", "agentic-mcp")


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from src.app_factory import create_app
    return TestClient(create_app())


# ── 1. 계약 ─────────────────────────────────────────────────────────────────
def test_every_studio_declares_both_engines():
    ds = {d["id"]: d for d in describe_all()}
    assert set(ds) == set(STUDIO_IDS), f"스튜디오 목록이 다르다: {sorted(ds)}"
    for sid, d in ds.items():
        assert d["question"], f"{sid}: 이 스튜디오가 무엇에 답하는지 적혀 있지 않다"
        for kind in ("frontier", "substitute"):
            e = d[kind]
            assert e["name"] and e["summary"], f"{sid}.{kind}: 이름/요약이 비었다"
            assert isinstance(e["requires"], list)


def test_an_unavailable_frontier_gives_a_reason_and_no_numbers():
    """★미가용은 숫자 대신 사유다★ 이 환경에서는 다섯 프론티어가 전부 미가용이다."""
    for d in describe_all():
        f = d["frontier"]
        if f["available"]:
            continue
        assert f["reason"], f"{d['id']}: 미가용인데 사유가 없다"
        assert "outputs" not in f, f"{d['id']}: 미가용 프론티어가 값을 냈다"
        assert f.get("missing"), f"{d['id']}: 어느 요건이 빠졌는지 말하지 않는다"


def test_the_frontier_verdict_comes_from_the_capability_ladder():
    """★두 곳에서 따로 판정하지 않는다★ 갈라지면 화면이 서로 다른 말을 한다."""
    from src.engine.capability import probe_all

    p = probe_all()
    for s in STUDIOS():
        d = next(x for x in describe_all() if x["id"] == s.id)
        expect_ok = all(p.get(r, {}).get("ok") for r in s.frontier.requires)
        assert d["frontier"]["available"] is expect_ok, \
            f"{s.id}: 스튜디오 판정이 사다리와 다르다"


def test_an_unknown_studio_is_refused_by_name():
    out = run_studio("no-such-studio")
    assert out["available"] is False and "no-such-studio" in out["reason"]


# ── 2. 대체 엔진이 실제로 돈다 ──────────────────────────────────────────────
@pytest.mark.parametrize("sid", ["tsfm-latent", "neural-sde", "causal-deepm"])
def test_the_substitute_engine_produces_labelled_output(sid):
    out = run_studio(sid, months=60)
    if not out["available"]:
        pytest.skip(f"{sid}: 이 환경에서 미가용 — {out['reason']}")
    assert out["engine"], "어느 엔진이 낸 값인지 밝히지 않았다"
    assert out["outputs"], "가용이라면서 산출이 비었다"
    assert out["note"], "대체 엔진인데 한계를 적지 않았다"
    span = out["span"]
    assert span and span["n"] > 0
    # ★요청보다 짧으면 응답이 그 사실을 말한다 (A8 규칙)★
    assert span["truncated"] is (span["n"] < span["requested"])


def test_the_term_studio_does_not_call_its_output_a_risk_price():
    """★이름이 곧 주장이다★ Nelson-Siegel 은 무차익 조건을 걸지 않으므로 여기서
    나오는 값을 λ_t 라고 부르면 무차익 모형이 준 것과 같은 무게로 읽힌다."""
    out = run_studio("neural-sde", months=60)
    if not out["available"]:
        pytest.skip(out["reason"])
    o = out["outputs"]
    assert "slope" in o and "term_premium_proxy" in o
    assert "risk_price" not in o and "lambda_t" not in o
    assert "위험가격" in out["note"] and "대용" in out["note"]


def test_the_causal_studio_says_granger_is_not_intervention():
    out = run_studio("causal-deepm", months=60)
    if not out["available"]:
        pytest.skip(out["reason"])
    assert "개입 인과가 아닙니다" in out["note"]


# ── 3. ★표본이 모자라면 적합하지 않고 거부한다★ ────────────────────────────
def test_the_tail_studio_refuses_rather_than_fitting_six_points():
    """60개월 mock 에서 상위 10% 초과관측은 6개다. GPD 모수 2개를 6점에 맞추면
    숫자는 나오지만 그 숫자는 아무 뜻도 없다 — 내지 않는 것이 정답이다."""
    out = run_studio("pinn-tail", months=60)
    if out["available"]:
        # 표본이 늘어난 환경이라면 최소 요건을 실제로 넘겼는지 확인한다.
        assert out["outputs"]["n_exceed"] >= 8
        return
    assert "초과 관측" in out["reason"] and "최소" in out["reason"]
    assert "outputs" not in out, "거부했는데 값을 냈다"


def test_the_tail_studio_refuses_a_series_it_does_not_have():
    out = run_studio("pinn-tail", months=60, target="NOPE")
    assert out["available"] is False and "NOPE" in out["reason"]


def _synthetic_prices(losses: np.ndarray) -> list[float]:
    """손실 수익률 배열 → 가격 수준. `load_series` 를 대신 물릴 때 쓴다."""
    return (100.0 * np.cumprod(np.exp(-losses))).tolist()


def test_a_heavy_tail_is_fitted_when_the_sample_is_long_enough(monkeypatch):
    """표본이 충분하면 실제로 적합하고, 꼬리지수를 낸다."""
    from src.engine.macro_models import pinn_tail

    rng = np.random.default_rng(3)
    losses = rng.standard_t(df=3, size=600) * 0.01
    monkeypatch.setattr(pinn_tail, "load_series",
                        lambda keys, months: {"KOSPI": _synthetic_prices(losses)})
    out = pinn_tail.run(months=600, target="KOSPI")
    assert out["available"] is True, out.get("reason")
    o = out["outputs"]
    assert o["n_exceed"] >= 8
    assert o["var95"] is not None and o["es95"] is not None
    assert o["var99"] >= o["var95"], "99% VaR 이 95% 보다 작다"


def test_es_is_not_reported_when_it_diverges(monkeypatch):
    """★ξ ≥ 1 이면 기대손실이 발산한다★ 그때 큰 수를 내면 화면은 그것을 '아주 나쁜
    시나리오' 로 읽는다 — 실제로는 **정의되지 않는 값**이다. None 을 낸다."""
    from src.engine.macro_models import pinn_tail

    # 파레토(α=0.7) → ξ = 1/α ≈ 1.43, 발산 영역.
    rng = np.random.default_rng(11)
    losses = (rng.pareto(0.7, size=800) + 1.0) * 0.002
    monkeypatch.setattr(pinn_tail, "load_series",
                        lambda keys, months: {"KOSPI": _synthetic_prices(losses)})
    out = pinn_tail.run(months=800, target="KOSPI")
    assert out["available"] is True, out.get("reason")
    o = out["outputs"]
    if o["xi"] < 1.0:
        pytest.skip(f"적합된 ξ={o['xi']} 가 발산 영역이 아니다 — 이 표본으로는 잴 수 없다")
    assert o["es95"] is None and o["es99"] is None, "발산하는 ES 를 숫자로 냈다"
    assert o["var95"] is not None, "VaR 은 정의되므로 내야 한다"
    assert "발산" in out["note"], "ES 를 왜 안 냈는지 말하지 않는다"


# ── 4. 뷰 컴파일러 ──────────────────────────────────────────────────────────
def test_views_compile_to_inequalities_with_human_text():
    out = run_studio("agentic-mcp", assets=["A", "B"],
                     views=[{"asset": "A", "direction": 1, "value": 0.02}])
    assert out["available"]
    o = out["outputs"]
    assert o["n_views"] == 1 and len(o["A"]) == 1
    # +1(≥) 은 -e_A 행 / -value 우변으로 컴파일된다.
    assert o["A"][0] == [-1.0, 0.0] and o["b"][0] == pytest.approx(-0.02)
    assert "≥" in o["human"][0]


def test_not_checking_feasibility_is_reported_as_null_not_true():
    """★확인하지 않은 것과 확인해서 통과한 것은 다른 사실이다★"""
    out = run_studio("agentic-mcp", assets=["A"],
                     views=[{"asset": "A", "direction": 1, "value": 0.02}])
    assert out["outputs"]["feasible"] is None
    assert "검사하지 않았습니다" in out["note"]


def test_contradictory_views_are_caught_when_scenarios_are_given():
    rng = np.random.default_rng(5)
    R = rng.normal(0.0, 0.01, size=(500, 2)).tolist()
    out = run_studio("agentic-mcp", assets=["A", "B"], scenarios=R, views=[
        {"asset": "A", "direction": 1, "value": 0.5},     # 지지집합 밖
    ])
    assert out["available"]
    assert out["outputs"]["feasible"] is False
    assert out["outputs"]["violations"]
    assert "배분하지 마세요" in out["note"]


def test_a_view_on_an_unknown_asset_is_refused():
    out = run_studio("agentic-mcp", assets=["A"],
                     views=[{"asset": "ZZ", "direction": 1, "value": 0.01}])
    assert out["available"] is False and "ZZ" in out["reason"]


# ── 5. 라우트 ───────────────────────────────────────────────────────────────
def test_the_studio_routes_answer(client):
    r = client.get("/api/v1/macro/studios")
    assert r.status_code == 200
    assert len(r.json()["studios"]) == len(STUDIO_IDS)

    r = client.get("/api/v1/macro/studios/neural-sde")
    assert r.status_code == 200 and "available" in r.json()

    r = client.post("/api/v1/macro/studios/agentic-mcp",
                    json={"assets": ["A"], "views": []})
    assert r.status_code == 200 and r.json()["available"] is True
