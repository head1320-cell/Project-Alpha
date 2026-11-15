"""규칙 가동의 관제 (W5c · 구현 계획 2026-11-15) — `GET …/rule-runs/{run_id}/monitor`

관제는 ★읽기만★ 한다. 가동기의 뜻(`tests/test_rule_runner.py`)과 문의 약속(`tests/test_rule_run_routes.py`)은 다시 걸지 않는다. 여기서 거는 것:

  · 로그인 · ★본인 계좌만★ · 등록부에 올라 있다
  · 실현손익은 매매일지 엔진이다 — 손 계산과 같고, 분봉 백테스트의 문이 낸 값과 같다
  · 주문은 ★주문 기록★에서 센다 — 거절은 문장과 함께 · 기록에 없는 신호를 센다 · 못 읽으면 열화하고 그렇게 적는다
  · 거절된 신호의 가상 체결도 손익에 든다 — 그 수를 함께 적는다(거절이 없었다고도, 거절 뒤의 세계도 지어내지 않는다)
  · 한도까지 남은 폭은 시뮬레이터의 판정과 같은 값이다(비용 전 실현손익 · 한 번 닿으면 닿은 것)
  · "그날의 백테스트와 같다"는 다시 계산해 본 ★관측★이다 — 다르면 다르다고, 못 보면 모른다고, 끝까지 돌지 않았으면 견주지 않는다고
  · 값이 없으면 0 이 아니라 사유 · ★관제는 아무것도 쓰지 않는다★
"""
from __future__ import annotations

import ast
import datetime as dt
import json
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import inspect, text

import src.data.rule_runs as rr
import src.database as dbmod
import src.execution.account_executors as ae
import src.execution.rule_monitor as monitor
from src.api.protected_routes import PROTECTED, REQUIRE_LOGIN
from src.data.market_rules import sell_tax_bp_on
from src.engine.intraday import NOT_MODELED, Day, Session
from src.engine.intraday import rules as templates
from src.engine.intraday.simulator import CostAssumptions, PositionRules, simulate
from src.execution.account_executors import get_account_executor
from tests.route_walk import flat_routes
from tests.test_intraday_simulator import R0, R1, R2, RULES, one_day, sess
from tests.test_rule_run_routes import (  # noqa: F401 — 고정물은 이름으로 들여와야 쓰인다
    BASE,
    BODY,
    DAY,
    SIM,
    _auth,
    _start,
    client,
    hand_made_day,
    with_days,
)

MON = BASE + "/{account_id}/rule-runs/{run_id}/monitor"
#: 한 종목 4천만 원 — 전략 비중 한도를 넘어 위험 검사가 매수를 거절한다(매도는 받는다). `tests/test_rule_runner.py` 의 BIG 과 같은 길.
BIG = {**BODY, "position": {"amount": 40_000_000}, "costs": {"commission_bp": 1.5, "slippage_ticks": 1, "participation_cap": None}}
#: 손실로 끝나는 하루: 09:02 에 99주 @10,080 → 하루 끝 09:03 종가 10,010 − 한 틱 = 10,000 → (10,000 − 10,080) × 99 = −7,920원.
LOSING = [R0, R1, R2, ("090300", 10_090, 10_090, 10_000, 10_010, 1_000)]
#: 문 시험의 손 계산 하루(`hand_made_day`)와 같은 봉 — 시장 · 상품만 바꿔 짓는 데 쓴다.
WINNING = [R0, R1, R2, ("090300", 10_090, 10_120, 10_080, 10_110, 1_000)]
RECORDED = {"basis": "recorded", "reason": None}


def _day_of(rows, ticker="005930", source="kis", market="KOSPI", instrument="stock") -> list[Day]:
    t, o, h, low, c, v = zip(*rows, strict=True)
    s = Session(ticker, DAY, np.array(t), np.array(o, float), np.array(h, float), np.array(low, float), np.array(c, float),
                np.array(v, float), source, None, market, instrument, "삼성전자")
    return [Day(DAY, {ticker: s})]


def _connect(client, user="alice", account_no="50123456") -> str:
    res = client.post(BASE, json=dict(label="내 계좌", app_key="PSkey-0123456789abcdef", app_secret="secret-0123456789abcdefghijklmnop",
                                      account_no=account_no, is_paper=True), headers=_auth(client, user))
    assert res.status_code == 201, res.text
    return res.json()["account_id"]


def _backtest(client, body=None, user="alice") -> tuple[str, dict]:
    """분봉 백테스트를 한 번 돌린다 → (시행 열쇠, 그 답의 매매일지)."""
    h = _auth(client, user)
    res = client.post(SIM, json=body or BODY, headers=h)
    assert res.status_code == 200, res.text
    return client.get("/api/v1/intraday/trials", headers=h).json()["trials"][0]["trial_key"], res.json()["journal"]


def _advance(client, acc, run_id, bars=None, user="alice") -> dict:
    res = client.post(f"{BASE}/{acc}/rule-runs/{run_id}/advance", json={} if bars is None else {"bars": bars}, headers=_auth(client, user))
    assert res.status_code == 200, res.text
    return res.json()["run"]


