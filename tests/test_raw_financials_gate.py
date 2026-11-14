"""원천 재무(`get_raw_financials`)는 ★운영에서 합성값을 돌려주지 않는다★ (2026-11-14 · 합성값 전수 감사 §3)

## 무엇이 문제였나

`FundamentalsStore.get_raw_financials` 는 실데이터가 없으면 ★게이트 없이★ `_mock_raw_financials` 로 넘어갔다
(`real or mock`). 같은 스토어의 `get_factors` 는 게이트를 지나는데 이 공개 함수만 빠져 있었다.

관측(운영 게이트 · 키 없음 · 빈 DB): `get_raw_financials("005930")` → 시총 21,091억 · 매출 43,116억(난수 26회).
그 값을 읽는 자리 — 확장 팩터의 실공식 파생(원가율·재고회전율 …) · 기업 화면의 시총과 Altman 분해 · 회전율 ·
조건식 백테스트의 원천 금액 토큰. `GET /api/v1/screener/peer-groups` 한 번에 난수 1,300회(50종목 × 26).

## 이 파일이 거는 계약

① 운영에서 실데이터가 없으면 ★빈값★이다 — 난수 원시 함수가 한 번도 불리지 않는다.
② mock 에서는 그대로 합성값이다(짝 — 항상 비우는 구현을 배제).
③ 운영에서 실데이터가 있으면 그 값 그대로다(짝 — 운영이면 무조건 비우는 구현을 배제).
④ 빈값은 오래 붙잡지 않는다 — 적재가 되면 다음 재시도에서 실데이터가 나온다.
⑤ 게이트가 없던 때 영속된 합성 원천은 운영에서 읽지 않는다(자가 치유).
⑥ 소비자가 조용해진다 — 확장 팩터 파생 · 기업 화면 시총.
"""
from __future__ import annotations

import pytest

from src.data import mock_base
from src.data.extended_factors_store import ExtendedFactorsStore
from src.data.fundamentals_store import FundamentalsStore

CODE = "005930"
#: 실데이터 경로가 돌려주는 모양(일부) — `_source` 가 실데이터 표식이다.
REAL = {"market_cap": 4_000_000.0, "revenue": 3_000_000.0, "total_assets": 5_000_000.0, "_source": "dart_real"}


@pytest.fixture
def store(monkeypatch):
    """새 스토어 하나 — 실데이터 경로는 '없음'으로 시작하고, DB 영속은 끈다(이 시험의 대상이 아니다)."""
    st = FundamentalsStore()
    st._real = None
    monkeypatch.setattr(st, "_real_raw_financials", lambda code, item=None: st._real)
    monkeypatch.setattr(st, "_persist_on", lambda: False)
    monkeypatch.setattr(FundamentalsStore, "_singleton", st)
    return st


@pytest.fixture
def rng_calls(monkeypatch):
    """합성 원시 함수(`_rng`)가 불린 횟수 — 값이 아니라 ★만들었는가★를 본다."""
    calls: list[tuple] = []
    real = mock_base.DeterministicMockStore._rng

    def spy(self, *keys):
        calls.append(keys)
        return real(self, *keys)

    monkeypatch.setattr(mock_base.DeterministicMockStore, "_rng", spy)
    return calls


def _prod(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "0")


