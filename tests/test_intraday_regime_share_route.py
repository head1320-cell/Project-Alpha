"""하루 유형 비중을 더한 시장 국면의 문 둘 (구현 계획 2026-11-16 §7.6 · K5).

- `POST /api/v1/intraday/market-regime/day-type-counts` — 내 모형으로 바구니 종목의 날마다 하루 유형을 세어 남긴다(예산 안에서 · 이어 센다).
- `GET  /api/v1/intraday/market-regime/day-type-input` — 지수만의 국면(K1 문의 답 그대로)과 하루 유형 비중을 더한 국면을 나란히(읽기만).

비중의 셈은 `test_day_type_share.py` · 국면 엔진은 `test_market_regime.py` · 저장소는 `test_day_type_counts.py` 가 건다.
여기서는 문이 지키는 약속: 로그인 · ★남의 모형 = 없는 모형(같은 404)★ · 학습 날 겹침 거절(규칙 문과 같은 코드 · 같은 문장) ·
기간 규칙 = 시장 국면 문의 규칙 · 바구니 상한은 읽기 전에 · 예산 안에서 날짜 순으로 세고 이어 센다 · ★나눠 센 끝의 답 = 한 번에 센 답★ ·
낡은 서명(일파일 · 게이트)은 다시 센다 · 운영에서 합성 모형 · 합성 표본을 쓰지 않는다 · ★GET 은 읽기만 — 모든 표의 줄 수 불변★ ·
GET 의 지수만 답 = 시장 국면 문의 답 · 비중을 더한 답 = 같은 센 값을 엔진에 넣은 값 · 덜 센 날은 더한 답만 미상 ·
시행을 남기지 않는다 · 증권사 클라이언트 · 주문 경로를 들이지 않는다.

시험을 빠르게 하려고 적합 창(750 → 30)과 읽기 구간(1,250 → 90 달력일) · 난수 시드 수(10 → 3)를 줄인다 — 문은 줄인 값을 그대로 쓴다
(엔진 · 읽기 구간을 시장 국면 문과 같은 자리에서 읽는다는 것도 이것으로 건다).
"""
from __future__ import annotations

import ast
import dataclasses
import functools
import os
import tempfile
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

import src.api.intraday_context as ctx
import src.api.intraday_market_regime_routes as k1
import src.api.intraday_regime_share_routes as routes
import src.data.minute_bars as mb
import src.database as dbmod
from src.api.protected_routes import PROTECTED, REQUIRE_LOGIN
from src.data import day_type_counts as counts
from src.data import intraday_day_types as models
from src.data import minute_feed
from src.domain.auth_identity import ROLE_ANALYST
from src.engine import day_type_share as ds
from src.engine import market_regime as mr
from src.engine.intraday import day_types as dt
from tests.route_walk import flat_routes

COUNT = "/api/v1/intraday/market-regime/day-type-counts"
INPUT = "/api/v1/intraday/market-regime/day-type-input"
REGIME = "/api/v1/intraday/market-regime"
TRAIN = "/api/v1/intraday/day-types"
_SECRET = "intraday-regime-share-route-test-secret-0123456789"
ROOT = Path(__file__).resolve().parents[1]
COLS = ["ticker", "time", "open", "high", "low", "close", "volume", "source"]
A, B = "005930", "000660"
#: 유형 넷의 장 시작 5분 경로(bp) — 끝값이 낮은 것부터 번호: 유형 1 = PATHS[1] · 2 = PATHS[2] · 3 = PATHS[3] · 4 = PATHS[0].
PATHS = ([10.0, 20.0, 30.0, 40.0, 50.0], [-10.0, -20.0, -30.0, -40.0, -50.0],
         [-10.0, -20.0, -30.0, -20.0, -10.0], [10.0, 20.0, 30.0, 20.0, 10.0])
TYPE_OF = {1: 1, 2: 2, 3: 3, 0: 4}

FIT, SEEDS, HISTORY = 30, 3, 90
FROM, TO = "2026-04-01", "2026-04-30"
READ_START = (date.fromisoformat(FROM) - timedelta(days=HISTORY)).isoformat()            # 2026-01-01


def weekdays(a: str, b: str) -> list[str]:
    return [d.strftime("%Y-%m-%d") for d in pd.bdate_range(a, b)]


