"""PIT 스토어 — DART 연동 단위 테스트.

_period_asof(공시완료 보고서 선택, look-ahead 차단 경계)와
get_financials_asof의 DART 분기/mock 폴백을 mock DART로 검증. 네트워크 불필요.
"""
import pytest

from src.engine import pit_store as ps
from src.engine.pit_store import PITStore, _period_asof

CUR = {"roe_pct": 12.0, "roa_pct": 6.0, "per": 10.0, "pbr": 1.2,
       "debt_ratio_pct": 80.0, "dividend_yield_pct": 2.0, "fcf_억": 100.0, "market_cap_억": 1000.0}


# ─── 보고서 선택 (look-ahead 경계) ────────────────────────────────────────────
@pytest.mark.parametrize("as_of,expected", [
    ("2024-05-14", ("2023", "11011")),  # Q1 공시(3/31+45=5/15) 전날 → 직전 연간
    ("2024-05-15", ("2024", "11013")),  # Q1 공시 완료일 → 1분기
    ("2024-08-13", ("2024", "11013")),  # 반기 공시(6/30+45=8/14) 전날 → 1분기
    ("2024-08-14", ("2024", "11012")),  # 반기
    ("2024-11-14", ("2024", "11014")),  # 3분기 (9/30+45)
    ("2025-02-01", ("2024", "11014")),  # 연간(12/31+90=3/31) 전 → 전년 3분기
    ("2025-03-31", ("2024", "11011")),  # 연간 공시 완료
])
def test_period_asof_boundaries(as_of, expected):
    assert _period_asof(as_of) == expected


def test_period_asof_invalid_date():
    assert _period_asof("not-a-date") is None


# ─── DART 분기 / mock 폴백 ────────────────────────────────────────────────────
class FakeFS:
    """compute_ratios 후 roe/roa/debt_ratio를 갖는 가짜 재무제표."""
    total_equity = 100.0
    total_assets = 200.0
    total_liabilities = 100.0
    net_income = 15.0
    roe = roa = debt_ratio = None

    def compute_ratios(self, current_price=None):
        self.roe = 15.0
        self.roa = 7.5
        self.debt_ratio = 100.0


class FakeDART:
    is_configured = True

    def __init__(self):
        self.calls = []

    def get_financial_statement_full(self, corp, year, reprt_code="11011"):
        self.calls.append((corp, year, reprt_code))
        return FakeFS()


@pytest.fixture
def fresh_store():
    store = PITStore()  # 싱글톤 대신 새 인스턴스 (캐시 격리)
    return store


def test_dart_snapshot_used_when_configured(fresh_store, monkeypatch):
    import src.data.dart_client as dc
    monkeypatch.setattr(dc, "DARTClient", FakeDART)
    monkeypatch.setattr(dc, "get_corp_code", lambda code: "00126380")
    monkeypatch.setattr("src.engine.universe_select.mktcap_asof",
                        lambda t, d, engine=None: None)  # 시총 미적재 환경

    snap = fresh_store.get_financials_asof("005930", "2024-05-20", CUR)
    assert snap["_source"] == "pit_dart"
    assert snap["_report"] == "2024/11013"          # as_of 기준 1분기 보고서
    # 1Q 누적 손익 연환산: NI 15×4=60 / equity 100 → ROE 60%
    assert snap["roe_pct"] == pytest.approx(60.0) and snap["_annualized"] is True
    assert snap["debt_ratio_pct"] == 100.0
    assert snap["per"] is None and snap["market_cap_억"] is None  # 시총 없음 → 부분 적용


