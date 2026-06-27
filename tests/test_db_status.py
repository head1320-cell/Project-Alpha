"""통합 DB 점검 엔드포인트 — 구조/설정/도구별 준비상태 (데이터 유무와 무관히 200)."""
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


def test_ingest_index_trigger_responds():
    r = c.post("/api/v1/data/ingest/index")
    assert r.status_code == 200 and "started" in r.json()   # 키 없으면 started=False(샌드박스)


def test_ingest_etf_trigger_responds():
    r = c.post("/api/v1/data/ingest/etf")
    assert r.status_code == 200 and "started" in r.json()
