"""ResearchRun 완결성 — 시나리오 팩 신원 (스펙 §5 Journal, Phase 10b).

런 하나가 재현 좌표 전부를 들어야 한다: 스냅샷 · 룰셋(+버전) · **시나리오 팩(+해시)** ·
제약 · 근거. Phase 4·7c 가 앞의 둘을, 이 파일이 팩을 고정한다(근거는 저널 항목 링크라
백엔드 계약이 이미 있다 — `GET /journal/by-run/{run_id}`).

★해시는 요청에서 받지 않는다★
서버가 지금 해석한 팩의 신원을 스탬프한다. 클라이언트가 해시를 주장할 수 있으면 **실제로
쓰지 않은 팩 버전을 썼다고 적힌 런**이 만들어지고, 그건 재현 좌표가 아니라 알리바이다.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

import src.data.journal_store as js
import src.data.research_runs as rr
import src.data.scenario_packs_store as store
from src.app_factory import create_app
from src.engine.scenario_packs import PACKS

ANALYZE = "/api/v1/allocation/analyze"
SAVE = "/api/v1/allocation/scenario-packs"


@pytest.fixture
def client(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    # 저널도 같은 인메모리 DB 를 쓴다 — 안 걸어 두면 근거 링크 테스트가 실제 DB 부재로
    # 조용히 통과하고(모든 조회가 None), "링크가 산다" 를 전혀 검증하지 못한다.
    for mod in (rr, store, js):
        monkeypatch.setattr(mod, "_engine", lambda: eng)
        monkeypatch.setattr(mod, "_inited", False)
    with TestClient(create_app()) as c:
        yield c


def _analyze(**kw):
    base = {"tickers": ["005930", "000660"], "model": "mvo",
            "record_run": True, "run_name": "t"}
    base.update(kw)
    return base


# ═══════════════════════════════════════════════════════════════════════════════
# 1. 팩 신원이 런에 박힌다 — 서버가 스탬프한다
# ═══════════════════════════════════════════════════════════════════════════════
def test_a_recorded_run_stamps_the_pack_hash(client):
    r = client.post(ANALYZE, json=_analyze(scenario_pack_id="semi_selloff"))
    assert r.status_code == 200, r.text
    rid = r.json().get("run_id")
    assert rid, "런이 기록되지 않았습니다(DB 미가용)"

    snap = client.get(f"/api/v1/research-runs/{rid}").json()["snapshot"]
    assert snap["scenario_pack_id"] == "semi_selloff"
    assert snap["scenario_pack_hash"] == PACKS["semi_selloff"].content_hash, (
        "서버가 현재 팩의 해시를 찍지 않았습니다")


def test_the_client_cannot_dictate_the_hash(client):
    """★해시를 주장할 수 있으면 재현 좌표가 알리바이가 된다★

    요청에 `scenario_pack_hash` 를 실어 보내도 스키마가 버리고, 런에는 서버가 계산한 값만
    남아야 한다.
    """
    r = client.post(ANALYZE, json=_analyze(scenario_pack_id="semi_selloff",
                                           scenario_pack_hash="deadbeefcafe"))
    assert r.status_code == 200, r.text
    snap = client.get(f"/api/v1/research-runs/{r.json()['run_id']}").json()["snapshot"]
    assert snap["scenario_pack_hash"] == PACKS["semi_selloff"].content_hash
    assert snap["scenario_pack_hash"] != "deadbeefcafe"


def test_a_saved_pack_is_stamped_with_its_stored_hash(client):
    saved = client.post(SAVE, json={"pack": {
        "label": "내 팩", "market": -6.0, "factors": {"size": -4.0},
        "assumptions": {}}}).json()
    r = client.post(ANALYZE, json=_analyze(scenario_pack_id=saved["pack_id"]))
    assert r.status_code == 200, r.text
    snap = client.get(f"/api/v1/research-runs/{r.json()['run_id']}").json()["snapshot"]
    assert snap["scenario_pack_id"] == saved["pack_id"]
    assert snap["scenario_pack_hash"] == saved["content_hash"]


# ═══════════════════════════════════════════════════════════════════════════════
# 2. 없는 팩은 계산 **전에** 거부한다
# ═══════════════════════════════════════════════════════════════════════════════
def test_an_unknown_pack_is_422_and_names_it(client):
    """복원할 수 없는 팩을 가리키는 런은 "팩 X 로 검증했다" 고 적혀 있어도 그 X 가 없다."""
    r = client.post(ANALYZE, json=_analyze(scenario_pack_id="nope_not_a_pack"))
    assert r.status_code == 422, r.text
    assert "nope_not_a_pack" in r.json()["detail"]


def test_the_pack_check_happens_before_the_computation(client, monkeypatch):
    """★값비싼 계산 뒤가 아니라 앞에서 막는다★ (스냅샷·룰셋 검증과 같은 자리)"""
    import src.api.allocation_routes as ar
    called: list[str] = []
    real = ar._load_clean_returns
    monkeypatch.setattr(ar, "_load_clean_returns",
                        lambda *a, **k: called.append("x") or real(*a, **k))
    r = client.post(ANALYZE, json=_analyze(scenario_pack_id="nope"))
    assert r.status_code == 422
    assert called == [], "거부 전에 수익률 로딩이 이미 돌았습니다"


def test_a_deleted_pack_makes_a_new_run_fail_loudly(client):
    """저장 팩을 지우면 그 id 로는 더 이상 런을 기록할 수 없다 — 조용히 비우지 않는다."""
    saved = client.post(SAVE, json={"pack": {
        "label": "임시", "market": -3.0, "factors": {"size": -1.0},
        "assumptions": {}}}).json()
    client.delete(f"{SAVE}/{saved['pack_id']}")
    r = client.post(ANALYZE, json=_analyze(scenario_pack_id=saved["pack_id"]))
    assert r.status_code == 422 and saved["pack_id"] in r.json()["detail"]


# ═══════════════════════════════════════════════════════════════════════════════
# 3. 팩 없이도 런은 기록된다 — 팩은 선택이다
# ═══════════════════════════════════════════════════════════════════════════════
def test_a_run_without_a_pack_still_records(client):
    r = client.post(ANALYZE, json=_analyze())
    assert r.status_code == 200, r.text
    snap = client.get(f"/api/v1/research-runs/{r.json()['run_id']}").json()["snapshot"]
    assert snap["scenario_pack_id"] is None
    # ★없는 것과 모르는 것을 같은 말로 적지 않는다★ 해시도 None 이지 빈 문자열이 아니다.
    assert snap["scenario_pack_hash"] is None


# ═══════════════════════════════════════════════════════════════════════════════
# 4. 근거는 링크다 — 사본이 아니다
# ═══════════════════════════════════════════════════════════════════════════════
def test_the_rationale_is_reachable_from_the_run(client):
    """저널 항목이 근거의 단일 진실이고 런은 `run_id` 로 연결만 한다.

    복사해 두면 사용자가 저널을 고쳤을 때 두 곳이 조용히 어긋나고, 어느 쪽이 맞는지
    화면만 봐서는 알 수 없다.
    """
    rid = client.post(ANALYZE, json=_analyze()).json()["run_id"]
    # 근거가 없을 때: 200 + entry=None (404 가 아니다 — "없음" 은 오류가 아니다)
    r = client.get(f"/api/v1/allocation/journal/by-run/{rid}")
    assert r.status_code == 200, r.text
    assert r.json()["entry"] is None

    client.post("/api/v1/allocation/journal", json={
        "run_id": rid, "title": "이번 결정",
        "record": {"thesis": "금리 정점 통과", "decision": "듀레이션 확대"}})
    got = client.get(f"/api/v1/allocation/journal/by-run/{rid}").json()["entry"]
    assert got is not None
    assert got["record"]["thesis"] == "금리 정점 통과"
    assert got["run_id"] == rid


def test_editing_the_journal_changes_what_the_run_shows(client):
    """★사본이 아니라 링크라는 것의 실질★ 고치면 런 쪽에서도 바뀐 값이 보인다."""
    rid = client.post(ANALYZE, json=_analyze()).json()["run_id"]
    made = client.post("/api/v1/allocation/journal", json={
        "run_id": rid, "title": "t", "record": {"thesis": "처음 생각"}}).json()
    eid = made["entry_id"]

    client.post("/api/v1/allocation/journal", json={
        "entry_id": eid, "run_id": rid, "title": "t",
        "record": {"thesis": "고친 생각"}})
    got = client.get(f"/api/v1/allocation/journal/by-run/{rid}").json()["entry"]
    assert got["record"]["thesis"] == "고친 생각", (
        "런이 오래된 사본을 보고 있습니다 — 링크가 아니라 복사입니다")
