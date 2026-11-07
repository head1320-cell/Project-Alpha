"""AI1 — 관측된 에쿼티의 **출처** (순수 계층).

## ★두 축을 섞지 않는다★

    실행 모드(SHADOW/PAPER/LIVE)  ⟂  잔고 출처(브로커 조회 / mock 합성)

`live_daily_pnl` 에는 `execution_mode` 칸만 있었다. 그런데 SHADOW 로 돌면서 실제
잔고를 읽을 수도, PAPER 로 돌면서 mock 을 읽을 수도 있다 — 모드만 보면 그 수치가
시장에서 온 것인지 지어낸 것인지 **알 수 없다**.

## ★왜 이것이 안전 문제인가★

`MockKISClient.get_balance()` 는 `self.cash` 와 mock 가격으로 만든 **완전 합성**
값이다(`kis_client.py:804`). 그것이 드로다운 계열에 들어가면 킬스위치의
`auto_dd`·`auto_cb` 가 **합성 숫자로 발동**한다 — CLAUDE.md §6 의
*"운영에서는 합성값을 만들지 않습니다"* 를 가장 위험한 자리에서 어기는 것이다.
"""
from __future__ import annotations

import ast
import dataclasses
import pathlib

import pytest

from src.domain.equity_observation import (
    EQUITY_SOURCES,
    SOURCE_BROKER,
    SOURCE_MOCK,
    SOURCE_UNKNOWN,
    EquityObservation,
    observation_label,
    usable_for_drawdown,
)

_MODULE = (pathlib.Path(__file__).resolve().parents[1]
           / "src" / "domain" / "equity_observation.py")


def _obs(source, **kw) -> EquityObservation:
    base = dict(trade_date="2026-09-14", execution_mode="SHADOW",
                starting_krw=100.0, ending_krw=90.0)
    base.update(kw)
    return EquityObservation(source=source, **base)


# ── ★핵심★ 브로커 조회만 드로다운 계열에 들어간다 ────────────────────────

def test_a_broker_observation_is_usable():
    assert usable_for_drawdown(SOURCE_BROKER) is True


def test_a_mock_observation_is_not_usable():
    """★합성으로 킬스위치를 발동시키지 않는다★"""
    assert usable_for_drawdown(SOURCE_MOCK) is False


def test_an_unknown_source_is_not_usable():
    """★미상은 통과가 아니다★ — 출처를 못 밝혔으면 계열에 못 넣는다."""
    assert usable_for_drawdown(SOURCE_UNKNOWN) is False


def test_a_missing_source_is_not_usable():
    assert usable_for_drawdown(None) is False


@pytest.mark.parametrize("junk", ["", "BROKER", "broker ", "real", 1, [], {}])
def test_an_unrecognised_source_is_not_usable(junk):
    """★모르는 값을 브로커로 접지 않는다★ — 대소문자·공백도 관대하게 보지 않는다."""
    assert usable_for_drawdown(junk) is False


def test_usable_is_not_constant():
    """★짝★ 언제나 참/거짓인 구현을 배제한다."""
    assert {usable_for_drawdown(s) for s in (SOURCE_BROKER, SOURCE_MOCK)} == {True, False}


# ── 라벨 ──────────────────────────────────────────────────────────────────

def test_the_label_carries_the_source_and_the_verdict():
    got = observation_label(_obs(SOURCE_BROKER))
    assert got["source"] == SOURCE_BROKER
    assert got["usable"] is True
    assert got["reason"] is None
    assert got["starting_krw"] == 100.0 and got["ending_krw"] == 90.0
    assert got["execution_mode"] == "SHADOW"


def test_an_unusable_label_always_carries_a_reason():
    """★사유 없는 배제는 금지★ (CLAUDE.md §4)"""
    for source in (SOURCE_MOCK, SOURCE_UNKNOWN, None):
        got = observation_label(_obs(source))
        assert got["usable"] is False
        assert got["reason"], f"{source} 에 사유가 없다"


def test_the_mock_reason_says_it_is_synthetic():
    reason = observation_label(_obs(SOURCE_MOCK))["reason"]
    assert "합성" in reason


def test_the_unknown_reason_does_not_claim_it_was_mock():
    """★'못 밝혔다' 와 '합성이었다' 는 다른 사실이다★"""
    reason = observation_label(_obs(SOURCE_UNKNOWN))["reason"]
    assert "합성" not in reason


# ── 기록 가능성 ≠ 사용 가능성 ────────────────────────────────────────────

def test_a_mock_observation_still_carries_its_numbers():
    """★mock 도 **기록은 한다**★ — 안 쓰는 것이 아니라 라벨해서 쓴다.

    기록하지 않으면 "그날 감시가 돌았는데 mock 이었다" 는 사실 자체가 사라진다.
    """
    got = observation_label(_obs(SOURCE_MOCK))
    assert got["starting_krw"] == 100.0 and got["ending_krw"] == 90.0
    assert got["trade_date"] == "2026-09-14"


# ── 타입·순수성 ───────────────────────────────────────────────────────────

def test_the_source_tuple_matches_the_constants():
    assert set(EQUITY_SOURCES) == {SOURCE_BROKER, SOURCE_MOCK, SOURCE_UNKNOWN}
    assert len(set(EQUITY_SOURCES)) == len(EQUITY_SOURCES), "중복된 출처"


def test_the_observation_is_immutable():
    with pytest.raises(dataclasses.FrozenInstanceError):
        _obs(SOURCE_BROKER).source = SOURCE_MOCK  # type: ignore[misc]


def test_an_empty_observation_is_unknown_not_broker():
    got = observation_label(EquityObservation())
    assert got["usable"] is False
    assert got["reason"]


def test_the_domain_module_stays_pure():
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    for name in imported:
        for bad in ("sqlalchemy", "fastapi", "requests", "pandas", "numpy",
                    "src.database", "src.data", "src.engine", "src.execution", "src.api"):
            assert not name.startswith(bad), f"순수 계층이 {name} 을 import 한다"
