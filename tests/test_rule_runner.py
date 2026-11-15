"""규칙 가동기(`src/execution/rule_runner.py`) — 기록 전용(SHADOW) · 재생 (W5b · 구현 계획 §4 · 설계 §5.6)

가동 하나 = 계좌 하나 × 시행 하나 × 하루. 가동기는 봉이 닫힐 때마다 걸음 엔진을 한 걸음 밀고, 새로 생긴 체결 줄마다 신호 하나를
★계좌 실행기의 `execute_signal` 한 길로만★ 보낸다. 기록 전용에서는 증권사로 아무것도 나가지 않고, 시뮬레이터가 계산한 체결을
'가상'으로 적는다.

거는 것:
  ① 끝까지 민 가상 체결 = 그 하루의 분봉 백테스트 체결(줄 단위 · 틀마다) · 봉 하나씩 밀어도 같다
  ② 실제 체결의 자리(`live_fills`)에 쓰지 않는다 · 신호는 전부 주문 경로를 지난다(주문 줄 = 신호 수 · 전부 SHADOW_LOGGED · 증권사로 0건)
  ③ 비상 정지 → 멈춤 ↔ 풀고 새로 가동하면 돈다
  ④ 봉이 끊기면 멈춤 ↔ 이어진 날은 끝까지
  ⑤ 남의 계좌 · 남의 가동 · 남의 시행은 없는 것과 같은 답
  ⑥ 시행이 없는 설정은 가동하지 못한다 · 운영에서는 합성 분봉으로 가동하지 않는다
  ⑦ 재시작하면 가동은 전부 꺼지고 남은 줄은 '중단됨'이다(되살리지 않는다)
  ⑧ 모드가 바뀌면 멈춘다 · 모의투자 모드에서는 시작하지 않는다(이 조각은 기록 전용만)
  ⑨ 상한 · 거절이 이어지면 멈춤 · 기록을 쓰지 못하면 멈춤 · 주문 경로가 터지면 멈춤
  ⑩ 주문 경로를 새로 만들지 않는다(정적)
"""
from __future__ import annotations

import ast
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

import src.data.intraday_trials as trials
import src.data.rule_runs as rr
import src.database as dbmod
import src.execution.account_executors as ae
import src.execution.broker_accounts as ba
import src.execution.kis_client as kc
import src.execution.rule_runner as runner
from src.api.intraday_routes import CostsBody, PositionBody
from src.engine.intraday import rules as templates
from src.engine.intraday.simulator import CostAssumptions, Day, PositionRules, simulate
from src.execution.live_schemas import init_live_trading_schema
from src.execution.rule_runner import RunRefused
from tests.test_intraday_simulator import DATE, R0, R1, R2, R3, RULES, _random_session, sess
from tests.test_intraday_stepper import TEMPLATE_CASES, _drop, _with_prev

HAND = [R0, R1, R2, R3]                    # 개장 1분 범위 돌파: 09:01 이 신호 봉 → 09:02 시가 + 한 틱에 99주 · 하루 끝 09:03 종가 − 한 틱
BUY = ("005930", "buy", f"{DATE} 09:02:00", 99, 10_080.0)
SELL = ("005930", "sell", f"{DATE} 09:03:00", 99, 10_100.0)
POSITION = PositionBody(amount=1_000_000).model_dump()
COSTS = CostsBody(commission_bp=1.5, slippage_ticks=1).model_dump()


