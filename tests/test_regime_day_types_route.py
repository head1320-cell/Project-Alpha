"""하루 유형 비율 × 국면의 문 — `GET /api/v1/intraday/trials/{trial_key}/regime-day-types` (구현 계획 §7.3 · K2b).

표의 셈은 `test_regime_day_types.py`(순수 함수) · 유형 배정은 `test_intraday_day_types*.py` · 국면은 `test_market_regime*.py` 가 건다.
여기서는 문이 지키는 약속: 로그인 · ★남의 시행 · 남의 모형은 없는 것과 같은 답★ · ★읽기만 — 모든 표의 줄 수와 실행 횟수 불변★ ·
답 = 같은 봉 · 같은 배정 · 같은 국면을 엔진에 넣은 값(손 계산 하나 · 실제 길 하나) · 시행 · 국면 · 모형 · 표본의 등급을 각자 ·
운영에서 합성 시행 · 합성 모형 · 합성 표본을 세지 않는다 · 저장소 장애 ≠ 없음 · 모형 기록이 깨졌으면 지어내지 않는다 ·
뺀 사유의 문장은 하루 유형 학습 문의 문장과 같다 · 증권사 클라이언트 · 주문 경로를 들이지 않는다.
"""
from __future__ import annotations

import ast
import os
import tempfile
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

import src.api.intraday_day_type_routes as t1routes
import src.api.intraday_regime_split_routes as routes
import src.data.minute_bars as mb
import src.database as dbmod
from src.data import intraday_day_types as store
from src.data import intraday_trials as trials
from src.data import minute_feed
from src.data.market_rules import session_rules
from src.domain.auth_identity import ROLE_ANALYST
from src.engine import regime_day_types as rdt
from src.engine import regime_split as rs
from src.engine.intraday import GRADE_REASONS, SKIP_REASONS, Day, Session
from src.engine.intraday import day_types as dt
from tests.route_walk import flat_routes

URL = "/api/v1/intraday/trials/{key}/regime-day-types"
DOOR = "/api/v1/intraday/trials/{trial_key}/regime-day-types"
TRAIN = "/api/v1/intraday/day-types"
REGIME = "/api/v1/intraday/market-regime"
_SECRET = "intraday-regime-day-types-route-test-secret-0123456789"
ROOT = Path(__file__).resolve().parents[1]
COLS = ["ticker", "time", "open", "high", "low", "close", "volume", "source"]
#: 유형 넷의 장 시작 5분 경로(bp) — 끝값이 낮은 것부터 번호가 붙어 유형 1 = PATHS[1] · 2 = PATHS[2] · 3 = PATHS[3] · 4 = PATHS[0].
PATHS = ([10.0, 20.0, 30.0, 40.0, 50.0], [-10.0, -20.0, -30.0, -40.0, -50.0],
         [-10.0, -20.0, -30.0, -20.0, -10.0], [10.0, 20.0, 30.0, 20.0, 10.0])
#: 6분째 값 — 6분 모형 시험용(6분의 끝값 순서도 PATHS[1] · [2] · [3] · [0] 이라 유형 번호가 같다).
SIXTH = (60.0, -60.0, -5.0, 5.0)
A, B = "005930", "000660"
TRAIN_DAYS = ["2026-05-04", "2026-05-05", "2026-05-06", "2026-05-07", "2026-05-08", "2026-05-11",
              "2026-05-12", "2026-05-13", "2026-05-14", "2026-05-15", "2026-05-18", "2026-05-19"]
NEW_DAYS = ["2026-05-20", "2026-05-21", "2026-05-22"]
TRIAL_DAYS = TRAIN_DAYS[-2:] + NEW_DAYS                     # 학습 날 이틀(05-18 · 05-19) + 새 날 사흘
TRAIN_BODY = {"tickers": [A, B], "from": TRAIN_DAYS[0], "to": TRAIN_DAYS[-1], "minutes": 5, "k": 4}
NOT_FULL = "적합 창이 덜 찼습니다(필요 750 · 있음 700)."
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


