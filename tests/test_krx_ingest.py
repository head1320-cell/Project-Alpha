"""KRX OpenAPI 클라이언트 파싱 + 백필 파이프라인 단위 테스트.

공식 응답 구조(OutBlock_1 필드명)를 미러한 fixture로 파싱·적재·재개·수정종가
재구성·시점 유니버스를 검증. 네트워크·실키 불필요 (실수신은 verify_connection 【5】).
"""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from src.data import krx_ingest as ki
from src.data.krx_client import parse_index_row, parse_stock_rows
from src.engine.universe_select import tickers_asof


# ─── 파서: 일별매매정보 ───────────────────────────────────────────────────────
def stock_row(**kw) -> dict:
    base = {
        "BAS_DD": "20240105", "ISU_CD": "005930", "ISU_NM": "삼성전자",
        "MKT_NM": "KOSPI", "SECT_TP_NM": "", "TDD_CLSPRC": "76,600",
        "CMPPREVDD_PRC": "-300", "FLUC_RT": "-0.39", "TDD_OPNPRC": "76,700",
        "TDD_HGPRC": "77,100", "TDD_LWPRC": "76,400",
        "ACC_TRDVOL": "11,304,316", "ACC_TRDVAL": "866,789,177,564",
        "MKTCAP": "457,283,550,529,000", "LIST_SHRS": "5,969,782,550",
    }
    base.update(kw)
    return base


def test_parse_stock_rows_comma_numbers():
    [r] = parse_stock_rows([stock_row()], "KOSPI")
    assert (r["ticker"], r["name"], r["market"]) == ("005930", "삼성전자", "KOSPI")
    assert r["date"] == "2024-01-05"
    assert r["close"] == 76_600 and r["high"] == 77_100
    assert r["volume"] == 11_304_316
    assert r["fluc_rt"] == pytest.approx(-0.39)


def test_parse_stock_rows_isin_normalized():
    """12자리 표준코드(KR7...) → 6자리 단축코드."""
    [r] = parse_stock_rows([stock_row(ISU_CD="KR7005930003")], "KOSPI")
    assert r["ticker"] == "005930"


def test_parse_stock_rows_skips_invalid():
    rows = parse_stock_rows([
        stock_row(TDD_CLSPRC="-"),            # 거래정지(가격 없음)
        stock_row(ISU_CD="ABC"),              # 코드 형식 이상
        stock_row(ISU_CD="000660", ISU_NM="SK하이닉스"),
    ], "KOSPI")
    assert [r["ticker"] for r in rows] == ["000660"]


def test_parse_index_row_picks_target():
    rows = [
        {"BAS_DD": "20240105", "IDX_NM": "코스피 200", "CLSPRC_IDX": "350.21"},
        {"BAS_DD": "20240105", "IDX_NM": "코스피", "CLSPRC_IDX": "2,587.02",
         "OPNPRC_IDX": "2,592.97", "HGPRC_IDX": "2,594.21", "LWPRC_IDX": "2,580.93",
         "ACC_TRDVOL": "401,310", "FLUC_RT": "-0.35"},
    ]
    idx = parse_index_row(rows, "코스피")
    assert idx and idx["close"] == pytest.approx(2587.02) and idx["date"] == "2024-01-05"
    assert parse_index_row(rows, "코스닥") is None


# ─── 백필 (fake client + in-memory SQLite) ───────────────────────────────────
class FakeKRX:
    """2거래일(1/4·1/5)만 데이터, 그 외 빈 응답(휴장 모사)."""
    is_configured = True
    TRADING = {"2024-01-04", "2024-01-05"}

    def __init__(self):
        self.calls = 0

    def get_daily_all(self, market, date):
        self.calls += 1
        if date not in self.TRADING:
            return []
        return parse_stock_rows([
            stock_row(BAS_DD=date.replace("-", "")),
            stock_row(BAS_DD=date.replace("-", ""), ISU_CD="000660", ISU_NM="SK하이닉스",
                      TDD_CLSPRC="140,000", FLUC_RT="1.00"),
        ], market)

    def get_index_daily(self, market, date):
        if date not in self.TRADING:
            return None
        return {"date": date, "open": 2580.0, "high": 2600.0, "low": 2570.0,
                "close": 2590.0, "volume": 400_000, "fluc_rt": 0.1}


@pytest.fixture
def mem_engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    yield eng
    eng.dispose()