INDEX_DAYS = weekdays("2025-10-01", "2026-06-30")
#: 셀 날 = 읽기 구간의 지수 거래일 가운데 기간 안 마지막 거래일(04-30) 전의 날.
NEEDED = [d for d in INDEX_DAYS if READ_START <= d < TO]
TRAIN_DAYS = weekdays("2026-01-05", "2026-01-20")                                       # 열이틀 — 읽기 구간 안(표본 안 분류)
EARLY_TRAIN = weekdays("2025-11-03", "2025-11-18")                                      # 열이틀 — 읽기 구간 앞
TRAIN_BODY = {"tickers": [A, B], "from": TRAIN_DAYS[0], "to": TRAIN_DAYS[-1], "minutes": 5, "k": 4}
Q = {"index": "KOSPI", "k": 2, "from": FROM, "to": TO}


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
    monkeypatch.setattr(k1, "HISTORY_CALENDAR_DAYS", HISTORY)
    monkeypatch.setattr(mr, "regime_days", functools.partial(mr.regime_days, fit_days=FIT, seeds=SEEDS))
    plant_index(monkeypatch)

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


# ── 지수 · 봉 · 모형을 심는 도우미 ──────────────────────────────────────────────────────────────
def closes_for(days: list[str], seed: int = 7) -> np.ndarray:
    """영업일 걸음 — 25일마다 일 0.5% ↔ 2%(국면이 있는 합성 지수)."""
    vols = np.array([0.005 if (i // 25) % 2 == 0 else 0.02 for i in range(len(days))])
    rng = np.random.default_rng(seed)
    return 2500.0 * np.exp(np.cumsum(rng.normal(0.0, 1.0, len(days)) * vols))


CLOSES = closes_for(INDEX_DAYS)


def plant_index(monkeypatch, source: str = "mock", *, error: bool = False, empty: bool = False) -> list:
    calls: list = []

    def load(code, start, end):
        calls.append((code, start, end))
        keep = [i for i, d in enumerate(INDEX_DAYS) if start <= d <= end and not empty]
        df = pd.DataFrame({"open": CLOSES[keep], "high": CLOSES[keep], "low": CLOSES[keep], "close": CLOSES[keep],
                           "volume": 0.0}, index=pd.to_datetime([INDEX_DAYS[i] for i in keep]))
        df.attrs.update({"source": source, "coverage_ok": True, "coverage_reason": None})
        if error:
            df.attrs["db_error"] = True
        return df
    monkeypatch.setattr(k1, "load_index_daily", load)
    return calls


def write_day(day: str, rows: list[tuple[str, list[float], str]], *, clear: bool = True) -> None:
    """(종목, bp 경로, 출처) → 그날의 일파일. 첫 봉 시가 10,000 · 09:00 부터 1분마다."""
    recs = []
    for ticker, path, source in rows:
        prev = 10_000.0
        for i, p in enumerate(path):
            close = 10_000.0 + p
            recs.append((ticker, f"09{i:02d}00", prev, max(prev, close), min(prev, close), close, 1_000.0, source))
            prev = close
    mb._write_day_file(pd.DataFrame(recs, columns=COLS), day)
    if clear:
        mb.clear_cache()


def path_index(day: str, ticker: str) -> int:
    """그날 그 종목의 경로 번호 — 학습 날은 유형 넷이 고루(K2b 와 같은 꼴) · 그 밖은 15일 묶음마다 (A 1 · B 0) ↔ (A 2 · B 3)."""
    for days in (TRAIN_DAYS, EARLY_TRAIN):
        if day in days:
            n = days.index(day)
            return (2 * n) % 4 if ticker == A else (2 * n + 1) % 4
    block = (INDEX_DAYS.index(day) // 15) % 2
    return (1 if ticker == A else 0) if block == 0 else (2 if ticker == A else 3)


def plant_bars(days: list[str] = NEEDED, source: str = "kis") -> None:
    for day in days:
        write_day(day, [(A, PATHS[path_index(day, A)], source), (B, PATHS[path_index(day, B)], source)], clear=False)
    mb.clear_cache()


def train(client, headers, body: dict = TRAIN_BODY) -> str:
    r = client.post(TRAIN, json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["model"]["key"]


def ready(client, headers, *, source: str = "kis") -> str:
    """읽기 구간의 봉(학습 날 포함)을 심고 모형을 학습한다 → 모형 열쇠."""
    plant_bars(NEEDED, source)
    return train(client, headers)


def count_body(model: str, **over) -> dict:
    return {"model": model, "tickers": [A, B], "index": "KOSPI", "from": FROM, "to": TO, **over}


def count(client, headers, model: str, **over):
    return client.post(COUNT, json=count_body(model, **over), headers=headers)


def count_all(client, headers, model: str, **over) -> dict:
    for _ in range(len(NEEDED) + 2):
        r = count(client, headers, model, **over)
        assert r.status_code == 200, r.text
        if r.json()["done"]:
            return r.json()
    raise AssertionError("세기가 끝나지 않았다")


def ask(client, headers, model: str, types=(1,), tickers=(A, B), **over):
    params = {**Q, "model": model, "types": list(types), "tickers": list(tickers), **over}
    return client.get(INPUT, params=params, headers=headers)


def row_counts() -> dict[str, int]:
    eng = dbmod.get_engine()
    out = {}
    with eng.connect() as c:
        for t in inspect(eng).get_table_names():
            out[t] = int(c.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar())
    return out


def table_rows() -> dict[str, list[str]]:
    """모든 표의 모든 줄(정렬한 글) — 줄 수만이 아니라 내용까지 견준다(있던 줄을 바꿔 써도 걸리게)."""
    eng = dbmod.get_engine()
    out = {}
    with eng.connect() as c:
        for t in inspect(eng).get_table_names():
            out[t] = sorted(repr(tuple(r)) for r in c.execute(text(f'SELECT * FROM "{t}"')))
    return out


def expected_with_share(types=(1,), stale: frozenset[str] = frozenset()) -> dict:
    """손으로 지은 센 값 → 엔진 — 문이 같은 함수에 같은 값을 넣는지 본다(읽기 구간 · 셀 날 · 날마다의 셈 · 사유 문장)."""
    read = [d for d in INDEX_DAYS if READ_START <= d <= TO]
    closes = np.asarray([CLOSES[INDEX_DAYS.index(d)] for d in read])
    by_day = {}
    for d in NEEDED:
        if d in stale:
            continue
        by_day[d] = ds.basket_day([(TYPE_OF[path_index(d, A)], None), (TYPE_OF[path_index(d, B)], None)])
    values, codes, _ = ds.window_share(read, by_day, types)
    reasons = [ds.REASONS[c] if c else None for c in codes]
    return mr.regime_days(read, closes, k=Q["k"], start=FROM, end=TO, extra=values, extra_reasons=reasons)


# ── 문 · 등록부 ──────────────────────────────────────────────────────────────────────────
def test_both_doors_need_a_login(client):
    assert client.post(COUNT, json=count_body("a" * 64)).status_code == 401
    assert client.get(INPUT, params={**Q, "model": "a" * 64, "types": [1], "tickers": [A]}).status_code == 401


def test_both_doors_are_registered_as_login_routes(client):
    seen = {(m, r.path) for r in flat_routes(client.app) for m in getattr(r, "methods", set()) or set()}
    for method, path in (("POST", COUNT), ("GET", INPUT)):
        assert (method, path) in seen
        assert PROTECTED[(method, path)][0] == REQUIRE_LOGIN


@pytest.mark.parametrize("missing", ["model", "types", "tickers", "index", "k", "from", "to"])
def test_a_missing_input_argument_is_refused_not_filled(client, auth, missing):
    params = {**Q, "model": "a" * 64, "types": [1], "tickers": [A]}
    params.pop(missing)
    assert client.get(INPUT, params=params, headers=auth).status_code == 422


# ── 모형 ────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("bad", ["nothex", "A" * 64, "a" * 63, "../" + "a" * 61])
def test_a_key_that_cannot_exist_is_the_same_404_without_asking_the_store(client, auth, monkeypatch, bad):
    asked: list = []
    monkeypatch.setattr(models, "model_of", lambda user, key: asked.append(key))
    for r in (count(client, auth, bad), ask(client, auth, bad)):
        assert r.status_code == 404 and r.json()["detail"]["code"] == "day_type_model_missing"
        assert r.json()["detail"]["reason"] == ctx.REASONS["day_type_model_missing"]
    assert asked == []


def test_someone_elses_model_is_the_same_404_as_a_missing_one(client, auth):
    key = ready(client, auth)
    bob = login(client, "bob")
    answers = [count(client, bob, key), ask(client, bob, key), count(client, auth, "f" * 64), ask(client, auth, "f" * 64)]
    assert {r.status_code for r in answers} == {404}
    assert len({(r.json()["detail"]["code"], r.json()["detail"]["reason"]) for r in answers}) == 1
    assert count(client, auth, key).status_code == 200                       # 짝 — 주인에게는 열린다


def test_a_model_trained_into_the_period_is_refused_like_the_rule_door(client, auth):
    key = ready(client, auth)
    late = TRAIN_DAYS[-1]                                                     # 학습 마지막 날 = 판정 시작일
    q_from = {"from": late, "to": (date.fromisoformat(late) + timedelta(days=20)).isoformat()}
    for r in (count(client, auth, key, **q_from), ask(client, auth, key, **q_from)):
        assert r.status_code == 400 and r.json()["detail"]["code"] == "day_type_model_overlaps"
        assert r.json()["detail"]["reason"] == ctx.REASONS["day_type_model_overlaps"]
    next_day = (date.fromisoformat(late) + timedelta(days=1)).isoformat()   # 짝 — 학습 다음 날부터는 열린다
    assert count(client, auth, key, **{"from": next_day, "to": TO}).status_code == 200


def test_a_synthetic_model_is_hidden_in_production(client, auth, monkeypatch):
    key = ready(client, auth, source="synthetic")
    assert count(client, auth, key).status_code == 200                        # mock — 장치를 확인하는 용도로 쓴다
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    plant_index(monkeypatch, source="db")
    for r in (count(client, auth, key), ask(client, auth, key)):
        assert r.status_code == 404 and r.json()["detail"]["code"] == "day_type_model_missing"


@pytest.mark.parametrize("door", ["count", "ask"])
def test_a_broken_model_store_is_503_not_missing(client, auth, monkeypatch, door):
    def broken():
        raise RuntimeError("DB 없음")
    monkeypatch.setattr(models, "_engine", broken)
    r = count(client, auth, "a" * 64) if door == "count" else ask(client, auth, "a" * 64)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "store_unavailable"


# ── 범위 · 바구니 · 유형 ───────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("over, code", [({"from": "2026-05-02", "to": "2026-05-01"}, "bad_range"),
                                        ({"from": "2025-04-01", "to": "2026-04-30"}, "range_too_long")])
def test_the_period_rules_are_the_market_regime_ones(client, auth, monkeypatch, over, code):
    key = ready(client, auth)
    calls = plant_index(monkeypatch)
    for r in (count(client, auth, key, **over), ask(client, auth, key, **over)):
        assert r.status_code == 400 and r.json()["detail"]["code"] == code
        assert r.json()["detail"]["reason"] == k1.REASONS[code]
    assert calls == []                                                        # 읽기 전에 거절


@pytest.mark.parametrize("tickers, code", [([], "no_tickers"), ([f"{i:06d}" for i in range(31)], "too_many_tickers")])
def test_the_basket_limits_are_refused_before_anything_is_read(client, auth, monkeypatch, tickers, code):
    key = ready(client, auth)
    calls = plant_index(monkeypatch)
    r = count(client, auth, key, tickers=tickers)
    assert r.status_code == 400 and r.json()["detail"]["code"] == code
    if tickers:
        r = ask(client, auth, key, tickers=tickers)
        assert r.status_code == 400 and r.json()["detail"]["code"] == code
    assert calls == []


@pytest.mark.parametrize("types, code", [((5,), "type_out_of_range"), ((0,), "type_out_of_range"),
                                         ((1, 2, 3, 4), "all_types"), ((2, 2), "duplicate_types")])
def test_the_choice_of_types_is_checked_against_the_model(client, auth, types, code):
    key = ready(client, auth)
    r = ask(client, auth, key, types=types)
    assert r.status_code == 400 and r.json()["detail"]["code"] == code
    assert r.json()["detail"]["reason"] == ds.REFUSALS[code]


def test_the_index_store_outage_is_503_and_a_missing_index_is_refused_with_its_sentence(client, auth, monkeypatch):
    key = ready(client, auth)
    plant_index(monkeypatch, error=True)
    r = count(client, auth, key)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "regime_store_unavailable"
    plant_index(monkeypatch, empty=True)
    r = count(client, auth, key)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "regime_unavailable"
    assert k1.EMPTY["not_loaded"].format(name="코스피") in r.json()["detail"]["reason"]


# ── 세기 ────────────────────────────────────────────────────────────────────────────────
def test_counting_reports_progress_and_keeps_one_row_per_needed_day_and_ticker(client, auth):
    key = ready(client, auth)
    js = count_all(client, auth, key)
    assert js["done"] is True and js["needed_days"] == len(NEEDED) and js["counted_days"] == len(NEEDED)
    assert js["remaining_days"] == 0 and js["stale_days"] == 0 and js["next_day"] is None
    assert (js["first_day"], js["last_day"]) == (NEEDED[0], NEEDED[-1])
    stored = counts.get("alice", key, "2000-01-01", "2100-01-01")
    assert set(stored) == {(d, t) for d in NEEDED for t in (A, B)}             # 기간 마지막 거래일(04-30)은 세지 않는다
    assert all(stored[(d, t)]["label"] == TYPE_OF[path_index(d, t)] for d, t in stored)
    assert js["grade"] == "E3"


def test_a_zero_budget_counts_one_day_per_call_in_date_order(client, auth, monkeypatch):
    key = ready(client, auth)
    monkeypatch.setattr(routes, "COUNT_BUDGET_SEC", 0.0)
    for n in range(3):
        js = count(client, auth, key).json()
        assert js["this_request"]["days"] == 1 and js["counted_days"] == n + 1
        assert js["remaining_days"] == len(NEEDED) - n - 1 and js["done"] is False
        assert js["this_request"]["stopped"] == "budget" and js["next_day"] == NEEDED[n + 1]
    stored = counts.get("alice", key, "2000-01-01", "2100-01-01")
    assert sorted({d for d, _ in stored}) == NEEDED[:3]


def test_a_byte_budget_counts_one_day_per_call_too(client, auth, monkeypatch):
    """읽는 바이트의 상한 — 첫 날은 상한과 무관하게 세고(부름마다 나아간다) 그 뒤에 멈춘 까닭이 `bytes` 다."""
    key = ready(client, auth)
    monkeypatch.setattr(routes, "COUNT_MAX_BYTES", 1)
    js = count(client, auth, key).json()
    assert js["this_request"]["days"] == 1 and js["this_request"]["stopped"] == "bytes" and js["counted_days"] == 1
    assert js["this_request"]["bytes"] > 0


def test_a_growing_basket_counts_the_new_ticker_and_only_the_stale_rows_as_stale(client, auth):
    """바구니에 종목을 더하면 그 종목이 없는 날은 다 센 날이 아니다(한 종목만 센 날을 '셌다'로 치지 않는다).
    그날 일파일이 바뀐 날은 이미 있던 줄(A)만 낡은 줄이다 — 없던 줄(B)을 낡았다고 세지 않는다."""
    key = ready(client, auth)
    count_all(client, auth, key, tickers=[A])
    day = NEEDED[10]
    path = mb._existing_day_path(day)
    st = path.stat()
    write_day(day, [(A, PATHS[3], "kis"), (B, PATHS[path_index(day, B)], "kis")])
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000))
    js = count(client, auth, key).json()                                      # 바구니 [A, B]
    assert js["done"] is True and js["this_request"]["days"] == len(NEEDED)
    assert js["this_request"]["stale_rows"] == 1
    stored = counts.get("alice", key, "2000-01-01", "2100-01-01")
    assert {d for d, t in stored if t == B} == set(NEEDED) and stored[(day, A)]["label"] == 3


def test_counting_in_pieces_ends_with_the_same_answer_as_counting_at_once(client, auth, monkeypatch):
    key = ready(client, auth)
    bob = login(client, "bob")
    assert train(client, bob) == key                                          # 같은 입력 = 같은 열쇠(모형은 주인마다)
    monkeypatch.setattr(routes, "COUNT_BUDGET_SEC", 0.0)
    for _ in range(4):
        count(client, auth, key)
    monkeypatch.setattr(routes, "COUNT_BUDGET_SEC", 60.0)
    count_all(client, auth, key)
    count_all(client, bob, key)
    a, b = ask(client, auth, key), ask(client, bob, key)
    assert a.status_code == b.status_code == 200
    assert a.json() == b.json()


def test_a_rewritten_day_file_is_stale_and_only_that_day_is_counted_again(client, auth):
    key = ready(client, auth)
    count_all(client, auth, key)
    day = NEEDED[40]
    path = mb._existing_day_path(day)
    st = path.stat()
    assert mb.load_day_frame(day).frame is not None                           # 옛 내용이 캐시에 있다
    write_day(day, [(A, PATHS[3], "kis"), (B, PATHS[path_index(day, B)], "kis")], clear=False)   # 다른 쓰는 이(캐시를 모른다)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000))
    js = ask(client, auth, key).json()
    assert js["counts"]["stale_days"] == 1 and js["counts"]["remaining_days"] == 1
    again = count(client, auth, key).json()
    assert again["this_request"]["days"] == 1 and again["this_request"]["stale_rows"] == 2 and again["done"] is True
    assert counts.get("alice", key, day, day)[(day, A)]["label"] == 3       # 캐시가 아니라 다시 쓴 파일로 셌다
    assert ask(client, auth, key).json()["counts"]["stale_days"] == 0


def test_the_gate_is_part_of_the_signature(client, auth, monkeypatch):
    key = ready(client, auth)
    count_all(client, auth, key)
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    plant_index(monkeypatch, source="db")
    js = ask(client, auth, key).json()
    assert js["counts"]["counted_days"] == 0 and js["counts"]["stale_days"] == len(NEEDED)
    monkeypatch.setenv("KIS_USE_MOCK", "1")                                    # 짝 — 게이트가 같으면 낡지 않았다
    plant_index(monkeypatch)
    assert ask(client, auth, key).json()["counts"]["stale_days"] == 0


def test_synthetic_bars_are_not_counted_in_production(client, auth, monkeypatch):
    key = ready(client, auth)
    blocked = NEEDED[30:33]
    plant_bars(blocked, source="synthetic")
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    plant_index(monkeypatch, source="db")
    count_all(client, auth, key)
    stored = counts.get("alice", key, "2000-01-01", "2100-01-01")
    assert {stored[(d, A)]["reason"] for d in blocked} == {"synthetic_rows_blocked"}
    assert all(stored[(d, A)]["label"] is not None for d in NEEDED if d not in blocked)
    js = ask(client, auth, key).json()
    assert js["share"]["excluded_by_reason"].get("synthetic_rows_blocked") == 6


def test_a_synthetic_sample_reaching_the_door_in_production_is_refused_and_nothing_is_stored(client, auth, monkeypatch):
    key = ready(client, auth)
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    plant_index(monkeypatch, source="db")
    real = minute_feed.build_days

    def leaky(tickers, start, end, **kw):                                     # 로더를 지나 합성 봉이 왔다(결함을 흉내)
        days = real(tickers, start, end, **kw)
        return [dataclasses.replace(d, sessions={t: dataclasses.replace(s, source="synthetic") for t, s in d.sessions.items()})
                for d in days]
    monkeypatch.setattr(minute_feed, "build_days", leaky)
    before = row_counts()
    r = count(client, auth, key)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "synthetic_samples_in_production"
    after = row_counts()
    assert after.pop(counts._TABLE, 0) == 0                                   # 표는 생겼을 수 있으나 줄은 0
    before.pop(counts._TABLE, None)
    assert after == before


def test_counting_writes_only_the_counts_table(client, auth):
    """센 값 표 밖은 줄 수도 ★내용★도 그대로다(시행 · 모형 · 다른 표 — 시행 수 N 불변). 내용 견줌은 GET 시험에서 찾은 구멍(덮어쓰기는 줄 수를 바꾸지 않는다)을 여기에도 메운 것."""
    key = ready(client, auth)
    before, rows = row_counts(), table_rows()
    count_all(client, auth, key)
    after, rows_after = row_counts(), table_rows()
    assert after.pop(counts._TABLE) == 2 * len(NEEDED)
    before.pop(counts._TABLE, None)
    assert after == before
    rows.pop(counts._TABLE, None)
    rows_after.pop(counts._TABLE)
    assert rows_after == rows


@pytest.mark.parametrize("door", ["count", "ask"])
def test_a_broken_counts_store_is_503_not_uncounted(client, auth, monkeypatch, door):
    key = ready(client, auth)

    def broken():
        raise RuntimeError("DB 없음")
    monkeypatch.setattr(counts, "_engine", broken)
    r = count(client, auth, key) if door == "count" else ask(client, auth, key)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "counts_store_unavailable"
    assert r.json()["detail"]["reason"] == counts.REASONS["store_unavailable"]


# ── 읽기(GET) ────────────────────────────────────────────────────────────────────────────
def test_the_input_door_only_reads(client, auth, monkeypatch):
    """GET 은 읽기만 — 모든 표의 줄 수와 ★내용★이 그대로다. 있던 센 값을 덮어쓰면 줄 수는 같다 —
    변이 'GET 이 저장한다'(덮어쓰기)가 줄 수만 보던 이 시험을 지나가 내용 견줌을 더했다."""
    key = ready(client, auth)
    monkeypatch.setattr(routes, "COUNT_BUDGET_SEC", 0.0)
    count(client, auth, key)
    before, rows = row_counts(), table_rows()
    assert ask(client, auth, key).status_code == 200
    assert row_counts() == before
    assert table_rows() == rows


def test_the_index_only_answer_is_the_market_regime_answer(client, auth):
    key = ready(client, auth)
    count_all(client, auth, key)
    js = ask(client, auth, key).json()
    k1_answer = client.get(REGIME, params=Q, headers=auth).json()
    assert js["index_only"] == k1_answer


def test_the_share_answer_is_the_engine_fed_with_the_counted_values(client, auth):
    key = ready(client, auth)
    count_all(client, auth, key)
    for types in ((1,), (2, 3)):
        js = ask(client, auth, key, types=types).json()
        want = expected_with_share(types)
        got = js["with_share"]
        for field in ("days", "states", "transitions", "bic", "agreement", "fit", "centers"):
            assert got[field] == want[field], field                           # JSON 의 실수는 그대로 되돌아온다(repr 왕복)
        assert any(d["probs"] is not None for d in got["days"])               # 공허하지 않다 — 값이 있는 날이 있다


def test_a_choice_whose_share_never_moves_is_not_split(client, auth):
    """심은 봉에서 유형 1 · 3 의 몫은 날마다 1/2 로 같다 — 비중이 변하지 않는 적합 창은 국면을 나누지 않는다(엔진의 `flat_share` 문장 그대로)."""
    key = ready(client, auth)
    count_all(client, auth, key)
    js = ask(client, auth, key, types=(1, 3)).json()
    flat = mr.REASONS["flat_share"].format(need=FIT, have=FIT)
    assert {r["reason"] for r in js["with_share"]["days"]} == {flat}
    assert all(r["probs"] is not None for r in js["index_only"]["days"][1:])  # 짝 — 지수만의 답은 나눈다
    assert js["with_share"]["days"] == expected_with_share((1, 3))["days"]


def test_days_not_yet_counted_leave_only_the_share_answer_unknown(client, auth):
    key = ready(client, auth)
    count_all(client, auth, key)
    day = "2026-04-15"
    path = mb._existing_day_path(day)
    st = path.stat()
    write_day(day, [(A, PATHS[1], "kis"), (B, PATHS[0], "kis")], clear=False)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000))         # 그날 하나가 낡았다 = 세지 않은 날
    js = ask(client, auth, key).json()
    after = [r for r in js["with_share"]["days"] if r["date"] > day]
    assert after and all(r["probs"] is None and r["reason"] == ds.REASONS["not_counted"] for r in after)
    assert all(r["probs"] is not None for r in js["index_only"]["days"] if r["date"] > day)     # 지수만 답은 그대로
    assert js["with_share"]["days"] == expected_with_share(stale=frozenset({day}))["days"]
    assert routes.NOT_COUNTED.format(n=1) in js["facts"]


