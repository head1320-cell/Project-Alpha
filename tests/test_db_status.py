"""통합 DB 점검 + 적재 트리거 엔드포인트 — 구조/응답 계약 (데이터·키 유무와 무관히 200)."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from fastapi.testclient import TestClient  # noqa: E402

from main_api import app  # noqa: E402

c = TestClient(app)


def test_db_status_structure():
    r = c.get("/api/v1/data/db-status")
    assert r.status_code == 200
    j = r.json()
    assert "config" in j and "tables" in j and "tools" in j
    assert set(j["config"]) >= {"kis_real", "dart_key", "krx_key", "bok_key", "fred_key"}
    assert "ingest_running" in j


def test_ingest_target_responds():
    # KRX 미설정(샌드박스) → 스레드 즉시 no-op. 엔드포인트는 started 리스트 반환.
    r = c.post("/api/v1/data/ingest/index")
    assert r.status_code == 200
    assert isinstance(r.json().get("started"), list)


def test_ingest_unknown_target_404():
    r = c.post("/api/v1/data/ingest/bogus")
    assert r.status_code == 404
