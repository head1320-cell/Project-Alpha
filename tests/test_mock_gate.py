"""실데이터 전용 게이트 — mock_allowed()는 명시적 KIS_USE_MOCK=1에서만 True."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.data.mock_gate import mock_allowed  # noqa: E402


def test_default_is_mock(monkeypatch):
    monkeypatch.delenv("KIS_USE_MOCK", raising=False)
    assert mock_allowed() is True   # 기본=mock(개발 안전)


def test_explicit_mock(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    assert mock_allowed() is True


def test_real_mode_forbids_mock(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    assert mock_allowed() is False  # 운영 → 합성 금지


def test_other_values_forbid_mock(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "false")
    assert mock_allowed() is False
