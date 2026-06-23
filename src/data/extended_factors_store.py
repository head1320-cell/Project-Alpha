"""
확장 팩터 스토어 — Butler 택소노미 Tier1/2 (유료 제외 전 팩터)
==========================================================================
fundamentals_store / price_factors_store 동일 패턴(DeterministicMockStore):
  · KIS_USE_MOCK=1·키 없음 → 결정론적 mock(종목별 일관)
  · 키 설정 시 실데이터/실파생 자동 — 전부 try/except → mock 폴백(무중단)

구현 방식(메타 주도):
  · DERIVE: 기존 DART raw(fundamentals_store.get_raw_financials) + KIS 가격에서 실공식 파생
            (매출원가율·회전율·CCC·POR·FCF배당성향·자산비중·1년수익률·총수익률·증가율 등)
  · REAL hook: 외국인지분율(KIS) · 주당배당금(DART dps) · 직원/임원(DART 사업보고서)
  · MOCK: 공시 기반 niche(배당횟수·자사주소각·주주현황·수주잔고·IR 등) — 메타 typical 범위
컨센서스(목표주가·예상실적)·공매도는 유료라 제외(미구현).
"""

from __future__ import annotations

import datetime as _dt
import logging
import os
from dataclasses import dataclass

from src.data.mock_base import DeterministicMockStore

logger = logging.getLogger(__name__)


@dataclass
class ExtFactorMeta:
    id: str
    label: str          # = Butler 토큰명 (catalog·_label_aliases 와 일치)
    category: str       # dividend | ownership | business | financials | fundamental | valuation | stock | ir
    unit: str
    higher_better: bool
    typical_min: float
    typical_max: float
    source: str
    description: str


def _M(id, label, cat, unit, hb, lo, hi, src="", desc=""):
    return ExtFactorMeta(id, label, cat, unit, hb, lo, hi, src, desc)


