"""규칙 가동의 문 (W5b · 구현 계획 §5) — 내 계좌의 `rule-runs` 다섯 + 분봉의 `arm-requests` 둘

가동기의 뜻(`tests/test_rule_runner.py`)은 다시 걸지 않는다. 여기서는 문이 지키는 약속만 본다:

  · 전부 로그인 · ★본인 계좌만★(남의 계좌는 404 — 없는 계좌와 같은 답) · 등록부에 올라 있다
  · 봉은 분봉 백테스트와 같은 준비로 짓는다 → 재생한 가상 체결이 손 계산과 같다
  · 시행이 없는 설정 · 적재되지 않은 날 · 모의투자 모드 · 비상 정지 중에는 사유와 함께 거절(아무것도 남기지 않는다)
  · 걸음 수는 1 이상의 정수만(글자 · 참거짓 · 0 은 422)
  · ★앱을 다시 띄우면 가동은 전부 꺼진다★ — 남은 줄은 '중단됨'
  · 가동 요청: 본인 것만 보이고 지운다 · 시행의 관문 요약이 있으면 싣고, 없으면 없다고 적는다(가동을 막지는 않는다)
  · 못 읽음은 빈 목록이 아니다
"""
from __future__ import annotations

import os
import tempfile

import numpy as np
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

import src.data.intraday_trials as trials
import src.data.minute_bars as mb
import src.data.rule_runs as rr
import src.database as dbmod
import src.execution.kis_client as kc
import src.execution.rule_runner as runner
from src.api.protected_routes import PROTECTED, REQUIRE_LOGIN
from src.domain.auth_identity import ROLE_ANALYST
from src.engine.intraday import Day, Session
from tests.route_walk import flat_routes

_SECRET = "rule-run-routes-test-secret-0123456789abcdef"
BASE = "/api/v1/broker-accounts"
REQS = "/api/v1/intraday/arm-requests"
SIM = "/api/v1/intraday/simulate"
DAY = "2026-03-04"
BODY = {"tickers": ["005930"], "from": DAY, "to": DAY, "rule": {"kind": "opening_range_breakout", "params": {"minutes": 1}},
        "position": {"amount": 1_000_000}, "costs": {"commission_bp": 1.5, "slippage_ticks": 1}}
RUN_ROUTES = [("GET", BASE + "/{account_id}/rule-runs"), ("POST", BASE + "/{account_id}/rule-runs"),
              ("GET", BASE + "/{account_id}/rule-runs/{run_id}"), ("POST", BASE + "/{account_id}/rule-runs/{run_id}/advance"),
              ("POST", BASE + "/{account_id}/rule-runs/{run_id}/stop")]
REQ_ROUTES = [("GET", REQS), ("DELETE", REQS + "/{request_id}")]


def hand_made_day(source="kis") -> list[Day]:
    """개장 1분 범위 돌파: 09:01 이 신호 봉 → 09:02 시가 + 한 틱에 99주 · 하루 끝 09:03 종가 − 한 틱."""
    rows = [("090000", 10_000, 10_020, 9_990, 10_000, 1_000), ("090100", 10_000, 10_060, 10_000, 10_060, 1_000),
            ("090200", 10_070, 10_100, 10_060, 10_090, 1_000), ("090300", 10_090, 10_120, 10_080, 10_110, 1_000)]
    t, o, h, low, c, v = zip(*rows)
    s = Session("005930", DAY, np.array(t), np.array(o, float), np.array(h, float), np.array(low, float),
                np.array(c, float), np.array(v, float), source, None, "KOSPI", "stock", "삼성전자")
    return [Day(DAY, {"005930": s})]


