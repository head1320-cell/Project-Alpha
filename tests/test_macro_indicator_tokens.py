"""★개정되는★ 매크로 계열을 조건식 토큰으로 연다 (전년비·전월차·레벨)

## 왜 필요한가

`aa3c4ba` 로 PIT 배관을 깔았지만 조건식이 노출하는 매크로 토큰 12개는
**ECOS 4개**(제공자에 빈티지 엔드포인트가 없어 구조적으로 불가) +
**FRED DGS 8개**(일별 시장 관측치라 개정되지 않음)다. 즉 ★제거할 룩어헤드가
애초에 없다.★ 개정되는 계열(CPI·고용·GDP…)이 토큰이 되어야 배관이 값을 한다.

## 레벨을 그대로 열지 않는 이유

`CPIAUCSL` 은 지수라 310.3, `PAYEMS` 는 천명 단위라 159,000 이다. `{US물가} > 3`
같은 조건은 쓸 수 없다. 그래서 **계열마다 의미 있는 표현 하나씩** 연다 —
레벨이 그대로 읽히는 것은 레벨로, 변화만 의미 있는 것은 변화로.

## 이 파일이 거는 계약

① **분자와 분모는 같은 빈티지에서 나온다** — 전년비의 분모만 오늘 최신 개정본이면
   룩어헤드를 분모로 되들인다. bitemporal 로 말하면 파생값은 단일
   transaction-time 슬라이스 안에서 계산해야 한다.
② **공식은 한 벌이다** — PIT 경로와 라이브 경로가 같은 함수를 쓴다. 공표 지연이
   0 이고 개정이 없는 픽스처에서 두 경로는 **같은 숫자**여야 한다.
③ ★`FRED_TOKENS` 를 오염시키지 않는다★ — 그 딕셔너리는 국채 커브 컴프리헨션이고
   `test_fred_coordinates.py::test_token_maturity_matches_the_series_id` 가
   *"손 예외가 들어오면 잡는다"* 로 지키고 있다. 새 토큰은 별도 레지스트리다.
④ **좌표는 레지스트리에 있어야 한다** — ECOS 토큰이 이미 그 규율을 따른다
   (`test_ecos_coordinates.py::test_every_token_coordinate_matches_a_registry_spec`).
⑤ ★0 으로 나누지 않는다★ — 전년비 분모가 0이면 `inf` 가 아니라 미상이다.
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

import src.data.pit_macro as pm  # noqa: E402
import src.kis_strategies.factor_tokens as FT  # noqa: E402

TOKEN_YOY = "US물가(전년비)"
TOKEN_MOM = "US고용(전월차)"
TOKEN_LEVEL = "US실업률"


@pytest.fixture(autouse=True)
def _clean():
    FT._ecos_cache.clear()
    FT._fred_cache.clear()
    FT._macro_failures.clear()
    yield
    FT._fred_cache.clear()
    FT._macro_failures.clear()


def _bars(start="2024-01-02", periods=60) -> pd.DataFrame:
    idx = pd.bdate_range(start, periods=periods)
    c = np.linspace(100, 120, len(idx))
    return pd.DataFrame({"open": c, "high": c, "low": c, "close": c,
                         "volume": np.full(len(idx), 1)}, index=idx)


def _obs(series_id: str, period: str, value: float, *, release: str):
    return pm.MacroObservation(
        series_id=series_id, observation_period=period, value=value,
        vintage_id=f"{release}..9999-12-31", release_timestamp=release,
        retrieved_at="2026-01-01")


# ═══════════════════════════════════════════════════════════════════════════════
# ③④ 레지스트리 규율 — 새 토큰이 기존 어휘를 오염시키지 않는다
# ═══════════════════════════════════════════════════════════════════════════════

def test_the_indicator_tokens_do_not_leak_into_the_treasury_curve_dict():
    """★`FRED_TOKENS` 는 국채 커브 컴프리헨션 그대로다★

    거기에 손으로 항목을 더하면 `test_fred_coordinates` 의 만기↔series_id 가드가
    깨진다. 그 가드는 정확히 이런 추가를 잡으려고 존재한다.
    """
    assert set(FT.FRED_TOKENS.values()) == {f"DGS{n}" for n in (1, 2, 3, 5, 7, 10, 20, 30)}
    for tok in FT.FRED_INDICATOR_TOKENS:
        assert tok not in FT.FRED_TOKENS, f"{tok} 이 국채 커브 딕셔너리에 섞였다"


def test_every_indicator_token_coordinate_is_in_the_source_registry():
    """★좌표를 지어내지 않는다★ ECOS 토큰이 이미 따르는 규율이다.

    레지스트리에 없는 계열을 가리키면 백필이 그 계열을 받지 않으므로, 토큰은
    영원히 빈티지를 얻지 못한 채 라이브(룩어헤드)로만 평가된다.
    """
    from src.data.source_registry import get_spec
    for tok, (sid, _kind) in FT.FRED_INDICATOR_TOKENS.items():
        assert get_spec(sid) is not None, f"{tok} 의 좌표 {sid} 가 레지스트리에 없다"


def test_every_indicator_token_is_reported_as_a_macro_token():
    """픽커가 읽는 지원 목록에 들어가야 실제로 쓸 수 있다."""
    ts = FT.token_support()
    for tok in FT.FRED_INDICATOR_TOKENS:
        assert ts["supported"].get(tok) == "macro", f"{tok} 이 지원 목록에 없다"
        assert tok not in ts["unsupported"], f"{tok} 이 지원·미지원 양쪽에 있다"


def test_the_representation_kind_is_one_of_the_three_known_ones():
    """★모르는 표현을 조용히 레벨로 처리하지 않는다★"""
    for tok, (_sid, kind) in FT.FRED_INDICATOR_TOKENS.items():
        assert kind in ("level", "yoy", "mom_diff"), f"{tok} 의 표현 {kind!r} 을 모른다"


# ═══════════════════════════════════════════════════════════════════════════════
# ⑤ 공식 — 0 으로 나누지 않는다
# ═══════════════════════════════════════════════════════════════════════════════

def test_year_over_year_is_a_percent_change():
    cur = pd.Series([110.0, 121.0])
    lag = pd.Series([100.0, 110.0])
    out = FT._apply_indicator(cur, lag, "yoy")
    assert out.tolist() == [pytest.approx(10.0), pytest.approx(10.0)]


def test_month_over_month_is_a_difference_in_the_native_unit():
    """고용은 "+150K" 로 읽는다 — 비율이 아니라 차이다."""
    cur = pd.Series([159_150.0])
    lag = pd.Series([159_000.0])
    out = FT._apply_indicator(cur, lag, "mom_diff")
    assert out.iloc[0] == pytest.approx(150.0)


def test_a_zero_denominator_is_unknown_not_infinity():
    """★H10★ `inf` 는 조건식에서 '무한히 큰 상승률' 로 읽혀 조건을 통과시킨다."""
    cur = pd.Series([110.0])
    lag = pd.Series([0.0])
    out = FT._apply_indicator(cur, lag, "yoy")
    assert out.isna().all(), f"0 으로 나눠 {out.tolist()} 을 냈다"


def test_a_missing_lag_yields_no_value_not_the_level():
    """★짝★ lag 이 없으면 전년비도 없다 — 레벨로 대신하지 않는다."""
    cur = pd.Series([110.0])
    lag = pd.Series([np.nan])
    assert FT._apply_indicator(cur, lag, "yoy").isna().all()
    assert FT._apply_indicator(cur, lag, "mom_diff").isna().all()


# ═══════════════════════════════════════════════════════════════════════════════
# ① 분자와 분모는 같은 빈티지에서
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def revised_store(monkeypatch):
    """2023-01 이 개정되는 CPI 픽스처.

      100.0 (2023-02-15 공표) → 101.0 (2024-03-01 개정)
      2024-01 은 110.0 (2024-02-15 공표)

    ⇒ 2024-02-20 봉의 전년비는 110/100-1 = **10.0%**
      2024-04-01 봉의 전년비는 110/101-1 = **8.91%**
    같은 관측기간인데 봉에 따라 분모가 달라야 한다.
    """
    rows = [
        _obs("CPIAUCSL", "2023-01-01", 100.0, release="2023-02-15"),
        _obs("CPIAUCSL", "2023-01-01", 101.0, release="2024-03-01"),
        _obs("CPIAUCSL", "2024-01-01", 110.0, release="2024-02-15"),
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


def test_the_denominator_is_the_vintage_known_at_that_bar(revised_store, monkeypatch):
    """★H1 을 죽이는 앵커★ 분모만 라이브에서 가져오면 여기서 걸린다.

    ★라이브 스텁이 반드시 있어야 한다★ — 없으면 분모를 라이브에서 가져오는 변이가
    조회 실패로 **PIT 로 되돌아가** 정답을 내고, 이 앵커는 겨냥이 빗나간다.
    라이브는 오늘 시점이므로 2023-01 을 **개정된 101.0** 으로 본다:

        올바름(PIT)      2024-02-20 → 110/100 = 10.00%   (개정 전 분모)
        변이(라이브 분모) 2024-02-20 → 110/101 =  8.91%   ← 룩어헤드
    """
    monkeypatch.setattr(FT, "_fred_fetch", lambda token: pd.Series(
        [101.0, 110.0], index=pd.DatetimeIndex(["2023-01-01", "2024-01-01"])))
    df = pd.DataFrame({"close": [1.0, 1.0]},
                      index=pd.DatetimeIndex(["2024-02-20", "2024-04-01"]))
    s = FT.resolve_macro_token(df, TOKEN_YOY, as_of="per_bar")
    assert s is not None, "빈티지가 있는데 전년비를 못 만들었다"
    got = [round(float(v), 2) for v in s.tolist()]
    assert got == [10.0, 8.91], f"분모가 그 시점의 빈티지가 아니다: {got}"


def test_a_bar_before_the_lag_is_publishable_has_no_value(revised_store):
    """★공표 전에는 알 수 없다★ 12개월 전 값이 아직 없으면 전년비도 없다."""
    df = pd.DataFrame({"close": [1.0]}, index=pd.DatetimeIndex(["2023-06-01"]))
    s = FT.resolve_macro_token(df, TOKEN_YOY, as_of="per_bar")
    assert s is None or s.isna().all(), f"lag 없이 전년비를 냈다: {s}"


def test_the_pit_request_never_falls_back_to_live(monkeypatch):
    """★침묵 폴백 금지★ 빈티지가 없으면 값을 내지 않는다 — 기존 계약 유지."""
    import src.data.macro_observation_store as mos
    monkeypatch.setattr(mos, "load", lambda *a, **k: [])
    called = {"n": 0}
    monkeypatch.setattr(FT, "_fred_fetch", lambda t: called.__setitem__("n", called["n"] + 1))
    assert FT.resolve_macro_token(_bars(), TOKEN_YOY, as_of="per_bar") is None
    assert called["n"] == 0, "PIT 요청인데 라이브를 불렀다"


def test_the_pit_path_does_not_touch_the_live_cache(revised_store):
    """★캐시 오염 금지★ PIT 산출이 남으면 다음 라이브 조회가 과거를 본다."""
    df = pd.DataFrame({"close": [1.0]}, index=pd.DatetimeIndex(["2024-04-01"]))
    FT.resolve_macro_token(df, TOKEN_YOY, as_of="per_bar")
    assert TOKEN_YOY not in FT._fred_cache, "PIT 산출이 라이브 캐시에 남았다"


# ═══════════════════════════════════════════════════════════════════════════════
# ② 공식은 한 벌 — 두 경로가 같은 숫자를 낸다
# ═══════════════════════════════════════════════════════════════════════════════

_FLAT_PERIODS = [f"2023-{m:02d}-01" for m in range(1, 13)] + \
                [f"2024-{m:02d}-01" for m in range(1, 4)]
#: 값은 기간마다 다르게 — 잘못 집으면 눈에 띄도록.
_FLAT_VALUES = [100.0 + i for i in range(len(_FLAT_PERIODS))]


@pytest.fixture
def unrevised_store(monkeypatch):
    """★개정 없음 · 공표 지연 0★ — 공식만 남기고 타이밍 차이를 지운다.

    PIT 와 라이브는 값이 **보이기 시작하는 시점**이 다르다(공표 지연). 그것은
    의도된 차이다. 여기서는 지연을 0 으로 두어 **공식이 같은지만** 본다.
    """
    rows = [_obs("CPIAUCSL", p, v, release=p)
            for p, v in zip(_FLAT_PERIODS, _FLAT_VALUES, strict=True)]
    import src.data.macro_observation_store as mos
    monkeypatch.setattr(mos, "load", lambda series_id=None, **k: [
        o for o in rows if series_id in (None, o.series_id)])
    return rows


def test_the_two_paths_agree_when_nothing_was_revised(unrevised_store, monkeypatch):
    """★계약★ 공식이 갈라지면 여기서 죽는다.

    라이브 경로는 FRED 를 타므로 같은 관측을 돌려주는 스텁을 끼운다.
    """
    monkeypatch.setattr(FT, "_fred_fetch", lambda token: pd.Series(
        _FLAT_VALUES, index=pd.DatetimeIndex(_FLAT_PERIODS)))
    df = pd.DataFrame({"close": [1.0, 1.0]},
                      index=pd.DatetimeIndex(["2024-02-05", "2024-03-05"]))
    pit = FT.resolve_macro_token(df, TOKEN_YOY, as_of="per_bar")
    live = FT.resolve_macro_token(df, TOKEN_YOY)
    assert pit is not None and live is not None
    assert [round(float(v), 6) for v in pit.tolist()] == \
           [round(float(v), 6) for v in live.tolist()], \
        f"두 경로가 다른 숫자를 냈다 — PIT {pit.tolist()} vs 라이브 {live.tolist()}"


def test_the_live_lag_is_calendar_shifted_not_positional(monkeypatch):
    """★H4 의 라이브 판★ 관측에 결측이 있으면 위치 이동은 어긋난다.

    2023-06 이 빠진 계열이다. 2024-01 관측의 12개월 전은 **달력으로** 2023-01 이다.
    """
    periods = [f"2023-{m:02d}-01" for m in range(1, 13) if m != 6] + ["2024-01-01"]
    values = [float(m) for m in range(1, 13) if m != 6] + [99.0]
    monkeypatch.setattr(FT, "_fred_fetch", lambda token: pd.Series(
        values, index=pd.DatetimeIndex(periods)))
    df = pd.DataFrame({"close": [1.0]}, index=pd.DatetimeIndex(["2024-01-20"]))
    s = FT.resolve_macro_token(df, TOKEN_YOY)
    assert s is not None
    assert float(s.iloc[0]) == pytest.approx((99.0 / 1.0 - 1) * 100), \
        f"달력으로 12개월 전(2023-01, 값 1.0)을 분모로 쓰지 않았다: {s.iloc[0]}"


def test_a_level_token_needs_no_lag(monkeypatch):
    """레벨 표현은 lag 이 없어도 첫 관측부터 값이 있다."""
    monkeypatch.setattr(FT, "_fred_fetch", lambda token: pd.Series(
        [3.7, 3.9], index=pd.DatetimeIndex(["2024-01-01", "2024-02-01"])))
    df = pd.DataFrame({"close": [1.0]}, index=pd.DatetimeIndex(["2024-02-05"]))
    s = FT.resolve_macro_token(df, TOKEN_LEVEL)
    assert s is not None
    assert float(s.iloc[0]) == pytest.approx(3.9)


def test_an_indicator_token_without_a_key_is_skipped_with_a_reason(monkeypatch):
    """★미상은 0 이 아니다★ 키가 없으면 건너뛰고 사유를 남긴다."""
    monkeypatch.setattr(FT, "_fred_fetch", lambda token: None)
    assert FT.resolve_macro_token(_bars(), TOKEN_MOM) is None
    rep = FT.macro_availability()
    assert TOKEN_MOM in rep["unavailable"], "사유 없이 사라졌다"
    assert rep["unavailable"][TOKEN_MOM]["reason"], "사유가 비어 있다"
