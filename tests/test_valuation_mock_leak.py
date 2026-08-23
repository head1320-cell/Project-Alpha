"""ValuationEngine.evaluate() — DART 실패 시 mock 재무제표가 조용히 새던 버그 수정 확인.

배경: dart_client.get_financial_statement_full()은 DART 호출이 실패하면(키 미설정·쿼터초과·
네트워크 에러 등) 내부적으로 항상 mock FinancialStatement(is_mock=True)로 폴백 — 절대 None을
반환하지 않는다. fundamentals_store.py는 이 플래그를 이미 방어하지만 valuation_models.py의
evaluate()는 방어가 없어, 운영(KIS_USE_MOCK=0)에서도 DART 호출 실패 시 RIM/DCF/DDM이 합성
재무로 조용히 계산되고 있었다. tests/test_realdata_only.py와 동일한 KIS_USE_MOCK 온오프
컨벤션을 따른다. 이 샌드박스엔 DART_API_KEY가 없어 get_financial_statement_full이 항상
mock으로 폴백하므로 별도 monkeypatch 없이 실제 경로를 그대로 태운다.
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.data.dart_client import DARTClient  # noqa: E402
from src.engine.valuation.valuation_models import ValuationEngine, ValuationParams  # noqa: E402


def test_mock_leak_blocked_in_real_mode(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    engine = ValuationEngine(DARTClient())
    r = engine.evaluate("005930", 70000, params=ValuationParams())
    assert r.is_mock is True
    assert r.verdict == "데이터 없음"
    assert r.intrinsic_value == 0
    assert r.models == []
    # "Unknown Corp" 금지 — stock_master.get_stock_name()로 실제 종목명 사용
    assert r.corp_name == "삼성전자"


def test_mock_transparent_in_mock_mode(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    engine = ValuationEngine(DARTClient())
    r = engine.evaluate("005930", 70000, params=ValuationParams())
    # mock 모드 — 기존처럼 RIM/DCF/DDM 계산이 정상 진행됨(회귀 불변)
    assert r.verdict != "데이터 없음"
    assert r.models
    # 단, 이제는 is_mock=True로 투명하게 표시됨
    assert r.is_mock is True


def test_unknown_corp_never_leaks_even_without_stock_master_entry(monkeypatch):
    # 마스터에 없는 임의 코드도 "Unknown"이 아니라 코드 자체로 폴백(get_stock_name이 None 반환 시)
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    engine = ValuationEngine(DARTClient())
    r = engine.evaluate("999999", 1000, params=ValuationParams())
    assert r.corp_name != "Unknown"
    assert r.corp_name == "999999"
