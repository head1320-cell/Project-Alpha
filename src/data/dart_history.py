"""DART 재무 시계열 백필 → financials_history (PIT·성장/흑자전환 팩터의 원천)
==========================================================================
종목 × 과거 N년(연간 + 선택 분기)의 재무제표를 1회 적재해 두면:
  · PIT 스크리닝이 DB에서 즉시(쿼터 무소모·키 불필요) 동작
  · 분기/트레일링 구분, 흑자전환·3년연속류 파생 팩터의 기반 확보
  · [C] 시총 시계열과 결합 → 역사 PER/PBR 계산 가능

쿼터: DART 일 20,000건 — 전 주권(~2,700) × 10년 연간 = 27,000콜
→ `--max-calls 18000`으로 이틀 분할 (resume: 적재된 (종목,연도,보고서) 자동 skip).

실행 (사용자 환경, DART_API_KEY 필요):
    python -m src.data.dart_history --years 10 --all-listed --max-calls 18000
    python -m src.data.dart_history --years 5 --quarters --tickers 005930,000660
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

logger = logging.getLogger(__name__)

_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS financials_history (
    ticker              VARCHAR(12) NOT NULL,
    bsns_year           VARCHAR(4)  NOT NULL,
    reprt_code          VARCHAR(5)  NOT NULL,
    revenue             FLOAT,
    operating_profit    FLOAT,
    net_income          FLOAT,
    gross_profit        FLOAT,
    total_assets        FLOAT,
    total_liabilities   FLOAT,
    total_equity        FLOAT,
    current_assets      FLOAT,
    current_liabilities FLOAT,
    operating_cf        FLOAT,
    capex               FLOAT,
    shares_outstanding  FLOAT,
    dps                 FLOAT,
    fetched_at          VARCHAR(32),
    PRIMARY KEY (ticker, bsns_year, reprt_code)
)
"""

# 기존 테이블 마이그레이션 (ALTER 멱등 — 이미 있음 무시)
#: ★`vintage_probe_at` 은 "시도했다" 이지 "빈티지가 없다" 가 아니다★
#: 3단계(소급 백필)가 접수번호를 못 받은 기간을 다시 묻지 않으려고 남기는 흔적이다.
#: 미상 ≠ 없음이므로 `--retry-probed` 로 언제든 다시 연다.
#: ★아래 `ALTER` 는 예외를 삼킨다★ — 그래서 이 컬럼에 **의존하는** 경로는
#: `_has_probe_column()` 으로 실제로 붙었는지 확인한다(`ensure_vintage_table` 과 같은 규율).
_MIGRATE_COLUMNS = ("dps FLOAT", "vintage_probe_at VARCHAR(32)")

#: 갭 질의가 의존하는 컬럼 이름 — 사유 문장이 이 이름을 그대로 말한다.
PROBE_COLUMN = "vintage_probe_at"

_UPSERT = """
INSERT INTO financials_history
    (ticker, bsns_year, reprt_code, revenue, operating_profit, net_income, gross_profit,
     total_assets, total_liabilities, total_equity, current_assets, current_liabilities,
     operating_cf, capex, shares_outstanding, dps, fetched_at)
VALUES
    (:ticker, :bsns_year, :reprt_code, :revenue, :operating_profit, :net_income, :gross_profit,
     :total_assets, :total_liabilities, :total_equity, :current_assets, :current_liabilities,
     :operating_cf, :capex, :shares_outstanding, :dps, :fetched_at)
ON CONFLICT (ticker, bsns_year, reprt_code) DO UPDATE SET
    revenue=EXCLUDED.revenue, operating_profit=EXCLUDED.operating_profit,
    net_income=EXCLUDED.net_income, gross_profit=EXCLUDED.gross_profit,
    total_assets=EXCLUDED.total_assets, total_liabilities=EXCLUDED.total_liabilities,
    total_equity=EXCLUDED.total_equity, current_assets=EXCLUDED.current_assets,
    current_liabilities=EXCLUDED.current_liabilities, operating_cf=EXCLUDED.operating_cf,
    capex=EXCLUDED.capex, shares_outstanding=EXCLUDED.shares_outstanding,
    dps=EXCLUDED.dps, fetched_at=EXCLUDED.fetched_at
"""

# ═══════════════════════════════════════════════════════════════════════════════
# 빈티지 테이블 — ★정정공시가 원본을 파괴하지 않게★
# ═══════════════════════════════════════════════════════════════════════════════
#
# `financials_history` 는 PK `(ticker, bsns_year, reprt_code)` 라 **정정공시가 원본
# 보고값을 덮어쓴다.** 되돌릴 수 없다 — 지나간 빈티지는 다시 받을 수 없다.
#
# ★그런데 그 테이블의 PK 를 바꾸지 않는다★ 실측된 이유 셋:
#   ① 이 테이블 리더 8곳에 `ORDER BY`·`DISTINCT` 가 **하나도 없다.** 행이 늘면
#      조용히 깨진다 — QOQ 팩터 4개가 통째로 None 이 되고(`:429` 가드), 적신호
#      R2·R3 은 안전해 보이는 방향으로 억제되고, PIT 패널은 두 공시를 필드
#      단위로 섞어 실재한 적 없는 재무를 만든다.
#   ② CI 가 SQLite 로만 돈다 — PK 재구축 DDL 이 프로덕션에서 처음 실행된다.
#   ③ `test_financial_revenue.py:87` 의 컬럼 명시 INSERT 가 즉시 깨진다.
#
# 그래서 **역할로 가른다** — 이 저장소가 매크로에서 이미 쓰는 모델이다
# (`pit_macro`: "지금 최신 값(대시보드)" vs "그때 알 수 있던 값(리서치·백테스트)").
#
#   financials_history   지금 값   (덮어쓰기 — 기존 리더 8곳이 그대로 읽는다)
#   financials_vintages  그때 값   (누적 — 접수번호가 빈티지 축이다)
#
# valid time = `(bsns_year, reprt_code)`, transaction time = `rcept_dt`.
# `macro_observations` 가 PK 에 `obs_key` 를 넣어 개정이 행을 더하게 한 것과 같다.
VINTAGE_TABLE = "financials_vintages"

_VINTAGE_DDL = f"""
CREATE TABLE IF NOT EXISTS {VINTAGE_TABLE} (
    ticker              VARCHAR(12) NOT NULL,
    bsns_year           VARCHAR(4)  NOT NULL,
    reprt_code          VARCHAR(5)  NOT NULL,
    rcept_no            VARCHAR(20) NOT NULL,
    rcept_dt            VARCHAR(10) NOT NULL,
    revenue             FLOAT,
    operating_profit    FLOAT,
    net_income          FLOAT,
    gross_profit        FLOAT,
    total_assets        FLOAT,
    total_liabilities   FLOAT,
    total_equity        FLOAT,
    current_assets      FLOAT,
    current_liabilities FLOAT,
    operating_cf        FLOAT,
    capex               FLOAT,
    shares_outstanding  FLOAT,
    dps                 FLOAT,
    retrieved_at        VARCHAR(32),
    PRIMARY KEY (ticker, bsns_year, reprt_code, rcept_no)
)
"""


