"""POST /api/v1/intraday/validate 와 시행 기록 — 분봉 백테스트의 판정 문 (설계 §8 · §9 · W4d d4).

계산은 `test_intraday_validate.py`(나누고 세기) · `test_intraday_gates.py`(관문 표) · `test_intraday_trials.py`(시행 기록)가 건다.
여기서는 문이 그것들을 ★옳게 잇는지★만 본다:

- 실행할 때마다 시행이 남고(같은 설정은 새 시행이 아니다), 판정은 그 수를 쓴다. ★기록하지 못하면 N=1 로 꾸미지 않는다.★
- 표본외 · 비용 두 배 · 슬리피지 민감도는 손으로 계산한 하루와 맞는다.
- 워크포워드의 격자는 받은 그대로이고(넓히지 않는다) 칸마다 시행으로 센다. 상한을 넘으면 잘라서 계산하지 않는다.
- 합성 분봉 위의 판정은 그렇게 적힌다. 분봉이 없으면 관문 표 대신 사유.

기본 하루(`WIN`)는 `test_intraday_simulator.py` 의 것이다 — 10,080 에 99주 사서 10,100 에 판다(+1,980원).
    슬리피지 0틱: 10,070 → 10,110 · 99주 → +3,960원      2틱: 10,090 → 10,090 · 99주 → 0원
    비용 두 배(수수료 3bp · 슬리피지 2틱): 대금 998,910 × 2 · 수수료 599.35 + 매도세 1,997.82 → −2,597.17원
"""
from __future__ import annotations

import logging
import os
import tempfile
from datetime import date, timedelta

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import src.data.backtest_runs as br
import src.data.minute_bars as mb
import src.database as dbmod
from src.data import intraday_trials as trials
from src.domain.auth_identity import ROLE_ANALYST
from src.engine.intraday import Day, Session
from src.engine.run_evidence import AXIS_DEGRADED, AXIS_OK, AXIS_UNKNOWN
from tests.route_walk import flat_routes

SIM = "/api/v1/intraday/simulate"
VAL = "/api/v1/intraday/validate"
TEMPLATES = "/api/v1/intraday/templates"
_SECRET = "intraday-validate-route-test-secret-0123456789"

BODY = {"tickers": ["005930"], "from": "2026-03-02", "to": "2026-03-13",
        "rule": {"kind": "opening_range_breakout", "params": {"minutes": 5}},
        "position": {"amount": 1_000_000}, "costs": {"commission_bp": 1.5, "slippage_ticks": 1}}
WIN = [("090000", 10_000, 10_020, 9_990, 10_000, 1_000), ("090100", 10_000, 10_060, 10_000, 10_060, 1_000),
       ("090200", 10_070, 10_100, 10_060, 10_090, 1_000), ("090300", 10_090, 10_120, 10_080, 10_110, 1_000)]
CROSSING = {"entry": {"op": "cross_up", "args": [{"ind": "close"}, {"const": 10_050}]}}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp.name}")
    monkeypatch.setenv("AUTH_SECRET", _SECRET)
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    monkeypatch.setenv("MINUTE_BARS_DIR", str(tmp_path / "bars"))
    monkeypatch.setattr(dbmod, "DATABASE_URL", f"sqlite:///{tmp.name}", raising=False)
    # 실행 저장소의 "표를 만들었다" 표시는 프로세스 전역이다(DB 주소를 보지 않는다). 기동이 임시 DB 에 표를 만들고
    # 그 표시를 남기면, 뒤에 도는 시험이 기본 DB 에서 "표 없음"으로 실패한다 — 시험이 끝나면 앞의 값으로 되돌린다.
    monkeypatch.setattr(br, "_inited", False)
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


