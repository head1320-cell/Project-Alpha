"""국면 조건을 쓰는 규칙이 ★규칙을 돌리는 다섯 길★을 모두 지난다 (구현 계획 2026-11-16 §7.4 · K3).

길: `POST /simulate` · `POST /validate`(캔버스 실행 단추와 같은 본체) · `prepare`(캔버스 설정 노드의 읽기 전 검사) · `POST /divergence` ·
규칙 가동의 하루(`broker_account_routes._day_of` — 시작과 관제). 길마다 거는 것:
- 그날 시가 전에 알던 국면 확률이 문턱을 넘는 날에만 진입한다(손 계산 — 맥락이 빠지면 엔진이 실패하므로 동작으로 건다)
- ★봉을 읽기 전에★ 거절한다 — 저장소 장애(503) · 국면을 계산하지 못함(400) · 분봉이 적재된 날 가운데 확률을 아는 날이 없음(400)
- 사실 줄(아는 날 · 모르는 날과 사유별 날 수 · 등급) · 판정의 짝 비교(국면 조건을 뺀 판 — ★시행으로 세지 않는다★)
- 국면 값은 시장 국면 문과 ★같은 함수★(`regime_answer`) — 규칙이 본 확률 = 그 문의 답 · 그날과 그 뒤의 지수 종가를 바꿔도 그날 확률은 같다

손 계산: 분봉 날 넷(06-01 ~ 06-04 · 두 종목 · 봉 넷 · 종가가 오르기만 한다) · 심은 국면 답(국면 2개 · 국면 1 확률):
    06-01 0.8 · 06-02 0.3 · 06-03 모름(창이 덜 참) · 06-04 지수 일봉 없음
'국면 1 > 0.6 그리고 종가 > 0' → 06-01 에만 첫 봉 종가에 서고 09:01 시가에 산다(두 종목 = 거래 2건). 국면 조건을 뺀 판은 나흘 모두(거래 8건).
"""
from __future__ import annotations

import os
from datetime import date

import numpy as np
import pandas as pd
import pytest
from fastapi import HTTPException

import src.api.intraday_market_regime_routes as k1
import src.api.intraday_routes as iroutes
import src.data.minute_bars as mb
from src.api import broker_account_routes as bar
from src.api import intraday_context as ctxmod
from src.data import minute_feed
from src.engine import portfolio_graph as pg
from src.engine.intraday import rules
from src.execution import rule_monitor
from tests.test_intraday_day_types_route import (  # noqa: F401 — 시험 틀
    TICKERS,
    auth,
    client,
    login,
    write_day,
)

DAYS = ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04"]
PATH = [10.0, 20.0, 30.0, 40.0]
SHORT = "적합에 쓸 날이 모자랍니다. 필요 750일 · 있는 날 700일."
PLANTED = {"2026-06-01": [0.8, 0.2], "2026-06-02": [0.3, 0.7], "2026-06-03": None}     # 06-04 는 지수에 없다


def answer(probs: dict | None = None, *, grade: str | None = "E3", empty: str | None = None) -> dict:
    """`regime_answer` 와 같은 꼴의 심은 답 — 이 시험이 읽는 칸만(날 · 등급 · 빈 값 사유)."""
    if empty is not None:
        message = k1.EMPTY[empty].format(name="코스피") if empty == "not_loaded" else k1.EMPTY[empty]
        return {"days": [], "grade": None, "grade_reason": None, "empty": {"reason": empty, "message": message}}
    rows = [{"date": d, "probs": p, "top": None if p is None else int(np.argmax(p)) + 1,
             "top_prob": None if p is None else max(p), "reason": SHORT if p is None else None}
            for d, p in sorted((PLANTED if probs is None else probs).items())]
    return {"days": rows, "grade": grade, "grade_reason": None if grade else k1.GRADE_UNKNOWN, "empty": None}


