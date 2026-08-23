"""시가총액 "—" 해결 — KIS master(load_master_flags)에서 market_cap_억 조회. 합성 안 함."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import src.data.stock_master as sm  # noqa: E402


def test_get_market_cap_from_master(monkeypatch):
    monkeypatch.setattr(sm, "_MASTER_FLAGS", {"005930": {"market_cap_억": 5_000_000}, "000660": {}})
    assert sm.get_market_cap("005930") == 5_000_000.0
    assert sm.get_market_cap("000660") is None   # 시총 필드 없음 → 정직 None(합성 금지)
    assert sm.get_market_cap("999999") is None    # 미등록 → None


def test_get_market_cap_zero_is_none(monkeypatch):
    monkeypatch.setattr(sm, "_MASTER_FLAGS", {"123450": {"market_cap_억": 0}})
    assert sm.get_market_cap("123450") is None    # 0/음수는 무효 → None


def test_get_market_cap_no_master(monkeypatch):
    monkeypatch.setattr(sm, "_MASTER_FLAGS", {})  # master 미적재(샌드박스)
    assert sm.get_market_cap("005930") is None    # 합성 안 함 — None
