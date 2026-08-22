"""사용자 정의 시나리오 팩 CRUD — 저장·버전·삭제 (스펙 §5 `user-authored`, Phase 10a).

Phase 9 는 인라인 실행만 배달했다. 이 파일이 고정하는 것은 네 가지다.

1. **저장돼도 `model_type` 은 사용자가 정하지 못한다.** 오히려 저장 쪽이 더 위험하다 —
   인라인 거짓말은 요청 한 건으로 끝나지만 **저장된 거짓말은 계속 남는다.**
2. **갱신은 버전을 올리고 그 시점 내용을 이력에 남긴다.** 제자리 덮어쓰기만 하면 런이 기록한
   팩 버전으로 충격을 복원할 수 없다.
3. **삭제는 이력까지 지운다.** 고아 이력이 남으면 같은 id 가 재발급될 때 남의 과거를 물려받는다.
4. **저장 팩이 등록 팩을 가리지 못한다.** 가릴 수 있으면 `semi_selloff` 라는 이름으로 저장하는
   것만으로 내장 시나리오를 조용히 바꿔치기할 수 있다.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

import src.data.scenario_packs_store as store
from src.app_factory import create_app

SAVE = "/api/v1/allocation/scenario-packs"
RUN = "/api/v1/allocation/scenario-run"
HOLDINGS = {"005930": 0.6, "000660": 0.4}


def _pack(**kw):
    base = {"label": "내 충격", "market": -6.0,
            "factors": {"size": -4.0, "leverage": -3.0},
            "assumptions": {"corr_rise": 0.2, "vol_rise": 0.4}}
    base.update(kw)
    return base


@pytest.fixture
def client(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    monkeypatch.setattr(store, "_engine", lambda: eng)
    monkeypatch.setattr(store, "_inited", False)
    with TestClient(create_app()) as c:
        yield c


# ═══════════════════════════════════════════════════════════════════════════════
# 1. 저장돼도 사용자가 model_type 을 정하지 못한다
# ═══════════════════════════════════════════════════════════════════════════════
def test_a_saved_pack_is_always_hypothetical(client):
    r = client.post(SAVE, json={"pack": _pack()})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["model_type"] == "hypothetical"
    assert body["family"] == "user_authored"
    assert body["pack_id"].startswith("sp_")


def test_a_save_cannot_smuggle_a_historical_claim(client):
    """★저장 경로가 §5 의 구멍이 되면 안 된다★ 인라인에서 막은 것을 여기서 열어 주면 안 된다."""
    r = client.post(SAVE, json={"pack": _pack(model_type="historical_replay"),
                                "model_type": "historical_replay"})
    assert r.status_code == 200, r.text
    assert r.json()["model_type"] == "hypothetical"

    listed = client.get(SAVE).json()["packs"]
    assert all(p["model_type"] == "hypothetical" for p in listed)


def test_saved_packs_carry_an_identity(client):
    body = client.post(SAVE, json={"pack": _pack()}).json()
    assert body["identity"] == f"{body['pack_id']}@{body['content_hash']}"
    assert len(body["content_hash"]) == 12


def test_the_saved_hash_matches_the_inline_hash_for_the_same_shock(client):
    """저장 팩과 인라인 팩의 신원 규칙은 **한 벌**이다 — 갈라지면 두 해시를 비교할 수 없다."""
    from src.engine.scenario_packs import inline_pack
    spec = _pack()
    saved = client.post(SAVE, json={"pack": spec}).json()
    assert saved["content_hash"] == inline_pack(spec).content_hash


# ═══════════════════════════════════════════════════════════════════════════════
# 2. 갱신 = 버전 + 이력
# ═══════════════════════════════════════════════════════════════════════════════
def test_updating_bumps_the_version_and_records_history(client):
    first = client.post(SAVE, json={"pack": _pack()}).json()
    pid = first["pack_id"]
    assert first["version"] == 1

    second = client.post(SAVE, json={"pack": _pack(market=-12.0), "pack_id": pid}).json()
    assert second["pack_id"] == pid
    assert second["version"] == 2
    assert second["content_hash"] != first["content_hash"], (
        "충격을 바꿨는데 해시가 그대로입니다")

    vers = client.get(f"{SAVE}/{pid}/versions").json()["versions"]
    assert [v["version"] for v in vers] == [1, 2]
    # ★버전 번호만으로는 무엇이 바뀌었는지 알 수 없다★ 해시가 함께 있어야 판단이 가능하다.
    assert vers[0]["content_hash"] != vers[1]["content_hash"]


def test_a_stored_version_keeps_its_own_content(client):
    """★없는 버전에 최신본을 돌려주지 않는다★ 는 규칙의 이면 — 있는 버전은 당시 내용을 준다."""
    pid = client.post(SAVE, json={"pack": _pack()}).json()["pack_id"]
    client.post(SAVE, json={"pack": _pack(market=-12.0), "pack_id": pid})

    v1 = store.get_pack_version(pid, 1)
    assert v1 is not None and v1["market"] == -6.0, "v1 이 갱신본으로 덮였습니다"
    assert store.get_pack_version(pid, 99) is None, "없는 버전에 무언가를 돌려줬습니다"


def test_updating_a_missing_pack_is_422_not_503(client):
    """두 실패를 같은 말로 보고하지 않는다 — 하나는 사용자가 고칠 수 있고 하나는 아니다."""
    r = client.post(SAVE, json={"pack": _pack(), "pack_id": "sp_does_not_exist"})
    assert r.status_code == 422, r.text
    assert "sp_does_not_exist" in r.json()["detail"]


# ═══════════════════════════════════════════════════════════════════════════════
# 3. 삭제는 이력까지
# ═══════════════════════════════════════════════════════════════════════════════
def test_delete_removes_the_version_history_too(client):
    pid = client.post(SAVE, json={"pack": _pack()}).json()["pack_id"]
    client.post(SAVE, json={"pack": _pack(market=-9.0), "pack_id": pid})
    assert len(client.get(f"{SAVE}/{pid}/versions").json()["versions"]) == 2

    assert client.delete(f"{SAVE}/{pid}").status_code == 200
    assert client.get(f"{SAVE}/{pid}/versions").json()["versions"] == [], (
        "고아 이력이 남았습니다 — 같은 id 가 재발급되면 남의 과거를 물려받습니다")
    assert client.delete(f"{SAVE}/{pid}").status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# 4. 저장 팩으로 실행 — 그리고 등록 팩을 가리지 못한다
# ═══════════════════════════════════════════════════════════════════════════════
def test_a_saved_pack_runs_through_scenario_run(client):
    pid = client.post(SAVE, json={"pack": _pack()}).json()["pack_id"]
    r = client.post(RUN, json={"holdings": HOLDINGS, "pack_id": pid})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["model_type"] == "hypothetical"
    assert body["pack_id"] == pid
    assert body["shock_pct"] is not None


def test_a_saved_pack_uses_its_own_coefficients(client):
    """저장된 계수로 돌아야 한다 — 등록 팩의 계수로 돌면 저장이 의미가 없다."""
    mild = client.post(SAVE, json={"pack": _pack(market=-2.0, factors={"size": -1.0})}).json()
    harsh = client.post(SAVE, json={"pack": _pack(market=-30.0, factors={"size": -20.0})}).json()
    a = client.post(RUN, json={"holdings": HOLDINGS, "pack_id": mild["pack_id"]}).json()
    b = client.post(RUN, json={"holdings": HOLDINGS, "pack_id": harsh["pack_id"]}).json()
    assert b["shock_pct"] < a["shock_pct"], (
        f"더 센 충격이 더 크지 않습니다: {b['shock_pct']} vs {a['shock_pct']}")


def test_a_saved_pack_cannot_shadow_a_registered_one(client, monkeypatch):
    """★등록 id 를 저장 팩이 가릴 수 있으면 내장 시나리오를 바꿔치기할 수 있다★"""
    from src.engine.scenario_packs import PACKS
    monkeypatch.setattr(store, "get_pack",
                        lambda pid: {"pack_id": pid, "label": "가짜", "market": -99.0,
                                     "factors": {"size": -50.0}, "assumptions": {},
                                     "content_hash": "deadbeef1234", "version": 1})
    body = client.post(RUN, json={"holdings": HOLDINGS, "pack_id": "semi_selloff"}).json()
    assert body["pack"]["engine"] == "kr_pack", "저장 팩이 등록 팩을 가렸습니다"
    assert body["content_hash"] == PACKS["semi_selloff"].content_hash


def test_an_unknown_pack_id_is_still_422(client):
    r = client.post(RUN, json={"holdings": HOLDINGS, "pack_id": "sp_nope"})
    assert r.status_code == 422 and "sp_nope" in r.json()["detail"]


# ═══════════════════════════════════════════════════════════════════════════════
# 5. DB 를 못 쓸 때 — 500 이 아니라 사유
# ═══════════════════════════════════════════════════════════════════════════════
def test_a_degraded_store_reports_503_not_500(client, monkeypatch):
    """DB 장애를 500 으로 뱉으면 사용자는 자기가 뭘 잘못했는지 영영 모른다."""
    monkeypatch.setattr(store, "save_pack", lambda spec, pack_id=None: None)
    r = client.post(SAVE, json={"pack": _pack()})
    assert r.status_code == 503, r.text
    assert "DB" in r.json()["detail"]


def test_a_degraded_store_lists_empty_rather_than_raising(client, monkeypatch):
    """★진짜 degraded 경로를 태운다★

    `list_packs` 를 [] 로 갈아 끼우면 라우트가 빈 목록을 잘 다루는지만 보게 되고, 정작
    "DB 가 죽었을 때 저장소가 예외를 삼키는가" 는 검증되지 않는다. 엔진 자체를 못 쓰게 만든다.
    """
    def dead():
        raise RuntimeError("DB 연결 불가")

    monkeypatch.setattr(store, "_engine", dead)
    monkeypatch.setattr(store, "_inited", False)
    r = client.get(SAVE)
    assert r.status_code == 200 and r.json()["packs"] == []
    # 조회도 같은 규칙 — 예외가 아니라 None.
    assert store.get_pack("sp_whatever") is None
    assert store.list_pack_versions("sp_whatever") == []
