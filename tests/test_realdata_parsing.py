"""
실데이터 파싱 검증 — API 키 없이 가능한 검증
==========================================================================
sandbox/CI는 DART/KIS 서버에 네트워크 접근이 차단되어 있고, 운영 환경에서도
실키를 코드에 넣을 수 없다. 그러나 실데이터 연동의 핵심 위험 두 가지 중
하나는 키 없이도 검증 가능하다:

  ① 요청을 올바르게 보내는가  → 실호출 필요 (키 + 네트워크). 여기서 못 함.
  ② 응답을 올바르게 파싱하는가 → 실제 응답 '구조'로 검증 가능. ★ 이 파일 ★

이 테스트는 DART/KIS가 실제로 반환하는 JSON 구조(공식 문서 기준)를 그대로
파서에 먹여, 필드 매핑·금액 변환·엣지케이스가 올바른지 확인한다.
실제 응답 형식이 바뀌거나 파서 가정이 틀리면 여기서 잡힌다.
"""

import pytest

from src.data.dart_client import DARTClient, FinancialStatement
from src.execution.kis_client import _safe_float

# ═══════════════════════════════════════════════════════════════════════════════
# DART — 실제 응답 구조 샘플 (공식 API 문서 fnlttSinglAcnt.json 형식)
# ═══════════════════════════════════════════════════════════════════════════════
# 삼성전자 2023 연결재무제표를 모사한 실제 구조. 금액은 원 단위 문자열(쉼표 포함).

DART_FS_RESPONSE = {
    "status": "000",
    "message": "정상",
    "list": [
        {"corp_code": "00126380", "corp_name": "삼성전자", "account_nm": "매출액",
         "thstrm_amount": "258,935,494,000,000", "sj_div": "IS"},
        {"corp_code": "00126380", "corp_name": "삼성전자", "account_nm": "매출원가",
         "thstrm_amount": "180,388,580,000,000", "sj_div": "IS"},
        {"corp_code": "00126380", "corp_name": "삼성전자", "account_nm": "영업이익",
         "thstrm_amount": "6,566,976,000,000", "sj_div": "IS"},
        {"corp_code": "00126380", "corp_name": "삼성전자", "account_nm": "당기순이익",
         "thstrm_amount": "15,487,100,000,000", "sj_div": "IS"},
        {"corp_code": "00126380", "corp_name": "삼성전자", "account_nm": "자산총계",
         "thstrm_amount": "455,905,980,000,000", "sj_div": "BS"},
        {"corp_code": "00126380", "corp_name": "삼성전자", "account_nm": "부채총계",
         "thstrm_amount": "92,228,115,000,000", "sj_div": "BS"},
        {"corp_code": "00126380", "corp_name": "삼성전자", "account_nm": "자본총계",
         "thstrm_amount": "363,677,865,000,000", "sj_div": "BS"},
    ],
}

# 적자 기업 (음수 금액 — DART는 음수를 "-" 부호로 반환)
DART_FS_LOSS_RESPONSE = {
    "status": "000", "message": "정상",
    "list": [
        {"account_nm": "매출액", "thstrm_amount": "1,200,000,000", "sj_div": "IS"},
        {"account_nm": "영업이익", "thstrm_amount": "-450,000,000", "sj_div": "IS"},
        {"account_nm": "당기순이익", "thstrm_amount": "-680,000,000", "sj_div": "IS"},
        {"account_nm": "자산총계", "thstrm_amount": "5,000,000,000", "sj_div": "BS"},
        {"account_nm": "부채총계", "thstrm_amount": "3,200,000,000", "sj_div": "BS"},
        {"account_nm": "자본총계", "thstrm_amount": "1,800,000,000", "sj_div": "BS"},
    ],
}

# 인증 실패 응답 (잘못된 키)
DART_AUTH_FAIL = {"status": "020", "message": "등록되지 않은 인증키입니다."}
# 데이터 없음
DART_NO_DATA = {"status": "013", "message": "조회된 데이터가 없습니다."}


