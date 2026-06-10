#!/usr/bin/env python3
"""
verify_connection.py — DART + KIS 실데이터 연동 검증
==========================================================================
배포 서버에서 .env에 키를 넣은 뒤 실행:

    python verify_connection.py
    python verify_connection.py --stock 000660   # 다른 종목

각 데이터 소스를 단계별로 점검하고, 실제 재무·시세가 뜨는지 확인합니다.
키가 없거나 mock 모드면 그 사실을 명확히 알려줍니다.

────────────────────────────────────────────────────────────────────────
※ 키가 없어도 가능한 검증 (네트워크/키 불필요):
    pytest tests/test_realdata_parsing.py -v

  이 테스트는 DART/KIS가 실제로 반환하는 JSON 구조를 파서에 먹여
  ① 재무제표 필드 매핑(매출/영업이익/자산 등), ② 금액 변환(쉼표·음수),
  ③ KIS 주문 요청 구성(실거래/모의 TR_ID 구분, 시장가/지정가),
  ④ 잔고·시세 응답 파싱이 올바른지 확인합니다.

  실데이터 연동의 위험은 (a)요청을 맞게 보내는가 (b)응답을 맞게 읽는가인데,
  (b)와 (a)의 형식 정확성은 키 없이 위 테스트로 검증됩니다.
  이 스크립트(verify_connection.py)는 (a)의 실제 도달까지 — 즉 실키로
  서버에 붙어 실제 값이 오는지 — 최종 확인하는 용도입니다.
────────────────────────────────────────────────────────────────────────
"""

import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# .env 로드 (python-dotenv 있으면 사용)
try:
    from dotenv import load_dotenv
    load_dotenv()
    _DOTENV = True
except ImportError:
    _DOTENV = False


GREEN = "\033[92m"; RED = "\033[91m"; YELLOW = "\033[93m"; BLUE = "\033[94m"; BOLD = "\033[1m"; END = "\033[0m"

def ok(msg):    print(f"  {GREEN}✓{END} {msg}")
def fail(msg):  print(f"  {RED}✗{END} {msg}")
def warn(msg):  print(f"  {YELLOW}⚠{END} {msg}")
def head(msg):  print(f"\n{BOLD}{BLUE}{msg}{END}")


def check_env():
    head("【0】 환경변수 점검")
    if not _DOTENV:
        warn("python-dotenv 미설치 — 시스템 환경변수만 읽음 (pip install python-dotenv 권장)")
    dart = os.getenv("DART_API_KEY", "")
    kis_mock = os.getenv("KIS_USE_MOCK", "1")
    kis_paper = os.getenv("KIS_IS_PAPER", "1")
    kis_key = os.getenv("KIS_APP_KEY", "")
    kis_secret = os.getenv("KIS_APP_SECRET", "")

    if dart:
        ok(f"DART_API_KEY 설정됨 ({dart[:6]}...{dart[-4:]}, {len(dart)}자)")
    else:
        fail("DART_API_KEY 미설정 → 재무 팩터가 mock으로 동작")

    print(f"  · KIS_USE_MOCK={kis_mock}  KIS_IS_PAPER={kis_paper}")
    if kis_mock == "1":
        warn("KIS_USE_MOCK=1 → KIS 시세가 mock으로 동작 (실데이터 보려면 0으로)")
    else:
        if kis_key and kis_secret:
            mode = "모의투자" if kis_paper == "1" else "실계좌"
            ok(f"KIS 키 설정됨 ({kis_key[:6]}..., {mode} 모드)")
        else:
            fail("KIS_USE_MOCK=0 인데 KIS_APP_KEY/SECRET 미설정")
    return dart, kis_mock, kis_key, kis_secret


def check_dart(stock_code):
    head(f"【1】 DART 재무제표 — {stock_code}")
    try:
        from src.data.dart_client import DARTClient, get_corp_code
    except Exception as e:
        fail(f"DART 모듈 import 실패: {e}")
        return False

    dart = DARTClient()
    if not dart.is_configured:
        fail("DART 미설정 (키 없음) → mock fallback 상태")
        return False

    corp_code = get_corp_code(stock_code)
    if not corp_code:
        fail(f"종목코드 {stock_code}의 DART corp_code를 찾을 수 없음")
        warn("CORP_CODE 매핑 테이블 확인 필요 (corpCode.xml)")
        return False
    ok(f"corp_code 매핑: {stock_code} → {corp_code}")

    # 종목명 캐시 생성 (전체 상장사 코드→이름)
    try:
        from src.data.stock_master import build_corp_name_cache_from_dart
        n = build_corp_name_cache_from_dart()
        if n > 0:
            ok(f"종목명 캐시 생성: {n}개 상장사 (Unknown Corp 박멸)")
    except Exception:
        pass

    from datetime import datetime
    year = datetime.now().year - 1
    fs = dart.get_financial_statement_full(corp_code, str(year))
    if fs is None or fs.revenue is None:
        warn(f"{year}년 데이터 없음 → {year-1}년 재시도")
        fs = dart.get_financial_statement_full(corp_code, str(year - 1))
    if fs is None or fs.revenue is None:
        fail("재무제표 조회 실패")
        return False

    E8 = 1e8
    ok(f"재무제표 조회 성공 ({fs.bsns_year}년, 연결)")
    print(f"      매출액:     {(fs.revenue/E8):>12,.0f} 억원")
    print(f"      영업이익:   {(fs.operating_profit/E8) if fs.operating_profit else 0:>12,.0f} 억원")
    print(f"      당기순이익: {(fs.net_income/E8) if fs.net_income else 0:>12,.0f} 억원")
    print(f"      자산총계:   {(fs.total_assets/E8) if fs.total_assets else 0:>12,.0f} 억원")
    if fs.gross_profit:
        print(f"      매출총이익: {(fs.gross_profit/E8):>12,.0f} 억원 (GP/A 계산용)")
    if fs.current_assets:
        print(f"      유동자산:   {(fs.current_assets/E8):>12,.0f} 억원 (유동비율용)")
    return True


