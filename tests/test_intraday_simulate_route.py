"""GET /api/v1/intraday/templates · POST /api/v1/intraday/simulate — 분봉 백테스트의 실행 문 (설계 §9 · W4c c2).

엔진의 계산은 `test_intraday_simulator.py`, 봉을 짓는 일은 `test_minute_feed.py` 가 건다. 여기서는 문이 지키는 약속만 본다:
로그인 · 상한과 사유(잘라서 계산하지 않는다) · 받은 설정이 그대로 엔진에 닿는다 · ★외부 호출 0 · 주문 경로에 닿지 않는다★ ·
합성이면 합성이라고 답한다 · 분봉이 없으면 없다고 답한다(빈 통계를 결과처럼 내지 않는다).
"""
from __future__ import annotations

import ast
import logging
import os
import tempfile
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

import src.data.minute_bars as mb
import src.database as dbmod
from src.domain.auth_identity import ROLE_ANALYST
from src.engine.intraday import Day, Session
from tests.route_walk import flat_routes

SIM = "/api/v1/intraday/simulate"
TEMPLATES = "/api/v1/intraday/templates"
_SECRET = "intraday-simulate-route-test-secret-0123456789"
ROOT = Path(__file__).resolve().parents[1]

BODY = {"tickers": ["005930"], "from": "2026-03-04", "to": "2026-03-04",
        "rule": {"kind": "opening_range_breakout", "params": {"minutes": 5}},
        "position": {"amount": 1_000_000}, "costs": {"commission_bp": 1.5, "slippage_ticks": 1}}


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

    from src.app_factory import create_app
    with TestClient(create_app()) as c:
        yield c

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
    mb.collect_day(tickers, day)
    mb.clear_cache()


def hand_made_day(source="kis"):
    """`test_intraday_simulator.py` 의 기본 하루 — 종가가 10,050 을 넘은 다음 봉 시가 + 1틱에 사서 마지막 봉 종가 − 1틱에 판다(+1,980원)."""
    rows = [("090000", 10_000, 10_020, 9_990, 10_000, 1_000), ("090100", 10_000, 10_060, 10_000, 10_060, 1_000),
            ("090200", 10_070, 10_100, 10_060, 10_090, 1_000), ("090300", 10_090, 10_120, 10_080, 10_110, 1_000)]
    t, o, h, low, c, v = zip(*rows)
    s = Session("005930", "2026-03-04", np.array(t), np.array(o, float), np.array(h, float), np.array(low, float),
                np.array(c, float), np.array(v, float), source, None, "KOSPI", "stock", "삼성전자")
    return [Day("2026-03-04", {"005930": s})]


def with_days(monkeypatch, days):
    import src.api.intraday_routes as mod
    from src.data import minute_feed
    monkeypatch.setattr(mod.minute_feed, "plan", lambda a, b: minute_feed.Plan([d.date for d in days], 1))
    monkeypatch.setattr(mod.minute_feed, "build_days", lambda *a, **k: days)


# ── 문 ───────────────────────────────────────────────────────────────────────────────
def test_both_routes_are_mounted_and_login_only(client):
    from src.api.protected_routes import PROTECTED, REQUIRE_LOGIN
    table = {(m, r.path) for r in flat_routes(client.app) for m in (getattr(r, "methods", None) or [])}
    assert {("POST", SIM), ("GET", TEMPLATES)} <= table
    assert PROTECTED[("POST", SIM)][0] == REQUIRE_LOGIN and PROTECTED[("GET", TEMPLATES)][0] == REQUIRE_LOGIN


def test_without_a_login_nothing_is_read_or_computed(client, monkeypatch):
    import src.api.intraday_routes as mod
    calls = []
    monkeypatch.setattr(mod.minute_feed, "build_days", lambda *a, **k: calls.append(1) or [])
    assert client.post(SIM, json=BODY).status_code == 401
    assert client.get(TEMPLATES).status_code == 401
    assert calls == []