def test_the_comparison_counts_only_days_known_on_both_sides(client, auth):
    key = ready(client, auth)
    count_all(client, auth, key)
    day = "2026-04-15"
    path = mb._existing_day_path(day)
    st = path.stat()
    write_day(day, [(A, PATHS[1], "kis"), (B, PATHS[0], "kis")], clear=False)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000))
    js = ask(client, auth, key).json()
    pairs = [(a["top"], b["top"]) for a, b in zip(js["index_only"]["days"], js["with_share"]["days"], strict=True)]
    both = [(x, y) for x, y in pairs if x is not None and y is not None]
    assert 0 < len(both) < len(pairs)                                         # 비교에서 빠진 날이 실제로 있다
    assert js["compare"] == {"both_days": len(both), "differ_days": sum(1 for x, y in both if x != y)}


def test_in_sample_counts_only_training_samples_inside_the_counted_days(client, auth):
    key = ready(client, auth)
    count_all(client, auth, key)
    js = ask(client, auth, key).json()
    assert js["share"]["in_sample"] == {"samples": 2 * len(TRAIN_DAYS), "days": len(TRAIN_DAYS)}
    assert js["share"]["classified"] == 2 * len(NEEDED)


def test_a_model_trained_before_the_read_range_has_no_in_sample_samples(client, auth):
    plant_bars(EARLY_TRAIN + NEEDED)
    key = train(client, auth, {**TRAIN_BODY, "from": EARLY_TRAIN[0], "to": EARLY_TRAIN[-1]})
    count_all(client, auth, key)
    js = ask(client, auth, key).json()
    assert js["share"]["in_sample"] == {"samples": 0, "days": 0}
    assert js["share"]["classified"] == 2 * len(NEEDED)


