"""시행 횟수 기록 — `src/data/intraday_trials.py` (분봉 백테스트 설계 §8.2 · W4d d1).

이 저장소에서 처음으로 ★몇 번 해 봤는가(N)★ 를 세는 자리다. 시험이 거는 약속:

- 한 시행 = 설정이 하나라도 다른 실행. 같은 설정 · 같은 종목 · 같은 기간을 다시 돌린 것은 새 시행이 아니다.
- 가족(N 을 세는 범위) = 그 사용자의 시행 가운데 ★기간이 겹치고 종목이 하나라도 겹치는★ 것 — 기간을 하루 옮기거나
  종목 하나를 바꿔 N 을 되돌릴 수 없다.
- 합성 분봉 위의 시행과 실제 분봉 위의 시행은 서로의 N 에 들어가지 않는다(다른 데이터를 본 것이다).
- 기록하지 못하면 `None` 이다. ★N=1 로 꾸미지 않는다.★
"""
from __future__ import annotations

import os
import tempfile

import pytest
from sqlalchemy import text

import src.database as dbmod
from src.data import intraday_trials as trials
from src.data import retention

SETTING = {"rule": {"kind": "opening_range_breakout", "params": {"minutes": 30}},
           "position": {"amount": 1_000_000.0, "stop_pct": None},
           "costs": {"commission_bp": 1.5, "slippage_ticks": 1, "participation_cap": 0.1}}
DAILY = {"basis": "net", "dates": ["2026-03-02", "2026-03-03", "2026-03-04"], "values": [1_200.0, 0.0, -300.5]}


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


def rec(user="alice", *, grade="E3", setting=SETTING, tickers=("005930", "000660"), start="2026-03-02", end="2026-03-31",
        daily=DAILY):
    return trials.record(user, grade=grade, setting=setting, tickers=list(tickers), start=start, end=end, daily=daily)


def fam(user="alice", *, grade="E3", tickers=("005930", "000660"), start="2026-03-02", end="2026-03-31"):
    return trials.family(user, grade=grade, tickers=list(tickers), start=start, end=end)


def changed(path: str, value) -> dict:
    """SETTING 에서 한 칸만 바꾼 설정."""
    section, key = path.split(".")
    out = {k: dict(v) for k, v in SETTING.items()}
    if section == "rule" and key != "kind":
        out["rule"] = {"kind": SETTING["rule"]["kind"], "params": {**SETTING["rule"]["params"], key: value}}
    else:
        out[section][key] = value
    return out


# ── 남기고 읽는다 ─────────────────────────────────────────────────────────────────────
def test_a_run_is_recorded_and_read_back_as_it_was(db):
    made = rec()
    assert made["new"] is True and made["runs"] == 1 and made["trial_key"]
    found = fam()
    assert found["user_total"] == 1 and len(found["trials"]) == 1
    row = found["trials"][0]
    assert row["trial_key"] == made["trial_key"] and row["setting"] == SETTING
    assert (row["tickers"], row["from"], row["to"]) == (["000660", "005930"], "2026-03-02", "2026-03-31")
    assert row["daily"] == DAILY and row["runs"] == 1 and row["oos_views"] == 0 and row["oos_from"] is None
    assert row["created_at"] > 0


def test_a_flow_before_costs_is_stored_as_such(db):
    rec(daily={**DAILY, "basis": "gross"})
    assert fam()["trials"][0]["daily"]["basis"] == "gross"


# ── 한 시행 ───────────────────────────────────────────────────────────────────────────
def test_the_same_setting_tickers_and_period_is_not_a_new_trial(db):
    first = rec()
    again = rec(tickers=("000660", "005930"), daily={**DAILY, "values": [1.0, 2.0, 3.0]})     # 종목의 순서만 다르다
    assert again["new"] is False and again["runs"] == 2 and again["trial_key"] == first["trial_key"]
    found = fam()
    assert len(found["trials"]) == 1 and found["user_total"] == 1
    assert found["trials"][0]["runs"] == 2 and found["trials"][0]["daily"]["values"] == [1.0, 2.0, 3.0]      # 흐름은 마지막 실행의 것


@pytest.mark.parametrize(("path", "value"), [("rule.minutes", 31), ("rule.kind", "vwap_cross"), ("position.stop_pct", 2.0),
                                             ("position.amount", 2_000_000.0), ("costs.commission_bp", 1.0),
                                             ("costs.slippage_ticks", 2)])
def test_any_difference_in_the_setting_is_a_new_trial(db, path, value):
    rec()
    other = rec(setting=changed(path, value))
    assert other["new"] is True and len(fam()["trials"]) == 2