@pytest.fixture()
def planted(monkeypatch, tmp_path) -> list:
    """분봉 날 넷을 심고 국면 답을 심는다 → 물은 (지수, 국면 수, 시작, 끝)의 목록.
    분봉은 그 시험의 임시 폴더에 쓴다(`client` 와 같은 폴더) — `client` 없이 이것만 쓰는 시험도 저장소의 기본 경로에 쓰지 않는다."""
    monkeypatch.setenv("MINUTE_BARS_DIR", str(tmp_path / "bars"))
    mb.clear_cache()
    for day in DAYS:
        write_day(day, [(t, PATH, "kis") for t in TICKERS])
    asked: list = []

    def fake(index, k, from_, to):
        asked.append((index, k, from_, to))
        return answer()
    monkeypatch.setattr(ctxmod, "regime_answer", fake)
    return asked


def plant_answer(monkeypatch, made: dict) -> None:
    monkeypatch.setattr(ctxmod, "regime_answer", lambda index, k, from_, to: made)


def test_the_planted_minute_bars_live_only_in_the_tests_own_folder(planted, tmp_path):
    """심은 분봉은 그 시험의 임시 폴더에만 쓴다 — `client` 없이 이 고정물만 쓰는 시험도 저장소의 기본 경로(`data/minute_bars`)에 쓰지 않는다.
    `client` 와 같은 폴더라 둘을 함께 쓰는 시험은 같은 날을 읽는다."""
    assert os.environ.get("MINUTE_BARS_DIR") == str(tmp_path / "bars")
    assert sorted(p.name.split(".")[0] for p in (tmp_path / "bars").iterdir()) == DAYS


def regime_cmp(state: int = 1, k: int = 2, value: float = 0.6, name: str = "gt", index: str = "KOSPI") -> dict:
    return {"op": name, "args": [{"ind": "regime_prob", "index": index, "k": k, "state": state}, {"const": value}]}


UP = {"op": "gt", "args": [{"ind": "close"}, {"const": 0}]}


def request(entry: dict | None = None, start: str = DAYS[0], end: str = DAYS[-1], **params) -> dict:
    body = {"entry": entry if entry is not None else {"op": "and", "args": [regime_cmp(), UP]}, **params}
    return {"tickers": list(TICKERS), "from": start, "to": end, "rule": {"kind": "custom", "params": body},
            "position": {"amount": 1_000_000}, "costs": {"commission_bp": 1.5}}


def opened(js: dict) -> set[tuple[str, str]]:
    return {(t["symbol"], t["opened_at"]) for t in js["journal"]["trades"]}


def regime_facts(js: dict) -> list[dict]:
    return [f for f in js["context"] if f.get("kind") == "regime"]


# ── simulate — 손 계산 · 사실 줄 ─────────────────────────────────────────────────────────────
def test_simulate_enters_only_on_the_day_whose_probability_is_above_the_threshold(client, auth, planted):
    r = client.post("/api/v1/intraday/simulate", json=request(), headers=auth)
    assert r.status_code == 200, r.text
    assert opened(r.json()) == {(t, "2026-06-01T09:01:00") for t in TICKERS}
    low = client.post("/api/v1/intraday/simulate", json=request({"op": "and", "args": [regime_cmp(2, value=0.6), UP]}), headers=auth)
    assert opened(low.json()) == {(t, "2026-06-02T09:01:00") for t in TICKERS}          # 짝 — 국면 2 > 0.6 은 06-02
    assert planted and all(a[:2] == ("KOSPI", 2) and (a[2], a[3]) == (date(2026, 6, 1), date(2026, 6, 4)) for a in planted)


def test_an_unknown_day_never_satisfies_even_a_below_condition(client, auth, planted):
    """모르는 날(창이 덜 참 · 지수에 없음)을 0 이나 균등 확률로 채우면 '미만'이 선다 — 서지 않아야 한다."""
    r = client.post("/api/v1/intraday/simulate", json=request({"op": "and", "args": [regime_cmp(1, value=0.9, name="lt"), UP]}),
                    headers=auth)
    assert opened(r.json()) == {(t, f"{d}T09:01:00") for t in TICKERS for d in ("2026-06-01", "2026-06-02")}


