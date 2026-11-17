"""하루 유형을 조건으로 쓰는 규칙이 ★규칙을 돌리는 다섯 길★을 모두 지난다 (구현 계획 2026-11-16 §6 · T2).

길: `POST /simulate` · `POST /validate`(캔버스 실행 단추와 같은 본체) · `prepare`(캔버스 설정 노드의 읽기 전 검사) · `POST /divergence` ·
규칙 가동의 하루(`broker_account_routes._day_of` — 시작과 관제). 길마다 거는 것:
- 그 유형인 날에만, 창이 끝난 다음 봉 시가에 진입한다(손 계산 — 맥락이 빠지면 엔진이 실패하므로 동작으로 건다)
- ★봉을 읽기 전에★ 거절한다 — 학습 마지막 날 ≥ 판정 시작일 · 남의 모형 = 없는 모형 · 유형 번호 > k · 모형 열쇠의 모양
- 모형이 다르면 다른 시행 · 응답의 사실 줄(학습 기간 · 종목) · 하루 유형을 쓰지 않는 규칙의 답은 맥락이 비어 있다

손 계산: 심은 네 유형(끝값 순 번호 — 1 DOWN · 2 VEE · 3 HAT · 4 UP)으로 5월에 학습하고, 6월의 네 날을 HAT · UP · DOWN · VEE 로 둔다.
'하루 유형 3 > 0.5' 는 6월 1일에만 09:04(창의 마지막 봉)에 서고 09:05 시가에 산다.
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException

import src.api.intraday_routes as iroutes
from src.api import broker_account_routes as bar
from src.api import intraday_context
from src.data import minute_feed
from src.engine import portfolio_graph as pg
from src.engine.intraday import rules
from src.execution import rule_monitor
from tests.test_intraday_day_types_route import (  # noqa: F401 — 시험 틀
    DAYS,
    PATHS,
    TICKERS,
    auth,
    client,
    login,
    plant,
    write_day,
)

TRAIN_URL = "/api/v1/intraday/day-types"
TRAIN = {"tickers": list(TICKERS), "from": DAYS[0], "to": DAYS[-1], "minutes": 5, "k": 4}
JUDGE = {"2026-06-01": PATHS[3], "2026-06-02": PATHS[0], "2026-06-03": PATHS[1], "2026-06-04": PATHS[2]}   # HAT · UP · DOWN · VEE
TAIL = [0.0, 10.0, 20.0]                                                   # 창 뒤의 봉 셋 — 다음 봉 시가에 살 수 있게


def train(client, headers, body=TRAIN) -> str:
    r = client.post(TRAIN_URL, json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["model"]["key"]


def judging_days() -> None:
    for day, path in JUDGE.items():
        write_day(day, [(t, [*path, *TAIL], "kis") for t in TICKERS])


def leaf(key: str, number: int = 3) -> dict:
    return {"op": "gt", "args": [{"ind": "day_type_is", "model": key, "type": number}, {"const": 0.5}]}


def request(key: str, number: int = 3, start: str = "2026-06-01", end: str = "2026-06-04") -> dict:
    return {"tickers": list(TICKERS), "from": start, "to": end, "rule": {"kind": "custom", "params": {"entry": leaf(key, number)}},
            "position": {"amount": 1_000_000}, "costs": {"commission_bp": 1.5}}


@pytest.fixture()
def ready(client, auth) -> str:
    plant()
    judging_days()
    return train(client, auth)


def opened(js: dict) -> set[tuple[str, str]]:
    return {(t["symbol"], t["opened_at"]) for t in js["journal"]["trades"]}


# ── simulate ─────────────────────────────────────────────────────────────────────────
def test_the_condition_enters_only_on_the_day_of_that_type_after_the_window(client, auth, ready):
    r = client.post("/api/v1/intraday/simulate", json=request(ready), headers=auth)
    assert r.status_code == 200, r.text
    assert opened(r.json()) == {(t, "2026-06-01T09:05:00") for t in TICKERS}
    up = client.post("/api/v1/intraday/simulate", json=request(ready, number=4), headers=auth).json()   # 짝 — 유형 4 는 6월 2일
    assert opened(up) == {(t, "2026-06-02T09:05:00") for t in TICKERS}


def test_the_answer_says_when_and_on_what_the_model_learned(client, auth, ready):
    js = client.post("/api/v1/intraday/simulate", json=request(ready), headers=auth).json()
    [fact] = js["context"]
    assert fact["key"] == ready and (fact["first_day"], fact["last_day"]) == (DAYS[0], DAYS[-1]) and fact["same_tickers"] is True
    assert fact["sentences"][0].startswith(f"하루 유형 모형 {ready[:8]}의 학습 기간은 {DAYS[0]}~{DAYS[-1]}")
    plain = {**request(ready), "rule": {"kind": "custom", "params": {"entry": {"op": "gt", "args": [{"ind": "close"}, {"ind": "vwap"}]}}}}
    assert client.post("/api/v1/intraday/simulate", json=plain, headers=auth).json()["context"] == []      # 짝 — 쓰지 않으면 비어 있다


# ── 거절 — 봉을 읽기 전에 ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("path", ["/api/v1/intraday/simulate", "/api/v1/intraday/validate"])
def test_a_model_learned_up_to_the_first_judged_day_is_refused_before_any_bar_is_read(client, auth, ready, monkeypatch, path):
    def no_reading(*a, **k):
        raise AssertionError("거절해야 할 요청이 봉을 읽었다")
    monkeypatch.setattr(minute_feed, "build_days", no_reading)
    r = client.post(path, json=request(ready, start=DAYS[-1], end="2026-06-04"), headers=auth)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "day_type_model_overlaps", r.text
    assert r.json()["detail"]["reason"]


def test_one_day_after_the_last_learned_day_runs(client, auth, ready):
    """짝 — 학습 마지막 날(5월 19일) 다음 날부터면 돈다(그 사이 적재가 없어도 된다)."""
    r = client.post("/api/v1/intraday/simulate", json=request(ready, start="2026-05-20"), headers=auth)
    assert r.status_code == 200, r.text


def test_someone_elses_model_is_refused_like_a_missing_one(client, ready):
    bob = login(client, "bob")
    alice = login(client, "alice")
    bobs = train(client, bob, {**TRAIN, "to": DAYS[9]})                    # 밥의 모형(다른 열쇠)
    theirs = client.post("/api/v1/intraday/simulate", json=request(bobs), headers=alice)
    missing = client.post("/api/v1/intraday/simulate", json=request("9" * 64), headers=alice)
    assert theirs.status_code == missing.status_code == 400
    assert theirs.json()["detail"]["code"] == missing.json()["detail"]["code"] == "day_type_model_missing"


def test_a_type_number_above_the_models_count_and_a_bad_key_are_refused_with_sentences(client, auth, ready):
    over = client.post("/api/v1/intraday/simulate", json=request(ready, number=5), headers=auth)
    assert over.status_code == 400 and over.json()["detail"]["code"] == "day_type_out_of_range"
    bad = client.post("/api/v1/intraday/simulate", json=request("A" * 64), headers=auth)
    assert bad.status_code == 400 and bad.json()["detail"]["code"] == "bad_model_key"
    assert bad.json()["detail"]["reason"] == iroutes.REASONS["bad_model_key"]


# ── 판정 · 캔버스 · 괴리 ─────────────────────────────────────────────────────────────────
def test_validate_carries_the_context_and_counts_the_two_trades(client, auth, ready):
    r = client.post("/api/v1/intraday/validate", json=request(ready), headers=auth)
    assert r.status_code == 200, r.text
    js = r.json()
    assert js["summary"]["trades"] == 2 and js["context"][0]["key"] == ready


def test_the_canvas_check_uses_the_same_refusal(ready):
    """캔버스 설정 노드는 `prepare` 를 부른다 — 같은 사용자 · 같은 거절(봉을 읽지 않는다)."""
    with pytest.raises(HTTPException) as err:
        iroutes.prepare(iroutes.ValidateBody(**request(ready, start=DAYS[-1])), "alice")
    assert err.value.detail["code"] == "day_type_model_overlaps"
    assert iroutes.prepare(iroutes.ValidateBody(**request(ready)), "alice").context.models[0]["key"] == ready
    with pytest.raises(HTTPException):                                      # 짝 — 남의 사용자로는 없는 모형이다
        iroutes.prepare(iroutes.ValidateBody(**request(ready)), "bob")


def test_divergence_simulates_with_the_context(client, auth, ready):
    fills = [{"executed_at": "2026-06-01 09:05:00", "symbol": TICKERS[0], "side": "buy", "quantity": 99, "price": 10_030}]
    r = client.post("/api/v1/intraday/divergence", json={**request(ready), "fills": fills}, headers=auth)
    assert r.status_code == 200, r.text
    counts = r.json()["divergence"]["counts"]
    assert counts["matched"] + counts["sim_only"] == 4                      # 산 둘 · 하루 끝에 판 둘
    assert [f["key"] for f in r.json()["context"]] == [ready]                # 견주기 답에도 같은 사실 줄


# ── 시행 ───────────────────────────────────────────────────────────────────────────────
def test_a_different_model_in_the_same_tree_is_a_different_trial(client, auth, ready):
    other = train(client, auth, {**TRAIN, "to": DAYS[9]})                    # 열흘 · 20표본 — 다른 열쇠
    assert other != ready
    for key in (ready, other, ready):
        assert client.post("/api/v1/intraday/simulate", json=request(key), headers=auth).status_code == 200
    rows = client.get("/api/v1/intraday/trials", headers=auth).json()["trials"]
    keys = {r["request"]["rule"]["params"]["entry"]["args"][0]["model"] for r in rows}
    assert keys == {ready, other} and len(rows) == 2                       # 같은 모형은 같은 시행(세 번 돌려도 둘)


# ── 캔버스 — 설정 노드의 보기 · 설명 · 실행 단추가 남긴 요약 ──────────────────────────────────
RUN, SAVE = "/api/v1/allocation/graph/run", "/api/v1/allocation/graph/save"
TRUST = "하루 유형 모형이 본인의 것이고 학습이 판정 시작일 전에 끝났는지 검사했습니다."


def canvas(key: str | None, start: str = "2026-06-01", node_id: str = "s") -> dict:
    rule = ({"rule": "custom", "custom_rule": {"entry": leaf(key)}} if key
            else {"rule": "opening_range_breakout", "opening_range_breakout__minutes": 5})
    params = {"tickers": list(TICKERS), "start_date": start, "end_date": "2026-06-04", **rule,
              "amount": 1_000_000, "commission_bp": 1.5, "slippage_ticks": 1}
    return {"format": pg.FORMAT, "version": pg.VERSION, "edges": [],
            "nodes": [{"id": node_id, "type": "intraday_setup", "params": params}]}


def node_of(client, headers, g: dict, node_id: str) -> dict:
    r = client.post(RUN, json=g, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["nodes"][node_id]


def test_the_canvas_setup_shows_the_model_facts_and_the_kept_result_carries_them(client, auth, ready):
    g = canvas(ready)
    s = node_of(client, auth, g, "s")
    assert s["status"] == "ok", s.get("reason")
    [fact] = s["view"]["context"]
    assert fact["key"] == ready and fact["same_tickers"] is True
    assert fact["sentences"][0] in s["explain"]["facts"]
    assert any(t["text"] == TRUST and t["state"] == "confirmed" for t in s["explain"]["trust"])
    saved = client.post(SAVE, json={"graph": g, "node_id": "s", "preview_hash": s["view_hash"] or "none"}, headers=auth)
    assert saved.status_code == 200, saved.text
    load = {"format": pg.FORMAT, "version": pg.VERSION, "edges": [],
            "nodes": [{"id": "l", "type": "intraday_load", "params": {"trial_key": saved.json()["saved_id"]}}]}
    kept = node_of(client, auth, load, "l")
    assert kept["status"] == "ok", kept.get("reason")
    assert [f["key"] for f in kept["view"]["context"]] == [ready]               # 실행 단추가 남긴 요약에 그대로 실린다
    assert fact["sentences"][0] in kept["explain"]["facts"]


def test_a_canvas_rule_without_day_types_says_nothing_about_models(client, auth, ready):
    """짝 — 하루 유형을 쓰지 않는 규칙은 사실 줄도 · 검사했다는 문장도 없다."""
    s = node_of(client, auth, canvas(None), "s")
    assert s["status"] == "ok", s.get("reason")
    assert s["view"]["context"] == []
    assert not any("하루 유형 모형" in f for f in s["explain"]["facts"])
    assert not any(t["text"] == TRUST for t in s["explain"]["trust"])


def test_the_canvas_setup_refuses_an_overlapping_model_with_the_same_sentence(client, auth, ready):
    s = node_of(client, auth, canvas(ready, start=DAYS[-1]), "s")
    assert s["status"] == "failed" and intraday_context.REASONS["day_type_model_overlaps"] in s["reason"]


# ── 규칙 가동의 하루 ───────────────────────────────────────────────────────────────────
def spec_of(key: str):
    return rules.build("custom", {"entry": leaf(key)})


def test_the_rule_run_day_carries_the_context_and_refuses_an_overlapping_model(ready):
    built = bar._day_of("alice", list(TICKERS), spec_of(ready), date(2026, 6, 1))
    assert built is not None
    day, _session = built
    assert all(s.context is not None and ready in s.context.day_types for s in day.sessions.values())
    with pytest.raises(HTTPException) as err:
        bar._day_of("alice", list(TICKERS), spec_of(ready), date(2026, 5, 19))
    assert err.value.detail["code"] == "day_type_model_overlaps"


def test_the_monitor_says_why_it_could_not_rebuild_the_day(ready):
    with pytest.raises(rule_monitor.DayUnavailable) as err:
        bar._monitor_day("alice", list(TICKERS), spec_of(ready), "2026-05-19")
    assert err.value.reason == intraday_context.REASONS["day_type_model_overlaps"]
