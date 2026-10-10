"""공시 시가배당률 + ★거짓 미지원 사유 제거★
==============================================================================
감사: `docs/specs/2026-08-27-capability-lineage-audit.md` §A.5 · 선행: `d5d9766`

## 이 파일이 막는 것

### ① 받아 놓고 버리는 필드

`alotMatter` 는 `{dps, payout_pct, yield_pct}` 를 준다. 앞의 둘은 배선돼 있었지만
`yield_pct`(**공시 현금배당수익률**)는 파싱해 놓고 **아무도 읽지 않았다** — 그래서
그것을 기다리던 토큰 "배당시점배당수익률" 이 닫혀 있었다.

### ② ★`dividend_yield` 를 덮는 것★ — 가장 위험하다

    FinancialStatement.dividend_yield      = dps / ★오늘 주가★  (compute_ratios 산출)
    FinancialStatement.disclosed_dividend_yield = alotMatter 공시값 (★배당 시점 기준★)

**다른 값이다.** 과거를 분석하면서 `dps / 오늘 주가` 를 쓰면 오늘 가격이 과거로
새어 든다. 덮으면 기존 소비자가 조용히 다른 정의를 받는다 — 더하고, 대체하지 않는다.

### ③ 거짓 미지원 사유

```
REASON_DIVDETAIL = "배당·자사주 상세 — DART 배당공시(alotMatter) 미연동(다음 단계)"
```

★`alotMatter` 는 배선돼 있다.★ 그리고 이 한 문장이 11개 토큰을 덮고 있었는데
실제 원인은 **다섯 가지로 서로 달랐다**. 넷은 **이미 supported** 라 항목 자체가
죽어 있었다 — 지금은 `token_support()` 가 걸러 안 보이지만, 그 팩터가 mock 으로
내려가는 날 **사용자에게 거짓말이 뜬다**.
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402

import src.kis_strategies.factor_tokens as ft  # noqa: E402
from src.data.dart_client import DARTClient  # noqa: E402

_ALOT = {
    "status": "000", "message": "정상",
    "list": [
        {"se": "주당 현금배당금(원)", "stock_knd": "보통주", "thstrm": "1,444"},
        {"se": "현금배당성향(%)", "stock_knd": "", "thstrm": "25.0"},
        {"se": "현금배당수익률(%)", "stock_knd": "보통주", "thstrm": "2.10"},
    ],
}

_FSALL = {"status": "000", "list": [
    {"account_nm": "매출액", "sj_div": "IS", "thstrm_amount": "1,000,000"},
    {"account_nm": "당기순이익", "sj_div": "IS", "thstrm_amount": "100,000"},
    {"account_nm": "자산총계", "sj_div": "BS", "thstrm_amount": "3,000,000"},
    {"account_nm": "부채총계", "sj_div": "BS", "thstrm_amount": "1,000,000"},
    {"account_nm": "자본총계", "sj_div": "BS", "thstrm_amount": "2,000,000"},
]}


def _client(monkeypatch, alot=_ALOT):
    c = DARTClient(api_key="x" * 20)

    def fake_get(endpoint, params):
        if "fnlttSinglAcntAll" in endpoint:
            return _FSALL
        if "alotMatter" in endpoint:
            return alot
        return None

    monkeypatch.setattr(c, "_get", fake_get)
    return c


# ══════════════════════════════════════════════════════════════════════════
# 1) ★버려지던 필드가 실린다★
# ══════════════════════════════════════════════════════════════════════════
def test_disclosed_yield_reaches_the_statement(monkeypatch):
    """D1 — `alotMatter.yield_pct` 가 `FinancialStatement` 에 도달한다."""
    fs = _client(monkeypatch).get_financial_statement_full("00126380", "2025")
    assert fs is not None
    assert fs.disclosed_dividend_yield == pytest.approx(2.10)


def test_dps_injection_still_works(monkeypatch):
    """D2 ★짝(회귀)★ — 새 필드를 넣다가 기존 주입을 깨지 않았다."""
    fs = _client(monkeypatch).get_financial_statement_full("00126380", "2025")
    assert fs.dps == pytest.approx(1444.0)


def test_disclosed_yield_does_not_overwrite_the_computed_one(monkeypatch):
    """D3 ★가장 위험한 변이를 막는다★

    `dividend_yield` 는 `dps / 현재가`, `disclosed_dividend_yield` 는 공시 시점
    기준이다. 덮으면 기존 소비자가 조용히 다른 정의를 받는다.
    """
    fs = _client(monkeypatch).get_financial_statement_full("00126380", "2025")

    # ★반환된 그대로를 본다★ 여기서 `compute_ratios` 를 먼저 부르면 그 호출이
    # `dividend_yield` 를 **다시 계산해** 덮어쓰는 변이를 지워 버린다 — 실제로
    # 첫 판이 그래서 변이를 놓쳤다(테스트가 검사하려던 필드를 스스로 덮었다).
    # 가격을 안 줬으므로 `compute_ratios()` 는 `dividend_yield` 를 채우지 않는다.
    assert fs.dividend_yield is None, \
        f"공시값이 계산 필드로 새어 들어갔다: {fs.dividend_yield}"
    assert fs.disclosed_dividend_yield == pytest.approx(2.10)

    # 가격을 주면 그때 비로소 계산된다 — 그리고 공시값과 **다른 값**이다.
    fs.compute_ratios(current_price=100_000.0)     # dps/가격 = 1.444%
    assert fs.dividend_yield == pytest.approx(1.444, abs=1e-3)
    assert fs.disclosed_dividend_yield == pytest.approx(2.10), "공시값이 덮였다"
    assert fs.dividend_yield != fs.disclosed_dividend_yield


def test_a_missing_disclosed_yield_stays_none(monkeypatch):
    """★공시가 없으면 비운다★ — 계산값으로 메우지 않는다."""
    alot = {"status": "000", "list": [
        {"se": "주당 현금배당금(원)", "stock_knd": "보통주", "thstrm": "1,444"}]}
    fs = _client(monkeypatch, alot).get_financial_statement_full("00126380", "2025")
    assert fs.disclosed_dividend_yield is None
    assert fs.dps == pytest.approx(1444.0), "전제: dps 는 들어왔다"


def test_the_extended_factor_is_declared_real_capable():
    """D4 뒷받침 — 합성 전용으로 남으면 토큰이 열리지 않는다."""
    from src.data.extended_factors_store import MOCK_ONLY_IDS, REAL_CAPABLE_IDS

    assert "div_at_record" in REAL_CAPABLE_IDS
    assert "div_at_record" not in MOCK_ONLY_IDS


def test_the_real_hook_does_nothing_without_a_key(monkeypatch):
    """D12 — ★키가 없으면 합성값을 만들지 않는다★ (`mock_gate` 원칙)"""
    from src.data.extended_factors_store import ExtendedFactorsStore

    monkeypatch.delenv("DART_API_KEY", raising=False)
    assert ExtendedFactorsStore.get_default()._real_dividend("005930") == {}


# ══════════════════════════════════════════════════════════════════════════
# 2) 토큰 — 하나를 열되 전부 열지는 않는다
# ══════════════════════════════════════════════════════════════════════════
def test_the_disclosure_yield_token_is_open():
    """D4 — 데이터가 이미 있으므로 열린다."""
    assert "배당시점배당수익률" in ft.token_support()["supported"]


def test_treasury_tokens_remain_closed():
    """D5 ★짝★ — 없으면 "전부 열기" 구현으로도 D4 가 통과한다.

    자사주는 `alotMatter` 에 **아예 없다** — 열 근거가 없다.
    """
    support = ft.token_support()
    for t in ("자사주보유비율", "자사주소각횟수", "자사주소각비율"):
        assert t not in support["supported"], f"{t} 를 근거 없이 열었다"
        assert t in support["unsupported"]


# ══════════════════════════════════════════════════════════════════════════
# 3) ★사유가 사실이어야 한다★
# ══════════════════════════════════════════════════════════════════════════
def test_no_reason_claims_alotmatter_is_unwired():
    """D6 — ★거짓 문장 제거★ `alotMatter` 는 배선돼 있다."""
    liars = {k: v for k, v in ft.UNSUPPORTED_REASONS.items()
             if "alotMatter 미연동" in v}
    assert liars == {}, f"거짓 사유가 남아 있다: {liars}"


#: 이번 단계가 정리한 주주환원 토큰들. ★범위를 이름으로 못 박는다★
_SHAREHOLDER_TOKENS = (
    "주당배당금", "배당횟수", "배당시점배당수익률", "FCF배당성향",
    "배당금총액증가율", "주당배당금증가율", "자사주보유비율", "자사주소각횟수",
    "자사주소각비율", "투자자주가수익률", "총수익률",
)


def test_no_supported_shareholder_token_carries_an_unsupported_reason():
    """D7 — 죽은 항목을 남기지 않는다(이번 범위: 주주환원 11종).

    지금은 `token_support()` 가 걸러서 안 보이지만, 그 팩터가 mock 으로 내려가는
    날 **사용자에게 거짓 사유가 뜬다**.
    """
    supported = ft.token_support()["supported"]
    dead = sorted(t for t in _SHAREHOLDER_TOKENS
                  if t in supported and t in ft.UNSUPPORTED_REASONS)
    assert dead == [], f"이미 지원되는데 사유가 남아 있다: {dead}"


def test_the_dead_reason_problem_is_wider_than_this_phase():
    """★상한이 아니라 **0** 이다★ — 기록하던 것을 실제로 고쳤다.

    이 테스트는 원래 결함을 고치지 않고 **기록**했다. D7 을 저장소 전체로 돌려
    보니 주주환원 밖에서 17개가 더 나왔고(`POR`·`매출원가율`·`직원급여총액` 등),
    당시 범위가 주주환원 11종뿐이라 상한 `<= 17` 로 증가만 막아 뒀다.

    그 17개를 실측해 보니 **두 종류**였다 — 15개는 `_derive` 가 실파생을 붙였는데
    사유만 남은 죽은 항목이었고(제거), 둘(`남자직원수`·`여자직원수`)은 반대로
    ★능력 선언이 과장된 경우★라 `REAL_CAPABLE_IDS` 에서 내려 진짜 미지원이 됐다.
    그래서 이제 죽은 항목은 **하나도 없어야 한다**.

    ★짝은 `test_unsupported_tokens_still_carry_reasons`★ — 이 단언만 있으면
    "사유를 전부 지운다" 는 구현으로도 통과한다.
    """
    supported = ft.token_support()["supported"]
    dead = sorted(k for k in ft.UNSUPPORTED_REASONS
                  if k in supported and k not in _SHAREHOLDER_TOKENS)
    assert dead == [], f"이미 지원되는데 사유가 남아 있다: {dead}"


def test_treasury_reason_names_the_actual_source():
    """D8 — 사유가 **자기주식 공시**를 지목한다."""
    r = ft.UNSUPPORTED_REASONS["자사주보유비율"]
    assert r == ft.REASON_TREASURY
    assert "자기주식" in r and "alotMatter" in r


def test_dividend_count_reason_names_quarterly_reports():
    """D9 — 사유가 **분기 보고서 다중 조회**를 지목한다."""
    r = ft.UNSUPPORTED_REASONS["배당횟수"]
    assert r == ft.REASON_DIVPERIOD
    assert "11012" in r


def test_dps_growth_reason_points_at_the_substitute():
    """D10 — 이미 지원되는 "배당성장률" 과 같은 양이므로 대체를 권한다."""
    assert ft.UNSUPPORTED_REASONS["주당배당금증가율"] == ft.REASON_DERIVE
    assert "배당성장률" in ft.token_support()["supported"]


def test_total_amount_growth_reason_names_the_record_date():
    """배당금총액증가율 — 진짜 공백은 배당 기준일이다."""
    r = ft.UNSUPPORTED_REASONS["배당금총액증가율"]
    assert r == ft.REASON_DIVDATE
    assert "기준일" in r


def test_each_remaining_reason_is_distinct():
    """★하나의 문장으로 다시 뭉치지 않는다★ 원인이 다섯 가지였다."""
    keys = ("자사주보유비율", "배당횟수", "배당금총액증가율", "주당배당금증가율")
    reasons = {ft.UNSUPPORTED_REASONS[k] for k in keys}
    assert len(reasons) == 4, f"사유가 뭉쳐졌다: {reasons}"


# ══════════════════════════════════════════════════════════════════════════
# 4) ★정리가 기능을 지우지 않았다★
# ══════════════════════════════════════════════════════════════════════════
def test_previously_supported_tokens_are_all_still_supported():
    """D11 — 사유를 지우다가 지원 토큰을 줄이지 않았다.

    `d5d9766` 시점의 배당·주주환원 관련 지원 토큰을 이름으로 고정한다.
    """
    supported = ft.token_support()["supported"]
    for t in ("주당배당금", "FCF배당성향", "투자자주가수익률", "총수익률",
              "배당성장률", "배당수익률", "배당성향"):
        assert t in supported, f"{t} 지원이 사라졌다"


def test_support_count_floor_is_kept():
    """기존 계약(`test_factor_tokens.py`) 과 같은 하한을 여기서도 지킨다."""
    assert len(ft.token_support()["supported"]) >= 80
