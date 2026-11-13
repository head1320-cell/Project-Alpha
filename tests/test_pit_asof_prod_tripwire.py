"""운영의 시점(as_of) 평가는 합성값을 만들지 않는다 — ★트립와이어였던 것★(2026-11-12) → 계약(2026-11-13 고침).

감사: `docs/specs/2026-11-12-pit-asof-prod-synthetic-audit.md` (F1 · F2 · F2b · 고침은 §7 A안).

2026-11-12 에는 되어야 하는 동작을 `xfail(strict=True)` 로 적어 두었다(부채가 시험 결과에 보이게). 2026-11-13 에 고치면서
표식을 뗐다 — 이제 보통의 시험이다. 파일 이름은 기록을 잇기 위해 그대로 둔다. 가격(F1)의 자세한 계약과 캐시 혼선(F4·F5)은
`tests/test_pit_asof_real_close.py` 에 있다.

짝: mock 모드에서는 같은 계약이 처음부터 지켜졌다 — 계약 자체가 불가능한 것이 아니다.
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

def test_prod_as_of_financials_are_absent_when_the_filing_cannot_be_read(prod, monkeypatch):
    """못 읽었으면 여덟 칸은 None 이어야 한다 — 현재 값을 흔들어 과거 값처럼 내면 안 된다."""
    s = _store()
    monkeypatch.setattr(s, "_dart_snapshot", lambda *a, **k: None)
    snap = s.get_financials_asof("005930", "2024-06-28", dict(_CUR))
    assert [k for k in _FIN_KEYS if snap.get(k) is not None] == []
    assert snap["_source"] == "pit_unavailable" and snap["_reason"]      # 없음 + 사유(사유 없는 "unavailable" 금지 — CLAUDE.md §4)


def test_mock_as_of_financials_are_still_the_labelled_mock_walk(mock, monkeypatch):
    """★짝★ — mock 은 그대로 `pit_mock` 이다(운영 고침이 mock 을 바꾸지 않았다 · 늘 None 인 구현이 아니다)."""
    s = _store()
    monkeypatch.setattr(s, "_dart_snapshot", lambda *a, **k: None)
    snap = s.get_financials_asof("005930", "2024-06-28", dict(_CUR))
    assert snap["_source"] == "pit_mock" and all(snap[k] is not None for k in _FIN_KEYS)


def test_the_reason_tells_a_missing_key_from_an_unreadable_filing(prod, monkeypatch):
    """미적재·키 없음과 '키는 있는데 못 읽음'은 다른 사유다(미적재 ≠ 제공자 미지원)."""
    import src.data.dart_client as dc
    s = _store()
    monkeypatch.setattr(s, "_dart_snapshot", lambda *a, **k: None)
    monkeypatch.setattr(dc, "DARTClient", type("NoKey", (), {"is_configured": False}))
    a = s.get_financials_asof("005930", "2024-06-28", dict(_CUR))["_reason"]
    s2 = _store()
    monkeypatch.setattr(s2, "_dart_snapshot", lambda *a, **k: None)
    monkeypatch.setattr(dc, "DARTClient", type("Key", (), {"is_configured": True}))
    b = s2.get_financials_asof("005930", "2024-06-28", dict(_CUR))["_reason"]
    assert a == "no_dart_key" and b == "filing_unreadable"


def test_a_readable_filing_is_passed_through_untouched(prod, monkeypatch):
    """★짝★ — 공시를 읽었으면 그 값 그대로다(흔들지 않는다). 위 시험이 '늘 None' 구현으로 통과하지 않게."""
    s = _store()
    real = {"roe_pct": 7.7, "per": 9.9, "_source": "pit_dart"}
    monkeypatch.setattr(s, "_dart_snapshot", lambda *a, **k: dict(real))
    snap = s.get_financials_asof("005930", "2024-06-28", dict(_CUR))
    assert snap["roe_pct"] == 7.7 and snap["per"] == 9.9 and snap["_source"] == "pit_dart"


# ── F2b — 항목에 실리는 값과 라벨 ────────────────────────────────────────────

def _item(is_mock=False):
    from src.engine.screener import ScreenerItem
    item = object.__new__(ScreenerItem)
    for k, v in _CUR.items():
        setattr(item, k, v)
    item.fundamentals_is_mock = is_mock
    return item


def _apply(store, monkeypatch, item):
    import src.engine.pit_store as ps
    from src.engine.screener import ValuationScreener
    monkeypatch.setattr(ps.PITStore, "get_default", classmethod(lambda cls: store))
    return ValuationScreener._apply_pit_financials(object.__new__(ValuationScreener), item, "005930", "2024-06-28")


def test_prod_item_fields_are_unknown_not_todays_values_when_the_filing_cannot_be_read(prod, monkeypatch):
    """못 읽었으면 여덟 칸은 ★미상(None)★ 이다 — 흔든 값도 아니고, 오늘 값을 과거 값처럼 남긴 것도 아니다."""
    s = _store()
    monkeypatch.setattr(s, "_dart_snapshot", lambda *a, **k: None)
    out = _apply(s, monkeypatch, _item())
    assert [k for k in _FIN_KEYS if getattr(out, k) is not None] == []
    assert out.fundamentals_is_mock is False                          # None 은 합성이 아니다 — 합성 라벨을 붙이지 않는다
    assert out.asof_financials == {"available": False, "reason": "no_dart_key"} or out.asof_financials["reason"] == "filing_unreadable"


def test_an_item_filled_from_a_manufactured_snapshot_is_labelled_so(mock, monkeypatch):
    """값이 합성이면 라벨도 합성이다 — 실데이터 라벨을 단 합성값은 '동등 품질 위장'이다(CLAUDE.md §4).
    (2026-11-13: 합성 스냅샷은 이제 mock 모드에서만 나온다 — 현재 재무가 실데이터였던 항목도 라벨이 따라 바뀐다.)"""
    s = _store()
    monkeypatch.setattr(s, "_dart_snapshot", lambda *a, **k: None)
    out = _apply(s, monkeypatch, _item(is_mock=False))
    assert [k for k in _FIN_KEYS if getattr(out, k) != _CUR[k]] != [] and out.fundamentals_is_mock is True


def test_an_item_filled_from_a_real_filing_keeps_the_real_label(prod, monkeypatch):
    """★짝★ — 읽은 공시로 채운 항목은 합성 라벨을 받지 않는다(늘 합성이라 하는 구현이 아니다)."""
    s = _store()
    monkeypatch.setattr(s, "_dart_snapshot", lambda *a, **k: {"roe_pct": 7.7, "per": 9.9, "_source": "pit_dart"})
    out = _apply(s, monkeypatch, _item())
    assert out.roe_pct == 7.7 and out.per == 9.9 and out.fundamentals_is_mock is False
    # 2026-11-13(감사 §12): 공시가 주지 않은 여섯 칸은 ★미상★이다 — 오늘 값을 과거 값처럼 남기지 않고, 걷어 낸 칸을 싣는다.
    missing = [k for k in _FIN_KEYS if k not in ("roe_pct", "per")]
    assert [getattr(out, k) for k in missing] == [None] * 6
    assert out.asof_financials == {"available": True, "missing": missing}
