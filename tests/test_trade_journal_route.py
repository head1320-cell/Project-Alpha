"""POST /api/v1/trade-journal/analyze — 보호 · 상한 · ★저장하지 않음★ · 마스터 조회 (설계 §6)

엔진의 계산은 `test_trade_journal_analyze.py` 가 건다. 여기서는 문(라우트)이 지키는 약속만 본다.
"""
from __future__ import annotations

import builtins
import io
import logging
import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

import src.database as dbmod
from src.domain.auth_identity import ROLE_ANALYST
from tests.route_walk import flat_routes

URL = "/api/v1/trade-journal/analyze"
_SECRET = "trade-journal-route-test-secret-0123456789"


def K(at, symbol, side, qty, price, **extra) -> dict:
    return {"executed_at": at, "symbol": symbol, "side": side, "quantity": qty, "price": price,
            "market": "KOSPI", "instrument": "stock", **extra}


FILLS = [
    K("2026-03-04 09:00:00", "005930", "buy", 100, 10_000), K("2026-03-04 09:00:40", "005930", "sell", 100, 10_200),
    K("2026-03-04 09:10:00", "ZQ9981", "buy", 50, 20_000), K("2026-03-04 09:13:00", "ZQ9981", "sell", 50, 19_800),
]
BODY = {"fills": FILLS, "commission_bp": 10}


@pytest.fixture()
def client(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp.name}")
    monkeypatch.setenv("AUTH_SECRET", _SECRET)
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    monkeypatch.setattr(dbmod, "DATABASE_URL", f"sqlite:///{tmp.name}", raising=False)
    dbmod.reset_session()
    dbmod.init_db()
    dbmod.create_user("alice", "alice-pw", role=ROLE_ANALYST)

    from src.app_factory import create_app
    with TestClient(create_app()) as c:
        yield c

    dbmod.reset_session()
    try:
        os.unlink(tmp.name)
    except OSError:
        pass


