"""행 → `FinancialStatement` 변환기를 ★한 벌만 둔다★ + `statement_as_of` (U1·U2)

## 왜 공용화하나

`fundamentals_store._fs_from_history()` 안에 이미 그 매핑이 있다 — 13개 필드
복사 + 회계 항등식 보완(자본=자산-부채). as-of 경로가 같은 매핑을 다시 쓰면
**두 벌이 갈라진다**. 이 저장소가 이미 두 번 값을 치른 실수이고,
`load_statement` 의 독스트링이 그것을 이름까지 적어 뒀다
(*"같은 산수를 두 곳에 두면 반드시 갈라지고 갈라져도 타입 에러가 나지 않는다"*).

## `statement_as_of` 가 지키는 것

    (None, 사유)  못 읽었다 · 빈티지가 없다 · 연간 보고서가 없다  ← ★셋이 다르다★
    (fs, None)    그 시점 최신 연간 빈티지로 만든 재무

★`financials_history` 로 폴백하지 않는다★ — V3 가 세운 계약 그대로다. 폴백하면
오늘 값(정정이 원본을 덮은 표)이 과거 시점 답으로 위장한다.
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from src.data import dart_history as dh  # noqa: E402
from src.data.dart_client import FinancialStatement  # noqa: E402

TICKER = "005930"


@pytest.fixture
def eng():
    e = create_engine("sqlite://", connect_args={"check_same_thread": False},
                      poolclass=StaticPool)
    dh.ensure_history_table(e)
    assert dh.ensure_vintage_table(e), "빈티지 테이블을 만들지 못했다"
    dh._VINTAGE_SKIPPED["no_rcept"] = 0
    yield e
    e.dispose()


def _fs(*, rcept_no: str, rcept_dt: str, revenue: float, year: str = "2024",
        reprt: str = "11011", equity: float = 500.0) -> FinancialStatement:
    fs = FinancialStatement(corp_code="00126380", corp_name="삼성전자",
                            bsns_year=year, reprt_code=reprt)
    fs.revenue, fs.net_income = revenue, 100.0
    fs.total_assets, fs.total_liabilities, fs.total_equity = 2000.0, 1500.0, equity
    fs.shares_outstanding, fs.dps = 10.0, 30.0
    fs.rcept_no, fs.rcept_dt = rcept_no, rcept_dt
    return fs


ORIGINAL = dict(rcept_no="20250314000777", rcept_dt="2025-03-14", revenue=1000.0)
RESTATED = dict(rcept_no="20250620000999", rcept_dt="2025-06-20", revenue=900.0)


# ═══════════════════════════════════════════════════════════════════════════
# U1 — 변환기
# ═══════════════════════════════════════════════════════════════════════════

def test_the_converter_copies_every_stored_field():
    row = {"revenue": 1000.0, "net_income": 100.0, "total_assets": 2000.0,
           "total_liabilities": 1500.0, "total_equity": 500.0,
           "shares_outstanding": 10.0, "dps": 30.0, "capex": 7.0,
           "operating_cf": 8.0}
    fs = dh.statement_from_row(row, bsns_year="2024", reprt_code="11011")
    assert fs is not None
    for f, v in row.items():
        assert getattr(fs, f) == v, f"{f} 가 옮겨지지 않았다"
    assert fs.bsns_year == "2024" and fs.reprt_code == "11011"


def test_the_converter_fills_equity_by_the_accounting_identity():
    """★날조가 아니라 항등식이다★ 자본=자산-부채. 일부 공시가 자본 라인을 뺀다."""
    fs = dh.statement_from_row(
        {"revenue": 1.0, "total_assets": 2000.0, "total_liabilities": 1500.0},
        bsns_year="2024", reprt_code="11011")
    assert fs.total_equity == 500.0


def test_the_converter_fills_liabilities_the_other_way():
    fs = dh.statement_from_row(
        {"revenue": 1.0, "total_assets": 2000.0, "total_equity": 500.0},
        bsns_year="2024", reprt_code="11011")
    assert fs.total_liabilities == 1500.0


def test_an_empty_row_is_none_not_a_hollow_statement():
    """핵심값(매출·자산)이 둘 다 없으면 `None` — 빈 껍데기를 만들지 않는다."""
    assert dh.statement_from_row({"dps": 30.0}, bsns_year="2024",
                                 reprt_code="11011") is None
    assert dh.statement_from_row({}, bsns_year="2024", reprt_code="11011") is None


def test_a_row_with_only_assets_still_converts():
    """★짝★ 항상-None 구현을 배제한다 — 자산만 있어도 유효하다."""
    fs = dh.statement_from_row({"total_assets": 2000.0}, bsns_year="2024",
                               reprt_code="11011")
    assert fs is not None and fs.total_assets == 2000.0


def test_there_is_only_one_converter(eng, monkeypatch):
    """★복제하면 두 벌이 갈라진다★ — 기존 소비자가 공용 함수를 실제로 부른다."""
    from src.data.fundamentals_store import FundamentalsStore
    seen: list = []
    real = dh.statement_from_row
    monkeypatch.setattr(dh, "statement_from_row",
                        lambda *a, **k: seen.append(a) or real(*a, **k))
    monkeypatch.setattr(dh, "history_snapshot",
                        lambda t, y, r: {"revenue": 1.0, "total_assets": 2.0})
    FundamentalsStore._fs_from_history(TICKER, 2024)
    assert seen, "_fs_from_history 가 공용 변환기를 부르지 않았다"


# ═══════════════════════════════════════════════════════════════════════════
# U2 — `statement_as_of`
# ═══════════════════════════════════════════════════════════════════════════

def test_before_the_restatement_the_original_is_used(eng):
    """★알맹이★ 정정 전 시점에는 그때 알던 값이 나온다."""
    dh.upsert_statement(eng, TICKER, _fs(**ORIGINAL))
    dh.upsert_statement(eng, TICKER, _fs(**RESTATED))
    fs, why = dh.statement_as_of(TICKER, "2025-04-01", engine=eng)
    assert why is None, why
    assert fs.revenue == 1000.0, "정정 후 값이 과거로 샜다"


def test_after_the_restatement_the_restated_is_used(eng):
    dh.upsert_statement(eng, TICKER, _fs(**ORIGINAL))
    dh.upsert_statement(eng, TICKER, _fs(**RESTATED))
    fs, why = dh.statement_as_of(TICKER, "2025-07-01", engine=eng)
    assert why is None, why
    assert fs.revenue == 900.0


def test_the_newest_usable_year_wins(eng):
    """여러 사업연도가 보이면 **가장 최근** 것을 쓴다."""
    dh.upsert_statement(eng, TICKER, _fs(year="2023", rcept_no="20240314000111",
                                         rcept_dt="2024-03-14", revenue=700.0))
    dh.upsert_statement(eng, TICKER, _fs(**ORIGINAL))          # 2024 사업연도
    fs, why = dh.statement_as_of(TICKER, "2025-04-01", engine=eng)
    assert why is None, why
    assert fs.bsns_year == "2024" and fs.revenue == 1000.0


# ── ★셋을 구별한다★ ───────────────────────────────────────────────────────

def test_nothing_filed_yet_is_its_own_reason(eng):
    dh.upsert_statement(eng, TICKER, _fs(**ORIGINAL))
    fs, why = dh.statement_as_of(TICKER, "2025-01-01", engine=eng)   # 접수 전
    assert fs is None
    assert why and "빈티지" in why, why


def test_an_unreadable_table_is_a_different_reason():
    """★못 읽음 ≠ 없음★ — DB 가 죽었을 때 "빈티지가 없다" 로 읽히면 안 된다."""
    bare = create_engine("sqlite://", connect_args={"check_same_thread": False},
                         poolclass=StaticPool)
    fs, why = dh.statement_as_of(TICKER, "2025-07-01", engine=bare)
    assert fs is None
    assert why and "읽지 못했" in why, why
    bare.dispose()


def test_only_quarterly_vintages_is_a_different_reason(eng):
    """연간이 없으면 그 사실을 말한다 — 분기를 연간인 척 쓰지 않는다."""
    dh.upsert_statement(eng, TICKER, _fs(reprt="11013", rcept_no="20241114000222",
                                         rcept_dt="2024-11-14", revenue=300.0))
    fs, why = dh.statement_as_of(TICKER, "2025-07-01", engine=eng)
    assert fs is None
    assert why and ("연간" in why or "11011" in why), why


def test_the_three_reasons_are_not_the_same_string(eng):
    """★뭉치면 처방이 사라진다★ — 적재하라 vs DB 를 고쳐라 vs 기다려라."""
    dh.upsert_statement(eng, TICKER, _fs(**ORIGINAL))
    _, early = dh.statement_as_of(TICKER, "2025-01-01", engine=eng)
    bare = create_engine("sqlite://", connect_args={"check_same_thread": False},
                         poolclass=StaticPool)
    _, unread = dh.statement_as_of(TICKER, "2025-07-01", engine=bare)
    bare.dispose()
    assert early != unread, (early, unread)


def test_it_never_falls_back_to_the_overwritten_table(eng):
    """★오늘 표로 폴백하지 않는다★ — 본문만 있고 빈티지가 없으면 거부한다."""
    no_v = _fs(**ORIGINAL)
    no_v.rcept_no = no_v.rcept_dt = None
    assert dh.upsert_statement(eng, TICKER, no_v)      # financials_history 에는 들어감
    assert dh.history_snapshot(TICKER, "2024", "11011", engine=eng) is not None
    fs, why = dh.statement_as_of(TICKER, "2025-07-01", engine=eng)
    assert fs is None, "빈티지가 없는데 오늘 표에서 값을 만들었다"
    assert why, "사유 없는 거부"
