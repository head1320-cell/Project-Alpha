# 대상 경로: src/engine/universe_select.py
#
# granular 유니버스 선택기 (공용) — 카운트 엔드포인트와 백테스트 후보 구성에서 함께 사용.
# 실데이터 기반: UNIVERSE_PRESETS(시총군 proxy) + STOCK_SECTOR(업종) + ETF 카테고리.
#
# 시총군(caps): market_cap이 정적 컬럼이 아니므로 프리셋 멤버십을 size proxy로 사용
#   kospi50 → kospi_l(대형) / kospi200(¬50) → kospi_m(중형) / kosdaq150 → kosdaq_l(대형)
#   그 외 코스닥 → kosdaq_s(소형, m/s/xs 합산). 시총 tier 세분화는 시총 데이터 연동 시 정밀화.
# 업종(sectors): STOCK_SECTOR의 실제 업종명. (프론트는 /sectors 로 실제 업종명을 받아 전송)
# ETF: ticker_universe의 ETF 카테고리. 관리/감리: 데이터 없음 → no-op.

from __future__ import annotations

from functools import lru_cache

import pandas as pd

# 프론트 시총군 id → 내부 tier. 시총 데이터로 실제 6단계 tier를 산출하므로 항등 매핑.
_CAP_TO_TIER = {
    "kospi_l": "kospi_l", "kospi_m": "kospi_m",
    "kosdaq_l": "kosdaq_l", "kosdaq_m": "kosdaq_m",
    "kosdaq_s": "kosdaq_s", "kosdaq_xs": "kosdaq_xs",
}


def _etf_codes() -> set[str]:
    try:
        from src.ticker_universe import TICKER_UNIVERSE
        out: set[str] = set()
        for name, items in TICKER_UNIVERSE.items():
            if "ETF" in name.upper():
                for t in items:
                    out.add(str(t[0]).split(".")[0])
        return out
    except Exception:
        return set()


def _market_cap_of(code: str) -> float | None:
    """종목 시가총액(억원) — fundamentals_store(결정론적) 조회. 실패 시 None."""
    try:
        from src.data.fundamentals_store import FundamentalsStore
        f = FundamentalsStore.get_default().get_factors(code)
        mc = f.get("market_cap")
        return float(mc) if mc is not None else None
    except Exception:
        return None


# 시총군 임계값(억원) — 튜닝 지점
CAP_TIER_THRESHOLDS = {
    "kospi_large": 30000,    # KOSPI 대형 ≥ 3조
    "kosdaq_large": 10000,   # KOSDAQ 대형 ≥ 1조
    "kosdaq_mid": 3000,      # KOSDAQ 중형 ≥ 3천억
    "kosdaq_small": 1000,    # KOSDAQ 소형 ≥ 1천억 (미만 초소형)
}


def _tier_from_mcap(market: str, mcap: float | None, proxy: str) -> str:
    """시총 기반 6단계 tier. 시총 없으면 프리셋 proxy 사용. 임계값은 CAP_TIER_THRESHOLDS."""
    if mcap is None:
        return proxy
    t = CAP_TIER_THRESHOLDS
    if market == "KOSPI":
        return "kospi_l" if mcap >= t["kospi_large"] else "kospi_m"
    if mcap >= t["kosdaq_large"]:
        return "kosdaq_l"
    if mcap >= t["kosdaq_mid"]:
        return "kosdaq_m"
    if mcap >= t["kosdaq_small"]:
        return "kosdaq_s"
    return "kosdaq_xs"


@lru_cache(maxsize=1)
def _status_codes() -> tuple[frozenset, frozenset]:
    """관리종목/감리(투자주의) 종목코드. 데이터 소스가 있으면 채워지고, 없으면 빈 집합.
    채우는 법: stock_master 에 MANAGED_CODES / SUPERVISED_CODES 를 정의하면 자동 인식."""
    managed: set = set()
    supervised: set = set()
    try:
        from src.data import stock_master as sm
        managed = set(getattr(sm, "MANAGED_CODES", []) or [])
        supervised = set(getattr(sm, "SUPERVISED_CODES", []) or [])
    except Exception:
        pass
    return (frozenset(str(c).split(".")[0] for c in managed),
            frozenset(str(c).split(".")[0] for c in supervised))


