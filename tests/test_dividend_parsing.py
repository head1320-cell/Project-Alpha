"""DART alotMatter(배당에 관한 사항) 파싱 + 배선 — 키 없이 픽스처로 검증."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.data.dart_client import DARTClient  # noqa: E402

_ALOT_OK = {
    "status": "000", "message": "정상",
    "list": [
        {"se": "주당 현금배당금(원)", "stock_knd": "보통주", "thstrm": "1,444"},
        {"se": "주당 현금배당금(원)", "stock_knd": "우선주", "thstrm": "1,445"},
        {"se": "현금배당성향(%)", "stock_knd": "", "thstrm": "25.0"},
        {"se": "현금배당수익률(%)", "stock_knd": "보통주", "thstrm": "2.10"},
        {"se": "주당액면가액(원)", "stock_knd": "", "thstrm": "100"},
    ],
}


def test_parse_dividend_rows():
    d = DARTClient._parse_dividend_rows(_ALOT_OK)
    assert d["dps"] == 1444.0       # 보통주 우선
    assert d["payout_pct"] == 25.0
    assert d["yield_pct"] == 2.10


def test_parse_dividend_rows_empty():
    none3 = {"dps": None, "payout_pct": None, "yield_pct": None}
    assert DARTClient._parse_dividend_rows({"status": "013"}) == none3
    assert DARTClient._parse_dividend_rows({}) == none3


def test_get_dividend_info_uses_get(monkeypatch):
    c = DARTClient(api_key="x" * 20)
    monkeypatch.setattr(c, "_get", lambda endpoint, params: _ALOT_OK
                        if endpoint == "alotMatter.json" else None)
    d = c.get_dividend_info("00126380", "2025")
    assert d["dps"] == 1444.0


def test_get_financial_statement_full_sets_dps(monkeypatch):
    c = DARTClient(api_key="x" * 20)
    fsall = {"status": "000", "list": [
        {"account_nm": "매출액", "sj_div": "IS", "thstrm_amount": "1,000,000"},
        {"account_nm": "당기순이익", "sj_div": "IS", "thstrm_amount": "100,000"},
        {"account_nm": "자산총계", "sj_div": "BS", "thstrm_amount": "3,000,000"},
        {"account_nm": "부채총계", "sj_div": "BS", "thstrm_amount": "1,000,000"},
        {"account_nm": "자본총계", "sj_div": "BS", "thstrm_amount": "2,000,000"},
    ]}

    def fake_get(endpoint, params):
        if "fnlttSinglAcntAll" in endpoint:
            return fsall
        if "alotMatter" in endpoint:
            return _ALOT_OK
        return None
    monkeypatch.setattr(c, "_get", fake_get)
    fs = c.get_financial_statement_full("00126380", "2025")
    assert fs is not None
    assert fs.dps == 1444.0     # alotMatter 배선으로 실 dps 주입


# ── fundamentals_store: 0.25×NI 날조 제거, 실 현금배당성향 기반 ──
class _FakeDart:
    def __init__(self, payout):
        self._payout = payout

    def get_dividend_info(self, corp, year, reprt_code="11011"):
        return {"dps": 1000.0, "payout_pct": self._payout, "yield_pct": 2.0}


def test_real_dividend_from_payout():
    from src.data.fundamentals_store import _real_dividend
    # 현금배당성향 30% × 순이익 1000억 = 300억 (0.25×NI=250억 아님)
    assert _real_dividend(_FakeDart(30.0), "00126380", 2025, 1000.0) == 300.0


def test_real_dividend_no_disclosure_zero():
    from src.data.fundamentals_store import _real_dividend
    # 공시에 배당 없음 → 0 (무배당, 날조 0.25 제거)
    assert _real_dividend(_FakeDart(None), "x", 2025, 1000.0) == 0.0
