"""AQ1 — KIS API 건강 관측 어휘. ★세는 코드는 이미 있고, 없는 것은 통로다★

`kis_client.CircuitBreaker` 가 이미 **연속 실패**를 센다(`record_success` 가 0 으로
되돌린다). 그런데 그 값을 그냥 `account_state` 로 옮기면 네 가지가 거짓이 된다:

    ① `MockKISClient` 에는 breaker 가 **없다** — mock 에서 0 을 실으면 합성 관측
    ② `HALF_OPEN` 이 30초 뒤 카운트를 **0 으로 되돌린다** — 장애 중에도 0 이 나온다
    ③ 싱글턴이 아직 없으면 잴 대상이 없다 — 0 이 아니라 미상
    ④ `OPEN`(차단 중)과 "실패 중" 은 다른 사실이다

★짝을 붙인다★ — 모든 "…여야 한다" 에 "…가 아니어야 한다" 를 함께 건다.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from src.domain.api_health import (
    API_SOURCES,
    BREAKER_CLOSED,
    BREAKER_HALF_OPEN,
    BREAKER_OPEN,
    BREAKER_STATES,
    BREAKER_UNKNOWN,
    OBSERVED,
    SOURCE_BROKER,
    SOURCE_MOCK,
    SOURCE_NO_CLIENT,
    SOURCE_UNKNOWN,
    UNOBSERVED,
    api_failure_observation,
    source_reason,
    usable_for_kill_switch,
)

_MODULE = pathlib.Path("src/domain/api_health.py")


# ── 레지스트리 ─────────────────────────────────────────────────────────────

def test_the_sources_and_states_are_registered():
    """★테스트의 테스트★ — 레지스트리를 비우면 아래 전수 검사가 공허해진다."""
    assert API_SOURCES == (SOURCE_BROKER, SOURCE_MOCK, SOURCE_NO_CLIENT,
                           SOURCE_UNKNOWN)
    assert BREAKER_STATES == (BREAKER_CLOSED, BREAKER_OPEN, BREAKER_HALF_OPEN,
                              BREAKER_UNKNOWN)


# ── ★broker 만이 킬스위치 재료가 된다★ ──────────────────────────────────

def test_only_a_broker_source_is_usable():
    assert usable_for_kill_switch(SOURCE_BROKER) is True


@pytest.mark.parametrize("source", [SOURCE_MOCK, SOURCE_NO_CLIENT,
                                    SOURCE_UNKNOWN, None, "BROKER", "broker "])
def test_nothing_else_is_usable(source):
    """★관대하게 보지 않는다★ — AI 의 `usable_for_drawdown` 과 같은 규율."""
    assert usable_for_kill_switch(source) is False


def test_mock_and_unknown_get_different_reasons():
    """★"합성이었다" 와 "못 밝혔다" 는 처방이 다르다★"""
    assert source_reason(SOURCE_BROKER) is None
    reasons = {source_reason(s) for s in (SOURCE_MOCK, SOURCE_NO_CLIENT,
                                          SOURCE_UNKNOWN)}
    assert len(reasons) == 3 and all(reasons)


# ── ① ★mock 의 0 은 관측이 아니다★ ──────────────────────────────────────

def test_a_mock_source_yields_no_count():
    obs = api_failure_observation(count=0, breaker_state=BREAKER_UNKNOWN,
                                  source=SOURCE_MOCK)
    assert obs["count"] is None
    assert obs["state"] == UNOBSERVED
    assert obs["reason"]


def test_a_broker_source_yields_the_count():
    """★짝★ — 언제나 `None` 인 구현을 배제한다."""
    obs = api_failure_observation(count=3, breaker_state=BREAKER_CLOSED,
                                  source=SOURCE_BROKER)
    assert obs["count"] == 3
    assert obs["state"] == OBSERVED
    assert obs["reason"] is None


def test_a_measured_zero_from_a_broker_is_an_observation():
    """★잰 0 은 관측이다★ — 문제는 **안 잰** 0 이다."""
    obs = api_failure_observation(count=0, breaker_state=BREAKER_CLOSED,
                                  source=SOURCE_BROKER)
    assert obs["count"] == 0 and obs["state"] == OBSERVED


# ── ③ 클라이언트가 없으면 미상 ────────────────────────────────────────────

def test_no_client_yields_no_count():
    obs = api_failure_observation(count=None, breaker_state=BREAKER_UNKNOWN,
                                  source=SOURCE_NO_CLIENT)
    assert obs["count"] is None and obs["state"] == UNOBSERVED and obs["reason"]


def test_a_broker_source_without_a_number_is_still_unobserved():
    """출처가 broker 라도 숫자를 못 읽었으면 관측이 아니다."""
    obs = api_failure_observation(count=None, breaker_state=BREAKER_CLOSED,
                                  source=SOURCE_BROKER)
    assert obs["count"] is None and obs["state"] == UNOBSERVED and obs["reason"]


@pytest.mark.parametrize("bad", [True, "3", 2.5, float("nan"), -1])
def test_a_count_that_is_not_a_whole_number_is_rejected(bad):
    """★모양이 다르면 지어내지 않는다★ — 연속 실패 횟수는 음이 아닌 정수다."""
    obs = api_failure_observation(count=bad, breaker_state=BREAKER_CLOSED,
                                  source=SOURCE_BROKER)
    assert obs["count"] is None and obs["state"] == UNOBSERVED


# ── ②·④ ★상태는 카운트가 잃는 것을 들고 있다★ ──────────────────────────

def test_the_breaker_state_travels_with_the_count():
    obs = api_failure_observation(count=0, breaker_state=BREAKER_HALF_OPEN,
                                  source=SOURCE_BROKER)
    assert obs["breaker_state"] == BREAKER_HALF_OPEN
    assert obs["count"] == 0


def test_a_half_open_zero_is_flagged_as_not_healthy():
    """★장애 중에도 0 이 나온다★ — 그 사실이 관측에 남아야 한다."""
    obs = api_failure_observation(count=0, breaker_state=BREAKER_HALF_OPEN,
                                  source=SOURCE_BROKER)
    assert obs["recently_tripped"] is True


def test_a_closed_zero_is_not_flagged():
    """★짝★ — 언제나 참인 플래그를 배제한다."""
    obs = api_failure_observation(count=0, breaker_state=BREAKER_CLOSED,
                                  source=SOURCE_BROKER)
    assert obs["recently_tripped"] is False


def test_blocking_is_the_open_state_not_the_count():
    """★차단 중 ≠ 실패 중★ — `OPEN` 이면 카운트와 무관하게 호출이 막힌다."""
    blocked = api_failure_observation(count=0, breaker_state=BREAKER_OPEN,
                                      source=SOURCE_BROKER)
    assert blocked["blocking"] is True
    busy = api_failure_observation(count=4, breaker_state=BREAKER_CLOSED,
                                   source=SOURCE_BROKER)
    assert busy["blocking"] is False


def test_blocking_is_unknown_when_the_state_is_unknown():
    obs = api_failure_observation(count=None, breaker_state=BREAKER_UNKNOWN,
                                  source=SOURCE_NO_CLIENT)
    assert obs["blocking"] is None


def test_an_unregistered_breaker_state_is_not_taken_at_face_value():
    """★모르는 값을 낙관하지 않는다★"""
    obs = api_failure_observation(count=1, breaker_state="정상",
                                  source=SOURCE_BROKER)
    assert obs["breaker_state"] == BREAKER_UNKNOWN


def test_an_unregistered_source_becomes_unknown():
    obs = api_failure_observation(count=1, breaker_state=BREAKER_CLOSED,
                                  source="실서버")
    assert obs["source"] == SOURCE_UNKNOWN
    assert obs["count"] is None


# ── 응답으로 나가는 문장 ───────────────────────────────────────────────────

def test_the_note_warns_that_zero_is_not_health():
    obs = api_failure_observation(count=0, breaker_state=BREAKER_CLOSED,
                                  source=SOURCE_BROKER)
    assert obs["note"] and "0" in obs["note"]


def test_no_response_string_carries_markdown():
    """★평문 응답 규율★ — `**` 가 화면에 그대로 보인다(AB 가 세운 규칙)."""
    obs = api_failure_observation(count=0, breaker_state=BREAKER_HALF_OPEN,
                                  source=SOURCE_MOCK)
    texts = [obs["note"], obs["reason"] or ""]
    assert not any("**" in t for t in texts), texts


# ── 계층 경계 ──────────────────────────────────────────────────────────────

def test_the_module_touches_neither_storage_nor_network_nor_the_client():
    """★`src/domain/` 은 순수하다★ — 특히 `kis_client` 를 알지 못한다."""
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
    assert not (imported & {"sqlalchemy", "requests", "httpx", "src"}), imported


# ── ★프런트 타입과 응답이 어긋나면 화면이 조용히 빈다★ (AQ4) ────────────

OBSERVATION_KEYS = {"count", "state", "source", "breaker_state", "blocking",
                    "recently_tripped", "streak", "reason", "note"}

_TYPES_TS = pathlib.Path("frontend/src/entities/kill-switch/types.ts")


def test_the_observation_shape_is_pinned():
    obs = api_failure_observation(count=1, breaker_state=BREAKER_CLOSED,
                                  source=SOURCE_BROKER)
    assert set(obs) == OBSERVATION_KEYS


def test_the_frontend_type_declares_every_observation_key():
    """★타입은 화면이 없어도 계약이다★ — 키가 빠지면 `undefined` 로 샌다."""
    src = _TYPES_TS.read_text(encoding="utf-8")
    block = src.split("export interface ApiFailureObservation {", 1)[1].split("\n}", 1)[0]
    declared = {line.split(":", 1)[0].strip()
                for line in block.splitlines()
                if ":" in line and not line.strip().startswith(("*", "/"))}
    assert OBSERVATION_KEYS <= declared, OBSERVATION_KEYS - declared
