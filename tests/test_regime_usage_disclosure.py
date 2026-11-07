"""국면확률의 **출처 신고** — ★계약이 기본값에서 우회된다★
==============================================================================
감사: `docs/specs/2026-08-28-macro-model-stack-audit.md` 부록 A
계약: `src/engine/regime_probability.py` (USAGE_* / SOURCE_* / require_portfolio_source)

## 이 파일이 막는 것

`regime_probability` 는 *"배분에 닿을 수 있는 것은 `k_step_forecast` 하나뿐"* 이라는
계약을 세우고 어휘와 검사를 갖췄다. 그런데 자기 독스트링이 이미 적어 뒀다:

> 그런데 포트폴리오에는 **넷째** — `regime_path` 의 하드 라벨, 즉 **1.000** — 이 간다.

실측(`allocation_backtest.py`): `weighting` 의 **기본값이 `"hard"`** 이고 그 분기는
`require_portfolio_source` 를 통과하지 않는다. 즉 계약은 **비기본 분기에서만**
강제된다. 기본 경로는 "오늘 국면이 보유기간 동안 지속된다" 는 **가정**을 쓰는데
그 가정이 어디에도 라벨되지 않았다.

★이번에 바꾸는 것은 기록뿐이다★ — 계약을 강제로 거는 것은 Macro → Allocation 정책
변경이라 별도 승인 사항이다. 여기서 하는 것은 **그 결정을 할 수 있게 사실을 드러내는
것**이고, 그래서 `U3` 가 "결정이 바뀌지 않았다" 를 함께 못 박는다.

## 두 번째 오해 — 진단 팔이 하중을 받는 것처럼 보인다

`regime_ensemble{axis, markov, cluster}` 의 소비자는 API 라우트 2곳뿐이고 배분에
흘러들지 않는다. 그 사실이 **다른 모듈의 독스트링에만** 있어서, 라우트 응답만 보는
사람은 "Markov 팔이 포트폴리오를 움직인다" 고 읽는다 — 실제로 그렇게 읽혔다.
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

import src.engine.allocation_backtest as ab  # noqa: E402
import src.engine.regime_ensemble as re_mod  # noqa: E402
import src.engine.regime_probability as rp  # noqa: E402

_NAMES = ["A", "B"]
_MONTHS = 36


def _panel():
    """월 36개 × 영업일 — 두 국면이 각각 충분한 달을 갖도록 번갈아 배치."""
    dates = pd.bdate_range("2022-01-03", periods=_MONTHS * 21)
    rng = np.random.default_rng(20260828)
    R = rng.normal(0.0004, 0.01, size=(len(dates), len(_NAMES)))
    months = sorted({d.strftime("%Y-%m") for d in dates})
    points = [{"t": m, "regime": ("Goldilocks" if i % 2 == 0 else "Reflation")}
              for i, m in enumerate(months)]
    return R, list(dates), points, months[-1]


def _run(weighting: str):
    R, dates, points, last = _panel()
    regime = {"points": points, "weighting": weighting}
    if weighting != "hard":
        regime["h_hold"] = 1
    return ab._regime_override_at(regime, last, R, dates, _NAMES, "bl")


# ══════════════════════════════════════════════════════════════════════════
# U1·U2 ★기본 경로가 계약을 통과하지 않는다는 사실이 기록된다★
# ══════════════════════════════════════════════════════════════════════════
def test_the_default_hard_path_declares_it_is_an_assumption():
    """★핵심★ 이 신고가 없으면 기본 경로가 계약을 통과한 것처럼 읽힌다."""
    _s, _v, audit = _run("hard")
    assert audit["prob_source"] == rp.SOURCE_HARD_LABEL
    assert audit["prob_usage"] == rp.USAGE_ASSUMPTION
    assert audit["prob_usage"] != rp.USAGE_PORTFOLIO


def test_the_probabilistic_path_declares_it_passed_the_contract():
    """★짝★ 없으면 U1 이 '항상 가정' 구현으로도 통과한다."""
    _s, _v, audit = _run("probabilistic")
    assert audit["prob_source"] == rp.SOURCE_FORECAST_MEAN
    assert audit["prob_usage"] == rp.USAGE_PORTFOLIO


def test_every_branch_reports_the_three_fields():
    """★모든 분기가 낸다★ 어떤 응답에만 있으면 소비자가 `.get()` 으로 읽다가
    `None` 을 거짓으로 취급한다(레지스트리 `not_ingested` 와 같은 규율)."""
    for weighting in ("hard", "probabilistic"):
        _s, _v, audit = _run(weighting)
        for key in ("prob_source", "prob_usage", "prob_note"):
            assert key in audit, (weighting, key)


def test_the_disclosure_survives_a_failed_regime_override():
    """경로가 실패해도 **무엇을 쓰려 했는지**는 남아야 한다 — 실패는 신고를
    지우는 이유가 아니다."""
    R, dates, points, _last = _panel()
    _s, _v, audit = ab._regime_override_at(
        {"points": points[:1], "weighting": "hard"},   # 2개월 미만 → 조기 반환
        points[0]["t"], R, dates, _NAMES, "bl")
    assert audit["applied"] is False and audit["reason"]
    assert "prob_source" in audit and "prob_usage" in audit


# ══════════════════════════════════════════════════════════════════════════
# U4 사유는 무엇을 가정했는지 말한다
# ══════════════════════════════════════════════════════════════════════════
def test_the_assumption_is_named_not_just_flagged():
    _s, _v, audit = _run("hard")
    note = audit["prob_note"]
    assert note and note not in ("unavailable", "-", "")
    assert "가정" in note, "무엇을 가정했는지 말하지 않는다"
    assert "적중률" in note, "왜 예측과 다른지 말하지 않는다"


def test_the_contract_passing_path_has_no_warning_note():
    """★짝★ 모든 분기에 경고를 붙이면 경고가 의미를 잃는다."""
    _s, _v, audit = _run("probabilistic")
    assert audit["prob_note"] is None


# ══════════════════════════════════════════════════════════════════════════
# U3 ★불변 — 관측을 늘렸을 뿐 결정은 그대로다★
# ══════════════════════════════════════════════════════════════════════════
def test_recording_the_disclosure_does_not_touch_the_decision():
    """★안전 계약★ 관측을 추가하다 결정을 바꾸는 것이 이 작업의 유일한 위험이다.

    반환되는 Σ 와 뷰가 `conditional_moments` 의 산출과 **정확히 같은지** 본다 —
    감사 필드가 결정으로 새면 여기가 깨진다.
    """
    from src.engine.conditional_market import (
        conditional_moments,
        regime_by_month_from_path,
    )

    R, dates, points, last = _panel()
    sigma, views, audit = ab._regime_override_at(
        {"points": points, "weighting": "hard"}, last, R, dates, _NAMES, "bl")

    by_month, _ = regime_by_month_from_path(points)
    df = pd.DataFrame(R, index=pd.DatetimeIndex(dates), columns=_NAMES)
    cond = conditional_moments(df, by_month, points[-1]["regime"])

    assert audit["applied"] is True
    np.testing.assert_array_equal(np.asarray(sigma), np.asarray(cond["sigma"]))
    mags = sorted(round(abs(float(m)) * 100.0, 10) for m in cond["mu"] if float(m) != 0.0)
    assert sorted(round(v["magnitude_pct"], 10) for v in (views or [])) == mags


# ══════════════════════════════════════════════════════════════════════════
# U5·U6 진단 팔은 스스로 진단이라고 말한다
# ══════════════════════════════════════════════════════════════════════════
def test_the_ensemble_declares_itself_diagnostic():
    out = re_mod.regime_ensemble({}, market="kr")
    assert out["usage"] == rp.USAGE_DIAGNOSTIC
    assert out["usage"] != rp.USAGE_PORTFOLIO


def test_the_ensemble_names_the_load_bearing_path():
    """★어디가 하중을 받는지 말한다★ 이 문장이 없어서 오해가 생겼다."""
    out = re_mod.regime_ensemble({}, market="kr")
    note = out["usage_note"]
    assert note and "regime_path" in note


def test_the_ensemble_reuses_the_existing_vocabulary(monkeypatch):
    """★어휘를 두 벌 만들지 않는다★ 값이 갈라지면 소비자가 둘 다 알아야 한다."""
    monkeypatch.setattr(rp, "USAGE_DIAGNOSTIC", "SENTINEL-DIAGNOSTIC")
    import importlib
    importlib.reload(re_mod)
    try:
        assert re_mod.regime_ensemble({}, market="kr")["usage"] == "SENTINEL-DIAGNOSTIC"
    finally:
        monkeypatch.undo()
        importlib.reload(re_mod)


# ══════════════════════════════════════════════════════════════════════════
# U7 ★트립와이어 — 진단 팔이 배분 입력이 되면 red★
# ══════════════════════════════════════════════════════════════════════════
#: 배분 결정으로 이어지는 모듈들. 여기서 진단 앙상블을 부르면 계약이 무너진다.
_ALLOCATION_MODULES = (
    "src/engine/allocation_backtest.py",
    "src/engine/conditional_market.py",
    "src/engine/allocation_studio.py",
    "src/engine/risk_allocations.py",
    "src/engine/entropy_pooling.py",
)


def _ensemble_public_names() -> set[str]:
    """★손으로 적지 않는다★ 모듈의 공개 API 에서 유도한다 — 목록을 비워서
    가드를 무장해제할 수 없게(이 저장소가 Z2 변이로 배운 규칙)."""
    return {n for n in dir(re_mod)
            if not n.startswith("_") and callable(getattr(re_mod, n))
            and getattr(getattr(re_mod, n), "__module__", "") == re_mod.__name__}


def _scan(text: str, label: str, banned: set[str]) -> list[str]:
    """한 파일의 본문에서 진단 앙상블 사용을 찾는다.

    ★설명 문구는 호출이 아니다★ 주석 줄은 세지 않는다 — 이 규칙을 설명하는 주석이
    스스로를 위반으로 오탐한 전례가 이 저장소에 있다(`test_price_provenance`).
    """
    hits = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#") or "regime_ensemble" not in line:
            continue
        if "import" in line or any(f"{n}(" in line for n in banned):
            hits.append(f"{label}: {stripped}")
    return hits


def test_the_allocation_path_does_not_consume_the_diagnostic_ensemble():
    """소비자가 생기면 red 가 된다 — ★그때 이 논증을 다시 해야 한다★.

    막으려는 것: 진단 전용 확률(축·Markov·GMM)이 배분 결정으로 흘러드는 것.
    독스트링이 아니라 **호출**을 본다.
    """
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    banned = _ensemble_public_names()
    assert banned, "공개 API 를 하나도 찾지 못했다 — 검사가 공허해졌다"

    hits = []
    for rel in _ALLOCATION_MODULES:
        hits += _scan((root / rel).read_text(encoding="utf-8"), rel, banned)
    assert not hits, f"진단 앙상블이 배분 경로로 들어왔다: {hits}"


def test_the_tripwire_actually_catches_a_planted_violation():
    """★짝★ **같은 검사 함수**에 위반을 먹여 본다 — 통과가 무력해서가 아님을 보인다."""
    banned = _ensemble_public_names()
    name = sorted(banned)[0]
    violation = (f"from src.engine.regime_ensemble import {name}\n"
                 f"def pick(series_map):\n    return {name}(series_map)\n")
    assert _scan(violation, "planted.py", banned), "위반을 심어도 잡지 못한다"


def test_the_tripwire_does_not_fire_on_prose():
    """★짝★ 주석·문서 언급으로 red 가 되면 가드가 소음이 되어 꺼진다."""
    prose = ("# regime_ensemble 은 진단 전용이라 배분에 쓰지 않는다\n"
             "MESSAGE = \"regime_ensemble 결과는 화면 전용입니다\"\n")
    assert _scan(prose, "prose.py", _ensemble_public_names()) == []


@pytest.mark.parametrize("name", ["regime_ensemble"])
def test_the_public_api_is_discovered(name):
    assert name in _ensemble_public_names()
