"""시장 국면(일)의 문 — `GET /api/v1/intraday/market-regime` (구현 계획 §7.1 · K1).

엔진의 계산은 `test_market_regime.py` 가 건다. 여기서는 문이 지키는 약속:
로그인 · 인자가 빠지면 기본값으로 채우지 않는다(422) · 기간 상한과 순서는 ★읽기 전에★ · 지수 일봉은 판정 시작일의 HISTORY 앞부터 한 길(지수 읽기)로 ·
mock 은 등급 E0 과 알림 ↔ 적재(DB)는 E3 · 운영에서 합성 출처면 국면을 내지 않는다(빈 값 + 사유) · 적재가 없으면 로더의 사유를 싣는다 ·
저장소 장애는 '못 읽음'(적재가 없다는 말이 아니다) · 운영은 증권사를 부르지 않는다 · 상한 문은 상수만 ·
적재가 판정 앞을 덮지 못하면 그 달은 미상 + 사유(조용히 짧은 창으로 적합하지 않는다) · 쓰기 0 · 증권사 클라이언트를 만들지 않는다 · 주문 경로를 들여오지 않는다.
"""
from __future__ import annotations

import ast
import os
import tempfile
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

import src.api.intraday_market_regime_routes as routes
import src.database as dbmod
from src.data import ohlcv_loader
from src.domain.auth_identity import ROLE_ANALYST
from src.engine import market_regime as mr
from tests.route_walk import flat_routes

URL = "/api/v1/intraday/market-regime"
_SECRET = "intraday-market-regime-route-test-secret-0123456789"
ROOT = Path(__file__).resolve().parents[1]
Q = {"index": "KOSPI", "k": 2, "from": "2026-01-02", "to": "2026-03-31"}


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


def frame(dates: list[str], closes, source: str | None, coverage_ok=True, coverage_reason=None) -> pd.DataFrame:
    df = pd.DataFrame({"open": closes, "high": closes, "low": closes, "close": closes, "volume": 0.0},
                      index=pd.to_datetime(dates))
    if source is not None:
        df.attrs["source"] = source
    df.attrs["coverage_ok"] = coverage_ok
    df.attrs["coverage_reason"] = coverage_reason
    return df


