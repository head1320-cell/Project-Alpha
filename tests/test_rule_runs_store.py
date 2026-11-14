"""가동 기록 저장소(`src/data/rule_runs.py`) — W5b 구현 계획 §3

가동 요청(캔버스가 남긴 '가동해 달라'는 한 줄) · 가동(계좌 하나 × 시행 하나 × 하루) · 가상 체결을 적는 자리다.

거는 것:
  · 전부 사용자로 갈린다 — 남의 것과 없는 것은 같은 답이다(있는지를 알려 주지 않는다)
  · 읽지 못함은 `None` 이다 — 빈 목록 · '없음'과 다르다(침묵 폴백 금지)
  · 요청을 지우면 목록에서 빠지지만 줄은 남는다(무엇을 요청했었는지의 기록) · 같은 시행의 살아 있는 요청은 한 줄이다
  · 가동 번호는 정수다(주문 · 감사 줄의 `strategy_id` 자리에 들어간다) · 가동마다 다르다
  · 가상 체결은 낸 순서(`seq`)대로 읽힌다 · 같은 순번을 두 번 쓰지 못한다 · ★종류는 늘 `virtual` 이다★
  · 재시작 표시: `running` 으로 남은 가동만 `interrupted` 로 바뀐다(끝난 가동은 그대로)
"""
from __future__ import annotations

import os
import tempfile

import pytest

import src.data.rule_runs as rr
import src.database as dbmod

REQUEST = {"tickers": ["035720"], "from": "2026-03-02", "to": "2026-03-13", "rule": {"kind": "opening_range_breakout", "params": {"minutes": 1}},
           "position": {"amount": 1_000_000}, "costs": {"slippage_ticks": 1}}
BUY = {"executed_at": "2026-03-02 09:02:00", "symbol": "035720", "side": "buy", "quantity": 99, "price": 10_080.0}
SELL = {"executed_at": "2026-03-02 09:03:00", "symbol": "035720", "side": "sell", "quantity": 99, "price": 10_100.0}
LOGGED = {"client_order_id": "CO-1", "status": "SHADOW_LOGGED", "reason": None}