def test_the_setting_digest_ignores_the_order_of_keys_and_nothing_else():
    shuffled = {"costs": dict(reversed(SETTING["costs"].items())), "position": SETTING["position"], "rule": SETTING["rule"]}
    assert trials.digest(shuffled) == trials.digest(SETTING)
    assert trials.digest(changed("rule.minutes", 31)) != trials.digest(SETTING)
    assert trials.digest(changed("position.stop_pct", 0.0)) != trials.digest(SETTING)          # 0 은 '쓰지 않음'과 다르다


def test_a_different_period_or_ticker_set_is_another_trial(db):
    rec()
    assert rec(end="2026-03-30")["new"] is True
    assert rec(tickers=("005930",))["new"] is True
    assert fam()["user_total"] == 3


# ── 가족 ──────────────────────────────────────────────────────────────────────────────
def test_moving_the_period_by_a_day_or_swapping_a_ticker_does_not_reset_the_count(db):
    rec()
    rec(setting=changed("rule.minutes", 15), start="2026-03-03", end="2026-04-01")             # 기간을 하루 옮겼다
    rec(setting=changed("rule.minutes", 60), tickers=("005930", "035720"))                     # 종목 하나를 바꿨다
    assert len(fam()["trials"]) == 3
    assert len(fam(tickers=("035720", "005930"), start="2026-03-31", end="2026-04-30")["trials"]) == 3      # 끝 하루만 겹쳐도 가족이다


def test_a_period_that_does_not_overlap_is_outside_the_family(db):
    rec()
    rec(setting=changed("rule.minutes", 15), start="2026-04-01", end="2026-04-30")             # 바로 다음 날부터 — 겹치지 않는다
    assert len(fam()["trials"]) == 1 and fam()["user_total"] == 2
    assert len(fam(start="2026-04-01", end="2026-04-30")["trials"]) == 1


def test_a_trial_that_shares_no_ticker_is_outside_the_family(db):
    rec()
    rec(tickers=("035720", "051910"))
    found = fam()
    assert len(found["trials"]) == 1 and found["user_total"] == 2
    assert found["trials"][0]["tickers"] == ["000660", "005930"]


def test_trials_are_counted_per_user(db):
    rec()
    rec("bob", setting=changed("rule.minutes", 15))
    rec("bob", setting=changed("rule.minutes", 60))
    assert len(fam("alice")["trials"]) == 1 and fam("alice")["user_total"] == 1
    assert len(fam("bob")["trials"]) == 2 and fam("bob")["user_total"] == 2


def test_runs_on_synthetic_bars_and_runs_on_real_bars_do_not_count_toward_each_other(db):
    real = rec(grade="E3")
    synthetic = rec(grade="E0")                                  # 같은 설정 · 같은 종목 · 같은 기간 — 본 데이터가 다르다
    assert synthetic["new"] is True and synthetic["trial_key"] != real["trial_key"]
    rec(grade="E0", setting=changed("rule.minutes", 15))
    assert len(fam(grade="E3")["trials"]) == 1 and fam(grade="E3")["user_total"] == 1
    assert len(fam(grade="E0")["trials"]) == 2
    assert fam(grade="unknown") == {"trials": [], "user_total": 0}


def test_the_family_comes_back_in_the_order_the_trials_were_first_made(db):
    keys = [rec(setting=changed("rule.minutes", m))["trial_key"] for m in (45, 15, 30)]
    rec(setting=changed("rule.minutes", 45))                     # 다시 돌려도 첫 시각은 그대로다
    assert [t["trial_key"] for t in fam()["trials"]] == keys


# ── 표본외를 본 횟수 ──────────────────────────────────────────────────────────────────
def test_each_look_at_the_out_of_sample_part_is_counted_on_the_trial(db):
    key = rec()["trial_key"]
    assert trials.mark_oos("alice", key, "2026-03-24", "2026-03-31") == 1
    assert trials.mark_oos("alice", key, "2026-03-24", "2026-03-31") == 2
    row = fam()["trials"][0]
    assert (row["oos_views"], row["oos_from"], row["oos_to"]) == (2, "2026-03-24", "2026-03-31")


def test_a_look_cannot_be_counted_on_a_trial_that_is_not_yours_or_not_there(db):
    key = rec()["trial_key"]
    assert trials.mark_oos("bob", key, "2026-03-24", "2026-03-31") is None
    assert trials.mark_oos("alice", "no-such-trial", "2026-03-24", "2026-03-31") is None
    assert fam()["trials"][0]["oos_views"] == 0


def test_looks_are_summed_over_the_trials_whose_out_of_sample_part_overlaps():
    rows = [{"oos_views": 2, "oos_from": "2026-03-24", "oos_to": "2026-03-31"},
            {"oos_views": 3, "oos_from": "2026-03-31", "oos_to": "2026-04-10"},              # 하루 겹친다
            {"oos_views": 5, "oos_from": "2026-04-01", "oos_to": "2026-04-10"},              # 겹치지 않는다
            {"oos_views": 0, "oos_from": None, "oos_to": None}]                              # 본 적이 없다
    assert trials.views_of(rows, "2026-03-24", "2026-03-31") == 5
    assert trials.views_of(rows, "2026-04-05", "2026-04-06") == 8
    assert trials.views_of([], "2026-03-24", "2026-03-31") == 0


