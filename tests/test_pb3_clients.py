"""CF 3부 PB3 — 고객 여러 명 관리 (★PB 본인 고객만 · 별칭만 · 지우지 않고 보관★)
==============================================================================
계획 PB3 · 사용자 결정(2026-10-23): 고객 자료는 서버 DB 새 표 — ★PB 가 정한 별칭만★(실명·연락처·주민번호·계좌번호를 받지 않는다).

  ① 로그인해야 열린다 · 소유자는 ★토큰에서만★ 온다(본문에 owner 를 넣을 칸이 없다)
  ② 남의 고객은 404 — 없는 고객과 같은 답(있는지조차 드러내지 않는다) · `{cid}` 가 든 경로 ★전수★
  ③ 별칭·문서 이름·문서 안 고객 노드 별칭에 개인정보 모양(전화·이메일·주민번호·긴 숫자열)이면 사유와 함께 거절 — 짝: 보통 별칭은 통과
  ④ 지우는 길이 없다 — 보관(목록에서 숨김 · 읽기만) · 다시 꺼내기
  ⑤ 설계 문서 — 그래프 문서 모양(format·version·nodes·edges)만 확인하고 그대로 둔다 · 512KB 상한 · 다른 고객의 문서 id 로는 404
  ⑥ 보호 등록부·돈/PII 표지 · 보존 분류(⑤ 계정 소유)
"""
from __future__ import annotations

import os
import tempfile

import pytest
from fastapi.testclient import TestClient

import src.database as dbmod
from src.api.protected_routes import PROTECTED, REQUIRE_LOGIN, looks_like_money_route
from src.domain.auth_identity import ROLE_ANALYST

_SECRET = "pb3-clients-routes-secret-0123456789abcdef"
BASE = "/api/v1/pb/clients"
F = {"format": "project-alpha.portfolio-graph", "version": 1}


@pytest.fixture()
def client(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp.name}")
    monkeypatch.setenv("AUTH_SECRET", _SECRET)
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    monkeypatch.setattr(dbmod, "DATABASE_URL", f"sqlite:///{tmp.name}", raising=False)
    dbmod.reset_session()
    dbmod.init_db()
    dbmod.create_user("alice", "alice-pw", role=ROLE_ANALYST)
    dbmod.create_user("bob", "bob-pw", role=ROLE_ANALYST)
    from src.app_factory import create_app
    with TestClient(create_app()) as c:
        yield c
    dbmod.reset_session()
    try:
        os.unlink(tmp.name)
    except OSError:
        pass


