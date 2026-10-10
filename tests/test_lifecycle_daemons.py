"""BE · ★기동할 때마다 끝나지 않는 데몬이 하나씩 늘었다★
==============================================================================
대상: `src/startup/lifecycle.py`(`_start_daemon_once`·`LIFECYCLE_DAEMONS`) ·
`tests/conftest.py`

## 실측 (2026-09-24)

`with TestClient(create_app())` 를 쓰는 테스트 파일이 15개다. 매번 `run_startup`
이 **끝나지 않는** 주기 데몬(`_orphan_sweep_bg`·`_risk_monitor_bg`)을 새로 띄웠고,
그 15개만 돌린 뒤 살아 있는 스레드가 ★각각 218개 — 436개★ 였다.

★재현했다★ — 짧은 주기의 스윕 스레드 20개를 곁에 둔 채
`test_execution_assumption_wiring.py` 를 돌리면 **5회 중 5회** 저장 테스트가
실패하고 SQLite `execute` 안에서 **SIGSEGV(139)** 로 죽는다. 스윕 스레드가 없으면
3회 중 3회 통과. 그 테스트는 `backtest_runs._engine` 을 **단일 연결**(`StaticPool`,
`check_same_thread=False`) 인메모리 DB 로 바꾸는데, 모듈 전역을 바꾸므로 누수된
데몬도 **같은 연결**을 다른 스레드에서 쓴다. AQ·AW 의 간헐 실패와 BA·BB 의
SIGSEGV 가 이 모양이었다.

## 고친 것 — 둘은 다른 결함이다

1. ★한 프로세스에 이름당 하나★ — 기동 이벤트가 두 번 오면 운영에서도 중복됐다.
2. ★명시 스위치★ `LIFECYCLE_DAEMONS` — **정확히 `"0"`** 일 때만 끈다(mock 게이트와
   같은 규율). 끄면 ★로그로 말한다★. pytest 를 감지하는 암묵 판정은 쓰지 않는다.
"""
from __future__ import annotations

import logging
import threading

import pytest

from src.startup import lifecycle


@pytest.fixture
def fresh(monkeypatch):
    """등록부를 비우고, 테스트가 띄운 가짜 데몬은 끝에 멈춘다."""
    monkeypatch.setattr(lifecycle, "_DAEMONS", {})
    stop = threading.Event()

    def _target():
        stop.wait(5)

    yield _target
    stop.set()


def _alive(name: str) -> int:
    return sum(1 for t in threading.enumerate()
               if t.name == f"lifecycle:{name}" and t.is_alive())


# ── ★한 프로세스에 이름당 하나★ ──────────────────────────────────────

def test_starting_twice_runs_one_thread(fresh, monkeypatch):
    """변이 — 등록부를 지우면 기동 두 번에 스레드 둘이 된다."""
    monkeypatch.delenv("LIFECYCLE_DAEMONS", raising=False)
    assert lifecycle._start_daemon_once("probe_a", fresh) == "started"
    assert lifecycle._start_daemon_once("probe_a", fresh) == "already_running"
    assert _alive("probe_a") == 1


def test_different_names_each_get_their_thread(fresh, monkeypatch):
    """★짝★ — 항상 "이미 있음" 을 내는 구현을 배제한다."""
    monkeypatch.delenv("LIFECYCLE_DAEMONS", raising=False)
    assert lifecycle._start_daemon_once("probe_b", fresh) == "started"
    assert lifecycle._start_daemon_once("probe_c", fresh) == "started"
    assert _alive("probe_b") == 1 and _alive("probe_c") == 1


def test_a_dead_daemon_can_be_started_again(fresh, monkeypatch):
    """죽은 데몬 자리를 영원히 막지 않는다 — 살아 있을 때만 "이미 있음"."""
    monkeypatch.delenv("LIFECYCLE_DAEMONS", raising=False)
    assert lifecycle._start_daemon_once("probe_d", lambda: None) == "started"
    lifecycle._DAEMONS["probe_d"].join(2)
    assert lifecycle._start_daemon_once("probe_d", fresh) == "started"


# ── ★명시 스위치 — 정확히 "0" 만 끈다★ ───────────────────────────────

def test_zero_disables_and_says_so(fresh, monkeypatch, caplog):
    monkeypatch.setenv("LIFECYCLE_DAEMONS", "0")
    with caplog.at_level(logging.WARNING):
        assert lifecycle._start_daemon_once("probe_e", fresh) == "disabled"
    assert _alive("probe_e") == 0
    assert "LIFECYCLE_DAEMONS" in caplog.text and "probe_e" in caplog.text


@pytest.mark.parametrize("value", ["1", "", "false", "no", "00", " 0"])
def test_anything_but_exactly_zero_keeps_them_on(fresh, monkeypatch, value):
    """★짝★ — 운영 기본을 조용히 끄지 않는다(mock 게이트 규율: 정확히 한 값)."""
    monkeypatch.setenv("LIFECYCLE_DAEMONS", value)
    name = f"probe_f{abs(hash(value)) % 10_000}"
    assert lifecycle._start_daemon_once(name, fresh) == "started"
    assert _alive(name) == 1


def test_unset_keeps_them_on(fresh, monkeypatch):
    monkeypatch.delenv("LIFECYCLE_DAEMONS", raising=False)
    assert lifecycle._start_daemon_once("probe_g", fresh) == "started"


def test_the_test_suite_runs_with_daemons_off():
    """★conftest 가 켜 둔 값★ — 이 줄이 빠지면 누수가 돌아온다."""
    import os
    assert os.environ.get("LIFECYCLE_DAEMONS") == "0"


# ── ★기동 시퀀스가 실제로 이 길을 탄다★ ──────────────────────────────

def test_run_startup_routes_every_periodic_daemon_through_the_registry(monkeypatch):
    """★소스 문자열이 아니라 동작★ — 기동하면 두 상시 데몬을 등록부로 띄운다."""
    import asyncio

    seen: list[str] = []
    monkeypatch.setattr(lifecycle, "_start_daemon_once",
                        lambda name, target: seen.append(name) or "started")
    asyncio.run(lifecycle.run_startup())
    assert {"orphan_sweep", "risk_monitor"} <= set(seen), seen


def test_no_periodic_loop_is_started_with_a_bare_thread():
    """★맨 스레드로 띄우는 주기 루프가 없다★ — 등록부를 건너뛰면 다시 샌다.

    AST 로 본다: `threading.Thread(target=X)` 의 X 가 `while True` 루프 함수면 위반.
    """
    import ast
    import pathlib

    tree = ast.parse(pathlib.Path("src/startup/lifecycle.py").read_text(encoding="utf-8"))
    loops = {f.name for f in tree.body if isinstance(f, ast.FunctionDef)
             and any(isinstance(n, ast.While) and isinstance(n.test, ast.Constant)
                     and n.test.value is True for n in ast.walk(f))}
    assert {"_orphan_sweep_bg", "_risk_monitor_bg"} <= loops   # 공허 방지
    bare = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "Thread":
            for kw in n.keywords:
                if kw.arg == "target" and getattr(kw.value, "id", None) in loops:
                    bare.append(kw.value.id)
    assert bare == [], bare