def _run(client, acc, key, bars=None, user="alice") -> int:
    """가동을 열고 `bars` 개(없으면 끝까지) 민다 → 가동 번호."""
    made = _start(client, acc, key, user)
    assert made.status_code == 201, made.text
    run_id = made.json()["run"]["run_id"]
    _advance(client, acc, run_id, bars, user)
    return run_id


def _get(client, acc, run_id, user="alice"):
    return client.get(f"{BASE}/{acc}/rule-runs/{run_id}/monitor", headers=_auth(client, user))


def _monitor(client, acc, run_id) -> dict:
    res = _get(client, acc, run_id)
    assert res.status_code == 200, res.text
    return res.json()["monitor"]


@pytest.fixture()
def known_master(monkeypatch):
    """종목 마스터가 이 종목을 안다(코스피 · 주식). 시험 환경의 기본 마스터는 시장을 모른다.

    가동의 체결 줄은 ★그때의★ 시장 · 상품을 갖고 있어 관제는 이 마스터에 기대지 않는다 — 이 고정물은 그 칸이 생기기 전에 적힌 줄
    (읽는 때의 마스터로 정한다)을 볼 때만 쓴다."""
    import src.api.intraday_routes as mod
    monkeypatch.setattr(mod, "master_lookup", lambda: lambda _symbol: {"market": "KOSPI", "group_code": "ST", "name": "삼성전자"})


def _forget_classes(run_id: int, seq: int | None = None) -> None:
    """그 가동의 줄(또는 한 줄)을 시장 · 상품 칸이 생기기 전에 적힌 줄처럼 만든다."""
    where, args = ("run_id = :r", {"r": run_id}) if seq is None else ("run_id = :r AND seq = :s", {"r": run_id, "s": seq})
    with dbmod.get_sync_engine().begin() as c:
        assert c.execute(text(f"UPDATE rule_run_fills SET market = NULL, instrument = NULL, classified = NULL WHERE {where}"), args).rowcount


def _table_rows() -> dict[str, int]:
    engine = dbmod.get_sync_engine()
    with engine.connect() as c:
        return {t: int(c.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar()) for t in inspect(engine).get_table_names()}


# ── 문 ─────────────────────────────────────────────────────────────────────────────

def test_the_monitor_is_mounted_login_only_and_on_the_access_map(client):
    table = {(m, r.path) for r in flat_routes(client.app) for m in (getattr(r, "methods", None) or [])}
    assert ("GET", MON) in table and PROTECTED[("GET", MON)][0] == REQUIRE_LOGIN
    acc = _connect(client)
    run_id = _run(client, acc, _backtest(client)[0])
    assert client.get(f"{BASE}/{acc}/rule-runs/{run_id}/monitor").status_code == 401
    access = Path("frontend/src/entities/session/accessMap.json").read_text(encoding="utf-8")
    assert f"GET {MON}" in json.dumps(json.loads(access), ensure_ascii=False)


def test_someone_elses_account_and_a_run_of_another_account_are_both_404(client):
    acc = _connect(client)
    run_id = _run(client, acc, _backtest(client)[0])
    assert _get(client, acc, run_id, "bob").status_code == 404
    mine_too = _connect(client, account_no="50123457")
    # 소유 확인이 ★먼저★다 — 남의 계좌의 실행기를 띄우지도 않는다(가동기도 한 번 더 보지만, 그 전에 문이 계좌의 상태를 읽는다).
    assert _get(client, mine_too, run_id, "bob").status_code == 404 and mine_too not in ae._executors
    assert _get(client, mine_too, run_id).status_code == 404            # 내 계좌지만 그 계좌의 가동이 아니다
    assert mine_too in ae._executors                                    # ★짝★ — 주인이 읽으면 그 계좌의 상태를 읽는다
    assert _get(client, acc, run_id + 999).status_code == 404
    assert _get(client, acc, run_id).status_code == 200                 # ★짝★ — 내 계좌의 내 가동은 읽힌다


# ── 끝까지 돈 가동 = 손 계산 = 그날의 백테스트 ──────────────────────────────────────────

