"""CF 3부 PB4 — 고객 한 장 (★서버가 다시 계산 · 새 숫자를 만들지 않는다 · PB 본인 고객만★)
==============================================================================
계획 PB4 · 리포트 AD5 규율: 한 장은 ★서버가 같은 그래프를 다시 계산한 보고에서 옮기기만★ 한다.

  ① 만들기 — 서버가 다시 계산하고, ★모든 노드의★ `view_hash` 가 PB 가 본 계산과 같을 때만 저장(`pg.save_node` 와 같은 규율 —
     한 장은 모든 단계의 설명을 싣는다)
  ② ★한 장의 모든 숫자가 같은 그래프의 서버 계산 보고에 있다★(전수) · 주인공 비중 = 그 노드 view 의 비중 그대로
  ③ 실패 노드는 빠지지 않는다 — '계산 못 함 + 사유' · 연습용(합성) 계보면 한 장이 그렇다고 말한다
  ④ 주인공은 비중 표를 내는 계산된 노드만 · 남의 고객 404(전수) · 보관한 고객은 만들 수 없다(읽기는 된다)
  ⑤ 지우기는 ★고객에게 보여 준 적 없는 한 장만★(PB6 가 보여 준 때를 적는다)
  ⑥ 미리 묻기(AI) — 근거는 ★그 한 장의 줄뿐★ · 문장마다 줄 · 그 줄의 숫자만 · 투자 판단은 고객용 고정 문장 · 키 없으면 사유
"""
from __future__ import annotations

import json
import os
import re
import tempfile

import pytest
from fastapi.testclient import TestClient

import src.database as dbmod
from src.api import allocation_graph_nodes as gn
from src.api.protected_routes import PROTECTED, REQUIRE_LOGIN
from src.domain.auth_identity import ROLE_ANALYST
from src.engine import portfolio_graph as pg
from src.services.canvas_assist import service as svc
from src.services.canvas_assist.narrate import flow_order
from src.services.narrative.claude_client import ClaudeClient
from tests.test_ai0_canvas_assist import FakeSDK, _client, _msg

_SECRET = "pb4-sheets-routes-secret-0123456789abcdef"
BASE = "/api/v1/pb/clients"
T3 = ["005930", "000660", "035420"]


def _n(i, t, **p):
    return {"id": i, "type": t, "params": p, "position": {"x": 0, "y": 0}}


def _e(s, sp, t, tp):
    return {"id": f"{s}.{sp}->{t}.{tp}", "source": s, "source_port": sp, "target": t, "target_port": tp}


def _graph(*, broken=False):
    nodes = [_n("c", "client_profile", alias="고객 A-12", risk_tolerance="moderate"),
             _n("u", "universe", tickers=T3, weights={"005930": 50, "000660": 30, "035420": 20}),
             _n("now", "current_weights"), _n("a", "account", **({} if broken else {"account_type": "irp"})),
             _n("r", "returns"), _n("e", "estimate"), _n("o", "optimizer", model="risk_parity")]
    edges = [_e("u", "universe", "now", "universe"), _e("now", "weights", "a", "weights"), _e("c", "client", "a", "client"),
             _e("u", "universe", "r", "universe"), _e("r", "returns", "e", "returns"), _e("r", "returns", "o", "returns"),
             _e("e", "belief", "o", "belief")]
    return {"format": pg.FORMAT, "version": pg.VERSION, "nodes": nodes, "edges": edges}


def _report(g):
    return pg.run(g, gn.REGISTRY)


@pytest.fixture()
def client(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp.name}")
    monkeypatch.setenv("AUTH_SECRET", _SECRET)
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CANVAS_ASSIST_HOURLY_LIMIT", raising=False)
    monkeypatch.setattr(ClaudeClient, "_singleton", None)
    monkeypatch.setattr(dbmod, "DATABASE_URL", f"sqlite:///{tmp.name}", raising=False)
    svc.reset()
    dbmod.reset_session()
    dbmod.init_db()
    dbmod.create_user("alice", "alice-pw", role=ROLE_ANALYST)
    dbmod.create_user("bob", "bob-pw", role=ROLE_ANALYST)
    from src.app_factory import create_app
    with TestClient(create_app()) as c:
        yield c
    svc.reset()
    dbmod.reset_session()
    try:
        os.unlink(tmp.name)
    except OSError:
        pass


