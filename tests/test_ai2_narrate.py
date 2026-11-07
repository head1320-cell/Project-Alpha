"""AI2 · AI 풀어 쓰기 — ★서버가 봉인한 설명만★ 근거로, 문단마다 근거 노드를 대고 그 노드의 숫자만
==============================================================================
스펙 `docs/superpowers/specs/2026-10-16-cf-comfy-canvas-claude-design.md` §AI1~AI5 표의 AI2 ·
사용자 결정(2026-10-22): 근거 = 서명한 사실 · 문단마다 근거 칩 · 누를 때만 · 계산된 그래프 전체.

## 거는 것 (짝으로 항상-통과·항상-거부 구현을 배제한다)
- 봉인: `/run` 이 노드 설명마다 `explain_sig` — 같은 문서면 통과 · 설명 한 글자·위 노드 설정이 바뀌면 실패(짝: 아래만 바뀌면 위는 통과) ·
  자리·경유점·이름은 무관 · 브라우저 왕복(`25.0` → `25`)에도 통과 · 다른 키·다른 용도 키로는 실패 · 엔진 결과는 서명 칸 말고 그대로.
- narrate: 확인된 사실만 근거 · 깨진 사실은 사유와 함께 `dropped` · 모두 깨지면 부르기 전에 못 보임 · 키 없음 = 사유 + 데모 글 0 ·
  문단 검사(근거 노드 없음 · 확인 안 된 노드 · ★그 문단 근거 노드 밖 숫자★(짝: 안 숫자) · 금지 표현 · 길이 · 5개) ·
  ★연습용 경고는 서버가 붙인다★(짝: 연습용이 없으면 없다) · 한도는 추천과 한 그릇 · 캐시 · 키 누출 0 · 경로 401/200/422 · 보호 목록·지도.

★실제 Claude 응답은 관측하지 않는다★ — 키가 없다. 가짜 SDK 를 주입한다(네트워크 0).
"""
from __future__ import annotations

import copy
import json
import logging
import os

import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.api import allocation_graph_routes as routes  # noqa: E402
from src.api import auth  # noqa: E402
from src.domain import fact_seal as fs  # noqa: E402
from src.engine import portfolio_graph as pg  # noqa: E402
from src.services.canvas_assist import ground as gr  # noqa: E402
from src.services.canvas_assist import narrate as nr  # noqa: E402
from src.services.canvas_assist import prompts as pr  # noqa: E402
from src.services.canvas_assist import service as svc  # noqa: E402
from src.services.narrative.claude_client import ClaudeClient  # noqa: E402
from tests.test_ai0_canvas_assist import (  # noqa: E402
    SECRET,
    FakeSDK,
    _auth,
    _blob,
    _client,
    _msg,
    _no_secret,
    api,  # noqa: F401 — 로그인 경로 픽스처
)

F = {"format": "project-alpha.portfolio-graph", "version": 1}
KINDS = routes._kinds()


def _n(i, t, x=0, y=0, **p):
    return {"id": i, "type": t, "params": p, "position": {"x": x, "y": y}}


def _e(s, sp, t, tp):
    return {"id": f"{s}.{sp}->{t}.{tp}", "source": s, "source_port": sp, "target": t, "target_port": tp}


DOC = {**F, "nodes": [_n("u", "universe", tickers=["005930", "000660"]), _n("r", "returns", 320), _n("es", "estimate", 640),
                      _n("o", "optimizer", 960)],
       "edges": [_e("u", "universe", "r", "universe"), _e("r", "returns", "es", "returns"),
                 _e("r", "returns", "o", "returns"), _e("es", "belief", "o", "belief")]}
KEY = b"k" * 32            # 서비스·직접 봉인용 — 경로가 봉인한 것은 그때의 키(`_route_key()`)로 확인한다


def _route_key() -> bytes:
    return auth.derived_key(fs.PURPOSE)


@pytest.fixture(scope="module")
def report():
    return routes._graph_run(copy.deepcopy(DOC), None, None)


def _facts(rep):
    return [{"node_id": nid, "explain": r["explain"], "sig": r["explain_sig"]} for nid, r in rep["nodes"].items()]


