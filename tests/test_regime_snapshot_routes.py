"""RegimeSnapshot API — 라우트 계약 검증.

관례: TestClient + in-memory SQLite monkeypatch (실DB·실네트워크 0).

핵심 주장:
  POST      — 생성 → snapshot_id, DB 미가용 시 recorded=False (500 아님)
  422       — as_of 이후 공표 관측치는 **거부**된다(경고 후 진행 아님)
  GET/{sid} — 관측치 신원까지 왕복
  /compare  — 경로 우선순위상 {snapshot_id} 에 잡아먹히지 않는다
  404       — 없는 스냅샷
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import src.data.regime_snapshots as rs  # noqa: E402
from src.app_factory import create_app  # noqa: E402

AS_OF = "2020-05-01"
OBS = [{
    "series_id": "DGS10", "observation_period": "2020-04-30",
    "release_timestamp": "2020-04-30", "value": 0.64,
    "vintage_id": "2020-04-30..9999-12-31", "retrieved_at": "2026-07-27T00:00:00Z",
    "data_status": "real",
}]


@pytest.fixture
def client(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    monkeypatch.setattr(rs, "_engine", lambda: eng)
    monkeypatch.setattr(rs, "_inited", False)
    with TestClient(create_app()) as c:
        yield c
    eng.dispose()


def _body(**over):
    b = {"as_of": AS_OF, "observations": OBS, "growth_axis": -1.2,
         "inflation_axis": -0.4, "phase_probabilities": {"Deflation": 0.7},
         "stress_score": 78.5, "confidence": 0.55, "explanation": "테스트"}
    b.update(over)
    return b


def test_create_then_get_roundtrip(client):
    r = client.post("/api/v1/regime-snapshots", json=_body())
    assert r.status_code == 200, r.text
    sid = r.json()["snapshot_id"]
    assert r.json()["recorded"] is True

    g = client.get(f"/api/v1/regime-snapshots/{sid}")
    assert g.status_code == 200
    d = g.json()
    assert d["as_of"] == AS_OF
    assert d["stress_score"] == pytest.approx(78.5)
    assert d["observations"][0]["release_timestamp"] == "2020-04-30"
    assert d["research_usage"] == "backtest_eligible"


def test_lookahead_observation_is_rejected_422(client):
    late = [{**OBS[0], "series_id": "GDPC1", "release_timestamp": "2020-06-25"}]
    r = client.post("/api/v1/regime-snapshots", json=_body(observations=late))
    assert r.status_code == 422, f"거부되지 않았다: {r.status_code} {r.text}"
    assert "GDPC1" in r.text
    # 거부됐으면 저장도 되지 않았어야 한다
    assert client.get("/api/v1/regime-snapshots").json()["snapshots"] == []


def test_compare_is_not_swallowed_by_the_id_route(client):
    """/compare 가 /{snapshot_id} 보다 먼저 선언되어 있어야 한다 — 아니면 404 가 난다."""
    a = client.post("/api/v1/regime-snapshots", json=_body(stress_score=10.0)).json()["snapshot_id"]
    b = client.post("/api/v1/regime-snapshots", json=_body(stress_score=30.0)).json()["snapshot_id"]

    r = client.get("/api/v1/regime-snapshots/compare", params={"a": a, "b": b})
    assert r.status_code == 200, f"compare 가 ID 라우트에 잡아먹혔다: {r.text}"
    assert r.json()["delta"]["stress_score"] == pytest.approx(20.0)
    assert r.json()["model_version_changed"] is False


def test_compare_missing_snapshot_404(client):
    a = client.post("/api/v1/regime-snapshots", json=_body()).json()["snapshot_id"]
    r = client.get("/api/v1/regime-snapshots/compare", params={"a": a, "b": "rgs_nope"})
    assert r.status_code == 404
    assert "rgs_nope" in r.text


def test_list_summary_excludes_observation_array(client):
    client.post("/api/v1/regime-snapshots", json=_body())
    items = client.get("/api/v1/regime-snapshots").json()["snapshots"]
    assert len(items) == 1
    assert "observations" not in items[0], "목록에까지 관측치를 실으면 payload 가 비대해진다"
    assert items[0]["observation_count"] == 1


def test_get_missing_returns_404(client):
    assert client.get("/api/v1/regime-snapshots/rgs_nope").status_code == 404


def test_db_unavailable_reports_honestly_not_500(client, monkeypatch):
    def boom():
        raise RuntimeError("no db")
    monkeypatch.setattr(rs, "_engine", boom)
    r = client.post("/api/v1/regime-snapshots", json=_body())
    assert r.status_code == 200, "DB 미가용을 500 으로 터뜨리면 안 된다"
    assert r.json()["recorded"] is False
    assert r.json()["snapshot_id"] is None