_FIELDS = ("revenue", "operating_profit", "net_income", "gross_profit",
           "total_assets", "total_liabilities", "total_equity",
           "current_assets", "current_liabilities", "operating_cf", "capex",
           "shares_outstanding", "dps")

REPRT_ANNUAL = "11011"
QUARTER_REPRTS = ("11013", "11012", "11014")  # 1Q, 반기, 3Q


def _get_engine(engine=None):
    if engine is not None:
        return engine
    from src.database import get_engine
    return get_engine()


#: 빈티지 UPSERT — ★`retrieved_at` 은 DO UPDATE 에 넣지 않는다★
#: `macro_observation_store.py:110` 이 적어 둔 규칙 그대로: "최초 관측 시각을
#: 보존한다 … 덮으면 '언제부터 알았나' 가 사라진다." 값은 갱신한다(같은 접수번호
#: 재조회는 멱등이어야 하고, 파서가 좋아지면 값이 채워질 수 있다).
_VINTAGE_UPSERT = f"""
INSERT INTO {VINTAGE_TABLE}
    (ticker, bsns_year, reprt_code, rcept_no, rcept_dt, revenue, operating_profit,
     net_income, gross_profit, total_assets, total_liabilities, total_equity,
     current_assets, current_liabilities, operating_cf, capex, shares_outstanding,
     dps, retrieved_at)
VALUES
    (:ticker, :bsns_year, :reprt_code, :rcept_no, :rcept_dt, :revenue, :operating_profit,
     :net_income, :gross_profit, :total_assets, :total_liabilities, :total_equity,
     :current_assets, :current_liabilities, :operating_cf, :capex, :shares_outstanding,
     :dps, :retrieved_at)
ON CONFLICT (ticker, bsns_year, reprt_code, rcept_no) DO UPDATE SET
    rcept_dt=EXCLUDED.rcept_dt,
    revenue=EXCLUDED.revenue, operating_profit=EXCLUDED.operating_profit,
    net_income=EXCLUDED.net_income, gross_profit=EXCLUDED.gross_profit,
    total_assets=EXCLUDED.total_assets, total_liabilities=EXCLUDED.total_liabilities,
    total_equity=EXCLUDED.total_equity, current_assets=EXCLUDED.current_assets,
    current_liabilities=EXCLUDED.current_liabilities, operating_cf=EXCLUDED.operating_cf,
    capex=EXCLUDED.capex, shares_outstanding=EXCLUDED.shares_outstanding,
    dps=EXCLUDED.dps
"""

#: 빈티지 없이 지나간 건수 (프로세스 수명). ★미상을 0 으로 만들지 않기 위한 카운터★
#: — 접수번호 없는 응답이 몇 건인지 모르면 "정정공시가 없다" 와 "못 봤다" 를
#: 구별할 수 없다.
_VINTAGE_SKIPPED = {"no_rcept": 0}


def ensure_vintage_table(engine) -> bool:
    """빈티지 테이블을 만들고 ★실제로 쓸 수 있는지 확인한다★.

    `ensure_history_table` 은 `ALTER` 를 `except: pass` 로 삼키고 검증을 하지
    않는다 — `schema_add_columns.py:11-13` 이 정확히 그것을 함정으로 적어 뒀다
    ("1번만 하면 못 붙은 컬럼을 붙었다고 믿고 이후 조회가 통째로 깨진다").
    여기서는 그 규율을 따라 만든 뒤 **읽어 본다**.

    못 쓰면 `False` — 호출자는 빈티지 없이 계속 동작한다(빈티지는 추가이지
    전제가 아니다).
    """
    from sqlalchemy import text
    try:
        with engine.begin() as conn:
            conn.execute(text(_VINTAGE_DDL))
    except Exception as e:  # noqa: BLE001
        logger.warning("%s 생성 실패 — 빈티지 없이 동작합니다: %s", VINTAGE_TABLE, e)
        return False
    try:
        with engine.connect() as conn:
            conn.execute(text(f"SELECT rcept_no, rcept_dt FROM {VINTAGE_TABLE} LIMIT 1"))
    except Exception as e:  # noqa: BLE001
        logger.warning("%s 사용 불가 — 빈티지 없이 동작합니다: %s", VINTAGE_TABLE, e)
        return False
    return True


def _upsert_vintage(engine, ticker: str, fs) -> bool:
    """빈티지 1건 저장. 접수번호가 없으면 저장하지 않는다(`False`).

    ★접수번호 없는 행은 빈티지가 아니다★ `macro_observation_store.record_series`
    가 같은 판단을 적어 뒀다 — "이 경로에는 빈티지가 없다 … 지어내면
    derive_usage 가 거짓으로 backtest_eligible 을 낸다."
    """
    from sqlalchemy import text
    rcept_no = getattr(fs, "rcept_no", None)
    rcept_dt = getattr(fs, "rcept_dt", None)
    if not rcept_no or not rcept_dt:
        _VINTAGE_SKIPPED["no_rcept"] += 1
        return False
    if not ensure_vintage_table(engine):
        return False
    row = {f: getattr(fs, f, None) for f in _FIELDS}
    row.update({
        "ticker": str(ticker), "bsns_year": str(fs.bsns_year),
        "reprt_code": str(fs.reprt_code), "rcept_no": str(rcept_no),
        "rcept_dt": str(rcept_dt),
        "retrieved_at": datetime.now().isoformat(timespec="seconds"),
    })
    with engine.begin() as conn:
        conn.execute(text(_VINTAGE_UPSERT), row)
    return True


def _has_probe_column(engine) -> bool:
    """`vintage_probe_at` 이 **실제로 쓸 수 있는지** 확인한다.

    ★붙은 줄 알고 진행하면 최악이다★ — 갭 질의가 이 컬럼을 `WHERE` 에서 쓰므로,
    없는데 있다고 믿으면 질의가 깨지거나(조용히 빈 목록 = 아무것도 안 채움)
    조건이 빠져 **매 실행 전량 재조회**가 된다. 둘 다 조용하다.
    `ensure_vintage_table()` 이 이미 같은 함정을 적어 두고 같은 방식으로 막는다.
    """
    from sqlalchemy import text
    try:
        with engine.connect() as conn:
            conn.execute(text(
                f"SELECT {PROBE_COLUMN} FROM financials_history LIMIT 1"))
        return True
    except Exception:  # noqa: BLE001
        return False


