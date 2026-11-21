"""스크리너 응답의 데이터 축(`data_source`) — ★관측한 것만 말하고, 모르면 `None` + 사유★
==============================================================================
대상: `src/api/screener_routes.py::_detect_data_source` · `src/data/fundamentals_store.py::attach_fundamentals`
설계: `docs/HISTORY.md` "스크리너 data_source 정직화" 절

## 예전의 셋
1. 재무를 **첫 줄 하나**의 저장소 재조회로 정했고 예외·빈 목록·빈 팩터를 모두 `"mock"` 으로 접었다.
2. 시세를 **키 유무**(`not mock_allowed() and KIS_APP_KEY`)로 추정했다 — 실제로 쓴 시세가 아니다.
3. `fully_real` 은 두 추정의 AND 였다.

## 거는 것
- 줄의 시세는 `price_is_mock`(KIS 패치 · 적재 종가에서만 `False`), 재무는 붙일 때 본 `_source` 로 판정한다.
- 응답은 그 줄들의 집계다 — 모두 실 · 모두 합성 · 섞임(`mixed`) · 미상(`None` + 사유).
- ★미상은 `"mock"` 이 아니다★(빈 목록 · 저장소 실패 · 기록 없는 줄) · ★키가 있어도 실이 아니다★(관측이 정한다).
- 라벨 함수는 저장소를 부르지 않는다(I/O 0) — 예외를 `"mock"` 으로 접을 자리가 없다.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.api.screener_routes import _detect_data_source  # noqa: E402
from src.data import fundamentals_store as fsmod  # noqa: E402
from src.data.fundamentals_store import FUND_SOURCE_ATTR, NO_FACTORS  # noqa: E402
from src.engine.screener import ScreenerItem  # noqa: E402

_UNSET = object()


def _item(code: str = "005930", *, price_is_mock=True, fundamentals_is_mock=False, fund_source=_UNSET):
    it = ScreenerItem(
        stock_code=code, corp_name=f"종목{code}", sector=None,
        current_price=10_000.0, intrinsic_value=12_000.0, gap_pct=20.0, verdict="저평가",
        composite_score=50.0, gap_score=50.0, roe_score=50.0, stability_score=50.0,
        roe_pct=10.0, roa_pct=5.0, per=10.0, pbr=1.0, debt_ratio_pct=50.0,
        dividend_yield_pct=2.0, market_cap_억=1_000.0, fcf_억=10.0,
        price_is_mock=price_is_mock, fundamentals_is_mock=fundamentals_is_mock)
    if fund_source is not _UNSET:
        setattr(it, FUND_SOURCE_ATTR, fund_source)
    return it


def _real(code: str = "005930"):
    return _item(code, price_is_mock=False, fund_source="dart_real")


def _synthetic(code: str = "005930"):
    return _item(code, price_is_mock=True, fund_source="ffl_mock")


def _gate(monkeypatch, *, on: bool, key: str | None = None):
    monkeypatch.setenv("KIS_USE_MOCK", "1" if on else "0")
    if key:
        monkeypatch.setenv("KIS_APP_KEY", key)
    else:
        monkeypatch.delenv("KIS_APP_KEY", raising=False)


# ═══════════════════════════════════════════════════════════════════════════
# 게이트 on · off(키 있음 · 없음)
# ═══════════════════════════════════════════════════════════════════════════

def test_gate_on_synthetic_rows_are_reported_as_mock_not_unknown(monkeypatch):
    _gate(monkeypatch, on=True)
    ds = _detect_data_source([_synthetic("000001"), _synthetic("000002")])
    assert ds["fundamentals"] == "mock" and ds["market_data"] == "mock"
    assert ds["fully_real"] is False, "합성을 관측했다 — 미상(None)이 아니다"
    assert ds["reason"] is None
    assert ds["mock_allowed"] is True
    assert ds["counts"]["market_data"] == {"real": 0, "mock": 2, "unknown": 0}
    assert ds["counts"]["fundamentals"] == {"real": 0, "mock": 2, "missing": 0, "unknown": 0}


def test_gate_off_with_key_and_observed_real_rows_is_fully_real(monkeypatch):
    _gate(monkeypatch, on=False, key="dummy-key")
    ds = _detect_data_source([_real("000001"), _real("000002")])
    assert ds["fundamentals"] == "dart_real" and ds["market_data"] == "kis_real"
    assert ds["fully_real"] is True
    assert ds["reason"] is None
    assert ds["mock_allowed"] is False


def test_a_key_does_not_make_an_unverified_price_real(monkeypatch):
    """★키가 있어도 실이 아니다★ — KIS 실패 줄 · 400 상한 밖 줄은 바탕 가격(합성) 그대로다."""
    _gate(monkeypatch, on=False, key="dummy-key")
    one_failed = [_real("000001"), _item("000002", price_is_mock=True, fund_source="dart_real")]
    ds = _detect_data_source(one_failed)
    assert ds["market_data"] == "mixed"
    assert ds["counts"]["market_data"] == {"real": 1, "mock": 1, "unknown": 0}
    assert ds["fully_real"] is False
    all_failed = [_item(c, price_is_mock=True, fund_source="dart_real") for c in ("000001", "000002")]
    assert _detect_data_source(all_failed)["market_data"] == "mock"


@pytest.mark.parametrize("key", [None, "dummy-key"])
def test_the_key_is_not_read_only_the_rows_are(monkeypatch, key):
    """같은 줄이면 키 유무와 무관하게 같은 답 — 키 없이 실시세가 관측된 줄(복원분)도 실이다."""
    _gate(monkeypatch, on=False, key=key)
    assert _detect_data_source([_real()])["market_data"] == "kis_real"
    assert _detect_data_source([_synthetic()])["market_data"] == "mock"


def test_gate_off_without_key_the_default_base_price_is_observed_mock(monkeypatch):
    """★운영 + 키 없음이면 바탕 가격이 합성이다(감사 F3)★ — 그것을 관측으로 말한다(추정이 아니다)."""
    _gate(monkeypatch, on=False)
    rows = [_item(c, price_is_mock=True, fund_source="dart_real") for c in ("000001", "000002", "000003")]
    ds = _detect_data_source(rows)
    assert ds["market_data"] == "mock"
    assert ds["counts"]["market_data"]["mock"] == 3
    assert ds["fundamentals"] == "dart_real"
    assert ds["fully_real"] is False


# ═══════════════════════════════════════════════════════════════════════════
# 미상 — 빈 목록 · 저장소 실패 · 기록 없는 줄 · 빈 팩터
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("on", [True, False])
def test_no_rows_is_unknown_with_a_reason_never_mock(monkeypatch, on):
    _gate(monkeypatch, on=on, key="dummy-key")
    ds = _detect_data_source([])
    assert ds["fundamentals"] is None and ds["market_data"] is None and ds["fully_real"] is None
    assert "mock" not in (ds["fundamentals"], ds["market_data"])
    assert ds["reason"] and len(ds["reason"]) > 5
    assert ds["mock_allowed"] is on, "설정은 관측과 따로 싣는다"


def test_a_store_failure_during_attach_is_unknown_not_mock(monkeypatch):
    _gate(monkeypatch, on=False, key="dummy-key")
    store = fsmod.FundamentalsStore.get_default()
    monkeypatch.setattr(store, "prime", lambda keys: None)

    def _boom(code, it=None):
        raise RuntimeError("DB 연결 실패")
    monkeypatch.setattr(store, "get_factors", _boom)
    rows = [_item(c, price_is_mock=False) for c in ("000001", "000002")]
    assert fsmod.attach_fundamentals(rows) == 0
    ds = _detect_data_source(rows)
    assert ds["fundamentals"] is None, "예외를 합성으로 접지 않는다"
    assert ds["fundamentals"] != "mock"
    assert ds["counts"]["fundamentals"]["unknown"] == 2
    assert ds["fully_real"] is None, "시세는 실이고 재무는 모른다 — 참도 거짓도 아니다"
    assert ds["reason"] and "재무" in ds["reason"]


def test_an_empty_store_result_is_missing_not_mock(monkeypatch):
    """운영에서 저장소가 `{}` 를 주면 그 종목은 재무가 **없다**(미적재) — 합성값이 쓰인 것이 아니다."""
    _gate(monkeypatch, on=False, key="dummy-key")
    store = fsmod.FundamentalsStore.get_default()
    monkeypatch.setattr(store, "prime", lambda keys: None)
    monkeypatch.setattr(store, "get_factors", lambda code, it=None: {})
    rows = [_item(c, price_is_mock=False) for c in ("000001", "000002")]
    fsmod.attach_fundamentals(rows)
    ds = _detect_data_source(rows)
    assert ds["fundamentals"] is None and ds["fundamentals"] != "mock"
    assert ds["counts"]["fundamentals"] == {"real": 0, "mock": 0, "missing": 2, "unknown": 0}
    assert ds["fully_real"] is None
    assert ds["reason"] and "재무" in ds["reason"]


def test_an_unrecorded_price_flag_is_unknown(monkeypatch):
    """옛 스냅샷에서 복원한 줄은 `price_is_mock` 이 없을 수 있다(`from_dict` → `None`)."""
    _gate(monkeypatch, on=True)
    ds = _detect_data_source([_item(price_is_mock=None, fund_source="dart_real")])
    assert ds["market_data"] is None
    assert ds["counts"]["market_data"] == {"real": 0, "mock": 0, "unknown": 1}
    assert ds["reason"] and "시세" in ds["reason"]


def test_the_label_does_no_store_io(monkeypatch):
    """★라벨 함수는 저장소를 부르지 않는다★ — 예전에는 캐시 미스마다 DART·DB 를 불렀다."""
    _gate(monkeypatch, on=False, key="dummy-key")

    def _no(*a, **k):
        raise AssertionError("라벨 함수가 저장소를 불렀다")
    monkeypatch.setattr(fsmod.FundamentalsStore, "get_default", classmethod(lambda cls: _no()))
    ds = _detect_data_source([_real("000001"), _real("000002")])
    assert ds["fully_real"] is True


# ═══════════════════════════════════════════════════════════════════════════
# 집계 — 첫 줄만이 아니다
# ═══════════════════════════════════════════════════════════════════════════

def test_every_row_counts_not_just_the_first(monkeypatch):
    _gate(monkeypatch, on=False, key="dummy-key")
    ds = _detect_data_source([_real("000001"), _item("000002", price_is_mock=False, fund_source="ffl_mock")])
    assert ds["fundamentals"] == "mixed" and ds["fully_real"] is False
    unseen_first = [_item("000001", price_is_mock=False), _real("000002")]
    ds = _detect_data_source(unseen_first)
    assert ds["fundamentals"] is None, "기록 없는 줄이 하나라도 있으면 실이라고 말하지 않는다"
    assert ds["counts"]["fundamentals"] == {"real": 1, "mock": 0, "missing": 0, "unknown": 1}


def test_gate_on_synthetic_valuation_overrides_a_real_factor_source(monkeypatch):
    """게이트 on 에서 평가 엔진이 합성 재무로 계산했으면(괴리율·판정·점수) 그 줄의 재무는 합성이다.

    ★짝★ 게이트 off 에서 같은 플래그는 '계산을 거부했다'는 뜻이라 합성값이 없다 — 저장소 출처가 정한다.
    """
    row = _item(price_is_mock=False, fundamentals_is_mock=True, fund_source="dart_real")
    _gate(monkeypatch, on=True)
    assert _detect_data_source([row])["fundamentals"] == "mock"
    _gate(monkeypatch, on=False, key="dummy-key")
    assert _detect_data_source([row])["fundamentals"] == "dart_real"


def test_known_axes_carry_no_reason_and_unknown_ones_do(monkeypatch):
    """★짝★ 아는 것에는 사유를 달지 않는다(항상-사유 · 항상-무사유 구현 배제)."""
    _gate(monkeypatch, on=False, key="dummy-key")
    assert _detect_data_source([_real()])["reason"] is None
    assert _detect_data_source([_synthetic()])["reason"] is None
    assert _detect_data_source([_real("000001"), _synthetic("000002")])["reason"] is None
    assert _detect_data_source([_item(price_is_mock=False)])["reason"]


# ═══════════════════════════════════════════════════════════════════════════
# 붙일 때 기록 — 값을 바꾸지 않고, 줄 모양도 바꾸지 않는다
# ═══════════════════════════════════════════════════════════════════════════

def test_attach_records_the_source_it_saw(monkeypatch):
    store = fsmod.FundamentalsStore.get_default()
    monkeypatch.setattr(store, "prime", lambda keys: None)
    answers = {"000001": {"roe": 11.0, "_source": "dart_real"},
               "000002": {"roe": 7.0, "_source": "ffl_mock"},
               "000003": {}}

    def _gf(code, it=None):
        if code == "000004":
            raise ValueError("boom")
        return answers[code]
    monkeypatch.setattr(store, "get_factors", _gf)
    rows = [_item(c) for c in ("000001", "000002", "000003", "000004")]
    fsmod.attach_fundamentals(rows)
    assert getattr(rows[0], FUND_SOURCE_ATTR) == "dart_real"
    assert getattr(rows[1], FUND_SOURCE_ATTR) == "ffl_mock"
    assert getattr(rows[2], FUND_SOURCE_ATTR) == NO_FACTORS
    assert not hasattr(rows[3], FUND_SOURCE_ATTR), "계산 실패는 기록하지 않는다(= 미상)"
    assert rows[0].roe == 11.0 and rows[1].roe == 7.0, "팩터 값은 그대로 붙는다"
    assert not hasattr(rows[0], "_source"), "밑줄 키는 여전히 팩터로 붙지 않는다"


def test_recording_the_source_does_not_change_the_row_shape():
    plain, marked = _item(), _item(fund_source="dart_real")
    assert FUND_SOURCE_ATTR not in marked.to_dict()
    assert marked.to_dict() == plain.to_dict()


# ═══════════════════════════════════════════════════════════════════════════
# 배선 — `/run-advanced` 본체가 이 집계를 싣는다
# ═══════════════════════════════════════════════════════════════════════════

_AST = {"logic": "AND", "conditions": [], "groups": []}


def test_the_run_advanced_payload_carries_the_rollup(monkeypatch):
    from src.api import screener_routes as sr
    from src.engine.screener import ScreenerResult

    rows = [_real("000001"), _item("000002", price_is_mock=False)]

    class _Fake:
        def run(self, **kw):
            return ScreenerResult(universe="kospi200", total_evaluated=2, total_passed=2, items=rows,
                                  elapsed_seconds=0.0, cache_hits=0, cache_misses=0, failures=0)
    monkeypatch.setattr(sr, "get_screener", lambda: _Fake())
    sr._RUN_ADVANCED_CACHE.clear()
    try:
        out = sr._run_advanced_core(sr.AdvancedRunRequest(filter_ast=_AST, universe="kospi200"))
    finally:
        sr._RUN_ADVANCED_CACHE.clear()
    ds = out["data_source"]
    assert ds["market_data"] == "kis_real"
    assert ds["fundamentals"] is None and ds["fully_real"] is None
    assert ds["counts"]["fundamentals"]["unknown"] == 1
