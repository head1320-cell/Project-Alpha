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

import argparse
import os
import sys

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


def check_network():
    """키 없이 DART/KIS 서버 도달성만 점검 — 방화벽/프록시 문제와 키 문제를 분리 진단.

    실서버는 키가 틀려도 JSON 에러를 돌려준다. JSON이 안 오면(프록시 HTML/타임아웃)
    네트워크 차단이다. 샌드박스/사내망에서 "키를 넣어도 안 되는" 원인을 즉시 구분."""
    head("【0.5】 네트워크 도달성 (키 불필요)")
    try:
        import httpx
    except ImportError:
        warn("httpx 미설치 — 도달성 점검 생략 (pip install httpx)")
        return

    # DART: 잘못된 키로 호출해도 실서버면 JSON status(010=미등록 키)가 온다
    try:
        r = httpx.get("https://opendart.fss.or.kr/api/fnlttSinglAcnt.json",
                      params={"crtfc_key": "connectivity-probe"}, timeout=8)
        d = r.json()
        ok(f"DART 서버 도달 (status={d.get('status')}) — 방화벽 통과, 키만 넣으면 됨")
    except Exception as e:
        fail(f"DART 서버 도달 실패 ({type(e).__name__}) — 방화벽/프록시 차단. 키 문제 아님")

    # KIS: 토큰 엔드포인트에 빈 요청 → 실서버면 JSON 에러 응답 (포트 9443/29443 주의)
    try:
        from src.execution.kis_client import KIS_BASE_URL_PAPER, KIS_BASE_URL_REAL
    except Exception:
        KIS_BASE_URL_REAL = "https://openapi.koreainvestment.com:9443"
        KIS_BASE_URL_PAPER = "https://openapivts.koreainvestment.com:29443"
    base = KIS_BASE_URL_PAPER if os.getenv("KIS_IS_PAPER", "1") == "1" else KIS_BASE_URL_REAL
    host = base.split("//")[1]
    try:
        r = httpx.post(f"{base}/oauth2/tokenP", json={}, timeout=8)
        r.json()
        ok(f"KIS 서버 도달 ({host}, HTTP {r.status_code}) — 방화벽 통과, 키만 넣으면 됨")
    except Exception as e:
        fail(f"KIS 서버 도달 실패 ({host}, {type(e).__name__}) — 방화벽/프록시 차단 또는 포트 미개방")


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
    head("【3】 통합 — 실데이터 기반 학술 팩터")
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