def mark_vintage_probed(engine, ticker: str, bsns_year: str,
                        reprt_code: str) -> bool:
    """이 기간을 **빈티지 목적으로 조회했다**고 기록한다.

    ★"빈티지가 없다" 고 적는 것이 아니다★ — 적는 것은 *우리가 물어봤다* 이고,
    제공자가 나중에 채울 수 있으므로 `retry_probed` 로 다시 연다.
    ★빈 빈티지 행을 만들지 않는다★ — 그것은 없는 사실을 지어내는 것이다.
    """
    from sqlalchemy import text
    try:
        with engine.begin() as conn:
            conn.execute(text(
                f"UPDATE financials_history SET {PROBE_COLUMN} = :at "
                "WHERE ticker=:t AND bsns_year=:y AND reprt_code=:r"),
                {"at": datetime.now().isoformat(timespec="seconds"),
                 "t": str(ticker), "y": str(bsns_year), "r": str(reprt_code)})
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("빈티지 시도 기록 실패 (%s %s/%s): %s",
                       ticker, bsns_year, reprt_code, e)
        return False


def vintage_gap(engine, *, limit: int | None = None,
                retry_probed: bool = False) -> list[tuple]:
    """빈티지가 **없는** (종목, 연도, 보고서) — 소급 백필의 후보.

    ★기존 `existing_keys()` 를 건드리지 않는다★ 그 키를 4-튜플로 바꾸면 정규
    백필이 매 실행 전량 재조회가 되어 DART 일 20,000건 쿼터를 태운다. 대신
    `refetch_revenue_null()` 과 같은 방식으로 **갭만** 고른다 — 채워지면 후보에서
    빠지므로 재실행이 저렴하고 **수렴한다**.

    ★최신 연도부터★ 백테스트가 최근 기간을 더 자주 보고, 쿼터가 중간에 끊겨도
    가치 있는 쪽이 먼저 채워진다.
    """
    from sqlalchemy import text
    sql = (
        "SELECT h.ticker, h.bsns_year, h.reprt_code "
        "FROM financials_history h "
        f"LEFT JOIN {VINTAGE_TABLE} v "
        "  ON v.ticker = h.ticker AND v.bsns_year = h.bsns_year "
        " AND v.reprt_code = h.reprt_code "
        "WHERE v.ticker IS NULL "
        f"  AND ({PROBE_COLUMN} IS NULL OR :retry = 1) "
        "ORDER BY h.bsns_year DESC, h.ticker"
    )
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    with engine.connect() as conn:
        rows = conn.execute(text(sql), {"retry": 1 if retry_probed else 0}).fetchall()
    return [(str(r[0]), str(r[1]), str(r[2])) for r in rows]


def backfill_vintages(engine=None, client=None, max_calls: int | None = None,
                      retry_probed: bool = False, progress_cb=None) -> dict:
    """빈티지 소급 백필 — ★갭만 재조회한다★ (로드맵 3단계)

    `refetch_revenue_null()` 의 형제다. 후보는 `vintage_gap()` 이 고르고, 각
    후보에 재무제표 호출 한 번을 쓴다 — ★접수번호는 그 응답에 딸려 온다★
    (`dart_client.py` 가 `fnlttSinglAcnt.json` 의 `rcept_no` 를 그대로 꺼내고
    `rcept_dt` 는 `filing_date_of()` 로 로컬 파생한다). 별도 엔드포인트가 없다.

    ★세 결과를 뭉치지 않는다★ — 처방이 전부 다르다:

        성공                  빈티지가 생긴다 → 다음부터 갭이 아니다(수렴)
        접수번호 없음          **시도 흔적**을 남긴다 → 다시 묻지 않는다
        조회 실패(None·예외)   ★흔적을 남기지 않는다★ → 다음에 다시 시도한다

    마지막이 핵심이다: 일시적 실패를 항구적으로 표시하면 **되찾을 수 있는
    데이터를 영영 잃는다.** 대신 `failed` 로 세어 사용자가 본다.

    ★본문(`upsert_statement`)을 다시 쓰지 않는다★ 대상은 접수일이고 본문은 이미
    있다. 다시 쓰면 다른 경로(`refetch_revenue_null` 등)의 갱신을 덮을 수 있다.
    """
    from src.data.dart_client import DARTClient, get_corp_code
    client = client or DARTClient()
    if not getattr(client, "is_configured", False):
        return {"error": True, "message": "DART_API_KEY 미설정 — .env에 키를 넣고 실행하세요"}
    engine = _get_engine(engine)
    if engine is None:
        return {"error": True, "message": "DB engine 없음"}
    ensure_history_table(engine)
    if not ensure_vintage_table(engine):
        return {"error": True, "message": f"{VINTAGE_TABLE} 를 쓸 수 없습니다"}
    # ★조용히 전량 재조회하지 않는다★ 컬럼이 없으면 흔적을 남길 수 없고,
    # 그러면 접수번호 없는 기간을 매 실행 다시 묻게 된다.
    if not _has_probe_column(engine):
        return {"error": True,
                "message": (f"`financials_history.{PROBE_COLUMN}` 컬럼이 없습니다 — "
                            "시도 흔적을 남길 수 없어 중단합니다(그대로 진행하면 "
                            "접수번호 없는 기간을 매 실행 다시 조회합니다).")}

    targets = vintage_gap(engine, retry_probed=retry_probed)
    stats = {"candidates": len(targets), "calls": 0, "saved": 0,
             "no_rcept": 0, "failed": 0, "no_corp": 0,
             "tickers": len({t[0] for t in targets})}
    corp_cache: dict[str, str | None] = {}
    for tk, year, reprt in targets:
        if max_calls is not None and stats["calls"] >= max_calls:
            stats["stopped_at_quota"] = True
            break
        if tk not in corp_cache:
            corp_cache[tk] = get_corp_code(tk)
        corp = corp_cache[tk]
        if not corp:
            stats["no_corp"] += 1
            continue
        try:
            fs = client.get_financial_statement_full(corp, year, reprt_code=reprt)
            stats["calls"] += 1
        except Exception as e:  # noqa: BLE001
            stats["calls"] += 1
            stats["failed"] += 1          # ★흔적을 남기지 않는다 — 일시적일 수 있다★
            logger.debug(f"빈티지 재조회 실패 [{tk} {year}/{reprt}]: {e}")
            continue
        if fs is None:
            stats["failed"] += 1          # 같은 이유로 흔적 없음
            continue
        if _upsert_vintage(engine, tk, fs):
            stats["saved"] += 1
        else:
            # ★제공자가 접수번호를 주지 않았다★ — 항구적 부재로 보고 흔적을 남긴다.
            stats["no_rcept"] += 1
            mark_vintage_probed(engine, tk, year, reprt)
        if progress_cb is not None:
            try:
                progress_cb(stats["calls"], len(targets), stats["saved"], stats["calls"])
            except Exception:
                pass
    return stats


