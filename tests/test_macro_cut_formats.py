"""매크로 계열을 `as_of` 로 자를 때 ★날짜를 글자로 견주지 않는다★ (2026-11-11)

## 무엇이 문제였나 (실측)

`factor_exposure.truncate_series` 는 `str(t)[:10] <= as_of` 였다. `as_of` 는 `YYYY-MM-DD` 인데 수집기가 내는
타임스탬프는 출처마다 모양이 다르다(`macro_collector` — 한국은행 월별 `YYYYMM` · 일별 `YYYYMMDD` · 연별 `YYYY` ·
FRED `YYYY-MM-DD` · 연습용 `YYYYMM`). 글자로 견주면 다섯째 글자에서 `"0"`(0x30) 과 `"-"`(0x2D) 가 만난다:

    형식          as_of        고치기 전에 남던 마지막 관측     맞는 값
    YYYYMM        2024-06-30   202312                           202406
    YYYYMM        2024-12-31   202312                           202412
    YYYYMMDD      2024-06-30   (그 해 것이 하나도 안 남음)      20240630
    YYYY          2024-06-30   2024  ← 끝나지 않은 해           2023
    YYYY-MM-DD    2024-06-30   2024-06-01                       그대로 맞다

한국은행 형식 계열은 as_of 가 든 해를 통째로 잃었고(최대 12개월), 응답은 `macro_data_as_of: 2024-06-30` 을
지켰다고 적었다. `tests/test_factor_stack_respects_as_of.py` 의 옛 독스트링 "매크로 계열이 자산 창보다 먼저
끝난다(2023-12)"는 자료 사정이 아니라 이 결함의 증상이었다.

## 규칙

타임스탬프를 ★그 관측 기간의 마지막 날★로 바꿔 날짜끼리 견준다. 달 라벨(`YYYYMM`·`YYYY-MM`)은 말일, 해 라벨은
12월 31일이다 — 끝나지 않은 기간의 관측은 넣지 않는다. 온전한 날짜(`YYYY-MM-DD`·`YYYYMMDD`)는 그 날 그대로다
(FRED 의 월별 계열은 달 첫날로 찍혀 오는데 날짜만으로는 주기를 알 수 없다 — 그 동작은 고치기 전과 같다).
모르는 모양이면 자르지 않고 ★못 잘랐다고 말한다★(`ok=False`) — 조용히 넣지도 빼지도 않는다.

공표 지연(6월 지표는 7월에 나온다)은 이 절단이 다루지 않는다. 그것은 `pit_macro` 의 빈티지 경로가 맡는다.
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402

from src.engine.factor_exposure import resolve_proxies, truncate_series  # noqa: E402


class _S:
    def __init__(self, timestamps, values=None):
        self.timestamps = list(timestamps)
        self.values = [100.0 + i for i in range(len(self.timestamps))] if values is None else list(values)


def _cut(ts, as_of):
    cut, ok = truncate_series(_S(ts), as_of)
    return (cut.timestamps[-1] if cut.timestamps else None), len(cut.timestamps), ok


_YM = [f"{y}{m:02d}" for y in (2022, 2023, 2024, 2025) for m in range(1, 13)]            # 한국은행 월별 · 연습용
_YM_DASH = [f"{y}-{m:02d}" for y in (2022, 2023, 2024, 2025) for m in range(1, 13)]
_FRED = [f"{y}-{m:02d}-01" for y in (2022, 2023, 2024, 2025) for m in range(1, 13)]     # FRED 월별 — 달 첫날로 찍힌다


# ── 1. 한국은행 월별 `YYYYMM` — as_of 가 든 달까지 남는다 ──────────────────────────────────────
@pytest.mark.parametrize("as_of,last,n", [
    ("2024-06-30", "202406", 30),
    ("2024-12-31", "202412", 36),       # 고치기 전: 202312 (그 해를 통째로 버렸다)
    ("2024-02-29", "202402", 26),       # 윤년 말일
    ("2025-01-31", "202501", 37),
])
def test_a_compact_month_label_is_kept_through_the_as_of_month(as_of, last, n):
    assert _cut(_YM, as_of) == (last, n, True)


@pytest.mark.parametrize("as_of,last", [
    ("2024-06-15", "202405"),           # 6월은 아직 안 끝났다
    ("2024-06-29", "202405"),
    ("2024-07-01", "202406"),
    ("2024-01-01", "202312"),
])
def test_an_unfinished_month_is_not_included(as_of, last):
    """★짝★ 달 라벨은 그 달 전체의 관측이다 — 말일 전에는 넣지 않는다(달 첫날로 취급하는 구현 배제)."""
    assert _cut(_YM, as_of)[0] == last
    assert _cut(_YM_DASH, as_of)[0] == f"{last[:4]}-{last[4:]}"


# ── 2. 한국은행 일별 `YYYYMMDD` · 연별 `YYYY` ────────────────────────────────────────────────
def test_a_compact_day_label_is_compared_as_a_date():
    days = ["20231229", "20240102", "20240614", "20240630", "20240701", "20241231"]
    assert _cut(days, "2024-06-30") == ("20240630", 4, True)      # 고치기 전: 2023년 것만 남았다
    assert _cut(days, "2024-06-29") == ("20240614", 3, True)


def test_an_unfinished_year_is_not_included():
    """고치기 전에는 `"2024" <= "2024-06-30"` 이 참이라 끝나지 않은 해가 들어갔다 — 미래를 본 것이다."""
    years = ["2021", "2022", "2023", "2024", "2025"]
    assert _cut(years, "2024-06-30") == ("2023", 3, True)
    assert _cut(years, "2024-12-31") == ("2024", 4, True)


# ── 3. FRED `YYYY-MM-DD` — ★고치기 전과 같다★ (골든) ─────────────────────────────────────────
@pytest.mark.parametrize("as_of,last,n", [
    ("2024-06-30", "2024-06-01", 30),
    ("2024-06-15", "2024-06-01", 30),
    ("2024-05-31", "2024-05-01", 29),
    ("2021-12-31", None, 0),
])
def test_a_full_date_label_behaves_as_before(as_of, last, n):
    assert _cut(_FRED, as_of) == (last, n, True)


def test_a_timestamp_with_a_time_part_is_read_by_its_date():
    ts = ["2024-06-28 00:00:00", "2024-06-30T09:00:00", "2024-07-01 00:00:00"]
    assert _cut(ts, "2024-06-30") == ("2024-06-30T09:00:00", 2, True)


# ── 4. 형식이 섞여도 같은 달에서 끝난다 ──────────────────────────────────────────────────────
def test_series_in_different_formats_end_in_the_same_month():
    """운영에서는 한 응답 안에 한국은행(`YYYYMM`)과 FRED(`YYYY-MM-DD`) 계열이 섞인다.
    고치기 전에는 앞쪽은 2023-12, 뒤쪽은 2024-06 에서 끝났다 — 같은 as_of 인데 창이 달랐다."""
    sm = {"KOSPI": _S(_YM, [100.0 + 3 * i + (i % 5) for i in range(len(_YM))]),            # equity — 한국은행 형식
          "VIXCLS": _S(_FRED, [15.0 + (i * 7 % 11) for i in range(len(_FRED))])}           # volatility — FRED 형식
    p = resolve_proxies(sm, as_of="2024-06-30")
    assert set(p["resolved"]) == {"equity", "volatility"}, p["unresolved"]
    ends = {f: max(d["changes"]) for f, d in p["resolved"].items()}
    assert ends == {"equity": "2024-06", "volatility": "2024-06"}
    assert p["resolved"]["equity"]["n_months"] == p["resolved"]["volatility"]["n_months"] == 29
    assert p["as_of_honored"] is True


# ── 5. 모르는 모양은 ★못 잘랐다고 말한다★ ───────────────────────────────────────────────────
@pytest.mark.parametrize("labels", [
    ["2024Q1", "2024Q2", "2024Q3"],       # 분기 — 한국은행의 분기 표기는 검증되지 않았다(수집기도 지어내지 않는다)
    ["Jun-2024", "Jul-2024"],
    ["202413", "202501"],                 # 13월
    ["20240631", "20240701"],             # 6월 31일
    ["", "202406"],
])
def test_an_unknown_label_is_reported_as_not_cut(labels):
    s = _S(labels)
    cut, ok = truncate_series(s, "2024-06-30")
    assert ok is False, "읽지 못한 타임스탬프를 조용히 넣거나 뺐다"
    assert cut is s, "못 잘랐으면 원본을 그대로 돌려준다(반쯤 자른 것을 내지 않는다)"


def test_an_unreadable_series_in_use_means_the_cutoff_was_not_honored():
    """상류가 `macro_data_as_of` 를 선언하지 않게 된다 — 지키지 않은 절단일을 적지 않는다.

    ★실제로 쓰이는 계열이어야 한다★ 분기 라벨 같은 것은 월 변화도 못 만들어 애초에 쓰이지 않는다
    (그러면 `resolved` 가 비어 이 단언이 공허하게 참이 된다 — 처음에 그렇게 썼다가 고쳤다).
    날이 `00` 인 라벨은 달은 읽히지만(`series_changes` 는 앞 7자만 본다) 날짜로는 읽을 수 없다.
    """
    labels = [f"{y}-{m:02d}-00" for y in (2021, 2022, 2023, 2024, 2025) for m in range(1, 13)]
    sm = {"KOSPI": _S(labels, [100.0 + 2 * i + (i % 3) for i in range(len(labels))])}
    p = resolve_proxies(sm, as_of="2024-06-30")
    assert p["resolved"], "쓰인 계열이 없다 — 아래 단언이 공허하다"
    assert p["as_of_honored"] is False


def test_without_an_as_of_nothing_is_cut_or_judged():
    """★짝★ as_of 가 없으면 모양을 따지지 않는다 — 기본 경로는 그대로다."""
    s = _S(["2024Q1", "garbage"])
    cut, ok = truncate_series(s, None)
    assert cut is s and ok is True
