"""DART 재무 시계열 백필(financials_history) + PIT DB 우선 조회 테스트.

FakeDART + in-memory SQLite로 적재·resume·쿼터 분할·비율 산출·PIT 연동 검증.
네트워크·실키 불필요.
"""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from src.data import dart_history as dh
from src.data.dart_client import FinancialStatement


def make_fs(year: str, reprt: str = "11011", revenue=1000.0, ni=100.0,
            equity=500.0, assets=2000.0, liab=1500.0) -> FinancialStatement:
    fs = FinancialStatement(corp_code="00126380", corp_name="삼성전자",
                            bsns_year=year, reprt_code=reprt)
    fs.revenue, fs.net_income = revenue, ni
    fs.total_equity, fs.total_assets, fs.total_liabilities = equity, assets, liab
    return fs


class FakeDART:
    is_configured = True

    def __init__(self, missing_years=()):
        self.calls = []
        self.missing = set(missing_years)

    def get_financial_statement_full(self, corp, year, reprt_code="11011"):
        self.calls.append((corp, year, reprt_code))
        if year in self.missing:
            return None  # 상장 전 연도 등
        return make_fs(year, reprt_code)


@pytest.fixture
def mem_engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    yield eng
    eng.dispose()


@pytest.fixture
def corp_map(monkeypatch):
    import src.data.dart_client as dc
    monkeypatch.setattr(dc, "get_corp_code",
                        lambda tk: "00126380" if tk != "999999" else None)


def test_backfill_saves_and_resumes(mem_engine, corp_map):
    client = FakeDART()
    stats = dh.backfill_financials(tickers=["005930"], years=3,
                                   engine=mem_engine, client=client)
    assert stats["calls"] == 3 and stats["saved"] == 3 and stats["empty"] == 0

    # 재실행 → 적재 3건 전부 skip, 추가 호출 0 (쿼터 분할 resume의 핵심)
    stats2 = dh.backfill_financials(tickers=["005930"], years=3,
                                    engine=mem_engine, client=client)
    assert stats2["skipped"] == 3 and stats2["calls"] == 0


def test_backfill_empty_year_retried_on_resume(mem_engine, corp_map):
    """상장 전 연도(빈 응답)는 저장이 없으므로 재실행 시 다시 시도된다."""
    last3 = str(__import__("datetime").datetime.now().year - 3)
    client = FakeDART(missing_years={last3})
    s1 = dh.backfill_financials(tickers=["005930"], years=3, engine=mem_engine, client=client)
    assert s1["saved"] == 2 and s1["empty"] == 1
    s2 = dh.backfill_financials(tickers=["005930"], years=3, engine=mem_engine, client=client)
    assert s2["skipped"] == 2 and s2["calls"] == 1  # 빈 연도만 재시도


def test_backfill_quota_split(mem_engine, corp_map):
    client = FakeDART()
    stats = dh.backfill_financials(tickers=["005930", "000660"], years=5,
                                   max_calls=3, engine=mem_engine, client=client)
    assert stats["calls"] == 3 and stats.get("stopped_at_quota")
    # 이어서 실행 → 남은 7건만
    stats2 = dh.backfill_financials(tickers=["005930", "000660"], years=5,
                                    engine=mem_engine, client=client)
    assert stats2["skipped"] == 3 and stats2["calls"] == 7
    with mem_engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM financials_history")).scalar() == 10


def test_backfill_unknown_corp_skipped(mem_engine, corp_map):
    client = FakeDART()
    stats = dh.backfill_financials(tickers=["999999"], years=3,
                                   engine=mem_engine, client=client)
    assert stats["no_corp"] == 1 and stats["calls"] == 0


def test_history_snapshot_and_ratios(mem_engine):
    dh.ensure_history_table(mem_engine)
    dh.upsert_statement(mem_engine, "005930", make_fs("2023"))
    row = dh.history_snapshot("005930", "2023", "11011", engine=mem_engine)
    assert row["net_income"] == 100.0
    r = dh.ratios_from_row(row)
    assert r["roe_pct"] == pytest.approx(20.0)        # 100/500
    assert r["roa_pct"] == pytest.approx(5.0)         # 100/2000
    assert r["debt_ratio_pct"] == pytest.approx(300.0)  # 1500/500
    assert dh.history_snapshot("005930", "2010", "11011", engine=mem_engine) is None


def test_empty_statement_not_saved(mem_engine):
    dh.ensure_history_table(mem_engine)
    fs = FinancialStatement(corp_code="x", corp_name="y", bsns_year="2023", reprt_code="11011")
    assert dh.upsert_statement(mem_engine, "005930", fs) is False


# ─── PIT 연동: DB 적재분 우선 (키 불필요) ────────────────────────────────────
def test_pit_uses_db_history_without_key(monkeypatch):
    from src.engine.pit_store import PITStore
    row = {"net_income": 100.0, "total_equity": 500.0, "total_assets": 2000.0,
           "total_liabilities": 1500.0}
    monkeypatch.setattr("src.data.dart_history.history_snapshot",
                        lambda t, y, r, engine=None: row if t == "005930" else None)

    class NoKeyDART:
        is_configured = False
    monkeypatch.setattr("src.data.dart_client.DARTClient", NoKeyDART)

    snap = PITStore().get_financials_asof("005930", "2024-05-20",
                                          {"roe_pct": 1.0, "per": 10.0})
    assert snap["_source"] == "pit_db"                 # DART 키 없이 DB로 PIT
    assert snap["roe_pct"] == pytest.approx(20.0)
    assert snap["per"] is None                          # 가격 의존 — 부분 적용