def vintage_stats(engine=None) -> dict:
    """빈티지 적재 현황. ★못 읽으면 `None` + 사유 — 0 이 아니다★

    `restated_periods` 가 답이다 — 행 수가 아니라 **빈티지가 2건 이상인 기간 수**가
    "정정공시를 실제로 봤는가" 를 말한다. 0 이면 "아직 본 적 없다" 이지
    "정정공시가 없다" 가 아니다.
    """
    from sqlalchemy import text
    out = {"rows": None, "restated_periods": None, "gap_periods": None,
           "skipped_no_rcept": _VINTAGE_SKIPPED["no_rcept"], "reason": ""}
    try:
        engine = _get_engine(engine)
        if engine is None:
            out["reason"] = "DB 엔진이 없습니다."
            return out
        with engine.connect() as conn:
            out["rows"] = int(conn.execute(text(
                f"SELECT COUNT(*) FROM {VINTAGE_TABLE}")).scalar() or 0)
            out["restated_periods"] = int(conn.execute(text(
                f"SELECT COUNT(*) FROM (SELECT 1 FROM {VINTAGE_TABLE} "  # noqa: S608
                "GROUP BY ticker, bsns_year, reprt_code HAVING COUNT(*) > 1) x"
            )).scalar() or 0)
    except Exception as e:  # noqa: BLE001
        out["rows"] = out["restated_periods"] = None
        out["reason"] = f"빈티지 테이블을 읽지 못했습니다: {type(e).__name__}: {e}"
    # ★진척도는 별도로 잰다★ 빈티지 테이블은 읽었는데 본문 표를 못 읽는 경우가
    # 있으므로 사유를 따로 붙인다 — ★미상 ≠ 0★ 이라 실패하면 `None` 으로 남긴다
    # (0 으로 적으면 "갭이 없다" = "다 채웠다" 로 읽힌다).
    try:
        engine = _get_engine(engine)
        if engine is not None:
            out["gap_periods"] = len(vintage_gap(engine))
    except Exception as e:  # noqa: BLE001
        out["gap_periods"] = None
        out["reason"] = (out["reason"] + " · " if out["reason"] else "") + (
            f"빈티지 갭을 세지 못했습니다: {type(e).__name__}: {e}")
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# as-of 리더 — ★그때 알 수 있던 재무★
# ═══════════════════════════════════════════════════════════════════════════════
#
# 지금 재무 PIT 은 **고정 시차 추정**이다(연간 90일 · 분기 45일, `pit_store.py:33-35`).
# 저장소가 그 한계를 스스로 적어 뒀다 — `company_snapshot_builder.py:158`:
#   "이 날짜는 실제 공표일이 아니라 정적 시차 규칙으로 추정한 가용일입니다."
# 여기에 **실측 접수일** 기반 조회를 놓는다.
#
# ★구조는 P1 의 매크로 경로 그대로다★ — 백테스트는 봉마다 as-of 를 묻는다.
# 봉마다 DB 를 때리면 종목 × 봉 만큼 쿼리가 나가므로 **읽기 1회 + 순수 필터**로
# 가른다:
#     load_vintages(ticker)          한 번 읽는다        → (행, 사유)
#     vintages_as_of(행, as_of)      봉마다 순수 필터    → 행
#     history_as_of(ticker, as_of)   둘의 편의 조합      → (행, 사유)


#: as_of 는 반드시 `YYYY-MM-DD` — ★문자열 비교라 형식이 틀리면 조용히 전부/전무★.
#: `"2025"` 는 모든 `"2025-03-14"` 보다 작아 아무것도 안 나오고, `"2025-13-01"` 은
#: 모든 것보다 커 전부 나온다. 둘 다 그럴듯해서 아무도 눈치채지 못한다.
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _valid_date(value) -> str | None:
    """`YYYY-MM-DD` 이고 **실재하는 날짜**면 그 문자열, 아니면 `None`."""
    s = str(value or "").strip()
    if not _DATE_RE.match(s):
        return None
    try:
        datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return None
    return s


def _vintage_period(row: dict) -> tuple:
    """valid time 축 — 이 수치가 **설명하는 기간**."""
    return (row["year"], row["reprt"])


def _vintage_stamp(row: dict) -> tuple:
    """transaction time 축 — **언제부터 알 수 있었나**.

    ★접수일만으로는 같은 날 정정의 순서가 갈리지 않는다★ — `rcept_dt` 는 일 단위라
    같은 날 원본과 정정이 동점이 되고, 그러면 답이 **행 순서(=미정)** 에 달린다.
    `rcept_no` 는 `YYYYMMDD` + 그날의 접수순번이므로(V1 의 `filing_date_of` 가 이미
    앞 8자리에 기대고 있다) 그날 안의 순서를 준다. PK 라 유일함도 보장된다.

    ★확인하지 못한 것★ — DART 가 정정공시에 실제로 더 큰 순번을 주는지 실호출로
    보지 못했다(이 컨테이너에 `DART_API_KEY` 없음). 접수번호가 접수 순으로
    부여된다는 것은 공시체계상의 성질이지 우리가 관측한 사실이 아니다.
    """
    return (row["rcept_dt"], row["rcept_no"])