def check_backtest_flow(stock_code, kis_mock):
    """백테스터 실데이터 흐름 — 통합 로더·지수·OHLC 컬럼 무결성.

    체결가 13종(시가/고저가/피벗), 돌파매수(전일 고가), ATR 비중(고저폭),
    마켓타이밍·벤치마크(지수 일봉)가 전부 이 경로의 컬럼을 사용한다."""
    head("【4】 백테스터 실데이터 흐름 — OHLCV·지수")
    try:
        from src.data.ohlcv_loader import load_ohlcv_unified
    except Exception as e:
        fail(f"ohlcv_loader import 실패: {e}")
        return

    from datetime import datetime, timedelta
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=120)).strftime("%Y-%m-%d")

    # (a) 종목 일봉 — mock 모드면 mock 직행(DB 시도 소음 차단), 실모드면 auto(DB→KIS)
    prefer = "mock" if kis_mock == "1" else "auto"
    df = load_ohlcv_unified(stock_code, start, end, prefer=prefer)
    if df is None or df.empty:
        fail("종목 OHLCV 로드 실패 — 백테스트 불가")
        return
    label = "mock (KIS_USE_MOCK=1)" if kis_mock == "1" else "DB/KIS 실데이터 경로"
    ok(f"종목 일봉 {len(df)}봉 ({df.index[0].date()} ~ {df.index[-1].date()}) · 출처: {label}")

    if kis_mock != "1":
        kdf = load_ohlcv_unified(stock_code, start, end, prefer="kis")
        if kdf is not None and not kdf.empty:
            ok(f"KIS 직접 경로 일봉 {len(kdf)}봉 — 실시세 수신 확인")
        else:
            warn("KIS 직접 경로 빈 응답 — 키/모의투자 기간 제약 확인")

    # (b) OHLC 컬럼 무결성 — 체결가·돌파매수·ATR 비중의 전제
    missing = {"open", "high", "low", "close", "volume"} - set(df.columns)
    if missing:
        fail(f"누락 컬럼 {missing} — 체결가 유형/돌파매수/ATR 비중 사용 불가")
    else:
        sane = bool((df["high"] >= df["low"]).all() and (df["high"] >= df["close"]).all()
                    and (df["low"] <= df["close"]).all())
        if sane:
            ok("OHLC 무결성 (고가≥종가≥저가) — 체결가 13종·돌파매수·ATR 비중 사용 가능")
        else:
            warn("OHLC 정합성 위반 행 존재 — 데이터 소스 점검 필요")

    # (c) 지수 일봉 — 마켓타이밍·벤치마크 경로
    idx_df = load_ohlcv_unified("KOSPI", start, end, prefer=prefer)
    if idx_df is not None and not idx_df.empty:
        ok(f"지수(KOSPI) 일봉 {len(idx_df)}봉 — 마켓타이밍·벤치마크 경로 정상")
        if kis_mock == "1":
            warn("mock 지수는 합성 곡선 — 실데이터에서 마켓타이밍/벤치마크가 의미값")
    else:
        warn("지수(KOSPI) 로드 실패 — 마켓타이밍은 미개입(fail-open), 벤치마크는 대형주 프록시 폴백")

    # (d) 종목마스터 플래그 캐시 — 전종목 유니버스·관리/감리 제외의 데이터원 (키 불필요)
    try:
        from src.data.stock_master import MANAGED_CODES, SUPERVISED_CODES, load_master_flags
        flags = load_master_flags()
        if flags:
            ok(f"마스터 플래그 캐시 {len(flags)}종목 · 관리/정지 {len(MANAGED_CODES)} · "
               f"투자주의 {len(SUPERVISED_CODES)} — 전종목 유니버스·관리/감리 제외 활성")
        else:
            warn("마스터 플래그 캐시 없음 — POST /api/v1/symbols/collect-master 1회 실행 시 "
                 "전종목(~2,700)·관리/감리 제외 활성 (인증 불필요)")
    except Exception as e:
        warn(f"마스터 플래그 조회 실패: {e}")


