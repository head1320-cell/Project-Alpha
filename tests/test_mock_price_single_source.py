"""mock 가격의 출처는 하나다 — ★지금 주가 = 시세 이력의 마지막 종가★
==============================================================================
2026-11-11 · 사용자 요청 "서버 mock 출처도 맞춰줘"

## 무엇이 문제였나 (실측)

연습용(mock) 자료에서 가격을 만드는 곳이 서로 다른 값을 냈다:

    지금 주가      screener._mock_price          고정 표 — 005930 = 71,000 (날짜와 무관)
    시점 가격      pit_store.get_price_asof      지금 주가 × (1 − 0.02 × 분기 수) × U(0.85, 1.15) — 과거 종가가 아니다
    일봉           ohlcv_loader._mock_walk       2000-01-03 기점 걸음 — 005930 의 2026-11-10 종가 56,511.67
                                                  (표에 없는 123456 은 걸음 137.95 · 지금 주가 52,333 — 379배)

기업 화면의 헤더는 71,000원인데 1년 주가 선은 56,512원에서 끝났다. 프론트는 그 차이를 덮으려고 과거 종가에 배율을
곱해 그렸고(걷어 냈다 — `1d9a109`), 덮지 않자 차이가 그대로 보였다.

## 무엇을 못 박나

1. **한 출처** — 지금 주가도 시점 가격도 날짜 주소 가능한 걸음(`mock_close_asof`)에서 읽는다.
2. **수준은 표를 지킨다** — mock 재무가 표 가격 수준에 맞춰져 있다(삼성전자 EPS ≈ 4,690 · 표 71,000). 걸음에 종목별
   ★상수★ 배율을 곱해 기준일(`_MOCK_ANCHOR`)의 종가가 표 값이 되게 한다. 상수라서 수익률·거래량은 그대로다.
3. **날짜 주소 가능성은 그대로** — 배율은 "오늘"이 아니라 고정 기준일로 정한다. 오늘에 맞추면 같은 날짜가 날마다 다른
   값이 된다(`tests/test_mock_is_date_addressable.py` 가 지키는 성질 · 프론트에서 걷은 배율을 서버로 옮기는 셈).
4. **운영은 그대로** — `KIS_USE_MOCK≠1` 이면 두 함수 모두 고치기 전과 같은 값을 낸다(골든). 운영 동작 변경은 이번 범위가 아니다.
5. **가격은 원 단위다** — 지금 주가·시점 가격은 그 날 종가를 원 단위로 반올림한 값이다(`mock_price_asof`). 걸음의 종가는
   소수라서 그대로 내면 응답에 "198,671.081원"이 실린다(전체 E2E 가 잡았다 — 홈·스크리너의 "서버 값 그대로" 시험 둘).
   예전 고정 표는 늘 정수였고 KRX 가격도 원 단위다. ★일봉은 반올림하지 않는다★ — 반올림하면 수익률이 바뀐다.

아래 골든 숫자는 고치기 전 코드에서 잰 것이다(2026-11-11).
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import math  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402

import pytest  # noqa: E402

import src.data.ohlcv_loader as ol  # noqa: E402
import src.engine.pit_store as ps  # noqa: E402
from src.engine.screener import ValuationScreener  # noqa: E402

TABLE = "005930"      # 표에 있는 종목 — 수준 71,000
OTHER = "123456"      # 표에 없는 종목 — 수준은 해시 값 52,333(걸음의 날것 값은 138 근처였다)
INDEX = "KOSPI"       # 지수 — 배율을 곱하지 않는다

# 고치기 전의 걸음(날것) — 종가와 거래량
RAW = {
    TABLE: {"2025-06-27": (38969.95282221712, 246887.1798741106), "2025-06-30": (37965.909233941486, 516689.8350950001),
            "2026-11-10": (56511.67075195304, 427743.23691045865), "2026-11-11": (58837.48539587131, 690747.1549466156)},
    OTHER: {"2025-06-27": (223.1977214154839, 813424.0679453439), "2025-06-30": (223.67656717910458, 669439.7514680693),
            "2026-11-10": (137.95236771760776, 618625.0371632436), "2026-11-11": (136.49405183291015, 720301.2226033629)},
    INDEX: {"2025-06-27": (15833.317814748261, 1948063.6682748778), "2025-06-30": (15921.391940297544, 2215817.0589083396),
            "2026-11-10": (16564.6165643027, 3329304.4705923484), "2026-11-11": (16500.05280322401, 2639743.022524929)},
}
LEVEL = {TABLE: 71000.0, OTHER: 52333.0}          # 고치기 전 `_mock_price` 가 내던 값
ANCHOR = "2026-11-10"


@pytest.fixture
def mock_mode(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")


def _pin_today(monkeypatch, y: int, m: int, d: int) -> datetime:
    """mock 의 "오늘"을 고정한다 — 자정 근처에서 흔들리지 않게, 그리고 주말·다른 날을 넣어 보려고."""
    day = datetime(y, m, d, 12, 0, 0)
    monkeypatch.setattr(ol, "_mock_today", lambda: day)
    return day


def _df(code: str, end: datetime, days: int = 400):
    return ol.load_ohlcv_unified(code, (end - timedelta(days=days)).strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), "mock")


def _won(x: float) -> float:
    """원 단위 반올림(반은 올린다) — 화면의 `Math.round` 와 같은 규칙. 파이썬 `round` 는 반을 짝수로 보내 다르다."""
    return float(math.floor(x + 0.5))


def _close_on(code: str, day: str) -> float:
    df = ol.load_ohlcv_unified(code, "2025-01-01", "2026-12-31", "mock")
    row = df.loc[df.index == day, "close"]
    assert len(row) == 1, f"{code} 의 {day} 봉이 없다"
    return float(row.iloc[0])


# ── 1. ★지금 주가 = 시세 이력의 마지막 종가★ ─────────────────────────────────────────────────────
@pytest.mark.parametrize("code", [TABLE, OTHER])
@pytest.mark.parametrize("today", [(2026, 11, 11), (2026, 11, 14), (2027, 3, 2)])        # 평일 · 토요일(금요일 종가) · 몇 달 뒤
def test_the_price_now_is_the_last_close_of_the_history(mock_mode, monkeypatch, code, today):
    day = _pin_today(monkeypatch, *today)
    last = float(_df(code, day)["close"].iloc[-1])
    assert ValuationScreener._mock_price(code) == _won(last)


def test_the_price_now_moves_with_the_day(mock_mode, monkeypatch):
    """★짝★ 날짜와 무관한 상수(옛 표)를 내는 구현을 배제한다 — 다른 날이면 다른 값이다."""
    _pin_today(monkeypatch, 2026, 11, 10)
    a = ValuationScreener._mock_price(TABLE)
    _pin_today(monkeypatch, 2026, 11, 11)
    b = ValuationScreener._mock_price(TABLE)
    assert a == 71000.0, "기준일의 지금 주가는 표 값이다"
    assert b != pytest.approx(a, rel=1e-6)
    want = 71000.0 * RAW[TABLE]["2026-11-11"][0] / RAW[TABLE]["2026-11-10"][0]
    assert abs(b - want) <= 0.5 + 1e-6, "하루 사이의 변화 = 걸음의 그날 수익률(원 단위 반올림만큼만 다르다)"


# ── 2. ★시점 가격 = 그 날의 종가★ ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("code", [TABLE, OTHER])
@pytest.mark.parametrize("as_of", ["2025-06-27", "2025-06-30"])
def test_the_as_of_price_is_that_days_close(mock_mode, monkeypatch, code, as_of):
    _pin_today(monkeypatch, 2026, 11, 11)
    store = ps.PITStore.get_default()
    want = _won(_close_on(code, as_of))
    assert store.get_price_asof(code, as_of, 71000.0) == want
    # 옛 식은 넘겨받은 "지금 주가"에 난수를 곱했다 — 그 날의 종가는 넘겨받은 값과 무관해야 한다
    assert store.get_price_asof(code, as_of, 12345.0) == want


def test_as_of_today_is_the_price_now(mock_mode, monkeypatch):
    """"지금"은 as_of = 오늘과 같은 말이다 — 예전에는 71,000 과 66,629.55 로 달랐다."""
    _pin_today(monkeypatch, 2026, 11, 11)
    now = ValuationScreener._mock_price(TABLE)
    assert ps.PITStore.get_default().get_price_asof(TABLE, "2026-11-11", now) == now


def test_an_as_of_day_without_a_bar_uses_the_last_trading_day(mock_mode, monkeypatch):
    _pin_today(monkeypatch, 2026, 11, 11)
    sunday = ps.PITStore.get_default().get_price_asof(TABLE, "2025-06-29", 71000.0)       # 일요일 → 금요일(06-27) 종가
    assert sunday == _won(_close_on(TABLE, "2025-06-27"))


# ── 2b. ★가격은 원 단위★ — 종가(소수)를 그대로 내지 않는다 · 일봉은 반올림하지 않는다 ─────────────────
def test_mock_prices_are_whole_won(mock_mode, monkeypatch):
    """지금 주가·시점 가격에 소수점이 없다. 올림과 내림이 둘 다 일어나는 날을 넣어 "내림" 구현을 배제한다."""
    store, seen = ps.PITStore.get_default(), []
    for code, day in [(OTHER, "2025-06-30"), (OTHER, "2025-06-27"), (TABLE, "2026-11-11"), ("207940", "2025-06-27")]:
        close = ol.mock_close_asof(code, day)
        y, m, d = (int(x) for x in day.split("-"))
        _pin_today(monkeypatch, y, m, d)
        for px in (ValuationScreener._mock_price(code), store.get_price_asof(code, day, 1.0), ol.mock_price_asof(code, day)):
            assert px == int(px), f"{code} {day}: {px} 에 소수점이 있다"
            assert px == _won(close), f"{code} {day}: {px} ≠ 반올림({close})"
        seen.append(close % 1)
    assert any(f >= 0.5 for f in seen) and any(f < 0.5 for f in seen), f"올림·내림이 둘 다 있어야 이 검사가 뜻이 있다: {seen}"


def test_daily_bars_are_not_rounded(mock_mode):
    """★짝★ 일봉의 종가는 걸음 그대로(소수)다 — 반올림하면 수익률이 바뀐다."""
    for code in (TABLE, OTHER):
        close = _close_on(code, "2025-06-30")
        assert close != int(close), f"{code}: 일봉 종가 {close} 가 정수다"
        assert close == ol.mock_close_asof(code, "2025-06-30")


# ── 3. ★수준 — 기준일의 종가가 표 값★ · 상수 배율이라 모양은 그대로 ───────────────────────────────
@pytest.mark.parametrize("code", [TABLE, OTHER])
def test_the_anchor_day_close_is_the_level(mock_mode, code):
    assert _close_on(code, ANCHOR) == pytest.approx(LEVEL[code], rel=1e-9)
    assert ol.mock_close_asof(code, ANCHOR) == pytest.approx(LEVEL[code], rel=1e-9)


@pytest.mark.parametrize("code", [TABLE, OTHER])
def test_returns_and_volume_are_what_they_were(mock_mode, code):
    """배율은 종목마다 ★상수★다 — 날짜 사이의 비율(수익률)과 거래량은 고치기 전과 같다."""
    days = sorted(RAW[code])
    new = {d: _close_on(code, d) for d in days}
    k = new[days[0]] / RAW[code][days[0]][0]
    assert k != pytest.approx(1.0, rel=1e-3), "배율이 1 이면 이 검사는 공허하다(수준을 옮기지 않았다)"
    for d in days:
        assert new[d] / RAW[code][d][0] == pytest.approx(k, rel=1e-12), f"{d} 의 배율이 다르다 — 상수가 아니다"
    df = ol.load_ohlcv_unified(code, "2025-01-01", "2026-12-31", "mock")
    for d in days:
        assert float(df.loc[df.index == d, "volume"].iloc[0]) == pytest.approx(RAW[code][d][1], rel=1e-12)
    row = df.loc[df.index == days[1]].iloc[0]
    assert row["low"] <= row["close"] <= row["high"], "시가·고가·저가도 같이 옮겨져야 한다"


def test_an_index_is_not_rescaled(mock_mode):
    """지수는 표에 없고 수준을 옮길 까닭이 없다 — 고치기 전 값 그대로."""
    for d, (close, vol) in RAW[INDEX].items():
        assert _close_on(INDEX, d) == pytest.approx(close, rel=1e-12)


# ── 4. ★날짜 주소 가능성은 그대로★ — 배율은 "오늘"이 아니라 고정 기준일로 정한다 ────────────────────
def test_a_past_close_does_not_move_when_today_moves(mock_mode, monkeypatch):
    """프로세스가 다른 날 새로 떴다고 치고(캐시를 비운다) 같은 과거 날짜를 다시 읽는다."""
    seen = []
    for today in [(2026, 11, 11), (2027, 6, 1)]:
        _pin_today(monkeypatch, *today)
        for fn in (getattr(ol, "_mock_walk", None), getattr(ol, "_mock_walk_raw", None), getattr(ol, "_mock_scale", None)):
            if fn is not None and hasattr(fn, "cache_clear"):
                fn.cache_clear()
        seen.append((_close_on(TABLE, "2025-06-30"), ol.mock_close_asof(TABLE, "2025-06-30")))
    assert seen[0] == pytest.approx(seen[1], rel=1e-12)
    assert seen[0][0] == pytest.approx(seen[0][1], rel=1e-12)


# ── 5. ★운영은 그대로★ (골든 — 고치기 전에 잰 값) ───────────────────────────────────────────────
class _Fixed(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 11, 11, 12, 0, 0)


@pytest.mark.parametrize("code,want", [("005930", 71000), ("000660", 200000), ("123456", 52333.0), ("999999", 56854.0)])
def test_in_real_mode_the_base_price_is_unchanged(monkeypatch, code, want):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    assert ValuationScreener._mock_price(code) == want


@pytest.mark.parametrize("code,as_of,cur,want", [
    ("005930", "2024-06-03", 71000.0, 53293.333388082065),
    ("123456", "2025-06-30", 50000.0, 39490.94252365739),
    ("005930", "2026-11-11", 71000.0, 66629.55077811869),
])
def test_in_real_mode_the_as_of_price_is_unchanged(monkeypatch, code, as_of, cur, want):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    monkeypatch.setattr(ps, "datetime", _Fixed)
    assert ps.PITStore.get_default().get_price_asof(code, as_of, cur) == pytest.approx(want, rel=1e-12)


# ── 6. 가장자리 ────────────────────────────────────────────────────────────────────────────────
def test_a_suffixed_ticker_reads_the_same_walk_as_the_loader(mock_mode, monkeypatch):
    """`load_ohlcv_unified` 는 `.KS`·`.KQ` 를 떼고 읽는다 — 지금 주가도 같은 종목을 읽어야 둘이 같다."""
    day = _pin_today(monkeypatch, 2026, 11, 11)
    last = float(_df("005930.KS", day)["close"].iloc[-1])
    assert ValuationScreener._mock_price("005930.KS") == _won(last)
    assert ol.mock_close_asof("005930.KS") == ol.mock_close_asof("005930")


def test_before_the_mock_epoch_there_is_no_bar(mock_mode, monkeypatch):
    """기점(2000-01-03) 이전에는 mock 봉이 없다 — 종가를 지어내지 않고(`None`), 시점 가격은 예전 식 그대로다(바닥값 100)."""
    monkeypatch.setattr(ps, "datetime", _Fixed)
    assert ol.mock_close_asof(TABLE, "1999-12-31") is None
    assert ol.mock_close_asof(TABLE, "2000-01-03") is not None
    assert ps.PITStore.get_default().get_price_asof(TABLE, "1999-12-31", 71000.0) == 100