# ── 틀 목록 ───────────────────────────────────────────────────────────────────────────
def test_templates_tell_the_screen_what_it_can_offer_and_what_cannot_be_known(client, auth):
    body = client.get(TEMPLATES, headers=auth).json()
    assert [t["kind"] for t in body["templates"]] == ["opening_range_breakout", "vwap_cross", "volatility_breakout", "gap",
                                                      "volume_surge", "rsi_reversal", "bollinger"]
    keys = [f["key"] for f in body["position"]]
    assert keys[0] == "amount" and {"stop_pct", "target_pct", "trail_pct", "time_exit", "daily_loss_limit",
                                    "cooldown_after_loss_min", "max_entries_per_ticker", "max_open_positions"} <= set(keys)
    assert all(f["label"] and f["type"] in ("int", "float", "time") for f in body["position"])
    assert [f["key"] for f in body["costs"]] == ["commission_bp", "slippage_ticks", "participation_cap", "unknown_market", "unknown_instrument"]
    assert body["limits"]["tickers"] == 30 and body["limits"]["ticker_days"] > 0 and body["limits"]["range_days"] > 0
    assert {u["what"] for u in body["unknowns"]} == {"bar_label", "lookback", "auction_vi_halt"}
    assert body["session_rules"]["available"] is True and body["gate"] == {"mock": True}


def test_the_form_defaults_are_values_the_engine_accepts(client, auth):
    from src.engine.intraday import CostAssumptions, PositionRules, rules, simulator
    body = client.get(TEMPLATES, headers=auth).json()
    position = PositionRules(**{f["key"]: f["default"] for f in body["position"] if f["default"] is not None})
    costs = CostAssumptions(**{f["key"]: f["default"] for f in body["costs"] if f["default"] is not None})
    simulator.validate(rules.build("opening_range_breakout"), position, costs)
    assert costs.commission_bp is None                       # 수수료율의 기본은 '모름'이다 — 지어낸 요율로 채우지 않는다


# ── 실행 ─────────────────────────────────────────────────────────────────────────────
def test_the_engine_s_answer_comes_back_unchanged(client, auth, monkeypatch):
    """손으로 계산한 하루를 문으로 돌린다 — +1,980원(비용 전) · 수수료 1.5bp 와 매도세 20bp 를 뺀 값(비용 뒤)."""
    import src.api.intraday_routes as mod
    with_days(monkeypatch, hand_made_day())
    crossing = {"entry": {"op": "cross_up", "args": [{"ind": "close"}, {"const": 10_050}]}}
    monkeypatch.setattr(mod.rules, "build", lambda kind, params=None: mod.RuleSpec(**crossing))
    body = client.post(SIM, json=BODY, headers=auth).json()
    assert body["journal"]["summary"]["gross"]["total"] == 1_980
    # 매수 997,920 · 매도 999,900 → 수수료 1.5bp 149.69 + 149.99 · 매도세 20bp 1,999.80 → 1,980 − 2,299.47 = −319.47
    assert body["journal"]["summary"]["net"]["total"] == pytest.approx(-319.47, abs=0.01)
    assert body["origin"] == {"kind": "simulated", "sessions": {"kis": 1, "synthetic": 0, "unknown": 0}, "grade": "E3",
                              "grade_reason": "쓰인 분봉이 전부 제공자의 실제 응답입니다."}
    assert body["data"]["days"] == 1 and body["data"]["sessions"] == 1 and body["data"]["bars"] == 4
    assert body["events_by_kind"] == {"entry_signal": 1, "session_end": 1}
    assert body["empty"] is None
    # 손익분기 비용: 1,980 ÷ (997,920 + 999,900) × 10,000 = 9.91bp
    assert body["breakeven"]["bp"] == pytest.approx(1_980 / 1_997_820 * 10_000)


def test_the_request_reaches_the_engine_as_sent(client, auth, monkeypatch):
    import src.api.intraday_routes as mod
    with_days(monkeypatch, hand_made_day())
    seen = {}

    def spy(days, rule, position, costs, **kw):
        seen.update(rule=rule, position=position, costs=costs, kw=kw)
        return real(days, rule, position, costs, **kw)

    real = mod.intraday.run
    monkeypatch.setattr(mod.intraday, "run", spy)
    sent = {**BODY, "rule": {"kind": "rsi_reversal", "params": {"n": 7}},
            "position": {"amount": 2_000_000, "stop_pct": 1.5, "time_exit": "1500", "daily_loss_limit": 50_000},
            "costs": {"commission_bp": 0, "slippage_ticks": 2, "participation_cap": 0.25}}
    body = client.post(SIM, json=sent, headers=auth).json()
    assert seen["rule"] == mod.rules.build("rsi_reversal", {"n": 7})
    assert (seen["position"].amount, seen["position"].stop_pct, seen["position"].time_exit, seen["position"].daily_loss_limit) == \
           (2_000_000, 1.5, "1500", 50_000)
    assert (seen["costs"].commission_bp, seen["costs"].slippage_ticks, seen["costs"].participation_cap) == (0, 2, 0.25)
    assert seen["kw"]["rules"]["available"] is True and callable(seen["kw"]["master"])
    assert body["request"]["rule"] == {"kind": "rsi_reversal", "params": {"n": 7, "oversold": 30.0, "overbought": 70.0}}
    assert body["request"]["tickers"] == ["005930"]


