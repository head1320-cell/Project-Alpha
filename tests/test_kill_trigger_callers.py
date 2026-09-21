"""AP3 — 발동 호출부가 ★관측을 싣는다★ + 전수 트립와이어

실측: `KillSwitch.trigger()` 의 `dd_pct` 를 **넘기는 호출부가 하나도 없었다**.
기본값이 `0` 이었으므로 `live_kill_events.dd_at_trigger` 는 저장소 전체에서
언제나 `0` 이었다 — ★드로다운 때문에 발동한 사건의 드로다운이 `0`★ 이다.
AM 의 `"dev"`(701행이 전부 같은 값)와 같은 모양이다.

기본값을 `None` 으로 바꾸는 것(AP2)만으로는 **다음 사람**을 막지 못한다. 새 호출부가
생기면 또 안 싣는다. 그래서 AA2 의 관용구대로 **AST 로 전수**를 건다.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from src.execution.risk_monitor import (
    DD_AXIS_BY_SOURCE,
    VERDICT_WOULD_TRIGGER,
    dd_for_source,
    run_once,
)

_SRC = pathlib.Path("src")


# ── ★발동을 일으킨 드로다운을 싣는다 — 두 축을 섞지 않고★ ────────────────

def _state(cum=0.20, intra=0.07):
    return {"equity_krw": None, "cumulative_dd_pct": cum,
            "current_drawdown_pct": intra, "drawdown_reason": None,
            "api_failure_count": 0}


def test_the_cumulative_trigger_carries_the_cumulative_drawdown():
    assert dd_for_source("auto_dd", _state()) == pytest.approx(0.20)


def test_the_intraday_trigger_carries_the_intraday_drawdown():
    """★짝★ — 두 축을 바꿔 싣는 구현을 배제한다."""
    assert dd_for_source("auto_cb", _state()) == pytest.approx(0.07)


@pytest.mark.parametrize("source", ["auto_risk", "auto_api", "manual", None])
def test_a_trigger_that_is_not_about_drawdown_carries_none(source):
    """★어떤 질문에 답한 것인지 밝힌다★ — 드로다운이 원인이 아니면 안 싣는다."""
    assert dd_for_source(source, _state()) is None


def test_the_axis_registry_names_exactly_the_two_drawdown_triggers():
    """★테스트의 테스트★ — 레지스트리를 비우면 위 단언들이 공허해진다."""
    assert DD_AXIS_BY_SOURCE == {"auto_dd": "cumulative_dd_pct",
                                 "auto_cb": "current_drawdown_pct"}


def test_an_unmeasured_drawdown_stays_none():
    assert dd_for_source("auto_dd", {"cumulative_dd_pct": None}) is None


# ── 자동 경로가 실제로 실어 보낸다 ────────────────────────────────────────

class _RecordingSwitch:
    """발동 인자를 그대로 붙잡는 가짜 — ★넘긴 것만 기록된다★"""

    def __init__(self):
        self.calls: list[dict] = []

    def unverified_checks(self, account_state, regime_state=None):
        return []

    def should_auto_trigger(self, account_state, regime_state=None):
        return ("auto_dd", "누적 drawdown 한도 초과")

    def trigger(self, **kw):
        self.calls.append(kw)
        return {"event_id": "TEST"}


class _NullAudit:
    def log(self, **kw):
        return None


def _fire(monkeypatch, source_hit=("auto_dd", "사유")):
    monkeypatch.setenv("RISK_MONITOR_AUTOTRIGGER", "1")
    ks = _RecordingSwitch()
    ks.should_auto_trigger = lambda a, r=None: source_hit          # type: ignore[method-assign]
    v = run_once(kill_switch=ks, audit=_NullAudit(), account_state=_state(),
                 regime_state={"regime": "BEAR", "stress_score": 91.0}, last=None)
    assert v.verdict == VERDICT_WOULD_TRIGGER
    return ks.calls[0]


def test_the_automatic_path_carries_the_drawdown_that_fired_it(monkeypatch):
    call = _fire(monkeypatch)
    assert call["dd_pct"] == pytest.approx(0.20)


def test_the_intraday_automatic_path_carries_the_other_axis(monkeypatch):
    """★짝★ — 두 경로가 같은 값을 실으면 축이 섞인 것이다."""
    call = _fire(monkeypatch, source_hit=("auto_cb", "일중 손실 한도 초과"))
    assert call["dd_pct"] == pytest.approx(0.07)


def test_the_automatic_path_carries_the_regime_it_saw(monkeypatch):
    assert _fire(monkeypatch)["regime"] == "BEAR"


def test_the_automatic_path_declares_the_equity_it_could_not_read(monkeypatch):
    """★감시는 브로커를 부르지 않는다★(AI 의 경계) — 그 사실을 `None` 으로 싣는다."""
    call = _fire(monkeypatch)
    assert "equity" in call and call["equity"] is None


def test_the_automatic_path_still_passes_no_broker_client(monkeypatch):
    """★동작 0줄★ — 이 프로그램은 취소·청산을 켜지 않는다(사용자 결정)."""
    assert _fire(monkeypatch).get("kis_client") is None


# ── ★전수 트립와이어★ — 새 호출부가 다시 빠뜨리지 못하게 ─────────────────

def _trigger_calls() -> list[tuple[str, int, set[str]]]:
    """`src/` 에서 `KillSwitch.trigger(...)` 호출을 전부 찾는다.

    ★`source=` 키워드로 식별한다★ — 이름이 `trigger` 인 다른 함수와 섞이지
    않도록 구조로 거른다(어휘가 아니라 구조).
    """
    found: list[tuple[str, int, set[str]]] = []
    for path in _SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else (
                fn.id if isinstance(fn, ast.Name) else None)
            if name != "trigger":
                continue
            kws = {k.arg for k in node.keywords if k.arg}
            if "source" not in kws:
                continue
            found.append((str(path), node.lineno, kws))
    return found


def test_every_trigger_call_site_loads_the_observations():
    """★상수가 관측 행세를 하지 못하게★ — 기본값에 기대는 호출부를 금지한다."""
    missing = [(p, ln, sorted({"equity", "dd_pct"} - kws))
               for p, ln, kws in _trigger_calls()
               if not {"equity", "dd_pct"} <= kws]
    assert not missing, f"관측을 싣지 않는 발동 호출부: {missing}"


def test_the_scanner_actually_finds_the_call_sites():
    """★테스트의 테스트★ — 0건이면 위 검사는 언제나 통과한다.

    실측 하한: 수동(`api/stage13_routes.py`) · 대사(`engine/reconciler.py`) ·
    자동(`execution/risk_monitor.py`) 셋이다.
    """
    calls = _trigger_calls()
    assert len(calls) >= 3, f"발동 호출부를 찾지 못했습니다: {calls}"
    files = {pathlib.Path(p).name for p, _, _ in calls}
    assert {"stage13_routes.py", "reconciler.py", "risk_monitor.py"} <= files
