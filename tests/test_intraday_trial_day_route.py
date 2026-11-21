"""분봉 하루 보기의 문 — `GET /api/v1/intraday/trials/{trial_key}/day` (G4 · 구현 계획 §5).

★핵심 계약(퀀트)★: 하루 보기의 체결 = 실행(`/simulate`)이 낸 체결을 그 날 · 종목으로 거른 것(시각 · 방향 · 수량 · 가격 · 종류).
그날 시행의 ★모든 종목★을 다시 돌리므로 동시 보유 상한처럼 종목 사이에 걸리는 제약도 같다(짝: 한 종목만 돌리면 달라지는 날이 있다).
봉은 시뮬레이터가 본 봉(정규장만 · 시각 순)이고, 다시 계산한 그날 값은 시행 줄에 남은 그날 값과 매번 견준다.
★읽기만★ — 시행을 남기지 않고 아무 표에도 쓰지 않는다 · 남의 시행 = 없는 시행 · 기록 장애 ≠ 없음 · 빈 배열만 주지 않는다.
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

import src.data.minute_bars as mb
import src.database as dbmod
from src.api import intraday_routes
from src.data import intraday_trials as trials
from src.domain.auth_identity import ROLE_ANALYST
from src.engine import intraday as engine
from src.engine.intraday import setting
from src.engine.intraday.simulator import FILL_KINDS
from tests.route_walk import flat_routes

ROOT = Path(__file__).resolve().parents[1]
URL = "/api/v1/intraday/trials/{key}/day"
SIM = "/api/v1/intraday/simulate"
_SECRET = "intraday-trial-day-route-test-secret-0123456789"
DAYS = ["2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05", "2026-03-06"]
TICKERS = ["000660", "005930", "035420"]
#: 종목 사이에 걸리는 제약(동시 보유 1) · 손절 · 익절 · 시각 청산 · 장 마감 · 참여율로 나뉜 체결이 나오게 고른 설정
BODY = {"tickers": TICKERS, "from": DAYS[0], "to": DAYS[-1],
        "rule": {"kind": "opening_range_breakout", "params": {"minutes": 5}},
        "position": {"amount": 30_000_000, "stop_pct": 0.4, "target_pct": 0.8, "time_exit": "1430",
                     "max_open_positions": 1, "max_entries_per_ticker": 3},
        "costs": {"commission_bp": 1.5, "slippage_ticks": 1, "participation_cap": 0.02}}


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


def record_trial(client, auth, monkeypatch):
    """분봉을 심고 실행해 시행 하나를 남긴다 → (실행 답, 실행이 엔진에서 받은 답). 엔진의 답은 실행 문이 실제로 부른 것을 엿본다."""
    for d in DAYS:
        mb.collect_day(TICKERS, d)
    mb.clear_cache()
    seen: list[dict] = []
    real = engine.run
    monkeypatch.setattr(engine, "run", lambda *a, **k: seen.append(real(*a, **k)) or seen[-1])
    js = client.post(SIM, json=BODY, headers=auth).json()
    assert js["trial"]["recorded"] is True, js.get("trial")
    assert len(seen) == 1
    monkeypatch.setattr(engine, "run", real)
    return js, seen[0]


@pytest.fixture()
def recorded(client, auth, monkeypatch):
    """모의 종목 마스터는 세 종목의 시장을 모른다 → 매도세를 몰라 이 시행의 기준은 비용 전(gross)이다(관측)."""
    return record_trial(client, auth, monkeypatch)


#: 종목 마스터가 아는 시장 · 상품(코스피 주식) — 매도세를 알아 모든 거래의 비용을 안다.
KNOWN_MARKET = {"market": "KOSPI", "group_code": "ST"}


@pytest.fixture()
def recorded_net(client, auth, monkeypatch):
    """종목 마스터가 세 종목의 시장 · 상품을 아는 실행 → 모든 거래의 비용을 알아 시행의 기준이 비용 뒤(net)다.
    마스터를 바꾼 채로 둔다 — 하루 보기도 같은 마스터로 다시 계산한다."""
    real = intraday_routes.master_lookup

    def knowing():
        known = real()
        return lambda t: {**(known(t) or {}), **KNOWN_MARKET}
    monkeypatch.setattr(intraday_routes, "master_lookup", knowing)
    return record_trial(client, auth, monkeypatch)


def day(client, auth, key: str, **q) -> dict:
    r = client.get(URL.format(key=key), params=q, headers=auth)
    assert r.status_code == 200, r.text
    return r.json()


def run_fills(out: dict, date: str, ticker: str) -> list[tuple]:
    """실행이 낸 체결을 그 날 · 종목으로 거른 것 — (시각, 방향, 수량, 가격, 종류)."""
    kinds = {e["row"]: e["kind"] for e in out["events"]}
    return [(f["executed_at"][11:], f["side"], f["quantity"], f["price"], kinds[i])
            for i, f in enumerate(out["fills"]) if f["executed_at"][:10] == date and f["symbol"] == ticker]


def view_fills(js: dict) -> list[tuple]:
    return [(f["time"], f["side"], f["quantity"], f["price"], f["kind"]) for f in js["fills"]]


def row_counts() -> dict[str, int]:
    eng = dbmod.get_engine()
    with eng.connect() as c:
        return {t: int(c.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar()) for t in inspect(eng).get_table_names()}


def bar_files(tmp: Path) -> dict[str, tuple[int, int]]:
    return {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in sorted(tmp.iterdir())}


# ── 핵심 계약: 하루 보기 = 실행의 그날 ──────────────────────────────────────────────────────────

def test_the_day_view_shows_exactly_the_fills_the_run_made_on_that_day_for_that_ticker(client, auth, recorded):
    js, out = recorded
    key = js["trial"]["trial_key"]
    kinds_seen: set[str] = set()
    pairs = crossed = 0
    for d in DAYS:
        for t in TICKERS:
            got = day(client, auth, key, date=d, ticker=t)
            want = run_fills(out, d, t)
            assert view_fills(got) == want, (d, t)
            # 같은 날 다른 종목의 체결 수 = 실행이 그날 다른 종목에 낸 체결 수(화면의 '같은 날 다른 종목의 체결 n건')
            others = sum(1 for f in out["fills"] if f["executed_at"][:10] == d and f["symbol"] != t)
            assert got["others"] == {"fills": others}, (d, t)
            kinds_seen |= {f[4] for f in want}
            pairs += bool(want)
            crossed += bool(want) and others > 0
    assert pairs >= 3                                   # 공허하지 않다 — 체결이 있는 (날, 종목)이 여럿
    assert crossed >= 1                                 # 공허하지 않다 — 그 종목도 다른 종목도 체결이 있는 날이 있다
    assert {"entry_signal", "stop", "target", "time_exit", "exit_remainder"} <= kinds_seen, kinds_seen


#: 나머지 체결 종류(미리 건 가격의 진입 · 추적 손절 · 청산 조건 · 장 마감 청산)를 내는 설정 둘 — 위의 설정과 합쳐 아홉 종류 모두
OTHER_SETTINGS = {
    "volatility_trail": ({"rule": {"kind": "volatility_breakout", "params": {}},
                          "position": {"amount": 5_000_000, "trail_pct": 0.3, "max_entries_per_ticker": 2},
                          "costs": {"commission_bp": 1.5}}, {"entry_stop", "trail"}),
    "vwap_exit": ({"rule": {"kind": "vwap_cross", "params": {}}, "position": {"amount": 5_000_000, "max_entries_per_ticker": 3},
                   "costs": {"commission_bp": 1.5}}, {"rule_exit", "session_end"}),
}


@pytest.mark.parametrize("name", sorted(OTHER_SETTINGS))
def test_the_day_view_matches_the_run_for_the_other_fill_kinds_too(client, auth, monkeypatch, name):
    setting_part, kinds_wanted = OTHER_SETTINGS[name]
    for d in DAYS:
        mb.collect_day(TICKERS, d)
    mb.clear_cache()
    seen: list[dict] = []
    real = engine.run
    monkeypatch.setattr(engine, "run", lambda *a, **k: seen.append(real(*a, **k)) or seen[-1])
    js = client.post(SIM, json={"tickers": TICKERS, "from": DAYS[0], "to": DAYS[-1], **setting_part}, headers=auth).json()
    monkeypatch.setattr(engine, "run", real)
    out, key = seen[0], js["trial"]["trial_key"]
    kinds_seen: set[str] = set()
    for d in DAYS:
        for t in TICKERS:
            want = run_fills(out, d, t)
            assert view_fills(day(client, auth, key, date=d, ticker=t)) == want, (name, d, t)
            kinds_seen |= {f[4] for f in want}
    assert kinds_wanted <= kinds_seen, kinds_seen


def test_every_ticker_of_the_trial_is_run_because_limits_cross_tickers(client, auth, recorded):
    """짝: 그날을 한 종목만으로 돌리면 동시 보유 상한이 풀려 체결이 달라지는 (날, 종목)이 있다 — 그래서 문은 모든 종목을 돌린다."""
    js, out = recorded
    assert out["assumptions"].get("entry_blocked_max_open", 0) > 0, out["assumptions"]   # 제약이 실제로 걸렸다
    rule, position, costs = setting.parts_of({k: BODY[k] for k in ("rule", "position", "costs")} | {
        "rule": {"kind": BODY["rule"]["kind"], "params": intraday_routes.rules.resolve(BODY["rule"]["kind"], BODY["rule"]["params"])},
        "position": intraday_routes.PositionBody(**BODY["position"]).model_dump(),
        "costs": intraday_routes.CostsBody(**BODY["costs"]).model_dump()})
    differs = 0
    for d in DAYS:
        for t in TICKERS:
            prepared = intraday_routes.prepared_day("alice", [t], rule, intraday_routes.date.fromisoformat(d))
            alone = engine.run([prepared[0]], rule, position, costs, rules=prepared[1], master=intraday_routes.master_lookup())
            kinds = {e["row"]: e["kind"] for e in alone["events"]}
            solo = [(f["executed_at"][11:], f["side"], f["quantity"], f["price"], kinds[i]) for i, f in enumerate(alone["fills"])]
            differs += solo != run_fills(out, d, t)
    assert differs > 0


def test_the_bars_are_the_regular_session_bars_the_simulator_saw(client, auth, recorded, tmp_path):
    js, _ = recorded
    key = js["trial"]["trial_key"]
    d, t = DAYS[1], TICKERS[0]
    frame = mb._read_day_file(mb._existing_day_path(d))
    extra = frame[frame["ticker"] == t].head(2).copy()
    extra["time"] = ["083000", "160500"]                                   # 장전 · 시간외 봉을 심는다
    mb._write_day_file(__import__("pandas").concat([frame, extra], ignore_index=True), d)
    mb.clear_cache()
    got = day(client, auth, key, date=d, ticker=t)
    times = got["bars"]["time"]
    assert "08:30:00" not in times and "16:05:00" not in times
    rules = intraday_routes.session_rules()
    regular = sorted(x for x in frame[frame["ticker"] == t]["time"].astype(str)
                     if rules["open"] <= x[:4] <= rules["close"])
    assert times == [f"{x[:2]}:{x[2:4]}:{x[4:6]}" for x in regular]
    assert len(got["bars"]["open"]) == len(times) == len(got["bars"]["volume"])


def test_a_ticker_the_simulator_skipped_that_day_shows_the_reason_instead_of_bars(client, auth, recorded):
    js, _ = recorded
    key = js["trial"]["trial_key"]
    d, t = DAYS[2], TICKERS[1]
    frame = mb._read_day_file(mb._existing_day_path(d))
    mb._write_day_file(frame[frame["ticker"] != t], d)                      # 그 종목의 봉을 지운다
    mb.clear_cache()
    got = day(client, auth, key, date=d, ticker=t)
    assert got["bars"] is None and got["fills"] == []
    assert got["skipped"]["reason"] == "no_bars" and got["skipped"]["message"]


# ── 정합: 다시 계산한 그날 = 시행 줄의 그날 ─────────────────────────────────────────────────────

def test_a_fill_at_a_minute_without_a_bar_of_that_ticker_is_kept_not_dropped(client, auth, monkeypatch):
    """한 종목의 봉이 일찍 끝난 날 — 그 종목의 장 마감 청산은 ★하루의 마지막 시각★(다른 종목의 마지막 봉)에 난다(시뮬레이터의 가정).
    그 시각에는 그 종목의 봉이 없다 → 답은 그 체결을 빼지 않는다(화면이 그리지 않고 세어 줄로 적는다). 짝: 봉은 그 종목이 본 봉뿐이다."""
    import pandas as pd
    d = "2026-03-02"
    flat = [("000660", t, 10_000, 10_010, 9_990, 10_000, 1_000, "kis") for t in ("090000", "090100", "090200", "090300", "090400", "090500")]
    early = [("005930", "090000", 10_000, 10_020, 9_990, 10_000, 1_000, "kis"), ("005930", "090100", 10_000, 10_060, 10_000, 10_060, 1_000, "kis"),
             ("005930", "090200", 10_070, 10_100, 10_060, 10_090, 1_000, "kis")]
    mb._write_day_file(pd.DataFrame(flat + early, columns=["ticker", "time", "open", "high", "low", "close", "volume", "source"]), d)
    mb.clear_cache()
    seen: list[dict] = []
    real = engine.run
    monkeypatch.setattr(engine, "run", lambda *a, **k: seen.append(real(*a, **k)) or seen[-1])
    body = {"tickers": ["000660", "005930"], "from": d, "to": d, "rule": {"kind": "opening_range_breakout", "params": {"minutes": 1}},
            "position": {"amount": 1_000_000}, "costs": {"commission_bp": 1.5}}
    js = client.post(SIM, json=body, headers=auth).json()
    monkeypatch.setattr(engine, "run", real)
    assert js["trial"]["recorded"] is True and len(seen) == 1
    v = day(client, auth, js["trial"]["trial_key"], date=d, ticker="005930")
    assert v["bars"]["time"] == ["09:00:00", "09:01:00", "09:02:00"]
    assert view_fills(v) == run_fills(seen[0], d, "005930")
    assert [(f["time"], f["side"], f["kind"]) for f in v["fills"]] == [("09:02:00", "buy", "entry_signal"), ("09:05:00", "sell", "session_end")]
    assert "09:05:00" not in v["bars"]["time"]                                  # 그 종목의 봉이 없는 시각의 체결 — 빠지지 않았다
    assert v["check"]["status"] == "same" and v["others"]["fills"] == 0


def test_every_answer_carries_the_fact_lines_including_the_ones_that_draw_nothing(client, auth, recorded, monkeypatch):
    """사실 줄(이 그림이 무엇이고 무엇이 아닌지)은 늘 싣는다 — 그린 답에도, 그리지 않은 답(사유만 있는 답)에도 같은 줄 그대로."""
    from src.api import intraday_trial_day_routes as route
    js, _ = recorded
    key = js["trial"]["trial_key"]
    drawn = day(client, auth, key)
    assert drawn["empty"] is None and drawn["facts"] == list(route.FACTS) and len(route.FACTS) >= 5
    monkeypatch.setattr(setting, "parts_of", lambda _s: (_ for _ in ()).throw(setting.SettingUnreadable("KeyError")))
    blank = day(client, auth, key)
    assert blank["empty"]["reason"] == "bad_setting" and blank["bars"] is None
    assert blank["facts"] == list(route.FACTS)


def test_the_recomputed_day_is_checked_against_the_stored_day(client, auth, recorded):
    js, _ = recorded
    key = js["trial"]["trial_key"]
    got = day(client, auth, key, date=DAYS[0], ticker=TICKERS[0])
    assert got["check"]["status"] == "same" and got["check"]["message"]
    assert got["check"]["stored"]["trades"] == got["check"]["recomputed"]["trades"]


def test_a_day_file_changed_after_the_run_is_reported_as_different(client, auth, recorded):
    js, out = recorded
    key = js["trial"]["trial_key"]
    traded = sorted({f["executed_at"][:10] for f in out["fills"]})
    d = traded[0]
    frame = mb._read_day_file(mb._existing_day_path(d))
    for col in ("open", "high", "low", "close"):
        frame[col] = frame.groupby("ticker")[col].transform("first")        # 하루 내내 같은 값 — 돌파가 사라진다
    mb._write_day_file(frame, d)
    mb.clear_cache()
    got = day(client, auth, key, date=d, ticker=TICKERS[0])
    assert got["check"]["status"] == "different"
    assert "바뀌" in got["check"]["message"]


@pytest.mark.parametrize("change, status", [
    ({}, "same"), ({"values": 0.005}, "same"), ({"values": -0.009}, "same"),                 # 허용 안쪽(0.01원 이하)
    ({"values": 0.02}, "different"), ({"values": -0.5}, "different"),                         # 손익만 0.01원을 넘게 다르다
    ({"trades": 1}, "different"), ({"wins": 1}, "different"),                                 # 손익이 같아도 거래 수 · 이긴 수가 다르다
])
def test_the_stored_day_matches_only_when_every_field_matches(client, auth, recorded, monkeypatch, change, status):
    """'같음' = 거래 수 · 이긴 거래 수가 같고 손익 차가 0.01원 이하(화면이 보이는 가장 작은 단위 1원보다 작다) — 같은 기준(비용 뒤)에서.
    남은 그날 값의 한 칸만 옮겨 본다(다시 계산한 값은 그대로) — 어느 칸이 달라도 '다름' ↔ 허용 안쪽이면 같음(짝).
    기준(비용 전 · 뒤)이 다른 경우는 아래 두 시험이 건다."""
    js, out = recorded
    key = js["trial"]["trial_key"]
    d = sorted({f["executed_at"][:10] for f in out["fills"]})[0]
    real = trials.daily_of

    def nudged(u, k):
        got = real(u, k)
        daily = dict(got["daily"])
        i = daily["dates"].index(d)
        for field, delta in change.items():
            daily[field] = [v + delta if j == i else v for j, v in enumerate(daily[field])]
        return {**got, "daily": daily}

    monkeypatch.setattr(trials, "daily_of", nudged)
    got = day(client, auth, key, date=d, ticker=TICKERS[0])
    assert got["check"]["status"] == status, got["check"]
    kept, again = got["check"]["stored"], got["check"]["recomputed"]
    assert abs(kept["total"] - again["total"] - change.get("values", 0)) < 1e-9
    assert kept["trades"] - again["trades"] == change.get("trades", 0) and kept["wins"] - again["wins"] == change.get("wins", 0)
    assert kept["basis"] == again["basis"]                         # 같은 기준에서 견줬다(이 시행은 비용 전)


def gross_daily(out: dict, dates: list[str]) -> dict:
    """실행이 비용 전(gross) 기준이었다면 시행 줄에 남겼을 일별 값 — 같은 거래의 비용 전 손익으로(`validate.daily_values` 와 같은 셈:
    청산한 날로 묶고 · 손익 > 0 이면 이긴 거래)."""
    by_day: dict[str, list[float]] = {}
    for r in out["journal"]["trades"]:
        by_day.setdefault(r["closed_at"][:10], []).append(float(r["gross"]))
    assert len(out["journal"]["trades"]) == out["journal"]["trades_total"]            # 잘린 표가 아니다 — 모든 거래를 셌다
    return {"basis": "gross", "dates": list(dates), "values": [float(sum(by_day.get(d, []))) for d in dates],
            "trades": [len(by_day.get(d, [])) for d in dates], "wins": [sum(1 for p in by_day.get(d, []) if p > 0) for d in dates]}


def test_a_trial_kept_before_costs_is_checked_before_costs_even_when_the_day_alone_knows_its_costs(client, auth, recorded_net, monkeypatch):
    """시행 줄의 기준은 실행 ★전체★가 정한다 — 한 거래라도 비용을 모르면 모든 날이 비용 전이다. 그날만 다시 돌리면 그날 거래의 비용을 다
    알아 비용 뒤가 될 수 있다 → 다시 계산한 값을 ★시행 줄의 기준으로★ 견준다(기준이 다르다는 것만으로 '다름'이 아니다).
    짝: 같은 날의 비용 뒤 값에 비용 전이라는 이름표만 붙여 두면 '다름'이다(이름표가 아니라 값을 견준다)."""
    js, out = recorded_net
    key = js["trial"]["trial_key"]
    real = trials.daily_of
    kept = real("alice", key)["daily"]
    assert kept["basis"] == "net"                                   # 이 시행은 비용을 다 안다 — 비용 전으로 남은 시행을 흉내 낸다
    gross = gross_daily(out, kept["dates"])
    d = sorted({f["executed_at"][:10] for f in out["fills"]})[0]
    i = kept["dates"].index(d)
    assert kept["values"][i] - gross["values"][i] < -1              # 그날 비용이 있다 — 비용 뒤로 견줬다면 '다름'이었다
    monkeypatch.setattr(trials, "daily_of", lambda u, k: {**real(u, k), "daily": gross})
    got = day(client, auth, key, date=d, ticker=TICKERS[0])
    assert got["check"]["status"] == "same", got["check"]
    assert got["check"]["stored"]["basis"] == got["check"]["recomputed"]["basis"] == "gross"
    assert abs(got["check"]["recomputed"]["total"] - gross["values"][i]) <= 0.01
    assert got["check"]["recomputed"]["wins"] == gross["wins"][i] and got["check"]["recomputed"]["trades"] == gross["trades"][i]
    mislabeled = {**kept, "basis": "gross"}
    monkeypatch.setattr(trials, "daily_of", lambda u, k: {**real(u, k), "daily": mislabeled})
    assert day(client, auth, key, date=d, ticker=TICKERS[0])["check"]["status"] == "different"


def test_a_trial_kept_after_costs_is_different_when_the_recomputed_day_no_longer_knows_its_costs(client, auth, recorded_net, monkeypatch):
    """짝: 시행 줄은 비용 뒤인데 지금 다시 계산한 그날 거래의 비용을 모르면(종목 마스터가 시장을 모른다) 비용 뒤로 견줄 수 없다 → '다름'.
    비용 전 값을 비용 뒤인 것처럼 견주지 않는다 — 비용 정보가 바뀐 것은 실제로 달라진 것이다."""
    js, out = recorded_net
    key = js["trial"]["trial_key"]
    d = sorted({f["executed_at"][:10] for f in out["fills"]})[0]
    assert day(client, auth, key, date=d, ticker=TICKERS[0])["check"]["status"] == "same"      # 같은 마스터면 같다
    monkeypatch.setattr(intraday_routes, "master_lookup", lambda: (lambda _t: None))
    got = day(client, auth, key, date=d, ticker=TICKERS[0])
    assert got["check"]["stored"]["basis"] == "net"
    assert got["check"]["recomputed"]["basis"] == "gross" and got["check"]["status"] == "different", got["check"]
    # 짝: 값(손익 · 거래 수 · 이긴 수)이 다시 계산한 비용 전 값과 같아도 시행 줄이 비용 뒤라고 적혀 있으면 '다름'이다(기준을 본다)
    again = got["check"]["recomputed"]
    real = trials.daily_of

    def forged(u, k):
        row = real(u, k)
        daily = dict(row["daily"])
        i = daily["dates"].index(d)
        for field, value in (("values", again["total"]), ("trades", again["trades"]), ("wins", again["wins"])):
            daily[field] = [value if j == i else v for j, v in enumerate(daily[field])]
        return {**row, "daily": {**daily, "basis": "net"}}
    monkeypatch.setattr(trials, "daily_of", forged)
    same_numbers = day(client, auth, key, date=d, ticker=TICKERS[0])["check"]
    assert same_numbers["stored"]["total"] == same_numbers["recomputed"]["total"]
    assert same_numbers["stored"]["trades"] == same_numbers["recomputed"]["trades"]
    assert same_numbers["status"] == "different", same_numbers


def test_the_arming_day_prepares_every_ticker_of_the_trial_like_the_day_view(client):
    """하루 준비는 한 곳이다(`intraday_routes.prepared_day`) — 가동 · 관제의 하루(`broker_account_routes._day_of`)도 받은 ★모든 종목★을
    싣는다(동시 보유 상한이 종목 사이에 걸린다 · 가동은 시행의 종목을 모두 넘긴다). 짝: 한 종목만 주면 그 종목만 싣는다(지어내지 않는다)."""
    from datetime import date

    from src.api import broker_account_routes as bar
    from src.engine.intraday import rules
    mb.collect_day(TICKERS, DAYS[0])
    mb.clear_cache()
    spec = rules.build("opening_range_breakout", {"minutes": 5})
    every = bar._day_of("alice", list(TICKERS), spec, date.fromisoformat(DAYS[0]))
    assert every is not None and sorted(every[0].sessions) == sorted(TICKERS)
    one = bar._day_of("alice", TICKERS[:1], spec, date.fromisoformat(DAYS[0]))
    assert one is not None and sorted(one[0].sessions) == TICKERS[:1]


def test_a_trial_without_a_stored_day_cannot_be_checked(client, auth, recorded, monkeypatch):
    js, _ = recorded
    key = js["trial"]["trial_key"]
    real = trials.daily_of
    monkeypatch.setattr(trials, "daily_of", lambda u, k: {**real(u, k), "daily": None})
    got = day(client, auth, key, date=DAYS[0], ticker=TICKERS[0])
    assert got["check"]["status"] == "unknown" and got["check"]["message"]


# ── 기본값 · 고르기 · 이름표 · 왕복 줄 ─────────────────────────────────────────────────────────

def test_without_a_date_and_ticker_the_first_traded_day_and_its_first_filled_ticker_are_shown(client, auth, recorded):
    js, out = recorded
    key = js["trial"]["trial_key"]
    got = day(client, auth, key)
    first = min(out["fills"], key=lambda f: f["executed_at"])
    assert (got["date"], got["ticker"]) == (first["executed_at"][:10], first["symbol"])
    assert [c["date"] for c in got["choices"]["dates"]] == DAYS
    assert sum(c["trades"] for c in got["choices"]["dates"]) == js["journal"]["trades_total"]
    assert got["choices"]["tickers"] == sorted(TICKERS)


def _with_daily(real, **daily_change):
    """시행 줄의 일별 값 가운데 한 칸만 바꾸거나(값) 지운다(`None`) — 다시 계산은 그대로."""
    def daily_of(u, k):
        got = real(u, k)
        daily = {kk: v for kk, v in got["daily"].items() if daily_change.get(kk, 0) is not None}
        daily.update({kk: v for kk, v in daily_change.items() if v is not None})
        return {**got, "daily": daily}
    return daily_of


def test_the_default_day_is_the_first_day_the_stored_row_counts_trades_on_not_simply_the_first_day(client, auth, recorded, monkeypatch):
    """기본 날짜 = 시행 줄에 거래가 적힌 ★첫 날★ — 기간의 첫날이 아니다. 이 시행은 첫날에 거래가 있어 위 시험만으로는 둘이 갈리지 않는다.
    짝: 어느 날에도 거래가 적혀 있지 않으면 기간의 첫날 · 날마다의 거래 수를 모르면(옛 줄) 역시 첫날(모르는 것을 '거래 없음'으로 고르지 않는다)."""
    js, _ = recorded
    key = js["trial"]["trial_key"]
    real = trials.daily_of
    monkeypatch.setattr(trials, "daily_of", _with_daily(real, trades=[0, 0, 2, 0, 1]))
    got = day(client, auth, key)
    assert got["date"] == DAYS[2]
    assert [c["trades"] for c in got["choices"]["dates"]] == [0, 0, 2, 0, 1]
    monkeypatch.setattr(trials, "daily_of", _with_daily(real, trades=[0] * len(DAYS)))
    assert day(client, auth, key)["date"] == DAYS[0]
    monkeypatch.setattr(trials, "daily_of", _with_daily(real, trades=None))
    assert day(client, auth, key)["date"] == DAYS[0]


@pytest.mark.parametrize("trades", [None, [1, 2]], ids=["칸이 없는 옛 줄", "길이가 맞지 않는 줄"])
def test_without_per_day_trade_counts_the_choices_say_unknown_not_zero(client, auth, recorded, monkeypatch, trades):
    """날마다의 거래 수를 읽지 못하면 고르기 목록의 거래 수는 ★미상(`None`)★ — 0 이 아니다(미상 ≠ 0 · 화면은 '거래 수 미상').
    짝: 읽히는 줄이면 정수(위 시험 — 합 = 실행의 왕복 수)."""
    js, _ = recorded
    key = js["trial"]["trial_key"]
    monkeypatch.setattr(trials, "daily_of", _with_daily(trials.daily_of, trades=trades))
    got = day(client, auth, key)
    assert [c["date"] for c in got["choices"]["dates"]] == DAYS
    assert [c["trades"] for c in got["choices"]["dates"]] == [None] * len(DAYS)


def test_a_day_whose_minute_file_is_gone_says_not_loaded_instead_of_an_empty_picture(client, auth, recorded):
    """실행 뒤 그날의 분봉 파일이 사라지면(지움 · 옮김) 봉 대신 '적재되지 않음' 사유 — 사유 없는 빈 그림을 주지 않는다(침묵 폴백 금지).
    짝: 파일이 남은 다른 날은 그대로 그린다(지운 것이 그날만이다)."""
    from src.api import intraday_trial_day_routes as route
    js, _ = recorded
    key = js["trial"]["trial_key"]
    path = mb._existing_day_path(DAYS[1])
    assert path is not None and path.exists()
    path.unlink()
    mb.clear_cache()
    gone = day(client, auth, key, date=DAYS[1], ticker=TICKERS[0])
    assert gone["empty"] == {"reason": "not_loaded", "message": route.EMPTY["not_loaded"]}
    assert gone["bars"] is None and gone["fills"] == [] and gone["check"] is None
    kept = day(client, auth, key, date=DAYS[0], ticker=TICKERS[0])
    assert kept["empty"] is None and kept["bars"]["time"]


def test_a_trial_with_no_stored_days_and_no_loaded_days_says_so(client, auth, recorded, monkeypatch):
    """남은 그날 값이 없고(옛 줄) 기간의 분봉 파일도 모두 사라지면 그릴 날이 없다 — 빈 그림이 아니라 '적재된 날 없음' 사유.
    짝: 파일이 남아 있으면 남은 값이 없어도 그 파일의 날로 고르기가 서고 첫날을 그린다(거래 수는 미상 · 정합은 '견주지 못함')."""
    from src.api import intraday_trial_day_routes as route
    js, _ = recorded
    key = js["trial"]["trial_key"]
    real = trials.daily_of
    monkeypatch.setattr(trials, "daily_of", lambda u, k: {**real(u, k), "daily": None})
    some = day(client, auth, key)
    assert some["empty"] is None and some["date"] == DAYS[0] and some["check"]["status"] == "unknown"
    assert [c["date"] for c in some["choices"]["dates"]] == DAYS and all(c["trades"] is None for c in some["choices"]["dates"])
    for d in DAYS:
        mb._existing_day_path(d).unlink()
    mb.clear_cache()
    none = day(client, auth, key)
    assert none["empty"] == {"reason": "no_days", "message": route.EMPTY["no_days"]}
    assert none["choices"]["dates"] == [] and none["date"] is None and none["bars"] is None and none["fills"] == []


def test_every_fill_carries_a_server_label_and_every_kind_the_simulator_can_emit_has_one(client, auth, recorded):
    js, _ = recorded
    key = js["trial"]["trial_key"]
    for d in DAYS:
        got = day(client, auth, key, date=d, ticker=TICKERS[0])
        assert all(f["kind_label"] == FILL_KINDS[f["kind"]] for f in got["fills"])
    src = (ROOT / "src/engine/intraday/simulator.py").read_text(encoding="utf-8")
    emitted = set(re.findall(r'self\.enter\(ctx, "([a-z_]+)"', src)) | set(re.findall(r'self\.sell\([^\n]*"([a-z_]+)"\)', src))
    emitted |= set(re.findall(r'(?:pending_exit|exiting) = "([a-z_]+)"', src)) | {"time_exit", "trail", "stop"}
    assert emitted and emitted <= set(FILL_KINDS), emitted - set(FILL_KINDS)


def test_the_round_trips_of_that_day_and_ticker_are_the_runs_own_rows(client, auth, recorded):
    js, _ = recorded
    key = js["trial"]["trial_key"]
    keys = ("symbol", "opened_at", "closed_at", "quantity", "avg_buy", "avg_sell", "gross", "net")
    for d in DAYS:
        for t in TICKERS:
            got = day(client, auth, key, date=d, ticker=t)
            want = [{k: r[k] for k in keys} for r in js["journal"]["trades"] if r["symbol"] == t and r["opened_at"][:10] == d]
            assert [{k: r[k] for k in keys} for r in got["trades"]] == want, (d, t)


# ── 읽기만 · 거절 ──────────────────────────────────────────────────────────────────────────

def test_the_day_view_reads_only(client, auth, recorded, tmp_path):
    js, _ = recorded
    key = js["trial"]["trial_key"]
    before, files, runs = row_counts(), bar_files(tmp_path / "bars"), trials.trial_of("alice", key)["runs"]
    day(client, auth, key, date=DAYS[3], ticker=TICKERS[2])
    day(client, auth, key)
    assert row_counts() == before and bar_files(tmp_path / "bars") == files
    assert trials.trial_of("alice", key)["runs"] == runs


def test_someone_elses_trial_reads_like_a_missing_one(client, auth, recorded):
    js, _ = recorded
    key = js["trial"]["trial_key"]
    bob = login(client, "bob")
    theirs = client.get(URL.format(key=key), params={"date": DAYS[0], "ticker": TICKERS[0]}, headers=bob)
    missing = client.get(URL.format(key="f" * 64), params={"date": DAYS[0], "ticker": TICKERS[0]}, headers=bob)
    assert theirs.status_code == missing.status_code == 404
    assert theirs.json() == missing.json()
    assert client.get(URL.format(key=key)).status_code == 401


def test_a_store_failure_is_not_a_missing_trial(client, auth, recorded, monkeypatch):
    js, _ = recorded
    monkeypatch.setattr(trials, "daily_of", lambda u, k: None)
    r = client.get(URL.format(key=js["trial"]["trial_key"]), headers=auth)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "store_unavailable"


@pytest.mark.parametrize(("q", "code"), [
    ({"date": "2026-02-27", "ticker": "000660"}, "date_outside_trial"),
    ({"date": "2026-03-09", "ticker": "000660"}, "date_outside_trial"),
    ({"date": "2026-03-02", "ticker": "012345"}, "ticker_not_in_trial"),
])
def test_a_date_or_ticker_outside_the_trial_is_refused_with_its_reason(client, auth, recorded, q, code):
    js, _ = recorded
    r = client.get(URL.format(key=js["trial"]["trial_key"]), params=q, headers=auth)
    assert r.status_code == 422 and r.json()["detail"]["code"] == code and r.json()["detail"]["reason"]
    ok = client.get(URL.format(key=js["trial"]["trial_key"]), params={"date": "2026-03-02", "ticker": "000660"}, headers=auth)
    assert ok.status_code == 200                                            # 짝: 안의 날 · 종목은 받는다


@pytest.mark.parametrize("q", [{"date": "2026-3-2"}, {"date": "not-a-date"}, {"ticker": "../etc"}, {"ticker": "0" * 20}])
def test_malformed_dates_and_tickers_are_refused(client, auth, recorded, q):
    js, _ = recorded
    assert client.get(URL.format(key=js["trial"]["trial_key"]), params=q, headers=auth).status_code == 422


def test_a_synthetic_trial_is_not_redrawn_in_production(client, auth, recorded, monkeypatch):
    js, _ = recorded
    assert js["origin"]["grade"] == "E0"
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    got = day(client, auth, js["trial"]["trial_key"], date=DAYS[0], ticker=TICKERS[0])
    assert got["empty"]["reason"] == "synthetic_trial_in_production" and got["bars"] is None and got["fills"] == []
    monkeypatch.setenv("KIS_USE_MOCK", "1")                                 # 짝: 모의 모드에서는 E0 표지와 함께 그린다
    again = day(client, auth, js["trial"]["trial_key"], date=DAYS[0], ticker=TICKERS[0])
    assert again["empty"] is None and again["origin"]["grade"] == "E0"


def test_an_old_trial_whose_setting_no_longer_reads_is_refused_with_its_reason(client, auth, recorded, monkeypatch):
    js, _ = recorded
    real = trials.daily_of
    monkeypatch.setattr(trials, "daily_of", lambda u, k: {**real(u, k), "setting": {"rule": {"kind": "gone", "params": {}}}})
    got = day(client, auth, js["trial"]["trial_key"], date=DAYS[0], ticker=TICKERS[0])
    assert got["empty"]["reason"] == "bad_setting" and got["empty"]["message"] and got["fills"] == []


# ── 등록부 · 정적 ──────────────────────────────────────────────────────────────────────────

def test_the_route_is_a_protected_login_get_in_the_route_table(client):
    from src.api.protected_routes import PROTECTED, REQUIRE_LOGIN
    path = "/api/v1/intraday/trials/{trial_key}/day"
    found = [sorted(r.methods) for r in flat_routes(client.app) if r.path == path]
    assert found == [["GET"]]
    assert PROTECTED[("GET", path)][0] == REQUIRE_LOGIN