def test_a_partial_basket_day_is_pooled_and_reported(client, auth):
    key = ready(client, auth)
    day = NEEDED[50]
    write_day(day, [(A, PATHS[path_index(day, A)], "kis"), (B, PATHS[0][:3], "kis")])          # B 는 봉 셋(창이 덜 참)
    count_all(client, auth, key)
    js = ask(client, auth, key).json()
    assert js["share"]["partial_days"] == 1
    assert js["share"]["excluded_by_reason"] == {"short_window": 1}
    assert js["share"]["excluded_messages"]["short_window"] == dt.EXCLUDE_REASONS["short_window"]
    assert js["share"]["classified"] == 2 * len(NEEDED) - 1


def test_the_share_used_for_each_day_is_the_previous_trading_days_window(client, auth):
    key = ready(client, auth)
    count_all(client, auth, key)
    js = ask(client, auth, key).json()
    read = [d for d in INDEX_DAYS if READ_START <= d <= TO]
    by_day = {d: ds.basket_day([(TYPE_OF[path_index(d, A)], None), (TYPE_OF[path_index(d, B)], None)]) for d in NEEDED}
    values, _, samples = ds.window_share(read, by_day, (1,))
    want = [(d, values[read.index(d) - 1], int(samples[read.index(d) - 1])) for d in read if FROM <= d <= TO]
    got = [(r["date"], r["value"], r["samples"]) for r in js["share"]["days"]]
    assert [g[0] for g in got] == [w[0] for w in want]
    assert all(g[1] == pytest.approx(w[1]) and g[2] == w[2] for g, w in zip(got, want, strict=True))


