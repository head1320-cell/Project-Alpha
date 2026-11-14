"""POST /api/v1/intraday/divergence — 괴리 보고의 문 (설계 W5 §4.4)
==============================================================================
설계 `docs/superpowers/specs/2026-11-14-paper-trading-monitor-design.md`. 계산은 `test_intraday_divergence.py`(엔진)가 건다.
여기서는 문이 그것을 ★옳게 잇는지★만 본다.

- 문이 엔진에 넘기는 시뮬레이션 체결은 손으로 계산한 그 체결이다(하루: 09:02 매수 99주 @10,080 · 09:03 매도 99주 @10,100).
- ★올린 체결은 저장하지 않는다★ — 호출 전후 DB 모든 표의 행 수가 시행 기록 한 줄 말고는 같다.
- 시뮬레이션 쪽은 실행 문과 ★같은 길★로 시행에 남는다(같은 설정은 새 시행이 아니다). 기록하지 못하면 N 을 꾸미지 않는다.
- 상한을 넘으면 잘라서 계산하지 않는다. 설정이 어긋나면 실행 문과 같은 사유로 거절한다.
- 로그인이 필요하다. 분봉이 없으면 괴리 대신 사유.

손 계산(열흘 · `WIN` · 슬리피지 1틱): 시뮬레이션 비용 전 +19,800원(하루 +1,980원).
    실제가 양쪽 모두 한 틱 불리하면: 10,090 에 사서 10,090 에 판다 → 비용 전 0원 · 차이 −19,800원 · 짝 스물 · 평균 1틱.
"""
from __future__ import annotations

import logging

import pytest
from sqlalchemy import inspect, text

import src.database as dbmod
from src.engine.intraday import Day
from src.engine.intraday import divergence as dv
from tests.route_walk import flat_routes
from tests.test_intraday_validate_route import (  # noqa: F401 — `client` · `auth` 는 틀이다
    BODY,
    auth,
    break_store,
    client,
    made_days,
    stored_rows,
    weekdays,
    with_days,
)

DIV = "/api/v1/intraday/divergence"
SIM = "/api/v1/intraday/simulate"
DAYS = weekdays(10)


def fills(buy: float = 10_080, sell: float = 10_100, *, buy_at="09:02:00", sell_at="09:03:00", qty=99, days=DAYS,
          symbol="005930") -> list[dict]:
    out = []
    for d in days:
        out.append({"executed_at": f"{d} {buy_at}", "symbol": symbol, "side": "buy", "quantity": qty, "price": buy})
        out.append({"executed_at": f"{d} {sell_at}", "symbol": symbol, "side": "sell", "quantity": qty, "price": sell})
    return out


def hand_sim() -> list[dict]:
    return fills(10_080, 10_100)


def post(client, auth, rows, **over):
    return client.post(DIV, json={**BODY, "fills": rows, **over}, headers=auth)


def table_rows() -> dict[str, int]:
    engine = dbmod.get_engine()
    with engine.connect() as c:
        return {t: int(c.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar()) for t in inspect(engine).get_table_names()}


@pytest.fixture()
def ten_days(monkeypatch):
    with_days(monkeypatch, made_days())


# ── 문이 잇는 것 ────────────────────────────────────────────────────────
KNOWN_MARKET = {"commission_bp": 1.5, "slippage_ticks": 1, "unknown_market": "KOSPI", "unknown_instrument": "stock"}


def test_identical_fills_report_no_gap(client, auth, ten_days):
    r = post(client, auth, hand_sim(), costs=KNOWN_MARKET)        # 올린 줄에는 시장 구분이 없다 — 가정을 선언해야 매도세가 나온다
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["divergence"]["counts"] == {"matched": 20, "sim_only": 0, "actual_only": 0}
    assert body["divergence"]["price_gap"]["mean"] == {"won": 0.0, "ticks": 0.0, "bp": 0.0}
    pnl = body["pnl"]
    assert pnl["simulated"]["gross"] == pytest.approx(19_800.0) and pnl["actual"]["gross"] == pytest.approx(19_800.0)
    assert pnl["gap"]["gross"] == pytest.approx(0.0) and pnl["gap"]["net"] == pytest.approx(0.0)
    assert pnl["simulated"]["net"] == pytest.approx(-3_194.73, abs=0.01)             # 실행 문의 손 계산과 같은 수


