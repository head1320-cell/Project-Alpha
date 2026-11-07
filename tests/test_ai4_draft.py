"""AI4 · 말로 설계 — 말씀 한 문장 → 지금 캔버스를 고치는 초안(스펙 §AI4 설계 · 사용자 결정 2026-10-23)
==============================================================================
## 거는 것 (짝으로 항상-통과·항상-거부 구현을 배제한다)
- ★Claude 는 값을 쓰지 않는다★: 조작은 더하기·잇기·값 넣기(말씀 조각 + 읽는 법)뿐이고 값은 서버가 읽는다 — 스키마에 값 칸이 없고, 값 칸을 더하면 탈락.
- 읽는 법: 프리셋 라벨·옵션(닫힌 집합, 라벨 숫자 ⊆ 조각) · 숫자(조각에 하나 · 단위가 칸과 같음 · 큰 단위·음수는 읽지 않음) · 종목(종목표 정확 일치 — 여러 개·없음은 후보와 사유).
- 조각은 말씀 안에 있어야 한다 · 말로 넣을 수 없는 칸은 탈락 · 칸 형식(범위)을 어기면 탈락.
- 더하기는 카탈로그 안 · 빠진 더하기에 매달린 잇기·값은 함께 탈락 · 잇기는 붙인 문서에 새 오류가 없어야(이미 이어진 입력·타입) — 짝: 빈 입력은 통과.
- 남은 빈 입력·필수 칸은 `empty` 로 사람 말 · 이해 못 함/투자 판단 → 서버 고정 문장, 초안 0 · 요약은 숫자 ⊆ 말씀 · 금지 표현 0.
- 서비스: 키 없음 = 사유 + 초안 0 · 치명 문서 = 부르지 않음 · 캐시(말씀·지금 설정이 다르면 빗나감) · 한도는 다른 AI 와 한 그릇.
- 경로: 로그인 · 말씀 1~300(공백만 거부) · 보호 목록·지도 · 실제 종목표·칸 검사.

★실제 Claude 응답은 관측하지 않는다★ — 가짜 SDK.
"""
from __future__ import annotations

import copy
import json
import os

import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.api import allocation_graph_routes as routes  # noqa: E402
from src.api import canvas_assist_routes as car  # noqa: E402
from src.services.canvas_assist import draft as dr  # noqa: E402
from src.services.canvas_assist import prompts as pr  # noqa: E402
from src.services.canvas_assist import service as svc  # noqa: E402
from src.services.narrative.claude_client import ClaudeClient  # noqa: E402
from tests.test_ai0_canvas_assist import (  # noqa: E402
    BT,
    DOC,
    F,
    FakeSDK,
    _auth,
    _blob,
    _client,
    _msg,
    api,  # noqa: F401 — 로그인 경로 픽스처
)

KINDS = car._draft_kinds()
EMPTY = {**F, "nodes": [], "edges": []}
STOCKS = {"삼성전자": "005930", "SK하이닉스": "000660", "NAVER": "035420"}
SENT = "삼성전자, SK하이닉스, NAVER로 3년 기준 비중을 위험 똑같이 짜 줘"


def fake_resolve(name: str) -> dict:
    """종목표 대역 — 이름 정확 일치·6자리 코드만. '삼성'은 여러 개, 그 밖은 없음."""
    if name in STOCKS:
        return {"code": STOCKS[name], "name": name}
    if name in STOCKS.values():
        return {"code": name, "name": next(k for k, v in STOCKS.items() if v == name)}
    if name == "삼성":
        return {"candidates": [{"code": "005930", "name": "삼성전자"}, {"code": "006400", "name": "삼성SDI"}]}
    return {"candidates": []}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_MODEL", raising=False)
    monkeypatch.delenv("CANVAS_ASSIST_HOURLY_LIMIT", raising=False)
    monkeypatch.setattr(ClaudeClient, "_singleton", None)
    svc.reset()
    yield
    svc.reset()


def _add(ref, kind):
    return {"ref": ref, "kind": kind}


def _con(a, ap, b, bp):
    return {"from": a, "from_port": ap, "to": b, "to_port": bp}


