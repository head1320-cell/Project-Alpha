"""
Global Ticker Universe
=======================
Curated universe of major tickers across Korea, US, Europe, Japan,
Commodities, Currencies, and Indices — with search and autocomplete.
"""


import streamlit as st

# ═══════════════════════════════════════════════════════════════════════════════
# Ticker Database — Category → [(ticker, name, currency)]
# ═══════════════════════════════════════════════════════════════════════════════

TICKER_UNIVERSE: dict[str, list[tuple[str, str, str]]] = {
    "Korea Large Cap": [
        ("005930.KS", "삼성전자", "KRW"),
        ("000660.KS", "SK하이닉스", "KRW"),
        ("035420.KS", "NAVER", "KRW"),
        ("035720.KS", "카카오", "KRW"),
        ("005380.KS", "현대자동차", "KRW"),
        ("051910.KS", "LG화학", "KRW"),
        ("006400.KS", "삼성SDI", "KRW"),
        ("068270.KS", "셀트리온", "KRW"),
        ("028260.KS", "삼성물산", "KRW"),
        ("105560.KS", "KB금융", "KRW"),
        ("055550.KS", "신한지주", "KRW"),
        ("003550.KS", "LG", "KRW"),
        ("207940.KS", "삼성바이오로직스", "KRW"),
        ("000270.KS", "기아", "KRW"),
        ("012330.KS", "현대모비스", "KRW"),
        ("066570.KS", "LG전자", "KRW"),
        ("034730.KS", "SK", "KRW"),
        ("096770.KS", "SK이노베이션", "KRW"),
        ("030200.KS", "KT", "KRW"),
        ("017670.KS", "SK텔레콤", "KRW"),
    ],
    "Korea ETF": [
        ("069500.KS", "KODEX 200", "KRW"),
        ("229200.KS", "KODEX 코스닥150", "KRW"),
        ("114800.KS", "KODEX 인버스", "KRW"),
        ("252670.KS", "KODEX 200선물인버스2X", "KRW"),
        ("133690.KS", "TIGER 미국나스닥100", "KRW"),
        ("360750.KS", "TIGER 미국S&P500", "KRW"),
        ("381180.KS", "TIGER 미국테크TOP10", "KRW"),
        ("453810.KS", "TIGER 미국배당다우존스", "KRW"),
    ],
    "US Large Cap": [
        ("AAPL", "Apple", "USD"),
        ("MSFT", "Microsoft", "USD"),
        ("GOOGL", "Alphabet (Google)", "USD"),
        ("AMZN", "Amazon", "USD"),
        ("NVDA", "NVIDIA", "USD"),
        ("META", "Meta (Facebook)", "USD"),
        ("TSLA", "Tesla", "USD"),
        ("BRK-B", "Berkshire Hathaway", "USD"),
        ("JPM", "JP Morgan", "USD"),
        ("V", "Visa", "USD"),
        ("JNJ", "Johnson & Johnson", "USD"),
        ("WMT", "Walmart", "USD"),
        ("MA", "Mastercard", "USD"),
        ("PG", "Procter & Gamble", "USD"),
        ("UNH", "UnitedHealth", "USD"),
        ("HD", "Home Depot", "USD"),
        ("DIS", "Walt Disney", "USD"),
        ("BAC", "Bank of America", "USD"),
        ("XOM", "ExxonMobil", "USD"),
        ("KO", "Coca-Cola", "USD"),
    ],
    "US ETF": [
        ("SPY", "S&P 500 ETF", "USD"),
        ("QQQ", "Nasdaq-100 ETF", "USD"),
        ("IWM", "Russell 2000 ETF", "USD"),
        ("DIA", "Dow Jones ETF", "USD"),
        ("VTI", "Total Stock Market", "USD"),
        ("TLT", "20+ Year Treasury", "USD"),
        ("HYG", "High Yield Bond ETF", "USD"),
        ("LQD", "Investment Grade Bond", "USD"),
        ("GLD", "Gold ETF", "USD"),
        ("SLV", "Silver ETF", "USD"),
        ("EEM", "Emerging Markets ETF", "USD"),
        ("VNQ", "Real Estate ETF", "USD"),
        ("XLF", "Financial Sector ETF", "USD"),
        ("XLE", "Energy Sector ETF", "USD"),
        ("XLK", "Technology Sector ETF", "USD"),
        ("ARKK", "ARK Innovation ETF", "USD"),
    ],
    "Europe": [
        ("^STOXX50E", "Euro Stoxx 50", "EUR"),
        ("SAP.DE", "SAP (Germany)", "EUR"),
        ("SIE.DE", "Siemens", "EUR"),
        ("ALV.DE", "Allianz", "EUR"),
        ("MC.PA", "LVMH", "EUR"),
        ("OR.PA", "L'Oreal", "EUR"),
        ("SAN.PA", "Sanofi", "EUR"),
        ("ASML.AS", "ASML", "EUR"),
        ("NESN.SW", "Nestle", "CHF"),
        ("ROG.SW", "Roche", "CHF"),
        ("SHEL.L", "Shell", "GBP"),
        ("AZN.L", "AstraZeneca", "GBP"),
        ("HSBA.L", "HSBC", "GBP"),
    ],
    "Japan": [
        ("7203.T", "Toyota", "JPY"),
        ("6758.T", "Sony", "JPY"),
        ("6861.T", "Keyence", "JPY"),
        ("9984.T", "SoftBank Group", "JPY"),
        ("6902.T", "Denso", "JPY"),
        ("8306.T", "MUFG", "JPY"),
        ("9433.T", "KDDI", "JPY"),
        ("4063.T", "Shin-Etsu Chemical", "JPY"),
        ("6501.T", "Hitachi", "JPY"),
        ("8035.T", "Tokyo Electron", "JPY"),
    ],
    "China/HK": [
        ("9988.HK", "Alibaba (HK)", "HKD"),
        ("0700.HK", "Tencent", "HKD"),
        ("9618.HK", "JD.com (HK)", "HKD"),
        ("1211.HK", "BYD", "HKD"),
        ("3690.HK", "Meituan", "HKD"),
        ("2318.HK", "Ping An Insurance", "HKD"),
        ("0941.HK", "China Mobile", "HKD"),
    ],
    "Indices": [
        ("^GSPC", "S&P 500", "USD"),
        ("^DJI", "Dow Jones", "USD"),
        ("^IXIC", "NASDAQ Composite", "USD"),
        ("^KS11", "KOSPI", "KRW"),
        ("^KQ11", "KOSDAQ", "KRW"),
        ("^N225", "Nikkei 225", "JPY"),
        ("^HSI", "Hang Seng", "HKD"),
        ("^FTSE", "FTSE 100", "GBP"),
        ("^GDAXI", "DAX", "EUR"),
        ("^VIX", "VIX (공포지수)", "USD"),
    ],
    "FX Currencies": [
        ("EURUSD=X", "EUR/USD", "USD"),
        ("JPYUSD=X", "JPY/USD", "USD"),
        ("GBPUSD=X", "GBP/USD", "USD"),
        ("KRWUSD=X", "KRW/USD", "USD"),
        ("USDKRW=X", "USD/KRW", "KRW"),
        ("CNHUSD=X", "CNH/USD", "USD"),
    ],
    "Commodities": [
        ("GC=F", "Gold Futures", "USD"),
        ("SI=F", "Silver Futures", "USD"),
        ("CL=F", "WTI Crude Oil", "USD"),
        ("BZ=F", "Brent Crude Oil", "USD"),
        ("NG=F", "Natural Gas", "USD"),
        ("HG=F", "Copper Futures", "USD"),
        ("ZC=F", "Corn Futures", "USD"),
        ("ZW=F", "Wheat Futures", "USD"),
    ],
    "Crypto": [
        ("BTC-USD", "Bitcoin", "USD"),
        ("ETH-USD", "Ethereum", "USD"),
        ("SOL-USD", "Solana", "USD"),
        ("BNB-USD", "Binance Coin", "USD"),
        ("XRP-USD", "Ripple", "USD"),
        ("ADA-USD", "Cardano", "USD"),
    ],
}