def _auth(client, user):
    tok = client.post("/api/v1/auth/login", json={"username": user, "password": f"{user}-pw"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def _new(client, h, **kw):
    r = client.post(BASE, json={"alias": "고객 A-12", **kw}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def _graph(alias=None, n=1):
    params = {"alias": alias} if alias else {}
    return {**F, "nodes": [{"id": "c", "type": "client_profile", "params": params, "position": {"x": 0, "y": 0}}]
            + [{"id": f"u{i}", "type": "universe", "params": {"tickers": ["005930"]}, "position": {"x": 0, "y": 0}}
               for i in range(n - 1)], "edges": []}


# ── ① 로그인 · 소유자는 토큰에서 ─────────────────────────────────────────

def test_signed_out_is_refused(client):
    assert client.get(BASE).status_code == 401
    assert client.post(BASE, json={"alias": "고객 A"}).status_code == 401


def test_owner_comes_only_from_the_token(client):
    a = _auth(client, "alice")
    r = client.post(BASE, json={"alias": "고객 A", "owner": "bob"}, headers=a)
    assert r.status_code == 422                                              # 본문에 owner 칸이 없다
    _new(client, a)
    assert [c["alias"] for c in client.get(BASE, headers=a).json()["clients"]] == ["고객 A-12"]
    assert client.get(BASE, headers=_auth(client, "bob")).json()["clients"] == []   # 짝 — 남의 목록에는 없다


# ── ② 남의 고객은 404 — 전수 ─────────────────────────────────────────────

#: 고객·문서 경로 — 한 장(`/snapshots`, PB4)은 만드는 데 계산 미리보기가 필요해 `test_pb4_sheets.py` 가 같은 방식으로 훑는다.
_CID_ROUTES = sorted(k for k in PROTECTED if "{cid}" in k[1] and "/snapshots" not in k[1])


def test_there_are_client_routes_to_check():
    """짝 — 목록이 비면 아래 전수 검사가 언제나 통과한다."""
    assert len(_CID_ROUTES) >= 7


def _body_for(method, path):
    if path.endswith("/docs") and method == "POST":
        return {"name": "점검", "graph": _graph()}
    if path.endswith("/{did}") and method == "PUT":
        return {"graph": _graph()}
    if method == "PATCH":
        return {"horizon_years": 5}
    return None


@pytest.mark.parametrize(("method", "path"), _CID_ROUTES)
def test_every_client_route_refuses_someone_elses_client(client, method, path):
    a, b = _auth(client, "alice"), _auth(client, "bob")
    cid = _new(client, a)["client_id"]
    did = client.post(f"{BASE}/{cid}/docs", json={"name": "점검", "graph": _graph()}, headers=a).json()["doc_id"]
    url = path.replace("{cid}", cid).replace("{did}", did)
    body = _body_for(method, path)
    r = client.request(method, url, json=body, headers=b)
    assert r.status_code == 404, (method, path, r.status_code, r.text)
    assert r.json()["detail"] == "그 고객이 없어요."
    # 짝 — 본인은 통과한다(늘 404 인 구현 배제)
    assert client.request(method, url, json=body, headers=a).status_code in (200, 201), (method, path)


def test_unknown_client_gets_the_same_answer_as_someone_elses(client):
    r = client.get(f"{BASE}/cl_0000000000000000", headers=_auth(client, "alice"))
    assert r.status_code == 404 and r.json()["detail"] == "그 고객이 없어요."


def test_doc_id_of_another_client_is_404_even_for_the_owner(client):
    a = _auth(client, "alice")
    c1, c2 = _new(client, a)["client_id"], _new(client, a, alias="고객 B")["client_id"]
    did = client.post(f"{BASE}/{c1}/docs", json={"name": "점검", "graph": _graph()}, headers=a).json()["doc_id"]
    assert client.get(f"{BASE}/{c2}/docs/{did}", headers=a).status_code == 404
    assert client.get(f"{BASE}/{c1}/docs/{did}", headers=a).status_code == 200          # 짝


# ── ③ 개인정보 모양 ──────────────────────────────────────────────────────

@pytest.mark.parametrize("alias,word", [
    ("010-1234-5678", "전화번호"), ("hong@example.com", "이메일"), ("900101-1234567", "주민"), ("12345678901", "숫자"),
])
def test_alias_shaped_like_personal_data_is_refused(client, alias, word):
    r = client.post(BASE, json={"alias": alias}, headers=_auth(client, "alice"))
    assert r.status_code == 422 and word in r.text
    assert client.get(BASE, headers=_auth(client, "alice")).json()["clients"] == []       # 아무것도 쓰지 않았다


def test_plain_alias_and_dates_pass(client):
    c = _new(client, _auth(client, "alice"), alias="2026 은퇴 준비 고객", risk_tolerance="moderate",
             profile_source="survey", assessed_at="2026-01-02", horizon_years=10)
    assert c["alias"] == "2026 은퇴 준비 고객" and c["risk_tolerance"] == "moderate"
    assert isinstance(c["assessed_age_days"], int) and c["assessed_age_days"] > 0


def test_empty_alias_and_future_assessment_are_refused(client):
    a = _auth(client, "alice")
    assert client.post(BASE, json={"alias": "  "}, headers=a).status_code == 422
    r = client.post(BASE, json={"alias": "고객 A", "assessed_at": "2999-01-01"}, headers=a)
    assert r.status_code == 422 and "미래" in r.text


def test_unknowns_stay_unknown(client):
    c = _new(client, _auth(client, "alice"))
    assert c["risk_tolerance"] is None and c["profile_source"] == "unknown" and c["assessed_at"] is None
    assert c["assessed_age_days"] is None and c["horizon_years"] is None


def test_patch_checks_the_alias_too(client):
    a = _auth(client, "alice")
    cid = _new(client, a)["client_id"]
    assert client.patch(f"{BASE}/{cid}", json={"alias": "010 1234 5678"}, headers=a).status_code == 422
    r = client.patch(f"{BASE}/{cid}", json={"risk_tolerance": "aggressive"}, headers=a)
    assert r.status_code == 200 and r.json()["risk_tolerance"] == "aggressive" and r.json()["alias"] == "고객 A-12"
    r = client.patch(f"{BASE}/{cid}", json={"risk_tolerance": None}, headers=a)              # 모름으로 되돌리기
    assert r.status_code == 200 and r.json()["risk_tolerance"] is None


def test_doc_name_and_client_node_alias_are_checked(client):
    a = _auth(client, "alice")
    cid = _new(client, a)["client_id"]
    r = client.post(f"{BASE}/{cid}/docs", json={"name": "hong@example.com 점검", "graph": _graph()}, headers=a)
    assert r.status_code == 422 and "이메일" in r.text
    r = client.post(f"{BASE}/{cid}/docs", json={"name": "점검", "graph": _graph(alias="010-1234-5678")}, headers=a)
    assert r.status_code == 422 and "전화번호" in r.text
    assert client.get(f"{BASE}/{cid}", headers=a).json()["docs"] == []
    assert client.post(f"{BASE}/{cid}/docs", json={"name": "10월 점검", "graph": _graph(alias="고객 A-12")},
                       headers=a).status_code == 201                                       # 짝


# ── ④ 지우지 않고 보관 ───────────────────────────────────────────────────

def test_there_is_no_delete_route_for_clients_or_docs():
    """고객·문서는 지우지 않는다 — 지우는 경로는 한 장(PB4 — 보여 준 적 없는 것만) 하나뿐."""
    deletes = [k for k in PROTECTED if k[1].startswith(BASE) and k[0] == "DELETE"]
    assert deletes == [("DELETE", f"{BASE}/{{cid}}/snapshots/{{sid}}")]


def test_archive_hides_from_the_list_and_makes_it_read_only(client):
    a = _auth(client, "alice")
    cid = _new(client, a)["client_id"]
    did = client.post(f"{BASE}/{cid}/docs", json={"name": "점검", "graph": _graph()}, headers=a).json()["doc_id"]
    assert client.post(f"{BASE}/{cid}/archive", headers=a).status_code == 200
    assert client.get(BASE, headers=a).json()["clients"] == []
    kept = client.get(BASE, params={"archived": 1}, headers=a).json()["clients"]
    assert [c["client_id"] for c in kept] == [cid] and kept[0]["archived"] is True
    assert client.get(f"{BASE}/{cid}/docs/{did}", headers=a).status_code == 200            # 읽기는 된다
    for method, url, body in (("PATCH", f"{BASE}/{cid}", {"horizon_years": 3}),
                              ("POST", f"{BASE}/{cid}/docs", {"name": "새", "graph": _graph()}),
                              ("PUT", f"{BASE}/{cid}/docs/{did}", {"graph": _graph()})):
        r = client.request(method, url, json=body, headers=a)
        assert r.status_code == 409 and "보관" in r.text, (method, url)
    assert client.post(f"{BASE}/{cid}/unarchive", headers=a).status_code == 200
    assert [c["client_id"] for c in client.get(BASE, headers=a).json()["clients"]] == [cid]
    assert client.patch(f"{BASE}/{cid}", json={"horizon_years": 3}, headers=a).status_code == 200   # 짝 — 다시 쓸 수 있다


# ── ⑤ 설계 문서 ─────────────────────────────────────────────────────────

def test_doc_round_trip_and_save(client):
    a = _auth(client, "alice")
    cid = _new(client, a)["client_id"]
    g1 = _graph(n=2)
    made = client.post(f"{BASE}/{cid}/docs", json={"name": "10월 점검", "graph": g1}, headers=a)
    assert made.status_code == 201
    did = made.json()["doc_id"]
    assert did.startswith("cd_") and "graph" not in made.json()
    got = client.get(f"{BASE}/{cid}/docs/{did}", headers=a).json()
    assert got["graph"] == g1 and got["name"] == "10월 점검"
    g2 = _graph(n=3)
    saved = client.put(f"{BASE}/{cid}/docs/{did}", json={"graph": g2}, headers=a)
    assert saved.status_code == 200 and saved.json()["name"] == "10월 점검"
    assert client.get(f"{BASE}/{cid}/docs/{did}", headers=a).json()["graph"] == g2
    detail = client.get(f"{BASE}/{cid}", headers=a).json()
    assert [d["doc_id"] for d in detail["docs"]] == [did] and "graph" not in detail["docs"][0]
    listed = client.get(BASE, headers=a).json()["clients"][0]
    assert listed["doc_count"] == 1 and listed["last_doc_at"]


def test_doc_must_look_like_a_graph(client):
    a = _auth(client, "alice")
    cid = _new(client, a)["client_id"]
    r = client.post(f"{BASE}/{cid}/docs", json={"name": "점검", "graph": {"format": "x", "version": 1, "nodes": [], "edges": []}},
                    headers=a)
    assert r.status_code == 422 and "포트폴리오 그래프가 아닙니다" in r.text


def test_doc_size_limit(client):
    a = _auth(client, "alice")
    cid = _new(client, a)["client_id"]
    big = {**F, "nodes": [], "edges": [], "meta": {"name": "x" * (512 * 1024)}}
    r = client.post(f"{BASE}/{cid}/docs", json={"name": "큰 문서", "graph": big}, headers=a)
    assert r.status_code == 413 and "512" in r.text
    ok = {**F, "nodes": [], "edges": [], "meta": {"name": "x" * (400 * 1024)}}
    assert client.post(f"{BASE}/{cid}/docs", json={"name": "보통 문서", "graph": ok}, headers=a).status_code == 201  # 짝


# ── ⑥ 등록부 · 표지 · 보존 ───────────────────────────────────────────────

def test_every_pb_route_is_registered_login_only(client):
    real = sorted((m, r.path) for r in client.app.routes if getattr(r, "path", "").startswith("/api/v1/pb/")
                  for m in (r.methods or []) if m not in {"HEAD", "OPTIONS"})
    assert len(real) >= 14
    for key in real:
        assert PROTECTED.get(key, (None,))[0] == REQUIRE_LOGIN, key
        assert looks_like_money_route(key[1]), key                          # 전수 검사의 사정거리 안


def test_tables_are_classified_as_account_owned():
    from src.data.retention import PROTECTED as KEEP
    from src.data.retention import USER_OWNED
    for t in ("pb_clients", "pb_client_docs"):
        assert t in USER_OWNED and t not in KEEP