def load_vintages(ticker: str, *, engine=None) -> tuple[list[dict] | None, str | None]:
    """종목의 **모든** 재무 빈티지 행. `(행, 사유)` — ★"없다" 와 "못 읽었다" 를 가른다★

      · `([], None)`      확인했더니 빈티지가 없다 (적재가 얕다)
      · `([...], None)`   읽었다
      · `(None, 사유)`    ★읽지 못했다★ — 테이블 없음·DB 장애 등

    이 구별이 없으면 DB 가 잠깐 죽었을 때 소비자가 "빈티지가 없구나" 로 읽고
    조용히 추정 시차(룩어헤드 근사)로 넘어간다. **하지 않은 진술**이다.
    `pit_macro.load_vintage_obs` 가 매크로에서 같은 이유로 같은 모양을 쓴다.

    행 모양은 `load_history` 의 **상위집합**이다 — 값 컬럼 + `year`/`reprt`/`month`/
    `seq` 에 출처(`rcept_no`·`rcept_dt`)가 붙는다. 그래서 기존 파생 팩터
    (`_compute_history_factors`)가 그대로 돈다.

    ★버리는 행 둘★ — 둘 다 조용히 버리지 않고 로그를 남긴다:
      ① 접수일이 `YYYY-MM-DD` 가 아닌 행 — transaction time 이 없으면 as-of 질문에
         답할 수 없다(`pit_macro` 가 `vintage_id` 빈 행을 버리는 것과 같은 판단).
      ② 월 축에 놓을 수 없는 보고서 코드 — `load_history` 와 같은 처리.
    """
    from sqlalchemy import text
    try:
        engine = _get_engine(engine)
        if engine is None:
            return None, f"DB 엔진이 없어 {VINTAGE_TABLE} 를 읽지 못했습니다."
        cols = ", ".join(_FIELDS)
        with engine.connect() as conn:
            raw = conn.execute(text(
                f"SELECT bsns_year, reprt_code, rcept_no, rcept_dt, {cols} "  # noqa: S608
                f"FROM {VINTAGE_TABLE} WHERE ticker=:t"), {"t": str(ticker)}).fetchall()
    except Exception as e:  # noqa: BLE001
        return None, f"{VINTAGE_TABLE} 를 읽지 못했습니다: {type(e).__name__}: {e}"

    out: list[dict] = []
    dropped = {"no_filing_date": 0, "unplaceable_report": 0}
    for r in raw:
        year, reprt, rcept_no, rcept_dt = str(r[0]), str(r[1]), str(r[2]), _valid_date(r[3])
        if rcept_dt is None:
            dropped["no_filing_date"] += 1
            continue
        month = _REPRT_MONTH.get(reprt)
        if month is None:
            dropped["unplaceable_report"] += 1
            continue
        d = {f: (float(v) if v is not None else None) for f, v in zip(_FIELDS, r[4:])}
        d.update({"year": int(year), "reprt": reprt, "month": month,
                  "seq": int(year) * 12 + month,
                  "rcept_no": rcept_no, "rcept_dt": rcept_dt})
        out.append(d)

    if any(dropped.values()):
        logger.warning("%s %s 빈티지 %d행을 버렸습니다 — 접수일 없음 %d · 미상 보고서코드 %d",
                       VINTAGE_TABLE, ticker, sum(dropped.values()),
                       dropped["no_filing_date"], dropped["unplaceable_report"])

    # ★정렬은 여기서 확정한다★ `financials_history` 리더 8곳이 조용히 깨진 원인이
    # 정렬 부재였다(DB 가 주는 순서는 미정이고 SQLite 와 Postgres 가 다르다).
    out.sort(key=lambda d: (d["seq"], d["rcept_dt"], d["rcept_no"]))
    return out, None


def vintages_as_of(rows: list[dict], as_of: str) -> list[dict]:
    """★순수 함수★ — `as_of` 시점에 알 수 있던 재무만, 기간별 최신 빈티지 하나.

    DB 를 건드리지 않는다. `load_vintages` 로 한 번 읽고 봉마다 이걸 부른다.

    `as_of` 가 `YYYY-MM-DD` 가 아니면 **예외**다 — `pit_macro.accumulate_for_bars`
    가 정렬되지 않은 입력에 `ValueError` 를 내는 것과 같은 규율이다. 조용히 빈
    목록을 돌려주면 "그때는 아무것도 몰랐다" 라는 **하지 않은 진술**이 된다.

    ★경계는 접수일 당일 포함(`<=`)★ 이고, 이 함수는 접수 **시각**을 모른다.
    DART 는 18시까지 접수를 받으므로 장마감 후 접수분이 같은 날에 섞일 수 있다.
    그 안전 여유는 호출자가 **보이는 자리에서** 준다(예: 직전 거래일을 넘긴다) —
    여기서 몰래 하루를 빼면 반대로 "왜 하루 늦나" 를 아무도 찾지 못한다.
    """
    from src.data import pit_macro

    day = _valid_date(as_of)
    if day is None:
        raise ValueError(f"as_of 가 YYYY-MM-DD 형식의 실재 날짜가 아닙니다: {as_of!r}")

    known = [r for r in rows if r.get("rcept_dt") and r["rcept_dt"] <= day]
    picked = pit_macro.latest_vintage_per_period(
        known, period_of=_vintage_period, stamp_of=_vintage_stamp)
    # 사본을 돌려준다 — 봉마다 부르는 자리라, 소비자가 만지면 캐시된 원본이 상한다.
    return sorted((dict(r) for r in picked), key=lambda d: d["seq"])


def history_as_of(ticker: str, as_of: str,
                  *, engine=None) -> tuple[list[dict] | None, str | None]:
    """`load_vintages` + `vintages_as_of` — 한 시점만 물을 때의 편의 조합.

    ★`financials_history` 로 폴백하지 않는다★ 그 테이블은 "지금 값"(정정이 원본을
    덮어쓴 결과)이라 as-of 를 답할 수 없다. 빈티지가 없을 때 그쪽을 읽으면
    **현재 개정본**이 과거 봉에 들어간다 — 막으려던 룩어헤드가 PIT 라벨을 달고
    되돌아온다. 추정 시차로의 **라벨 붙은** 열화는 소비자 층(V4)의 판단이다.
    """
    day = _valid_date(as_of)
    if day is None:
        return None, f"as_of 가 YYYY-MM-DD 형식의 실재 날짜가 아닙니다: {as_of!r}"
    rows, reason = load_vintages(ticker, engine=engine)
    if rows is None:
        return None, reason
    return vintages_as_of(rows, day), None


def ensure_history_table(engine) -> None:
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text(_TABLE_DDL))
    for col in _MIGRATE_COLUMNS:
        try:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE financials_history ADD COLUMN {col}"))
        except Exception:
            pass  # 이미 존재 — 정상


def upsert_statement(engine, ticker: str, fs) -> bool:
    """FinancialStatement 1건 UPSERT. 핵심 값이 전부 비면 저장하지 않음(False)."""
    row = {f: getattr(fs, f, None) for f in _FIELDS}
    if row["revenue"] is None and row["total_assets"] is None and row["net_income"] is None:
        return False
    from sqlalchemy import text
    row.update({
        "ticker": ticker, "bsns_year": str(fs.bsns_year), "reprt_code": str(fs.reprt_code),
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
    })
    with engine.begin() as conn:
        conn.execute(text(_UPSERT), row)
    # ★빈티지는 추가이지 전제가 아니다★ 실패해도 위 적재는 이미 성공했다 —
    # 새 테이블이 기존 적재를 막으면 V2 가 적재를 망가뜨린 것이다.
    try:
        _upsert_vintage(engine, ticker, fs)
    except Exception as e:  # noqa: BLE001
        logger.warning("빈티지 저장 실패 (%s %s/%s) — 기존 적재는 유지됩니다: %s",
                       ticker, fs.bsns_year, fs.reprt_code, e)
    return True