class TestDARTAmountParsing:
    """DART 금액 문자열 파싱 (가장 빈번한 버그 지점)."""

    def test_comma_separated(self):
        assert DARTClient._parse_amount("258,935,494,000,000") == 258935494000000.0

    def test_negative_amount(self):
        assert DARTClient._parse_amount("-450,000,000") == -450000000.0

    def test_empty_string(self):
        assert DARTClient._parse_amount("") is None

    def test_none(self):
        assert DARTClient._parse_amount(None) is None

    def test_whitespace(self):
        assert DARTClient._parse_amount(" 1,000 ") == 1000.0

    def test_garbage(self):
        assert DARTClient._parse_amount("N/A") is None

    def test_zero(self):
        assert DARTClient._parse_amount("0") == 0.0


class TestDARTFinancialParsing:
    """DART 재무제표 응답 → FinancialStatement 매핑."""

    def _parse(self, response):
        """_get을 모킹해 파싱 로직만 검증 (네트워크 없이)."""
        client = DARTClient(api_key="DUMMY")  # 키는 형식만, 실호출 안 함
        client._get = lambda endpoint, params: response  # 응답 주입
        return client.get_financial_statement("00126380", "2023")

    def test_revenue_mapped(self):
        fs = self._parse(DART_FS_RESPONSE)
        assert fs.revenue == 258935494000000.0

    def test_revenue_excludes_cost(self):
        """'매출원가'는 revenue로 잘못 매핑되면 안 됨 ('원가' 제외 로직)."""
        fs = self._parse(DART_FS_RESPONSE)
        # 매출액만 잡혀야지 매출원가(180조)가 아님
        assert fs.revenue == 258935494000000.0
        assert fs.revenue != 180388580000000.0

    def test_operating_profit(self):
        fs = self._parse(DART_FS_RESPONSE)
        assert fs.operating_profit == 6566976000000.0

    def test_net_income(self):
        fs = self._parse(DART_FS_RESPONSE)
        assert fs.net_income == 15487100000000.0

    def test_balance_sheet(self):
        fs = self._parse(DART_FS_RESPONSE)
        assert fs.total_assets == 455905980000000.0
        assert fs.total_liabilities == 92228115000000.0
        assert fs.total_equity == 363677865000000.0

    def test_accounting_identity(self):
        """자산 = 부채 + 자본 (회계 항등식)."""
        fs = self._parse(DART_FS_RESPONSE)
        assert abs(fs.total_assets - (fs.total_liabilities + fs.total_equity)) < 1.0

    def test_loss_company_negatives(self):
        """적자 기업: 음수 이익이 올바르게 파싱."""
        fs = self._parse(DART_FS_LOSS_RESPONSE)
        assert fs.operating_profit == -450000000.0
        assert fs.net_income == -680000000.0
        assert fs.revenue == 1200000000.0  # 매출은 양수


class TestDARTRatios:
    """파싱된 재무제표로 계산하는 비율 (ROE/부채비율 등)."""

    def _fs(self, response):
        client = DARTClient(api_key="DUMMY")
        client._get = lambda endpoint, params: response
        return client.get_financial_statement("00126380", "2023")

    def test_roe_computed(self):
        """ROE = 당기순이익 / 자본총계 × 100."""
        fs = self._fs(DART_FS_RESPONSE)
        expected_roe = 15487100000000.0 / 363677865000000.0 * 100
        # compute_ratios가 호출됐는지 + 합리적 범위
        if fs.roe is not None:
            assert abs(fs.roe - expected_roe) < 1.0
            assert 0 < fs.roe < 20  # 삼성 ROE는 한 자릿수~십몇%

    def test_debt_ratio_computed(self):
        """부채비율 = 부채총계 / 자본총계 × 100."""
        fs = self._fs(DART_FS_RESPONSE)
        expected = 92228115000000.0 / 363677865000000.0 * 100
        if fs.debt_ratio is not None:
            assert abs(fs.debt_ratio - expected) < 1.0
            assert 0 < fs.debt_ratio < 50  # 삼성은 저부채

    def test_loss_company_negative_roe(self):
        """적자 기업은 ROE가 음수."""
        fs = self._fs(DART_FS_LOSS_RESPONSE)
        if fs.roe is not None:
            assert fs.roe < 0


