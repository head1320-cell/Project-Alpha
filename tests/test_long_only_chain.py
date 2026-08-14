"""롱온리 증거 사슬 — MES → TPV → executable → 주문 diff (M1-V)
==============================================================================
브리프의 요청 ④("롱온리 파이프라인이 실행 게이트를 통과하는지 검증")가 여기 들어온다.
그런데 계획 단계에서 재 보니 **사슬을 채울 수 있는 경로가 하나도 없었다**:

  · `regime_snapshots.attach_evidence()`  — 호출자 0개 → 어떤 스냅샷도 MES 가 아님
  · `POST /allocation/target-versions`    — `case_id`·`mes_id` 를 안 받음
  · `POST /research-runs`                 — `case_id` 를 안 받음

M1-S 는 저장소와 함수 인자를 만들었지만 라우트가 그것을 넘기지 않았다. 그 상태에서
사슬 가드를 쓰면 **아무것도 지키지 않는 초록 테스트**가 된다 — 이 저장소가 A4·A5·A7
에서 세 번 값을 치른 실패 양식이다. 그래서 M1-V 는 배선을 먼저 하고, 이 파일이 그
배선이 실제로 동작하는지를 잰다.

여기 단언은 **정책**이다. 화면이 무엇을 보내든 서버가 마지막 방어선이고, 실행 목표는
승인된 `TargetPortfolioVersion` 하나에서만 나온다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.data.target_versions import (
    MODE_LONG_ONLY,
    STATUS_EXECUTABLE,
    STATUS_RESEARCH_ONLY,
    compile_target,
)

# 실제 KR 종목·ETF (mock 가격 로더가 값을 준다). 합 100%.
BASE = {"005930": 40.0, "000660": 25.0, "069500": 20.0, "132030": 15.0}
CUR = {"005930": 30.0, "000660": 30.0, "069500": 25.0, "035720": 15.0}


@pytest.fixture(scope="module")
def client():
    from src.app_factory import create_app
    return TestClient(create_app())


# ═══════════════════════════════════════════════════════════════════════════
# 1. MES 승격 — 스냅샷이 실제로 증거를 갖는다
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def snapshot_id(client) -> str:
    r = client.post("/api/v1/regime-snapshots/from-current?market=kr")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("recorded") is True, "이 테스트는 저장소가 동작해야 성립한다"
    return body["snapshot_id"]


def test_snapshot_creation_promotes_it_to_a_macro_evidence_snapshot(client, snapshot_id):
    """★M1-S 가 만든 승격 경로에 생산자가 생겼다★

    이 단언이 red 이면 `attach_evidence` 는 다시 호출자 0개가 된 것이고, Case 사슬의
    `mes` 조각은 영원히 "고정된 증거가 없습니다" 로 남는다.
    """
    snap = client.get(f"/api/v1/regime-snapshots/{snapshot_id}").json()

    level = snap.get("capability_level")
    assert level in ("L0", "L1", "L2", "L3"), f"능력 레벨이 붙지 않았다: {level!r}"
    assert snap.get("mes_version"), "MES 스키마 버전이 비어 있다"

    # 모델은 **계약 상태**이지 실행 결과가 아니다 — 그 사실이 값 안에 있어야 한다.
    models = snap.get("models") or {}
    assert models, "모델 계약 상태가 비어 있다"
    for mid, m in models.items():
        assert m.get("computed") is False, f"{mid}: 실행 결과인 척한다"
        assert m.get("note"), f"{mid}: 계약 상태라는 설명이 없다"


def test_evidence_covers_every_registered_source_and_never_fakes_a_value(client, snapshot_id):
    """★값이 없어도 키는 존재한다 (M1-S·M1-I 계약)★

    키가 사라지면 화면은 "그 지표를 안 본다" 로, `0` 이 들어가면 "0 이다" 로 읽는다 —
    둘 다 거짓이다. 참인 것은 `available:false` + 사유뿐이다.
    """
    from src.data.source_registry import all_specs

    ind = client.get(f"/api/v1/regime-snapshots/{snapshot_id}").json().get("indicators") or {}
    for spec in all_specs():
        assert spec.key in ind, f"등록된 소스인데 MES 에 키가 없다: {spec.key}"
        item = ind[spec.key]
        if not spec.verified_live:
            # 미검증 소스는 값을 내지 않는다 — 검증되지 않은 코드가 만든 값은 실데이터인지
            # mock 인지 구분할 수 없다.
            assert item.get("available") is False, f"{spec.key}: 미검증인데 가용이라고 답한다"
            assert item.get("value") is None, f"{spec.key}: 미검증인데 값이 있다"
            assert item.get("reason"), f"{spec.key}: 사유 없는 미가용"


def test_evidence_is_write_once_even_through_the_production_path(snapshot_id):
    """★증거는 사후에 바뀌지 않는다★ 두 번째 승격은 거부된다.

    증거가 나중에 바뀌면 "그 결정을 내릴 때 무엇을 보고 있었는가" 에 답할 수 없고,
    그게 스냅샷이 존재하는 유일한 이유다. M1-S 는 이 불변식을 DB WHERE 절로 강제했고,
    여기서는 **생산 경로**를 통해서도 성립하는지 확인한다.
    """
    from src.engine.regime_snapshot_builder import promote_to_mes

    again = promote_to_mes(snapshot_id)
    assert again["attached"] is False, "이미 채워진 스냅샷을 덮어썼다"
    assert again["reason"], "거부에 사유가 없다"


# ═══════════════════════════════════════════════════════════════════════════
# 2. 사슬 — rc_* → rgs_* → tpv_* → rr_*
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def case_id(client) -> str:
    r = client.post("/api/v1/research-cases", json={
        "name": "M1-V 롱온리 사슬",
        "question": "MES 아래 컴파일한 롱온리 목표가 실행 게이트를 통과하는가?",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("created") is True, body
    return body["case_id"]


def test_target_version_route_preserves_the_case_and_evidence_ids(client, case_id, snapshot_id):
    """★라우트가 `case_id`·`mes_id` 를 보존한다 (M1-V 배선)★

    이 단언은 배선 이전에는 반드시 red 였다 — 요청 모델에 두 필드가 아예 없었으므로
    저장된 행의 두 열은 언제나 NULL 이었다.
    """
    r = client.post("/api/v1/allocation/target-versions", json={
        "base_weights": BASE,
        "overlay": {"exposure": 0.6, "source": "canary"},
        "case_id": case_id, "mes_id": snapshot_id,
    })
    assert r.status_code == 200, r.text
    tpv_id = r.json()["tpv_id"]
    assert tpv_id, "저장되지 않았다"

    got = client.get(f"/api/v1/allocation/target-versions/{tpv_id}").json()
    assert got["case_id"] == case_id
    assert got["mes_id"] == snapshot_id
    # ★`snapshot_id` 로 기본값을 채우지 않는다★ 세션이 붙인 스냅샷과 케이스가 고정한
    # 증거는 다른 사실이고, 하나로 다른 하나를 채우면 없는 사실이 만들어진다.
    assert got["snapshot_id"] is None


def test_chain_endpoint_returns_the_target_and_run_of_this_case(client, case_id, snapshot_id):
    """★사슬이 실제로 이어진다★ CaseBar 가 그리는 것이 참인지 여기서 결정된다."""
    tpv_id = client.post("/api/v1/allocation/target-versions", json={
        "base_weights": BASE, "case_id": case_id, "mes_id": snapshot_id,
    }).json()["tpv_id"]

    run_id = client.post("/api/v1/research-runs", json={
        "kind": "allocation_analyze", "inputs": {"base": BASE},
        "outputs": {"weights": {"optimized": BASE}}, "case_id": case_id,
    }).json()["run_id"]
    assert run_id, "런이 저장되지 않았다"

    # 케이스의 활성 포인터를 갱신 — 지금은 PATCH 가 유일한 경로다.
    assert client.patch(f"/api/v1/research-cases/{case_id}", json={
        "active_mes_id": snapshot_id, "active_tpv_id": tpv_id, "active_run_id": run_id,
    }).status_code == 200

    chain = client.get(f"/api/v1/research-cases/{case_id}/chain").json()
    assert chain["case"]["active_mes_id"] == snapshot_id
    assert chain["mes"]["available"] is True, chain["mes"]
    assert chain["targets"]["available"] is True
    assert tpv_id in [t["tpv_id"] for t in chain["targets"]["items"]], "목표가 사슬에 없다"
    assert chain["runs"]["available"] is True
    assert run_id in [r["run_id"] for r in chain["runs"]["items"]], "런이 사슬에 없다"


# ═══════════════════════════════════════════════════════════════════════════
# 3. ★롱온리 폐쇄★ — 노출을 줄여도 어디로도 새지 않는다
# ═══════════════════════════════════════════════════════════════════════════

_KR_CODE = 6


@pytest.mark.parametrize("exposure", [1.0, 0.6, 0.25, 0.0])
def test_long_only_target_closes_with_kr_assets_and_cash(exposure):
    tv = compile_target(BASE, {"exposure": exposure, "source": "canary"})

    assert tv["mode"] == MODE_LONG_ONLY
    assert tv["status"] == STATUS_EXECUTABLE, tv["status_reason"]

    final = tv["final_weights"]
    # 자산은 전부 6자리 KR 코드다 — 해외 티커나 합성 코드가 섞이지 않는다.
    assert all(len(c) == _KR_CODE and c.isdigit() for c in final), sorted(final)
    assert all(v >= 0 for v in final.values()), "롱온리인데 음수가 있다"

    # ★폐쇄★ 자산 + 현금 = 원래 배분. 정규화로 현금을 지우면 노출 축소가 사라진다.
    assert sum(final.values()) + tv["cash_weight"] == pytest.approx(sum(BASE.values()))
    assert tv["cash_weight"] == pytest.approx(sum(BASE.values()) * (1.0 - exposure))


def test_order_diff_from_an_executable_target_closes_too():
    """★주문 diff 가 목표 밖으로 나가지 않는다★"""
    from src.engine.execution_plan import build_plan

    tv = compile_target(BASE, {"exposure": 0.6, "source": "canary"})
    plan = build_plan(CUR, tv["final_weights"], 1e8)

    known = set(CUR) | set(tv["final_weights"])
    for o in plan["orders"]:
        assert o["stock_code"] in known, f"목표에도 보유에도 없는 종목 주문: {o['stock_code']}"
        assert o["side"] in ("buy", "sell")

    # 목표에서 빠진 종목(035720)은 전량 매도로 나와야 한다 — 조용히 남겨두지 않는다.
    sells = {o["stock_code"] for o in plan["orders"] if o["side"] == "sell"}
    assert "035720" in sells, "유니버스에서 빠진 보유 종목이 정리되지 않았다"

    # 목표 비중 합 + 현금 = 100 (주문에 실린 목표가 컴파일된 목표와 같다).
    tgt = {o["stock_code"]: o["tgt_weight_pct"] for o in plan["orders"]}
    for c, w in tv["final_weights"].items():
        if c in tgt:
            assert tgt[c] == pytest.approx(w, abs=1e-6)


def test_execution_gate_accepts_the_executable_target(client, case_id, snapshot_id):
    """MES → TPV → executable → 계획 생성까지 한 번에 닫힌다."""
    tpv_id = client.post("/api/v1/allocation/target-versions", json={
        "base_weights": BASE, "overlay": {"exposure": 0.6, "source": "canary"},
        "case_id": case_id, "mes_id": snapshot_id,
    }).json()["tpv_id"]

    r = client.post("/api/v1/allocation/execution-plan", json={
        "current_weights": CUR, "tpv_id": tpv_id, "portfolio_value": 1e8,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("blocked") is not True, body
    tgt = {o["stock_code"]: o["tgt_weight_pct"] for o in body["plan"]["orders"]}
    assert tgt["005930"] == pytest.approx(24.0)   # 40 × 0.6


# ═══════════════════════════════════════════════════════════════════════════
# 4. ★음수 클램프는 고정만 한다 — 바꾸지 않는다 (P3 소관)★
# ═══════════════════════════════════════════════════════════════════════════

def test_build_plan_still_clamps_negative_targets_to_zero():
    """`execution_plan.py:72-73` 의 `max(..., 0.0)` — **현재 동작을 고정**한다.

    R0 이 P3 로 미룬 부채다. 음수 목표를 0 으로 만드는 것은 롱숏에서는 조용한 왜곡이지만,
    롱온리에서는 두 번째 방어선이다. 여기서 바꾸지 않고 **적어 둔다** — P3 가 롱숏을 열
    때 이 테스트가 대화 상대가 된다.
    """
    from src.engine.execution_plan import build_plan

    plan = build_plan({"005930": 10.0}, {"005930": -30.0}, 1e8)
    tgt = {o["stock_code"]: o["tgt_weight_pct"] for o in plan["orders"]}
    assert tgt["005930"] == pytest.approx(0.0), "클램프 동작이 바뀌었다 — P3 라면 의도된 변경인지 확인할 것"
    assert all(o["side"] == "sell" for o in plan["orders"])


def test_that_clamp_is_unreachable_through_the_gate():
    """★그리고 그 경로는 게이트를 통해서는 도달할 수 없다★

    `compile_target` 이 롱온리에서 음수를 **버리지 않고 거부**하므로, 음수 목표는
    `research_only` 가 되어 실행으로 갈 수 없다. 클램프는 두 번째 방어선이지 첫 번째가
    아니다 — 이 짝이 성립해야 "롱온리 파이프라인이 안전하다" 고 말할 수 있다.
    """
    tv = compile_target({**BASE, "000660": -5.0}, None)
    assert tv["status"] == STATUS_RESEARCH_ONLY
    assert "음수" in (tv["status_reason"] or ""), tv["status_reason"]
    # 값은 남는다 — 버리면 롱숏이 아닌데 롱온리처럼 보이게 된다.
    assert tv["final_weights"]["000660"] == pytest.approx(-5.0)
