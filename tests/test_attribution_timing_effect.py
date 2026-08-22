"""Attribution 의 timing 성분 — 노출 경로로 실측 (스펙 §9, Phase 10d).

스펙은 6분해를 요구한다: allocation · timing · selection · factor · cost · residual.
`cost`·`residual`(+ 슬리피지·모델알파·사전/사후 리스크)은 이미 실측된다. Brinson 세 성분
(allocation·selection·factor)은 **벤치마크 구성종목 가중과 섹터수익**이 있어야 하고 이
저장소에는 그 데이터가 없다 — 코드가 이미 `unavailable` + 사유로 답한다.

Phase 9 의 `/timing/simulate` 가 시점별 노출 경로를 주면서 **timing 만** 계산 가능해졌다.
이 파일이 그 성분을 고정한다.

★"타이밍을 안 했다" 와 "타이밍 기록이 없다" 는 다른 사실이다★
룰셋이 기록되지 않은 런에 0.0 을 적으면 전자로 읽힌다.
"""
from dataclasses import dataclass
from datetime import date

import pytest

from src.engine.attribution import timing_effect


@dataclass
class _Pt:
    as_of: str
    exposure: float


@dataclass
class _Walk:
    points: list


def _fake_sim(exposures: list[tuple[str, float]]):
    """지정한 (as_of, exposure) 경로를 그대로 돌려주는 가짜 시뮬레이터."""
    def sim(rule_set, *, months=24, mode="forward", anchor=None, **kw):
        return _Walk(points=[_Pt(a, e) for a, e in exposures])
    return sim


def _run(**kw):
    base = {"run_id": "rr_1", "inputs": {"timing_rule_set_id": "tr_1"},
            "snapshot": {}, "outputs": {}}
    base.update(kw)
    return base


@pytest.fixture(autouse=True)
def _stub_rule_set(monkeypatch):
    """룰셋 복원은 이 파일의 관심사가 아니다 — 존재한다고 두고 노출 경로만 본다."""
    import src.data.timing_rules as tr
    monkeypatch.setattr(tr, "get_rule_set", lambda sid: {
        "set_id": sid, "market": "kr", "version": 1,
        "rules": [{"factor_id": "avg_abs_momentum", "universe": ["SPY"]}],
        "gate": {"combination": "all"}})
    monkeypatch.setattr(tr, "get_rule_set_version", lambda sid, v: {
        "set_id": sid, "market": "kr", "version": v,
        "rules": [{"factor_id": "avg_abs_momentum", "universe": ["SPY"]}],
        "gate": {"combination": "all"}})


# ═══════════════════════════════════════════════════════════════════════════════
# 1. 방향 — 하락을 피하면 +, 상승을 놓치면 −
# ═══════════════════════════════════════════════════════════════════════════════
def test_being_risk_off_through_a_drawdown_is_a_positive_effect():
    """★이 성분의 존재 이유★ 손실을 피한 것이 타이밍의 기여다."""
    daily = [-0.02] * 10                       # 꾸준한 하락
    out = timing_effect(_run(), daily, date(2026, 1, 1), date(2026, 3, 1),
                        simulate=_fake_sim([("2026-01-01", 0.0)]))
    assert out["basis"] == "real"
    assert out["value"] > 0, f"하락을 피했는데 효과가 {out['value']} 입니다"
    assert out["timed_return_pct"] == 0.0      # 노출 0 → 수익도 손실도 없다
    assert out["full_invested_return_pct"] < 0


def test_being_risk_off_through_a_rally_is_a_negative_effect():
    """놓친 수익도 정직하게 음수로 적는다 — 타이밍이 늘 이득인 척하지 않는다."""
    daily = [0.02] * 10
    out = timing_effect(_run(), daily, date(2026, 1, 1), date(2026, 3, 1),
                        simulate=_fake_sim([("2026-01-01", 0.0)]))
    assert out["value"] < 0, f"상승을 놓쳤는데 효과가 {out['value']} 입니다"


def test_full_exposure_throughout_has_no_effect():
    """노출 1.0 이면 전액 투자와 같다 — 0 이 나와야 할 유일한 경우다."""
    daily = [0.01, -0.02, 0.03]
    out = timing_effect(_run(), daily, date(2026, 1, 1), date(2026, 3, 1),
                        simulate=_fake_sim([("2026-01-01", 1.0)]))
    assert out["value"] == pytest.approx(0.0, abs=1e-6)
    assert out["avg_exposure_pct"] == 100.0