def test_a_finished_run_shows_the_hand_computed_day_and_the_backtests_own_numbers(client):
    """시험 환경의 종목 마스터는 시장을 모른다 — 그래도 관제의 비용은 그날의 백테스트와 같다(시장 · 상품은 체결 줄에 적혀 있다)."""
    acc = _connect(client)
    key, backtest = _backtest(client)
    run_id = _run(client, acc, key)
    body = _get(client, acc, run_id).json()
    assert (body["mode"], body["kill_switch"], body["gate"]) == ("SHADOW", False, {"mock": True})
    assert (body["run"]["status"], body["run"]["active"], len(body["run"]["fills"])) == ("finished", False, 2)
    assert [(f["market"], f["instrument"], f["classified"]) for f in body["run"]["fills"]] == [("KOSPI", "stock", True)] * 2
    m = body["monitor"]
    assert m["orders"] == {"basis": "order_log", "reason": None, "signals": 2, "by_status": {"SHADOW_LOGGED": 2}, "rejected": [], "unrecorded": 0}
    assert m["fills"] == {"virtual": 2, "broker": 0, "broker_reason": None}

    pnl = m["pnl"]
    assert (pnl["available"], pnl["reason"], pnl["closed_trades"], pnl["open_positions"], pnl["includes_rejected"]) == (True, None, 1, 0, 0)
    assert pnl["gross"] == 1_980.0                                       # (10,100 − 10,080) × 99 — 손 계산
    tax_bp = sell_tax_bp_on(dt.date(2026, 3, 4), "KOSPI", "stock")["bp"]
    cost = (99 * 10_080 + 99 * 10_100) * 1.5 / 10_000 + 99 * 10_100 * tax_bp / 10_000
    assert pnl["cost"] == pytest.approx(cost) and pnl["net"] == pytest.approx(1_980.0 - cost) and pnl["net_reason"] is None
    assert pnl["gross"] == backtest["summary"]["gross"]["total"]          # 그날의 백테스트가 낸 값과 같다
    assert pnl["net"] == pytest.approx(backtest["summary"]["net"]["total"])
    assert pnl["basis"] == backtest["basis"]                              # 무엇이 관측 · 추론 · 가정인지도 같다
    assert pnl["classification"] == RECORDED                              # 시장 · 상품은 가동 때 적힌 값이다

    assert m["backtest"] == {"state": "same", "reason": monitor.BACKTEST["same"], "run_fills": 2, "backtest_fills": 2}
    assert m["loss_limit"] == {"limit": None, "reason": monitor.REASONS["no_loss_limit"], "realized_gross": 1_980.0, "room": None, "touched": None}
    assert m["kill"] == {"active": False, "own": False}
    assert m["feed"] == {"kind": "replay", "lag_seconds": None, "lag_reason": monitor.REASONS["replay_has_no_lag"]}
    journal = m["journal"]                                                # 하루가 끝났다 — 매매일지 전체
    assert (journal["trades_total"], journal["summary"]["gross"]["total"]) == (1, 1_980.0)
    assert journal["not_covered"] == list(NOT_MODELED)                    # 올린 파일의 이야기가 아니라 시뮬레이션의 한계를 적는다


def test_a_master_that_changes_after_the_run_does_not_move_the_net(client, monkeypatch):
    """가동 때의 시장 · 상품은 줄에 적혀 있다 — 뒤에 종목 마스터가 다른 말을 해도 지난 가동의 비용 뒤 손익은 움직이지 않는다."""
    acc = _connect(client)
    key, backtest = _backtest(client)
    run_id = _run(client, acc, key)
    before = _monitor(client, acc, run_id)["pnl"]
    import src.api.intraday_routes as mod
    etf = {"market": "KOSDAQ", "group_code": "EF", "name": "다른 이름"}
    assert sell_tax_bp_on(dt.date(2026, 3, 4), "KOSDAQ", "etf")["bp"] != sell_tax_bp_on(dt.date(2026, 3, 4), "KOSPI", "stock")["bp"]   # 마스터를 믿으면 달라질 값
    monkeypatch.setattr(mod, "master_lookup", lambda: lambda _symbol: etf)
    after = _monitor(client, acc, run_id)
    assert after["pnl"]["net"] == before["net"] == pytest.approx(backtest["summary"]["net"]["total"])
    assert after["pnl"]["cost"] == before["cost"] and after["pnl"]["basis"] == before["basis"]
    assert after["pnl"]["classification"] == RECORDED
    assert after["journal"]["trades"][0]["name"] == "다른 이름"            # 이름은 지금의 마스터에서 읽는다(표시일 뿐 — 값에 닿지 않는다)


def test_rows_written_before_the_columns_are_classified_by_todays_master_and_the_monitor_says_so(client, known_master):
    """★짝★ — 그때의 시장 · 상품이 적히지 않은 옛 줄은 지어내지 않는다: 읽는 때의 마스터로 정하고 그렇게 적는다."""
    acc = _connect(client)
    key, backtest = _backtest(client)
    run_id = _run(client, acc, key)
    at_read = {"basis": "read_time_master", "reason": monitor.REASONS["classified_at_read"]}
    _forget_classes(run_id, seq=0)                                        # 한 줄만 미기록이어도 가동 전체가 그렇다(한 가동에 두 기준을 섞지 않는다)
    assert _monitor(client, acc, run_id)["pnl"]["classification"] == at_read
    _forget_classes(run_id)
    pnl = _monitor(client, acc, run_id)["pnl"]
    assert pnl["classification"] == at_read
    assert pnl["net"] == pytest.approx(backtest["summary"]["net"]["total"])   # 지금의 마스터가 안다 — 그 값으로 센다


