"""★출처 라벨은 사실보다 강할 수 없다★ — 가치평가 기본 가정 Rf·β 의 출처 (BL3 W3-0)
==============================================================================
감사 실측(2026-09-26): `company_analytics.resolve_default_params` 는 Rf 가 0<v<0.15 면 무조건 "ECOS 국고채 10년 (실시간)" 이라
적었다. 그런데 `get_dynamic_risk_free_rate()` 는 실패하면 0.035 를, 국면 상태는 `KR_10Y` 가 없으면 0.035 를 돌려준다 —
**기본값이 '실시간'으로 둔갑**했다. mock 모드의 합성 `KR_10Y` 도 '실시간'이었다. β 도 mock 모드 합성값이 "KIS 1년 실측" 이었다.

고친 것은 **라벨뿐**이다 — Rf·β 의 **값**과 `get_dynamic_risk_free_rate()` 의 의미(킬스위치·밸류에이션 소비자)는 그대로다.
"""
from __future__ import annotations

import dataclasses
import os

import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.engine import company_analytics as ca  # noqa: E402
from src.engine import regime_analyzer as ra  # noqa: E402


def _mock_snapshot():
    from src.services.macro_collector import MacroCollector
    return MacroCollector().collect_all(use_cache=False)


# ══ 국면 상태가 Rf 의 출처를 함께 싣는다 ══════════════════════════════════════

def test_regime_state_carries_the_source_of_the_risk_free_rate(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    snap = _mock_snapshot()
    st = ra.RegimeAnalyzer().analyze(snap)
    assert snap.series["KR_10Y"].source == "MOCK"
    assert st.dynamic_risk_free_rate_source == "MOCK"
    assert st.dynamic_risk_free_rate == pytest.approx(snap.series["KR_10Y"].latest / 100)


def test_a_bok_series_is_named_bok(monkeypatch):
    snap = _mock_snapshot()
    snap.series["KR_10Y"] = dataclasses.replace(snap.series["KR_10Y"], source="BOK")
    assert ra.RegimeAnalyzer().analyze(snap).dynamic_risk_free_rate_source == "BOK"


def test_without_kr10y_the_rate_is_the_default_and_says_so():
    snap = _mock_snapshot()
    snap.series.pop("KR_10Y")
    st = ra.RegimeAnalyzer().analyze(snap)
    assert st.dynamic_risk_free_rate == 0.035          # 값은 그대로(소비자 불변)
    assert st.dynamic_risk_free_rate_source == "default"


def test_the_helper_reports_default_when_the_state_fails_and_the_old_function_is_unchanged(monkeypatch):
    monkeypatch.setattr(ra, "get_regime_state", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    assert ra.get_dynamic_risk_free_rate_with_source() == (0.035, "default")
    # 짝: 기존 함수의 값·의미는 그대로다
    assert ra.get_dynamic_risk_free_rate() == 0.035


# ══ 가치평가 기본 가정의 라벨 ═════════════════════════════════════════════════

@pytest.fixture()
def no_beta(monkeypatch):
    from src.data.price_factors_store import PriceFactorsStore

    class _S:
        def get_factors(self, code):
            return {}
    monkeypatch.setattr(PriceFactorsStore, "get_default", classmethod(lambda cls: _S()))


def _rf(monkeypatch, value, source):
    monkeypatch.setattr(ra, "get_dynamic_risk_free_rate_with_source", lambda: (value, source))
    return ca.resolve_default_params("005930")


def test_an_observed_bok_rate_is_labelled_as_an_observation(monkeypatch, no_beta):
    p = _rf(monkeypatch, 0.0412, "BOK")
    assert p["rf"] == 0.0412
    assert "ECOS" in p["rf_source"] and "실시간" not in p["rf_source"]


def test_a_default_rate_is_never_labelled_as_ecos(monkeypatch, no_beta):
    """★핵심★ 예전에는 0.035 기본값이 'ECOS 국고채 10년 (실시간)' 이었다."""
    p = _rf(monkeypatch, 0.035, "default")
    assert p["rf"] == 0.035
    assert "기본값" in p["rf_source"] and "ECOS" not in p["rf_source"]


def test_a_mock_rate_is_labelled_as_practice(monkeypatch, no_beta):
    p = _rf(monkeypatch, 0.0457, "MOCK")
    assert p["rf"] == 0.0457
    assert "연습용" in p["rf_source"] and "ECOS" not in p["rf_source"]


def test_an_out_of_range_rate_still_falls_back_to_the_default_label(monkeypatch, no_beta):
    p = _rf(monkeypatch, 0.4, "BOK")
    assert p["rf"] == 0.035 and "기본값" in p["rf_source"]


def _beta(monkeypatch, factors, mock):
    from src.data.price_factors_store import PriceFactorsStore

    class _S:
        def get_factors(self, code):
            return factors
    monkeypatch.setattr(PriceFactorsStore, "get_default", classmethod(lambda cls: _S()))
    monkeypatch.setattr(ra, "get_dynamic_risk_free_rate_with_source", lambda: (0.035, "default"))
    monkeypatch.setenv("KIS_USE_MOCK", "1" if mock else "0")
    return ca.resolve_default_params("005930")


def test_a_beta_in_mock_mode_is_practice(monkeypatch):
    p = _beta(monkeypatch, {"beta_1y": 1.2}, mock=True)
    assert p["beta"] == 1.2
    assert "연습용" in p["beta_source"] and "KIS" not in p["beta_source"]


def test_a_beta_outside_mock_mode_is_measured_from_daily_prices(monkeypatch):
    p = _beta(monkeypatch, {"beta_1y": 1.2}, mock=False)
    assert p["beta"] == 1.2
    assert "실측" in p["beta_source"] and "연습용" not in p["beta_source"]


def test_a_missing_beta_is_the_default(monkeypatch):
    p = _beta(monkeypatch, {}, mock=False)
    assert p["beta"] == 1.0 and p["beta_source"] == "기본값"


def test_golden_the_values_are_what_the_old_code_would_have_used(monkeypatch):
    """라벨만 바뀌었다 — Rf 는 여전히 `get_dynamic_risk_free_rate()` 를 4자리로 반올림한 값이다(기본값이면 0.035)."""
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    p = ca.resolve_default_params("005930")
    v = ra.get_dynamic_risk_free_rate()
    assert p["rf"] == (round(v, 4) if 0 < v < 0.15 else 0.035)