def _js(v):
    """브라우저 왕복 흉내 — JSON.parse 뒤 정수인 수는 정수(`25.0` → `25`)."""
    def fix(x):
        if isinstance(x, float) and x.is_integer():
            return int(x)
        if isinstance(x, dict):
            return {k: fix(y) for k, y in x.items()}
        if isinstance(x, list):
            return [fix(y) for y in x]
        return x
    return fix(json.loads(json.dumps(v)))


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_MODEL", raising=False)
    monkeypatch.delenv("CANVAS_ASSIST_HOURLY_LIMIT", raising=False)
    monkeypatch.setattr(ClaudeClient, "_singleton", None)
    svc.reset()
    yield
    svc.reset()


# ═════════════════════════════════════════════════════════════════════════════
# 1. 봉인
# ═════════════════════════════════════════════════════════════════════════════

def test_run_seals_every_explain_and_the_same_document_verifies(report):
    deep = fs.deep_sigs(DOC)
    assert report["nodes"] and all(isinstance(r.get("explain_sig"), str) and r["explain_sig"] for r in report["nodes"].values())
    for nid, r in report["nodes"].items():
        assert fs.verify(_route_key(), nid, r["type"], deep[nid], r["explain"], r["explain_sig"]), nid


def test_the_engine_result_is_unchanged_but_for_the_seal(report):
    eng = pg.run(copy.deepcopy(DOC), routes.REGISTRY)

    def strip(nodes):
        return {k: {kk: vv for kk, vv in v.items() if kk not in ("explain_sig", "elapsed_ms")} for k, v in nodes.items()}
    assert all("explain_sig" in v for v in report["nodes"].values())                    # 경로는 봉인한다
    assert strip(report["nodes"]) == strip(eng["nodes"])
    assert all("explain_sig" not in v for v in eng["nodes"].values())                   # 엔진은 그대로


def test_a_changed_explain_fails_and_a_browser_round_trip_passes(report):
    deep = fs.deep_sigs(DOC)
    r = report["nodes"]["o"]
    bad = copy.deepcopy(r["explain"])
    bad["facts"][0] += " "
    assert not fs.verify(_route_key(), "o", r["type"], deep["o"], bad, r["explain_sig"])
    assert fs.verify(_route_key(), "o", r["type"], deep["o"], _js(r["explain"]), r["explain_sig"])          # ★짝★


def test_integral_floats_round_trip():
    ex = {"title": "t", "headline": {"value": 25.0, "text": "25%"}, "facts": [], "trust": []}
    sig = fs.seal(KEY, "o", "optimizer", "d", ex)
    assert fs.verify(KEY, "o", "optimizer", "d", _js(ex), sig)
    assert _js(ex)["headline"]["value"] == 25 and isinstance(_js(ex)["headline"]["value"], int)
    assert not fs.verify(KEY, "o", "optimizer", "d", {**ex, "headline": {"value": 25.5, "text": "25%"}}, sig)  # 짝: 값이 다르면 실패


def test_an_upstream_setting_change_breaks_the_downstream_seal_and_the_pair_downstream_change_keeps_upstream(report):
    up = copy.deepcopy(DOC)
    up["nodes"][0]["params"]["tickers"] = ["005930"]
    deep_up = fs.deep_sigs(up)
    for nid in ("u", "r", "es", "o"):
        r = report["nodes"][nid]
        assert not fs.verify(_route_key(), nid, r["type"], deep_up[nid], r["explain"], r["explain_sig"]), nid
    down = copy.deepcopy(DOC)
    down["nodes"][3]["params"]["model"] = "risk_parity"
    deep_down = fs.deep_sigs(down)
    for nid in ("u", "r", "es"):                                                                    # ★짝★
        r = report["nodes"][nid]
        assert fs.verify(_route_key(), nid, r["type"], deep_down[nid], r["explain"], r["explain_sig"]), nid
    assert not fs.verify(_route_key(), "o", "optimizer", deep_down["o"], report["nodes"]["o"]["explain"], report["nodes"]["o"]["explain_sig"])