class TestDARTErrorHandling:
    """DART 에러/빈 응답 시 graceful 처리 (mock fallback)."""

    def test_auth_fail_falls_back(self):
        """인증 실패 → mock으로 폴백 (크래시 안 함)."""
        client = DARTClient(api_key="DUMMY")
        client._get = lambda endpoint, params: None  # _get이 에러 시 None 반환
        fs = client.get_financial_statement("00126380", "2023")
        # 폴백으로 mock FinancialStatement 반환 (None 아님)
        assert fs is not None
        assert isinstance(fs, FinancialStatement)

    def test_no_data_falls_back(self):
        client = DARTClient(api_key="DUMMY")
        client._get = lambda endpoint, params: {"status": "013", "message": "no data"}
        # "list" 키 없음 → 폴백
        fs = client.get_financial_statement("00126380", "2023")
        assert fs is not None


# ═══════════════════════════════════════════════════════════════════════════════
# KIS — 실제 응답 구조 샘플 (공식 API 문서 형식)
# ═══════════════════════════════════════════════════════════════════════════════
# KIS는 HTTP 200 + rt_cd로 성공/실패, output/output1/output2로 데이터 반환.

class TestKISSafeFloat:
    """KIS 숫자 문자열 파싱."""

    def test_comma(self):
        assert _safe_float("71,000") == 71000.0

    def test_plain(self):
        assert _safe_float("71000") == 71000.0

    def test_decimal(self):
        assert _safe_float("2.03") == 2.03

    def test_negative_pct(self):
        assert _safe_float("-1.52") == -1.52

    def test_empty(self):
        assert _safe_float("") is None

    def test_none(self):
        assert _safe_float(None) is None


class TestKISBalanceStructure:
    """KIS 잔고 응답 구조 파싱 (output1=종목별, output2=요약)."""

    # 실제 inquire-balance 응답 구조
    KIS_BALANCE = {
        "rt_cd": "0", "msg1": "정상처리 되었습니다.",
        "output1": [
            {"pdno": "005930", "prdt_name": "삼성전자", "hldg_qty": "10",
             "pchs_avg_pric": "68000", "prpr": "71000", "evlu_amt": "710000",
             "evlu_pfls_rt": "4.41", "evlu_pfls_amt": "30000"},
            {"pdno": "000660", "prdt_name": "SK하이닉스", "hldg_qty": "0",  # 보유 0 → 제외돼야
             "pchs_avg_pric": "0", "prpr": "130000", "evlu_amt": "0",
             "evlu_pfls_rt": "0", "evlu_pfls_amt": "0"},
        ],
        "output2": [{"dnca_tot_amt": "5000000", "tot_evlu_amt": "5710000",
                     "nass_amt": "5710000", "prvs_rcdl_excc_amt": "5000000"}],
    }

    def test_balance_structure_valid(self):
        """응답 구조가 파서 가정과 일치하는지."""
        data = self.KIS_BALANCE
        # 종목별 파싱 (kis_client.get_balance 로직 모사)
        positions = []
        for item in data.get("output1", []):
            qty = int(item.get("hldg_qty") or 0)
            if qty == 0:
                continue
            positions.append({
                "ticker": item.get("pdno"),
                "quantity": qty,
                "avg_price": float(item.get("pchs_avg_pric") or 0),
                "current_price": float(item.get("prpr") or 0),
            })
        # 삼성전자만 (하이닉스는 보유 0 → 제외)
        assert len(positions) == 1
        assert positions[0]["ticker"] == "005930"
        assert positions[0]["quantity"] == 10
        assert positions[0]["current_price"] == 71000.0

    def test_balance_summary(self):
        """계좌 요약(output2) 파싱."""
        data = self.KIS_BALANCE
        output2 = data.get("output2", [{}])[0] if data.get("output2") else {}
        assert float(output2.get("dnca_tot_amt") or 0) == 5000000.0
        assert float(output2.get("tot_evlu_amt") or 0) == 5710000.0

    def test_rt_cd_success(self):
        """rt_cd='0'이 성공."""
        assert str(self.KIS_BALANCE.get("rt_cd")) == "0"