def login(client, user="alice") -> dict[str, str]:
    tok = client.post("/api/v1/auth/login", json={"username": user, "password": f"{user}-pw"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture()
def auth(client) -> dict[str, str]:
    return login(client)


def weekdays(n: int, start=date(2026, 3, 2)) -> list[str]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def made_days(n=10, rows=WIN, source="kis") -> list[Day]:
    t, o, h, low, c, v = zip(*rows)
    return [Day(d, {"005930": Session("005930", d, np.array(t), np.array(o, float), np.array(h, float), np.array(low, float),
                                      np.array(c, float), np.array(v, float), source, None, "KOSPI", "stock", "삼성전자")})
            for d in weekdays(n)]


def with_days(monkeypatch, days, crossing=True):
    """파일 대신 손으로 만든 하루들을 문에 준다. `crossing` 이면 규칙도 손 계산의 그 규칙(종가가 10,050 을 상향 돌파)으로 바꾼다."""
    import src.api.intraday_routes as mod
    from src.data import minute_feed
    monkeypatch.setattr(mod.minute_feed, "plan", lambda a, b: minute_feed.Plan([d.date for d in days], 1))
    monkeypatch.setattr(mod.minute_feed, "build_days", lambda *a, **k: days)
    if crossing:
        monkeypatch.setattr(mod.rules, "build", lambda kind, params=None: mod.RuleSpec(**CROSSING))


def collect(tickers, days):
    for d in days:
        mb.collect_day(tickers, d)
    mb.clear_cache()


def stored_rows() -> int:
    with dbmod.get_engine().connect() as c:
        try:
            return int(c.execute(text("SELECT COUNT(*) FROM intraday_trials")).scalar())
        except Exception:                                        # noqa: BLE001 — 표가 아직 없다 = 남긴 것이 없다
            return 0


def gate(body, key) -> dict:
    return next(g for g in body["gates"]["gates"] if g["key"] == key)


def break_store(monkeypatch):
    def broken():
        raise RuntimeError("db down")
    monkeypatch.setattr(trials, "_engine", broken)


# ── 문 ───────────────────────────────────────────────────────────────────────────────
def test_the_route_is_mounted_login_only_and_on_the_access_map(client):
    import json
    from pathlib import Path

    from src.api.protected_routes import PROTECTED, REQUIRE_LOGIN
    table = {(m, r.path) for r in flat_routes(client.app) for m in (getattr(r, "methods", None) or [])}
    assert ("POST", VAL) in table and PROTECTED[("POST", VAL)][0] == REQUIRE_LOGIN
    access = json.loads((Path(__file__).resolve().parents[1] / "frontend/src/entities/session/accessMap.json").read_text("utf-8"))
    assert VAL in json.dumps(access, ensure_ascii=False)


def test_without_a_login_nothing_is_read_computed_or_recorded(client, monkeypatch):
    import src.api.intraday_routes as mod
    calls = []
    monkeypatch.setattr(mod.minute_feed, "build_days", lambda *a, **k: calls.append(1) or [])
    assert client.post(VAL, json=BODY).status_code == 401
    assert calls == [] and stored_rows() == 0


# ── 실행은 시행을 남긴다 ──────────────────────────────────────────────────────────────
def test_a_run_is_recorded_and_running_it_again_is_not_a_new_trial(client, auth, monkeypatch):
    with_days(monkeypatch, made_days())
    first = client.post(SIM, json=BODY, headers=auth).json()["trial"]
    assert first == {"recorded": True, "new": True, "runs": 1, "family_n": 1, "user_total": 1, "reason": None, "message": None}
    again = client.post(SIM, json=BODY, headers=auth).json()["trial"]
    assert (again["new"], again["runs"], again["family_n"], again["user_total"]) == (False, 2, 1, 1)
    other = client.post(SIM, json={**BODY, "position": {"amount": 1_000_000, "stop_pct": 1.0}}, headers=auth).json()["trial"]
    assert (other["new"], other["family_n"], other["user_total"]) == (True, 2, 2)
    assert stored_rows() == 2


def test_two_spellings_of_the_same_number_are_one_trial(client, auth, monkeypatch):
    with_days(monkeypatch, made_days())
    client.post(SIM, json=BODY, headers=auth)
    same = {**BODY, "rule": {"kind": "opening_range_breakout", "params": {"minutes": 5.0}}, "position": {"amount": 1_000_000.0}}
    assert client.post(SIM, json=same, headers=auth).json()["trial"]["new"] is False


def test_another_user_s_runs_are_not_in_my_count(client, auth, monkeypatch):
    with_days(monkeypatch, made_days())
    client.post(SIM, json=BODY, headers=auth)
    theirs = client.post(SIM, json=BODY, headers=login(client, "bob")).json()["trial"]
    assert (theirs["new"], theirs["family_n"], theirs["user_total"]) == (True, 1, 1)


def test_an_answer_without_usable_bars_records_nothing(client, auth):
    body = client.post(SIM, json=BODY, headers=auth).json()                 # 적재된 분봉이 없다
    assert body["empty"]["reason"] == "not_loaded" and body["trial"] is None and stored_rows() == 0


def test_a_run_whose_bars_were_all_blocked_records_nothing(client, auth, monkeypatch):
    collect(["005930"], weekdays(3))
    monkeypatch.setenv("KIS_USE_MOCK", "0")                                   # 운영 게이트 — 합성 분봉은 쓰이지 않는다
    body = client.post(SIM, json=BODY, headers=auth).json()
    assert body["empty"]["reason"] == "no_usable_bars" and body["trial"] is None and stored_rows() == 0


def test_when_the_trial_cannot_be_recorded_the_run_still_answers_and_says_so(client, auth, monkeypatch):
    with_days(monkeypatch, made_days())
    break_store(monkeypatch)
    body = client.post(SIM, json=BODY, headers=auth).json()
    assert body["journal"]["summary"]["gross"]["total"] == 19_800           # 계산은 그대로 답한다
    assert body["trial"] == {"recorded": False, "new": None, "runs": None, "family_n": None, "user_total": None,
                             "reason": "store_unavailable", "message": trials.REASONS["store_unavailable"]}


def test_runs_on_synthetic_bars_do_not_count_toward_runs_on_real_bars(client, auth, monkeypatch):
    with_days(monkeypatch, made_days(source="synthetic"))
    assert client.post(SIM, json=BODY, headers=auth).json()["trial"]["family_n"] == 1
    with_days(monkeypatch, made_days(source="kis"))
    real = client.post(SIM, json=BODY, headers=auth).json()["trial"]
    assert (real["new"], real["family_n"], real["user_total"]) == (True, 1, 1)


# ── 판정 — 손 계산과 맞는다 ───────────────────────────────────────────────────────────
def test_the_checks_match_the_hand_computed_days(client, auth, monkeypatch):
    with_days(monkeypatch, made_days())
    body = client.post(VAL, json=BODY, headers=auth).json()
    assert body["empty"] is None and body["origin"]["grade"] == "E3"
    assert body["summary"]["trades"] == 10 and body["summary"]["gross_total"] == 19_800
    assert body["summary"]["net_total"] == pytest.approx(-3_194.7, abs=0.1)

    oos = body["out_of_sample"]
    assert oos["split"]["in_sample_days"] == 7 and oos["split"]["out_of_sample_days"] == 3
    assert (oos["split"]["out_of_sample_from"], oos["split"]["out_of_sample_to"]) == ("2026-03-11", "2026-03-13")
    assert oos["in_sample"]["gross_total"] == 13_860 and oos["out_of_sample"]["gross_total"] == 5_940
    assert oos["out_of_sample"]["net_total"] == pytest.approx(-958.41, abs=0.05) and oos["views"] == 1

    assert [(r["ticks"], r["gross_total"], r["is_base"]) for r in body["slippage"]] == [(0, 39_600, False), (1, 19_800, True),
                                                                                        (2, 0, False)]
    stress = body["stress"]
    assert (stress["commission_bp"], stress["slippage_ticks"]) == (3.0, 2)
    assert stress["double"]["gross_total"] == 0 and stress["double"]["net_total"] == pytest.approx(-25_971.66, abs=0.1)


def test_the_gate_table_reads_those_numbers(client, auth, monkeypatch):
    with_days(monkeypatch, made_days())
    body = client.post(VAL, json=BODY, headers=auth).json()
    states = {g["key"]: g["state"] for g in body["gates"]["gates"]}
    assert states == {"data_integrity": AXIS_OK, "point_in_time": AXIS_UNKNOWN, "costs": AXIS_OK,
                      "out_of_sample": AXIS_UNKNOWN,              # 표본외 거래 3건 — 30건에 못 미친다
                      "cost_robustness": AXIS_DEGRADED,           # 비용을 두 배로 놓으면 기대값이 0 이하
                      "multiplicity": AXIS_UNKNOWN,               # 열흘 — 분포를 재기에 짧다
                      "economic_value": AXIS_UNKNOWN}
    assert body["gates"]["sentence"] == "관문 일곱 가운데 통과 2 · 미달 1 · 미상 4 입니다."
    assert body["gates"]["on_synthetic"] is False
    assert body["multiplicity"]["n"] == 1 and body["multiplicity"]["days"] == 10 and body["multiplicity"]["value"] is None
    assert body["trial"]["recorded"] is True and body["trial"]["family_n"] == 1


def test_a_larger_base_slippage_is_checked_at_itself_one_more_tick_and_twice(client, auth, monkeypatch):
    import src.api.intraday_routes as mod
    with_days(monkeypatch, made_days())
    seen = []
    real = mod.intraday.run
    monkeypatch.setattr(mod.intraday, "run", lambda days, rule, position, costs, **kw: seen.append(
        (costs.slippage_ticks, costs.commission_bp)) or real(days, rule, position, costs, **kw))
    body = client.post(VAL, json={**BODY, "costs": {"commission_bp": 1.5, "slippage_ticks": 3}}, headers=auth).json()
    assert [r["ticks"] for r in body["slippage"]] == [0, 1, 2, 3, 4] and [r["is_base"] for r in body["slippage"]].index(True) == 3
    assert body["stress"]["slippage_ticks"] == 6 and body["stress"]["commission_bp"] == 3.0
    # 여섯 번 — 같은 것을 두 번 돌리지 않는다. 체결은 수수료율과 무관하므로 두 배 수수료는 6틱의 체결 줄을 다시 계산한 것이다.
    assert sorted(seen) == [(0, 1.5), (1, 1.5), (2, 1.5), (3, 1.5), (4, 1.5), (6, 1.5)]


def test_without_a_commission_rate_the_cost_checks_are_unknown_not_zero(client, auth, monkeypatch):
    with_days(monkeypatch, made_days())
    body = client.post(VAL, json={**BODY, "costs": {"slippage_ticks": 1}}, headers=auth).json()
    assert body["summary"]["net_total"] is None and body["stress"]["commission_bp"] is None
    assert body["stress"]["double"]["net_expectancy"] is None
    assert gate(body, "costs")["state"] == AXIS_UNKNOWN and gate(body, "cost_robustness")["state"] == AXIS_UNKNOWN
    assert body["multiplicity"]["value"] is None and gate(body, "multiplicity")["state"] == AXIS_UNKNOWN


# ── 표본외를 본 횟수 · 시행 횟수 ──────────────────────────────────────────────────────
def test_looking_at_the_same_out_of_sample_part_again_is_counted_and_said(client, auth, monkeypatch):
    with_days(monkeypatch, made_days())
    first = client.post(VAL, json=BODY, headers=auth).json()
    assert first["out_of_sample"]["views"] == 1 and not any("번째" in f for f in gate(first, "out_of_sample")["facts"])
    second = client.post(VAL, json=BODY, headers=auth).json()
    assert second["out_of_sample"]["views"] == 2
    assert any("2번째" in f for f in gate(second, "out_of_sample")["facts"])
    third = client.post(VAL, json={**BODY, "position": {"amount": 1_000_000, "stop_pct": 1.0}}, headers=auth).json()
    assert third["out_of_sample"]["views"] == 3                   # 설정을 바꿔 본 것도 같은 날들을 본 것이다
    assert third["trial"]["family_n"] == 2


def test_running_alone_does_not_count_as_a_look_at_the_out_of_sample_part(client, auth, monkeypatch):
    with_days(monkeypatch, made_days())
    client.post(SIM, json=BODY, headers=auth)
    client.post(SIM, json=BODY, headers=auth)
    assert client.post(VAL, json=BODY, headers=auth).json()["out_of_sample"]["views"] == 1


def test_when_the_trial_store_fails_multiplicity_is_unknown_and_never_one(client, auth, monkeypatch):
    with_days(monkeypatch, made_days())
    break_store(monkeypatch)
    body = client.post(VAL, json=BODY, headers=auth).json()
    assert body["trial"]["recorded"] is False and body["trial"]["family_n"] is None
    assert body["multiplicity"] is None                           # N=1 로 계산한 확률을 내지 않는다
    found = gate(body, "multiplicity")
    assert found["state"] == AXIS_UNKNOWN and found["reason"] == trials.REASONS["store_unavailable"]
    assert body["out_of_sample"]["views"] is None
    assert any("세지 못했습니다" in f for f in gate(body, "out_of_sample")["facts"])
    assert body["summary"]["gross_total"] == 19_800               # 다른 검사는 그대로 답한다


def test_the_trial_count_feeds_the_correction_on_enough_days(client, auth):
    """합성 분봉 64일 — 숫자의 뜻이 아니라 ★배선★을 본다: 시행이 하나면 보정 전 확률, 둘이면 보정한 확률."""
    days = weekdays(64)
    collect(["005930"], days)
    body = {**BODY, "from": days[0], "to": days[-1], "costs": ASSUMED}     # 마스터가 없는 환경 — 시장 구분은 선언한 가정이다
    one = client.post(VAL, json=body, headers=auth).json()
    assert one["origin"]["grade"] == "E0" and one["gates"]["on_synthetic"] is True
    assert one["gates"]["sentence"].endswith("합성 분봉 위의 숫자이며 예측력이나 수익의 증거가 아닙니다.")
    assert gate(one, "data_integrity")["state"] == AXIS_DEGRADED
    m1 = one["multiplicity"]
    assert m1["n"] == 1 and m1["days"] == 64 and m1["corrected"] is False and m1["value"] == m1["psr0"] is not None

    two = client.post(VAL, json={**body, "rule": {"kind": "opening_range_breakout", "params": {"minutes": 30}}},
                      headers=auth).json()
    m2 = two["multiplicity"]
    assert m2["n"] == 2 and m2["corrected"] is True and m2["value"] == m2["dsr"] is not None
    assert m2["n_effective"] is not None                          # 두 시행이 같은 날들을 봤다 — 닮음을 잴 수 있다
    assert (m2["dsr_effective"] is None) == (m2["n_effective"] < 2)          # 닮아서 2 보다 작으면 그 보정은 내지 않는다(사유)
    assert m2["n_effective"] >= 2 or m2["n_effective_reason"]
    again = client.post(VAL, json=body, headers=auth).json()
    assert again["multiplicity"]["n"] == 2 and again["trial"]["new"] is False     # 같은 설정을 다시 봐도 N 은 늘지 않는다

    # 수수료율 없이 본 시행 — 비용 뒤 흐름이 없다. 그 시행 자신은 점수를 매기지 못하고, 남의 보정에는 '세기만' 한다.
    from src.engine.intraday import validate as v
    blind = client.post(VAL, json={**body, "costs": {"slippage_ticks": 1, "unknown_market": "KOSPI", "unknown_instrument": "stock"}},
                        headers=auth).json()["multiplicity"]
    assert blind["n"] == 3 and blind["value"] is None and blind["days"] is None and blind["reason"] == v.REASONS["net_unknown"]
    after = client.post(VAL, json=body, headers=auth).json()["multiplicity"]
    assert after["n"] == 3 and after["unscored"] == 1 and after["dsr"] is not None
    assert after["dsr"] < again["multiplicity"]["dsr"]            # 세는 수가 늘었으니 보정은 더 세진다 — 흐름을 몰라도 약해지지 않는다


def test_trials_that_saw_different_days_are_counted_but_their_likeness_is_not_measured(client, auth, monkeypatch):
    """가족은 기간이 ★겹치면★ 든다 — 날이 어긋난 두 흐름의 상관은 뜻이 없으므로 닮음으로 줄인 수는 내지 않고 그렇게 말한다."""
    from src.engine.intraday import validate as v
    with_days(monkeypatch, made_days(10))
    client.post(VAL, json=BODY, headers=auth)
    with_days(monkeypatch, made_days(8))
    shorter = client.post(VAL, json={**BODY, "to": weekdays(8)[-1], "position": {"amount": 1_000_000, "stop_pct": 1}},
                          headers=auth).json()
    m = shorter["multiplicity"]
    assert m["n"] == 2 and m["corrected"] is True                 # 세는 데에는 든다
    assert m["n_effective"] is None and m["dsr_effective"] is None and m["n_effective_reason"] == v.REASONS["different_days"]

    # 짝: 같은 날들을 본 시행끼리는 그 사유가 붙지 않는다.
    same = client.post(VAL, json={**BODY, "to": weekdays(8)[-1], "position": {"amount": 1_000_000, "stop_pct": 2}},
                       headers=auth).json()["multiplicity"]
    assert same["n"] == 3 and same["n_effective_reason"] == v.REASONS["different_days"]      # 열흘짜리 시행이 여전히 가족에 있다


# ── 시장 구분을 모르는 종목 ───────────────────────────────────────────────────────────
ASSUMED = {"commission_bp": 1.5, "slippage_ticks": 1, "unknown_market": "KOSPI", "unknown_instrument": "stock"}


def test_a_ticker_whose_market_is_unknown_has_no_net_until_the_user_declares_an_assumption(client, auth):
    """이 시험 환경에는 종목 마스터가 없다 — 수집한 분봉의 종목은 시장 구분이 미상이다."""
    collect(["005930"], weekdays(3))
    blind = client.post(SIM, json=BODY, headers=auth).json()
    assert blind["journal"]["summary"]["gross"]["n"] >= 0 and blind["journal"]["summary"]["net"] is None
    assert blind["journal"]["basis"]["tax_unknown"][0]["reason"] == "unknown_market_or_instrument" or blind["journal"]["summary"]["gross"]["n"] == 0
    assumed = client.post(SIM, json={**BODY, "costs": ASSUMED}, headers=auth).json()
    assert assumed["journal"]["basis"]["unknown_market"] == "KOSPI"
    if assumed["journal"]["summary"]["gross"]["n"]:
        assert assumed["journal"]["summary"]["net"] is not None and assumed["journal"]["basis"]["tax"]["assumed"] > 0
    assert assumed["request"]["costs"]["unknown_market"] == "KOSPI"
    assert assumed["trial"]["new"] is True and assumed["trial"]["family_n"] == 2          # 가정이 다르면 다른 시행이다


def test_the_declared_market_reaches_every_check_that_recomputes_costs(client, auth, monkeypatch):
    """표본외 분할 · 두 배 비용 · 워크포워드는 체결 줄을 ★다시★ 계산한다 — 선언한 가정이 거기까지 가지 않으면 그 칸만 비용 뒤가 빈다."""
    t, o, h, low, c, v = zip(*WIN)
    days = [Day(d, {"005930": Session("005930", d, np.array(t), np.array(o, float), np.array(h, float), np.array(low, float),
                                      np.array(c, float), np.array(v, float), "kis", None, None, None, "삼성전자")})
            for d in weekdays(10)]
    with_days(monkeypatch, days)
    grid = {"folds": 2, "position": {"stop_pct": [1, 2]}}
    blind = client.post(VAL, json={**BODY, "walk_forward": grid}, headers=auth).json()
    assert blind["summary"]["net_total"] is None and blind["out_of_sample"]["out_of_sample"]["net_total"] is None
    assert blind["stress"]["double"]["net_total"] is None and blind["walk_forward"]["reason"] == "net_unknown"

    out = client.post(VAL, json={**BODY, "costs": ASSUMED, "walk_forward": grid}, headers=auth).json()
    assert out["summary"]["net_total"] == pytest.approx(-3_194.7, abs=0.1)     # 코스피 주식으로 가정 = 손 계산의 그 값
    assert out["out_of_sample"]["in_sample"]["net_total"] is not None
    assert out["out_of_sample"]["out_of_sample"]["net_total"] == pytest.approx(-958.41, abs=0.1)
    assert out["stress"]["double"]["net_total"] == pytest.approx(-25_971.66, abs=0.1)
    assert out["walk_forward"]["reason"] is None and out["walk_forward"]["stitched"]["net_total"] is not None


def test_the_assumption_must_be_a_market_the_tax_table_knows(client, auth):
    for costs in ({"unknown_market": "NYSE"}, {"unknown_instrument": "bond"}):
        assert client.post(SIM, json={**BODY, "costs": costs}, headers=auth).status_code == 422
    fields = {f["key"]: f for f in client.get(TEMPLATES, headers=auth).json()["costs"]}
    assert [c["value"] for c in fields["unknown_market"]["choices"]] == ["KOSPI", "KOSDAQ", "KONEX"]
    assert [c["value"] for c in fields["unknown_instrument"]["choices"]] == ["stock", "etf"]
    assert fields["unknown_market"]["default"] is None and fields["unknown_market"]["type"] == "choice"


# ── 워크포워드 ────────────────────────────────────────────────────────────────────────
GRID = {"folds": 4, "rule": {"minutes": [5, 15, 30]}}


def test_walk_forward_runs_each_declared_cell_once_and_counts_each_as_a_trial(client, auth, monkeypatch):
    import src.api.intraday_routes as mod
    days = weekdays(12)
    collect(["005930"], days)
    runs = []
    real = mod.intraday.run
    monkeypatch.setattr(mod.intraday, "run", lambda d, rule, position, costs, **kw: runs.append(1) or real(d, rule, position, costs, **kw))
    body = client.post(VAL, json={**BODY, "from": days[0], "to": days[-1], "costs": ASSUMED, "walk_forward": GRID},
                       headers=auth).json()
    wf = body["walk_forward"]
    assert wf["reason"] is None and wf["folds"] == 4 and len(wf["steps"]) == 3
    assert [c["rule"] for c in wf["cells"]] == [{"minutes": 5}, {"minutes": 15}, {"minutes": 30}]
    assert [c["is_base"] for c in wf["cells"]] == [True, False, False]
    assert all(c["whole"]["trades"] >= 0 and c["position"] == {} for c in wf["cells"])
    assert len(runs) == 3 + 2                                     # 슬리피지 0·1·2틱 + 기본 설정이 아닌 칸 둘
    assert body["trial"]["family_n"] == 3 and stored_rows() == 3  # 칸마다 한 시행 — 기본 설정과 같은 칸은 다시 세지 않는다
    assert body["request"]["walk_forward"] == {"folds": 4, "rule": {"minutes": [5, 15, 30]}, "position": {}}


def test_a_position_setting_can_be_on_the_grid_too(client, auth, monkeypatch):
    with_days(monkeypatch, made_days(12))
    grid = {"folds": 3, "position": {"stop_pct": [0.5, 1.0]}, "rule": {"minutes": [5, 10]}}
    wf = client.post(VAL, json={**BODY, "walk_forward": grid}, headers=auth).json()["walk_forward"]
    assert [(c["rule"], c["position"]) for c in wf["cells"]] == [
        ({"minutes": 5}, {"stop_pct": 0.5}), ({"minutes": 5}, {"stop_pct": 1.0}),
        ({"minutes": 10}, {"stop_pct": 0.5}), ({"minutes": 10}, {"stop_pct": 1.0})]
    assert not any(c["is_base"] for c in wf["cells"])             # 기본 설정에는 손절이 없다 — 어느 칸과도 같지 않다


def test_without_a_declared_grid_there_is_no_walk_forward(client, auth, monkeypatch):
    with_days(monkeypatch, made_days())
    assert client.post(VAL, json=BODY, headers=auth).json()["walk_forward"] is None


@pytest.mark.parametrize(("grid", "code"), [
    ({"folds": 4, "rule": {"minutes": list(range(1, 14))}}, "grid_too_large"),            # 13칸
    ({"folds": 4, "rule": {"minutes": [5, 15, 30, 45], "width": [1]}}, "unknown_param"),
    ({"folds": 4, "rule": {"minutes": [5]}}, "grid_too_small"),
    ({"folds": 4}, "grid_too_small"),
    ({"folds": 4, "rule": {"minutes": [5, 500]}}, "param_out_of_range"),
    ({"folds": 4, "position": {"stop_pct": [1.0, 150.0]}}, "bad_percent"),
    ({"folds": 4, "position": {"leverage": [1, 2]}}, "grid_unknown_position"),
    ({"folds": 1, "rule": {"minutes": [5, 15]}}, "bad_folds"),
    ({"folds": 13, "rule": {"minutes": [5, 15]}}, "bad_folds"),
])
def test_a_grid_that_cannot_be_run_is_refused_before_anything_is_read(client, auth, monkeypatch, grid, code):
    import src.api.intraday_routes as mod
    calls = []
    monkeypatch.setattr(mod.minute_feed, "plan", lambda a, b: calls.append(1))
    r = client.post(VAL, json={**BODY, "walk_forward": grid}, headers=auth)
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert detail["code"] == code and detail["reason"].endswith("니다.") and calls == [] and stored_rows() == 0


def test_the_grid_limit_is_twelve_cells_and_exactly_twelve_is_accepted(client, auth, monkeypatch):
    with_days(monkeypatch, made_days(12))
    twelve = {"folds": 2, "rule": {"minutes": list(range(1, 13))}}
    assert client.post(VAL, json={**BODY, "walk_forward": twelve}, headers=auth).status_code == 200
    over = client.post(VAL, json={**BODY, "walk_forward": {"folds": 2, "rule": {"minutes": list(range(1, 14))}}}, headers=auth)
    assert over.json()["detail"]["limit"] == 12 and over.json()["detail"]["cells"] == 13


def test_repeated_values_on_the_grid_are_one_cell(client, auth, monkeypatch):
    with_days(monkeypatch, made_days(12))
    wf = client.post(VAL, json={**BODY, "walk_forward": {"folds": 2, "rule": {"minutes": [5, 5, 15, 15.0]}}},
                     headers=auth).json()["walk_forward"]
    assert [c["rule"] for c in wf["cells"]] == [{"minutes": 5}, {"minutes": 15}]


# ── 상한 ──────────────────────────────────────────────────────────────────────────────
def test_too_much_work_is_refused_with_the_numbers_and_never_cut_short(client, auth, monkeypatch):
    import src.api.intraday_routes as mod
    with_days(monkeypatch, made_days(10))
    built = []
    monkeypatch.setattr(mod.minute_feed, "build_days", lambda *a, **k: built.append(1) or made_days(10))
    monkeypatch.setattr(mod, "MAX_VALIDATE_WORK", 29)             # 종목 1 × 거래일 10 × 계산 3번 = 30
    r = client.post(VAL, json=BODY, headers=auth)
    assert r.status_code == 400 and built == []
    assert r.json()["detail"] == {"code": "too_much_work", "reason": mod.REASONS["too_much_work"], "limit": 29, "work": 30,
                                  "ticker_days": 10, "simulations": 3}
    monkeypatch.setattr(mod, "MAX_VALIDATE_WORK", 30)             # 꼭 상한이면 받는다
    assert client.post(VAL, json=BODY, headers=auth).status_code == 200


def test_the_grid_cells_count_toward_the_work(client, auth, monkeypatch):
    import src.api.intraday_routes as mod
    with_days(monkeypatch, made_days(10))
    monkeypatch.setattr(mod, "MAX_VALIDATE_WORK", 30)
    r = client.post(VAL, json={**BODY, "walk_forward": {"folds": 2, "rule": {"minutes": [5, 15]}}}, headers=auth)
    assert r.status_code == 400 and r.json()["detail"]["simulations"] == 4 and r.json()["detail"]["work"] == 40


def test_the_templates_route_tells_the_screen_the_validation_limits(client, auth):
    import src.api.intraday_routes as mod
    limits = client.get(TEMPLATES, headers=auth).json()["limits"]
    assert limits["grid_cells"] == mod.MAX_GRID_CELLS == 12 and limits["validate_work"] == mod.MAX_VALIDATE_WORK
    assert (limits["folds_min"], limits["folds_max"]) == (2, 12)


# ── 없음 · 합성 · 기록 ────────────────────────────────────────────────────────────────
def test_without_bars_there_is_a_reason_instead_of_a_gate_table(client, auth):
    body = client.post(VAL, json=BODY, headers=auth).json()
    assert body["empty"] == {"reason": "not_loaded", "message": "이 기간에 적재된 분봉이 없습니다."}
    assert body["gates"] is None and body["summary"] is None and body["trial"] is None and stored_rows() == 0


def test_in_production_synthetic_bars_are_not_judged(client, auth, monkeypatch):
    collect(["005930"], weekdays(3))
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    body = client.post(VAL, json=BODY, headers=auth).json()
    assert body["empty"]["reason"] == "no_usable_bars" and body["gates"] is None and stored_rows() == 0
    assert body["data"]["skipped_by_reason"] == {"synthetic_rows_blocked": 3}


def test_one_day_cannot_be_split_and_the_gate_says_so(client, auth, monkeypatch):
    with_days(monkeypatch, made_days(1))
    body = client.post(VAL, json=BODY, headers=auth).json()
    assert body["out_of_sample"]["reason"] == "too_few_days" and body["out_of_sample"]["views"] is None
    assert gate(body, "out_of_sample")["state"] == AXIS_UNKNOWN
    with dbmod.get_engine().connect() as c:
        assert c.execute(text("SELECT oos_views FROM intraday_trials")).scalar() == 0     # 가르지 못했으면 본 것도 아니다


def test_skipped_sessions_reach_the_data_gate(client, auth, monkeypatch):
    days = made_days(10)
    days[0] = Day(days[0].date, days[0].sessions, skipped=(("000660", "no_bars"),))
    with_days(monkeypatch, days)
    body = client.post(VAL, json={**BODY, "tickers": ["005930", "000660"]}, headers=auth).json()
    found = gate(body, "data_integrity")
    assert found["state"] == AXIS_DEGRADED and "1건" in found["reason"] and body["data"]["skipped_total"] == 1


def test_the_log_carries_counts_only(client, auth, monkeypatch, caplog):
    with_days(monkeypatch, made_days())
    with caplog.at_level(logging.INFO, logger="api.intraday"):
        client.post(VAL, json=BODY, headers=auth)
    lines = [r.getMessage() for r in caplog.records if r.name == "api.intraday"]
    assert lines and all("005930" not in line and "alice" not in line for line in lines)


def test_a_malformed_grid_is_422_not_a_silent_default(client, auth):
    for bad in ({"folds": 4, "rule": {"minutes": 5}}, {"folds": 4, "rule": {"minutes": [5, 15]}, "extra": 1},
                {"rule": {"minutes": [5, 15]}}):
        assert client.post(VAL, json={**BODY, "walk_forward": bad}, headers=auth).status_code == 422, bad