def test_pit_valuation_with_mktcap(fresh_store, monkeypatch):
    """[C]시총 × [A]재무 결합 — 역사 PER/PBR 실값. 연간 보고서 + 시총 1,000억."""
    row = {"net_income": 1e10, "total_equity": 5e10, "total_assets": 2e11,
           "total_liabilities": 1.5e11}
    monkeypatch.setattr("src.data.dart_history.history_snapshot",
                        lambda t, y, r, engine=None: row)
    monkeypatch.setattr("src.engine.universe_select.mktcap_asof",
                        lambda t, d, engine=None: 1e11)

    snap = fresh_store.get_financials_asof("005930", "2025-04-01", CUR)  # 2024 연간 공시 직후
    assert snap["_source"] == "pit_db" and snap["_report"] == "2024/11011"
    assert snap["_annualized"] is False
    assert snap["per"] == pytest.approx(10.0)            # 1,000억 / 100억
    assert snap["pbr"] == pytest.approx(2.0)             # 1,000억 / 500억
    assert snap["market_cap_억"] == pytest.approx(1000.0)


def test_pit_valuation_loss_company_per_none(fresh_store, monkeypatch):
    """적자 기업 — PER 무의미(None), PBR·시총은 유지."""
    row = {"net_income": -1e9, "total_equity": 5e10, "total_assets": 2e11,
           "total_liabilities": 1.5e11}
    monkeypatch.setattr("src.data.dart_history.history_snapshot",
                        lambda t, y, r, engine=None: row)
    monkeypatch.setattr("src.engine.universe_select.mktcap_asof",
                        lambda t, d, engine=None: 1e11)
    snap = fresh_store.get_financials_asof("005930", "2025-04-01", CUR)
    assert snap["per"] is None
    assert snap["pbr"] == pytest.approx(2.0)
    assert snap["market_cap_억"] == pytest.approx(1000.0)


def test_annualization_factors():
    from src.data.dart_history import annualized_net_income, ratios_from_row
    row = {"net_income": 30.0, "total_equity": 400.0, "total_assets": 1200.0,
           "total_liabilities": 800.0}
    assert annualized_net_income(row, "11013") == pytest.approx(120.0)   # 1Q ×4
    assert annualized_net_income(row, "11012") == pytest.approx(60.0)    # 반기 ×2
    assert annualized_net_income(row, "11014") == pytest.approx(40.0)    # 3Q ×4/3
    assert annualized_net_income(row, "11011") == pytest.approx(30.0)
    assert ratios_from_row(row, "11013")["roe_pct"] == pytest.approx(30.0)  # 120/400
    assert ratios_from_row(row, "11013")["debt_ratio_pct"] == pytest.approx(200.0)  # BS 비연환산


def test_mock_fallback_without_key(fresh_store, monkeypatch):
    import src.data.dart_client as dc

    class NoKeyDART:
        is_configured = False

    monkeypatch.setattr(dc, "DARTClient", NoKeyDART)
    snap = fresh_store.get_financials_asof("005930", "2024-05-20", CUR)
    assert snap["_source"] == "pit_mock"            # 기존 동작 불변
    assert snap["roe_pct"] is not None


def test_mock_fallback_on_dart_error(fresh_store, monkeypatch):
    import src.data.dart_client as dc

    class BrokenDART:
        is_configured = True

        def get_financial_statement_full(self, *a, **k):
            raise RuntimeError("DART down")

    monkeypatch.setattr(dc, "DARTClient", BrokenDART)
    monkeypatch.setattr(dc, "get_corp_code", lambda code: "00126380")
    snap = fresh_store.get_financials_asof("005930", "2024-05-20", CUR)
    assert snap["_source"] == "pit_mock"


def test_dart_snapshot_cached(fresh_store, monkeypatch):
    import src.data.dart_client as dc
    fake_instances = []

    class CountingDART(FakeDART):
        def __init__(self):
            super().__init__()
            fake_instances.append(self)

    monkeypatch.setattr(dc, "DARTClient", CountingDART)
    monkeypatch.setattr(dc, "get_corp_code", lambda code: "00126380")
    fresh_store.get_financials_asof("005930", "2024-05-20", CUR)
    fresh_store.get_financials_asof("005930", "2024-05-20", CUR)  # 캐시 적중
    assert sum(len(i.calls) for i in fake_instances) == 1