# ── 기록하지 못할 때 ──────────────────────────────────────────────────────────────────
def test_when_the_store_cannot_be_reached_nothing_is_made_up(db, monkeypatch):
    def broken():
        raise RuntimeError("db down")
    monkeypatch.setattr(trials, "_engine", broken)
    assert rec() is None                                          # 기록 실패는 '새 시행 하나'가 아니다
    assert fam() is None                                          # 빈 가족(N=0)도 아니다 — 모른다
    assert trials.mark_oos("alice", "k", "2026-03-24", "2026-03-31") is None
    assert trials.REASONS["store_unavailable"]


def test_a_row_whose_flow_cannot_be_read_still_counts_but_carries_no_flow(db):
    key = rec()["trial_key"]
    with dbmod.get_engine().begin() as c:
        c.execute(text("UPDATE intraday_trials SET daily = :d WHERE trial_key = :k"), {"d": "{not json", "k": key})
    found = fam()
    assert len(found["trials"]) == 1 and found["trials"][0]["daily"] is None


def test_each_database_gets_its_own_table(db, monkeypatch):
    rec()
    other = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    other.close()
    monkeypatch.setattr(dbmod, "DATABASE_URL", f"sqlite:///{other.name}", raising=False)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{other.name}")
    dbmod.reset_session()
    try:
        assert fam() == {"trials": [], "user_total": 0}           # 새 DB 에 표가 없어 실패(None)하면 안 된다
        assert rec()["new"] is True
    finally:
        dbmod.reset_session()
        os.unlink(other.name)


# ── 보존 분류 ─────────────────────────────────────────────────────────────────────────
def test_the_table_is_classified_as_a_decision_record_and_has_no_delete_path():
    assert "intraday_trials" in retention.DECISION_RECORD
    assert "N" in retention.DECISION_RECORD["intraday_trials"]
    source = open(trials.__file__, encoding="utf-8").read()
    assert "DELETE" not in source.upper().replace("ON DELETE", "")           # 지우면 N 이 줄어든다 — 지우는 길을 두지 않는다


# ── 결과 요약 (캔버스 노드 설계 §6) ────────────────────────────────────────────────────────
RESULT = {"summary": {"trades": 10, "gross_total": 19_800.0, "net_total": -3_194.73}, "origin": {"grade": "E3"},
          "gates": {"counts": {"ok": 2, "degraded": 1, "unknown": 4}}}


def test_a_result_is_kept_on_my_trial_and_read_back_as_it_was(db):
    key = rec()["trial_key"]
    assert trials.keep_result("alice", key, RESULT) is True
    found = trials.result_of("alice", key)
    assert found["found"] is True and found["result"] == RESULT and found["runs"] == 1
    assert found["result_at"] > 0 and found["grade"] == "E3"
    assert (found["tickers"], found["from"], found["to"]) == (["000660", "005930"], "2026-03-02", "2026-03-31")


def test_a_trial_without_a_kept_result_reads_as_not_found(db):
    """시행만 있고 결과 요약이 없으면(화면에서 돌린 것) '없음'이다 — 빈 결과를 지어내지 않는다."""
    key = rec()["trial_key"]
    assert trials.result_of("alice", key) == {"found": False}
    assert trials.results_of("alice") == []


def test_someone_elses_trial_reads_exactly_like_a_missing_one(db):
    key = rec("alice")["trial_key"]
    trials.keep_result("alice", key, RESULT)
    assert trials.result_of("bob", key) == trials.result_of("bob", "0" * 64) == {"found": False}
    assert trials.results_of("bob") == []
    assert trials.result_of("alice", key)["found"] is True                       # 짝 — 본인은 읽는다


def test_i_cannot_keep_a_result_on_someone_elses_trial(db):
    key = rec("alice")["trial_key"]
    assert trials.keep_result("bob", key, {"summary": "남의 것"}) is False
    assert trials.result_of("alice", key) == {"found": False}                   # 덮어쓰이지 않았다


def test_running_the_same_trial_again_replaces_the_result_and_keeps_one_row(db):
    key = rec()["trial_key"]
    trials.keep_result("alice", key, RESULT)
    assert rec()["trial_key"] == key
    trials.keep_result("alice", key, {**RESULT, "summary": {"trades": 11}})
    found = trials.result_of("alice", key)
    assert found["result"]["summary"] == {"trades": 11} and found["runs"] == 2
    assert len(trials.results_of("alice")) == 1


