"""하루 유형 모형의 문 — `POST/GET /api/v1/intraday/day-types` · `GET /api/v1/intraday/day-types/{key}` (구현 계획 2026-11-16 §5.3 · T1).

엔진의 계산은 `test_intraday_day_types.py`, 저장은 `test_intraday_day_types_store.py` 가 건다. 여기서는 문이 지키는 약속:
로그인 · 상한은 ★읽기 전에★(실행 문과 같은 값) · 같은 입력 = 같은 열쇠(다시 학습하지 않는다) · 봉이 바뀌면 다른 모형 ·
운영에서는 합성 분봉으로 학습하지 않고 합성 모형을 내주지 않는다(뺀 수는 사유와 함께) · 남의 모형 = 없는 모형 ·
저장하지 못하면 그렇다고 답한다 · 외부 호출 0 · 주문 경로를 들여오지 않는다.
"""
from __future__ import annotations

import ast
import os
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import src.api.intraday_day_type_routes as routes
import src.data.minute_bars as mb
import src.database as dbmod
from src.data import intraday_day_types as store
from src.data import minute_feed
from src.domain.auth_identity import ROLE_ANALYST
from src.engine.intraday import SKIP_REASONS, Day, Session
from src.engine.intraday import day_types as dt
from tests.route_walk import flat_routes

URL = "/api/v1/intraday/day-types"
_SECRET = "intraday-day-types-route-test-secret-0123456789"
ROOT = Path(__file__).resolve().parents[1]
COLS = ["ticker", "time", "open", "high", "low", "close", "volume", "source"]
PATHS = ([10.0, 20.0, 30.0, 40.0, 50.0], [-10.0, -20.0, -30.0, -40.0, -50.0],
         [-10.0, -20.0, -30.0, -20.0, -10.0], [10.0, 20.0, 30.0, 20.0, 10.0])
TICKERS = ("005930", "000660")
DAYS = ["2026-05-04", "2026-05-05", "2026-05-06", "2026-05-07", "2026-05-08", "2026-05-11",
        "2026-05-12", "2026-05-13", "2026-05-14", "2026-05-15", "2026-05-18", "2026-05-19"]
BODY = {"tickers": list(TICKERS), "from": DAYS[0], "to": DAYS[-1], "minutes": 5, "k": 4}


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


