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


def test_the_screener_fields_stay_unknown_with_the_merge_reason(monkeypatch):
    """★157개(73%)가 여기 걸린다★ — 사유가 구체적 결함을 가리킨다."""
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    fields = [s for s in collect_signals().signals
              if s.kind == KIND_SCREENER_FIELD]
    assert fields
    for s in fields:
        assert s.evidence_grade is None
        assert "filter_ast" in s.evidence_grade_reason


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