def test_my_results_are_listed_newest_first_with_what_a_picker_needs(db, monkeypatch):
    from types import SimpleNamespace
    clock = iter([100.0, 200.0, 300.0, 400.0])
    monkeypatch.setattr(trials, "time", SimpleNamespace(time=lambda: next(clock)))      # 이 모듈의 시계만 — 전역 time 은 그대로
    old = rec()["trial_key"]
    new = rec(setting=changed("rule.minutes", 31))["trial_key"]
    trials.keep_result("alice", old, RESULT)                                    # 300
    trials.keep_result("alice", new, RESULT)                                    # 400
    rows = trials.results_of("alice")
    assert [r["trial_key"] for r in rows] == [new, old]
    assert rows[0]["setting"]["rule"] == {"kind": "opening_range_breakout", "params": {"minutes": 31}}
    assert rows[0]["tickers"] == ["000660", "005930"] and rows[0]["grade"] == "E3" and rows[0]["result_at"] == 400.0
    assert "result" not in rows[0]                                              # 목록은 요약을 싣지 않는다
    assert [r["trial_key"] for r in trials.results_of("alice", limit=1)] == [new]


def test_keeping_a_result_never_changes_what_the_family_counts(db):
    """결과 요약은 N 을 세는 길에 닿지 않는다 — 남겨도 가족과 시행 수는 그대로다."""
    key = rec()["trial_key"]
    rec(setting=changed("rule.minutes", 31))
    before = fam()
    trials.keep_result("alice", key, RESULT)
    assert fam() == before


def test_a_store_that_cannot_be_reached_is_unknown_not_empty(db, monkeypatch):
    key = rec()["trial_key"]
    trials.keep_result("alice", key, RESULT)

    def broken():
        raise RuntimeError("db down")

    monkeypatch.setattr(trials, "_engine", broken)
    assert trials.keep_result("alice", key, RESULT) is None                     # 못 남김 ≠ 내 것이 아님(False)
    assert trials.result_of("alice", key) is None                               # 못 읽음 ≠ 없음({"found": False})
    assert trials.results_of("alice") is None                                   # 못 읽음 ≠ 빈 목록([])


def test_a_table_made_before_the_result_columns_gets_them_without_losing_rows(db):
    """W4d 에서 만든 표(결과 열 없음)를 가진 DB — 열을 덧붙이고, 있던 시행은 그대로다."""
    engine = dbmod.get_engine()
    with engine.begin() as c:
        c.execute(text(
            "CREATE TABLE intraday_trials (trial_key VARCHAR(64) PRIMARY KEY, username VARCHAR(60), grade VARCHAR(10), "
            "setting_digest VARCHAR(64), setting TEXT, tickers TEXT, period_from VARCHAR(10), period_to VARCHAR(10), "
            "daily TEXT, runs INTEGER, oos_views INTEGER, oos_from VARCHAR(10), oos_to VARCHAR(10), "
            "created_at DOUBLE PRECISION, updated_at DOUBLE PRECISION)"))
    trials._ready_for = None
    key = rec()["trial_key"]
    assert trials.keep_result("alice", key, RESULT) is True
    assert trials.result_of("alice", key)["result"] == RESULT
    assert fam()["user_total"] == 1


def test_without_the_result_columns_trials_still_count_and_results_are_unknown(db, monkeypatch):
    """열을 붙이지 못한 DB — ★시행 세기는 그대로 돌고★ 결과 기능만 '모른다'가 된다."""
    import src.data.schema_add_columns as adder
    monkeypatch.setattr(adder, "add_columns", lambda *a, **k: False)
    trials._ready_for = None
    made = rec()
    assert made["new"] is True and fam()["user_total"] == 1
    assert trials.keep_result("alice", made["trial_key"], RESULT) is None
    assert trials.result_of("alice", made["trial_key"]) is None
    assert trials.results_of("alice") is None


def test_the_helpers_answer_is_what_decides_not_whether_the_columns_happen_to_exist(db, monkeypatch):
    """열을 덧붙이는 도우미가 '쓸 수 없다'고 답하면 결과 기능은 '모른다'다 — 열이 마침 있더라도 그 답을 따른다
    (도우미의 계약: 거짓이면 부르는 쪽은 그 열 없이 돈다). 짝은 위의 '열을 덧붙인다' 시험이다."""
    import src.data.schema_add_columns as adder
    key = rec()["trial_key"]                                                    # 열이 붙은 표가 생긴다
    assert trials.keep_result("alice", key, RESULT) is True
    monkeypatch.setattr(adder, "add_columns", lambda *a, **k: False)
    trials._ready_for = None                                                    # 다시 준비 — 이번에는 도우미가 거짓을 답한다
    assert trials.keep_result("alice", key, RESULT) is None
    assert trials.result_of("alice", key) is None and trials.results_of("alice") is None
    assert fam()["user_total"] == 1                                             # 시행 세기는 그대로 돈다