# Flat lookup: ticker → (name, currency, category)
_TICKER_LOOKUP: dict[str, tuple[str, str, str]] = {}
for cat, items in TICKER_UNIVERSE.items():
    for ticker, name, currency in items:
        _TICKER_LOOKUP[ticker] = (name, currency, cat)


def get_all_tickers() -> list[str]:
    """Return flat list of all tickers."""
    return list(_TICKER_LOOKUP.keys())


def get_ticker_info(ticker: str) -> dict:
    """Return name, currency, category for a ticker."""
    info = _TICKER_LOOKUP.get(ticker)
    if info:
        return {"ticker": ticker, "name": info[0], "currency": info[1], "category": info[2]}
    return {"ticker": ticker, "name": ticker, "currency": "?", "category": "기타"}


def search_tickers(query: str, limit: int = 10) -> list[dict]:
    """Search tickers by name or code (case-insensitive)."""
    q = query.upper().strip()
    if not q:
        return []
    results = []
    for ticker, (name, currency, cat) in _TICKER_LOOKUP.items():
        if q in ticker.upper() or q in name.upper():
            results.append({
                "ticker": ticker,
                "name": name,
                "currency": currency,
                "category": cat,
                "display": f"{ticker}  —  {name}  [{currency}]",
            })
            if len(results) >= limit:
                break
    return results