def test_old_rows_and_a_master_that_does_not_know_leave_the_net_without_a_value(client):
    acc = _connect(client)
    run_id = _run(client, acc, _backtest(client)[0])
    _forget_classes(run_id)
    pnl = _monitor(client, acc, run_id)["pnl"]
    assert (pnl["gross"], pnl["net"], pnl["net_reason"]) == (1_980.0, None, monitor.REASONS["cost_unknown"])
    assert pnl["classification"] == {"basis": "read_time_master", "reason": monitor.REASONS["classified_at_read"]}


def test_a_running_run_counts_what_closed_and_never_values_what_is_still_open(client):
    acc = _connect(client)
    made = _start(client, acc, _backtest(client)[0])
    run_id = made.json()["run"]["run_id"]
    empty = _monitor(client, acc, run_id)                                 # 아직 한 봉도 밀지 않았다
    assert (empty["orders"]["signals"], empty["orders"]["by_status"], empty["fills"]["virtual"]) == (0, {}, 0)
    assert (empty["pnl"]["available"], empty["pnl"]["gross"], empty["pnl"]["closed_trades"], empty["pnl"]["open_positions"]) == (True, 0.0, 0, 0)

    _advance(client, acc, run_id, 3)                                      # 09:02 의 매수까지
    body = _get(client, acc, run_id).json()
    m = body["monitor"]
    assert (body["run"]["active"], body["run"]["clock"]["done"]) == (True, 3)
    assert m["orders"]["by_status"] == {"SHADOW_LOGGED": 1} and m["fills"]["virtual"] == 1
    assert (m["pnl"]["gross"], m["pnl"]["closed_trades"], m["pnl"]["open_positions"]) == (0.0, 0, 1)      # 든 채로는 손익이 아니다
    assert m["journal"] is None                                           # 하루가 끝나지 않았다
    assert m["backtest"] == {"state": "not_compared", "reason": monitor.BACKTEST["running"], "run_fills": 1, "backtest_fills": None}


def test_a_stopped_run_is_not_compared_with_the_backtest_and_its_journal_keeps_the_open_position(client):
    acc = _connect(client)
    run_id = _run(client, acc, _backtest(client)[0], bars=3)
    assert client.post(f"{BASE}/{acc}/rule-runs/{run_id}/stop", json={}, headers=_auth(client, "alice")).status_code == 200
    m = _monitor(client, acc, run_id)
    assert m["backtest"] == {"state": "not_compared", "reason": monitor.BACKTEST["stopped"], "run_fills": 1, "backtest_fills": None}
    assert m["journal"]["trades_total"] == 0 and len(m["journal"]["open_positions"]) == 1     # 없는 청산을 지어내지 않는다
    assert (m["pnl"]["gross"], m["pnl"]["open_positions"]) == (0.0, 1)


# ── 주문 — 주문 기록에서 센다 ───────────────────────────────────────────────────────────

def test_a_rejected_signal_is_counted_with_the_order_paths_own_sentence(client):
    acc = _connect(client)
    run_id = _run(client, acc, _backtest(client, BIG)[0])
    body = _get(client, acc, run_id).json()
    m = body["monitor"]
    assert body["run"]["status"] == "finished"
    assert (m["orders"]["signals"], m["orders"]["by_status"], m["orders"]["unrecorded"]) == (2, {"REJECTED": 1, "SHADOW_LOGGED": 1}, 0)
    [refused] = m["orders"]["rejected"]
    assert (refused["seq"], refused["executed_at"], refused["symbol"], refused["side"], refused["quantity"], refused["reason_code"]) == (
        0, f"{DAY} 09:02:00", "005930", "buy", 3_968, "risk_check_failed")
    logged = get_account_executor(acc).list_orders(status="REJECTED")[0]["error_message"]
    assert logged and refused["message"] == logged                        # 위험 검사가 한 말 그대로(주문 기록의 것)
    # 가상 체결은 시뮬레이터가 계산한 것이다 — 거절된 신호의 체결도 손익에 들고, 그 수를 적는다.
    assert (m["pnl"]["gross"], m["pnl"]["includes_rejected"]) == ((10_100 - 10_080) * 3_968, 1)


def test_a_signal_missing_from_the_order_log_is_counted_not_hidden(client):
    acc = _connect(client)
    run_id = _run(client, acc, _backtest(client)[0])
    assert _monitor(client, acc, run_id)["orders"]["unrecorded"] == 0     # ★짝★
    lost = rr.fills_of(run_id)[0]["client_order_id"]
    with dbmod.get_sync_engine().begin() as c:
        assert c.execute(text("DELETE FROM live_orders WHERE client_order_id = :coid"), {"coid": lost}).rowcount == 1
    orders = _monitor(client, acc, run_id)["orders"]
    assert (orders["basis"], orders["signals"], orders["unrecorded"]) == ("order_log", 2, 1)
    assert orders["by_status"] == {"SHADOW_LOGGED": 2}                    # 기록에 없는 신호는 가동 기록의 답으로 센다


