"""국면별 성과 나눔의 문 — `GET /api/v1/intraday/trials/{trial_key}/regime-split` (구현 계획 §7.3 · K2a).

나눔의 계산은 `test_regime_split.py`(순수 함수) · 국면은 `test_market_regime*.py` 가 건다. 여기서는 문과 기록이 지키는 약속:
실행이 날마다의 거래 · 이긴 거래를 시행 줄에 함께 남긴다(다중 비교가 읽는 값은 그대로) · 실행 답이 자기 시행 열쇠를 싣는다 ·
로그인 · ★남의 시행은 없는 시행과 같은 답★ · ★읽기만 — 모든 표의 줄 수와 실행 횟수 불변 · 시행을 남기지 않는다★ ·
답 = 같은 흐름과 같은 국면을 엔진에 넣은 값 · 시행과 국면의 등급을 함께 · 옛 시행 줄은 거래 수가 미상 + 사유 ·
운영에서 합성 시행 · 합성 지수는 나누지 않는다 · 저장소 장애 ≠ 없음 · 흐름이 깨졌으면 지어내지 않는다.
"""
from __future__ import annotations

import os
import tempfile

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

import src.api.intraday_regime_split_routes as routes
import src.data.minute_bars as mb
import src.database as dbmod
from src.data import intraday_trials as trials
from src.domain.auth_identity import ROLE_ANALYST
from src.engine import regime_split as rs
from src.engine.intraday import validate as validation
from tests.route_walk import flat_routes

URL = "/api/v1/intraday/trials/{key}/regime-split"
SIM = "/api/v1/intraday/simulate"
REGIME = "/api/v1/intraday/market-regime"
_SECRET = "intraday-regime-split-route-test-secret-0123456789"
DAYS = ["2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05", "2026-03-06"]
BODY = {"tickers": ["005930", "000660"], "from": DAYS[0], "to": DAYS[-1],
        "rule": {"kind": "opening_range_breakout", "params": {"minutes": 5}},
        "position": {"amount": 1_000_000}, "costs": {"commission_bp": 1.5, "slippage_ticks": 1}}
Q = {"index": "KOSPI", "k": 2}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp.name}")
    monkeypatch.setenv("AUTH_SECRET", _SECRET)
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    monkeypatch.setenv("MINUTE_BARS_DIR", str(tmp_path / "bars"))
    monkeypatch.setattr(dbmod, "DATABASE_URL", f"sqlite:///{tmp.name}", raising=False)
    dbmod.reset_session()
    dbmod.init_db()
    dbmod.create_user("alice", "alice-pw", role=ROLE_ANALYST)
    dbmod.create_user("bob", "bob-pw", role=ROLE_ANALYST)
    mb.clear_cache()

    from src.app_factory import create_app
    with TestClient(create_app()) as c:
        yield c

    mb.clear_cache()
    dbmod.reset_session()
    try:
        os.unlink(tmp.name)
    except OSError:
        pass