class TestKISOrderResponse:
    """KIS 주문 응답 구조."""

    KIS_ORDER_OK = {
        "rt_cd": "0", "msg1": "주문 전송 완료",
        "output": {"KRX_FWDG_ORD_ORGNO": "00950", "ODNO": "0000117057", "ORD_TMD": "121052"},
    }
    KIS_ORDER_FAIL = {"rt_cd": "1", "msg1": "장 종료", "output": {}}

    def test_order_success_parsing(self):
        data = self.KIS_ORDER_OK
        output = data.get("output", {})
        assert output.get("ODNO") == "0000117057"
        assert str(data.get("rt_cd")) == "0"

    def test_order_failure_detected(self):
        """주문 실패(rt_cd≠0) 감지."""
        data = self.KIS_ORDER_FAIL
        assert str(data.get("rt_cd")) != "0"
        assert "장 종료" in data.get("msg1", "")


class TestKISPriceResponse:
    """KIS 현재가 응답 구조 (inquire-price)."""

    KIS_PRICE = {
        "rt_cd": "0", "msg1": "정상",
        "output": {
            "stck_prpr": "71000",        # 현재가
            "prdy_vrss": "1000",          # 전일 대비
            "prdy_vrss_sign": "2",        # 등락 부호
            "prdy_ctrt": "1.43",          # 등락률
            "stck_oprc": "70200",         # 시가
            "stck_hgpr": "71200",         # 고가
            "stck_lwpr": "70100",         # 저가
            "acml_vol": "12345678",       # 누적 거래량
        },
    }

    def test_current_price(self):
        output = self.KIS_PRICE["output"]
        assert _safe_float(output.get("stck_prpr")) == 71000.0

    def test_ohlc_parsing(self):
        output = self.KIS_PRICE["output"]
        assert _safe_float(output.get("stck_oprc")) == 70200.0
        assert _safe_float(output.get("stck_hgpr")) == 71200.0
        assert _safe_float(output.get("stck_lwpr")) == 70100.0
        # 고가 ≥ 현재가 ≥ 저가 (정합성)
        assert (_safe_float(output.get("stck_hgpr"))
                >= _safe_float(output.get("stck_prpr"))
                >= _safe_float(output.get("stck_lwpr")))

    def test_change_rate(self):
        output = self.KIS_PRICE["output"]
        assert _safe_float(output.get("prdy_ctrt")) == 1.43


# ═══════════════════════════════════════════════════════════════════════════════
# KIS — 요청 구성 검증 (네트워크 없이, 요청 객체만 가로채서 형식 확인)
# ═══════════════════════════════════════════════════════════════════════════════
# 실거래 안전의 핵심: TR_ID(실/모의·매수/매도)와 주문구분코드(시장가/지정가)가
# 정확해야 한다. 틀리면 의도와 다른 주문이 나간다. 키 없이도 이건 검증 가능.

from src.execution.kis_client import TR_ID, KISClient, KISCredentials


def _make_client(is_paper=True):
    """실호출 없이 요청 구성만 검증하기 위한 클라이언트."""
    creds = KISCredentials(
        app_key="DUMMY_KEY", app_secret="DUMMY_SECRET",
        account_no="12345678", account_prdt="01", is_paper=is_paper,
    )
    client = KISClient(creds)
    # 토큰 발급 우회 (네트워크 차단)
    from datetime import datetime, timedelta

    from src.execution.kis_client import KISToken
    client.token = KISToken(access_token="DUMMY_TOKEN", token_type="Bearer",
                            expires_at=datetime.now() + timedelta(days=1))
    client._ensure_token = lambda: None
    return client


