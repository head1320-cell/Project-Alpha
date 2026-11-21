"""가치평가 엔진은 ★가격이 없으면 가격에서 나오는 값을 모른다고 말한다★ (2026-11-21 · 감사 F3)
====================================================================================
스크리너는 운영(`KIS_USE_MOCK≠"1"`)에서 확인된 가격(실시세·적재 종가)이 없는 종목을 합성 바탕 가격으로 평가했다(F3).
고친 뒤에는 가격 없이(`current_price=None`) 평가한다 — 그래서 엔진이 `None` 을 받아야 한다.

계약(엔진 · `ValuationEngine.evaluate`):
  · 가격이 없으면 가격에서 나오는 값 — 괴리율 · 판정 · PER · PBR · 배당수익률 — 은 ★미상★이다(판정 문자열은 "시세 없음").
  · 가격과 무관한 값 — 적정가 · 모델별 적정가 · ROE · ROA · 부채비율 · FCF · EPS · BPS · DPS — 은 ★가격이 있을 때와 같다★.
  · ★짝★ 숫자 가격을 주면 예전과 한 자리도 같다(다른 호출부 다섯 곳 — 회사 화면·밸류에이션 경로 — 는 그대로다).
  · 적정가가 없는(0) 종목의 괴리율 0 은 가격과 무관한 정의다(`compute_gap_pct` — "정의 불가") — 가격이 없어도 그대로(F7 은 손대지 않는다).

DART 는 흉내 낸다(재무 한 벌) — 진짜 `load_statement → prepare_statement → evaluate` 를 탄다(가격이 `compute_ratios` 의 배당수익률로
들어가는 길까지). 시험 순서: ★고치기 전에★ 일곱 가운데 둘(가격 없이 · 적정가가 있는 종목)이 `TypeError` 로 실패했다 — 나머지
다섯은 짝(숫자 가격)이거나 예전에도 맞던 경우(적정가 0 · 재무 없음 — 가격 산술에 닿지 않는다)다.
"""
from __future__ import annotations

import copy

import pytest

from src.data.dart_client import FinancialStatement
from src.engine.valuation.valuation_models import ValuationEngine

CODE = "005930"
#: 삼성전자 근사 재무(원) — `DARTClient._mock_financial_statement` 의 숫자. 세 모델이 모두 산출된다.
FS = FinancialStatement(
    corp_code="00126380", corp_name="테스트전자", bsns_year="2025", reprt_code="11011",
    revenue=300e12, operating_profit=35e12, net_income=28e12,
    total_assets=450e12, total_liabilities=100e12, total_equity=350e12,
    operating_cf=60e12, capex=45e12, shares_outstanding=5_969_782_550, dps=1444,
)
#: 모델이 하나도 산출되지 않는 재무(적정가 0) — 매출 말고는 없다.
FS_EMPTY = FinancialStatement(corp_code="00000001", corp_name="빈회사", bsns_year="2025", reprt_code="11011", revenue=1e12)

#: 가격에서 나오는 값(엔진의 출력에서) — 아래 '두 가격' 시험이 이 집합을 동작으로 확인한다.
PRICE_DERIVED_UV = {"current_price", "gap_pct", "verdict"}
PRICE_DERIVED_FIN = {"per", "pbr", "dividend_yield_pct"}


class _FakeDart:
    """재무 한 벌을 매번 ★새로★ 준다(`prepare_statement` 가 제자리에서 손질하므로)."""

    def __init__(self, fs):
        self.fs = fs

    def get_financial_statement_full(self, corp_code, bsns_year):
        return copy.deepcopy(self.fs)

    def get_corp_info(self, corp_code):
        return None


def _eval(price, fs=FS):
    return ValuationEngine(_FakeDart(fs)).evaluate(CODE, price, bsns_year="2025")


@pytest.fixture(autouse=True)
def _prod(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "0")      # 엔진은 게이트와 무관하다 — 운영 쪽에서 본다(합성 재무 폴백 방어가 켜진 채)