def _set(node, field, quote, how, choice="", names=None):
    return {"node": node, "field": field, "quote": quote, "how": how, "choice": choice, "names": names or []}


def _raw(add=(), connect=(), sets=(), summary="", understood=True, why_not="none"):
    return {"understood": understood, "why_not": why_not, "summary": summary,
            "add": list(add), "connect": list(connect), "set": list(sets)}


BUILD = _raw(add=[_add("u", "universe"), _add("r", "returns"), _add("e", "estimate"), _add("o", "optimizer")],
             connect=[_con("u", "universe", "r", "universe"), _con("r", "returns", "e", "returns"),
                      _con("r", "returns", "o", "returns"), _con("e", "belief", "o", "belief")],
             sets=[_set("u", "tickers", "삼성전자, SK하이닉스, NAVER", "tickers", names=["삼성전자", "SK하이닉스", "NAVER"]),
                   _set("r", "lookback_days", "3년", "preset", "3년"),
                   _set("o", "model", "위험 똑같이", "option", "risk_parity")],
             summary="세 종목으로 비중 계산 흐름을 만들어요")


def _check(raw, graph=EMPTY, sentence=SENT, resolve=fake_resolve):
    g = dr.ground(graph, sentence, KINDS, routes.graph_validate(graph))
    return dr.check(raw, g, graph, KINDS, routes.graph_validate, car._field_errors, resolve)


def _sets(res):
    return {(s["node"], s["field"]): s["value"] for s in res["draft"]["set"]}


def _codes(res):
    return [b["code"] for b in res["rejected"]]


# ═════════════════════════════════════════════════════════════════════════════
# 1. 말로 넣을 수 있는 칸
# ═════════════════════════════════════════════════════════════════════════════

def test_speakable_fields_say_how_they_are_read():
    ret = dr.speakable(KINDS["returns"]["params_schema"])["lookback_days"]
    assert ret["label"] == "기간" and set(ret["read"]) == {"preset", "number"}
    assert ret["presets"] == ["1년", "3년", "5년"] and ret["unit"] == "거래일"
    model = dr.speakable(KINDS["optimizer"]["params_schema"])["model"]
    assert model["read"] == ["option"] and model["options"]["risk_parity"] == "위험 똑같이"
    reb = dr.speakable(KINDS["backtest"]["params_schema"])["rebalance"]            # enum 이 아니라 pattern + 옵션
    assert reb["read"] == ["option"] and reb["options"] == {"M": "매월", "Q": "분기마다"}
    assert dr.speakable(KINDS["universe"]["params_schema"])["tickers"]["read"] == ["tickers"]
    cons = dr.speakable(KINDS["optimizer"]["params_schema"])["constraints"]
    assert cons["read"] == ["preset"] and "20%" in cons["presets"]                   # 객체 칸 — 프리셋만


def test_booleans_text_and_lists_are_not_speakable_pair_numbers_are():
    est = dr.speakable(KINDS["estimate"]["params_schema"])
    assert "conditional" not in est                                                   # 불리언
    assert "benchmark" not in dr.speakable(KINDS["universe"]["params_schema"])        # 글
    assert "views" not in dr.speakable(KINDS["views"]["params_schema"])                # 목록
    assert "number" in dr.speakable(KINDS["optimizer"]["params_schema"])["tau"]["read"]   # ★짝★ 숫자 칸


# ═════════════════════════════════════════════════════════════════════════════
# 2. 근거
# ═════════════════════════════════════════════════════════════════════════════

def test_the_grounding_has_the_sentence_structure_and_readable_fields_but_no_settings():
    g = dr.ground(DOC, SENT, KINDS, routes.graph_validate(DOC))
    assert g["sentence"] == SENT
    assert {"id": "o", "type": "optimizer", "label": "비중 계산"} in g["graph"]["nodes"]
    assert g["kinds"]["returns"]["fields"]["lookback_days"]["presets"] == ["1년", "3년", "5년"]
    assert "conditional" not in g["kinds"]["estimate"]["fields"]
    blob = json.dumps(g["graph"], ensure_ascii=False)
    assert "005930" not in blob and "params" not in blob                               # 지금 설정값은 싣지 않는다
    assert g["procedure"]["steps"]


