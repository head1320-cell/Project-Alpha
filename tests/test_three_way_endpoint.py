"""Phase 7b 백엔드 표면 — `rule_set_states` 추출 + 3자 비교 엔드포인트.

`e6e05c1` 이 엔진(`MacroOverlay`·`three_way`·`conflict_explanation`)을 만들었지만 **HTTP 표면이
없어 UI 에서 닿을 수 없었다.** 이 파일이 그 표면을 고정한다.

★오버레이는 붙어 있는 RegimeSnapshot 에서 온다 — 라이브 매크로가 아니다★
버전이 있고 시점이 고정된 값만 쓴다. 스냅샷이 없으면 세 번째 다리를 **지어내지 않고**
unavailable + 사유로 둔다.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

import src.data.regime_snapshots as rs
from src.app_factory import create_app
from src.engine import timing_rules_v2 as v2

URL = "/api/v1/allocation/timing/three-way"


@pytest.fixture
def client(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    monkeypatch.setattr(rs, "_engine", lambda: eng)
    monkeypatch.setattr(rs, "_inited", False)
    monkeypatch.setattr(rs, "_has_regime_cols", False)
    with TestClient(create_app()) as c:
        yield c


def _body(**kw):
    base = {"market": "kr", "combination": "continuous",
            "rules": [{"factor_id": "avg_abs_momentum", "universe": ["SPY"]},
                      {"factor_id": "disparity", "universe": ["SPY"]}]}
    base.update(kw)
    return base


# ═══════════════════════════════════════════════════════════════════════════════
# 1. rule_set_states 추출 — evaluate_rule_set 과 같은 파생을 공유한다
# ═══════════════════════════════════════════════════════════════════════════════
def test_rule_set_states_exists_and_returns_one_state_per_rule():
    rset = v2.TimingRuleSetV2(set_id="s", rules=[
        v2.TimingRuleV2(factor_id="avg_abs_momentum"),
        v2.TimingRuleV2(factor_id="disparity"),
    ])
    states = v2.rule_set_states(rset, as_of=None, market="kr")
    assert len(states) == 2
    assert all(s in set(v2.SignalState) for s in states)


def test_evaluate_rule_set_uses_the_same_derivation():
    """★두 경로가 같은 파생을 써야 한다★ 갈라지면 3자 비교와 단독 평가가 어긋난다."""
    rset = v2.TimingRuleSetV2(set_id="s", combination="continuous",
                              rules=[v2.TimingRuleV2(factor_id="avg_abs_momentum")])
    states = v2.rule_set_states(rset, as_of=None, market="kr")
    direct = v2.combine(states, method="continuous")
    via = v2.evaluate_rule_set(rset, as_of=None, mode="forward")
    assert via.state is direct.state
    assert via.exposure == direct.exposure


# ═══════════════════════════════════════════════════════════════════════════════
# 2. 엔드포인트 — 세 다리
# ═══════════════════════════════════════════════════════════════════════════════
def test_returns_three_legs(client):
    r = client.post(URL, json=_body())
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body["legs"]) == {"baseline", "timing_only", "timing_macro"}
    for leg in body["legs"].values():
        assert "state" in leg and "exposure" in leg and "explanation" in leg


def test_baseline_is_fully_invested(client):
    body = client.post(URL, json=_body()).json()
    assert body["legs"]["baseline"]["exposure"] == 1.0
    assert body["legs"]["baseline"]["state"] == "risk_on"


def test_without_a_snapshot_the_macro_leg_is_unavailable_with_a_reason(client):
    """★스냅샷이 없으면 비교를 지어내지 않는다★"""
    body = client.post(URL, json=_body()).json()
    macro = body["legs"]["timing_macro"]
    assert macro["state"] == "unavailable"
    assert "매크로" in macro["explanation"]
    assert body["overlay"] is None


def test_unknown_snapshot_id_is_rejected(client):
    r = client.post(URL, json=_body(regime_snapshot_id="rgs_0_deadbeef"))
    assert r.status_code == 422
    assert "rgs_0_deadbeef" in r.text


def test_unknown_combination_is_rejected(client):
    r = client.post(URL, json=_body(combination="telepathy"))
    assert r.status_code == 422


def test_regime_conditioned_without_a_snapshot_is_refused_not_substituted(client):
    """엔진의 거부를 HTTP 로도 정직하게 전달한다 — 다른 방식으로 조용히 대치하지 않는다."""
    r = client.post(URL, json=_body(combination="regime_conditioned"))
    assert r.status_code == 422
    assert "오버레이" in r.text


# ═══════════════════════════════════════════════════════════════════════════════
# 3. 스냅샷이 붙었을 때 — 오버레이가 실제로 작동한다
# ═══════════════════════════════════════════════════════════════════════════════
def _snapshot(client) -> str:
    r = client.post("/api/v1/regime-snapshots/from-current", params={"market": "kr"})
    assert r.status_code == 200, r.text
    return r.json()["snapshot_id"]


def test_with_a_snapshot_the_macro_leg_is_computed(client):
    sid = _snapshot(client)
    body = client.post(URL, json=_body(regime_snapshot_id=sid)).json()
    assert body["legs"]["timing_macro"]["state"] != "unavailable"
    assert body["overlay"] is not None
    assert body["overlay"]["enabled"] is True


def test_overlay_never_raises_exposure_over_timing_only(client):
    """★one-way 불변식이 HTTP 경계를 넘어서도 유지되는가★"""
    sid = _snapshot(client)
    body = client.post(URL, json=_body(regime_snapshot_id=sid)).json()
    assert body["legs"]["timing_macro"]["exposure"] <= body["legs"]["timing_only"]["exposure"] + 1e-9


def test_disabling_the_overlay_equals_timing_only(client):
    """게이트의 실질 — 끄면 타이밍 단독과 같아야 한다."""
    sid = _snapshot(client)
    off = client.post(URL, json=_body(regime_snapshot_id=sid, overlay_enabled=False)).json()
    assert off["legs"]["timing_macro"]["exposure"] == off["legs"]["timing_only"]["exposure"]
    assert off["overlay"]["enabled"] is False


def test_conflict_explanation_is_present_or_null(client):
    sid = _snapshot(client)
    body = client.post(URL, json=_body(regime_snapshot_id=sid)).json()
    assert "conflict" in body
    assert body["conflict"] is None or isinstance(body["conflict"], str)


def test_degraded_regime_columns_do_not_fabricate_a_mode():
    """열이 없어 regime/mode 가 None 으로 오는 스냅샷 → **쓸 수 없는** 오버레이.

    ★이 테스트는 원래 HTTP 로 작성했는데 아무것도 검증하지 않았다★
    픽스처에서 `rs._has_regime_cols = False` 로 두면 degraded 경로가 재현될 거라 봤지만,
    `_ensure_table()` 이 새 테이블을 열까지 함께 만들며 그 플래그를 True 로 되돌린다. 그래서
    스냅샷에는 regime 이 실제로 담겨 있었고, 조건문 `if not ov.get("usable", True)` 는 한 번도
    참이 되지 않았다 — 가드를 지우는 뮤테이션 프로브가 통과한 이유가 이것이다.
    지금은 헬퍼를 직접 부른다. 가드가 있는 자리를 검증한다.
    """
    from src.engine.macro_overlay import overlay_from_snapshot
    ov = overlay_from_snapshot(
        {"regime": None, "recommended_mode": None, "confidence": 0.9,
         "stress_score": 12.0, "data_status": "real", "research_usage": "forward_only"},
        enabled=True)
    assert ov.usable is False, "국면을 못 읽었는데 쓸 수 있다고 표시했다"
    assert ov.exposure_cap() == 1.0, "국면을 못 읽었는데 노출을 깎았다"
    assert "중립" not in ov.regime and "neutral" not in ov.recommended_mode.lower()


def test_a_mode_without_a_regime_label_is_not_acted_on():
    """모드는 있는데 국면 이름을 못 읽은 반쪽 판독 → 조정하지 않는다.

    ★이 케이스가 라우트의 `status = UNAVAILABLE` 한 줄이 유일하게 지키는 곳이다★
    양쪽이 다 None 이면 빈 모드가 이미 `mode_cap is None` 을 만들어 오버레이를 못 쓰게 하므로
    그 줄은 잉여다. 뮤테이션 프로브로 그 줄을 지웠을 때 아무 테스트도 깨지지 않아서 알았다.
    반쪽만 읽힌 경우에 조정하면 스펙 §8("모든 위험-온/오프 결정이 이유를 갖는다")을 어긴다 —
    국면을 이름 부를 수 없는데 그 국면 때문에 노출을 깎았다고 설명할 수는 없다.
    """
    from src.engine.macro_overlay import overlay_from_snapshot
    ov = overlay_from_snapshot(
        {"regime": None, "recommended_mode": "CAUTIOUS", "confidence": 0.9,
         "stress_score": 12.0, "data_status": "real", "research_usage": "forward_only"},
        enabled=True)
    assert ov.usable is False, "국면 이름 없이 모드만으로 노출을 조정하려 한다"
    assert ov.exposure_cap() == 1.0


def test_a_real_snapshot_does_not_zero_out_exposure(client):
    """★실제 스냅샷이 흘러들 때 매크로가 전액 방어를 지시하지 않는가★

    Phase 7b 배선 전까지 `MacroOverlay` 는 스트레스를 0~1 분수로, 모드를
    `risk_on`/`neutral`/`risk_off` 로 기대했다. 실제 스냅샷은 스트레스 51.8(0~100)과
    모드 `CAUTIOUS` 를 준다 — 그래서 상한이 0.0 이 되어 이 엔드포인트의 첫 실호출이
    포트폴리오를 전액 위험-오프로 떨어뜨렸다. 단위 테스트는 전부 초록이었다.
    """
    sid = _snapshot(client)
    body = client.post(URL, json=_body(regime_snapshot_id=sid)).json()
    ov, macro = body["overlay"], body["legs"]["timing_macro"]
    assert ov["recommended_mode"], "스냅샷에 권고 모드가 없다 — 전제가 바뀌었다"
    if ov["usable"] and body["legs"]["timing_only"]["exposure"] > 0:
        assert macro["exposure"] > 0.0, (
            f"쓸 수 있는 매크로({ov['recommended_mode']} · 스트레스 {ov['stress_score']})가 "
            f"노출을 0 으로 만들었다 — 단위/어휘 불일치의 징후다")


# ═══════════════════════════════════════════════════════════════════════════════
# 4. 사용자 임계가 존중되는가 — 미리보기와 비교가 같은 노브를 같은 뜻으로 쓰는지
# ═══════════════════════════════════════════════════════════════════════════════
def test_a_user_threshold_is_honored_not_replaced_by_the_catalogue_default():
    """★같은 노브가 두 화면에서 다른 뜻이면 안 된다★

    과거 미리보기(`/timing-factors/{id}/history`)는 사용자 임계로 채점하는데, 3자 비교는
    카탈로그 기본 임계로만 채점하고 있었다. 두 패널이 나란히 놓이는 화면에서 한쪽은
    사용자가 고른 임계로, 다른 쪽은 다른 임계로 판정하면 비교를 신뢰할 수 없다.

    방향(direction)은 반대로 카탈로그가 계속 소유한다 — defense_first 는 음수일 때 위험-온이고
    그건 사용자가 뒤집을 값이 아니다.
    """
    lo = v2.rule_set_from_specs(
        [{"factor_id": "avg_abs_momentum", "universe": ["SPY"], "threshold": -1e9}],
        market="kr")
    hi = v2.rule_set_from_specs(
        [{"factor_id": "avg_abs_momentum", "universe": ["SPY"], "threshold": 1e9}],
        market="kr")
    assert lo.rules[0].threshold == -1e9 and hi.rules[0].threshold == 1e9
    # 임계 아래로는 무엇이든 통과, 위로는 무엇도 통과 못 함 — 값이 읽혔다면 갈려야 한다.
    s_lo = v2.rule_set_states(lo, as_of=None, market="kr")
    s_hi = v2.rule_set_states(hi, as_of=None, market="kr")
    if s_lo[0] is not v2.SignalState.UNAVAILABLE:
        assert s_lo[0] is v2.SignalState.RISK_ON
        assert s_hi[0] is v2.SignalState.RISK_OFF, "사용자 임계가 무시됐다"


def test_omitting_the_threshold_falls_back_to_the_catalogue(client):
    """임계를 안 주면 카탈로그 기본값 — 0 으로 지어내지 않는다."""
    rset = v2.rule_set_from_specs([{"factor_id": "disparity", "universe": ["SPY"]}], market="kr")
    assert rset.rules[0].threshold is None
    r = client.post(URL, json=_body())
    assert r.status_code == 200, r.text