def check_krx():
    """KRX OpenAPI — 도달성(키 불필요) → 키 검증(전종목 1콜 sanity) → DB 적재 현황."""
    head("【5】 KRX OpenAPI — 장기 백테스트 적재")
    key = os.getenv("KRX_API_KEY", "")
    from datetime import datetime, timedelta

    # (a) 도달성 — 더미 키로도 실서버면 JSON(에러 포함)이 온다
    try:
        import httpx

        from src.data.krx_client import KRX_BASE_URL
        r = httpx.get(f"{KRX_BASE_URL}/sto/stk_bydd_trd",
                      params={"basDd": "20240105"},
                      headers={"AUTH_KEY": key or "connectivity-probe"}, timeout=8)
        r.json()
        ok(f"KRX 서버 도달 (HTTP {r.status_code}) — 방화벽 통과")
    except Exception as e:
        fail(f"KRX 서버 도달 실패 ({type(e).__name__}) — 방화벽/프록시 차단. 키 문제 아님")

    # (b) 키 검증 — 최근 평일 전종목 1콜 (행 수 + 삼성전자 종가로 필드 매핑 정합 확인)
    if not key:
        fail("KRX_API_KEY 미설정 → 장기 백필 불가 (.env에 키 입력)")
    else:
        try:
            from src.data.krx_client import KRXClient
            client = KRXClient()
            rows = []
            d = datetime.now() - timedelta(days=1)
            for _ in range(7):  # 휴장 대비 최근 평일 역순 시도
                if d.weekday() < 5:
                    rows = client.get_daily_all("KOSPI", d.strftime("%Y-%m-%d"))
                    if rows:
                        break
                d -= timedelta(days=1)
            if rows:
                ss = next((r for r in rows if r["ticker"] == "005930"), None)
                ok(f"KOSPI 전종목 수신: {len(rows)}행 ({d.strftime('%Y-%m-%d')})")
                if ss and ss["close"] > 0:
                    ok(f"필드 매핑 정합: 삼성전자 종가 {ss['close']:,.0f} · 시총 {(ss.get('mktcap') or 0)/1e12:,.1f}조")
                else:
                    warn("삼성전자 행 미발견 — 필드 코드 매핑 점검 필요 (ISU_CD 형식)")
                if len(rows) < 800:
                    warn(f"행 수 {len(rows)} < 800 — 응답 구조/엔드포인트 확인 권장")
            else:
                fail("전종목 수신 실패 — 키 유효성·승인 상태·쿼터 확인")
        except Exception as e:
            fail(f"KRX 호출 오류: {e}")

    # (c) DB 적재 현황 — 백테스트가 실제로 읽는 데이터
    try:
        from sqlalchemy import text

        from src.database import get_engine
        engine = get_engine()
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT COUNT(DISTINCT trade_date), MIN(trade_date), MAX(trade_date), "
                "COUNT(DISTINCT ticker) FROM daily_prices")).fetchone()
        if row and row[0]:
            ok(f"daily_prices 적재: {row[0]:,}거래일 ({row[1]} ~ {row[2]}) · {row[3]:,}종목")
            try:
                with engine.connect() as conn:
                    mk = conn.execute(text(
                        "SELECT SUM(CASE WHEN mktcap IS NOT NULL THEN 1 ELSE 0 END), COUNT(*) "
                        "FROM daily_prices")).fetchone()
                if mk and mk[1]:
                    pct = (mk[0] or 0) / mk[1] * 100
                    if pct > 0:
                        ok(f"시총 시계열 채움 {pct:.0f}% — 역사 PER/PBR·top200_asof 근사 유니버스 가능")
                    else:
                        warn("시총(mktcap) 미채움 — 구버전 적재분. --force 재백필 시 채워짐")
            except Exception:
                warn("mktcap 컬럼 없음(구 스키마) — 다음 백필 실행 시 자동 마이그레이션")
        else:
            warn("daily_prices 비어있음 — python -m src.data.krx_ingest --start 2015-01-01 로 백필")
    except Exception:
        warn("daily_prices 조회 불가 (DB 미기동 또는 테이블 없음) — 백필 시 자동 생성")


def check_ecos():
    """ECOS(한국은행) — 환율·금리 팩터 토큰. 키 검증 + 코드표 정합 sanity."""
    head("【6】 ECOS — 환율·금리 팩터")
    key = os.getenv("BOK_API_KEY", "")
    if not key:
        warn("BOK_API_KEY 미설정 → 환율·금리 토큰은 평가 시 건너뜀 (ecos.bok.or.kr 무료 발급)")
        return
    try:
        from src.kis_strategies.factor_tokens import _ecos_series
        usd = _ecos_series("US달러환율")
        if usd is not None and len(usd):
            v = float(usd.iloc[-1])
            if 800 <= v <= 2500:
                ok(f"US달러환율 수신: {v:,.1f}원 ({usd.index[-1].date()}, {len(usd):,}일)")
            else:
                warn(f"US달러환율 값 {v} — 항목 코드 매핑 점검 필요 (factor_tokens.ECOS_TOKENS)")
        else:
            fail("US달러환율 수신 실패 — 키 유효성/쿼터 확인")
        ktb = _ecos_series("국고채(3년)")
        if ktb is not None and len(ktb):
            v = float(ktb.iloc[-1])
            if 0 <= v <= 15:
                ok(f"국고채(3년) 수신: {v:.3f}% ({len(ktb):,}일)")
            else:
                warn(f"국고채(3년) 값 {v} — 항목 코드 매핑 점검 필요")
        else:
            warn("국고채(3년) 수신 실패 — ECOS_TOKENS 항목 코드 확인 (통계표 817Y002)")
    except Exception as e:
        fail(f"ECOS 호출 오류: {e}")

    # FRED — 미국 국채금리
    fred_key = os.getenv("FRED_API_KEY", "")
    if not fred_key:
        warn("FRED_API_KEY 미설정 → US국채 토큰은 평가 시 건너뜀 (fred.stlouisfed.org 무료 발급)")
        return
    try:
        from src.kis_strategies.factor_tokens import _fred_series
        us10 = _fred_series("US국채(10년)")
        if us10 is not None and len(us10):
            v = float(us10.iloc[-1])
            if 0 <= v <= 15:
                ok(f"US국채(10년) 수신: {v:.2f}% ({us10.index[-1].date()}, {len(us10):,}일)")
            else:
                warn(f"US국채(10년) 값 {v} — FRED 시리즈 매핑 점검 필요")
        else:
            fail("US국채(10년) 수신 실패 — FRED 키 유효성 확인")
    except Exception as e:
        fail(f"FRED 호출 오류: {e}")


