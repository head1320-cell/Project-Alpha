"""company_routes — 기업분석 심화 API smoke (mock 모드)."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from fastapi.testclient import TestClient  # noqa: E402
from main_api import app  # noqa: E402

client = TestClient(app)


def test_valuation_sandbox_endpoint():
    r = client.get("/api/v1/company/005930/valuation-sandbox", params={"price": 70000})
    assert r.status_code == 200
    body = r.json()
    assert {"unified", "assumptions", "sensitivity", "football_field", "comps"} <= set(body)
    assert len(body["sensitivity"]["grid"]) == 5


def test_valuation_sandbox_overrides():
    r = client.get("/api/v1/company/005930/valuation-sandbox",
                   params={"price": 70000, "rf": 0.04, "beta": 1.2})
    assert r.status_code == 200
    a = {x["key"]: x for x in r.json()["assumptions"]}
    assert a["rf"]["value"] == 0.04 and a["rf"]["source"] == "사용자 조정"


def test_financial_deep_endpoint():
    r = client.get("/api/v1/company/005930/financial-deep")
    assert r.status_code == 200
    assert {"qoe", "nwc", "waterfall", "dupont"} <= set(r.json())