def test_orders_of_another_source_with_the_same_number_are_not_mixed_in(client):
    """주문 기록의 `strategy_id` 는 가동 번호와 겹칠 수 있다(손으로 낸 주문 · 다른 전략). 가동의 주문 번호로만 잇는다."""
    acc = _connect(client)
    run_id = _run(client, acc, _backtest(client)[0])
    get_account_executor(acc).execute_signal({"ticker": "000660", "side": "BUY", "quantity": 1, "price": 100_000.0, "order_type": "MARKET",
                                              "strategy_id": run_id, "source": "manual"}, actor="alice")
    assert len(get_account_executor(acc).list_orders(strategy_id=run_id)) == 3
    orders = _monitor(client, acc, run_id)["orders"]
    assert (orders["signals"], orders["by_status"], orders["unrecorded"]) == (2, {"SHADOW_LOGGED": 2}, 0)


def test_the_order_logs_current_status_and_its_broker_fills_are_what_is_counted(client):
    """상태는 주문 기록의 ★지금 값★이다(가동 기록에 적힌 것은 신호를 낸 순간의 답) · 증권사 체결은 주문 기록의 체결 수량으로 센다."""
    acc = _connect(client)
    run_id = _run(client, acc, _backtest(client)[0])
    first = rr.fills_of(run_id)[0]["client_order_id"]
    with dbmod.get_sync_engine().begin() as c:
        assert c.execute(text("UPDATE live_orders SET status = 'FILLED', filled_quantity = 99 WHERE client_order_id = :coid"),
                         {"coid": first}).rowcount == 1
    m = _monitor(client, acc, run_id)
    assert m["orders"]["by_status"] == {"FILLED": 1, "SHADOW_LOGGED": 1}
    assert m["fills"] == {"virtual": 2, "broker": 1, "broker_reason": None}


def test_an_unreadable_order_log_degrades_to_the_runs_own_record_and_says_so(client, monkeypatch):
    acc = _connect(client)
    run_id = _run(client, acc, _backtest(client, BIG)[0])

    def down(**_kw):
        raise RuntimeError("db down")
    monkeypatch.setattr(get_account_executor(acc), "list_orders", down)
    m = _monitor(client, acc, run_id)
    assert (m["orders"]["basis"], m["orders"]["reason"]) == ("run_record", monitor.REASONS["order_log_unavailable"])
    assert (m["orders"]["by_status"], m["orders"]["unrecorded"]) == ({"REJECTED": 1, "SHADOW_LOGGED": 1}, None)     # 모른다 ≠ 0
    assert [(r["reason_code"], r["message"]) for r in m["orders"]["rejected"]] == [("risk_check_failed", None)]
    assert m["fills"] == {"virtual": 2, "broker": None, "broker_reason": monitor.REASONS["order_log_unavailable"]}
    assert m["pnl"]["available"] is True                                  # 손익은 가상 체결에서 — 주문 기록과 무관하다


# ── 일 손실 한도까지 남은 폭 ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("limit", "room", "touched"), [(5_000, -2_920.0, True), (7_920, 0.0, True), (20_000, 12_080.0, False)])
def test_the_room_to_the_daily_loss_limit_is_the_rules_own_limit_plus_the_gross_realised_pnl(client, monkeypatch, limit, room, touched):
    with_days(monkeypatch, _day_of(LOSING))
    acc = _connect(client)
    run_id = _run(client, acc, _backtest(client, {**BODY, "position": {"amount": 1_000_000, "daily_loss_limit": limit}})[0])
    m = _monitor(client, acc, run_id)
    assert m["pnl"]["gross"] == -7_920.0                                  # (10,000 − 10,080) × 99
    assert m["loss_limit"] == {"limit": float(limit), "reason": None, "realized_gross": -7_920.0, "room": room, "touched": touched}


def _fill(clock: str, symbol: str, side: str, quantity: int, price: float) -> dict:
    return {"executed_at": f"{DAY} {clock}:00", "symbol": symbol, "side": side, "quantity": quantity, "price": price}


def test_touching_the_limit_is_remembered_after_a_later_exit_recovers_the_loss():
    """한도는 한 번 닿으면 그날 새 진입이 없다 — 뒤의 청산으로 누계가 회복돼도 '닿았다'는 남는다."""
    rows = [_fill("09:01", "005930", "buy", 100, 10_000.0), _fill("09:01", "000660", "buy", 100, 10_000.0),
            _fill("09:02", "005930", "sell", 100, 9_900.0),              # −10,000 — 한도 5,000 에 닿는다
            _fill("09:03", "000660", "sell", 100, 10_200.0)]             # +20,000 — 누계는 +10,000 으로 회복
    assert monitor.loss_limit(rows, 5_000.0) == {"limit": 5_000.0, "reason": None, "realized_gross": 10_000.0, "room": 15_000.0, "touched": True}
    assert monitor.loss_limit(rows, 10_001.0)["touched"] is False        # ★짝★ — 닿지 않은 한도
    assert monitor.loss_limit(rows, None) == {"limit": None, "reason": monitor.REASONS["no_loss_limit"], "realized_gross": 10_000.0,
                                              "room": None, "touched": None}