def login(client, who: str = "alice") -> dict[str, str]:
    tok = client.post("/api/v1/auth/login", json={"username": who, "password": f"{who}-pw"}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture()
def auth(client) -> dict[str, str]:
    return login(client)


# ── 봉 · 모형 · 시행 · 국면을 심는 도우미 ────────────────────────────────────────────────────────
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


def path(i: int, six: bool) -> list[float]:
    return [*PATHS[i], SIXTH[i]] if six else list(PATHS[i])


def plant_training(source: str = "kis", days: list[str] = TRAIN_DAYS, six: bool = False) -> None:
    """종목 둘 × 날마다 — n번째 날의 A 는 PATHS[2n % 4] · B 는 PATHS[(2n + 1) % 4](05-18: 유형 4 · 1 · 05-19: 유형 2 · 3)."""
    for n, day in enumerate(days):
        write_day(day, [(A, path((2 * n) % 4, six), source), (B, path((2 * n + 1) % 4, six), source)])


def plant_new(source: str = "kis", six: bool = False) -> None:
    """새 날 사흘 — 05-20: A 유형 4 · B 유형 1 / 05-21: A 유형 2 · B 봉 셋(창이 덜 참) / 05-22: A · B 유형 3."""
    write_day(NEW_DAYS[0], [(A, path(0, six), source), (B, path(1, six), source)])
    write_day(NEW_DAYS[1], [(A, path(2, six), source), (B, PATHS[0][:3], source)])
    write_day(NEW_DAYS[2], [(A, path(3, six), source), (B, path(3, six), source)])


def train(client, headers, body: dict = TRAIN_BODY) -> str:
    r = client.post(TRAIN, json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["model"]["key"]


def plant_trial(grade: str = "E3", start: str = TRIAL_DAYS[0], end: str = TRIAL_DAYS[-1], user: str = "alice") -> str:
    made = trials.record(user, grade=grade, setting={"rule": {"kind": "planted", "params": {"grade": grade}}},
                         tickers=[A, B], start=start, end=end, daily={"basis": "net", "dates": [], "values": []})
    return made["trial_key"]


def regime_row(day: str, probs: list[float]) -> dict:
    top = max(range(len(probs)), key=lambda i: probs[i])
    return {"date": day, "probs": probs, "top": top + 1, "top_prob": probs[top], "reason": None}


#: 심은 국면(국면 2개) — 05-18 · 05-20 은 1 · 05-19 는 2 · 05-21 은 확률이 없고(사유) · 05-22 는 지수 자료에 없다.
PLANTED_DAYS = [regime_row("2026-05-18", [0.8, 0.2]), regime_row("2026-05-19", [0.3, 0.7]),
                regime_row("2026-05-20", [0.6, 0.4]),
                {"date": "2026-05-21", "probs": None, "top": None, "top_prob": None, "reason": NOT_FULL}]


def plant_regime(monkeypatch, days: list[dict] = PLANTED_DAYS) -> None:
    monkeypatch.setattr(routes, "regime_answer", lambda index, k, f, t: {
        "grade": "E0", "grade_reason": None, "source": "mock", "coverage": {"ok": True, "reason": None}, "empty": None,
        "days": days})


def frame(dates: list[str], closes, source: str) -> pd.DataFrame:
    df = pd.DataFrame({"open": closes, "high": closes, "low": closes, "close": closes, "volume": 0.0}, index=pd.to_datetime(dates))
    df.attrs.update(source=source, coverage_ok=True, coverage_reason=None)
    return df


def walk_frame(source: str) -> pd.DataFrame:
    dates = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2021-01-01", "2026-06-30")]
    rng = np.random.default_rng(3)
    return frame(dates, 2500.0 * np.exp(np.cumsum(rng.normal(0.0, 0.01, len(dates)))), source)


def fake_index(monkeypatch, df: pd.DataFrame) -> None:
    import src.api.intraday_market_regime_routes as k1
    monkeypatch.setattr(k1, "load_index_daily", lambda code, start, end: df)


def ready(client, headers) -> tuple[str, str]:
    """학습한 모형 · 새 날의 봉 · 시행 하나 → (시행 열쇠, 모형 열쇠)."""
    plant_training()
    model = train(client, headers)
    plant_new()
    return plant_trial(), model


def ask(client, headers, key: str, model: str, **q) -> dict:
    r = client.get(URL.format(key=key), params={**Q, "model": model, **q}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def cells(group: dict) -> list[tuple]:
    return [(t["type"], t["n"], t["in_sample"], t["share"]) for t in group["types"]]


def row_counts() -> dict[str, int]:
    eng = dbmod.get_engine()
    out = {}
    with eng.connect() as c:
        for t in inspect(eng).get_table_names():
            out[t] = int(c.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar())
    return out


# ── 손 계산 · 실제 길 ────────────────────────────────────────────────────────────────────────
def test_by_hand_types_by_regime_with_training_days_unknown_days_and_a_short_window(client, auth, monkeypatch):
    """학습 날 이틀 + 새 날 사흘 × 종목 둘 = 표본 열(짧은 창 하나는 뺌) · 심은 국면 다섯 날.

    국면 1(05-18 · 05-20): 유형 4 · 1 · 4 · 1 → 표본 4 · 분류 4 · 표본 안 2(05-18) · 비율 0.5 · 0 · 0 · 0.5
    국면 2(05-19): 유형 2 · 3 → 표본 2 · 분류 2 · 표본 안 2 · 비율 0 · 0.5 · 0.5 · 0
    미상(05-21 적합 창 사유 · 05-22 지수에 없는 날): 유형 2 · 뺌 · 3 · 3 → 표본 4 · 분류 3 · 비율 0 · 1/3 · 2/3 · 0
    합계: 표본 10 · 분류 9 · 표본 안 4 · 유형별 2 · 2 · 3 · 2 → 비율 2/9 · 2/9 · 3/9 · 2/9
    """
    key, model = ready(client, auth)
    plant_regime(monkeypatch)
    js = ask(client, auth, key, model)
    assert js["empty"] is None
    assert (js["trial_key"], js["index"], js["k"], js["from"], js["to"]) == (key, "KOSPI", 2, TRIAL_DAYS[0], TRIAL_DAYS[-1])
    t = js["table"]
    assert (t["k"], t["types_k"]) == (2, 4)
    s1, s2 = t["states"]
    assert (s1["state"], s1["samples"], s1["classified"], s1["in_sample"]) == (1, 4, 4, 2)
    assert cells(s1) == [(1, 2, 1, 0.5), (2, 0, 0, 0.0), (3, 0, 0, 0.0), (4, 2, 1, 0.5)]
    assert (s2["state"], s2["samples"], s2["classified"], s2["in_sample"]) == (2, 2, 2, 2)
    assert cells(s2) == [(1, 0, 0, 0.0), (2, 1, 1, 0.5), (3, 1, 1, 0.5), (4, 0, 0, 0.0)]
    assert s1["excluded"] == s2["excluded"] == {}
    u = t["unknown"]
    assert (u["samples"], u["classified"], u["in_sample"]) == (4, 3, 0)
    assert cells(u) == [(1, 0, 0, 0.0), (2, 1, 0, pytest.approx(1 / 3)), (3, 2, 0, pytest.approx(2 / 3)), (4, 0, 0, 0.0)]
    assert u["excluded"] == {"short_window": 1}
    assert u["reasons"] == [{"reason": NOT_FULL, "days": 1, "samples": 2},
                            {"reason": rs.REASONS["no_index_day"], "days": 1, "samples": 2}]
    tot = t["total"]
    assert (tot["samples"], tot["classified"], tot["in_sample"]) == (10, 9, 4)
    assert cells(tot) == [(1, 2, 1, pytest.approx(2 / 9)), (2, 2, 1, pytest.approx(2 / 9)),
                          (3, 3, 1, pytest.approx(3 / 9)), (4, 2, 1, pytest.approx(2 / 9))]
    assert tot["excluded"] == {"short_window": 1}
    assert js["excluded_messages"] == {"short_window": dt.EXCLUDE_REASONS["short_window"]}
    m = js["model"]
    assert (m["key"], m["minutes"], m["k"], m["first_day"], m["last_day"]) == (model, 5, 4, TRAIN_DAYS[0], TRAIN_DAYS[-1])
    assert m["tickers"] == [B, A] and m["same_tickers"] is True and m["overlap_days"] == 2
    assert (m["grade"], m["synthetic"]) == ("E3", False)
    assert m["facts"] == [f"하루 유형 모형 {model[:8]}의 학습 기간은 {TRAIN_DAYS[0]}~{TRAIN_DAYS[-1]}이며 종목 2개 · 장 시작 5분 · "
                          "유형 4개로 학습했습니다.",
                          routes.SAME_TICKERS,
                          "모형의 학습 날 가운데 2일이 이 시행의 기간 안에 있습니다. 그날의 표본은 표본 안 분류로 따로 셉니다."]
    assert js["notes"] == list(routes.DAY_TYPE_NOTES) and len(js["notes"]) == 6
    assert (js["samples_grade"], js["samples_grade_reason"], js["sources"]) == ("E3", GRADE_REASONS["E3"], {"kis": 9})


def test_the_answer_is_the_engine_on_the_same_bars_the_same_assignment_and_the_regime_days(client, auth):
    """실제 길(mock 의 합성 지수 · GMM 국면) — 답의 표 = 같은 준비로 읽은 봉 · 모형 중심의 배정 · 국면 문의 날들을 엔진에 넣은 값."""
    key, model = ready(client, auth)
    js = ask(client, auth, key, model, k=3)
    regime = client.get(REGIME, params={"index": "KOSPI", "k": 3, "from": TRIAL_DAYS[0], "to": TRIAL_DAYS[-1]},
                        headers=auth).json()
    row = store.model_of("alice", model)
    centres = np.asarray([t["path"] for t in row["body"]["types"]], dtype=np.float64)
    days = minute_feed.build_days([B, A], date.fromisoformat(TRIAL_DAYS[0]), date.fromisoformat(TRIAL_DAYS[-1]),
                                  rules=session_rules())
    got = dt.collect(days, 5)
    labels = (dt.assign(centres, got.X) + 1).tolist()
    samples = [(d, t, label, None) for (d, t), label in zip(got.samples, labels, strict=True)]
    samples += [(d, t, None, why) for d, t, why in got.excluded]
    want = rdt.day_types_by_regime(samples, regime["days"], 3, 4, row["body"]["days"])
    assert js["empty"] is None and js["table"] == want
    assert sum(s["samples"] for s in want["states"]) > 0                  # 전제 — 국면이 있는 날의 표본이 있다(공허하지 않다)
    assert (js["regime_grade"], js["source"], js["mock"]) == ("E0", "mock", True)


# ── 문 · 인자 · 주인 ─────────────────────────────────────────────────────────────────────────
def test_the_door_is_mounted_registered_and_needs_a_login(client):
    from src.api.protected_routes import PROTECTED, REQUIRE_LOGIN
    walked = {(m, r.path) for r in flat_routes(client.app) for m in (getattr(r, "methods", None) or [])}
    assert ("GET", DOOR) in walked and PROTECTED[("GET", DOOR)][0] == REQUIRE_LOGIN
    assert client.get(URL.format(key="x" * 64), params={**Q, "model": "a" * 64}).status_code == 401


@pytest.mark.parametrize("q", [{"index": "KOSPI", "k": 2}, {"k": 2, "model": "a" * 64}, {"index": "KOSPI", "model": "a" * 64},
                               {"index": "NASDAQ", "k": 2, "model": "a" * 64}, {"index": "KOSPI", "k": 5, "model": "a" * 64},
                               {"index": "KOSPI", "k": 1, "model": "a" * 64}])
def test_index_k_and_model_are_required_and_bounded(client, auth, q):
    assert client.get(URL.format(key="x" * 64), params=q, headers=auth).status_code == 422


@pytest.mark.parametrize("bad", ["not-a-key", "A" * 64, "a" * 63, "g" * 64])
def test_a_model_key_that_cannot_exist_reads_missing_without_asking_the_store(client, auth, monkeypatch, bad):
    key = plant_trial()
    asked = []
    monkeypatch.setattr(store, "model_of", lambda user, k: asked.append(k))
    r = client.get(URL.format(key=key), params={**Q, "model": bad}, headers=auth)
    assert r.status_code == 404 and r.json()["detail"] == {"code": "model_not_found", "reason": routes.REASONS["model_not_found"]}
    assert asked == []


def test_someone_elses_trial_is_answered_like_a_missing_one(client, auth):
    key, model = ready(client, auth)
    theirs = client.get(URL.format(key=key), params={**Q, "model": model}, headers=login(client, "bob"))
    missing = client.get(URL.format(key="f" * 64), params={**Q, "model": model}, headers=auth)
    assert theirs.status_code == missing.status_code == 404
    assert theirs.json() == missing.json() and theirs.json()["detail"]["code"] == "not_found"


def test_someone_elses_model_is_answered_like_a_missing_one(client, auth):
    """밥이 학습한 모형으로 앨리스의 시행을 묻는다 — 없는 모형과 같은 답(있는지를 알려 주지 않는다) ↔ 짝: 앨리스의 모형이면 답한다."""
    key, mine = ready(client, auth)
    plant_training(days=TRAIN_DAYS[:10])                                   # 다른 표본 → 다른 열쇠
    theirs = train(client, login(client, "bob"), {**TRAIN_BODY, "to": TRAIN_DAYS[9]})
    assert theirs != mine
    a = client.get(URL.format(key=key), params={**Q, "model": theirs}, headers=auth)
    b = client.get(URL.format(key=key), params={**Q, "model": "b" * 64}, headers=auth)
    assert a.status_code == b.status_code == 404 and a.json() == b.json()
    assert a.json()["detail"]["code"] == "model_not_found"
    assert client.get(URL.format(key=key), params={**Q, "model": mine}, headers=auth).status_code == 200


def test_the_count_reads_only_and_records_no_trial_and_no_model(client, auth):
    key, model = ready(client, auth)
    before, runs = row_counts(), trials.trial_of("alice", key)["runs"]
    for k in (2, 3):
        ask(client, auth, key, model, k=k)
    assert row_counts() == before and trials.trial_of("alice", key)["runs"] == runs


# ── 등급 ─────────────────────────────────────────────────────────────────────────────────
def test_the_four_grades_are_each_their_own(client, auth, monkeypatch):
    """시행 · 국면 · 모형 · 지금 읽은 표본의 등급은 각자의 출처다 — 하나로 다른 것을 채우지 않는다.
    ① 시행 등급이 E0 · E3 가 아니면 미상(`None`) ② 실제 표시로 학습한 모형 + 합성 표시의 새 봉 → 모형 E3 · 표본 E0."""
    plant_training()
    model = train(client, auth)
    plant_new(source="synthetic")
    plant_regime(monkeypatch)
    key = plant_trial(grade="unknown")
    js = ask(client, auth, key, model)
    assert js["empty"] is None
    assert (js["trial_grade"], js["model"]["grade"], js["samples_grade"], js["regime_grade"]) == (None, "E3", "E0", "E0")
    assert js["samples_grade_reason"] == GRADE_REASONS["E0"] and js["sources"] == {"kis": 4, "synthetic": 5}
    key = plant_trial(grade="E3")
    js = ask(client, auth, key, model)
    assert (js["trial_grade"], js["model"]["grade"], js["samples_grade"]) == ("E3", "E3", "E0")


def test_a_synthetic_model_says_so_in_its_facts(client, auth, monkeypatch):
    plant_training(source="synthetic")
    model = train(client, auth)
    plant_new(source="synthetic")
    plant_regime(monkeypatch)
    js = ask(client, auth, plant_trial(grade="E0"), model)
    assert (js["model"]["grade"], js["model"]["synthetic"]) == ("E0", True)
    assert js["model"]["facts"][-1] == routes.SYNTHETIC_MODEL


# ── 운영 게이트 ────────────────────────────────────────────────────────────────────────────
def test_in_production_a_synthetic_trial_is_not_counted(client, auth, monkeypatch):
    plant_training()
    model = train(client, auth)
    plant_new()
    key = plant_trial(grade="E0")
    fake_index(monkeypatch, walk_frame("db"))
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    js = ask(client, auth, key, model)
    assert js["table"] is None and js["empty"] == {"reason": "synthetic_trial_in_production",
                                                   "message": routes.EMPTY["synthetic_trial_in_production"]}


def test_in_production_a_synthetic_model_is_missing_and_a_real_one_answers(client, auth, monkeypatch):
    plant_training(source="synthetic")
    synthetic = train(client, auth)
    plant_training(days=TRAIN_DAYS[:10])                                   # 실제 표시로 다시 — 다른 열쇠
    real = train(client, auth, {**TRAIN_BODY, "to": TRAIN_DAYS[9]})
    plant_new()
    key = plant_trial()
    fake_index(monkeypatch, walk_frame("db"))
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    r = client.get(URL.format(key=key), params={**Q, "model": synthetic}, headers=auth)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "model_not_found"
    js = ask(client, auth, key, real)                                     # 짝 — 실제 표시의 모형은 센다
    assert js["empty"] is None and (js["model"]["grade"], js["regime_grade"], js["mock"]) == ("E3", "E3", False)
    assert js["table"]["total"]["samples"] > 0


def _synthetic_days(tickers, start, end, rules=None) -> list[Day]:
    """로더가 합성 행을 걸러 주지 못했다고 치는 봉 — 문이 한 번 더 막는지 본다."""
    out = []
    for day in TRIAL_DAYS:
        sessions = {}
        for j, ticker in enumerate(sorted(tickers)):
            path = np.asarray(PATHS[j])
            close = 10_000.0 + path
            opens = np.concatenate([[10_000.0], close[:-1]])
            sessions[ticker] = Session(ticker, day, np.asarray([f"09{i:02d}00" for i in range(5)]), opens,
                                       np.maximum(opens, close), np.minimum(opens, close), close, np.full(5, 1_000.0),
                                       "synthetic")
        out.append(Day(day, sessions))
    return out


def test_the_door_checks_again_when_synthetic_sessions_slip_through(client, auth, monkeypatch):
    key, model = ready(client, auth)
    plant_regime(monkeypatch)
    monkeypatch.setattr(minute_feed, "build_days", _synthetic_days)
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    js = ask(client, auth, key, model)
    assert js["table"] is None and js["empty"] == {"reason": "synthetic_samples_in_production",
                                                   "message": routes.EMPTY["synthetic_samples_in_production"]}
    monkeypatch.setenv("KIS_USE_MOCK", "1")                                # 짝: mock 게이트에서는 같은 봉을 센다(합성 등급과 함께)
    js = ask(client, auth, key, model)
    assert js["empty"] is None and js["samples_grade"] == "E0" and js["table"]["total"]["samples"] == 10


def test_in_production_blocked_synthetic_rows_are_left_out_with_the_sentence_the_training_door_uses(client, auth, monkeypatch):
    """운영 로더가 합성 행을 막은 (날, 종목)은 뺀 표본이다 — 사유 문장은 하루 유형 학습 문 · 분봉 실행 문과 같다."""
    plant_training()
    model = train(client, auth)
    plant_new(source="synthetic")
    key = plant_trial()
    plant_regime(monkeypatch)
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    js = ask(client, auth, key, model)
    assert js["empty"] is None and js["table"]["total"]["excluded"] == {"synthetic_rows_blocked": 6}
    assert js["table"]["total"]["classified"] == 4                         # 학습 날 이틀의 실제 표본만
    assert js["excluded_messages"] == {"synthetic_rows_blocked": SKIP_REASONS["synthetic_rows_blocked"]}
    assert js["excluded_messages"]["synthetic_rows_blocked"] == t1routes._message("synthetic_rows_blocked")


def test_exclusion_sentences_are_the_training_doors_for_every_reason():
    for code in sorted(set(dt.EXCLUDE_REASONS) | set(SKIP_REASONS) | set(mb.DAY_REASONS)):
        assert routes.excluded_message(code) == t1routes._message(code), code
    assert routes.excluded_message("no_such_reason") is None                # 모르는 사유를 지어내지 않는다


# ── 장애 · 결함 ───────────────────────────────────────────────────────────────────────────
def test_when_the_trial_store_breaks_the_answer_is_unknown_not_missing(client, auth, monkeypatch):
    key, model = ready(client, auth)

    def broken():
        raise RuntimeError("db down")
    monkeypatch.setattr(trials, "_engine", broken)
    r = client.get(URL.format(key=key), params={**Q, "model": model}, headers=auth)
    assert r.status_code == 503 and r.json()["detail"] == {"code": "store_unavailable", "reason": routes.REASONS["store_unavailable"]}


def test_when_the_model_store_breaks_the_answer_is_unknown_not_missing(client, auth, monkeypatch):
    key, model = ready(client, auth)

    def broken():
        raise RuntimeError("db down")
    monkeypatch.setattr(store, "_engine", broken)
    assert store.model_of("alice", model) is None
    r = client.get(URL.format(key=key), params={**Q, "model": model}, headers=auth)
    assert r.status_code == 503 and r.json()["detail"] == {"code": "model_store_unavailable",
                                                           "reason": routes.REASONS["model_store_unavailable"]}


def _drop_a_type(body: dict) -> None:
    body["types"] = body["types"][:-1]


def _short_path(body: dict) -> None:
    body["types"][0]["path"] = body["types"][0]["path"][:-1]


def _nan_path(body: dict) -> None:
    body["types"][1]["path"][2] = float("nan")


def _no_types(body: dict) -> None:
    del body["types"]


def _no_days(body: dict) -> None:
    body["days"] = []


@pytest.mark.parametrize("damage", [_drop_a_type, _short_path, _nan_path, _no_types, _no_days],
                         ids=["types_lt_k", "path_lt_minutes", "nan", "no_types", "no_days"])
def test_a_model_record_that_does_not_fit_its_own_head_is_not_used(client, auth, monkeypatch, damage):
    """중심의 수가 그 모형의 유형 수와 · 경로의 길이가 N 과 맞지 않거나 · 유한하지 않거나 · 학습 날이 없으면 세지 않는다(지어내지 않는다 · 500 도 아니다)."""
    key, model = ready(client, auth)
    plant_regime(monkeypatch)
    real = store.model_of

    def damaged(user, k):
        row = real(user, k)
        damage(row["body"])
        return row
    monkeypatch.setattr(store, "model_of", damaged)
    js = ask(client, auth, key, model)
    assert js["table"] is None and js["empty"] == {"reason": "model_unreadable", "message": routes.EMPTY["model_unreadable"]}
    assert js["model"]["key"] == model and js["model"]["overlap_days"] is None


def test_a_regime_number_outside_k_is_not_blamed_on_the_samples(client, auth, monkeypatch):
    key, model = ready(client, auth)
    plant_regime(monkeypatch, [regime_row(d, [0.05, 0.05, 0.9]) for d in TRIAL_DAYS])   # 국면 2개를 물었는데 번호 3
    js = ask(client, auth, key, model)
    assert js["table"] is None and js["empty"] == {"reason": "state_out_of_range", "message": routes.EMPTY["state_out_of_range"]}


def test_a_regime_store_failure_is_not_absence(client, auth, monkeypatch):
    key, model = ready(client, auth)
    df = walk_frame("db")
    df.attrs["db_error"] = True
    fake_index(monkeypatch, df)
    js = ask(client, auth, key, model)
    assert js["table"] is None and js["empty"]["reason"] == "store_error"


def test_a_period_without_minute_files_is_said_not_loaded(client, auth, monkeypatch):
    plant_training()
    model = train(client, auth)
    key = plant_trial(start="2026-06-01", end="2026-06-05")
    plant_regime(monkeypatch)
    js = ask(client, auth, key, model)
    assert js["table"] is None and js["empty"] == {"reason": "not_loaded", "message": routes.EMPTY["not_loaded"]}


def test_a_model_trained_before_the_trial_has_no_in_sample_count(client, auth, monkeypatch):
    """짝 — 학습이 시행 기간 전에 끝난 모형은 표본 안 분류가 0 이고 그렇게 적는다(학습 날과 겹친 모형만 따로 센다)."""
    plant_training()
    model = train(client, auth, {**TRAIN_BODY, "to": TRAIN_DAYS[9]})      # 05-15 까지 — 시행은 05-18 부터
    plant_new()
    key = plant_trial()
    plant_regime(monkeypatch)
    js = ask(client, auth, key, model)
    assert js["table"]["total"]["in_sample"] == 0 and js["table"]["total"]["classified"] == 9
    assert js["model"]["overlap_days"] == 0 and routes.NO_OVERLAP in js["model"]["facts"]


def test_counting_never_builds_a_broker_client(client, auth, monkeypatch):
    key, model = ready(client, auth)
    plant_regime(monkeypatch)
    import src.execution.kis_client as kc

    def boom(*a, **k):
        raise AssertionError("하루 유형 × 국면이 증권사 클라이언트를 만들었다")
    monkeypatch.setattr(kc, "get_kis_client", boom)
    assert ask(client, auth, key, model)["empty"] is None


def test_the_modules_never_import_the_order_path():
    banned = ("trading_engine", "order_executor", "kis_client", "execution")
    for path in (ROOT / "src/api/intraday_regime_split_routes.py", ROOT / "src/engine/regime_day_types.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)] + \
                [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        assert names and not [n for n in names if any(b in n.lower() for b in banned)], path.name


def test_a_model_counts_with_its_own_window_length(client, auth, monkeypatch):
    """모형의 분 수(N)로 창을 자른다 — 봉 여섯의 하루를 6분으로 학습한 모형은 6분으로 센다(유형 번호 · 표가 손 계산과 같다:
    6분의 끝값 순서도 PATHS[1] · [2] · [3] · [0]). 창 길이를 모형과 다르게(예: 기본값) 자르면 중심과 맞지 않는다."""
    plant_training(six=True)
    model = train(client, auth, {**TRAIN_BODY, "minutes": 6})
    plant_new(six=True)
    key = plant_trial()
    plant_regime(monkeypatch)
    js = ask(client, auth, key, model)
    assert js["empty"] is None and js["model"]["minutes"] == 6
    tot = js["table"]["total"]
    assert (tot["samples"], tot["classified"], tot["excluded"]) == (10, 9, {"short_window": 1})
    assert [t["n"] for t in tot["types"]] == [2, 2, 3, 2]


def test_a_broken_assignment_is_blamed_on_the_model_not_invented(client, auth, monkeypatch):
    """배정이 유형 수 밖의 번호를 내면(모형 중심의 결함) 세지 않고 모형의 사유로 적는다 — 표본의 탓으로 적지 않는다."""
    key, model = ready(client, auth)
    plant_regime(monkeypatch)
    monkeypatch.setattr(dt, "assign", lambda centres, X: np.full(len(X), 7, dtype=np.int64))
    js = ask(client, auth, key, model)
    assert js["table"] is None and js["empty"] == {"reason": "model_unreadable", "message": routes.EMPTY["model_unreadable"]}


def test_a_sample_defect_the_engine_refuses_is_said_without_blaming_the_model(client, auth, monkeypatch):
    """사유 없이 뺀 표본처럼 엔진이 거절하는 그 밖의 표본 결함 — '표본 기록을 읽을 수 없다'(모형 · 국면의 탓이 아니다)."""
    key, model = ready(client, auth)
    plant_regime(monkeypatch)
    real = dt.collect

    def blank_reasons(days, minutes):
        got = real(days, minutes)
        return dt.Collected(X=got.X, samples=got.samples, starts=got.starts,
                            excluded=[(d, t, "") for d, t, _ in got.excluded], grade=got.grade, sources=got.sources)
    monkeypatch.setattr(dt, "collect", blank_reasons)
    js = ask(client, auth, key, model)
    assert js["table"] is None and js["empty"] == {"reason": "bad_samples", "message": routes.EMPTY["bad_samples"]}


def test_a_trial_with_other_tickers_than_the_model_says_so(client, auth, monkeypatch):
    """짝 — 시행의 종목이 학습 종목과 다르면 그렇게 적는다(손 계산 시험은 같은 종목)."""
    plant_training()
    model = train(client, auth)
    plant_new()
    made = trials.record("alice", grade="E3", setting={"rule": {"kind": "planted", "params": {"one": True}}},
                         tickers=[A], start=TRIAL_DAYS[0], end=TRIAL_DAYS[-1], daily={"basis": "net", "dates": [], "values": []})
    plant_regime(monkeypatch)
    js = ask(client, auth, made["trial_key"], model)
    assert js["model"]["same_tickers"] is False and routes.OTHER_TICKERS in js["model"]["facts"]
    assert routes.SAME_TICKERS not in js["model"]["facts"]
    assert js["table"]["total"]["samples"] == 5                            # A 의 닷새만


def test_when_every_sample_is_left_out_the_shares_are_unknown_and_the_grade_says_no_bars(client, auth, monkeypatch):
    """미상 상태 — 운영 로더가 새 날의 합성 행을 모두 막아 쓸 표본이 없다: 표는 뺀 표본만 세고 비율은 `None`(0% 가 아니다) ·
    표본 등급은 '쓰인 분봉이 없습니다'(합성도 실제도 아니다 — 미상으로 지어내지 않는다)."""
    plant_training()
    model = train(client, auth)
    plant_new(source="synthetic")
    key = plant_trial(start=NEW_DAYS[0], end=NEW_DAYS[-1])
    plant_regime(monkeypatch)
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    js = ask(client, auth, key, model)
    tot = js["table"]["total"]
    assert (tot["samples"], tot["classified"], tot["excluded"]) == (6, 0, {"synthetic_rows_blocked": 6})
    assert [t["share"] for t in tot["types"]] == [None] * 4 and [t["n"] for t in tot["types"]] == [0] * 4
    assert (js["samples_grade"], js["samples_grade_reason"], js["sources"]) == (None, GRADE_REASONS["none"], {})
