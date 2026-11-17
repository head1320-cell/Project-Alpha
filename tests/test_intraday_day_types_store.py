"""하루 유형 모형의 저장소 — `src/data/intraday_day_types.py` (구현 계획 2026-11-16 §5.2 · T1).

거는 약속:
- 주인 + 열쇠가 한 모형이다. 같은 주인이 같은 열쇠로 다시 저장하면 ★쓰지 않고★ 처음 것을 돌려준다(`created: false`).
- 남의 모형과 없는 모형은 같은 답이다(있는지를 알려 주지 않는다).
- 읽거나 쓰지 못하면 `None` — 빈 목록 · 없음과 다르다.
- 지우는 길이 없다 · 보존 분류 ③ 결정 기록(T2 의 규칙이 열쇠로 가리킨다).
"""
from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace

import pytest
from sqlalchemy import text

import src.database as dbmod
from src.data import intraday_day_types as store
from src.data import retention

BODY = {"types": [{"type": 1, "days": 3, "path": [-10.0, -20.0]}], "loss": {"emeans": 1.5, "lloyd": 1.5},
        "days": ["2026-05-04", "2026-05-05"]}


@pytest.fixture()
def db(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp.name}")
    monkeypatch.setattr(dbmod, "DATABASE_URL", f"sqlite:///{tmp.name}", raising=False)
    dbmod.reset_session()
    yield tmp.name
    dbmod.reset_session()
    try:
        os.unlink(tmp.name)
    except OSError:
        pass


def put(user="alice", key="k" * 64, *, grade="E3", body=BODY, minutes=30, k=6):
    return store.save(user, key=key, grade=grade, minutes=minutes, k=k, method="e-means", version=1, seed=1234,
                      tickers=["005930", "000660"], first_day="2026-05-04", last_day="2026-05-05", samples=4, body=body)


def rows() -> int:
    with dbmod.get_engine().connect() as c:
        return int(c.execute(text("SELECT COUNT(*) FROM intraday_day_types")).scalar())


def test_a_saved_model_reads_back_whole(db):
    made = put()
    assert made["created"] is True
    got = store.model_of("alice", "k" * 64)
    assert got["found"] is True
    assert got["body"] == BODY
    assert (got["key"], got["grade"], got["minutes"], got["k"], got["method"], got["version"], got["seed"]) == (
        "k" * 64, "E3", 30, 6, "e-means", 1, 1234)
    assert got["tickers"] == ["005930", "000660"]
    assert (got["first_day"], got["last_day"], got["samples"]) == ("2026-05-04", "2026-05-05", 4)
    assert isinstance(got["created_at"], float)


def test_the_same_key_twice_keeps_the_first_row(db):
    first = put()
    again = put(body={"types": [], "note": "다른 몸통"})              # 같은 주인 · 같은 열쇠
    assert again["created"] is False
    assert again["model"]["body"] == BODY                             # 처음 것을 돌려준다(덮어쓰지 않는다)
    assert again["model"]["created_at"] == first["model"]["created_at"]
    assert rows() == 1


def test_another_owner_with_the_same_key_gets_a_separate_row(db):
    put("alice")
    other = put("bob")
    assert other["created"] is True
    assert rows() == 2


def test_someone_elses_model_reads_like_a_missing_one(db):
    put("alice")
    assert store.model_of("bob", "k" * 64) == {"found": False}
    assert store.model_of("alice", "z" * 64) == {"found": False}


def test_my_models_come_newest_first_and_without_bodies(db, monkeypatch):
    clock = iter([100.0, 200.0, 300.0])
    monkeypatch.setattr(store, "time", SimpleNamespace(time=lambda: next(clock)))
    put(key="a" * 64)
    put(key="b" * 64)
    put("bob", key="c" * 64)
    mine = store.models_of("alice")
    assert [m["key"] for m in mine] == ["b" * 64, "a" * 64]           # 남의 것은 오지 않는다
    assert all("body" not in m for m in mine)                         # 목록은 가볍다 — 몸통은 하나를 읽을 때
    assert store.models_of("carol") == []


def test_the_limit_caps_the_list(db):
    for i in range(3):
        put(key=str(i) * 64)
    assert len(store.models_of("alice", limit=2)) == 2


@pytest.mark.parametrize("call", [
    lambda: put(),
    lambda: store.models_of("alice"),
    lambda: store.model_of("alice", "k" * 64),
])
def test_a_broken_store_answers_none_not_empty(db, monkeypatch, call):
    def broken():
        raise RuntimeError("DB 없음")
    monkeypatch.setattr(store, "_engine", broken)
    assert call() is None
    assert store.REASONS["store_unavailable"]


def test_an_unreadable_body_is_unknown_not_missing(db):
    put()
    with dbmod.get_engine().begin() as c:
        c.execute(text("UPDATE intraday_day_types SET body = '{깨진' WHERE username = 'alice'"))
    assert store.model_of("alice", "k" * 64) is None                  # 있는데 못 읽었다 — '없음'이 아니다


def test_the_table_is_a_decision_record_and_has_no_delete_path():
    assert "intraday_day_types" in retention.DECISION_RECORD
    assert "열쇠" in retention.DECISION_RECORD["intraday_day_types"]
    src = open(store.__file__, encoding="utf-8").read()
    assert "DELETE" not in src.upper().replace("ON DELETE", "")
