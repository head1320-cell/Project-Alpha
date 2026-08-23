"""날짜가 붙은 종가 접근자 — 두 종목을 **날짜로 맞춰야 하는** 계산의 전제 (Phase 8, Drift 8-5).

★왜 이 접근자가 필요한가★
`daily_closes()` 는 값만 돌려준다. 두 종목의 꼬리를 zip 하면 "두 종목의 거래일이 같다" 고
가정하게 되는데, 한·미 달력이 다르고 상장일도 달라서 실제로는 **다른 날짜끼리 짝지어진다.**
그 상태로 상관계수를 계산하면 숫자는 나오지만 그 숫자가 무엇의 상관인지 말할 수 없다.
스펙 §6.2 가 VIX 텀 스트럭처에 대해 금지한 것과 같은 종류의 오류다("결측을 전진 채움하면
낡았지만 자신만만한 신호를 만들어낸다").
"""
import pytest

from src.data import etf_prices as ep


@pytest.fixture(autouse=True)
def _clear_cache():
    ep.cache_clear()
    yield
    ep.cache_clear()


def _fake_df(dates, closes):
    import pandas as pd
    return pd.DataFrame({"close": closes}, index=pd.to_datetime(dates))


def test_returns_date_close_pairs(monkeypatch):
    monkeypatch.setattr(ep, "_daily_df",
                        lambda code: _fake_df(["2026-01-02", "2026-01-05"], [100.0, 101.0]))
    out = ep.daily_closes_indexed("SPY", "us", 10)
    assert out == [("2026-01-02", 100.0), ("2026-01-05", 101.0)]


def test_dates_are_iso_strings_so_two_tickers_can_be_joined(monkeypatch):
    """조인 키가 되므로 표현이 안정적이어야 한다 — Timestamp 객체면 비교가 미묘해진다."""
    monkeypatch.setattr(ep, "_daily_df", lambda code: _fake_df(["2026-03-02"], [7.0]))
    (d, v), = ep.daily_closes_indexed("SPY", "us", 5)
    assert isinstance(d, str) and len(d) == 10 and d.count("-") == 2
    assert isinstance(v, float)


def test_tail_limit_matches_daily_closes(monkeypatch):
    dates = [f"2026-01-{i:02d}" for i in range(1, 11)]
    monkeypatch.setattr(ep, "_daily_df", lambda code: _fake_df(dates, list(range(10))))
    out = ep.daily_closes_indexed("SPY", "us", 3)
    assert [v for _, v in out] == [7.0, 8.0, 9.0]


def test_as_of_truncation_is_honored(monkeypatch):
    """★as_of 관례를 따르지 않으면 과거 미리보기가 미래를 본다★

    `daily_closes` 는 as_of 안에서 뒤에서 (개월×21봉) 만큼 잘라낸다. 새 접근자가 그 규칙을
    따르지 않으면 6b-2 의 과거 미리보기가 이 팩터에 대해서만 조용히 룩어헤드를 갖는다.
    """
    import pandas as pd
    # ★날짜는 date_range 로 만든다★ f"2026-01-{i:02d}" 로 42개를 만들면 2026-01-42 같은
    # 존재하지 않는 날짜가 섞여 to_datetime 이 던지고, 접근자가 빈 리스트를 돌려주는 바람에
    # 이 테스트가 "절단됐다" 가 아니라 "데이터가 없다" 를 확인하게 된다(실제로 그렇게 깨졌다).
    dates = pd.date_range("2026-01-01", periods=42, freq="D")
    monkeypatch.setattr(ep, "_daily_df", lambda code: _fake_df(dates, list(range(42))))
    full = ep.daily_closes_indexed("SPY", "us", 100)
    ep.cache_clear()
    with ep.as_of(1):                      # 1개월 = 21 거래일 절단
        cut = ep.daily_closes_indexed("SPY", "us", 100)
    assert len(cut) == len(full) - 21
    assert cut[-1][0] < full[-1][0], "as_of 안에서 더 이른 날짜로 끝나야 한다"


def test_missing_data_returns_empty_not_fabricated(monkeypatch):
    monkeypatch.setattr(ep, "_daily_df", lambda code: None)
    assert ep.daily_closes_indexed("NOPE", "us", 10) == []


def test_rows_without_a_close_are_dropped_not_zero_filled(monkeypatch):
    """결측 종가를 0 으로 채우면 수익률이 −100% 로 튄다 — 행을 버린다."""
    import numpy as np
    monkeypatch.setattr(ep, "_daily_df", lambda code: _fake_df(
        ["2026-01-02", "2026-01-03", "2026-01-06"], [100.0, np.nan, 102.0]))
    out = ep.daily_closes_indexed("SPY", "us", 10)
    assert [d for d, _ in out] == ["2026-01-02", "2026-01-06"]
