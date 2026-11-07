"""DART ★접수일★ 을 받는다 — 재무의 transaction time

## 무엇이 문제인가

`financials_history` 는 `(ticker, bsns_year, reprt_code)` 를 PK 로 쓰고
`ON CONFLICT ... DO UPDATE` 한다. 즉 **정정공시가 원본 보고값을 덮어쓴다.**
"그때 알려져 있던 재무" 가 영구히 사라지고, 되돌릴 수 없다.

그리고 `fetched_at` 은 **우리가 가져온 시각**이지 **DART 가 공표한 시각**이
아니다. 공표 지연을 모르므로 as-of 조회 자체가 성립하지 않는다.

지금 재무 PIT 은 **고정 시차 추정**(연간 90일 · 분기 45일)이다. 저장소가 그것을
스스로 적어 뒀다 — `company_snapshot_builder.py:159`:

    "**실제 공표일이 아니라 정적 시차 규칙으로 추정한 가용일**입니다."

## ★새 엔드포인트가 필요 없다★

감사 결과 `fnlttSinglAcnt.json` 응답의 각 항목이 **이미 `rcept_no` 를 담고 있다.**
저장소는 그것을 읽지 않을 뿐이다. 그리고 `rcept_no` 앞 8자리가 접수일(YYYYMMDD)
이라는 것을 `_parse_insider_rows`(`dart_client.py:584`)가 이미 쓰고 있다.

⇒ **DART 쿼터를 한 건도 더 쓰지 않는다.** 이미 받는 응답에서 한 필드를 더 읽는다.

## 이 파일이 거는 계약

① 재무 응답에서 접수번호·접수일을 읽는다.
② ★모르면 지어내지 않는다★ — `rcept_no` 가 없거나 형식이 다르면 `None` 이다.
   추정 접수일(기간말 + 90일)을 여기서 만들지 않는다. 그 추정은 소비자 층의
   **명시적 폴백**이지 수집 층의 값이 아니다.
③ 같은 `(연도, 보고서)` 에 접수번호가 **여럿**일 수 있다 — 그것이 정정공시이고,
   빈티지 축이다.
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.data.dart_client import DARTClient  # noqa: E402


def _fs_payload(rcept_no: str | None, *, corp_name: str = "테스트전자") -> dict:
    """`fnlttSinglAcnt.json` 응답 모양 — 실제 응답의 필드 이름을 그대로 쓴다."""
    item = {"corp_name": corp_name, "account_nm": "매출액", "thstrm_amount": "1,000"}
    if rcept_no is not None:
        item["rcept_no"] = rcept_no
    return {"status": "000", "list": [item]}


# ═══════════════════════════════════════════════════════════════════════════════
# ① 접수번호 → 접수일
# ═══════════════════════════════════════════════════════════════════════════════

def test_the_receipt_number_yields_the_filing_date():
    """★접수번호 앞 8자리가 접수일이다★ 저장소가 내부자 공시에서 이미 쓰는 규칙."""
    assert DARTClient.filing_date_of("20240315000123") == "2024-03-15"


def test_a_missing_receipt_number_is_unknown_not_estimated():
    """★미상 ≠ 추정★ 접수번호가 없으면 접수일도 없다.

    여기서 "기간말 + 90일" 을 만들어 내면, 소비자는 그것을 **실측 접수일**로
    읽는다. 추정은 소비자 층에서 라벨과 함께 붙어야 한다.
    """
    for bad in (None, "", "  ", "abcd1234", "2024031", "20241315000123"):
        assert DARTClient.filing_date_of(bad) is None, f"{bad!r} 에서 날짜를 만들어 냈다"


def test_an_impossible_date_is_rejected():
    """★그럴듯한 쓰레기를 통과시키지 않는다★ 13월·32일은 접수일이 아니다."""
    assert DARTClient.filing_date_of("20240230000001") is None   # 2월 30일
    assert DARTClient.filing_date_of("20240000000001") is None   # 0월


# ═══════════════════════════════════════════════════════════════════════════════
# ② 재무 응답에서 읽는다 — ★새 호출 없이★
# ═══════════════════════════════════════════════════════════════════════════════

def test_the_statement_carries_the_receipt_number_from_the_same_response(monkeypatch):
    """★쿼터를 더 쓰지 않는다★ 이미 받는 응답에서 한 필드를 더 읽을 뿐이다."""
    calls = {"n": 0}

    def _get(self, endpoint, params):
        calls["n"] += 1
        return _fs_payload("20250314000777")

    monkeypatch.setattr(DARTClient, "_get", _get)
    c = DARTClient(api_key="x" * 40)
    c._cache.clear()
    fs = c.get_financial_statement("00126380", "2024", "11011")
    assert fs is not None
    assert fs.rcept_no == "20250314000777", fs
    assert fs.rcept_dt == "2025-03-14", fs
    assert calls["n"] == 1, f"응답 하나에 DART 호출이 {calls['n']}회 — 쿼터를 더 썼다"


def test_a_response_without_a_receipt_number_leaves_it_unknown(monkeypatch):
    """★짝★ 이것이 없으면 "항상 채운다" 구현도 위 테스트를 통과한다."""
    monkeypatch.setattr(DARTClient, "_get", lambda self, e, p: _fs_payload(None))
    c = DARTClient(api_key="x" * 40)
    c._cache.clear()
    fs = c.get_financial_statement("00126380", "2024", "11011")
    assert fs is not None
    assert fs.rcept_no is None and fs.rcept_dt is None, fs


def test_the_financial_values_are_unchanged_by_this(monkeypatch):
    """★동작 불변★ 접수일을 읽는다고 재무 파싱이 달라지면 안 된다."""
    monkeypatch.setattr(DARTClient, "_get", lambda self, e, p: _fs_payload("20250314000777"))
    c = DARTClient(api_key="x" * 40)
    c._cache.clear()
    fs = c.get_financial_statement("00126380", "2024", "11011")
    assert fs.revenue == 1000.0, fs
    assert fs.corp_name == "테스트전자", fs


# ═══════════════════════════════════════════════════════════════════════════════
# ③ 정정공시 — 같은 기간에 접수번호가 여럿
# ═══════════════════════════════════════════════════════════════════════════════

def test_two_filings_for_one_period_are_distinguishable(monkeypatch):
    """★이것이 빈티지 축이다★ 같은 (연도, 보고서) 인데 접수번호가 다르면 정정공시다.

    지금 스키마는 그 둘을 구별하지 못해 뒤에 온 것이 앞의 것을 덮는다.
    """
    seq = ["20250314000777", "20250620000999"]

    def _get(self, endpoint, params):
        return _fs_payload(seq.pop(0))

    monkeypatch.setattr(DARTClient, "_get", _get)
    c = DARTClient(api_key="x" * 40)
    c._cache.clear()
    first = c.get_financial_statement("00126380", "2024", "11011")
    c._cache.clear()                       # 두 번째 조회 — 실제로는 며칠 뒤
    second = c.get_financial_statement("00126380", "2024", "11011")
    assert first.rcept_no != second.rcept_no
    assert first.rcept_dt == "2025-03-14" and second.rcept_dt == "2025-06-20"
