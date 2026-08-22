"""애플리케이션 기동 시퀀스 — main_api.py에서 분리.

DB 초기화 · 고아 백테스트 정리 · 스크리너 테이블 · KIS master 수집 · DART/KRX/OHLCV
사전적재 데몬 등 11단계. 각 단계는 개별 try/except로 감싸 하나가 실패해도 기동은 계속된다.
라우트가 아니므로 어떤 라우터 파일에도 속하지 않는다.
"""

import logging

from src.database import init_db

logger = logging.getLogger("api.startup")

async def _collect_master_bg(engine):
    """백그라운드: KIS 마스터파일 수집 (다운로드+파싱+DB/플래그 캐시). 실패해도 폴백 유지."""
    import logging
    log = logging.getLogger("api.main")
    try:
        from src.kis_master_parser import collect_master_files
        r = await collect_master_files(engine)
        log.info(f"KIS 마스터 수집 완료: KOSPI {r.get('KOSPI')} + KOSDAQ {r.get('KOSDAQ')}")
    except Exception as e:
        log.warning(f"KIS 마스터 수집 실패(폴백 유지): {e}")

def _prewarm_real_data():
    """백그라운드(데몬 스레드): corp_code 맵 준비 + 기본 유니버스 팩터를 DB에 적재.
    이미 DB(factor_snapshot)에 적재돼 있으면 디스크/DB 캐시 히트로 빠르게 끝남."""
    import logging
    log = logging.getLogger("api.main")
    try:
        from src.data.dart_client import _load_full_corp_map
        n = len(_load_full_corp_map())
        log.info(f"사전 워밍: corp_code 맵 {n}개 준비")
    except Exception as e:
        log.warning(f"사전 워밍 corp_code 실패: {e}")
    try:
        import os

        from src.data.snapshot_db import ingest_universe
        # 공통 유니버스 먼저(빠르게 준비) → 전종목 펀더멘털까지 확장(조건식이 ROE 등 펀더멘털을
        # 써도 전종목이 DB 캐시에서 즉시). DART 호출이 크지만 재개 가능(item:CODE/디스크캐시) + 데몬.
        unis = ["kospi200"]
        if os.getenv("FUNDAMENTALS_PREWARM_ALL", "1") != "0":
            unis += ["kosdaq150", "all_listed"]
        for uni in unis:
            r = ingest_universe(uni)  # 펀더멘털+가격 팩터 → factor_snapshot 적재(write-through)
            log.info(f"사전 워밍[{uni}]: factor_snapshot 적재 {r}")
    except Exception as e:
        log.warning(f"사전 워밍 적재 실패: {e}")

    # Load symbol master cache (non-blocking)
    try:
        from src.database import get_engine
        from src.kis_master_parser import load_symbol_cache
        engine = get_engine()
        load_symbol_cache(engine)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Symbol cache load skipped: {e}")

def _krx_backfill_bg():
    """백그라운드(데몬): KRX 전종목 장기 일봉 → daily_prices 자동 백필 + 주기 증분.
    키 없거나 KRX_AUTOBACKFILL=0이면 auto_backfill이 즉시 no-op."""
    import logging
    log = logging.getLogger("api.main")
    try:
        from src.data.krx_ingest import auto_backfill
        auto_backfill(loop=True)  # 초기 백필 후 주기 증분 (데몬이라 비차단)
    except Exception as e:
        log.warning(f"KRX 자동 백필 실패(폴백 유지): {e}")

def _prewarm_ohlcv_bg():
    """백그라운드(데몬): KIS 일봉을 daily_prices에 전종목 사전 적재 → 백테스터(조건식 포함) DB 즉시 가속.

    우선순위 kospi200 → kosdaq150 → 전종목(all_listed)로 공통 유니버스를 먼저 준비.
    prewarm_ohlcv는 병렬(스레드 안전 KIS 클라이언트)·재개 가능(이미 적재분 스킵)이며,
    mock/키 없음이면 즉시 no-op. KRX 백필 활성 시엔 startup 게이트에서 이 데몬을 스킵."""
    import logging
    import os
    log = logging.getLogger("api.main")
    try:
        from src.data.ohlcv_loader import prewarm_ohlcv
        from src.engine.screener import resolve_universe
        days = int(os.getenv("OHLCV_PREWARM_DAYS", "3650") or 3650)  # 기본 ~10년(페이지네이션)
        unis = ["kospi200", "kosdaq150"]
        if os.getenv("OHLCV_PREWARM_ALL", "1") != "0":
            unis.append("all_listed")
        for uni in unis:
            try:
                tickers = resolve_universe(uni)
            except Exception:
                tickers = []
            if not tickers:
                continue
            r = prewarm_ohlcv(tickers, days=days)
            log.info(f"OHLCV 사전적재[{uni}]: {r}")
    except Exception as e:
        log.warning(f"OHLCV 사전 적재 실패(폴백 유지): {e}")