def test_the_fact_line_counts_known_and_unknown_days_with_their_reasons(client, auth, planted):
    js = client.post("/api/v1/intraday/simulate", json=request(), headers=auth).json()
    [fact] = regime_facts(js)
    assert (fact["key"], fact["index"], fact["k"], fact["states"], fact["grade"]) == ("KOSPI:2", "KOSPI", 2, [1], "E3")
    assert fact["days"] == {"loaded": 4, "known": 2, "unknown": 2}
    assert fact["unknown_reasons"] == [{"reason": SHORT, "days": 1}, {"reason": ctxmod.NO_INDEX_DAY, "days": 1}]
    assert fact["sentences"] == [
        "코스피 시장 국면(국면 2개)의 확률은 그날 시가 전에 알던 값입니다. 전 거래일 종가까지의 지수 일봉으로 계산했고 그날 종가는 쓰지 않았습니다.",
        "분봉이 적재된 날 4일 가운데 국면 확률을 아는 날은 2일입니다.",
        "확률을 모르는 날 2일은 국면 조건을 충족하지 않은 것으로 계산했습니다.",
        f"1일: {SHORT}",
        f"1일: {ctxmod.NO_INDEX_DAY}",
        k1.NOTES[0],
    ]
    assert all("—" not in s and "–" not in s for s in fact["sentences"])


def test_unknown_days_are_counted_by_day_not_by_reason(client, auth, planted, monkeypatch):
    """모르는 날은 ★날로★ 센다 — 같은 사유가 이틀이면 사유 하나 · 날 둘(사유의 수로 세면 틀린다)."""
    plant_answer(monkeypatch, answer({"2026-06-01": [0.8, 0.2], "2026-06-02": None, "2026-06-03": None}))   # 06-04 는 지수에 없다
    [fact] = regime_facts(client.post("/api/v1/intraday/simulate", json=request(), headers=auth).json())
    assert fact["days"] == {"loaded": 4, "known": 1, "unknown": 3}
    assert fact["unknown_reasons"] == [{"reason": SHORT, "days": 2}, {"reason": ctxmod.NO_INDEX_DAY, "days": 1}]
    assert "확률을 모르는 날 3일은 국면 조건을 충족하지 않은 것으로 계산했습니다." in fact["sentences"]


def test_a_synthetic_regime_says_so_and_an_unlabelled_one_has_no_grade(client, auth, planted, monkeypatch):
    plant_answer(monkeypatch, answer(grade="E0"))
    [fact] = regime_facts(client.post("/api/v1/intraday/simulate", json=request(), headers=auth).json())
    assert fact["grade"] == "E0" and ctxmod.REGIME_SYNTHETIC in fact["sentences"]
    plant_answer(monkeypatch, answer(grade=None))
    [fact] = regime_facts(client.post("/api/v1/intraday/simulate", json=request(), headers=auth).json())
    assert fact["grade"] is None and k1.GRADE_UNKNOWN in fact["sentences"] and ctxmod.REGIME_SYNTHETIC not in fact["sentences"]
    plant_answer(monkeypatch, answer())
    [fact] = regime_facts(client.post("/api/v1/intraday/simulate", json=request(), headers=auth).json())
    assert ctxmod.REGIME_SYNTHETIC not in fact["sentences"] and k1.GRADE_UNKNOWN not in fact["sentences"]   # 짝


def test_a_rule_without_a_regime_asks_no_regime_and_has_no_regime_facts(client, auth, planted):
    r = client.post("/api/v1/intraday/simulate", json=request(UP), headers=auth)
    assert r.status_code == 200 and regime_facts(r.json()) == [] and planted == []


def test_two_regimes_in_one_rule_are_each_asked_once_and_each_have_a_fact(client, auth, planted):
    entry = {"op": "and", "args": [regime_cmp(), regime_cmp(1, k=3, value=0.0, name="ge", index="KOSDAQ"), UP]}
    js = client.post("/api/v1/intraday/simulate", json=request(entry), headers=auth).json()
    assert sorted((a[0], a[1]) for a in planted) == [("KOSDAQ", 3), ("KOSPI", 2)]
    assert [f["key"] for f in regime_facts(js)] == ["KOSDAQ:3", "KOSPI:2"]