def test_sentences_are_stripped_and_a_different_sentence_is_a_different_grounding():
    a = dr.ground(DOC, "  3년으로  ", KINDS, routes.graph_validate(DOC))
    assert a["sentence"] == "3년으로" and a != dr.ground(DOC, "5년으로", KINDS, routes.graph_validate(DOC))


# ═════════════════════════════════════════════════════════════════════════════
# 3. 검사 — 값은 서버가 말씀에서 읽는다
# ═════════════════════════════════════════════════════════════════════════════

def test_a_whole_build_on_an_empty_canvas_reads_every_value_from_the_sentence():
    res = _check(BUILD)
    assert res["understood"] is True and res["cannot"] is None and res["rejected"] == []
    d = res["draft"]
    assert [(a["ref"], a["id"], a["kind"]) for a in d["add"]] == [
        ("u", "universe", "universe"), ("r", "returns", "returns"), ("e", "estimate", "estimate"), ("o", "optimizer", "optimizer")]
    assert d["add"][3]["label"] == "비중 계산"
    assert [c["id"] for c in d["connect"]] == ["universe.universe->returns.universe", "returns.returns->estimate.returns",
                                               "returns.returns->optimizer.returns", "estimate.belief->optimizer.belief"]
    assert _sets(res) == {("universe", "tickers"): ["005930", "000660", "035420"], ("returns", "lookback_days"): 756,
                          ("optimizer", "model"): "risk_parity"}
    by = {s["field"]: s for s in d["set"]}
    assert by["lookback_days"]["display"] == "3년" and by["lookback_days"]["quote"] == "3년" and by["lookback_days"]["read"] == "preset"
    assert by["lookback_days"]["label"] == "기간"
    assert by["model"]["display"] == "위험 똑같이" and by["tickers"]["display"] == "삼성전자 · SK하이닉스 · NAVER"
    assert d["empty"] == [] and d["summary"] == "세 종목으로 비중 계산 흐름을 만들어요"


def test_a_value_written_by_the_model_is_refused():
    raw = _raw(add=[_add("r", "returns")], sets=[{**_set("r", "lookback_days", "3년", "preset", "3년"), "value": 1260}])
    res = _check(raw)
    assert _sets(res) == {} and _codes(res) == ["shape"] and "value" in res["rejected"][0]["reason"]


def test_a_preset_label_with_a_number_the_words_lack_is_refused_and_the_pair_passes():
    for quote, label in (("2년", "3년"), ("장기로", "5년")):
        res = _check(_raw(add=[_add("r", "returns")], sets=[_set("r", "lookback_days", quote, "preset", label)]),
                     sentence=f"{quote} 기준으로 볼래")
        assert _sets(res) == {} and _codes(res) == ["numbers"], quote
    res = _check(_raw(add=[_add("r", "returns")], sets=[_set("r", "lookback_days", "5년", "preset", "5년")]), sentence="5년 기준")
    assert _sets(res) == {("returns", "lookback_days"): 1260}                          # ★짝★
    res = _check(_raw(add=[_add("o", "optimizer")], sets=[_set("o", "risk_aversion", "위험을 많이 피하게", "preset", "많이 피함")]),
                 sentence="위험을 많이 피하게 해 줘")
    assert _sets(res) == {("optimizer", "risk_aversion"): 10.0}                         # 숫자 없는 라벨 — 말을 닫힌 집합으로


def test_unknown_presets_and_options_are_refused():
    res = _check(_raw(add=[_add("r", "returns"), _add("o", "optimizer")],
                      sets=[_set("r", "lookback_days", "3년", "preset", "7년"), _set("o", "model", "위험 똑같이", "option", "zzz")]))
    assert _sets(res) == {} and _codes(res) == ["preset", "option"]


