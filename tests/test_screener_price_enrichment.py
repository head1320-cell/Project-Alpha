"""_enrich_kis_quotes — 실시세로 current_price를 패치할 때 gap_pct/verdict/composite_score도
함께 재계산되는지 확인.

배경: ValuationScreener의 기본 price_provider(_mock_price)는 KIS_USE_MOCK/키 설정과 무관하게
상시 적용돼 gap_pct/verdict/composite_score가 항상 가짜 가격 기준으로 계산된다.
_enrich_kis_quotes(KIS_USE_MOCK=0 + 실키일 때만 동작)가 사후에 current_price만 실가로
패치하고 파생값을 재계산하지 않으면, 화면엔 진짜 가격이 보이는데 저평가 판정은 가짜 가격
기준인 내적 불일치가 생긴다 — 이 테스트는 그 수정을 고정한다.
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.engine.screener import ScreenerItem, ValuationScreener  # noqa: E402


def _make_item(current_price: float) -> ScreenerItem:
    return ScreenerItem(
        stock_code="005930", corp_name="삼성전자", sector=None,
        current_price=current_price, intrinsic_value=100_000,
        gap_pct=-29.0, verdict="약간 저평가",
        composite_score=50.0, gap_score=50.0, roe_score=50.0, stability_score=50.0,
        roe_pct=10.0, roa_pct=5.0, per=10.0, pbr=1.0, debt_ratio_pct=50.0,
        dividend_yield_pct=2.0, market_cap_억=4_000_000, fcf_억=1000,
    )


class _FakeRealClient:
    """MockKISClient가 아닌 '실제처럼 보이는' 클라이언트 — _enrich_kis_quotes의
    type(client).__name__=="MockKISClient" 단락을 피해서 보강 로직을 실제로 태운다."""

    def get_price(self, code: str) -> dict:
        # 극심한 고평가 구간(적정가 100,000 대비 현재가 200,000, gap +100%)로 실가를 부여 —
        # 원래 mock current_price(71,000, gap -29%)와 판정이 완전히 달라지는 값을 의도적으로 사용.
        return {"current_price": 200_000, "market_cap_억": 5_000_000, "per": 15.0, "pbr": 2.0}


def test_enrich_recomputes_gap_pct_verdict_and_score(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    monkeypatch.setattr("src.execution.kis_client.get_kis_client", lambda: _FakeRealClient())

    screener = ValuationScreener()
    item = _make_item(current_price=71_000)  # mock price_provider가 줬을 법한 값 (원래 판정: 약간 저평가)
    n = screener._enrich_kis_quotes([item])

    assert n == 1
    assert item.current_price == 200_000
    assert item.price_is_mock is False
    # 실가(200,000) 기준 gap_pct = (200000-100000)/100000*100 = +100% → "극심한 고평가"로 뒤집힘
    assert item.gap_pct == 100.0
    assert item.verdict == "극심한 고평가"
    # composite_score도 재계산됨(gap_score가 낮아지므로 원래 50.0에서 바뀜)
    assert item.composite_score != 50.0
    assert item.market_cap_억 == 5_000_000
    assert item.per == 15.0
    assert item.pbr == 2.0


def test_enrich_noop_in_mock_mode(monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    screener = ValuationScreener()
    item = _make_item(current_price=71_000)
    n = screener._enrich_kis_quotes([item])
    assert n == 0
    assert item.current_price == 71_000  # 무변화
    assert item.price_is_mock is True    # 기본값 유지(증명된 적 없음)


def test_new_item_defaults_price_is_mock_true():
    # 아무 보강도 거치지 않은 신규 ScreenerItem은 정직하게 "mock으로 간주"가 기본값
    item = _make_item(current_price=71_000)
    assert item.price_is_mock is True
    assert item.fundamentals_is_mock is False  # _to_item이 uv.is_mock으로 명시 설정하는 필드