def format_ticker_display(ticker: str) -> str:
    """Format ticker for display: 'AAPL — Apple [USD]'"""
    info = _TICKER_LOOKUP.get(ticker)
    if info:
        return f"{ticker}  —  {info[0]}  [{info[1]}]"
    return ticker


# ═══════════════════════════════════════════════════════════════════════════════
# Streamlit Widget: Ticker Selector with Category + Search
# ═══════════════════════════════════════════════════════════════════════════════

def ticker_selector(
    label: str = "종목 선택",
    default: str = "005930.KS",
    key: str = "ticker_sel",
    show_search: bool = True,
) -> str:
    """
    Full-featured ticker selector for Streamlit sidebar.

    Features:
      - Category-based browsing (tabs)
      - Search by ticker or name
      - Shows name + currency
      - Supports manual input for unlisted tickers
    """
    # Search mode
    if show_search:
        search_q = st.text_input(
            f" {label} (검색 또는 직접 입력)",
            value=default,
            key=f"{key}_search",
            help="티커 코드 또는 종목명으로 검색. 목록에 없는 Yahoo Finance 티커도 직접 입력 가능.",
        )

        # If it matches a known ticker exactly, use it
        if search_q.strip() in _TICKER_LOOKUP:
            info = get_ticker_info(search_q.strip())
            st.caption(f" {info['name']} [{info['currency']}] — {info['category']}")
            return search_q.strip()

        # Otherwise show search results
        if len(search_q.strip()) >= 2:
            results = search_tickers(search_q.strip(), limit=8)
            if results:
                options = [r["display"] for r in results]
                tickers = [r["ticker"] for r in results]
                selected_display = st.selectbox(
                    "검색 결과", options, key=f"{key}_results",
                )
                selected_idx = options.index(selected_display)
                selected_ticker = tickers[selected_idx]
                return selected_ticker

        # Manual ticker (not in universe)
        if search_q.strip():
            st.caption(f" 직접 입력: {search_q.strip()} (Yahoo Finance 형식)")
            return search_q.strip()

    return default


def multi_ticker_selector(
    label: str = "종목 추가",
    max_tickers: int = 10,
    key: str = "multi_tk",
) -> list[dict]:
    """
    Multi-ticker selector for portfolio building.

    Returns list of {ticker, name, weight} dicts.
    """
    # Category selector
    categories = list(TICKER_UNIVERSE.keys())
    selected_cat = st.selectbox("카테고리", categories, key=f"{key}_cat")

    # Tickers in selected category
    cat_items = TICKER_UNIVERSE[selected_cat]
    display_options = [f"{t[0]}  —  {t[1]}" for t in cat_items]
    ticker_codes = [t[0] for t in cat_items]

    # Multi-select
    selected_displays = st.multiselect(
        label, display_options,
        key=f"{key}_multi",
        max_selections=max_tickers,
    )

    selected = []
    for display in selected_displays:
        idx = display_options.index(display)
        ticker = ticker_codes[idx]
        info = get_ticker_info(ticker)
        selected.append(info)

    return selected