def _prewarm_etf_bg():
    """백그라운드(데몬): 크로스에셋 ETF 유니버스(US→KR 매핑)를 daily_prices에 적재.
    ★KIS/KRX 분기와 무관히 실행★ — KRX 전종목 백필은 '주식'만 다루므로 ETF는 여기서 별도 적재.
    매크로 전략·자산배분 백테스트(LAA 등)의 ETF 가격 원천. mock/키 없음이면 prewarm_ohlcv가 no-op."""
    import logging
    log = logging.getLogger("api.main")
    try:
        from src.data.etf_prices import prewarm_etf_universe
        r = prewarm_etf_universe("kr")
        log.info(f"OHLCV 사전적재[etf_universe]: {r}")
    except Exception as e:
        log.warning(f"ETF 유니버스 prewarm 실패: {e}")

def _dart_backfill_sleep_seconds(stats: dict) -> int:
    """백필 1회 결과에 따른 다음 시도까지 대기(초).

    부팅 시 KIS 마스터 수집과 이 백필이 동시 스레드로 시작되는데, 백필이 먼저 돌면
    마스터 캐시가 비어 all_listed가 SEED 30종목으로 조용히 축소된다(dart_history.
    backfill_financials의 fallback_to_seed). 이걸 '오늘은 완료'로 오판해 24시간
    자면, 마스터가 수 초~수 분 뒤 채워져도 다음날까지 재시도를 안 해 정체된 것처럼
    보인다(실측: last_fetch가 이틀째 정지) — 그래서 fallback이면 짧게 재시도한다."""
    import os
    if not isinstance(stats, dict):
        return 24 * 3600
    if stats.get("stopped_at_quota"):
        return 3 * 3600                                              # 일쿼터 도달 → 리셋 대기
    if stats.get("fallback_to_seed"):
        return int(os.getenv("DART_HISTORY_RETRY_SEC", "300") or 300)  # 마스터캐시 경쟁 → 곧 재시도
    return 24 * 3600                                                  # 실제 완료 → 다음날 증분

def _dart_history_backfill_bg():
    """백그라운드(데몬): 전종목 과거 재무 → financials_history 적재 (PIT 펀더멘털 백테스트 원천).

    DART 일 20,000콜 한도라 max_calls로 분할하고, 쿼터 도달 시 대기 후 이어서(resume) 적재한다.
    완료되면 하루 뒤 증분(최신 보고서) 재확인. 키 없으면 backfill_financials가 즉시 error 반환→종료."""
    import logging
    import os
    import time
    log = logging.getLogger("api.main")
    try:
        from src.data.dart_history import backfill_financials
        years = int(os.getenv("DART_HISTORY_YEARS", "10") or 10)
        quarters = os.getenv("DART_HISTORY_QUARTERS", "0") != "0"  # 1=분기까지(4배 콜)
        max_calls = int(os.getenv("DART_HISTORY_MAX_CALLS", "18000") or 18000)
        while True:
            stats = backfill_financials(all_listed=True, years=years,
                                        include_quarters=quarters, max_calls=max_calls)
            log.info(f"DART 재무 시계열 백필: {stats}")
            if isinstance(stats, dict) and stats.get("error"):
                return  # 키 없음/DB 없음 → 종료
            time.sleep(_dart_backfill_sleep_seconds(stats))
    except Exception as e:
        log.warning(f"DART 재무 시계열 백필 실패(폴백 유지): {e}")

def _kis_flows_sync_bg():
    """백그라운드(데몬): KIS 투자자별 수급(최근 ~30영업일)을 investor_flows에 매일 누적.
    수급 토큰(외국인·기관 순매수) 백테스트의 최근 구간 실데이터. mock/키 없으면 error→종료."""
    import logging
    import os
    import time
    log = logging.getLogger("api.main")
    try:
        from src.data.kis_flows import sync_investor_flows
        time.sleep(int(os.getenv("FLOWS_SYNC_DELAY_SEC", "120") or 120))  # 마스터 수집 선행 여유
        while True:
            stats = sync_investor_flows(all_listed=True)
            log.info(f"KIS 수급 적재: {stats}")
            if isinstance(stats, dict) and stats.get("error"):
                return  # mock/키 없음/DB 없음 → 종료
            time.sleep(24 * 3600)  # 매일 누적 (KIS는 최근 ~30일 윈도만 반환)
    except Exception as e:
        log.warning(f"KIS 수급 적재 실패(폴백 유지): {e}")

