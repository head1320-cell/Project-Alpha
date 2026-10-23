"""AI0 · Claude 서버 기반 + 노드 추천 경로 — ★키가 없으면 AI 글을 만들지 않는다★
==============================================================================
스펙 `docs/superpowers/specs/2026-10-16-cf-comfy-canvas-claude-design.md` §AI0 ·
대상 `src/services/narrative/claude_client.py`(고침) · `src/services/canvas_assist/` ·
`POST /api/v1/assist/canvas/suggest`(로그인)

## 거는 것 (짝으로 항상-통과·항상-거부 구현을 배제한다)
- 기존 클라이언트: API 2026-10-21 은 `temperature` 를 받지 않는다 → 보내지 않는다(짝: model·messages 는 간다) ·
  키 있음 + SDK 없음은 데모 글이 아니라 오류(짝: 키 없음은 지금 그대로 — 범위 밖) · 가격표가 지금 표.
- 구조화 호출: 스키마·effort·서버 거절 대비(fallbacks) 인자 · 거절·잘림·형식 오류·키 없음은 ★데이터 0★ ·
  답한 모델(대체 모델이면 그 모델) · 모르는 모델의 비용은 0 이 아니라 None + 사유.
- 검사(스펙 1~6): 카탈로그 · 연결(타입·찬 입력·순환·없는 포트) · 근거 밖 숫자 · 금지 표현 · 설정값 없음 · 3개 한도 —
  각각 짝(통과하는 것)을 붙인다. 탈락은 조용히 버리지 않고 사유와 함께 낸다.
- 서비스: 쓸 수 없으면 `available:false` + 사유 + 규칙 대체, ★데모 글 0★ · 사용자별 시간당 한도(짝: 캐시 적중은 안 센다) ·
  캐시(짝: 모델이 바뀌면 다시 부른다 · 실패는 캐시하지 않는다) · ★키 값 누출 0★(응답·로그).
- 경로: 로그인 없으면 401(짝: 로그인하면 200) · 보호 목록·로그인 지도에 적힘.

★실제 Claude 응답은 여기서 관측하지 않는다★ — 이 환경엔 키가 없다. 가짜 SDK·클라이언트를 주입한다(네트워크 0).
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from types import SimpleNamespace

import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

import src.services.narrative.claude_client as cc  # noqa: E402
from src.api import allocation_graph_routes as routes  # noqa: E402
from src.services.canvas_assist import check as ck  # noqa: E402
from src.services.canvas_assist import ground as gr  # noqa: E402
from src.services.canvas_assist import prompts as pr  # noqa: E402
from src.services.canvas_assist import service as svc  # noqa: E402
from src.services.narrative.claude_client import ClaudeClient, NarrativeRequest  # noqa: E402

SECRET = "fake-claude-key-thisisaverysecretvalue-0123456789abcdef"   # 가짜 — 진짜 키 접두사를 쓰지 않는다(비밀 훑개 오탐 방지)
F = {"format": "project-alpha.portfolio-graph", "version": 1}
KINDS = routes._kinds()
MOCKS = (cc.MOCK_STOCK_NARRATIVE, cc.MOCK_PORTFOLIO_NARRATIVE, cc.MOCK_MACRO_NARRATIVE,
         cc.MOCK_OPS_NARRATIVE, cc.MOCK_GENERAL_NARRATIVE)


def _n(i, t, **p):
    return {"id": i, "type": t, "params": p}


def _e(s, sp, t, tp):
    return {"id": f"{s}.{sp}->{t}.{tp}", "source": s, "source_port": sp, "target": t, "target_port": tp}


def _a(s, sp, t, tp):
    return {"source": s, "source_port": sp, "target": t, "target_port": tp}


CORE = [_n("u", "universe", tickers=["005930", "000660"]), _n("r", "returns"), _n("es", "estimate"), _n("o", "optimizer")]
CORE_E = [_e("u", "universe", "r", "universe"), _e("r", "returns", "es", "returns"),
          _e("r", "returns", "o", "returns"), _e("es", "belief", "o", "belief")]
DOC = {**F, "nodes": CORE, "edges": CORE_E}
BT = {"kind": "backtest", "attach": [_a("o", "weights", "@new", "weights"), _a("r", "returns", "@new", "returns")],
      "reason": "거래비용과 처음 보는 기간을 아직 재지 않았어요."}


# ── 가짜 SDK ─────────────────────────────────────────────────────────────────

class _Stream:
    def __init__(self, text):
        self.text_stream = iter([text])
        self._text = text

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return SimpleNamespace(usage=SimpleNamespace(input_tokens=10, output_tokens=5))


class _Messages:
    def __init__(self, reply=None, exc=None):
        self.calls: list[dict] = []
        self.reply, self.exc = reply, exc

    def create(self, **kw):
        self.calls.append(kw)
        if self.exc:
            raise self.exc
        return self.reply

    def stream(self, **kw):
        self.calls.append(kw)
        return _Stream("흘려 보낸 글")


class FakeSDK:
    def __init__(self, reply=None, exc=None):
        self.messages = _Messages(reply, exc)
        self.beta = SimpleNamespace(messages=_Messages(reply, exc))


def _msg(payload=None, *, text=None, stop="end_turn", model="claude-opus-5-5", inp=1200, out=300,
         details=None, content=None, iterations=None):
    text = json.dumps(payload, ensure_ascii=False) if text is None else text
    return SimpleNamespace(content=content or [SimpleNamespace(type="text", text=text)], stop_reason=stop,
                           stop_details=details, model=model,
                           usage=SimpleNamespace(input_tokens=inp, output_tokens=out, iterations=iterations))


def _client(sdk=None, key=SECRET):
    c = ClaudeClient(api_key=key)
    c._client = sdk
    return c


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_MODEL", raising=False)
    monkeypatch.delenv("CANVAS_ASSIST_HOURLY_LIMIT", raising=False)
    monkeypatch.setattr(ClaudeClient, "_singleton", None)
    svc.reset()
    yield
    svc.reset()


def _blob(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _no_secret(text: str):
    assert SECRET not in text, "키 값이 그대로 나갔다"
    for n in (12, 8):
        assert SECRET[-n:] not in text, f"키 뒤 {n}글자가 나갔다"
    assert SECRET[12:24] not in text, "키 가운데 조각이 나갔다"


# ═════════════════════════════════════════════════════════════════════════════
# 1. 기존 클라이언트 고침
# ═════════════════════════════════════════════════════════════════════════════

def test_invoke_does_not_send_temperature_and_the_pair_sends_model_system_and_messages():
    sdk = FakeSDK(_msg(text="안녕"))
    r = _client(sdk).invoke(NarrativeRequest(system_prompt="시스템", user_prompt="질문", model="claude-opus-5-5"))
    kw = sdk.messages.calls[0]
    assert "temperature" not in kw and "top_p" not in kw and "top_k" not in kw
    assert kw["model"] == "claude-opus-5-5" and kw["system"] == "시스템"            # ★짝★
    assert kw["messages"] == [{"role": "user", "content": "질문"}]
    assert r.content == "안녕" and r.error is None


def test_stream_does_not_send_temperature_either():
    sdk = FakeSDK()
    gen = _client(sdk).stream(NarrativeRequest(system_prompt="s", user_prompt="u"))
    assert list(gen) == ["흘려 보낸 글"]
    kw = sdk.messages.calls[0]
    assert "temperature" not in kw and kw["messages"] == [{"role": "user", "content": "u"}]


def test_key_without_sdk_is_an_error_not_demo_text_and_the_pair_no_key_keeps_todays_demo(monkeypatch):
    monkeypatch.setattr(cc, "ANTHROPIC_AVAILABLE", False)
    req = NarrativeRequest(system_prompt="s", user_prompt="포트폴리오 백테스트 보고서")
    r = ClaudeClient(api_key=SECRET).invoke(req)
    assert r.error == "sdk_missing"
    assert not any(m in r.content for m in MOCKS) and "데모" not in r.content
    chunks = list(ClaudeClient(api_key=SECRET).stream(req))
    assert not any(m in "".join(chunks) for m in MOCKS)
    # ★짝★ 키가 없을 때의 데모 글은 이번 범위 밖 — 지금 그대로(사유 라벨이 붙어 있다).
    r0 = ClaudeClient(api_key="").invoke(req)
    assert r0.content == cc.MOCK_PORTFOLIO_NARRATIVE and r0.error and r0.error.startswith("Mock")


def test_the_price_table_is_the_current_one_and_an_unknown_model_has_no_price():
    assert cc.MODEL_PRICING["claude-opus-5-5"] == {"input": 4.0, "output": 20.0}
    assert cc.MODEL_PRICING["claude-opus-4-6"] == {"input": 5.0, "output": 25.0}       # 15/75 는 낡은 값
    assert cc.MODEL_PRICING["claude-haiku-4-5"] == {"input": 1.0, "output": 5.0}       # 0.8/4 는 낡은 값
    assert cc.MODEL_PRICING["claude-sonnet-5-5"] == {"input": 2.0, "output": 10.0}
    assert cc.price_of("claude-opus-5-5") == {"input": 4.0, "output": 20.0}
    assert cc.price_of("claude-imaginary-9") is None                                   # ★짝★ 다른 모델 값으로 메우지 않는다


# ═════════════════════════════════════════════════════════════════════════════
# 2. 구조화 호출
# ═════════════════════════════════════════════════════════════════════════════

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["x"], "properties": {"x": {"type": "string"}}}


def test_structured_call_sends_schema_effort_and_server_fallback_and_reads_the_json():
    sdk = FakeSDK(_msg({"x": "값"}))
    r = _client(sdk).invoke_structured("시스템", "질문", SCHEMA, model="claude-opus-5-5", effort="medium", max_tokens=8000)
    kw = sdk.beta.messages.calls[0]
    assert kw["betas"] == ["server-side-fallback-2026-07-01"] and kw["fallbacks"] == "default"
    assert kw["output_config"] == {"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}}
    assert kw["model"] == "claude-opus-5-5" and kw["max_tokens"] == 8000 and kw["system"] == "시스템"
    assert kw["messages"] == [{"role": "user", "content": "질문"}]
    assert "temperature" not in kw and "tool_choice" not in kw and "thinking" not in kw
    assert sdk.messages.calls == []                                     # 구조화는 beta 경로만
    assert r.error is None and r.data == {"x": "값"} and r.served_model == "claude-opus-5-5"
    assert r.cost_usd == pytest.approx((1200 * 4 + 300 * 20) / 1e6) and r.cost_note is None


@pytest.mark.parametrize("setup,code", [
    ("no_key", "no_key"), ("sdk_missing", "sdk_missing"), ("circuit", "circuit_open")])
def test_structured_unavailable_states_return_no_data_and_do_not_call(monkeypatch, setup, code):
    sdk = FakeSDK(_msg({"x": "값"}))
    if setup == "no_key":
        c = _client(sdk, key="")
    elif setup == "sdk_missing":
        monkeypatch.setattr(cc, "ANTHROPIC_AVAILABLE", False)
        c = _client(None)
    else:
        c = _client(sdk)
        c.circuit.state, c.circuit.last_failure = "OPEN", time.time()
    assert c.unavailable_reason() == code
    r = c.invoke_structured("s", "u", SCHEMA)
    assert r.error == code and r.data is None and sdk.beta.messages.calls == []


def test_a_refusal_is_not_a_success_even_when_the_text_parses_and_the_pair_end_turn_is():
    det = SimpleNamespace(type="refusal", category="cyber", explanation="설명")
    r = _client(FakeSDK(_msg({"x": "값"}, stop="refusal", details=det))).invoke_structured("s", "u", SCHEMA)
    assert r.error == "refusal" and r.detail == "cyber" and r.data is None
    ok = _client(FakeSDK(_msg({"x": "값"}))).invoke_structured("s", "u", SCHEMA)
    assert ok.error is None and ok.data == {"x": "값"}                 # ★짝★


@pytest.mark.parametrize("reply,code", [
    (_msg(text='{"x": "잘', stop="max_tokens"), "max_tokens"),
    (_msg(text="JSON 이 아니다"), "bad_json"),
    (_msg(text='["x"]'), "bad_json"),
])
def test_truncated_or_unreadable_answers_are_errors_with_no_data(reply, code):
    r = _client(FakeSDK(reply)).invoke_structured("s", "u", SCHEMA)
    assert r.error == code and r.data is None


def test_a_server_fallback_reports_the_model_that_answered_and_prices_each_hop():
    hop = SimpleNamespace(type="fallback", from_=SimpleNamespace(model="claude-opus-5-5"),
                          to=SimpleNamespace(model="claude-opus-4-8"), trigger=None)
    content = [SimpleNamespace(type="text", text='{"x": "거절 전 조각'), hop,
               SimpleNamespace(type="text", text='{"x": "대체 모델"}')]
    its = [SimpleNamespace(type="message", model="claude-opus-5-5", input_tokens=1000, output_tokens=10),
           SimpleNamespace(type="fallback_message", model="claude-opus-4-8", input_tokens=1000, output_tokens=200)]
    r = _client(FakeSDK(_msg(content=content, iterations=its))).invoke_structured("s", "u", SCHEMA)
    assert r.error is None and r.data == {"x": "대체 모델"}             # 경계 뒤의 글만 읽는다
    assert r.served_model == "claude-opus-4-8"
    assert r.cost_usd == pytest.approx((1000 * 4 + 10 * 20 + 1000 * 5 + 200 * 25) / 1e6)


def test_an_unknown_model_cost_is_none_with_a_reason_not_zero():
    r = _client(FakeSDK(_msg({"x": "값"}, model="claude-imaginary-9"))).invoke_structured(
        "s", "u", SCHEMA, model="claude-imaginary-9")
    assert r.error is None and r.cost_usd is None and "claude-imaginary-9" in (r.cost_note or "")


def test_an_exception_carrying_the_key_does_not_leak_into_the_response_or_the_log(caplog):
    caplog.set_level(logging.DEBUG)
    c = _client(FakeSDK(exc=RuntimeError(f"connection failed using key {SECRET}")))
    r = c.invoke_structured("s", "u", SCHEMA)
    assert r.error == "unexpected" and r.data is None
    _no_secret(_blob(r.__dict__))
    _no_secret(caplog.text)
    assert "RuntimeError" in caplog.text                                # ★짝★ 로그가 비어 있어 통과하는 게 아니다
    assert c.circuit.failures == 1                                      # 차단기는 센다


# ═════════════════════════════════════════════════════════════════════════════
# 3. 근거 · 프롬프트 · 스키마
# ═════════════════════════════════════════════════════════════════════════════

def test_numbers_are_collected_from_every_string_and_number_in_the_grounding():
    assert gr.numbers_of({"a": "종목 2개, 0.30 과 1,234", "b": [1.50, 7, True], "c": None}) == {"2", "0.3", "1234", "1.5", "7"}


def test_the_grounding_carries_the_structure_procedure_and_catalog_but_no_params():
    g = gr.ground(DOC, KINDS, routes.graph_validate(DOC))
    assert {n["id"]: n["type"] for n in g["graph"]["nodes"]} == {"u": "universe", "r": "returns", "es": "estimate", "o": "optimizer"}
    assert len(g["graph"]["edges"]) == 4 and all(set(e) == {"source", "source_port", "target", "target_port"}
                                                 for e in g["graph"]["edges"])
    assert g["procedure"]["next"] == routes.graph_validate(DOC)["procedure"]["next"]
    assert set(g["catalog"]) == set(KINDS)
    assert "005930" not in _blob(g) and "params" not in _blob(g)        # 설정값은 근거에 없다(추천하지 않는다)


def test_the_output_schema_has_no_params_and_closes_every_object():
    s = pr.output_schema(KINDS)
    assert "params" not in _blob(s)

    def objs(x):
        if isinstance(x, dict):
            if x.get("type") == "object":
                yield x
            for v in x.values():
                yield from objs(v)
        elif isinstance(x, list):
            for v in x:
                yield from objs(v)
    found = list(objs(s))
    assert len(found) == 3 and all(o.get("additionalProperties") is False and o.get("required") for o in found)
    item = s["properties"]["suggestions"]["items"]
    assert item["properties"]["kind"]["enum"] == sorted(KINDS)
    assert "maxItems" not in _blob(s) and "minimum" not in _blob(s)     # 구조화 출력이 받지 않는 제약 — 한도는 서버 검사


def test_the_system_prompt_states_the_rules():
    for must in ("설정값", "카탈로그", "숫자", "3"):
        assert must in pr.SYSTEM


# ═════════════════════════════════════════════════════════════════════════════
# 4. 출력 검사 — 각 검사 + 짝
# ═════════════════════════════════════════════════════════════════════════════

def _check(sugs, doc=DOC, numbers=frozenset()):
    return ck.check({"suggestions": sugs}, doc, KINDS, set(numbers), routes.graph_validate)


def test_a_valid_suggestion_passes_with_the_catalog_label():
    ok, bad = _check([BT])
    assert bad == []
    assert ok == [{"action": "add", "kind": "backtest", "label": "과거로 돌려 보기", "attach": BT["attach"], "reason": BT["reason"]}]


def test_a_kind_outside_the_catalog_is_rejected_and_the_pair_inside_passes():
    ok, bad = _check([{**BT, "kind": "magic_alpha"}])
    assert ok == [] and bad[0]["code"] == "unknown_kind" and "magic_alpha" in bad[0]["reason"]
    assert _check([BT])[0]                                               # ★짝★


@pytest.mark.parametrize("attach,code", [
    ([_a("r", "returns", "@new", "weights")], "type_mismatch"),                 # 수익률을 비중 자리에
    ([_a("o", "nope", "@new", "weights")], "unknown_port"),
    ([_a("ghost", "weights", "@new", "weights")], "dangling_edge"),
    ([_a("o", "weights", "r", "returns")], "attach_shape"),                    # 새 노드가 없다
    ([_a("@new", "x", "@new", "y")], "attach_shape"),
])
def test_bad_connections_are_rejected(attach, code):
    ok, bad = _check([{**BT, "attach": attach}])
    assert ok == [] and bad[0]["code"] == code and bad[0]["reason"]


def test_an_occupied_input_is_rejected_and_the_pair_free_input_passes():
    est = {"kind": "estimate", "attach": [_a("r", "returns", "@new", "returns"), _a("@new", "belief", "o", "belief")],
           "reason": "기대 수익을 한 번 더 추정해 이어요."}
    ok, bad = _check([est])
    assert ok == [] and bad[0]["code"] == "multiple_inputs"                    # 비중 계산의 belief 는 이미 차 있다
    free = {**DOC, "edges": CORE_E[:-1]}                                       # ★짝★ 그 선이 없으면
    assert _check([est], doc=free)[0][0]["kind"] == "estimate"


def test_a_cycle_is_rejected_and_the_pair_one_way_passes():
    doc = {**F, "nodes": [_n("sc", "screener"), _n("r", "returns")], "edges": [_e("sc", "universe", "r", "universe")]}
    loop = {"kind": "screener", "attach": [_a("sc", "universe", "@new", "universe"), _a("@new", "universe", "sc", "universe")],
            "reason": "한 번 더 거릅니다."}
    ok, bad = _check([loop], doc=doc)
    assert ok == [] and bad[0]["code"] == "cycle"
    assert _check([{**loop, "attach": loop["attach"][:1]}], doc=doc)[0]       # ★짝★


def test_numbers_outside_the_grounding_are_rejected_and_the_pair_grounded_numbers_pass():
    ok, bad = _check([{**BT, "reason": "거래비용 0.3% 를 넣어 2번 돌려 보세요."}], numbers={"2"})
    assert ok == [] and bad[0]["code"] == "numbers" and "0.3" in bad[0]["reason"]
    assert _check([{**BT, "reason": "종목 2개로 돌려 보세요."}], numbers={"2"})[0]   # ★짝★


@pytest.mark.parametrize("word", ["더 나은 전략", "검증됨", "투자 우위", "좋아져요"])
def test_banned_claims_are_rejected(word):
    ok, bad = _check([{**BT, "reason": f"붙이면 {word} 이에요."}])
    assert ok == [] and bad[0]["code"] == "banned" and word in bad[0]["reason"]


def test_a_suggestion_carrying_settings_is_rejected_and_the_pair_without_passes():
    ok, bad = _check([{**BT, "params": {"cost_bps": 30}}])
    assert ok == [] and bad[0]["code"] == "settings"
    assert _check([BT])[0]                                               # ★짝★


def test_at_most_three_pass_and_the_rest_are_reported_not_dropped():
    one = lambda k: {"kind": k, "attach": [_a("o", "weights", "@new", "weights")], "reason": "비중을 다른 눈으로 봐요."}  # noqa: E731
    ok, bad = _check([BT, one("risk"), one("scenario_stress"), one("custom_scenario"), one("factor_xray")])
    assert ck.MAX_SUGGESTIONS == 3
    assert [s["kind"] for s in ok] == ["backtest", "risk", "scenario_stress"]
    assert [(b["kind"], b["code"]) for b in bad] == [("custom_scenario", "limit"), ("factor_xray", "limit")]


def test_a_repeated_suggestion_is_reported_as_a_duplicate():
    rev = {**BT, "attach": list(reversed(BT["attach"]))}
    ok, bad = _check([BT, rev])
    assert len(ok) == 1 and [b["code"] for b in bad] == ["duplicate"]


def test_an_unattached_suggestion_is_rejected_on_a_graph_and_the_pair_empty_canvas_allows_it():
    uni = {"kind": "universe", "attach": [], "reason": "종목부터 골라요."}
    ok, bad = _check([uni])
    assert ok == [] and bad[0]["code"] == "unattached"
    assert _check([uni], doc={**F, "nodes": [], "edges": []})[0][0]["kind"] == "universe"   # ★짝★


@pytest.mark.parametrize("raw", [None, [], {"suggestions": "x"}, {"suggestions": [{"kind": 3}]}])
def test_a_malformed_answer_is_rejected_with_a_reason(raw):
    ok, bad = ck.check(raw, DOC, KINDS, set(), routes.graph_validate)
    assert ok == [] and bad and all(b["code"] == "shape" and b["reason"] for b in bad)


# ═════════════════════════════════════════════════════════════════════════════
# 5. 서비스
# ═════════════════════════════════════════════════════════════════════════════

def _suggest(client, graph=DOC, user="alice"):
    return svc.suggest(graph, user, catalog=routes._kinds, validate=routes.graph_validate, client=client)


def test_an_available_answer_says_its_source_model_and_usage():
    sdk = FakeSDK(_msg({"suggestions": [BT]}))
    res = _suggest(_client(sdk))
    assert res["available"] is True and res["source"] == "claude" and res["model"] == "claude-opus-5-5"
    assert [s["kind"] for s in res["suggestions"]] == ["backtest"] and res["suggestions"][0]["label"] == "과거로 돌려 보기"
    assert res["rejected"] == [] and res["cached"] is False
    assert res["usage"] == {"input_tokens": 1200, "output_tokens": 300,
                            "cost_usd": pytest.approx((1200 * 4 + 300 * 20) / 1e6), "cost_note": None}
    kw = sdk.beta.messages.calls[0]
    assert kw["model"] == "claude-opus-5-5" and kw["output_config"]["effort"] == "medium"
    assert kw["output_config"]["format"]["schema"] == pr.output_schema(KINDS) and kw["system"] == pr.SYSTEM
    user = kw["messages"][0]["content"]
    assert '"optimizer"' in user and routes.graph_validate(DOC)["procedure"]["next"]["text"] in user


def test_the_model_comes_from_claude_model_env(monkeypatch):
    monkeypatch.setenv("CLAUDE_MODEL", "claude-sonnet-5-5")
    sdk = FakeSDK(_msg({"suggestions": []}, model="claude-sonnet-5-5"))
    assert _suggest(_client(sdk))["model"] == "claude-sonnet-5-5"
    assert sdk.beta.messages.calls[0]["model"] == "claude-sonnet-5-5"


def test_rejected_suggestions_travel_with_their_reasons():
    sdk = FakeSDK(_msg({"suggestions": [BT, {**BT, "kind": "magic"}]}))
    res = _suggest(_client(sdk))
    assert [s["kind"] for s in res["suggestions"]] == ["backtest"]
    assert res["rejected"] and res["rejected"][0]["code"] == "unknown_kind" and res["rejected"][0]["reason"]


def test_the_service_checks_numbers_against_its_own_grounding_and_the_pair_rejects_outside_ones():
    g = gr.ground(DOC, KINDS, routes.graph_validate(DOC))
    n = sorted(gr.numbers_of(g), key=len)[0]
    assert "987654" not in gr.numbers_of(g)
    sdk = FakeSDK(_msg({"suggestions": [{**BT, "reason": f"근거의 {n} 을 그대로 써요."},
                                        {**BT, "kind": "risk", "attach": BT["attach"][:1], "reason": "987654 번 돌려요."}]}))
    res = _suggest(_client(sdk))
    assert [s["kind"] for s in res["suggestions"]] == ["backtest"]
    assert [(r["kind"], r["code"]) for r in res["rejected"]] == [("risk", "numbers")]


def test_no_key_is_unavailable_with_a_reason_and_the_rule_fallback_and_no_demo_text():
    sdk = FakeSDK(_msg({"suggestions": [BT]}))
    res = _suggest(_client(sdk, key=""))
    assert res["available"] is False and res["source"] == "unavailable" and res["reason_code"] == "no_key"
    assert res["reason"] == "서버에 Claude 키가 없어요"
    assert "suggestions" not in res and sdk.beta.messages.calls == []
    proc = routes.graph_validate(DOC)["procedure"]
    assert res["rule"] == {"next": proc["next"], "by_gate": proc["by_gate"]}
    text = _blob(res)
    assert not any(m[:40] in text for m in MOCKS) and "Mock" not in text and "데모" not in text


def test_the_default_client_without_a_key_is_unavailable_not_demo():
    res = svc.suggest(DOC, "alice", catalog=routes._kinds, validate=routes.graph_validate)
    assert res["available"] is False and res["reason_code"] == "no_key"


@pytest.mark.parametrize("reply,code", [
    (_msg({"x": 1}, stop="refusal", details=SimpleNamespace(type="refusal", category="bio", explanation=None)), "refusal"),
    (_msg(text="{", stop="max_tokens"), "max_tokens"),
    (_msg(text="아님"), "bad_json"),
])
def test_failed_calls_are_unavailable_with_a_reason_and_are_not_cached(reply, code):
    sdk = FakeSDK(reply)
    c = _client(sdk)
    res = _suggest(c)
    assert res["available"] is False and res["reason_code"] == code and res["reason"] and "suggestions" not in res
    _suggest(c)
    assert len(sdk.beta.messages.calls) == 2                            # 실패는 캐시하지 않는다


def test_an_unreadable_graph_is_refused_before_any_call():
    sdk = FakeSDK(_msg({"suggestions": []}))
    res = _suggest(_client(sdk), graph={"nodes": "x"})
    assert res["available"] is False and res["reason_code"] == "bad_graph" and sdk.beta.messages.calls == []


def _other(i):
    return {**DOC, "nodes": CORE + [_n(f"x{i}", "views")]}


def test_the_hourly_limit_refuses_the_next_call_and_the_pair_cache_hits_do_not_count(monkeypatch):
    monkeypatch.setenv("CANVAS_ASSIST_HOURLY_LIMIT", "2")
    sdk = FakeSDK(_msg({"suggestions": [BT]}))
    c = _client(sdk)
    assert _suggest(c, _other(1))["available"]
    hit = _suggest(c, _other(1))                                         # ★짝★ 캐시 적중 — 세지 않는다
    assert hit["available"] is True and hit["cached"] is True
    assert _suggest(c, _other(2))["available"] is True                   # 적중을 셌다면 여기서 막힌다
    third = _suggest(c, _other(3))
    assert third["available"] is False and third["reason_code"] == "rate_limited" and "2" in third["reason"]
    assert len(sdk.beta.messages.calls) == 2
    assert _suggest(c, _other(3), user="bob")["available"] is True       # 사용자별


def test_the_limit_window_slides(monkeypatch):
    monkeypatch.setenv("CANVAS_ASSIST_HOURLY_LIMIT", "1")
    now = [1000.0]
    monkeypatch.setattr(svc, "_now", lambda: now[0])
    c = _client(FakeSDK(_msg({"suggestions": []})))
    assert _suggest(c, _other(1))["available"]
    assert _suggest(c, _other(2))["reason_code"] == "rate_limited"
    now[0] += 3601
    assert _suggest(c, _other(2))["available"]


def test_a_bad_limit_setting_is_reported_not_guessed(monkeypatch):
    monkeypatch.setenv("CANVAS_ASSIST_HOURLY_LIMIT", "많이")
    sdk = FakeSDK(_msg({"suggestions": []}))
    res = _suggest(_client(sdk))
    assert res["available"] is False and res["reason_code"] == "config" and sdk.beta.messages.calls == []


def test_the_cache_is_keyed_by_model_too(monkeypatch):
    sdk = FakeSDK(_msg({"suggestions": [BT]}))
    c = _client(sdk)
    _suggest(c)
    assert _suggest(c)["cached"] is True and len(sdk.beta.messages.calls) == 1
    monkeypatch.setenv("CLAUDE_MODEL", "claude-sonnet-5-5")
    assert _suggest(c)["cached"] is False and len(sdk.beta.messages.calls) == 2


def test_the_key_never_reaches_the_response_or_the_log(caplog):
    caplog.set_level(logging.DEBUG)
    ok = _suggest(_client(FakeSDK(_msg({"suggestions": [BT]}))))
    boom = _suggest(_client(FakeSDK(exc=RuntimeError(f"bad key {SECRET}"))), graph=_other(9))
    assert ok["available"] and boom["available"] is False and boom["reason_code"] == "unexpected"
    for t in (_blob(ok), _blob(boom), caplog.text):
        _no_secret(t)
    assert "canvas-assist" in caplog.text                               # ★짝★ 비용 한 줄은 남는다


# ═════════════════════════════════════════════════════════════════════════════
# 6. 경로 — 로그인
# ═════════════════════════════════════════════════════════════════════════════

ROUTE = "/api/v1/assist/canvas/suggest"


@pytest.fixture()
def api(monkeypatch):
    from cryptography.fernet import Fernet
    from fastapi.testclient import TestClient

    import src.database as dbmod
    from src.domain.auth_identity import ROLE_ANALYST

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp.name}")
    monkeypatch.setenv("AUTH_SECRET", "ai0-canvas-assist-secret-0123456789abcdef")
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    monkeypatch.setenv("BROKER_CRED_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(dbmod, "DATABASE_URL", f"sqlite:///{tmp.name}", raising=False)
    # 앱 시작이 임시 DB 에 만든 표·싱글턴 메모가 뒤 테스트로 새지 않게(`test_account_balance_route.py` 와 같은 관용구).
    import src.api.stage13_routes as stage13
    import src.data.backtest_runs as br
    import src.execution.account_executors as ae
    import src.execution.kis_client as kc
    monkeypatch.setattr(br, "_inited", False)
    monkeypatch.setattr(kc, "_kis_singleton", None, raising=False)
    monkeypatch.setattr(kc, "_account_clients", {}, raising=False)
    monkeypatch.setattr(stage13, "_EXECUTOR", None, raising=False)
    monkeypatch.setattr(ae, "_executors", {}, raising=False)
    dbmod.reset_session()
    dbmod.init_db()
    dbmod.create_user("alice", "alice-pw", role=ROLE_ANALYST)
    from src.app_factory import create_app
    with TestClient(create_app()) as c:
        yield c
    dbmod.reset_session()
    try:
        os.unlink(tmp.name)
    except OSError:
        pass


def _auth(c):
    tok = c.post("/api/v1/auth/login", json={"username": "alice", "password": "alice-pw"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def test_the_route_needs_login_and_the_pair_logged_in_gets_an_answer(api):
    assert api.post(ROUTE, json=DOC).status_code == 401
    res = api.post(ROUTE, json=DOC, headers=_auth(api))                 # ★짝★
    assert res.status_code == 200
    body = res.json()
    assert body["available"] is False and body["reason_code"] == "no_key" and body["reason"] == "서버에 Claude 키가 없어요"


def test_the_route_passes_the_login_name_to_the_service(api, monkeypatch):
    seen = {}

    def fake(graph, username, **kw):
        seen.update(graph=graph, username=username, kw=set(kw))
        return {"available": False, "source": "unavailable", "reason_code": "x", "reason": "y"}
    monkeypatch.setattr(svc, "suggest", fake)
    api.post(ROUTE, json=DOC, headers=_auth(api))
    assert seen["username"] == "alice" and seen["graph"] == DOC and {"catalog", "validate"} <= seen["kw"]


def test_the_route_is_registered_as_login_only_and_on_the_login_map():
    from src.api.protected_routes import PROTECTED, REQUIRE_LOGIN
    level, why = PROTECTED[("POST", ROUTE)]
    assert level == REQUIRE_LOGIN and "Claude" in why
    amap = json.load(open("frontend/src/entities/session/accessMap.json", encoding="utf-8"))
    assert any(f"POST {ROUTE}" in i["routes"] for i in amap["login"]["items"])