def check_flows():
    """KIS 투자자별 수급 적재 현황 — 수급 토큰(외국인순매수량 등)의 데이터원."""
    head("【7】 KIS 수급 적재 (투자자별 순매수)")
    if os.getenv("KIS_USE_MOCK", "1") == "1":
        warn("KIS mock 모드 — 수급 적재는 실키 필요 (KIS_USE_MOCK=0 후 "
             "python -m src.data.kis_flows --all-listed)")
    try:
        from sqlalchemy import text

        from src.database import get_engine
        engine = get_engine()
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT COUNT(DISTINCT trade_date), MIN(trade_date), MAX(trade_date), "
                "COUNT(DISTINCT ticker) FROM investor_flows")).fetchone()
            sample = conn.execute(text(
                "SELECT ticker, trade_date, frgn_qty, frgn_amt FROM investor_flows "
                "ORDER BY trade_date DESC LIMIT 1")).fetchone()
        if row and row[0]:
            ok(f"investor_flows 적재: {row[0]:,}거래일 ({row[1]} ~ {row[2]}) · {row[3]:,}종목")
            if sample:
                print(f"      샘플: {sample[0]} {sample[1]} 외국인 {sample[2]:,.0f}주 / "
                      f"{sample[3]:,.0f} (금액 단위는 KIS pbmn — 이 값으로 확인)")
            warn("KIS TR은 최근 ~30영업일만 제공 — cron 등으로 매일 적재해 누적하세요")
        else:
            warn("investor_flows 비어있음 — python -m src.data.kis_flows --all-listed 로 적재")
    except Exception:
        warn("investor_flows 조회 불가 (DB 미기동 또는 테이블 없음) — 적재 시 자동 생성")


def check_fin_history():
    """DART 재무 시계열 적재 현황 — PIT(키 불필요 동작)·성장/흑자전환 팩터의 원천."""
    head("【8】 DART 재무 시계열 적재")
    try:
        from sqlalchemy import text

        from src.database import get_engine
        engine = get_engine()
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT COUNT(*), COUNT(DISTINCT ticker), MIN(bsns_year), MAX(bsns_year) "
                "FROM financials_history")).fetchone()
        if row and row[0]:
            ok(f"financials_history 적재: {row[0]:,}건 · {row[1]:,}종목 · {row[2]}~{row[3]}년")
            print("      → PIT 스크리닝이 DB에서 즉시 동작 (DART 키·쿼터 무소모)")
        else:
            warn("financials_history 비어있음 — python -m src.data.dart_history "
                 "--years 10 --all-listed --max-calls 18000 (일쿼터 분할, 재실행 시 이어서)")
    except Exception:
        warn("financials_history 조회 불가 (DB 미기동 또는 테이블 없음) — 백필 시 자동 생성")


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
    check_network()
    dart_ok = check_dart(code)
    kis_ok = check_kis(code, kis_mock)
    check_integration(code, dart_ok, kis_ok)
    check_backtest_flow(code, kis_mock)
    check_krx()
    check_ecos()
    check_flows()
    check_fin_history()

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
