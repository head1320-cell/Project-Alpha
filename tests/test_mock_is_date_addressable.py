"""mock 시세는 **날짜**에 값을 붙인다 — 창 안의 위치가 아니라.

★이 파일이 있는 이유 (실측)★ mock 생성기는 요청 **창의 시작점**에서 난수 보행을
시작했고 시드는 종목명에만 의존했다. 그래서 같은 난수열이 다른 날짜에 붙었다:

    2024-06-03 종가 = 40,311.88   (2022 시작 창에서 조회)
    2024-06-03 종가 = 33,623.99   (2023 시작 창에서 조회)   ← 같은 날, 20% 차이

가격이 날짜가 아니라 **창 안의 위치**에 붙어 있었다는 뜻이다. 결과:

  · `as_of` 를 과거로 옮겨도 마지막 종가가 **똑같이** 나온다
  · 그래서 mock 이 기본값인 개발·테스트 환경에서 **모든 PIT/as_of 단언이 무의미**하다
  · `tests/test_alpha_portfolio_gate.py::test_a_past_as_of_changes_the_portfolio` 가
    이것을 잡고 있었고, 이 저장소에서 유일하게 오래 남아 있던 red 였다

★이 가드가 없으면 재발을 알 수 없다★ 재발해도 다른 테스트는 전부 통과한다 —
그것이 이 결함이 오래 살아남은 이유다.
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402

from src.data.ohlcv_loader import _mock_ohlcv_df  # noqa: E402

_T = "005930"
_PROBE = "2024-06-03"


def _at(start: str, end: str, col: str = "close") -> float:
    df = _mock_ohlcv_df(_T, start, end)
    row = df.loc[df.index == _PROBE, col]
    assert len(row) == 1, f"{_PROBE} 이 창 [{start}, {end}] 에 없다"
    return float(row.iloc[0])


# ── 1. ★같은 날짜 = 같은 값★ ────────────────────────────────────────────
@pytest.mark.parametrize("start", ["2020-01-01", "2022-01-01", "2023-01-01", "2023-07-15"])
def test_the_same_date_has_the_same_close_in_any_window(start):
    """창의 시작점을 바꿔도 그 날의 종가는 같아야 한다."""
    assert _at(start, "2025-06-30") == pytest.approx(_at("2021-01-01", "2025-06-30"))


@pytest.mark.parametrize("end", ["2024-12-31", "2025-06-30", "2026-08-24"])
def test_the_same_date_has_the_same_close_for_any_end(end):
    """★짝★ 끝점을 바꿔도 마찬가지다 — 끝점이 값을 밀지 않는다."""
    assert _at("2022-01-01", end) == pytest.approx(_at("2022-01-01", "2025-06-30"))


@pytest.mark.parametrize("col", ["open", "high", "low", "volume"])
def test_ohlc_and_volume_are_date_addressable_too(col):
    """★종가만 고치면 절반이다★ 시가·고가·저가·거래량의 잡음을 위치에서 뽑으면
    같은 결함이 되살아난다."""
    assert _at("2022-01-01", "2025-06-30", col) == \
        pytest.approx(_at("2023-01-01", "2025-06-30", col))


# ── 2. ★그래서 as_of 가 결과를 바꾼다★ ─────────────────────────────────
def test_a_later_window_ends_on_a_different_price():
    """앞의 단언들이 "전부 상수" 로도 만족되지 않게 — 끝값은 실제로 달라야 한다."""
    late = float(_mock_ohlcv_df(_T, "2022-01-01", "2026-08-24")["close"].iloc[-1])
    early = float(_mock_ohlcv_df(_T, "2022-01-01", "2025-06-30")["close"].iloc[-1])
    assert late != pytest.approx(early), \
        "as_of 를 옮겨도 마지막 종가가 같다 — 값이 날짜가 아니라 위치에 붙어 있다"


def test_the_series_is_not_degenerate():
    """★짝★ "전부 같은 값" 이면 위 단언들이 공짜로 통과한다."""
    px = _mock_ohlcv_df(_T, "2023-01-01", "2025-06-30")["close"]
    assert len(px) > 400
    assert px.nunique() > 100, "합성 계열이 사실상 상수다"
    assert px.min() > 0


def test_windows_agree_on_their_whole_overlap():
    """단일 프로브 날짜가 우연히 맞은 것이 아님을 겹치는 구간 전체로 확인한다."""
    a = _mock_ohlcv_df(_T, "2021-06-01", "2025-06-30")["close"]
    b = _mock_ohlcv_df(_T, "2023-02-14", "2026-01-31")["close"]
    common = a.index.intersection(b.index)
    assert len(common) > 500, f"겹치는 구간이 너무 짧다: {len(common)}"
    assert (a.loc[common] - b.loc[common]).abs().max() == pytest.approx(0.0, abs=1e-9)