def test_one_tick_worse_on_both_sides_is_the_hand_computed_gap(client, auth, ten_days):
    body = post(client, auth, fills(10_090, 10_090, buy_at="09:02:40", sell_at="09:03:20")).json()
    d = body["divergence"]
    assert d["counts"] == {"matched": 20, "sim_only": 0, "actual_only": 0}
    assert d["price_gap"]["mean"]["won"] == 10.0 and d["price_gap"]["mean"]["ticks"] == 1.0
    assert d["price_gap"]["adverse"] == 20 and d["price_gap"]["favorable"] == 0
    assert body["pnl"]["actual"]["gross"] == pytest.approx(0.0)                         # 10,090 에 사서 10,090 에 판다
    assert body["pnl"]["gap"]["gross"] == pytest.approx(-19_800.0)
    assert body["pnl"]["actual"]["trades"] == 10 and body["pnl"]["simulated"]["trades"] == 10


def test_the_route_hands_the_engine_the_hand_computed_simulated_fills(client, auth, ten_days):
    rows = fills(10_090, 10_085, buy_at="09:04:10", sell_at="09:03:30") + [
        {"executed_at": f"{DAYS[0]} 10:00:00", "symbol": "000660", "side": "buy", "quantity": 1, "price": 80_000},
        {"executed_at": "?", "symbol": "005930", "side": "buy", "quantity": 1, "price": 1}]
    got = post(client, auth, rows, window_minutes=3).json()["divergence"]
    want = dv.compare(hand_sim(), rows, tickers=["005930"], start=BODY["from"], end=BODY["to"], window_minutes=3)
    for key in ("mode", "degraded", "window_minutes", "counts", "by_window", "matched", "sim_only", "actual_only",
                "price_gap", "time_gap", "quantity_gap", "set_aside", "inputs"):
        assert got[key] == want[key], key
    assert got["rows_limit"] >= 500


def test_the_actual_side_counts_only_what_was_compared(client, auth, ten_days):
    """다른 종목 · 기간 밖의 줄은 실제 손익에도 들어가지 않는다 — 견준 것과 센 것이 같은 줄이다."""
    extra = fills(50_000, 90_000, symbol="000660", days=DAYS[:1]) + fills(10_000, 20_000, days=["2026-02-20"])
    body = post(client, auth, hand_sim() + extra).json()
    assert body["pnl"]["actual"]["gross"] == pytest.approx(19_800.0) and body["pnl"]["actual"]["trades"] == 10
    aside = body["divergence"]["set_aside"]
    assert aside["other_symbols"] == {"rows": 2, "symbols": ["000660"]} and aside["outside_period"] == 2


def test_unknown_commission_leaves_the_net_gap_unknown_not_zero(client, auth, ten_days):
    body = post(client, auth, hand_sim(), costs={**KNOWN_MARKET, "commission_bp": None}).json()
    assert body["pnl"]["gap"]["gross"] == pytest.approx(0.0)
    assert body["pnl"]["gap"]["net"] is None and body["pnl"]["net_reason"] == "cost_unknown"


def test_an_undeclared_market_leaves_the_actual_net_unknown_while_the_simulated_net_is_known(client, auth, ten_days):
    """시뮬레이션은 분봉의 시장 구분을 알고, 올린 파일은 모른다 — 모르는 매도세를 0 으로 치지 않는다."""
    pnl = post(client, auth, hand_sim()).json()["pnl"]
    assert pnl["simulated"]["net"] == pytest.approx(-3_194.73, abs=0.01)
    assert pnl["actual"]["net"] is None and pnl["gap"]["net"] is None and pnl["net_reason"] == "cost_unknown"
    assert pnl["gap"]["gross"] == pytest.approx(0.0)


def test_long_lists_are_cut_for_the_screen_but_the_counts_are_whole(client, auth, ten_days, monkeypatch):
    import src.api.intraday_routes as mod
    monkeypatch.setattr(mod, "DIVERGENCE_ROWS_LIMIT", 3)
    d = post(client, auth, hand_sim()).json()["divergence"]
    assert len(d["matched"]) == 3 and d["counts"]["matched"] == 20 and d["rows_limit"] == 3
    assert d["price_gap"]["n"] == 20                                                     # 잘린 것은 목록뿐이다


