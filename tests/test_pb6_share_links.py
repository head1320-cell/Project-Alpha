"""CF 3부 PB6 — 고객 주소 · 고객 세션 · 고객 AI (★유통 관문 뒤★)
==============================================================================
사용자 결정(2026-10-23): 고객 화면은 '관문 뒤에 만들기' · 고객 접속은 '비밀 주소 + PIN'(만료·언제든 끄기, 고객 계정 없음).

  ① ★여는 경로는 관문이 맨 앞★ — 닫혀 있으면 로그인·조회보다 먼저 403 `distribution_blocked` + 사유 + 빠진 칸
     · 닫는 경로(목록·철회)는 관문과 무관하게 늘 된다 — 토큰·한 장을 내지 않는다
  ② 주소 — 토큰은 ★한 번만★ 보여 주고 해시만 저장(DB·로그에 평문 없음) · PIN 6자리(쉬운 PIN 거절) · 7/30/90일 ·
     그 고객의 한 장만 · 보관 고객은 못 만듦 · 만들면 그 한 장은 '보여 준 것'(지울 수 없음)
  ③ 고객 — 토큰+PIN → 30분 세션 · 틀린 주소와 틀린 PIN 은 같은 말 · 5번 틀리면 잠김 · 잠긴 주소는 PIN 이 맞는지 드러내지 않는다 ·
     만료·철회·보관은 410 · ★관문을 닫거나 주소를 철회하면 살아 있는 세션도 즉시 막힘★ · 위조·만료 세션 401
  ④ 고객 AI — 근거는 그 주소의 한 장뿐 · 투자 판단은 고객용 고정 문장 · 주소마다 시간당 10번
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import pathlib

import pytest

import src.database as dbmod
from tests.test_pb4_sheets import BASE, _auth, _cid, _fake, _make, client  # noqa: F401

ROOT = pathlib.Path(__file__).resolve().parents[1]
GATE = "/api/v1/admin/distribution-gate"
SHARE = "/api/v1/share"
_DECL = dict(authority="운영자가 확인한 기관", license_kind="운영자가 확인한 종류", license_no="TEST-0001",
             verified_at="2026-10-29", scope="PB 고객 한 장을 그 고객에게 보여 주기")
PIN = "382915"


def _admin(c):
    tok = c.post("/api/v1/auth/login", json={"username": "admin", "password": "frm123!"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def _open_gate(c):
    assert c.post(GATE, json=_DECL, headers=_admin(c)).status_code == 201


def _close_gate(c):
    assert c.delete(GATE, headers=_admin(c)).status_code == 200


def _sheet_id(c, h, cid):
    return _make(c, h, cid)[0].json()["sheet_id"]


def _link(c, h, cid, sid, pin=PIN, days=30):
    return c.post(f"{BASE}/{cid}/share-links", json={"sheet_id": sid, "pin": pin, "days": days}, headers=h)


def _setup(c, *, gate=True):
    """alice 의 고객 하나 · 한 장 하나 · (관문 열고) 주소 하나 → (h, cid, sid, link_id, token)."""
    h = _auth(c, "alice")
    cid = _cid(c, h)
    sid = _sheet_id(c, h, cid)
    if gate:
        _open_gate(c)
    r = _link(c, h, cid, sid)
    assert r.status_code == 201, r.text
    return h, cid, sid, r.json()["link"]["link_id"], r.json()["token"]


def _session(c, token, pin=PIN):
    return c.post(f"{SHARE}/open", json={"token": token, "pin": pin})


def _sh(session):
    return {"X-Share-Session": session}


def _links(c, h, cid):
    return c.get(f"{BASE}/{cid}/share-links", headers=h).json()


def _blocked(r):
    assert r.status_code == 403, r.text
    d = r.json()["detail"]
    assert d["code"] == "distribution_blocked" and d["reason"] and d["missing"]
    return d


# ── ① 관문이 맨 앞 ─────────────────────────────────────────────────────────

def test_creating_a_link_is_blocked_while_the_gate_is_closed_and_nothing_is_saved(client):
    h = _auth(client, "alice")
    cid = _cid(client, h)
    sid = _sheet_id(client, h, cid)
    d = _blocked(_link(client, h, cid, sid))
    assert "license_no" in d["missing"]
    assert _links(client, h, cid)["links"] == []
    assert _links(client, h, cid)["gate"]["state"] == "blocked"


def test_the_gate_comes_before_any_lookup(client):
    """닫혀 있으면 없는 고객·주소여도 같은 403 — 무엇이 있는지 드러내기 전에 멈춘다. PB 경로는 로그인이 먼저(보호 등록부 계약 — 익명은 401)."""
    h = _auth(client, "alice")
    _blocked(client.post(f"{BASE}/cl_nope/share-links", json={"sheet_id": "sh_x", "pin": PIN, "days": 30}, headers=h))
    _blocked(client.post(f"{BASE}/cl_nope/share-links/ln_nope/reopen", headers=h))
    _blocked(client.patch(f"{BASE}/cl_nope/share-links/ln_nope", json={"sheet_id": "sh_x"}, headers=h))
    assert client.post(f"{BASE}/cl_nope/share-links", json={"sheet_id": "sh_x", "pin": PIN, "days": 30}).status_code == 401
    _blocked(client.post(f"{SHARE}/open", json={"token": "x" * 43, "pin": PIN}))
    _blocked(client.get(f"{SHARE}/sheet", headers=_sh("garbage")))


def test_closing_routes_work_while_the_gate_is_closed(client):
    h, cid, _sid, lid, _tok = _setup(client)
    _close_gate(client)
    body = _links(client, h, cid)
    assert body["gate"]["state"] == "blocked" and [x["link_id"] for x in body["links"]] == [lid]
    r = client.post(f"{BASE}/{cid}/share-links/{lid}/revoke", headers=h)
    assert r.status_code == 200 and r.json()["state"] == "revoked"


def test_the_pb_list_shows_the_gate_without_the_licence_values(client):
    h, cid, *_ = _setup(client)
    g = _links(client, h, cid)["gate"]
    assert g["state"] == "allowed" and "license" not in g
    assert _DECL["license_no"] not in json.dumps(_links(client, h, cid), ensure_ascii=False)


# ── ② 주소 ─────────────────────────────────────────────────────────────────

def test_the_token_is_shown_once_and_never_listed(client):
    h, cid, _sid, lid, tok = _setup(client)
    assert len(tok) >= 40
    text = json.dumps(_links(client, h, cid), ensure_ascii=False)
    assert tok not in text and "token" not in text and "pin" not in text.replace("pinned", "")
    r = client.post(f"{BASE}/{cid}/share-links/{lid}/revoke", headers=h)
    assert tok not in r.text and "sheet\"" not in r.text


def test_the_plain_token_and_pin_are_not_in_the_database_or_the_logs(client, caplog):
    caplog.set_level(logging.DEBUG)
    h, cid, _sid, _lid, tok = _setup(client)
    assert _session(client, tok).status_code == 200
    dbmod.reset_session()
    raw = pathlib.Path(dbmod.DATABASE_URL.removeprefix("sqlite:///")).read_bytes()
    assert tok.encode() not in raw and PIN.encode() not in raw
    assert tok not in caplog.text and PIN not in caplog.text


@pytest.mark.parametrize("pin", ["111111", "123456", "654321", "012345", "121212", "123123", "12345", "1234567", "12a456", " 38291"])
def test_easy_or_malformed_pins_are_refused(client, pin):
    h = _auth(client, "alice")
    cid = _cid(client, h)
    sid = _sheet_id(client, h, cid)
    _open_gate(client)
    r = _link(client, h, cid, sid, pin=pin)
    assert r.status_code == 422, r.text
    assert _links(client, h, cid)["links"] == []


def test_an_ordinary_pin_is_accepted(client):
    """짝 — 늘 거절하는 구현을 배제한다."""
    h, cid, *_ = _setup(client)
    assert len(_links(client, h, cid)["links"]) == 1


@pytest.mark.parametrize("days,ok", [(7, True), (30, True), (90, True), (10, False), (0, False), (365, False)])
def test_a_link_lasts_7_30_or_90_days(client, days, ok):
    h = _auth(client, "alice")
    cid = _cid(client, h)
    sid = _sheet_id(client, h, cid)
    _open_gate(client)
    r = _link(client, h, cid, sid, days=days)
    assert r.status_code == (201 if ok else 422), r.text                             # 없는 경로의 404 로 통과하지 않게
    if ok:
        exp = dt.datetime.fromisoformat(r.json()["link"]["expires_at"])
        left = exp - dt.datetime.now(dt.timezone.utc)
        assert dt.timedelta(days=days) - dt.timedelta(minutes=5) < left <= dt.timedelta(days=days)


def test_only_a_sheet_of_that_client_can_be_linked(client):
    h = _auth(client, "alice")
    c1, c2 = _cid(client, h), _cid(client, h, alias="고객 B")
    sid1 = _sheet_id(client, h, c1)
    _open_gate(client)
    assert _link(client, h, c2, sid1).status_code == 404
    hb = _auth(client, "bob")
    assert _link(client, hb, c1, sid1).status_code == 404                           # 남의 고객
    assert client.get(f"{BASE}/{c1}/share-links", headers=hb).status_code == 404
    assert _link(client, h, c1, sid1).status_code == 201                            # 짝


def test_every_link_route_refuses_someone_elses_client(client):
    """★전수★ — 등록부의 주소 경로를 남(bob)이 부르면 404(없는 고객과 같은 말) · 짝: 본인은 통과."""
    from src.api.protected_routes import PROTECTED
    routes = sorted(k for k in PROTECTED if "/share-links" in k[1])
    assert len(routes) == 5
    h, cid, sid, lid, _tok = _setup(client)
    hb = _auth(client, "bob")
    bodies = {"POST": {"sheet_id": sid, "pin": "529174", "days": 7}, "PATCH": {"sheet_id": sid}}
    for method, path in routes:
        url = path.replace("{cid}", cid).replace("{lid}", lid)
        body = bodies.get(method) if path.endswith("share-links") or method == "PATCH" else None
        r = client.request(method, url, json=body, headers=hb)
        assert r.status_code == 404 and r.json()["detail"] == "그 고객이 없어요.", (method, path, r.text)
    for method, path in routes:                                                     # 짝 — 철회는 맨 뒤에
        url = path.replace("{cid}", cid).replace("{lid}", lid)
        body = bodies.get(method) if path.endswith("share-links") or method == "PATCH" else None
        if path.endswith("/revoke"):
            continue
        assert client.request(method, url, json=body, headers=h).status_code in (200, 201), (method, path)
    assert client.post(f"{BASE}/{cid}/share-links/{lid}/revoke", headers=h).status_code == 200


def test_a_link_id_of_another_client_is_404_even_for_the_owner(client):
    h, cid, _sid, lid, _tok = _setup(client)
    other = _cid(client, h, alias="고객 B")
    r = client.post(f"{BASE}/{other}/share-links/{lid}/revoke", headers=h)
    assert r.status_code == 404 and r.json()["detail"] == "그 주소가 없어요."
    assert _links(client, h, cid)["links"][0]["state"] == "open"


def test_an_archived_client_cannot_get_a_link(client):
    h = _auth(client, "alice")
    cid = _cid(client, h)
    sid = _sheet_id(client, h, cid)
    _open_gate(client)
    client.post(f"{BASE}/{cid}/archive", headers=h)
    r = _link(client, h, cid, sid)
    assert r.status_code == 409 and "보관" in r.text


def test_a_linked_sheet_counts_as_shown_and_cannot_be_deleted(client):
    h, cid, sid, *_ = _setup(client)
    got = client.get(f"{BASE}/{cid}/snapshots/{sid}", headers=h).json()
    assert got["shared"] is True
    assert client.delete(f"{BASE}/{cid}/snapshots/{sid}", headers=h).status_code == 409


# ── ③ 고객 ─────────────────────────────────────────────────────────────────

def test_token_and_pin_open_a_session_that_reads_the_linked_sheet(client):
    h, cid, sid, lid, tok = _setup(client)
    r = _session(client, tok)
    assert r.status_code == 200, r.text
    s = r.json()
    left = dt.datetime.fromisoformat(s["expires_at"]) - dt.datetime.now(dt.timezone.utc)
    assert dt.timedelta(minutes=25) < left <= dt.timedelta(minutes=30)
    got = client.get(f"{SHARE}/sheet", headers=_sh(s["session"]))
    assert got.status_code == 200
    want = client.get(f"{BASE}/{cid}/snapshots/{sid}", headers=h).json()["sheet"]
    assert got.json()["sheet"] == want
    row = _links(client, h, cid)["links"][0]
    assert row["views"] == 1 and row["last_viewed_at"]


def test_a_wrong_pin_and_an_unknown_token_get_the_same_answer(client):
    _h, _cid_, _sid, _lid, tok = _setup(client)
    a = _session(client, tok, pin="902817")
    b = _session(client, "z" * len(tok))
    assert a.status_code == b.status_code == 401
    assert a.json()["detail"] == b.json()["detail"]


def test_four_wrong_pins_then_the_right_one_opens(client):
    h, cid, _sid, _lid, tok = _setup(client)
    for _ in range(4):
        assert _session(client, tok, pin="902817").status_code == 401
    assert _session(client, tok).status_code == 200
    assert _links(client, h, cid)["links"][0]["failures"] == 0                      # 맞히면 센 것을 비운다


def test_five_wrong_pins_lock_the_link_and_the_pb_can_reopen_it(client):
    h, cid, _sid, lid, tok = _setup(client)
    for _ in range(5):
        _session(client, tok, pin="902817")
    r = _session(client, tok)
    assert r.status_code == 423 and "PB" in r.json()["detail"]
    assert _links(client, h, cid)["links"][0]["state"] == "locked"
    assert client.post(f"{BASE}/{cid}/share-links/{lid}/reopen", headers=h).status_code == 200
    assert _session(client, tok).status_code == 200


def test_the_wrong_pin_that_locks_the_link_says_so_at_once(client):
    """다섯 번째로 틀린 그 요청이 바로 '잠겼어요'(423) — 고객이 한 번 더 넣어 봐야 알게 하지 않는다. 틀린 PIN 이라 드러나는 것이 없다."""
    _h, _cid_, _sid, _lid, tok = _setup(client)
    for _ in range(4):
        assert _session(client, tok, pin="902817").status_code == 401
    r = _session(client, tok, pin="902817")
    assert r.status_code == 423 and "PB" in r.json()["detail"]


def test_a_locked_link_does_not_tell_whether_the_pin_is_right(client):
    h, cid, _sid, _lid, tok = _setup(client)
    for _ in range(5):
        _session(client, tok, pin="902817")
    right, wrong = _session(client, tok), _session(client, tok, pin="902817")
    assert right.status_code == wrong.status_code == 423
    assert right.json() == wrong.json()
    assert _links(client, h, cid)["links"][0]["failures"] == 5                      # 잠긴 뒤로는 세지도 않는다


def _expire(lid):
    with dbmod.session_scope() as s:
        row = s.query(dbmod.PbClientLink).filter(dbmod.PbClientLink.link_id == lid).one()
        row.expires_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)


def test_an_expired_link_is_gone_for_new_and_live_sessions(client):
    h, cid, _sid, lid, tok = _setup(client)
    sess = _session(client, tok).json()["session"]
    _expire(lid)
    assert _session(client, tok).status_code == 410
    assert client.get(f"{SHARE}/sheet", headers=_sh(sess)).status_code == 410
    assert _links(client, h, cid)["links"][0]["state"] == "expired"


def test_revoking_a_link_stops_its_live_session_at_once(client):
    h, cid, _sid, lid, tok = _setup(client)
    sess = _session(client, tok).json()["session"]
    assert client.get(f"{SHARE}/sheet", headers=_sh(sess)).status_code == 200
    client.post(f"{BASE}/{cid}/share-links/{lid}/revoke", headers=h)
    assert client.get(f"{SHARE}/sheet", headers=_sh(sess)).status_code == 410
    assert _session(client, tok).status_code == 410


def test_closing_the_gate_stops_live_sessions_at_once(client):
    _h, _cid_, _sid, _lid, tok = _setup(client)
    sess = _session(client, tok).json()["session"]
    _close_gate(client)
    _blocked(client.get(f"{SHARE}/sheet", headers=_sh(sess)))
    _blocked(client.post(f"{SHARE}/ask", json={"question": "비중은요?"}, headers=_sh(sess)))
    _open_gate(client)
    assert client.get(f"{SHARE}/sheet", headers=_sh(sess)).status_code == 200      # 짝 — 다시 열면 같은 세션이 읽힌다


def test_archiving_the_client_stops_the_link(client):
    h, cid, _sid, _lid, tok = _setup(client)
    sess = _session(client, tok).json()["session"]
    client.post(f"{BASE}/{cid}/archive", headers=h)
    assert client.get(f"{SHARE}/sheet", headers=_sh(sess)).status_code == 410
    assert _session(client, tok).status_code == 410


@pytest.mark.parametrize("mangle", ["", "garbage", "flip", "expired"])
def test_a_missing_forged_or_expired_session_is_401(client, mangle):
    from src.services import pb_links
    _h, _cid_, _sid, lid, tok = _setup(client)
    good = _session(client, tok).json()["session"]
    if mangle == "flip":
        bad = good[:-2] + ("A" if good[-2] != "A" else "B") + good[-1]
    elif mangle == "expired":
        from src.api.auth import derived_key
        bad = pb_links._issue_session(lid, key=derived_key(pb_links.SESSION_PURPOSE), ttl=dt.timedelta(seconds=-1))
    else:
        bad = mangle
    headers = _sh(bad) if bad else {}
    assert client.get(f"{SHARE}/sheet", headers=headers).status_code == 401
    assert client.get(f"{SHARE}/sheet", headers=_sh(good)).status_code == 200       # 짝


def test_each_session_reads_only_its_own_links_sheet(client):
    h, cid, sid1, _l1, tok1 = _setup(client)
    sid2 = _sheet_id(client, h, cid)
    tok2 = _link(client, h, cid, sid2).json()["token"]
    s1, s2 = _session(client, tok1).json()["session"], _session(client, tok2).json()["session"]
    title = lambda s: client.get(f"{SHARE}/sheet", headers=_sh(s)).json()["sheet_id"]  # noqa: E731
    assert (title(s1), title(s2)) == (sid1, sid2)


def test_changing_the_shown_sheet_needs_the_gate_and_a_sheet_of_that_client(client):
    h, cid, _sid, lid, tok = _setup(client)
    other = _cid(client, h, alias="고객 B")
    sid_other = _sheet_id(client, h, other)
    sid_new = _sheet_id(client, h, cid)
    assert client.patch(f"{BASE}/{cid}/share-links/{lid}", json={"sheet_id": sid_other}, headers=h).status_code == 404
    r = client.patch(f"{BASE}/{cid}/share-links/{lid}", json={"sheet_id": sid_new}, headers=h)
    assert r.status_code == 200 and r.json()["sheet_id"] == sid_new
    assert client.get(f"{BASE}/{cid}/snapshots/{sid_new}", headers=h).json()["shared"] is True
    sess = _session(client, tok).json()["session"]
    assert client.get(f"{SHARE}/sheet", headers=_sh(sess)).json()["sheet_id"] == sid_new
    _close_gate(client)
    _blocked(client.patch(f"{BASE}/{cid}/share-links/{lid}", json={"sheet_id": sid_new}, headers=h))


def test_a_revoked_or_expired_link_cannot_be_reopened(client):
    h, cid, _sid, lid, _tok = _setup(client)
    client.post(f"{BASE}/{cid}/share-links/{lid}/revoke", headers=h)
    r = client.post(f"{BASE}/{cid}/share-links/{lid}/reopen", headers=h)
    assert r.status_code == 409 and "새 주소" in r.json()["detail"]


# ── ④ 고객 AI ───────────────────────────────────────────────────────────────

def test_client_ask_is_grounded_in_the_links_sheet(client, monkeypatch):
    h, cid, sid, _lid, tok = _setup(client)
    sheet = client.get(f"{BASE}/{cid}/snapshots/{sid}", headers=h).json()["sheet"]
    w = sheet["focus"]["weights"][0]
    sdk = _fake({"answerable": True, "why_not": "none", "sentences": [
        {"text": f"{w['name']} 비중은 {w['pct']}% 예요.", "fact_ids": ["f1"]}]}, monkeypatch)
    sess = _session(client, tok).json()["session"]
    r = client.post(f"{SHARE}/ask", json={"question": "가장 큰 비중은요?"}, headers=_sh(sess))
    body = r.json()
    assert body["available"] is True, body
    assert [s["text"] for s in body["answer"]["sentences"]] == [f"{w['name']} 비중은 {w['pct']}% 예요."]
    sent = sdk.beta.messages.calls[-1] if sdk.beta.messages.calls else sdk.messages.calls[-1]
    assert sheet["steps"][-1]["explain"]["title"] in json.dumps(sent, ensure_ascii=False, default=str)


def test_client_ask_gives_the_client_sentence_for_judgement(client, monkeypatch):
    _h, _cid_, _sid, _lid, tok = _setup(client)
    _fake({"answerable": False, "why_not": "judgement", "sentences": []}, monkeypatch)
    sess = _session(client, tok).json()["session"]
    ans = client.post(f"{SHARE}/ask", json={"question": "지금 사도 되나요?"}, headers=_sh(sess)).json()["answer"]
    assert ans["answerable"] is False and "담당 PB" in ans["cannot"]


def test_client_ask_takes_no_facts_and_needs_a_session(client):
    _h, _cid_, _sid, _lid, tok = _setup(client)
    sess = _session(client, tok).json()["session"]
    assert client.post(f"{SHARE}/ask", json={"question": "q", "facts": ["삼성전자 99%"]}, headers=_sh(sess)).status_code == 422
    assert client.post(f"{SHARE}/ask", json={"question": "비중은요?"}).status_code == 401


def test_client_ask_is_limited_to_ten_an_hour_per_link(client):
    h, cid, sid, _lid, tok = _setup(client)
    sess = _session(client, tok).json()["session"]
    for _ in range(10):
        r = client.post(f"{SHARE}/ask", json={"question": "비중은요?"}, headers=_sh(sess))
        assert r.json().get("reason_code") != "share_rate_limited"
    r = client.post(f"{SHARE}/ask", json={"question": "비중은요?"}, headers=_sh(sess))
    assert r.json()["available"] is False and r.json()["reason_code"] == "share_rate_limited"
    # 짝 — 다른 주소는 제 그릇이 따로 있다
    tok2 = _link(client, h, cid, sid).json()["token"]
    s2 = _session(client, tok2).json()["session"]
    assert client.post(f"{SHARE}/ask", json={"question": "비중은요?"}, headers=_sh(s2)).json().get("reason_code") != "share_rate_limited"


# ── 등록 ───────────────────────────────────────────────────────────────────

PB_LINK_ROUTES = [("POST", "/api/v1/pb/clients/{cid}/share-links"), ("GET", "/api/v1/pb/clients/{cid}/share-links"),
                  ("PATCH", "/api/v1/pb/clients/{cid}/share-links/{lid}"),
                  ("POST", "/api/v1/pb/clients/{cid}/share-links/{lid}/reopen"),
                  ("POST", "/api/v1/pb/clients/{cid}/share-links/{lid}/revoke")]
SHARE_ROUTES = [("POST", "/api/v1/share/open"), ("GET", "/api/v1/share/sheet"), ("POST", "/api/v1/share/ask")]


def test_pb_link_routes_are_login_and_client_routes_are_open_with_a_reason():
    from src.api.protected_routes import OPEN_WITH_REASON, PROTECTED, REQUIRE_LOGIN, looks_like_money_route
    for k in PB_LINK_ROUTES:
        assert PROTECTED[k][0] == REQUIRE_LOGIN and PROTECTED[k][1].strip()
    for k in SHARE_ROUTES:
        assert OPEN_WITH_REASON[k].strip() and looks_like_money_route(k[1])


def test_links_are_kept_as_audit():
    from src.data.retention import AUDIT
    assert "pb_client_links" in AUDIT
    doc = (ROOT / "docs" / "specs" / "RETENTION_POLICY.md").read_text(encoding="utf-8")
    assert "pb_client_links" in doc.split("<!-- PROTECTED-LIST:START -->")[1].split("<!-- PROTECTED-LIST:END -->")[0]


def test_the_login_map_names_the_link_routes():
    m = json.loads((ROOT / "frontend" / "src" / "entities" / "session" / "accessMap.json").read_text(encoding="utf-8"))
    login = [r for it in m["login"]["items"] for r in it.get("routes", [])]
    for meth, path in PB_LINK_ROUTES:
        assert f"{meth} {path}" in login
