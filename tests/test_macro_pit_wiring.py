"""조건식 매크로 토큰을 ★빈티지(PIT)★ 에 배선한다

## 무엇이 문제였나

조건식의 매크로 토큰(`US국채(10년)` 등)은 조회 시점에 FRED/ECOS 를 **라이브 호출**해
**지금 최신값**(= 그동안 여러 번 개정된 값)을 받았다. 2023년 백테스트에서 2023년
지표를 읽으면 2024년에 개정된 숫자를 2023년에 알고 있었던 셈이다 — ★룩어헤드★.

## ★배선의 범위가 조사로 좁아졌다★

    빈티지 가능 계열 21개 — 전부 FRED
    PROVIDER_HAS_VINTAGE = {FRED: True, ECOS: False, KRX: False, ...}

  · **ECOS(한국은행)** 토큰 4개는 ★구조적으로 PIT 가 불가★ 하다 — 제공자에 빈티지
    엔드포인트가 없어 `pit_macro.fetch_observations` 가 ALFRED(FRED) 전용이다.
  · **FRED** 토큰 8개 중 레지스트리에 있는 것은 3개(DGS2·DGS10·DGS30)뿐이었다.
    나머지 5개는 커밋 ④ 에서 등록한다.

## 이 파일이 거는 세 계약

① **PIT 요청에 라이브 폴백은 없다** — 빈티지가 없으면 값을 내지 않는다. 폴백하면
   PIT 인 값과 아닌 값이 한 시계열에 섞여, 라벨을 붙여도 소비자가 구별하지 못한다.
② ★순환 거짓 금지★ — `record_series` 의 write-through 행은 `vintage_id=""` 이고
   `load(as_of=)` 는 그런 행을 **통과시킨다**(그 함수가 스스로 적어 둔 규칙).
   거르지 않으면 **자기가 써 넣은 현재값**을 빈티지로 되읽어 PIT 를 주장한다.
③ ★캐시 오염 금지★ — PIT 산출이 라이브 캐시에 남으면 **다음 라이브 조회가 과거
   값을 받는다**. 화면이 조용히 과거를 본다.

②③ 은 저장소가 매크로 수집기에서 이미 겪고 기록해 둔 함정이다(HISTORY).
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

import src.data.pit_macro as pm  # noqa: E402
import src.kis_strategies.factor_tokens as FT  # noqa: E402

TOKEN_FRED = "US국채(10년)"
TOKEN_ECOS = "국고채(10년)"
SERIES = "DGS10"


def _obs(period: str, value: float, *, vintage: str, release: str):
    return pm.MacroObservation(
        series_id=SERIES, observation_period=period, value=value,
        vintage_id=vintage, release_timestamp=release, retrieved_at="2026-01-01")


def _bars() -> pd.DataFrame:
    idx = pd.bdate_range("2023-01-02", periods=60)
    c = np.linspace(100, 120, len(idx))
    return pd.DataFrame({"open": c, "high": c, "low": c, "close": c,
                         "volume": np.full(len(idx), 1)}, index=idx)


@pytest.fixture(autouse=True)
def _clean():
    FT._ecos_cache.clear()
    FT._fred_cache.clear()
    FT._macro_failures.clear()
    yield


@pytest.fixture
def store(monkeypatch):
    """빈티지 2건 — 같은 기간에 개정이 한 번 있었다."""
    rows = [
        _obs("2023-01-01", 3.50, vintage="2023-02-01..9999-12-31", release="2023-02-01"),
        _obs("2023-01-01", 3.72, vintage="2024-05-01..9999-12-31", release="2024-05-01"),
    ]
    import src.data.macro_observation_store as mos

    def _load(series_id=None, *, as_of=None, engine=None):
        out = [o for o in rows if series_id in (None, o.series_id)]
        if as_of:
            out = [o for o in out
                   if not (o.release_timestamp and o.release_timestamp > str(as_of))]
        return out

    monkeypatch.setattr(mos, "load", _load)
    return rows


# ── ① 공용 as-of 리더 ───────────────────────────────────────────────────────

def test_the_as_of_reader_returns_the_value_known_at_that_time(store):
    """★그때 알던 값★ — 2023년 조회는 개정 전 3.50 이어야 한다."""
    got = pm.series_as_of(SERIES, "2023-06-01")
    assert got is not None, "빈티지가 있는데 못 읽었다"
    periods, values = got
    assert values == [pytest.approx(3.50)], f"개정본을 줬다: {values}"


def test_the_same_series_later_reflects_the_revision(store):
    """★짝★ 위 테스트만 걸면 "항상 첫 값" 구현도 통과한다."""
    _p, values = pm.series_as_of(SERIES, "2025-01-01")
    assert values == [pytest.approx(3.72)], f"개정을 반영하지 않았다: {values}"


def test_a_write_through_row_is_not_mistaken_for_a_vintage(monkeypatch):
    """★순환 거짓 금지★ (변이 G1)

    `record_series` 가 써 넣는 현재값 행은 `vintage_id=""` 다. `load(as_of=)` 는
    `release_timestamp` 가 빈 행을 **통과시키므로**, 거르지 않으면 자기가 써 넣은
    현재값을 빈티지로 되읽어 PIT 를 주장하게 된다.
    """
    import src.data.macro_observation_store as mos
    monkeypatch.setattr(mos, "load", lambda series_id=None, *, as_of=None, engine=None: [
        _obs("2023-01-01", 9.99, vintage="", release="")])
    assert pm.series_as_of(SERIES, "2023-06-01") is None, (
        "vintage_id 가 빈 write-through 행을 빈티지로 인정했다")


def test_no_vintage_at_all_is_none_not_empty(monkeypatch):
    import src.data.macro_observation_store as mos
    monkeypatch.setattr(mos, "load", lambda *a, **k: [])
    assert pm.series_as_of(SERIES, "2023-06-01") is None


def test_the_collector_still_works_through_the_shared_reader(store):
    """★동작 불변★ 로직을 옮겼을 뿐이다 — 수집기 경로가 그대로여야 한다."""
    from src.services.macro_collector import _from_vintage_store
    got = _from_vintage_store(SERIES, "2023-06-01")
    assert got is not None and got[1] == [pytest.approx(3.50)]


# ── ② 토큰의 as_of 경로 ─────────────────────────────────────────────────────

def test_a_pit_request_uses_the_vintage(store):
    s = FT.resolve_macro_token(_bars(), TOKEN_FRED, as_of="2023-06-01")
    assert s is not None, "빈티지가 있는데 조건이 평가 불가가 됐다"
    assert s.dropna().unique().tolist() == [pytest.approx(3.50)]


def test_a_pit_request_without_a_vintage_refuses_rather_than_falling_back(monkeypatch):
    """★침묵 폴백 금지★ (변이 G2)

    PIT 요청인데 빈티지가 없으면 **값을 내지 않는다**. 라이브로 떨어지면 PIT 인 값과
    아닌 값이 한 시계열에 섞인다.
    """
    import src.data.macro_observation_store as mos
    monkeypatch.setattr(mos, "load", lambda *a, **k: [])
    called: list = []
    monkeypatch.setattr(FT, "_fred_fetch", lambda t: called.append(t) or pd.Series(dtype=float))
    s = FT.resolve_macro_token(_bars(), TOKEN_FRED, as_of="2023-06-01")
    assert s is None, "빈티지가 없는데 값을 냈다 — 라이브로 떨어졌다"
    assert not called, "PIT 요청인데 라이브를 호출했다"
    rep = FT.macro_availability()
    assert TOKEN_FRED in rep["unavailable"], "왜 못 냈는지 기록하지 않았다"


def test_an_ecos_token_can_never_be_pit(monkeypatch):
    """★제공자 구조상 불가★ (변이 G4)

    ECOS 는 빈티지 엔드포인트가 없다. 스토어에 그 계열 행이 있어도 그것은
    `record_series` 의 현재값 write-through 이지 빈티지가 아니다.
    """
    import src.data.macro_observation_store as mos

    # ★스토어가 그 토큰 이름으로 '진짜 빈티지처럼 보이는' 행을 준다고 가정한다★
    # 이렇게 하지 않으면 ECOS 가드를 없애는 변이가 **조회 결과가 비어서** 어차피
    # None 이 되는 바람에 통과한다 — 결과는 같고 이유가 다르다(변이 G4 가 그렇게
    # 살아남았다). 가드가 실제로 실행되는지는 **사유**로만 구별된다.
    def _load(series_id=None, *, as_of=None, engine=None):
        return [pm.MacroObservation(
            series_id=str(series_id), observation_period="2023-01-01", value=1234.5,
            vintage_id="2023-02-01..9999-12-31", release_timestamp="2023-02-01",
            retrieved_at="2026-01-01")]

    monkeypatch.setattr(mos, "load", _load)
    s = FT.resolve_macro_token(_bars(), TOKEN_ECOS, as_of="2023-06-01")
    assert s is None, "ECOS 토큰에 PIT 값을 냈다 — 제공자가 빈티지를 주지 않는다"
    reason = FT.macro_availability()["unavailable"].get(TOKEN_ECOS, {}).get("reason", "")
    assert "구조적으로 불가능" in reason, (
        f"제공자 구조상 불가 사유가 아니다(조회가 비어 우연히 None 이 됐을 수 있다): {reason}")

    # 짝: per_bar 모드도 같은 가드를 거쳐야 한다
    FT._macro_failures.clear()
    assert FT.resolve_macro_token(_bars(), TOKEN_ECOS, as_of="per_bar") is None
    r2 = FT.macro_availability()["unavailable"].get(TOKEN_ECOS, {}).get("reason", "")
    assert "구조적으로 불가능" in r2, f"per_bar 경로에 ECOS 가드가 없다: {r2}"


def test_a_pit_read_neither_uses_nor_fills_the_live_cache(store, monkeypatch):
    """★캐시 오염 금지★ (변이 G3)

    PIT 산출이 라이브 캐시에 남으면 **다음 라이브 조회가 과거 값을 받는다** —
    화면이 조용히 과거를 본다.
    """
    FT._fred_cache[TOKEN_FRED] = pd.Series(
        [9.99], index=pd.DatetimeIndex(["2023-01-02"]))       # 라이브 캐시에 심어 둔다
    s = FT.resolve_macro_token(_bars(), TOKEN_FRED, as_of="2023-06-01")
    assert s.dropna().unique().tolist() == [pytest.approx(3.50)], (
        "PIT 조회가 라이브 캐시를 읽었다")
    assert FT._fred_cache[TOKEN_FRED].tolist() == [9.99], (
        "PIT 산출이 라이브 캐시를 덮어썼다 — 다음 라이브 조회가 과거를 본다")


# ── ★짝: 기존 동작 불변★ ───────────────────────────────────────────────────

def test_a_call_without_as_of_is_unchanged(monkeypatch):
    """★변이 G5★ 위 테스트들만 걸면 "항상 거절한다" 는 구현도 통과한다.

    `as_of` 를 안 주는 기존 호출부(대시보드·라이브 화면)는 예전 그대로여야 한다.
    """
    idx = pd.bdate_range("2023-01-02", periods=60)
    monkeypatch.setattr(FT, "_fred_fetch",
                        lambda t: pd.Series(np.full(len(idx), 4.44), index=idx))
    s = FT.resolve_macro_token(_bars(), TOKEN_FRED)          # as_of 없음
    assert s is not None and s.dropna().unique().tolist() == [pytest.approx(4.44)], (
        "as_of 없는 호출의 동작이 바뀌었다")


# ── ④ ★내가 틀렸다 — 레지스트리 확장은 근거가 없다★ ──────────────────────
#
# 이 자리에는 "조건식이 쓰는 FRED 토큰 8개가 전부 빈티지 대상이어야 한다"는 테스트가
# 있었다. `DGS1·3·5·7·20` 을 `source_registry` 에 등록해 커버리지를 3/8 → 8/8 로
# 올렸고, 그것을 "현실과의 괴리 축소" 라고 적었다.
#
# **틀렸다.** `tests/test_fred_coordinates.py::test_fred_collection_targets_count_is_unchanged`
# 가 그 결정을 이미 기록해 두고 있었다:
#
#   > 등록하지 않기로 한 이유: 소비자가 없고(term_structure 요건은 scipy 프로브다),
#   > ★DGS 는 일별 시장 관측치라 개정되지 않아 빈티지 연구에도 보탬이 안 된다.★
#
# 개정되지 않는 계열에는 제거할 룩어헤드가 없다. 등록해도 얻는 것이 없고, 대신
# `fred_collection_targets()` 가 21→26 이 되어 `capability.total_series` 를 타고
# 골든 스냅샷을 깨뜨린다(6커밋 동안 지켜온 바이트 동일성). 게다가 내가 새 스펙에
# `verified_live=True` 를 적었는데 **검증한 적이 없다** —
# `test_no_source_claims_verification_it_was_never_given` 이 그것도 잡았다.
#
# 되돌렸다. 이 사실은 아래 테스트로 못 박는다.


def test_the_unrevised_treasury_series_are_deliberately_not_registered():
    """★개정되지 않는 계열에는 제거할 룩어헤드가 없다★

    이 배선의 가치를 과장하지 않기 위한 테스트다. DGS 는 일별 시장 관측치라
    개정이 없다 — 빈티지를 붙여도 얻는 것이 없다. 그 판단은 이미
    `test_fred_coordinates.py` 가 내렸고, 여기서는 **이 배선 작업이 그것을
    되돌리지 않았다**는 것을 건다.
    """
    from src.data.source_registry import get_spec
    for n in (1, 3, 5, 7, 20):
        assert get_spec(f"DGS{n}") is None, (
            f"DGS{n} 을 등록했다 — 개정되지 않는 계열이라 빈티지가 무의미하고, "
            "수집 대상이 늘어 골든 스냅샷이 깨진다")


# ── ③ 봉마다 다른 빈티지 — 벡터화 경로의 핵심 ─────────────────────────────

def test_each_bar_sees_only_what_was_published_by_that_bar(store):
    """★단일 as_of 로는 부족하다★

    벡터화 경로는 전 구간을 한 번에 평가한다. 창 전체에 **하나의** `as_of` 를 쓰면
    창 마지막 봉의 빈티지가 창 첫 봉에도 적용돼 — 창 안에서 여전히 룩어헤드다.

    픽스처는 2023-02-01 에 3.50 이 공표되고 2024-05-01 에 3.72 로 개정됐다.
    2023년 봉은 3.50 을, 2024-05 이후 봉은 3.72 를 봐야 한다.
    """
    bars = pd.DatetimeIndex(["2023-06-01", "2023-12-01", "2024-06-01", "2025-01-02"])
    s = pm.pit_series_for_bars(SERIES, bars)
    assert s is not None, "빈티지가 있는데 못 만들었다"
    got = s.tolist()
    assert got[:2] == [pytest.approx(3.50), pytest.approx(3.50)], (
        f"개정 전 봉이 개정본을 봤다 — 룩어헤드: {got}")
    assert got[2:] == [pytest.approx(3.72), pytest.approx(3.72)], (
        f"개정 후 봉이 개정을 반영하지 않았다: {got}")


def test_a_bar_before_the_first_release_has_no_value(store):
    """★공표 전에는 알 수 없다★ 0 이나 첫 값으로 채우지 않는다."""
    s = pm.pit_series_for_bars(SERIES, pd.DatetimeIndex(["2023-01-15"]))
    assert s is not None
    assert s.isna().all(), f"공표(2023-02-01) 전 봉에 값을 냈다: {s.tolist()}"


def test_the_panel_is_read_once_not_per_bar(store, monkeypatch):
    """★실행당 1회 조회★ `load()` 는 전체 스캔 + 파이썬 필터라 봉마다 부르면
    O(봉수 × 계열 전체) 다."""
    import src.data.macro_observation_store as mos
    calls = {"n": 0}
    real = mos.load

    def counted(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(mos, "load", counted)
    pm.pit_series_for_bars(SERIES, pd.bdate_range("2023-01-02", periods=300))
    assert calls["n"] == 1, f"스토어를 {calls['n']}회 읽었다 — 봉마다 읽고 있다"


def test_the_token_layer_exposes_the_per_bar_mode(store):
    """★벡터화 경로가 쓸 진입점★ — 창 안에서도 봉마다 다른 값이어야 한다."""
    bars = pd.DataFrame({"close": [1.0] * 4},
                        index=pd.DatetimeIndex(["2023-06-01", "2023-12-01",
                                                "2024-06-01", "2025-01-02"]))
    s = FT.resolve_macro_token(bars, TOKEN_FRED, as_of="per_bar")
    assert s is not None and s.tolist() == [pytest.approx(3.50), pytest.approx(3.50),
                                            pytest.approx(3.72), pytest.approx(3.72)], (
        f"창 안에서 봉마다 다른 빈티지를 주지 않는다: {None if s is None else s.tolist()}")
