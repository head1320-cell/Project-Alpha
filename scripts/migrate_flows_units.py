"""investor_flows 금액 단위 1회 마이그레이션 — 혼합 단위(pbmn/원) → 억원 단일화.

배경(CIO 실사): '외국인 20일 순매수 -1519조' — KIS pbmn(백만원)을 원본 그대로 저장하고
표시 라벨은 '억'이라 100배 뻥튀기. 적재 코드는 억 단위로 수정됨(kis_client/krx_mdc) —
이 스크립트는 **기존 적재분**을 1회 변환한다. 멱등: 마커(factor_snapshot 'meta:flows_unit')
가 있으면 재실행해도 건너뜀.

행별 단위 판별(보수적):
  |amt| >= 1e9  → 원 단위(KRX 백필)로 간주 → /1e8
  |amt| >= 1    → pbmn(백만원, KIS)로 간주 → /100
  (이미 억 단위로 재적재된 신규 행은 마커 이후에만 존재 — 마커가 이중 변환을 차단)

실행:  docker compose exec backend python scripts/migrate_flows_units.py [--dry-run]
"""
import argparse
import json
import sys

sys.path.insert(0, ".")

AMT_COLS = ("prsn_amt", "frgn_amt", "orgn_amt", "pension_amt", "trust_amt",
            "pe_amt", "othercorp_amt")
MARKER = "meta:flows_unit"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="변환 통계만 출력 (미적용)")
    args = ap.parse_args()

    from sqlalchemy import text

    from src.database import get_engine
    eng = get_engine()

    # 멱등 마커 확인
    with eng.connect() as c:
        try:
            row = c.execute(text(
                "SELECT value FROM factor_snapshot WHERE cache_key = :k"), {"k": MARKER}).fetchone()
        except Exception:
            row = None
    if row:
        print(f"이미 마이그레이션됨: {row[0]} — 건너뜀 (이중 변환 방지)")
        return

    # 통계
    with eng.connect() as c:
        n = c.execute(text("SELECT COUNT(*) FROM investor_flows")).scalar() or 0
        mx = c.execute(text("SELECT MAX(ABS(frgn_amt)) FROM investor_flows")).scalar()
    print(f"investor_flows 행: {n:,} · |frgn_amt| 최대: {mx}")
    if not n:
        print("데이터 없음 — 마커만 기록")
    if args.dry_run:
        with eng.connect() as c:
            krx = c.execute(text(
                "SELECT COUNT(*) FROM investor_flows WHERE ABS(frgn_amt) >= 1e9")).scalar() or 0
        print(f"[dry-run] 원단위(/1e8) 추정 {krx:,}행 · pbmn(/100) 추정 {n - krx:,}행 — 미적용")
        return

    # 변환 (행별 임계 판별 — 컬럼별 독립 적용)
    updated = 0
    with eng.begin() as c:
        for col in AMT_COLS:
            try:
                r1 = c.execute(text(
                    f"UPDATE investor_flows SET {col} = {col} / 1e8 "     # noqa: S608
                    f"WHERE {col} IS NOT NULL AND ABS({col}) >= 1e9"))
                r2 = c.execute(text(
                    f"UPDATE investor_flows SET {col} = {col} / 100.0 "   # noqa: S608
                    f"WHERE {col} IS NOT NULL AND ABS({col}) >= 1 AND ABS({col}) < 1e9"))
                updated += (r1.rowcount or 0) + (r2.rowcount or 0)
            except Exception as e:
                print(f"  {col} 변환 실패(컬럼 없음 등 — 계속): {e}")
        # 마커 기록 (멱등)
        c.execute(text(
            "INSERT INTO factor_snapshot (cache_key, value, updated_at) "
            "VALUES (:k, :v, 0) ON CONFLICT (cache_key) DO UPDATE SET value = excluded.value"),
            {"k": MARKER, "v": json.dumps({"unit": "억", "migrated_updates": updated})})
    print(f"완료: {updated:,} 컬럼값 변환 → 억원 단일화. 마커 기록됨({MARKER}).")
    print("주의: price_factors(수급 팩터) 캐시가 남아있으면 '펀더멘털' 재적재로 갱신하세요.")


if __name__ == "__main__":
    main()