def existing_keys(engine) -> set[tuple]:
    """적재 완료 (ticker, year, reprt) 집합 — resume용."""
    from sqlalchemy import text
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT ticker, bsns_year, reprt_code FROM financials_history")).fetchall()
        return {(str(r[0]), str(r[1]), str(r[2])) for r in rows}
    except Exception:
        return set()


def backfill_financials(tickers: list[str] | None = None, all_listed: bool = False,
                        years: int = 10, include_quarters: bool = False,
                        max_calls: int | None = None,
                        engine=None, client=None, progress_cb=None) -> dict:
    """종목×연도(×분기) 재무 백필 — DART 일쿼터 대응 max_calls 분할 + resume.

    progress_cb(done, total, saved, calls): 종목 1건 처리할 때마다 보고(UI 표면화).
    fallback_to_seed: all_listed=True인데 마스터 캐시가 비어(부팅 시 수집 경쟁 등) SEED
    30종목으로 축소됐는지 — 호출부가 '진짜 완료'와 '축소 실행'을 구분해 재시도 간격을
    조절할 수 있게(짧게 재시도 vs 다음날 증분)."""
    from src.data.dart_client import DARTClient, get_corp_code
    client = client or DARTClient()
    if not client.is_configured:
        return {"error": True, "message": "DART_API_KEY 미설정 — .env에 키를 넣고 실행하세요"}

    engine = _get_engine(engine)
    if engine is None:
        return {"error": True, "message": "DB engine 없음"}
    ensure_history_table(engine)

    fallback_to_seed = False
    if tickers is None:
        if all_listed:
            from src.data_sync import _all_listed_tickers
            tickers = _all_listed_tickers()
            if not tickers:
                fallback_to_seed = True
        if not tickers:
            from src.data_sync import SEED_TICKERS
            tickers = [t[0] for t in SEED_TICKERS]

    last_year = datetime.now().year - 1
    year_list = [str(y) for y in range(last_year, last_year - years, -1)]
    reprts = (REPRT_ANNUAL,) + (QUARTER_REPRTS if include_quarters else ())

    done = existing_keys(engine)
    stats = {"tickers": len(tickers), "calls": 0, "saved": 0,
             "skipped": 0, "empty": 0, "no_corp": 0, "fallback_to_seed": fallback_to_seed}

    for i, tk in enumerate(tickers):
        corp = None
        corp_missing = False  # corp_code 매핑 실패 — 전부 skip된 종목과 구분(resume 버그 방지)
        for year in year_list:
            if corp_missing:
                break
            for reprt in reprts:
                if (tk, year, reprt) in done:
                    stats["skipped"] += 1
                    continue
                if max_calls is not None and stats["calls"] >= max_calls:
                    stats["stopped_at_quota"] = True
                    return stats
                if corp is None:
                    corp = get_corp_code(tk)
                    if not corp:
                        stats["no_corp"] += 1
                        corp_missing = True
                        break  # 이 종목의 모든 연도 skip
                try:
                    fs = client.get_financial_statement_full(corp, year, reprt_code=reprt)
                    stats["calls"] += 1
                    if fs is not None and upsert_statement(engine, tk, fs):
                        stats["saved"] += 1
                    else:
                        stats["empty"] += 1  # 상장 전 연도 등 — 정상
                except Exception as e:
                    stats["empty"] += 1
                    logger.debug(f"재무 조회 실패 [{tk} {year}/{reprt}]: {e}")
        if stats["saved"] and stats["saved"] % 500 == 0:
            logger.info(f"DART 백필 진행: {stats['saved']:,}건 저장 / {stats['calls']:,}콜")
        if progress_cb is not None:
            try:
                progress_cb(i + 1, len(tickers), stats["saved"], stats["calls"])
            except Exception:
                pass
    _HISTORY_CACHE.clear()  # 새 적재분 반영 (파생 팩터 캐시 무효화)
    return stats


def refetch_revenue_null(engine=None, client=None, max_calls: int | None = None,
                         progress_cb=None) -> dict:
    """금융업 등 revenue=NULL로 적재된 (ticker, year, reprt) 행을 확장 파서로 재조회·갱신.

    매출액 라인이 없어 revenue=NULL이던 금융업(은행·보험·증권·지주)을, DART 파서에
    영업수익/이자수익 매핑을 추가한 뒤 다시 채운다. net_income이 있는 행만 대상(진짜
    결측 아님 → 매출 정의만 빠진 것). 파서 확장 후 fs.revenue가 채워진 건만 UPSERT.

    progress_cb(done, total, updated, calls): 재조회 진행 보고.
    이미 revenue가 채워졌으면 후보에서 빠져 재실행이 저렴(멱등)."""
    from src.data.dart_client import DARTClient, get_corp_code
    client = client or DARTClient()
    if not client.is_configured:
        return {"error": True, "message": "DART_API_KEY 미설정"}
    engine = _get_engine(engine)
    if engine is None:
        return {"error": True, "message": "DB engine 없음"}
    ensure_history_table(engine)

    from sqlalchemy import text
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT ticker, bsns_year, reprt_code FROM financials_history "
            "WHERE revenue IS NULL AND net_income IS NOT NULL "
            "ORDER BY ticker, bsns_year DESC"
        )).fetchall()
    targets = [(str(r[0]), str(r[1]), str(r[2])) for r in rows]

    stats = {"candidates": len(targets), "calls": 0, "updated": 0,
             "still_null": 0, "no_corp": 0, "tickers": len({t[0] for t in targets})}
    corp_cache: dict[str, str | None] = {}
    for tk, year, reprt in targets:
        if max_calls is not None and stats["calls"] >= max_calls:
            stats["stopped_at_quota"] = True
            break
        if tk not in corp_cache:
            corp_cache[tk] = get_corp_code(tk)
        corp = corp_cache[tk]
        if not corp:
            stats["no_corp"] += 1
            continue
        try:
            fs = client.get_financial_statement_full(corp, year, reprt_code=reprt)
            stats["calls"] += 1
            if fs is not None and getattr(fs, "revenue", None) is not None:
                upsert_statement(engine, tk, fs)   # 확장 파서로 revenue 채워짐 → 갱신
                stats["updated"] += 1
            else:
                stats["still_null"] += 1           # 영업수익도 없음(진짜 매출 정의 없음) — 잔여
        except Exception as e:
            stats["still_null"] += 1
            logger.debug(f"revenue 재조회 실패 [{tk} {year}/{reprt}]: {e}")
        if progress_cb is not None:
            try:
                progress_cb(stats["calls"], len(targets), stats["updated"], stats["calls"])
            except Exception:
                pass
    _HISTORY_CACHE.clear()  # 갱신분 반영
    return stats


