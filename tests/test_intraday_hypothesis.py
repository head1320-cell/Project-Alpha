"""실행 전 가설(G3 · 구현 계획 §4) — 시행 줄에 ★처음 적은 것만★ 남기고, 적을 때의 실행 횟수를 함께 남긴다.

계약(저장소 `src/data/intraday_trials.py`)
- 처음 적은 가설만 남는다 — 다시 보내도 바뀌지 않는다(답이 남아 있는 것을 돌려준다).
- 적을 때의 실행 횟수를 남긴다: 1 이면 첫 실행과 함께(결과를 보기 전) · 그보다 크면 앞선 실행의 결과를 본 뒤다(가설 찍어내기의 정직 라벨).
- 남의 시행과 없는 시행은 같은 답이다(있는지를 알려 주지 않는다) · 남의 줄에 쓰지 않는다.
- 가설은 시행 열쇠에 들지 않는다 — 적어도 같은 설정은 같은 시행이다(실행 횟수만 는다).
- 칸을 붙이지 못한 DB 에서는 가설이 '모른다'(`None`)이고 시행 세기는 그대로 돈다 · 저장소 장애도 `None`(없음으로 꾸미지 않는다).
"""
from __future__ import annotations

import os
import tempfile

import pytest

import src.database as dbmod
from src.data import intraday_trials as trials

SETTING = {"rule": {"kind": "opening_range_breakout", "params": {"minutes": 30}},
           "position": {"amount": 1_000_000.0, "stop_pct": None},
           "costs": {"commission_bp": 1.5, "slippage_ticks": 1, "participation_cap": 0.1}}
DAILY = {"basis": "net", "dates": ["2026-03-02"], "values": [1_200.0]}
IDEA = "장 초반 30분 고가를 넘으면 그날 매수세가 이어진다고 봅니다."


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


def rec(user="alice"):
    return trials.record(user, grade="E3", setting=SETTING, tickers=["005930"], start="2026-03-02", end="2026-03-31", daily=DAILY)


def test_the_first_hypothesis_is_kept_and_a_later_one_does_not_replace_it(db):
    key = rec()["trial_key"]
    first = trials.keep_hypothesis("alice", key, IDEA)
    assert first == {"found": True, "kept": True, "hypothesis": IDEA, "at_run": 1}
    again = trials.keep_hypothesis("alice", key, "결과를 보고 고친 다른 기제")
    assert again == {"found": True, "kept": False, "hypothesis": IDEA, "at_run": 1}       # 처음 것이 남아 있다
    assert trials.hypotheses_of("alice") == {key: {"hypothesis": IDEA, "at_run": 1}}


def test_the_run_count_at_writing_is_kept__written_after_two_runs_says_two(db):
    """짝: 첫 실행과 함께 적으면 1 ↔ 두 번 돌린 뒤 처음 적으면 2(앞선 결과를 본 뒤다)."""
    rec()
    key = rec()["trial_key"]                                                     # 같은 설정을 한 번 더 — runs 2
    assert trials.keep_hypothesis("alice", key, IDEA)["at_run"] == 2


def test_someone_elses_trial_is_the_same_as_no_trial_and_is_not_written(db):
    key = rec("alice")["trial_key"]
    assert trials.keep_hypothesis("bob", key, IDEA) == {"found": False}
    assert trials.keep_hypothesis("bob", "0" * 64, IDEA) == {"found": False}
    assert trials.hypotheses_of("alice") == {}                                   # alice 의 줄은 비어 있다
    assert trials.keep_hypothesis("alice", key, IDEA)["kept"] is True            # 짝: 주인은 적을 수 있다


def test_the_hypothesis_does_not_enter_the_trial_key(db):
    """가설을 적은 뒤 같은 설정을 다시 돌려도 같은 시행이다 — 실행 횟수만 늘고 가설은 그대로다."""
    made = rec()
    trials.keep_hypothesis("alice", made["trial_key"], IDEA)
    again = rec()
    assert (again["trial_key"], again["new"], again["runs"]) == (made["trial_key"], False, 2)
    assert trials.hypotheses_of("alice")[made["trial_key"]] == {"hypothesis": IDEA, "at_run": 1}


def test_without_the_columns_the_hypothesis_is_unknown_and_trials_still_count(db, monkeypatch):
    import src.data.schema_add_columns as adder
    monkeypatch.setattr(adder, "add_columns", lambda *a, **k: False)
    trials._ready_for = None
    made = rec()
    assert made["new"] is True and made["runs"] == 1
    assert trials.keep_hypothesis("alice", made["trial_key"], IDEA) is None
    assert trials.hypotheses_of("alice") is None


def test_an_empty_run_count_is_unknown_not_zero(db):
    """미상 ≠ 0 — 가설은 있는데 적을 때의 실행 횟수 칸이 비어 있으면(손으로 고친 줄 등) 0 이 아니라 `None` 이다."""
    key = rec()["trial_key"]
    trials.keep_hypothesis("alice", key, IDEA)
    from sqlalchemy import text
    with trials._engine().begin() as c:
        c.execute(text(f"UPDATE {trials._TABLE} SET hypothesis_run = NULL WHERE trial_key = :k"), {"k": key})
    assert trials.hypotheses_of("alice") == {key: {"hypothesis": IDEA, "at_run": None}}
    assert trials.keep_hypothesis("alice", key, "다른 글") == {"found": True, "kept": False, "hypothesis": IDEA, "at_run": None}


def test_a_broken_store_is_unknown_not_empty(db, monkeypatch):
    key = rec()["trial_key"]

    def broken():
        raise RuntimeError("db down")

    monkeypatch.setattr(trials, "_engine", broken)
    assert trials.keep_hypothesis("alice", key, IDEA) is None
    assert trials.hypotheses_of("alice") is None