def test_positions_waypoints_and_names_do_not_matter_but_a_rewire_does():
    moved = copy.deepcopy(DOC)
    moved["nodes"][1]["position"] = {"x": 5, "y": 999}
    moved["edges"][0]["waypoints"] = [{"x": 1, "y": 2}]
    moved["name"] = "다른 이름"
    assert fs.deep_sigs(moved) == fs.deep_sigs(DOC)
    rewired = copy.deepcopy(DOC)
    rewired["edges"] = [x for x in rewired["edges"] if x["source"] != "es"]
    assert fs.deep_sigs(rewired)["o"] != fs.deep_sigs(DOC)["o"] and fs.deep_sigs(rewired)["es"] == fs.deep_sigs(DOC)["es"]


def test_another_key_or_purpose_cannot_verify(report):
    r = report["nodes"]["u"]
    deep = fs.deep_sigs(DOC)
    assert not fs.verify(auth.derived_key("something-else/v1"), "u", r["type"], deep["u"], r["explain"], r["explain_sig"])
    assert not fs.verify(b"x" * 32, "u", r["type"], deep["u"], r["explain"], r["explain_sig"])
    assert not fs.verify(_route_key(), "u", r["type"], deep["u"], r["explain"], None)
    assert auth.derived_key("a") == auth.derived_key("a") and auth.derived_key("a") != auth.derived_key("b")


def test_the_derived_key_does_not_carry_the_secret(monkeypatch):
    monkeypatch.setenv("AUTH_SECRET", SECRET)
    k = auth.derived_key(fs.PURPOSE)
    assert isinstance(k, bytes) and len(k) == 32
    assert SECRET.encode() not in k and SECRET[:16].encode() not in k


# ═════════════════════════════════════════════════════════════════════════════
# 2. 사실 확인 · 근거
# ═════════════════════════════════════════════════════════════════════════════

def _sealed(nid, type_, explain, doc=DOC, key=KEY):
    return {"node_id": nid, "explain": explain, "sig": fs.seal(key, nid, type_, fs.deep_sigs(doc)[nid], explain)}


EX_U = {"title": "종목 2개를 골랐어요", "facts": ["삼성전자, SK하이닉스"], "trust": []}
EX_O = {"title": "비중을 이렇게 나눴어요", "headline": {"label": "삼성전자 비중", "value": 50.5, "unit": "%", "text": "삼성전자 50.5%"},
        "facts": ["계산 방식: 위험 똑같이"], "trust": [{"state": "confirmed", "text": "비중 계산은 문제없이 끝났어요."}]}
PRACTICE = {"state": "unknown", "text": "연습용 합성 데이터예요.", "kind": "practice"}


def test_verified_facts_come_in_flow_order_and_broken_ones_are_dropped_with_a_reason():
    good_o, good_u = _sealed("o", "optimizer", EX_O), _sealed("u", "universe", EX_U)
    forged = {**_sealed("r", "returns", EX_U), "explain": {**EX_U, "title": "바꿨다"}}
    ghost = {"node_id": "nope", "explain": EX_U, "sig": "x"}
    wrong_type = {"node_id": "es", "explain": EX_U, "sig": fs.seal(KEY, "es", "returns", fs.deep_sigs(DOC)["es"], EX_U)}
    ok, dropped = nr.verify_facts(DOC, [good_o, forged, good_u, ghost, wrong_type], KEY)
    assert [f["node_id"] for f in ok] == ["u", "o"]                                     # 흐름 순서
    assert {d["node_id"] for d in dropped} == {"r", "nope", "es"} and all(d["reason"] for d in dropped)


def test_the_grounding_has_names_and_explain_text_and_says_practice():
    ok, _ = nr.verify_facts(DOC, [_sealed("u", "universe", EX_U), _sealed("o", "optimizer", {**EX_O, "trust": [PRACTICE]})], KEY)
    g = nr.ground(ok, KINDS)
    assert [n["id"] for n in g["nodes"]] == ["u", "o"] and g["nodes"][0]["label"] == "종목 고르기"
    assert g["nodes"][1]["headline"] == "삼성전자 50.5%" and g["practice"] is True
    ok2, _ = nr.verify_facts(DOC, [_sealed("o", "optimizer", EX_O)], KEY)
    assert nr.ground(ok2, KINDS)["practice"] is False                                  # ★짝★


