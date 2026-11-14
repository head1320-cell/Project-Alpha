"""GET /api/v1/intraday/coverage — 분봉이 어느 날 · 어떤 출처로 · 얼마나 있는가 (분봉 백테스트 설계 W4a · a4).

품질 검사의 계산은 `test_minute_quality.py`, 출처와 운영 차단은 `test_minute_bars_origin.py` 가 건다.
여기서는 문(라우트)이 지키는 약속만 본다: 로그인 · 상한과 사유 · ★파일만 읽는다(외부 호출 0 · 쓰기 0)★ ·
막힌 날은 0 이 아니라 값 없음 + 사유 · 시간 예산을 넘긴 날은 "아직 확인하지 않음"이라고 말한다.
"""
from __future__ import annotations

import os
import tempfile

import pytest
from fastapi.testclient import TestClient

import src.data.minute_bars as mb
import src.database as dbmod
from src.domain.auth_identity import ROLE_ANALYST
from tests.route_walk import flat_routes

URL = "/api/v1/intraday/coverage"
_SECRET = "intraday-coverage-route-test-secret-0123456789"
RANGE = {"from": "2026-03-01", "to": "2026-03-10"}


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
    mb.clear_cache()

    import src.api.intraday_routes as mod
    from src.app_factory import create_app
    mod.clear_coverage_cache()
    with TestClient(create_app()) as c:
        yield c

    mod.clear_coverage_cache()
    mb.clear_cache()
    dbmod.reset_session()
    try:
        os.unlink(tmp.name)
    except OSError:
        pass


