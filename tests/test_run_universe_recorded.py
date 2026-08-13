"""유니버스 구성 종목을 런에 남긴다 (P1-B)
==============================================================================
실측된 결함: `alpha_routes.py:177` 이 `{"universe": "kospi50", "tickers_n": 50}` 만
적었다. 유니버스는 `_resolve_universe_capped`(:143)가 **요청 시점의**
`resolve_universe()` 로 푸는 것이라, 레지스트리가 바뀌면 같은 `"kospi50"` 이 다른
종목 집합을 가리킨다. 개수만으로는 "그때 그 50종목"을 되살릴 수 없다.

팩터 포트폴리오는 더 나쁘다 — 후보풀이 `sample_factors`(`snapshot_db.py:165`)에서
오는데 그 SQL 에 `ORDER BY` 가 없어 `list(merged.values())[:limit]` 가 안정적이지
않다. 여기서는 **비결정성을 고치지 않고 기록한다**(고치면 기업분석 퍼센타일 분포에
파급된다). 그래서 응답이 후보 목록을 그대로 내는지를 잠근다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from src.app_factory import create_app
    return TestClient(create_app())


# ── 1. 알파 검증 런은 개수가 아니라 목록을 남긴다 ───────────────────────────
def test_alpha_validate_records_the_constituents_not_only_the_count(client, monkeypatch):
    """★개수만으로는 재현할 수 없다★ — 목록과 개수가 함께, 그리고 서로 일치해야 한다."""
    captured: dict = {}

    import src.api.alpha_routes as ar

    def fake_record(kind, inputs, outputs, **kw):
        captured["kind"] = kind
        captured["inputs"] = inputs
        return "rr_fake"

    # 유니버스 해소를 고정해 이 테스트가 레지스트리 상태에 의존하지 않게 한다.
    fixed = ["005930", "000660", "035420", "051910", "005380",
             "068270", "005490", "012330", "028260", "105560"]
    monkeypatch.setattr(ar, "_resolve_universe_capped", lambda req: list(fixed))
    monkeypatch.setattr("src.data.research_runs.record_run", fake_record)

    r = client.post("/api/v1/alpha-lab/validate", json={
        "expr": "rank(mom_12m)", "tickers": fixed, "months": 12, "record_run": True})
    assert r.status_code == 200, r.text
    if r.json().get("error"):
        pytest.skip(f"이 환경에서는 알파 검증이 돌지 않는다: {r.json().get('message')}")

    assert captured.get("kind") == "alpha_validate", "런이 기록되지 않았다"
    inp = captured["inputs"]
    assert "tickers" in inp, "구성 종목이 기록되지 않았다 — 개수만으로는 재현 불가"
    assert inp["tickers"] == fixed
    # `tickers_n` 은 기존 소비자 호환으로 유지되고, 목록과 어긋나면 안 된다.
    assert inp["tickers_n"] == len(inp["tickers"])


# ── 2. 팩터 포트폴리오는 후보풀을 응답에 낸다 ───────────────────────────────
def test_factor_portfolio_reports_the_candidate_pool_it_actually_used(client):
    r = client.post("/api/v1/allocation/factor-portfolio", json={
        "factors": [{"id": "per", "weight": 1.0}], "top_k": 5, "sample_size": 80})
    assert r.status_code == 200, r.text
    body = r.json()
    if body.get("error"):
        pytest.skip(f"이 환경에는 팩터 표본이 없다: {body.get('message')}")

    uni = body.get("universe")
    assert uni is not None, "후보풀이 응답에 없다 — 무엇 중에서 골랐는지 재현할 수 없다"
    assert isinstance(uni["codes"], list) and uni["codes"], "후보 목록이 비었다"
    # 개수 필드와 실제 목록이 어긋나면 둘 중 하나가 거짓이다.
    assert uni["resolved_n"] == len(uni["codes"]) == body["candidates"]
    # 선정된 종목은 반드시 후보풀 안에 있어야 한다 — 밖에서 나왔다면 후보풀 기록이 거짓이다.
    pool = set(uni["codes"])
    for h in body["holdings"]:
        assert h["code"] in pool, f"{h['code']} 가 기록된 후보풀 밖에서 선정됐다"