@pytest.mark.parametrize("quote,value", [("500거래일", 500), ("500", 500), ("1,000 거래일로", 1000)])
def test_a_number_is_read_from_the_words(quote, value):
    res = _check(_raw(add=[_add("r", "returns")], sets=[_set("r", "lookback_days", quote, "number")]), sentence=f"기간은 {quote} 해 줘")
    assert _sets(res) == {("returns", "lookback_days"): value} and res["draft"]["set"][0]["display"] == quote.strip()


@pytest.mark.parametrize("quote,code", [
    ("500일", "unit"), ("2년", "unit"), ("3년 동안 500", "number_count"), ("기간은 길게", "number_count"),
    ("500.5", "integer"), ("40", "bad_value"), ("1만", "unit"), ("-500", "negative"),
])
def test_numbers_that_cannot_be_read_as_said_are_refused(quote, code):
    res = _check(_raw(add=[_add("r", "returns")], sets=[_set("r", "lookback_days", quote, "number")]), sentence=f"기간 {quote} 로")
    assert _sets(res) == {} and _codes(res) == [code], quote


def test_units_must_match_the_field_and_the_pair_matches():
    raw = _raw(add=[_add("b", "backtest")], sets=[_set("b", "cost_bps", "15bp", "number")])
    assert _sets(_check(raw, sentence="거래비용 15bp")) == {("backtest", "cost_bps"): 15}      # ★짝★
    raw = _raw(add=[_add("b", "backtest")], sets=[_set("b", "cost_bps", "15%", "number")])
    assert _codes(_check(raw, sentence="거래비용 15%")) == ["unit"]


def test_words_not_in_the_sentence_are_refused():
    res = _check(_raw(add=[_add("r", "returns")], sets=[_set("r", "lookback_days", "5년", "preset", "5년")]), sentence="3년으로")
    assert _sets(res) == {} and _codes(res) == ["quote"]


def test_number_how_must_not_carry_a_choice():
    res = _check(_raw(add=[_add("r", "returns")], sets=[_set("r", "lookback_days", "500", "number", choice="1260")]),
                 sentence="기간 500")
    assert _sets(res) == {} and _codes(res) == ["shape"]


def test_stock_names_resolve_exactly_and_ambiguous_or_unknown_names_are_listed_not_guessed():
    sent = "삼성, SK하이닉스, 가짜회사, 005930 으로"
    res = _check(_raw(add=[_add("u", "universe")],
                      sets=[_set("u", "tickers", "삼성, SK하이닉스, 가짜회사, 005930", "tickers", names=["삼성", "SK하이닉스", "가짜회사", "005930"])]),
                 sentence=sent)
    assert _sets(res) == {("universe", "tickers"): ["000660", "005930"]}
    bad = {b["code"]: b["reason"] for b in res["rejected"]}
    assert set(bad) == {"ticker_ambiguous", "ticker_unknown"}
    assert "삼성전자" in bad["ticker_ambiguous"] and "삼성SDI" in bad["ticker_ambiguous"] and "‘삼성’" in bad["ticker_ambiguous"]
    assert "가짜회사" in bad["ticker_unknown"]


def test_tickers_need_at_least_one_resolved_name_and_names_must_be_in_the_words():
    res = _check(_raw(add=[_add("u", "universe")], sets=[_set("u", "tickers", "삼성", "tickers", names=["삼성"])]), sentence="삼성으로")
    assert _sets(res) == {} and _codes(res) == ["ticker_ambiguous"]
    res = _check(_raw(add=[_add("u", "universe")], sets=[_set("u", "tickers", "삼성전자", "tickers", names=["NAVER"])]), sentence="삼성전자로")
    assert _sets(res) == {} and _codes(res) == ["ticker_quote"]


def test_fields_that_cannot_be_spoken_or_do_not_exist_are_refused():
    res = _check(_raw(add=[_add("e", "estimate")], sets=[_set("e", "conditional", "국면 반영", "option", "true"),
                                                          _set("e", "nope", "국면 반영", "number")]), sentence="국면 반영해서")
    assert _sets(res) == {} and _codes(res) == ["not_speakable", "no_field"]
    assert "설정 탭" in res["rejected"][0]["reason"]