def history_snapshot(ticker: str, bsns_year: str, reprt_code: str, engine=None) -> dict | None:
    """적재된 (종목, 연도, 보고서) 재무 1건 → dict. 없으면 None (PIT가 실시간 폴백)."""
    from sqlalchemy import text
    try:
        engine = _get_engine(engine)
        if engine is None:
            return None
        cols = ", ".join(_FIELDS)
        with engine.connect() as conn:
            row = conn.execute(text(
                f"SELECT {cols} FROM financials_history "  # noqa: S608 — 컬럼 상수
                "WHERE ticker=:t AND bsns_year=:y AND reprt_code=:r"
            ), {"t": str(ticker), "y": str(bsns_year), "r": str(reprt_code)}).fetchone()
        if row is None:
            return None
        return {f: (float(v) if v is not None else None) for f, v in zip(_FIELDS, row)}
    except Exception:
        return None


# 손익 연환산 계수 — DART 분기 보고서의 손익 항목은 누적(1Q=3개월, 반기=6개월, 3Q=9개월)
# 기준이라 그대로 쓰면 ROE/PER이 ×4~×1.33 왜곡된다. (표준 XBRL 누적 가정 — 문서화)
ANNUALIZE_FACTOR = {"11011": 1.0, "11012": 2.0, "11013": 4.0, "11014": 4.0 / 3.0}


def annualized_net_income(row: dict, reprt_code: str | None) -> float | None:
    ni = row.get("net_income")
    if ni is None:
        return None
    return ni * ANNUALIZE_FACTOR.get(str(reprt_code or "11011"), 1.0)


# ═══════════════════════════════════════════════════════════════════════════════
# 시계열 파생 팩터 — 흑자전환·3년연속·성장률류 (조건식 펀더멘털 토큰)
#   · YoY = 동일 보고서(누적) 전년 대비 — 누적끼리 비교라 연환산 불필요
#   · QOQ = 단일 분기값(누적 차분: 반기-1Q 등) 비교 — 인접 보고서 없으면 None(정직)
#   · 3년연속 = 최근 3개 연간 보고서 기준 (부족하면 None)
#   현재 스냅샷 기준(최신 적재 보고서) — 펀더멘털 토글과 동일한 look-ahead 근사.
# ═══════════════════════════════════════════════════════════════════════════════

_REPRT_MONTH = {"11013": 3, "11012": 6, "11014": 9, "11011": 12}

HISTORY_FACTOR_IDS = (
    "ni_positive_3y", "op_positive_3y",
    "ni_turnaround_yoy", "ni_turnaround_qoq", "op_turnaround_yoy", "op_turnaround_qoq",
    "ni_growth_yoy", "ni_growth_qoq", "op_growth_qoq",
    "asset_growth_yoy", "equity_growth_yoy",
    "debt_ratio_growth_yoy", "current_ratio_growth_yoy",
    "gross_margin_growth_yoy", "asset_turnover_growth_yoy",
    "roa_growth_yoy", "roe_growth_yoy",
    "dps_up_3y", "dps_growth_yoy",
)

_HISTORY_CACHE: dict[str, dict] = {}


def load_history(ticker: str, engine=None) -> list[dict]:
    """종목의 전체 적재 행 (연대순 정렬, year/reprt/month 포함). 없으면 []."""
    from sqlalchemy import text
    try:
        engine = _get_engine(engine)
        if engine is None:
            return []
        cols = ", ".join(_FIELDS)
        with engine.connect() as conn:
            rows = conn.execute(text(
                f"SELECT bsns_year, reprt_code, {cols} FROM financials_history "  # noqa: S608
                "WHERE ticker=:t"), {"t": str(ticker)}).fetchall()
        out = []
        for r in rows:
            year, reprt = str(r[0]), str(r[1])
            month = _REPRT_MONTH.get(reprt)
            if month is None:
                continue
            d = {f: (float(v) if v is not None else None) for f, v in zip(_FIELDS, r[2:])}
            d.update({"year": int(year), "reprt": reprt, "month": month,
                      "seq": int(year) * 12 + month})
            out.append(d)
        out.sort(key=lambda x: x["seq"])
        return out
    except Exception:
        return []


def _growth(cur, prev) -> float | None:
    """성장률(%) — 기반(prev)이 양수일 때만 의미 있음.

    음수 기반(전년 적자 등)의 '성장률'은 부호가 뒤집혀 오독을 유발 → None,
    그 경우는 흑자전환(turnaround) 토큰이 담당한다."""
    if cur is None or prev is None or prev <= 0:
        return None
    return (cur - prev) / prev * 100.0


def _turnaround(cur, prev) -> float | None:
    if cur is None or prev is None:
        return None
    return 1.0 if (prev <= 0 < cur) else 0.0


def _ratio(a, b, scale=100.0) -> float | None:
    if a is None or b in (None, 0, 0.0):
        return None
    return a / b * scale


def _single_quarters(rows: list[dict], field: str) -> list[tuple[int, float]]:
    """누적 손익 → 단일 분기값 [(seq, value)]. 1Q=누적, 이후는 직전 보고서와의 차분
    (같은 연도 내 인접 보고서가 있을 때만 — 없으면 그 분기는 산출 불가)."""
    by_key = {(r["year"], r["month"]): r.get(field) for r in rows}
    singles = []
    for r in rows:
        v = r.get(field)
        if v is None:
            continue
        if r["month"] == 3:
            singles.append((r["seq"], v))
            continue
        prev = by_key.get((r["year"], r["month"] - 3))
        if prev is not None:
            singles.append((r["seq"], v - prev))
    return singles


