"""빈티지 계열의 ★파생값★ 을 같은 시점 안에서 계산한다 (전년비·전월차)

## 무엇이 문제인가

`US물가(전년비)` 같은 토큰은 두 값이 필요하다 — 그 봉의 최신 관측치와 12개월 전
관측치. ★둘은 같은 빈티지에서 나와야 한다.★ 분자만 그 시점 값이고 분모가 오늘의
최신 개정본이면, 룩어헤드를 없애려다 **분모로 다시 들여온다**.

이것은 bitemporal 의 기본 규율이다 — `observation_period` 가 valid time,
`release_timestamp`/`vintage_id` 가 transaction time 이고, **파생값은 단일
transaction-time 슬라이스 안에서 계산해야 한다**.

## 이 파일이 거는 네 계약

① **lag 값은 그 봉 시점의 known 집합에서 나온다** — 나중 개정본을 쓰지 않는다.
② **기간 이동은 달력 연산이다** — "목록에서 k칸 뒤" 로 세면 결측이 하나만 있어도
   조용히 어긋난다. 그리고 어긋난 결과는 그럴듯해서 눈으로 못 잡는다.
③ **읽기는 1회다** — 현재값과 lag 값 때문에 스토어를 두 번 읽지 않는다
   (`test_macro_pit_wiring.py::test_the_panel_is_read_once_not_per_bar` 와 같은 계약).
④ **누적기는 순수 함수다** — 스토어 없이 테스트된다. 그래야 이 규칙들을 DB 픽스처
   없이 못 박을 수 있다.
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pandas as pd  # noqa: E402
import pytest  # noqa: E402

import src.data.pit_macro as pm  # noqa: E402

SERIES = "CPIAUCSL"


def _obs(period: str, value: float, *, release: str):
    """빈티지 1건. `vintage_id` 는 비우지 않는다 — 빈 값은 빈티지가 아니다."""
    return pm.MacroObservation(
        series_id=SERIES, observation_period=period, value=value,
        vintage_id=f"{release}..9999-12-31", release_timestamp=release,
        retrieved_at="2026-01-01")


#: 월별 지수. 2023-01 이 **개정**된다 — 100.0 → 101.0 (2024-03-01 공표).
#: 그래서 "2024-02 봉의 전년비" 와 "2024-04 봉의 전년비" 는 **분모가 다르다**.
REVISED_ROWS = [
    _obs("2023-01-01", 100.0, release="2023-02-15"),
    _obs("2023-01-01", 101.0, release="2024-03-01"),   # ★개정★
    _obs("2024-01-01", 110.0, release="2024-02-15"),
]


@pytest.fixture
def store(monkeypatch):
    """`macro_observation_store.load` 를 픽스처로 갈아 끼운다."""
    rows = list(REVISED_ROWS)
    import src.data.macro_observation_store as mos

    def _load(series_id=None, *, as_of=None, engine=None):
        out = [o for o in rows if series_id in (None, o.series_id)]
        if as_of:
            out = [o for o in out
                   if not (o.release_timestamp and o.release_timestamp > str(as_of))]
        return out

    monkeypatch.setattr(mos, "load", _load)
    return rows


# ── ④ 누적기는 순수 함수다 ───────────────────────────────────────────────────

def test_the_accumulator_needs_no_store():
    """★DB 없이 테스트된다★ 로더와 누적을 가른 이유가 이것이다.

    스토어를 타야만 검사할 수 있으면, 아래 규칙들은 픽스처 DB 의 우연에 기대게 된다.
    """
    bars = pd.DatetimeIndex(["2023-03-01", "2024-03-15"])
    s = pm.accumulate_for_bars(REVISED_ROWS, bars)
    assert s is not None
    assert s.tolist() == [pytest.approx(100.0), pytest.approx(110.0)]


def test_missing_values_are_a_prefix_never_a_hole():
    """★단조성★ — 이 성질이 "첫 봉만 보면 된다" 는 판정 규칙의 근거다.

    `known` 이 줄지 않으므로, 한 번 값이 생긴 뒤로는 사라지지 않는다. 누군가
    누적기를 "잊어버리게" 만들면 그 규칙이 조용히 깨지므로 여기서 못 박는다.
    """
    bars = pd.DatetimeIndex(["2022-06-01", "2023-01-10", "2023-03-01",
                             "2023-09-01", "2024-03-15"])
    s = pm.accumulate_for_bars(REVISED_ROWS, bars)
    assert s is not None
    na = s.isna().tolist()
    first_value_at = na.index(False)
    assert all(na[:first_value_at]), "결측이 앞쪽 접두가 아니다"
    assert not any(na[first_value_at:]), f"값이 생긴 뒤 다시 사라졌다: {s.tolist()}"


def test_unsorted_bars_are_rejected_not_silently_sorted():
    """★조용히 정렬하지 않는다★

    누적기는 봉을 한 방향으로 훑으며 관측을 흡수한다 — 오름차순이 전제다. 몰래
    정렬하면 호출자가 넘긴 순서와 반환 인덱스가 어긋나 **값이 엉뚱한 날짜에 붙는다**.
    """
    bars = pd.DatetimeIndex(["2024-03-15", "2023-03-01"])
    with pytest.raises(ValueError):
        pm.accumulate_for_bars(REVISED_ROWS, bars)


# ── ① lag 값은 그 봉 시점의 빈티지에서 나온다 ────────────────────────────────

def test_the_lag_value_is_the_one_known_at_that_bar_not_the_latest_revision():
    """★H1 을 죽이는 앵커★ 분모만 라이브에서 가져오면 여기서 걸린다.

    2023-01 은 100.0 으로 공표됐다가 2024-03-01 에 101.0 으로 개정됐다.
      · 2024-02-20 봉  — 개정 **전** 이므로 분모는 100.0
      · 2024-04-01 봉  — 개정 **후** 이므로 분모는 101.0
    같은 관측기간인데 봉에 따라 분모가 달라야 한다.
    """
    bars = pd.DatetimeIndex(["2024-02-20", "2024-04-01"])
    lag = pm.accumulate_for_bars(REVISED_ROWS, bars, lag_months=12)
    assert lag is not None
    assert lag.tolist() == [pytest.approx(100.0), pytest.approx(101.0)], (
        f"lag 이 그 시점의 빈티지가 아니다: {lag.tolist()}")


def test_the_current_value_and_the_lag_value_move_together():
    """분자는 그대로인데 분모만 개정됐다 — 전년비가 봉에 따라 달라야 한다."""
    bars = pd.DatetimeIndex(["2024-02-20", "2024-04-01"])
    cur = pm.accumulate_for_bars(REVISED_ROWS, bars, lag_months=0)
    lag = pm.accumulate_for_bars(REVISED_ROWS, bars, lag_months=12)
    assert cur.tolist() == [pytest.approx(110.0), pytest.approx(110.0)]
    assert lag.tolist() != cur.tolist()


# ── ② 기간 이동은 달력 연산이다 ──────────────────────────────────────────────

def _monthly(period_values: dict[str, float]):
    """전부 같은 날 공표된 월별 계열 — 개정 없음. 결측을 만들기 위한 픽스처."""
    return [_obs(p, v, release="2020-01-01") for p, v in period_values.items()]


def test_the_lag_period_is_calendar_shifted_not_counted_backwards():
    """★H4 를 죽이는 앵커★ 결측이 하나만 있어도 위치 계산은 어긋난다.

    2023-06 이 빠진 월별 계열이다. 2024-01 봉에서 12개월 전은 **달력으로**
    2023-01 이고 값은 1.0 이다. "목록에서 12칸 뒤" 로 세면 결측 때문에 다른
    기간을 집는다 — 그리고 그 값도 그럴듯해서 눈으로는 못 잡는다.
    """
    vals = {f"2023-{m:02d}-01": float(m) for m in range(1, 13) if m != 6}
    vals["2024-01-01"] = 99.0
    rows = _monthly(vals)
    bars = pd.DatetimeIndex(["2024-01-20"])
    lag = pm.accumulate_for_bars(rows, bars, lag_months=12)
    assert lag is not None
    assert lag.iloc[0] == pytest.approx(1.0), (
        f"달력으로 12개월 전(2023-01, 값 1.0)이 아니다: {lag.iloc[0]}")


def test_a_lag_period_that_does_not_exist_yields_no_value():
    """★없으면 없다★ 가장 가까운 기간으로 대신하지 않는다 — 그것은 지어내기다."""
    rows = _monthly({"2023-03-01": 3.0, "2024-01-01": 99.0})
    bars = pd.DatetimeIndex(["2024-01-20"])
    lag = pm.accumulate_for_bars(rows, bars, lag_months=12)
    assert lag is not None
    assert lag.isna().all(), f"없는 기간(2023-01)을 채웠다: {lag.tolist()}"


def test_an_unparseable_period_yields_no_lag_value():
    """★추측하지 않는다★ 스토어에 `YYYYMM` 이 섞여 있다(쓰는 곳이 셋이다).

    `YYYY-MM-DD` 로 못 읽으면 몇 개월 전인지 **모른다**. 모르면 값을 내지 않는다.
    """
    rows = [_obs("202301", 100.0, release="2023-02-15"),
            _obs("202401", 110.0, release="2024-02-15")]
    bars = pd.DatetimeIndex(["2025-03-01"])
    lag = pm.accumulate_for_bars(rows, bars, lag_months=12)
    assert lag is not None
    assert lag.isna().all(), f"형식을 모르는 기간에서 lag 을 만들어 냈다: {lag.tolist()}"


def test_lag_zero_does_not_parse_the_period_at_all():
    """★짝★ `lag_months=0` 은 기존 동작이다 — 파싱을 도입해 깨뜨리지 않는다.

    위 테스트의 `YYYYMM` 계열도 현재값은 정상적으로 나와야 한다.

    ★봉 날짜를 2025 로 둔 이유★ — 기존 누적기는 관측기간을 `p[:10] <= 봉날짜` 로
    **문자열 비교**한다. `"202401"` 과 `"2024-03-01"` 을 비교하면 `'0' > '-'` 이라
    기간이 미래로 판정된다. 이 스코프에서 고치지 않는 기존 동작이므로, 그 함정을
    **피해서** lag 계약만 검사한다(형식 정규화는 별도 판단 — 스펙 §10).
    """
    rows = [_obs("202301", 100.0, release="2023-02-15"),
            _obs("202401", 110.0, release="2024-02-15")]
    bars = pd.DatetimeIndex(["2025-03-01"])
    cur = pm.accumulate_for_bars(rows, bars, lag_months=0)
    assert cur is not None
    assert cur.iloc[0] == pytest.approx(110.0), f"현재값까지 잃었다: {cur.tolist()}"


# ── ③ 읽기는 1회다 ──────────────────────────────────────────────────────────

def test_the_pair_reads_the_store_once(store, monkeypatch):
    """★H9 를 죽이는 앵커★ 현재값·lag 값 때문에 두 번 읽으면 안 된다.

    `pit_series_for_bars` 를 두 번 부르는 구현은 읽기가 2회가 된다.
    """
    import src.data.macro_observation_store as mos
    calls = {"n": 0}
    real = mos.load

    def counted(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(mos, "load", counted)
    got = pm.pit_pair_for_bars(SERIES, pd.bdate_range("2023-01-02", periods=400),
                               lag_months=12)
    assert got is not None
    assert calls["n"] == 1, f"스토어를 {calls['n']}회 읽었다 — 쌍 때문에 두 번 읽고 있다"


def test_the_pair_agrees_with_the_single_series_on_the_current_leg(store):
    """★기존 계약 불변★ 쌍의 첫 항은 `pit_series_for_bars` 와 같아야 한다.

    다르면 같은 질문에 두 가지 답이 있는 것이고, 언젠가 갈라진다.
    """
    bars = pd.DatetimeIndex(["2023-03-01", "2024-03-15", "2024-06-01"])
    cur, _lag = pm.pit_pair_for_bars(SERIES, bars, lag_months=12)
    single = pm.pit_series_for_bars(SERIES, bars)
    assert single is not None
    pd.testing.assert_series_equal(cur, single, check_names=False)


def test_the_pair_is_none_when_there_are_no_vintages(monkeypatch):
    """★빈 결과는 0 이 아니다★ 빈티지가 없으면 쌍도 없다."""
    import src.data.macro_observation_store as mos
    monkeypatch.setattr(mos, "load", lambda *a, **k: [])
    assert pm.pit_pair_for_bars(SERIES, pd.DatetimeIndex(["2024-01-02"]),
                                lag_months=12) is None


def test_write_through_rows_are_not_vintages_on_the_pair_path(monkeypatch):
    """★순환 거짓 금지★ — `series_as_of` 와 **같은 가드**가 이 경로에도 살아 있어야 한다.

    `record_series` 의 write-through 행은 `vintage_id=""` 다 — transaction time 이
    없는 행이라 as-of 질의에 답할 수 없다. 거르지 않으면 자기가 써 넣은 현재값을
    빈티지라 주장한다.
    """
    rows = [pm.MacroObservation(
        series_id=SERIES, observation_period="2023-01-01", value=100.0,
        vintage_id="", release_timestamp="", retrieved_at="2026-01-01")]
    import src.data.macro_observation_store as mos
    monkeypatch.setattr(mos, "load", lambda *a, **k: rows)
    assert pm.pit_pair_for_bars(SERIES, pd.DatetimeIndex(["2024-01-02"]),
                                lag_months=12) is None