# ── 저장하지 않는다 · 시행은 같은 길 ────────────────────────────────────
def test_uploaded_fills_are_not_stored(client, auth, ten_days):
    post(client, auth, hand_sim())                                                       # 표를 만들고 시행 한 줄을 남긴다
    before = table_rows()
    r = post(client, auth, fills(10_123, 10_077, buy_at="09:02:10", sell_at="09:03:50"))
    assert r.status_code == 200
    assert table_rows() == before                                                        # 같은 설정 — 행 수는 하나도 늘지 않는다
    engine = dbmod.get_engine()
    with engine.connect() as c:                                                          # 올린 값이 어느 표에도 없다
        for table in inspect(engine).get_table_names():
            blob = " ".join(str(v) for row in c.execute(text(f'SELECT * FROM "{table}"')).fetchall() for v in row)
            assert "10123" not in blob and "10077" not in blob, table


def test_the_simulated_side_is_recorded_as_a_trial_through_the_same_path(client, auth, ten_days):
    assert stored_rows() == 0
    first = post(client, auth, hand_sim()).json()["trial"]
    assert stored_rows() == 1 and first["recorded"] is True and first["new"] is True and first["runs"] == 1
    again = post(client, auth, fills(10_090, 10_090)).json()["trial"]                    # 올린 체결이 달라도 설정은 같다
    assert stored_rows() == 1 and again["new"] is False and again["runs"] == 2
    seen = client.post(SIM, json=BODY, headers=auth).json()["trial"]                     # 실행 문이 보는 것도 같은 시행이다
    assert stored_rows() == 1 and seen["new"] is False and seen["runs"] == 3


def test_a_trial_that_cannot_be_recorded_is_said_so_and_not_counted_as_one(client, auth, ten_days, monkeypatch):
    break_store(monkeypatch)
    body = post(client, auth, hand_sim()).json()
    assert body["trial"]["recorded"] is False and body["trial"]["family_n"] is None
    assert body["trial"]["reason"] == "store_unavailable"
    assert body["divergence"]["counts"]["matched"] == 20                                  # 괴리는 본다 — 세지 못했다고 적힐 뿐이다


def test_the_log_carries_counts_not_fills(client, auth, ten_days, caplog):
    with caplog.at_level(logging.INFO, logger="api.intraday"):
        post(client, auth, fills(10_123, 10_077))
    mine = [r.getMessage() for r in caplog.records if r.name == "api.intraday"]
    assert any(m.startswith("intraday divergence:") and "rows=20" in m and "matched=" in m for m in mine), mine
    everything = " ".join(r.getMessage() for r in caplog.records)                        # 어느 로거에도 값이 없다
    assert "10123" not in everything and "10077" not in everything


# ── 거절 ────────────────────────────────────────────────────────────────
def test_no_rows_and_too_many_rows_are_refused_not_trimmed(client, auth, ten_days, monkeypatch):
    r = post(client, auth, [])
    assert r.status_code == 400 and r.json()["detail"]["code"] == "no_rows"
    import src.api.intraday_routes as mod
    monkeypatch.setattr(mod, "MAX_FILLS", 5)
    r = post(client, auth, hand_sim())
    assert r.status_code == 400 and r.json()["detail"]["code"] == "too_many_rows"
    assert r.json()["detail"]["limit"] == 5 and r.json()["detail"]["rows"] == 20
    assert stored_rows() == 0                                                            # 거절은 시행이 아니다


@pytest.mark.parametrize("bad", [0, 61, -3, 2.5, "five"])
def test_a_bad_window_is_refused(client, auth, ten_days, bad):
    r = post(client, auth, hand_sim(), window_minutes=bad)
    assert r.status_code in (400, 422) and stored_rows() == 0


