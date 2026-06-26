"""DART elestock(임원·주요주주 소유보고) 파싱 + insider_net 집계 — 키 없이 픽스처로 검증."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.data.dart_client import DARTClient  # noqa: E402

# 실제 elestock.json 응답 구조 축약 픽스처
_ELESTOCK_OK = {
    "status": "000", "message": "정상",
    "list": [
        {"rcept_no": "20260610000123", "repror": "홍길동",
         "sp_stock_lmp_cnt": "100,000", "sp_stock_lmp_irds_cnt": "10,000"},
        {"rcept_no": "20260605000045", "repror": "김임원",
         "sp_stock_lmp_cnt": "5,000", "sp_stock_lmp_irds_cnt": "-2,000"},
        {"rcept_no": "20260102000077", "repror": "옛날보고",
         "sp_stock_lmp_cnt": "1,000", "sp_stock_lmp_irds_cnt": "500"},
        {"rcept_no": "20260608000099", "repror": "변동없음",
         "sp_stock_lmp_cnt": "3,000", "sp_stock_lmp_irds_cnt": "-"},
    ],
}


def test_parse_insider_rows_signed():
    rows = DARTClient._parse_insider_rows(_ELESTOCK_OK)
    # 4행 모두 파싱, 날짜 8자리 + 증감 부호 정수("-"는 0)
    by_date = {r["rcept_date"]: r["irds_cnt"] for r in rows}
    assert by_date["20260610"] == 10000
    assert by_date["20260605"] == -2000
    assert by_date["20260102"] == 500
    assert by_date["20260608"] == 0   # "-" → 0


def test_parse_insider_rows_empty_or_bad():
    assert DARTClient._parse_insider_rows({"status": "013", "message": "no data"}) == []
    assert DARTClient._parse_insider_rows({}) == []
    assert DARTClient._parse_insider_rows({"list": []}) == []


def test_get_insider_disclosures_uses_get(monkeypatch):
    c = DARTClient(api_key="x" * 20)
    monkeypatch.setattr(c, "_get", lambda endpoint, params: _ELESTOCK_OK
                        if endpoint == "elestock.json" else None)
    rows = c.get_insider_disclosures("00126380")
    assert len(rows) == 4
    assert rows[0]["rcept_date"] == "20260610"


def test_get_insider_disclosures_no_data(monkeypatch):
    c = DARTClient(api_key="x" * 20)
    monkeypatch.setattr(c, "_get", lambda endpoint, params: None)
    assert c.get_insider_disclosures("00126380") == []


def test_insider_net_window_and_price(monkeypatch):
    import src.data.insider_flows as inf
    monkeypatch.setenv("KIS_USE_MOCK", "0")  # 운영 — 실데이터 경로
    monkeypatch.setattr(inf, "get_corp_code", lambda code: "00126380")
    monkeypatch.setattr(inf, "_disclosures", lambda corp: [
        {"rcept_date": "20260610", "irds_cnt": 10000},
        {"rcept_date": "20260605", "irds_cnt": -2000},
        {"rcept_date": "20260102", "irds_cnt": 500},   # 윈도우 밖
    ])
    # as_of=2026-06-12, days=20 → 6/10·6/5 포함(8000주), 1/2 제외. price=50,000원
    net = inf.insider_net("005930", days=20, price=50000.0, as_of="20260612")
    assert net == round(8000 * 50000 / 1e8, 1)   # 4.0 억


def test_insider_net_real_mode_no_price_or_data(monkeypatch):
    import src.data.insider_flows as inf
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    monkeypatch.setattr(inf, "get_corp_code", lambda code: "00126380")
    monkeypatch.setattr(inf, "_disclosures", lambda corp: [{"rcept_date": "20260610", "irds_cnt": 10000}])
    assert inf.insider_net("005930", days=20, price=None, as_of="20260612") is None   # 가격없음→None
    monkeypatch.setattr(inf, "_disclosures", lambda corp: [])
    assert inf.insider_net("005930", days=20, price=50000.0, as_of="20260612") is None  # 데이터없음→None


def test_insider_net_mock_mode_synthetic(monkeypatch):
    import src.data.insider_flows as inf
    monkeypatch.setenv("KIS_USE_MOCK", "1")  # mock — 합성(가격·공시 무관)
    v = inf.insider_net("005930", days=20, price=None, as_of="20260612")
    assert isinstance(v, float)
