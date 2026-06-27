"""매크로(택티컬) 백테스트 data_source 정직성 — 키 유무가 아니라 실제 사용한 시세 기준."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.engine.strategy_backtest_map import _ds, _market_data_real  # noqa: E402


def test_ds_reflects_market_real_flag():
    assert _ds(False)["fully_real"] is False
    assert _ds(False)["market_data"] == "mock"
    assert _ds(True)["fully_real"] is True
    assert _ds(True)["market_data"] == "kis_real"


def test_market_data_real_false_in_mock_mode(monkeypatch):
    # 샌드박스(KIS_USE_MOCK=1) + 키가 있어도 실제 시세는 mock → False (정직)
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    monkeypatch.setenv("KIS_APP_KEY", "dummy-key")
    assert _market_data_real([{"us_ticker": "SPY"}], "us") is False


def test_market_data_real_false_without_key(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    monkeypatch.delenv("KIS_APP_KEY", raising=False)
    assert _market_data_real([{"us_ticker": "SPY"}], "us") is False


def test_market_data_real_empty_holdings():
    assert _market_data_real([], "kr") is False
    assert _market_data_real(None, "kr") is False