# ── 짝: 숫자 가격은 예전 그대로 ───────────────────────────────────────────────────────────────────
def test_a_numeric_price_values_exactly_as_before():
    """★짝★ 손으로 다시 계산한 값 — 괴리율 = (가격 − 적정가)/적정가 · PER = 가격/EPS · PBR = 가격/BPS · 배당 = DPS/가격."""
    uv = _eval(70_000.0)
    eps, bps = 28e12 / 5_969_782_550, 350e12 / 5_969_782_550
    assert uv.current_price == 70_000.0
    assert uv.intrinsic_value > 0 and len([m for m in uv.models if m.available]) == 3
    want_gap = round((70_000.0 - uv.intrinsic_value) / uv.intrinsic_value * 100, 2)
    assert uv.gap_pct == pytest.approx(want_gap, abs=0.011)   # 적정가는 반올림된 값 — 엔진은 반올림 전 값으로 낸다
    assert uv.financial_summary["per"] == round(70_000.0 / eps, 2)
    assert uv.financial_summary["pbr"] == round(70_000.0 / bps, 2)
    assert uv.financial_summary["dividend_yield_pct"] == round(1444 / 70_000.0 * 100, 2)
    assert uv.verdict not in ("시세 없음", "데이터 없음")


def test_a_numeric_price_on_a_company_without_models_keeps_the_zero_gap():
    """★짝★ 적정가가 없으면 괴리율은 0("정의 불가") · 판정 "적정" — 예전 그대로(F7 은 이 변경의 범위 밖이다)."""
    uv = _eval(70_000.0, FS_EMPTY)
    assert (uv.intrinsic_value, uv.gap_pct, uv.verdict) == (0, 0, "적정")


# ── 가격이 없으면 가격에서 나오는 값은 미상 ──────────────────────────────────────────────────────
def test_without_a_price_the_price_derived_values_are_unknown():
    uv = _eval(None)
    assert uv.current_price is None
    assert uv.gap_pct is None
    assert uv.verdict == "시세 없음"
    fin = uv.financial_summary
    assert (fin["per"], fin["pbr"], fin["dividend_yield_pct"]) == (None, None, None)


def test_without_a_price_the_price_free_values_are_the_same():
    """★짝★ 가격이 없어도 적정가·모델·재무는 가격이 있을 때와 같다 — '모르는 것'만 모른다(평가를 통째로 버리지 않는다)."""
    a, b = _eval(None), _eval(70_000.0)
    assert a.intrinsic_value == b.intrinsic_value > 0
    assert [(m.model, m.available, m.intrinsic_value_per_share) for m in a.models] == \
           [(m.model, m.available, m.intrinsic_value_per_share) for m in b.models]
    free = {k: v for k, v in b.financial_summary.items() if k not in PRICE_DERIVED_FIN}
    assert {k: a.financial_summary[k] for k in free} == free
    assert free["roe_pct"] and free["eps"] and free["bps"] and free["dps"]      # 공허하지 않다 — 값이 있는 칸을 비교했다


def test_without_a_price_a_company_without_models_keeps_its_zero_gap():
    """적정가 0 의 괴리율 0 은 가격과 무관한 정의다 — 가격이 없어도 같다(가격이 없다고 다른 판정을 지어내지 않는다)."""
    a, b = _eval(None, FS_EMPTY), _eval(70_000.0, FS_EMPTY)
    assert (a.gap_pct, a.verdict) == (b.gap_pct, b.verdict) == (0, "적정")
    assert a.current_price is None


def test_without_a_price_an_unreadable_statement_still_says_no_data():
    """재무를 못 읽으면(운영 · DART 실패) 예전처럼 "데이터 없음" — 가격이 없다는 사실이 그 사유를 덮지 않는다."""
    class _NoFs(_FakeDart):
        def get_financial_statement_full(self, corp_code, bsns_year):
            return None
    uv = ValuationEngine(_NoFs(FS)).evaluate(CODE, None, bsns_year="2025")
    assert (uv.verdict, uv.intrinsic_value, uv.gap_pct, uv.current_price) == ("데이터 없음", 0, 0, None)


# ── 집합과 동작을 묶는다 ─────────────────────────────────────────────────────────────────────────
def test_exactly_the_price_derived_outputs_move_with_the_price():
    """두 가격으로 평가해 ★달라지는 출력★이 정확히 가격 파생 집합이다 — 가격에 기대는 새 출력이 생기면 이 시험이 짚는다
    (그 출력은 가격이 없을 때 미상이 되도록 위 계약에 넣어야 한다)."""
    a, b = _eval(50_000.0), _eval(90_000.0)
    moved_uv = {k for k in ("current_price", "intrinsic_value", "gap_pct", "verdict", "is_mock", "corp_name")
                if getattr(a, k) != getattr(b, k)}
    moved_fin = {k for k in a.financial_summary if a.financial_summary[k] != b.financial_summary[k]}
    assert moved_uv == PRICE_DERIVED_UV
    assert moved_fin == PRICE_DERIVED_FIN