def test_how_must_fit_the_field():
    res = _check(_raw(add=[_add("o", "optimizer")], sets=[_set("o", "model", "6", "number")]), sentence="6으로")
    assert _sets(res) == {} and _codes(res) == ["how"]


def test_an_unknown_kind_takes_its_connections_and_values_with_it():
    raw = _raw(add=[_add("x", "magic_box"), _add("r", "returns")],
               connect=[_con("r", "returns", "x", "returns")], sets=[_set("x", "lookback_days", "3년", "preset", "3년")])
    res = _check(raw)
    assert [a["kind"] for a in res["draft"]["add"]] == ["returns"]
    assert res["draft"]["connect"] == [] and _sets(res) == {}
    assert _codes(res) == ["unknown_kind", "depends", "depends"]
    assert "magic_box" in res["rejected"][0]["reason"]


def test_connecting_into_a_filled_input_is_refused_and_the_pair_into_an_empty_input_passes():
    raw = _raw(add=[_add("r2", "returns"), _add("b", "backtest")],
               connect=[_con("r2", "returns", "o", "returns"),                                      # o.returns 는 이미 r 에서
                        _con("o", "weights", "b", "weights"), _con("r", "returns", "b", "returns")])
    res = _check(raw, graph=DOC, sentence="백테스트를 붙여 줘")
    assert [c["id"] for c in res["draft"]["connect"]] == ["o.weights->backtest.weights", "r.returns->backtest.returns"]
    assert _codes(res) == ["multiple_inputs"] and res["rejected"][0]["op"] == "connect"


def test_a_type_mismatch_and_an_unknown_node_are_refused():
    res = _check(_raw(connect=[_con("u", "universe", "o", "views"), _con("ghost", "x", "o", "views")]), graph=DOC, sentence="이어 줘")
    assert res["draft"]["connect"] == [] and _codes(res) == ["type_mismatch", "no_node"]


def test_values_can_go_into_existing_nodes():
    res = _check(_raw(sets=[_set("r", "lookback_days", "5년", "preset", "5년"),
                            _set("u", "tickers", "NAVER", "tickers", names=["NAVER"])]), graph=DOC, sentence="5년으로, 종목은 NAVER")
    assert _sets(res) == {("r", "lookback_days"): 1260, ("u", "tickers"): ["035420"]} and res["draft"]["add"] == []


def test_the_same_field_twice_keeps_the_first():
    res = _check(_raw(sets=[_set("r", "lookback_days", "5년", "preset", "5년"), _set("r", "lookback_days", "1년", "preset", "1년")]),
                 graph=DOC, sentence="5년 아니 1년")
    assert _sets(res) == {("r", "lookback_days"): 1260} and _codes(res) == ["duplicate"]


def test_new_ids_do_not_collide_and_refs_cannot_shadow_nodes():
    graph = {**F, "nodes": [{"id": "optimizer", "type": "optimizer", "params": {}}], "edges": []}
    res = _check(_raw(add=[_add("a", "optimizer"), _add("b", "optimizer"), _add("optimizer", "returns"), _add("a", "returns")]),
                 graph=graph, sentence="둘 더")
    assert [a["id"] for a in res["draft"]["add"]] == ["optimizer_w2", "optimizer_w3"]
    assert _codes(res) == ["ref", "ref"]


def test_limits():
    res = _check(_raw(add=[_add(f"r{i}", "returns") for i in range(dr.MAX_ADD + 1)]), sentence="많이")
    assert len(res["draft"]["add"]) == dr.MAX_ADD and _codes(res) == ["limit"]


def test_what_the_words_leave_out_is_listed_as_empty():
    raw = _raw(add=[_add("u", "universe"), _add("r", "returns"), _add("o", "optimizer")],
               connect=[_con("u", "universe", "r", "universe"), _con("r", "returns", "o", "returns")])
    res = _check(raw, sentence="비중을 짜 줘")
    empty = res["draft"]["empty"]
    assert {(x["node"], x.get("field"), x.get("port")) for x in empty} == {("universe", "tickers", None), ("optimizer", None, "belief")}
    by = {(x.get("field") or x.get("port")): x["why"] for x in empty}
    assert "종목" in by["tickers"] and "말씀에 없어요" in by["tickers"]
    assert "기대 수익" in by["belief"]
    res = _check(BUILD)                                                                    # ★짝★ 다 말했으면 비어 있는 것 없음
    assert res["draft"]["empty"] == []


