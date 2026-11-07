"""재무 PIT 배선 — ★고정 시차 상수는 한 곳에만 있다★ (V4 ①)

## 무엇이 문제인가

공시 시차 90/45일은 `src/engine/pit_store.py:32-35` 에 `ANNUAL_LAG_DAYS` ·
`DISCLOSURE_LAG_DAYS` 로 정의돼 있다. 그런데 **백테스트 봉 경로는 그것을 쓰지
않는다** — `condition_strategy._build_pit_base` 가 리터럴로 한 벌 더 들고 있었다:

    lag = 90 if r["reprt"] == "11011" else 45

두 값이 우연히 같아 아무도 몰랐다. ★갈라져도 조용히 갈라진다★ — 스크리너는
바뀌고 백테스트는 안 바뀌는데, 둘 다 "공시 시차" 라고 부른다.

## 이 파일이 거는 계약

`pit_store` 의 상수를 바꾸면 **백테스트 봉이 따라 움직인다.** 저장소에 이미
같은 모양의 짝 단언이 있다 — `test_company_snapshot_builder.py:123-133` 이
`ANNUAL_LAG_DAYS = 120` 으로 몽키패치해 스냅샷 빌더가 상수를 **베끼지 않았음**을
증명한다. 백테스트 경로에는 그 짝이 없었다.

★결합을 만드는 게 아니라 이미 있는 결합을 보이게 하는 것이다.★
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

import src.data.dart_history as DH  # noqa: E402
from src.kis_strategies.condition_strategy import ConditionStrategy  # noqa: E402

TK = "005930"

#: 연간 보고서 2건. 2023 → 100억, 2024 → 140억.
#: ★값이 달라야 한다★ — None→값 이 아니라 **값→값** 이어야 "언제 바뀌나" 를 잰다.
ANNUALS = [
    {"ticker": TK, "year": 2023, "reprt": "11011", "revenue": 1200e8,
     "operating_profit": 130e8, "net_income": 100e8, "total_equity": 600e8,
     "total_liabilities": 320e8, "operating_cf": 110e8, "shares_outstanding": 1e8},
    {"ticker": TK, "year": 2024, "reprt": "11011", "revenue": 1500e8,
     "operating_profit": 170e8, "net_income": 140e8, "total_equity": 750e8,
     "total_liabilities": 350e8, "operating_cf": 150e8, "shares_outstanding": 1e8},
]

#: 3분기 보고서(기간말 9/30) — 분기 상수를 재는 데 쓴다. 연환산 ×(4/3).
Q3_2024 = {"ticker": TK, "year": 2024, "reprt": "11014", "revenue": 900e8,
           "operating_profit": 90e8, "net_income": 60e8, "total_equity": 700e8,
           "total_liabilities": 340e8, "operating_cf": 100e8, "shares_outstanding": 1e8}


def _frame(start: str, end: str) -> pd.DataFrame:
    idx = pd.bdate_range(start, end)
    c = np.linspace(10000, 20000, len(idx))
    return pd.DataFrame({"open": c, "high": c, "low": c, "close": c,
                         "volume": np.full(len(idx), 1000)}, index=idx)


def _at(panel: dict, field: str, day: str):
    """그 날짜(또는 직전 거래일)의 값."""
    s = panel[field]
    upto = s[s.index <= pd.Timestamp(day)]
    return None if upto.empty else upto.iloc[-1]


def _panel(rows, frame):
    return ConditionStrategy(buy_conditions=[], sell_conditions=[])._build_pit_base(TK, frame)


# ═══════════════════════════════════════════════════════════════════════════════
# ① 기본값에서의 경계 — ★먼저 못 박지 않으면 아래 짝이 공허해진다★
# ═══════════════════════════════════════════════════════════════════════════════

def test_the_annual_report_becomes_usable_ninety_days_after_the_period_end(monkeypatch):
    """2024-12-31 + 90일 = 2025-03-31 부터 2024년 값을 쓴다."""
    monkeypatch.setattr(DH, "load_history", lambda tk: list(ANNUALS))
    p = _panel(ANNUALS, _frame("2025-02-01", "2025-05-31"))
    assert p is not None
    assert _at(p, "net_income", "2025-03-28") == pytest.approx(100.0), "이른 봉에 신규 값이 샜다"
    assert _at(p, "net_income", "2025-03-31") == pytest.approx(140.0), "경계에서 안 바뀌었다"


def test_the_quarterly_report_becomes_usable_forty_five_days_after_the_period_end(monkeypatch):
    """2024-09-30 + 45일 = 2024-11-14 부터 3Q 값을 쓴다(연환산 ×4/3)."""
    monkeypatch.setattr(DH, "load_history", lambda tk: [ANNUALS[0], Q3_2024])
    p = _panel(None, _frame("2024-10-01", "2024-12-31"))
    assert p is not None
    assert _at(p, "net_income", "2024-11-13") == pytest.approx(100.0), "이른 봉에 3Q 가 샜다"
    assert _at(p, "net_income", "2024-11-14") == pytest.approx(60.0 * 4 / 3), "경계에서 안 바뀌었다"


# ═══════════════════════════════════════════════════════════════════════════════
# ② ★짝★ — 상수를 베끼지 않았다
# ═══════════════════════════════════════════════════════════════════════════════

def test_the_annual_lag_comes_from_pit_store_not_a_local_literal(monkeypatch):
    """`pit_store.ANNUAL_LAG_DAYS` 를 바꾸면 **백테스트 봉이 따라 움직인다**.

    ★위 ① 만으로는 리터럴 90 을 박은 구현도 통과한다.★
    """
    monkeypatch.setattr(DH, "load_history", lambda tk: list(ANNUALS))
    monkeypatch.setattr("src.engine.pit_store.ANNUAL_LAG_DAYS", 120)
    p = _panel(ANNUALS, _frame("2025-02-01", "2025-05-31"))
    assert p is not None
    assert _at(p, "net_income", "2025-03-31") == pytest.approx(100.0), (
        "상수를 120 으로 바꿨는데 90일 자리에서 바뀌었다 — 리터럴이 남아 있다")
    assert _at(p, "net_income", "2025-04-30") == pytest.approx(140.0), (
        "2024-12-31 + 120일 = 2025-04-30 에서 바뀌지 않았다")


def test_the_quarterly_lag_comes_from_pit_store_not_a_local_literal(monkeypatch):
    """분기 상수도 마찬가지 — 연간만 배선하고 분기를 리터럴로 두는 구현을 배제한다."""
    monkeypatch.setattr(DH, "load_history", lambda tk: [ANNUALS[0], Q3_2024])
    monkeypatch.setattr("src.engine.pit_store.DISCLOSURE_LAG_DAYS", 100)
    p = _panel(None, _frame("2024-10-01", "2025-01-31"))
    assert p is not None
    assert _at(p, "net_income", "2024-11-14") == pytest.approx(100.0), (
        "상수를 100 으로 바꿨는데 45일 자리에서 바뀌었다 — 리터럴이 남아 있다")
    assert _at(p, "net_income", "2025-01-08") == pytest.approx(60.0 * 4 / 3), (
        "2024-09-30 + 100일 = 2025-01-08 에서 바뀌지 않았다")


def test_the_two_lags_are_still_distinct(monkeypatch):
    """★한 상수로 뭉뚱그리지 않았다★ 연간만 바꿨을 때 분기가 따라가면 안 된다."""
    monkeypatch.setattr(DH, "load_history", lambda tk: [ANNUALS[0], Q3_2024])
    monkeypatch.setattr("src.engine.pit_store.ANNUAL_LAG_DAYS", 300)
    p = _panel(None, _frame("2024-10-01", "2024-12-31"))
    assert p is not None
    assert _at(p, "net_income", "2024-11-14") == pytest.approx(60.0 * 4 / 3), (
        "연간 상수를 바꿨는데 분기 가용일이 따라 움직였다 — 두 상수가 하나로 뭉쳤다")


# ═══════════════════════════════════════════════════════════════════════════════
# ③ 실측 접수일 ★기간 단위 병합★ — 전환이 아니다 (V4 ②)
#
# `financials_vintages` 는 V2 이후로만 쌓인다. 사용자 DB 는 지금 **비어 있고**,
# `existing_keys` 가 3-튜플이라 이미 적재된 기간은 재조회되지 않는다. 그래서
# 빈티지로 통째로 갈아타면 PIT 재무 조건이 전부 NaN 이 되어 백테스트가 조용히
# 퇴화한다. ⇒ **기간마다** 실측이 있으면 실측, 없으면 라벨 붙은 추정.
#
# ★날짜만이 아니라 값도 그 빈티지의 것을 쓴다★ `financials_history` 는 정정이
# 원본을 덮은 **뒤**의 값이라, 날짜만 실측으로 바꾸고 값을 거기서 가져오면
# 개정본이 과거 봉에 그대로 들어간다 — 막으려던 룩어헤드가 다른 문으로 돌아온다.
# ═══════════════════════════════════════════════════════════════════════════════

from src.engine.pit_store import FILING_SAME_DAY_GUARD_DAYS  # noqa: E402
from src.kis_strategies.fundamentals_pit_context import (  # noqa: E402
    FundamentalsPitContext,
)


def _vint(*, year: int, reprt: str, rcept_no: str, rcept_dt: str, net_income: float,
          revenue: float = 1500e8) -> dict:
    """`load_vintages` 가 돌려주는 행 모양 (V3) — `_FIELDS` + 축 + 출처."""
    month = {"11013": 3, "11012": 6, "11014": 9, "11011": 12}[reprt]
    return {"revenue": revenue, "operating_profit": 170e8, "net_income": net_income,
            "gross_profit": None, "total_assets": 1100e8, "total_liabilities": 350e8,
            "total_equity": 750e8, "current_assets": None, "current_liabilities": None,
            "operating_cf": 150e8, "capex": None, "shares_outstanding": 1e8, "dps": None,
            "year": year, "reprt": reprt, "month": month, "seq": year * 12 + month,
            "rcept_no": rcept_no, "rcept_dt": rcept_dt}


def _wire(monkeypatch, *, vintages, reason=None, history=None):
    """`load_history` + `load_vintages` 를 세팅하고 (전략, ctx) 를 돌려준다."""
    # ★`history or ANNUALS` 로 쓰면 안 된다★ 빈 리스트가 falsy 라 `history=[]`
    # (적재 없음 검사)가 조용히 기본값으로 되돌아간다 — 실제로 그랬다.
    monkeypatch.setattr(DH, "load_history",
                        lambda tk: list(ANNUALS if history is None else history))
    monkeypatch.setattr(DH, "load_vintages", lambda tk, engine=None: (vintages, reason))
    s = ConditionStrategy(buy_conditions=[], sell_conditions=[])
    ctx = FundamentalsPitContext()
    s.set_fund_ctx(ctx)
    return s, ctx


#: 2024 연간의 **실측** 접수일 — 추정일(2025-03-31)보다 이르다. 값도 다르다(120 ≠ 140).
#: 2025-03-14(금) 접수 + 당일 가드 1일 = 2025-03-15(토) → 첫 사용 봉은 2025-03-17(월).
V2024_EARLY = dict(year=2024, reprt="11011", rcept_no="20250314000777",
                   rcept_dt="2025-03-14", net_income=120e8)
#: ★늦은 공시★ — 추정일보다 늦다. 지금까지 이 구간이 **실제 룩어헤드**였다.
#: 2025-05-15(목) + 1일 = 2025-05-16(금) 부터.
V2024_LATE = dict(year=2024, reprt="11011", rcept_no="20250515000777",
                  rcept_dt="2025-05-15", net_income=120e8)


def test_a_measured_filing_date_replaces_the_estimate(monkeypatch):
    """★알맹이★ 빈티지가 있으면 **그 접수일부터**(당일 가드 뒤) 그 값을 쓴다."""
    s, _ = _wire(monkeypatch, vintages=[_vint(**V2024_EARLY)])
    p = s._build_pit_base(TK, _frame("2025-02-01", "2025-05-31"))
    assert p is not None
    assert _at(p, "net_income", "2025-03-14") == pytest.approx(100.0), "접수 전/당일에 값이 샜다"
    assert _at(p, "net_income", "2025-03-17") == pytest.approx(120.0), "실측 접수일 뒤에 안 바뀌었다"


def test_a_filing_is_not_usable_on_the_day_it_was_filed(monkeypatch):
    """★당일 가드★ DART 는 18시까지 접수를 받고 장은 15:30 에 닫는다.

    접수 **시각**을 모르므로(★미상★) 당일 봉에는 쓰지 않는다. 이 여유는 상수로
    이름이 있고 결과에도 실린다 — 몰래 하루를 빼면 "왜 하루 늦나" 를 아무도 못 찾는다.
    V3 의 `vintages_as_of` 가 *"안전 여유는 호출자가 보이는 자리에서 준다"* 라고
    적어 뒀고, 이 함수가 그 호출자다.
    """
    assert FILING_SAME_DAY_GUARD_DAYS == 1
    s, _ = _wire(monkeypatch, vintages=[_vint(**V2024_EARLY)])
    p = s._build_pit_base(TK, _frame("2025-02-01", "2025-05-31"))
    assert _at(p, "net_income", "2025-03-14") == pytest.approx(100.0), (
        "접수 당일 봉에서 값을 썼다 — 장마감 후 접수분이면 룩어헤드다")


def test_without_a_vintage_the_static_estimate_still_works(monkeypatch):
    """★짝 — 이것이 없으면 빈 빈티지 테이블에서 백테스트가 통째로 퇴화한다★

    사용자 DB 의 빈티지 테이블은 지금 비어 있다. 그 상태에서 동작이 지금과
    똑같아야 한다.
    """
    s, ctx = _wire(monkeypatch, vintages=[])
    p = s._build_pit_base(TK, _frame("2025-02-01", "2025-05-31"))
    assert p is not None
    assert _at(p, "net_income", "2025-03-28") == pytest.approx(100.0)
    assert _at(p, "net_income", "2025-03-31") == pytest.approx(140.0), "추정 경로가 죽었다"
    c = ctx.counts()
    assert c["measured"] == 0 and c["estimated"] == 2 and c["unknown"] == 0, c


def test_one_ticker_can_hold_a_measured_and_an_estimated_period_at_once(monkeypatch):
    """★전환이 아니라 병합이다★ 한 종목 안에서 기간마다 다르게 판정한다.

    "전부 실측이어야 실측을 쓴다" 구현을 배제한다.
    """
    s, ctx = _wire(monkeypatch, vintages=[_vint(**V2024_EARLY)])   # 2024 만 실측, 2023 은 추정
    p = s._build_pit_base(TK, _frame("2024-02-01", "2025-05-31"))
    # 2023 연간: 2023-12-31 + 90일 = 2024-03-30(토) → 첫 사용 봉은 2024-04-01(월)
    assert pd.isna(_at(p, "net_income", "2024-03-29")), "추정일 전에 값이 샜다"
    assert _at(p, "net_income", "2024-04-01") == pytest.approx(100.0), "2023 추정이 안 들어왔다"
    assert _at(p, "net_income", "2025-03-17") == pytest.approx(120.0), "2024 실측이 안 들어왔다"
    c = ctx.counts()
    assert c["measured"] == 1 and c["estimated"] == 1, c


def test_a_late_filing_removes_a_real_look_ahead(monkeypatch):
    """★이 작업의 경제적 가치가 여기 있다★

    접수일이 추정일(기간말+90일)보다 **늦으면**, 지금까지 백테스트는 아직
    공표되지 않은 재무를 6주 동안 보고 있었다. 실측이 그것을 없앤다.
    """
    s, _ = _wire(monkeypatch, vintages=[_vint(**V2024_LATE)])
    p = s._build_pit_base(TK, _frame("2025-02-01", "2025-06-30"))
    assert p is not None
    assert _at(p, "net_income", "2025-03-31") == pytest.approx(100.0), (
        "추정일에 값이 들어왔다 — 아직 공표되지 않은 재무다(룩어헤드)")
    assert _at(p, "net_income", "2025-05-15") == pytest.approx(100.0)
    assert _at(p, "net_income", "2025-05-16") == pytest.approx(120.0), "실측 접수일 뒤에 안 들어왔다"


def test_the_overwrite_table_value_does_not_leak_at_the_estimated_date(monkeypatch):
    """★값 축도 함께 고친다★ `financials_history` 는 정정이 원본을 덮은 **뒤**의 값이다.

    빈티지가 있는 기간에 history 행까지 넣으면, 추정일에 **현재 개정본**이 들어온다 —
    막으려던 룩어헤드가 다른 문으로 되돌아온다.
    """
    s, _ = _wire(monkeypatch, vintages=[_vint(**V2024_EARLY)])
    p = s._build_pit_base(TK, _frame("2025-02-01", "2025-06-30"))
    assert _at(p, "net_income", "2025-06-30") == pytest.approx(120.0), (
        "추정일 이후 history 값(140)이 빈티지 값(120)을 덮었다")


def test_a_restatement_updates_the_value_from_its_own_filing_date(monkeypatch):
    """같은 기간의 빈티지 **둘**이 각자의 접수일부터 값을 준다 — step-forward 그대로.

    ★기간당 하나만 고르지 않는 이유★ 최초 공시만 쓰면 정정을 영원히 못 보고,
    최종 정정만 쓰면 정정 전 봉이 **미래의 값**을 본다. 각자의 접수일에 각자의
    값을 넣는 것이 실제로 일어난 일이다.
    """
    s, _ = _wire(monkeypatch, vintages=[
        _vint(**V2024_EARLY),
        _vint(year=2024, reprt="11011", rcept_no="20250620000999",
              rcept_dt="2025-06-20", net_income=90e8),
    ])
    p = s._build_pit_base(TK, _frame("2025-02-01", "2025-08-31"))
    assert _at(p, "net_income", "2025-03-17") == pytest.approx(120.0), "원본이 안 들어왔다"
    assert _at(p, "net_income", "2025-06-20") == pytest.approx(120.0), "정정본이 일찍 샜다"
    assert _at(p, "net_income", "2025-06-23") == pytest.approx(90.0), "정정본이 안 들어왔다"


def test_a_late_filing_of_an_old_period_does_not_overwrite_a_newer_one(monkeypatch):
    """★실측 날짜가 만드는 새 위험 — 순서 역전★

    step-forward 루프는 `avail` 순으로 **무조건 덮어쓴다**. 추정 시차에서는
    `avail` 순서가 곧 기간 순서라(12/31+90 < 3/31+45 < …) 우연히 안전했다.
    실측 접수일에서는 아니다 — 늦게 낸 **과거** 보고서가 최신 분기 값을 덮는다.
    그러면 패널이 조용히 낡고, 영원히 데이터 버그처럼 보인다.

    ★이 가드는 추정만 쓸 때는 아무 일도 하지 않는다★(위 테스트들이 그 증거).
    """
    hist = [
        {"ticker": TK, "year": 2023, "reprt": "11011", "revenue": 1200e8,
         "operating_profit": 130e8, "net_income": 100e8, "total_equity": 600e8,
         "total_liabilities": 320e8, "operating_cf": 110e8, "shares_outstanding": 1e8},
        {"ticker": TK, "year": 2024, "reprt": "11013", "revenue": 400e8,
         "operating_profit": 40e8, "net_income": 30e8, "total_equity": 700e8,
         "total_liabilities": 330e8, "operating_cf": 50e8, "shares_outstanding": 1e8},
    ]
    s, _ = _wire(monkeypatch, history=hist, vintages=[
        # 2024 1Q — 정시 접수
        _vint(year=2024, reprt="11013", rcept_no="20240510000111",
              rcept_dt="2024-05-10", net_income=30e8),
        # ★2023 연간을 1년 넘게 늦게 냈다★ — avail 순서로는 1Q 뒤에 온다
        _vint(year=2023, reprt="11011", rcept_no="20240801000222",
              rcept_dt="2024-08-01", net_income=100e8),
    ])
    p = s._build_pit_base(TK, _frame("2024-04-01", "2024-12-31"))
    assert _at(p, "net_income", "2024-05-13") == pytest.approx(30.0 * 4), "1Q 가 안 들어왔다"
    assert _at(p, "net_income", "2024-08-05") == pytest.approx(30.0 * 4), (
        "늦게 접수된 2023 연간이 더 최신인 2024 1Q 를 덮었다")


def test_a_vintage_only_period_is_used_too(monkeypatch):
    """`financials_history` 에 없고 빈티지에만 있는 기간도 쓴다 — 실재하는 지식이다."""
    s, ctx = _wire(monkeypatch, history=[ANNUALS[0]], vintages=[_vint(**V2024_EARLY)])
    p = s._build_pit_base(TK, _frame("2025-02-01", "2025-05-31"))
    assert _at(p, "net_income", "2025-03-17") == pytest.approx(120.0), "빈티지 전용 기간이 버려졌다"
    assert ctx.counts()["measured"] == 1, ctx.counts()


def test_an_unreadable_vintage_table_is_unknown_not_estimated(monkeypatch):
    """★미상 ≠ 추정★ 조회 실패는 추정으로 내려가되 **다른 칸**에 센다.

    섞으면 DB 가 잠깐 죽었을 때 추정 비율이 정상으로 보이고, 아무도 모른다.
    """
    s, ctx = _wire(monkeypatch, vintages=None, reason="financials_vintages 를 읽지 못했습니다: X")
    p = s._build_pit_base(TK, _frame("2025-02-01", "2025-05-31"))
    assert p is not None, "조회 실패가 패널을 통째로 죽였다"
    assert _at(p, "net_income", "2025-03-31") == pytest.approx(140.0), "추정으로 안 내려갔다"
    c = ctx.counts()
    assert c["unknown"] == 2 and c["estimated"] == 0, c
    assert any("읽지 못했" in v["reason"] for v in ctx.reasons().values()), ctx.reasons()


def test_a_context_that_blows_up_degrades_to_estimates_not_to_a_missing_panel(monkeypatch):
    """★조용한 무력화를 막는다★ `_pit_fund_series:889` 가 예외를 통째로 삼킨다.

    거기서 삼켜지면 패널이 `None` 이 되고 **PIT 재무 조건이 통째로 건너뛰어진다** —
    화면에는 아무 표시가 없다. 그러니 이 층에서 예외가 새어 나가면 안 된다.
    """
    monkeypatch.setattr(DH, "load_history", lambda tk: list(ANNUALS))
    s = ConditionStrategy(buy_conditions=[], sell_conditions=[])

    class _Exploding:
        """★메서드 이름을 하드코딩하지 않는다★ 어떤 접근이든 터진다 — 구현이
        컨텍스트를 어떻게 부르든 이 테스트가 유효하다."""

        def __getattr__(self, name):
            raise RuntimeError(f"의도적 폭발: {name}")

    s.set_fund_ctx(_Exploding())
    p = s._build_pit_base(TK, _frame("2025-02-01", "2025-05-31"))
    assert p is not None, "컨텍스트가 터지자 PIT 재무가 통째로 사라졌다"
    assert _at(p, "net_income", "2025-03-31") == pytest.approx(140.0), "추정으로 안 내려갔다"


def test_a_ticker_is_counted_once_even_when_both_paths_build_it(monkeypatch):
    """★두 경로가 같은 종목을 두 번 세지 않는다★

    `_build_pit_base` 는 `(종목, len(df))` 로 캐시되고 벡터화 경로와 per-bar
    폴백 경로가 **서로 다른 프레임**을 넘긴다
    (`test_pit_fundamentals_path_parity.py` 가 그 사고를 기록한다).
    """
    s, ctx = _wire(monkeypatch, vintages=[_vint(**V2024_EARLY)])
    s._build_pit_base(TK, _frame("2025-02-01", "2025-05-31"))
    s._build_pit_base(TK, _frame("2025-02-01", "2025-04-30"))   # 길이가 다른 프레임
    s._build_pit_base(TK, _frame("2025-01-01", "2025-05-31"))
    c = ctx.counts()
    assert c["measured"] == 1 and c["estimated"] == 1, f"같은 종목을 여러 번 셌다: {c}"


def test_the_vintages_are_read_once_per_ticker(monkeypatch):
    """★프레임마다 재조회하지 않는다★ 빈티지는 프레임 모양과 무관하다."""
    calls = {"n": 0}

    def _lv(tk, engine=None):
        calls["n"] += 1
        return [_vint(**V2024_EARLY)], None

    monkeypatch.setattr(DH, "load_history", lambda tk: list(ANNUALS))
    monkeypatch.setattr(DH, "load_vintages", _lv)
    s = ConditionStrategy(buy_conditions=[], sell_conditions=[])
    s.set_fund_ctx(FundamentalsPitContext())
    for span in (("2025-02-01", "2025-05-31"), ("2025-02-01", "2025-04-30"),
                 ("2025-01-01", "2025-05-31")):
        s._build_pit_base(TK, _frame(*span))
    assert calls["n"] == 1, f"종목 하나에 빈티지를 {calls['n']}회 읽었다"


def test_a_ticker_with_no_financials_is_a_reason_not_an_absence(monkeypatch):
    """적재가 없어 조건이 건너뛰어진 사실을 센다 — 화면에 아무 표시가 없던 자리."""
    s, ctx = _wire(monkeypatch, history=[], vintages=[])
    assert s._build_pit_base(TK, _frame("2025-02-01", "2025-05-31")) is None
    assert ctx.ticker_counts()["no_financials"] == 1, ctx.ticker_counts()


def test_without_a_context_the_panel_is_exactly_todays_estimate(monkeypatch):
    """★골든★ ctx 가 없으면(스크리너·실시간) 오늘 동작 그대로 — 조회조차 하지 않는다."""
    calls = {"n": 0}

    def _lv(tk, engine=None):
        calls["n"] += 1
        return [_vint(**V2024_EARLY)], None

    monkeypatch.setattr(DH, "load_history", lambda tk: list(ANNUALS))
    monkeypatch.setattr(DH, "load_vintages", _lv)
    s = ConditionStrategy(buy_conditions=[], sell_conditions=[])
    assert s._fund_ctx is None
    p = s._build_pit_base(TK, _frame("2025-02-01", "2025-05-31"))
    assert _at(p, "net_income", "2025-03-31") == pytest.approx(140.0), "ctx 없이 동작이 바뀌었다"
    assert calls["n"] == 0, "ctx 도 없는데 빈티지를 읽었다 — 스크리너에 쿼리가 늘어난다"


def test_both_frame_shapes_agree_with_measured_dates(monkeypatch):
    """★경로 동등성★ 실측을 넣었다고 벡터화/per-bar 가 갈라지면 안 된다."""
    monkeypatch.setattr(DH, "load_history", lambda tk: list(ANNUALS))
    monkeypatch.setattr(DH, "load_vintages",
                        lambda tk, engine=None: ([_vint(**V2024_EARLY)], None))
    vec = _frame("2025-02-01", "2025-05-31")
    pb = pd.DataFrame({"date": vec.index.strftime("%Y%m%d").values,
                       "open": vec["open"].values, "high": vec["high"].values,
                       "low": vec["low"].values, "close": vec["close"].values,
                       "volume": vec["volume"].values})
    assert isinstance(pb.index, pd.RangeIndex), "전제가 깨지면 이 테스트는 공허하다"
    a = ConditionStrategy(buy_conditions=[], sell_conditions=[])
    b = ConditionStrategy(buy_conditions=[], sell_conditions=[])
    a.set_fund_ctx(FundamentalsPitContext())
    b.set_fund_ctx(FundamentalsPitContext())
    pa, pb_ = a._build_pit_base(TK, vec), b._build_pit_base(TK, pb)
    assert np.allclose(pa["net_income"].values, pb_["net_income"].values, equal_nan=True), (
        "두 경로가 다른 답을 낸다")


def test_two_reports_filed_on_the_same_day_let_the_newer_period_win(monkeypatch):
    """★실측 날짜에서만 생기는 경우 — 같은 날 두 보고서★

    추정 시차에서는 `avail` 이 겹치지 않는다(12/31+90 ≠ 3/31+45). 실측에서는
    회사가 밀린 사업보고서와 분기보고서를 **같은 날** 낼 수 있고, 그러면
    `avail` 이 정확히 겹쳐 답이 정렬 순서에 달린다.

    ★이 계약은 `(avail, seq)` 정렬과 `avail` 단독 정렬 **둘 다** 만족한다★ —
    키 합집합을 `sorted()` 로 도는 덕에 삽입 순서가 이미 기간 순서이기 때문이다.
    그래서 "정렬 키에서 seq 를 뺀다" 변이는 **동치 변이**이고 이 테스트가 죽이지
    못한다. 그래도 이 동작 자체는 계약이므로 못 박는다 — 삽입 순서가 바뀌면
    여기가 먼저 깨진다.
    """
    hist = [
        {"ticker": TK, "year": 2023, "reprt": "11011", "revenue": 1200e8,
         "operating_profit": 130e8, "net_income": 100e8, "total_equity": 600e8,
         "total_liabilities": 320e8, "operating_cf": 110e8, "shares_outstanding": 1e8},
        {"ticker": TK, "year": 2024, "reprt": "11013", "revenue": 400e8,
         "operating_profit": 40e8, "net_income": 30e8, "total_equity": 700e8,
         "total_liabilities": 330e8, "operating_cf": 50e8, "shares_outstanding": 1e8},
    ]
    s, _ = _wire(monkeypatch, history=hist, vintages=[
        _vint(year=2023, reprt="11011", rcept_no="20240510000111",
              rcept_dt="2024-05-10", net_income=100e8),
        _vint(year=2024, reprt="11013", rcept_no="20240510000222",
              rcept_dt="2024-05-10", net_income=30e8),
    ])
    p = s._build_pit_base(TK, _frame("2024-04-01", "2024-12-31"))
    assert _at(p, "net_income", "2024-05-20") == pytest.approx(30.0 * 4), (
        "같은 날 접수에서 더 오래된 기간(2023 연간)이 이겼다")