@pytest.fixture()
def client(monkeypatch, tmp_path):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp.name}")
    monkeypatch.setenv("AUTH_SECRET", _SECRET)
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    monkeypatch.setenv("BROKER_CRED_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("MINUTE_BARS_DIR", str(tmp_path / "bars"))
    monkeypatch.setattr(dbmod, "DATABASE_URL", f"sqlite:///{tmp.name}", raising=False)
    import src.api.stage13_routes as stage13
    import src.data.backtest_runs as br
    import src.execution.account_executors as ae
    monkeypatch.setattr(br, "_inited", False)
    monkeypatch.setattr(kc, "_kis_singleton", None, raising=False)
    monkeypatch.setattr(kc, "_account_clients", {}, raising=False)
    monkeypatch.setattr(stage13, "_EXECUTOR", None, raising=False)
    monkeypatch.setattr(ae, "_executors", {}, raising=False)
    monkeypatch.setattr(runner, "_active", {}, raising=False)
    dbmod.reset_session()
    dbmod.init_db()
    dbmod.create_user("alice", "alice-pw", role=ROLE_ANALYST)
    dbmod.create_user("bob", "bob-pw", role=ROLE_ANALYST)
    mb.clear_cache()
    with_days(monkeypatch, hand_made_day())

    from src.app_factory import create_app
    with TestClient(create_app()) as c:
        c.post("/api/v1/live/init-schema", headers=_auth(c, "admin", "frm123!"))
        yield c

    mb.clear_cache()
    dbmod.reset_session()
    try:
        os.unlink(tmp.name)
    except OSError:
        pass


def with_days(monkeypatch, days: list[Day]) -> None:
    """분봉 준비가 내줄 하루를 정한다 — 분봉 백테스트의 문과 가동의 문이 같은 준비(`minute_feed`)를 쓴다."""
    import src.api.intraday_routes as mod
    from src.data import minute_feed
    monkeypatch.setattr(mod.minute_feed, "plan", lambda a, b: minute_feed.Plan([d.date for d in days], 1))
    monkeypatch.setattr(mod.minute_feed, "build_days", lambda *a, **k: days)


def _auth(client, username: str, password: str | None = None) -> dict[str, str]:
    tok = client.post("/api/v1/auth/login", json={"username": username, "password": password or f"{username}-pw"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def _connect(client, user="alice") -> str:
    res = client.post(BASE, json=dict(label="내 계좌", app_key="PSkey-0123456789abcdef", app_secret="secret-0123456789abcdefghijklmnop",
                                      account_no="50123456", is_paper=True), headers=_auth(client, user))
    assert res.status_code == 201, res.text
    return res.json()["account_id"]


def _trial(client, user="alice", body=None) -> str:
    """분봉 백테스트를 한 번 돌려 시행을 남기고 그 열쇠를 돌려준다."""
    h = _auth(client, user)
    assert client.post(SIM, json=body or BODY, headers=h).status_code == 200
    return client.get("/api/v1/intraday/trials", headers=h).json()["trials"][0]["trial_key"]


def _start(client, acc, key, user="alice", day=DAY):
    return client.post(f"{BASE}/{acc}/rule-runs", json={"trial_key": key, "day": day}, headers=_auth(client, user))


def _code(res) -> str:
    return res.json()["detail"]["code"]


# ── 문 ───────────────────────────────────────────────────────────────────────────────

def test_every_route_is_mounted_and_login_only(client):
    table = {(m, r.path) for r in flat_routes(client.app) for m in (getattr(r, "methods", None) or [])}
    for route in RUN_ROUTES + REQ_ROUTES:
        assert route in table, route
        assert PROTECTED[route][0] == REQUIRE_LOGIN, route


@pytest.mark.parametrize(("method", "path"), RUN_ROUTES + REQ_ROUTES)
def test_without_a_login_nothing_is_read_or_started(client, method, path):
    acc = _connect(client)
    url = path.replace("{account_id}", acc).replace("{run_id}", "1").replace("{request_id}", "1")
    assert client.request(method, url, json={"trial_key": "a" * 64, "day": DAY}).status_code == 401
    assert rr.runs_of("alice", acc) == [] and runner.active(acc) == []


# ── 가동 → 걸음 → 읽기 ─────────────────────────────────────────────────────────────────

def test_a_run_started_through_the_door_replays_to_the_hand_computed_fills(client):
    acc, key = _connect(client), _trial(client)
    made = _start(client, acc, key)
    assert made.status_code == 201, made.text
    body = made.json()
    run = body["run"]
    assert (run["status"], run["mode"], run["day"], run["trial_key"], run["active"]) == ("running", "SHADOW", DAY, key, True)
    assert run["clock"] == {"total": 4, "done": 0, "next": "090000"} and run["grade"] == "E3"
    assert (body["mode"], body["kill_switch"]) == ("SHADOW", False) and body["gate"] == {"mock": True}
    assert body["limits"] == {"runs": runner.MAX_RUNS_PER_ACCOUNT, "tickers": runner.MAX_RUN_TICKERS, "gap_minutes": runner.GAP_MINUTES}
    h = _auth(client, "alice")
    step = client.post(f"{BASE}/{acc}/rule-runs/{run['run_id']}/advance", json={"bars": 3}, headers=h).json()
    assert (step["run"]["status"], step["run"]["last_bar"]) == ("running", "090200")
    assert [(f["side"], f["quantity"], f["price"]) for f in step["run"]["new_fills"]] == [("buy", 99, 10_080.0)]
    done = client.post(f"{BASE}/{acc}/rule-runs/{run['run_id']}/advance", json={}, headers=h).json()      # 걸음 수 없이 = 끝까지
    assert (done["run"]["status"], done["run"]["stop_reason"]) == ("finished", "finished")
    got = client.get(f"{BASE}/{acc}/rule-runs/{run['run_id']}", headers=h).json()
    assert [(f["executed_at"], f["side"], f["quantity"], f["price"], f["kind"], f["order_status"]) for f in got["run"]["fills"]] == [
        (f"{DAY} 09:02:00", "buy", 99, 10_080.0, "virtual", "SHADOW_LOGGED"), (f"{DAY} 09:03:00", "sell", 99, 10_100.0, "virtual", "SHADOW_LOGGED")]
    listed = client.get(f"{BASE}/{acc}/rule-runs", headers=h).json()
    assert listed["available"] is True and [(r["run_id"], r["status"]) for r in listed["runs"]] == [(run["run_id"], "finished")]
    assert kc.get_kis_client(account_id=acc).orders == []                  # 증권사로 0건


def test_the_bars_come_from_the_same_preparation_as_the_backtest(client, monkeypatch):
    """문이 봉을 짓는 인자 — 시행의 종목 · 그 하루 · 장 운영 규칙. 다른 날 · 다른 종목으로 짓지 않는다."""
    import src.api.intraday_routes as mod
    acc, key = _connect(client), _trial(client)
    seen = []
    monkeypatch.setattr(mod.minute_feed, "build_days", lambda tickers, a, b, **kw: seen.append((tickers, a.isoformat(), b.isoformat(), sorted(kw))) or hand_made_day())
    assert _start(client, acc, key).status_code == 201
    assert seen == [(["005930"], DAY, DAY, ["master", "need_prev", "rules"])]


# ── 남의 계좌 ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("method", "path"), RUN_ROUTES)
def test_someone_elses_account_is_404_on_every_route(client, method, path):
    acc, key = _connect(client), _trial(client)
    run_id = _start(client, acc, key).json()["run"]["run_id"]
    url = path.replace("{account_id}", acc).replace("{run_id}", str(run_id))
    res = client.request(method, url, json={"trial_key": _trial(client, "bob"), "day": DAY}, headers=_auth(client, "bob"))
    assert res.status_code == 404, f"{method} {path} → {res.status_code}"
    assert rr.run_of("alice", acc, run_id)["status"] == "running" and [r["run_id"] for r in rr.runs_of("alice", acc)] == [run_id]


def test_a_malformed_body_to_someone_elses_account_is_still_404(client):
    """소유 확인이 본문 검사보다 먼저다 — 남의 계좌에 틀린 본문을 보내 422 로 '그 계좌가 있다'를 알아낼 수 없다."""
    acc, key = _connect(client), _trial(client)
    run_id = _start(client, acc, key).json()["run"]["run_id"]
    bob = _auth(client, "bob")
    assert client.post(f"{BASE}/{acc}/rule-runs", json={"rule": {"kind": "gap"}}, headers=bob).status_code == 404
    assert client.post(f"{BASE}/{acc}/rule-runs/{run_id}/advance", json={"bars": 0}, headers=bob).status_code == 404
    assert client.post(f"{BASE}/no-such-account/rule-runs", json={}, headers=bob).status_code == 404      # 없는 계좌와 같은 답
    assert client.post(f"{BASE}/{acc}/rule-runs", json={}, headers=_auth(client, "alice")).status_code == 422  # 짝 — 주인에게는 본문 오류


def test_a_run_is_read_only_through_its_own_account(client):
    acc, other, key = _connect(client), _connect(client), _trial(client)
    run_id = _start(client, acc, key).json()["run"]["run_id"]
    h = _auth(client, "alice")
    assert client.get(f"{BASE}/{other}/rule-runs/{run_id}", headers=h).status_code == 404        # 내 다른 계좌의 번호가 아니다
    assert client.get(f"{BASE}/{acc}/rule-runs/{run_id + 99}", headers=h).status_code == 404
    assert client.get(f"{BASE}/{acc}/rule-runs/{run_id}", headers=h).status_code == 200


# ── 거절 ─────────────────────────────────────────────────────────────────────────────

def test_a_setting_without_a_trial_or_a_day_without_bars_is_refused_with_a_reason(client, monkeypatch):
    acc, key = _connect(client), _trial(client)
    none = _start(client, acc, "f" * 64)
    assert none.status_code == 400 and _code(none) == "no_trial" and none.json()["detail"]["reason"] == runner.REASONS["no_trial"]
    with_days(monkeypatch, [])                                             # 그 날짜의 분봉 파일이 없다
    empty = _start(client, acc, key)
    assert empty.status_code == 400 and _code(empty) == "not_loaded"
    assert rr.runs_of("alice", acc) == []


def test_a_day_without_bar_files_is_refused_before_anything_is_built(client, monkeypatch):
    """적재 계획이 그날을 모르면 봉을 지으러 가지 않는다 — 지을 것이 있었더라도 거절이 먼저다."""
    import src.api.intraday_routes as mod
    from src.data import minute_feed
    acc, key = _connect(client), _trial(client)
    built = []
    monkeypatch.setattr(mod.minute_feed, "plan", lambda a, b: minute_feed.Plan([], 0))
    monkeypatch.setattr(mod.minute_feed, "build_days", lambda *a, **k: built.append(a) or hand_made_day())
    res = _start(client, acc, key)
    assert res.status_code == 400 and _code(res) == "not_loaded" and res.json()["detail"]["reason"]
    assert built == [] and rr.runs_of("alice", acc) == []


def test_a_day_that_builds_to_nothing_is_refused_not_crashed(client, monkeypatch):
    """짝 — 파일은 있는데 지어진 하루가 없다(그 종목의 봉이 없는 날). 500 이 아니라 사유 있는 거절이다."""
    import src.api.intraday_routes as mod
    acc, key = _connect(client), _trial(client)
    monkeypatch.setattr(mod.minute_feed, "build_days", lambda *a, **k: [])          # 계획은 그날을 안다(고정물의 것 그대로)
    res = _start(client, acc, key)
    assert res.status_code == 400 and _code(res) == "not_loaded"
    assert rr.runs_of("alice", acc) == []


@pytest.mark.parametrize("body", [{"trial_key": "a" * 64}, {"day": DAY}, {"trial_key": "a" * 64, "day": "어제"},
                                  {"trial_key": "a" * 64, "day": DAY, "rule": {"kind": "gap"}}])
def test_a_malformed_start_is_a_422_and_carries_no_setting_of_its_own(client, body):
    """설정은 본문으로 받지 않는다 — 시행 열쇠와 날짜뿐이다(다른 규칙을 끼워 넣을 칸이 없다)."""
    acc = _connect(client)
    assert client.post(f"{BASE}/{acc}/rule-runs", json=body, headers=_auth(client, "alice")).status_code == 422


@pytest.mark.parametrize("bars", [0, -1, "3", True, 1.5])
def test_the_number_of_bars_must_be_a_positive_integer(client, bars):
    acc, key = _connect(client), _trial(client)
    run_id = _start(client, acc, key).json()["run"]["run_id"]
    res = client.post(f"{BASE}/{acc}/rule-runs/{run_id}/advance", json={"bars": bars}, headers=_auth(client, "alice"))
    assert res.status_code == 422, res.text
    assert rr.run_of("alice", acc, run_id)["bars"] == 0


def test_paper_mode_and_an_active_kill_switch_refuse_the_start(client):
    acc, key = _connect(client), _trial(client)
    h = _auth(client, "alice")
    client.post(f"{BASE}/{acc}/kill-switch/trigger", json={"reason": "잠깐 멈춤"}, headers=h)
    halted = _start(client, acc, key)
    assert halted.status_code == 400 and _code(halted) == "kill_switch_active"
    assert client.get(f"{BASE}/{acc}/rule-runs", headers=h).json()["kill_switch"] is True          # 화면이 왜인지 읽는다
    client.post(f"{BASE}/{acc}/kill-switch/resolve", json={"notes": "다시"}, headers=h)
    client.post(f"{BASE}/{acc}/mode", json={"mode": "PAPER"}, headers=h)
    paper = _start(client, acc, key)
    assert paper.status_code == 400 and _code(paper) == "mode_not_supported"
    assert client.get(f"{BASE}/{acc}/rule-runs", headers=h).json()["mode"] == "PAPER"
    assert rr.runs_of("alice", acc) == []


def test_stopping_ends_the_run_and_it_cannot_be_advanced_again(client):
    acc, key = _connect(client), _trial(client)
    h = _auth(client, "alice")
    run_id = _start(client, acc, key).json()["run"]["run_id"]
    stopped = client.post(f"{BASE}/{acc}/rule-runs/{run_id}/stop", headers=h)
    assert stopped.status_code == 200 and (stopped.json()["run"]["status"], stopped.json()["run"]["stop_reason"]) == ("stopped", "user")
    again = client.post(f"{BASE}/{acc}/rule-runs/{run_id}/advance", json={}, headers=h)
    assert again.status_code == 400 and _code(again) == "not_running"


def test_production_refuses_a_trial_run_on_synthetic_bars(client, monkeypatch):
    acc = _connect(client)
    with_days(monkeypatch, hand_made_day(source="synthetic"))
    key = _trial(client)                                                   # 합성 분봉으로 돌린 시행(등급 E0)
    monkeypatch.setattr(runner, "mock_allowed", lambda: False)
    res = _start(client, acc, key)
    assert res.status_code == 400 and _code(res) == "synthetic_in_production"
    assert rr.runs_of("alice", acc) == []


# ── 재시작 ───────────────────────────────────────────────────────────────────────────

def test_starting_the_app_again_turns_every_run_off(client):
    acc, key = _connect(client), _trial(client)
    h = _auth(client, "alice")
    run_id = _start(client, acc, key).json()["run"]["run_id"]
    client.post(f"{BASE}/{acc}/rule-runs/{run_id}/advance", json={"bars": 1}, headers=h)
    assert runner.active(acc) == [run_id]

    from src.app_factory import create_app
    with TestClient(create_app()) as again:                                # 서버가 다시 떴다
        assert runner.active(acc) == []
        got = again.get(f"{BASE}/{acc}/rule-runs/{run_id}", headers=h).json()["run"]
        assert (got["status"], got["stop_reason"], got["active"]) == ("interrupted", "interrupted", False)
        res = again.post(f"{BASE}/{acc}/rule-runs/{run_id}/advance", json={}, headers=h)
        assert res.status_code == 400 and _code(res) == "not_running"       # 되살리지 않는다


# ── 가동 요청 ─────────────────────────────────────────────────────────────────────────

def test_my_arm_requests_are_listed_with_what_they_would_run(client):
    key = _trial(client)
    h = _auth(client, "alice")
    assert client.get(REQS, headers=h).json() == {"available": True, "reason": None, "requests": [], "gate": {"mock": True}}
    made = rr.add_request("alice", key, note="캔버스에서")
    rows = client.get(REQS, headers=h).json()["requests"]
    assert len(rows) == 1
    row = rows[0]
    assert (row["id"], row["trial_key"], row["note"]) == (made["id"], key, "캔버스에서")
    assert row["trial"]["found"] is True and row["trial"]["rule_label"] and row["trial"]["rule_kind"] == "opening_range_breakout"
    assert (row["trial"]["tickers"], row["trial"]["from"], row["trial"]["to"], row["trial"]["grade"]) == (["005930"], DAY, DAY, "E3")
    assert row["trial"]["synthetic"] is False and row["trial"]["runs"] == 1
    assert row["gates"] == {"known": False, "counts": None, "reason": row["gates"]["reason"]} and "판정" in row["gates"]["reason"]
    assert client.get(REQS, headers=_auth(client, "bob")).json()["requests"] == []                # 남의 요청은 보이지 않는다


def test_a_request_for_a_trial_run_on_synthetic_bars_says_so(client, monkeypatch):
    """짝 — 위 시험의 `synthetic: False` 가 상수가 아님을 건다. 합성 분봉으로 돌린 시행은 요청 목록에서도 합성이라고 읽힌다."""
    with_days(monkeypatch, hand_made_day(source="synthetic"))
    key = _trial(client)
    rr.add_request("alice", key)
    row = client.get(REQS, headers=_auth(client, "alice")).json()["requests"][0]
    assert (row["trial"]["grade"], row["trial"]["synthetic"]) == ("E0", True)


def test_a_request_shows_the_gate_counts_when_a_verdict_was_kept(client):
    """캔버스의 단추로 실행한 시행은 판정 요약을 남긴다 — 그 수를 싣는다(보여 주기만 한다 — 가동을 막지 않는다)."""
    key = _trial(client)
    assert trials.keep_result("alice", key, {"gates": {"counts": {"ok": 2, "degraded": 1, "unknown": 4}}}) is True
    rr.add_request("alice", key)
    row = client.get(REQS, headers=_auth(client, "alice")).json()["requests"][0]
    assert row["gates"] == {"known": True, "counts": {"ok": 2, "degraded": 1, "unknown": 4}, "reason": None}
    acc = _connect(client)
    assert _start(client, acc, key).status_code == 201                      # 미달 · 미상이 있어도 가동은 열린다


def test_a_verdict_that_cannot_be_read_is_not_said_to_be_missing(client, monkeypatch):
    """못 읽음 ≠ 없음 — 판정을 남기지 않은 실행과, 남긴 판정을 읽지 못한 것은 다른 문장이다(둘 다 관문 수는 싣지 않는다)."""
    key = _trial(client)
    rr.add_request("alice", key)
    h = _auth(client, "alice")
    none = client.get(REQS, headers=h).json()["requests"][0]["gates"]
    monkeypatch.setattr(trials, "result_of", lambda *a, **k: None)
    unread = client.get(REQS, headers=h).json()["requests"][0]["gates"]
    assert (none["known"], none["counts"], unread["known"], unread["counts"]) == (False, None, False, None)
    assert "남기지 않은" in none["reason"] and "읽지 못했습니다" in unread["reason"] and none["reason"] != unread["reason"]


def test_a_request_whose_trial_is_gone_or_unreadable_says_which(client, monkeypatch):
    """요청이 가리키는 시행이 없으면 없다고, 시행 기록을 못 읽으면 못 읽었다고 적는다 — 빈 설정을 지어 보여 주지 않는다."""
    rr.add_request("alice", "e" * 64)                                       # 시행 기록에 없는 열쇠
    h = _auth(client, "alice")
    row = client.get(REQS, headers=h).json()["requests"][0]
    assert row["trial"]["found"] is False and "없습니다" in row["trial"]["reason"]
    assert set(row["trial"]) == {"found", "reason"} and row["gates"] == {"known": False, "counts": None, "reason": row["gates"]["reason"]}
    monkeypatch.setattr(trials, "trial_of", lambda *a, **k: None)
    lost = client.get(REQS, headers=h).json()["requests"][0]
    assert lost["trial"]["found"] is None and "읽지 못했습니다" in lost["trial"]["reason"]
    assert lost["trial"]["reason"] != row["trial"]["reason"] and "읽지 못했습니다" in lost["gates"]["reason"]


def test_only_the_owner_removes_a_request_and_it_is_gone_from_the_list(client):
    key = _trial(client)
    made = rr.add_request("alice", key)
    assert client.delete(f"{REQS}/{made['id']}", headers=_auth(client, "bob")).status_code == 404
    assert len(client.get(REQS, headers=_auth(client, "alice")).json()["requests"]) == 1
    gone = client.delete(f"{REQS}/{made['id']}", headers=_auth(client, "alice"))
    assert gone.status_code == 200 and gone.json() == {"removed": True, "id": made["id"]}
    assert client.get(REQS, headers=_auth(client, "alice")).json()["requests"] == []
    assert client.delete(f"{REQS}/{made['id']}", headers=_auth(client, "alice")).status_code == 404


def test_a_request_that_could_not_be_removed_is_not_said_to_be_missing(client, monkeypatch):
    """못 지움 ≠ 없음 — 저장소가 답하지 못하면 404(그런 요청 없음)가 아니라 503 과 사유다. 지웠다고도 하지 않는다."""
    made = rr.add_request("alice", _trial(client))
    monkeypatch.setattr(rr, "remove_request", lambda *a, **k: None)
    res = client.delete(f"{REQS}/{made['id']}", headers=_auth(client, "alice"))
    assert res.status_code == 503 and _code(res) == "store_unavailable" and res.json()["detail"]["reason"]


# ── 못 읽음 ≠ 없음 ─────────────────────────────────────────────────────────────────────

def test_an_unreadable_store_is_said_not_shown_as_empty(client, monkeypatch):
    acc, key = _connect(client), _trial(client)
    h = _auth(client, "alice")
    monkeypatch.setattr(rr, "runs_of", lambda *a, **k: None)
    monkeypatch.setattr(rr, "requests_of", lambda *a, **k: None)
    monkeypatch.setattr(rr, "open_run", lambda *a, **k: None)
    listed = client.get(f"{BASE}/{acc}/rule-runs", headers=h).json()
    assert listed["available"] is False and listed["runs"] == [] and listed["reason"] == runner.REASONS["store_unavailable"]
    reqs = client.get(REQS, headers=h).json()
    assert reqs["available"] is False and reqs["requests"] == [] and reqs["reason"]
    res = _start(client, acc, key)
    assert res.status_code == 503 and _code(res) == "store_unavailable"
