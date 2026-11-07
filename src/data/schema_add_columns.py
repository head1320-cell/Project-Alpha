"""운영 중인 테이블에 컬럼을 덧붙이는 단일 헬퍼 (M1-S)
==============================================================================
`regime_snapshots.py:89-107` 이 세운 패턴을 한 곳으로 모은다. M1 에서 세 테이블
(`regime_snapshots` · `research_runs` · `target_portfolio_versions`)에 같은 일을 하게
되는데, 10줄짜리 패턴을 세 벌 복사하면 반드시 갈라진다 — 이 저장소가 A1(`currentSig`/
`req`)과 R0(오버레이 컴파일)에서 두 번 값을 치른 실수다.

★두 단계가 다 필요하다★
  1. `ADD COLUMN` 은 이미 있으면 예외를 낸다. SQLite 는 `IF NOT EXISTS` 를 지원하지
     않으므로 "이미 있음"과 "진짜 실패"가 같은 예외로 온다 → 삼킨다.
  2. **그래서 실제로 붙었는지 SELECT 로 확인한다.** 1번만 하면 못 붙은 컬럼을 붙었다고
     믿고 이후 조회가 통째로 깨진다 — 원본 주석이 "무조건 SELECT 하면 조회 전체가
     깨져서 수정 전보다 나빠진다" 고 적어 둔 그 함정이다.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def add_columns(engine, table: str, cols: list[tuple[str, str]], *,
                label: str | None = None) -> bool:
    """`cols` 를 `table` 에 덧붙이고 **실제로 쓸 수 있는지** 확인해 돌려준다.

    Returns:
        True  — 전부 붙었고 SELECT 가 통한다.
        False — 하나라도 못 쓴다. 호출자는 그 컬럼 없이 동작해야 한다(조회를 깨지 않는다).
    """
    from sqlalchemy import text

    for col, ddl in cols:
        try:
            with engine.begin() as c:
                c.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
        except Exception:
            pass   # 이미 있음 — SQLite 는 이것도 예외다

    names = ", ".join(c for c, _ in cols)
    try:
        with engine.connect() as c:
            c.execute(text(f"SELECT {names} FROM {table} LIMIT 1"))
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("%s: %s 사용 불가 — 해당 컬럼 없이 동작합니다: %s",
                       label or table, names, e)
        return False