def login(client, who="alice") -> dict[str, str]:
    tok = client.post("/api/v1/auth/login", json={"username": who, "password": f"{who}-pw"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture()
def auth(client) -> dict[str, str]:
    return login(client)


def write_day(day: str, rows: list[tuple[str, list[float], str]]) -> None:
    """(종목, bp 경로, 출처) → 그날의 일파일. 첫 봉 시가 10,000 · 09:00 부터 1분마다 · 10bp = 10원."""
    recs = []
    for ticker, path, source in rows:
        prev = 10_000.0
        for i, p in enumerate(path):
            close = 10_000.0 + p
            recs.append((ticker, f"09{i:02d}00", prev, max(prev, close), min(prev, close), close, 1_000.0, source))
            prev = close
    mb._write_day_file(pd.DataFrame(recs, columns=COLS), day)
    mb.clear_cache()


def plant(source="kis", days=DAYS) -> None:
    """종목 둘 × 열이틀 = 24표본 · 유형 넷이 여섯 번씩(표본 i 는 유형 i % 4)."""
    i = 0
    for day in days:
        rows = []
        for ticker in TICKERS:
            rows.append((ticker, PATHS[i % 4], source))
            i += 1
        write_day(day, rows)


def table_rows() -> int:
    with dbmod.get_engine().connect() as c:
        try:
            return int(c.execute(text("SELECT COUNT(*) FROM intraday_day_types")).scalar())
        except Exception:                                            # noqa: BLE001 — 표가 아직 없으면 0
            return 0


# ── 로그인 · 학습 ─────────────────────────────────────────────────────────────────────────
def test_every_door_needs_a_login(client):
    assert client.post(URL, json=BODY).status_code == 401
    assert client.get(URL).status_code == 401
    assert client.get(f"{URL}/{'a' * 64}").status_code == 401


def test_training_answers_a_model_and_keeps_it(client, auth):
    plant()
    r = client.post(URL, json=BODY, headers=auth)
    assert r.status_code == 200, r.text
    js = r.json()
    m = js["model"]
    assert js["created"] is True and js["stored"] is True and js["store_reason"] is None
    assert len(m["key"]) == 64 and m["samples"] == 24 and m["minutes"] == 5 and m["k"] == 4
    assert (m["method"], m["version"], m["seed"]) == ("e-means", 1, 1234)
    assert m["tickers"] == ["000660", "005930"] and (m["first_day"], m["last_day"]) == (DAYS[0], DAYS[-1])
    assert [t["samples"] for t in m["types"]] == [6, 6, 6, 6]
    np.testing.assert_allclose(m["types"][0]["path"], PATHS[1], atol=1e-3)     # 끝값이 가장 낮은 유형이 1
    assert m["agreement"]["same"] is True
    assert m["grade"] == "E3" and m["synthetic"] is False
    assert m["days"] == DAYS and m["starts"] == [{"start": "0900", "samples": 24}]
    assert m["excluded"] == {"total": 0, "by_reason": {}, "messages": {}, "rows": []}
    assert len(m["members"]) == 24 and {x["type"] for x in m["members"]} == {1, 2, 3, 4}
    assert m["request"] == {"tickers": ["005930", "000660"], "from": DAYS[0], "to": DAYS[-1], "minutes": 5, "k": 4}
    assert js["notes"] and all("예측합니다" not in n for n in js["notes"])
    assert table_rows() == 1


def test_my_list_and_one_model_read_back_what_was_trained(client, auth):
    plant()
    made = client.post(URL, json=BODY, headers=auth).json()["model"]
    listed = client.get(URL, headers=auth).json()
    assert listed["available"] is True and listed["hidden_synthetic"] == 0
    assert [x["key"] for x in listed["models"]] == [made["key"]]
    assert "types" not in listed["models"][0]                       # 목록은 가볍다
    assert listed["limits"]["k"] == [4, 16] and listed["limits"]["minutes"] == [5, 120]
    one = client.get(f"{URL}/{made['key']}", headers=auth).json()["model"]
    assert one["types"] == made["types"] and one["created_at"] == made["created_at"]


def test_the_same_request_returns_the_kept_model_without_training_again(client, auth, monkeypatch):
    plant()
    first = client.post(URL, json=BODY, headers=auth).json()

    def boom(*a, **k):
        raise AssertionError("같은 열쇠인데 다시 학습했다")
    monkeypatch.setattr(dt, "fit", boom)
    again = client.post(URL, json=BODY, headers=auth).json()
    assert again["created"] is False and again["stored"] is True
    assert again["model"]["key"] == first["model"]["key"]
    assert again["model"]["created_at"] == first["model"]["created_at"]
    assert table_rows() == 1


def test_a_wider_period_over_the_same_samples_is_the_same_model(client, auth):
    plant()
    key = client.post(URL, json=BODY, headers=auth).json()["model"]["key"]
    wider = client.post(URL, json={**BODY, "from": "2026-04-20"}, headers=auth).json()
    assert wider["model"]["key"] == key and wider["created"] is False


def test_a_changed_bar_is_a_new_model(client, auth):
    plant()
    key = client.post(URL, json=BODY, headers=auth).json()["model"]["key"]
    write_day(DAYS[0], [("005930", [10.0, 20.0, 30.0, 40.0, 60.0], "kis"), ("000660", PATHS[1], "kis")])
    changed = client.post(URL, json=BODY, headers=auth).json()
    assert changed["model"]["key"] != key and changed["created"] is True
    assert table_rows() == 2


# ── 상한 · 거절 ─────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("patch, code", [
    ({"tickers": []}, "no_tickers"),
    ({"tickers": [f"{i:06d}" for i in range(31)]}, "too_many_tickers"),
    ({"from": "2026-05-19", "to": "2026-05-04"}, "bad_range"),
    ({"from": "2025-01-01", "to": "2026-05-19"}, "range_too_long"),
    ({"minutes": 4}, "bad_minutes"),
    ({"minutes": 121}, "bad_minutes"),
    ({"k": 3}, "bad_k"),
    ({"k": 17}, "bad_k"),
])
def test_limits_are_refused_before_any_file_is_read(client, auth, monkeypatch, patch, code):
    def boom(*a, **k):
        raise AssertionError("상한을 넘었는데 분봉을 읽었다")
    monkeypatch.setattr(minute_feed, "build_days", boom)
    r = client.post(URL, json={**BODY, **patch}, headers=auth)
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == code and r.json()["detail"]["reason"]