def _auth(client, user):
    tok = client.post("/api/v1/auth/login", json={"username": user, "password": f"{user}-pw"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def _cid(client, h, alias="고객 A-12"):
    return client.post(BASE, json={"alias": alias}, headers=h).json()["client_id"]


def _make(client, h, cid, g=None, focus="o", **kw):
    g = g or _graph()
    rep = _report(g)
    body = {"graph": g, "focus_node_id": focus, "preview": _seen(rep), "title": "10월 점검 한 장", **kw}
    return client.post(f"{BASE}/{cid}/snapshots", json=body, headers=h), rep


def _seen(rep):
    """PB 가 본 계산 — 노드마다 view 해시(계산 못 한 노드는 null)."""
    return {nid: r["view_hash"] for nid, r in rep["nodes"].items()}


_NUM = re.compile(r"\d+(?:\.\d+)?")


def _numbers(obj) -> set[str]:
    """JSON 안의 모든 숫자(수 값과 글자 속 숫자) — 정수로 같은 수는 같은 꼴로."""
    out: set[str] = set()

    def norm(x: str) -> str:
        return str(int(float(x))) if float(x).is_integer() else str(float(x))

    def walk(v):
        if isinstance(v, bool) or v is None:
            return
        if isinstance(v, (int, float)):
            out.add(norm(str(v)))
        elif isinstance(v, str):
            out.update(norm(m) for m in _NUM.findall(v))
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk(obj)
    return out


# ── ① · ② 만들기 · 숫자 ──────────────────────────────────────────────────

def test_sheet_is_the_server_recomputation_of_the_same_graph(client):
    h = _auth(client, "alice")
    cid = _cid(client, h)
    r, rep = _make(client, h, cid)
    assert r.status_code == 201, r.text
    meta = r.json()
    assert meta["sheet_id"].startswith("sh_") and meta["focus_node_id"] == "o" and meta["shared"] is False
    sheet = client.get(f"{BASE}/{cid}/snapshots/{meta['sheet_id']}", headers=h).json()["sheet"]
    # 흐름 순서의 모든 노드 — 하나도 빠지지 않는다
    assert [s["node_id"] for s in sheet["steps"]] == flow_order(_graph())
    assert sorted(flow_order(_graph())) == sorted(n["id"] for n in _graph()["nodes"])
    # 주인공 비중 = 그 노드 view 의 비중 그대로(반올림·합계를 새로 만들지 않는다) · 이름은 서버 이름표
    view = rep["nodes"]["o"]["view"]
    assert {w["code"]: w["pct"] for w in sheet["focus"]["weights"]} == view["weights"]
    assert {w["code"]: w["name"] for w in sheet["focus"]["weights"]} == {k: view["labels"][k] for k in view["weights"]}
    # 설명은 서버 설명 그대로
    by = {s["node_id"]: s for s in sheet["steps"]}
    assert by["o"]["explain"] == rep["nodes"]["o"]["explain"]


def test_every_number_on_the_sheet_is_in_the_server_report(client):
    """★전수★ — 한 장의 내용(단계 설명 · 주인공 비중)의 숫자는 모두 같은 그래프의 서버 보고(설명·view)에 있다."""
    h = _auth(client, "alice")
    cid = _cid(client, h)
    r, rep = _make(client, h, cid)
    sheet = client.get(f"{BASE}/{cid}/snapshots/{r.json()['sheet_id']}", headers=h).json()["sheet"]
    have = _numbers([{"explain": x.get("explain"), "view": x.get("view"), "reason": x.get("reason")} for x in rep["nodes"].values()])
    on_sheet = _numbers({"steps": sheet["steps"], "focus": sheet["focus"]})
    assert on_sheet, "공허하지 않다 — 한 장에 숫자가 있다"
    assert on_sheet <= have, f"보고에 없는 숫자: {sorted(on_sheet - have)}"


def test_stale_preview_is_refused_and_nothing_is_saved(client):
    h = _auth(client, "alice")
    cid = _cid(client, h)
    g = _graph()
    seen = _seen(_report(g))
    for nid in ("o", "a"):                       # 주인공도, ★주인공이 아닌 노드도★ — 한 장은 모든 단계의 설명을 싣는다
        stale = {**seen, nid: "0" * 64}
        r = client.post(f"{BASE}/{cid}/snapshots", json={"graph": g, "focus_node_id": "o", "preview": stale, "title": "낡음"},
                        headers=h)
        assert r.status_code == 409 and "다시 계산" in r.text, nid
    missing = {k: v for k, v in seen.items() if k != "a"}                     # 본 적 없는 노드가 있어도
    r = client.post(f"{BASE}/{cid}/snapshots", json={"graph": g, "focus_node_id": "o", "preview": missing, "title": "낡음"},
                    headers=h)
    assert r.status_code == 409
    assert client.get(f"{BASE}/{cid}/snapshots", headers=h).json()["sheets"] == []
    r = client.post(f"{BASE}/{cid}/snapshots", json={"graph": g, "focus_node_id": "o", "preview": seen, "title": "짝"}, headers=h)
    assert r.status_code == 201                                                # 짝 — 본 것과 같으면 둔다


# ── ③ 실패 노드 · 연습용 ─────────────────────────────────────────────────

def test_failed_nodes_stay_on_the_sheet_with_their_reason(client):
    h = _auth(client, "alice")
    cid = _cid(client, h)
    r, rep = _make(client, h, cid, g=_graph(broken=True))
    assert r.status_code == 201, r.text
    sheet = client.get(f"{BASE}/{cid}/snapshots/{r.json()['sheet_id']}", headers=h).json()["sheet"]
    a = next(s for s in sheet["steps"] if s["node_id"] == "a")
    assert a["status"] == "failed" and "계좌 유형" in a["reason"] and a["explain"] is None
    o = next(s for s in sheet["steps"] if s["node_id"] == "o")
    assert o["status"] == "ok" and o["explain"]["title"]                     # 짝 — 계산된 노드는 설명이 있다


def test_practice_lineage_is_said_on_the_sheet(client):
    h = _auth(client, "alice")
    cid = _cid(client, h)
    r, rep = _make(client, h, cid)
    assert rep["nodes"]["o"]["lineage"]["practice"] is True                   # 전제 — 연습 모드
    assert r.json()["practice"] is True
    sheet = client.get(f"{BASE}/{cid}/snapshots/{r.json()['sheet_id']}", headers=h).json()["sheet"]
    assert sheet["practice"] is True and "연습용" in sheet["practice_note"]


# ── ④ 주인공 · 소유 · 보관 ───────────────────────────────────────────────

@pytest.mark.parametrize("focus,word", [("r", "비중"), ("zz", "없어요")])
def test_focus_must_be_a_computed_weights_node(client, focus, word):
    h = _auth(client, "alice")
    cid = _cid(client, h)
    g = _graph()
    body = {"graph": g, "focus_node_id": focus, "preview": _seen(_report(g)), "title": "한 장"}
    r = client.post(f"{BASE}/{cid}/snapshots", json=body, headers=h)
    assert r.status_code == 422 and word in r.text, r.text


def test_failed_focus_is_refused(client):
    h = _auth(client, "alice")
    cid = _cid(client, h)
    g = _graph()
    g["nodes"][-1]["params"] = {"model": "nope"}                              # 옵티마이저 실패
    body = {"graph": g, "focus_node_id": "o", "preview": _seen(_report(g)), "title": "한 장"}
    r = client.post(f"{BASE}/{cid}/snapshots", json=body, headers=h)
    assert r.status_code == 422


_SHEET_ROUTES = sorted(k for k in PROTECTED if "/snapshots" in k[1])


def test_there_are_sheet_routes_to_check():
    assert len(_SHEET_ROUTES) >= 5
    assert all(PROTECTED[k][0] == REQUIRE_LOGIN for k in _SHEET_ROUTES)


@pytest.mark.parametrize(("method", "path"), _SHEET_ROUTES)
def test_every_sheet_route_refuses_someone_elses_client(client, method, path):
    a, b = _auth(client, "alice"), _auth(client, "bob")
    cid = _cid(client, a)
    made, rep = _make(client, a, cid)
    sid = made.json()["sheet_id"]
    url = path.replace("{cid}", cid).replace("{sid}", sid)
    body = None
    if method == "POST" and path.endswith("/snapshots"):
        body = {"graph": _graph(), "focus_node_id": "o", "preview": _seen(rep), "title": "t"}
    elif path.endswith("/ask"):
        body = {"question": "비중이 어떻게 되나요?"}
    r = client.request(method, url, json=body, headers=b)
    assert r.status_code == 404 and r.json()["detail"] == "그 고객이 없어요.", (method, path, r.text)


def test_archived_client_cannot_get_a_new_sheet_but_old_ones_are_readable(client):
    h = _auth(client, "alice")
    cid = _cid(client, h)
    made, _ = _make(client, h, cid)
    client.post(f"{BASE}/{cid}/archive", headers=h)
    r, _ = _make(client, h, cid)
    assert r.status_code == 409 and "보관" in r.text
    assert client.get(f"{BASE}/{cid}/snapshots/{made.json()['sheet_id']}", headers=h).status_code == 200


def test_client_alias_inside_the_graph_is_checked(client):
    h = _auth(client, "alice")
    cid = _cid(client, h)
    g = _graph()
    g["nodes"][0]["params"]["alias"] = "010-1234-5678"
    body = {"graph": g, "focus_node_id": "o", "preview": {}, "title": "한 장"}
    r = client.post(f"{BASE}/{cid}/snapshots", json=body, headers=h)
    assert r.status_code == 422 and "전화번호" in r.text


# ── ⑤ 지우기 ────────────────────────────────────────────────────────────

def test_delete_only_while_never_shown_to_the_client(client):
    h = _auth(client, "alice")
    cid = _cid(client, h)
    s1 = _make(client, h, cid)[0].json()["sheet_id"]
    s2 = _make(client, h, cid)[0].json()["sheet_id"]
    assert client.delete(f"{BASE}/{cid}/snapshots/{s1}", headers=h).status_code == 200
    assert [x["sheet_id"] for x in client.get(f"{BASE}/{cid}/snapshots", headers=h).json()["sheets"]] == [s2]
    from src.services import pb_clients as pbc
    pbc.mark_shared(s2)                                                       # PB6 가 고객 주소를 만들 때 적는다
    r = client.delete(f"{BASE}/{cid}/snapshots/{s2}", headers=h)
    assert r.status_code == 409 and "보여 준" in r.text
    assert client.get(f"{BASE}/{cid}/snapshots/{s2}", headers=h).json()["shared"] is True


def test_client_list_tells_the_last_sheet(client):
    h = _auth(client, "alice")
    cid = _cid(client, h)
    assert client.get(BASE, headers=h).json()["clients"][0]["last_sheet_at"] is None
    _make(client, h, cid)
    assert client.get(BASE, headers=h).json()["clients"][0]["last_sheet_at"]


# ── ⑥ 미리 묻기 ─────────────────────────────────────────────────────────

def _sheet(client, h):
    cid = _cid(client, h)
    made, rep = _make(client, h, cid)
    sid = made.json()["sheet_id"]
    return cid, sid, client.get(f"{BASE}/{cid}/snapshots/{sid}", headers=h).json()["sheet"]


def _fake(payload, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    sdk = FakeSDK(reply=_msg(payload))
    monkeypatch.setattr(ClaudeClient, "_singleton", _client(sdk, key="test-key-not-real"))
    return sdk


def test_ask_without_a_key_says_why(client):
    h = _auth(client, "alice")
    cid, sid, _ = _sheet(client, h)
    r = client.post(f"{BASE}/{cid}/snapshots/{sid}/ask", json={"question": "비중은요?"}, headers=h)
    assert r.status_code == 200 and r.json()["available"] is False and r.json()["reason"]


def test_ask_is_grounded_only_in_the_sheet(client, monkeypatch):
    h = _auth(client, "alice")
    cid, sid, sheet = _sheet(client, h)
    w = sheet["focus"]["weights"][0]
    sdk = _fake({"answerable": True, "why_not": "none", "sentences": [
        {"text": f"{w['name']} 비중은 {w['pct']}% 예요.", "fact_ids": ["f1"]},
        {"text": "기대 수익은 77.7% 예요.", "fact_ids": ["f1"]}]}, monkeypatch)
    r = client.post(f"{BASE}/{cid}/snapshots/{sid}/ask", json={"question": "비중은요?"}, headers=h)
    body = r.json()
    assert body["available"] is True, body
    assert [s["text"] for s in body["answer"]["sentences"]] == [f"{w['name']} 비중은 {w['pct']}% 예요."]
    assert [x["code"] for x in body["rejected"]] == ["numbers"]               # 한 장에 없는 숫자는 버린다
    sent = sdk.beta.messages.calls[-1] if sdk.beta.messages.calls else sdk.messages.calls[-1]
    prompt = json.dumps(sent, ensure_ascii=False, default=str)
    # 근거 줄은 한 장에서만 — 한 장의 단계 설명 문장이 있고, 한 장에 없는 문장은 없다
    assert sheet["steps"][-1]["explain"]["title"] in prompt
    # 비중 줄은 한 장의 비중을 한 문장으로 이은 것 — 그 숫자는 모두 한 장의 것이다
    assert _numbers(body["facts"]["f1"]["text"]) and _numbers(body["facts"]["f1"]["text"]) <= _numbers(sheet["focus"])


def test_investment_judgement_gets_the_client_sentence(client, monkeypatch):
    h = _auth(client, "alice")
    cid, sid, _ = _sheet(client, h)
    _fake({"answerable": False, "why_not": "judgement", "sentences": []}, monkeypatch)
    r = client.post(f"{BASE}/{cid}/snapshots/{sid}/ask", json={"question": "지금 사도 되나요?"}, headers=h)
    ans = r.json()["answer"]
    assert ans["answerable"] is False and "담당 PB" in ans["cannot"]


# ── 개인정보 모양 검사가 날짜를 계좌번호로 보지 않는다 (PB4 E2E 에서 찾음) ─────────────

@pytest.mark.parametrize("text", ["고객 A-12 2026-10-29 한 장", "PB4 한 장 ab3c12 2026-10-29 한 장", "2026.10.29 점검 · 고객 7"])
def test_dates_next_to_digits_are_not_account_numbers(text):
    """제목에 날짜를 붙이면(별칭 끝 숫자 + 2026-10-29) 공백·하이픈을 걷은 숫자열이 9자리를 넘어 계좌번호로 잘못 봤다."""
    from src.domain.pii_guard import pii_reason
    assert pii_reason(text, label="한 장 제목", max_len=80) is None


@pytest.mark.parametrize("text", ["123-456-789012 점검", "고객 110 2345 678901", "2026-10-29 110-234-567890"])
def test_account_shaped_runs_are_still_refused(text):
    """짝 — 날짜를 빼도 계좌번호 모양은 그대로 거절한다."""
    from src.domain.pii_guard import pii_reason
    assert "계좌번호" in (pii_reason(text, label="한 장 제목", max_len=80) or "")


def test_sheet_id_of_another_client_is_404_even_for_the_owner(client):
    h = _auth(client, "alice")
    c1, c2 = _cid(client, h), _cid(client, h, alias="고객 B")
    sid = _make(client, h, c1)[0].json()["sheet_id"]
    assert client.get(f"{BASE}/{c2}/snapshots/{sid}", headers=h).status_code == 404
    assert client.delete(f"{BASE}/{c2}/snapshots/{sid}", headers=h).status_code == 404
    assert client.get(f"{BASE}/{c1}/snapshots/{sid}", headers=h).status_code == 200            # 짝


def test_ask_does_not_take_facts_from_the_request(client):
    """근거는 서버가 저장한 한 장뿐 — 요청이 사실 줄을 보낼 칸이 없다(넣으면 422)."""
    h = _auth(client, "alice")
    cid, sid, _ = _sheet(client, h)
    r = client.post(f"{BASE}/{cid}/snapshots/{sid}/ask",
                    json={"question": "비중은요?", "facts": [{"text": "삼성전자 99%"}]}, headers=h)
    assert r.status_code == 422


def test_archived_client_is_refused_before_any_recomputation(client, monkeypatch):
    """보관한 고객이면 다시 계산하기 ★전에★ 멈춘다(무거운 계산을 헛되이 돌리지 않는다)."""
    from src.api import pb_client_routes as routes
    h = _auth(client, "alice")
    cid = _cid(client, h)
    client.post(f"{BASE}/{cid}/archive", headers=h)
    calls = []
    monkeypatch.setattr(routes, "_recompute", lambda *a: calls.append(a) or {"ok": False, "code": "stale", "message": "x"})
    r = client.post(f"{BASE}/{cid}/snapshots", json={"graph": _graph(), "focus_node_id": "o", "preview": {}, "title": "t"}, headers=h)
    assert r.status_code == 409 and "보관" in r.text and calls == []