def test_the_answer_says_what_it_is_not_in_server_sentences(client, auth):
    key = ready(client, auth)
    count_all(client, auth, key)
    js = ask(client, auth, key).json()
    assert js["notes"] == list(routes.NOTES) and len(js["notes"]) >= 4
    for line in js["notes"] + js["facts"]:
        assert line.endswith(("다.", "다).")) and "—" not in line and "–" not in line, line
    assert any("예측" in n for n in js["notes"]) and any("관측" in n for n in js["notes"])
    assert js["model"]["key"] == key and js["types"] == [1] and js["tickers"] == [A, B] and js["window"] == ds.WINDOW


def test_the_share_answer_names_its_third_feature_in_its_notes(client, auth):
    """K1 의 문장 가운데 넷은 더한 답에서 틀리거나 넘치는 말이다 — 셋째 특징에 맞게 바꾼다:
    ① 특징('지수의 20거래일 수익과 실현 변동성이 닮은 날끼리') ③ 계산 시점(그날 종가만 말한다)
    ④ 달마다 적합 — 창은 세 특징이 모두 있는 날이고(비중을 모르는 날은 빠진다 · `test_market_regime` 이 건다) 같은 값의 조건에 분봉이 든다
    ⑥ 시드 일치도 — '잰 값'은 지수만의 답으로 잰 것이다(더한 답으로는 재지 않았다).
    번호(②) · BIC(⑤)는 같은 말이 그대로 맞다. ④ · ⑥ 은 첫 화면 촬영 검수에서 찾았다(처음에는 그대로 맞다고 적었다)."""
    key = ready(client, auth)
    count_all(client, auth, key)
    js = ask(client, auth, key).json()
    ws, io = js["with_share"]["notes"], js["index_only"]["notes"]
    assert io == list(k1.NOTES)
    assert ws == list(routes.WITH_SHARE_NOTES)
    assert [a == b for a, b in zip(ws, io, strict=True)] == [False, True, False, False, True, False]
    assert "하루 유형 비중" in ws[0] and "하루 유형 비중" in ws[2] and "예측" in ws[0]
    assert "세 특징" in ws[3] and "같은 종가와 같은 분봉에서는" in ws[3] and "같은 종가에서는" not in ws[3]
    assert "같은 종가에서는 같은 날이 언제 다시 봐도 같은 값입니다" in io[3]          # 짝 — 지수만의 답에는 그 말이 맞다
    assert "비중을 더한 답으로는 재지 않았습니다" in ws[5] and "재지 않았습니다" not in io[5]


