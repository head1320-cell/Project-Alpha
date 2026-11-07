"""경제노출 → 상품 구현 계층 배선 (Brief §7.1/7.2)

★이 파일이 거는 것★
  1. 카탈로그가 **무엇을 모르는지**까지 낸다.
  2. 구현 결과가 상품마다 **어느 노출에서 왔는지** 남긴다.
  3. 알 수 없는 노출은 500 이 아니라 사유다.
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402

CATALOG = "/api/v1/allocation/exposures"
IMPLEMENT = "/api/v1/allocation/implement"
LEGACY = ("/api/v1/allocation/analyze",
          "/api/v1/allocation/rebalance-decision",
          "/api/v1/allocation/target-versions")


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from src.app_factory import create_app
    return TestClient(create_app())


# ── 1. 라우트 ───────────────────────────────────────────────────────────────
def test_the_routes_are_registered_and_the_neighbours_are_intact(client):
    paths = {r.path for r in client.app.routes}
    assert CATALOG in paths and IMPLEMENT in paths
    for p in LEGACY:
        assert p in paths, p


# ── 2. ★카탈로그는 모르는 것도 낸다★ ─────────────────────────────────────
def test_the_catalog_lists_exposures_with_candidates(client):
    b = client.get(CATALOG).json()
    assert b["available"] is True
    names = {r["exposure"] for r in b["exposures"]}
    assert {"equity", "equity_us", "duration", "credit", "commodity"} <= names
    for row in b["exposures"]:
        assert row["primary"], row["exposure"]
        assert row["label"] and row["note"]


def test_the_catalog_names_what_it_cannot_measure(client):
    """★빈칸이 아니라 왜 없는지가 정보다★"""
    b = client.get(CATALOG).json()
    un = b["unavailable_criteria"]
    assert "expense_ratio" in un and "corporate_actions" in un
    assert "저장소에 없습니다" in un["expense_ratio"]


def test_the_catalog_exposes_the_scoring_weights(client):
    """점수 공식을 숨기지 않는다."""
    w = client.get(CATALOG).json()["score_weights"]
    assert set(w) == {"liquidity", "cost", "history"}
    assert sum(w.values()) == pytest.approx(1.0)


def test_exposures_without_kr_candidates_declare_the_fallback(client):
    """★조용히 해외로 넘어가지 않는다★"""
    rows = {r["exposure"]: r for r in client.get(CATALOG).json()["exposures"]}
    assert rows["duration"]["market_fallback"], "국내 후보가 없다는 사실을 말한다"
    assert rows["duration"]["kr"] == []
    # 국내 후보가 있는 노출은 폴백이 없다(짝).
    assert rows["equity_us"]["market_fallback"] is None
    assert rows["equity_us"]["kr"], "KR 후보가 실제로 있다"


def test_alternatives_are_shown_not_hidden(client):
    rows = {r["exposure"]: r for r in client.get(CATALOG).json()["exposures"]}
    assert rows["equity_us"]["alternatives"], "해외 대안을 감추지 않는다"


# ── 3. ★구현은 출처를 남긴다★ ───────────────────────────────────────────
def _impl(client, exposures: dict, **kw) -> dict:
    r = client.post(IMPLEMENT, json={"exposures": exposures, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def test_implementation_maps_exposures_to_instruments(client):
    b = _impl(client, {"equity_us": 40.0, "duration": 30.0})
    assert b["available"] is True
    assert b["holdings"]
    by = {ln["exposure"]: ln["instrument"] for ln in b["lines"]}
    assert set(by) == {"equity_us", "duration"}
    for code in by.values():
        assert code in b["holdings"]


def test_a_kr_listed_instrument_is_chosen_for_us_equity(client):
    """★KR 상장 우선★ 미국 대형주 노출도 국내 상장으로 먼저 구현한다."""
    b = _impl(client, {"equity_us": 50.0})
    ln = b["lines"][0]
    assert ln["foreign_listing"] is False
    assert ln["instrument"] in ("360750", "381180")


def test_a_foreign_only_exposure_is_marked(client):
    b = _impl(client, {"duration": 50.0})
    ln = b["lines"][0]
    assert ln["instrument"] == "TLT"
    assert ln["foreign_listing"] is True
    assert ln["market_fallback"]


def test_the_weights_are_preserved_and_traceable(client):
    """★합만 재지 않는다★ 각 상품 비중이 어느 노출의 합인지까지 맞아야 한다."""
    from collections import defaultdict
    b = _impl(client, {"equity_us": 40.0, "duration": 30.0, "commodity": 10.0})
    rebuilt = defaultdict(float)
    for ln in b["lines"]:
        rebuilt[ln["instrument"]] += ln["weight_pct"]
    assert dict(rebuilt) == pytest.approx(b["holdings"])
    assert b["placed_pct"] == pytest.approx(80.0)


def test_an_unknown_exposure_is_a_reason_not_a_500(client):
    """★알 수 없는 노출로 요청 전체를 죽이지 않는다★"""
    b = _impl(client, {"equity_us": 40.0, "없는노출": 25.0})
    assert b["available"] is True, "나머지는 구현된다"
    assert "없는노출" in b["unresolved"] and b["unresolved"]["없는노출"]
    assert b["unplaced_pct"] == pytest.approx(25.0)


def test_unplaced_weight_is_not_redistributed(client):
    """★재분배하면 요청하지 않은 노출이 커진다★"""
    b = _impl(client, {"equity_us": 40.0, "없는노출": 25.0})
    assert sum(b["holdings"].values()) == pytest.approx(40.0)
    assert b["requested_pct"] == pytest.approx(65.0)


def test_the_price_source_is_disclosed(client):
    """mock 인지 실데이터인지 응답이 말한다."""
    b = _impl(client, {"equity_us": 40.0})
    assert b["price_source"] in ("mock", "db", "unknown")


def test_empty_exposures_are_rejected(client):
    assert client.post(IMPLEMENT, json={"exposures": {}}).status_code == 422
