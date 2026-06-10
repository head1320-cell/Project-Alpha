"""granular 유니버스 선택기(select_universe) 단위 테스트.

시총 6단계 tier·업종·ETF·관심그룹·관리/감리 제외를 픽스처 프레임으로 검증.
load_universe_frame / _status_codes 를 monkeypatch — DB·실데이터 불필요.
"""
import pandas as pd
import pytest

from src.engine import universe_select as us


# ─── 픽스처 프레임 ────────────────────────────────────────────────────────────
def fixture_frame() -> pd.DataFrame:
    rows = [
        # ticker, market, tier, sector, market_cap(억), is_etf
        ("005930", "KOSPI", "kospi_l", "반도체", 4_000_000, False),
        ("000270", "KOSPI", "kospi_m", "자동차", 20_000, False),
        ("247540", "KOSDAQ", "kosdaq_l", "이차전지", 15_000, False),
        ("058470", "KOSDAQ", "kosdaq_m", "반도체", 5_000, False),
        ("123456", "KOSDAQ", "kosdaq_s", "바이오", 1_500, False),
        ("654321", "KOSDAQ", "kosdaq_xs", None, 500, False),
        ("069500", "KOSPI", "kospi_l", None, None, True),   # ETF
    ]
    return pd.DataFrame(rows, columns=["ticker", "market", "tier", "sector",
                                       "market_cap", "is_etf"])


@pytest.fixture
def patched_frame(monkeypatch):
    monkeypatch.setattr(us, "load_universe_frame", fixture_frame)
    monkeypatch.setattr(us, "_status_codes", lambda: (frozenset(), frozenset()))
    return fixture_frame()


# ─── 시총군(tier) ────────────────────────────────────────────────────────────
def test_cap_tier_filter(patched_frame):
    tickers, total = us.select_universe(caps=["kospi_l"])
    assert total == 7
    assert tickers == ["005930"]  # ETF(069500)는 기본 제외

    tickers, _ = us.select_universe(caps=["kosdaq_l", "kosdaq_m"])
    assert set(tickers) == {"247540", "058470"}


def test_no_caps_means_all_tiers(patched_frame):
    tickers, _ = us.select_universe()
    assert set(tickers) == {"005930", "000270", "247540", "058470", "123456", "654321"}


# ─── 업종 ────────────────────────────────────────────────────────────────────
def test_sector_filter(patched_frame):
    tickers, _ = us.select_universe(sectors=["반도체"])
    assert set(tickers) == {"005930", "058470"}


def test_unknown_sector_is_noop(patched_frame):
    """알 수 없는 업종명만 오면 전체 통과(fake id 방어)."""
    tickers, _ = us.select_universe(sectors=["존재하지않는업종"])
    assert len(tickers) == 6


# ─── ETF ─────────────────────────────────────────────────────────────────────
def test_etf_excluded_by_default_included_when_on(patched_frame):
    assert "069500" not in us.select_universe()[0]
    assert "069500" in us.select_universe(etf=True)[0]


# ─── 관심그룹 ─────────────────────────────────────────────────────────────────
def test_watchlist_exclude_and_include(patched_frame):
    tickers, _ = us.select_universe(groups=[{"mode": "exclude", "tickers": ["005930"]}])
    assert "005930" not in tickers

    # include 는 다른 필터에 걸렸더라도 다시 포함(union)
    tickers, _ = us.select_universe(caps=["kospi_l"],
                                    groups=[{"mode": "include", "tickers": ["123456"]}])
    assert set(tickers) == {"005930", "123456"}


# ─── 관리/감리 제외 ───────────────────────────────────────────────────────────
def test_managed_supervised_exclusion(monkeypatch):
    monkeypatch.setattr(us, "load_universe_frame", fixture_frame)
    monkeypatch.setattr(us, "_status_codes",
                        lambda: (frozenset({"058470"}), frozenset({"123456"})))
    # 토글 미포함(기본) → 관리/감리 코드 제외
    tickers, _ = us.select_universe()
    assert "058470" not in tickers and "123456" not in tickers
    # 토글 포함 → 유지
    tickers, _ = us.select_universe(managed=True, supervised=True)
    assert "058470" in tickers and "123456" in tickers


# ─── 시총 tier 산출 ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("market,mcap,expected", [
    ("KOSPI", 30_000, "kospi_l"),    # ≥ 3조 → 대형
    ("KOSPI", 29_999, "kospi_m"),
    ("KOSDAQ", 10_000, "kosdaq_l"),  # ≥ 1조 → 대형
    ("KOSDAQ", 3_000, "kosdaq_m"),   # ≥ 3천억 → 중형
    ("KOSDAQ", 1_000, "kosdaq_s"),   # ≥ 1천억 → 소형
    ("KOSDAQ", 999, "kosdaq_xs"),    # 미만 → 초소형
])
def test_tier_from_mcap_thresholds(market, mcap, expected):
    assert us._tier_from_mcap(market, mcap, proxy="unused") == expected


def test_tier_falls_back_to_proxy_without_mcap():
    assert us._tier_from_mcap("KOSPI", None, proxy="kospi_m") == "kospi_m"


def test_empty_frame_returns_empty(monkeypatch):
    monkeypatch.setattr(us, "load_universe_frame",
                        lambda: pd.DataFrame(columns=["ticker", "market", "tier",
                                                      "sector", "market_cap", "is_etf"]))
    assert us.select_universe() == ([], 0)
