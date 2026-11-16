"""직접 구성한 규칙(`custom`)의 문 — `POST /api/v1/intraday/rules/expand` 와 기존 문들이 나무를 받는 길 (자유 조건식 설계 §5 · 구현 계획 f1).

엔진의 뜻은 `test_intraday_custom_rules.py` 가 건다. 여기서는 문이 지키는 약속만 본다:
- `rules/expand` 는 ★계산하지 않는다★ — 쓰기 0 · 분봉 읽기 0 · 시행 기록 0(편집 중의 '검사'는 시행이 아니다) ↔ 실행은 시행을 남긴다.
- 실행 · 판정 · 괴리의 문은 본문 모형을 바꾸지 않고 `custom` 을 받는다 — 손 계산의 그 숫자가 ★규칙을 바꿔치기하지 않고★ 문을 지나 나온다.
- 거절은 엔진의 사유 그대로이고 문장이 있다(`bad_setting` 으로 뭉개지 않는다) · 어느 자리인지 말한다.
- 격자의 규칙 축은 `custom` 에서 거절한다(나무 전체를 갈아 끼우는 격자가 지나가지 않게).
- 목록(시행 · 결과 · 가동 요청)은 규칙의 글을 싣는다 — 읽히지 않는 설정이면 글 없이 사유를 싣는다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from sqlalchemy import inspect, text

import src.database as dbmod
from src.data import intraday_trials as trials
from src.data import rule_runs
from src.engine.intraday import expr, rules
from tests.route_walk import flat_routes
from tests.test_intraday_validate_route import (  # noqa: F401 — client · auth 는 픽스처다
    BODY,
    CROSSING,
    SIM,
    TEMPLATES,
    VAL,
    auth,
    client,
    login,
    made_days,
    stored_rows,
    with_days,
)

EXPAND = "/api/v1/intraday/rules/expand"
DIV = "/api/v1/intraday/divergence"
TRIALS = "/api/v1/intraday/trials"
RESULTS = "/api/v1/intraday/results"
REQUESTS = "/api/v1/intraday/arm-requests"
ROOT = Path(__file__).resolve().parents[1]

CUSTOM = {"kind": "custom", "params": CROSSING}                  # 종가가 10,050 을 상향 돌파 — 손 계산의 그 규칙
CROSSING_FORM = {"entry": {"op": "cross_up", "args": [{"ind": "close"}, {"const": 10_050.0}]}}
ABOVE = {"op": "gt", "args": [{"ind": "close"}, {"ind": "sma"}]}
BELOW = {"op": "lt", "args": [{"ind": "close"}, {"ind": "vwap"}]}


def expand(client, auth, rule):
    return client.post(EXPAND, json={"rule": rule}, headers=auth)


def refusal(client, auth, rule) -> dict:
    r = expand(client, auth, rule)
    assert r.status_code == 400, r.text
    return r.json()["detail"]


def counts() -> dict[str, int]:
    engine = dbmod.get_engine()
    with engine.connect() as c:
        return {t: int(c.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar()) for t in inspect(engine).get_table_names()}


def hand_days(monkeypatch):
    """손으로 만든 열흘 — ★규칙은 바꿔치기하지 않는다★(문이 받은 나무를 그대로 짓는다)."""
    with_days(monkeypatch, made_days(), crossing=False)


# ── 문 ───────────────────────────────────────────────────────────────────────────────
def test_expand_is_mounted_login_only_and_on_the_access_map(client):
    from src.api.protected_routes import PROTECTED, REQUIRE_LOGIN
    table = {(m, r.path) for r in flat_routes(client.app) for m in (getattr(r, "methods", None) or [])}
    assert ("POST", EXPAND) in table and PROTECTED[("POST", EXPAND)][0] == REQUIRE_LOGIN
    access = json.loads((ROOT / "frontend/src/entities/session/accessMap.json").read_text("utf-8"))
    assert f"POST {EXPAND}" in json.dumps(access, ensure_ascii=False)
    assert client.post(EXPAND, json={"rule": CUSTOM}).status_code == 401


# ── 틀 → 나무 · 직접 구성 → 하나의 꼴 ────────────────────────────────────────────────────
def test_a_template_expands_to_the_trees_it_builds(client, auth):
    body = expand(client, auth, {"kind": "opening_range_breakout", "params": {"minutes": 5}}).json()
    spec = rules.build("opening_range_breakout", {"minutes": 5})
    assert body["rule"] == {"kind": "custom", "params": rules.as_custom(spec)}
    assert body["source"] == {"kind": "opening_range_breakout", "label": "시가 범위 돌파"}
    assert body["text"] == rules.text_of(spec) and body["text"].startswith("진입 조건: 종가 상향 돌파 시가 범위 고가(5분)")
    assert (body["nodes"], body["depth"]) == expr.size(spec.entry) and body["nodes"] > 10
    assert body["limits"] == {"nodes": 64, "depth": 12} and body["needs_prev"] is False
    # 이 틀은 '직전 M봉 동안'으로 범위가 막 끝난 봉을 짚는다 — 그 연산이 그 봉을 보지 않는다는 말이 붙는다(쓰지 않는 규칙에는 없다 — 짝).
    assert len(body["notes"]) == 2 and "그날의 봉" in body["notes"][0] and "그 봉을 포함하지 않습니다" in body["notes"][1]
    plain = expand(client, auth, {"kind": "custom", "params": {"entry": {"op": "gt", "args": [{"ind": "close"}, {"ind": "vwap"}]}}}).json()
    assert len(plain["notes"]) == 1 and "그날의 봉" in plain["notes"][0]


def test_a_template_that_uses_yesterday_says_so(client, auth):
    body = expand(client, auth, {"kind": "volatility_breakout", "params": {}}).json()
    assert body["needs_prev"] is True and any("전일 값은 원주가" in n for n in body["notes"])
    assert body["text"] == "미리 건 매수 가격: 당일 시가 + (0.5 × (전일 고가 − 전일 저가))"
    assert set(body["rule"]["params"]) == {"entry_stop"}


def test_expanding_what_was_expanded_changes_nothing(client, auth):
    first = expand(client, auth, {"kind": "vwap_cross", "params": {"bars_below": 3}}).json()
    again = expand(client, auth, first["rule"]).json()
    assert again["rule"] == first["rule"] and again["text"] == first["text"] and again["nodes"] == first["nodes"]
    assert again["source"] == {"kind": "custom", "label": "직접 구성"}


def test_a_custom_rule_comes_back_in_its_one_form(client, auth):
    body = expand(client, auth, {"kind": "custom", "params": {"exit": None, "entry": {"args": ABOVE["args"], "op": "gt"}}}).json()
    assert body["rule"]["params"] == {"entry": {"op": "gt", "args": [{"ind": "close"}, {"ind": "sma", "n": 20}]}}
    assert (body["nodes"], body["depth"], body["needs_prev"]) == (3, 2, False)
    assert body["text"] == "진입 조건: 종가 > 이동평균(20봉)"
    two = expand(client, auth, {"kind": "custom", "params": {"entry": ABOVE, "exit": BELOW}}).json()
    assert (two["nodes"], two["depth"]) == (6, 2)               # 마디 수는 자리를 합쳐 센다 · 깊이는 가장 깊은 나무


# ── 계산하지 않는다 ──────────────────────────────────────────────────────────────────
def test_expand_writes_nothing_reads_no_bars_and_is_not_a_trial(client, auth, monkeypatch):
    import src.api.intraday_routes as mod
    hand_days(monkeypatch)
    touched = []
    monkeypatch.setattr(mod.minute_feed, "plan", lambda *a, **k: touched.append("plan") or mod.minute_feed.Plan([], 0))
    monkeypatch.setattr(mod.minute_feed, "build_days", lambda *a, **k: touched.append("days") or [])
    monkeypatch.setattr(mod.trials, "record", lambda *a, **k: touched.append("record"))
    client.get(TRIALS, headers=auth)                             # 표를 미리 만든다 — 아래의 '그대로'가 표가 없어서가 아니게
    before = counts()
    assert "intraday_trials" in before
    assert expand(client, auth, {"kind": "opening_range_breakout", "params": {}}).status_code == 200
    assert expand(client, auth, CUSTOM).status_code == 200
    assert expand(client, auth, {"kind": "custom", "params": {}}).status_code == 400
    assert counts() == before and touched == []


def test_running_the_same_rule_is_what_makes_a_trial(client, auth, monkeypatch):
    """짝 — 검사는 시행이 아니고 실행은 시행이다."""
    hand_days(monkeypatch)
    for _ in range(3):
        expand(client, auth, CUSTOM)
    assert stored_rows() == 0
    assert client.post(SIM, json={**BODY, "rule": CUSTOM}, headers=auth).json()["trial"]["new"] is True
    assert stored_rows() == 1


# ── 거절 ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("rule, code, slot", [
    ({"kind": "custom", "params": {}}, "no_entry", None),
    ({"kind": "custom", "params": {"entry": {"ind": "close"}}}, "entry_not_a_condition", "entry"),
    ({"kind": "custom", "params": {"entry_stop": ABOVE}}, "entry_stop_not_a_price", "entry_stop"),
    ({"kind": "custom", "params": {"entry": ABOVE, "exit": {"const": 1}}}, "exit_not_a_condition", "exit"),
    ({"kind": "custom", "params": {"entry": {"op": "gt", "args": [{"ind": "stochastic"}, {"const": 0}]}}}, "unknown_indicator", "entry"),
    ({"kind": "custom", "params": {"entry": {"op": "gt", "args": [{"ind": "sma", "n": 500}, {"const": 0}]}}}, "param_out_of_range", "entry"),
    ({"kind": "custom", "params": {"entry": ABOVE, "exit": {**BELOW, "memo": "x"}}}, "unknown_key", "exit"),
    ({"kind": "custom", "params": {"entry": {"op": "and", "args": [ABOVE, {"ind": "close"}]}}}, "wrong_kind", "entry"),
    ({"kind": "custom", "params": {"entry": {"op": "not", "args": [ABOVE, BELOW]}}}, "wrong_arity", "entry"),
    ({"kind": "custom", "params": {"entry": {"op": "held_before", "bars": 0, "args": [ABOVE]}}}, "bad_bars", "entry"),
    ({"kind": "custom", "params": {"entry": {"op": "xor", "args": [ABOVE, BELOW]}}}, "unknown_op", "entry"),
    ({"kind": "custom", "params": {"entry": "close > sma"}}, "not_a_node", "entry"),
    ({"kind": "custom", "params": {"entry": {"op": "gt", "args": [{"ind": "close"}, {"const": "30"}]}}}, "bad_const", "entry"),
    ({"kind": "custom", "params": {"entry": ABOVE, "target": ABOVE}}, "unknown_param", None),
    ({"kind": "macd_cross", "params": {}}, "unknown_kind", None),
    ({"kind": "opening_range_breakout", "params": {"minutes": 0}}, "param_out_of_range", None),
])
def test_a_refusal_carries_the_engine_s_reason_a_sentence_and_the_slot(client, auth, rule, code, slot):
    import src.api.intraday_routes as mod
    detail = refusal(client, auth, rule)
    assert (detail["code"], detail["slot"]) == (code, slot)
    assert detail["reason"] == mod.REASONS[code] and detail["reason"].endswith("니다.") and "—" not in detail["reason"]


def test_too_many_nodes_and_too_deep_are_refused_with_their_own_sentences(client, auth):
    wide = {"op": "and", "args": [{"op": "gt", "args": [{"ind": "close"}, {"const": i}]} for i in range(20)]}       # 61 마디
    assert expand(client, auth, {"kind": "custom", "params": {"entry": wide, "exit": BELOW}}).json()["nodes"] == 64
    over = refusal(client, auth, {"kind": "custom", "params": {"entry": wide, "exit": {"op": "and", "args": [BELOW, ABOVE]}}})
    assert (over["code"], over["slot"]) == ("too_many_nodes", None)
    deep = ABOVE
    for _ in range(12):
        deep = {"op": "not", "args": [deep]}
    assert refusal(client, auth, {"kind": "custom", "params": {"entry": deep}})["code"] == "too_deep"


def test_every_reason_the_engine_can_give_has_a_sentence():
    """엔진의 사유 코드를 소스에서 훑는다 — 문장이 없는 코드는 화면에 `bad_setting` 으로 뭉개져 나간다."""
    import src.api.intraday_routes as mod
    found = set()
    for name in ("expr.py", "indicators.py", "rules.py", "simulator.py"):
        source = (ROOT / "src/engine/intraday" / name).read_text("utf-8")
        found |= set(re.findall(r'(?:ExprError|IndicatorError|RuleError|SimError)\("([a-z_]+)"', source))
    found |= {wrong for *_, wrong in rules.SLOTS}                # 자리의 종류가 틀렸을 때의 코드(변수로 넘긴다)
    assert {"no_entry", "too_many_nodes", "unknown_key", "wrong_kind", "unknown_indicator", "bad_amount"} <= found and len(found) >= 25
    assert sorted(found - set(mod.REASONS)) == []
    assert all(mod.REASONS[code].endswith("니다.") for code in found)


@pytest.mark.parametrize("body", [{}, {"rule": {"kind": "custom"}, "position": {"amount": 1}}, {"rule": {"params": {}}},
                                  {"rule": {"kind": "custom", "params": []}}])
def test_a_malformed_expand_body_is_422(client, auth, body):
    assert client.post(EXPAND, json=body, headers=auth).status_code == 422


# ── 실행 · 판정 · 괴리가 나무를 받는다 ───────────────────────────────────────────────────
def test_simulate_runs_the_tree_it_was_given_and_the_hand_computed_number_comes_out(client, auth, monkeypatch):
    hand_days(monkeypatch)
    body = client.post(SIM, json={**BODY, "rule": CUSTOM}, headers=auth).json()
    assert body["journal"]["summary"]["gross"]["total"] == 19_800           # 열흘 × +1,980원 — 분봉 시뮬레이터의 손 계산
    assert body["request"]["rule"] == {"kind": "custom", "params": CROSSING_FORM}
    assert body["template"]["kind"] == "custom" and body["template"]["custom"] is True
    assert body["trial"]["recorded"] is True and body["trial"]["new"] is True


def test_a_template_and_its_expansion_give_the_same_answer_but_are_counted_apart(client, auth, monkeypatch):
    hand_days(monkeypatch)
    template = {**BODY, "rule": {"kind": "opening_range_breakout", "params": {"minutes": 1}}}
    a = client.post(SIM, json=template, headers=auth).json()
    b = client.post(SIM, json={**BODY, "rule": expand(client, auth, template["rule"]).json()["rule"]}, headers=auth).json()
    assert a["journal"]["summary"]["gross"]["total"] == 19_800               # 공허하지 않다 — 열흘에 열 번 거래했다(+1,980원씩)
    for key in ("journal", "data", "origin", "assumptions", "events_by_kind", "breakeven"):
        assert a[key] == b[key], key
    assert (a["trial"]["new"], b["trial"]["new"], b["trial"]["family_n"]) == (True, True, 2)   # 종류가 달라 다른 시행이다


def test_the_same_tree_is_one_trial_however_it_is_spelled_and_a_reordered_one_is_new(client, auth, monkeypatch):
    hand_days(monkeypatch)

    def run(entry) -> dict:
        return client.post(SIM, json={**BODY, "rule": {"kind": "custom", "params": {"entry": entry}}}, headers=auth).json()["trial"]

    both = {"op": "and", "args": [CROSSING["entry"], {"op": "gt", "args": [{"ind": "close"}, {"ind": "vwap"}]}]}
    assert run(both)["new"] is True
    spelled = {"args": [{"args": [{"ind": "close"}, {"const": 10_050.0}], "op": "cross_up"},
                        {"args": [{"ind": "close"}, {"ind": "vwap"}], "op": "gt"}], "op": "and"}
    same = run(spelled)
    assert (same["new"], same["runs"]) == (False, 2)
    swapped = run({"op": "and", "args": list(reversed(both["args"]))})
    assert (swapped["new"], swapped["family_n"]) == (True, 2)


def test_a_new_day_high_rule_built_from_the_added_pieces_trades_like_the_hand_rule(client, auth, monkeypatch):
    """지표 보탬(f4) — `종가 > 1봉 전 당일 고가`: 손으로 만든 하루에서 09:01 에 처음 충족한다(10,060 > 10,020) → 손 계산의 규칙과 같은 체결.
    짝: 당일 고가는 그 봉을 포함하므로 `고가 > 당일 고가` 는 한 번도 충족하지 않는다(거래 0)."""
    hand_days(monkeypatch)
    before = {"op": "ago", "bars": 1, "args": [{"ind": "day_high"}]}
    new_high = {"kind": "custom", "params": {"entry": {"op": "gt", "args": [{"ind": "close"}, before]}}}
    body = client.post(VAL, json={**BODY, "rule": new_high}, headers=auth).json()
    assert body["summary"]["trades"] == 10 and body["summary"]["gross_total"] == 19_800
    never = {"kind": "custom", "params": {"entry": {"op": "gt", "args": [{"ind": "high"}, {"ind": "day_high"}]}}}
    assert client.post(VAL, json={**BODY, "rule": never}, headers=auth).json()["summary"]["trades"] == 0


def test_validate_judges_a_custom_rule_with_the_hand_computed_numbers(client, auth, monkeypatch):
    hand_days(monkeypatch)
    body = client.post(VAL, json={**BODY, "rule": CUSTOM}, headers=auth).json()
    assert body["summary"]["trades"] == 10 and body["summary"]["gross_total"] == 19_800
    assert body["summary"]["net_total"] == pytest.approx(-3_194.7, abs=0.1)
    assert body["gates"]["sentence"] == "관문 일곱 가운데 통과 2 · 미달 1 · 미상 4 입니다."
    assert body["request"]["rule"]["kind"] == "custom" and body["trial"]["recorded"] is True


def test_the_position_grid_works_for_a_custom_rule(client, auth, monkeypatch):
    hand_days(monkeypatch)
    grid = {"folds": 2, "position": {"stop_pct": [0.5, 1.0]}}
    body = client.post(VAL, json={**BODY, "rule": CUSTOM, "walk_forward": grid}, headers=auth).json()
    assert [c["position"] for c in body["walk_forward"]["cells"]] == [{"stop_pct": 0.5}, {"stop_pct": 1.0}]
    assert stored_rows() == 3                                    # 기본 설정 + 칸 둘


@pytest.mark.parametrize("axis", [{"entry": [ABOVE, BELOW]}, {"n": [5, 10]}, {"exit": [BELOW, ABOVE]}])
def test_a_rule_axis_on_the_grid_is_refused_for_a_custom_rule(client, auth, monkeypatch, axis):
    """직접 구성에는 이름 붙은 규칙 매개변수가 없다. 문이 먼저 사유와 함께 거절한다 —
    가드가 없으면 축의 값이 나무일 때 500 으로 깨진다(변이로 확인 · 겹친 값을 걷는 자리가 사전을 해시하지 못한다)."""
    import src.api.intraday_routes as mod
    hand_days(monkeypatch)
    r = client.post(VAL, json={**BODY, "rule": CUSTOM, "walk_forward": {"folds": 2, "rule": axis}}, headers=auth)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "grid_rule_axis_custom"
    assert r.json()["detail"]["reason"] == mod.REASONS["grid_rule_axis_custom"] and stored_rows() == 0


def test_a_rule_axis_still_works_for_a_template(client, auth, monkeypatch):
    """짝 — 막는 것은 직접 구성한 규칙의 규칙 축뿐이다."""
    hand_days(monkeypatch)
    grid = {"folds": 2, "rule": {"minutes": [1, 2]}}
    body = client.post(VAL, json={**BODY, "rule": {"kind": "opening_range_breakout", "params": {"minutes": 1}}, "walk_forward": grid},
                       headers=auth)
    assert body.status_code == 200 and [c["rule"] for c in body.json()["walk_forward"]["cells"]] == [{"minutes": 1}, {"minutes": 2}]


def test_the_divergence_report_takes_a_custom_rule(client, auth, monkeypatch):
    hand_days(monkeypatch)
    day = made_days()[0].date
    rows = [{"executed_at": f"{day} 09:02:00", "symbol": "005930", "side": "buy", "quantity": 99, "price": 10_080},
            {"executed_at": f"{day} 09:03:00", "symbol": "005930", "side": "sell", "quantity": 99, "price": 10_100}]
    body = client.post(DIV, json={**BODY, "rule": CUSTOM, "fills": rows}, headers=auth).json()
    assert body["divergence"]["counts"]["matched"] == 2 and body["trial"]["recorded"] is True
    assert body["request"]["rule"] == {"kind": "custom", "params": CROSSING_FORM}


# ── 틀 목록과 문법 표 ─────────────────────────────────────────────────────────────────
def test_the_listing_has_the_custom_kind_and_the_grammar(client, auth):
    body = client.get(TEMPLATES, headers=auth).json()
    assert [t["kind"] for t in body["templates"]][-1] == "custom" and len(body["templates"]) == 8
    assert [t["custom"] for t in body["templates"]] == [False] * 7 + [True]
    g = body["grammar"]
    assert g == json.loads(json.dumps(rules.grammar()))                      # 문은 엔진의 표를 그대로 싣는다
    assert len(g["indicators"]) == 28 and len(g["ops"]) == 16 and g["limits"] == {"nodes": 64, "depth": 12}


def test_checking_a_condition_built_from_the_added_indicators_gives_its_text_and_notes(client, auth):
    """지표 보탬(f4) — 새 지표와 'N봉 전 값'으로 지은 조건도 같은 문이 검사하고 같은 글을 낸다(계산하지 않는다)."""
    new_high = {"op": "gt", "args": [{"ind": "high"}, {"op": "ago", "bars": 1, "args": [{"ind": "day_high"}]}]}
    body = client.post(EXPAND, json={"rule": {"kind": "custom", "params": {"entry": new_high, "exit": {
        "op": "cross_down", "args": [{"ind": "macd"}, {"ind": "macd_signal"}]}}}}, headers=auth)
    assert body.status_code == 200, body.text
    said = body.json()
    assert said["text"] == "진입 조건: 고가 > 1봉 전 당일 고가 · 청산 조건: MACD(12봉, 26봉) 하향 돌파 MACD 신호선(12봉, 26봉, 9봉)"
    assert said["rule"]["params"]["entry"]["args"][1] == {"op": "ago", "args": [{"ind": "day_high"}], "bars": 1}
    assert (said["nodes"], said["depth"], said["needs_prev"]) == (7, 3, False)
    assert sum("그 봉을 포함합니다" in n for n in said["notes"]) == 1 and sum("다시 계산합니다" in n for n in said["notes"]) == 1
    bad = client.post(EXPAND, json={"rule": {"kind": "custom", "params": {"entry": {
        "op": "gt", "args": [{"ind": "close"}, {"op": "ago", "args": [{"ind": "close"}]}]}}}}, headers=auth)
    assert bad.status_code == 400 and bad.json()["detail"]["code"] == "bad_bars" and bad.json()["detail"]["slot"] == "entry"


# ── 목록의 글 ─────────────────────────────────────────────────────────────────────────
def _daily() -> dict:
    return {"basis": "net", "dates": [], "values": []}


def test_my_trials_carry_the_rule_s_text(client, auth, monkeypatch):
    hand_days(monkeypatch)
    client.post(SIM, json=BODY, headers=auth)                                # 틀(시가 범위 돌파 5분)
    client.post(SIM, json={**BODY, "rule": CUSTOM}, headers=auth)
    rows = {r["request"]["rule"]["kind"]: r for r in client.get(TRIALS, headers=auth).json()["trials"]}
    assert rows["custom"]["rule_label"] == "직접 구성"
    assert (rows["custom"]["rule_text"], rows["custom"]["rule_text_reason"]) == ("진입 조건: 종가 상향 돌파 10050", None)
    assert rows["custom"]["request"]["rule"] == {"kind": "custom", "params": CROSSING_FORM}      # 편집기에 다시 실을 수 있다
    assert rows["opening_range_breakout"]["rule_text"].startswith("진입 조건: 종가 상향 돌파 시가 범위 고가(5분)")


def test_a_trial_whose_rule_is_no_longer_readable_has_no_text_and_says_why(client, auth):
    stale = {"rule": {"kind": "macd_cross", "params": {}}, "position": {"amount": 1_000_000}, "costs": {}}
    trials.record("alice", grade="E3", setting=stale, tickers=["005930"], start="2026-03-02", end="2026-03-13", daily=_daily())
    row = client.get(TRIALS, headers=auth).json()["trials"][0]
    assert row["rule_text"] is None and row["rule_text_reason"] == rules.RULE_TEXT_UNREADABLE
    assert row["rule_label"] == "macd_cross"                                 # 이름표는 지금처럼 종류 이름으로 남는다(글이 아니다)


def test_the_results_list_and_the_arm_requests_carry_the_text_too(client, auth, monkeypatch):
    hand_days(monkeypatch)
    client.post(SIM, json={**BODY, "rule": CUSTOM}, headers=auth)
    key = client.get(TRIALS, headers=auth).json()["trials"][0]["trial_key"]
    assert trials.keep_result("alice", key, {"gates": {"counts": {"ok": 2, "degraded": 1, "unknown": 4}}})
    listed = client.get(RESULTS, headers=auth).json()["results"]
    assert [(r["rule_kind"], r["rule_label"], r["rule_text"]) for r in listed] == [("custom", "직접 구성", "진입 조건: 종가 상향 돌파 10050")]
    assert rule_runs.add_request("alice", key) is not None
    request = client.get(REQUESTS, headers=auth).json()["requests"][0]
    assert request["trial"]["rule_label"] == "직접 구성" and request["trial"]["rule_text"] == "진입 조건: 종가 상향 돌파 10050"
    assert request["trial"]["rule_text_reason"] is None
    assert client.get(RESULTS, headers=login(client, "bob")).json()["results"] == []             # 남의 것은 여전히 보이지 않는다
