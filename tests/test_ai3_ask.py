"""AI3 · 노드·선에게 묻기 — ★봉인한 설명·전달 점검만★ 근거로, 문장마다 사실 줄을 대고 그 줄의 숫자만
==============================================================================
스펙 `docs/superpowers/specs/2026-10-16-cf-comfy-canvas-claude-design.md` §AI3 설계 ·
사용자 결정(2026-10-23): 근거 = 고른 것 + 위쪽 전부 + 바로 아래 · 사실 줄마다 칩 · 계산한 뒤에만 · 직전 문답 하나만.

## 거는 것 (짝으로 항상-통과·항상-거부 구현을 배제한다)
- 선 봉인: `/run` 이 전달 점검 기록마다 `sig` — 같은 문서면 통과 · 기록 한 글자 · 위 설정이 바뀌면 실패 · 자리는 무관 · 엔진은 그대로.
- 범위: 노드 = 조상 전부 + 그 노드 + 바로 아래(먼 아래 · 다른 갈래 · 조상→자식 선은 뺌) / 선 = 보내는 쪽 조상 + 양끝 + 그 선.
- 근거 줄: 서버가 id 를 붙인다 · 범위 밖은 줄이 없다 · 관계 문장은 서버가 문서로 다시 만든 것(화면이 보낸 글이 아니다).
- 문장 검사: 사실 줄 ≥1 · 근거에 있는 줄 · ★그 문장이 댄 줄 밖 숫자★(짝: 안 숫자) · 금지 표현 · 길이 · 4문장 · 형식.
  답할 수 없으면 서버 고정 문장(모델 글이 아니다). 연습용 경고는 서버가(짝: 없으면 없다).
- 서비스: 대상 결과가 없으면 부르기 전에 못 보임 · 깨진 기록은 사유와 함께 · 직전 문답은 근거·캐시 열쇠에 들어간다 ·
  한도는 추천·풀어 쓰기와 한 그릇 · 키 없음 = 사유 + 글 0 · 키 누출 0 · 경로 401/200/422 · 보호 목록·지도.

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
from src.domain import fact_seal as fs  # noqa: E402
from src.engine import portfolio_graph as pg  # noqa: E402
from src.services.canvas_assist import ask as ak  # noqa: E402
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
from tests.test_ai2_narrate import _js, _route_key  # noqa: E402

F = {"format": "project-alpha.portfolio-graph", "version": 1}
KINDS = routes._kinds()
KEY = b"k" * 32


def _n(i, t, x=0, y=0, **p):
    return {"id": i, "type": t, "params": p, "position": {"x": x, "y": y}}


def _e(s, sp, t, tp):
    return {"id": f"{s}.{sp}->{t}.{tp}", "source": s, "source_port": sp, "target": t, "target_port": tp}


# u → r → es → o → bt · r → o · r → bt · o → rk · 따로 떨어진 갈래 u2 → r2
DOC = {**F, "nodes": [_n("u", "universe", tickers=["005930", "000660"]), _n("r", "returns", 320), _n("es", "estimate", 640),
                      _n("o", "optimizer", 960), _n("bt", "backtest", 1280), _n("rk", "risk", 1280, 300),
                      _n("u2", "universe", 0, 600, tickers=["035420"]), _n("r2", "returns", 320, 600)],
       "edges": [_e("u", "universe", "r", "universe"), _e("r", "returns", "es", "returns"), _e("r", "returns", "o", "returns"),
                 _e("es", "belief", "o", "belief"), _e("o", "weights", "bt", "weights"), _e("r", "returns", "bt", "returns"),
                 _e("o", "weights", "rk", "weights"), _e("u2", "universe", "r2", "universe")]}
EID = {f"{e['source']}>{e['target']}": pg._edge_id(e) for e in DOC["edges"]}


def _relate(graph):
    return routes._relations(graph, KINDS)


@pytest.fixture(scope="module")
def report():
    return routes._graph_run(copy.deepcopy(DOC), None, None)


def _facts(rep):
    return [{"node_id": k, "explain": v["explain"], "sig": v["explain_sig"]} for k, v in rep["nodes"].items() if v.get("explain_sig")]


def _records(rep):
    """화면이 돌려보내는 꼴 — 기록에서 `sig` 칸을 떼어 따로(봉인은 `sig` 를 붙이기 전의 기록에 대한 것)."""
    return [{"edge_id": k, "record": {kk: vv for kk, vv in v.items() if kk != "sig"}, "sig": v["sig"]}
            for k, v in (rep.get("edges") or {}).items()]


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
# 1. 선 봉인
# ═════════════════════════════════════════════════════════════════════════════

def _rec_ok(graph, eid, rec, sig, key):
    e = next(x for x in graph["edges"] if pg._edge_id(x) == eid)
    return fs.verify(key, eid, fs.EDGE_TYPE, fs.deep_sigs(graph)[e["target"]], rec, sig)


def test_run_seals_every_handoff_record_and_the_same_document_verifies(report):
    edges = report["edges"]
    assert edges and all(isinstance(r.get("sig"), str) and r["sig"] for r in edges.values())
    for eid, r in edges.items():
        rec = {k: v for k, v in r.items() if k != "sig"}
        assert _rec_ok(DOC, eid, rec, r["sig"], _route_key()), eid
        assert _rec_ok(DOC, eid, _js(rec), r["sig"], _route_key()), eid            # 브라우저 왕복


def test_a_changed_record_or_an_upstream_setting_fails_but_a_move_does_not(report):
    eid = EID["r>o"]
    r = report["edges"][eid]
    rec = {k: v for k, v in r.items() if k != "sig"}
    bad = copy.deepcopy(rec)
    bad["facts"][0]["text"] += " "
    assert not _rec_ok(DOC, eid, bad, r["sig"], _route_key())
    up = copy.deepcopy(DOC)
    up["nodes"][0]["params"]["tickers"] = ["005930"]
    assert not _rec_ok(up, eid, rec, r["sig"], _route_key())
    moved = copy.deepcopy(DOC)
    moved["nodes"][3]["position"] = {"x": 1, "y": 2}
    assert _rec_ok(moved, eid, rec, r["sig"], _route_key())                         # ★짝★


def test_the_engine_handoff_records_are_unchanged_but_for_the_seal(report):
    eng = pg.run(copy.deepcopy(DOC), routes.REGISTRY)
    assert all("sig" not in v for v in eng["edges"].values())
    assert {k: {kk: vv for kk, vv in v.items() if kk != "sig"} for k, v in report["edges"].items()} == eng["edges"]


# ═════════════════════════════════════════════════════════════════════════════
# 2. 범위
# ═════════════════════════════════════════════════════════════════════════════

def test_a_node_scope_is_all_ancestors_itself_and_direct_children():
    nodes, edges = ak.scope(DOC, {"kind": "node", "id": "o"})
    assert nodes == ["u", "r", "es", "o", "bt", "rk"]
    assert set(edges) == {EID["u>r"], EID["r>es"], EID["r>o"], EID["es>o"], EID["o>bt"], EID["o>rk"]}
    assert EID["r>bt"] not in edges and EID["u2>r2"] not in edges                    # 조상→자식 선 · 다른 갈래는 뺌


def test_far_descendants_are_out_of_a_node_scope():
    nodes, edges = ak.scope(DOC, {"kind": "node", "id": "es"})
    assert nodes == ["u", "r", "es", "o"] and "bt" not in nodes and "rk" not in nodes
    assert set(edges) == {EID["u>r"], EID["r>es"], EID["es>o"]}


def test_an_edge_scope_is_the_senders_ancestors_both_ends_and_the_edge():
    nodes, edges = ak.scope(DOC, {"kind": "edge", "id": EID["r>o"]})
    assert nodes == ["u", "r", "o"] and set(edges) == {EID["u>r"], EID["r>o"]}


def test_an_unknown_target_has_no_scope():
    assert ak.scope(DOC, {"kind": "node", "id": "nope"}) is None
    assert ak.scope(DOC, {"kind": "edge", "id": "a.b->c.d"}) is None
    assert ak.scope(DOC, {"kind": "group", "id": "o"}) is None


# ═════════════════════════════════════════════════════════════════════════════
# 3. 근거 줄
# ═════════════════════════════════════════════════════════════════════════════

def _sealed(nid, explain, doc=DOC, key=KEY):
    t = next(n["type"] for n in doc["nodes"] if n["id"] == nid)
    return {"node_id": nid, "explain": explain, "sig": fs.seal(key, nid, t, fs.deep_sigs(doc)[nid], explain)}


def _srec(eid, rec, doc=DOC, key=KEY):
    e = next(x for x in doc["edges"] if pg._edge_id(x) == eid)
    return {"edge_id": eid, "record": rec, "sig": fs.seal(key, eid, fs.EDGE_TYPE, fs.deep_sigs(doc)[e["target"]], rec)}


EX_O = {"title": "비중을 이렇게 나눴어요", "headline": {"label": "삼성전자 비중", "value": 50.5, "unit": "%", "text": "삼성전자 50.5%"},
        "facts": ["계산 방식: 위험 똑같이", "종목 2개"], "trust": [{"state": "confirmed", "text": "비중 계산은 문제없이 끝났어요."}],
        "unmeasured": ["거래비용"]}
EX_ES = {"title": "기대 수익을 잡았어요", "facts": ["과거 평균 7.2%"], "trust": [{"state": "assumed", "text": "과거 평균이 이어진다는 가정이에요."}]}
EX_BT = {"title": "과거로 돌려 봤어요", "facts": ["누적 수익 31.4%"], "trust": []}
EX_U2 = {"title": "종목 1개를 골랐어요", "facts": ["NAVER 99"], "trust": []}
PRACTICE = {"state": "unknown", "text": "연습용 합성 데이터예요.", "kind": "practice"}
REC_RO = {"source": "r", "target": "o", "facts": [{"key": "n_obs", "label": "기간", "text": "756일", "value": 756}],
          "facts_reason": None, "checks": ["빈 날"], "issues": [{"level": "lost", "code": "gap", "text": "빈 날 4일을 뺐어요", "fix": None}],
          "issues_reason": None}


def _ground(target=None, question="왜 이렇게 나눴나요?", previous=None, facts=None, records=None, key=KEY):
    target = target or {"kind": "node", "id": "o"}
    facts = facts if facts is not None else [_sealed("o", EX_O), _sealed("es", EX_ES), _sealed("bt", EX_BT), _sealed("u2", EX_U2)]
    records = records if records is not None else [_srec(EID["r>o"], REC_RO)]
    vn, _ = nr.verify_facts(DOC, facts, key)
    vr, _ = ak.verify_records(DOC, records, key)
    return ak.ground(DOC, target, question, previous, vn, vr, KINDS, _relate(DOC))


def test_lines_get_server_ids_and_cover_explain_parts_relations_and_records_in_scope():
    g, refs = _ground()
    ids = [x["id"] for x in g["lines"]]
    assert ids == [f"f{i}" for i in range(1, len(ids) + 1)] and set(refs) == set(ids)
    texts = " | ".join(x["text"] for x in g["lines"])
    for must in ("비중을 이렇게 나눴어요", "삼성전자 50.5%", "계산 방식: 위험 똑같이", "비중 계산은 문제없이 끝났어요.", "거래비용",
                 "과거 평균 7.2%", "누적 수익 31.4%", "756일", "빈 날 4일을 뺐어요"):
        assert must in texts, must
    assert "NAVER 99" not in texts                                                     # 범위 밖 갈래
    rel = [x for x in g["lines"] if x["part"] == "관계"]
    assert rel and all(x["text"] == _relate(DOC)[refs[x["id"]]["target_id"]]["text"] for x in rel)
    assert g["target"] == {"kind": "node", "id": "o", "label": "비중 계산"} and g["question"] == "왜 이렇게 나눴나요?"
    o_fact = next(k for k, v in refs.items() if v["target_id"] == "o" and v["part"] == "사실" and v["index"] == 1)
    assert refs[o_fact] == {"target_kind": "node", "target_id": "o", "part": "사실", "index": 1, "text": "종목 2개"}
    assert all(not any(ch.isdigit() for ch in x["part"]) for x in g["lines"])           # 줄 이름에 숫자가 없다(숫자 검사가 헷갈리지 않게)


def test_previous_turn_and_practice_are_in_the_grounding_and_the_pair():
    g, _ = _ground(previous={"question": "어디서 왔나요?", "answer": "기대 수익에서 왔어요."})
    assert g["previous"] == {"question": "어디서 왔나요?", "answer": "기대 수익에서 왔어요."} and g["practice"] is False
    g2, _ = _ground(facts=[_sealed("o", {**EX_O, "trust": [PRACTICE]})])
    assert g2["previous"] is None and g2["practice"] is True                           # ★짝★


def test_a_broken_record_is_dropped_with_a_reason():
    good = _srec(EID["r>o"], REC_RO)
    forged = {**good, "record": {**REC_RO, "issues": []}}
    ghost = {"edge_id": "x.y->z.w", "record": REC_RO, "sig": "s"}
    ok, dropped = ak.verify_records(DOC, [forged, ghost], KEY)
    assert ok == {} and {d["edge_id"] for d in dropped} == {EID["r>o"], "x.y->z.w"} and all(d["reason"] for d in dropped)
    assert ak.verify_records(DOC, [good], KEY)[0] == {EID["r>o"]: REC_RO}               # ★짝★


# ═════════════════════════════════════════════════════════════════════════════
# 4. 문장 검사
# ═════════════════════════════════════════════════════════════════════════════

def _id(refs, target_id, part, index=0):
    return next(k for k, v in refs.items() if v["target_id"] == target_id and v["part"] == part and v["index"] == index)


def _ans(*sentences, answerable=True, why_not="none"):
    return {"answerable": answerable, "why_not": why_not, "sentences": [{"text": t, "fact_ids": ids} for t, ids in sentences]}


def test_a_grounded_answer_passes():
    g, refs = _ground()
    head = _id(refs, "o", "핵심 값")
    answer, bad = ak.check(_ans(("삼성전자 비중이 50.5% 로 가장 커요.", [head])), g)
    assert bad == [] and answer == {"answerable": True, "cannot": None,
                                    "sentences": [{"text": "삼성전자 비중이 50.5% 로 가장 커요.", "fact_ids": [head]}]}


def test_numbers_must_come_from_the_sentences_own_lines_and_the_pair_passes():
    g, refs = _ground()
    title = _id(refs, "o", "제목")
    answer, bad = ak.check(_ans(("삼성전자 비중이 50.5% 예요.", [title])), g)
    assert answer["sentences"] == [] and bad[0]["code"] == "numbers" and "50.5" in bad[0]["reason"]
    answer, bad = ak.check(_ans(("과거 평균은 7.2% 예요.", [_id(refs, "es", "사실")])), g)          # ★짝★
    assert bad == [] and len(answer["sentences"]) == 1
    answer, bad = ak.check(_ans(("기간은 756일이에요.", [_id(refs, EID["r>o"], "건너간 것")])), g)  # 선의 줄
    assert bad == []


@pytest.mark.parametrize("sentence,code", [
    (("비중을 나눴어요.", []), "no_source"),
    (("비중을 나눴어요.", ["f999"]), "unknown_fact"),
    (("이건 더 나은 전략이에요.", None), "banned"),
    (("가" * 241, None), "too_long"),
])
def test_bad_sentences_are_rejected_with_a_reason(sentence, code):
    g, refs = _ground()
    text, ids = sentence
    answer, bad = ak.check(_ans((text, ids if ids is not None else [_id(refs, "o", "제목")])), g)
    assert answer["sentences"] == [] and bad[0]["code"] == code and bad[0]["reason"]


def test_shape_limit_and_malformed_answers_are_reported():
    g, refs = _ground()
    t = _id(refs, "o", "제목")
    answer, bad = ak.check(_ans(*[(f"비중을 나눴어요{'.' * i}", [t]) for i in range(1, 7)]), g)
    assert ak.MAX_SENTENCES == 4 and len(answer["sentences"]) == 4 and [b["code"] for b in bad] == ["limit", "limit"]
    answer, bad = ak.check({"answerable": True, "why_not": "none", "sentences": [{"text": "x", "fact_ids": [t], "extra": 1}]}, g)
    assert answer["sentences"] == [] and bad[0]["code"] == "shape"
    answer, bad = ak.check({"nope": 1}, g)
    assert answer == {"answerable": False, "cannot": ak.CANNOT["not_in_facts"], "sentences": []} and bad[0]["code"] == "shape"


@pytest.mark.parametrize("why", ["not_in_facts", "judgement", "off_topic"])
def test_cannot_answer_uses_the_servers_fixed_sentence(why):
    g, refs = _ground()
    answer, bad = ak.check(_ans(("이 결과에는 거래비용이 없어요.", [_id(refs, "o", "재지 않은 것")]), answerable=False, why_not=why), g)
    assert answer["answerable"] is False and answer["cannot"] == ak.CANNOT[why] and bad == []
    assert answer["sentences"] == [{"text": "이 결과에는 거래비용이 없어요.", "fact_ids": [_id(refs, "o", "재지 않은 것")]}]
    ok, _ = ak.check(_ans(("비중을 나눴어요.", [_id(refs, "o", "제목")])), g)
    assert ok["cannot"] is None                                                       # ★짝★
    assert set(ak.CANNOT) == {"not_in_facts", "judgement", "off_topic"} and "투자 판단" in ak.CANNOT["judgement"]


def test_the_schema_closes_objects_and_limits_ids_to_lines():
    s = pr.ask_schema(["f1", "f2"])
    sen = s["properties"]["sentences"]["items"]
    assert s["additionalProperties"] is False and sen["additionalProperties"] is False
    assert sen["properties"]["fact_ids"]["items"]["enum"] == ["f1", "f2"]
    assert s["properties"]["why_not"]["enum"] == ["none", "not_in_facts", "judgement", "off_topic"]
    assert "maxItems" not in _blob(s)
    for must in ("근거", "숫자", "투자 판단", "해요"):
        assert must in pr.ASK_SYSTEM


# ═════════════════════════════════════════════════════════════════════════════
# 5. 서비스
# ═════════════════════════════════════════════════════════════════════════════

def _ask(client, target=None, question="왜 이렇게 나눴나요?", previous=None, facts=None, records=None, graph=DOC, user="alice", key=KEY):
    return svc.ask(graph, target or {"kind": "node", "id": "o"}, question, previous,
                   facts if facts is not None else [_sealed("o", EX_O), _sealed("es", EX_ES)],
                   records if records is not None else [_srec(EID["r>o"], REC_RO)],
                   user, catalog=routes._kinds, relate=_relate, key=key, client=client)


def test_an_answer_carries_sentences_cited_lines_and_the_server_notice(report):
    facts, recs = _facts(report), _records(report)
    sdk = FakeSDK(_msg(_ans(("비중은 여기서 나눴어요.", ["f1"]))))
    res = _ask(_client(sdk), facts=facts, records=recs, key=_route_key())
    assert res["available"] is True and res["source"] == "claude" and res["cached"] is False
    assert res["answer"]["sentences"] == [{"text": "비중은 여기서 나눴어요.", "fact_ids": ["f1"]}] and res["rejected"] == []
    assert set(res["facts"]) == {"f1"} and res["facts"]["f1"]["target_id"] == "u"         # 흐름 맨 앞 줄
    assert res["notice"] == nr.NOTICE and res["dropped"] == []                             # mock 결과 — 연습용
    assert res["scope"] == {"nodes": ["u", "r", "es", "o", "bt", "rk"],
                            "edges": sorted([EID["u>r"], EID["r>es"], EID["r>o"], EID["es>o"], EID["o>bt"], EID["o>rk"]])}
    kw = sdk.beta.messages.calls[0]
    assert kw["system"] == pr.ASK_SYSTEM and kw["output_config"]["effort"] == "medium"
    user = kw["messages"][0]["content"]
    assert "왜 이렇게 나눴나요?" in user and "u2" not in user


def test_no_practice_no_notice():
    res = _ask(_client(FakeSDK(_msg(_ans(("비중을 이렇게 나눴어요.", ["f1"]))))), facts=[_sealed("o", EX_O)], records=[])
    assert res["available"] and res["notice"] is None
    res2 = _ask(_client(FakeSDK(_msg(_ans()))), facts=[_sealed("o", {**EX_O, "trust": [PRACTICE]})], records=[])
    assert res2["notice"] == nr.NOTICE                                                    # ★짝★


@pytest.mark.parametrize("target,facts,records,code", [
    ({"kind": "node", "id": "o"}, [], [], "no_facts_target"),
    ({"kind": "node", "id": "o"}, [{"node_id": "o", "explain": EX_O, "sig": "x"}], [], "no_facts_target"),
    ({"kind": "node", "id": "nope"}, None, None, "no_target"),
    ({"kind": "edge", "id": "r.returns->o.returns"}, None, [], "no_facts_target"),
])
def test_without_the_targets_own_result_it_does_not_call(target, facts, records, code):
    sdk = FakeSDK(_msg(_ans()))
    res = _ask(_client(sdk), target=target, facts=facts, records=records)
    assert res["available"] is False and res["reason_code"] == code and res["reason"] and sdk.beta.messages.calls == []
    assert "answer" not in res


def test_an_edge_target_answers_from_its_record():
    sdk = FakeSDK(_msg(_ans(("빈 날 4일을 뺐어요.", ["f3"]))))
    res = _ask(_client(sdk), target={"kind": "edge", "id": EID["r>o"]}, facts=[_sealed("o", EX_O)])
    assert res["available"] is True
    user = sdk.beta.messages.calls[0]["messages"][0]["content"]
    assert "빈 날 4일을 뺐어요" in user and "과거 평균 7.2%" not in user                     # es 는 r→o 선의 범위 밖


def test_dropped_items_inside_the_scope_are_reported_and_outside_are_ignored():
    forged = {**_sealed("es", EX_ES), "explain": {**EX_ES, "title": "바꿨다"}}
    far = {**_sealed("u2", EX_U2), "sig": "bad"}
    res = _ask(_client(FakeSDK(_msg(_ans()))), facts=[_sealed("o", EX_O), forged, far])
    assert [d.get("node_id") for d in res["dropped"]] == ["es"]


def test_the_previous_turn_is_part_of_the_cache_key_and_the_pair_hits():
    sdk = FakeSDK(_msg(_ans(("비중을 나눴어요.", ["f1"]))))
    c = _client(sdk)
    _ask(c, previous={"question": "a", "answer": "b"})
    assert _ask(c, previous={"question": "a", "answer": "b"})["cached"] is True and len(sdk.beta.messages.calls) == 1
    _ask(c, previous={"question": "a", "answer": "c"})
    _ask(c, previous=None)
    _ask(c, question="다른 질문")
    assert len(sdk.beta.messages.calls) == 4


def test_a_cache_hit_reports_this_requests_dropped_items():
    c = _client(FakeSDK(_msg(_ans(("비중을 나눴어요.", ["f1"])))))
    _ask(c, facts=[_sealed("o", EX_O)])
    res = _ask(c, facts=[_sealed("o", EX_O), {**_sealed("es", EX_ES), "sig": "bad"}])
    assert res["cached"] is True and [d["node_id"] for d in res["dropped"]] == ["es"]


def test_no_key_is_unavailable_with_a_reason_and_no_demo_text():
    sdk = FakeSDK(_msg(_ans(("x", ["f1"]))))
    res = _ask(_client(sdk, key=""))
    assert res["available"] is False and res["reason_code"] == "no_key" and sdk.beta.messages.calls == []
    assert "answer" not in res and "Mock" not in _blob(res) and "데모" not in _blob(res)


def test_the_hourly_limit_is_one_budget_with_suggest_and_narrate(monkeypatch):
    monkeypatch.setenv("CANVAS_ASSIST_HOURLY_LIMIT", "2")
    from tests.test_ai0_canvas_assist import BT
    from tests.test_ai0_canvas_assist import DOC as SUG_DOC
    c = _client(FakeSDK(_msg({"suggestions": [BT], "paragraphs": [], **_ans()})))
    assert svc.suggest(SUG_DOC, "alice", catalog=routes._kinds, validate=routes.graph_validate, client=c)["available"]
    assert svc.narrate(DOC, [_sealed("o", EX_O)], "alice", catalog=routes._kinds, key=KEY, client=c)["available"]
    res = _ask(c)
    assert res["available"] is False and res["reason_code"] == "rate_limited"
    assert _ask(c, user="bob")["available"]                                             # 짝: 사용자별


def test_the_key_never_reaches_the_response_or_the_log(caplog):
    caplog.set_level(logging.DEBUG)
    boom = _ask(_client(FakeSDK(exc=RuntimeError(f"bad key {SECRET}"))))
    assert boom["available"] is False and boom["reason_code"] == "unexpected"
    _no_secret(_blob(boom))
    _no_secret(caplog.text)
    assert "canvas-assist ask" in caplog.text


# ═════════════════════════════════════════════════════════════════════════════
# 6. 경로
# ═════════════════════════════════════════════════════════════════════════════

ROUTE = "/api/v1/assist/canvas/ask"


def _body(**kw):
    return {"graph": DOC, "target": {"kind": "node", "id": "o"}, "question": "왜요?",
            "facts": [_sealed("o", EX_O, key=_route_key())], "records": [], **kw}


def test_the_route_needs_login_and_logged_in_gets_the_no_key_reason(api):  # noqa: F811
    assert api.post(ROUTE, json=_body()).status_code == 401
    res = api.post(ROUTE, json=_body(), headers=_auth(api))
    assert res.status_code == 200 and res.json()["reason_code"] == "no_key"


def test_the_run_route_seals_verify_through_the_ask_route(api):  # noqa: F811
    run = api.post("/api/v1/allocation/graph/run", json=DOC).json()
    facts = [{"node_id": k, "explain": _js(v["explain"]), "sig": v["explain_sig"]} for k, v in run["nodes"].items()]
    recs = [{"edge_id": k, "record": _js({kk: vv for kk, vv in v.items() if kk != "sig"}), "sig": v["sig"]}
            for k, v in run["edges"].items()]
    res = api.post(ROUTE, json=_body(facts=facts, records=recs, target={"kind": "edge", "id": EID["r>o"]}),
                   headers=_auth(api)).json()
    assert res["reason_code"] == "no_key" and res["dropped"] == []                       # 봉인은 통과 — 키가 없어 못 부를 뿐


@pytest.mark.parametrize("patch", [
    {"question": ""}, {"question": "   "}, {"question": "가" * 301},
    {"target": {"kind": "group", "id": "o"}},
    {"previous": {"question": "a", "answer": "가" * 1201}},
    {"facts": [{"node_id": "o", "explain": EX_O, "sig": "x"}] * 121},
    {"records": [{"edge_id": "e", "record": {"x": "y" * 9000}, "sig": "x"}]},
    {"records": [{"edge_id": "e", "record": {}, "sig": "x"}] * 241},
])
def test_oversized_or_malformed_requests_are_422(api, patch):  # noqa: F811
    assert api.post(ROUTE, json=_body(**patch), headers=_auth(api)).status_code == 422


def test_the_route_is_login_only_and_on_the_login_map():
    from src.api.protected_routes import PROTECTED, REQUIRE_LOGIN
    level, why = PROTECTED[("POST", ROUTE)]
    assert level == REQUIRE_LOGIN and "Claude" in why
    amap = json.load(open("frontend/src/entities/session/accessMap.json", encoding="utf-8"))
    assert any(f"POST {ROUTE}" in i["routes"] for i in amap["login"]["items"])
