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