def check_kis(stock_code, kis_mock):
    head(f"【2】 KIS 시세 — {stock_code}")
    if kis_mock == "1":
        warn("KIS_USE_MOCK=1 → 실시세 미조회 (mock). 실데이터 검증하려면 .env에서 KIS_USE_MOCK=0")
        return False
    try:
        from src.execution.kis_client import get_kis_client
    except Exception as e:
        fail(f"KIS 모듈 import 실패: {e}")
        return False

    client = get_kis_client()
    if type(client).__name__ == "MockKISClient":
        fail("MockKISClient로 fallback됨 (키 확인 필요)")
        return False

    # 현재가
    try:
        q = client.get_price(stock_code)
        if q.get("current_price"):
            ok(f"현재가 조회: {q['name'] or stock_code} {q['current_price']:,.0f}원 ({q['change_pct']:+.2f}%)")
            if q.get("market_cap_억"):
                print(f"      시가총액: {q['market_cap_억']:,.0f} 억원")
            if q.get("per") is not None:
                print(f"      PER {q['per']} · PBR {q['pbr']} · EPS {q['eps']}")
        else:
            fail("현재가 0 — 조회 실패")
            return False
    except Exception as e:
        fail(f"현재가 조회 오류: {e}")
        return False

    # 일봉 (백테스트/기술지표용)
    try:
        ohlcv = client.get_daily_ohlcv(stock_code, days=60)
        if ohlcv and len(ohlcv) >= 30:
            ok(f"일봉 조회: {len(ohlcv)}일 (최근 {ohlcv[-1]['date']} 종가 {ohlcv[-1]['close']:,.0f})")
        else:
            warn(f"일봉 {len(ohlcv) if ohlcv else 0}일 — 모의투자는 기간 제약 가능 (실전 키 권장)")
    except Exception as e:
        fail(f"일봉 조회 오류: {e}")
    return True


def check_integration(stock_code, dart_ok, kis_ok):
    head(f"【3】 통합 — 실데이터 기반 학술 팩터")
    try:
        from src.data.fundamentals_store import FundamentalsStore
    except Exception as e:
        fail(f"fundamentals_store import 실패: {e}")
        return

    store = FundamentalsStore.get_default()
    store._cache.clear() if hasattr(store, "_cache") else None
    f = store.get_factors(stock_code)
    src = f.get("_source", "?")
    if src == "dart_real":
        ok(f"펀더멘털 팩터 = {GREEN}실제 DART 데이터{END}")
    else:
        warn(f"펀더멘털 팩터 = mock (source={src}) — DART 키 설정 시 실데이터로 전환")

    print(f"      GP/A (Novy-Marx):    {f.get('gp_to_assets')}")
    print(f"      ROIC:                {f.get('roic')}%")
    print(f"      영업이익률:          {f.get('operating_margin')}%")
    print(f"      Altman Z-Score:      {f.get('altman_z')}")
    print(f"      Piotroski F-Score:   {f.get('piotroski_f')}/9")
    print(f"      EV/EBITDA:           {f.get('ev_ebitda')}")
    print(f"      매출성장률(YoY):     {f.get('revenue_growth_yoy')}%")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stock", default="005930", help="검증할 종목코드 (기본 삼성전자)")
    args = ap.parse_args()
    code = args.stock

    print(f"{BOLD}{'='*64}{END}")
    print(f"{BOLD}  Project Alpha — 실데이터 연동 검증{END}")
    print(f"{BOLD}  종목: {code}{END}")
    print(f"{BOLD}{'='*64}{END}")

    dart, kis_mock, kis_key, kis_secret = check_env()
    dart_ok = check_dart(code)
    kis_ok = check_kis(code, kis_mock)
    check_integration(code, dart_ok, kis_ok)

    head("【결과 요약】")
    print(f"  DART 재무:  {GREEN+'실데이터 ✓'+END if dart_ok else YELLOW+'mock'+END}")
    print(f"  KIS 시세:   {GREEN+'실데이터 ✓'+END if kis_ok else YELLOW+'mock'+END}")
    if dart_ok and kis_ok:
        print(f"\n  {GREEN}{BOLD}✓ 완전 실데이터 연동 성공 — 실투자 분석 가능 상태{END}")
    elif dart_ok or kis_ok:
        print(f"\n  {YELLOW}{BOLD}△ 부분 연동 — 위 ✗/⚠ 항목 확인{END}")
    else:
        print(f"\n  {YELLOW}{BOLD}△ 전부 mock — .env에 키를 넣고 KIS_USE_MOCK=0 설정하세요{END}")
    print()


if __name__ == "__main__":
    main()