@pytest.mark.parametrize("template, args", [
    (routes.COUNTED, {"needed": 1020, "counted": 1003}),
    (routes.NOT_COUNTED, {"n": 1017}),
    (routes.STALE, {"n": 1200}),
    (routes.IN_SAMPLE, {"classified": 1780, "n": 1128}),
    (routes.PARTIAL, {"n": 1001}),
    (routes.COMPARE, {"both": 1019, "differ": 1002}),
], ids=["counted", "not_counted", "stale", "in_sample", "partial", "compare"])
def test_counts_in_the_server_sentences_are_grouped_by_thousands_like_the_screen(template, args):
    """화면은 수를 천 단위 쉼표로 쓴다('1,250 달력일' · '센 날 1,020') — 같은 답 안의 서버 문장도 같게.
    읽기 구간이 1,250 달력일이라 셀 날 · 표본 수는 1,000 을 쉽게 넘는다(첫 촬영 검수에서 '표본 1780개'를 찾았다)."""
    line = template.format(**args)
    for v in args.values():
        assert f"{v:,}" in line, line


def test_the_doors_never_build_a_broker_client(client, auth, monkeypatch):
    key = ready(client, auth)
    import src.execution.kis_client as kc

    def boom(*a, **k):
        raise AssertionError("비중 세기가 증권사 클라이언트를 만들었다")
    monkeypatch.setattr(kc, "get_kis_client", boom)
    count_all(client, auth, key)
    assert ask(client, auth, key).status_code == 200


def test_the_modules_never_import_the_order_path():
    banned = ("trading_engine", "order_executor", "kis_client", "execution")
    for path in (ROOT / "src/api/intraday_regime_share_routes.py", ROOT / "src/data/day_type_counts.py",
                 ROOT / "src/engine/day_type_share.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)] + \
                [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        assert names and not [n for n in names if any(b in n.lower() for b in banned)], path.name