# ═════════════════════════════════════════════════════════════════════════════
# 3. 문단 검사 — 각 검사 + 짝
# ═════════════════════════════════════════════════════════════════════════════

def _g():
    ok, _ = nr.verify_facts(DOC, [_sealed("u", "universe", EX_U), _sealed("o", "optimizer", EX_O)], KEY)
    return nr.ground(ok, KINDS)


def _para(text, ids):
    return {"text": text, "node_ids": ids}


def test_a_grounded_paragraph_passes():
    ok, bad = nr.check({"paragraphs": [_para("삼성전자 비중이 50.5% 로 가장 커요.", ["o"])]}, _g())
    assert bad == [] and ok == [{"text": "삼성전자 비중이 50.5% 로 가장 커요.", "node_ids": ["o"]}]


def test_numbers_must_come_from_the_paragraphs_own_nodes_and_the_pair_passes():
    ok, bad = nr.check({"paragraphs": [_para("삼성전자 비중이 50.5% 예요.", ["u"])]}, _g())
    assert ok == [] and bad[0]["code"] == "numbers" and "50.5" in bad[0]["reason"]
    assert nr.check({"paragraphs": [_para("종목 2개를 골랐어요.", ["u"])]}, _g())[0]        # ★짝★


@pytest.mark.parametrize("para,code", [
    (_para("비중을 나눴어요.", []), "no_source"),
    (_para("비중을 나눴어요.", ["r"]), "unknown_node"),
    (_para("이건 더 나은 전략이에요.", ["o"]), "banned"),
    (_para("가" * 601, ["o"]), "too_long"),
    ({"text": "비중", "node_ids": ["o"], "extra": 1}, "shape"),
    ({"text": "", "node_ids": ["o"]}, "shape"),
])
def test_bad_paragraphs_are_rejected_with_a_reason(para, code):
    ok, bad = nr.check({"paragraphs": [para]}, _g())
    assert ok == [] and bad[0]["code"] == code and bad[0]["reason"]


def test_at_most_five_paragraphs_and_a_malformed_answer_is_reported():
    ok, bad = nr.check({"paragraphs": [_para(f"비중을 나눴어요{'.' * i}", ["o"]) for i in range(1, 8)]}, _g())
    assert nr.MAX_PARAGRAPHS == 5 and len(ok) == 5 and [b["code"] for b in bad] == ["limit", "limit"]
    ok, bad = nr.check({"para": []}, _g())
    assert ok == [] and bad[0]["code"] == "shape"


def test_the_output_schema_closes_objects_and_limits_node_ids_to_verified_ones():
    s = pr.narrate_schema(["u", "o"])
    item = s["properties"]["paragraphs"]["items"]
    assert s["additionalProperties"] is False and item["additionalProperties"] is False
    assert item["properties"]["node_ids"]["items"]["enum"] == ["u", "o"]
    assert "maxItems" not in _blob(s)
    for must in ("근거", "숫자", "번호", "해요"):
        assert must in pr.NARRATE_SYSTEM


# ═════════════════════════════════════════════════════════════════════════════
# 4. 서비스
# ═════════════════════════════════════════════════════════════════════════════

def _narrate(client, facts, graph=DOC, user="alice", key=KEY):
    return svc.narrate(graph, facts, user, catalog=routes._kinds, key=key, client=client)


