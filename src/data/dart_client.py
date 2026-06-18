"""
DART OpenAPI Client — 재무제표 수집 파이프라인
===================================================
금융감독원 전자공시시스템(DART)에서 재무제표 및 기업 정보를 수집.

핵심 엔드포인트:
  · /company.json              — 기업 개황 (업종, 대표자, 결산월)
  · /fnlttSinglAcnt.json      — 단일회사 주요 재무제표
  · /fnlttSinglAcntAll.json   — 전체 개별 항목
  · /alotMatter.json           — 배당 정보

수집 데이터:
  · Income Statement: 매출액, 영업이익, 당기순이익
  · Balance Sheet:    자산총계, 부채총계, 자본총계, BPS
  · Cash Flow:        영업현금흐름, CapEx → FCF 계산
  · Ratios:           PER, PBR, ROE, ROA, 부채비율, 배당수익률

방어적 프로그래밍:
  · API key 없으면 Mock 데이터 자동 사용
  · Rate limit (1초 1회 — DART 한도)
  · 모든 외부 호출 try/except
  · 캐시 (동일 corp_code + year → 재호출 방지)

환경변수:
  DART_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime

try:
    import requests
except ImportError:
    requests = None

logger = logging.getLogger(__name__)

DART_BASE_URL = "https://opendart.fss.or.kr/api"

# ── 디스크 응답 캐시 (재시작에도 살아남음) ───────────────────────────────────
# 재무·기업개황은 분기 단위로만 바뀌므로 성공 응답을 디스크에 캐시한다.
# 첫 조회만 네트워크(+throttle), 이후엔 즉시 → 스크리너/분석 체감속도가 결정적으로 개선.
_DART_CACHE_DIR = os.path.join(os.path.dirname(__file__), "dart_cache")
_DART_CACHE_TTL_SEC = 7 * 24 * 3600  # 7일 (분기 공시라 충분, 주 1회 갱신)


def _dart_cache_path(key: str) -> str:
    import hashlib
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return os.path.join(_DART_CACHE_DIR, f"{h}.json")


def _dart_cache_get(key: str):
    """성공 응답 디스크 캐시 조회 (TTL 내). 실패/없음 → None."""
    try:
        path = _dart_cache_path(key)
        if not os.path.exists(path):
            return None
        if time.time() - os.path.getmtime(path) > _DART_CACHE_TTL_SEC:
            return None
        import json
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _dart_cache_set(key: str, data: dict) -> None:
    """성공 응답만 디스크에 저장 (실패는 캐시하지 않음 → 일시적 오류 고착 방지)."""
    try:
        os.makedirs(_DART_CACHE_DIR, exist_ok=True)
        import json
        tmp = _dart_cache_path(key) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, _dart_cache_path(key))  # 원자적 교체
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# Data Models
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class CorpInfo:
    """기업 기본 정보."""
    corp_code:      str                # DART 고유번호
    corp_name:      str
    stock_code:     str | None      # KRX 종목코드 (6자리)
    corp_cls:       str | None      # Y=유가, K=코스닥, N=코넥스, E=기타
    sector:         str | None      # 업종명
    ceo:            str | None
    est_dt:         str | None      # 설립일
    acc_mt:         str | None      # 결산월
    adres:          str | None
    hm_url:         str | None


@dataclass
class FinancialStatement:
    """단일 연도 재무제표."""
    corp_code:       str
    corp_name:       str
    bsns_year:       str               # 사업연도 "2024"
    reprt_code:      str               # 11011=연간, 11012=반기, 11013=1분기, 11014=3분기

    # ── Income Statement ───────────────────────────────────────────
    revenue:             float | None = None   # 매출액
    operating_profit:    float | None = None   # 영업이익
    net_income:          float | None = None   # 당기순이익
    ebitda:              float | None = None
    gross_profit:        float | None = None   # 매출총이익 (FFL: GP/A)
    cogs:                float | None = None    # 매출원가

    # ── Balance Sheet ──────────────────────────────────────────────
    total_assets:        float | None = None   # 자산총계
    total_liabilities:   float | None = None   # 부채총계
    total_equity:        float | None = None   # 자본총계
    shares_outstanding:  int | None   = None   # 발행주식수
    current_assets:      float | None = None   # 유동자산 (FFL: 유동비율)
    current_liabilities: float | None = None   # 유동부채
    inventory:           float | None = None   # 재고자산 (FFL: 당좌비율)

    # ── Cash Flow ──────────────────────────────────────────────────
    operating_cf:        float | None = None   # 영업활동 현금흐름
    capex:               float | None = None   # 자본적지출 (유형자산 취득)
    investing_cf:        float | None = None   # 투자활동 현금흐름
    financing_cf:        float | None = None   # 재무활동 현금흐름

    # ── Per Share ──────────────────────────────────────────────────
    eps:                 float | None = None   # 주당순이익
    bps:                 float | None = None   # 주당순자산
    dps:                 float | None = None   # 주당배당금

    # ── Ratios (계산) ──────────────────────────────────────────────
    roe:                 float | None = None
    roa:                 float | None = None
    debt_ratio:          float | None = None
    dividend_yield:      float | None = None
    payout_ratio:        float | None = None

    # mock 폴백으로 만들어진 값인지 (실데이터 판별용). 실 DART 파싱 시 False 유지.
    is_mock:             bool = False

    @property
    def fcf(self) -> float | None:
        """Free Cash Flow = 영업CF - CapEx."""
        if self.operating_cf is not None and self.capex is not None:
            return self.operating_cf - abs(self.capex)
        return None

    def compute_ratios(self, current_price: float | None = None):
        """핵심 비율 계산."""
        if self.total_equity and self.net_income:
            self.roe = (self.net_income / self.total_equity) * 100
        if self.total_assets and self.net_income:
            self.roa = (self.net_income / self.total_assets) * 100
        if self.total_equity and self.total_liabilities:
            self.debt_ratio = (self.total_liabilities / self.total_equity) * 100
        if self.shares_outstanding:
            if self.net_income:
                self.eps = self.net_income / self.shares_outstanding
            if self.total_equity:
                self.bps = self.total_equity / self.shares_outstanding
        if self.dps and self.eps and self.eps > 0:
            self.payout_ratio = (self.dps / self.eps) * 100
        if self.dps and current_price and current_price > 0:
            self.dividend_yield = (self.dps / current_price) * 100


# ═══════════════════════════════════════════════════════════════════════════════
# DART Client
# ═══════════════════════════════════════════════════════════════════════════════

class DARTClient:
    """
    DART OpenAPI 클라이언트.

    Usage:
        client = DARTClient()  # DART_API_KEY 환경변수에서 자동 읽기

        # 기업 개황
        info = client.get_corp_info("00126380")  # 삼성전자

        # 재무제표
        fs = client.get_financial_statement("00126380", "2024", "11011")

        # 최근 N년 재무 시계열
        history = client.get_financial_history("00126380", years=5)
    """

    def __init__(self, api_key: str | None = None, timeout: float = 10.0):
        self.api_key = api_key or os.getenv("DART_API_KEY", "")
        self.timeout = timeout
        self._cache: dict = {}
        self._last_call_time = 0.0

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key) and len(self.api_key) > 10

    # ─────────────────────────────────────────────────────────────────────
    # Rate limit
    # ─────────────────────────────────────────────────────────────────────

    def _throttle(self):
        """DART 한도: 분당 1000건(≈16/s) → 안전하게 0.25초 간격(4/s).
        디스크 캐시 히트 시엔 호출되지 않으므로, 워밍 후엔 throttle 영향 없음."""
        now = time.time()
        elapsed = now - self._last_call_time
        if elapsed < 0.25:
            time.sleep(0.25 - elapsed)
        self._last_call_time = time.time()

    def _get(self, endpoint: str, params: dict) -> dict | None:
        """공통 GET 요청. 성공 응답은 디스크 캐시(재시작에도 유지)."""
        if not self.is_configured:
            return None
        if requests is None:
            return None

        # crtfc_key를 제외한 안정적 캐시 키
        cache_key = endpoint + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        hit = _dart_cache_get(cache_key)
        if hit is not None:
            return hit

        self._throttle()
        params["crtfc_key"] = self.api_key
        url = f"{DART_BASE_URL}/{endpoint}"

        try:
            resp = requests.get(url, params=params, timeout=self.timeout)
            data = resp.json()
            if data.get("status") != "000":
                logger.warning(f"DART {endpoint}: {data.get('message', 'error')}")
                return None
            _dart_cache_set(cache_key, data)  # 성공만 캐시
            return data
        except Exception as e:
            logger.error(f"DART API 오류 ({endpoint}): {e}")
            return None

    # ─────────────────────────────────────────────────────────────────────
    # 기업 개황
    # ─────────────────────────────────────────────────────────────────────

    def get_corp_info(self, corp_code: str) -> CorpInfo | None:
        """기업 기본 정보 조회."""
        cache_key = f"corp_info_{corp_code}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        data = self._get("company.json", {"corp_code": corp_code})
        if not data:
            return self._mock_corp_info(corp_code)

        info = CorpInfo(
            corp_code=corp_code,
            corp_name=data.get("corp_name", ""),
            stock_code=data.get("stock_code"),
            corp_cls=data.get("corp_cls"),
            sector=data.get("induty_code"),
            ceo=data.get("ceo_nm"),
            est_dt=data.get("est_dt"),
            acc_mt=data.get("acc_mt"),
            adres=data.get("adres"),
            hm_url=data.get("hm_url"),
        )
        self._cache[cache_key] = info
        return info

    # ─────────────────────────────────────────────────────────────────────
    # 재무제표
    # ─────────────────────────────────────────────────────────────────────

    def get_financial_statement(
        self, corp_code: str, bsns_year: str, reprt_code: str = "11011",
    ) -> FinancialStatement | None:
        """단일 연도 주요 재무제표."""
        cache_key = f"fs_{corp_code}_{bsns_year}_{reprt_code}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        data = self._get("fnlttSinglAcnt.json", {
            "corp_code": corp_code,
            "bsns_year": bsns_year,
            "reprt_code": reprt_code,
            "fs_div": "CFS",  # 연결재무제표
        })

        if not data or "list" not in data:
            return self._mock_financial_statement(corp_code, bsns_year)

        fs = FinancialStatement(
            corp_code=corp_code,
            corp_name=data["list"][0].get("corp_name", "") if data["list"] else "",
            bsns_year=bsns_year,
            reprt_code=reprt_code,
        )

        # DART 항목 코드 → 필드 매핑
        for item in data["list"]:
            account = item.get("account_nm", "")
            value = self._parse_amount(item.get("thstrm_amount"))

            if "매출" in account and "원가" not in account:
                fs.revenue = value
            elif "영업이익" in account or "영업손익" in account:
                fs.operating_profit = value
            elif "당기순이익" in account or "당기순손익" in account:
                fs.net_income = value
            elif "자산총계" in account:
                fs.total_assets = value
            elif "부채총계" in account:
                fs.total_liabilities = value
            elif "자본총계" in account:
                fs.total_equity = value

        fs.compute_ratios()
        self._cache[cache_key] = fs
        return fs

    def get_financial_statement_full(
        self, corp_code: str, bsns_year: str, reprt_code: str = "11011",
    ) -> FinancialStatement | None:
        """
        전체 재무항목 조회 (fnlttSinglAcntAll) — FFL 펀더멘털 팩터용.
        매출총이익·유동자산·유동부채·재고·현금흐름 등 세부 항목 포함.
        실패 시 주요항목(get_financial_statement)으로 fallback.
        """
        cache_key = f"fsall_{corp_code}_{bsns_year}_{reprt_code}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        data = self._get("fnlttSinglAcntAll.json", {
            "corp_code": corp_code,
            "bsns_year": bsns_year,
            "reprt_code": reprt_code,
            "fs_div": "CFS",  # 연결재무제표
        })
        if not data or "list" not in data:
            # fallback: 주요항목만
            return self.get_financial_statement(corp_code, bsns_year, reprt_code)

        fs = FinancialStatement(
            corp_code=corp_code,
            corp_name=data["list"][0].get("corp_name", "") if data["list"] else "",
            bsns_year=bsns_year, reprt_code=reprt_code,
        )

        for item in data["list"]:
            account = item.get("account_nm", "")
            sj = item.get("sj_div", "")  # BS=재무상태표, IS=손익, CIS=포괄손익, CF=현금흐름
            value = self._parse_amount(item.get("thstrm_amount"))
            if value is None:
                continue

            # 손익계산서
            if sj in ("IS", "CIS"):
                if account == "매출액" or (("매출" in account) and ("총" not in account) and ("원가" not in account) and ("이익" not in account)):
                    if fs.revenue is None: fs.revenue = value
                elif "매출원가" in account:
                    fs.cogs = value
                elif "매출총이익" in account:
                    fs.gross_profit = value
                elif "영업이익" in account or "영업손익" in account:
                    fs.operating_profit = value
                elif ("당기순이익" in account or "당기순손익" in account) and "지배" not in account:
                    if fs.net_income is None: fs.net_income = value
            # 재무상태표
            elif sj == "BS":
                if "자산총계" in account:
                    fs.total_assets = value
                elif "부채총계" in account:
                    fs.total_liabilities = value
                elif "자본총계" in account:
                    fs.total_equity = value
                elif "유동자산" in account and "비유동" not in account:
                    fs.current_assets = value
                elif "유동부채" in account and "비유동" not in account:
                    fs.current_liabilities = value
                elif "재고자산" in account:
                    fs.inventory = value
            # 현금흐름표
            elif sj == "CF":
                if "영업활동" in account and "현금흐름" in account:
                    fs.operating_cf = value
                elif "투자활동" in account and "현금흐름" in account:
                    fs.investing_cf = value
                elif "재무활동" in account and "현금흐름" in account:
                    fs.financing_cf = value

        # 매출총이익 미제공 시 매출-원가로 계산
        if fs.gross_profit is None and fs.revenue is not None and fs.cogs is not None:
            fs.gross_profit = fs.revenue - fs.cogs

        fs.compute_ratios()
        self._cache[cache_key] = fs
        return fs

    def get_financial_history(
        self, corp_code: str, years: int = 5,
        current_year: int | None = None,
    ) -> list[FinancialStatement]:
        """최근 N년 재무 시계열."""
        if current_year is None:
            current_year = datetime.now().year - 1  # 직전 결산연도

        history = []
        for y in range(current_year, current_year - years, -1):
            fs = self.get_financial_statement(corp_code, str(y))
            if fs:
                history.append(fs)

        return history

    # ─────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_amount(value) -> float | None:
        """DART 금액 문자열 → float (억 단위 아닌 원 단위)."""
        if value is None or value == "":
            return None
        try:
            return float(str(value).replace(",", "").replace(" ", ""))
        except (ValueError, TypeError):
            return None

    # ─────────────────────────────────────────────────────────────────────
    # Mock (DART_API_KEY 미설정 시)
    # ─────────────────────────────────────────────────────────────────────

    @staticmethod
    def _mock_corp_info(corp_code: str) -> CorpInfo:
        MOCK_CORPS = {
            "00126380": ("삼성전자", "005930", "Y", "반도체"),
            "00164779": ("SK하이닉스", "000660", "Y", "반도체"),
            "00356361": ("NAVER", "035420", "Y", "인터넷"),
            "00401731": ("카카오", "035720", "Y", "인터넷"),
            "00258801": ("LG에너지솔루션", "373220", "Y", "배터리"),
        }
        name, stock, cls, sector = MOCK_CORPS.get(
            corp_code, ("Unknown Corp", "000000", "Y", "기타")
        )
        return CorpInfo(
            corp_code=corp_code, corp_name=name, stock_code=stock,
            corp_cls=cls, sector=sector, ceo="대표이사",
            est_dt="19690101", acc_mt="12", adres="서울", hm_url="",
        )

    @staticmethod
    def _mock_financial_statement(corp_code: str, year: str) -> FinancialStatement:
        """주요 기업의 근사 재무 데이터 (교육/개발용)."""
        # 삼성전자 2024 근사치 (단위: 원)
        MOCK_DATA = {
            "00126380": {  # 삼성전자
                "revenue": 300_000_000_000_000,
                "operating_profit": 35_000_000_000_000,
                "net_income": 28_000_000_000_000,
                "total_assets": 450_000_000_000_000,
                "total_liabilities": 100_000_000_000_000,
                "total_equity": 350_000_000_000_000,
                "operating_cf": 60_000_000_000_000,
                "capex": 45_000_000_000_000,
                "shares_outstanding": 5_969_782_550,
                "dps": 1444,
            },
            "00164779": {  # SK하이닉스
                "revenue": 66_000_000_000_000,
                "operating_profit": 23_000_000_000_000,
                "net_income": 19_000_000_000_000,
                "total_assets": 100_000_000_000_000,
                "total_liabilities": 50_000_000_000_000,
                "total_equity": 50_000_000_000_000,
                "operating_cf": 30_000_000_000_000,
                "capex": 20_000_000_000_000,
                "shares_outstanding": 728_002_365,
                "dps": 1200,
            },
        }

        base = MOCK_DATA.get(corp_code, {
            "revenue": 10_000_000_000_000,
            "operating_profit": 1_000_000_000_000,
            "net_income": 800_000_000_000,
            "total_assets": 20_000_000_000_000,
            "total_liabilities": 8_000_000_000_000,
            "total_equity": 12_000_000_000_000,
            "operating_cf": 1_500_000_000_000,
            "capex": 500_000_000_000,
            "shares_outstanding": 100_000_000,
            "dps": 500,
        })

        # 연도별 약간의 변동 (성장률 시뮬레이션)
        year_int = int(year)
        growth = 1.0 + (year_int - 2024) * 0.05

        fs = FinancialStatement(
            corp_code=corp_code,
            corp_name=DARTClient._mock_corp_info(corp_code).corp_name,
            bsns_year=year,
            reprt_code="11011",
            revenue=base["revenue"] * growth,
            operating_profit=base["operating_profit"] * growth,
            net_income=base["net_income"] * growth,
            total_assets=base["total_assets"] * (1 + (year_int - 2024) * 0.03),
            total_liabilities=base["total_liabilities"] * (1 + (year_int - 2024) * 0.02),
            total_equity=base["total_equity"] * (1 + (year_int - 2024) * 0.04),
            operating_cf=base["operating_cf"] * growth,
            capex=base["capex"] * growth,
            shares_outstanding=base["shares_outstanding"],
            dps=base["dps"],
            is_mock=True,
        )
        fs.compute_ratios()
        return fs


# ═══════════════════════════════════════════════════════════════════════════════
# Convenience: Stock Code → Corp Code 매핑
# ═══════════════════════════════════════════════════════════════════════════════

STOCK_TO_CORP: dict[str, str] = {
    "005930": "00126380",  # 삼성전자
    "000660": "00164779",  # SK하이닉스
    "035420": "00356361",  # NAVER
    "035720": "00401731",  # 카카오
    "373220": "00258801",  # LG에너지솔루션
    "051910": "00159263",  # LG화학
    "006400": "00155334",  # 삼성SDI
    "003670": "00124618",  # 포스코퓨처엠
    "105560": "00527050",  # KB금융
    "055550": "00382199",  # 신한지주
}


_SHARED_DART_CLIENT: DARTClient | None = None


def get_dart_client() -> DARTClient:
    """프로세스 공용 DARTClient (인메모리 캐시를 종목·요청 간 공유).
    종목마다 새 DARTClient()를 만들면 캐시가 매번 버려져 느려진다 → 단일 인스턴스 재사용."""
    global _SHARED_DART_CLIENT
    if _SHARED_DART_CLIENT is None:
        _SHARED_DART_CLIENT = DARTClient()
    return _SHARED_DART_CLIENT


def get_corp_code(stock_code: str) -> str | None:
    """종목코드(6자리) → DART corp_code 변환.

    1) 하드코딩 매핑(STOCK_TO_CORP) 우선
    2) 없으면 DART corpCode.xml 자동 다운로드 캐시에서 조회
       (DART_API_KEY 설정 시, 최초 1회 다운로드 후 디스크 캐시)
    """
    if stock_code in STOCK_TO_CORP:
        return STOCK_TO_CORP[stock_code]
    # 전체 매핑 (corpCode.xml) 시도
    full = _load_full_corp_map()
    return full.get(stock_code)


_FULL_CORP_MAP: dict | None = None

def _load_full_corp_map() -> dict:
    """
    DART corpCode.xml 다운로드 → {종목코드: 고유번호} 매핑.
    디스크 캐시(corp_code_cache.json)에 저장하여 재다운로드 방지.
    키 없거나 실패 시 빈 dict (하드코딩 매핑만 사용).
    """
    global _FULL_CORP_MAP
    if _FULL_CORP_MAP is not None:
        return _FULL_CORP_MAP

    import json
    import os
    cache_path = os.path.join(os.path.dirname(__file__), "corp_code_cache.json")

    # 디스크 캐시
    if os.path.exists(cache_path):
        try:
            with open(cache_path) as f:
                _FULL_CORP_MAP = json.load(f)
                logger.info(f"DART corp_code 캐시 로드: {len(_FULL_CORP_MAP)}개")
                return _FULL_CORP_MAP
        except Exception:
            pass

    api_key = os.getenv("DART_API_KEY", "")
    if not api_key or requests is None:
        _FULL_CORP_MAP = {}
        return _FULL_CORP_MAP

    # corpCode.xml 다운로드 (ZIP)
    try:
        import io
        import xml.etree.ElementTree as ET
        import zipfile
        url = f"{DART_BASE_URL}/corpCode.xml"
        resp = requests.get(url, params={"crtfc_key": api_key}, timeout=30)
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        xml_data = zf.read(zf.namelist()[0])
        root = ET.fromstring(xml_data)

        mapping = {}
        for corp in root.iter("list"):
            stock = (corp.findtext("stock_code") or "").strip()
            corp_code = (corp.findtext("corp_code") or "").strip()
            if stock and len(stock) == 6 and corp_code:
                mapping[stock] = corp_code

        _FULL_CORP_MAP = mapping
        logger.info(f"DART corpCode.xml 다운로드: {len(mapping)}개 상장사")
        try:
            with open(cache_path, "w") as f:
                json.dump(mapping, f)
        except Exception:
            pass
        return _FULL_CORP_MAP
    except Exception as e:
        logger.warning(f"corpCode.xml 다운로드 실패: {e}")
        _FULL_CORP_MAP = {}
        return _FULL_CORP_MAP