def test_a_bad_setting_is_refused_with_the_run_routes_reason(client, auth, ten_days):
    for patch in ({"tickers": []}, {"from": "2026-03-13", "to": "2026-03-02"}):
        mine = post(client, auth, hand_sim(), **patch)
        theirs = client.post(SIM, json={**BODY, **patch}, headers=auth)
        assert mine.status_code == theirs.status_code == 400
        assert mine.json()["detail"] == theirs.json()["detail"], patch
    assert stored_rows() == 0


def test_login_is_required_and_the_route_is_registered_as_such(client, ten_days):
    assert client.post(DIV, json={**BODY, "fills": hand_sim()}).status_code == 401
    from src.api.protected_routes import PROTECTED, REQUIRE_LOGIN, auth_requirement_of_route
    hits = [r for r in flat_routes(client.app) if getattr(r, "path", None) == DIV and "POST" in (r.methods or ())]
    assert len(hits) == 1 and auth_requirement_of_route(hits[0]) == REQUIRE_LOGIN
    assert PROTECTED[("POST", DIV)][0] == REQUIRE_LOGIN


def test_without_loaded_bars_there_is_a_reason_instead_of_a_gap(client, auth, monkeypatch):
    import src.api.intraday_routes as mod
    from src.data import minute_feed
    monkeypatch.setattr(mod.minute_feed, "plan", lambda a, b: minute_feed.Plan([], 0))
    body = post(client, auth, hand_sim()).json()
    assert body["empty"]["reason"] == "not_loaded" and body["divergence"] is None and body["pnl"] is None
    assert body["trial"] is None and stored_rows() == 0


def test_days_without_a_usable_session_give_a_reason_and_are_not_a_trial(client, auth, monkeypatch):
    with_days(monkeypatch, [Day(d, {}) for d in DAYS])
    body = post(client, auth, hand_sim()).json()
    assert body["empty"]["reason"] == "no_usable_bars" and body["divergence"] is None and body["pnl"] is None
    assert body["trial"] is None and stored_rows() == 0                                   # 본 것이 없으면 해 본 것도 아니다


def test_synthetic_bars_are_said_to_be_synthetic(client, auth, monkeypatch):
    with_days(monkeypatch, made_days(source="synthetic"))
    body = post(client, auth, hand_sim()).json()
    same = client.post(SIM, json=BODY, headers=auth).json()
    assert body["origin"] == same["origin"] and body["origin"]["grade"] == "E0"


# ── 내 시행의 목록 — 매매일지가 고를 것 ─────────────────────────────────
TRIALS = "/api/v1/intraday/trials"


def test_my_trials_come_back_as_requests_that_can_be_sent_again(client, auth, ten_days):
    client.post(SIM, json=BODY, headers=auth)
    listed = client.get(TRIALS, headers=auth).json()
    assert listed["available"] is True and listed["reason"] is None and len(listed["trials"]) == 1
    row = listed["trials"][0]
    assert row["runs"] == 1 and row["rule_label"] and len(row["trial_key"]) == 64
    assert row["request"]["tickers"] == ["005930"] and (row["request"]["from"], row["request"]["to"]) == (BODY["from"], BODY["to"])
    again = client.post(DIV, json={**row["request"], "fills": hand_sim()}, headers=auth)      # 받은 요청을 그대로 본문으로
    assert again.status_code == 200, again.text
    assert again.json()["trial"]["new"] is False and again.json()["trial"]["runs"] == 2       # 같은 시행이다 — 설정이 그대로 돌아왔다
    assert again.json()["divergence"]["counts"]["matched"] == 20


def test_the_trial_list_is_mine_only_and_needs_login(client, auth, ten_days):
    client.post(SIM, json=BODY, headers=auth)
    assert client.get(TRIALS).status_code == 401
    from tests.test_intraday_validate_route import login
    assert client.get(TRIALS, headers=login(client, "bob")).json()["trials"] == []
    from src.api.protected_routes import PROTECTED, REQUIRE_LOGIN
    assert PROTECTED[("GET", TRIALS)][0] == REQUIRE_LOGIN


def test_an_unreadable_trial_store_is_said_so_not_shown_as_empty(client, auth, ten_days, monkeypatch):
    client.post(SIM, json=BODY, headers=auth)
    break_store(monkeypatch)
    listed = client.get(TRIALS, headers=auth).json()
    assert listed["available"] is False and listed["reason"] and listed["trials"] == []