def test_a_varying_exposure_path_is_followed_not_averaged():
    """★경로를 따라가야 한다★ 평균만 쓰면 "언제" 줄였는지가 사라진다.

    앞은 하락·뒤는 상승인 구간에서, 앞에서만 위험-오프였다면 두 번 이득이다(손실 회피 +
    상승 참여). 평균 노출 0.5 를 통째로 곱하면 그 구별이 없어진다.
    """
    daily = [-0.05] * 5 + [0.05] * 5
    path = _fake_sim([("2026-01-01", 0.0), ("2026-02-05", 1.0)])
    out = timing_effect(_run(), daily, date(2026, 1, 1), date(2026, 3, 1), simulate=path)

    flat = timing_effect(_run(), daily, date(2026, 1, 1), date(2026, 3, 1),
                         simulate=_fake_sim([("2026-01-01", 0.5)]))
    assert out["value"] != pytest.approx(flat["value"], abs=1e-6), (
        "경로가 평균과 같은 결과를 냈습니다 — 노출 시점이 반영되지 않았습니다")
    assert out["value"] > 0


# ═══════════════════════════════════════════════════════════════════════════════
# 2. 없는 것은 0 이 아니다
# ═══════════════════════════════════════════════════════════════════════════════
def test_a_run_without_a_rule_set_is_unavailable_not_zero():
    """★0 은 "타이밍을 했는데 효과가 없었다" 를 뜻한다★ 기록이 없는 것과 다르다."""
    out = timing_effect({"run_id": "r", "inputs": {}, "snapshot": {}},
                        [0.01], date(2026, 1, 1), date(2026, 2, 1))
    assert out["value"] is None
    assert out["basis"] == "unavailable"
    assert "기록되지 않" in out["reason"]


def test_no_daily_returns_is_unavailable():
    out = timing_effect(_run(), [], date(2026, 1, 1), date(2026, 2, 1))
    assert out["value"] is None and out["basis"] == "unavailable"


def test_a_deleted_rule_set_is_unavailable_not_recomputed_from_current(monkeypatch):
    """★없는 버전에 현재 룰로 계산해 주지 않는다★ 그건 복원이 아니라 위조다(7c 규칙)."""
    import src.data.timing_rules as tr
    monkeypatch.setattr(tr, "get_rule_set", lambda sid: None)
    monkeypatch.setattr(tr, "get_rule_set_version", lambda sid, v: None)
    out = timing_effect(_run(inputs={"timing_rule_set_id": "tr_gone",
                                     "timing_rule_set_version": 3}),
                        [0.01, 0.02], date(2026, 1, 1), date(2026, 2, 1))
    assert out["value"] is None and out["basis"] == "unavailable"
    assert "복원할 수 없" in out["reason"]


def test_a_failing_simulation_does_not_break_attribution():
    """한 성분의 실패가 귀인 전체를 깨지 않는다 — 사유를 담고 나머지는 살린다."""
    def boom(*a, **k):
        raise RuntimeError("시뮬레이터 고장")
    out = timing_effect(_run(), [0.01], date(2026, 1, 1), date(2026, 2, 1), simulate=boom)
    assert out["value"] is None and out["basis"] == "unavailable"
    assert "시뮬레이터 고장" in out["reason"]


# ═══════════════════════════════════════════════════════════════════════════════
# 3. 한계를 숨기지 않는다 · 일방향
# ═══════════════════════════════════════════════════════════════════════════════
def test_the_monthly_sampling_caveat_ships_with_the_number():
    out = timing_effect(_run(), [0.01, 0.02], date(2026, 1, 1), date(2026, 3, 1),
                        simulate=_fake_sim([("2026-01-01", 0.5)]))
    assert "월" in out["note"], "월 표본 한계가 결과에 적혀 있지 않습니다"
    assert "근사" in out["note"]


def test_exposure_above_one_is_clamped():
    """★오버레이는 노출을 키우지 않는다★ 레버리지로 번 것을 타이밍 기여로 적으면 안 된다."""
    daily = [0.10] * 5
    out = timing_effect(_run(), daily, date(2026, 1, 1), date(2026, 3, 1),
                        simulate=_fake_sim([("2026-01-01", 3.0)]))
    assert out["avg_exposure_pct"] == 100.0
    assert out["value"] == pytest.approx(0.0, abs=1e-6)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. 나머지 세 성분은 여전히 unavailable — 프록시로 채우지 않았다
# ═══════════════════════════════════════════════════════════════════════════════
def test_the_other_brinson_components_stay_unavailable():
    from src.engine.attribution import compute_attribution
    rep = compute_attribution(
        {"run_id": "r", "created_at": None, "inputs": {"weights": {"005930": 100}},
         "outputs": {}, "snapshot": {}},
        path_of=lambda c, s, e: None)
    be = rep["brinson_effects"]
    for k in ("selection", "allocation", "factor", "hedge"):
        assert be[k] is None, f"{k} 가 프록시로 채워졌습니다"
    assert "벤치마크 구성종목" in be["note"], "무엇이 없어서 못 하는지 적혀 있지 않습니다"