@pytest.mark.parametrize("why,text", [("judgement", dr.CANNOT["judgement"]), ("off_topic", dr.CANNOT["off_topic"]),
                                      ("none", dr.CANNOT["off_topic"])])
def test_not_understood_gives_a_fixed_server_sentence_and_no_draft(why, text):
    res = _check({**BUILD, "understood": False, "why_not": why, "summary": "삼성전자를 사세요"})
    assert res["understood"] is False and res["cannot"] == text
    assert res["draft"] == {"summary": None, "add": [], "connect": [], "set": [], "empty": []}
    assert "사세요" not in _blob(res)


@pytest.mark.parametrize("summary,code", [("5개 종목으로 짜요", "numbers"), ("견고함이 확인된 설계예요", "banned"), ("가" * 81, "too_long")])
def test_a_bad_summary_is_dropped_with_a_reason_and_the_draft_stays(summary, code):
    res = _check({**BUILD, "summary": summary})
    assert res["draft"]["summary"] is None and _codes(res) == [code] and len(res["draft"]["add"]) == 4


def test_a_broken_answer_is_a_shape_rejection():
    res = _check({"nope": 1})
    assert res["draft"]["add"] == [] and _codes(res) == ["shape"]


# ═════════════════════════════════════════════════════════════════════════════
# 4. 스키마·프롬프트
# ═════════════════════════════════════════════════════════════════════════════

def test_the_schema_has_no_value_field_and_closed_objects():
    s = pr.draft_schema(KINDS)

    def keys(x):                                                                           # 스키마 안의 모든 속성 이름
        if isinstance(x, dict):
            return set(x.get("properties") or {}) | {k for v in x.values() for k in keys(v)}
        return {k for v in x for k in keys(v)} if isinstance(x, list) else set()
    assert not keys(s) & {"value", "values", "params", "number"} and "maxItems" not in _blob(s)   # 값 칸이 없다
    props = s["properties"]
    assert s["additionalProperties"] is False
    for k in ("add", "connect", "set"):
        assert props[k]["items"]["additionalProperties"] is False
    assert props["add"]["items"]["properties"]["kind"]["enum"] == sorted(KINDS)
    assert props["set"]["items"]["properties"]["how"]["enum"] == ["preset", "option", "number", "tickers"]
    assert "lookback_days" in props["set"]["items"]["properties"]["field"]["enum"]
    assert "conditional" not in props["set"]["items"]["properties"]["field"]["enum"]
    assert props["why_not"]["enum"] == ["none", "off_topic", "judgement"]
    for must in ("값", "quote", "비워", "지우지", "투자 판단"):
        assert must in pr.DRAFT_SYSTEM


# ═════════════════════════════════════════════════════════════════════════════
# 5. 서비스
# ═════════════════════════════════════════════════════════════════════════════

def _draft(client, graph=EMPTY, sentence=SENT, user="alice", resolve=fake_resolve):
    return svc.draft(graph, sentence, user, catalog=car._draft_kinds, validate=routes.graph_validate,
                     field_errors=car._field_errors, resolve_ticker=resolve, client=client)


def test_an_answer_carries_the_checked_draft():
    sdk = FakeSDK(_msg(BUILD))
    res = _draft(_client(sdk))
    assert res["available"] is True and res["source"] == "claude" and res["understood"] is True
    assert _sets(res)[("returns", "lookback_days")] == 756 and res["rejected"] == []
    kw = sdk.beta.messages.calls[0]
    assert kw["system"] == pr.DRAFT_SYSTEM and kw["output_config"]["format"]["schema"] == pr.draft_schema(KINDS)
    assert SENT in kw["messages"][0]["content"]


def test_no_key_is_unavailable_with_a_reason_and_no_draft():
    sdk = FakeSDK(_msg(BUILD))
    res = _draft(_client(sdk, key=""))
    assert res["available"] is False and res["reason_code"] == "no_key" and "draft" not in res and sdk.beta.messages.calls == []


