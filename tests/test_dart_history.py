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


# ─── 시계열 파생 팩터 (흑자전환·3년연속·성장률) ──────────────────────────────
def seed_fs(engine, year, reprt, **kw):
    fs = FinancialStatement(corp_code="c", corp_name="n", bsns_year=str(year),
                            reprt_code=reprt)
    for k, v in kw.items():
        setattr(fs, k, v)
    assert dh.upsert_statement(engine, "005930", fs)


def test_history_factors_turnaround_and_3y(mem_engine):
    dh.ensure_history_table(mem_engine)
    # 연간 3개: 순이익 -50 → -10 → 80 (3년연속 X), 영업이익 5 → 10 → 20 (3년연속 O)
    # 배당 100 → 100 → 120 (같거나상승 O)
    seed_fs(mem_engine, 2022, "11011", net_income=-50.0, operating_profit=5.0, dps=100.0,
            total_assets=1000.0, total_equity=500.0, total_liabilities=500.0, revenue=900.0)
    seed_fs(mem_engine, 2023, "11011", net_income=-10.0, operating_profit=10.0, dps=100.0,
            total_assets=1000.0, total_equity=500.0, total_liabilities=500.0, revenue=900.0)
    seed_fs(mem_engine, 2024, "11011", net_income=80.0, operating_profit=20.0, dps=120.0,
            total_assets=1100.0, total_equity=550.0, total_liabilities=550.0, revenue=1000.0)
    # 1Q: 2024(-5, 누적) → 2025(+40) — YoY 흑자전환
    seed_fs(mem_engine, 2024, "11013", net_income=-5.0, operating_profit=3.0,
            total_assets=1050.0, total_equity=520.0, total_liabilities=530.0, revenue=240.0,
            current_assets=400.0, current_liabilities=200.0, gross_profit=60.0)
    seed_fs(mem_engine, 2025, "11013", net_income=40.0, operating_profit=15.0,
            total_assets=1155.0, total_equity=572.0, total_liabilities=583.0, revenue=270.0,
            current_assets=460.0, current_liabilities=200.0, gross_profit=81.0)

    f = dh._compute_history_factors(dh.load_history("005930", engine=mem_engine))
    assert f["ni_turnaround_yoy"] == 1.0            # 1Q: -5 → +40
    assert f["op_turnaround_yoy"] == 0.0            # 3 → 15 (둘 다 흑자)
    assert f["ni_positive_3y"] == 0.0 and f["op_positive_3y"] == 1.0
    assert f["dps_up_3y"] == 1.0
    assert f["dps_growth_yoy"] == pytest.approx(20.0)
    assert f["asset_growth_yoy"] == pytest.approx(10.0)        # 1050 → 1155
    assert f["equity_growth_yoy"] == pytest.approx(10.0)       # 520 → 572
    assert f["ni_growth_yoy"] is None               # 전년 음수 분모 → 성장률 무의미(None)
    assert f["gross_margin_growth_yoy"] == pytest.approx(
        ((81 / 270) - (60 / 240)) / (60 / 240) * 100)
    # QOQ: 2025 1Q의 직전 단일분기(2024 4Q = 연간-3Q)가 없음(3Q 미적재) → None
    assert f["ni_growth_qoq"] is None and f["ni_turnaround_qoq"] is None


def test_history_factors_qoq_single_quarter_diff(mem_engine):
    """QOQ는 누적 차분 단일 분기값 — 반기(누적) - 1Q = 2Q 단일."""
    dh.ensure_history_table(mem_engine)
    seed_fs(mem_engine, 2025, "11013", net_income=-10.0, operating_profit=30.0)   # 1Q
    seed_fs(mem_engine, 2025, "11012", net_income=20.0, operating_profit=75.0)    # 반기 누적
    f = dh._compute_history_factors(dh.load_history("005930", engine=mem_engine))
    # 2Q 단일 NI = 20-(-10) = 30, 1Q = -10 → 흑자전환 1.0
    assert f["ni_turnaround_qoq"] == 1.0
    assert f["op_growth_qoq"] == pytest.approx((45 - 30) / 30 * 100)  # 2Q 단일 op=45
    assert f["ni_positive_3y"] is None              # 연간 3개 미만 → None(정직)


def test_history_factors_empty_without_data(mem_engine):
    dh.ensure_history_table(mem_engine)
    f = dh._compute_history_factors(dh.load_history("005930", engine=mem_engine))
    assert all(v is None for v in f.values())       # 전부 None → 조건 건너뜀


# ─── PIT 연동: DB 적재분 우선 (키 불필요) ────────────────────────────────────
def test_pit_uses_db_history_without_key(monkeypatch):
    from src.engine.pit_store import PITStore
    row = {"net_income": 100.0, "total_equity": 500.0, "total_assets": 2000.0,
           "total_liabilities": 1500.0}
    monkeypatch.setattr("src.data.dart_history.history_snapshot",
                        lambda t, y, r, engine=None: row if t == "005930" else None)
    monkeypatch.setattr("src.engine.universe_select.mktcap_asof",
                        lambda t, d, engine=None: None)  # 시총 미적재 환경

    class NoKeyDART:
        is_configured = False
    monkeypatch.setattr("src.data.dart_client.DARTClient", NoKeyDART)

    snap = PITStore().get_financials_asof("005930", "2024-05-20",
                                          {"roe_pct": 1.0, "per": 10.0})
    assert snap["_source"] == "pit_db"                 # DART 키 없이 DB로 PIT
    # as_of 5/20 → 1Q 보고서 — 누적 손익 연환산 ×4: 400/500 = 80%
    assert snap["roe_pct"] == pytest.approx(80.0)
    assert snap["per"] is None                          # 시총 없음 — 부분 적용