def two_level(start: str, end: str, seed: int = 7) -> tuple[list[str], np.ndarray]:
    """영업일 걸음 — 120일마다 일 0.5% ↔ 2% (엔진 시험의 두 단계 자료와 같은 꼴)."""
    dates = [d.strftime("%Y-%m-%d") for d in pd.bdate_range(start, end)]
    vols = np.array([0.005 if (i // 120) % 2 == 0 else 0.02 for i in range(len(dates))])
    rng = np.random.default_rng(seed)
    return dates, 2500.0 * np.exp(np.cumsum(rng.normal(0.0, 1.0, len(dates)) * vols))


def fake_loader(monkeypatch, df: pd.DataFrame, calls: list | None = None):
    def load(code, start, end):
        if calls is not None:
            calls.append((code, start, end))
        out = df.copy() if not df.empty else df
        out.attrs.update(df.attrs)
        return out
    monkeypatch.setattr(routes, "load_index_daily", load)


def row_counts() -> dict[str, int]:
    eng = dbmod.get_engine()
    out = {}
    with eng.connect() as c:
        for t in inspect(eng).get_table_names():
            out[t] = int(c.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar())
    return out


# ── 로그인 · 인자 ─────────────────────────────────────────────────────────────────────────
def test_the_door_needs_a_login(client):
    assert client.get(URL, params=Q).status_code == 401


@pytest.mark.parametrize("missing", ["index", "k", "from", "to"])
def test_a_missing_argument_is_refused_not_filled_with_a_default(client, auth, missing):
    q = {k: v for k, v in Q.items() if k != missing}
    assert client.get(URL, params=q, headers=auth).status_code == 422


@pytest.mark.parametrize("bad", [{"index": "KS11"}, {"index": "kospi"}, {"k": 1}, {"k": 5}, {"from": "2026-13-01"}])
def test_an_unknown_index_or_a_number_of_states_out_of_range_is_refused(client, auth, bad):
    assert client.get(URL, params={**Q, **bad}, headers=auth).status_code == 422


@pytest.mark.parametrize("k", [2, 3, 4])
def test_two_to_four_states_are_all_accepted(client, auth, k):
    r = client.get(URL, params={**Q, "k": k}, headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["k"] == k and len(r.json()["states"]) == k


@pytest.mark.parametrize("frm, to, code", [("2026-03-02", "2026-03-01", "bad_range"),
                                           ("2025-01-01", "2026-01-02", "range_too_long")])
def test_range_limits_are_refused_before_anything_is_read(client, auth, monkeypatch, frm, to, code):
    def boom(*a, **k):
        raise AssertionError("상한을 넘은 요청이 일봉을 읽었다")
    monkeypatch.setattr(routes, "load_index_daily", boom)
    r = client.get(URL, params={**Q, "from": frm, "to": to}, headers=auth)
    assert r.status_code == 400 and r.json()["detail"]["code"] == code
    assert r.json()["detail"]["reason"] == routes.REASONS[code]


def test_exactly_the_longest_range_is_read(client, auth):
    """짝 — 366일(양 끝 포함)은 받는다."""
    r = client.get(URL, params={**Q, "from": "2025-01-01", "to": "2026-01-01"}, headers=auth)
    assert r.status_code == 200, r.text


# ── 읽기 · 등급 ───────────────────────────────────────────────────────────────────────────
def test_the_door_reads_the_history_before_the_judged_period_through_one_loader_path(client, auth, monkeypatch):
    calls: list = []
    dates, closes = two_level("2021-01-01", "2026-03-31")
    fake_loader(monkeypatch, frame(dates, closes, "db"), calls)
    assert client.get(URL, params=Q, headers=auth).status_code == 200
    start = (date(2026, 1, 2) - timedelta(days=routes.HISTORY_CALENDAR_DAYS)).isoformat()
    assert calls == [("KOSPI", start, "2026-03-31")]


def test_the_mock_gate_answers_synthetic_closes_as_e0_with_the_engine_answer(client, auth):
    r = client.get(URL, params=Q, headers=auth)
    assert r.status_code == 200, r.text
    js = r.json()
    assert (js["grade"], js["source"], js["mock"], js["empty"]) == ("E0", "mock", True, None)
    want = ohlcv_loader.load_ohlcv_unified("KOSPI", "2026-01-02", "2026-03-31", prefer="mock")
    assert [d["date"] for d in js["days"]] == [d.strftime("%Y-%m-%d") for d in want.index]   # 판정 기간의 거래일 그대로
    valued = [d for d in js["days"] if d["probs"] is not None]
    assert valued and all(len(d["probs"]) == 2 and abs(sum(d["probs"]) - 1) < 1e-9 for d in valued)
    assert all(d["top"] == 1 + int(np.argmax(d["probs"])) for d in valued)
    assert set(js["bic"]) == {"2", "3", "4"} and js["fit"]["window_days"] == mr.FIT_DAYS and js["fit"]["seeds"] == mr.SEEDS
    assert js["notes"] == list(routes.NOTES)


def test_the_numbering_note_says_which_volatility_orders_the_numbers_and_that_the_table_may_differ():
    """K1b — '변동성이 낮은 것부터'만으로는 어느 변동성인지 모른다. 화면의 국면별 통계도 '실현 변동성'이라 그 순서로 읽히는데,
    번호는 적합 창에서 성분의 σ20 평균 순이고 표는 그 기간의 일 수익이라 어긋날 수 있다(엔진 시험
    `test_the_table_volatility_can_leave_the_numbering_order_without_regimes` 가 어긋나는 자료를 보인다)."""
    note = [n for n in routes.NOTES if n.startswith("국면 번호")]
    assert len(note) == 1
    assert "적합 창에서 20거래일 실현 변동성의 평균이 낮은 국면부터 매겼습니다" in note[0]
    assert "국면별 통계의 실현 변동성은 이 기간에 그 국면으로 센 날들의 일 수익으로 잰 값이라 번호 순서와 다를 수 있습니다" in note[0]


def test_the_answer_equals_the_engine_on_the_same_closes(client, auth, monkeypatch):
    """문은 계산하지 않는다 — 같은 종가를 엔진에 넣은 값과 같다."""
    dates, closes = two_level("2021-01-01", "2026-03-31")
    fake_loader(monkeypatch, frame(dates, closes, "db"))
    js = client.get(URL, params=Q, headers=auth).json()
    want = mr.regime_days(dates, closes, k=2, start="2026-01-02", end="2026-03-31")
    assert js["days"] == want["days"] and js["states"] == want["states"] and js["transitions"] == want["transitions"]
    assert js["bic"] == want["bic"] and js["agreement"] == want["agreement"] and js["fit"] == want["fit"]
    assert (js["grade"], js["source"]) == ("E3", "db")


def test_the_two_indexes_are_read_separately(client, auth):
    a = client.get(URL, params=Q, headers=auth).json()
    b = client.get(URL, params={**Q, "index": "KOSDAQ"}, headers=auth).json()
    assert (a["index"], b["index"]) == ("KOSPI", "KOSDAQ") and (a["name"], b["name"]) == ("코스피", "코스닥")
    assert [d["probs"] for d in a["days"]] != [d["probs"] for d in b["days"]]


def test_production_answers_loaded_closes_as_e3(client, auth, monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    dates, closes = two_level("2021-01-01", "2026-03-31")
    fake_loader(monkeypatch, frame(dates, closes, "db"))
    js = client.get(URL, params=Q, headers=auth).json()
    assert (js["grade"], js["source"], js["mock"], js["empty"]) == ("E3", "db", False, None) and js["days"]


def test_a_broker_labelled_index_frame_is_not_graded_real(client, auth, monkeypatch):
    """짝 — 지수 경로에는 증권사 출처가 없다. 그런 표가 붙어 오면 실데이터로 올리지 않는다(등급 미상 + 사유)."""
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    dates, closes = two_level("2021-01-01", "2026-03-31")
    fake_loader(monkeypatch, frame(dates, closes, "kis"))
    js = client.get(URL, params=Q, headers=auth).json()
    assert js["grade"] is None and js["grade_reason"] == routes.GRADE_UNKNOWN


def test_production_never_computes_regimes_on_synthetic_closes(client, auth, monkeypatch):
    """로더가 이미 막지만 문이 한 번 더 본다 — 짝: 같은 종가가 실데이터 출처면 값이 나온다(위 시험)."""
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    dates, closes = two_level("2021-01-01", "2026-03-31")
    fake_loader(monkeypatch, frame(dates, closes, "mock"))
    js = client.get(URL, params=Q, headers=auth).json()
    assert js["days"] == [] and js["states"] == [] and js["grade"] is None
    assert js["empty"] == {"reason": "synthetic_in_production", "message": routes.EMPTY["synthetic_in_production"]}


def test_an_unlabelled_source_is_unknown_not_real(client, auth, monkeypatch):
    """미상 ≠ 실데이터 — 출처 표가 없는 일봉은 등급을 매기지 않는다(값은 내되 등급 None + 사유)."""
    dates, closes = two_level("2021-01-01", "2026-03-31")
    fake_loader(monkeypatch, frame(dates, closes, None))
    js = client.get(URL, params=Q, headers=auth).json()
    assert js["grade"] is None and js["source"] is None and js["grade_reason"] == routes.GRADE_UNKNOWN


def test_nothing_loaded_is_said_with_the_loaders_own_reason(client, auth, monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    empty = pd.DataFrame()
    empty.attrs.update(coverage_ok=False, coverage_reason="실데이터가 없습니다(합성 금지).")
    fake_loader(monkeypatch, empty)
    js = client.get(URL, params=Q, headers=auth).json()
    assert js["days"] == [] and js["grade"] is None
    assert js["empty"] == {"reason": "not_loaded", "message": routes.EMPTY["not_loaded"].format(name="코스피")}
    assert js["coverage"] == {"ok": False, "reason": "실데이터가 없습니다(합성 금지)."}


def test_closes_outside_the_judged_period_only_are_also_not_loaded(client, auth, monkeypatch):
    dates, closes = two_level("2021-01-01", "2025-12-30")                 # 판정 기간 앞에서 끝난다
    fake_loader(monkeypatch, frame(dates, closes, "db"))
    js = client.get(URL, params=Q, headers=auth).json()
    assert js["days"] == [] and js["empty"]["reason"] == "not_loaded"


def test_a_short_history_leaves_early_months_unknown_with_numbers_and_carries_the_coverage_reason(client, auth, monkeypatch):
    """적재가 판정 앞 1년뿐이면 — 조용히 짧은 창으로 적합하지 않는다. 그 달은 미상 + 필요 · 있는 날 수."""
    dates, closes = two_level("2025-01-02", "2026-03-31")
    why = "적재 구간이 요청을 덮지 못합니다 — 시작 2025-01-02 > 요청 2022-07-31"
    fake_loader(monkeypatch, frame(dates, closes, "db", coverage_ok=False, coverage_reason=why))
    js = client.get(URL, params=Q, headers=auth).json()
    assert js["coverage"] == {"ok": False, "reason": why}
    first = js["days"][0]
    assert first["probs"] is None and str(mr.FIT_DAYS) in first["reason"]
    assert not any(d["probs"] for d in js["days"])                       # 석 달 모두 창이 다 차지 않는다


def test_dates_that_repeat_are_not_computed(client, auth, monkeypatch):
    dates, closes = two_level("2021-01-01", "2026-03-31")
    dates[500] = dates[499]
    fake_loader(monkeypatch, frame(dates, closes, "db"))
    js = client.get(URL, params=Q, headers=auth).json()
    assert js["days"] == [] and js["empty"] == {"reason": "bad_dates", "message": routes.EMPTY["bad_dates"]}


def test_a_store_outage_is_cannot_read_not_nothing_loaded(client, auth, monkeypatch):
    """미상 ≠ 없음 — 저장소 장애를 '적재되지 않음'으로 접지 않는다. 짝: 장애 표시가 없는 빈 일봉은 not_loaded."""
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    down = pd.DataFrame()
    down.attrs.update(source="db", coverage_ok=False, coverage_reason="가격 저장소를 읽지 못했습니다.", db_error="커넥션 풀 고갈")
    fake_loader(monkeypatch, down)
    js = client.get(URL, params=Q, headers=auth).json()
    assert js["days"] == [] and js["empty"] == {"reason": "store_error", "message": routes.EMPTY["store_error"]}
    none = pd.DataFrame()
    none.attrs.update(source="db", coverage_ok=False, coverage_reason="적재분이 없습니다.")
    fake_loader(monkeypatch, none)
    assert client.get(URL, params=Q, headers=auth).json()["empty"]["reason"] == "not_loaded"


def test_production_reads_the_store_and_never_builds_a_broker_client(client, auth, monkeypatch):
    """실제 지수 읽기(`load_index_daily`)로 — 저장소의 행만 쓰고 증권사 클라이언트를 만들지 않는다(운영 게이트에서)."""
    import src.execution.kis_client as kc

    def boom(*a, **k):
        raise AssertionError("운영의 시장 국면이 증권사에 닿았다")
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    monkeypatch.setattr(kc, "get_kis_client", boom)
    monkeypatch.setattr(ohlcv_loader, "_kis_ohlcv_df", boom)
    dates, closes = two_level("2021-01-01", "2026-03-31")
    rows = pd.DataFrame({"open": closes, "high": closes, "low": closes, "close": closes, "volume": 0.0}, index=pd.to_datetime(dates))
    monkeypatch.setattr(ohlcv_loader, "_db_index_rows", lambda code, s, e: rows[(rows.index >= s) & (rows.index <= e)].copy())
    r = client.get(URL, params=Q, headers=auth)
    assert r.status_code == 200, r.text
    js = r.json()
    assert (js["grade"], js["source"], js["empty"]) == ("E3", "db", None) and js["days"]


def test_the_limits_door_gives_the_constants_and_needs_a_login(client, auth):
    assert client.get(URL + "/limits").status_code == 401
    js = client.get(URL + "/limits", headers=auth).json()
    assert js == {"range_days": routes.MAX_RANGE_DAYS, "k": list(mr.K_RANGE), "fit_days": mr.FIT_DAYS, "window": mr.WINDOW,
                  "seeds": mr.SEEDS, "history_calendar_days": routes.HISTORY_CALENDAR_DAYS,
                  "indexes": [{"code": "KOSPI", "name": "코스피"}, {"code": "KOSDAQ", "name": "코스닥"}]}
    assert client.get(URL, params=Q, headers=auth).json()["limits"] == js          # 답에 실린 상한과 같은 값


# ── 쓰기 0 · 경계 ─────────────────────────────────────────────────────────────────────────
def test_reading_regimes_writes_nothing(client, auth):
    before = row_counts()
    assert client.get(URL, params=Q, headers=auth).status_code == 200
    assert row_counts() == before


def test_the_door_never_builds_a_broker_client(client, auth, monkeypatch):
    import src.execution.kis_client as kc

    def boom(*a, **k):
        raise AssertionError("시장 국면이 증권사 클라이언트를 만들었다")
    monkeypatch.setattr(kc, "get_kis_client", boom)
    assert client.get(URL, params=Q, headers=auth).status_code == 200


def test_the_new_modules_never_import_the_order_path():
    banned = ("trading_engine", "order_executor", "kis_client", "execution")
    for path in (ROOT / "src/api/intraday_market_regime_routes.py", ROOT / "src/engine/market_regime.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)] + \
                [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        assert names and not [n for n in names if any(b in n.lower() for b in banned)], path.name


def test_the_door_is_registered_and_locked(client):
    from src.api.protected_routes import PROTECTED, REQUIRE_LOGIN
    walked = {(m, r.path) for r in flat_routes(client.app) for m in (getattr(r, "methods", None) or [])}
    for path in (URL, URL + "/limits"):
        assert ("GET", path) in walked
        assert PROTECTED[("GET", path)][0] == REQUIRE_LOGIN
    assert routes.router.prefix == "/api/v1/intraday"