def test_an_answer_carries_paragraphs_dropped_facts_and_the_server_practice_notice(report):
    facts = _facts(report)
    tampered = {**facts[0], "explain": {**facts[0]["explain"], "title": "지어낸 제목"}}
    sdk = FakeSDK(_msg({"paragraphs": [_para("비중을 이렇게 나눴어요.", ["o"])]}))
    res = _narrate(_client(sdk), [tampered, *facts[1:]], key=_route_key())             # 경로가 봉인한 사실
    assert res["available"] is True and res["source"] == "claude" and res["cached"] is False
    assert res["paragraphs"] == [{"text": "비중을 이렇게 나눴어요.", "node_ids": ["o"]}] and res["rejected"] == []
    assert [d["node_id"] for d in res["dropped"]] == ["u"]
    assert res["notice"] == nr.NOTICE                                                   # 연습용(mock) 결과 — 서버가 붙인다
    kw = sdk.beta.messages.calls[0]
    assert kw["system"] == pr.NARRATE_SYSTEM and kw["output_config"]["effort"] == "medium"
    assert kw["output_config"]["format"]["schema"] == pr.narrate_schema(["r", "es", "o"])
    user = kw["messages"][0]["content"]
    assert "비중을 이렇게 나눴어요" in user and "지어낸 제목" not in user                    # 깨진 사실은 근거가 아니다


def test_no_practice_no_notice():
    sdk = FakeSDK(_msg({"paragraphs": [_para("삼성전자 비중이 50.5% 예요.", ["o"])]}))
    res = _narrate(_client(sdk), [_sealed("o", "optimizer", EX_O)])
    assert res["available"] and res["notice"] is None
    res2 = _narrate(_client(FakeSDK(_msg({"paragraphs": []}))), [_sealed("o", "optimizer", {**EX_O, "trust": [PRACTICE]})])
    assert res2["notice"] == nr.NOTICE                                                  # ★짝★


def test_rejected_paragraphs_travel_with_reasons():
    sdk = FakeSDK(_msg({"paragraphs": [_para("삼성전자 비중이 50.5% 예요.", ["o"]), _para("99% 확실해요.", ["o"])]}))
    res = _narrate(_client(sdk), [_sealed("o", "optimizer", EX_O)])
    assert len(res["paragraphs"]) == 1 and res["rejected"][0]["code"] == "numbers"


@pytest.mark.parametrize("facts,code", [([], "no_facts"), ([{"node_id": "o", "explain": EX_O, "sig": "x"}], "stale_facts")])
def test_without_verified_facts_it_does_not_call(facts, code):
    sdk = FakeSDK(_msg({"paragraphs": []}))
    res = _narrate(_client(sdk), facts)
    assert res["available"] is False and res["reason_code"] == code and res["reason"] and sdk.beta.messages.calls == []
    assert "paragraphs" not in res


def test_no_key_is_unavailable_with_a_reason_and_no_demo_text():
    sdk = FakeSDK(_msg({"paragraphs": [_para("x", ["o"])]}))
    res = _narrate(_client(sdk, key=""), [_sealed("o", "optimizer", EX_O)])
    assert res["available"] is False and res["reason_code"] == "no_key" and res["reason"] == "서버에 Claude 키가 없어요"
    assert sdk.beta.messages.calls == [] and "paragraphs" not in res
    assert "Mock" not in _blob(res) and "데모" not in _blob(res)


def test_an_unreadable_graph_is_refused():
    res = _narrate(_client(FakeSDK(_msg({"paragraphs": []}))), [_sealed("o", "optimizer", EX_O)], graph={"nodes": "x"})
    assert res["available"] is False and res["reason_code"] == "bad_graph"


def test_the_hourly_limit_is_one_budget_with_suggest(monkeypatch):
    monkeypatch.setenv("CANVAS_ASSIST_HOURLY_LIMIT", "1")
    from tests.test_ai0_canvas_assist import BT
    from tests.test_ai0_canvas_assist import DOC as SUG_DOC
    c = _client(FakeSDK(_msg({"suggestions": [BT], "paragraphs": []})))
    assert svc.suggest(SUG_DOC, "alice", catalog=routes._kinds, validate=routes.graph_validate, client=c)["available"]
    res = _narrate(c, [_sealed("o", "optimizer", EX_O)])
    assert res["available"] is False and res["reason_code"] == "rate_limited"
    assert _narrate(c, [_sealed("o", "optimizer", EX_O)], user="bob")["available"]        # 짝: 사용자별