EXTENDED_FACTORS: list[ExtFactorMeta] = [
    # ── Tier1: 배당·자사주·지분율 ──
    _M("dps", "주당배당금", "dividend", "원", True, 0, 5000, "DART", "주당 현금배당금"),
    _M("treasury_ratio", "자사주보유비율", "dividend", "%", True, 0, 20, "DART", "발행주식 대비 자기주식"),
    _M("foreign_ownership", "외국인지분율", "ownership", "%", True, 0, 60, "KIS", "외국인 보유(소진)율"),
    _M("div_count", "배당횟수", "dividend", "회", True, 0, 4, "DART", "연간 배당 횟수"),
    _M("div_at_record", "배당시점배당수익률", "dividend", "%", True, 0, 8, "DART", "배당기준일 시가배당률"),
    _M("div_total_growth", "배당금총액증가율", "dividend", "%", True, -30, 50, "DART", "배당금 총액 YoY"),
    _M("fcf_payout", "FCF배당성향", "dividend", "%", True, 0, 100, "DART 파생", "배당금 / FCF"),
    _M("treasury_cancel_cnt", "자사주소각횟수", "dividend", "회", True, 0, 3, "DART", "최근 자사주 소각 횟수"),
    _M("treasury_cancel_ratio", "자사주소각비율", "dividend", "%", True, 0, 10, "DART", "소각 / 발행주식"),
    # ── Tier2: 사업정보(직원·임원·수주) ──
    _M("employees", "직원수", "business", "명", True, 50, 50000, "DART 사업보고서", "전체 직원 수"),
    _M("emp_growth", "직원수증가율", "business", "%", True, -20, 30, "DART", "직원수 YoY"),
    _M("male_emp", "남자직원수", "business", "명", True, 30, 35000, "DART", "남자 직원 수"),
    _M("female_emp", "여자직원수", "business", "명", True, 10, 20000, "DART", "여자 직원 수"),
    _M("female_ratio", "여자직원비율", "business", "%", True, 5, 70, "DART", "여자 직원 비율"),
    _M("avg_salary", "평균급여", "business", "백만원", True, 30, 150, "DART", "1인 평균 연봉"),
    _M("avg_salary_growth", "평균급여증가율", "business", "%", True, -10, 25, "DART", "평균급여 YoY"),
    _M("salary_total", "직원급여총액", "business", "억", True, 50, 50000, "DART 파생", "직원수 × 평균급여"),
    _M("rev_per_emp", "1인당매출액", "business", "백만원", True, 100, 3000, "DART 파생", "매출 / 직원수"),
    _M("op_per_emp", "1인당영업이익", "business", "백만원", True, -100, 500, "DART 파생", "영업이익 / 직원수"),
    _M("executives", "임원수", "business", "명", True, 3, 20, "DART 사업보고서", "임원 수"),
    _M("exec_avg_salary", "임원평균급여", "business", "백만원", True, 100, 2000, "DART", "임원 1인 평균 보수"),
    _M("exec_salary_growth", "임원급여총액증가율", "business", "%", True, -20, 40, "DART", "임원 보수총액 YoY"),
    _M("order_backlog", "수주잔고", "business", "억", True, 0, 100000, "DART", "수주잔고(업종 한정)"),
    _M("order_backlog_growth", "수주잔고증가율", "business", "%", True, -40, 60, "DART", "수주잔고 YoY"),
    # ── 주주현황·발행·내부자 ──
    _M("major_holder", "대주주지분율", "business", "%", True, 5, 75, "DART", "최대주주 및 특수관계인 지분"),
    _M("minority_cnt", "소액주주수", "business", "명", True, 1000, 800000, "DART", "소액주주 수"),
    _M("minority_ratio", "소액주주지분율", "business", "%", True, 10, 80, "DART", "소액주주 지분율"),
    _M("pref_shares", "우선주발행", "business", "만주", True, 0, 5000, "DART", "우선주 발행주식수"),
    _M("insider_buy", "장내매수", "business", "주", True, 0, 1000000, "DART", "임원·주요주주 장내매수"),
    _M("insider_sell", "장내매도", "business", "주", False, 0, 1000000, "DART", "임원·주요주주 장내매도"),
    # ── 재무정보(자산구성·CAPEX) ──
    _M("tangible_ratio", "유형자산비중", "financials", "%", True, 10, 80, "DART 파생", "비유동자산/총자산 근사"),
    _M("intangible_ratio", "무형자산비중", "financials", "%", True, 0, 30, "DART", "무형자산/총자산"),
    _M("net_fin_asset", "시총대비순금융자산비율", "financials", "%", True, -50, 60, "DART 파생", "(현금-부채)/시총"),
    _M("capex_amt", "자본지출(CAPEX)", "financials", "억", False, 0, 100000, "DART", "자본적지출"),
    # ── 펀더멘탈(원가·회전율·증가율) ──
    _M("cogs_ratio", "매출원가율", "fundamental", "%", False, 30, 95, "DART 파생", "매출원가/매출액"),
    _M("gp_growth", "매출총이익성장율", "fundamental", "%", True, -30, 50, "DART 파생", "매출총이익 YoY"),
    _M("inv_growth", "재고자산증가율", "fundamental", "%", False, -30, 50, "DART 파생", "재고자산 YoY"),
    _M("recv_growth", "매출채권증가율", "fundamental", "%", False, -30, 50, "DART 파생", "매출채권 YoY"),
    _M("payable_growth", "매입채무증가율", "fundamental", "%", True, -30, 50, "DART", "매입채무 YoY"),
    _M("recv_turnover", "매출채권회전율", "fundamental", "회", True, 2, 20, "DART 파생", "매출/매출채권"),
    _M("inv_turnover", "재고자산회전율", "fundamental", "회", True, 2, 30, "DART 파생", "매출/재고자산"),
    _M("ccc", "현금회전일수", "fundamental", "일", False, -30, 200, "DART 파생", "DSO+DIO-DPO"),
    # ── 밸류에이션 ──
    _M("por", "POR", "valuation", "배", False, 1, 50, "KIS+DART 파생", "시총/영업이익"),
    _M("bps_growth", "주당순자산증가율", "valuation", "%", True, -20, 40, "DART 파생", "자본(BPS) YoY"),
    # ── 주식정보(수익률·거래) ──
    _M("return_1y", "주가변동률1년", "stock", "%", True, -50, 80, "KIS", "최근 252일 수익률"),
    _M("investor_return", "투자자주가수익률", "stock", "%", True, -50, 80, "KIS", "주가 수익률(1년)"),
    _M("total_return", "총수익률", "stock", "%", True, -50, 85, "KIS+DART", "주가수익률 + 배당수익률"),
    _M("amount_growth", "거래대금증가율", "stock", "%", True, -50, 100, "KIS", "거래대금 추세"),
    # ── IR ──
    _M("earnings_recency", "실적발표일", "ir", "일", False, 0, 180, "DART 공시", "최근 실적발표 경과일"),
    _M("ir_count", "기업설명회횟수", "ir", "회", True, 0, 12, "DART 공시", "최근 1년 IR 횟수"),
]
EXT_FACTOR_BY_ID = {f.id: f for f in EXTENDED_FACTORS}
EXT_CATEGORY_LABELS = {
    "dividend": "배당·자사주", "ownership": "지분율", "business": "사업정보",
    "financials": "재무정보", "fundamental": "펀더멘탈", "valuation": "밸류에이션",
    "stock": "주식정보", "ir": "IR",
}
_INT_UNITS = {"명", "회", "주", "만주", "일"}