def test_the_answer_lists_what_the_simulator_does_not_model(client, auth):
    import src.api.intraday_routes as mod
    collect(["005930"], "2026-03-04")
    body = client.post(SIM, json=BODY, headers=auth).json()
    assert body["journal"]["not_covered"] == list(mod.intraday.NOT_MODELED)
    assert not any("파일" in s for s in body["journal"]["not_covered"])


def test_with_synthetic_bars_the_answer_says_so(client, auth):
    collect(["005930", "000660"], "2026-03-04")
    body = client.post(SIM, json={**BODY, "tickers": ["005930", "000660", "035720"]}, headers=auth).json()
    assert body["origin"]["grade"] == "E0" and "합성" in body["origin"]["grade_reason"]
    assert body["origin"]["sessions"] == {"kis": 0, "synthetic": 2, "unknown": 0} and body["gate"] == {"mock": True}
    assert body["data"]["sessions"] == 2 and body["data"]["bars"] == 780
    assert body["data"]["skipped"] == [{"date": "2026-03-04", "ticker": "035720", "reason": "no_bars",
                                        "message": "이 날짜에 이 종목의 분봉이 없습니다."}]
    assert body["data"]["skipped_total"] == 1 and body["data"]["skipped_by_reason"] == {"no_bars": 1}
    assert all(a["label"].endswith("니다.") and a["count"] > 0 for a in body["assumptions"])


def test_when_no_bars_are_loaded_the_answer_is_empty_with_a_reason_not_a_zero_result(client, auth):
    body = client.post(SIM, json=BODY, headers=auth).json()
    assert body["empty"] == {"reason": "not_loaded", "message": "이 기간에 적재된 분봉이 없습니다."}
    assert body["journal"] is None and body["breakeven"] is None and body["data"]["days"] == 0


def test_in_production_synthetic_bars_are_not_simulated_and_the_broker_is_never_built(client, auth, monkeypatch):
    collect(["005930"], "2026-03-04")
    import src.execution.kis_client as kc

    def boom(*a, **k):
        raise AssertionError("분봉 백테스트가 증권사 클라이언트를 만들었다")

    monkeypatch.setattr(kc, "get_kis_client", boom)
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    body = client.post(SIM, json=BODY, headers=auth).json()
    assert body["gate"] == {"mock": False} and body["data"]["sessions"] == 0
    assert body["data"]["skipped"][0]["reason"] == "synthetic_rows_blocked"
    assert body["origin"]["grade"] is None and body["journal"]["inputs"]["fills"] == 0
    assert body["empty"] == {"reason": "no_usable_bars", "message": "쓸 수 있는 분봉이 없습니다. 건너뛴 사유를 보십시오."}


# ── 상한과 거절 ────────────────────────────────────────────────────────────────────────
def refuse(client, auth, body) -> dict:
    r = client.post(SIM, json=body, headers=auth)
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["reason"].endswith("니다.")
    return r.json()["detail"]


def test_too_many_tickers_are_refused_not_truncated(client, auth):
    detail = refuse(client, auth, {**BODY, "tickers": [f"{i:06d}" for i in range(31)]})
    assert detail["code"] == "too_many_tickers" and detail["limit"] == 30 and detail["tickers"] == 31
    assert refuse(client, auth, {**BODY, "tickers": []})["code"] == "no_tickers"
    assert refuse(client, auth, {**BODY, "tickers": ["  ", ""]})["code"] == "no_tickers"


def test_ranges_are_checked_before_anything_is_read(client, auth, monkeypatch):
    import src.api.intraday_routes as mod
    monkeypatch.setattr(mod.minute_feed, "build_days", lambda *a, **k: (_ for _ in ()).throw(AssertionError("읽었다")))
    assert refuse(client, auth, {**BODY, "from": "2026-03-05", "to": "2026-03-04"})["code"] == "bad_range"
    long = refuse(client, auth, {**BODY, "from": "2025-01-01", "to": "2026-03-04"})
    assert long["code"] == "range_too_long" and long["limit"] == mod.MAX_RANGE_DAYS