def test_a_broken_document_is_not_sent():
    sdk = FakeSDK(_msg(BUILD))
    res = _draft(_client(sdk), graph={"format": "x", "version": 1, "nodes": [], "edges": []})
    assert res["available"] is False and res["reason_code"] == "bad_graph" and sdk.beta.messages.calls == []


def test_the_cache_keys_on_the_sentence_and_on_current_settings():
    sdk = FakeSDK(_msg(_raw()))
    c = _client(sdk)
    _draft(c, graph=DOC)
    assert _draft(c, graph=DOC)["cached"] is True                                           # ★짝★
    assert _draft(c, graph=DOC, sentence="다른 말")["cached"] is False
    other = copy.deepcopy(DOC)
    other["nodes"][0]["params"]["tickers"] = ["035420"]                                     # 구조는 같고 설정만 다름
    assert _draft(c, graph=other)["cached"] is False
    assert len(sdk.beta.messages.calls) == 3


def test_the_hourly_limit_is_one_budget_with_the_other_assists(monkeypatch):
    monkeypatch.setenv("CANVAS_ASSIST_HOURLY_LIMIT", "1")
    c = _client(FakeSDK(_msg({"suggestions": [BT], **BUILD})))
    assert svc.suggest(DOC, "alice", catalog=routes._kinds, validate=routes.graph_validate, client=c)["available"]
    res = _draft(c)
    assert res["available"] is False and res["reason_code"] == "rate_limited"
    assert _draft(c, user="bob")["available"]                                               # 짝: 사용자별


# ═════════════════════════════════════════════════════════════════════════════
# 6. 경로 · 실제 종목표·칸 검사
# ═════════════════════════════════════════════════════════════════════════════

ROUTE = "/api/v1/assist/canvas/draft"


def test_the_route_needs_login_and_logged_in_gets_the_no_key_reason(api):  # noqa: F811
    body = {"graph": DOC, "sentence": SENT}
    assert api.post(ROUTE, json=body).status_code == 401
    res = api.post(ROUTE, json=body, headers=_auth(api))
    assert res.status_code == 200 and res.json()["reason_code"] == "no_key"


@pytest.mark.parametrize("sentence", ["", "   ", "가" * 301])
def test_a_blank_or_long_sentence_is_422(api, sentence):  # noqa: F811
    assert api.post(ROUTE, json={"graph": DOC, "sentence": sentence}, headers=_auth(api)).status_code == 422


def test_the_route_is_login_only_and_on_the_login_map():
    from src.api.protected_routes import PROTECTED, REQUIRE_LOGIN
    level, why = PROTECTED[("POST", ROUTE)]
    assert level == REQUIRE_LOGIN and "Claude" in why
    amap = json.load(open("frontend/src/entities/session/accessMap.json", encoding="utf-8"))
    assert any(f"POST {ROUTE}" in i["routes"] for i in amap["login"]["items"])


def test_the_real_stock_table_resolves_exact_names_and_lists_ambiguous_ones():
    assert car._resolve_ticker("삼성전자") == {"code": "005930", "name": "삼성전자"}
    assert car._resolve_ticker("005930") == {"code": "005930", "name": "삼성전자"}
    amb = car._resolve_ticker("삼성")
    assert "code" not in amb and len(amb["candidates"]) >= 2 and len(amb["candidates"]) <= 3
    assert car._resolve_ticker("없는회사이름") == {"candidates": []}
    assert car._resolve_ticker("999999") == {"candidates": []}                              # 표에 없는 코드는 넣지 않는다


def test_field_errors_name_the_field_and_the_kind_of_error():
    assert car._field_errors("optimizer", {"risk_aversion": 50}) == {("risk_aversion", "less_than_equal")}
    assert car._field_errors("optimizer", {"risk_aversion": 6}) == set()                    # ★짝★
    assert car._field_errors("universe", {}) == {("tickers", "missing")}
    assert car._field_errors("risk", {}) == set()                                           # 설정이 없는 종류