def test_a_partial_exit_counts_towards_the_limit_before_the_position_is_closed():
    rows = [_fill("09:01", "005930", "buy", 100, 10_000.0), _fill("09:02", "005930", "sell", 50, 9_900.0)]     # 절반만 팔았다: −5,000
    assert monitor.loss_limit(rows, 5_000.0) == {"limit": 5_000.0, "reason": None, "realized_gross": -5_000.0, "room": 0.0, "touched": True}
    assert monitor.loss_limit(rows[:1], 5_000.0) == {"limit": 5_000.0, "reason": None, "realized_gross": 0.0, "room": 5_000.0, "touched": False}


def _virtual(clock: str, symbol: str, side: str, quantity: int, price: float) -> dict:
    return {**_fill(clock, symbol, side, quantity, price), "order_status": "SHADOW_LOGGED"}


def test_pnl_counts_the_realised_part_of_a_partial_exit_and_withholds_the_net_when_any_cost_is_unknown():
    assumed = CostAssumptions(commission_bp=1.5, unknown_market="KOSPI", unknown_instrument="stock")
    half = [_virtual("09:01", "005930", "buy", 100, 10_000.0), _virtual("09:02", "005930", "sell", 50, 9_900.0)]     # 절반만 팔았다
    pnl, journal = monitor.pnl_of(half, assumed, None)
    assert (pnl["gross"], pnl["closed_trades"], pnl["open_positions"]) == (-5_000.0, 0, 1)       # 일부 청산한 몫도 실현손익이다
    assert pnl["gross"] == monitor.loss_limit(half, 5_000.0)["realized_gross"]                  # 한도가 보는 값과 같다
    assert pnl["net"] is not None and pnl["net"] < pnl["gross"] and pnl["cost"] == pytest.approx(pnl["gross"] - pnl["net"])
    assert journal["summary"]["gross"]["total"] == 0.0 and journal["summary"]["open_realized"]["gross"] == -5_000.0

    def only_samsung(symbol: str) -> dict | None:
        return {"market": "KOSPI", "group_code": "ST"} if symbol == "005930" else None
    plain = CostAssumptions(commission_bp=1.5)
    closed = [_virtual("09:01", "005930", "buy", 10, 10_000.0), _virtual("09:02", "005930", "sell", 10, 10_100.0)]
    other = [_virtual("09:03", "000660", "buy", 10, 20_000.0), _virtual("09:04", "000660", "sell", 10, 20_100.0)]
    assert monitor.pnl_of(closed, plain, only_samsung)[0]["net"] is not None                    # ★짝★ — 전부 알면 값이 있다
    mixed = monitor.pnl_of(closed + other, plain, only_samsung)[0]                              # 한 거래의 매도세를 모른다
    assert (mixed["gross"], mixed["net"], mixed["cost"], mixed["net_reason"]) == (2_000.0, None, None, monitor.REASONS["cost_unknown"])
    partial = monitor.pnl_of(closed + other[:1] + [_virtual("09:04", "000660", "sell", 5, 20_100.0)], plain, only_samsung)[0]
    assert (partial["gross"], partial["net"], partial["net_reason"]) == (1_500.0, None, monitor.REASONS["cost_unknown"])     # 일부 청산의 비용을 모른다


@pytest.mark.parametrize(("limit", "blocked", "touched"), [
    (3_000, True, True), (6_930, True, True),          # 005930 의 손절(−6,930원)이 한도에 닿아 000660 의 진입이 막힌다
    (6_931, False, True), (14_280, False, True),       # 그때는 안 닿아 000660 이 들어가고, 그 청산(−7,350원)으로 누계 −14,280원이 닿는다
    (14_281, False, False), (50_000, False, False)])   # 끝까지 닿지 않는다
def test_touched_is_the_simulators_own_running_total(limit, blocked, touched):
    """★같은 값★ — 시뮬레이터는 누계가 한도에 닿은 뒤에만 진입을 막는다(막힌 진입 ⇒ 닿음). 닿았어도 그 뒤에 신호가 없으면 막힌 진입은 없다.

    005930 이 09:03 에 손절(−6,930원)하고 000660 의 돌파 신호가 그 뒤(09:04)에 온다."""
    a = [R0, R1, R2, ("090300", 10_090, 10_090, 10_000, 10_010, 1_000), ("090400", 10_010, 10_020, 10_000, 10_010, 1_000),
         ("090500", 10_010, 10_020, 10_000, 10_010, 1_000)]
    b = [("090000", 20_000, 20_020, 19_990, 20_000, 1_000), ("090100", 20_000, 20_010, 19_990, 20_000, 1_000),
         ("090200", 20_000, 20_010, 19_990, 20_000, 1_000), ("090300", 20_000, 20_010, 19_990, 20_000, 1_000),
         ("090400", 20_000, 20_060, 20_000, 20_060, 1_000), ("090500", 20_070, 20_100, 20_060, 20_090, 1_000)]
    out = simulate(one_day(sess(a), sess(b, ticker="000660")), templates.build("opening_range_breakout", {"minutes": 1}),
                   PositionRules(amount=1_000_000, stop_pct=0.5, daily_loss_limit=limit), CostAssumptions(commission_bp=1.5), rules=RULES)
    assert (out["assumptions"].get("entry_blocked_daily_loss", 0) > 0) is blocked
    seen = monitor.loss_limit(out["fills"], float(limit))
    assert seen["touched"] is touched and (touched or not blocked)
    assert seen["realized_gross"] == (-6_930.0 if blocked else -14_280.0)      # 손 계산: 70원 × 99주 · 150원 × 49주


