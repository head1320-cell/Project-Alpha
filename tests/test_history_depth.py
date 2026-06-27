"""과거 데이터 적재 깊이 — 매크로(BOK/FRED) 깊이 env화(5년 하드코딩 제거)."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import src.services.macro_collector as mc  # noqa: E402


def test_macro_history_years_default(monkeypatch):
    monkeypatch.delenv("MACRO_HISTORY_YEARS", raising=False)
    assert mc._history_years() == 15   # 기본 15년 (BOK/FRED는 수십 년 제공)


def test_macro_history_years_override(monkeypatch):
    monkeypatch.setenv("MACRO_HISTORY_YEARS", "25")
    assert mc._history_years() == 25


def test_macro_history_years_bad_value_fallback(monkeypatch):
    monkeypatch.setenv("MACRO_HISTORY_YEARS", "oops")
    assert mc._history_years() == 15   # 잘못된 값 → 기본 폴백