# ── 거절 — 봉을 읽기 전에 ──────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("path", ["/api/v1/intraday/simulate", "/api/v1/intraday/validate"])
@pytest.mark.parametrize(("made", "status", "code"), [
    (answer(empty="store_error"), 503, "regime_store_unavailable"),
    (answer(empty="not_loaded"), 400, "regime_unavailable"),
    (answer(empty="synthetic_in_production"), 400, "regime_unavailable"),
    (answer(empty="bad_dates"), 400, "regime_unavailable"),
    (answer({"2026-06-01": None, "2026-06-02": None}), 400, "regime_unknown_all"),
])
def test_a_regime_that_cannot_be_used_is_refused_before_any_bar_is_read(client, auth, planted, monkeypatch, path, made, status, code):
    plant_answer(monkeypatch, made)
    monkeypatch.setattr(minute_feed, "build_days", lambda *a, **k: (_ for _ in ()).throw(AssertionError("읽었다")))
    r = client.post(path, json=request(), headers=auth)
    assert r.status_code == status, r.text
    detail = r.json()["detail"]
    assert detail["code"] == code and detail["reason"].startswith(ctxmod.REASONS[code])
    if made["empty"] and made["empty"]["reason"] != "store_error":
        assert made["empty"]["message"] in detail["reason"]                  # 시장 국면 문의 그 문장
    if code == "regime_unknown_all":
        assert detail["reasons"] == [{"reason": SHORT, "days": 2}, {"reason": ctxmod.NO_INDEX_DAY, "days": 2}]
        assert SHORT in detail["reason"]


def test_one_known_day_is_enough_to_run(client, auth, planted, monkeypatch):
    """짝 — 아는 날이 하루라도 있으면 돈다(모르는 날은 조건 불충족 + 사실 줄)."""
    plant_answer(monkeypatch, answer({"2026-06-01": None, "2026-06-02": None, "2026-06-03": None, "2026-06-04": [0.9, 0.1]}))
    r = client.post("/api/v1/intraday/simulate", json=request(), headers=auth)
    assert r.status_code == 200, r.text
    assert opened(r.json()) == {(t, "2026-06-04T09:01:00") for t in TICKERS}


def test_loading_a_regime_without_the_period_and_the_days_is_a_bug_not_a_single_day(planted):
    spec = rules.build("custom", request()["rule"]["params"])
    with pytest.raises(ValueError):
        ctxmod.load("alice", spec, date(2026, 6, 1))
    with pytest.raises(ValueError):
        ctxmod.load("alice", spec, date(2026, 6, 1), end=date(2026, 6, 4))
    assert ctxmod.load("alice", spec, date(2026, 6, 1), end=date(2026, 6, 4), dates=DAYS).context is not None   # 짝


# ── validate — 짝 비교 · 시행 하나 · 계산량 ─────────────────────────────────────────────────────
def test_validate_reports_the_pair_without_recording_it_as_a_trial(client, auth, planted):
    r = client.post("/api/v1/intraday/validate", json=request(), headers=auth)
    assert r.status_code == 200, r.text
    js = r.json()
    pair = js["regime_pair"]
    assert pair["known"] is True and pair["reason"] is None and pair["note"] == iroutes.REGIME_PAIR_NOTE
    assert pair["with"] == js["summary"] and pair["with"]["trades"] == 2 and pair["without"]["trades"] == 8
    assert pair["rule_text"] == "진입 조건: 종가 > 0"
    rows = client.get("/api/v1/intraday/trials", headers=auth).json()["trials"]
    assert len(rows) == 1 and rows[0]["runs"] == 1                            # 뺀 판은 시행이 아니다
    bare = client.post("/api/v1/intraday/validate", json=request(UP), headers=auth).json()
    assert bare["summary"] == pair["without"] and bare["regime_pair"] is None   # 뺀 판 = 그 규칙을 따로 판정한 요약
    assert len(client.get("/api/v1/intraday/trials", headers=auth).json()["trials"]) == 2


def test_the_pair_is_counted_in_the_work_once(planted):
    with_it = iroutes.prepare(iroutes.ValidateBody(**request()), "alice")
    bare = iroutes.prepare(iroutes.ValidateBody(**request(UP)), "alice")
    only = iroutes.prepare(iroutes.ValidateBody(**request(regime_cmp())), "alice")
    assert with_it.simulations == bare.simulations + 1
    assert only.simulations == bare.simulations                             # 뺀 판을 지을 수 없으면 더 돌리지 않는다


def test_a_rule_made_only_of_the_regime_has_no_pair_and_says_why(client, auth, planted):
    js = client.post("/api/v1/intraday/validate", json=request(regime_cmp()), headers=auth).json()
    pair = js["regime_pair"]
    assert pair["known"] is False and pair["without"] is None and pair["reason"] == iroutes.REGIME_PAIR_NO_ENTRY
    assert pair["with"] == js["summary"]