# ── 그날의 백테스트와 견주기 — 관측 ──────────────────────────────────────────────────────

def test_bars_that_changed_since_the_run_make_the_backtest_differ_and_the_monitor_says_so(client, monkeypatch):
    acc = _connect(client)
    run_id = _run(client, acc, _backtest(client)[0])
    assert _monitor(client, acc, run_id)["backtest"]["state"] == "same"   # ★짝★
    with_days(monkeypatch, _day_of(LOSING))                               # 가동 뒤에 그날의 봉이 바뀌었다(마지막 봉)
    back = _monitor(client, acc, run_id)["backtest"]
    assert back == {"state": "differs", "reason": monitor.BACKTEST["differs"], "run_fills": 2, "backtest_fills": 2}


def test_a_day_that_is_no_longer_loaded_leaves_the_comparison_unknown(client, monkeypatch):
    import src.api.intraday_routes as mod
    from src.data import minute_feed
    acc = _connect(client)
    run_id = _run(client, acc, _backtest(client)[0])
    monkeypatch.setattr(mod.minute_feed, "plan", lambda a, b: minute_feed.Plan([], 1))
    m = _monitor(client, acc, run_id)
    assert m["backtest"] == {"state": "unknown", "reason": monitor.BACKTEST["not_loaded"], "run_fills": 2, "backtest_fills": None}
    assert m["pnl"]["gross"] == 1_980.0                                   # 손익은 가상 체결에서 — 봉이 없어도 읽힌다


def test_a_backtest_with_a_different_number_of_fills_also_differs(client, monkeypatch):
    acc = _connect(client)
    run_id = _run(client, acc, _backtest(client)[0])
    with_days(monkeypatch, _day_of([R0, ("090100", 10_000, 10_010, 9_995, 10_000, 1_000)]))     # 돌파가 없는 하루 — 체결 0줄
    assert _monitor(client, acc, run_id)["backtest"] == {"state": "differs", "reason": monitor.BACKTEST["differs"], "run_fills": 2,
                                                         "backtest_fills": 0}


# ── 값이 없으면 0 이 아니라 사유 ─────────────────────────────────────────────────────────

def test_a_setting_copy_that_no_longer_reads_leaves_pnl_limit_and_comparison_without_values(client):
    acc = _connect(client)
    run_id = _run(client, acc, _backtest(client)[0])
    with dbmod.get_sync_engine().begin() as c:
        broken = json.dumps({"rule": {"kind": "no_such_template", "params": {}}, "position": {"amount": 1}, "costs": {}})
        assert c.execute(text("UPDATE rule_runs SET request = :r WHERE run_id = :id"), {"r": broken, "id": run_id}).rowcount == 1
    res = _get(client, acc, run_id)
    assert res.status_code == 200, res.text
    m = res.json()["monitor"]
    why = monitor.REASONS["bad_setting"]
    assert m["pnl"] == {"available": False, "reason": why, "gross": None, "cost": None, "net": None, "net_reason": None,
                        "closed_trades": None, "open_positions": None, "includes_rejected": None, "basis": None, "classification": None}
    assert m["loss_limit"] == {"limit": None, "reason": why, "realized_gross": None, "room": None, "touched": None}
    assert m["backtest"] == {"state": "unknown", "reason": why, "run_fills": 2, "backtest_fills": None}
    assert m["journal"] is None
    assert m["orders"]["by_status"] == {"SHADOW_LOGGED": 2} and m["fills"]["virtual"] == 2      # 가동 줄과 주문은 그대로 보인다