def _compute_history_factors(rows: list[dict]) -> dict:
    out: dict = dict.fromkeys(HISTORY_FACTOR_IDS)
    if not rows:
        return out
    latest = rows[-1]

    # 동일 보고서 전년(YoY) — 누적끼리 비교
    prev_y = next((r for r in reversed(rows[:-1])
                   if r["year"] == latest["year"] - 1 and r["reprt"] == latest["reprt"]), None)
    if prev_y is not None:
        out["ni_turnaround_yoy"] = _turnaround(latest.get("net_income"), prev_y.get("net_income"))
        out["op_turnaround_yoy"] = _turnaround(latest.get("operating_profit"),
                                               prev_y.get("operating_profit"))
        out["ni_growth_yoy"] = _growth(latest.get("net_income"), prev_y.get("net_income"))
        out["asset_growth_yoy"] = _growth(latest.get("total_assets"), prev_y.get("total_assets"))
        out["equity_growth_yoy"] = _growth(latest.get("total_equity"), prev_y.get("total_equity"))
        for fid, cur_v, prev_v in (
            ("debt_ratio_growth_yoy",
             _ratio(latest.get("total_liabilities"), latest.get("total_equity")),
             _ratio(prev_y.get("total_liabilities"), prev_y.get("total_equity"))),
            ("current_ratio_growth_yoy",
             _ratio(latest.get("current_assets"), latest.get("current_liabilities")),
             _ratio(prev_y.get("current_assets"), prev_y.get("current_liabilities"))),
            ("gross_margin_growth_yoy",
             _ratio(latest.get("gross_profit"), latest.get("revenue")),
             _ratio(prev_y.get("gross_profit"), prev_y.get("revenue"))),
            ("asset_turnover_growth_yoy",
             _ratio(latest.get("revenue"), latest.get("total_assets"), 1.0),
             _ratio(prev_y.get("revenue"), prev_y.get("total_assets"), 1.0)),
            ("roa_growth_yoy",
             _ratio(latest.get("net_income"), latest.get("total_assets")),
             _ratio(prev_y.get("net_income"), prev_y.get("total_assets"))),
            ("roe_growth_yoy",
             _ratio(latest.get("net_income"), latest.get("total_equity")),
             _ratio(prev_y.get("net_income"), prev_y.get("total_equity"))),
        ):
            out[fid] = _growth(cur_v, prev_v)

    # 단일 분기(QOQ) — 누적 차분, 인접(3개월) 분기끼리만
    for fid_g, fid_t, field in (("ni_growth_qoq", "ni_turnaround_qoq", "net_income"),
                                ("op_growth_qoq", "op_turnaround_qoq", "operating_profit")):
        singles = _single_quarters(rows, field)
        if len(singles) >= 2 and singles[-1][0] - singles[-2][0] == 3:
            out[fid_g] = _growth(singles[-1][1], singles[-2][1])
            out[fid_t] = _turnaround(singles[-1][1], singles[-2][1])

    # 3년연속 (연간 보고서 3개 필요)
    annuals = [r for r in rows if r["reprt"] == REPRT_ANNUAL][-3:]
    if len(annuals) == 3:
        ni = [r.get("net_income") for r in annuals]
        op = [r.get("operating_profit") for r in annuals]
        if all(v is not None for v in ni):
            out["ni_positive_3y"] = 1.0 if all(v > 0 for v in ni) else 0.0
        if all(v is not None for v in op):
            out["op_positive_3y"] = 1.0 if all(v > 0 for v in op) else 0.0
        dps = [r.get("dps") for r in annuals]
        if all(v is not None for v in dps):
            out["dps_up_3y"] = 1.0 if (dps[0] <= dps[1] <= dps[2]) else 0.0
    if len(annuals) >= 2:
        out["dps_growth_yoy"] = _growth(annuals[-1].get("dps"), annuals[-2].get("dps"))
    return out


def history_factors(ticker: str, engine=None) -> dict:
    """시계열 파생 팩터 (캐시) — 적재 없으면 전부 None(조건 건너뜀)."""
    key = str(ticker)
    if key in _HISTORY_CACHE:
        return _HISTORY_CACHE[key]
    out = _compute_history_factors(load_history(key, engine))
    _HISTORY_CACHE[key] = out
    return out


def ratios_from_row(row: dict, reprt_code: str | None = None) -> dict:
    """재무 행 → PIT 스냅샷 비율 (ROE/ROA/부채비율 %). 분모 없으면 None.

    reprt_code가 분기 보고서면 손익(순이익)을 연환산해 연간 기준과 비교 가능하게."""
    def _div(a, b):
        return (a / b * 100.0) if (a is not None and b not in (None, 0, 0.0)) else None
    ni_ann = annualized_net_income(row, reprt_code)
    return {
        "roe_pct": _div(ni_ann, row.get("total_equity")),
        "roa_pct": _div(ni_ann, row.get("total_assets")),
        "debt_ratio_pct": _div(row.get("total_liabilities"), row.get("total_equity")),
    }


def main() -> None:
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="DART 재무 시계열 백필 → financials_history")
    ap.add_argument("--years", type=int, default=10)
    ap.add_argument("--quarters", action="store_true", help="분기 보고서(1Q/반기/3Q)도 적재")
    ap.add_argument("--tickers", default=None, help="쉼표 구분 (기본 SEED)")
    ap.add_argument("--all-listed", action="store_true", help="마스터 전 주권 대상")
    ap.add_argument("--max-calls", type=int, default=18000,
                    help="이번 실행 최대 호출 수 (DART 일쿼터 20,000 보호)")
    ap.add_argument("--vintages", action="store_true",
                    help="★소급 백필★ 이미 적재된 기간 중 빈티지가 없는 것만 다시 "
                         "받아 접수일을 채운다(정규 백필은 건드리지 않는다)")
    ap.add_argument("--retry-probed", action="store_true",
                    help="접수번호를 못 받아 표시해 둔 기간도 다시 시도한다")
    args = ap.parse_args()

    if args.vintages:
        stats = backfill_vintages(max_calls=args.max_calls,
                                  retry_probed=args.retry_probed)
        print(f"빈티지 소급 백필 결과: {stats}")
        if stats.get("error"):
            return
        # ★셋을 나눠서 읽는다★ 처방이 전부 다르다.
        print(f"→ 채움 {stats['saved']} · 접수번호 없음 {stats['no_rcept']}"
              f"(다시 묻지 않음 — `--retry-probed` 로 재개) · "
              f"조회 실패 {stats['failed']}(★흔적을 남기지 않았으므로 다음 실행에서 "
              f"다시 시도합니다★)")
        if stats.get("stopped_at_quota"):
            print("→ 쿼터 도달로 중단 — 같은 명령으로 재실행하면 이어서 채웁니다"
                  "(갭이 줄어들므로 수렴합니다)")
        remaining = vintage_stats()
        print(f"→ 남은 갭: {remaining.get('gap_periods')} 기간"
              + (f"  ({remaining['reason']})" if remaining.get("reason") else ""))
        return

    tickers = [t.strip() for t in args.tickers.split(",")] if args.tickers else None
    stats = backfill_financials(tickers=tickers, all_listed=args.all_listed,
                                years=args.years, include_quarters=args.quarters,
                                max_calls=args.max_calls)
    print(f"재무 백필 결과: {stats}")
    if stats.get("stopped_at_quota"):
        print("→ 쿼터 도달로 중단 — 내일 같은 명령으로 재실행하면 이어서 적재됩니다(resume)")


if __name__ == "__main__":
    main()
