"""실행 게이트가 **거래 가능성**을 본다 (벤치마크 §7 · S3 의 최소 발현)

★착수 0단계 실측 — 미국 티커가 실행 경로 끝까지 갔다★

    implement_exposures({"equity_us": 60, "gold": 40}, market="us")
        → compile_target(...)  status = executable   사유 = None
        → build_plan(...)      주문 = [('SPY', 30), ('GLD', 178737)]

게이트가 막던 것은 넷뿐이었다 — 사후중립화·롱온리 음수·롱숏 모드·출처 없는
오버레이. ★어느 것도 "이 상품을 우리 실행 경로가 살 수 있는가" 를 묻지 않았다.★
`instrument_selector.EXPOSURES` 가 `SPY`·`VTI`·`QQQ` 를 정식으로 제시하므로
사용자가 만들 수 있는 조합이다.

운영에서는 조용하지 않지만 **막히지도 않았다**. `SPY` 가격이 없을 때 실측:

    목표 {005930: 40%, SPY: 60%}
      주문 1건(005930만) · 회전율 40.0% · missing_price ['SPY']
      pre-trade: 6 pass + 1 warning · blocked = None    ← 승인 가능

목표의 60% 가 사라졌는데 "회전율 40% 정상" 으로 통과한다.

★두 가지를 섞지 않는다★
  · KR 종목의 **일시적** 결측(내일은 있다) → 경고 유지. 지금 동작이 옳다.
  · 구조적으로 **거래 불가**(KIS 는 KR 전용) → 게이트. `research_only`.
전자를 게이트로 만들면 정상 운영이 막히고, 후자를 경고로 두면 반쪽 계획이 승인된다.
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402

from src.data.target_versions import (  # noqa: E402
    STATUS_EXECUTABLE,
    STATUS_RESEARCH_ONLY,
    UNTRADABLE_BLOCKERS,
    compile_target,
    untradable,
)

_FOREIGN = {"SPY": 60.0, "GLD": 40.0}
_KR = {"005930": 60.0, "069500": 40.0}


# ── 1. ★실측 재현★ ──────────────────────────────────────────────────────
def test_a_foreign_target_is_not_executable():
    tv = compile_target(_FOREIGN, None)
    assert tv["status"] == STATUS_RESEARCH_ONLY, tv["status_reason"]


def test_the_reason_names_the_offending_codes():
    """★무엇 때문인지 지목한다★ '거래 불가' 만으로는 어느 종목인지 모른다."""
    reason = compile_target(_FOREIGN, None)["status_reason"] or ""
    assert "SPY" in reason and "GLD" in reason, reason


def test_the_block_names_all_three_measured_reasons():
    """사유가 뭉뚱그려지지 않는다 — 나중에 무엇이 풀렸는지 알 수 있어야 한다.
    (`test_long_short_block_names_all_three_measured_reasons` 와 같은 형태.)"""
    reason = compile_target(_FOREIGN, None)["status_reason"] or ""
    for blocker in UNTRADABLE_BLOCKERS:
        assert blocker in reason, f"차단 사유가 빠졌다: {blocker}"


# ── 2. ★짝 — 국내 목표는 그대로다★ ─────────────────────────────────────
def test_a_domestic_target_is_still_executable():
    tv = compile_target(_KR, None)
    assert tv["status"] == STATUS_EXECUTABLE
    assert tv["status_reason"] is None


@pytest.mark.parametrize("code", ["ABCDEF", "SPY.US", "KR7005", "A05930"])
def test_a_six_character_non_numeric_code_is_still_untradable(code):
    """★길이만 보면 새어 나간다★

    변이 프로브(`isdigit()` 제거)가 **green** 이었다 — 픽스처 `SPY`·`GLD` 가
    3자라 길이 검사만으로도 걸렸기 때문이다. 판정의 절반이 검증되지 않은 채였다.
    6자이면서 숫자가 아닌 코드로 그 절반을 건다.
    """
    assert untradable([code]) == [code]


@pytest.mark.parametrize("code", ["005930", "000660", "069500", "132030", "035720"])
def test_real_kr_codes_are_tradable(code):
    """★게이트가 국내를 잡으면 운영이 멈춘다★ 실제 쓰이는 코드로 건다."""
    assert untradable([code]) == []


def test_a_mixed_target_is_blocked_and_names_only_the_foreign_leg():
    """혼합이면 막되, 국내 종목을 범인으로 지목하지 않는다."""
    tv = compile_target({"005930": 40.0, "SPY": 60.0}, None)
    assert tv["status"] == STATUS_RESEARCH_ONLY
    reason = tv["status_reason"] or ""
    assert "SPY" in reason
    assert "005930" not in reason.split("—")[0], "국내 종목이 범인으로 지목됐다"


# ── 3. ★게이트를 통해서는 주문이 만들어지지 않는다★ ────────────────────
@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from src.app_factory import create_app
    return TestClient(create_app())


def test_the_execution_route_refuses_a_foreign_target(client):
    """롱숏의 짝 테스트와 같은 구조 — 게이트가 첫 번째 방어선이다."""
    from src.data.target_versions import save_target
    tpv_id = save_target(compile_target(_FOREIGN, None))
    if tpv_id is None:
        pytest.skip("목표 저장소 미가용 — 라우트 경로를 태울 수 없다")
    r = client.post("/api/v1/allocation/execution-plan", json={
        "current_weights": {"005930": 100.0}, "tpv_id": tpv_id,
        "portfolio_value": 1e8})
    assert r.status_code == 200, r.text
    assert r.json().get("blocked") is True, r.text


# ── 4. ★일시적 결측은 여전히 경고다 (섞지 않았다는 증거)★ ─────────────
def test_a_kr_code_without_a_price_still_produces_a_plan_with_a_warning():
    """★이 짝이 없으면 두 개념을 섞은 것을 알 수 없다★

    KR 종목의 시세가 오늘 없다고 목표를 연구용으로 내리면 정상 운영이 막힌다.
    그쪽은 계획을 만들되 커버리지 **경고**로 말하는 것이 옳고, 그 동작은 그대로다.
    """
    from src.engine.execution_plan import build_plan, pre_trade_checks
    tv = compile_target({"005930": 40.0, "000660": 60.0}, None)
    assert tv["status"] == STATUS_EXECUTABLE, "국내 목표가 게이트에 걸렸다"

    px = {"005930": 70000.0}          # 000660 은 오늘 시세가 없다
    plan = build_plan({}, tv["final_weights"], 1e9,
                      price_of=lambda c: px.get(c), adv_of=lambda c: 1e12)
    assert plan["orders"], "계획이 통째로 사라졌다"
    assert plan["missing_price"] == ["000660"]
    checks = {c["name"]: c["status"] for c in pre_trade_checks(plan, limits={},
                                                              data_fresh=True)["checks"]}
    assert checks.get("시세 커버리지") == "warning", checks