@pytest.fixture()
def auth(client) -> dict[str, str]:
    tok = client.post("/api/v1/auth/login", json={"username": "alice", "password": "alice-pw"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def collect(tickers, day):
    out = mb.collect_day(tickers, day)
    mb.clear_cache()
    return out


def by_date(body) -> dict:
    return {d["date"]: d for d in body["days"]}


# ── 문 ───────────────────────────────────────────────────────────────────────────────
def test_the_route_is_mounted(client):
    assert ("GET", URL) in {(m, r.path) for r in flat_routes(client.app) for m in (getattr(r, "methods", None) or [])}


def test_without_a_login_it_is_401_and_no_file_is_read(client, monkeypatch):
    calls = []
    monkeypatch.setattr(mb, "load_day_frame", lambda *a, **k: calls.append(1))
    assert client.get(URL, params=RANGE).status_code == 401
    assert calls == []


def test_the_route_is_in_the_protected_registry_as_login_only():
    from src.api.protected_routes import PROTECTED, REQUIRE_LOGIN
    assert PROTECTED[("GET", URL)][0] == REQUIRE_LOGIN


# ── 답 ───────────────────────────────────────────────────────────────────────────────
def test_with_nothing_loaded_the_answer_is_an_empty_list_with_a_reason(client, auth):
    body = client.get(URL, params=RANGE, headers=auth).json()
    assert body["days"] == []
    assert body["empty"]["reason"] == "not_loaded" and body["empty"]["message"].endswith("니다.")
    assert body["summary"] == {"calendar_days": 10, "loaded_days": 0, "blocked_days": 0, "unreadable_days": 0,
                               "not_checked_days": 0, "bars": 0, "sources": {"kis": 0, "synthetic": 0, "unknown": 0},
                               "defect_total": 0}


def test_loaded_days_come_back_with_counts_and_sources(client, auth):
    collect(["005930", "000660"], "2026-03-04")
    collect(["005930"], "2026-03-05")
    collect(["005930"], "2026-03-20")                       # 물은 기간 밖
    body = client.get(URL, params=RANGE, headers=auth).json()
    days = by_date(body)
    assert list(days) == ["2026-03-04", "2026-03-05"]       # 오름차순 · 기간 안만
    d = days["2026-03-04"]
    assert d["status"] == "loaded" and d["reason"] is None
    assert (d["tickers"], d["bars"], d["blocked_rows"]) == (2, 780, 0)
    assert d["sources"] == {"kis": 0, "synthetic": 780, "unknown": 0}
    assert d["defect_total"] == 0 and d["session_shifted"] is False
    assert body["empty"] is None and body["gate"] == {"mock": True}
    assert body["summary"]["loaded_days"] == 2 and body["summary"]["bars"] == 1170
    assert body["summary"]["sources"]["synthetic"] == 1170


def test_in_production_a_synthetic_day_is_blocked_with_a_reason_and_no_counts(client, auth, monkeypatch):
    """★막힌 날의 봉 수는 0 이 아니라 값 없음이다★ — 그리고 이 문은 증권사 클라이언트를 만들지 않는다."""
    collect(["005930", "000660"], "2026-03-04")
    import src.execution.kis_client as kc

    def boom(*a, **k):
        raise AssertionError("적재 범위 보고가 증권사 클라이언트를 만들었다")

    monkeypatch.setattr(kc, "get_kis_client", boom)
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    body = client.get(URL, params=RANGE, headers=auth).json()
    d = by_date(body)["2026-03-04"]
    assert d["status"] == "blocked" and d["reason"] == "synthetic_rows_blocked" and d["message"].endswith("니다.")
    assert d["bars"] is None and d["tickers"] is None and d["sources"] is None and d["defect_total"] is None
    assert d["blocked_rows"] == 780
    assert body["gate"] == {"mock": False}
    assert body["summary"]["blocked_days"] == 1 and body["summary"]["loaded_days"] == 0 and body["summary"]["bars"] == 0


def test_asked_tickers_get_their_own_rows_and_the_absent_ones_are_named(client, auth):
    collect(["005930", "000660"], "2026-03-04")
    body = client.get(URL, params={**RANGE, "tickers": "005930, 035720"}, headers=auth).json()
    d = by_date(body)["2026-03-04"]
    assert set(d["by_ticker"]) == {"005930"} and d["missing_tickers"] == ["035720"]
    assert d["by_ticker"]["005930"]["bars"] == 390 and d["by_ticker"]["005930"]["first"] == "090100"
    assert d["tickers"] == 2 and d["bars"] == 780           # 합계는 고른 종목과 무관하게 하루 전체다


def test_without_asked_tickers_there_are_no_per_ticker_rows(client, auth):
    collect(["005930"], "2026-03-04")
    d = by_date(client.get(URL, params=RANGE, headers=auth).json())["2026-03-04"]
    assert d["by_ticker"] == {} and d["missing_tickers"] == []


def test_what_cannot_be_known_from_the_bars_is_listed_with_reasons(client, auth):
    body = client.get(URL, params=RANGE, headers=auth).json()
    assert {u["what"] for u in body["unknowns"]} == {"bar_label", "lookback", "auction_vi_halt"}
    assert all(u["reason"].endswith("니다.") and u["how_to_verify"] for u in body["unknowns"])
    assert body["session_rules"]["available"] is True and body["session_rules"]["open"] == "0900"
    assert body["limits"] == {"days": 31, "tickers": 30}


def test_without_a_range_it_looks_at_the_last_days_up_to_today(client, auth):
    body = client.get(URL, headers=auth).json()
    assert body["summary"]["calendar_days"] == 31 and body["days"] == []


# ── 상한과 거절 ────────────────────────────────────────────────────────────────────────
def test_a_range_longer_than_the_limit_is_refused_with_a_reason(client, auth):
    r = client.get(URL, params={"from": "2026-03-01", "to": "2026-04-01"}, headers=auth)       # 32일
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert detail["code"] == "range_too_long" and detail["limit"] == 31 and detail["days"] == 32
    assert detail["reason"].endswith("니다.")
    assert client.get(URL, params={"from": "2026-03-01", "to": "2026-03-31"}, headers=auth).status_code == 200   # 꼭 31일


def test_a_backwards_range_is_refused(client, auth):
    r = client.get(URL, params={"from": "2026-03-10", "to": "2026-03-01"}, headers=auth)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "bad_range"


def test_too_many_tickers_are_refused_not_truncated(client, auth):
    many = ",".join(f"{i:06d}" for i in range(1, 32))
    r = client.get(URL, params={**RANGE, "tickers": many}, headers=auth)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "too_many_tickers" and r.json()["detail"]["limit"] == 30


def test_an_unreadable_date_is_422(client, auth):
    assert client.get(URL, params={"from": "3월 1일", "to": "2026-03-10"}, headers=auth).status_code == 422


# ── 파일만 읽는다 ──────────────────────────────────────────────────────────────────────
def test_the_report_writes_nothing(client, auth, tmp_path):
    collect(["005930"], "2026-03-04")
    root = tmp_path / "bars"
    before = {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in root.iterdir()}
    client.get(URL, params={**RANGE, "tickers": "005930"}, headers=auth)
    assert {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in root.iterdir()} == before


# ── 시간 예산과 기억 ───────────────────────────────────────────────────────────────────
def test_days_beyond_the_time_budget_are_reported_as_not_checked_yet(client, auth, monkeypatch):
    import src.api.intraday_routes as mod
    collect(["005930"], "2026-03-04")
    collect(["005930"], "2026-03-05")
    monkeypatch.setattr(mod, "CHECK_BUDGET_SEC", 0.0)
    body = client.get(URL, params=RANGE, headers=auth).json()
    assert {d["status"] for d in body["days"]} == {"not_checked"}
    assert all(d["reason"] == "not_checked_yet" and d["bars"] is None for d in body["days"])
    assert body["summary"]["not_checked_days"] == 2 and body["summary"]["loaded_days"] == 0
    monkeypatch.setattr(mod, "CHECK_BUDGET_SEC", 60.0)       # 짝: 예산이 있으면 확인한다
    again = client.get(URL, params=RANGE, headers=auth).json()
    assert {d["status"] for d in again["days"]} == {"loaded"}


def test_a_checked_day_is_remembered_until_its_file_changes(client, auth, monkeypatch):
    import src.api.intraday_routes as mod
    collect(["005930"], "2026-03-04")
    calls = []
    real = mod.check_day
    monkeypatch.setattr(mod, "check_day", lambda *a, **k: calls.append(1) or real(*a, **k))
    first = client.get(URL, params=RANGE, headers=auth).json()
    second = client.get(URL, params=RANGE, headers=auth).json()
    assert len(calls) == 1 and first["days"] == second["days"]
    collect(["000660"], "2026-03-04")                        # 파일이 바뀌면 다시 센다
    third = by_date(client.get(URL, params=RANGE, headers=auth).json())["2026-03-04"]
    assert len(calls) == 2 and third["tickers"] == 2


def test_asking_for_tickers_on_a_remembered_day_still_gives_their_rows(client, auth):
    """기억해 둔 것은 하루의 합계다 — 종목을 물으면 기억으로 때우지 않고 그 종목의 줄을 만든다."""
    collect(["005930", "000660"], "2026-03-04")
    plain = by_date(client.get(URL, params=RANGE, headers=auth).json())["2026-03-04"]
    asked = by_date(client.get(URL, params={**RANGE, "tickers": "000660"}, headers=auth).json())["2026-03-04"]
    assert plain["by_ticker"] == {} and set(asked["by_ticker"]) == {"000660"}
    assert {k: v for k, v in asked.items() if k not in ("by_ticker", "missing_tickers")} == \
           {k: v for k, v in plain.items() if k not in ("by_ticker", "missing_tickers")}
    after = by_date(client.get(URL, params=RANGE, headers=auth).json())["2026-03-04"]
    assert after["by_ticker"] == {}                      # 종목을 묻지 않은 다음 요청에 앞 요청의 종목 줄이 새지 않는다


def test_a_remembered_day_does_not_leak_across_the_gate(client, auth, monkeypatch):
    """모의 게이트에서 확인해 기억한 합성 하루가, 게이트가 닫힌 뒤에도 '적재됨'으로 나가면 안 된다."""
    collect(["005930"], "2026-03-04")
    assert by_date(client.get(URL, params=RANGE, headers=auth).json())["2026-03-04"]["status"] == "loaded"
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    assert by_date(client.get(URL, params=RANGE, headers=auth).json())["2026-03-04"]["status"] == "blocked"
