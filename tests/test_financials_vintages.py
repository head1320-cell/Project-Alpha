"""재무 정정공시를 ★파괴하지 않고★ 쌓는다 (`financials_vintages`)

## 무엇이 문제였나

`financials_history` 는 PK `(ticker, bsns_year, reprt_code)` + `ON CONFLICT DO
UPDATE` 라 **정정공시가 원본 보고값을 덮어쓴다.** 되돌릴 수 없다 — 지나간
빈티지는 다시 받을 수 없다.

V1(`939b33b`)이 `fs.rcept_no`·`fs.rcept_dt` 를 받게 했지만 **저장 층이 그것을
버리고 있었다.** `tests/test_dart_filing_date.py:122` 가 그 계약을 이미 적어
뒀고 저장 층 대응물이 없었다:

    ★이것이 빈티지 축이다★ 같은 (연도, 보고서) 인데 접수번호가 다르면
    정정공시다. 지금 스키마는 그 둘을 구별하지 못해 뒤에 온 것이 앞의 것을 덮는다.

## ★기존 테이블을 건드리지 않는다★

`financials_history` 는 그대로 두고("지금 값") 새 `financials_vintages` 가
빈티지를 누적한다("그때 알던 값"). 이유는 셋 다 실측했다:

  ① 이 테이블에는 `ORDER BY`·`DISTINCT` 가 하나도 없어, 행이 늘면 리더 8곳이
     **조용히** 깨진다(QOQ 팩터 4개가 통째로 `None` 이 되고, 적신호 R2·R3 은
     안전해 보이는 방향으로 억제되고, PIT 패널은 두 공시를 필드 단위로 섞는다).
  ② CI 가 SQLite 로만 돌아 PK 재구축 DDL 이 **프로덕션에서 처음 실행**된다.
  ③ `test_financial_revenue.py:87` 의 손수 INSERT 가 즉시 깨진다.

이건 이 저장소의 기존 모델이기도 하다 — `pit_macro` 가 *"지금 최신 값(대시보드)
/ 그때 알 수 있던 값(리서치·백테스트)"* 로 두 경로를 갈라 뒀다.

## 이 파일이 거는 계약

① 같은 기간의 두 접수번호가 **나란히** 남는다 — 덮어쓰지 않는다.
② 같은 접수번호 재조회는 **멱등** — 새 행을 만들지 않는다.
③ ★`retrieved_at` 은 갱신하지 않는다★ — 최초 관측 시각이 사라지면 "언제부터
   알았나" 를 잃는다(`macro_observation_store.py:110` 과 같은 규칙).
④ ★접수번호가 없으면 빈티지가 아니다★ — 저장하지 않고, 건너뛴 수를 센다.
⑤ 빈티지 쓰기가 실패해도 **기존 적재는 성공한다**.
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from src.data import dart_history as dh  # noqa: E402
from src.data.dart_client import FinancialStatement  # noqa: E402

TICKER = "005930"


@pytest.fixture
def mem_engine():
    """두 테이블을 **미리** 만든다.

    ★빈티지 테이블을 미리 만들지 않으면 "저장 안 됨" 검사가 공허해진다★ —
    테이블이 없어서 조회가 실패한 것인지, 있는데 비어 있는 것인지 구별되지 않는다.
    후자가 이 파일이 검사하려는 것이다.
    """
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    dh.ensure_history_table(eng)
    assert dh.ensure_vintage_table(eng), "빈티지 테이블을 만들지 못했다"
    dh._VINTAGE_SKIPPED["no_rcept"] = 0        # 프로세스 수명 카운터 — 테스트마다 초기화
    yield eng
    eng.dispose()


def _fs(*, rcept_no: str | None, rcept_dt: str | None, revenue: float,
        year: str = "2024", reprt: str = "11011") -> FinancialStatement:
    fs = FinancialStatement(corp_code="00126380", corp_name="삼성전자",
                            bsns_year=year, reprt_code=reprt)
    fs.revenue, fs.net_income = revenue, 100.0
    fs.total_equity, fs.total_assets, fs.total_liabilities = 500.0, 2000.0, 1500.0
    fs.rcept_no, fs.rcept_dt = rcept_no, rcept_dt
    return fs


def _vintages(engine, ticker: str = TICKER) -> list[dict]:
    with engine.connect() as c:
        rows = c.execute(text(
            "SELECT rcept_no, rcept_dt, revenue, retrieved_at FROM financials_vintages "
            "WHERE ticker=:t ORDER BY rcept_dt"), {"t": ticker}).fetchall()
    return [{"rcept_no": r[0], "rcept_dt": r[1], "revenue": r[2],
             "retrieved_at": r[3]} for r in rows]


# ═══════════════════════════════════════════════════════════════════════════════
# ① 정정공시가 원본을 파괴하지 않는다 — ★이 작업의 알맹이★
# ═══════════════════════════════════════════════════════════════════════════════

def test_a_restatement_does_not_destroy_the_original(mem_engine):
    """★W-a 를 죽이는 앵커★ 같은 (연도, 보고서) 인데 접수번호가 다르면 둘 다 남는다.

    지금까지는 뒤에 온 것이 앞의 것을 덮었고, 되돌릴 수 없었다.
    """
    dh.upsert_statement(mem_engine, TICKER,
                        _fs(rcept_no="20250314000777", rcept_dt="2025-03-14", revenue=1000.0))
    dh.upsert_statement(mem_engine, TICKER,
                        _fs(rcept_no="20250620000999", rcept_dt="2025-06-20", revenue=1100.0))

    got = _vintages(mem_engine)
    assert len(got) == 2, f"정정공시가 원본을 덮었다: {got}"
    assert [g["revenue"] for g in got] == [1000.0, 1100.0], got
    assert [g["rcept_dt"] for g in got] == ["2025-03-14", "2025-06-20"], got


def test_refetching_the_same_filing_is_idempotent(mem_engine):
    """★W-d 짝★ 이것이 없으면 "무조건 새 행" 구현도 위 테스트를 통과한다."""
    for _ in range(3):
        dh.upsert_statement(mem_engine, TICKER,
                            _fs(rcept_no="20250314000777", rcept_dt="2025-03-14",
                                revenue=1000.0))
    assert len(_vintages(mem_engine)) == 1, "같은 접수번호가 행을 늘렸다"


def test_refetching_the_same_filing_updates_values_but_not_the_first_seen_time(mem_engine):
    """★W-c★ 값은 갱신하되 ★최초 관측 시각은 보존한다★.

    `macro_observation_store.py:110` 이 적어 둔 규칙 그대로 —
    "덮으면 '언제부터 알았나' 가 사라진다."
    """
    dh.upsert_statement(mem_engine, TICKER,
                        _fs(rcept_no="20250314000777", rcept_dt="2025-03-14", revenue=None))
    first = _vintages(mem_engine)[0]["retrieved_at"]
    assert first, "최초 관측 시각이 비었다"

    import time
    time.sleep(1.1)          # `isoformat(timespec="seconds")` 해상도를 넘긴다
    dh.upsert_statement(mem_engine, TICKER,
                        _fs(rcept_no="20250314000777", rcept_dt="2025-03-14", revenue=1000.0))

    got = _vintages(mem_engine)
    assert len(got) == 1
    assert got[0]["revenue"] == 1000.0, "값이 갱신되지 않았다"
    assert got[0]["retrieved_at"] == first, (
        f"최초 관측 시각이 덮였다: {first} → {got[0]['retrieved_at']}")


# ═══════════════════════════════════════════════════════════════════════════════
# ④ 접수번호가 없으면 빈티지가 아니다
# ═══════════════════════════════════════════════════════════════════════════════

def test_a_statement_without_a_receipt_number_is_not_stored_as_a_vintage(mem_engine):
    """★W-b★ 접수번호 없는 행은 빈티지가 아니다 — 지어내지 않는다.

    `macro_observation_store.record_series` 가 같은 판단을 적어 뒀다:
    "이 경로에는 빈티지가 없다 … 지어내면 derive_usage 가 거짓으로
    backtest_eligible 을 낸다."
    """
    dh.upsert_statement(mem_engine, TICKER,
                        _fs(rcept_no=None, rcept_dt=None, revenue=1000.0))
    assert _vintages(mem_engine) == [], "접수번호 없는 행을 빈티지로 저장했다"


def test_the_skipped_count_is_reported_not_silent(mem_engine):
    """★미상을 0 으로 만들지 않는다★ 몇 건이 빈티지 없이 지나갔는지 셀 수 있어야 한다."""
    dh.upsert_statement(mem_engine, TICKER,
                        _fs(rcept_no=None, rcept_dt=None, revenue=1000.0))
    dh.upsert_statement(mem_engine, TICKER,
                        _fs(rcept_no="20250314000777", rcept_dt="2025-03-14", revenue=1000.0))
    stats = dh.vintage_stats(mem_engine)
    assert stats["rows"] == 1, stats
    assert stats["skipped_no_rcept"] >= 1, f"빈티지 없이 지나간 건수를 안 센다: {stats}"


# ═══════════════════════════════════════════════════════════════════════════════
# ⑤ 기존 적재를 막지 않는다 — ★동작 불변★
# ═══════════════════════════════════════════════════════════════════════════════

def test_the_existing_table_is_written_exactly_as_before(mem_engine):
    """★W-e★ `financials_history` 는 한 글자도 안 바뀐다 — 리더 8곳이 그대로 돈다."""
    dh.upsert_statement(mem_engine, TICKER,
                        _fs(rcept_no="20250314000777", rcept_dt="2025-03-14", revenue=1000.0))
    snap = dh.history_snapshot(TICKER, "2024", "11011", engine=mem_engine)
    assert snap is not None and snap["revenue"] == 1000.0, snap

    # 정정공시가 와도 "지금 값" 테이블은 최신값 1건을 유지한다(기존 동작).
    dh.upsert_statement(mem_engine, TICKER,
                        _fs(rcept_no="20250620000999", rcept_dt="2025-06-20", revenue=1100.0))
    with mem_engine.connect() as c:
        n = c.execute(text("SELECT COUNT(*) FROM financials_history "
                           "WHERE ticker=:t"), {"t": TICKER}).scalar()
    assert n == 1, f"기존 테이블에 행이 늘었다 — 리더 8곳이 깨진다: {n}"
    assert dh.history_snapshot(TICKER, "2024", "11011",
                               engine=mem_engine)["revenue"] == 1100.0


def test_a_vintage_write_failure_does_not_block_the_existing_ingest(mem_engine, monkeypatch):
    """★W-f★ 새 테이블이 죽어도 기존 적재는 성공해야 한다.

    빈티지는 **추가**이지 전제가 아니다. 여기서 막히면 V2 가 적재를 망가뜨린다.
    """
    def _boom(*a, **k):
        raise RuntimeError("빈티지 테이블 사용 불가")

    monkeypatch.setattr(dh, "_upsert_vintage", _boom)
    ok = dh.upsert_statement(mem_engine, TICKER,
                             _fs(rcept_no="20250314000777", rcept_dt="2025-03-14",
                                 revenue=1000.0))
    assert ok is True, "빈티지 쓰기 실패가 기존 적재를 막았다"
    assert dh.history_snapshot(TICKER, "2024", "11011",
                               engine=mem_engine)["revenue"] == 1000.0


# ═══════════════════════════════════════════════════════════════════════════════
# 관측 — 안 보이면 없는 것과 같다
# ═══════════════════════════════════════════════════════════════════════════════

def test_the_restated_period_count_is_what_answers_the_question(mem_engine):
    """★W-g★ 행 수가 아니라 **빈티지 2건 이상인 기간 수**가 "정정공시를 봤는가" 다."""
    dh.upsert_statement(mem_engine, TICKER,
                        _fs(rcept_no="20250314000777", rcept_dt="2025-03-14", revenue=1000.0))
    assert dh.vintage_stats(mem_engine)["restated_periods"] == 0, "정정 없는데 셌다"

    dh.upsert_statement(mem_engine, TICKER,
                        _fs(rcept_no="20250620000999", rcept_dt="2025-06-20", revenue=1100.0))
    stats = dh.vintage_stats(mem_engine)
    assert stats["rows"] == 2 and stats["restated_periods"] == 1, stats


def test_stats_on_a_missing_table_is_unknown_not_zero(monkeypatch):
    """★미상 ≠ 0★ 테이블을 못 읽으면 `None` + 사유이지 "0건" 이 아니다."""
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)          # 테이블을 만들지 않는다
    stats = dh.vintage_stats(eng)
    assert stats["rows"] is None, f"못 읽었는데 수치를 적었다: {stats}"
    assert stats["reason"], "못 읽었는데 사유가 없다"
    eng.dispose()
