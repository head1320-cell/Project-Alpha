"""펀더멘털 적재 파이프라인 진단 — GCP 컨테이너에서 실행해 어디서 막히는지 확정.

    docker compose exec backend python scripts/diag_fundamentals.py

민감정보(키 전체)는 출력하지 않는다. 각 단계 독립 try/except라 하나 실패해도 계속 진행."""
import os

print("=" * 70)
print("1) 배포 코드 마커 (수정 반영 여부)")
try:
    from src.data.fundamentals_store import FundamentalsStore
    print("   _fs_from_history 존재      :", hasattr(FundamentalsStore, "_fs_from_history"))  # DB-우선
    print("   _get_fs 존재               :", hasattr(FundamentalsStore, "_get_fs"))
    import inspect
    from src.engine.screener import ValuationScreener
    print("   run(reattach_fundamentals) :", "reattach_fundamentals" in inspect.signature(ValuationScreener.run).parameters)
    import src.data.snapshot_db as sdb
    print("   snapshot_db.ingested_count :", hasattr(sdb, "ingested_count"))
except Exception as e:
    print("   ERR:", e)

print("=" * 70)
print("2) 실행 모드")
print("   KIS_USE_MOCK :", os.getenv("KIS_USE_MOCK"))
print("   DART_API_KEY :", "설정됨" if os.getenv("DART_API_KEY") else "없음")
try:
    from src.data.mock_gate import mock_allowed
    print("   mock_allowed :", mock_allowed(), "(False=운영, 합성 금지)")
except Exception as e:
    print("   ERR:", e)

print("=" * 70)
print("3) factor_snapshot vs financials_history 카운트")
tickers_fh: list[str] = []
ffl_codes: set[str] = set()
try:
    from sqlalchemy import text

    from src.database import get_engine
    eng = get_engine()
    with eng.connect() as c:
        total = c.execute(text("SELECT COUNT(*) FROM factor_snapshot")).scalar()
        ffl = c.execute(text("SELECT COUNT(*) FROM factor_snapshot WHERE cache_key LIKE 'ffl:%'")).scalar()
        item = c.execute(text("SELECT COUNT(*) FROM factor_snapshot WHERE cache_key LIKE 'item:%'")).scalar()
        fh = c.execute(text("SELECT COUNT(DISTINCT ticker) FROM financials_history")).scalar()
        ffl_codes = {r[0].split(":", 1)[1] for r in c.execute(text(
            "SELECT cache_key FROM factor_snapshot WHERE cache_key LIKE 'ffl:%'"))}
        tickers_fh = [r[0] for r in c.execute(text(
            "SELECT DISTINCT ticker FROM financials_history"))]
    print(f"   factor_snapshot 총행 : {total}")
    print(f"   ffl:  키(=유니버스)   : {ffl}")
    print(f"   item: 키             : {item}")
    print(f"   financials_history 종목: {fh}")
    missing = [t for t in tickers_fh if t not in ffl_codes]
    print(f"   → financials 있는데 ffl: 없는 종목: {len(missing)}  (이게 재적재로 채워져야 함)")
    print(f"   샘플 미충족 종목: {missing[:5]}")
except Exception as e:
    print("   ERR:", e)

print("=" * 70)
print("4) 미충족 종목 1건 파이프라인 추적 (DB→FS→raw→factors)")
try:
    from src.data.dart_history import history_snapshot
    from src.data.fundamentals_store import FundamentalsStore
    probe = next((t for t in tickers_fh if t not in ffl_codes), tickers_fh[0] if tickers_fh else "005930")
    print(f"   대상 종목: {probe}")
    for y in (2025, 2024, 2023):
        snap = history_snapshot(str(probe), str(y), "11011")
        has = bool(snap and (snap.get("revenue") is not None or snap.get("total_assets") is not None))
        print(f"   history_snapshot({probe},{y}) : {'데이터 있음' if has else '없음'}")
    st = FundamentalsStore()
    fs = st._fs_from_history(probe, 2025) if hasattr(st, "_fs_from_history") else None
    print(f"   _fs_from_history → FS      : {'생성됨' if fs is not None else 'None'}")
    raw = st._real_raw_financials(probe)
    print(f"   _real_raw_financials       : {'dict(비어있지않음)' if raw else 'None/빈값'}")
    fac = st._build_factors(probe)
    print(f"   _build_factors             : {'팩터 {}개'.format(len(fac)) if fac else '빈 dict {} → 영속 안 됨'}")
    if fac:
        print(f"   샘플 팩터 roe/per          : {fac.get('roe')}, {fac.get('per')}")
except Exception as e:
    import traceback
    print("   ERR:", e)
    traceback.print_exc()

print("=" * 70)
print("5) DART 사용량")
try:
    from src.data.dart_client import dart_usage
    print("  ", dart_usage())
except Exception as e:
    print("   ERR:", e)
print("=" * 70)
print("진단 끝. 4)에서 history_snapshot='데이터 있음'인데 _build_factors가 '빈 dict'면")
print("→ DB 매핑/파싱 문제. history_snapshot='없음'이면 → 티커 포맷/연도 불일치.")
