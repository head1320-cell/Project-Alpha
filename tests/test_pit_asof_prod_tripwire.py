"""★트립와이어★ — 운영의 시점(as_of) 평가가 합성값을 만든다.

감사: `docs/specs/2026-11-12-pit-asof-prod-synthetic-audit.md` (F1 · F2 · F2b).

여기 시험은 ★되어야 하는 동작★을 적고 `xfail(strict=True)` 로 표시한다. 지금은 예상대로 실패하고(부채가
시험 결과에 보인다), 고치는 날 strict 가 "예상과 달리 통과"를 실패로 바꿔 ★표식을 떼라고★ 알린다.
이 파일은 `src` 를 바꾸지 않는다 — 고침은 운영 동작 변경이라 별도 승인 사항이다.
`raises=AssertionError` — 단언이 아닌 다른 오류(import 실패 등)는 예상된 실패로 숨지 않고 그대로 빨갛다.

짝(지금 통과): mock 모드에서는 같은 계약이 이미 지켜진다 — 계약 자체가 불가능한 것이 아니다.
"""
from __future__ import annotations

import pytest

_FIN_KEYS = ("roe_pct", "roa_pct", "per", "pbr", "debt_ratio_pct", "dividend_yield_pct", "fcf_억", "market_cap_억")
_CUR = {"roe_pct": 10.0, "roa_pct": 5.0, "per": 12.0, "pbr": 1.2, "debt_ratio_pct": 80.0,
        "dividend_yield_pct": 2.0, "fcf_억": 1000.0, "market_cap_억": 50000.0}


def _store():
    from src.engine.pit_store import PITStore
    return PITStore()       # 기본 싱글턴을 건드리지 않는다(캐시가 다른 시험에 새지 않게)


@pytest.fixture
def prod(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "0")


@pytest.fixture
def mock(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")


# ── F1 — 시점 가격 ───────────────────────────────────────────────────────────

@pytest.mark.xfail(strict=True, raises=AssertionError, reason="F1: 운영 get_price_asof 가 현재가 × 추세 × 난수를 과거 종가로 낸다 (감사 §2)")
def test_prod_as_of_price_does_not_follow_the_price_passed_in(prod):
    """과거 종가는 '넘겨받은 현재가'의 함수가 아니다. 읽을 수 없으면 값이 없어야 한다(None + 사유)."""
    s = _store()
    a = s.get_price_asof("005930", "2024-06-28", 71000.0)
    b = s.get_price_asof("005930", "2024-06-28", 50000.0)
    assert a is None or a == b


def test_mock_as_of_price_does_not_follow_the_price_passed_in(mock):
    """★짝★ — mock 은 이미 그렇다(2026-11-11): 그 날의 mock 종가라 넘겨받은 현재가와 무관하다."""
    s = _store()
    assert s.get_price_asof("005930", "2024-06-28", 71000.0) == s.get_price_asof("005930", "2024-06-28", 50000.0)


# ── F2 — 시점 재무 ───────────────────────────────────────────────────────────

@pytest.mark.xfail(strict=True, raises=AssertionError, reason="F2: 그 시점 공시를 못 읽으면 운영에서도 현재 재무를 흔든 값(pit_mock)을 낸다 (감사 §3)")
def test_prod_as_of_financials_are_absent_when_the_filing_cannot_be_read(prod, monkeypatch):
    """못 읽었으면 여덟 칸은 None 이어야 한다 — 현재 값을 흔들어 과거 값처럼 내면 안 된다."""
    s = _store()
    monkeypatch.setattr(s, "_dart_snapshot", lambda *a, **k: None)
    snap = s.get_financials_asof("005930", "2024-06-28", dict(_CUR))
    assert [k for k in _FIN_KEYS if snap.get(k) is not None] == []


def test_a_readable_filing_is_passed_through_untouched(prod, monkeypatch):
    """★짝★ — 공시를 읽었으면 그 값 그대로다(흔들지 않는다). 위 시험이 '늘 None' 구현으로 통과하지 않게."""
    s = _store()
    real = {"roe_pct": 7.7, "per": 9.9, "_source": "pit_dart"}
    monkeypatch.setattr(s, "_dart_snapshot", lambda *a, **k: dict(real))
    snap = s.get_financials_asof("005930", "2024-06-28", dict(_CUR))
    assert snap["roe_pct"] == 7.7 and snap["per"] == 9.9 and snap["_source"] == "pit_dart"


# ── F2b — 합성 스냅샷을 넣고도 라벨은 실데이터 ────────────────────────────────

@pytest.mark.xfail(strict=True, raises=AssertionError, reason="F2b: 합성 스냅샷을 항목에 덮어 쓰고도 fundamentals_is_mock 이 False 로 남는다 (감사 §3)")
def test_an_item_filled_from_a_manufactured_snapshot_is_labelled_so(prod, monkeypatch):
    """값이 합성이면 라벨도 합성이어야 한다 — 실데이터 라벨을 단 합성값은 '동등 품질 위장'이다(CLAUDE.md §4)."""
    import src.engine.pit_store as ps
    from src.engine.screener import ScreenerItem, ValuationScreener
    s = _store()
    monkeypatch.setattr(s, "_dart_snapshot", lambda *a, **k: None)
    monkeypatch.setattr(ps.PITStore, "get_default", classmethod(lambda cls: s))
    item = object.__new__(ScreenerItem)
    for k, v in _CUR.items():
        setattr(item, k, v)
    item.fundamentals_is_mock = False                       # 현재 재무는 실데이터였다
    out = ValuationScreener._apply_pit_financials(object.__new__(ValuationScreener), item, "005930", "2024-06-28")
    changed = [k for k in _FIN_KEYS if getattr(out, k) != _CUR[k]]
    assert changed == [] or out.fundamentals_is_mock is True
