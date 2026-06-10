"""
Multi-Asset Portfolio Manager
==============================
Build, analyze, and manage diversified portfolios across global markets.

Features:
  - Add/remove tickers with weight allocation
  - Auto-normalize weights to 100%
  - Correlation matrix visualization
  - Risk contribution decomposition
  - Portfolio optimization hints
"""

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.ticker_universe import (
    get_ticker_info,
    search_tickers,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Portfolio State Management
# ═══════════════════════════════════════════════════════════════════════════════

def _init_portfolio_state():
    """Initialize session state for portfolio holdings."""
    if "portfolio_holdings" not in st.session_state:
        st.session_state["portfolio_holdings"] = [
            {"ticker": "005930.KS", "weight": 0.30},
            {"ticker": "AAPL", "weight": 0.25},
            {"ticker": "NVDA", "weight": 0.20},
            {"ticker": "SPY", "weight": 0.15},
            {"ticker": "GC=F", "weight": 0.10},
        ]


def get_holdings() -> list[dict]:
    """Return current portfolio holdings with enriched info."""
    _init_portfolio_state()
    holdings = []
    for h in st.session_state["portfolio_holdings"]:
        info = get_ticker_info(h["ticker"])
        holdings.append({
            **info,
            "weight": h["weight"],
        })
    return holdings


def set_holdings(holdings: list[dict]):
    """Update portfolio holdings."""
    st.session_state["portfolio_holdings"] = [
        {"ticker": h["ticker"], "weight": h["weight"]}
        for h in holdings
    ]


def normalize_weights(holdings: list[dict]) -> list[dict]:
    """Normalize weights to sum to 1.0."""
    total = sum(h["weight"] for h in holdings)
    if total <= 0:
        n = len(holdings)
        return [{**h, "weight": round(1.0 / n, 4)} for h in holdings]
    return [{**h, "weight": round(h["weight"] / total, 4)} for h in holdings]


# ═══════════════════════════════════════════════════════════════════════════════
# Portfolio Builder UI
# ═══════════════════════════════════════════════════════════════════════════════

def render_portfolio_builder() -> list[dict]:
    """
    Render the interactive portfolio builder widget.

    Returns the current list of holdings [{ticker, name, weight, ...}].
    """
    _init_portfolio_state()
    holdings = get_holdings()

    st.markdown("#### Portfolio Composition")

    # ─── Current Holdings Table ──────────────────────────────────────────
    if holdings:
        sum(h["weight"] for h in holdings)

        # Display as styled cards
        for i, h in enumerate(holdings):
            c1, c2, c3, c4, c5 = st.columns([2, 3, 2, 1, 1])
            c1.markdown(f"**{h['ticker']}**")
            c2.caption(f"{h['name']} [{h['currency']}]")
            new_weight = c3.number_input(
                "비중", value=round(h["weight"] * 100, 1),
                min_value=0.0, max_value=100.0, step=1.0,
                key=f"pw_{i}", label_visibility="collapsed",
            )
            holdings[i]["weight"] = new_weight / 100

            if c4.button("", key=f"del_{i}"):
                st.session_state["portfolio_holdings"].pop(i)
                st.rerun()

        # Weight summary bar
        total = sum(h["weight"] for h in holdings)
        color = "#28a745" if abs(total - 1.0) < 0.01 else "#ffc107" if total < 1.0 else "#dc3545"
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:8px;margin:8px 0">'
            f'<div style="flex:1;background:#e8ecf1;border-radius:4px;height:8px">'
            f'<div style="width:{min(total*100,100):.0f}%;background:{color};'
            f'border-radius:4px;height:8px"></div></div>'
            f'<span style="font-weight:600;color:{color}">{total*100:.1f}%</span></div>',
            unsafe_allow_html=True,
        )

        # Normalize button
        if abs(total - 1.0) > 0.01:
            if st.button("Normalize to 100%", key="normalize"):
                normalized = normalize_weights(holdings)
                set_holdings(normalized)
                st.rerun()

    # ─── Add New Ticker ──────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("**종목 추가**")

    a1, a2, a3 = st.columns([3, 2, 1])
    new_ticker = a1.text_input(
        "티커 코드 검색",
        placeholder="AAPL, 005930.KS, GC=F ...",
        key="add_ticker_input",
    )
    new_weight = a2.number_input("비중 (%)", value=10.0, min_value=0.1, max_value=100.0,
                                   step=1.0, key="add_weight")

    # Show search suggestions
    if new_ticker and len(new_ticker) >= 2:
        results = search_tickers(new_ticker, limit=5)
        if results:
            suggestions = [r["display"] for r in results]
            st.caption(f" 검색 결과: {' | '.join(suggestions[:3])}")

    if a3.button("Add", key="add_btn"):
        if new_ticker.strip():
            ticker_code = new_ticker.strip().upper()
            # Check if already in portfolio
            existing = [h["ticker"] for h in st.session_state["portfolio_holdings"]]
            if ticker_code in existing:
                st.warning(f"{ticker_code} 이미 포트폴리오에 있습니다.")
            else:
                st.session_state["portfolio_holdings"].append({
                    "ticker": ticker_code,
                    "weight": new_weight / 100,
                })
                st.rerun()

    # ─── Quick Add Presets ───────────────────────────────────────────────
    with st.expander("Preset Portfolios"):
        presets = {
            "Korea Blue Chip": [
                ("005930.KS", 0.30), ("000660.KS", 0.20),
                ("035420.KS", 0.15), ("005380.KS", 0.15),
                ("051910.KS", 0.10), ("105560.KS", 0.10),
            ],
            "US Big Tech": [
                ("AAPL", 0.20), ("MSFT", 0.20), ("GOOGL", 0.15),
                ("AMZN", 0.15), ("NVDA", 0.15), ("META", 0.15),
            ],
            "Global Diversified": [
                ("SPY", 0.25), ("069500.KS", 0.20), ("ASML.AS", 0.10),
                ("7203.T", 0.10), ("GC=F", 0.10), ("TLT", 0.15),
                ("EEM", 0.10),
            ],
            "60/40 Equity/Bond": [
                ("SPY", 0.40), ("QQQ", 0.20),
                ("TLT", 0.25), ("LQD", 0.15),
            ],
            "All-Weather": [
                ("SPY", 0.30), ("TLT", 0.40),
                ("GLD", 0.15), ("DIA", 0.075), ("EEM", 0.075),
            ],
            "Crypto + Traditional": [
                ("BTC-USD", 0.15), ("ETH-USD", 0.10),
                ("SPY", 0.30), ("GLD", 0.15), ("TLT", 0.30),
            ],
        }

        cols = st.columns(3)
        for idx, (name, tickers) in enumerate(presets.items()):
            if cols[idx % 3].button(name, key=f"preset_{idx}", use_container_width=True):
                st.session_state["portfolio_holdings"] = [
                    {"ticker": t, "weight": w} for t, w in tickers
                ]
                st.rerun()

    # Save and return
    set_holdings(holdings)
    return holdings


