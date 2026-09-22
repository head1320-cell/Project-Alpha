"""AV3 · ★등급이 표면에 닿는다★ — `collect_signals` 와 `GET /signals`
==============================================================================
대상: `src/domain/signal_definition.collect_signals` · `src/api/signal_routes.py`

`GET /signals` 는 `evidence_grade` 칸을 **예전부터 내보내고 있었다** — 다만
아무도 채우지 않아 언제나 `null` 이었다. 이 파일은 그 칸이 실제로 값을 갖고,
★못 정한 신호는 사유와 함께 `null` 로 남는지★를 잰다.

## ★아무도 안 부르는 규칙은 규칙이 아니다★

이 저장소에는 배선만 되고 소비되지 않는 모듈 선례가 여럿 있다
(`exposure_taxonomy` 의 docstring 이 스스로 그렇게 적어 두었고, 그 문장마저
지금은 낡았다). AU 가 같은 이유로 `enriched_label` 을 표면까지 이었다.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.domain.signal_definition import (
    KIND_SCREENER_FIELD,
    KIND_STRATEGY_TOKEN,
    KIND_TIMING_RULE,
    collect_signals,
)
from src.domain.signal_evidence import PROV_E0, PROV_E2


@pytest.fixture()
def client():
    from src.api import signal_routes as routes

    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app)


# ── ★카탈로그가 등급을 달고 나온다★ ──────────────────────────────────

def test_collect_signals_fills_the_grade(monkeypatch):
    """예전에는 이 칸이 언제나 `None` 이었다."""
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    graded = [s for s in collect_signals().signals if s.evidence_grade is not None]
    assert graded, "등급이 붙은 신호가 하나도 없다"


def test_every_signal_carries_a_grade_reason(monkeypatch):
    """★사유 없는 미상은 금지★ — 등급이 있든 없든 왜인지 말한다."""
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    for s in collect_signals().signals:
        assert s.evidence_grade_reason, s.signal_id


def test_most_screener_fields_are_now_graded(monkeypatch):
    """★AW 이후 — 병합이 되살린 출처가 등급이 된다★

    AV 때는 157개 전부가 미상이었다. 이제 선언된 출처가 있는 스토어에서 온
    것은 등급을 받고, ★맨손 리터럴 14개만 미상으로 남는다★.
    """
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    fields = [s for s in collect_signals().signals
              if s.kind == KIND_SCREENER_FIELD]
    assert fields
    graded = [s for s in fields if s.evidence_grade is not None]
    ungraded = [s for s in fields if s.evidence_grade is None]
    assert len(graded) > 100, len(graded)
    # ★짝★ — 전부 등급이 붙으면 지어내고 있는 것이다.
    assert ungraded, "기본 필드까지 등급을 받았다"
    assert all(s.origin == "base_fields_store" for s in ungraded)


def test_the_stale_merge_reason_is_gone(monkeypatch):
    """변이 l — ★거짓이 된 문장이 남아 있으면 죽는다★"""
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    for s in collect_signals().signals:
        assert "버립니다" not in (s.evidence_grade_reason or "")


def test_the_tokens_are_graded_synthetic_under_the_mock_gate(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    tokens = [s for s in collect_signals().signals
              if s.kind == KIND_STRATEGY_TOKEN]
    assert tokens
    assert all(s.evidence_grade == PROV_E0 for s in tokens)


def test_the_same_tokens_are_not_synthetic_outside_the_gate(monkeypatch):
    """★짝★ — 게이트가 실제로 판정을 움직인다."""
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    tokens = [s for s in collect_signals().signals
              if s.kind == KIND_STRATEGY_TOKEN]
    assert tokens
    assert all(s.evidence_grade == PROV_E2 for s in tokens)


def test_the_availability_axis_is_untouched(monkeypatch):
    """★쓸 수 있는가 ⟂ 어디서 왔는가★ — 기존 칸을 덮지 않았다."""
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    timing = [s for s in collect_signals().signals if s.availability is not None]
    assert timing, "availability 를 싣던 신호가 사라졌다"


# ── ★라우트가 낸다★ ─────────────────────────────────────────────────

def test_the_route_emits_grades(client, monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    body = client.get("/api/v1/signals").json()
    grades = {s["evidence_grade"] for s in body["signals"]}
    assert PROV_E0 in grades
    assert None in grades          # ★전부 붙었다면 지어내고 있는 것이다★


def test_the_route_emits_the_reason(client, monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    body = client.get("/api/v1/signals").json()
    assert all(s["evidence_grade_reason"] for s in body["signals"])


def test_the_route_reports_the_gap_rollup(client, monkeypatch):
    """★빈틈 목록이 산출물이다★ — 표면이 그것을 말한다."""
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    body = client.get("/api/v1/signals").json()
    ev = body["evidence"]
    assert ev["n_ungraded"] > 0
    assert ev["complete"] is False
    assert ev["by_grade"][PROV_E0] > 0


def test_the_rollup_counts_the_whole_catalog_not_the_filtered_page(
        client, monkeypatch):
    """★필터는 보기이고 판정은 전체다★ — 걸러서 세면 빈틈이 줄어 보인다."""
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    whole = client.get("/api/v1/signals").json()
    one_kind = client.get(
        f"/api/v1/signals?kind={KIND_STRATEGY_TOKEN}").json()
    assert len(one_kind["signals"]) < len(whole["signals"])
    assert one_kind["evidence"] == whole["evidence"]


# ── ★AX — 타이밍 팩터가 출처를 싣는다★ ──────────────────────────────────

def test_most_timing_rules_are_now_graded(monkeypatch):
    """★AX 이후 — 24개가 `etf_prices` 를 싣는다★

    AV·AW 때는 33개 전부가 미상이었다. 이제 남는 미상은 두 묶음뿐이고
    ★둘 다 서로 다른 사유★를 단다.
    """
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    rules = [s for s in collect_signals().signals
             if s.kind == KIND_TIMING_RULE]
    assert rules
    graded = [s for s in rules if s.evidence_grade is not None]
    ungraded = [s for s in rules if s.evidence_grade is None]
    assert len(graded) >= 20, len(graded)
    # ★짝★ — 전부 등급이 붙으면 지어내고 있는 것이다.
    assert ungraded, "소스 없는 팩터까지 등급을 받았다"
    assert {s.origin for s in ungraded} == {"pit_macro", None}


def test_the_two_ungraded_timing_groups_give_different_reasons(monkeypatch):
    """★같은 미상이라도 이유가 다르면 다르게 말한다★

    "키가 없다" 와 "평가 함수가 아예 없다" 는 처방이 정반대다 — 전자는
    키를 넣으면 되고 후자는 데이터 소스를 구해야 한다.
    """
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    un = [s for s in collect_signals().signals
          if s.kind == KIND_TIMING_RULE and s.evidence_grade is None]
    keyless = {s.evidence_grade_reason for s in un if s.origin == "pit_macro"}
    sourceless = {s.evidence_grade_reason for s in un if s.origin is None}
    assert keyless and sourceless
    assert keyless.isdisjoint(sourceless)
    assert all("FRED_API_KEY" in r for r in keyless)


def test_the_fred_key_moves_the_rollup(monkeypatch):
    """변이 m ★짝★ — 항상-거부가 아니다. 환경이 빈틈을 줄인다."""
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    from src.domain.signal_evidence import grade_catalog
    without = grade_catalog(collect_signals())["n_ungraded"]
    monkeypatch.setenv("FRED_API_KEY", "x" * 8)
    with_key = grade_catalog(collect_signals())["n_ungraded"]
    assert with_key < without, (with_key, without)
    # ★그래도 0 이 되지 않는다★ — 기본 필드와 소스 없는 팩터가 남는다.
    assert with_key > 0