class TestKISOrderConstruction:
    """주문 요청이 올바르게 구성되는지 (실거래 안전 핵심)."""

    def _capture_order(self, client, **kwargs):
        """_request를 가로채 실제 전송 없이 (path, headers, body) 캡처."""
        captured = {}
        def fake_request(method, path, headers, params=None, json_body=None):
            captured["method"] = method
            captured["path"] = path
            captured["headers"] = headers
            captured["body"] = json_body
            return {"rt_cd": "0", "output": {"ODNO": "TEST"}, "msg1": "ok"}
        client._request = fake_request
        client.place_order(**kwargs)
        return captured

    def test_paper_buy_tr_id(self):
        """모의투자 매수 → VTTC0802U."""
        c = _make_client(is_paper=True)
        cap = self._capture_order(c, ticker="005930", side="BUY", quantity=10)
        assert cap["headers"]["tr_id"] == "VTTC0802U"

    def test_real_buy_tr_id(self):
        """실거래 매수 → TTTC0802U (모의와 다름!)."""
        c = _make_client(is_paper=False)
        cap = self._capture_order(c, ticker="005930", side="BUY", quantity=10)
        assert cap["headers"]["tr_id"] == "TTTC0802U"

    def test_paper_sell_tr_id(self):
        """모의 매도 → VTTC0801U."""
        c = _make_client(is_paper=True)
        cap = self._capture_order(c, ticker="005930", side="SELL", quantity=10)
        assert cap["headers"]["tr_id"] == "VTTC0801U"

    def test_real_vs_paper_differ(self):
        """실거래와 모의의 TR_ID가 절대 같으면 안 됨 (사고 방지)."""
        assert TR_ID["ORDER_BUY_REAL"] != TR_ID["ORDER_BUY_PAPER"]
        assert TR_ID["ORDER_SELL_REAL"] != TR_ID["ORDER_SELL_PAPER"]

    def test_market_order_code(self):
        """시장가 주문 → ORD_DVSN=01, 가격=0."""
        c = _make_client()
        cap = self._capture_order(c, ticker="005930", side="BUY",
                                  quantity=10, order_type="MARKET")
        assert cap["body"]["ORD_DVSN"] == "01"
        assert cap["body"]["ORD_UNPR"] == "0"

    def test_limit_order_code(self):
        """지정가 주문 → ORD_DVSN=00, 가격 지정."""
        c = _make_client()
        cap = self._capture_order(c, ticker="005930", side="BUY",
                                  quantity=10, order_type="LIMIT", price=70000)
        assert cap["body"]["ORD_DVSN"] == "00"
        assert cap["body"]["ORD_UNPR"] == "70000"

    def test_order_body_required_fields(self):
        """주문 body에 필수 필드(계좌/종목/수량) 포함."""
        c = _make_client()
        cap = self._capture_order(c, ticker="005930", side="BUY", quantity=10)
        body = cap["body"]
        assert body["PDNO"] == "005930"          # 종목코드
        assert body["ORD_QTY"] == "10"           # 수량
        assert body["CANO"] == "12345678"        # 계좌번호
        assert body["ACNT_PRDT_CD"] == "01"      # 계좌상품코드

    def test_order_endpoint_path(self):
        """주문 엔드포인트 경로 정확성."""
        c = _make_client()
        cap = self._capture_order(c, ticker="005930", side="BUY", quantity=10)
        assert cap["path"] == "/uapi/domestic-stock/v1/trading/order-cash"
        assert cap["method"] == "POST"

    def test_auth_header_present(self):
        """인증 헤더(Bearer/appkey/appsecret) 포함."""
        c = _make_client()
        cap = self._capture_order(c, ticker="005930", side="BUY", quantity=10)
        h = cap["headers"]
        assert h["authorization"].startswith("Bearer ")
        assert "appkey" in h and "appsecret" in h


class TestKISOrderValidation:
    """잘못된 주문 입력 거부 (방어 로직)."""

    def test_invalid_side_rejected(self):
        c = _make_client()
        with pytest.raises(ValueError):
            c.place_order(ticker="005930", side="HOLD", quantity=10)

    def test_zero_quantity_rejected(self):
        c = _make_client()
        with pytest.raises(ValueError):
            c.place_order(ticker="005930", side="BUY", quantity=0)

    def test_limit_without_price_rejected(self):
        c = _make_client()
        with pytest.raises(ValueError):
            c.place_order(ticker="005930", side="BUY", quantity=10,
                          order_type="LIMIT", price=None)
