"""규칙 맥락의 문 층 — 규칙이 쓰는 하루 유형 모형을 ★그 사용자의 것만★ 읽어 싣는다 (구현 계획 2026-11-16 §6 · T2).

`src/api/intraday_context.py` 가 지키는 약속:
- ★봉을 읽기 전에★ 거절한다 — 없는 모형 · 남의 모형 · 운영 게이트의 합성 모형은 같은 답(있는지를 알려 주지 않는다) ·
  유형 번호 > 그 모형의 유형 수 · ★학습 마지막 날 ≥ 판정 시작일★(겹침도 뒤의 모형도 앞보기다) · 저장소를 읽지 못하면 503.
- 모형을 쓰지 않는 규칙은 맥락 없이 그대로 지난다(기존 경로 · 골든 불변 — 같은 하루 목록 객체).
- 판정 응답의 사실 줄 — 학습 기간 · 종목 수 · 판정 종목과 같은지 · 합성이면 그렇다고.
"""
from __future__ import annotations

import os
import tempfile

import numpy as np
import pytest
from fastapi import HTTPException

import src.database as dbmod
from src.api import intraday_context as ctxmod
from src.data import intraday_day_types as store
from src.engine.intraday import Day, Session
from src.engine.intraday import day_types as dt
from src.engine.intraday.simulator import RuleSpec

PATHS = [[10.0, 20.0, 30.0, 40.0, 50.0], [-10.0, -20.0, -30.0, -40.0, -50.0],
         [-10.0, -20.0, -30.0, -20.0, -10.0], [10.0, 20.0, 30.0, 20.0, 10.0]]
KEY = "1a2b3c4d" + "0" * 56
SYN = "5e" * 32
FIRST, LAST = "2026-05-04", "2026-05-19"


def leaf(model=KEY, number=3):
    return {"ind": "day_type_is", "model": model, "type": number}


def rule(*leaves, exit_leaf=None) -> RuleSpec:
    entry = {"op": "gt", "args": [leaves[0], {"const": 0.5}]} if len(leaves) == 1 else \
        {"op": "and", "args": [{"op": "gt", "args": [x, {"const": 0.5}]} for x in leaves]}
    return RuleSpec(entry=entry, exit={"op": "lt", "args": [exit_leaf, {"const": 0.5}]} if exit_leaf else None)


def plant(user="alice", key=KEY, grade="E3", tickers=("005930", "000660"), first=FIRST, last=LAST):
    centroids = dt.order_centroids(np.asarray(PATHS))
    types = [{"type": j + 1, "samples": 6, "share": 0.25, "path": c.tolist(), "end": float(c[-1]), "low": float(c.min()),
              "high": float(c.max()), "spread": 0.0} for j, c in enumerate(centroids)]
    saved = store.save(user, key=key, grade=grade, minutes=5, k=4, method="e-means", version=1, seed=1234, tickers=list(tickers),
                       first_day=first, last_day=last, samples=24, body={"types": types, "days": [first, last]})
    assert saved is not None and saved["created"]
    return centroids


@pytest.fixture(autouse=True)
def db(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp.name}")
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    monkeypatch.setattr(dbmod, "DATABASE_URL", f"sqlite:///{tmp.name}", raising=False)
    dbmod.reset_session()
    dbmod.init_db()
    yield
    dbmod.reset_session()
    try:
        os.unlink(tmp.name)
    except OSError:
        pass


def refused(username, spec, start) -> HTTPException:
    with pytest.raises(HTTPException) as err:
        ctxmod.load(username, spec, start)
    return err.value


def day(date: str, tickers=("005930", "000660")) -> Day:
    sessions = {t: Session(t, date, np.array(["090000", "090100"]), np.array([1.0, 2.0]), np.array([2.0, 3.0]),
                           np.array([0.5, 1.5]), np.array([2.0, 2.5]), np.array([10.0, 20.0]), "kis", market="KOSPI")
                for t in tickers}
    return Day(date, sessions, skipped=(("035420", "no_bars"),), shifted=False)


# ── 읽기 ───────────────────────────────────────────────────────────────────────────────
def test_a_rule_without_a_day_type_needs_no_context_and_passes_untouched():
    """짝 — 모형을 쓰지 않는 규칙은 저장소를 묻지도 않고 하루 목록도 같은 객체 그대로다(기존 경로 불변)."""
    plain = RuleSpec(entry={"op": "gt", "args": [{"ind": "close"}, {"ind": "vwap"}]})
    loaded = ctxmod.load("alice", plain, date_("2026-06-01"))
    assert loaded.context is None and loaded.models == []
    days = [day("2026-06-01")]
    assert ctxmod.attach(days, loaded) is days


def date_(s: str):
    from datetime import date
    return date.fromisoformat(s)


def test_my_model_loads_with_its_centroids_in_number_order():
    centroids = plant()
    loaded = ctxmod.load("alice", rule(leaf()), date_("2026-05-20"))
    ref = loaded.context.day_types[KEY]
    assert np.array_equal(ref.centroids, centroids) and (ref.minutes, ref.k) == (5, 4)
    assert [m["key"] for m in loaded.models] == [KEY] and loaded.models[0]["last_day"] == LAST


