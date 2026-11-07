"""예측 하네스의 ★음성 통제★ — "재 봤다" 가 "스킬이 있다" 는 아니다
==============================================================================
워크플로우: 감사문 `2026-08-28-macro-model-stack-audit.md` 부록 A.5 Track A3
대상: `src/engine/regime_forecast.py::forecast_coverage`

## 이 파일이 막는 것

`forecast_coverage` 는 walk-forward 로 적중률과 평균 집합 크기를 **실측**한다.
기존 테스트는 "쉬운 경로 vs 어려운 경로가 다른 값을 낸다" 까지 확인했다. 그런데
★그 '어려운 경로'(`_churning_path`)는 주기 4의 결정론적 순환이라 상태전환 모형에는
오히려 쉽다.★ 즉 **신호가 없는 경로를 한 번도 먹여 본 적이 없다.**

그래서 이 하네스는 지금까지 다음 둘을 구분해 보인 적이 없다:

    ⑴ 전이 구조를 실제로 학습해서 맞혔다        ← 스킬
    ⑵ 한 국면이 표본의 90% 라 그냥 그것을 찍었다  ← ★기저율★

★적중률만으로는 ⑴과 ⑵를 가를 수 없다★ 그리고 ⑵는 숫자가 아주 좋아 보인다.
비교 대상이 없으면 "90% 적중" 은 투자 판단으로 읽히고, 그것이 이 저장소가
`CLAUDE.md` §2 에서 금지한 "증거보다 강한 결론" 이다.

## 그래서 무엇을 더하나

**주변분포(기저율) 기준선** — 같은 walk-forward 루프를 돌리되 전이 사후 대신
`history` 의 경험적 빈도만 쓴다. 두 값의 차이가 **전이 구조에 귀속할 수 있는
전부**다. 기준선이 없으면 귀속할 수 없다.
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import random  # noqa: E402

import src.engine.regime_forecast as rf  # noqa: E402
from src.engine.regime_transitions import REGIMES  # noqa: E402


def _iid_path(n: int = 200, seed: int = 20260828) -> list[str]:
    """★신호 없음★ — 매달 독립 균등. 전이 구조가 **존재하지 않는다**."""
    rng = random.Random(seed)
    return [rng.choice(list(REGIMES)) for _ in range(n)]


def _persistent_path(n: int = 200) -> list[str]:
    """★신호 있음★ — 30개월 블록. 전이 구조가 실재한다."""
    return ["Goldilocks" if (i // 30) % 2 == 0 else "Stagflation" for i in range(n)]


def _skewed_path(n: int = 200, seed: int = 4242) -> list[str]:
    """★기저율 함정★ — 한 국면이 90%. 독립이라 전이 정보는 **없다**."""
    rng = random.Random(seed)
    others = [r for r in REGIMES if r != "Goldilocks"]
    return ["Goldilocks" if rng.random() < 0.9 else rng.choice(others)
            for _ in range(n)]


# ══════════════════════════════════════════════════════════════════════════
# N1·N2 ★신호가 없으면 없다고 말한다★
# ══════════════════════════════════════════════════════════════════════════
def test_a_signalless_path_yields_no_skill_over_the_base_rate():
    """★핵심 음성 통제★ 독립 균등 경로에는 전이 구조가 없다.

    적중률은 목표 근처로 나올 수 있다(집합을 키우면 언제든 맞는다). 그러나
    **기저율보다 나은 것이 없어야** 한다.
    """
    out = rf.forecast_coverage(_iid_path(), k=1, alpha=0.1)
    assert out["available"], out.get("reason")
    assert out["baseline_available"] is True
    # 집합 크기가 기저율 기준선보다 유의하게 작으면 없는 스킬을 보고한 것이다.
    assert out["set_size_skill_pct"] < 10.0, (
        f"신호 없는 경로에서 스킬을 보고했다: {out['set_size_skill_pct']}%")


def test_a_structured_path_does_beat_the_base_rate():
    """★짝★ 없으면 N1 이 '항상 스킬 0' 구현으로도 통과한다."""
    out = rf.forecast_coverage(_persistent_path(), k=1, alpha=0.1)
    assert out["available"]
    assert out["set_size_skill_pct"] > 30.0, (
        f"구조가 뚜렷한 경로에서 스킬을 못 찾았다: {out['set_size_skill_pct']}%")


def test_the_two_paths_are_told_apart():
    """하네스가 무력하지 않다 — 두 경로가 **다른** 판정을 받는다."""
    weak = rf.forecast_coverage(_iid_path(), k=1, alpha=0.1)
    strong = rf.forecast_coverage(_persistent_path(), k=1, alpha=0.1)
    assert strong["set_size_skill_pct"] > weak["set_size_skill_pct"] * 3, (
        "구조 있는 경로와 없는 경로가 비슷한 스킬을 받는다 — 판별하지 못한다")


# ══════════════════════════════════════════════════════════════════════════
# N3 ★기저율 함정 — 숫자가 좋아 보이는 바로 그 경우★
# ══════════════════════════════════════════════════════════════════════════
def test_a_skewed_path_looks_accurate_but_shows_no_transition_skill():
    """한 국면이 90% 면 적중률은 높다. ★그것은 전이 스킬이 아니다.★

    기준선이 없으면 이 숫자가 투자 판단으로 읽힌다 — 이 테스트가 막는 것이 그것이다.
    """
    out = rf.forecast_coverage(_skewed_path(), k=1, alpha=0.1)
    assert out["available"]
    assert out["coverage"] >= 0.8, "이 경로는 원래 적중률이 높아야 한다"
    assert out["set_size_skill_pct"] <= 0.0, (
        f"기저율로 맞힌 것을 전이 스킬로 보고했다: {out['set_size_skill_pct']}%")


def test_the_baseline_is_reported_next_to_the_measurement():
    """★귀속 가능해야 한다★ 기준선을 응답에 함께 싣지 않으면 읽는 사람이 비교할
    수 없고, 비교할 수 없으면 그 숫자는 주장이다."""
    out = rf.forecast_coverage(_persistent_path(), k=1, alpha=0.1)
    for key in ("baseline_available", "baseline_coverage",
                "baseline_mean_set_size", "set_size_skill",
                "set_size_skill_pct", "baseline_note"):
        assert key in out, key
    assert out["baseline_note"]


def test_the_baseline_uses_the_same_evaluation_points():
    """기준선이 다른 표본에서 나오면 비교가 성립하지 않는다."""
    out = rf.forecast_coverage(_persistent_path(), k=1, alpha=0.1)
    assert out["baseline_n_eval"] == out["n_eval"]


# ══════════════════════════════════════════════════════════════════════════
# N4 ★누출 — 각 예측이 오직 과거만 본다★
# ══════════════════════════════════════════════════════════════════════════
def test_every_forecast_sees_only_a_strict_prefix(monkeypatch):
    """walk-forward 라는 **주장**을 구조로 확인한다.

    ★독스트링이 아니라 호출 인자를 본다★ — `walk_forward: True` 는 상수이고,
    상수는 코드가 바뀌어도 그대로 참을 말한다.
    """
    path = _persistent_path()
    seen: list[list[str]] = []
    real = rf._posterior_forecast

    def spy(history, k):
        seen.append(list(history))
        return real(history, k)

    monkeypatch.setattr(rf, "_posterior_forecast", spy)
    out = rf.forecast_coverage(path, k=1, alpha=0.1)

    assert out["available"]
    assert seen, "예측 함수가 한 번도 불리지 않았다 — 검사가 공허하다"
    for i, hist in enumerate(seen):
        t = out["min_history"] + i
        assert hist == path[:t], f"{i}번째 예측이 과거 접두사가 아니다"


def test_the_leak_spy_is_not_vacuous(monkeypatch):
    """★짝★ 스파이 호출 수가 평가 시점 수와 같아야 한다 — 적으면 위 검사가
    일부 시점을 못 본 것이다."""
    seen = []
    real = rf._posterior_forecast
    monkeypatch.setattr(rf, "_posterior_forecast",
                        lambda h, k: (seen.append(1), real(h, k))[1])
    out = rf.forecast_coverage(_persistent_path(), k=1, alpha=0.1)
    assert len(seen) == out["n_eval"]


# ══════════════════════════════════════════════════════════════════════════
# N5 기존 계약 불변
# ══════════════════════════════════════════════════════════════════════════
def test_the_existing_fields_are_unchanged():
    """기준선은 **덧붙는다** — 기존 소비자가 읽던 필드의 의미가 바뀌지 않는다."""
    out = rf.forecast_coverage(_persistent_path(), k=1, alpha=0.1)
    assert out["target"] == 0.9
    assert out["hits"] + out["misses"] == out["n_eval"]
    assert out["coverage"] == out["hits"] / out["n_eval"]
    assert out["walk_forward"] is True


def test_an_unavailable_path_reports_no_baseline_either():
    """★모든 분기가 낸다★ 사용할 수 없을 때 기준선 키가 사라지면 소비자가
    `.get()` 으로 읽다가 `None` 을 거짓으로 취급한다."""
    out = rf.forecast_coverage(["Goldilocks"] * 5, k=1, alpha=0.1)
    assert out["available"] is False and out["reason"]
    assert out["baseline_available"] is False
