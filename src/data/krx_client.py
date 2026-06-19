"""KRX 정보데이터시스템 OpenAPI 클라이언트 (data-dbg.krx.co.kr)
==========================================================================
공식 키 기반 OpenAPI — KIS와 반대로 **날짜 기준**: basDd 1콜 = 그날 전종목.
  · 유가 일별매매정보  /svc/apis/sto/stk_bydd_trd
  · 코스닥 일별매매정보 /svc/apis/sto/ksq_bydd_trd
  · 지수 일별시세      /svc/apis/idx/kospi_dd_trd · kosdaq_dd_trd

용도: 장기 백테스트용 역사 적재(krx_ingest가 daily_prices를 채움) + 시점 유니버스.
KRX_API_KEY 미설정이면 is_configured=False — 호출부가 건너뜀 (기존 DART 패턴, 동작 불변).

주의: 응답 필드명·엔드포인트는 공식 문서 기준으로 전사 — 실계정 첫 호출에서
verify_connection 【5】 sanity(행 수·삼성전자 종가)로 정합을 확정한다.
시세는 원주가(수정주가 아님) — 수정종가는 등락률(FLUC_RT) 체인으로 krx_ingest가 재구성.
"""

from __future__ import annotations

import logging
import os
import time

logger = logging.getLogger(__name__)

KRX_BASE_URL = "https://data-dbg.krx.co.kr/svc/apis"  # https (http는 302 리다이렉트)

# 시장 → 전종목 일별매매정보 엔드포인트
STOCK_ENDPOINTS = {
    "KOSPI": "/sto/stk_bydd_trd",
    "KOSDAQ": "/sto/ksq_bydd_trd",
}
# 시장 → 지수 일별시세 엔드포인트 + 대표 지수명
INDEX_ENDPOINTS = {
    "KOSPI": ("/idx/kospi_dd_trd", "코스피"),
    "KOSDAQ": ("/idx/kosdaq_dd_trd", "코스닥"),
}

_MIN_INTERVAL_SEC = 0.6  # ~1.7 TPS — 쿼터 보호 (10년 백필 ≈ 5,000콜 ≈ 50분)


def _num(s) -> float | None:
    """KRX 숫자 문자열 → float. 쉼표 제거, ''/'-'/None → None."""
    if s is None:
        return None
    t = str(s).replace(",", "").strip()
    if t in ("", "-"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _norm_ticker(isu_cd: str | None) -> str | None:
    """ISU_CD → 6자리 단축코드. 12자리 표준코드(KR7xxxxxx00n)는 [3:9] 추출."""
    code = (isu_cd or "").strip()
    if len(code) == 12 and code[:3].isalnum() and code[3:9].isdigit():
        return code[3:9]
    if len(code) == 6 and code.isdigit():
        return code
    return None


def _norm_date(d: str) -> str:
    """YYYY-MM-DD | YYYYMMDD → YYYYMMDD (basDd 파라미터)."""
    return d.replace("-", "").strip()


def parse_stock_rows(rows: list[dict], market: str) -> list[dict]:
    """일별매매정보 OutBlock_1 → 정규화 행 리스트.

    반환 키: ticker, name, date(YYYY-MM-DD), open/high/low/close, volume,
            trading_value, mktcap, shares, fluc_rt(등락률 % — 수정종가 체인용)."""
    out: list[dict] = []
    for r in rows or []:
        ticker = _norm_ticker(r.get("ISU_CD"))
        close = _num(r.get("TDD_CLSPRC"))
        bas = str(r.get("BAS_DD") or "").strip()
        if not ticker or close is None or close <= 0 or len(bas) != 8:
            continue  # 거래정지 등으로 가격 없는 행·이상 행은 건너뜀
        out.append({
            "ticker": ticker,
            "name": str(r.get("ISU_NM") or "").strip(),
            "market": market,
            "date": f"{bas[:4]}-{bas[4:6]}-{bas[6:]}",
            "open": _num(r.get("TDD_OPNPRC")) or close,
            "high": _num(r.get("TDD_HGPRC")) or close,
            "low": _num(r.get("TDD_LWPRC")) or close,
            "close": close,
            "volume": _num(r.get("ACC_TRDVOL")) or 0.0,
            "trading_value": _num(r.get("ACC_TRDVAL")) or 0.0,
            "mktcap": _num(r.get("MKTCAP")),
            "shares": _num(r.get("LIST_SHRS")),
            "fluc_rt": _num(r.get("FLUC_RT")),
        })
    return out


def parse_index_row(rows: list[dict], index_name: str) -> dict | None:
    """지수 일별시세 OutBlock_1에서 대표 지수(코스피/코스닥) 행 추출 → OHLC dict."""
    for r in rows or []:
        if str(r.get("IDX_NM") or "").strip() != index_name:
            continue
        close = _num(r.get("CLSPRC_IDX"))
        bas = str(r.get("BAS_DD") or "").strip()
        if close is None or close <= 0 or len(bas) != 8:
            return None
        return {
            "date": f"{bas[:4]}-{bas[4:6]}-{bas[6:]}",
            "open": _num(r.get("OPNPRC_IDX")) or close,
            "high": _num(r.get("HGPRC_IDX")) or close,
            "low": _num(r.get("LWPRC_IDX")) or close,
            "close": close,
            "volume": _num(r.get("ACC_TRDVOL")) or 0.0,
            "fluc_rt": _num(r.get("FLUC_RT")),
        }
    return None


class KRXClient:
    """KRX OpenAPI — AUTH_KEY 헤더 + basDd 파라미터. 키 없으면 비활성."""

    def __init__(self, api_key: str | None = None, timeout: float = 15.0):
        self.api_key = api_key if api_key is not None else os.getenv("KRX_API_KEY", "")
        self.timeout = timeout
        self._last_call = 0.0

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _throttle(self) -> None:
        wait = _MIN_INTERVAL_SEC - (time.time() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.time()

    def _get(self, path: str, bas_dd: str) -> list[dict]:
        """공통 GET → OutBlock_1 리스트. 미설정·실패 시 빈 리스트 (호출부 폴백)."""
        if not self.is_configured:
            return []
        import httpx
        self._throttle()
        try:
            r = httpx.get(
                f"{KRX_BASE_URL}{path}",
                params={"basDd": bas_dd},
                headers={"AUTH_KEY": self.api_key},
                timeout=self.timeout,
                follow_redirects=True,  # http→https 302 추적 (이중 안전)
            )
            r.raise_for_status()
            return r.json().get("OutBlock_1") or []
        except Exception as e:
            logger.warning(f"KRX 호출 실패 {path}?basDd={bas_dd}: {type(e).__name__}: {e}")
            return []

    def get_daily_all(self, market: str, date: str) -> list[dict]:
        """해당일 전종목 일별시세 (정규화). 휴장·실패 시 빈 리스트."""
        path = STOCK_ENDPOINTS.get(market)
        if not path:
            return []
        return parse_stock_rows(self._get(path, _norm_date(date)), market)

    def get_index_daily(self, market: str, date: str) -> dict | None:
        """해당일 대표 지수(코스피/코스닥) OHLC. 휴장·실패 시 None."""
        ep = INDEX_ENDPOINTS.get(market)
        if not ep:
            return None
        path, index_name = ep
        return parse_index_row(self._get(path, _norm_date(date)), index_name)