@pytest.fixture()
def acc(monkeypatch):
    """임시 DB · 모의 모드 · kim 의 모의투자 계좌 하나. 실행기 · 클라이언트 · 가동기의 프로세스 상태를 비우고 시작한다."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    url = f"sqlite:///{tmp.name}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    monkeypatch.setenv("BROKER_CRED_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(dbmod, "DATABASE_URL", url, raising=False)
    monkeypatch.setattr(kc, "_kis_singleton", None, raising=False)
    monkeypatch.setattr(kc, "_account_clients", {}, raising=False)
    monkeypatch.setattr(ae, "_executors", {}, raising=False)
    monkeypatch.setattr(runner, "_active", {}, raising=False)
    dbmod.reset_session()
    dbmod.init_db()
    init_live_trading_schema(dbmod.get_sync_engine())
    yield _account("kim")
    dbmod.reset_session()
    os.unlink(tmp.name)


def _account(owner: str) -> str:
    return ba.connect(owner, label="내 계좌", app_key="PSkey-0123456789abcdef", app_secret="secret-0123456789abcdefghijklmnop",
                      account_no="50123456", is_paper=True)["account_id"]


def _setting(kind="opening_range_breakout", params=None, position=None, costs=None) -> dict:
    return {"rule": {"kind": kind, "params": templates.resolve(kind, {"minutes": 1} if params is None else params)},
            "position": {**POSITION, **(position or {})}, "costs": {**COSTS, **(costs or {})}}


def _trial(user="kim", *, tickers=("005930",), grade="E3", setting=None, **kw) -> str:
    made = trials.record(user, grade=grade, setting=setting or _setting(**kw), tickers=list(tickers), start="2026-03-02",
                         end="2026-03-13", daily={"basis": "net", "dates": [], "values": []})
    return made["trial_key"]


def _day(*sessions, **kw) -> Day:
    return Day(DATE, {s.ticker: s for s in (sessions or (sess(HAND),))}, **kw)


def _start(acc, key=None, day=None, user="kim") -> dict:
    return runner.start(user, acc, key or _trial(), day or _day(), session=RULES)


def _rows(run_id: int) -> list[tuple]:
    return [(f["symbol"], f["side"], f["executed_at"], f["quantity"], f["price"]) for f in rr.fills_of(run_id)]


def _batch(setting: dict, day: Day) -> list[tuple]:
    out = simulate([day], templates.build(setting["rule"]["kind"], setting["rule"]["params"]), PositionRules(**setting["position"]),
                   CostAssumptions(**setting["costs"]), rules=RULES)
    return [(f["symbol"], f["side"], f["executed_at"], f["quantity"], f["price"]) for f in out["fills"]]


def _orders(acc: str) -> list[dict]:
    with dbmod.get_sync_engine().connect() as c:
        rows = c.execute(text("SELECT strategy_id, status, execution_mode, signal_source, ticker, side, quantity, price, order_type "
                              "FROM live_orders WHERE account_id = :a ORDER BY id"), {"a": acc}).fetchall()
    return [dict(r._mapping) for r in rows]


def _count(table: str) -> int:
    with dbmod.get_sync_engine().connect() as c:
        return int(c.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar())


def _refused(code: str, call, *args, **kw) -> RunRefused:
    with pytest.raises(RunRefused) as caught:
        call(*args, **kw)
    assert caught.value.code == code, (caught.value.code, caught.value.message)
    assert caught.value.message == runner.REASONS[code] and caught.value.message.strip()
    return caught.value


def _halt(acc: str) -> None:
    ex = ae.get_account_executor(acc)
    ex.kill_switch.trigger(source="manual_kim", reason="시험", equity=None, dd_pct=None, kis_client=ex.kis, liquidation_mode="hold")


# ── ① 가상 체결 = 그 하루의 분봉 백테스트 체결 ─────────────────────────────────────────

def _class(fill: dict) -> tuple:
    return fill["market"], fill["instrument"], fill["classified"]


def test_each_virtual_fill_keeps_the_market_and_instrument_the_simulator_saw(acc):
    """준비가 정한 시장 · 상품을 체결 줄에 남긴다(관제의 매도세가 뒤에 달라지는 종목 마스터에 기대지 않게)."""
    done = runner.advance("kim", acc, _start(acc)["run_id"])
    kept = [_class(f) for f in rr.fills_of(done["run_id"])]
    assert kept == [("KOSPI", "stock", True)] * 2
    assert [_class(f) for f in done["new_fills"]] == kept                  # 답의 새 줄도 적힌 것과 같은 모양이다
    # ★짝★ — 준비가 시장을 몰랐던 종목은 모른다고 적힌다(지어내지 않는다 · 그래도 '그때의 값'이다)
    unknown = runner.advance("kim", acc, _start(acc, day=_day(sess(HAND, market=None, instrument=None)))["run_id"])
    assert [_class(f) for f in rr.fills_of(unknown["run_id"])] == [(None, None, True)] * 2


def test_on_a_store_that_could_not_take_the_columns_the_answer_does_not_claim_them_either(acc, monkeypatch):
    """칸을 붙이지 못한 DB — 줄은 적히지만 '그때의 값'이라고 하지 않는다. 답의 새 줄도 ★적힌 것과 같은 말★을 한다."""
    monkeypatch.setattr(rr.schema_add_columns, "add_columns", lambda *a, **k: False)
    monkeypatch.setattr(rr, "_ready_for", None)                           # 이 DB 의 표를 다시 살핀다
    done = runner.advance("kim", acc, _start(acc)["run_id"])
    assert done["status"] == "finished" and done["signals"] == 2           # 가동은 그대로 돈다
    assert [_class(f) for f in rr.fills_of(done["run_id"])] == [(None, None, False)] * 2
    assert [_class(f) for f in done["new_fills"]] == [(None, None, False)] * 2


def test_a_run_pushed_to_the_end_writes_the_hand_computed_fills(acc):
    started = _start(acc)
    assert started["status"] == "running" and started["active"] is True and started["mode"] == "SHADOW" and started["feed"] == "replay"
    assert started["clock"] == {"total": 4, "done": 0, "next": "090000"} and started["new_fills"] == []
    done = runner.advance("kim", acc, started["run_id"])
    assert (done["status"], done["stop_reason"], done["active"]) == ("finished", "finished", False)
    assert done["stop_message"] == runner.STOPS["finished"] and done["ended_at"] is not None
    assert (done["last_bar"], done["bars"], done["signals"]) == ("090300", 4, 2)
    assert _rows(done["run_id"]) == [BUY, SELL]
    rows = rr.fills_of(done["run_id"])
    assert [r["event"] for r in rows] == ["entry_signal", "session_end"] and {r["kind"] for r in rows} == {"virtual"}
    assert {r["order_status"] for r in rows} == {"SHADOW_LOGGED"} and all(r["client_order_id"].startswith("CO-") for r in rows)
    assert [(f["seq"], f["side"]) for f in done["new_fills"]] == [(0, "buy"), (1, "sell")]      # 이번 부름에서 새로 적은 줄


def test_a_custom_rule_s_trial_replays_to_the_same_hand_computed_fills(acc):
    """직접 구성한 규칙(자유 조건식 f1)의 시행도 같은 길로 가동된다 — 설정은 시행 줄에서 읽고(`parts_of`), 시행 줄에 나무가 들어 있다."""
    crossing = {"entry": {"op": "cross_up", "args": [{"ind": "close"}, {"const": 10_050}]}}      # 종가가 10,050 을 상향 돌파
    setting = {"rule": {"kind": "custom", "params": templates.resolve("custom", crossing)}, "position": POSITION, "costs": COSTS}
    started = _start(acc, _trial(setting=setting))
    assert (started["rule_text"], started["rule_text_reason"]) == ("진입 조건: 종가 상향 돌파 10050", None)
    done = runner.advance("kim", acc, started["run_id"])
    assert done["status"] == "finished" and _rows(done["run_id"]) == [BUY, SELL] == _batch(setting, _day())
    assert [r["rule_text"] for r in runner.runs("kim", acc)] == ["진입 조건: 종가 상향 돌파 10050"]


def test_a_template_run_says_its_rule_in_words_and_an_unreadable_copy_says_why(acc):
    started = _start(acc)
    assert started["rule_text"].startswith("진입 조건: 종가 상향 돌파 시가 범위 고가(1분)") and started["rule_text_reason"] is None
    rr.update_run(started["run_id"], status="stopped", stop_reason="user", ended=True)
    broken = runner._view({"run_id": 0, "request": {"rule": {"kind": "macd_cross", "params": {}}}})
    assert broken["rule_text"] is None and broken["rule_text_reason"].endswith("니다.")
    assert runner._view({"run_id": 0, "request": None})["rule_text"] is None


def test_stepping_one_bar_at_a_time_writes_the_same_rows_and_no_exit_before_the_day_ends(acc):
    run_id = _start(acc)["run_id"]
    seen = []
    for done, label in enumerate(["090000", "090100", "090200"], start=1):
        view = runner.advance("kim", acc, run_id, 1)
        seen += view["new_fills"]
        assert (view["status"], view["last_bar"], view["bars"]) == ("running", label, done)
        assert view["clock"] == {"total": 4, "done": done, "next": ["090100", "090200", "090300"][done - 1]}
        assert "session_end" not in [f["event"] for f in rr.fills_of(run_id)]              # 하루가 끝나기 전에는 청산 줄이 없다
    assert [f["side"] for f in seen] == ["buy"]                                            # 09:02 봉에서 진입 줄 하나
    last = runner.advance("kim", acc, run_id, 1)                                           # 마지막 봉 — 하루가 끝난다
    assert last["status"] == "finished" and [f["event"] for f in last["new_fills"]] == ["session_end"]
    assert _rows(run_id) == [BUY, SELL]


@pytest.mark.parametrize("kind, params, prev_close", TEMPLATE_CASES, ids=[f"{k}-{i}" for i, (k, _, _) in enumerate(TEMPLATE_CASES)])
def test_every_template_replays_to_its_backtest_fills(acc, kind, params, prev_close):
    """★성질★ — 틀마다, 종목 둘(하나는 봉이 일찍 끝난다)의 하루를 재생으로 가동한 가상 체결이 그 하루를 한 번에 돌린 체결과 같다."""
    setting = _setting(kind, params, position={"stop_pct": 0.5, "target_pct": 0.8, "max_entries_per_ticker": 3, "max_open_positions": 1})
    key = _trial(tickers=("000660", "005930"), setting=setting)
    total = 0
    for seed in range(3):
        a = _random_session(seed, "000660", n=120)
        b = _drop(_random_session(seed + 50, "005930", n=120), range(90 + seed, 120))      # 이 종목의 봉은 일찍 끝난다
        if prev_close is not None:
            a, b = _with_prev(a, prev_close), _with_prev(b, prev_close)
        day = _day(a, b)
        done = runner.advance("kim", acc, _start(acc, key, day)["run_id"])
        assert done["status"] == "finished", (seed, done["stop_reason"], done["stop_message"])
        assert _rows(done["run_id"]) == _batch(setting, day), (kind, seed)
        assert {r["order_status"] for r in rr.fills_of(done["run_id"])} <= {"SHADOW_LOGGED"}
        total += done["signals"]
    assert total > 0, f"틀 {kind} 은 이 표본에서 체결을 하나도 내지 않았다 — 공허한 성질 시험이다"


def test_the_session_rules_reach_the_rule_as_they_do_in_the_backtest(acc):
    """장 운영 규칙(종가 단일가 구간의 진입 마감)이 가동에도 걸린다 — 15:19 의 신호는 15:20 에 들어가지 못한다.
    ★짝★: 규칙을 넘기지 않으면(읽지 못한 날) 그 마감은 없고, 백테스트도 그렇게 계산한다."""
    late = [("151800", 10_000, 10_020, 9_990, 10_000, 1_000), ("151900", 10_000, 10_060, 10_000, 10_060, 1_000),
            ("152000", 10_070, 10_100, 10_060, 10_090, 1_000), ("152100", 10_090, 10_120, 10_080, 10_110, 1_000)]
    key = _trial()
    blocked = runner.advance("kim", acc, runner.start("kim", acc, key, _day(sess(late)), session=RULES)["run_id"])
    assert blocked["status"] == "finished" and blocked["signals"] == 0 and rr.fills_of(blocked["run_id"]) == []
    free = runner.advance("kim", acc, runner.start("kim", acc, key, _day(sess(late)), session=None)["run_id"])
    assert [f["side"] for f in rr.fills_of(free["run_id"])] == ["buy", "sell"]


def test_the_run_keeps_a_copy_of_what_it_ran(acc):
    key = _trial()
    view = _start(acc, key)
    assert view["trial_key"] == key and view["day"] == DATE and view["tickers"] == ["005930"] and view["grade"] == "E3"
    assert view["request"] == {**_setting(), "tickers": ["005930"], "from": "2026-03-02", "to": "2026-03-13"}
    assert rr.run_of("kim", acc, view["run_id"])["request"] == view["request"]


# ── ② 실제 체결의 자리에 쓰지 않는다 · 신호는 전부 주문 경로를 지난다 ───────────────────────

def test_nothing_reaches_the_real_fills_table_or_the_broker_and_every_signal_is_one_shadow_order(acc):
    before = _count("live_fills")
    done = runner.advance("kim", acc, _start(acc)["run_id"])
    assert _count("live_fills") == before == 0
    assert kc.get_kis_client(account_id=acc).fills == [] and kc.get_kis_client(account_id=acc).orders == []    # 증권사로 0건
    orders = _orders(acc)
    assert [(o["status"], o["execution_mode"], o["signal_source"]) for o in orders] == [("SHADOW_LOGGED", "SHADOW", "rule_run")] * 2
    assert [(o["ticker"], o["side"], o["quantity"], o["price"], o["order_type"]) for o in orders] == [
        ("005930", "BUY", 99, 10_080.0, "MARKET"), ("005930", "SELL", 99, 10_100.0, "MARKET")]
    assert {str(o["strategy_id"]) for o in orders} == {str(done["run_id"])}                 # 가동 번호가 주문 줄과 가동을 잇는다
    assert [o["client_order_id"] for o in rr.fills_of(done["run_id"])] == _order_ids(acc)


def _order_ids(acc: str) -> list[str]:
    with dbmod.get_sync_engine().connect() as c:
        return [r[0] for r in c.execute(text("SELECT client_order_id FROM live_orders WHERE account_id = :a ORDER BY id"), {"a": acc})]


def test_the_audit_names_the_rule_and_who_armed_it(acc):
    runner.advance("kim", acc, _start(acc)["run_id"])
    rows = ae.get_account_executor(acc).audit.query(event_type="SIGNAL_RECEIVED")
    assert len(rows) == 2 and {r["actor"] for r in rows} == {"rule:kim"}


# ── ③ 비상 정지 ──────────────────────────────────────────────────────────────────────

def test_a_kill_switch_stops_the_run_at_the_next_bar_and_no_signal_goes_out(acc):
    run_id = _start(acc)["run_id"]
    runner.advance("kim", acc, run_id, 2)                                # 09:01 까지 — 다음 봉이 진입 봉이다
    _halt(acc)
    view = runner.advance("kim", acc, run_id)
    assert (view["status"], view["stop_reason"], view["active"]) == ("stopped", "kill_switch", False)
    assert view["stop_message"] == runner.STOPS["kill_switch"] and view["last_bar"] == "090100" and view["signals"] == 0
    assert rr.fills_of(run_id) == [] and _orders(acc) == []                # 멈춘 뒤에는 신호를 내지 않는다
    _refused("not_running", runner.advance, "kim", acc, run_id)


def test_a_run_does_not_start_under_a_kill_switch_and_runs_again_once_it_is_lifted(acc):
    key = _trial()
    _halt(acc)
    _refused("kill_switch_active", runner.start, "kim", acc, key, _day(), session=RULES)
    assert rr.runs_of("kim", acc) == []                                    # 거절은 아무것도 남기지 않는다
    ae.get_account_executor(acc).kill_switch.resolve("kim", "다시 시작")
    done = runner.advance("kim", acc, _start(acc, key)["run_id"])
    assert done["status"] == "finished" and _rows(done["run_id"]) == [BUY, SELL]


def test_a_signal_the_order_path_rejects_for_a_kill_switch_stops_the_run(acc, monkeypatch):
    """봉을 보기 전의 확인을 지나친 뒤에 정지가 걸린 경우 — 주문 경로의 답으로도 멈춘다. 거절된 신호의 줄은 그 답과 함께 남는다."""
    run_id = _start(acc)["run_id"]
    runner.advance("kim", acc, run_id, 2)
    ex = ae.get_account_executor(acc)
    states = iter([False, True])                                           # 가동기의 확인에는 꺼져 있고, 주문 경로가 볼 때는 켜져 있다
    monkeypatch.setattr(ex.kill_switch, "is_active", lambda: next(states, True))
    view = runner.advance("kim", acc, run_id)
    assert (view["status"], view["stop_reason"]) == ("stopped", "kill_switch")
    assert [(f["side"], f["order_status"], f["order_reason"]) for f in rr.fills_of(run_id)] == [("buy", "REJECTED", "kill_switch_active")]


def test_a_kill_switch_at_the_end_of_the_day_stops_the_run_without_a_closing_signal(acc, monkeypatch):
    """마지막 봉까지는 꺼져 있다가 하루를 끝맺을 때 걸려 있으면 — 강제 청산 신호를 내지 않고 멈춘다(끝난 것으로 적지 않는다)."""
    run_id = _start(acc)["run_id"]
    ex = ae.get_account_executor(acc)
    states = iter([False] * 5)                                             # 봉 넷의 확인 + 진입 신호 때 주문 경로의 확인
    monkeypatch.setattr(ex.kill_switch, "is_active", lambda: next(states, True))
    view = runner.advance("kim", acc, run_id)
    assert (view["status"], view["stop_reason"], view["last_bar"], view["bars"]) == ("stopped", "kill_switch", "090300", 4)
    assert _rows(run_id) == [BUY]


# ── ④ 봉이 끊기면 멈춘다 ────────────────────────────────────────────────────────────────

def _later(*minutes: int) -> list[tuple]:
    return [(f"09{m:02d}00", 10_110, 10_130, 10_100, 10_120, 1_000) for m in minutes]


def test_a_gap_in_the_bars_stops_the_run_before_the_stale_bar(acc):
    assert runner.GAP_MINUTES == 5
    day = _day(sess([*HAND, *_later(9, 10)]))                             # 09:03 다음 봉이 09:09 — 여섯 분
    view = runner.advance("kim", acc, _start(acc, day=day)["run_id"])
    assert (view["status"], view["stop_reason"], view["last_bar"]) == ("stopped", "feed_gap", "090300")
    assert view["stop_message"] == runner.STOPS["feed_gap"]
    assert _rows(view["run_id"]) == [BUY]                                  # 끊긴 뒤의 봉으로 돌지 않았고 · 없는 청산을 지어내지 않았다


def test_a_gap_of_exactly_the_limit_keeps_running(acc):
    """★짝★ — 늘 멈추는 구현을 배제한다. 다섯 분은 끊긴 것이 아니다."""
    day = _day(sess([*HAND, *_later(8, 9)]))                              # 09:03 다음 봉이 09:08
    view = runner.advance("kim", acc, _start(acc, day=day)["run_id"])
    assert view["status"] == "finished" and view["last_bar"] == "090900"
    assert _rows(view["run_id"]) == [BUY, ("005930", "sell", f"{DATE} 09:09:00", 99, 10_110.0)]


# ── ⑤ 남의 것은 없는 것과 같은 답 ────────────────────────────────────────────────────────

def test_someone_elses_run_account_and_trial_are_all_not_there(acc):
    key = _trial()
    run_id = _start(acc, key)["run_id"]
    for call in (runner.advance, runner.stop, runner.get):
        _refused("not_found", call, "lee", acc, run_id)                    # 남의 가동
        _refused("not_found", call, "kim", acc, run_id + 99)               # 없는 가동 — 같은 답
        _refused("not_found", call, "kim", _account("kim"), run_id)        # 내 다른 계좌의 번호도 아니다
    _refused("not_found", runner.start, "lee", acc, _trial("lee"), _day(), session=RULES)       # 남의 계좌에서는 시작하지 못한다
    _refused("no_trial", runner.start, "lee", _account("lee"), key, _day(), session=RULES)      # 남의 시행은 내 시행이 아니다
    assert runner.runs("lee", acc) == [] and [r["run_id"] for r in runner.runs("kim", acc)] == [run_id]
    assert runner.get("kim", acc, run_id)["status"] == "running"           # 그 사이 내 가동은 그대로다


# ── ⑥ 시행 없는 설정 · 운영의 합성 ───────────────────────────────────────────────────────

def test_a_setting_that_was_never_run_as_a_backtest_cannot_be_armed(acc):
    _refused("no_trial", runner.start, "kim", acc, "f" * 64, _day(), session=RULES)
    assert rr.runs_of("kim", acc) == [] and runner.active(acc) == [] and _orders(acc) == []


def test_production_refuses_synthetic_bars_and_synthetic_trials(acc, monkeypatch):
    monkeypatch.setattr(runner, "mock_allowed", lambda: False)
    _refused("synthetic_in_production", runner.start, "kim", acc, _trial(grade="E0"), _day(), session=RULES)       # 합성으로 돌린 시행
    _refused("synthetic_in_production", runner.start, "kim", acc, _trial(), _day(sess(HAND, source="synthetic")), session=RULES)
    assert rr.runs_of("kim", acc) == []


def test_mock_mode_arms_synthetic_bars_and_says_so(acc):
    """★짝★ — 모의 모드에서는 가동하고 등급을 합성(E0)으로 적는다. 등급은 ★그날 쓰인 봉★에서 온다(시행의 등급이 아니다)."""
    view = _start(acc, _trial(grade="E3"), _day(sess(HAND, source="synthetic")))
    assert view["grade"] == "E0" and view["status"] == "running"
    assert _start(acc, _trial(grade="E0", params={"minutes": 2}))["grade"] == "E3"


def test_a_setting_the_templates_no_longer_read_is_refused(acc):
    stale = {**_setting(), "rule": {"kind": "no_such_template", "params": {}}}
    _refused("bad_setting", runner.start, "kim", acc, _trial(setting=stale), _day(), session=RULES)


def test_the_day_must_be_the_trials_tickers_and_have_bars(acc):
    key = _trial()
    _refused("bad_day", runner.start, "kim", acc, key, _day(sess(HAND, ticker="000660")), session=RULES)     # 시행에 없는 종목
    refused = _refused("no_usable_bars", runner.start, "kim", acc, key, Day(DATE, {}, (("005930", "defects"),)), session=RULES)
    assert refused.extra["skipped"] == [{"ticker": "005930", "reason": "defects"}]                            # 왜 쓸 봉이 없는지
    assert rr.runs_of("kim", acc) == []


# ── ⑦ 재시작 ────────────────────────────────────────────────────────────────────────

def test_a_restart_turns_every_run_off_and_marks_what_was_running(acc):
    live = _start(acc)["run_id"]
    done = runner.advance("kim", acc, _start(acc, _trial(params={"minutes": 2}))["run_id"])["run_id"]
    runner.advance("kim", acc, live, 1)
    assert runner.active(acc) == [live]
    assert runner.reset() == 1                                             # 기동 때 부른다 — 돌던 가동 하나를 '중단됨'으로
    assert runner.active(acc) == []
    view = runner.get("kim", acc, live)
    assert (view["status"], view["stop_reason"], view["active"]) == ("interrupted", "interrupted", False)
    assert view["stop_message"] == rr.REASONS["interrupted"] and view["clock"] is None
    assert runner.get("kim", acc, done)["status"] == "finished"            # 끝난 가동은 그대로다
    _refused("not_running", runner.advance, "kim", acc, live)              # 되살리지 않는다 — 다시 켜는 것은 사람이 한다
    assert _orders(acc) == _orders(acc) and len(_orders(acc)) == 2         # 중단된 가동은 신호를 더 내지 않았다(끝난 가동의 둘뿐)


def test_a_run_left_running_without_a_process_is_read_as_interrupted(acc):
    """기동 때의 표시가 실패했더라도 — 메모리에 없는 '가동 중'은 가동 중이 아니다. 읽는 자리에서 바로잡는다."""
    run_id = _start(acc)["run_id"]
    runner._active.clear()                                                 # 프로세스가 죽었다(표시는 하지 못했다)
    assert rr.run_of("kim", acc, run_id)["status"] == "running"
    assert [r["status"] for r in runner.runs("kim", acc)] == ["interrupted"]
    assert rr.run_of("kim", acc, run_id)["status"] == "interrupted"


# ── ⑧ 모드 ──────────────────────────────────────────────────────────────────────────

def test_changing_the_mode_stops_the_run_and_sends_nothing(acc):
    run_id = _start(acc)["run_id"]
    runner.advance("kim", acc, run_id, 2)
    ae.get_account_executor(acc).set_mode("PAPER", actor="kim")
    view = runner.advance("kim", acc, run_id)
    assert (view["status"], view["stop_reason"]) == ("stopped", "mode_changed") and view["stop_message"] == runner.STOPS["mode_changed"]
    assert (view["last_bar"], view["bars"]) == ("090100", 2)               # 다음 봉을 보기 전에 멈췄다(신호를 기다리지 않는다)
    assert rr.fills_of(run_id) == [] and _orders(acc) == []
    assert kc.get_kis_client(account_id=acc).orders == []                  # 기록 전용으로 켠 가동이 모의투자 주문을 내지 않았다


def test_a_run_does_not_start_in_paper_mode_yet(acc):
    ae.get_account_executor(acc).set_mode("PAPER", actor="kim")
    _refused("mode_not_supported", runner.start, "kim", acc, _trial(), _day(), session=RULES)
    assert rr.runs_of("kim", acc) == []


def test_only_the_replay_feed_exists(acc):
    with pytest.raises(RunRefused) as caught:
        runner.start("kim", acc, _trial(), _day(), session=RULES, feed="polling")
    assert caught.value.code == "feed_not_supported"


# ── ⑨ 상한 · 이어지는 거절 · 기록 실패 · 주문 경로의 예외 ─────────────────────────────────

def test_an_account_runs_at_most_three_rules_at_once(acc):
    assert runner.MAX_RUNS_PER_ACCOUNT == 3
    keys = [_trial(params={"minutes": m}) for m in (1, 2, 3, 4)]
    ids = [_start(acc, k)["run_id"] for k in keys[:3]]
    refused = _refused("too_many_runs", runner.start, "kim", acc, keys[3], _day(), session=RULES)
    assert refused.extra == {"limit": 3}
    assert sorted(runner.active(acc)) == ids
    other = _account("kim")
    assert _start(other, keys[3])["status"] == "running"                   # 상한은 계좌마다다
    runner.stop("kim", acc, ids[0])
    assert _start(acc, keys[3])["status"] == "running"                     # 하나를 멈추면 자리가 난다


def test_a_trial_with_too_many_tickers_cannot_be_armed(acc):
    assert runner.MAX_RUN_TICKERS == 10
    names = [f"{n:06d}" for n in range(11)]
    refused = _refused("too_many_tickers", runner.start, "kim", acc, _trial(tickers=names), _day(), session=RULES)
    assert refused.extra == {"limit": 10, "tickers": 11}


BIG = {"position": {"amount": 40_000_000}, "costs": {"participation_cap": None}}      # 한 종목 4천만 원 — 전략 비중 한도(자산의 30%)를 넘는다


def test_three_rejections_in_a_row_stop_the_run(acc):
    names = ("000660", "005930", "035720")
    key = _trial(tickers=names, **BIG)
    view = runner.advance("kim", acc, _start(acc, key, _day(*(sess(HAND, ticker=t) for t in names)))["run_id"])
    assert (view["status"], view["stop_reason"], view["last_bar"]) == ("stopped", "risk_rejections", "090200")
    rows = rr.fills_of(view["run_id"])
    assert [(r["symbol"], r["order_status"], r["order_reason"]) for r in rows] == [(t, "REJECTED", "risk_check_failed") for t in names]
    assert runner.MAX_REJECTIONS == 3 and view["signals"] == 3


def test_two_rejections_then_an_accepted_signal_do_not_stop_the_run(acc):
    """★짝★ — 이어진 거절만 센다. 받아들여진 신호가 끼면 처음부터 다시 센다."""
    names = ("000660", "005930")
    key = _trial(tickers=names, **BIG)
    view = runner.advance("kim", acc, _start(acc, key, _day(*(sess(HAND, ticker=t) for t in names)))["run_id"])
    assert view["status"] == "finished"
    assert [r["order_status"] for r in rr.fills_of(view["run_id"])] == ["REJECTED", "REJECTED", "SHADOW_LOGGED", "SHADOW_LOGGED"]


def test_a_run_that_cannot_write_its_record_stops(acc, monkeypatch):
    run_id = _start(acc)["run_id"]
    monkeypatch.setattr(rr, "add_fill", lambda *a, **k: None)
    view = runner.advance("kim", acc, run_id)
    assert (view["status"], view["stop_reason"]) == ("stopped", "store_unavailable")
    assert view["stop_message"] == runner.STOPS["store_unavailable"] and view["last_bar"] == "090200"
    assert len(_orders(acc)) == 1                                          # 적지 못한 뒤로는 신호를 더 내지 않았다


class _Fake:
    """주문 경로의 대역 — 가동기가 보내는 신호를 그대로 붙든다."""

    def __init__(self, answer=None, boom: Exception | None = None, script: list[str] | None = None):
        self.state = SimpleNamespace(mode="SHADOW")
        self.kill_switch = SimpleNamespace(is_active=lambda: False)
        self.sent: list[tuple[dict, str]] = []
        self._answer, self._boom, self._script = answer, boom, list(script or [])

    def execute_signal(self, signal, account_state=None, regime_state=None, *, actor="system"):
        self.sent.append((dict(signal), actor))
        if self._boom is not None:
            raise self._boom
        if self._script:                                                   # 신호마다 차례대로 — "no" 는 위험 검사의 거절
            said = self._script.pop(0)
            return ({"client_order_id": f"CO-{len(self.sent)}", "status": "REJECTED", "reason": "risk_check_failed"} if said == "no"
                    else {"client_order_id": f"CO-{len(self.sent)}", "status": "SHADOW_LOGGED"})
        return self._answer or {"client_order_id": f"CO-{len(self.sent)}", "status": "SHADOW_LOGGED"}


def test_the_signal_is_the_fill_row_and_goes_out_only_through_execute_signal(acc, monkeypatch):
    fake = _Fake()
    monkeypatch.setattr(runner, "get_account_executor", lambda account_id: fake if account_id == acc else None)
    run_id = runner.advance("kim", acc, _start(acc)["run_id"])["run_id"]
    assert fake.sent == [
        ({"ticker": "005930", "side": "BUY", "quantity": 99, "price": 10_080.0, "order_type": "MARKET", "strategy_id": run_id,
          "source": "rule_run"}, "rule:kim"),
        ({"ticker": "005930", "side": "SELL", "quantity": 99, "price": 10_100.0, "order_type": "MARKET", "strategy_id": run_id,
          "source": "rule_run"}, "rule:kim")]


def test_a_mode_change_between_two_signals_of_one_bar_holds_the_second_back(acc, monkeypatch):
    """한 봉에서 신호가 둘 나올 때, 첫 신호 뒤에 모드가 바뀌면 둘째는 보내지 않는다(봉을 보기 전의 확인만으로는 막지 못한다)."""
    fake = _Fake()
    sent = fake.execute_signal

    def flip(signal, **kw):
        out = sent(signal, **kw)
        fake.state.mode = "PAPER"
        return out

    fake.execute_signal = flip
    monkeypatch.setattr(runner, "get_account_executor", lambda account_id: fake)
    names = ("000660", "005930")
    view = runner.advance("kim", acc, _start(acc, _trial(tickers=names), _day(*(sess(HAND, ticker=t) for t in names)))["run_id"])
    assert (view["status"], view["stop_reason"]) == ("stopped", "mode_changed")
    assert [s["ticker"] for s, _ in fake.sent] == ["000660"] and view["signals"] == 1


def test_an_accepted_signal_starts_the_count_of_rejections_again(acc, monkeypatch):
    """거절 · 거절 · 받음 · 거절 — 이어진 거절은 하나뿐이라 멈추지 않는다(지우지 않고 세면 셋이라 멈춘다)."""
    fake = _Fake(script=["no", "no", "ok", "no"])
    monkeypatch.setattr(runner, "get_account_executor", lambda account_id: fake)
    names = ("000660", "005930")
    view = runner.advance("kim", acc, _start(acc, _trial(tickers=names), _day(*(sess(HAND, ticker=t) for t in names)))["run_id"])
    assert view["status"] == "finished" and len(fake.sent) == 4
    assert [r["order_status"] for r in rr.fills_of(view["run_id"])] == ["REJECTED", "REJECTED", "SHADOW_LOGGED", "REJECTED"]


def test_a_kill_switch_seen_only_by_the_order_path_stops_the_run_at_once(acc, monkeypatch):
    """가동기의 확인에는 끝내 걸리지 않고 주문 경로만 정지를 본 경우 — 그 답 하나로 멈춘다(위험 검사의 거절처럼 세며 계속하지 않는다)."""
    fake = _Fake(answer={"client_order_id": "CO-k", "status": "REJECTED", "reason": "kill_switch_active"})
    monkeypatch.setattr(runner, "get_account_executor", lambda account_id: fake)
    view = runner.advance("kim", acc, _start(acc)["run_id"])
    assert (view["status"], view["stop_reason"], view["last_bar"]) == ("stopped", "kill_switch", "090200") and len(fake.sent) == 1


def test_a_run_that_cannot_write_its_progress_stops(acc, monkeypatch):
    """봉을 밀고도 어디까지 밀었는지 적지 못하면 멈춘다 — 기록과 다른 자리에서 계속 돌지 않는다."""
    run_id = _start(acc)["run_id"]
    real = rr.update_run
    monkeypatch.setattr(rr, "update_run", lambda rid, **kw: real(rid, **kw) if "status" in kw else None)
    view = runner.advance("kim", acc, run_id)
    assert (view["status"], view["stop_reason"]) == ("stopped", "store_unavailable")
    assert _orders(acc) == [] and rr.fills_of(run_id) == []                # 첫 봉에서 멈췄다 — 신호 전이다


def test_an_answer_that_is_not_a_shadow_record_stops_the_run(acc, monkeypatch):
    """기록 전용으로 켠 가동의 신호가 '보냈다'는 답을 받았다면 그 사이 모드가 바뀐 것이다 — 그 답을 적고 멈춘다."""
    fake = _Fake(answer={"client_order_id": "CO-x", "status": "SUBMITTED"})
    monkeypatch.setattr(runner, "get_account_executor", lambda account_id: fake)
    view = runner.advance("kim", acc, _start(acc)["run_id"])
    assert (view["status"], view["stop_reason"]) == ("stopped", "mode_changed") and len(fake.sent) == 1
    assert [(r["side"], r["order_status"]) for r in rr.fills_of(view["run_id"])] == [("buy", "SUBMITTED")]


def test_an_order_path_that_raises_stops_the_run_and_does_not_leak_the_error_text(acc, monkeypatch):
    fake = _Fake(boom=RuntimeError("appkey=PSkey-0123456789abcdef"))
    monkeypatch.setattr(runner, "get_account_executor", lambda account_id: fake)
    view = runner.advance("kim", acc, _start(acc)["run_id"])
    assert (view["status"], view["stop_reason"]) == ("stopped", "order_error") and len(fake.sent) == 1
    assert "PSkey" not in view["stop_message"] and "RuntimeError" in view["stop_message"]
    assert rr.fills_of(view["run_id"]) == []


# ── 걸음 수 · 정지 · 읽기 ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bars", [0, -1, True, "3", 1.5])
def test_the_number_of_bars_must_be_a_positive_integer(acc, bars):
    run_id = _start(acc)["run_id"]
    _refused("bad_bars", runner.advance, "kim", acc, run_id, bars)
    assert runner.get("kim", acc, run_id)["bars"] == 0


def test_stopping_is_the_users_and_leaves_the_position_as_it_is(acc):
    run_id = _start(acc)["run_id"]
    runner.advance("kim", acc, run_id, 3)                                  # 09:02 — 들어간 뒤
    view = runner.stop("kim", acc, run_id)
    assert (view["status"], view["stop_reason"], view["active"]) == ("stopped", "user", False)
    assert view["stop_message"] == runner.STOPS["user"] and _rows(run_id) == [BUY]      # 없는 청산을 지어내지 않는다
    assert runner.stop("kim", acc, run_id)["stop_reason"] == "user"        # 두 번 눌러도 같다
    _refused("not_running", runner.advance, "kim", acc, run_id)
    done = runner.advance("kim", acc, _start(acc)["run_id"])
    assert runner.stop("kim", acc, done["run_id"])["status"] == "finished"   # 끝난 가동을 '정지'로 바꾸지 않는다


def test_reading_a_run_gives_its_fills_and_the_list_is_newest_first(acc):
    first = runner.advance("kim", acc, _start(acc)["run_id"])["run_id"]
    second = _start(acc, _trial(params={"minutes": 2}))["run_id"]
    got = runner.get("kim", acc, first)
    assert [(f["side"], f["kind"]) for f in got["fills"]] == [("buy", "virtual"), ("sell", "virtual")] and got["new_fills"] == []
    listed = runner.runs("kim", acc)
    assert [(r["run_id"], r["status"], r["active"]) for r in listed] == [(second, "running", True), (first, "finished", False)]
    assert all("fills" not in r for r in listed)


def test_an_unreadable_store_is_not_an_empty_answer(acc, monkeypatch):
    run_id = _start(acc)["run_id"]
    monkeypatch.setattr(rr, "run_of", lambda *a, **k: None)
    monkeypatch.setattr(rr, "runs_of", lambda *a, **k: None)
    for call, args in ((runner.get, (run_id,)), (runner.advance, (run_id,)), (runner.stop, (run_id,)), (runner.runs, ())):
        _refused("store_unavailable", call, "kim", acc, *args)
    monkeypatch.setattr(trials, "trial_of", lambda *a, **k: None)
    _refused("store_unavailable", runner.start, "kim", acc, "a" * 64, _day(), session=RULES)


# ── ⑩ 주문 경로를 새로 만들지 않는다 ──────────────────────────────────────────────────────

def test_the_runner_builds_no_order_path_of_its_own():
    source = Path(runner.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert not [m for m in imported if m and m.startswith("src.api")], "가동기가 문(API) 층을 들여온다"
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    banned = {"OrderExecutor", "TradingEngine", "KISClient", "MockKISClient", "get_kis_client", "place_order", "cancel_order",
              "set_mode", "kis"}
    assert not names & banned, names & banned
    calls = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert "execute_signal" in calls and "get_account_executor" in names
    assert "live_fills" not in source.replace("`live_fills`", "")


def test_every_stop_and_refusal_has_a_sentence():
    assert set(runner.STOPS) >= {"user", "kill_switch", "risk_rejections", "feed_gap", "not_monotone", "mode_changed", "finished",
                                 "store_unavailable", "order_error"}
    for table in (runner.STOPS, runner.REASONS):
        assert all(isinstance(v, str) and v.endswith(".") for v in table.values()), table