def _krx_flows_backfill_bg():
    """백그라운드(데몬): KRX MDC 투자자별 수급 '과거' 1회 백필(비공식) → 깊은 수급 역사 + 세부 주체.
    마스터(ISIN)가 준비될 때까지 대기 후 1회 실행(재적재 없음). 비공식 스크래핑이라 opt-in."""
    import logging
    import os
    import time
    log = logging.getLogger("api.main")
    try:
        from src.data.krx_mdc import backfill_flows_krx
        start = os.getenv("KRX_FLOWS_START", "2018-01-01")
        for _ in range(30):  # 마스터(collect-master) 준비 대기 — 최대 ~30분
            stats = backfill_flows_krx(start=start, all_listed=True)
            log.info(f"KRX 수급 과거 백필: {stats}")
            if (isinstance(stats, dict) and stats.get("error")
                    and "마스터" in str(stats.get("message", ""))):
                time.sleep(60)
                continue  # 마스터 아직 미준비 → 재시도
            return  # 완료/다른 에러 → 종료 (1회성)
    except Exception as e:
        log.warning(f"KRX 수급 과거 백필 실패(폴백 유지): {e}")


async def run_startup() -> None:
    import asyncio
    try:
        init_db()
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"init_db failed (DB 준비 전일 수 있음): {e}")

    # 고아 백테스트 실행 정리 — 실행 워커는 daemon 스레드라 재시작 시 정리 없이 사라진다.
    # 훑지 않으면 그 행이 영원히 비종료로 남아 결과 페이지가 끝나지 않는 실행을 보여준다.
    try:
        from src.data.backtest_runs import sweep_orphaned
        sweep_orphaned()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"backtest 고아 정리 건너뜀: {e}")

    # Initialize screener tables (legacy sync path)
    try:
        from src.database import get_engine
        from src.screener_models import init_screener_tables
        from src.screener_pipeline import update_market_cache_loop
        engine = get_engine()
        init_screener_tables(engine)
        asyncio.create_task(update_market_cache_loop(engine))
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Screener startup failed: {e}")

    # Initialize KIS-backed async DB and scheduler
    try:
        from src.data_sync import daily_sync_scheduler
        from src.database_async import init_async_db
        ok = await init_async_db()
        if ok:
            asyncio.create_task(daily_sync_scheduler())
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"KIS async DB startup failed: {e}")

    # KIS 종목 마스터 자동 수집 (무료·인증불필요): 전종목 코드·실명·KOSPI200/KOSDAQ150·ETF 플래그.
    # → 유니버스(실제 지수·시장전체·ETF 전체)와 종목명 해소의 단일 소스. 미적재 시에만.
    try:
        from src.data.stock_master import load_master_flags
        if not load_master_flags():
            from src.database import get_engine
            asyncio.create_task(_collect_master_bg(get_engine()))
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"마스터 수집 시작 실패: {e}")

    # 실데이터 사전 워밍 (DART 키 있을 때만, 백그라운드 스레드):
    #   ① corp_code 맵을 미리 로드 → 첫 스크린의 corp_code 미스("조회된 데이터 없음") 방지
    #   ② 기본 유니버스 펀더멘털을 미리 계산 → 디스크 캐시 채움 → 사용자 첫 클릭이
    #      44초를 기다리지 않게 함. 재시작 후엔 디스크 캐시 히트로 빠르게 재워밍.
    try:
        import os
        if os.getenv("DART_API_KEY"):
            import threading
            threading.Thread(target=_prewarm_real_data, daemon=True).start()
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"실데이터 사전 워밍 시작 실패: {e}")

    # KRX 전종목 장기 일봉 자동 백필 (KRX_API_KEY 있을 때만, 데몬 스레드):
    #   날짜기준 전종목 일봉을 daily_prices에 적재 → 백테스터(ohlcv_loader DB 1순위)가
    #   장기 기간을 KRX 실데이터로 로딩(생존편향 보정·지수 포함). 재개 가능·비차단.
    #   KRX_AUTOBACKFILL=0으로 비활성, KRX_BACKFILL_START로 범위 조절.
    try:
        import os
        if os.getenv("KRX_API_KEY") and os.getenv("KRX_AUTOBACKFILL", "1") != "0":
            import threading
            threading.Thread(target=_krx_backfill_bg, daemon=True).start()
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"KRX 자동 백필 시작 실패: {e}")

    # KIS 일봉 전종목 사전 적재 (KIS 실데이터 키 있고 + KRX 백필 비활성일 때만, 데몬 스레드):
    #   KRX 키 없이도 daily_prices를 전종목 OHLCV로 미리 채워 백테스터(조건식 포함)를 즉시 DB-가속
    #   (이전엔 백테스트한 종목만 reactively 적재 → 첫 콜드런이 느림). 우선순위 kospi200→kosdaq150→
    #   전종목, 재개 가능(이미 적재분 스킵). KRX 활성 시엔 KRX가 더 깊은 역사를 담당하므로 스킵.
    #   OHLCV_PREWARM=0 비활성 · OHLCV_PREWARM_ALL=0 공통 유니버스까지만 · OHLCV_PREWARM_DAYS 범위.
    try:
        import os

        from src.data.mock_gate import mock_allowed
        _kis_real = not mock_allowed() and bool(os.getenv("KIS_APP_KEY"))
        _krx_active = bool(os.getenv("KRX_API_KEY")) and os.getenv("KRX_AUTOBACKFILL", "1") != "0"
        if _kis_real and not _krx_active and os.getenv("OHLCV_PREWARM", "1") != "0":
            import threading
            threading.Thread(target=_prewarm_ohlcv_bg, daemon=True).start()
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"OHLCV 사전 적재 시작 실패: {e}")

    # 크로스에셋 ETF 유니버스 적재 (★KIS/KRX 분기 무관★ — KRX 전종목 백필은 '주식'만 다루므로
    #   ETF는 별도 적재 필요. 매크로 전략·자산배분 백테스트(LAA 등)의 ETF 가격 원천.
    #   실데이터 가용(KIS 실키 또는 KRX 활성) + OHLCV_PREWARM_ETF≠0일 때. mock/키 없음이면 no-op.):
    try:
        import os

        from src.data.mock_gate import mock_allowed
        _real_ohlcv = (not mock_allowed() and bool(os.getenv("KIS_APP_KEY"))) \
            or (bool(os.getenv("KRX_API_KEY")) and os.getenv("KRX_AUTOBACKFILL", "1") != "0")
        if _real_ohlcv and os.getenv("OHLCV_PREWARM_ETF", "1") != "0":
            import threading
            threading.Thread(target=_prewarm_etf_bg, daemon=True).start()
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"ETF 유니버스 prewarm 시작 실패: {e}")

    # 전종목 과거 재무(financials_history) 백필 (DART 키 있을 때만, 데몬 스레드):
    #   PIT 펀더멘털 백테스트(look-ahead 없는 ROE/PER 등)의 실데이터 원천. DART 일 20,000콜 한도라
    #   max_calls로 분할하고 매일 이어서 적재(resume). 키 없으면 즉시 no-op.
    #   DART_HISTORY_BACKFILL=0 비활성 · DART_HISTORY_YEARS 깊이 · DART_HISTORY_QUARTERS=1 분기까지.
    try:
        import os
        if os.getenv("DART_API_KEY") and os.getenv("DART_HISTORY_BACKFILL", "1") != "0":
            import threading
            threading.Thread(target=_dart_history_backfill_bg, daemon=True).start()
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"DART 재무 시계열 백필 시작 실패: {e}")

    # KIS 투자자별 수급(최근 ~30영업일) 매일 적재 (KIS 실키 있을 때만, 데몬):
    #   수급 토큰(외국인·기관 순매수) 백테스트의 최근 구간 실데이터(investor_flows). FLOWS_SYNC=0 비활성.
    try:
        import os

        from src.data.mock_gate import mock_allowed
        if (not mock_allowed() and bool(os.getenv("KIS_APP_KEY"))
                and os.getenv("FLOWS_SYNC", "1") != "0"):
            import threading
            threading.Thread(target=_kis_flows_sync_bg, daemon=True).start()
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"KIS 수급 적재 시작 실패: {e}")

    # KRX MDC 투자자별 수급 '과거' 1회 백필 (opt-in — 비공식 스크래핑, 깊은 역사 + 세부 주체):
    #   KIS는 최근 ~30일만 → 깊은 수급 역사는 KRX MDC로 1회 적재. 마스터(ISIN) 준비 후 실행.
    #   비공식 엔드포인트라 기본 OFF — KRX_FLOWS_BACKFILL=1 로 명시 활성, KRX_FLOWS_START 로 범위.
    try:
        import os
        if os.getenv("KRX_FLOWS_BACKFILL", "0") == "1":
            import threading
            threading.Thread(target=_krx_flows_backfill_bg, daemon=True).start()
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"KRX 수급 과거 백필 시작 실패: {e}")