@pytest.mark.parametrize("dates, size, code", [
    ([f"2026-05-{d:02d}" for d in range(1, 31)] * 3, 0, "too_many_ticker_days"),    # 30종목 × 90일 = 2,700 > 2,000
    (["2026-05-04"], 300 * 1024 * 1024, "too_much_data"),
])
def test_the_reading_limits_match_the_run_door(client, auth, monkeypatch, dates, size, code):
    monkeypatch.setattr(minute_feed, "plan", lambda start, end: minute_feed.Plan(dates, size))
    monkeypatch.setattr(minute_feed, "build_days", lambda *a, **k: (_ for _ in ()).throw(AssertionError("읽었다")))
    r = client.post(URL, json={**BODY, "tickers": [f"{i:06d}" for i in range(30)]}, headers=auth)
    assert r.status_code == 400 and r.json()["detail"]["code"] == code


def test_a_period_without_files_is_said_not_loaded(client, auth):
    r = client.post(URL, json=BODY, headers=auth)
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "not_loaded" and r.json()["detail"]["reason"] == "이 기간에 적재된 분봉이 없습니다."
    assert table_rows() == 0


def test_too_few_usable_samples_name_why_each_was_left_out(client, auth):
    for day in DAYS:                                                 # 봉 넷짜리 하루 — 5분 창이 모자란다
        write_day(day, [(t, PATHS[0][:4], "kis") for t in TICKERS])
    r = client.post(URL, json=BODY, headers=auth)
    assert r.status_code == 400
    d = r.json()["detail"]
    assert d["code"] == "too_few_samples" and (d["samples"], d["needed"], d["k"]) == (0, 20, 4)
    assert d["excluded"]["by_reason"] == {"short_window": 24} and d["excluded"]["total"] == 24
    assert d["excluded"]["rows"][0]["message"] == dt.EXCLUDE_REASONS["short_window"]
    assert d["excluded"]["messages"] == {"short_window": dt.EXCLUDE_REASONS["short_window"]}
    assert table_rows() == 0


# ── mock 게이트 ────────────────────────────────────────────────────────────────────────
def test_production_never_trains_on_synthetic_bars(client, auth, monkeypatch):
    plant(source="synthetic")
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    r = client.post(URL, json=BODY, headers=auth)
    assert r.status_code == 400
    d = r.json()["detail"]
    assert d["code"] == "too_few_samples" and d["excluded"]["by_reason"] == {"synthetic_rows_blocked": 24}
    # 같은 화면의 분봉 백테스트가 '건너뛴 날'에 쓰는 문장과 같다(아래 일관성 시험)
    assert d["excluded"]["messages"]["synthetic_rows_blocked"] == SKIP_REASONS["synthetic_rows_blocked"]
    assert table_rows() == 0


