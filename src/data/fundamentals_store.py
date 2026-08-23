"""
Fundamentals Store — Screener V3 Fundamental Factor Library (FFL)
==========================================================================
DART 원천 재무 데이터에서 학술 논문·퀀트 플랫폼 수준의 50+ 펀더멘털 팩터 도출.

★ 설계 철학 ★
  · DeterministicMockStore 상속 — 종목별 일관된 mock 재무
  · 실제로는 DART 원천(매출·영업이익·자산·부채·현금흐름)에서 계산
  · 모든 팩터는 `field` kind로 통합 → 기존 아키텍처 무변경
  · _maybe_missing으로 결측 시뮬 (실데이터 정합성)

★ 팩터 카테고리 ★
  Phase A 수익성·효율성 : 마진, GP/A(Novy-Marx), ROIC, 듀폰
  Phase B 밸류에이션    : EV/EBITDA, PEG, FCF Yield, Acquirer's Multiple, Shareholder Yield
  Phase C 성장성        : 매출/이익/EPS 성장률 (YoY, CAGR)
  Phase D 안정성·건전성 : Altman Z, Beneish M, 유동비율, Accruals(Sloan)
  Phase E 종합          : F-Score(Piotroski), QMJ(Asness), Magic Formula
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.data.mock_base import DeterministicMockStore

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# 팩터 메타 (카탈로그)
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class FactorMeta:
    id: str
    label: str
    category: str       # quality | valuation | growth | safety | composite
    unit: str
    higher_better: bool
    typical_min: float
    typical_max: float
    source: str         # 논문/출처
    description: str


FUNDAMENTAL_FACTORS: list[FactorMeta] = [
    # ─── Phase A: 수익성·효율성 (Quality) ───
    FactorMeta("operating_margin", "영업이익률", "quality", "%", True, -10, 35, "기본", "영업이익 / 매출액"),
    FactorMeta("net_margin", "순이익률", "quality", "%", True, -10, 30, "기본", "당기순이익 / 매출액"),
    FactorMeta("gross_margin", "매출총이익률", "quality", "%", True, 0, 70, "기본", "매출총이익 / 매출액"),
    FactorMeta("gp_to_assets", "GP/A", "quality", "", True, 0, 1.2, "Novy-Marx (2013)", "매출총이익 / 총자산 — 가장 강력한 퀄리티 팩터"),
    FactorMeta("roic", "ROIC", "quality", "%", True, -10, 40, "기관 표준", "투하자본이익률 = NOPAT / 투하자본"),
    FactorMeta("asset_turnover", "자산회전율", "quality", "회", True, 0, 3, "DuPont", "매출액 / 총자산 — 자산 효율성"),
    FactorMeta("equity_multiplier", "재무레버리지", "quality", "배", False, 1, 5, "DuPont", "총자산 / 자기자본 — 듀폰 레버리지 항"),
    FactorMeta("fcf_margin", "FCF 마진", "quality", "%", True, -10, 30, "기관 표준", "잉여현금흐름 / 매출액"),

    # ─── Phase B: 밸류에이션 (Valuation) ───
    FactorMeta("ev_ebitda", "EV/EBITDA", "valuation", "배", False, 0, 30, "기관 표준", "기업가치 / EBITDA — 자본구조 중립 밸류"),
    FactorMeta("ev_sales", "EV/Sales", "valuation", "배", False, 0, 10, "기관 표준", "기업가치 / 매출액"),
    FactorMeta("ev_fcf", "EV/FCF", "valuation", "배", False, 0, 50, "기관 표준", "기업가치 / 잉여현금흐름"),
    FactorMeta("psr", "PSR", "valuation", "배", False, 0, 10, "기본", "주가매출비율 = 시총 / 매출액"),
    FactorMeta("pcr", "PCR", "valuation", "배", False, 0, 30, "기본", "주가현금흐름비율 = 시총 / 영업현금흐름"),
    FactorMeta("peg", "PEG", "valuation", "배", False, 0, 5, "Lynch", "PER / EPS성장률 — 성장 대비 밸류"),
    FactorMeta("fcf_yield", "FCF 수익률", "valuation", "%", True, -5, 20, "기관 표준", "잉여현금흐름 / 시총 — 높을수록 저평가"),
    FactorMeta("earnings_yield", "이익수익률", "valuation", "%", True, -5, 25, "기본", "1 / PER — Magic Formula 구성"),
    FactorMeta("acquirers_multiple", "Acquirer's Multiple", "valuation", "배", False, 0, 30, "Carlisle (2014)", "EV / EBIT — 인수자 관점 밸류"),
    FactorMeta("shareholder_yield", "주주환원수익률", "valuation", "%", True, -5, 15, "Faber (2013)", "(배당+자사주매입) / 시총"),

    # ─── Phase C: 성장성 (Growth) ───
    FactorMeta("revenue_growth_yoy", "매출성장률(YoY)", "growth", "%", True, -30, 50, "기본", "전년 대비 매출 증가율"),
    FactorMeta("op_growth_yoy", "영업이익성장률(YoY)", "growth", "%", True, -50, 80, "기본", "전년 대비 영업이익 증가율"),
    FactorMeta("eps_growth_yoy", "EPS성장률(YoY)", "growth", "%", True, -50, 80, "기본", "전년 대비 주당순이익 증가율"),
    FactorMeta("revenue_cagr_3y", "매출 CAGR(3년)", "growth", "%", True, -20, 40, "기본", "3년 매출 연평균 성장률"),
    FactorMeta("eps_cagr_3y", "EPS CAGR(3년)", "growth", "%", True, -20, 50, "기본", "3년 EPS 연평균 성장률"),
    FactorMeta("price_momentum_12_1", "12-1 모멘텀", "growth", "%", True, -40, 60, "Jegadeesh-Titman (1993)", "최근 12개월 수익률(직전 1개월 제외)"),
    FactorMeta("pead_score", "PEAD 점수", "growth", "", True, -3, 3, "Bernard-Thomas (1989)", "실적 서프라이즈 후 표류 신호"),

    # ─── Phase D: 안정성·건전성 (Safety) ───
    FactorMeta("altman_z", "Altman Z-Score", "safety", "", True, 0, 8, "Altman (1968)", "부도예측 — 3.0↑ 안전, 1.8↓ 위험"),
    FactorMeta("beneish_m", "Beneish M-Score", "safety", "", False, -4, 0, "Beneish (1999)", "분식회계 탐지 — -1.78↑ 조작 의심"),
    FactorMeta("current_ratio", "유동비율", "safety", "%", True, 0, 400, "기본", "유동자산 / 유동부채"),
    FactorMeta("quick_ratio", "당좌비율", "safety", "%", True, 0, 300, "기본", "(유동자산-재고) / 유동부채"),
    FactorMeta("interest_coverage", "이자보상배율", "safety", "배", True, -5, 30, "기본", "영업이익 / 이자비용"),
    FactorMeta("accruals", "발생액 비율", "safety", "%", False, -20, 20, "Sloan (1996)", "(순이익-영업CF)/자산 — 낮을수록 이익의 질↑"),
    FactorMeta("debt_to_equity", "부채자본비율", "safety", "배", False, 0, 3, "기본", "총부채 / 자기자본"),

    # ─── Phase E: 종합 멀티팩터 (Composite) ───
    FactorMeta("piotroski_f", "F-Score", "composite", "점", True, 0, 9, "Piotroski (2000)", "재무건전성 9점 — 7↑ 우량"),
    FactorMeta("qmj_score", "QMJ 점수", "composite", "점", True, 0, 100, "Asness (2019, AQR)", "Quality Minus Junk — 수익성+성장+안전+배당"),
    FactorMeta("magic_formula_rank", "Magic Formula 순위", "composite", "위", False, 1, 200, "Greenblatt", "이익수익률+ROIC 결합 순위 (낮을수록 우수)"),

    # ═══ 확장 팩터 (DART 원천 파생, 추가 API 불필요) ═══
    # 수익성 심화
    FactorMeta("roe", "ROE", "quality", "%", True, -10, 40, "기본", "자기자본이익률 = 순이익 / 자기자본"),
    FactorMeta("roa", "ROA", "quality", "%", True, -5, 25, "기본", "총자산이익률 = 순이익 / 총자산"),
    FactorMeta("roe_dupont", "ROE(듀폰)", "quality", "%", True, -10, 40, "DuPont", "순이익률×자산회전율×레버리지 분해"),
    FactorMeta("ebitda_margin", "EBITDA 마진", "quality", "%", True, -5, 45, "기관 표준", "(영업이익+감가상각) / 매출액"),
    FactorMeta("ocf_to_ni", "이익의 질", "quality", "배", True, 0, 3, "Sloan", "영업현금흐름 / 순이익 — 1↑ 양호"),
    FactorMeta("cash_conversion", "현금전환율", "quality", "배", True, 0, 2, "기관 표준", "잉여현금흐름 / 순이익"),
    FactorMeta("rnd_intensity", "R&D 집약도", "quality", "%", True, 0, 15, "기본", "연구개발비 / 매출액"),
    FactorMeta("sga_to_revenue", "판관비율", "quality", "%", False, 0, 35, "기본", "판매관리비 / 매출액 — 낮을수록 효율적"),
    FactorMeta("capex_intensity", "설비투자 집약도", "quality", "%", False, 0, 20, "기본", "CAPEX / 매출액"),
    # 밸류에이션 심화
    FactorMeta("per", "PER", "valuation", "배", False, 0, 50, "기본", "주가수익비율 = 시총 / 순이익"),
    FactorMeta("pbr", "PBR", "valuation", "배", False, 0, 10, "기본", "주가순자산비율 = 시총 / 자기자본"),
    FactorMeta("ev_ic", "EV/투하자본", "valuation", "배", False, 0, 20, "기관 표준", "기업가치 / 투하자본"),
    FactorMeta("dividend_yield", "배당수익률", "valuation", "%", True, 0, 12, "기본", "배당금 / 시총"),
    FactorMeta("payout_ratio", "배당성향", "valuation", "%", True, 0, 100, "기본", "배당금 / 순이익"),
    FactorMeta("bps", "BPS", "valuation", "원", True, 0, 500000, "기본", "주당순자산 = 자기자본 / 발행주식수"),
    FactorMeta("book_to_market", "장부/시장", "valuation", "배", True, 0, 3, "Fama-French (1992)", "자기자본 / 시총 — 가치주 지표"),
    FactorMeta("ncav_to_mcap", "NCAV/시총", "valuation", "배", True, -1, 2, "Graham", "순유동자산 / 시총 — 그레이엄 청산가치"),
    # 성장성 심화
    FactorMeta("revenue_qoq", "매출성장률(QoQ)", "growth", "%", True, -30, 40, "기본", "전분기 대비 매출 성장"),
    FactorMeta("growth_acceleration", "성장 가속도", "growth", "%p", True, -30, 30, "기관 표준", "당기 성장률 - 전기 성장률"),
    FactorMeta("sustainable_growth", "지속가능성장률", "growth", "%", True, -10, 35, "Higgins", "ROE × 유보율 — 자체 조달 성장 한계"),
    FactorMeta("fcf_growth", "FCF 성장률", "growth", "%", True, -40, 60, "기관 표준", "잉여현금흐름 전년 대비 성장"),
    # 안전성 심화
    FactorMeta("net_debt_to_ebitda", "순부채/EBITDA", "safety", "배", False, -2, 8, "기관 표준", "(총부채-현금) / EBITDA — 부채상환능력"),
    FactorMeta("cash_ratio", "현금비율", "safety", "%", True, 0, 150, "기본", "현금 / 유동부채"),
    FactorMeta("equity_ratio", "자기자본비율", "safety", "%", True, 0, 90, "기본", "자기자본 / 총자산"),
    FactorMeta("sloan_accruals", "Sloan 발생액", "safety", "%", False, -20, 20, "Sloan (1996)", "운전자본변화-감가상각 / 총자산 — 낮을수록 양질"),
    FactorMeta("debt_to_assets", "부채/자산", "safety", "배", False, 0, 1, "기본", "총부채 / 총자산"),
    # 종합 심화
    FactorMeta("graham_number", "그레이엄 넘버", "composite", "원", True, 0, 500000, "Graham", "√(22.5×EPS×BPS) — 적정주가 상한"),
    FactorMeta("greenblatt_score", "Greenblatt 점수", "composite", "점", True, 0, 100, "Greenblatt", "이익수익률+ROIC 결합 (높을수록 우수)"),
    FactorMeta("value_composite", "가치 종합점수", "composite", "점", True, 0, 100, "기관 표준", "장부/시장+이익수익률+FCF수익률 결합"),
]

FACTOR_BY_ID = {f.id: f for f in FUNDAMENTAL_FACTORS}

FACTOR_CATEGORY_LABELS = {
    "quality": "수익성·퀄리티",
    "valuation": "밸류에이션(고급)",
    "growth": "성장성·모멘텀",
    "safety": "안정성·건전성",
    "composite": "종합 팩터",
}


# ═══════════════════════════════════════════════════════════════════════════════
# Fundamentals Store
# ═══════════════════════════════════════════════════════════════════════════════

def _real_dividend(dart, corp_code: str, year, net_income: float | None) -> float:
    """실 alotMatter 현금배당성향 기반 배당(억). 미공시 → 0(무배당, 0.25×NI 날조 금지)."""
    try:
        div = dart.get_dividend_info(corp_code, str(year))
    except Exception:
        div = {}
    payout = div.get("payout_pct")
    if payout is not None and net_income and net_income > 0:
        return payout / 100 * net_income
    return 0.0


class FundamentalsStore(DeterministicMockStore):
    """DART 원천 → 50+ 학술 팩터 도출 (Mock + 실데이터 연결 여지)."""

    PERSIST = True  # 계산된 팩터를 DB(factor_snapshot)에 영속 → 재시작·벌크 읽기

    _singleton: FundamentalsStore | None = None

    @classmethod
    def get_default(cls) -> FundamentalsStore:
        if cls._singleton is None:
            cls._singleton = cls()
        return cls._singleton

    def get_factors(self, stock_code: str, item=None) -> dict:
        """단일 종목의 모든 펀더멘털 팩터 (캐시 + 결정론적)."""
        return self.cached(
            f"ffl:{stock_code}",
            lambda: self._build_factors(stock_code, item),
        )

    def get_raw_financials(self, stock_code: str, item=None) -> dict:
        """원천 재무 항목(42키, 단위: 억 / EPS류는 원) — 조건식 raw 금액 토큰용 공개 API.

        get_factors와 동일 정책: DART 키 설정 시 실데이터, 아니면 결정론적 mock."""
        return self.cached(
            f"ffl_raw:{stock_code}",
            lambda: (self._real_raw_financials(stock_code, item)
                     or self._mock_raw_financials(stock_code, item)),
        )

    def _build_factors(self, stock_code: str, item=None) -> dict:
        """
        DART 실데이터 우선 → 실패 시: mock 모드만 합성, 운영선 빈 팩터(정직 "—").
        DART_API_KEY 설정 시 실제 재무제표로 학술 팩터 계산.
        """
        raw = self._real_raw_financials(stock_code, item)
        if raw is None:
            from src.data.mock_gate import mock_allowed
            if not mock_allowed():
                return {}  # 운영 — DART 실패 시 합성 금지(지표 "—")
            raw = self._mock_raw_financials(stock_code, item)
        return self._derive_factors(stock_code, raw)

    @staticmethod
    def _fs_from_history(stock_code: str, year: int):
        """financials_history(백필된 재무시계열, 원 단위)를 FinancialStatement로 매핑.

        재무시계열 적재분을 스크리너 펀더멘털 원천으로 재사용 → DART 쿼터 무소모로
        전종목 팩터 확보. 핵심값(매출·자산) 없으면 None(상장 전 연도 등)."""
        try:
            from src.data.dart_client import FinancialStatement
            from src.data.dart_history import history_snapshot
            snap = history_snapshot(str(stock_code), str(year), "11011")
        except Exception:
            return None
        if not snap or (snap.get("revenue") is None and snap.get("total_assets") is None):
            return None
        fs = FinancialStatement(corp_code="", corp_name="", bsns_year=str(year), reprt_code="11011")
        for f in ("revenue", "operating_profit", "net_income", "gross_profit",
                  "total_assets", "total_liabilities", "total_equity",
                  "current_assets", "current_liabilities", "operating_cf",
                  "shares_outstanding", "dps"):
            v = snap.get(f)
            if v is not None:
                setattr(fs, f, v)
        # 회계 항등식으로 결측 보완(정확 — 날조 아님): 자본총계=자산총계-부채총계.
        # DART 일부 공시가 자본총계 라인을 누락(자산·부채만) → 자본 결측만으로 팩터 전체가
        # 탈락하던 것을 방지. 역방향(부채=자산-자본)도 동일.
        if fs.total_equity is None and fs.total_assets is not None and fs.total_liabilities is not None:
            fs.total_equity = fs.total_assets - fs.total_liabilities
        if fs.total_liabilities is None and fs.total_assets is not None and fs.total_equity is not None:
            fs.total_liabilities = fs.total_assets - fs.total_equity
        return fs  # is_mock=False 유지 → 실데이터 판별 통과

    def _market_snapshot(self, stock_code: str) -> dict:
        """실측 시총(억, KIS master)+최근 종가(원, daily_prices) — 주식수 파생·시총 단일화용.

        네트워크 0 (마스터 캐시 + DB 1행). 없으면 None → 호출측이 기존 근사 유지."""
        out: dict = {"mcap_억": None, "price": None}
        try:
            from src.data.stock_master import get_market_cap
            out["mcap_억"] = get_market_cap(stock_code)
        except Exception:
            pass
        try:
            from sqlalchemy import text

            from src.database import get_engine
            with get_engine().connect() as c:
                row = c.execute(text(
                    "SELECT close FROM daily_prices WHERE ticker=:t "
                    "ORDER BY trade_date DESC LIMIT 1"), {"t": str(stock_code)}).fetchone()
            if row and row[0]:
                out["price"] = float(row[0])
        except Exception:
            pass
        return out

    def _get_fs(self, dart, stock_code, year, db_only=False):
        """연도 재무 1건 — financials_history(DB) 우선, 없으면 라이브 DART 폴백.

        corp_code는 DB 미스 + DART 설정 시에만 지연 조회 → DB로 서빙되는 종목은
        corpCode.xml(수 MB) 다운로드 없이 즉시 반환. 콜드 프로세스·재배포 직후
        전종목이 corp_code 다운로드에 묶여 적재가 느려지던 것을 방지.
        db_only=True(성장연도용): 근사 폴백이 있으므로 네트워크 금지."""
        fs = self._fs_from_history(stock_code, year)
        if fs is not None:
            return fs
        if db_only:
            return None
        if dart is not None and getattr(dart, "is_configured", False):
            from src.data.dart_client import get_corp_code
            corp_code = get_corp_code(stock_code)
            if corp_code:
                return dart.get_financial_statement_full(corp_code, str(year))
        return None

    def _real_raw_financials(self, stock_code: str, item=None) -> dict | None:
        """
        실 원천 재무 구성 (FFL 팩터용) — financials_history(DB) 우선 → 라이브 DART 폴백.
        DB·DART 모두 없으면 None → 호출측이 mock(허용 시)/빈값 처리.

        단위: 원 → 억원으로 변환 (/1e8). 성장률 계산용 전년/3년전 재무도 함께 조회.
        """
        try:
            from datetime import datetime

            from src.data.dart_client import get_dart_client
        except Exception:
            return None

        dart = get_dart_client()  # 공용 인스턴스 (캐시 공유). DB만 있어도 동작하므로 미설정도 통과.

        def _complete(fs) -> bool:
            # 팩터 계산에 필요한 핵심 5필드가 모두 실측(mock·빈값 아님)인 '완전한' 연도.
            # ★ 최신 연도가 조기·부분 공시(매출·자산만)면 여기서 걸러 직전 완전연도를 쓴다 →
            #   과거엔 부분연도를 선택하고 5필드 게이트에서 탈락해 유니버스가 정체됐음.
            return fs is not None and not getattr(fs, "is_mock", False) and all(
                getattr(fs, k, None) is not None for k in
                ("revenue", "operating_profit", "net_income", "total_assets", "total_equity"))

        # 최신 결산연도부터 최대 8개 연도 후행 탐색 — 재무시계열 10년 적재분을 활용해
        # '완전한' 연도를 찾는다(미공시·부분공시면 한 해씩 뒤로). 없으면 정직하게 None.
        cur_year = datetime.now().year - 1
        fs = None
        for back in range(0, 8):
            cand = self._get_fs(dart, stock_code, cur_year - back)
            if _complete(cand):
                fs = cand
                cur_year -= back
                break
        if fs is None:
            return None

        # 전년 / 3년전 (성장률용) — DB 전용(네트워크 금지, 근사 폴백 존재)
        fs_prev = self._get_fs(dart, stock_code, cur_year - 1, db_only=True)
        fs_3y = self._get_fs(dart, stock_code, cur_year - 3, db_only=True)

        E8 = 1e8  # 원 → 억원
        def to_억(v):
            return (v / E8) if v is not None else None

        # 시총 (item 우선, KIS에서 주입됐을 수 있음)
        mcap = getattr(item, "market_cap_억", None) if item else None

        revenue = to_억(fs.revenue)
        gross_profit = to_억(fs.gross_profit) if fs.gross_profit is not None else (revenue * 0.3 if revenue else None)
        operating_profit = to_억(fs.operating_profit)
        net_income = to_억(fs.net_income)
        total_assets = to_억(fs.total_assets)
        total_equity = to_억(fs.total_equity)
        total_liabilities = to_억(fs.total_liabilities)
        current_assets = to_억(fs.current_assets) if fs.current_assets else (total_assets * 0.4 if total_assets else None)
        current_liabilities = to_억(fs.current_liabilities) if fs.current_liabilities else (total_liabilities * 0.5 if total_liabilities else None)
        inventory = to_억(fs.inventory) if fs.inventory else (current_assets * 0.2 if current_assets else 0)
        operating_cf = to_억(fs.operating_cf) if fs.operating_cf else (operating_profit * 1.1 if operating_profit else None)
        capex = abs(to_억(fs.investing_cf) * 0.5) if fs.investing_cf else (revenue * 0.05 if revenue else 0)
        fcf = (operating_cf - capex) if (operating_cf is not None and capex is not None) else None

        # 결측 핵심값 방어
        if None in (revenue, operating_profit, net_income, total_assets, total_equity):
            return None
        if not mcap or mcap <= 0:
            # 시총 미주입 시 PBR≈1.2 가정으로 근사 (실데이터 결합 전까지)
            mcap = total_equity * 1.2

        interest_expense = total_liabilities * 0.03 if total_liabilities else 0
        buyback = 0

        # 전년/3년전
        revenue_prev = to_억(fs_prev.revenue) if (fs_prev and fs_prev.revenue) else (revenue * 0.95)
        op_prev = to_억(fs_prev.operating_profit) if (fs_prev and fs_prev.operating_profit) else (operating_profit * 0.93)
        ni_prev = to_억(fs_prev.net_income) if (fs_prev and fs_prev.net_income) else (net_income * 0.94)
        revenue_3y_ago = to_억(fs_3y.revenue) if (fs_3y and fs_3y.revenue) else (revenue * 0.8)
        ni_3y_ago = to_억(fs_3y.net_income) if (fs_3y and fs_3y.net_income) else (net_income * 0.78)

        # ── 발행주식수 정규화(만주) — CIO 실사 "BPS ₩566만" 버그의 근본 수정 ──
        # 원인 2중: ① financials_history의 shares_outstanding은 대부분 NULL(DART 재무제표
        #   API가 주식수를 안 줌) → 10000 만주 폴백 → BPS≈자본총계(억) 그대로 노출.
        #   ② 값이 있어도 원천은 '주' 단위인데 이 모듈은 '만주' 의미로 사용 — 단위 불일치.
        # 수정: 실측 시총(KIS master)÷현재가(daily_prices)로 파생 주식수를 구해 단일 진실로.
        #   시총·주가 모두 액면분할 후(post-split) 값이라 분할 보정이 자동으로 성립한다.
        #   DART 주식수(만주 환산)와 2배 이상 괴리하면 파생값 채택(분할 미보정·오염 차단).
        dart_shares = (fs.shares_outstanding / 1e4) if fs.shares_outstanding else None  # 주→만주
        snap = self._market_snapshot(stock_code)
        derived = None
        if snap["mcap_억"] and snap["price"] and snap["price"] > 0:
            derived = snap["mcap_억"] * 1e8 / snap["price"] / 1e4   # 만주
        shares = dart_shares
        if derived and derived > 0:
            if not shares or shares <= 0 or \
                    max(shares, derived) / max(1e-9, min(shares, derived)) > 2:
                shares = derived
        if not shares or shares <= 0:
            shares = 10000  # 최후 근사 (마스터·주가 모두 미적재)
        # 시총도 실측 우선: item(KIS 주입) > master 실측 > PBR≈1.2 근사(기존)
        if (not getattr(item, "market_cap_억", None) if item else True) and snap["mcap_억"]:
            mcap = snap["mcap_억"]

        # 배당(억) = dps(원/주) × shares(만주) / 1e4. dps 미적재(None)면 dividend=None —
        # '무배당(0)'과 '미상(None)'을 구분(정직): dividend_yield/payout이 None으로 전파.
        _dps = getattr(fs, "dps", None)
        dividend = (_dps * shares / 1e4) if (_dps is not None and shares) else None
        eps = fs.eps if fs.eps else (net_income / shares * 10000 if shares else None)
        eps_prev = (ni_prev / shares * 10000) if shares else None
        eps_3y_ago = (ni_3y_ago / shares * 10000) if shares else None

        # ── 확장 원천 (기본 DART FS에 없는 항목 → 실 값 기반 근사) ──
        cash = current_assets * 0.25 if current_assets else 0
        receivables = current_assets * 0.25 if current_assets else 0
        rnd = revenue * 0.03 if revenue else 0
        sga = revenue * 0.12 if revenue else 0
        depreciation = revenue * 0.04 if revenue else 0
        tax = max(0.0, operating_profit * 0.25) if (operating_profit and operating_profit > 0) else 0.0
        ta_prev = to_억(fs_prev.total_assets) if (fs_prev and fs_prev.total_assets) else (total_assets * 0.95)
        ca_prev = to_억(fs_prev.current_assets) if (fs_prev and fs_prev.current_assets) else ((current_assets or 0) * 0.95)
        cl_prev = to_억(fs_prev.current_liabilities) if (fs_prev and fs_prev.current_liabilities) else ((current_liabilities or 0) * 0.95)
        inventory_prev = to_억(fs_prev.inventory) if (fs_prev and fs_prev.inventory) else ((inventory or 0) * 0.95)
        receivables_prev = receivables * 0.95
        equity_prev = to_억(fs_prev.total_equity) if (fs_prev and fs_prev.total_equity) else (total_equity * 0.95)
        gross_profit_prev = (revenue_prev * (gross_profit / revenue)) if (revenue_prev and revenue and gross_profit) else ((gross_profit or 0) * 0.95)
        # 분기(QoQ): 연간/4 근사는 YoY와 수치가 완전히 같아지는 복사버그(CIO 실사 지적) —
        # 실 분기 원천(financials_history 분기 보고서) 없이는 None(정직). 적재 시 후속 연결.
        rev_q = None
        rev_q_prev = None
        share_price = (mcap / shares * 100) if (mcap and shares) else 0

        # mock 스키마를 베이스로 깔고(전 키 보장) 실값+근사로 덮어쓴다 → 스키마 누락(KeyError) 불가.
        raw = self._mock_raw_financials(stock_code, item)
        raw.update(dict(
            market_cap=mcap, revenue=revenue, gross_profit=gross_profit,
            operating_profit=operating_profit, net_income=net_income,
            total_assets=total_assets, total_equity=total_equity,
            total_liabilities=total_liabilities, current_assets=current_assets,
            current_liabilities=current_liabilities, inventory=inventory or 0,
            operating_cf=operating_cf, capex=capex, fcf=fcf,
            interest_expense=interest_expense, dividend=dividend, buyback=buyback,
            revenue_prev=revenue_prev, op_prev=op_prev, ni_prev=ni_prev,
            revenue_3y_ago=revenue_3y_ago, ni_3y_ago=ni_3y_ago,
            eps=eps or 0, eps_prev=eps_prev or 0, eps_3y_ago=eps_3y_ago or 0,
            cash=cash, receivables=receivables, rnd=rnd, sga=sga,
            depreciation=depreciation, tax=tax,
            ta_prev=ta_prev, ca_prev=ca_prev, cl_prev=cl_prev,
            inventory_prev=inventory_prev, receivables_prev=receivables_prev,
            equity_prev=equity_prev, gross_profit_prev=gross_profit_prev,
            rev_q=rev_q, rev_q_prev=rev_q_prev, share_price=share_price,
            shares=shares,
            _source="dart_real",
        ))
        return raw

    def _mock_raw_financials(self, stock_code: str, item=None) -> dict:
        """결정론적 mock 원천 재무 (DART 스키마 모방, 단위: 억원)."""
        # 시총 기반 스케일 (item이 있으면 활용)
        mcap = getattr(item, "market_cap_억", None) if item else None
        if not mcap or mcap <= 0:
            mcap = abs(self._normal(stock_code, "mcap", mu=8000, sigma=15000)) + 500

        # 매출 = 시총의 0.4~1.8배
        psr_implied = self._uniform(stock_code, "psr_imp", lo=0.4, hi=1.8)
        revenue = mcap / psr_implied

        gross_m = self._uniform(stock_code, "gm", lo=0.12, hi=0.55)
        op_m = gross_m * self._uniform(stock_code, "opm_ratio", lo=0.25, hi=0.6)
        net_m = op_m * self._uniform(stock_code, "nm_ratio", lo=0.55, hi=0.92)

        gross_profit = revenue * gross_m
        operating_profit = revenue * op_m
        net_income = revenue * net_m

        total_assets = revenue * self._uniform(stock_code, "ta_ratio", lo=0.6, hi=2.2)
        debt_ratio = self._uniform(stock_code, "dr", lo=0.2, hi=2.0)  # 부채/자본
        total_equity = total_assets / (1 + debt_ratio)
        total_liabilities = total_assets - total_equity
        current_liabilities = total_liabilities * self._uniform(stock_code, "cl_ratio", lo=0.4, hi=0.8)
        current_assets = current_liabilities * self._uniform(stock_code, "ca_ratio", lo=0.8, hi=2.5)
        inventory = current_assets * self._uniform(stock_code, "inv_ratio", lo=0.1, hi=0.4)

        operating_cf = operating_profit * self._uniform(stock_code, "ocf_ratio", lo=0.7, hi=1.4)
        capex = revenue * self._uniform(stock_code, "capex_ratio", lo=0.02, hi=0.12)
        fcf = operating_cf - capex

        interest_expense = total_liabilities * self._uniform(stock_code, "int_rate", lo=0.02, hi=0.06)
        dividend = net_income * self._uniform(stock_code, "payout", lo=0, hi=0.5) if net_income > 0 else 0
        buyback = net_income * self._uniform(stock_code, "buyback", lo=0, hi=0.2) if net_income > 0 else 0

        # 전년/3년전 (성장률 계산용)
        g1 = self._uniform(stock_code, "g1", lo=-0.2, hi=0.4)
        g3 = self._uniform(stock_code, "g3", lo=-0.1, hi=0.3)
        revenue_prev = revenue / (1 + g1)
        op_prev = operating_profit / (1 + g1 * 1.3)
        ni_prev = net_income / (1 + g1 * 1.2)
        revenue_3y_ago = revenue / ((1 + g3) ** 3)
        ni_3y_ago = net_income / ((1 + g3) ** 3)

        shares = self._uniform(stock_code, "shares", lo=1000, hi=50000)  # 만주
        eps = net_income / shares * 10000  # 원
        eps_prev = ni_prev / shares * 10000
        eps_3y_ago = ni_3y_ago / shares * 10000

        # ── 추가 원천 (확장 팩터용) ──
        cash = current_assets * self._uniform(stock_code, "cash_ratio", lo=0.1, hi=0.45)
        receivables = current_assets * self._uniform(stock_code, "recv_ratio", lo=0.15, hi=0.4)
        rnd = revenue * self._uniform(stock_code, "rnd_ratio", lo=0.0, hi=0.12)
        sga = revenue * self._uniform(stock_code, "sga_ratio", lo=0.05, hi=0.25)
        depreciation = revenue * self._uniform(stock_code, "dep_ratio", lo=0.02, hi=0.08)
        tax = max(0.0, (operating_profit * 0.25)) if operating_profit > 0 else 0.0
        # 전년 대차대조표 (운전자본·발생액 변화용)
        ta_prev = total_assets / (1 + g1 * 0.8)
        ca_prev = current_assets / (1 + g1 * 0.9)
        cl_prev = current_liabilities / (1 + g1 * 0.85)
        inventory_prev = inventory / (1 + g1 * 1.1)
        receivables_prev = receivables / (1 + g1)
        equity_prev = total_equity / (1 + g1 * 0.7)
        gross_profit_prev = revenue_prev * gross_m * self._uniform(stock_code, "gm_prev", lo=0.9, hi=1.05)
        # 분기 (QoQ·가속도용)
        rev_q = revenue / 4 * self._uniform(stock_code, "q_now", lo=0.9, hi=1.15)
        rev_q_prev = revenue_prev / 4 * self._uniform(stock_code, "q_prev", lo=0.9, hi=1.1)
        # 변동성·베타 (mock — 실데이터에선 가격 시계열로 대체)
        share_price = mcap / shares * 100  # 근사 주가

        return dict(
            market_cap=mcap, revenue=revenue, gross_profit=gross_profit,
            operating_profit=operating_profit, net_income=net_income,
            total_assets=total_assets, total_equity=total_equity,
            total_liabilities=total_liabilities, current_assets=current_assets,
            current_liabilities=current_liabilities, inventory=inventory,
            operating_cf=operating_cf, capex=capex, fcf=fcf,
            interest_expense=interest_expense, dividend=dividend, buyback=buyback,
            revenue_prev=revenue_prev, op_prev=op_prev, ni_prev=ni_prev,
            revenue_3y_ago=revenue_3y_ago, ni_3y_ago=ni_3y_ago,
            eps=eps, eps_prev=eps_prev, eps_3y_ago=eps_3y_ago,
            # 확장 원천
            cash=cash, receivables=receivables, rnd=rnd, sga=sga,
            depreciation=depreciation, tax=tax,
            ta_prev=ta_prev, ca_prev=ca_prev, cl_prev=cl_prev,
            inventory_prev=inventory_prev, receivables_prev=receivables_prev,
            equity_prev=equity_prev, gross_profit_prev=gross_profit_prev,
            rev_q=rev_q, rev_q_prev=rev_q_prev, share_price=share_price, shares=shares,
        )

    def _derive_factors(self, stock_code: str, r: dict) -> dict:
        """원천 재무 → 학술 팩터 계산."""
        def safe_div(a, b, default=None):
            if b is None or abs(b) < 1e-9 or a is None:
                return default
            return a / b

        def pct(x):
            return round(x * 100, 2) if x is not None else None

        rev = r["revenue"]; mcap = r["market_cap"]; ni = r["net_income"]
        op = r["operating_profit"]; ta = r["total_assets"]; te = r["total_equity"]
        # 실데이터 경로 여부 — mock 난수 성분(모멘텀·PEAD·결측시뮬 등)을 실팩터에 섞지 않음(CIO 실사)
        is_real = r.get("_source") == "dart_real"

        # ── Phase A: 수익성 ──
        operating_margin = pct(safe_div(op, rev))
        net_margin = pct(safe_div(ni, rev))
        gross_margin = pct(safe_div(r["gross_profit"], rev))
        gp_to_assets = round(safe_div(r["gross_profit"], ta) or 0, 3)
        nopat = op * 0.75  # 세후영업이익 (세율 25% 가정)
        invested_capital = te + r["total_liabilities"] * 0.6  # 이자부부채 근사
        roic = pct(safe_div(nopat, invested_capital))
        asset_turnover = round(safe_div(rev, ta) or 0, 2)
        equity_multiplier = round(safe_div(ta, te) or 0, 2)
        fcf_margin = pct(safe_div(r["fcf"], rev))

        # ── Phase B: 밸류에이션 ──
        ebitda = op + rev * 0.05  # 감가상각 근사 5%
        ev = mcap + r["total_liabilities"] * 0.6 - r.get("cash", rev * 0.1)  # EV 근사
        ev = max(ev, mcap * 0.5)
        ev_ebitda = round(safe_div(ev, ebitda) or 0, 2)
        ev_sales = round(safe_div(ev, rev) or 0, 2)
        ev_fcf = round(safe_div(ev, r["fcf"]) or 0, 2) if r["fcf"] > 0 else None
        psr = round(safe_div(mcap, rev) or 0, 2)
        pcr = round(safe_div(mcap, r["operating_cf"]) or 0, 2) if r["operating_cf"] > 0 else None
        eps_growth = safe_div(r["eps"] - r["eps_prev"], abs(r["eps_prev"]))
        per_implied = safe_div(mcap, ni) if ni > 0 else None
        peg = round(safe_div(per_implied, (eps_growth * 100)) or 0, 2) if (per_implied and eps_growth and eps_growth > 0) else None
        fcf_yield = pct(safe_div(r["fcf"], mcap))
        earnings_yield = pct(safe_div(ni, mcap))
        acquirers_multiple = round(safe_div(ev, op) or 0, 2) if op > 0 else None
        # 배당 미상(None)이면 주주환원도 미상 — 0%로 단정하지 않음(정직)
        _div_total = (r["dividend"] + r["buyback"]) if r["dividend"] is not None else None
        shareholder_yield = pct(safe_div(_div_total, mcap))

        # ── Phase C: 성장성 ──
        revenue_growth_yoy = pct(safe_div(rev - r["revenue_prev"], abs(r["revenue_prev"])))
        op_growth_yoy = pct(safe_div(op - r["op_prev"], abs(r["op_prev"])))
        eps_growth_yoy = pct(eps_growth)
        # CAGR: 비율이 양수일 때만 3제곱근이 실수. 부호 전환(적자→흑자/흑자→적자)이면
        #   비율<0 → (음수)**(1/3)=복소수 → round() 크래시. 실데이터 적자기업에서 터지던
        #   버그(mock eps는 항상 양수라 미검출) → 비율≤0이면 CAGR 미정의로 None(정직).
        _rev_ratio = safe_div(rev, r["revenue_3y_ago"])
        revenue_cagr_3y = pct(_rev_ratio ** (1/3) - 1) if (r["revenue_3y_ago"] > 0 and _rev_ratio and _rev_ratio > 0) else None
        _eps_ratio = safe_div(r["eps"], r["eps_3y_ago"])
        eps_cagr_3y = pct(_eps_ratio ** (1/3) - 1) if (r["eps_3y_ago"] > 0 and _eps_ratio and _eps_ratio > 0) else None
        # 실데이터: 모멘텀은 가격팩터 momentum_12_1(실측)이 담당, PEAD는 컨센서스 필요 → None
        price_momentum_12_1 = None if is_real else round(self._normal(stock_code, "mom121", mu=8, sigma=22), 1)
        pead_score = None if is_real else round(self._normal(stock_code, "pead", mu=0.2, sigma=1.0), 2)

        # ── Phase D: 안정성 ──
        # Altman Z (제조업 모델): 1.2*X1 + 1.4*X2 + 3.3*X3 + 0.6*X4 + 1.0*X5
        wc = r["current_assets"] - r["current_liabilities"]
        x1 = safe_div(wc, ta) or 0
        x2 = safe_div(ni * 0.6, ta) or 0  # 이익잉여금 근사
        x3 = safe_div(op, ta) or 0
        x4 = safe_div(mcap, r["total_liabilities"]) or 0
        x5 = safe_div(rev, ta) or 0
        altman_z = round(1.2*x1 + 1.4*x2 + 3.3*x3 + 0.6*x4 + 1.0*x5, 2)
        # Beneish M — 실데이터: 산출 가능한 지수만 실측(GMI·SGI·발생액), 원천 없는 지수는
        # 중립 1.0 (mock 난수 오염 금지 — Risk 탭 8지수 드릴다운과 일관). mock 모드는 기존 유지.
        if is_real:
            gm_cur = safe_div(r["gross_profit"], rev)
            gm_prev = safe_div(r.get("gross_profit_prev"), r.get("revenue_prev"))
            dsri, aqi = 1.0, 1.0
            gmi = (gm_prev / gm_cur) if (gm_prev and gm_cur) else 1.0
        else:
            dsri = self._uniform(stock_code, "dsri", lo=0.9, hi=1.3)
            gmi = self._uniform(stock_code, "gmi", lo=0.9, hi=1.2)
            aqi = self._uniform(stock_code, "aqi", lo=0.95, hi=1.15)
        sgi = 1 + (revenue_growth_yoy or 0) / 100
        accr = safe_div(ni - r["operating_cf"], ta) or 0
        beneish_m = round(-4.84 + 0.92*dsri + 0.528*gmi + 0.404*aqi + 0.892*sgi + 4.679*accr, 2)
        current_ratio = pct(safe_div(r["current_assets"], r["current_liabilities"]))
        quick_ratio = pct(safe_div(r["current_assets"] - r["inventory"], r["current_liabilities"]))
        interest_coverage = round(safe_div(op, r["interest_expense"]) or 0, 2)
        accruals = pct(accr)
        debt_to_equity = round(safe_div(r["total_liabilities"], te) or 0, 2)

        # ── Phase E: 종합 ──
        # Piotroski F-Score (9개 항목)
        f = 0
        if ni > 0: f += 1                                    # 1. 순이익 양수
        if r["operating_cf"] > 0: f += 1                     # 2. 영업CF 양수
        if safe_div(ni, ta) and safe_div(r["ni_prev"], ta): # 3. ROA 개선
            if safe_div(ni, ta) > safe_div(r["ni_prev"], ta): f += 1
        if r["operating_cf"] > ni: f += 1                    # 4. 영업CF > 순이익 (이익의 질)
        if (revenue_growth_yoy or 0) > 0: f += 1             # 5. 매출 성장
        if (gross_margin or 0) > 30: f += 1                  # 6. 매출총이익률 양호
        if (op_growth_yoy or 0) > 0: f += 1                  # 7. 영업이익 성장
        if debt_to_equity < 1.5: f += 1                      # 8. 낮은 레버리지
        if (current_ratio or 0) > 100: f += 1                # 9. 유동성 양호
        piotroski_f = f

        # QMJ (Quality Minus Junk) — 수익성+성장+안전+배당 정규화 합산 (0~100)
        prof_z = min(1, max(-1, (gp_to_assets - 0.3) / 0.3))
        growth_z = min(1, max(-1, (revenue_growth_yoy or 0) / 30))
        safety_z = min(1, max(-1, (altman_z - 3) / 2))
        payout_z = min(1, max(-1, (shareholder_yield or 0) / 5))
        qmj_score = round((prof_z + growth_z + safety_z + payout_z + 4) / 8 * 100, 1)

        # Magic Formula rank proxy (이익수익률+ROIC 순위 — mock 순위)
        mf_quality = (earnings_yield or 0) + (roic or 0) * 0.5
        magic_formula_rank = max(1, round(200 - mf_quality * 3 + self._normal(stock_code, "mf", mu=0, sigma=15)))

        # ══════════════════════════════════════════════════════════════════════
        # 확장 팩터 (DART 원천 파생 — 추가 API 불필요)
        # ══════════════════════════════════════════════════════════════════════
        cash = r.get("cash", 0)
        rnd = r.get("rnd", 0); sga = r.get("sga", 0); dep = r.get("depreciation", 0)

        # ── 수익성 심화 (quality) ──
        roe = pct(safe_div(ni, te))                                      # 자기자본이익률
        roa = pct(safe_div(ni, ta))                                      # 총자산이익률
        # 듀폰 3분해: ROE = 순이익률 × 자산회전율 × 재무레버리지
        ebitda_margin = pct(safe_div(op + dep, rev))                     # EBITDA 마진
        ocf_to_ni = round(safe_div(r["operating_cf"], ni) or 0, 2) if ni > 0 else None  # 이익의 질
        cash_conversion = round(safe_div(r["fcf"], ni) or 0, 2) if ni > 0 else None     # 현금전환율
        rnd_intensity = pct(safe_div(rnd, rev))                          # R&D 집약도
        sga_to_revenue = pct(safe_div(sga, rev))                         # 판관비율
        capex_intensity = pct(safe_div(r["capex"], rev))                 # 설비투자 집약도
        roe_dupont = pct((safe_div(ni, rev) or 0) * (safe_div(rev, ta) or 0) * (safe_div(ta, te) or 0))

        # ── 밸류에이션 심화 (valuation) ──
        per = round(safe_div(mcap, ni) or 0, 2) if ni > 0 else None      # PER
        pbr = round(safe_div(mcap, te) or 0, 2) if te > 0 else None      # PBR
        ev_ic = round(safe_div(ev, invested_capital) or 0, 2)           # EV/투하자본
        dividend_yield = pct(safe_div(r["dividend"], mcap))             # 배당수익률
        payout_ratio = pct(safe_div(r["dividend"], ni)) if ni > 0 else None  # 배당성향
        bps = round(safe_div(te * 1e8, r["shares"] * 1e4) or 0, 0)      # 주당순자산(원)
        book_to_market = round(safe_div(te, mcap) or 0, 3)             # 장부/시장 (가치주 지표)
        ncav_to_mcap = round(safe_div(r["current_assets"] - r["total_liabilities"], mcap) or 0, 3)  # 그레이엄 NCAV

        # ── 성장성 심화 (growth) ──
        # 분기 QoQ: 실 분기 원천 없으면 None (연간/4 근사는 YoY 복사값이 되던 버그 — CIO 실사)
        revenue_qoq = pct(safe_div(r["rev_q"] - r["rev_q_prev"], abs(r["rev_q_prev"]))) \
            if (r.get("rev_q") is not None and r.get("rev_q_prev") not in (None, 0)) else None
        # 성장 가속도: 전기 성장률 원천(t-2 매출) 미보유 → 실데이터는 None(정직), mock은 기존
        growth_acceleration = None if is_real else \
            round((revenue_growth_yoy or 0) - (self._normal(stock_code, "g_accel", mu=5, sigma=10)), 2)
        sustainable_growth = pct((safe_div(ni, te) or 0) * (1 - (safe_div(r["dividend"], ni) or 0)))  # 지속가능성장률 g=ROE×유보율
        # FCF 성장: 영업이익 성장률을 프록시로 사용 (FCF 전년값 미보유)
        _fcf_g = (op_growth_yoy or 0) / 100
        fcf_growth = round((op_growth_yoy or 0) * self._uniform(stock_code, "fcfg", lo=0.7, hi=1.2), 2) if op_growth_yoy is not None else None

        # ── 안전성 심화 (safety) ──
        net_debt_to_ebitda = round(safe_div(r["total_liabilities"] - cash, op + dep) or 0, 2) if (op + dep) > 0 else None
        cash_ratio = pct(safe_div(cash, r["current_liabilities"]))      # 현금비율
        equity_ratio = pct(safe_div(te, ta))                            # 자기자본비율
        pct(safe_div(r["total_liabilities"], ta))    # 부채비율(총자산대비)
        # Sloan 발생액 (운전자본 변화 기반)
        delta_wc = (r["current_assets"] - r["ca_prev"]) - (r["current_liabilities"] - r["cl_prev"])
        sloan_accruals = pct(safe_div(delta_wc - dep, ta))
        debt_to_assets = round(safe_div(r["total_liabilities"], ta) or 0, 2)

        # ── 종합 심화 (composite) ──
        # Graham Number = sqrt(22.5 × EPS × BPS) — 적정주가
        graham_number = round((22.5 * max(0, r["eps"]) * max(0, bps)) ** 0.5, 0) if (r["eps"] > 0 and bps > 0) else None
        # Greenblatt 결합 점수 (이익수익률 + ROIC, 0~100)
        greenblatt_score = round(min(100, max(0, (earnings_yield or 0) * 2 + (roic or 0))), 1)
        # 종합 가치점수 (저평가 + 우량) — 자체 콤보
        value_composite = round(min(100, max(0,
            (book_to_market or 0) * 30 + (earnings_yield or 0) * 1.5 + (fcf_yield or 0) * 1.5)), 1)

        factors = dict(
            operating_margin=operating_margin, net_margin=net_margin, gross_margin=gross_margin,
            gp_to_assets=gp_to_assets, roic=roic, asset_turnover=asset_turnover,
            equity_multiplier=equity_multiplier, fcf_margin=fcf_margin,
            ev_ebitda=ev_ebitda, ev_sales=ev_sales, ev_fcf=ev_fcf, psr=psr, pcr=pcr,
            peg=peg, fcf_yield=fcf_yield, earnings_yield=earnings_yield,
            acquirers_multiple=acquirers_multiple, shareholder_yield=shareholder_yield,
            revenue_growth_yoy=revenue_growth_yoy, op_growth_yoy=op_growth_yoy,
            eps_growth_yoy=eps_growth_yoy, revenue_cagr_3y=revenue_cagr_3y, eps_cagr_3y=eps_cagr_3y,
            price_momentum_12_1=price_momentum_12_1, pead_score=pead_score,
            altman_z=altman_z, beneish_m=beneish_m, current_ratio=current_ratio,
            quick_ratio=quick_ratio, interest_coverage=interest_coverage,
            accruals=accruals, debt_to_equity=debt_to_equity,
            piotroski_f=piotroski_f, qmj_score=qmj_score, magic_formula_rank=magic_formula_rank,
            # ── 확장 팩터 ──
            roe=roe, roa=roa, ebitda_margin=ebitda_margin, ocf_to_ni=ocf_to_ni,
            cash_conversion=cash_conversion, rnd_intensity=rnd_intensity,
            sga_to_revenue=sga_to_revenue, capex_intensity=capex_intensity, roe_dupont=roe_dupont,
            per=per, pbr=pbr, ev_ic=ev_ic, dividend_yield=dividend_yield,
            payout_ratio=payout_ratio, bps=bps, book_to_market=book_to_market, ncav_to_mcap=ncav_to_mcap,
            revenue_qoq=revenue_qoq, growth_acceleration=growth_acceleration,
            sustainable_growth=sustainable_growth, fcf_growth=fcf_growth,
            net_debt_to_ebitda=net_debt_to_ebitda, cash_ratio=cash_ratio,
            equity_ratio=equity_ratio,
            sloan_accruals=sloan_accruals, debt_to_assets=debt_to_assets,
            graham_number=graham_number, greenblatt_score=greenblatt_score, value_composite=value_composite,
        )

        # 결측 시뮬 — mock 전용 (실데이터에 인위 결측을 섞으면 오염 — CIO 실사)
        if not is_real:
            optional_missing = ["ev_fcf", "pcr", "peg", "revenue_cagr_3y", "eps_cagr_3y", "interest_coverage"]
            for k in optional_missing:
                factors[k] = self._maybe_missing(stock_code, f"m_{k}", value=factors[k], missing_rate=0.10)

        factors["_source"] = "dart_real" if r.get("_source") == "dart_real" else "ffl_mock"
        return factors


def attach_fundamentals(items: list) -> int:
    """
    ScreenerItem 리스트에 펀더멘털 팩터를 동적 속성으로 주입.
    field kind가 getattr(item, factor_id)로 접근하므로 setattr로 부착.
    Returns: 주입된 종목 수
    """
    import os
    store = FundamentalsStore.get_default()
    codes = [c for c in (getattr(it, "stock_code", None) for it in items) if c]
    store.prime([f"ffl:{c}" for c in codes])  # DB → in-memory 벌크(1쿼리) → 종목별 호출은 히트
    # 미적재(캐시 미스) 종목의 실시간 계산은 요청당 상한 — 전종목(~3,970) 선택 시
    # DART 쿼터 폭발/지연 방지. 적재(ingest)는 이 경로를 안 거치므로 전체 적재엔 무영향.
    max_live = int(os.getenv("SCREENER_MAX_LIVE_COMPUTE", "400"))
    live = 0
    count = 0
    for it in items:
        code = getattr(it, "stock_code", None)
        if not code:
            continue
        if f"ffl:{code}" not in store._cache:
            if live >= max_live:
                continue  # 한도 초과: 미적재 종목은 이번엔 스킵 (ingest 후 표시)
            live += 1
        # 종목별 격리 — 한 종목 계산이 예외를 던져도 청크 전체(뒤 종목들)의 주입·영속이
        # 중단되지 않게. (적자기업 CAGR 크래시처럼 한 건이 배치를 통째로 날리던 문제 방어)
        try:
            factors = store.get_factors(code, it)
        except Exception:
            logger.exception(f"펀더멘털 계산 실패 [{code}] — 이 종목만 건너뜀")
            continue
        for fid, val in factors.items():
            if not fid.startswith("_"):
                setattr(it, fid, val)
        # 동일 지표 단일화(CIO 실사: 헤더 PER 36.99 vs 팩터 15.05 불일치) — 실데이터에선
        # ffl 팩터를 단일 진실로 삼아 기본 필드(roe_pct/per 등)를 동기화. mock은 불변.
        if factors.get("_source") == "dart_real":
            for src_key, dst_attr in (("roe", "roe_pct"), ("roa", "roa_pct"),
                                      ("per", "per"), ("pbr", "pbr"),
                                      ("dividend_yield", "dividend_yield_pct")):
                v = factors.get(src_key)
                if v is not None:
                    setattr(it, dst_attr, v)
        count += 1
    return count


def fundamentals_catalog() -> dict:
    """API용 펀더멘털 팩터 카탈로그 (카테고리별)."""
    by_cat: dict = {}
    for f in FUNDAMENTAL_FACTORS:
        by_cat.setdefault(f.category, []).append({
            "id": f.id, "label": f.label, "unit": f.unit,
            "higher_better": f.higher_better,
            "typical_min": f.typical_min, "typical_max": f.typical_max,
            "source": f.source, "description": f.description,
        })
    return {
        "categories": [
            {"id": cat, "label": FACTOR_CATEGORY_LABELS.get(cat, cat), "factors": facs}
            for cat, facs in by_cat.items()
        ],
        "total": len(FUNDAMENTAL_FACTORS),
    }