def test_a_rule_with_a_stop_keeps_the_stop_in_the_pair(client, auth, planted):
    """국면 조건뿐인 진입 조건 + 미리 건 매수 가격 → 뺀 판은 미리 건 매수만 남는다(지을 수 있다)."""
    body = request(regime_cmp(), entry_stop={"ind": "or_high", "minutes": 1})
    js = client.post("/api/v1/intraday/validate", json=body, headers=auth).json()
    pair = js["regime_pair"]
    assert pair["known"] is True and pair["rule_text"] == "미리 건 매수 가격: 시가 범위 고가(1분)"
    assert rules.REGIME_STOP_NOTE in rules.notes_of(rules.build("custom", body["rule"]["params"]))


def test_a_rule_without_a_regime_has_no_pair(client, auth, planted):
    assert client.post("/api/v1/intraday/validate", json=request(UP), headers=auth).json()["regime_pair"] is None


# ── divergence · prepare · 규칙 가동의 하루 ────────────────────────────────────────────────────
def test_divergence_simulates_with_the_regime(client, auth, planted):
    fills = [{"executed_at": "2026-06-01 09:01:00", "symbol": TICKERS[0], "side": "buy", "quantity": 99, "price": 10_010}]
    r = client.post("/api/v1/intraday/divergence", json={**request(), "fills": fills}, headers=auth)
    assert r.status_code == 200, r.text
    counts = r.json()["divergence"]["counts"]
    assert counts["matched"] + counts["sim_only"] == 4                      # 06-01 에 산 둘 · 판 둘
    [fact] = regime_facts(r.json())
    assert fact["key"] == "KOSPI:2" and fact["days"] == {"loaded": 4, "known": 2, "unknown": 2}   # 분봉 날짜로 센다(빈 날짜로 메우지 않는다)


def test_the_canvas_check_carries_the_regime_and_the_same_refusal(planted, monkeypatch):
    ready = iroutes.prepare(iroutes.ValidateBody(**request()), "alice")
    assert ("KOSPI", 2) in ready.context.context.regimes
    plant_answer(monkeypatch, answer(empty="store_error"))
    with pytest.raises(HTTPException) as err:
        iroutes.prepare(iroutes.ValidateBody(**request()), "alice")
    assert err.value.status_code == 503


def test_the_rule_run_day_carries_the_regime_and_refuses_an_unknown_day(planted):
    spec = rules.build("custom", request()["rule"]["params"])
    built = bar._day_of("alice", list(TICKERS), spec, date(2026, 6, 1))
    assert built is not None
    day, _session = built
    assert all(s.context is not None and ("KOSPI", 2) in s.context.regimes for s in day.sessions.values())
    with pytest.raises(HTTPException) as err:
        bar._day_of("alice", list(TICKERS), spec, date(2026, 6, 3))          # 그날은 모른다 — 가동하지 않는다
    assert err.value.detail["code"] == "regime_unknown_all"
    with pytest.raises(rule_monitor.DayUnavailable) as gone:
        bar._monitor_day("alice", list(TICKERS), spec, "2026-06-03")
    assert gone.value.reason.startswith(ctxmod.REASONS["regime_unknown_all"])


