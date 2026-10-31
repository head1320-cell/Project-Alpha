"""AE4 — 조립과 표면의 계약.

★조립기는 값을 옮기기만 한다★(AD5 의 리포트와 같은 규율) — 축 점수를 새로
계산하지 않고, 세 축을 가중평균하지 않는다.
"""
from __future__ import annotations

import ast
import pathlib
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.domain.distribution_gate import DISTRIBUTION_BLOCKED
from src.domain.strategy_scorecard import AXIS_EVIDENCE, AXIS_HEALTH, AXIS_LIFECYCLE

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_BUILDER = _ROOT / "src" / "engine" / "scorecard_builder.py"


@pytest.fixture(scope="module")
def client():
    from src.app_factory import create_app
    # ★모듈 스코프에서 `with` 를 쓰지 않는다★ — AD 에서 앱 shutdown 이 공용 워커
    # 풀을 닫아 뒤따르는 테스트를 망가뜨렸다(집 관용구: 컨텍스트 없이 생성).
    return TestClient(create_app())


def _post(client, ids):
    return client.post("/api/v1/strategies/scorecard", json={"alpha_ids": ids})


# ── 없는 알파 ───────────────────────────────────────────────────────────────

def test_an_unknown_alpha_is_reported_not_skipped(client):
    """★조용히 건너뛰지 않는다★ — 빠지면 "그런 알파는 없었다" 로 읽힌다."""
    res = _post(client, ["definitely-not-an-alpha"])
    assert res.status_code == 200
    body = res.json()
    assert len(body["cards"]) == 1
    card = body["cards"][0]
    assert card["available"] is False
    assert card["reason"]
    assert "definitely-not-an-alpha" in body["unavailable"]


def test_one_failing_card_does_not_swallow_the_others(client):
    body = _post(client, ["ghost-1", "ghost-2"]).json()
    assert len(body["cards"]) == 2
    assert all(not c["available"] for c in body["cards"])


def test_the_response_declares_what_the_card_is_and_is_not(client):
    body = _post(client, ["ghost"]).json()
    assert "종합 등급" in body["note"]
    assert "업권" in body["distribution_note"]


# ── 실제 카드 한 장 — ★주변 DB 상태에 기대지 않는다★ ────────────────────
#
# 처음에는 `seed_templates()` 로 등록부를 채우고 없으면 `pytest.skip` 했다.
# ★전체 게이트에서 그 여섯 개가 **전부 조용히 스킵**됐다★ — 앞선 테스트가 DB 를
# 갈아 끼워 등록부가 사라졌기 때문이다. 스킵된 테스트는 증거가 아니므로
# (CLAUDE.md §5), 알파를 **주입**해 결정론적으로 만든다.

_FAKE_ALPHA = {
    "alpha_id": "ae-test-alpha",
    "name": "AE 테스트 알파",
    "status": "experimental",
    "last_run_id": None,
    "notes": "",
}


@pytest.fixture()
def injected(monkeypatch):
    """등록부·검증 리포트를 주입한다 — DB 없이 카드 한 장이 완성된다."""
    import src.data.alpha_registry as registry

    monkeypatch.setattr(
        registry, "get_alpha",
        lambda aid: dict(_FAKE_ALPHA) if aid == _FAKE_ALPHA["alpha_id"] else None)
    return _FAKE_ALPHA["alpha_id"]


def _card_of(alpha_id: str) -> dict:
    from src.engine.scorecard_builder import build_scorecard

    out = build_scorecard(alpha_id, run_getter=lambda rid: None)
    assert out["available"] is True, out["reason"]
    return out["card"]


def test_a_real_card_carries_all_three_axes(injected):
    card = _card_of(injected)
    for axis in (AXIS_LIFECYCLE, AXIS_HEALTH, AXIS_EVIDENCE):
        assert axis in card, f"{axis} 축이 없다"


def test_a_real_card_is_blocked_from_distribution(injected):
    """★이 저장소를 그대로 돌리면 어떤 카드도 유통 가능하지 않다★."""
    card = _card_of(injected)
    assert card["distribution"]["state"] == DISTRIBUTION_BLOCKED
    assert "업권" in card["distribution"]["reason"]