def test_the_cache_answers_the_same_facts_once_and_failures_are_not_cached():
    sdk = FakeSDK(_msg({"paragraphs": [_para("비중을 나눴어요.", ["o"])]}))
    c = _client(sdk)
    _narrate(c, [_sealed("o", "optimizer", EX_O)])
    assert _narrate(c, [_sealed("o", "optimizer", EX_O)])["cached"] is True and len(sdk.beta.messages.calls) == 1
    bad = FakeSDK(_msg(text="{", stop="max_tokens"))
    cb = _client(bad)
    _narrate(cb, [_sealed("u", "universe", EX_U)])
    _narrate(cb, [_sealed("u", "universe", EX_U)])
    assert len(bad.beta.messages.calls) == 2


def test_a_cache_hit_reports_this_requests_dropped_facts():
    """(AI3 설계 중 찾음) 캐시는 근거로 찾는데 `dropped` 는 요청마다 다르다 — 적중해도 이번 요청의 것을 말한다."""
    c = _client(FakeSDK(_msg({"paragraphs": [_para("비중을 나눴어요.", ["o"])]})))
    first = _narrate(c, [_sealed("o", "optimizer", EX_O)])
    assert first["dropped"] == []
    res = _narrate(c, [_sealed("o", "optimizer", EX_O), {"node_id": "u", "explain": EX_U, "sig": "bad"}])
    assert res["cached"] is True and [d["node_id"] for d in res["dropped"]] == ["u"]


def test_the_key_never_reaches_the_response_or_the_log(caplog):
    caplog.set_level(logging.DEBUG)
    boom = _narrate(_client(FakeSDK(exc=RuntimeError(f"bad key {SECRET}"))), [_sealed("o", "optimizer", EX_O)])
    assert boom["available"] is False and boom["reason_code"] == "unexpected"
    _no_secret(_blob(boom))
    _no_secret(caplog.text)
    assert "canvas-assist narrate" in caplog.text


# ═════════════════════════════════════════════════════════════════════════════
# 5. 경로
# ═════════════════════════════════════════════════════════════════════════════

ROUTE = "/api/v1/assist/canvas/narrate"


def test_the_route_needs_login_and_logged_in_gets_the_no_key_reason(api):  # noqa: F811
    body = {"graph": DOC, "facts": [_sealed("o", "optimizer", EX_O, key=_route_key())]}  # 경로가 쓰는 키로
    assert api.post(ROUTE, json=body).status_code == 401
    res = api.post(ROUTE, json=body, headers=_auth(api))
    assert res.status_code == 200 and res.json()["reason_code"] == "no_key"


def test_the_run_route_seal_verifies_through_the_narrate_route(api):  # noqa: F811
    run = api.post("/api/v1/allocation/graph/run", json=DOC).json()
    facts = [{"node_id": k, "explain": _js(v["explain"]), "sig": v["explain_sig"]} for k, v in run["nodes"].items()]
    res = api.post(ROUTE, json={"graph": DOC, "facts": facts}, headers=_auth(api)).json()
    assert res["reason_code"] == "no_key" and res["dropped"] == []                       # 봉인은 통과 — 키가 없어 못 부를 뿐


@pytest.mark.parametrize("body", [
    {"graph": DOC, "facts": [{"node_id": "o", "explain": EX_O, "sig": "x"}] * 121},
    {"graph": DOC, "facts": [{"node_id": "o", "explain": {"title": "x" * 9000}, "sig": "x"}]},
    {"graph": DOC, "facts": [{"node_id": "o", "sig": "x"}]},
])
def test_oversized_or_malformed_requests_are_422(api, body):  # noqa: F811
    assert api.post(ROUTE, json=body, headers=_auth(api)).status_code == 422


def test_the_route_is_login_only_and_on_the_login_map():
    from src.api.protected_routes import PROTECTED, REQUIRE_LOGIN
    level, why = PROTECTED[("POST", ROUTE)]
    assert level == REQUIRE_LOGIN and "Claude" in why
    amap = json.load(open("frontend/src/entities/session/accessMap.json", encoding="utf-8"))
    assert any(f"POST {ROUTE}" in i["routes"] for i in amap["login"]["items"])
    assert gr.numbers_of("x") == set()                                                   # (ground 재사용 확인)
