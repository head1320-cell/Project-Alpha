"""ResearchRun ↔ RegimeSnapshot 연결 (AAS Phase 4a).

왜 필요한가: 런을 나중에 다시 열었을 때 **어떤 매크로 국면 아래에서 내린 결정인지**
알 수 없으면 재현이 성립하지 않는다. 지금까지 런에는 그 링크가 없었다.

설계 결정 하나가 여기서 검증된다:
  research_runs 의 목록 조회(list_runs)는 `inputs` 를 **제외**하고 `snapshot` 은 포함한다
  (src/data/research_runs.py::_row_to_dict, full=False). 따라서 링크를 inputs 에만 두면
  런 목록에서 스냅샷을 볼 수 없다 → **snapshot 에도 넣어야** 재열기 UI 가 동작한다.

관례: TestClient + in-memory SQLite monkeypatch (실DB·실네트워크 0).
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import src.data.regime_snapshots as rs  # noqa: E402
import src.data.research_runs as rr  # noqa: E402
import src.data.timing_rules as tr  # noqa: E402
from src.app_factory import create_app  # noqa: E402

TICKERS = ["005930", "000660"]


@pytest.fixture
def client(monkeypatch):
    """두 스토어를 같은 in-memory DB 로 격리."""
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    for mod in (rs, rr, tr):
        monkeypatch.setattr(mod, "_engine", lambda: eng)
        monkeypatch.setattr(mod, "_inited", False)
    monkeypatch.setattr(rs, "_has_regime_cols", False)
    monkeypatch.setattr(tr, "_has_version", False)
    with TestClient(create_app()) as c:
        yield c
    eng.dispose()


def _make_snapshot(client) -> str:
    r = client.post("/api/v1/regime-snapshots/from-current", params={"market": "kr"})
    assert r.status_code == 200, r.text
    return r.json()["snapshot_id"]


def _analyze(client, **over):
    body = {"tickers": TICKERS, "model": "mvo", "record_run": True, "run_name": "링크 테스트"}
    body.update(over)
    return client.post("/api/v1/allocation/analyze", json=body)


# ─── 1. 링크가 런에 실린다 ────────────────────────────────────────────────────
def test_run_records_the_snapshot_id(client):
    sid = _make_snapshot(client)
    r = _analyze(client, regime_snapshot_id=sid)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("run_recorded") is True, "런이 기록되지 않으면 링크 검증이 공허하다"
    rid = body["run_id"]

    got = client.get(f"/api/v1/research-runs/{rid}").json()
    assert got["inputs"].get("regime_snapshot_id") == sid
    assert got["snapshot"].get("regime_snapshot_id") == sid, (
        "snapshot 에도 넣어야 런 목록(inputs 제외)에서 스냅샷을 볼 수 있다"
    )


def test_snapshot_id_is_visible_in_the_run_list(client):
    """★재열기 UI 의 전제★ — 목록은 inputs 를 안 주므로 snapshot 에 있어야 한다."""
    sid = _make_snapshot(client)
    _analyze(client, regime_snapshot_id=sid)

    runs = client.get("/api/v1/research-runs").json()["runs"]
    assert runs, "런 목록이 비었다"
    assert "inputs" not in runs[0], "목록이 inputs 를 준다면 이 테스트의 전제가 바뀐 것"
    assert runs[0]["snapshot"].get("regime_snapshot_id") == sid


# ─── 2. 없는 스냅샷은 조용히 흘리지 않는다 ────────────────────────────────────
def test_unknown_snapshot_id_is_rejected(client):
    r = _analyze(client, regime_snapshot_id="rgs_0_deadbeef")
    assert r.status_code == 422, f"없는 스냅샷을 그냥 기록하면 안 된다: {r.status_code}"
    assert "rgs_0_deadbeef" in r.text


def test_rejection_does_not_record_a_run(client):
    _analyze(client, regime_snapshot_id="rgs_0_deadbeef")
    assert client.get("/api/v1/research-runs").json()["runs"] == [], (
        "거부된 요청이 런을 남기면 안 된다"
    )


# ─── 3. 링크가 없어도 기존 동작은 그대로 ──────────────────────────────────────
def test_analyze_without_snapshot_still_works(client):
    r = _analyze(client)
    assert r.status_code == 200, r.text
    rid = r.json()["run_id"]
    got = client.get(f"/api/v1/research-runs/{rid}").json()
    assert got["snapshot"].get("regime_snapshot_id") is None


# ─── 4. Phase 7: 규칙 세트 **버전** 도 같은 재현성 ID 다 ──────────────────────
def _make_rule_set(rules=None) -> str:
    sid = tr.save_rule_set("타이밍 세트", "kr",
                           rules or [{"factor_id": "curve_slope"}])
    assert sid, "규칙 세트 저장 실패 — 이후 검증이 공허해진다"
    return sid


def test_run_records_the_rule_set_version(client):
    sid = _make_rule_set()
    r = _analyze(client, timing_rule_set_id=sid, timing_rule_set_version=1)
    assert r.status_code == 200, r.text
    rid = r.json()["run_id"]
    got = client.get(f"/api/v1/research-runs/{rid}").json()
    assert got["snapshot"].get("timing_rule_set_id") == sid
    assert got["snapshot"].get("timing_rule_set_version") == 1


def test_omitted_version_is_stamped_with_the_current_one(client):
    """버전을 안 보내면 서버가 **그때의 현재 버전**을 각인한다 — 나중에 세트가 바뀌어도
    이 런이 어느 내용으로 계산되었는지 남는다."""
    sid = _make_rule_set([{"factor_id": "curve_slope"}])
    tr.save_rule_set("타이밍 세트", "kr", [{"factor_id": "disparity"}], set_id=sid)  # v2

    r = _analyze(client, timing_rule_set_id=sid)
    assert r.status_code == 200, r.text
    rid = r.json()["run_id"]
    got = client.get(f"/api/v1/research-runs/{rid}").json()
    assert got["snapshot"].get("timing_rule_set_version") == 2


def test_the_stamped_version_still_resolves_after_the_set_changes(client):
    """★재열기 = 복원★ — v1 로 만든 런은 세트가 v3 이 된 뒤에도 v1 규칙을 되찾는다."""
    sid = _make_rule_set([{"factor_id": "curve_slope"}])
    r = _analyze(client, timing_rule_set_id=sid, timing_rule_set_version=1)
    rid = r.json()["run_id"]

    tr.save_rule_set("타이밍 세트", "kr", [{"factor_id": "disparity"}], set_id=sid)
    tr.save_rule_set("타이밍 세트", "kr", [{"factor_id": "vol_breakout"}], set_id=sid)

    snap = client.get(f"/api/v1/research-runs/{rid}").json()["snapshot"]
    restored = tr.get_rule_set_version(snap["timing_rule_set_id"],
                                       snap["timing_rule_set_version"])
    assert restored is not None
    assert restored["rules"] == [{"factor_id": "curve_slope"}], (
        "런이 가리키는 버전이 최신본으로 바뀌어 버리면 그 런은 재현 불가다"
    )
    assert tr.get_rule_set(sid)["version"] == 3, "현재 버전은 별도로 전진한다"


def test_unknown_rule_set_version_is_rejected(client):
    sid = _make_rule_set()
    r = _analyze(client, timing_rule_set_id=sid, timing_rule_set_version=99)
    assert r.status_code == 422, f"없는 버전을 그냥 기록하면 안 된다: {r.status_code}"
    assert "99" in r.text


def test_unknown_rule_set_id_is_rejected(client):
    r = _analyze(client, timing_rule_set_id="tr_0_deadbeef")
    assert r.status_code == 422
    assert "tr_0_deadbeef" in r.text


def test_rule_set_rejection_does_not_record_a_run(client):
    _analyze(client, timing_rule_set_id="tr_0_deadbeef")
    assert client.get("/api/v1/research-runs").json()["runs"] == []


def test_analyze_without_a_rule_set_still_works(client):
    r = _analyze(client)
    assert r.status_code == 200, r.text
    snap = client.get(f"/api/v1/research-runs/{r.json()['run_id']}").json()["snapshot"]
    assert snap.get("timing_rule_set_id") is None
    assert snap.get("timing_rule_set_version") is None