def test_a_real_card_names_what_it_could_not_measure(injected):
    """★못 잰 여섯이 이름으로 실린다★."""
    from src.engine.strategy_health import _UNMEASURED

    card = _card_of(injected)
    keys = {u["key"] for u in card["unmeasured"]}
    assert {k for k, _ in _UNMEASURED} <= keys, f"미측정 신호가 빠졌다: {keys}"
    assert all(u["label"] for u in card["unmeasured"])


def test_an_unvalidated_alpha_has_unknown_evidence(injected):
    """★검증 리포트가 없으면 증거는 `unknown` 이고 통과가 아니다★."""
    evidence = _card_of(injected)[AXIS_EVIDENCE]
    assert evidence["status"] != "ok"
    assert evidence["reason"]


def test_the_card_does_not_claim_an_unapproved_alpha_is_usable(injected):
    """사다리를 통과하지 않은 알파는 포트폴리오 사용 불가 — 사유와 함께."""
    lifecycle = _card_of(injected)[AXIS_LIFECYCLE]
    assert lifecycle["status"] == "experimental"
    assert lifecycle["usable_for_portfolio"] is False
    assert lifecycle["reason"], "막았으면 사유가 있어야 한다"


def test_an_approved_alpha_is_reported_as_usable(injected, monkeypatch):
    """★짝★ — 언제나 사용 불가로 답하는 구현을 배제한다."""
    import src.data.alpha_registry as registry

    monkeypatch.setattr(registry, "get_alpha",
                        lambda aid: {**_FAKE_ALPHA, "status": "approved"})
    lifecycle = _card_of(_FAKE_ALPHA["alpha_id"])[AXIS_LIFECYCLE]
    assert lifecycle["usable_for_portfolio"] is True


def test_the_route_returns_the_same_card_shape(client, injected):
    """HTTP 표면도 같은 모양을 낸다 — 조립기와 라우트가 갈리지 않는다."""
    body = _post(client, [injected]).json()
    card = body["cards"][0]
    assert card["available"] is True, card["reason"]
    for axis in (AXIS_LIFECYCLE, AXIS_HEALTH, AXIS_EVIDENCE):
        assert axis in card["card"]


# ── ★조립기는 계산하지 않는다★ ──────────────────────────────────────────

def test_the_builder_contains_no_arithmetic():
    """★소스 전수★ — 값을 옮기는 모듈에 산술 연산이 생기면 그것이 새 숫자의 입구다."""
    tree = ast.parse(_BUILDER.read_text(encoding="utf-8"))
    ops = [
        type(node.op).__name__ for node in ast.walk(tree)
        if isinstance(node, ast.BinOp)
        and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv))
    ]
    assert not ops, f"조립기에 산술 연산이 있다: {ops}"


def _numeric_leaves(node: Any, out: set[float] | None = None) -> set[float]:
    if out is None:
        out = set()
    if isinstance(node, bool):
        return out
    if isinstance(node, (int, float)):
        out.add(round(float(node), 9))
    elif isinstance(node, dict):
        for v in node.values():
            _numeric_leaves(v, out)
    elif isinstance(node, (list, tuple)):
        for v in node:
            _numeric_leaves(v, out)
    return out


def test_the_card_invents_no_numbers(injected):
    """카드의 수치가 출처(건강도 응답)에 그대로 있는지 — 새 축 점수가 없다."""
    from src.engine.strategy_health import strategy_health

    source = strategy_health(alphas=[dict(_FAKE_ALPHA)], run_getter=lambda rid: None)
    card = _card_of(injected)
    invented = _numeric_leaves(card) - _numeric_leaves(source)
    assert not invented, f"카드가 출처에 없는 수치를 만들었다: {sorted(invented)[:10]}"


def test_the_leaf_detector_actually_detects():
    assert _numeric_leaves({"a": 1, "b": [2.5]}) == {1.0, 2.5}
    assert _numeric_leaves({"flag": True}) == set()


# ── 레지스트리 ──────────────────────────────────────────────────────────────

def test_the_route_is_declared_in_the_protection_registry():
    from src.api.protected_routes import OPEN_WITH_REASON, PROTECTED

    key = ("POST", "/api/v1/strategies/scorecard")
    assert key in PROTECTED or key in OPEN_WITH_REASON
    if key in OPEN_WITH_REASON:
        assert OPEN_WITH_REASON[key].strip(), "사유 없는 면제"