def test_backfill_loads_and_resumes(mem_engine):
    client = FakeKRX()
    stats = ki.backfill("2024-01-03", "2024-01-05", markets=("KOSPI",),
                        engine=mem_engine, client=client, full_day_min_rows=2)
    assert not stats.get("error")
    assert stats["days_loaded"] == 2 and stats["days_empty"] == 1   # 1/3 휴장
    assert stats["rows"] == 4 and stats["index_rows"] == 2          # 2종목×2일 + 지수

    # 재실행 → 적재된 날짜는 skip (쿼터 분할 실행 안전)
    stats2 = ki.backfill("2024-01-03", "2024-01-05", markets=("KOSPI",),
                         engine=mem_engine, client=client, full_day_min_rows=2)
    assert stats2["days_skipped"] == 2 and stats2["rows"] == 0

    with mem_engine.connect() as conn:
        n = conn.execute(text("SELECT COUNT(*) FROM daily_prices")).scalar()
        assert n == 6  # 4 종목행 + 2 지수행(KOSPI)


def test_backfill_requires_key(mem_engine):
    class NoKey:
        is_configured = False
    stats = ki.backfill("2024-01-03", "2024-01-05", engine=mem_engine, client=NoKey())
    assert stats.get("error")


# ─── 수정종가 재구성 (등락률 체인 — 분할 점프 제거) ──────────────────────────
def test_rebuild_adj_close_handles_split(mem_engine):
    ki.ensure_table(mem_engine)
    # 액면분할 시나리오: 102 → (다음날 기준가 51, 등락률 0%) 51 → +2%
    rows = [
        {"ticker": "000001", "date": "2024-01-02", "open": 100, "high": 100, "low": 100,
         "close": 100.0, "volume": 0, "trading_value": 0, "fluc_rt": None},
        {"ticker": "000001", "date": "2024-01-03", "open": 102, "high": 102, "low": 102,
         "close": 102.0, "volume": 0, "trading_value": 0, "fluc_rt": 2.0},
        {"ticker": "000001", "date": "2024-01-04", "open": 51, "high": 51, "low": 51,
         "close": 51.0, "volume": 0, "trading_value": 0, "fluc_rt": 0.0},   # 분할일
        {"ticker": "000001", "date": "2024-01-05", "open": 52, "high": 52, "low": 52,
         "close": 52.02, "volume": 0, "trading_value": 0, "fluc_rt": 2.0},
    ]
    ki.bulk_upsert(mem_engine, rows)
    assert ki.rebuild_adj_close(engine=mem_engine, tickers=["000001"]) == 4

    with mem_engine.connect() as conn:
        adj = dict(conn.execute(text(
            "SELECT trade_date, adj_close FROM daily_prices WHERE ticker='000001'")).fetchall())
    # 원주가는 102→51 (-50% 가짜 점프), 수정종가는 연속: 50 → 51 → 51 → 52.02
    assert adj["2024-01-05"] == pytest.approx(52.02)
    assert adj["2024-01-04"] == pytest.approx(51.0)
    assert adj["2024-01-03"] == pytest.approx(51.0)   # 분할 전 102가 51로 소급
    assert adj["2024-01-02"] == pytest.approx(50.0)


# ─── 시점 유니버스 (생존편향 보정) ────────────────────────────────────────────
def test_tickers_asof_uses_prior_day_and_excludes_index(mem_engine):
    ki.ensure_table(mem_engine)
    rows = [
        {"ticker": "005930", "date": "2024-01-05", "open": 1, "high": 1, "low": 1,
         "close": 1.0, "volume": 0, "trading_value": 0, "fluc_rt": None},
        {"ticker": "999999", "date": "2024-01-05", "open": 1, "high": 1, "low": 1,
         "close": 1.0, "volume": 0, "trading_value": 0, "fluc_rt": None},  # 이후 상폐 종목 가정
        {"ticker": "KOSPI", "date": "2024-01-05", "open": 1, "high": 1, "low": 1,
         "close": 2590.0, "volume": 0, "trading_value": 0, "fluc_rt": None},
    ]
    ki.bulk_upsert(mem_engine, rows)

    # 주말(1/6) 기준 → 직전 거래일(1/5) 유니버스, 지수 행 제외
    out = tickers_asof("2024-01-06", engine=mem_engine, min_count=2)
    assert set(out) == {"005930", "999999"}
    # 표본 부족 → 빈 리스트 (호출부 폴백)
    assert tickers_asof("2024-01-06", engine=mem_engine, min_count=10) == []
    # 데이터 이전 날짜 → 빈 리스트
    assert tickers_asof("2023-12-01", engine=mem_engine, min_count=1) == []