def test_a_sell_whose_tax_cannot_be_determined_leaves_the_net_without_a_value(client, monkeypatch):
    """가동 때 시장을 몰랐던 종목 → 매도세 미상 → 비용 뒤 손익은 값이 없다(0 도, 수수료만 뺀 값도 아니다)."""
    with_days(monkeypatch, _day_of(WINNING, market=None, instrument=None))
    acc = _connect(client)
    key, _journal = _backtest(client)
    run_id = _run(client, acc, key)
    pnl = _monitor(client, acc, run_id)["pnl"]
    assert (pnl["available"], pnl["gross"], pnl["cost"], pnl["net"], pnl["net_reason"]) == (True, 1_980.0, None, None, monitor.REASONS["cost_unknown"])
    assert pnl["classification"] == RECORDED                              # ★미상도 그때의 기록이다★(미기록이 아니다)
    # ★짝★ — 모르는 종목을 무엇으로 볼지(사용자의 가정)가 설정에 있으면 값이 있다.
    assumed = {**BODY, "costs": {"commission_bp": 1.5, "slippage_ticks": 1, "unknown_market": "KOSPI", "unknown_instrument": "stock"}}
    key, journal = _backtest(client, assumed)
    pnl = _monitor(client, acc, _run(client, acc, key))["pnl"]
    assert pnl["net_reason"] is None and pnl["net"] == pytest.approx(journal["summary"]["net"]["total"]) and pnl["net"] < pnl["gross"]
    # 뒤에 종목 마스터가 알게 돼도 ★그때의 미상은 미상★이다 — 지금의 마스터가 지난 가동의 빈칸을 채우지 않는다.
    import src.api.intraday_routes as mod
    monkeypatch.setattr(mod, "master_lookup", lambda: lambda _symbol: {"market": "KOSPI", "group_code": "ST", "name": "삼성전자"})
    later = _monitor(client, acc, run_id)["pnl"]
    assert (later["net"], later["net_reason"], later["classification"]) == (None, monitor.REASONS["cost_unknown"], RECORDED)


def test_an_order_log_cut_at_the_scan_limit_does_not_claim_to_know_what_is_missing(client, monkeypatch):
    acc = _connect(client)
    run_id = _run(client, acc, _backtest(client)[0])
    monkeypatch.setattr(monitor, "ORDER_SCAN", 2)                         # 이 가동의 주문 두 줄이 상한에 닿는다
    m = _monitor(client, acc, run_id)
    assert (m["orders"]["basis"], m["orders"]["reason"], m["orders"]["unrecorded"]) == ("order_log", monitor.REASONS["order_log_truncated"], None)
    assert m["fills"] == {"virtual": 2, "broker": None, "broker_reason": monitor.REASONS["order_log_truncated"]}
    monkeypatch.setattr(monitor, "ORDER_SCAN", 3)                         # ★짝★ — 상한 아래면 센다
    assert _monitor(client, acc, run_id)["orders"]["unrecorded"] == 0


def test_an_unreadable_run_store_is_503_not_an_empty_monitor(client, monkeypatch):
    acc = _connect(client)
    run_id = _run(client, acc, _backtest(client)[0])
    monkeypatch.setattr(rr, "fills_of", lambda _run_id: None)
    res = _get(client, acc, run_id)
    assert res.status_code == 503 and res.json()["detail"]["code"] == "store_unavailable"


def test_a_kill_switch_of_this_account_shows_as_its_own(client):
    acc = _connect(client)
    run_id = _run(client, acc, _backtest(client)[0])
    assert _monitor(client, acc, run_id)["kill"] == {"active": False, "own": False}            # ★짝★
    made = client.post(f"{BASE}/{acc}/kill-switch/trigger", json={"reason": "관제 시험의 정지"}, headers=_auth(client, "alice"))
    assert made.status_code == 200, made.text
    body = _get(client, acc, run_id).json()
    assert body["monitor"]["kill"] == {"active": True, "own": True} and body["kill_switch"] is True


# ── 관제는 쓰지 않는다 ───────────────────────────────────────────────────────────────────

def test_reading_the_monitor_writes_nothing_and_never_calls_the_order_path(client, monkeypatch):
    acc = _connect(client)
    key = _backtest(client)[0]
    done = _run(client, acc, key)
    running = _run(client, acc, key, bars=3)
    h = _auth(client, "alice")

    def boom(*_a, **_k):
        raise AssertionError("관제가 주문 경로를 불렀다")
    monkeypatch.setattr(get_account_executor(acc), "execute_signal", boom)
    before, clock = _table_rows(), client.get(f"{BASE}/{acc}/rule-runs/{running}", headers=h).json()["run"]["clock"]
    for run_id in (done, running, done, running):
        assert client.get(f"{BASE}/{acc}/rule-runs/{run_id}/monitor", headers=h).status_code == 200
    assert _table_rows() == before                                        # 모든 표의 줄 수가 그대로다
    assert client.get(f"{BASE}/{acc}/rule-runs/{running}", headers=h).json()["run"]["clock"] == clock     # 봉도 밀지 않았다


def test_the_monitor_module_has_no_way_to_write_or_to_order():
    """정적 — 관제 모듈에는 쓰는 부름도 주문 경로의 부름도 없다(동작 시험이 놓친 갈래를 막는다)."""
    tree = ast.parse(Path(monitor.__file__).read_text(encoding="utf-8"))
    called = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    forbidden = {"execute_signal", "cancel_order", "set_mode", "trigger", "resolve", "start", "advance", "stop", "reset",
                 "add_fill", "update_run", "open_run", "add_request", "remove_request", "mark_interrupted", "record"}
    assert called & forbidden == set(), called & forbidden
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names} | {
        n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not any(name.startswith("src.api") for name in imported), imported      # 문 층을 들여오지 않는다
    assert {"analyze", "simulate", "list_orders"} <= called | {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
