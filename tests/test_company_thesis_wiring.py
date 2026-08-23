"""논지 저장 + 라우트 배선 (P2-5 커밋 ②)

★이 파일이 새로 거는 것★
  1. `thesis` 는 **가산 필드** — 없으면 스냅샷 동작이 이전과 완전히 같다.
  2. 논지는 **작성된다** — 빌더가 짓지 않고, 고치면 새 스냅샷이 된다.
  3. `thesis-check` 는 **저장하지 않는다** — 다듬는 반복이 저장소를 더럽히지 않는다.
  4. 후행 컬럼 넷의 플래그가 서로 **독립**이다(P2-3 가드 확장).
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import src.data.company_snapshots as cs  # noqa: E402
import src.engine.company_snapshot_builder as bld  # noqa: E402
from src.engine.company_thesis import TIER_SCREEN_ONLY  # noqa: E402

CODE = "005930"
PRICE = 71000.0
TC = f"/api/v1/company/{CODE}/thesis-check"

THESIS = {
    "claim": "반도체 사이클 저점에서 ROE 가 정상화된다",
    "evidence": [{"section": "quality", "path": "roe", "note": "8.8%"}],
    "catalysts": [{"what": "4분기 실적", "by": "2026-12-31"}],
    "kill_conditions": [
        {"kind": "field", "field": "roe", "op": "lt", "value": 8.0},
        {"kind": "field", "field": "momentum_12_1", "op": "lt", "value": 0.0},
    ],
}


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from src.app_factory import create_app
    return TestClient(create_app())


@pytest.fixture
def mem_cs(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    monkeypatch.setattr(cs, "_engine", lambda: eng)
    monkeypatch.setattr(cs, "_inited", False)
    yield eng
    eng.dispose()


def _snap(**kw) -> dict:
    sid = bld.build_and_store(CODE, price=PRICE, **kw)
    assert sid
    out = cs.get_snapshot(sid)
    assert out is not None
    return out


# ── 1. 라우트 ───────────────────────────────────────────────────────────────
def test_the_route_is_registered_alongside_the_existing_six(client):
    paths = {r.path for r in client.app.routes}
    assert "/api/v1/company/{code}/thesis-check" in paths
    for p in ("/api/v1/company/{code}/valuation-sandbox",
              "/api/v1/company/{code}/financial-deep",
              "/api/v1/company/{code}/risk-deep",
              "/api/v1/company/{code}/reverse-dcf",
              "/api/v1/company/{code}/valuation-distribution",
              "/api/v1/company/{code}/macro-sensitivity"):
        assert p in paths, p


def test_the_check_classifies_and_lifts(client):
    b = client.post(TC, json=THESIS).json()
    assert b["available"] is True, b["reason"]
    assert b["kill_conditions"]["counts"]["screen_only"] == 1
    assert len(b["sell_conditions"]["conditions"]) == 1
    assert b["sell_conditions"]["excluded"][0]["tier"] == TIER_SCREEN_ONLY


def test_a_failed_validation_is_a_reason_not_a_500(client):
    """★검증 실패는 오류가 아니라 판정이다★"""
    r = client.post(TC, json={**THESIS, "claim": ""})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["available"] is False and b["errors"]


def test_the_check_does_not_store_anything(client, mem_cs):
    """★다듬는 반복이 저장소를 더럽히지 않는다★"""
    before = len(cs.list_snapshots(code=CODE))
    for _ in range(3):
        assert client.post(TC, json=THESIS).status_code == 200
    assert len(cs.list_snapshots(code=CODE)) == before


# ── 2. 스냅샷 컬럼 ──────────────────────────────────────────────────────────
def test_the_snapshot_carries_the_authored_thesis_and_its_classification(mem_cs):
    t = _snap(thesis=THESIS)["thesis"]
    assert t["available"] is True, t.get("reason")
    # 원문이 그대로 남는다 — "그때 무엇을 믿었는가".
    assert t["authored"]["claim"] == THESIS["claim"]
    # 분류도 함께 굳는다.
    assert t["kill_conditions"]["counts"]["screen_only"] == 1
    assert t["sell_conditions"]["conditions"]


def test_a_thesis_is_authored_not_computed(mem_cs):
    """★빌더가 논지를 짓지 않는다★ 안 주면 사유가 남고 지어내지 않는다."""
    t = _snap()["thesis"]
    assert t["available"] is False
    assert "입력" in t["reason"]
    assert "authored" not in t


def test_the_optional_field_does_not_change_the_default_snapshot(mem_cs):
    """★가산★ 논지 없이 만든 스냅샷은 이전과 같다 — 다른 섹션이 흔들리지 않는다."""
    plain = _snap()
    with_t = _snap(thesis=THESIS)
    for section in ("valuation", "implied", "valuation_dist", "macro_sensitivity",
                    "quality", "risk", "financials"):
        assert plain[section]["available"] == with_t[section]["available"], section
    assert plain["research_usage"] == with_t["research_usage"]


def test_revising_a_thesis_makes_a_new_snapshot_rather_than_editing(mem_cs):
    """★불변★ 논지를 고치면 새 기록이다 — 옛 판단이 지워지지 않는다."""
    a = bld.build_and_store(CODE, price=PRICE, thesis=THESIS)
    b = bld.build_and_store(CODE, price=PRICE,
                            thesis={**THESIS, "claim": "생각이 바뀌었다"})
    assert a != b
    assert cs.get_snapshot(a)["thesis"]["authored"]["claim"] == THESIS["claim"]
    assert cs.get_snapshot(b)["thesis"]["authored"]["claim"] == "생각이 바뀌었다"
    # 갱신 경로가 없다는 것이 불변식이다.
    assert not [n for n in dir(cs) if n.startswith(("update_", "set_"))]


def test_a_bad_thesis_does_not_kill_the_snapshot(mem_cs):
    """★검증 실패가 나머지를 굳히는 것을 막지 않는다★"""
    snap = _snap(thesis={"claim": "", "kill_conditions": [
        {"kind": "field", "field": "없는필드", "op": "lt", "value": 1}]})
    t = snap["thesis"]
    assert t["available"] is False and t["errors"]
    assert t["authored"] is not None, "실패해도 원문은 남는다"
    assert snap["valuation"]["available"] is True
    assert snap["macro_sensitivity"]["available"] is True


def test_a_dead_thesis_engine_does_not_kill_the_snapshot(mem_cs, monkeypatch):
    def _boom(thesis, **kw):
        raise RuntimeError("논지 검증 실패")
    monkeypatch.setattr("src.engine.company_thesis.validate_thesis", _boom)
    snap = _snap(thesis=THESIS)
    assert snap["thesis"]["available"] is False
    assert "RuntimeError" in snap["thesis"]["reason"]
    assert snap["valuation"]["available"] is True


def test_the_snapshot_route_accepts_the_optional_thesis(client, mem_cs):
    r = client.post("/api/v1/company-snapshots",
                    json={"code": CODE, "price": PRICE, "thesis": THESIS})
    assert r.status_code == 200, r.text
    sid = r.json()["snapshot_id"]
    assert cs.get_snapshot(sid)["thesis"]["authored"]["claim"] == THESIS["claim"]


def test_the_snapshot_route_without_a_thesis_still_works(client, mem_cs):
    r = client.post("/api/v1/company-snapshots", json={"code": CODE, "price": PRICE})
    assert r.status_code == 200, r.text
    assert cs.get_snapshot(r.json()["snapshot_id"])["thesis"]["available"] is False


# ── 3. 후행 컬럼 넷이 독립 ──────────────────────────────────────────────────
def test_the_late_column_registry_carries_all_four(mem_cs):
    assert {"implied", "valuation_dist", "macro_sensitivity", "thesis"} <= set(
        cs._LATE_COLUMNS)
    assert set(cs._late_ok) == set(cs._LATE_COLUMNS)


@pytest.mark.parametrize("missing", ["thesis", "macro_sensitivity",
                                     "valuation_dist", "implied"])
def test_a_missing_column_hides_only_its_own_section(mem_cs, monkeypatch, missing):
    """★플래그를 하나로 뭉치지 않는다★ 넷 각각이 이웃을 건드리지 않는다."""
    sid = bld.build_and_store(CODE, price=PRICE, thesis=THESIS)
    assert sid
    monkeypatch.setattr(cs, "_late_ok", {**cs._late_ok, missing: False})
    got = cs.get_snapshot(sid)
    assert got is not None
    assert missing not in got
    for other in set(cs._LATE_COLUMNS) - {missing}:
        assert other in got, f"{missing} 를 끄자 {other} 까지 사라졌다"


def test_the_evidence_sections_include_the_late_columns_but_not_thesis(mem_cs):
    """근거는 스냅샷이 실제로 갖는 섹션을 가리켜야 한다 — 목록을 코드에서 읽는다."""
    from src.engine.company_thesis import known_sections
    sections = known_sections()
    assert {"implied", "valuation_dist", "macro_sensitivity"} <= sections
    assert "thesis" not in sections