@pytest.fixture()
def db(monkeypatch):
    """임시 DB 하나. 이 저장소의 '표를 만들었다' 표시는 DB 주소별이라 다른 시험에 남지 않는다."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setattr(dbmod, "DATABASE_URL", f"sqlite:///{tmp.name}", raising=False)
    dbmod.reset_session()
    yield tmp.name
    dbmod.reset_session()
    os.unlink(tmp.name)


def _open(user="kim", account="acc-1", trial="t" * 64, day="2026-03-02", **kw) -> int:
    run_id = rr.open_run(user, account, trial, REQUEST, day, feed="replay", mode="SHADOW", grade=kw.pop("grade", "E3"), tickers=["035720"])
    assert isinstance(run_id, int)
    return run_id


# ── 가동 요청 ────────────────────────────────────────────────────────────────

def test_a_request_is_listed_for_its_owner_only(db):
    made = rr.add_request("kim", "a" * 64, note="캔버스에서")
    assert made["new"] is True and made["trial_key"] == "a" * 64 and isinstance(made["id"], int)
    mine = rr.requests_of("kim")
    assert [(r["id"], r["trial_key"], r["note"]) for r in mine] == [(made["id"], "a" * 64, "캔버스에서")] and mine[0]["created_at"] > 0
    assert rr.requests_of("lee") == []                                    # 남의 요청은 보이지 않는다


def test_asking_again_for_the_same_trial_does_not_add_a_second_row(db):
    first = rr.add_request("kim", "a" * 64)
    again = rr.add_request("kim", "a" * 64)
    assert again["new"] is False and again["id"] == first["id"] and len(rr.requests_of("kim")) == 1
    other = rr.add_request("lee", "a" * 64)                               # 다른 사람의 같은 열쇠는 다른 줄이다
    assert other["new"] is True and other["id"] != first["id"]


def test_removing_a_request_hides_it_and_only_its_owner_can(db):
    made = rr.add_request("kim", "a" * 64)
    assert rr.remove_request("lee", made["id"]) is False and len(rr.requests_of("kim")) == 1   # 남의 것은 '없는 것'이다
    assert rr.remove_request("kim", made["id"]) is True and rr.requests_of("kim") == []
    assert rr.remove_request("kim", made["id"]) is False                  # 이미 지운 것도 없는 것이다
    back = rr.add_request("kim", "a" * 64)                                 # 지운 뒤 다시 요청하면 새 줄이다
    assert back["new"] is True and back["id"] != made["id"]


def test_requests_come_newest_first_and_are_capped(db):
    ids = [rr.add_request("kim", f"{i:064d}")["id"] for i in range(5)]
    assert [r["id"] for r in rr.requests_of("kim")] == ids[::-1]
    assert [r["id"] for r in rr.requests_of("kim", limit=2)] == ids[::-1][:2]


# ── 가동 ────────────────────────────────────────────────────────────────────

def test_a_run_is_numbered_and_read_back_by_its_owner_and_account(db):
    a, b = _open(), _open(day="2026-03-03")
    assert a != b and a > 0 and b > 0
    got = rr.run_of("kim", "acc-1", a)
    assert got["found"] is True and got["run_id"] == a and got["status"] == "running" and got["stop_reason"] is None
    assert got["request"] == REQUEST and got["day"] == "2026-03-02" and got["mode"] == "SHADOW" and got["feed"] == "replay"
    assert got["grade"] == "E3" and got["tickers"] == ["035720"] and got["bars"] == 0 and got["signals"] == 0 and got["last_bar"] is None
    assert got["started_at"] > 0 and got["ended_at"] is None


@pytest.mark.parametrize("user, account", [("lee", "acc-1"), ("kim", "acc-2"), ("lee", "acc-2")])
def test_someone_elses_run_and_a_missing_run_are_the_same_answer(db, user, account):
    run_id = _open()
    assert rr.run_of(user, account, run_id) == {"found": False} == rr.run_of("kim", "acc-1", run_id + 99)
    assert rr.runs_of(user, account) == []


def test_runs_are_listed_newest_first_for_one_account(db):
    a, b = _open(), _open(day="2026-03-03")
    other = _open(account="acc-2")
    assert [r["run_id"] for r in rr.runs_of("kim", "acc-1")] == [b, a]
    assert [r["run_id"] for r in rr.runs_of("kim", "acc-2")] == [other]
    assert [r["run_id"] for r in rr.runs_of("kim", "acc-1", limit=1)] == [b]


def test_progress_and_the_stop_reason_are_written_as_given(db):
    run_id = _open()
    assert rr.update_run(run_id, last_bar="090300", bars=4, signals=2) is True
    assert rr.update_run(run_id, status="stopped", stop_reason="kill_switch", stop_message="비상 정지가 걸려 있어 가동을 멈췄습니다.", ended=True) is True
    got = rr.run_of("kim", "acc-1", run_id)
    assert (got["last_bar"], got["bars"], got["signals"]) == ("090300", 4, 2)
    assert (got["status"], got["stop_reason"], got["stop_message"]) == ("stopped", "kill_switch", "비상 정지가 걸려 있어 가동을 멈췄습니다.")
    assert got["ended_at"] >= got["started_at"]
    assert rr.update_run(run_id + 99, bars=1) is False                    # 없는 가동


def test_a_field_that_is_not_progress_cannot_be_rewritten(db):
    run_id = _open()
    for bad in ({"username": "lee"}, {"account_id": "acc-2"}, {"request": "{}"}, {"mode": "LIVE"}, {"status": "weird"}):
        with pytest.raises(ValueError):
            rr.update_run(run_id, **bad)
    got = rr.run_of("kim", "acc-1", run_id)
    assert got["mode"] == "SHADOW" and got["status"] == "running"


# ── 가상 체결 ────────────────────────────────────────────────────────────────

def test_virtual_fills_are_read_back_in_the_order_they_were_emitted(db):
    run_id = _open()
    assert rr.add_fill(run_id, 0, BUY, event="entry_signal", order=LOGGED) is True
    assert rr.add_fill(run_id, 1, SELL, event="session_end", order={"client_order_id": "CO-2", "status": "REJECTED", "reason": "kill_switch_active"}) is True
    rows = rr.fills_of(run_id)
    assert [(r["seq"], r["side"], r["executed_at"], r["quantity"], r["price"], r["event"]) for r in rows] == [
        (0, "buy", "2026-03-02 09:02:00", 99, 10_080.0, "entry_signal"), (1, "sell", "2026-03-02 09:03:00", 99, 10_100.0, "session_end")]
    assert [(r["client_order_id"], r["order_status"], r["order_reason"]) for r in rows] == [("CO-1", "SHADOW_LOGGED", None), ("CO-2", "REJECTED", "kill_switch_active")]
    assert {r["kind"] for r in rows} == {"virtual"} and {r["symbol"] for r in rows} == {"035720"}
    assert rr.fills_of(run_id + 99) == []


def test_the_same_sequence_number_cannot_be_written_twice(db):
    run_id = _open()
    assert rr.add_fill(run_id, 0, BUY, event="entry_signal", order=LOGGED) is True
    assert rr.add_fill(run_id, 0, SELL, event="session_end", order=LOGGED) is None      # 쓰지 못했다 — 덮어쓰지 않는다
    assert [r["side"] for r in rr.fills_of(run_id)] == ["buy"]


def test_fills_of_one_run_do_not_leak_into_another(db):
    a, b = _open(), _open(day="2026-03-03")
    rr.add_fill(a, 0, BUY, event="entry_signal", order=LOGGED)
    assert rr.fills_of(b) == [] and len(rr.fills_of(a)) == 1


# ── 재시작 ──────────────────────────────────────────────────────────────────

def test_a_restart_marks_only_the_runs_still_running(db):
    live, done = _open(), _open(day="2026-03-03")
    rr.update_run(done, status="finished", stop_reason="finished", stop_message="하루가 끝났습니다.", ended=True)
    assert rr.mark_interrupted() == 1
    got = rr.run_of("kim", "acc-1", live)
    assert (got["status"], got["stop_reason"]) == ("interrupted", "interrupted") and got["stop_message"] == rr.REASONS["interrupted"]
    assert got["ended_at"] is not None
    assert rr.run_of("kim", "acc-1", done)["status"] == "finished"
    assert rr.mark_interrupted() == 0                                     # 두 번 불러도 더 바꾸지 않는다


# ── 못 읽음 ≠ 없음 ─────────────────────────────────────────────────────────────

def test_an_unreadable_store_answers_none_not_empty(db, monkeypatch):
    run_id = _open()

    def broken():
        raise RuntimeError("DB 가 죽었다")

    monkeypatch.setattr(rr, "_engine", broken)
    assert rr.requests_of("kim") is None and rr.add_request("kim", "a" * 64) is None and rr.remove_request("kim", 1) is None
    assert rr.runs_of("kim", "acc-1") is None and rr.run_of("kim", "acc-1", run_id) is None
    assert rr.open_run("kim", "acc-1", "t" * 64, REQUEST, "2026-03-02", feed="replay", mode="SHADOW", grade="E3", tickers=["035720"]) is None
    assert rr.update_run(run_id, bars=1) is None and rr.add_fill(run_id, 0, BUY, event="entry_signal", order=LOGGED) is None
    assert rr.fills_of(run_id) is None and rr.mark_interrupted() is None


def test_this_store_never_touches_the_real_fills_table(db):
    """가상 체결을 실제 체결의 자리(`live_fills`)에 쓰지 않는다 — 이 저장소는 그 표의 이름조차 모른다."""
    import inspect
    assert "live_fills" not in inspect.getsource(rr).replace("`live_fills`", "")
    run_id = _open()
    rr.add_fill(run_id, 0, BUY, event="entry_signal", order=LOGGED)
    from sqlalchemy import inspect as sa_inspect
    assert "live_fills" not in sa_inspect(dbmod.get_engine()).get_table_names()        # 표를 만들지도 않았다
