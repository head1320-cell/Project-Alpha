"""연구 패널과 그 출처 — ★등급은 주장이 아니라 파생이다★ (M9)
==============================================================================
지금까지 증거 등급은 `regime_control.run(panel_is_synthetic=...)` 이라는
**호출자가 주는 검증되지 않은 불리언**이 정했다. 합성 패널에 `False` 를 넘기면
그대로 `E3` 가 찍혔고, `regime_signal_gate` 는 아예 `"E0"` 하드코딩이라 실데이터가
들어와도 계속 E0 라고 말했을 것이다.

★여기서는 등급을 **출처에서 파생**한다★ — 찍는 것이 아니라 읽는 것이다.
그리고 출처를 모르면 ★등급을 찍지 않는다★. 미상은 E3 가 아니다.

★가장 중요한 불변식★ 실데이터가 없을 때 **합성으로 대체하지 않는다**. 운영에서
합성값을 만들지 않는다는 CLAUDE.md §6 이 연구 경로에도 그대로 적용된다.
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from src.engine.research_panel import (  # noqa: E402
    BASIS_ADJ,
    BASIS_CLOSE,
    GRADE_E0,
    GRADE_E3,
    GRADE_E4,
    PRICE_SOURCE_KRX,
    REGIME_SOURCE_AXES,
    SOURCE_SYNTHETIC,
    Panel,
    evidence_grade,
    inject_regime_drift,
    panel_for,
    real_panel,
    synthetic_panel,
)


def _prov(**kw):
    base = {"price_source": SOURCE_SYNTHETIC, "regime_source": SOURCE_SYNTHETIC,
            "price_basis": None, "vintage": None, "injected_scale": None}
    return {**base, **kw}


# ══════════════════════════════════════════════════════════════════════════
# ★등급 파생 — 규칙이지 데이터가 아니다★
# ══════════════════════════════════════════════════════════════════════════
def test_a_fully_synthetic_panel_is_e0():
    grade, why = evidence_grade(_prov())
    assert grade == GRADE_E0 and why


def test_real_prices_and_real_regimes_are_e3():
    grade, _ = evidence_grade(_prov(price_source=PRICE_SOURCE_KRX,
                                    regime_source=REGIME_SOURCE_AXES,
                                    price_basis=BASIS_ADJ))
    assert grade == GRADE_E3


def test_a_vintage_reproduced_panel_is_e4():
    grade, _ = evidence_grade(_prov(price_source=PRICE_SOURCE_KRX,
                                    regime_source=REGIME_SOURCE_AXES,
                                    price_basis=BASIS_ADJ,
                                    vintage={"revision_bias": "managed"}))
    assert grade == GRADE_E4


def test_an_unmanaged_vintage_is_e3_not_e4():
    """★짝★ — 빈티지가 실제로 재현될 때만 E4 다. 지금 KRX·ECOS 는 도달 불가."""
    grade, why = evidence_grade(_prov(price_source=PRICE_SOURCE_KRX,
                                      regime_source=REGIME_SOURCE_AXES,
                                      price_basis=BASIS_ADJ,
                                      vintage={"revision_bias": "unmanaged",
                                               "blocked_permanently": ["ecos.x"]}))
    assert grade == GRADE_E3
    assert "빈티지" in why or "개정" in why


@pytest.mark.parametrize("ps,rs", [
    (PRICE_SOURCE_KRX, SOURCE_SYNTHETIC), (SOURCE_SYNTHETIC, REGIME_SOURCE_AXES)])
def test_a_mixed_panel_falls_to_the_weaker_grade(ps, rs):
    """★약한 고리가 지배한다★ 실가격 + 합성 국면은 실증거가 아니다.

    ★`price_basis` 를 일부러 `adj_close` 로 준다★ — 처음에는 `None` 으로 뒀는데,
    그러면 가격 기준 규칙이 먼저 E0 를 내서 **약한 고리 규칙을 통째로 우회**했다.
    변이 Q6(혼합을 E3 로)이 살아남아 그 사실을 드러냈다. 이 테스트가 걸어야 하는
    것은 기준이 아니라 **출처의 혼합**이다.
    """
    grade, why = evidence_grade(_prov(price_source=ps, regime_source=rs,
                                      price_basis=BASIS_ADJ))
    assert grade == GRADE_E0
    assert "약한 고리" in why


@pytest.mark.parametrize("prov", [
    {"price_source": None, "regime_source": REGIME_SOURCE_AXES},
    {"price_source": PRICE_SOURCE_KRX, "regime_source": None},
    {},
])
def test_an_unknown_source_refuses_to_stamp_a_grade(prov):
    """★미상 ≠ E3★ 모르는 출처에 등급을 찍으면 그것이 곧 과대주장이다."""
    grade, why = evidence_grade(prov)
    assert grade is None
    assert why and ("모르" in why or "미상" in why)


def test_injecting_a_signal_demotes_a_real_panel_to_e0():
    """★주입한 순간 실증거가 아니다★ 반합성은 검정력을 재는 도구이지 증거가 아니다."""
    grade, why = evidence_grade(_prov(price_source=PRICE_SOURCE_KRX,
                                      regime_source=REGIME_SOURCE_AXES,
                                      price_basis=BASIS_ADJ,
                                      injected_scale=2.0))
    assert grade == GRADE_E0
    assert "주입" in why or "반합성" in why


def test_even_an_identity_injection_demotes():
    """★짝★ scale=1 은 값이 같아도 **반합성 실험의 일부**다 — 리포트가 그걸 말해야 한다."""
    grade, _ = evidence_grade(_prov(price_source=PRICE_SOURCE_KRX,
                                    regime_source=REGIME_SOURCE_AXES,
                                    price_basis=BASIS_ADJ, injected_scale=1.0))
    assert grade == GRADE_E0


def test_real_prices_on_a_raw_close_basis_are_not_e3():
    """★원주가 ≠ 수정주가★ 기업행위 미조정 가격으로 낸 수익은 실증거가 아니다."""
    grade, why = evidence_grade(_prov(price_source=PRICE_SOURCE_KRX,
                                      regime_source=REGIME_SOURCE_AXES,
                                      price_basis=BASIS_CLOSE))
    assert grade != GRADE_E3
    assert "수정" in why or "adj" in why.lower()


# ══════════════════════════════════════════════════════════════════════════
# 합성 공급자 — ★비트 동일★
# ══════════════════════════════════════════════════════════════════════════
def test_the_synthetic_panel_matches_the_frozen_hash():
    import hashlib

    from tests.test_regime_panel_scale import FROZEN
    p = synthetic_panel(months=36)
    h = hashlib.sha256(np.ascontiguousarray(p.returns, dtype=np.float64).tobytes())
    assert h.hexdigest() == FROZEN[36]


def test_the_synthetic_panel_declares_itself_synthetic():
    p = synthetic_panel(months=12)
    assert p.provenance["price_source"] == SOURCE_SYNTHETIC
    assert p.provenance["regime_source"] == SOURCE_SYNTHETIC
    assert evidence_grade(p.provenance)[0] == GRADE_E0
    assert p.provenance["injected_scale"] is None


def test_the_synthetic_panel_records_the_scale_it_was_built_with():
    p = synthetic_panel(months=12, scale=3.0)
    assert p.provenance["synthetic_scale"] == 3.0


# ══════════════════════════════════════════════════════════════════════════
# ★실데이터 공급자 — 없으면 거부한다★
# ══════════════════════════════════════════════════════════════════════════
def _prices(codes, n=300):
    import pandas as pd
    idx = pd.bdate_range("2020-01-01", periods=n, freq="C")
    rng = np.random.default_rng(0)
    return {c: pd.Series(rng.normal(0, 0.01, n), index=idx) for c in codes}


def _points(n=12):
    return [{"t": f"2020-{i + 1:02d}", "growth": 0.1, "inflation": -0.1,
             "regime": ["Goldilocks", "Stagflation"][i % 2]} for i in range(n)]


def test_a_real_panel_is_built_from_injected_loaders():
    p, why = real_panel(["A", "B"], months=12,
                        price_loader=lambda codes, **kw: (_prices(codes), BASIS_ADJ, []),
                        regime_loader=lambda **kw: (_points(), {"revision_bias": "unmanaged"}))
    assert p is not None, why
    assert p.names == ["A", "B"] and p.returns.shape[1] == 2
    assert p.provenance["price_source"] == PRICE_SOURCE_KRX
    assert p.provenance["regime_source"] == REGIME_SOURCE_AXES
    assert evidence_grade(p.provenance)[0] == GRADE_E3


def test_no_prices_means_no_panel_not_a_synthetic_one():
    """★가장 중요한 불변식★ 실데이터가 없으면 **합성으로 대체하지 않는다**."""
    p, why = real_panel(["A"], months=12,
                        price_loader=lambda codes, **kw: ({}, None, ["가격이 없습니다"]),
                        regime_loader=lambda **kw: (_points(), None))
    assert p is None
    assert any("가격" in r for r in why)


def test_no_regime_labels_means_no_panel():
    p, why = real_panel(["A"], months=12,
                        price_loader=lambda codes, **kw: (_prices(["A"]), BASIS_ADJ, []),
                        regime_loader=lambda **kw: ([], {"revision_bias": "unmanaged"}))
    assert p is None
    assert any("국면" in r for r in why)


def test_a_code_without_adjusted_prices_is_dropped_with_a_reason():
    """★`close` 로 조용히 갈아타지 않는다★ 빠진 종목은 사유와 함께 빠진다."""
    p, why = real_panel(["A", "B"], months=12,
                        price_loader=lambda codes, **kw: (
                            _prices(["A"]), BASIS_ADJ, ["B: adj_close 없음"]),
                        regime_loader=lambda **kw: (_points(), None))
    assert p is not None
    assert p.names == ["A"]
    assert any("B" in r for r in why)
    assert p.provenance["coverage"]["requested"] == 2
    assert p.provenance["coverage"]["used"] == 1


def test_the_real_panel_never_falls_back_even_when_mock_is_allowed(monkeypatch):
    """★개발 모드에서도 실 공급자는 실 아니면 없음이다★

    `mock_allowed()` 는 **호출자가 합성으로 갈아탈 수 있는가**를 정하지, 실
    공급자가 몰래 합성을 내도 되는가를 정하지 않는다. 두 개념을 섞으면 개발
    환경에서 통과한 경로가 운영에서 다르게 동작한다.
    """
    import src.data.mock_gate as mg
    monkeypatch.setattr(mg, "mock_allowed", lambda: True)
    p, _ = real_panel(["A"], months=12,
                      price_loader=lambda codes, **kw: ({}, None, ["없음"]),
                      regime_loader=lambda **kw: (_points(), None))
    assert p is None


# ══════════════════════════════════════════════════════════════════════════
# ★panel_for — mock 게이트가 여기서 하중이 된다★
# ══════════════════════════════════════════════════════════════════════════
def test_a_synthetic_panel_is_refused_in_production(monkeypatch):
    """★운영에서 합성 연구 패널을 돌리지 않는다★ (CLAUDE.md §6)"""
    import src.engine.research_panel as rp
    monkeypatch.setattr(rp, "mock_allowed", lambda: False)
    p, why = panel_for(real=False, months=12)
    assert p is None
    assert any("mock" in r.lower() or "합성" in r for r in why)


def test_a_synthetic_panel_is_allowed_in_development(monkeypatch):
    """★짝★ — 언제나 거부하는 구현을 배제한다."""
    import src.engine.research_panel as rp
    monkeypatch.setattr(rp, "mock_allowed", lambda: True)
    p, why = panel_for(real=False, months=12)
    assert p is not None and why == []


# ══════════════════════════════════════════════════════════════════════════
# 반합성 양성 통제
# ══════════════════════════════════════════════════════════════════════════
def _real_like():
    p, _ = real_panel(["A", "B", "C"], months=12,
                      price_loader=lambda codes, **kw: (_prices(codes), BASIS_ADJ, []),
                      regime_loader=lambda **kw: (_points(), None))
    return p


def test_injecting_at_scale_one_is_the_identity():
    """★항등★ 이것이 깨지면 검정력 곡선의 1× 지점이 원래 패널이 아니게 된다."""
    p = _real_like()
    out = inject_regime_drift(p, 1.0)
    assert np.allclose(out.returns, p.returns, atol=1e-15)
    assert out.provenance["injected_scale"] == 1.0


def test_injecting_at_scale_zero_erases_the_regime_differences():
    """★음성 통제★ 국면별 평균 차이가 0 이 된다."""
    p = _real_like()
    out = inject_regime_drift(p, 0.0)
    labels = np.array([q["regime"] for q in out.points])
    monthly = _monthly(out)
    means = [monthly[labels == g].mean(axis=0) for g in np.unique(labels)]
    assert np.allclose(means[0], means[1], atol=1e-12)


def test_injecting_above_one_widens_the_regime_spread():
    """★짝★ — 상수를 내는 주입기를 배제한다."""
    p = _real_like()

    def spread(scale):
        out = inject_regime_drift(p, scale)
        labels = np.array([q["regime"] for q in out.points])
        m = _monthly(out)
        gs = [m[labels == g].mean(axis=0) for g in np.unique(labels)]
        return float(np.abs(gs[0] - gs[1]).sum())

    assert spread(0.0) < spread(1.0) < spread(3.0)
    assert spread(3.0) == pytest.approx(3 * spread(1.0), rel=1e-6)


def test_injection_leaves_the_noise_structure_alone():
    """★반합성의 요점★ 공분산·꼬리·자기상관은 실데이터 그대로여야 한다.

    주입은 **월 단위 수준 이동**이므로 각 달 안에서 일수익의 편차는 변하지 않는다.
    """
    p = _real_like()
    out = inject_regime_drift(p, 4.0)
    d = out.returns - p.returns
    import pandas as pd
    mo = pd.Series(pd.DatetimeIndex(p.dates)).dt.strftime("%Y-%m").values
    for m in np.unique(mo):
        rows = d[mo == m]
        assert np.allclose(rows, rows[0], atol=1e-15), f"{m} 에서 잡음이 바뀌었다"


def test_injection_preserves_the_overall_level():
    """★국면 간 **차이**만 배율한다 — 전체 수준은 건드리지 않는다★

    변이 Q9(전체평균 중심화 제거)가 살아남아서 찾았다. 중심화를 빼도 scale=0 에서
    국면별 평균이 전부 0 으로 같아지므로 음성 통제 테스트는 그대로 통과한다 —
    그런데 그 구현은 **전체 수익 수준까지 밀어 버린다**. 그러면 척도를 올릴 때
    관문이 국면 정보가 아니라 드리프트를 보고 반응한다.

    `scaled_profiles` 가 합성 쪽에서 지키는 것과 같은 계약이다.
    """
    p = _real_like()
    base = _monthly(p).mean(axis=0)
    for scale in (0.0, 1.0, 3.0, 5.0):
        out = _monthly(inject_regime_drift(p, scale)).mean(axis=0)
        assert np.allclose(out, base, atol=1e-12), f"scale={scale} 에서 수준이 움직였다"


def test_injection_records_itself_and_demotes_the_grade():
    p = _real_like()
    assert evidence_grade(p.provenance)[0] == GRADE_E3
    out = inject_regime_drift(p, 2.0)
    assert out.provenance["injected_scale"] == 2.0
    assert evidence_grade(out.provenance)[0] == GRADE_E0
    assert out.provenance["semi_synthetic"] is True


def test_injection_does_not_mutate_the_input_panel():
    """★순수★ 같은 패널로 여러 척도를 돌리므로 원본이 변하면 곡선이 오염된다."""
    p = _real_like()
    before = p.returns.copy()
    inject_regime_drift(p, 5.0)
    assert np.array_equal(p.returns, before)
    assert p.provenance["injected_scale"] is None


def _monthly(panel):
    from src.engine.regime_signal import monthly_matrix
    return monthly_matrix(panel.returns, panel.dates)
