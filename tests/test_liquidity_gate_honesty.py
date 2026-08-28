"""유동성 게이트 — ★운영에서 합성값으로 유니버스를 자르고 있었다★
==============================================================================
감사: `docs/specs/2026-08-27-feature-layer-mock-audit.md`

## 무엇이 망가져 있었나

CLAUDE.md 의 하드 불변식:

> **mock 게이트** — `mock_allowed()` 가 유일한 판정 기준이며 `KIS_USE_MOCK` 이
> 정확히 `"1"` 일 때만 mock. 운영에서 조회가 실패하면 합성값으로 가리지 말고
> 정직하게 `None`/빈값을 반환할 것.

`liquidity_gate` 는 이 게이트를 **한 번도 부르지 않았다**(실측: `mock_allowed`
0회). `_build_liquidity` 가 `KIS_USE_MOCK` 과 무관하게 거래대금·스프레드·거래가능
여부를 `self._uniform(...)` 으로 만들었고, 운영과 개발의 출력이 **완전히 동일**했다.

그리고 그 값이 유니버스를 정했다 — `screener.py` 가 **모든 필터보다 먼저**,
**기본 프로파일 `standard`(ADV≥10억·시총≥1000억·스프레드≤0.5%)로 켜진 채**
게이트를 돌린다. 특히:

```python
tradable = self._uniform(stock_code, "halt") > 0.1   # 소형주 10% 무작위 비거래
```

실측 — 시총 300억 종목 200개 중 **13개가 종목코드 MD5 해시로 "거래정지"** 판정을
받아 조용히 사라졌다.

## 고칠 재료는 이미 있었다 (고아 능력)

`price_factors_store.amount_20d_avg`("20일 평균거래대금", 억)는 사전적재 일봉에서
계산되고 **이미 mock 게이트를 지킨다**(키 없으면 `None`). 게이트는 한 모듈 옆에서
정직하게 유도되는 그 숫자를 무시하고 스스로 날조했다. 거래정지도 마찬가지로
`stock_master` 마스터 플래그가 있다. ★스프레드만 진짜 원천이 없다.★

## ★잠복 결함 하나가 이 변경으로 드러났다★

`passes_liquidity` 의 `not liq_data.get("is_tradable", True)` 는 키가 **없을 때만**
기본값을 쓴다. 키가 있고 값이 `None` 이면 `None` 을 돌려주고 `not None` 은 `True`
라 **전부 배제**된다. 나머지 세 조건은 전부 `is not None` 으로 미상을 건너뛰는데
여기만 달랐고, 합성 경로에서는 항상 bool 이라 드러나지 않았다.

## 짝 검증

L1/L5 · L7/L8 · L10/L11 — 한쪽만 있으면 "전부 None" · "전부 통과" · "전부 skipped"
구현으로도 통과한다.
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402

import src.engine.liquidity_gate as lg  # noqa: E402

#: 리팩터링 **직전** 실측한 mock 값 — L5 가 이것으로 "이름만 옮겼음" 을 못 박는다.
MOCK_BASELINE = {
    "005930": {"adv_value_억": 87.5, "market_cap_억": 10448.9,
               "spread_pct": 0.111, "is_tradable": True},
    "000660": {"adv_value_억": 8.5, "market_cap_억": 6038.9,
               "spread_pct": 0.572, "is_tradable": True},
    "035720": {"adv_value_억": 17.8, "market_cap_억": 16517.0,
               "spread_pct": 0.036, "is_tradable": True},
}
#: mock 모드에서 `standard` 를 통과하던 종목 수(1000~1199 · 시총 미상).
MOCK_PASSED_COUNT = 145
SMALL_CAPS = [f"{i:06d}" for i in range(1000, 1200)]


class _Item:
    def __init__(self, code, mcap=None):
        self.stock_code, self.market_cap_억 = code, mcap


def _clear_caches():
    """게이트 캐시 + ★상류 가격 팩터 캐시★

    상류를 비우는 이유가 있다 — `PriceFactorsStore._cache` 는 키가
    `price_factors:{code}` 라 **어느 모드에서 만들어졌는지 기록하지 않는다**.
    앞선 테스트가 mock 모드에서 데워 두면 운영 경로가 그 합성값을 그대로 받는다
    (실측: 908.9). 전체 스위트에서 이 파일이 두 번 빨개진 원인이 정확히 그것이었다.

    ★이것은 테스트 편의가 아니라 잠복 결함의 우회다★ —
    `test_a_mock_era_cache_entry_leaks_into_the_real_path` 가 그 사실을 기록하고,
    `docs/specs/2026-08-27-feature-layer-mock-audit.md` §7 이 감사 항목으로 남긴다.
    """
    from src.data.price_factors_store import PriceFactorsStore
    lg.LiquidityStore.get_default()._cache.clear()
    PriceFactorsStore.get_default()._cache.clear()


@pytest.fixture
def prod(monkeypatch):
    """운영 모드 — ★`mock_allowed()` 가 거짓인 진짜 경로를 밟는다★"""
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    _clear_caches()
    yield
    _clear_caches()


@pytest.fixture
def dev(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    _clear_caches()
    yield
    _clear_caches()


# ══════════════════════════════════════════════════════════════════════════
# 1) 운영 — ★모르는 것을 지어내지 않는다★
# ══════════════════════════════════════════════════════════════════════════
def test_spread_is_never_synthesised_in_production(prod):
    """L1 — ★호가 실데이터 원천이 저장소에 없다★

    모든 `spread` 가 `rng.uniform` 이다. 없는 것을 만들어 `max_spread_pct` 와
    비교하면, 그 비교는 종목코드 해시와 임계값의 비교일 뿐이다.
    """
    assert lg.LiquidityStore.get_default().get_liquidity("005930", 3000)["spread_pct"] is None


def test_random_halts_are_gone_in_production(prod):
    """L2 — ★이 테스트가 결함이 사라졌음을 재는 자리다★

    리팩터링 전 실측: 시총 300억 종목 200개 중 **13개**가 비거래 판정.
    근거는 `_uniform(code, "halt") > 0.1` — 종목코드 MD5 해시였다.
    """
    s = lg.LiquidityStore.get_default()
    halted = [c for c in SMALL_CAPS if s.get_liquidity(c, 300).get("is_tradable") is False]
    assert halted == [], f"운영에서 아직 무작위 거래정지 판정이 있다: {halted[:5]}"


def test_market_cap_has_no_synthetic_fallback(prod):
    """L3 — 시총을 모르면 `None`. 예전엔 `_normal(...)` 로 지어냈고 그 값이 곧바로
    `min_market_cap_억` 과 비교됐다."""
    s = lg.LiquidityStore.get_default()
    assert s.get_liquidity("005930")["market_cap_억"] is None
    assert s.get_liquidity("005930", 3000)["market_cap_억"] == 3000


def test_adv_comes_from_the_price_factor_store_cache(prod, monkeypatch):
    """L4 — ★한 모듈 옆의 정직한 값을 재사용한다 — 단, 이미 계산된 것만★

    `amount_20d_avg` 는 사전적재 일봉에서 계산되고 이미 mock 게이트를 지킨다.
    게이트는 그것을 **읽기만** 한다 — `get_factors()` 를 부르면 캐시 미스 때
    종목당 KIS 를 치게 되고, 게이트는 유니버스 전체를 돈다(L12 가 그 짝이다).
    """
    import time

    from src.data.price_factors_store import PriceFactorsStore

    calls: list[str] = []
    monkeypatch.setattr(PriceFactorsStore, "get_factors",
                        lambda self, code, item=None: calls.append(code) or {})

    pf = PriceFactorsStore.get_default()
    # ★스코프된 키로 데운다★ — 캐시는 `mock`/`real` 로 갈린다(`2aff832` 후속).
    pf._cache[pf._scoped(lg.LiquidityStore._PF_CACHE_KEY.format(code="005930"))] = (
        time.time(), {"amount_20d_avg": 42.0})

    d = lg.LiquidityStore.get_default().get_liquidity("005930", 3000)
    assert d["adv_value_억"] == 42.0, "데워 둔 실값을 읽지 않았다"
    assert calls == [], "get_factors 를 불렀다 — 캐시 미스면 종목당 KIS 를 친다"


def test_a_cold_price_cache_yields_unknown_not_a_network_call(prod, monkeypatch):
    """L4 짝 — ★캐시가 비면 `None`(미상)이지 조회가 아니다★

    "캐시만 읽는다" 구현이 실제로 그렇게 동작하는지 본다. 이것이 없으면
    `get_factors` 로 되돌려도 L4 는 통과한다(데워 뒀으니 캐시 히트라서).
    """
    from src.data.price_factors_store import PriceFactorsStore

    calls: list[str] = []
    monkeypatch.setattr(PriceFactorsStore, "get_factors",
                        lambda self, code, item=None: calls.append(code) or
                        {"amount_20d_avg": 99.0})
    assert lg.LiquidityStore.get_default().get_liquidity("005930", 3000)["adv_value_억"] is None
    assert calls == []


def test_the_price_factor_cache_key_format_has_not_drifted():
    """L4 보강 — ★키 형식에 결합돼 있다는 사실을 못 박는다★

    상류가 키를 바꾸면 게이트는 **조용히 항상 `None`** 이 된다(예외도 안 난다).
    그 침묵이 이 결합의 유일한 위험이므로 여기서 잡는다.
    """
    import time

    from src.data.price_factors_store import PriceFactorsStore

    pf = PriceFactorsStore.get_default()
    pf._cache.clear()
    pf.get_factors("005930")
    assert pf._scoped(lg.LiquidityStore._PF_CACHE_KEY.format(code="005930")) in pf._cache, \
        "PriceFactorsStore 의 캐시 키 형식이 바뀌었다 — 게이트가 조용히 미상이 된다"
    pf._cache.clear()


def test_real_adv_reads_the_current_mode_not_a_hardcoded_one(monkeypatch):
    """L4 보강 — ★게이트가 네임스페이스를 **복제**하지 않는다★

    변이 실험이 이 자리를 찾아냈다: `_real_adv` 안의 `store._scoped(...)` 를
    `'real:' + ...` 로 바꿔도 기존 테스트가 전부 통과했다. ★그 변이는 오늘은
    의미상 동등하다★ — `_real_adv` 는 `mock_allowed()` 가 거짓일 때만 도달하므로
    `'real:'` 이 언제나 맞다.

    그러나 **그래서 안전하다는 사실 자체를 테스트가 붙들고 있지 않았다.** 누군가
    mock 경로에서 이 함수를 부르는 순간 하드코딩은 다른 네임스페이스를 읽고
    조용히 `None` 을 낸다. 여기서는 함수를 **직접** 불러 그 속성을 못 박는다 —
    현재 모드의 캐시를 읽는다.
    """
    import time

    from src.data.price_factors_store import PriceFactorsStore

    monkeypatch.setenv("KIS_USE_MOCK", "1")
    pf = PriceFactorsStore.get_default()
    pf._cache.clear()
    pf._cache[pf._scoped(lg.LiquidityStore._PF_CACHE_KEY.format(code="005930"))] = (
        time.time(), {"amount_20d_avg": 7.7})
    assert lg.LiquidityStore._real_adv("005930") == 7.7, \
        "게이트가 현재 모드가 아닌 고정 네임스페이스를 읽는다"
    pf._cache.clear()


def test_the_gate_makes_no_per_stock_network_call(prod, monkeypatch):
    """L12 — ★대량 스크리닝에서 종목당 호출은 프록시 타임아웃을 낸다★

    이 저장소는 그 사고를 이미 겪었다(`extended_factors_store` 의 `live=True`
    독스트링). `_fetch_ohlcv` 가 사전적재 DB 를 1순위로 읽어 종목당 KIS 호출을
    제거해 뒀고, 게이트는 그 규율 안에 있어야 한다.

    ★예외를 신호로 쓰지 않는다★ — 첫 판은 `get_kis_client` 가 `AssertionError` 를
    던지게 했는데, `_real_adv` 의 `except Exception` 이 그것을 **삼켜** 테스트가
    공허했다(변이 M10 이 살아남았다). 호출을 **기록**해서 관찰한다.
    """
    calls: list[int] = []
    monkeypatch.setattr("src.execution.kis_client.get_kis_client",
                        lambda *a, **k: calls.append(1))
    s = lg.LiquidityStore.get_default()
    for c in SMALL_CAPS[:30]:
        s.get_liquidity(c, 1500)
    assert calls == [], f"게이트가 KIS 를 종목당 직접 호출했다({len(calls)}회)"


def test_the_source_label_tells_the_two_paths_apart(prod, dev):
    """L6 — `_source` 가 어느 경로였는지 말한다."""
    s = lg.LiquidityStore.get_default()
    assert s.get_liquidity("005930", 3000)["_source"] == "liquidity_mock"  # dev 픽스처가 마지막
    s._cache.clear()
    os.environ["KIS_USE_MOCK"] = "0"
    try:
        s._cache.clear()
        assert s.get_liquidity("005930", 3000)["_source"] == "liquidity_real"
    finally:
        os.environ["KIS_USE_MOCK"] = "1"
        s._cache.clear()


# ══════════════════════════════════════════════════════════════════════════
# 2) ★mock 경로는 한 글자도 안 바뀌었다★
# ══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("code", sorted(MOCK_BASELINE))
def test_the_mock_path_is_unchanged(dev, code):
    """L5 ★짝★ — 이 변경의 안전성 **전부**가 여기 걸려 있다.

    개발 기본값이 `KIS_USE_MOCK=1` 이므로 기존 3,236 테스트와 골든 3종이 전부 이
    가지를 지난다. 기준값은 리팩터링 **직전** 실측이다.
    """
    got = lg.LiquidityStore.get_default().get_liquidity(code, None)
    for k, v in MOCK_BASELINE[code].items():
        assert got[k] == v, f"{code}.{k} 가 {v} → {got[k]} 로 바뀌었다"
    assert got["_source"] == "liquidity_mock"


def test_the_mock_universe_is_unchanged(dev):
    """L15 — ★통과 종목 **집합**이 동일하다★ 값 세 개가 같은 것보다 강한 증거다."""
    items = [_Item(c) for c in SMALL_CAPS]
    passed, _ = lg.apply_liquidity_gate(items, lg.resolve_floor("standard"))
    assert len(passed) == MOCK_PASSED_COUNT
    assert [p.stock_code for p in passed[:8]] == [
        "001000", "001001", "001002", "001004", "001005", "001006", "001007", "001009"]


# ══════════════════════════════════════════════════════════════════════════
# 3) ★근거 없으면 배제하지 않는다 — 그러나 근거가 있으면 배제한다★
# ══════════════════════════════════════════════════════════════════════════
def test_unknown_metrics_do_not_exclude(prod):
    """L7 — 없는 근거로 배제하는 것도 날조다.

    ★이 단언이 잠복 결함을 잡았다★ — `passes_liquidity` 가
    `not liq_data.get("is_tradable", True)` 였을 때, 값이 `None` 이면 `.get` 이
    기본값을 **쓰지 않아** 전부 배제됐다.
    """
    # 시총은 **알고 있고 임계를 넘는다**(institutional 5000억). 나머지 셋
    # (ADV·스프레드·거래가능)은 미상이므로 그 조건들은 적용되면 안 된다.
    passed, _ = lg.apply_liquidity_gate([_Item("005930", 9000)],
                                        lg.resolve_floor("institutional"))
    assert [p.stock_code for p in passed] == ["005930"]
    # 네 값이 **전부** 미상인 종목도 통과한다 — 아무 근거도 없으면 아무것도 못 막는다.
    passed2, _ = lg.apply_liquidity_gate([_Item("000660", None)],
                                         lg.resolve_floor("institutional"))
    assert [p.stock_code for p in passed2] == ["000660"]


def test_a_real_value_below_the_floor_still_excludes(prod):
    """L8 ★짝★ — "전부 통과" 구현을 배제한다. 게이트는 여전히 게이트다."""
    passed, _ = lg.apply_liquidity_gate(
        [_Item("005930", 3000), _Item("000660", 500)], lg.resolve_floor("standard"))
    assert [p.stock_code for p in passed] == ["005930"], "시총 500억이 통과했다"


def test_a_real_halt_flag_excludes(prod, monkeypatch):
    """L9 — 실제 거래정지 플래그가 있으면 배제한다. `False` 와 `None` 은 다르다."""
    monkeypatch.setattr(lg.LiquidityStore, "_real_tradable",
                        staticmethod(lambda code: code == "005930"))
    lg.LiquidityStore.get_default()._cache.clear()
    passed, _ = lg.apply_liquidity_gate(
        [_Item("005930", 3000), _Item("000660", 3000)], lg.resolve_floor("standard"))
    assert [p.stock_code for p in passed] == ["005930"]


def test_tradable_none_is_not_false():
    """L9 짝 — 비교 계층에서 미상과 거래정지를 구분한다(단위)."""
    floor = lg.resolve_floor("standard")
    it = _Item("X", 3000)
    assert lg.passes_liquidity(it, floor, {"is_tradable": None}) is True
    assert lg.passes_liquidity(it, floor, {}) is True
    assert lg.passes_liquidity(it, floor, {"is_tradable": False}) is False


# ══════════════════════════════════════════════════════════════════════════
# 4) 건너뛴 조건을 ★사유와 함께★ 말한다
# ══════════════════════════════════════════════════════════════════════════
def test_skipped_conditions_are_reported_with_reasons(prod):
    """L10 — ★침묵이 두 가지를 뜻하게 두지 않는다★

    사유가 없으면 "검사했고 통과" 와 "검사하지 못함" 이 화면에서 똑같아 보인다.
    """
    _, st = lg.apply_liquidity_gate([_Item("005930", 3000)], lg.resolve_floor("standard"))
    sk = st["skipped_conditions"]
    assert "spread_pct" in sk and "원천이 없습니다" in sk["spread_pct"]
    assert "adv_value_억" in sk and "is_tradable" in sk
    assert st["checked_counts"]["spread_pct"] == 0


def test_a_checked_condition_is_not_reported_as_skipped(prod):
    """L11 ★짝★ — "전부 skipped" 구현을 배제한다.

    시총은 실제로 검사됐으므로 사유가 뜨면 안 된다. 사유가 늘 떠 있으면
    아무도 읽지 않게 된다.
    """
    _, st = lg.apply_liquidity_gate([_Item("005930", 3000)], lg.resolve_floor("standard"))
    assert "market_cap_억" not in st["skipped_conditions"]
    assert st["checked_counts"]["market_cap_억"] == 1


def test_mock_mode_skips_nothing(dev):
    """L11 보강 — 합성 경로는 네 값을 다 내므로 건너뛴 조건이 없다."""
    _, st = lg.apply_liquidity_gate([_Item("005930")], lg.resolve_floor("standard"))
    assert st["skipped_conditions"] == {}


# ══════════════════════════════════════════════════════════════════════════
# 5) 기존 계약
# ══════════════════════════════════════════════════════════════════════════
def test_none_metrics_attach_without_crashing(prod):
    """L13 — 운영에서 `None` 메트릭이 item 에 붙어도 터지지 않는다(UI 가 "—")."""
    items = [_Item("005930", 3000)]
    passed, _ = lg.apply_liquidity_gate(items, lg.resolve_floor("standard"))
    assert passed[0]._adv_value_억 is None and passed[0]._spread_pct is None


def test_gate_off_is_unchanged(prod):
    """L14 — `floor=None` 이면 손대지 않는다(기존 계약)."""
    items = [_Item(c, 1) for c in SMALL_CAPS[:10]]
    passed, st = lg.apply_liquidity_gate(items, None)
    assert len(passed) == 10 and st["applied"] is False
    assert st["filtered_out"] == 0


def test_the_store_now_consults_the_mock_gate():
    """L1 보강 — ★불변식 자체를 못 박는다★ 소스가 아니라 **동작**으로 본다."""
    s = lg.LiquidityStore.get_default()
    out = {}
    for m in ("1", "0"):
        os.environ["KIS_USE_MOCK"] = m
        s._cache.clear()
        out[m] = s.get_liquidity("005930", 3000)["_source"]
    os.environ["KIS_USE_MOCK"] = "1"
    s._cache.clear()
    assert out["1"] != out["0"], "KIS_USE_MOCK 이 게이트 동작을 바꾸지 않는다"


def test_a_mock_era_cache_entry_no_longer_leaks(monkeypatch):
    """★뒤집힌 트립와이어★ — 결함이 고쳐졌다.

    이 테스트는 원래 누수를 **기록**했다(`2aff832`): `mock_base.cached()` 의 키에
    모드가 없어 `KIS_USE_MOCK=1` 에서 만든 값이 `=0` 에서 그대로 서빙됐다.
    독스트링에 *"이 테스트가 빨개지면 결함이 고쳐진 것 — 그때 뒤집어라"* 라고
    적어 뒀고, 실제로 빨개져서 뒤집었다.

    ★그때 적은 위험 평가는 틀렸었다★ — *"운영에서의 위험은 낮다, 프로세스는 한
    모드로 시작해 끝난다"* 고 했는데, `snapshot_db.enabled()` 가
    `bool(DART_API_KEY) or not mock_allowed()` 라 `KIS_USE_MOCK=1` + 실 DART 키에서
    합성값이 **영속 DB 에 기록**됐다. 재시작을 넘는 누수였다.

    상세는 `tests/test_cache_mode_isolation.py`.
    """
    from src.data.price_factors_store import PriceFactorsStore

    _clear_caches()
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    monkeypatch.setenv("SNAPSHOT_DB", "0")
    warmed = PriceFactorsStore.get_default().get_factors("005930").get("amount_20d_avg")
    assert warmed is not None, "mock 모드에서 값이 나와야 이 시나리오가 성립한다"

    monkeypatch.setenv("KIS_USE_MOCK", "0")
    lg.LiquidityStore.get_default()._cache.clear()      # ★상류는 일부러 안 비운다★
    leaked = lg.LiquidityStore.get_default().get_liquidity("005930", 3000)["adv_value_억"]

    assert leaked is None, f"mock 값 {warmed} 가 아직 운영 경로로 샌다 ({leaked})"
    _clear_caches()
