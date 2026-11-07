"""CompanySnapshot API — 저장소가 **실제로 닿을 수 있는가** (P2-1 커밋 ②)

★저장소만 만들고 소비자를 안 만들면 감사가 지목한 그 결함을 새로 만드는 것★
이 저장소의 재발 패턴이다 — `attach_evidence` 는 M1-S 가 만들었지만 M1-V 전까지
호출자가 0 이었고, `src/engine/portfolio_rebalancer.py`(341줄)는 **오늘도** 호출자가
0 이다. 이 파일의 첫 테스트가 그 계열을 막는다: 라우터가 앱에 실제로 등록되는가.
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import src.data.company_snapshots as cs  # noqa: E402

CODE = "005930"
PREFIX = "/api/v1/company-snapshots"


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


# ── 1. ★라우터가 실제로 등록된다★ ──────────────────────────────────────────
def test_the_router_is_actually_registered(client):
    """`ROUTER_MODULES` 에 없으면 저장소는 지었지만 아무도 못 부른다."""
    paths = {(r.path, m) for r in client.app.routes
             for m in getattr(r, "methods", set())}
    assert (PREFIX, "POST") in paths
    assert (PREFIX, "GET") in paths
    assert (f"{PREFIX}/{{snapshot_id}}", "GET") in paths
    assert (f"{PREFIX}/{{snapshot_id}}", "DELETE") in paths


def test_the_existing_company_endpoints_are_untouched(client):
    """이 슬라이스는 가산이다 — 기존 세 엔드포인트는 그대로 있다."""
    paths = {r.path for r in client.app.routes}
    for p in ("/api/v1/company/{code}/valuation-sandbox",
              "/api/v1/company/{code}/financial-deep",
              "/api/v1/company/{code}/risk-deep"):
        assert p in paths


# ── 2. 생성 → 조회 → 삭제 ──────────────────────────────────────────────────
def test_create_read_delete_round_trip(client, mem_cs):
    r = client.post(PREFIX, json={"code": CODE, "price": 71000})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["recorded"] is True
    sid = body["snapshot_id"]

    got = client.get(f"{PREFIX}/{sid}")
    assert got.status_code == 200
    snap = got.json()
    assert snap["code"] == CODE and snap["snapshot_id"] == sid
    # 섹션 본문은 단건에서만 나온다.
    assert "provenance" in snap

    listed = client.get(PREFIX, params={"code": CODE}).json()["snapshots"]
    assert [s["snapshot_id"] for s in listed] == [sid]
    assert "provenance" not in listed[0]

    assert client.delete(f"{PREFIX}/{sid}").json()["deleted"] is True
    assert client.get(f"{PREFIX}/{sid}").status_code == 404


def test_a_missing_snapshot_is_404_with_a_reason(client, mem_cs):
    r = client.get(f"{PREFIX}/cs_nope")
    assert r.status_code == 404
    assert "찾을 수 없습니다" in r.json()["detail"]
    assert client.delete(f"{PREFIX}/cs_nope").status_code == 404


# ── 3. ★정직 라벨을 응답이 먼저 말한다★ ────────────────────────────────────
def test_the_create_response_states_the_pit_limitation_up_front(client, mem_cs):
    """UI 가 숨기지 못하도록 서버가 먼저 말한다 — MES 의 `from-current` 와 같은 규약."""
    body = client.post(PREFIX, json={"code": CODE, "price": 71000}).json()
    assert body["research_usage"] == "forward_only"
    assert body["data_status"] != "real"
    assert "forward_only" in body["note"]
    # 어느 섹션이 비었는지도 생성 응답에서 바로 보인다.
    assert isinstance(body["unavailable_sections"], list)


def test_the_price_source_is_stamped_by_the_server(client, mem_cs):
    """클라이언트가 출처를 주장할 수 있으면, 쓰지 않은 출처가 적힌 스냅샷이 만들어진다."""
    given = client.post(PREFIX, json={"code": CODE, "price": 71000}).json()
    assert given["price_source"] == "caller"

    omitted = client.post(PREFIX, json={"code": CODE}).json()
    assert omitted["price_source"] in ("ohlcv_loader", "unavailable")


# ── 4. DB 미가용은 500 이 아니라 정직 보고 ──────────────────────────────────
def test_a_dead_database_reports_instead_of_erroring(client, monkeypatch):
    def _boom():
        raise RuntimeError("DB 없음")
    monkeypatch.setattr(cs, "_engine", _boom)
    monkeypatch.setattr(cs, "_inited", False)

    r = client.post(PREFIX, json={"code": CODE, "price": 71000})
    assert r.status_code == 200
    assert r.json() == {"recorded": False, "snapshot_id": None,
                        "message": "DB 미가용 — 스냅샷이 저장되지 않았습니다."}
    assert client.get(PREFIX).json() == {"snapshots": []}


def test_a_bad_code_is_rejected_before_any_work(client, mem_cs):
    assert client.post(PREFIX, json={"code": "1"}).status_code == 422
    assert client.post(PREFIX, json={"code": CODE, "price": -5}).status_code == 422
