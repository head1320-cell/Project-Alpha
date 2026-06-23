"""
확장 팩터 스토어 — Butler 택소노미 Tier1/2 (배당상세·자사주·지분율·사업정보)
==========================================================================
fundamentals_store / price_factors_store 와 동일 패턴(DeterministicMockStore):
  · KIS_USE_MOCK=1 또는 키 없으면 결정론적 mock(종목별 일관)
  · 키 설정 시 실데이터 자동 — 전부 try/except → mock 폴백(프로덕션 무중단)

데이터 출처(실데이터 경로):
  · 외국인지분율   : KIS 현재가(hts_frgn_ehrt 외국인 소진율)
  · 주당배당금     : DART 재무(FinancialStatement.dps — 기존 추출분)
  · 직원수/평균급여 : DART 사업보고서 empSttus.json (직원 현황)
  · 임원수         : DART 사업보고서 exctvSttus.json (임원 현황)
  · 자사주보유비율  : DART tesstkAcqsDspsSttus.json (자기주식) — best-effort
  · 1인당매출/영업익: 매출/영업이익(DART) ÷ 직원수
※ 사업보고서·자기주식 실파싱은 실 DART 응답으로 GCP에서 보정(현재 mock 폴백 안전).
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
    label: str          # = Butler 토큰명 (factor_tokens.FUNDAMENTAL_ALIASES 와 일치)
    category: str       # dividend | ownership | business
    unit: str
    higher_better: bool
    typical_min: float
    typical_max: float
    source: str
    description: str


EXTENDED_FACTORS: list[ExtFactorMeta] = [
    ExtFactorMeta("dps", "주당배당금", "dividend", "원", True, 0, 5000, "DART 배당", "최근 결산 주당 현금배당금"),
    ExtFactorMeta("treasury_ratio", "자사주보유비율", "dividend", "%", True, 0, 20, "DART 자기주식", "발행주식 대비 자기주식 보유 비율"),
    ExtFactorMeta("foreign_ownership", "외국인지분율", "ownership", "%", True, 0, 60, "KIS 시세", "외국인 보유(소진) 비율"),
    ExtFactorMeta("employees", "직원수", "business", "명", True, 50, 50000, "DART 사업보고서", "전체 직원 수"),
    ExtFactorMeta("avg_salary", "평균급여", "business", "백만원", True, 30, 150, "DART 사업보고서", "1인 평균 연간 급여액"),
    ExtFactorMeta("rev_per_emp", "1인당매출액", "business", "백만원", True, 100, 3000, "DART 파생", "매출액 / 직원수"),
    ExtFactorMeta("op_per_emp", "1인당영업이익", "business", "백만원", True, -100, 500, "DART 파생", "영업이익 / 직원수"),
    ExtFactorMeta("executives", "임원수", "business", "명", True, 3, 20, "DART 사업보고서", "등기/미등기 임원 수"),
]
EXT_FACTOR_BY_ID = {f.id: f for f in EXTENDED_FACTORS}
EXT_CATEGORY_LABELS = {"dividend": "배당·자사주", "ownership": "지분율", "business": "사업정보"}


class ExtendedFactorsStore(DeterministicMockStore):
    """Butler 확장 팩터(배당·지분율·사업정보). Mock + 실데이터 hook."""

    PERSIST = True
    _default = None

    @classmethod
    def get_default(cls):
        if cls._default is None:
            cls._default = cls()
        return cls._default

    def get_factors(self, stock_code: str, item=None) -> dict:
        return self.cached(f"ext_factors:{stock_code}", lambda: self._build(stock_code))

    # ── 빌더: 실데이터 우선 → 항목별 mock 폴백 ────────────────────────────────
    def _build(self, stock_code: str) -> dict:
        m = self._mock(stock_code)
        if os.getenv("KIS_USE_MOCK", "1") == "1" and not os.getenv("DART_API_KEY"):
            return m
        real = {}
        real.update(self._real_ownership(stock_code))
        real.update(self._real_dividend(stock_code))
        real.update(self._real_business(stock_code))
        # 실데이터가 채운 항목만 덮어쓰기(나머지는 mock 유지 — 부분 결측 안전)
        out = dict(m)
        for k, v in real.items():
            if v is not None:
                out[k] = v
        out["_source"] = "ext_real" if real else "ext_mock"
        return out

    def _real_ownership(self, stock_code: str) -> dict:
        if os.getenv("KIS_USE_MOCK", "1") == "1":
            return {}
        try:
            from src.execution.kis_client import get_kis_client
            p = get_kis_client().get_price(stock_code) or {}
            v = p.get("hts_frgn_ehrt") or p.get("frgn_ehrt")
            return {"foreign_ownership": round(float(v), 2)} if v not in (None, "") else {}
        except Exception as e:
            logger.debug(f"외국인지분율 조회 실패 [{stock_code}]: {e}")
            return {}

    def _real_dividend(self, stock_code: str) -> dict:
        if not os.getenv("DART_API_KEY"):
            return {}
        try:
            from src.data.fundamentals_store import FundamentalsStore
            raw = FundamentalsStore.get_default().get_raw_financials(stock_code) or {}
            dps = raw.get("dps")
            return {"dps": round(float(dps), 1)} if dps not in (None, "") else {}
        except Exception as e:
            logger.debug(f"주당배당금 조회 실패 [{stock_code}]: {e}")
            return {}

    def _real_business(self, stock_code: str) -> dict:
        """DART 사업보고서(직원·임원) — best-effort. 실패 시 {} (mock 유지)."""
        if not os.getenv("DART_API_KEY"):
            return {}
        try:
            from src.data.dart_client import get_corp_code, get_dart_client
            corp = get_corp_code(stock_code)
            if not corp:
                return {}
            client = get_dart_client()
            year = str(_dt.date.today().year - 1)
            out: dict = {}
            emp = client._get("empSttus.json", {"corp_code": corp, "bsns_year": year, "reprt_code": "11011"})
            rows = (emp or {}).get("list") or []
            if rows:
                def _num(s):
                    try:
                        return float(str(s).replace(",", ""))
                    except (ValueError, TypeError):
                        return None
                total = sum(_num(r.get("sm")) or 0 for r in rows)
                if total > 0:
                    out["employees"] = round(total)
                sal = [_num(r.get("jan_salary_am")) for r in rows if _num(r.get("jan_salary_am"))]
                if sal:
                    out["avg_salary"] = round(sum(sal) / len(sal) / 1_000_000, 1)  # 원 → 백만원
            exe = client._get("exctvSttus.json", {"corp_code": corp, "bsns_year": year, "reprt_code": "11011"})
            erows = (exe or {}).get("list") or []
            if erows:
                out["executives"] = len(erows)
            return out
        except Exception as e:
            logger.debug(f"사업보고서 조회 실패 [{stock_code}]: {e}")
            return {}

    # ── 결정론적 mock ─────────────────────────────────────────────────────────
    def _mock(self, stock_code: str) -> dict:
        u = self._uniform
        emp = round(u(stock_code, "emp", lo=80, hi=30000))
        rev_pe = round(u(stock_code, "rpe", lo=120, hi=2500), 1)
        return {
            "dps": round(u(stock_code, "dps", lo=0, hi=3000)),
            "treasury_ratio": round(u(stock_code, "trs", lo=0, hi=15), 2),
            "foreign_ownership": round(u(stock_code, "frgn", lo=0, hi=55), 2),
            "employees": emp,
            "avg_salary": round(u(stock_code, "sal", lo=35, hi=130), 1),
            "rev_per_emp": rev_pe,
            "op_per_emp": round(rev_pe * u(stock_code, "ope", lo=-0.05, hi=0.2), 1),
            "executives": round(u(stock_code, "exec", lo=3, hi=15)),
            "_source": "ext_mock",
        }


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
