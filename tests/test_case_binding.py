"""Case ↔ 아티팩트 양방향 바인딩 (M2-D)
==============================================================================
M1-U 가 `caseApi.patch` 를 정의했지만 **호출자가 0건**이었다(실측). 그래서 케이스의 세
포인터는 어떤 경로로도 채워지지 않았고, `CaseBar` 가 읽는 값은 언제나 null,
`/chain` 의 `mes` 는 언제나 "고정된 증거 없음" 이었다 — 사슬을 그리는 화면은 있는데
사슬을 잇는 손이 없었다.

★서버가, 아티팩트를 만든 그 요청 안에서 전진시킨다★
클라이언트가 "만들고 → PATCH" 로 두 번 치면 **반쪽 실패**가 가능해, 저장되지 않은 목표를
가리키는 케이스가 남는다. 그리고 결과를 `case_bound` 로 되돌려 조용히 삼키지 않는다.
"""

from __future__ import annotations

import pytest

from src.data.research_cases import advance_pointer, create_case, get_case


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from src.app_factory import create_app
    return TestClient(create_app())


@pytest.fixture()
def case_id():
    cid = create_case("M2-D 바인딩", "포인터가 실제로 전진하는가?")
    if not cid:
        pytest.skip("연구 케이스 저장소를 쓸 수 없는 환경")
    yield cid


# ── 1. 헬퍼의 계약 ─────────────────────────────────────────────────────────

def test_no_case_is_not_a_failure(case_id):
    """케이스 없이 도는 것은 결함이 아니다 — 사유도 없다."""
    r = advance_pointer(None, "tpv", "tpv_x")
    assert r == {"ok": False, "reason": None}


def test_an_unsaved_artifact_does_not_move_the_pointer(case_id):
    """★없는 것을 가리키는 케이스는 사슬이 아니라 거짓 사슬이다★"""
    r = advance_pointer(case_id, "tpv", None)
    assert r["ok"] is False and "저장되지 않아" in r["reason"]
    assert get_case(case_id)["active_tpv_id"] is None


def test_an_unknown_case_is_reported_not_silently_ignored():
    r = advance_pointer("rc_does_not_exist", "run", "rr_1")
    assert r["ok"] is False and "찾을 수 없" in r["reason"]


@pytest.mark.parametrize("kind,field", [("mes", "active_mes_id"),
                                        ("tpv", "active_tpv_id"),
                                        ("run", "active_run_id")])
def test_each_pointer_kind_moves_its_own_field(case_id, kind, field):
    assert advance_pointer(case_id, kind, f"{kind}_abc")["ok"] is True
    c = get_case(case_id)
    assert c[field] == f"{kind}_abc"
    # 다른 포인터는 건드리지 않는다.
    for other in ("active_mes_id", "active_tpv_id", "active_run_id"):
        if other != field:
            assert c[other] is None


# ── 2. ★TPV 라우트가 실제로 전진시킨다★ (이 단계 이전에는 반드시 red) ──────

def _tpv(client, **kw):
    body = {"base_weights": {"005930": 60.0, "000660": 40.0}}
    body.update(kw)
    return client.post("/api/v1/allocation/target-versions", json=body)


def test_creating_a_target_version_advances_the_case_pointer(client, case_id):
    r = _tpv(client, case_id=case_id)
    assert r.status_code == 200, r.text
    b = r.json()
    if not b["saved"]:
        pytest.skip("목표 버전 저장소를 쓸 수 없는 환경")
    assert b["case_bound"]["ok"] is True
    assert get_case(case_id)["active_tpv_id"] == b["tpv_id"]


def test_a_dry_run_compile_does_not_move_the_pointer(client, case_id):
    """★화면 표시용 컴파일은 사슬을 바꾸지 않는다★ 슬라이더를 움직일 때마다 케이스의
    활성 목표가 바뀌면 감사 기록이 노이즈가 된다 (R0 이 `dry_run` 을 둔 이유)."""
    r = _tpv(client, case_id=case_id, dry_run=True)
    assert r.status_code == 200, r.text
    assert r.json()["case_bound"]["ok"] is False
    assert get_case(case_id)["active_tpv_id"] is None


def test_a_research_only_target_still_advances_the_pointer(client, case_id):
    """실행 불가여도 그것이 이 케이스의 **최신 목표**라는 사실은 참이다.

    실행 가능 여부는 TPV 자신의 `status` 가 말한다 — 감추는 쪽이 더 거짓이다.
    """
    r = _tpv(client, case_id=case_id, neutralized=True)
    b = r.json()
    if not b["saved"]:
        pytest.skip("목표 버전 저장소를 쓸 수 없는 환경")
    assert b["status"] == "research_only" and b["status_reason"]
    assert b["case_bound"]["ok"] is True
    assert get_case(case_id)["active_tpv_id"] == b["tpv_id"]


def test_without_a_case_id_the_route_behaves_exactly_as_before(client):
    r = _tpv(client)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["case_bound"] == {"ok": False, "reason": None}


# ── 3. 런과 MES 도 같은 규칙 ───────────────────────────────────────────────

def test_recording_a_run_advances_the_active_run_pointer(client, case_id):
    r = client.post("/api/v1/research-runs", json={
        "kind": "allocation_analyze", "inputs": {}, "outputs": {}, "case_id": case_id})
    assert r.status_code == 200, r.text
    b = r.json()
    if not b["recorded"]:
        pytest.skip("연구 기록 저장소를 쓸 수 없는 환경")
    assert b["case_bound"]["ok"] is True
    assert get_case(case_id)["active_run_id"] == b["run_id"]


def test_creating_a_snapshot_with_a_case_pins_it_as_the_macro_evidence(client, case_id):
    r = client.post(f"/api/v1/regime-snapshots/from-current?market=kr&case_id={case_id}")
    if r.status_code != 200:
        pytest.skip(f"이 환경에서 스냅샷을 만들 수 없다: {r.status_code}")
    b = r.json()
    if not b["recorded"]:
        pytest.skip("스냅샷 저장소를 쓸 수 없는 환경")
    assert b["case_bound"]["ok"] is True
    assert get_case(case_id)["active_mes_id"] == b["snapshot_id"]


# ── 4. ★사슬이 실제로 이어진다★ 양방향 (아티팩트→케이스, 케이스→아티팩트) ──

def test_the_chain_endpoint_returns_the_artifacts_bound_to_this_case(client, case_id):
    tpv = _tpv(client, case_id=case_id).json()
    if not tpv["saved"]:
        pytest.skip("목표 버전 저장소를 쓸 수 없는 환경")
    run = client.post("/api/v1/research-runs", json={
        "kind": "allocation_analyze", "inputs": {}, "outputs": {},
        "case_id": case_id}).json()

    ch = client.get(f"/api/v1/research-cases/{case_id}/chain")
    assert ch.status_code == 200, ch.text
    c = ch.json()
    # 케이스 → 아티팩트 (포인터)
    assert c["case"]["active_tpv_id"] == tpv["tpv_id"]
    # 아티팩트 → 케이스 (`case_id` 열) — 양방향이 닫힌다
    assert c["targets"]["available"] is True
    assert tpv["tpv_id"] in [t["tpv_id"] for t in c["targets"]["items"]]
    if run.get("recorded"):
        assert c["case"]["active_run_id"] == run["run_id"]
        assert run["run_id"] in [r["run_id"] for r in c["runs"]["items"]]
