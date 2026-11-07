"""AT2 · ★링은 카운터와 같은 수명을 산다★
==============================================================================
대상: `kis_client.CircuitBreaker`

## 왜 여기인가

구성은 기존 기록으로 재구성할 수 없다(실측): `record_failure()` 는 인자를 받지
않고, 감사 로그는 `_request` 의 7개 호출부 중 주문·취소 둘만 본다 —
`get_balance` 실패 5회로 breaker 가 열려도 감사 로그는 아무것도 모른다.

그래서 ★숫자와 같은 객체에 기록한다★. breaker 자체가 프로세스 로컬 메모리
상태이고(CLAUDE.md 가 `uvicorn --workers 1` 을 박은 이유가 그것이다), 구성이
그 숫자를 설명하려면 **같은 수명**을 살아야 한다.

## ★이 파일의 핵심 계약 — 두 자리 모두★

`failure_count` 가 0 이 되는 자리는 **둘**이다:

    record_success()            → 성공했으니 연속이 끊겼다
    call_allowed() 의 HALF_OPEN → 시간이 지나 다시 열어 본다

★둘 중 하나만 비우면 구성이 **다른 집합**을 설명하게 된다★ — 그래서 각각을
따로 잰다. 이것이 변이 a·b 다.

## ★이 파일이 재지 않는 것★

- **세는 것을 바꿨는지 재지 않는다** — 바뀌지 않았기 때문이다. 임계값도,
  어떤 종류가 카운트되는지도 그대로다(그쪽 가드는 `test_kis_failure*.py`).
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from src.domain.kis_failure import (
    KIND_BUSINESS,
    KIND_TRANSPORT,
    KIND_UNKNOWN,
)
from src.execution.kis_client import STREAK_RING, CircuitBreaker

_SRC = pathlib.Path("src/execution/kis_client.py")


@pytest.fixture()
def breaker():
    return CircuitBreaker()


# ── ★종류가 함께 남는다★ ───────────────────────────────────────────────

def test_a_recorded_failure_keeps_its_kind(breaker):
    breaker.record_failure(KIND_BUSINESS)
    breaker.record_failure(KIND_TRANSPORT)
    assert breaker.streak_kinds() == (KIND_BUSINESS, KIND_TRANSPORT)


def test_the_ring_and_the_counter_move_together(breaker):
    for _ in range(3):
        breaker.record_failure(KIND_BUSINESS)
    assert breaker.failure_count == len(breaker.streak_kinds()) == 3


def test_a_failure_without_a_kind_is_unknown_not_invented(breaker):
    """변이 d — ★미상을 관측으로 바꾸지 않는다★

    기존 호출부가 인자 없이 부를 수 있어야 하므로 기본값이 필요한데, 그
    기본값이 `business` 나 `transport` 이면 **상수가 관측 행세를 한다**.
    """
    breaker.record_failure()
    assert breaker.streak_kinds() == (KIND_UNKNOWN,)


@pytest.mark.parametrize("bad", ["망가짐", "", None, 7])
def test_a_kind_outside_the_vocabulary_is_stored_as_unknown(breaker, bad):
    breaker.record_failure(bad)
    assert breaker.streak_kinds() == (KIND_UNKNOWN,)


def test_recording_a_kind_does_not_change_what_is_counted(breaker):
    """★세는 것은 0줄 바뀌었다★ — 라벨을 붙였을 뿐이다."""
    for _ in range(5):
        breaker.record_failure(KIND_BUSINESS)
    assert breaker.failure_count == 5
    assert breaker.state == "OPEN"           # 임계도 전이도 그대로


# ── ★리셋 — 두 자리 모두★ ─────────────────────────────────────────────

def test_success_clears_the_ring_with_the_counter(breaker):
    """변이 a — `record_success` 가 링을 안 비우면 죽는다."""
    breaker.record_failure(KIND_BUSINESS)
    breaker.record_failure(KIND_TRANSPORT)
    breaker.record_success()
    assert breaker.failure_count == 0
    assert breaker.streak_kinds() == ()


def test_the_half_open_transition_clears_the_ring_with_the_counter(breaker):
    """변이 b — ★두 자리 중 하나만 비우면 죽는다★

    `call_allowed()` 는 시간이 지나면 `failure_count` 를 0 으로 되돌리고
    `HALF_OPEN` 으로 간다(AQ 가 이 자리를 라벨로 막았다). 링이 따라가지
    않으면 ★0회를 5개의 종류가 설명하는★ 상태가 된다.
    """
    from datetime import datetime, timedelta

    for _ in range(5):
        breaker.record_failure(KIND_BUSINESS)
    assert breaker.state == "OPEN"
    breaker.last_failure_time = datetime.now() - timedelta(seconds=120)

    assert breaker.call_allowed() is True
    assert breaker.state == "HALF_OPEN"
    assert breaker.failure_count == 0
    assert breaker.streak_kinds() == ()


def test_a_blocked_call_does_not_clear_the_ring(breaker):
    """★짝★ — 아직 차단 중이면 구성은 그대로여야 한다(그때가 가장 필요하다)."""
    for _ in range(5):
        breaker.record_failure(KIND_BUSINESS)
    assert breaker.call_allowed() is False
    assert len(breaker.streak_kinds()) == 5


# ── ★링은 경계가 있다★ ────────────────────────────────────────────────

def test_the_ring_is_bounded(breaker):
    """변이 j — 무제한이면 메모리가 새고, 넘침을 감지할 수도 없다."""
    for _ in range(STREAK_RING + 25):
        breaker.record_failure(KIND_BUSINESS)
    assert len(breaker.streak_kinds()) == STREAK_RING


def test_the_bound_is_at_least_the_threshold(breaker):
    """★임계만큼은 담아야 그 발동을 설명할 수 있다★"""
    assert STREAK_RING >= breaker.failure_threshold


def test_an_overflowed_ring_is_visible_as_a_mismatch(breaker):
    """넘치면 ★구성이 그 숫자를 설명하지 않는다★ 고 말할 수 있어야 한다."""
    from src.domain.failure_streak import streak_composition

    for _ in range(STREAK_RING + 3):
        breaker.record_failure(KIND_BUSINESS)
    c = streak_composition(breaker.streak_kinds(), count=breaker.failure_count)
    assert c["describes_count"] is False


# ── ★각 breaker 는 자기 링을 갖는다★ ──────────────────────────────────

def test_two_breakers_do_not_share_a_ring():
    """★가변 기본값 함정★ — 공유되면 한 클라이언트의 실패가 다른 쪽에 보인다."""
    a, b = CircuitBreaker(), CircuitBreaker()
    a.record_failure(KIND_BUSINESS)
    assert b.streak_kinds() == ()


def test_the_reader_returns_a_snapshot_not_the_live_ring(breaker):
    """돌려준 것을 밖에서 바꿔도 안이 흔들리지 않는다."""
    breaker.record_failure(KIND_BUSINESS)
    snapshot = breaker.streak_kinds()
    breaker.record_failure(KIND_TRANSPORT)
    assert snapshot == (KIND_BUSINESS,)


# ── ★호출부가 종류를 넘긴다★ ──────────────────────────────────────────

def test_every_record_failure_call_in_request_passes_a_kind():
    """★트립와이어★ — 변이 i(종류를 버린다)가 죽는다.

    AR 이 `record_failure()` 호출 자리를 AST 로 못 박았다. 여기서는 그 자리들이
    **인자를 넘기는지**를 본다 — 안 넘기면 전부 `unknown` 이 되어 구성이
    아무것도 말하지 못하고, 그 사실이 조용히 지나간다.
    """
    tree = ast.parse(_SRC.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_request")
    calls = [n for n in ast.walk(fn)
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute)
             and n.func.attr == "record_failure"]
    assert calls, "_request 안에 record_failure 호출이 없다 — 스캐너가 깨졌다"
    for call in calls:
        assert call.args or call.keywords, (
            "record_failure 가 종류 없이 불린다 — 구성이 전부 unknown 이 된다")
