"""실행 게이트 — 주문은 승인된 목표 하나에서만 나온다 (R0-T1)
==============================================================================
`ExecutionRoom.tsx:87` 은 `result.weights.optimized` 를 그대로 주문 목표로 보냈다.
타이밍 오버레이로 노출을 줄여도 실행은 그 사실을 몰랐다. 이제 실행은
`tpv_id` 를 받아 **서버가 컴파일한 목표**를 쓰고, 승인되지 않은 목표는 거부한다.

여기 단언은 **정책**이다 — UI 가 무엇을 보내든 서버가 마지막 방어선이다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.data.target_versions import compile_target, save_target

BASE = {"005930": 40.0, "000660": 35.0, "035720": 25.0}
CUR = {"005930": 34.0, "000660": 33.0, "035720": 33.0}


@pytest.fixture(scope="module")
def client():
    from src.app_factory import create_app
    return TestClient(create_app())


def _save(**kw) -> str:
    tpv_id = save_target(compile_target(BASE, **kw))
    assert tpv_id, "이 테스트는 저장소가 동작해야 성립한다"
    return tpv_id


# ── 1. ★오버레이가 실행 목표에 실제로 도달한다★ ──────────────────────────────
def test_execution_target_comes_from_the_compiled_version_not_the_raw_optimizer():
    """이 저장소의 핵심 결함을 막는 단언이다. 노출 60% 오버레이를 건 목표로 계획을
    만들면 주문은 `optimized × 0.6` 을 향해야 하고, 남은 40%는 현금이어야 한다."""
    from src.engine.execution_plan import build_plan

    tv = compile_target(BASE, overlay={"exposure": 0.6, "source": "canary"})
    plan = build_plan(CUR, tv["final_weights"], 1e8)

    tgt = {o["stock_code"]: o["tgt_weight_pct"] for o in plan["orders"]}
    assert tgt["005930"] == pytest.approx(24.0)
    assert sum(tv["final_weights"].values()) == pytest.approx(60.0)
    # 노출을 줄였으니 순매도가 나와야 한다 — 매수만 나오면 오버레이가 무시된 것이다.
    assert plan["summary"]["sell_notional"] > plan["summary"]["buy_notional"]


def test_route_uses_tpv_weights_when_tpv_id_is_given(client):
    tpv_id = _save(overlay={"exposure": 0.6, "source": "canary"})
    r = client.post("/api/v1/allocation/execution-plan",
                    json={"current_weights": CUR, "tpv_id": tpv_id, "portfolio_value": 1e8})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("blocked") is not True, body
    tgt = {o["stock_code"]: o["tgt_weight_pct"] for o in body["plan"]["orders"]}
    assert tgt["005930"] == pytest.approx(24.0)


# ── 2. 승인되지 않은 목표는 실행으로 못 간다 ─────────────────────────────────
def test_research_only_target_is_refused_with_a_reason(client):
    tpv_id = _save(overlay=None, neutralized=True)
    r = client.post("/api/v1/allocation/execution-plan",
                    json={"current_weights": CUR, "tpv_id": tpv_id, "portfolio_value": 1e8})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["blocked"] is True
    assert "중립화" in body["reason"]
    assert "plan" not in body or body.get("plan") is None   # 계획을 만들어 두지 않는다


def test_saving_a_plan_from_a_research_only_target_is_refused_too(client):
    """미리보기만 막고 저장을 열어 두면 게이트가 아니다."""
    tpv_id = _save(overlay=None, neutralized=True)
    r = client.post("/api/v1/allocation/execution-plan/save",
                    json={"current_weights": CUR, "tpv_id": tpv_id,
                          "portfolio_value": 1e8, "name": "should not exist"})
    assert r.status_code == 200, r.text
    assert r.json()["blocked"] is True


def test_unknown_tpv_id_is_reported_not_silently_ignored(client):
    """모르는 목표를 받으면 **원래 요청의 비중으로 조용히 진행하면 안 된다.**"""
    r = client.post("/api/v1/allocation/execution-plan",
                    json={"current_weights": CUR, "tpv_id": "tpv_nope",
                          "target_weights": BASE, "portfolio_value": 1e8})
    body = r.json()
    assert body["blocked"] is True
    assert "찾을 수 없" in body["reason"]


def test_client_weights_that_disagree_with_the_version_are_refused(client):
    """`tpv_id` 를 붙여 놓고 다른 비중을 보내는 것 — 감사 기록과 실제 주문이 갈라진다."""
    tpv_id = _save(overlay={"exposure": 0.6, "source": "canary"})
    r = client.post("/api/v1/allocation/execution-plan",
                    json={"current_weights": CUR, "tpv_id": tpv_id,
                          "target_weights": BASE, "portfolio_value": 1e8})
    body = r.json()
    assert body["blocked"] is True
    assert "일치하지" in body["reason"]


# ── 3. 기존 계약은 깨지 않는다 ───────────────────────────────────────────────
def test_plain_target_weights_still_work_without_a_tpv(client):
    """`tpv_id` 없는 기존 호출은 그대로 동작한다 — 배선 전 화면이 죽지 않아야 한다."""
    r = client.post("/api/v1/allocation/execution-plan",
                    json={"current_weights": CUR, "target_weights": BASE,
                          "portfolio_value": 1e8})
    assert r.status_code == 200, r.text
    assert r.json()["error"] is False


def test_neither_tpv_nor_weights_is_a_clear_error(client):
    r = client.post("/api/v1/allocation/execution-plan",
                    json={"current_weights": CUR, "portfolio_value": 1e8})
    body = r.json()
    assert body["blocked"] is True
    assert "목표" in body["reason"]
