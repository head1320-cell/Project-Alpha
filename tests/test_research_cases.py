"""ResearchCase + MacroEvidenceSnapshot 승격 + Case 사슬 (M1-S)
==============================================================================
지금까지 "무엇을 연구 중인가" 를 들고 있는 것은 **브라우저의 Study**(localStorage)뿐이었다.
그래서 다른 브라우저에서 열면 연구가 사라지고, 서버의 MES·TPV·Run 을 무엇이 묶는지
아무도 몰랐다. `ResearchCase` 가 그 묶음을 서버에 둔다.

★이 파일이 지키는 것 셋★
  1. 사슬이 실제로 이어진다 — `rc_* → rgs_* / tpv_* / rr_*` 를 양방향으로 되짚을 수 있다.
  2. **증거는 사후에 바뀌지 않는다** — MES 를 두 번 채우려 하면 거부한다. 증거가 나중에
     바뀌면 "그 결정을 내릴 때 무엇을 보고 있었는가" 에 답할 수 없고, 그게 스냅샷이
     존재하는 유일한 이유다.
  3. 저장소 장애 ≠ 없음 (R0-S 가 세운 404/503 분기를 Case 도 지킨다).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    from src.app_factory import create_app
    return TestClient(create_app())


def _make_case(client, **over) -> str:
    body = {"name": "M1 픽스처", "question": "국면이 배분을 바꾸는가?", "market": "kr"}
    body.update(over)
    r = client.post("/api/v1/research-cases", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    if not out["created"]:
        pytest.skip(f"이 환경에는 케이스 저장소가 없다: {out.get('message')}")
    return out["case_id"]


# ── 1. 생성·조회·목록 ────────────────────────────────────────────────────────
def test_a_case_carries_its_research_question(client):
    """★질문이 Case 를 Study 와 구분한다★ 질문 없는 Case 는 폴더일 뿐이다."""
    cid = _make_case(client, question="금리 역전이 방어자산 비중을 정당화하는가?")
    assert cid.startswith("rc_")
    got = client.get(f"/api/v1/research-cases/{cid}")
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["question"] == "금리 역전이 방어자산 비중을 정당화하는가?"
    assert body["status"] == "open"
    # 새 Case 는 아무것도 가리키지 않는다 — 빈 포인터를 0 이나 ""로 채우지 않는다.
    assert body["active_mes_id"] is None
    assert body["active_tpv_id"] is None
    assert body["active_run_id"] is None


def test_a_question_is_required(client):
    r = client.post("/api/v1/research-cases", json={"name": "질문 없음"})
    assert r.status_code == 422, r.text


def test_a_missing_case_is_404(client):
    assert client.get("/api/v1/research-cases/rc_nope").status_code == 404


def test_a_storage_failure_is_503_not_404(client, monkeypatch):
    """★없는 것과 못 읽는 것은 다른 사실이다★ (R0-S 분기)"""
    import src.data.research_cases as rc

    def boom(_cid):
        raise RuntimeError("storage down (test)")

    monkeypatch.setattr(rc, "get_case", boom)
    assert client.get("/api/v1/research-cases/rc_anything").status_code == 503


def test_an_empty_list_is_not_a_storage_failure(client, monkeypatch):
    import src.data.research_cases as rc
    monkeypatch.setattr(rc, "list_cases", lambda *a, **k: [])
    body = client.get("/api/v1/research-cases").json()
    assert body["available"] is True and body["cases"] == []

    def boom(*_a, **_k):
        raise RuntimeError("storage down (test)")

    monkeypatch.setattr(rc, "list_cases", boom)
    body = client.get("/api/v1/research-cases").json()
    assert body["available"] is False and body["reason"]


# ── 2. 갱신은 포인터만 ───────────────────────────────────────────────────────
def test_pointers_update_but_the_question_does_not(client):
    """★질문이 바뀌면 그건 다른 연구다★ 같은 Case 안에서 질문을 갈아끼우면 그 아래
    붙은 증거가 무엇에 대한 것인지 사라진다."""
    cid = _make_case(client)
    r = client.patch(f"/api/v1/research-cases/{cid}",
                     json={"active_mes_id": "rgs_fake", "name": "이름 변경"})
    assert r.status_code == 200, r.text
    body = client.get(f"/api/v1/research-cases/{cid}").json()
    assert body["active_mes_id"] == "rgs_fake"
    assert body["name"] == "이름 변경"

    # question 은 UpdateCaseRequest 에 아예 없다 — 보내도 무시되고 원문이 남는다.
    before = body["question"]
    client.patch(f"/api/v1/research-cases/{cid}", json={"question": "다른 질문"})
    assert client.get(f"/api/v1/research-cases/{cid}").json()["question"] == before


def test_updating_a_missing_case_is_404(client):
    r = client.patch("/api/v1/research-cases/rc_nope", json={"name": "x"})
    assert r.status_code == 404


# ── 3. ★MES 승격 — 증거는 사후에 바뀌지 않는다★ ─────────────────────────────
def _make_snapshot() -> str | None:
    from src.data.pit_macro import MacroObservation
    from src.data.regime_snapshots import create_snapshot
    obs = [MacroObservation(series_id="KR_BASE_RATE", observation_period="2026-06-30",
                            release_timestamp="2026-06-30T00:00:00Z",
                            vintage_id="2026-06-30", retrieved_at="2026-06-30T00:00:00Z",
                            value=3.5)]
    return create_snapshot(
        as_of="2026-07-01", observations=obs, growth_axis=0.2, inflation_axis=-0.1,
        phase_probabilities={"goldilocks": 0.6, "reflation": 0.2,
                             "deflation": 0.1, "stagflation": 0.1},
        stress_score=0.3, confidence=0.7, explanation="M1 픽스처")


def test_evidence_can_be_attached_once_and_only_once():
    from src.data.regime_snapshots import attach_evidence

    sid = _make_snapshot()
    if sid is None:
        pytest.skip("이 환경에는 스냅샷 저장소가 없다")

    ok = attach_evidence(sid, indicators={"VIX": {"value": 18.2, "available": True,
                                                  "source": "FRED", "as_of": "2026-06-30"}},
                         models={"causal_deepm": {"available": True, "engine": "granger"}},
                         capability_level="L2", capability_reason="torch 미설치")
    assert ok is True

    # ★두 번째는 거부★ — 증거가 사후에 바뀌면 스냅샷이 존재할 이유가 없다.
    again = attach_evidence(sid, indicators={"VIX": {"value": 99.9, "available": True}},
                            models={}, capability_level="L0", capability_reason=None)
    assert again is False, "이미 채워진 증거를 덮어썼다 — 스냅샷이 불변이 아니게 된다"

    from src.data.regime_snapshots import get_snapshot
    snap = get_snapshot(sid)
    assert snap["indicators"]["VIX"]["value"] == 18.2, "덮어쓰기가 실제로 반영됐다"
    assert snap["capability_level"] == "L2"


def test_an_indicator_key_exists_even_when_the_value_does_not():
    """★키가 사라지면 화면은 '그 지표를 안 본다' 로 읽는다★ 그건 거짓이다 —
    미가용은 `{available:false, reason}` 로 **존재**해야 한다."""
    from src.data.regime_snapshots import attach_evidence, get_snapshot

    sid = _make_snapshot()
    if sid is None:
        pytest.skip("이 환경에는 스냅샷 저장소가 없다")
    attach_evidence(
        sid,
        indicators={
            "VIX": {"value": 18.2, "available": True, "source": "FRED"},
            "VKOSPI": {"value": None, "available": False,
                       "reason": "KRX 공개 API 가 VKOSPI 를 제공하지 않습니다."},
        },
        models={}, capability_level="L2", capability_reason=None)

    ind = get_snapshot(sid)["indicators"]
    assert "VKOSPI" in ind, "미가용 지표의 키가 사라졌다"
    assert ind["VKOSPI"]["available"] is False
    assert ind["VKOSPI"]["reason"]
    assert ind["VKOSPI"]["value"] is None, "미가용인데 값을 지어냈다"


# ── 4. 사슬이 실제로 이어진다 ───────────────────────────────────────────────
def test_the_chain_links_case_to_run_and_target(client):
    from src.data.research_runs import record_run
    from src.data.target_versions import compile_target, save_target

    cid = _make_case(client)
    rid = record_run("allocation_analyze", inputs={}, outputs={}, case_id=cid)
    tv = compile_target({"005930": 60.0, "000660": 40.0}, None, case_id=cid, mes_id="rgs_x")
    tpv_id = save_target(tv)
    if rid is None or tpv_id is None:
        pytest.skip("이 환경에는 런/목표 저장소가 없다")

    r = client.get(f"/api/v1/research-cases/{cid}/chain")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["runs"]["available"] is True
    assert any(x["run_id"] == rid for x in body["runs"]["items"]), "런이 Case 로 되짚히지 않는다"
    assert body["targets"]["available"] is True
    tgt = next(x for x in body["targets"]["items"] if x["tpv_id"] == tpv_id)
    assert tgt["case_id"] == cid and tgt["mes_id"] == "rgs_x"


def test_a_case_without_pinned_evidence_says_so_instead_of_faking_it(client):
    """빈 포인터를 빈 객체로 그리면 화면은 "증거가 있는데 비었다" 로 읽는다."""
    cid = _make_case(client)
    body = client.get(f"/api/v1/research-cases/{cid}/chain").json()
    assert body["mes"]["available"] is False
    assert body["mes"]["reason"]
