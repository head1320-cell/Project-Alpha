"""
가격·수급 팩터 스토어 — KIS OHLCV에서 파생 (재무와 독립적, 추가 API 불필요)
==========================================================================
fundamentals_store와 동일한 패턴:
  · DeterministicMockStore 상속 — 종목별 일관된 mock
  · 실제로는 KIS get_daily_ohlcv(과거 일봉)에서 계산
  · DART/재무와 무관한 독립 팩터군 → 팩터 다양성 실질 증가

팩터 카테고리:
  momentum   : 모멘텀 (1/3/6/12개월 수익률, 12-1 모멘텀)
  volatility : 변동성 (실현변동성, 베타, 최대낙폭, 다운사이드)
  technical  : 기술 위치 (52주 고저 대비, 이평선 이격, RSI)
  volume     : 거래 (거래량 추세, 거래대금, 회전율)
  supply     : 수급 (외국인·기관 순매수 — KIS 투자자별 매매동향)

KIS_USE_MOCK=1 또는 키 없으면 결정론적 mock, 실키 설정 시 실데이터 자동 사용.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

from src.data.mock_base import DeterministicMockStore

logger = logging.getLogger(__name__)


@dataclass
class PriceFactorMeta:
    id: str
    label: str
    category: str       # momentum | volatility | technical | volume | supply
    unit: str
    higher_better: bool
    typical_min: float
    typical_max: float
    source: str
    description: str


# ═══════════════════════════════════════════════════════════════════════════════
# 가격·수급 팩터 정의 (28개)
# ═══════════════════════════════════════════════════════════════════════════════
PRICE_FACTORS: list[PriceFactorMeta] = [
    # ── 모멘텀 ──
    PriceFactorMeta("return_1m", "1개월 수익률", "momentum", "%", True, -30, 30, "기본", "최근 21영업일 가격 수익률"),
    PriceFactorMeta("return_3m", "3개월 수익률", "momentum", "%", True, -40, 40, "기본", "최근 63영업일 수익률"),
    PriceFactorMeta("return_6m", "6개월 수익률", "momentum", "%", True, -50, 60, "기본", "최근 126영업일 수익률"),
    PriceFactorMeta("return_12m", "12개월 수익률", "momentum", "%", True, -50, 80, "Jegadeesh-Titman (1993)", "최근 252영업일 수익률"),
    PriceFactorMeta("momentum_12_1", "12-1 모멘텀", "momentum", "%", True, -40, 60, "Jegadeesh-Titman (1993)", "12개월 수익률 - 최근 1개월 (단기 반전 제거)"),
    PriceFactorMeta("momentum_6_1", "6-1 모멘텀", "momentum", "%", True, -40, 50, "기관 표준", "6개월 수익률 - 최근 1개월"),
    # ── 변동성 ──
    PriceFactorMeta("volatility_20d", "20일 변동성", "volatility", "%", False, 5, 80, "기본", "최근 20일 일간수익률 연율화 표준편차"),
    PriceFactorMeta("volatility_60d", "60일 변동성", "volatility", "%", False, 5, 70, "기본", "최근 60일 연율화 변동성"),
    PriceFactorMeta("beta_1y", "베타(1년)", "volatility", "", False, 0, 2.5, "CAPM", "시장 대비 민감도 (1년)"),
    PriceFactorMeta("max_drawdown_1y", "최대낙폭(1년)", "volatility", "%", False, 0, 70, "기본", "1년 내 고점 대비 최대 하락폭"),
    PriceFactorMeta("downside_vol", "하방변동성", "volatility", "%", False, 3, 50, "Sortino", "음의 수익률만의 변동성"),
    PriceFactorMeta("skewness", "수익률 왜도", "volatility", "", True, -2, 2, "기관 표준", "수익률 분포 비대칭 (양수=우측 꼬리)"),
    # ── 기술 위치 ──
    PriceFactorMeta("price_to_52w_high", "52주 고가 대비", "technical", "%", True, 30, 100, "기본", "현재가 / 52주 최고가 — 100% 근접 = 신고가"),
    PriceFactorMeta("price_to_52w_low", "52주 저가 대비", "technical", "%", True, 100, 400, "기본", "현재가 / 52주 최저가"),
    PriceFactorMeta("dist_ma20", "20일선 이격도", "technical", "%", True, -20, 20, "기본", "(현재가-20일이평) / 20일이평"),
    PriceFactorMeta("dist_ma60", "60일선 이격도", "technical", "%", True, -25, 25, "기본", "(현재가-60일이평) / 60일이평"),
    PriceFactorMeta("dist_ma120", "120일선 이격도", "technical", "%", True, -30, 30, "기본", "(현재가-120일이평) / 120일이평"),
    PriceFactorMeta("rsi_14", "RSI(14)", "technical", "", True, 0, 100, "Wilder", "상대강도지수 — 30↓ 과매도, 70↑ 과매수"),
    PriceFactorMeta("ma_alignment", "이평 정배열", "technical", "점", True, 0, 3, "기본", "5>20>60>120 정배열 충족 개수 (0~3)"),
    # ── 거래 ──
    PriceFactorMeta("volume_trend_20d", "거래량 추세", "volume", "%", True, -50, 100, "기본", "최근 5일 평균거래량 / 20일 평균 - 1"),
    PriceFactorMeta("turnover_rate", "거래회전율", "volume", "%", True, 0, 15, "기본", "거래량 / 상장주식수 (일평균)"),
    PriceFactorMeta("amount_20d_avg", "20일 평균거래대금", "volume", "억", True, 0, 5000, "기본", "최근 20일 평균 거래대금 (유동성)"),
    PriceFactorMeta("volume_spike", "거래량 급증", "volume", "배", True, 0, 5, "기본", "당일 거래량 / 20일 평균"),
    PriceFactorMeta("price_volume_corr", "가격-거래량 상관", "volume", "", True, -1, 1, "기관 표준", "최근 20일 가격·거래량 상관계수"),
    # ── 수급 (외국인·기관) ──
    PriceFactorMeta("foreign_net_5d", "외국인 5일 순매수", "supply", "억", True, -500, 500, "KIS 투자자동향", "최근 5일 외국인 순매수 금액"),
    PriceFactorMeta("foreign_net_20d", "외국인 20일 순매수", "supply", "억", True, -2000, 2000, "KIS 투자자동향", "최근 20일 외국인 순매수"),
    PriceFactorMeta("inst_net_5d", "기관 5일 순매수", "supply", "억", True, -500, 500, "KIS 투자자동향", "최근 5일 기관 순매수 금액"),
    PriceFactorMeta("inst_net_20d", "기관 20일 순매수", "supply", "억", True, -2000, 2000, "KIS 투자자동향", "최근 20일 기관 순매수"),
]

PRICE_FACTOR_BY_ID = {f.id: f for f in PRICE_FACTORS}

PRICE_CATEGORY_LABELS = {
    "momentum": "모멘텀",
    "volatility": "변동성",
    "technical": "기술 위치",
    "volume": "거래",
    "supply": "수급",
}


class PriceFactorsStore(DeterministicMockStore):
    """KIS OHLCV → 가격·수급 팩터. Mock + 실데이터 연결."""

    PERSIST = True  # 계산된 가격·수급 팩터를 DB(factor_snapshot)에 영속

    _default = None

    @classmethod
    def get_default(cls):
        if cls._default is None:
            cls._default = cls()
        return cls._default

    def get_factors(self, stock_code: str, item=None) -> dict:
        return self.cached(
            f"price_factors:{stock_code}",
            lambda: self._build_factors(stock_code, item),
        )

    def _build_factors(self, stock_code: str, item=None) -> dict:
        """실데이터(KIS OHLCV) 우선 → 실패 시 mock."""
        ohlcv = self._fetch_ohlcv(stock_code)
        if ohlcv and len(ohlcv) >= 60:
            try:
                return self._derive_from_ohlcv(stock_code, ohlcv)
            except Exception as e:
                logger.warning(f"가격 팩터 계산 실패 [{stock_code}]: {e}, mock 폴백")
        return self._mock_factors(stock_code)

    def _fetch_ohlcv(self, stock_code: str):
        """가격 팩터용 일봉 — 사전적재 daily_prices(DB) 우선 → KIS(없으면). 실데이터만(mock 안 씀).

        이전엔 종목마다 KIS를 직접 호출했으나, 사전적재(OHLCV prewarm/KRX)된 DB를 1순위로 읽어
        스크리닝 시 종목당 KIS 호출을 제거(백테스터와 동일 데이터원). KIS_USE_MOCK이면 None→_mock."""
        import os
        if os.getenv("KIS_USE_MOCK", "1") == "1":
            return None
        try:
            from datetime import datetime, timedelta

            from src.data.ohlcv_loader import _db_ohlcv_df, _kis_ohlcv_df, ingest_df_to_db
            end = datetime.now().strftime("%Y-%m-%d")
            start = (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d")
            df = _db_ohlcv_df(stock_code, start, end)
            if df is None or df.empty or len(df) < 60:
                df = _kis_ohlcv_df(stock_code, start, end)  # DB 미적재분 → KIS 후 적재(다음부터 DB)
                if df is not None and not df.empty:
                    try:
                        ingest_df_to_db(stock_code, df)
                    except Exception:
                        pass
            if df is None or df.empty:
                return None
            return [{"date": (i.strftime("%Y%m%d") if hasattr(i, "strftime") else str(i)),
                     "open": float(r["open"]), "high": float(r["high"]), "low": float(r["low"]),
                     "close": float(r["close"]), "volume": float(r.get("volume", 0) or 0)}
                    for i, r in df.iterrows()]
        except Exception as e:
            logger.debug(f"가격팩터 OHLCV 조회 실패 [{stock_code}]: {e}")
            return None

    # ── 실데이터 계산 ──────────────────────────────────────────────────────────
    def _derive_from_ohlcv(self, stock_code: str, ohlcv: list) -> dict:
        """OHLCV 시계열 → 가격 팩터 계산."""
        closes = [r["close"] for r in ohlcv if r.get("close")]
        vols = [r["volume"] for r in ohlcv if r.get("volume") is not None]
        n = len(closes)
        cur = closes[-1]

        def ret(days):
            if n > days and closes[-days - 1] > 0:
                return round((cur / closes[-days - 1] - 1) * 100, 2)
            return None

        def daily_returns(window):
            seg = closes[-window:] if n >= window else closes
            rets = [(seg[i] / seg[i - 1] - 1) for i in range(1, len(seg)) if seg[i - 1] > 0]
            return rets

        def annualized_vol(window):
            rets = daily_returns(window)
            if len(rets) < 2:
                return None
            mean = sum(rets) / len(rets)
            var = sum((x - mean) ** 2 for x in rets) / (len(rets) - 1)
            return round(math.sqrt(var) * math.sqrt(252) * 100, 2)

        def ma(days):
            seg = closes[-days:] if n >= days else closes
            return sum(seg) / len(seg) if seg else None

        r1m, r3m, r6m, r12m = ret(21), ret(63), ret(126), ret(252)
        ma20, ma60, ma120 = ma(20), ma(60), ma(120)
        ma5 = ma(5)
        hi52 = max(closes) if closes else cur
        lo52 = min(closes) if closes else cur

        # RSI(14)
        rsi = self._rsi(closes, 14)
        # 최대낙폭
        peak = closes[0]; mdd = 0.0
        for c in closes:
            peak = max(peak, c)
            mdd = min(mdd, c / peak - 1)
        # 하방변동성
        rets_all = daily_returns(min(n, 60))
        downs = [x for x in rets_all if x < 0]
        dvol = round(math.sqrt(sum(x*x for x in downs)/len(downs)) * math.sqrt(252) * 100, 2) if downs else None
        # 정배열
        align = 0
        if ma5 and ma20 and ma60 and ma120:
            if ma5 > ma20: align += 1
            if ma20 > ma60: align += 1
            if ma60 > ma120: align += 1
        # 거래량
        vol5 = sum(vols[-5:]) / 5 if len(vols) >= 5 else None
        vol20 = sum(vols[-20:]) / 20 if len(vols) >= 20 else None
        vol_trend = round((vol5 / vol20 - 1) * 100, 1) if (vol5 and vol20 and vol20 > 0) else None
        vol_spike = round(vols[-1] / vol20, 2) if (vol20 and vol20 > 0) else None

        def dist(price, m):
            return round((price / m - 1) * 100, 2) if (m and m > 0) else None

        out = {
            "return_1m": r1m, "return_3m": r3m, "return_6m": r6m, "return_12m": r12m,
            "momentum_12_1": round((r12m or 0) - (r1m or 0), 2) if r12m is not None else None,
            "momentum_6_1": round((r6m or 0) - (r1m or 0), 2) if r6m is not None else None,
            "volatility_20d": annualized_vol(20), "volatility_60d": annualized_vol(60),
            "beta_1y": self._beta(ohlcv),  # KOSPI(daily_prices) 대비 1년 베타 — 지수 미적재면 None
            "max_drawdown_1y": round(abs(mdd) * 100, 2),
            "downside_vol": dvol, "skewness": self._skew(rets_all),
            "price_to_52w_high": round(cur / hi52 * 100, 2) if hi52 > 0 else None,
            "price_to_52w_low": round(cur / lo52 * 100, 2) if lo52 > 0 else None,
            "dist_ma20": dist(cur, ma20), "dist_ma60": dist(cur, ma60), "dist_ma120": dist(cur, ma120),
            "rsi_14": rsi, "ma_alignment": align,
            "volume_trend_20d": vol_trend,
            "turnover_rate": self._turnover(stock_code, (vols[-1] * cur) if vols else None),
            "amount_20d_avg": round((vol20 or 0) * cur / 1e8, 1) if vol20 else None,
            "volume_spike": vol_spike, "price_volume_corr": self._corr(closes[-20:], vols[-20:]),
            # 수급(외국인·기관 순매수 N일 합) — investor_flows 적재(#3) 시 실값, 미적재면 None
            **self._supply_factors(stock_code),
            "_source": "kis_real",
        }
        return out

    def _supply_factors(self, stock_code: str) -> dict:
        """investor_flows(KIS/KRX MDC 적재)에서 외국인·기관 순매수 N일 합. 미적재면 전부 None."""
        out = {"foreign_net_5d": None, "foreign_net_20d": None,
               "inst_net_5d": None, "inst_net_20d": None}
        try:
            from src.data.kis_flows import load_flows_series
        except Exception:
            return out

        def _sum_last(field: str, days: int):
            s = load_flows_series(stock_code, field)
            if s is None or len(s) == 0:
                return None
            tail = s.dropna().tail(days)
            return round(float(tail.sum()), 0) if len(tail) else None
        out["foreign_net_5d"] = _sum_last("frgn_qty", 5)
        out["foreign_net_20d"] = _sum_last("frgn_qty", 20)
        out["inst_net_5d"] = _sum_last("orgn_qty", 5)
        out["inst_net_20d"] = _sum_last("orgn_qty", 20)
        return out

    def _market_returns(self):
        """시장지수(KOSPI 우선, 없으면 KOSDAQ) 일간수익률 — daily_prices 실적재분만(mock 없음).
        전 종목 공통이라 6시간 캐시. 지수 미적재면 None → 베타도 None(합성 안 함)."""
        import time
        now = time.time()
        c = getattr(self, "_mkt_ret_cache", None)
        if c and now - c[0] < 6 * 3600:
            return c[1]
        s = None
        try:
            from datetime import datetime, timedelta

            from src.data.ohlcv_loader import _db_ohlcv_df
            end = datetime.now().strftime("%Y-%m-%d")
            start = (datetime.now() - timedelta(days=480)).strftime("%Y-%m-%d")
            for idx in ("KOSPI", "KOSDAQ"):
                df = _db_ohlcv_df(idx, start, end)
                if df is not None and not df.empty and len(df) >= 60:
                    s = df["close"].astype(float).pct_change().dropna()
                    break
        except Exception:
            s = None
        self._mkt_ret_cache = (now, s)
        return s

    def _beta(self, ohlcv: list):
        """종목 일간수익률 vs 시장지수 1년 베타 (cov/var). 지수·표본 부족 시 None."""
        mkt = self._market_returns()
        if mkt is None or len(mkt) < 60:
            return None
        try:
            import pandas as pd
            rows = [(r.get("date"), r.get("close")) for r in ohlcv if r.get("close")]
            if len(rows) < 60:
                return None
            idx = pd.to_datetime([str(d) for d, _ in rows], format="%Y%m%d", errors="coerce")
            sret = pd.Series([float(c) for _, c in rows], index=idx).pct_change().dropna()
            j = pd.concat([sret, mkt], axis=1, join="inner").dropna().tail(252)
            if len(j) < 60:
                return None
            mser = j.iloc[:, 1]
            var = float(mser.var())
            if var <= 0:
                return None
            return round(float(j.iloc[:, 0].cov(mser)) / var, 2)
        except Exception:
            return None

    def _turnover(self, stock_code: str, trading_value):
        """거래대금/시가총액 × 100 (회전율 근사). 시총(DART get_raw_financials, 억) 미상이면 None.
        (volume×close=원, market_cap_억×1e8=원 → 단위 정합 비율.)"""
        if not trading_value:
            return None
        try:
            from src.data.fundamentals_store import FundamentalsStore
            raw = FundamentalsStore.get_default().get_raw_financials(stock_code) or {}
            mcap_억 = raw.get("market_cap")
            if mcap_억 and mcap_억 > 0:
                return round(trading_value / (mcap_억 * 1e8) * 100, 3)
        except Exception:
            pass
        return None

    @staticmethod
    def _rsi(closes, period=14):
        if len(closes) < period + 1:
            return None
        gains, losses = [], []
        for i in range(-period, 0):
            diff = closes[i] - closes[i - 1]
            gains.append(max(0, diff)); losses.append(max(0, -diff))
        ag = sum(gains) / period; al = sum(losses) / period
        if al == 0:
            return 100.0
        rs = ag / al
        return round(100 - 100 / (1 + rs), 1)

    @staticmethod
    def _skew(rets):
        if len(rets) < 3:
            return None
        m = sum(rets) / len(rets)
        sd = (sum((x - m) ** 2 for x in rets) / len(rets)) ** 0.5
        if sd == 0:
            return 0.0
        return round(sum(((x - m) / sd) ** 3 for x in rets) / len(rets), 2)

    @staticmethod
    def _corr(a, b):
        if len(a) != len(b) or len(a) < 3:
            return None
        n = len(a)
        ma_, mb = sum(a) / n, sum(b) / n
        cov = sum((a[i] - ma_) * (b[i] - mb) for i in range(n))
        va = sum((x - ma_) ** 2 for x in a) ** 0.5
        vb = sum((x - mb) ** 2 for x in b) ** 0.5
        if va == 0 or vb == 0:
            return 0.0
        return round(cov / (va * vb), 2)

    # ── Mock (결정론적, 종목별 일관) ─────────────────────────────────────────────
    def _mock_factors(self, stock_code: str) -> dict:
        u = self._uniform; nm = self._normal
        r1m = round(nm(stock_code, "r1m", mu=1, sigma=8), 2)
        r3m = round(nm(stock_code, "r3m", mu=3, sigma=14), 2)
        r6m = round(nm(stock_code, "r6m", mu=5, sigma=20), 2)
        r12m = round(nm(stock_code, "r12m", mu=8, sigma=28), 2)
        vol20 = round(abs(nm(stock_code, "vol20", mu=28, sigma=12)) + 8, 2)
        align = int(u(stock_code, "align", lo=0, hi=3.99))
        return {
            "return_1m": r1m, "return_3m": r3m, "return_6m": r6m, "return_12m": r12m,
            "momentum_12_1": round(r12m - r1m, 2), "momentum_6_1": round(r6m - r1m, 2),
            "volatility_20d": vol20, "volatility_60d": round(vol20 * u(stock_code, "v60", lo=0.85, hi=1.1), 2),
            "beta_1y": round(abs(nm(stock_code, "beta", mu=1.0, sigma=0.35)), 2),
            "max_drawdown_1y": round(abs(nm(stock_code, "mdd", mu=22, sigma=10)) + 5, 2),
            "downside_vol": round(vol20 * u(stock_code, "dvol", lo=0.6, hi=0.85), 2),
            "skewness": round(nm(stock_code, "skew", mu=0, sigma=0.6), 2),
            "price_to_52w_high": round(min(100, abs(nm(stock_code, "p52h", mu=82, sigma=12))), 2),
            "price_to_52w_low": round(abs(nm(stock_code, "p52l", mu=135, sigma=30)) + 100, 2),
            "dist_ma20": round(nm(stock_code, "d20", mu=0, sigma=6), 2),
            "dist_ma60": round(nm(stock_code, "d60", mu=1, sigma=10), 2),
            "dist_ma120": round(nm(stock_code, "d120", mu=2, sigma=14), 2),
            "rsi_14": round(min(95, max(5, nm(stock_code, "rsi", mu=52, sigma=16))), 1),
            "ma_alignment": align,
            "volume_trend_20d": round(nm(stock_code, "vt", mu=5, sigma=30), 1),
            "turnover_rate": round(abs(nm(stock_code, "turn", mu=1.2, sigma=1.5)), 2),
            "amount_20d_avg": round(abs(nm(stock_code, "amt", mu=300, sigma=600)) + 10, 1),
            "volume_spike": round(abs(nm(stock_code, "vspk", mu=1.1, sigma=0.6)) + 0.3, 2),
            "price_volume_corr": round(nm(stock_code, "pvc", mu=0.1, sigma=0.4), 2),
            "foreign_net_5d": round(nm(stock_code, "f5", mu=0, sigma=120), 1),
            "foreign_net_20d": round(nm(stock_code, "f20", mu=0, sigma=400), 1),
            "inst_net_5d": round(nm(stock_code, "i5", mu=0, sigma=100), 1),
            "inst_net_20d": round(nm(stock_code, "i20", mu=0, sigma=350), 1),
            "_source": "price_mock",
        }


def attach_price_factors(items: list) -> int:
    """ScreenerItem 리스트에 가격·수급 팩터 주입 (attach_fundamentals와 동일 패턴)."""
    import os
    store = PriceFactorsStore.get_default()
    codes = [c for c in (getattr(it, "stock_code", None) for it in items) if c]
    store.prime([f"price_factors:{c}" for c in codes])  # DB → in-memory 벌크(1쿼리)
    max_live = int(os.getenv("SCREENER_MAX_LIVE_COMPUTE", "400"))
    live = 0
    count = 0
    for it in items:
        code = getattr(it, "stock_code", None)
        if not code:
            continue
        if f"price_factors:{code}" not in store._cache:
            if live >= max_live:
                continue
            live += 1
        factors = store.get_factors(code, it)
        for fid, val in factors.items():
            if not fid.startswith("_"):
                setattr(it, fid, val)
        count += 1
    return count


def price_factors_catalog() -> dict:
    """API용 가격 팩터 카탈로그."""
    by_cat: dict = {}
    for f in PRICE_FACTORS:
        by_cat.setdefault(f.category, []).append({
            "id": f.id, "label": f.label, "unit": f.unit,
            "higher_better": f.higher_better,
            "typical_min": f.typical_min, "typical_max": f.typical_max,
            "source": f.source, "description": f.description,
        })
    return {"categories": [
        {"id": cat, "label": PRICE_CATEGORY_LABELS.get(cat, cat), "factors": items}
        for cat, items in by_cat.items()
    ]}