# ── 같은 함수 · 앞보기 ──────────────────────────────────────────────────────────────────────────
def two_level_frame(poison_from: str | None = None, poison_day: str | None = None) -> pd.DataFrame:
    dates = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2021-01-01", "2026-06-30")]
    vols = np.array([0.005 if (i // 120) % 2 == 0 else 0.02 for i in range(len(dates))])
    closes = 2500.0 * np.exp(np.cumsum(np.random.default_rng(7).normal(0.0, 1.0, len(dates)) * vols))
    for i, d in enumerate(dates):
        if (poison_from and d >= poison_from) or d == poison_day:
            closes[i] *= 3.0
    df = pd.DataFrame({"open": closes, "high": closes, "low": closes, "close": closes, "volume": 0.0}, index=pd.to_datetime(dates))
    df.attrs.update(source="db", coverage_ok=True, coverage_reason=None)
    return df


def test_the_rule_reads_the_same_function_as_the_market_regime_door(planted, monkeypatch):
    monkeypatch.setattr(ctxmod, "regime_answer", k1.regime_answer)
    assert ctxmod.regime_answer is k1.regime_answer
    df = two_level_frame()
    monkeypatch.setattr(k1, "load_index_daily", lambda code, start, end: df)
    spec = rules.build("custom", request()["rule"]["params"])
    seen = ctxmod.load("alice", spec, date(2026, 6, 1), end=date(2026, 6, 4), dates=DAYS).context.regimes[("KOSPI", 2)].probs
    door = {row["date"]: row["probs"] for row in k1.regime_answer("KOSPI", 2, date(2026, 6, 1), date(2026, 6, 4))["days"]}
    assert set(door) == set(DAYS) and all(door[d] is not None for d in DAYS)
    assert {d: list(seen[d]) for d in DAYS} == {d: list(door[d]) for d in DAYS}


def test_the_closes_of_the_day_and_after_never_change_that_days_probability(planted, monkeypatch):
    monkeypatch.setattr(ctxmod, "regime_answer", k1.regime_answer)
    spec = rules.build("custom", request()["rule"]["params"])

    def probs(df: pd.DataFrame) -> tuple:
        monkeypatch.setattr(k1, "load_index_daily", lambda code, start, end: df)
        return ctxmod.load("alice", spec, date(2026, 6, 1), end=date(2026, 6, 1), dates=["2026-06-01"]).context.regimes[
            ("KOSPI", 2)].probs["2026-06-01"]

    clean = probs(two_level_frame())
    assert probs(two_level_frame(poison_from="2026-06-01")) == clean          # 그날과 그 뒤의 종가는 보지 않는다
    assert probs(two_level_frame(poison_day="2026-05-29")) != clean          # 짝 — 전 거래일 종가는 본다


# ── 캔버스 — 설정 노드의 보기 · 설명 · 실행 단추가 남긴 요약 ─────────────────────────────────────
RUN, SAVE = "/api/v1/allocation/graph/run", "/api/v1/allocation/graph/save"


def canvas(entry: dict, node_id: str = "s") -> dict:
    params = {"tickers": list(TICKERS), "start_date": DAYS[0], "end_date": DAYS[-1], "rule": "custom", "custom_rule": {"entry": entry},
              "amount": 1_000_000, "commission_bp": 1.5, "slippage_ticks": 1}
    return {"format": pg.FORMAT, "version": pg.VERSION, "edges": [],
            "nodes": [{"id": node_id, "type": "intraday_setup", "params": params}]}


def node_of(client, headers, g: dict, node_id: str) -> dict:
    r = client.post(RUN, json=g, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["nodes"][node_id]


def test_the_canvas_setup_shows_the_regime_facts_and_the_kept_result_carries_the_pair(client, auth, planted):
    g = canvas({"op": "and", "args": [regime_cmp(), UP]})
    s = node_of(client, auth, g, "s")
    assert s["status"] == "ok", s.get("reason")
    [fact] = [f for f in s["view"]["context"] if f.get("kind") == "regime"]
    assert fact["sentences"][0] in s["explain"]["facts"]
    trust = [t["text"] for t in s["explain"]["trust"]]
    assert iroutes_trust("regime") in trust and iroutes_trust("day_type") not in trust
    saved = client.post(SAVE, json={"graph": g, "node_id": "s", "preview_hash": s["view_hash"] or "none"}, headers=auth)
    assert saved.status_code == 200, saved.text
    load = {"format": pg.FORMAT, "version": pg.VERSION, "edges": [],
            "nodes": [{"id": "l", "type": "intraday_load", "params": {"trial_key": saved.json()["saved_id"]}}]}
    kept = node_of(client, auth, load, "l")
    assert kept["status"] == "ok", kept.get("reason")
    pair = kept["view"]["regime_pair"]
    assert pair["known"] is True and pair["without"]["trades"] == 8
    assert any(f.startswith("국면 조건을 뺀 같은 규칙: 거래 8건") for f in kept["explain"]["facts"])


def iroutes_trust(kind: str) -> str:
    from src.api import allocation_graph_nodes_intraday as nodes
    return nodes.CONTEXT_TRUST[kind]