def _mock(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")


# ══ ① 운영 — 만들지 않는다 ════════════════════════════════════════════════════

def test_prod_without_real_data_returns_nothing(store, rng_calls, monkeypatch):
    _prod(monkeypatch)
    assert store.get_raw_financials(CODE) == {}


def test_prod_without_real_data_never_touches_the_synthetic_primitive(store, rng_calls, monkeypatch):
    """값이 비었는지만 보면 '만든 뒤 버리는' 구현이 통과한다 — 만드는 일 자체가 없어야 한다."""
    _prod(monkeypatch)
    store.get_raw_financials(CODE)
    assert rng_calls == [], f"운영에서 합성 원시 함수를 {len(rng_calls)}회 불렀다"


@pytest.mark.parametrize("value", ["", "0", "true", "TRUE", "2", " 1"])
def test_anything_but_exactly_one_is_prod(store, rng_calls, monkeypatch, value):
    """게이트는 `KIS_USE_MOCK` 이 정확히 "1" 일 때만 연다(CLAUDE.md §6) — 이 자리도 같은 판정을 쓴다."""
    monkeypatch.setenv("KIS_USE_MOCK", value)
    assert store.get_raw_financials(CODE) == {}
    assert rng_calls == []


# ══ ② mock — 그대로 만든다(짝) ════════════════════════════════════════════════

def test_mock_still_returns_synthetic_financials(store, rng_calls, monkeypatch):
    _mock(monkeypatch)
    raw = store.get_raw_financials(CODE)
    assert raw.get("revenue", 0) > 0 and raw.get("market_cap", 0) > 0
    assert rng_calls, "mock 인데 합성 원시 함수를 부르지 않았다 — 시험이 공허하다"


def test_mock_values_are_not_served_after_the_gate_closes(store, rng_calls, monkeypatch):
    """같은 스토어에서 mock 으로 만든 값이 운영으로 바뀐 뒤 나오면 안 된다(캐시 누수)."""
    _mock(monkeypatch)
    assert store.get_raw_financials(CODE)
    _prod(monkeypatch)
    assert store.get_raw_financials(CODE) == {}


# ══ ③ 운영 + 실데이터 — 그 값 그대로(짝) ══════════════════════════════════════

def test_prod_with_real_data_returns_it_unchanged(store, rng_calls, monkeypatch):
    _prod(monkeypatch)
    store._real = dict(REAL)
    assert store.get_raw_financials(CODE) == REAL


# ══ ④ 빈값을 오래 붙잡지 않는다 ═══════════════════════════════════════════════

def test_real_data_appears_after_the_empty_retry_window(store, monkeypatch):
    """적재 전에 한 번 비었다고 여섯 시간 동안 비어 있으면 안 된다 — 빈 결과의 재시도 간격만 붙잡는다."""
    _prod(monkeypatch)
    now = [1_000_000.0]
    monkeypatch.setattr(mock_base.time, "time", lambda: now[0])
    assert store.get_raw_financials(CODE) == {}
    store._real = dict(REAL)
    assert store.get_raw_financials(CODE) == {}, "재시도 간격 안에서는 다시 만들지 않는다"
    now[0] += mock_base.EMPTY_RETRY_TTL + 1
    assert store.get_raw_financials(CODE) == REAL


# ══ ⑤ 예전에 영속된 합성 원천 — 운영에서 읽지 않는다 ══════════════════════════

def _persisted(monkeypatch, store, value: dict) -> list:
    """DB 영속 캐시에 `value` 가 들어 있는 상황을 만든다. 돌려주는 목록에 쓰기가 기록된다."""
    from src.data import snapshot_db
    writes: list = []
    monkeypatch.setattr(store, "_persist_on", lambda: True)
    monkeypatch.setattr(snapshot_db, "bulk_read", lambda keys, ttl: {k: dict(value) for k in keys})
    monkeypatch.setattr(snapshot_db, "write", lambda k, v: writes.append((k, v)))
    return writes


def _stale_synthetic(monkeypatch, store) -> dict:
    """게이트가 없던 때 운영 DB 에 남았을 값 — mock 원천(실데이터 표식이 없다)."""
    _mock(monkeypatch)
    stale = store._mock_raw_financials(CODE)
    assert stale.get("_source") != "dart_real" and stale["revenue"] > 0
    return stale


def test_a_persisted_synthetic_raw_is_not_served_in_prod(store, monkeypatch):
    stale = _stale_synthetic(monkeypatch, store)
    _prod(monkeypatch)
    _persisted(monkeypatch, store, stale)
    assert store.get_raw_financials(CODE) == {}


def test_a_persisted_synthetic_raw_is_replaced_once_real_data_exists(store, monkeypatch):
    stale = _stale_synthetic(monkeypatch, store)
    _prod(monkeypatch)
    writes = _persisted(monkeypatch, store, stale)
    store._real = dict(REAL)
    assert store.get_raw_financials(CODE) == REAL
    assert writes and writes[-1][1] == REAL, "실데이터로 덮어쓰지 않았다 — 다음 프로세스가 다시 합성값을 읽는다"


def test_a_persisted_real_raw_is_served_as_is(store, monkeypatch):
    """짝 — 영속된 것을 전부 버리면 영속 캐시가 무의미해진다. 실데이터 표식이 있는 것은 그대로 읽는다."""
    _prod(monkeypatch)
    _persisted(monkeypatch, store, REAL)
    store._real = {"market_cap": 1.0, "_source": "dart_real"}      # 다시 만들었다면 이 값이 나온다
    assert store.get_raw_financials(CODE) == REAL


# ══ ⑥ 소비자 ══════════════════════════════════════════════════════════════════

def _ext(monkeypatch) -> ExtendedFactorsStore:
    ext = ExtendedFactorsStore()
    monkeypatch.setattr(ext, "_persist_on", lambda: False)
    monkeypatch.setattr(ext, "_real_dividend", lambda code: {})
    return ext


def test_extended_factors_derive_nothing_from_absent_financials_in_prod(store, rng_calls, monkeypatch):
    """관측: 고치기 전 운영에서 `cogs_ratio 60.83 · inv_turnover 2.55 …` 가 나왔다(원천이 합성이었다)."""
    _prod(monkeypatch)
    out = _ext(monkeypatch).get_factors(CODE)
    values = {k: v for k, v in out.items() if not k.startswith("_")}
    assert values == {}, f"원천 재무가 없는데 파생 팩터가 나왔다: {sorted(values)[:6]}"
    assert rng_calls == []


def test_extended_factors_still_derive_from_real_financials_in_prod(store, monkeypatch):
    """짝 — 운영에서 파생을 통째로 끄는 구현을 배제한다."""
    _prod(monkeypatch)
    store._real = {**REAL, "operating_profit": 400_000.0}
    out = _ext(monkeypatch).get_factors(CODE)
    assert out.get("por") == round(REAL["market_cap"] / 400_000.0, 2)


def test_company_market_cap_is_unknown_without_financials_in_prod(store, monkeypatch):
    from src.engine.company_analytics import _mcap
    _prod(monkeypatch)
    assert _mcap(CODE) is None
    store.cache_clear()
    store._real = dict(REAL)
    assert _mcap(CODE) == REAL["market_cap"]