def test_every_model_the_rule_uses_is_loaded_once_from_any_slot():
    plant()
    plant(key="2b" * 32)
    loaded = ctxmod.load("alice", rule(leaf(), leaf(number=1), exit_leaf=leaf(model="2b" * 32, number=2)), date_("2026-05-20"))
    assert sorted(loaded.context.day_types) == sorted([KEY, "2b" * 32]) and len(loaded.models) == 2
    assert ctxmod.uses(rule(leaf(), leaf(number=1), exit_leaf=leaf(model="2b" * 32, number=2))) == {KEY: {1, 3}, "2b" * 32: {2}}


# ── 학습 날 ─────────────────────────────────────────────────────────────────────────────
def test_the_last_learned_day_must_be_before_the_first_judged_day():
    plant()
    err = refused("alice", rule(leaf()), date_(LAST))                   # 학습 마지막 날 = 판정 시작일 → 겹친다
    assert err.status_code == 400 and err.detail["code"] == "day_type_model_overlaps"
    assert (err.detail["first_day"], err.detail["last_day"], err.detail["start"]) == (FIRST, LAST, LAST)
    assert ctxmod.load("alice", rule(leaf()), date_("2026-05-20")).context is not None      # 짝 — 하루 뒤면 돈다


def test_a_model_learned_after_the_judged_period_is_refused_too():
    plant()
    err = refused("alice", rule(leaf()), date_("2026-04-01"))           # 판정이 학습보다 앞 — 뒤의 날로 학습한 모형은 앞보기다
    assert err.detail["code"] == "day_type_model_overlaps"


# ── 주인 · 합성 · 저장소 ─────────────────────────────────────────────────────────────────
def test_someone_elses_model_and_a_missing_model_get_the_same_answer():
    plant(user="bob")
    other = refused("alice", rule(leaf()), date_("2026-06-01"))
    missing = refused("alice", rule(leaf(model="9" * 64)), date_("2026-06-01"))
    assert other.status_code == missing.status_code == 400
    assert other.detail["code"] == missing.detail["code"] == "day_type_model_missing"
    assert other.detail["reason"] == missing.detail["reason"] and set(other.detail) == set(missing.detail)


def test_a_synthetic_model_is_hidden_in_production_and_labelled_in_mock(monkeypatch):
    plant(key=SYN, grade="E0")
    monkeypatch.setenv("KIS_USE_MOCK", "0")                                 # 운영 게이트(비우면 기본값이 mock 이다)
    assert refused("alice", rule(leaf(model=SYN)), date_("2026-06-01")).detail["code"] == "day_type_model_missing"
    monkeypatch.setenv("KIS_USE_MOCK", "1")                                 # 짝 — 모의 모드에서는 쓰되 합성이라고 적는다
    loaded = ctxmod.load("alice", rule(leaf(model=SYN)), date_("2026-06-01"))
    said = ctxmod.facts(loaded, ["005930", "000660"])
    assert said[0]["grade"] == "E0" and ctxmod.SYNTHETIC_FACT in said[0]["sentences"]


def test_a_type_number_above_the_models_count_is_refused():
    plant()
    err = refused("alice", rule(leaf(number=5)), date_("2026-06-01"))
    assert err.detail["code"] == "day_type_out_of_range" and (err.detail["type"], err.detail["k"]) == (5, 4)


def test_a_store_that_cannot_be_read_is_a_503_not_a_missing_model(monkeypatch):
    plant()
    monkeypatch.setattr(store, "model_of", lambda user, key: None)
    err = refused("alice", rule(leaf()), date_("2026-06-01"))
    assert err.status_code == 503 and err.detail["code"] == "store_unavailable"


# ── 싣기 · 사실 줄 ───────────────────────────────────────────────────────────────────────
def test_every_session_of_every_day_carries_the_same_context_object_and_keeps_the_rest():
    plant()
    loaded = ctxmod.load("alice", rule(leaf()), date_("2026-06-01"))
    days = [day("2026-06-01"), day("2026-06-02", tickers=("005930",))]
    out = ctxmod.attach(days, loaded)
    assert [d.date for d in out] == ["2026-06-01", "2026-06-02"]
    for before, after in zip(days, out, strict=True):
        assert after.skipped == before.skipped and after.shifted == before.shifted and set(after.sessions) == set(before.sessions)
        for t, s in after.sessions.items():
            assert s.context is loaded.context and s.market == "KOSPI" and np.array_equal(s.close, before.sessions[t].close)
    assert all(s.context is None for d in days for s in d.sessions.values())   # 받은 하루는 바꾸지 않는다


def test_the_fact_line_names_the_learning_period_and_whether_the_tickers_are_the_same():
    plant()
    loaded = ctxmod.load("alice", rule(leaf()), date_("2026-06-01"))
    same = ctxmod.facts(loaded, ["000660", "005930"])[0]
    assert same["key"] == KEY and same["same_tickers"] is True and same["grade"] == "E3"
    assert same["sentences"][0] == "하루 유형 모형 1a2b3c4d의 학습 기간은 2026-05-04~2026-05-19이며 종목 2개로 학습했습니다. 학습은 판정 시작일 전에 끝났습니다."
    assert same["sentences"][1] == ctxmod.SAME_TICKERS and ctxmod.SYNTHETIC_FACT not in same["sentences"]
    other = ctxmod.facts(loaded, ["035420"])[0]
    assert other["same_tickers"] is False and other["sentences"][1] == ctxmod.OTHER_TICKERS
    assert all("—" not in s and "–" not in s for s in (*same["sentences"], *other["sentences"]))