def login(client, who: str) -> dict[str, str]:
    tok = client.post("/api/v1/auth/login", json={"username": who, "password": f"{who}-pw"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture()
def auth(client) -> dict[str, str]:
    return login(client, "alice")


def run_trial(client, auth) -> dict:
    for d in DAYS:
        mb.collect_day(BODY["tickers"], d)
    mb.clear_cache()
    js = client.post(SIM, json=BODY, headers=auth).json()
    assert js["trial"]["recorded"] is True, js.get("trial")
    return js


def row_counts() -> dict[str, int]:
    eng = dbmod.get_engine()
    out = {}
    with eng.connect() as c:
        for t in inspect(eng).get_table_names():
            out[t] = int(c.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar())
    return out


def plant(grade: str, daily: dict, start: str = DAYS[0], end: str = DAYS[-1]) -> str:
    made = trials.record("alice", grade=grade, setting={"rule": {"kind": "planted", "params": {"grade": grade}}},
                         tickers=["005930"], start=start, end=end, daily=daily)
    return made["trial_key"]


def frame(dates: list[str], closes, source: str) -> pd.DataFrame:
    df = pd.DataFrame({"open": closes, "high": closes, "low": closes, "close": closes, "volume": 0.0}, index=pd.to_datetime(dates))
    df.attrs.update(source=source, coverage_ok=True, coverage_reason=None)
    return df


def walk_frame(source: str) -> pd.DataFrame:
    dates = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2021-01-01", "2026-03-31")]
    rng = np.random.default_rng(3)
    return frame(dates, 2500.0 * np.exp(np.cumsum(rng.normal(0.0, 0.01, len(dates)))), source)


def fake_index(monkeypatch, df: pd.DataFrame):
    import src.api.intraday_market_regime_routes as k1
    monkeypatch.setattr(k1, "load_index_daily", lambda code, start, end: df)


# ── 기록 — 날마다의 거래 · 이긴 거래 · 시행 열쇠 ─────────────────────────────────────────────────
def test_daily_values_carry_trades_and_wins_per_day_without_changing_the_values():
    journal = {"breakdowns": {"basis": "net", "daily": [
        {"key": "2026-03-03", "n": 2, "wins": 1, "total": 150.0}, {"key": "2026-03-05", "n": 1, "wins": 0, "total": -40.0}]}}
    out = validation.daily_values(journal, ["2026-03-05", "2026-03-02", "2026-03-03", "2026-03-05"])
    assert out == {"basis": "net", "values": [0.0, 150.0, -40.0], "trades": [0, 2, 1], "wins": [0, 1, 0]}


def test_a_run_keeps_trades_and_wins_per_day_and_answers_its_trial_key(client, auth):
    js = run_trial(client, auth)
    key = js["trial"]["trial_key"]
    assert isinstance(key, str) and len(key) >= 16
    got = trials.daily_of("alice", key)
    assert got["found"] is True and got["grade"] == "E0" and (got["from"], got["to"]) == (DAYS[0], DAYS[-1])
    daily = got["daily"]
    days = sorted(set(daily["dates"]))
    rows = {r["key"]: r for r in js["journal"]["breakdowns"]["daily"]}
    assert daily["trades"] == [rows[d]["n"] if d in rows else 0 for d in days]
    assert daily["wins"] == [rows[d]["wins"] if d in rows else 0 for d in days]
    assert sum(daily["trades"]) > 0                                       # 전제 — 거래가 있었다(공허하지 않다)


def test_a_failed_record_answers_no_trial_key(client, auth, monkeypatch):
    monkeypatch.setattr(trials, "record", lambda *a, **k: None)
    for d in DAYS:
        mb.collect_day(BODY["tickers"], d)
    mb.clear_cache()
    trial = client.post(SIM, json=BODY, headers=auth).json()["trial"]
    assert trial["recorded"] is False and trial["trial_key"] is None


# ── 문 ───────────────────────────────────────────────────────────────────────────────────
def test_the_door_is_mounted_and_needs_a_login(client):
    walked = {(m, r.path) for r in flat_routes(client.app) for m in (getattr(r, "methods", None) or [])}
    assert ("GET", "/api/v1/intraday/trials/{trial_key}/regime-split") in walked
    assert client.get(URL.format(key="x" * 64), params=Q).status_code == 401


@pytest.mark.parametrize("q", [{"index": "KOSPI"}, {"k": 2}, {"index": "NASDAQ", "k": 2}, {"index": "KOSPI", "k": 5},
                               {"index": "KOSPI", "k": 1}])
def test_index_and_k_are_required_and_bounded(client, auth, q):
    assert client.get(URL.format(key="x" * 64), params=q, headers=auth).status_code == 422


def test_someone_elses_trial_is_answered_like_a_missing_one(client, auth):
    key = run_trial(client, auth)["trial"]["trial_key"]
    theirs = client.get(URL.format(key=key), params=Q, headers=login(client, "bob"))
    missing = client.get(URL.format(key="f" * 64), params=Q, headers=auth)
    assert theirs.status_code == missing.status_code == 404
    assert theirs.json() == missing.json()


def test_the_split_reads_only_and_records_no_trial(client, auth):
    key = run_trial(client, auth)["trial"]["trial_key"]
    before, runs = row_counts(), trials.daily_of("alice", key)["runs"]
    for k in (2, 3):
        assert client.get(URL.format(key=key), params={"index": "KOSPI", "k": k}, headers=auth).status_code == 200
    assert row_counts() == before and trials.daily_of("alice", key)["runs"] == runs


def test_the_answer_is_the_engine_on_the_trial_flow_and_the_regime_days(client, auth):
    key = run_trial(client, auth)["trial"]["trial_key"]
    js = client.get(URL.format(key=key), params={"index": "KOSPI", "k": 3}, headers=auth).json()
    regime = client.get(REGIME, params={"index": "KOSPI", "k": 3, "from": DAYS[0], "to": DAYS[-1]}, headers=auth).json()
    want = rs.split_by_regime(trials.daily_of("alice", key)["daily"], regime["days"], 3)
    assert js["split"] == want and js["empty"] is None
    assert (js["trial_key"], js["index"], js["k"], js["from"], js["to"]) == (key, "KOSPI", 3, DAYS[0], DAYS[-1])
    assert (js["trial_grade"], js["regime_grade"], js["mock"]) == ("E0", "E0", True)
    assert js["notes"] == list(routes.NOTES) and len(js["notes"]) == 5
    assert sum(s["days"] for s in want["states"]) > 0                     # 전제 — 국면이 있는 날이 있다


def test_the_trial_grade_and_the_regime_grade_are_each_their_own(client, auth):
    """시행 등급은 그 시행 분봉의 출처, 국면 등급은 지수 일봉의 출처 — 하나로 다른 하나를 채우지 않는다
    (mock 서버: 실데이터 표시의 시행 · 합성 지수). 짝: 등급이 E0 · E3 가 아닌 시행은 미상(`None`)이지 그 글자가 아니다."""
    key = plant("E3", {"basis": "net", "dates": DAYS, "values": [1.0] * 5, "trades": [1] * 5, "wins": [1] * 5})
    js = client.get(URL.format(key=key), params=Q, headers=auth).json()
    assert js["empty"] is None and (js["trial_grade"], js["regime_grade"], js["mock"]) == ("E3", "E0", True)
    key = plant("unknown", {"basis": "net", "dates": DAYS, "values": [1.0] * 5, "trades": [1] * 5, "wins": [1] * 5})
    js = client.get(URL.format(key=key), params=Q, headers=auth).json()
    assert js["empty"] is None and (js["trial_grade"], js["regime_grade"]) == (None, "E0")


def test_an_old_trial_without_trade_counts_says_so_instead_of_zero(client, auth):
    key = plant("E0", {"basis": "net", "dates": DAYS, "values": [10.0, -5.0, 0.0, 7.0, 3.0]})
    split = client.get(URL.format(key=key), params=Q, headers=auth).json()["split"]
    assert split["trades_known"] is False and split["trades_reason"] == rs.REASONS["no_trade_counts"]
    low = split["total"].pop("low_conf_days")
    assert split["total"] == {"days": 5, "trades": None, "wins": None, "win_rate": None, "pnl": 15.0}
    assert low == sum(s["low_conf_days"] for s in split["states"])        # 확률은 거래 수와 무관하게 센다


def test_a_flow_that_does_not_line_up_is_not_split(client, auth):
    key = plant("E0", {"basis": "net", "dates": DAYS, "values": [1.0, 2.0], "trades": [1, 1], "wins": [1, 0]})
    js = client.get(URL.format(key=key), params=Q, headers=auth).json()
    assert js["split"] is None and js["empty"] == {"reason": "flow_mismatch", "message": routes.EMPTY["flow_mismatch"]}


@pytest.mark.parametrize("bad", ["x", float("nan")])
def test_a_flow_that_cannot_be_read_says_so_instead_of_blaming_the_length(client, auth, bad):
    """값이 숫자가 아니거나 NaN 인 흐름 — '길이가 안 맞는다'가 아니라 '읽을 수 없다'(사유가 원인과 같아야 한다 · NaN 을 더해 사유 없는 500 을 내지 않는다)."""
    key = plant("E0", {"basis": "net", "dates": DAYS, "values": [1.0, bad, 0.0, 0.0, 0.0], "trades": [1] * 5, "wins": [0] * 5})
    js = client.get(URL.format(key=key), params=Q, headers=auth).json()
    assert js["split"] is None and js["empty"] == {"reason": "bad_flow", "message": routes.EMPTY["bad_flow"]}


def test_a_regime_number_outside_k_is_not_blamed_on_the_trial(client, auth, monkeypatch):
    """국면 계산이 1 ~ k 밖의 번호를 내면(계산 결함) 시행 기록의 탓으로 적지 않는다 — 나누지 않고 그 사유."""
    key = plant("E0", {"basis": "net", "dates": DAYS, "values": [1.0] * 5, "trades": [1] * 5, "wins": [1] * 5})
    days = [{"date": d, "probs": [0.05, 0.05, 0.9], "top": 3, "top_prob": 0.9, "reason": None} for d in DAYS]
    monkeypatch.setattr(routes, "regime_answer", lambda index, k, f, t: {
        "grade": "E0", "grade_reason": None, "source": "mock", "coverage": {"ok": True, "reason": None}, "empty": None, "days": days})
    js = client.get(URL.format(key=key), params=Q, headers=auth).json()       # Q 는 국면 2개 — 번호 3 은 밖이다
    assert js["split"] is None and js["empty"] == {"reason": "state_out_of_range", "message": routes.EMPTY["state_out_of_range"]}


@pytest.mark.parametrize("flow", [{}, {"basis": "net", "dates": [], "values": []}, {"basis": "net", "dates": DAYS}],
                         ids=["nothing", "no_days", "no_values"])
def test_a_trial_without_a_flow_is_not_split(client, auth, flow):
    """흐름이 없거나 날이 없거나 값이 없으면 나누지 않는다 — 0일 · 0원뿐인 표(자료처럼 보이는 빈 답)를 내지 않는다."""
    key = plant("E0", flow)
    js = client.get(URL.format(key=key), params=Q, headers=auth).json()
    assert js["split"] is None and js["empty"] == {"reason": "no_flow", "message": routes.EMPTY["no_flow"]}


def test_a_store_failure_is_unknown_not_missing(client, auth, monkeypatch):
    monkeypatch.setattr(trials, "daily_of", lambda user, key: None)
    r = client.get(URL.format(key="a" * 64), params=Q, headers=auth)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "store_unavailable"


def test_when_the_trial_store_itself_breaks_the_answer_is_unknown_not_missing(client, auth, monkeypatch):
    """`daily_of` 의 장애 길 그대로 — 저장소를 읽지 못하면 `None`(모른다) → 503. `{found: False}`(없다 → 404)가 아니다.
    짝: 기록한 흐름이 없는 시행은 찾되 `daily` 가 `None`(빈 흐름을 지어내지 않는다)."""
    key = plant("E0", {})
    got = trials.daily_of("alice", key)
    assert got["found"] is True and got["daily"] is None

    def broken():
        raise RuntimeError("db down")
    monkeypatch.setattr(trials, "_engine", broken)
    assert trials.daily_of("alice", key) is None
    r = client.get(URL.format(key=key), params=Q, headers=auth)
    assert r.status_code == 503 and r.json()["detail"] == {"code": "store_unavailable", "reason": routes.REASONS["store_unavailable"]}


def test_a_regime_store_failure_is_not_absence(client, auth, monkeypatch):
    key = plant("E3", {"basis": "net", "dates": DAYS, "values": [1.0] * 5, "trades": [1] * 5, "wins": [1] * 5})
    df = walk_frame("db")
    df.attrs["db_error"] = True
    fake_index(monkeypatch, df)
    js = client.get(URL.format(key=key), params=Q, headers=auth).json()
    assert js["split"] is None and js["empty"]["reason"] == "store_error"


def test_in_production_a_synthetic_trial_is_not_split(client, auth, monkeypatch):
    key = plant("E0", {"basis": "net", "dates": DAYS, "values": [1.0] * 5, "trades": [1] * 5, "wins": [1] * 5})
    fake_index(monkeypatch, walk_frame("db"))
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    js = client.get(URL.format(key=key), params=Q, headers=auth).json()
    assert js["split"] is None and js["empty"] == {"reason": "synthetic_trial_in_production",
                                                   "message": routes.EMPTY["synthetic_trial_in_production"]}


def test_in_production_a_synthetic_index_is_not_split_and_a_loaded_one_is(client, auth, monkeypatch):
    key = plant("E3", {"basis": "net", "dates": DAYS, "values": [1.0] * 5, "trades": [1] * 5, "wins": [1] * 5})
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    fake_index(monkeypatch, walk_frame("mock"))
    js = client.get(URL.format(key=key), params=Q, headers=auth).json()
    assert js["split"] is None and js["empty"]["reason"] == "synthetic_in_production"
    fake_index(monkeypatch, walk_frame("db"))                             # 짝 — 적재된 지수는 나눈다
    js = client.get(URL.format(key=key), params=Q, headers=auth).json()
    assert js["empty"] is None and (js["trial_grade"], js["regime_grade"], js["mock"]) == ("E3", "E3", False)
    js["split"]["total"].pop("low_conf_days")
    assert js["split"]["total"] == {"days": 5, "trades": 5, "wins": 5, "win_rate": 1.0, "pnl": 5.0}