def test_too_many_ticker_days_or_too_much_data_is_refused_before_reading(client, auth, monkeypatch):
    import src.api.intraday_routes as mod
    collect(["005930", "000660"], "2026-03-04")
    collect(["005930"], "2026-03-05")
    monkeypatch.setattr(mod.minute_feed, "build_days", lambda *a, **k: (_ for _ in ()).throw(AssertionError("읽었다")))
    two_days = {**BODY, "tickers": ["005930", "000660"], "to": "2026-03-05"}
    monkeypatch.setattr(mod, "MAX_TICKER_DAYS", 3)
    detail = refuse(client, auth, two_days)                  # 종목 2 × 적재일 2 = 4
    assert detail["code"] == "too_many_ticker_days" and detail["limit"] == 3 and detail["ticker_days"] == 4
    monkeypatch.setattr(mod, "MAX_TICKER_DAYS", 4)
    monkeypatch.setattr(mod, "MAX_LOAD_BYTES", 10)
    detail = refuse(client, auth, two_days)
    assert detail["code"] == "too_much_data" and detail["limit"] == 10 and detail["bytes"] > 10


def test_exactly_the_limit_is_accepted(client, auth, monkeypatch):
    import src.api.intraday_routes as mod
    collect(["005930", "000660"], "2026-03-04")
    monkeypatch.setattr(mod, "MAX_TICKER_DAYS", 2)
    assert client.post(SIM, json={**BODY, "tickers": ["005930", "000660"]}, headers=auth).status_code == 200


@pytest.mark.parametrize("change, code", [
    ({"rule": {"kind": "macd_cross", "params": {}}}, "unknown_kind"),
    ({"rule": {"kind": "opening_range_breakout", "params": {"minutes": 0}}}, "param_out_of_range"),
    ({"rule": {"kind": "gap", "params": {"direction": "sideways"}}}, "bad_choice"),
    ({"position": {"amount": 0}}, "bad_amount"),
    ({"position": {"amount": 1_000_000, "stop_pct": 100}}, "bad_percent"),
    ({"position": {"amount": 1_000_000, "time_exit": "25:00"}}, "bad_time"),
    ({"position": {"amount": 1_000_000, "max_entries_per_ticker": 0}}, "bad_count"),
    ({"costs": {"slippage_ticks": -1}}, "bad_slippage"),
    ({"costs": {"participation_cap": 2}}, "bad_participation"),
    ({"costs": {"commission_bp": -1}}, "bad_commission"),
])
def test_a_bad_setting_is_refused_with_the_engine_s_reason(client, auth, change, code):
    assert refuse(client, auth, {**BODY, **change})["code"] == code


@pytest.mark.parametrize("change", [{"position": {"amount": 1, "leverage": 3}}, {"costs": {"fee": 1}}, {"rule": {"kind": "gap"}, "extra": 1},
                                    {"from": "3월 4일"}, {"position": {}}])
def test_a_malformed_body_is_422_not_a_silent_default(client, auth, change):
    assert client.post(SIM, json={**BODY, **change}, headers=auth).status_code == 422


# ── 쓰지 않는다 · 주문 경로에 닿지 않는다 ───────────────────────────────────────────────
def test_the_log_carries_counts_only(client, auth, caplog):
    collect(["005930"], "2026-03-04")
    with caplog.at_level(logging.INFO, logger="api.intraday"):
        client.post(SIM, json=BODY, headers=auth)
    lines = [r.getMessage() for r in caplog.records if r.name == "api.intraday"]
    assert lines and all("005930" not in line for line in lines)


def test_the_bar_files_are_not_touched(client, auth, tmp_path):
    collect(["005930"], "2026-03-04")
    root = tmp_path / "bars"
    before = {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in root.iterdir()}
    client.post(SIM, json=BODY, headers=auth)
    assert {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in root.iterdir()} == before


def test_the_intraday_modules_never_import_the_order_path():
    """정적 시험 — 분봉 백테스트의 문·봉 준비·엔진은 주문 경로와 증권사 클라이언트를 들이지 않는다."""
    banned = ("trading_engine", "order_executor", "kis_client", "execution")
    files = [ROOT / "src/api/intraday_routes.py", ROOT / "src/data/minute_feed.py", ROOT / "src/data/minute_quality.py",
             ROOT / "src/data/intraday_trials.py", *sorted((ROOT / "src/engine/intraday").glob("*.py"))]
    assert len(files) >= 12
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)] + \
                [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        assert not [n for n in names if any(b in n.lower() for b in banned)], path.name


def test_the_static_check_would_catch_such_an_import(tmp_path):
    planted = tmp_path / "x.py"
    planted.write_text("from src.execution.kis_client import get_kis_client\n", encoding="utf-8")
    names = [n.module or "" for n in ast.walk(ast.parse(planted.read_text())) if isinstance(n, ast.ImportFrom)]
    assert [n for n in names if "kis_client" in n.lower()]