@pytest.fixture()
def auth(client) -> dict[str, str]:
    tok = client.post("/api/v1/auth/login", json={"username": "alice", "password": "alice-pw"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


# ── 문 ────────────────────────────────────────────────────────────────────────

def test_the_route_is_mounted(client):
    assert ("POST", URL) in {(m, r.path) for r in flat_routes(client.app) for m in (getattr(r, "methods", None) or [])}


def test_without_a_login_it_is_401_and_nothing_is_computed(client, monkeypatch):
    import src.api.trade_journal_routes as mod
    calls = []
    monkeypatch.setattr(mod, "analyze", lambda *a, **k: calls.append(1) or {})
    res = client.post(URL, json=BODY)
    assert res.status_code == 401 and calls == []


def test_with_a_login_it_answers_with_the_journal(client, auth):
    res = client.post(URL, json=BODY, headers=auth)
    assert res.status_code == 200, res.text
    out = res.json()
    assert set(out) >= {"inputs", "rejects", "basis", "summary", "curve", "breakdowns", "extremes", "trades",
                        "open_positions", "unmatched_sells", "not_covered", "limits"}
    assert out["inputs"]["fills"] == 4 and out["summary"]["net"]["n"] == 2
    assert out["summary"]["net"]["total"] == 15_940.0 - 13_970.0
    assert out["basis"]["fee"]["assumed"] == 4 and out["basis"]["tax"]["inferred"] == 2
    assert out["limits"] == {"fills": 20_000}
    assert len(out["not_covered"]) >= 5


def test_the_request_options_reach_the_engine(client, auth):
    """수수료율을 안 주면 모름이다 — 문이 기본값을 지어 넣지 않는다."""
    out = client.post(URL, json={"fills": FILLS}, headers=auth).json()
    assert out["summary"]["net"] is None and out["basis"]["commission_bp"] is None
    bare = [{k: v for k, v in f.items() if k not in ("market", "instrument")} for f in FILLS]
    unknown = client.post(URL, json={"fills": bare, "commission_bp": 0}, headers=auth).json()
    assert unknown["basis"]["tax"]["unknown"] == 2
    assumed = client.post(URL, json={"fills": bare, "commission_bp": 0, "unknown_market": "KOSDAQ", "unknown_instrument": "stock"},
                          headers=auth).json()
    assert assumed["basis"]["tax"]["assumed"] == 2 and assumed["basis"]["tax_rates"][0]["market"] == "KOSDAQ"


# ── 상한과 잘못된 요청 ────────────────────────────────────────────────────────

def test_too_many_rows_are_refused_with_a_reason_and_not_truncated(client, auth, monkeypatch):
    import src.api.trade_journal_routes as mod
    calls = []
    monkeypatch.setattr(mod, "analyze", lambda *a, **k: calls.append(1) or {})
    res = client.post(URL, json={"fills": [FILLS[0]] * (mod.MAX_FILLS + 1)}, headers=auth)
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert detail["code"] == "too_many_rows" and detail["limit"] == 20_000 and detail["rows"] == 20_001
    assert "20,000" in detail["reason"] and "20,001" in detail["reason"]
    assert calls == [], "잘라서 계산하지 않는다 — 앞부분만의 통계는 다른 통계다"


def test_exactly_the_limit_is_accepted(client, auth, monkeypatch):
    import src.api.trade_journal_routes as mod
    seen = []
    monkeypatch.setattr(mod, "analyze", lambda rows, *a, **k: seen.append(len(rows)) or {"ok": True})
    res = client.post(URL, json={"fills": [FILLS[0]] * mod.MAX_FILLS}, headers=auth)
    assert res.status_code == 200 and seen == [20_000]


def test_an_empty_request_is_refused_with_a_reason(client, auth):
    res = client.post(URL, json={"fills": []}, headers=auth)
    assert res.status_code == 400 and res.json()["detail"]["code"] == "no_rows" and res.json()["detail"]["reason"]


@pytest.mark.parametrize("bad", [{"commission_bp": -1}, {"commission_bp": 1_001}, {"unknown_market": "NASDAQ"},
                                 {"unknown_instrument": "etn"}, {"fills": "005930"}, {"fills": ["005930"]}])
def test_malformed_options_are_422_not_a_silent_default(client, auth, bad):
    assert client.post(URL, json={**BODY, **bad}, headers=auth).status_code == 422


def test_rows_the_engine_cannot_read_come_back_as_rejects_not_as_an_error(client, auth):
    res = client.post(URL, json={"fills": [*FILLS, {"executed_at": "어제", "symbol": "A"}], "commission_bp": 10}, headers=auth)
    assert res.status_code == 200 and res.json()["rejects"]["count"] == 1


# ── ★저장하지 않는다★ ─────────────────────────────────────────────────────────

def _row_counts() -> dict[str, int]:
    engine = dbmod.get_engine()
    with engine.connect() as conn:
        return {t: conn.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar() for t in inspect(engine).get_table_names()}


def test_the_database_is_untouched_by_an_analysis(client, auth):
    before = _row_counts()
    assert before, "표가 하나도 없으면 이 시험은 아무것도 보지 않는다"
    assert client.post(URL, json=BODY, headers=auth).status_code == 200
    assert _row_counts() == before


def test_no_file_is_opened_for_writing_during_an_analysis(client, auth, monkeypatch):
    opened: list[tuple] = []
    real = builtins.open

    def spy(file, mode="r", *a, **k):
        if any(ch in str(mode) for ch in "wax+"):
            opened.append((str(file), mode))
        return real(file, mode, *a, **k)

    client.post(URL, json=BODY, headers=auth)            # 첫 호출의 지연 적재(세율표 읽기 등)를 먼저 흘려보낸다
    monkeypatch.setattr(builtins, "open", spy)
    monkeypatch.setattr(io, "open", spy)
    assert client.post(URL, json=BODY, headers=auth).status_code == 200
    assert opened == []


def test_the_spy_itself_sees_a_write(tmp_path, monkeypatch):
    """★짝★ — 위 시험의 감시가 실제로 쓰기를 보는지(늘 빈 목록인 감시가 아닌지)."""
    opened: list[str] = []
    real = builtins.open

    def spy(file, mode="r", *a, **k):
        if any(ch in str(mode) for ch in "wax+"):
            opened.append(str(file))
        return real(file, mode, *a, **k)

    monkeypatch.setattr(builtins, "open", spy)
    monkeypatch.setattr(io, "open", spy)
    (tmp_path / "x.txt").write_text("x", encoding="utf-8")
    with open(tmp_path / "y.txt", "a", encoding="utf-8"):
        pass
    assert len(opened) == 2


def test_the_log_carries_counts_only(client, auth, caplog):
    with caplog.at_level(logging.DEBUG):
        assert client.post(URL, json=BODY, headers=auth).status_code == 200
    lines = [r.getMessage() for r in caplog.records if "trade-journal" in r.getMessage()]
    assert lines, "분석을 했다는 줄은 남긴다(줄 수만)"
    joined = "\n".join(r.getMessage() for r in caplog.records)
    for secret in ("ZQ9981", "19800", "19,800", "10200"):
        assert secret not in joined, f"로그에 체결 내용이 남았다: {secret}"
    assert "rows=4" in lines[0]


# ── 종목 마스터 ───────────────────────────────────────────────────────────────

def test_names_and_markets_come_from_the_stock_master_when_it_knows(client, auth, monkeypatch):
    import src.api.trade_journal_routes as mod
    flags = {"ZQ9981": {"name": "마스터가 아는 이름", "market": "KOSDAQ", "group_code": "ST"},
             "ZQ9982": {"name": "어떤 ETF", "market": "KOSPI", "group_code": "EF", "is_etf": True}}
    monkeypatch.setattr(mod, "load_master_flags", lambda: flags)
    monkeypatch.setattr(mod, "get_stock_name", lambda code: (flags.get(code) or {}).get("name"))
    rows = [{"executed_at": "2026-03-04 09:00:00", "symbol": "ZQ9981", "side": "buy", "quantity": 1, "price": 10_000},
            {"executed_at": "2026-03-04 09:10:00", "symbol": "ZQ9981", "side": "sell", "quantity": 1, "price": 10_000},
            {"executed_at": "2026-03-04 09:00:00", "symbol": "AZQ9982", "side": "buy", "quantity": 1, "price": 10_000},
            {"executed_at": "2026-03-04 09:20:00", "symbol": "AZQ9982", "side": "sell", "quantity": 1, "price": 10_000},
            {"executed_at": "2026-03-04 09:00:00", "symbol": "NOPE01", "side": "buy", "quantity": 1, "price": 10_000},
            {"executed_at": "2026-03-04 09:30:00", "symbol": "NOPE01", "side": "sell", "quantity": 1, "price": 10_000}]
    out = client.post(URL, json={"fills": rows, "commission_bp": 0}, headers=auth).json()
    by = {t["symbol"]: t for t in out["trades"]}
    assert (by["ZQ9981"]["name"], by["ZQ9981"]["taxes"]) == ("마스터가 아는 이름", 20.0)
    assert (by["AZQ9982"]["name"], by["AZQ9982"]["taxes"]) == ("어떤 ETF", 0.0), "앞에 A 가 붙은 단축코드도 찾는다"
    assert (by["NOPE01"]["name"], by["NOPE01"]["taxes"]) == (None, None), "모르는 종목의 이름·세금을 지어내지 않는다"
    assert out["basis"]["tax"] == {"observed": 0, "inferred": 2, "assumed": 0, "unknown": 1, "not_applicable": 3}


def test_without_a_loaded_master_nothing_is_made_up(client, auth, monkeypatch):
    import src.api.trade_journal_routes as mod
    monkeypatch.setattr(mod, "load_master_flags", lambda: {})
    rows = [{"executed_at": "2026-03-04 09:00:00", "symbol": "NOPE01", "side": "buy", "quantity": 1, "price": 10_000},
            {"executed_at": "2026-03-04 09:10:00", "symbol": "NOPE01", "side": "sell", "quantity": 1, "price": 10_100}]
    out = client.post(URL, json={"fills": rows, "commission_bp": 0}, headers=auth).json()
    assert out["trades"][0]["name"] is None and out["trades"][0]["net"] is None and out["trades"][0]["gross"] == 100.0


# ── 보호 등록부 ───────────────────────────────────────────────────────────────

def test_the_route_is_in_the_protected_registry_as_login_only():
    from src.api.protected_routes import PROTECTED, REQUIRE_LOGIN
    level, why = PROTECTED[("POST", URL)]
    assert level == REQUIRE_LOGIN and "매매" in why
