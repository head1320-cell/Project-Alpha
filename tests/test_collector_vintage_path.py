"""수집 경로의 PIT 읽기 — ★선언을 뒤집는 게 아니라 참으로 만든다★
==============================================================================
승인: Track B4(국면 축 빈티지 게이트) — 감사문 `2026-08-28-macro-model-stack-audit.md`
선행: `ac938c4`(계열별 판정) · P2(`4983f71`, 선언 → 논리곱 측정)

## 이 파일이 지키는 것

`COLLECTOR_READS_VINTAGE` 는 "수집 경로가 빈티지를 가져온다" 는 **사실 진술**이다.
코드가 그러지 않는데 값만 올리면 승인 집행이 아니라 **거짓 선언**이고,
`test_axis_revision_status.py` 의 `tokenize` 대조가 그것을 잡는다. 그래서 승인은
**경로를 실제로 PIT 로 만드는 것**으로 집행한다.

## ★남는 안전장치★

축 판정은 `⑵ 수집 경로가 빈티지를 읽는가 ∧ ⑶ 그 계열에 실제 빈티지 행이 있는가` 다.
⑵ 가 참이 되어도 ⑶ 은 **관측**이라 그대로다. 오늘 빈티지 0건이므로 축 출력은
**완전히 동일**하고, 키가 온 뒤 빈티지가 쌓인 **계열만** 열린다.

## 두 함정 — 둘 다 `ac938c4` 가 막은 결함의 재발이다

    ⑴ ★순환 거짓★ `record_series` 의 write-through 행은 `vintage_id=""` 다.
       그것을 빈티지로 되읽으면 **자기가 써 넣은 현재값**으로 PIT 를 주장한다.
       `load(as_of=)` 는 `release_timestamp` 가 빈 행을 **통과시킨다**(스스로 적어
       둔 규칙)이므로 as-of 필터만으로는 걸러지지 않는다.
    ⑵ ★침묵 폴백★ `as_of` 를 줬는데 빈티지가 없을 때 현재값을 조용히 주는 것.
       그것이 "현재 개정본으로 과거를 채점" 이다.
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402

import src.data.macro_observation_store as mos  # noqa: E402
import src.services.macro_collector as mc  # noqa: E402
from src.data.pit_macro import DataStatus, MacroObservation  # noqa: E402

#: ★축 계열★ 이면서 제공자가 빈티지를 주는 것(FRED). 축 밖 계열을 쓰면 P8 이
#: 공허해진다 — 축이 보지 않는 계열은 무엇을 해도 판정을 안 움직인다.
_FRED_KEY = "INDPRO"          # us 성장축
_ECOS_KEY = "KR_CPI"          # kr 물가축 — ECOS 라 영구 차단



@pytest.fixture
def eng():
    return create_engine("sqlite://", connect_args={"check_same_thread": False})


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, eng):
    """★프로세스 공용 DB 를 건드리지 않는다★ 수집기 캐시도 비운다."""
    monkeypatch.setattr(mos, "_engine", lambda engine=None: eng)
    mc.MacroCollector._singleton = None
    yield
    mc.MacroCollector._singleton = None


def _obs(series_id: str, period: str, value: float, *,
         vintage: str, released: str) -> MacroObservation:
    return MacroObservation(
        series_id=series_id, observation_period=period,
        release_timestamp=released, vintage_id=vintage,
        retrieved_at="2026-08-28T00:00:00Z", value=value,
        data_status=DataStatus.REAL)


def _seed_vintages(eng, series_id=_FRED_KEY, *, n=6, released_prefix="2024"):
    obs = [_obs(series_id, f"{released_prefix}-{m:02d}", 3.0 + m * 0.1,
                vintage=f"{released_prefix}-{m:02d}-15..9999-12-31",
                released=f"{released_prefix}-{m:02d}-15T00:00:00Z")
           for m in range(1, n + 1)]
    assert mos.save(obs, source=mos.SOURCE_ALFRED, engine=eng) == n
    return obs


# ══════════════════════════════════════════════════════════════════════════
# P1·P2 ★핵심 불변 — 오늘은 아무것도 바뀌지 않는다★
# ══════════════════════════════════════════════════════════════════════════
def test_with_no_vintages_nothing_uses_the_vintage_path():
    snap = mc.MacroCollector().collect_all(use_cache=False)
    assert snap.series, "수집 자체가 비었다 — 검사가 공허하다"
    used = [k for k, s in snap.series.items() if getattr(s, "vintage_used", False)]
    assert used == [], f"빈티지가 0건인데 PIT 를 주장한 계열이 있다: {used}"


def test_the_axis_verdict_is_unchanged_today():
    """★승인의 정확한 범위★ — 지금 managed 로 만드는 것이 아니다."""
    from src.engine.regime_axes import axis_revision_status

    for market, expected in (("kr", {("ECOS", "source"): 4, ("FRED", "path"): 1}),
                             ("us", {("FRED", "path"): 6})):
        st = axis_revision_status(market)
        assert st["revision_bias"] == "unmanaged", market
        assert st["path_uses_vintage"] is False, market
        got: dict = {}
        for row in st["series"]:
            k = (row["provider"], row["blocked_by"])
            got[k] = got.get(k, 0) + 1
        assert got == expected, market


def test_one_series_gaining_vintages_does_not_perturb_the_others(eng):
    """★계열별이다★ 한 계열에 빈티지가 생겨도 다른 계열의 값은 그대로다."""
    before = mc.MacroCollector().collect_all(use_cache=False).series
    _seed_vintages(eng)
    after = mc.MacroCollector().collect_all(use_cache=False).series

    for key in before:
        if key == _FRED_KEY:
            continue
        assert list(before[key].values) == list(after[key].values), key
        assert list(before[key].timestamps) == list(after[key].timestamps), key


# ══════════════════════════════════════════════════════════════════════════
# P3·P4 ★순환 거짓을 막는다★
# ══════════════════════════════════════════════════════════════════════════
def test_write_through_rows_are_not_vintages(eng):
    """★핵심★ `record_series` 가 남긴 `vintage_id=""` 행으로 PIT 를 주장하면
    **자기가 써 넣은 현재값**을 빈티지로 되읽는 것이다."""
    obs = [_obs(_FRED_KEY, f"2024-{m:02d}", 4.0 + m, vintage="", released="")
           for m in range(1, 7)]
    assert mos.save(obs, source=mos.SOURCE_FRED, engine=eng) == 6

    snap = mc.MacroCollector().collect_all(use_cache=False)
    assert snap.series[_FRED_KEY].vintage_used is False, "빈 빈티지를 PIT 로 읽었다"


def test_real_vintage_rows_are_used(eng):
    """★짝★ 없으면 P3 가 '빈티지를 절대 안 읽는다' 구현으로도 통과한다."""
    _seed_vintages(eng)
    snap = mc.MacroCollector().collect_all(use_cache=False)
    s = snap.series[_FRED_KEY]
    assert s.vintage_used is True
    assert s.values, "빈티지를 읽었다면서 값이 없다"


# ══════════════════════════════════════════════════════════════════════════
# P5·P6·P7 ★as_of 는 침묵 폴백을 하지 않는다★
# ══════════════════════════════════════════════════════════════════════════
def test_a_pit_request_without_vintages_refuses_instead_of_returning_today(eng):
    """★핵심★ 현재 개정본으로 과거를 채점하는 것이 `ac938c4` 가 막은 결함이다."""
    snap = mc.MacroCollector().collect_all(use_cache=False, as_of="2024-06-30")
    s = snap.series[_FRED_KEY]
    assert s.values == [] and s.latest is None
    assert s.source == "unavailable"
    assert s.reason and "빈티지" in s.reason
    assert s.vintage_used is False


def test_a_pit_request_with_vintages_returns_values(eng):
    """★짝★ 없으면 P5 가 '항상 거부' 구현으로도 통과한다."""
    _seed_vintages(eng)
    snap = mc.MacroCollector().collect_all(use_cache=False, as_of="2024-12-31")
    s = snap.series[_FRED_KEY]
    assert s.vintage_used is True and s.values
    assert s.as_of == "2024-12-31"


def test_rows_released_after_the_as_of_are_excluded(eng):
    """PIT 의 의미 그 자체 — 그때 몰랐던 것은 쓰지 않는다."""
    _seed_vintages(eng, n=6)
    early = mc.MacroCollector().collect_all(use_cache=False, as_of="2024-03-31")
    late = mc.MacroCollector().collect_all(use_cache=False, as_of="2024-12-31")
    assert len(early.series[_FRED_KEY].values) < len(late.series[_FRED_KEY].values)


def test_a_pit_request_does_not_poison_the_live_cache(eng):
    """as_of 산출이 캐시에 남으면 다음 라이브 조회가 과거 값을 받는다."""
    _seed_vintages(eng)
    collector = mc.MacroCollector()
    collector.collect_all(use_cache=True, as_of="2024-03-31")
    live = collector.collect_all(use_cache=True)
    assert live.series[_FRED_KEY].as_of is None


# ══════════════════════════════════════════════════════════════════════════
# P8·P9 ★게이트는 계열별로 열린다 — 영구 차단은 안 풀린다★
# ══════════════════════════════════════════════════════════════════════════
def test_only_the_series_with_vintages_opens(eng):
    from src.engine.regime_axes import axis_revision_status

    _seed_vintages(eng, _FRED_KEY)
    st = axis_revision_status("us")
    rows = {r["key"]: r for r in st["series"]}
    assert rows[_FRED_KEY]["blocked_by"] is None, "빈티지가 있는 계열이 안 열렸다"
    others = [k for k in rows if k != _FRED_KEY]
    assert others, "다른 계열이 없어 비교가 공허하다"
    for k in others:
        assert rows[k]["blocked_by"] == "path", k


def test_ecos_stays_blocked_by_source_even_with_vintage_rows(eng):
    """★영구 차단★ ECOS 에는 빈티지 엔드포인트가 없다. 행을 넣어도 열리면 안 된다."""
    from src.engine.regime_axes import axis_revision_status

    _seed_vintages(eng, _ECOS_KEY)
    st = axis_revision_status("kr")
    rows = {r["key"]: r for r in st["series"]}
    assert rows[_ECOS_KEY]["blocked_by"] == "source", "영구 차단이 풀렸다"


# ══════════════════════════════════════════════════════════════════════════
# P10 선언이 코드와 일치한다
# ══════════════════════════════════════════════════════════════════════════
def test_the_declaration_is_now_true():
    assert mc.COLLECTOR_READS_VINTAGE is True