def test_exactly_five_samples_per_type_is_enough_and_one_fewer_is_not(client, auth):
    """경계 — 유형 넷이면 쓸 수 있는 표본 20개에서 학습하고 19개에서는 거절한다(문이 엔진보다 먼저 보지만 같은 선이다)."""
    plant(days=DAYS[:10])                                             # 10일 × 2종목 = 20
    body = {**BODY, "to": DAYS[9]}
    r = client.post(URL, json=body, headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["model"]["samples"] == 20
    write_day(DAYS[9], [(TICKERS[0], PATHS[2], "kis")])               # 마지막 날 한 종목만 → 19
    r = client.post(URL, json=body, headers=auth)
    assert r.status_code == 400
    d = r.json()["detail"]
    assert (d["code"], d["samples"], d["needed"], d["k"]) == ("too_few_samples", 19, 20, 4)


def test_every_member_names_its_first_bar_as_hour_and_minute(client, auth):
    """표본마다 첫 봉 시각은 'HHMM'(초 없이) — 첫 봉 시각 요약과 같은 단위다."""
    plant()
    m = client.post(URL, json=BODY, headers=auth).json()["model"]
    assert {x["start"] for x in m["members"]} == {"0900"} and len(m["members"]) == 24
    assert m["starts"] == [{"start": "0900", "samples": 24}]


def test_the_excluded_rows_are_capped_but_every_reason_keeps_its_count_and_sentence(client, auth, monkeypatch):
    """행 목록은 상한(실행 문의 건너뛴 날과 같은 값)까지만 · 사유별 수와 문장은 잘리지 않는다."""
    for day in DAYS:
        write_day(day, [(t, PATHS[0][:4], "kis") for t in TICKERS])   # 봉 넷 — 5분 구간이 모자란다
    monkeypatch.setattr(routes.base, "SKIPPED_LIMIT", 3)
    r = client.post(URL, json=BODY, headers=auth)
    assert r.status_code == 400
    ex = r.json()["detail"]["excluded"]
    assert ex["total"] == 24 and ex["by_reason"] == {"short_window": 24} and len(ex["rows"]) == 3
    assert ex["messages"] == {"short_window": dt.EXCLUDE_REASONS["short_window"]}


def test_my_list_honours_the_limit(client, auth):
    """`limit` 은 최신 순 목록의 앞에서 자른다(같은 초에 만든 두 모형의 순서에 기대지 않는다 — 전체 목록의 앞과 같다)."""
    plant()
    for to in (DAYS[-1], DAYS[9]):                                      # 24표본 · 20표본 — 열쇠가 다른 두 모형
        assert client.post(URL, json={**BODY, "to": to}, headers=auth).status_code == 200
    full = client.get(URL, headers=auth).json()["models"]
    one = client.get(URL, params={"limit": 1}, headers=auth).json()["models"]
    assert len(full) == 2 and one == full[:1]
    assert client.get(URL, params={"limit": 0}, headers=auth).status_code == 422
    assert client.get(URL, params={"limit": 201}, headers=auth).status_code == 422


@pytest.mark.parametrize("bad", ["not-a-key", "A" * 64, "a" * 63, "g" * 64])
def test_a_key_that_cannot_exist_reads_missing_without_asking_the_store(client, auth, monkeypatch, bad):
    """열쇠는 sha256 의 소문자 16진 64자다 — 그 모양이 아니면 저장소에 묻지 않고 없음(404)이다. 저장소가 고장이어도 그렇다."""
    asked: list[str] = []
    monkeypatch.setattr(routes.store, "model_of", lambda user, key: asked.append(key))   # 물으면 None(= 고장)
    r = client.get(f"{URL}/{bad}", headers=auth)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "not_found"
    assert asked == []
    good = client.get(f"{URL}/{'a' * 64}", headers=auth)                # 짝: 모양이 맞으면 묻는다 → 고장은 503
    assert good.status_code == 503 and asked == ["a" * 64]


def test_exclusion_sentences_are_the_ones_the_run_route_shows_for_the_same_reason():
    """같은 화면(백테스트 › 분봉 규칙)에서 같은 사유는 같은 문장이다 — 실행 문의 '건너뛴 날'은 시뮬레이터 사유를 먼저,
    없으면 적재 사유를 쓴다(`intraday_routes` 의 skipped). 하루 유형만의 사유(구간 · 가격)는 엔진의 문장이다."""
    upstream = set(SKIP_REASONS) | set(mb.DAY_REASONS)
    assert upstream and not (upstream & set(dt.EXCLUDE_REASONS))          # 이름이 겹치면 어느 문장인지 모호해진다
    for reason in sorted(upstream):
        assert routes._message(reason) == (SKIP_REASONS.get(reason) or mb.DAY_REASONS.get(reason)), reason
    both = set(SKIP_REASONS) & set(mb.DAY_REASONS)
    assert both, "두 사전이 함께 갖는 사유가 있어야 순서가 시험된다(공허한 분기 방지)"
    assert any(SKIP_REASONS[r] != mb.DAY_REASONS[r] for r in both)        # 문장이 실제로 다른 사유가 있다 — 순서가 관측된다
    for reason, sentence in dt.EXCLUDE_REASONS.items():
        assert routes._message(reason) == sentence
    assert routes._message("no_such_reason") is None                         # 모르는 사유를 지어내지 않는다


def test_the_mock_gate_trains_on_synthetic_bars_and_labels_them(client, auth):
    plant(source="synthetic")
    m = client.post(URL, json=BODY, headers=auth).json()["model"]
    assert m["grade"] == "E0" and m["synthetic"] is True
    assert "합성" in m["grade_reason"]


def _synthetic_days(*a, **k) -> list[Day]:
    """로더가 합성 행을 걸러 주지 못했다고 치는 봉 — 문이 한 번 더 막는지 본다."""
    out = []
    for n, day in enumerate(DAYS):
        sessions = {}
        for j, ticker in enumerate(TICKERS):
            path = np.asarray(PATHS[(2 * n + j) % 4])
            close = 10_000.0 + path
            opens = np.concatenate([[10_000.0], close[:-1]])
            sessions[ticker] = Session(ticker, day, np.asarray([f"09{i:02d}00" for i in range(5)]), opens,
                                       np.maximum(opens, close), np.minimum(opens, close), close, np.full(5, 1_000.0),
                                       "synthetic")
        out.append(Day(day, sessions))
    return out


def test_the_door_checks_again_when_synthetic_sessions_slip_through(client, auth, monkeypatch):
    plant()                                                          # 적재된 날이 있어야 읽기까지 간다
    monkeypatch.setattr(minute_feed, "build_days", _synthetic_days)
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    r = client.post(URL, json=BODY, headers=auth)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "synthetic_in_production"
    assert table_rows() == 0
    monkeypatch.setenv("KIS_USE_MOCK", "1")                          # 짝: mock 게이트에서는 같은 봉으로 학습한다(합성 표지와 함께)
    ok = client.post(URL, json=BODY, headers=auth)
    assert ok.status_code == 200 and ok.json()["model"]["grade"] == "E0"


def test_production_hides_synthetic_models_and_says_how_many(client, auth, monkeypatch):
    plant(source="synthetic")
    key = client.post(URL, json=BODY, headers=auth).json()["model"]["key"]
    assert [x["key"] for x in client.get(URL, headers=auth).json()["models"]] == [key]     # mock: 보인다
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    listed = client.get(URL, headers=auth).json()
    assert listed["models"] == [] and listed["hidden_synthetic"] == 1
    assert listed["hidden_reason"] and "합성" in listed["hidden_reason"]
    one = client.get(f"{URL}/{key}", headers=auth)
    assert one.status_code == 404 and one.json()["detail"]["code"] == "not_found"


# ── 남의 것 · 저장 실패 ─────────────────────────────────────────────────────────────────────
def test_someone_elses_model_reads_like_a_missing_one(client, auth):
    plant()
    key = client.post(URL, json=BODY, headers=auth).json()["model"]["key"]
    bob = login(client, "bob")
    theirs = client.get(f"{URL}/{key}", headers=bob)
    missing = client.get(f"{URL}/{'f' * 64}", headers=bob)
    assert theirs.status_code == missing.status_code == 404
    assert theirs.json() == missing.json()
    assert client.get(URL, headers=bob).json()["models"] == []
    assert client.get(f"{URL}/not-a-key", headers=auth).status_code == 404


def test_a_broken_store_still_answers_but_says_the_model_was_not_kept(client, auth, monkeypatch):
    plant()
    monkeypatch.setattr(store, "model_of", lambda *a, **k: None)
    monkeypatch.setattr(store, "save", lambda *a, **k: None)
    monkeypatch.setattr(store, "models_of", lambda *a, **k: None)
    js = client.post(URL, json=BODY, headers=auth).json()
    assert js["stored"] is False and js["created"] is True
    assert js["store_reason"] == store.REASONS["store_unavailable"]
    assert len(js["model"]["types"]) == 4 and js["model"]["created_at"] is None
    listed = client.get(URL, headers=auth).json()
    assert listed["available"] is False and listed["reason"] == store.REASONS["store_unavailable"] and listed["models"] == []
    one = client.get(f"{URL}/{js['model']['key']}", headers=auth)
    assert one.status_code == 503 and one.json()["detail"]["code"] == "store_unavailable"


# ── 경계 ─────────────────────────────────────────────────────────────────────────────
def test_training_never_builds_a_broker_client(client, auth, monkeypatch):
    plant()
    import src.execution.kis_client as kc

    def boom(*a, **k):
        raise AssertionError("하루 유형 학습이 증권사 클라이언트를 만들었다")
    monkeypatch.setattr(kc, "get_kis_client", boom)
    assert client.post(URL, json=BODY, headers=auth).status_code == 200


def test_the_new_modules_never_import_the_order_path():
    banned = ("trading_engine", "order_executor", "kis_client", "execution")
    for path in (ROOT / "src/api/intraday_day_type_routes.py", ROOT / "src/data/intraday_day_types.py",
                 ROOT / "src/engine/intraday/day_types.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)] + \
                [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        assert names and not [n for n in names if any(b in n.lower() for b in banned)], path.name


def test_the_three_doors_are_registered_and_locked(client):
    from src.api.protected_routes import PROTECTED, REQUIRE_LOGIN
    walked = {(m, r.path) for r in flat_routes(client.app) for m in (getattr(r, "methods", None) or [])}
    for door in (("POST", URL), ("GET", URL), ("GET", f"{URL}/{{key}}")):
        assert door in walked, door
        assert PROTECTED[door][0] == REQUIRE_LOGIN, door
    assert routes.router.prefix == "/api/v1/intraday"