class ExtendedFactorsStore(DeterministicMockStore):
    """Butler 확장 팩터(유료 제외 전 팩터). Mock + 실파생/실데이터 hook."""

    PERSIST = True
    _default = None

    @classmethod
    def get_default(cls):
        if cls._default is None:
            cls._default = cls()
        return cls._default

    def get_factors(self, stock_code: str, item=None) -> dict:
        return self.cached(f"ext_factors:{stock_code}", lambda: self._build(stock_code))

    def _build(self, stock_code: str) -> dict:
        # 1) 메타 typical 범위로 결정론적 mock 채움
        out: dict = {}
        for m in EXTENDED_FACTORS:
            v = self._uniform(stock_code, m.id, lo=m.typical_min, hi=m.typical_max)
            out[m.id] = round(v) if m.unit in _INT_UNITS else round(v, 2)
        # 2) 실데이터 hook(외국인지분율·주당배당금·직원/임원) — 가능 시 override
        for k, v in {**self._real_ownership(stock_code), **self._real_dividend(stock_code),
                     **self._real_business(stock_code)}.items():
            if v is not None:
                out[k] = v
        # 3) 실공식 파생(기존 raw·가격) — 가능 항목 override
        for k, v in self._derive(stock_code, out).items():
            if v is not None:
                out[k] = v
        out["_source"] = "ext"
        return out

    # ── 실공식 파생 (기존 DART raw + KIS 가격) ──────────────────────────────────
    def _derive(self, code: str, base: dict) -> dict:
        try:
            from src.data.fundamentals_store import FundamentalsStore
            fs = FundamentalsStore.get_default()
            r = fs.get_raw_financials(code) or {}
        except Exception:
            return {}
        g = r.get
        rev = g("revenue") or 0.0; gp = g("gross_profit") or 0.0; cogs = max(rev - gp, 0.0)
        mcap = g("market_cap") or 0.0; op = g("operating_profit") or 0.0
        inv = g("inventory") or 0.0; recv = g("receivables") or 0.0
        cash = g("cash") or 0.0; tl = g("total_liabilities") or 0.0
        ta = g("total_assets") or 0.0; ca = g("current_assets") or 0.0; cl = g("current_liabilities") or 0.0
        div = g("dividend") or 0.0; fcf = g("fcf") or 0.0
        te = g("total_equity") or 0.0; te_prev = g("equity_prev") or 0.0
        capex = g("capex") or 0.0
        inv_prev = g("inventory_prev") or 0.0; recv_prev = g("receivables_prev") or 0.0
        gp_prev = g("gross_profit_prev") or 0.0

        d: dict = {}
        if rev > 0:
            d["cogs_ratio"] = round(cogs / rev * 100, 2)
        if inv > 0:
            d["inv_turnover"] = round(rev / inv, 2)
        if recv > 0:
            d["recv_turnover"] = round(rev / recv, 2)
        if rev > 0 and cogs > 0:
            dso = recv / rev * 365; dio = inv / cogs * 365; dpo = (cl * 0.35) / cogs * 365
            d["ccc"] = round(dso + dio - dpo, 1)
        if mcap > 0:
            d["net_fin_asset"] = round((cash - tl * 0.5) / mcap * 100, 2)
        d["capex_amt"] = round(capex, 1)
        if op > 0:
            d["por"] = round(mcap / op, 2)
        if fcf > 0:
            d["fcf_payout"] = round(min(div / fcf * 100, 300), 2)
        if te_prev > 0:
            d["bps_growth"] = round((te / te_prev - 1) * 100, 2)
        if ta > 0:
            d["tangible_ratio"] = round(max(ta - ca, 0.0) / ta * 100, 2)
        if gp_prev > 0:
            d["gp_growth"] = round((gp / gp_prev - 1) * 100, 2)
        if inv_prev > 0:
            d["inv_growth"] = round((inv / inv_prev - 1) * 100, 2)
        if recv_prev > 0:
            d["recv_growth"] = round((recv / recv_prev - 1) * 100, 2)
        # 직원급여총액(억) = 직원수 × 평균급여(백만원)/100, 성별 직원수 = 직원수 × 비율
        emp = base.get("employees"); sal = base.get("avg_salary"); fr = base.get("female_ratio")
        if emp and sal:
            d["salary_total"] = round(emp * sal / 100, 1)
        if emp and rev > 0:
            d["rev_per_emp"] = round(rev * 100 / emp, 1)   # 억 → 백만원
        if emp and op:
            d["op_per_emp"] = round(op * 100 / emp, 1)
        if emp is not None and fr is not None:
            d["female_emp"] = round(emp * fr / 100); d["male_emp"] = round(emp * (1 - fr / 100))
        # 가격(1년 수익률·총수익률·거래대금추세)
        try:
            from src.data.price_factors_store import PriceFactorsStore
            pf = PriceFactorsStore.get_default().get_factors(code) or {}
            r12 = pf.get("return_12m")
            if r12 is not None:
                d["return_1y"] = r12; d["investor_return"] = r12
                dy = None
                try:
                    dy = (fs.get_factors(code) or {}).get("dividend_yield")
                except Exception:
                    pass
                d["total_return"] = round(r12 + (dy or 0.0), 2)
            vt = pf.get("volume_trend_20d")
            if vt is not None:
                d["amount_growth"] = vt
        except Exception:
            pass
        return d

    # ── 실데이터 hook ───────────────────────────────────────────────────────────
    def _real_ownership(self, code: str) -> dict:
        if os.getenv("KIS_USE_MOCK", "1") == "1":
            return {}
        try:
            from src.execution.kis_client import get_kis_client
            p = get_kis_client().get_price(code) or {}
            v = p.get("hts_frgn_ehrt") or p.get("frgn_ehrt")
            return {"foreign_ownership": round(float(v), 2)} if v not in (None, "") else {}
        except Exception as e:
            logger.debug(f"외국인지분율 조회 실패 [{code}]: {e}")
            return {}

    def _real_dividend(self, code: str) -> dict:
        if not os.getenv("DART_API_KEY"):
            return {}
        try:
            from src.data.fundamentals_store import FundamentalsStore
            raw = FundamentalsStore.get_default().get_raw_financials(code) or {}
            dps = raw.get("dps")
            return {"dps": round(float(dps), 1)} if dps not in (None, "") else {}
        except Exception as e:
            logger.debug(f"주당배당금 조회 실패 [{code}]: {e}")
            return {}

    def _real_business(self, code: str) -> dict:
        """DART 사업보고서(직원·임원) best-effort. 실패 시 {} (mock/파생 유지)."""
        if not os.getenv("DART_API_KEY"):
            return {}
        try:
            from src.data.dart_client import get_corp_code, get_dart_client
            corp = get_corp_code(code)
            if not corp:
                return {}
            client = get_dart_client()
            year = str(_dt.date.today().year - 1)
            out: dict = {}

            def _num(s):
                try:
                    return float(str(s).replace(",", ""))
                except (ValueError, TypeError):
                    return None
            emp = client._get("empSttus.json", {"corp_code": corp, "bsns_year": year, "reprt_code": "11011"})
            rows = (emp or {}).get("list") or []
            if rows:
                total = sum(_num(r.get("sm")) or 0 for r in rows)
                if total > 0:
                    out["employees"] = round(total)
                sal = [_num(r.get("jan_salary_am")) for r in rows if _num(r.get("jan_salary_am"))]
                if sal:
                    out["avg_salary"] = round(sum(sal) / len(sal) / 1_000_000, 1)
            exe = client._get("exctvSttus.json", {"corp_code": corp, "bsns_year": year, "reprt_code": "11011"})
            erows = (exe or {}).get("list") or []
            if erows:
                out["executives"] = len(erows)
            return out
        except Exception as e:
            logger.debug(f"사업보고서 조회 실패 [{code}]: {e}")
            return {}


def attach_extended_factors(items: list) -> int:
    """ScreenerItem 리스트에 확장 팩터 주입 (attach_price_factors 동일 패턴)."""
    store = ExtendedFactorsStore.get_default()
    codes = [c for c in (getattr(it, "stock_code", None) for it in items) if c]
    store.prime([f"ext_factors:{c}" for c in codes])
    max_live = int(os.getenv("SCREENER_MAX_LIVE_COMPUTE", "400"))
    live = 0
    count = 0
    for it in items:
        code = getattr(it, "stock_code", None)
        if not code:
            continue
        if f"ext_factors:{code}" not in store._cache:
            if live >= max_live:
                continue
            live += 1
        for fid, val in store.get_factors(code, it).items():
            if not fid.startswith("_"):
                setattr(it, fid, val)
        count += 1
    return count