# ═══════════════════════════════════════════════════════════════════════════════
# Portfolio Analysis Charts
# ═══════════════════════════════════════════════════════════════════════════════

def render_portfolio_pie(holdings: list[dict]):
    """Render a donut chart of portfolio weights."""
    if not holdings:
        return

    labels = [f"{h['ticker']}\n{h['name']}" for h in holdings]
    values = [h["weight"] for h in holdings]

    colors = px.colors.qualitative.Set3[:len(holdings)]

    fig = go.Figure(go.Pie(
        labels=labels, values=values,
        hole=0.55,
        textinfo="label+percent",
        textfont_size=11,
        marker=dict(colors=colors, line=dict(color="#ffffff", width=2)),
    ))
    fig.update_layout(
        title="포트폴리오 구성 비중",
        showlegend=False,
        height=380,
        margin=dict(t=50, b=20, l=20, r=20),
    )
    st.plotly_chart(fig, use_container_width=True)


def render_portfolio_summary(holdings: list[dict], portfolio_value: float):
    """Render summary metrics for the portfolio."""
    if not holdings:
        return

    n_assets = len(holdings)
    n_countries = len(set(h.get("currency", "?") for h in holdings))
    n_categories = len(set(h.get("category", "?") for h in holdings))
    max_weight = max(h["weight"] for h in holdings)
    hhi = sum(h["weight"] ** 2 for h in holdings)  # Herfindahl index

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("종목 수", f"{n_assets}")
    c2.metric("통화 수", f"{n_countries}")
    c3.metric("카테고리", f"{n_categories}")
    c4.metric("최대 비중", f"{max_weight:.0%}")
    c5.metric("집중도 (HHI)", f"{hhi:.3f}",
              help="HHI < 0.15 = 분산 양호, > 0.25 = 집중 과다")

    # Diversification assessment
    if hhi < 0.15:
        st.success(" 분산이 양호합니다 (HHI < 0.15)")
    elif hhi < 0.25:
        st.info(" 적정 수준의 집중도입니다")
    else:
        st.warning(" 포트폴리오가 특정 종목에 집중되어 있습니다 (HHI > 0.25)")


def get_portfolio_tickers_weights(holdings: list[dict]) -> tuple[list[str], list[float]]:
    """Extract tickers and weights for API calls."""
    tickers = [h["ticker"] for h in holdings]
    weights = [h["weight"] for h in holdings]
    return tickers, weights
