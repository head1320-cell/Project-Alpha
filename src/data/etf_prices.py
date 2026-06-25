"""ETF 가격 소스 — 택티컬 자산배분 전략 시그널용 (US 원본 ⇄ 국내 ETF 토글)
==========================================================================
13 택티컬 전략(전통/종합/가속 듀얼모멘텀·영구포트·LAA·RAA·GTAA·PAA·VAA·FAA·AAA·DAA·채권동적)이
쓰는 ETF의 월간 종가·일간 종가를 공급한다.

데이터: load_ohlcv_unified(DB→KIS→mock) 재사용.
  · 국내(market="kr"): KRX/KIS 실데이터(키 설정 시), 없으면 결정론적 mock.
  · 글로벌(market="us"): 미국 ETF — GCP에선 KIS 해외주식/적재 DB, 샌드박스는 결정론적 mock.
    (US 실시세 연동은 데이터 단계에서 KIS 해외주식 API로 — 현재는 mock 폴백으로 엔진 검증.)
키 없으면 전부 mock(결정론적)이라 시그널은 항상 산출되되, 실값은 GCP에서.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# 일간 히스토리 적재 윈도우 (장기 상관/타이밍 추이용). DB가 깊을수록 롤링 분석이 자동 장기화.
# 기본 ~5년. mock도 이 길이만큼 결정론 생성 → 샌드박스 롤링 차트도 길어짐.
_HISTORY_DAYS = int(os.getenv("ETF_HISTORY_DAYS", "1825") or 1825)

# ── 미국 ETF 유니버스 (전략들이 참조) ──────────────────────────────────────────
US_UNIVERSE: dict[str, str] = {
    "SPY": "S&P500", "QQQ": "나스닥100", "IWD": "미국 대형가치", "IWN": "미국 소형가치",
    "IWM": "미국 소형주", "VTI": "미국 전체시장", "EFA": "선진국(미국제외)", "EEM": "신흥국",
    "EWJ": "일본", "SCZ": "선진국 소형", "VNQ": "미국 리츠", "REM": "모기지 리츠",
    "TLT": "미국 장기국채", "IEF": "미국 중기국채", "SHY": "미국 단기국채", "BIL": "초단기 국채(현금)",
    "AGG": "미국 종합채권", "LQD": "투자등급 회사채", "HYG": "하이일드", "EMB": "신흥국 채권",
    "TIP": "물가연동채", "GLD": "금", "PDBC": "원자재", "DBC": "원자재(광의)",
}

# ── 국내 ETF 매핑 (US 티커 → KODEX/TIGER 등 국내 대응) ──────────────────────────
US_TO_KR: dict[str, tuple[str, str]] = {
    "SPY": ("379800", "KODEX 미국S&P500"), "QQQ": ("379810", "KODEX 미국나스닥100"),
    "IWD": ("379800", "KODEX 미국S&P500"), "IWM": ("277630", "KODEX 미국러셀2000"),
    "IWN": ("277630", "KODEX 미국러셀2000"), "VTI": ("379800", "KODEX 미국S&P500"),
    "EFA": ("195930", "TIGER 선진국MSCI"), "EEM": ("195980", "TIGER 신흥국MSCI"),
    "EWJ": ("241180", "TIGER 일본니케이225"), "SCZ": ("195930", "TIGER 선진국MSCI"),
    "VNQ": ("182480", "TIGER 미국리츠"), "REM": ("182480", "TIGER 미국리츠"),
    "TLT": ("304660", "KODEX 미국채10년"), "IEF": ("305080", "TIGER 미국채10년"),
    "SHY": ("153130", "KODEX 단기채권"), "BIL": ("153130", "KODEX 단기채권"),
    "AGG": ("273130", "KODEX 종합채권액티브"), "LQD": ("273130", "KODEX 종합채권액티브"),
    "HYG": ("182490", "TIGER 단기선진하이일드"), "EMB": ("332620", "ARIRANG 미국채30년"),
    "TIP": ("305080", "TIGER 미국채10년"), "GLD": ("132030", "KODEX 골드선물"),
    "PDBC": ("271060", "KODEX WTI원유선물"), "DBC": ("271060", "KODEX WTI원유선물"),
}


def resolve(ticker: str, market: str) -> tuple[str, str]:
    """전략의 US 티커 → (조회 티커, 표시명). market='kr'이면 국내 ETF로 치환."""
    if market == "kr":
        code, name = US_TO_KR.get(ticker, (ticker, US_UNIVERSE.get(ticker, ticker)))
        return code, name
    return ticker, US_UNIVERSE.get(ticker, ticker)


_CACHE: dict[tuple[str, str], list[float]] = {}


def _daily_df(ticker: str):
    from src.data.ohlcv_loader import load_ohlcv_unified
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=_HISTORY_DAYS)).strftime("%Y-%m-%d")
    return load_ohlcv_unified(ticker, start, end, prefer="auto")


def monthly_closes(ticker: str, market: str = "us", n: int = 14) -> list[float]:
    """최근 n개 '월말' 종가 (모멘텀 산정용). 데이터 부족 시 가능한 만큼."""
    key = (f"m:{market}", ticker)
    if key in _CACHE:
        return _CACHE[key][-n:]
    code, _ = resolve(ticker, market)
    out: list[float] = []
    try:
        df = _daily_df(code)
        if df is not None and not df.empty:
            m = df["close"].astype(float).resample("ME").last().dropna()
            out = [float(x) for x in m.tolist()]
    except Exception as e:
        logger.debug(f"monthly_closes 실패 [{ticker}/{market}]: {e}")
    _CACHE[key] = out
    return out[-n:]


def daily_closes(ticker: str, market: str = "us", days: int = 300) -> list[float]:
    """최근 일간 종가 (이동평균 산정용)."""
    key = (f"d:{market}", ticker)
    if key in _CACHE:
        return _CACHE[key][-days:]
    code, _ = resolve(ticker, market)
    out: list[float] = []
    try:
        df = _daily_df(code)
        if df is not None and not df.empty:
            out = [float(x) for x in df["close"].astype(float).tolist()]
    except Exception as e:
        logger.debug(f"daily_closes 실패 [{ticker}/{market}]: {e}")
    _CACHE[key] = out
    return out[-days:]


def cache_clear() -> None:
    _CACHE.clear()


def prewarm_etf_universe(market: str = "kr") -> dict:
    """크로스에셋 ETF 유니버스의 KR 코드를 daily_prices에 깊게 사전적재 (장기 상관/타이밍 추이용).

    US_UNIVERSE의 각 티커를 KR ETF 코드로 매핑(중복 제거) → prewarm_ohlcv로 ~5년 병렬 적재.
    mock/키 없음이면 prewarm_ohlcv가 즉시 no-op. KR ETF는 도메스틱 경로라 KIS/KRX로 적재 가능.
    """
    from src.data.ohlcv_loader import prewarm_ohlcv
    codes: list[str] = []
    seen: set[str] = set()
    for us in US_UNIVERSE:
        code, _ = resolve(us, market)
        if code and code not in seen:
            seen.add(code)
            codes.append(code)
    return prewarm_ohlcv(codes, days=_HISTORY_DAYS)