@lru_cache(maxsize=1)
def load_universe_frame() -> pd.DataFrame:
    """전체 매매가능 종목 프레임: ticker, market, tier, sector, market_cap, is_etf."""
    from src.engine.screener import UNIVERSE_PRESETS, get_sector_universe

    kospi50 = set(UNIVERSE_PRESETS.get("kospi50", []))
    kospi200 = set(UNIVERSE_PRESETS.get("kospi200", []))
    kosdaq150 = set(UNIVERSE_PRESETS.get("kosdaq150", []))

    sector_map: dict[str, str] = {}
    try:
        for sector, codes in get_sector_universe().items():
            for c in codes:
                sector_map[str(c)] = sector
    except Exception:
        pass

    etf = _etf_codes()
    codes = set().union(kospi50, kospi200, kosdaq150, set(sector_map.keys()))

    rows = []
    for c in codes:
        c = str(c)
        market = "KOSPI" if (c in kospi50 or c in kospi200) else "KOSDAQ"
        if c in kospi50:
            proxy = "kospi_l"
        elif c in kospi200:
            proxy = "kospi_m"
        elif c in kosdaq150:
            proxy = "kosdaq_l"
        else:
            proxy = "kosdaq_s"
        mcap = _market_cap_of(c)
        tier = _tier_from_mcap(market, mcap, proxy)
        rows.append({
            "ticker": c, "market": market, "tier": tier,
            "sector": sector_map.get(c), "market_cap": mcap, "is_etf": c in etf,
        })
    return pd.DataFrame(rows, columns=["ticker", "market", "tier", "sector", "market_cap", "is_etf"])


def select_universe(
    caps: list[str] | None = None,
    sectors: list[str] | None = None,
    etf: bool = False,
    managed: bool = False,
    supervised: bool = False,
    groups: list[dict] | None = None,
) -> tuple[list[str], int]:
    """granular 선택 → (통과 종목코드 리스트, 전체 종목 수)."""
    df = load_universe_frame()
    total = int(len(df))
    if total == 0:
        return [], 0

    mask = pd.Series(True, index=df.index)

    # 시총군(tier) — proxy
    caps = caps or []
    tiers = {_CAP_TO_TIER.get(c) for c in caps if _CAP_TO_TIER.get(c)}
    if tiers:
        mask &= df["tier"].isin(tiers)

    # 업종(실제 업종명). 알 수 없는 값만 오면 no-op(전체 통과) — fake id 방어.
    sectors = [s for s in (sectors or []) if s]
    known = set(df["sector"].dropna().unique())
    sel = [s for s in sectors if s in known]
    if sel:
        mask &= df["sector"].isin(sel)

    # ETF — 미포함이면 제외
    if not etf:
        mask &= ~df["is_etf"].fillna(False)

    # 관리/감리: 토글 미포함(기본)이면 해당 코드 제외. 데이터 소스 없으면 집합이 비어 no-op.
    managed_codes, supervised_codes = _status_codes()
    tk0 = df["ticker"].astype(str)
    if not managed and managed_codes:
        mask &= ~tk0.isin(managed_codes)
    if not supervised and supervised_codes:
        mask &= ~tk0.isin(supervised_codes)

    # 관심그룹
    exclude: set[str] = set()
    include: set[str] = set()
    for g in (groups or []):
        mode = g.get("mode")
        ts = [str(t) for t in (g.get("tickers") or [])]
        if mode == "exclude":
            exclude.update(ts)
        elif mode == "include":
            include.update(ts)
    tk = df["ticker"].astype(str)
    if exclude:
        mask &= ~tk.isin(exclude)
    if include:
        mask |= tk.isin(include)

    tickers = df.loc[mask, "ticker"].astype(str).tolist()
    return tickers, total
