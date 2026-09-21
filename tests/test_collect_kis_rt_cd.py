"""AS5 · 수집기 — ★관측이 코드를 모으고, 뜻은 사람이 적는다★
==============================================================================
대상: `scripts/collect_kis_rt_cd.py`

## ECOS 스크립트와 결정적으로 다른 점

`scripts/verify_ecos_meta.py` 는 API 를 **프로브**해 증거를 만든다. KIS 오류
코드는 일부러 일으킬 수 없다 — 장 종료를 만들 수도, 잔고를 비울 수도 없다.
그래서 이 수집기는 ★이미 일어난 것을 수확한다★: 감사 로그를 읽어 관측을
접고, `--write` 일 때만 증거 파일에 `K1` 로 병합한다.

## ★여기서 지키는 네 가지★

1. `--write` 없이는 파일을 **쓰지 않는다**.
2. 병합이 ★사람이 적은 것을 덮지 않는다★ — `meaning`·`fault`·`grade`·
   `evidence_source` 는 보존하고 `observed` 블록만 갱신한다.
3. `first_seen` 은 ★UPDATE 하지 않는다★ — "언제부터 알았나" 가 사라진다
   (`macro_observation_store` 가 같은 이유로 `retrieved_at` 을 보존한다).
4. 0건이면 `skipped` 라고 말한다. ★"0건 성공" 이라고 말하지 않는다★ —
   그것은 "확인했더니 문제가 없었다" 로 읽히고, 실제로는 아무것도 확인하지
   않았다.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

_SCRIPT = pathlib.Path("scripts/collect_kis_rt_cd.py")


def _run(*args, env=None):
    import os

    full = dict(os.environ)
    full["KIS_USE_MOCK"] = "1"
    full.update(env or {})
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        capture_output=True, text=True, env=full, timeout=120,
    )
    return proc


@pytest.fixture()
def world(tmp_path):
    """감사 로그가 담긴 DB 와 증거 파일 하나."""
    from sqlalchemy import create_engine, text

    from src.execution.live_schemas import init_live_trading_schema

    db = tmp_path / "live.db"
    engine = create_engine(f"sqlite:///{db}")
    init_live_trading_schema(engine)

    def insert(msg_cd="A", mode="paper", ts="2026-09-02 00:00:00",
               msg1="장 종료", rt_cd="1", kind="business", n=1):
        ctx = {"error": "…", "execution_mode": mode,
               "failure": {"kind": kind, "rt_cd": rt_cd, "msg_cd": msg_cd,
                           "kis_msg": msg1}}
        with engine.begin() as conn:
            for i in range(n):
                conn.execute(text("""
                    INSERT INTO live_audit_trail
                        (audit_id, event_type, event_category, context_json, timestamp)
                    VALUES (:aid, 'ORDER_FAILED', 'EXECUTION', :ctx, :ts)
                """), {"aid": f"{msg_cd}{mode}{ts}{i}",
                       "ctx": json.dumps(ctx, ensure_ascii=False), "ts": ts})

    ev = tmp_path / "ev.json"

    def write_evidence(codes):
        ev.write_text(json.dumps(
            {"schema": 1, "min_grade_to_apply": "K2", "why_empty": "테스트",
             "grades": {"K0": "", "K1": "", "K2": "", "K3": ""},
             "codes": codes}, ensure_ascii=False, indent=2), encoding="utf-8")

    write_evidence({})
    env = {"KIS_RT_CD_EVIDENCE_PATH": str(ev),
           "DATABASE_URL": f"sqlite:///{db}"}
    return insert, ev, write_evidence, env


def _codes(ev):
    return json.loads(ev.read_text(encoding="utf-8"))["codes"]


# ── ★기본은 읽기 전용★ ─────────────────────────────────────────────────

def test_without_write_the_file_is_untouched(world):
    insert, ev, _, env = world
    insert(msg_cd="A")
    before = ev.read_text(encoding="utf-8")
    proc = _run(env=env)
    assert proc.returncode == 0, proc.stderr
    assert ev.read_text(encoding="utf-8") == before


def test_without_write_it_still_reports_what_it_saw(world):
    insert, _, _, env = world
    insert(msg_cd="A", n=3)
    out = json.loads(_run(env=env).stdout)
    assert out["observed"][0]["msg_cd"] == "A"
    assert out["observed"][0]["count"] == 3
    assert out["would_write"] is False


# ── ★0건은 성공이 아니다★ ──────────────────────────────────────────────

def test_no_observations_is_skipped_not_success(world):
    _, _, _, env = world
    out = json.loads(_run(env=env).stdout)
    assert "skipped" in out
    assert out["skipped"]
    assert "observed" not in out or out["observed"] == []


def test_an_unreachable_database_is_skipped_not_success(tmp_path):
    env = {"KIS_RT_CD_EVIDENCE_PATH": str(tmp_path / "ev.json"),
           "DATABASE_URL": "sqlite:///" + str(tmp_path / "없는디렉터리" / "x.db")}
    out = json.loads(_run(env=env).stdout)
    assert "skipped" in out


def test_write_with_nothing_seen_does_not_touch_the_file(world):
    _, ev, _, env = world
    before = ev.read_text(encoding="utf-8")
    _run("--write", env=env)
    assert ev.read_text(encoding="utf-8") == before


# ── ★관측은 K1 로만 들어간다★ ──────────────────────────────────────────

def test_write_records_observations_at_the_observed_grade(world):
    from src.domain.kis_rt_cd import OBSERVED_GRADE

    insert, ev, _, env = world
    insert(msg_cd="A", n=2)
    assert _run("--write", env=env).returncode == 0
    entry = _codes(ev)["1/A"]
    assert entry["grade"] == OBSERVED_GRADE
    assert entry["observed"]["count"] == 2


def test_a_written_observation_does_not_become_a_meaning(world):
    """변이 a — 수집기가 뜻이나 책임 소재를 지어내면 죽는다."""
    insert, ev, _, env = world
    insert(msg_cd="A", n=50)
    _run("--write", env=env)
    entry = _codes(ev)["1/A"]
    assert entry.get("meaning") in (None, "")
    assert entry.get("fault") in (None, "unknown")


def test_a_written_observation_is_still_a_gap(world):
    """★관측해 두었다고 아는 것이 아니다★ — 표의 크기가 늘지 않는다."""
    insert, ev, _, env = world
    insert(msg_cd="A", n=5)
    _run("--write", env=env)
    out = json.loads(_run(env=env).stdout)
    assert out["table"]["size"] == 0
    assert out["gaps"][0]["msg_cd"] == "A"


# ── ★사람이 적은 것을 덮지 않는다★ ────────────────────────────────────

def test_the_merge_preserves_a_curated_entry(world):
    """변이 g — 손으로 얻은 증거를 파괴하면 죽는다."""
    insert, ev, write_evidence, env = world
    write_evidence({"1/A": {"rt_cd": "1", "msg_cd": "A", "meaning": "장 종료",
                            "fault": "self", "grade": "K2",
                            "evidence_source": "KIS 문서 3.2",
                            "probed_at": "2026-09-10"}})
    insert(msg_cd="A", n=7)
    _run("--write", env=env)
    entry = _codes(ev)["1/A"]
    assert entry["meaning"] == "장 종료"
    assert entry["fault"] == "self"
    assert entry["grade"] == "K2"
    assert entry["evidence_source"] == "KIS 문서 3.2"
    assert entry["probed_at"] == "2026-09-10"
    assert entry["observed"]["count"] == 7      # 관측만 갱신됐다


def test_the_merge_preserves_the_first_seen(world):
    """변이 h — "언제부터 알았나" 가 사라지면 죽는다."""
    insert, ev, write_evidence, env = world
    write_evidence({"1/A": {"rt_cd": "1", "msg_cd": "A", "grade": "K1",
                            "observed": {"count": 1,
                                         "first_seen": "2020-01-01T00:00:00",
                                         "last_seen": "2020-01-01T00:00:00"}}})
    insert(msg_cd="A", ts="2026-09-02 00:00:00")
    _run("--write", env=env)
    obs = _codes(ev)["1/A"]["observed"]
    assert obs["first_seen"] == "2020-01-01T00:00:00"
    assert obs["last_seen"].startswith("2026-09-02")


def test_the_merge_does_not_drop_codes_it_did_not_see(world):
    """★이번에 못 본 것이 없어진 것은 아니다★"""
    insert, ev, write_evidence, env = world
    write_evidence({"1/Z": {"rt_cd": "1", "msg_cd": "Z", "meaning": "옛 코드",
                            "fault": "provider", "grade": "K2"}})
    insert(msg_cd="A")
    _run("--write", env=env)
    assert "1/Z" in _codes(ev)
    assert _codes(ev)["1/Z"]["meaning"] == "옛 코드"


def test_the_file_keeps_its_header(world):
    """`why_empty`·`min_grade_to_apply` 를 수집기가 지우지 않는다."""
    insert, ev, _, env = world
    insert(msg_cd="A")
    _run("--write", env=env)
    doc = json.loads(ev.read_text(encoding="utf-8"))
    assert doc["min_grade_to_apply"] == "K2"
    assert doc["why_empty"]
    assert doc["schema"] == 1


# ── ★모드를 섞지 않는다★ ───────────────────────────────────────────────

def test_modes_stay_apart_in_the_report(world):
    insert, _, _, env = world
    insert(msg_cd="A", mode="paper")
    insert(msg_cd="A", mode="live")
    out = json.loads(_run(env=env).stdout)
    modes = {o["execution_mode"] for o in out["observed"]}
    assert modes == {"paper", "live"}


def test_the_written_entry_names_the_modes_it_came_from(world):
    """★한 칸에 접히더라도 어느 모드에서 왔는지 사라지지 않는다★"""
    insert, ev, _, env = world
    insert(msg_cd="A", mode="paper", n=2)
    insert(msg_cd="A", mode="live", n=1)
    _run("--write", env=env)
    obs = _codes(ev)["1/A"]["observed"]
    assert obs["count"] == 3
    assert set(obs["execution_modes"]) == {"paper", "live"}


# ── ★관측 환경을 라벨한다★ ─────────────────────────────────────────────

def test_the_report_says_which_mock_mode_it_ran_under(world):
    insert, _, _, env = world
    insert(msg_cd="A")
    out = json.loads(_run(env=env).stdout)
    assert out["ran_under"]["mock_allowed"] is True


def test_non_business_kinds_never_reach_the_table(world):
    """표는 `rt_cd` 의 표다 — 전송 오류를 코드 표에 넣지 않는다."""
    insert, ev, _, env = world
    insert(msg_cd=None, kind="transport", rt_cd=None)
    out = json.loads(_run(env=env).stdout)
    assert "skipped" in out
    _run("--write", env=env)
    assert _codes(ev) == {}
