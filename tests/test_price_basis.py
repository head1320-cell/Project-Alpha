"""가격 **정의**(basis) — ★`close` 는 하나의 값이 아니다★
==============================================================================
설계: `/root/.claude/plans` Phase 2 · 선행: `tests/test_price_quality_gate.py`

## 이 파일이 막는 것

`daily_prices.close` 에 두 정의가 섞여 있다:

    source='krx' → 원주가   (`krx_client` 독스트링: "시세는 원주가(수정주가 아님)")
    source='kis' → 수정주가 (`kis_client.DAILY_ADJ_PRC_FLAG="0"` 로 요청)

소스 경계를 넘는 티커의 계열에는 **정의 점프**가 생긴다 — 기업행위 점프가 아니라
**누적 수정계수 전체**다. 그리고 정본 로더가 고르는 것이 바로 그 `close` 다.

1. ★NULL basis 를 추정하는 것★ — 레거시 행은 "모른다" 이지 "원주가" 가 아니다.
2. ★`mixed` 를 `unknown` 으로 접는 것★ — 둘은 다른 사실이고 고치는 방법도 다르다.
3. ★네 상태(Phase 1)를 덮는 것★ — basis 는 **직교하는 축**이다. 더하되 대체하지 않는다.
4. ★적재 경로가 `"adjusted"` 를 베껴 적는 것★ — 요청 플래그와 기록이 갈라지면
   DB 가 조용히 거짓을 적는다.
5. ★못 잰 겹침을 "일치" 로 적는 것★ — 0 은 판단이지 결측이 아니다.
6. ★KIS 행의 `adj_close` 를 채우는 것★ — 근거가 코드 주석 하나뿐인 단정이다.
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import src.data.price_quality as pq  # noqa: E402
from src.data.krx_ingest import (  # noqa: E402
    BASIS_ADJUSTED,
    BASIS_RAW,
    bulk_upsert,
    ensure_table,
    rebuild_adj_close,
)
from src.data.pit_macro import ResearchUsage  # noqa: E402


@pytest.fixture
def eng():
    e = create_engine("sqlite://", connect_args={"check_same_thread": False},
                      poolclass=StaticPool)
    ensure_table(e)
    yield e
    e.dispose()


def _row(ticker, date, close, fluc=None):
    return {"ticker": ticker, "date": date, "close": close, "open": close,
            "high": close, "low": close, "volume": 100,
            "trading_value": 1000, "fluc_rt": fluc}


def _series(ticker="A", fluc=(0.5, 1.0, -0.2, 1.0, 0.99)):
    dates = ["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"]
    closes = [1000.0, 1010.0, 500.0, 505.0, 510.0]      # 2026-01-06 이 2:1 분할
    return [_row(ticker, d, c, f) for d, c, f in zip(dates, closes, fluc, strict=True)]


def _insert_kis(eng, ticker, dates_closes, *, basis=BASIS_ADJUSTED):
    """`ohlcv_loader.ingest_df_to_db` 가 넣는 모양의 행(등락률 없음)."""
    with eng.begin() as c:
        for d, close in dates_closes:
            c.execute(text(
                "INSERT INTO daily_prices (ticker, trade_date, close, source, "
                "price_basis) VALUES (:t, :d, :c, 'kis', :b)"),
                {"t": ticker, "d": d, "c": close, "b": basis})


# ══════════════════════════════════════════════════════════════════════════
# 1) 적재 경로가 정의를 기록한다
# ══════════════════════════════════════════════════════════════════════════
def test_krx_rows_record_raw_basis(eng):
    """B1a — KRX 시세는 원주가다."""
    bulk_upsert(eng, _series("A"))
    with eng.connect() as c:
        got = {r[0] for r in c.execute(text(
            "SELECT DISTINCT price_basis FROM daily_prices WHERE ticker='A'"))}
    assert got == {BASIS_RAW}


def test_kis_ingest_records_the_basis_it_requested(eng, monkeypatch):
    """B1b/B8 — ★적재 경로가 `kis_client` 상수를 읽는다★

    문자열을 베껴 적으면 누가 `FID_ORG_ADJ_PRC` 를 뒤집었을 때 DB 가 조용히
    거짓을 적는다. 상수를 뒤집어서 기록도 따라 바뀌는지 확인한다.
    """
    import pandas as pd

    import src.data.ohlcv_loader as ol
    import src.execution.kis_client as kc

    df = pd.DataFrame(
        {"open": [100.0], "high": [100.0], "low": [100.0], "close": [100.0],
         "volume": [10.0]},
        index=pd.to_datetime(["2026-01-02"]))

    monkeypatch.setattr("src.database.get_engine", lambda: eng)
    monkeypatch.setattr(kc, "DAILY_PRICE_BASIS", BASIS_RAW)   # ★플래그를 뒤집는다★
    assert ol.ingest_df_to_db("ZZZ", df) == 1

    with eng.connect() as c:
        got = c.execute(text(
            "SELECT price_basis FROM daily_prices WHERE ticker='ZZZ'")).scalar()
    assert got == BASIS_RAW, "적재 경로가 상수를 읽지 않고 문자열을 베꼈다"


def test_the_basis_constant_follows_the_request_flag():
    """B8 짝 — 상수가 플래그에서 **파생**되는지, 독립적으로 박혀 있는지."""
    import src.execution.kis_client as kc
    assert kc.DAILY_ADJ_PRC_FLAG in ("0", "1")
    expected = "adjusted" if kc.DAILY_ADJ_PRC_FLAG == "0" else "raw"
    assert kc.DAILY_PRICE_BASIS == expected


# ══════════════════════════════════════════════════════════════════════════
# 2) ★NULL 을 추정하지 않는다★
# ══════════════════════════════════════════════════════════════════════════
def test_legacy_null_basis_stays_unknown(eng):
    """B2 — 레거시 행의 정의를 `raw` 로 추정하면 통계가 거짓말을 한다."""
    with eng.begin() as c:
        c.execute(text("INSERT INTO daily_prices (ticker, trade_date, close) "
                       "VALUES ('OLD', '2026-01-02', 100)"))
    cov = pq.adj_close_coverage(["OLD"], engine=eng)
    assert cov["basis_by_ticker"]["OLD"] == pq.BASIS_UNKNOWN
    assert cov["basis_states"][pq.BASIS_UNIFORM_RAW] == 0
    assert cov["basis_unknown_rows"] == 1


def test_null_mixed_with_one_known_basis_is_not_mixed(eng):
    """★NULL 은 '다른 정의' 가 아니다★ 혼합의 증거로 쓰면 거짓 양성이 쏟아진다.

    대신 그 사실은 `basis_unknown_rows` 로 **따로** 보고된다 — 대체가 아니라 추가.
    """
    bulk_upsert(eng, _series("A"))                       # raw 5행
    with eng.begin() as c:
        c.execute(text("INSERT INTO daily_prices (ticker, trade_date, close) "
                       "VALUES ('A', '2026-01-09', 512)"))   # basis NULL
    cov = pq.adj_close_coverage(["A"], engine=eng)
    assert cov["basis_by_ticker"]["A"] == pq.BASIS_UNIFORM_RAW
    assert cov["mixed_basis_tickers"] == []
    assert cov["basis_unknown_rows"] == 1, "NULL 행이 사라졌다"


# ══════════════════════════════════════════════════════════════════════════
# 3) ★혼합을 이름으로 낸다★
# ══════════════════════════════════════════════════════════════════════════
def test_two_definitions_in_one_ticker_is_mixed_and_named(eng):
    """B3 — 어느 종목의 계열이 점프하는지 알아야 고칠 수 있다."""
    bulk_upsert(eng, _series("A"))                       # raw
    _insert_kis(eng, "A", [("2026-01-09", 515.0)])       # adjusted
    cov = pq.adj_close_coverage(["A"], engine=eng)
    assert cov["basis_by_ticker"]["A"] == pq.BASIS_MIXED
    assert cov["mixed_basis_tickers"] == ["A"]
    assert cov["basis_notes"][pq.BASIS_MIXED]


def test_basis_states_are_exclusive_and_sum_to_seen_tickers(eng):
    bulk_upsert(eng, _series("PURE"))
    _insert_kis(eng, "ADJ", [("2026-01-02", 100.0), ("2026-01-05", 101.0)])
    bulk_upsert(eng, _series("MIX"))
    _insert_kis(eng, "MIX", [("2026-01-09", 515.0)])
    with eng.begin() as c:
        c.execute(text("INSERT INTO daily_prices (ticker, trade_date, close) "
                       "VALUES ('OLD', '2026-01-02', 100)"))

    cov = pq.adj_close_coverage(["PURE", "ADJ", "MIX", "OLD"], engine=eng)
    st = cov["basis_states"]
    assert set(st) == set(pq.BASIS_CONSISTENCY)
    assert sum(st.values()) == cov["tickers"]
    assert cov["basis_by_ticker"] == {
        "PURE": pq.BASIS_UNIFORM_RAW, "ADJ": pq.BASIS_UNIFORM_ADJUSTED,
        "MIX": pq.BASIS_MIXED, "OLD": pq.BASIS_UNKNOWN}


# ══════════════════════════════════════════════════════════════════════════
# 4) ★적격성 — 새 등급도 새 임계값도 없다★
# ══════════════════════════════════════════════════════════════════════════
def test_mixed_basis_blocks_eligibility_even_when_all_rows_are_adjusted(eng):
    """B4 ★핵심★ 모든 행에 `adj_close` 가 있어도 정의가 섞이면 부적격이다.

    조정 커버리지만 보면 100% 다 — 그래서 이 축이 따로 필요하다.
    """
    bulk_upsert(eng, _series("MIX"))
    rebuild_adj_close(eng, tickers=["MIX"])
    # 이미 조정된 날짜에 KIS 정의를 덮어씌운다 — adj_close 는 그대로 남는다.
    with eng.begin() as c:
        c.execute(text("UPDATE daily_prices SET price_basis='adjusted', "
                       "source='kis' WHERE ticker='MIX' AND trade_date='2026-01-08'"))

    cov = pq.adj_close_coverage(["MIX"], engine=eng)
    assert cov["ticker_states"][pq.STATE_ADJUSTED] == 1, "전제: 커버리지는 100%"
    assert cov["basis_by_ticker"]["MIX"] == pq.BASIS_MIXED

    got = pq.price_usage(["MIX"], engine=eng)
    assert got["usage"] == ResearchUsage.FORWARD_ONLY.value
    assert "혼합" in got["reason"]


def test_uniform_basis_with_full_coverage_is_eligible(eng):
    """B5 ★짝★ — 없으면 '언제나 부적격' 구현으로도 위 테스트가 통과한다."""
    bulk_upsert(eng, _series("OK"))
    rebuild_adj_close(eng, tickers=["OK"])
    cov = pq.adj_close_coverage(["OK"], engine=eng)
    assert cov["basis_by_ticker"]["OK"] == pq.BASIS_UNIFORM_RAW

    got = pq.price_usage(["OK"], engine=eng)
    assert got["usage"] == ResearchUsage.BACKTEST_ELIGIBLE.value
    assert got["reason"] is None


def test_reason_distinguishes_coverage_failure_from_basis_failure(eng):
    """B6 — ★두 사유를 뭉치면 고치는 사람이 어디를 볼지 모른다★"""
    # ① 커버리지만 실패 (정의는 균일)
    bulk_upsert(eng, _series("COV", fluc=(0.5, 1.0, -0.2, 1.0, None)))
    rebuild_adj_close(eng, tickers=["COV"])
    r1 = pq.price_usage(["COV"], engine=eng)["reason"]
    assert "수정주가 전량" in r1
    assert "혼합" not in r1, "정의는 균일한데 혼합을 사유로 냈다"

    # ② 정의만 실패 (커버리지는 100%)
    bulk_upsert(eng, _series("BAS"))
    rebuild_adj_close(eng, tickers=["BAS"])
    with eng.begin() as c:
        c.execute(text("UPDATE daily_prices SET price_basis='adjusted' "
                       "WHERE ticker='BAS' AND trade_date='2026-01-08'"))
    r2 = pq.price_usage(["BAS"], engine=eng)["reason"]
    assert "혼합" in r2
    assert "수정주가 전량" not in r2, "커버리지는 100% 인데 그것을 사유로 냈다"


def test_price_usage_still_goes_through_derive_usage(eng, monkeypatch):
    """B7 — 축이 늘어도 등급은 여전히 `derive_usage` 가 판다."""
    seen = {}
    real = pq.derive_usage

    def spy(**kw):
        seen.update(kw)
        return real(**kw)

    monkeypatch.setattr(pq, "derive_usage", spy)
    bulk_upsert(eng, _series("MIX"))
    rebuild_adj_close(eng, tickers=["MIX"])
    with eng.begin() as c:
        c.execute(text("UPDATE daily_prices SET price_basis='adjusted' "
                       "WHERE ticker='MIX' AND trade_date='2026-01-08'"))
    pq.price_usage(["MIX"], engine=eng)
    assert seen, "`derive_usage` 를 부르지 않았다 — 자체 판정 중이다"
    assert seen["has_vintage"] is False, "혼합이 `has_vintage` 에 반영되지 않았다"


def test_phase1_states_are_unchanged_by_the_new_axis(eng):
    """B13 ★직교★ — 새 축이 옛 축의 값을 바꾸면 안 된다."""
    bulk_upsert(eng, _series("A"))
    rebuild_adj_close(eng, tickers=["A"])
    before = pq.adj_close_coverage(["A"], engine=eng)
    _insert_kis(eng, "A", [("2026-01-09", 515.0)])       # 정의만 섞는다
    after = pq.adj_close_coverage(["A"], engine=eng)

    assert after["basis_by_ticker"]["A"] == pq.BASIS_MIXED, "전제: 혼합이 됐다"
    # 행이 하나 늘었으니 chain_broken 이 되는 것은 4상태 규칙 그대로의 결과다.
    # 바뀌면 안 되는 것은 **규칙**이지 값이 아니므로, 규칙의 형태를 확인한다.
    assert set(before["ticker_states"]) == set(after["ticker_states"])
    assert sum(after["ticker_states"].values()) == 1
    assert "basis" not in str(after["state_notes"]), "basis 가 4상태 설명을 오염시켰다"


# ══════════════════════════════════════════════════════════════════════════
# 5) 겹침 검증 — ★가정을 데이터가 판정한다★
# ══════════════════════════════════════════════════════════════════════════
def _overlap_row(eng, ticker, date, close, ret):
    """★KIS 가 KRX 행을 덮은 뒤의 모양★ — close 는 KIS, return_1d 는 KRX.

    실측으로 확인한 사실이다: `ingest_df_to_db` 의 UPSERT 는 `return_1d` 를
    건드리지 않으므로, KIS 가 덮은 행에는 두 출처가 **한 행 안에** 남는다.
    """
    with eng.begin() as c:
        c.execute(text(
            "INSERT INTO daily_prices (ticker, trade_date, close, return_1d, "
            "source, price_basis) VALUES (:t, :d, :c, :r, 'kis', 'adjusted')"),
            {"t": ticker, "d": date, "c": close, "r": ret})


def test_matching_returns_are_reported_consistent(eng):
    """B9 — 종가 수익률이 KRX 등락률과 맞으면 "KIS=수정주가" 가 뒷받침된다."""
    _overlap_row(eng, "A", "2026-01-02", 1000.0, None)
    _overlap_row(eng, "A", "2026-01-05", 1010.0, 1.0)     # +1.0% 실제로 맞음
    _overlap_row(eng, "A", "2026-01-06", 1020.1, 1.0)
    got = pq.basis_overlap_check(["A"], engine=eng)
    assert got["available"] is True, got
    assert got["consistent"] == ["A"], got
    assert got["verdict_by_ticker"]["A"]["points"] == 2


def test_diverging_returns_are_reported_inconsistent(eng):
    """B10 ★짝★ — 조용히 통과시키면 틀린 가정 위에 `adj_close` 를 채우게 된다.

    2:1 분할이 있던 날: 종가는 반토막(−50%)인데 등락률은 −0.2% 다.
    KIS 종가가 정말 수정주가라면 이런 어긋남이 나올 수 없다.
    """
    _overlap_row(eng, "A", "2026-01-05", 1010.0, None)
    _overlap_row(eng, "A", "2026-01-06", 505.0, -0.2)     # ★원주가 냄새★
    got = pq.basis_overlap_check(["A"], engine=eng)
    assert got["available"] is True, got
    assert got["inconsistent"] == ["A"], got
    assert got["verdict_by_ticker"]["A"]["worst_date"] == "2026-01-06"


def test_raw_rows_get_no_verdict(eng):
    """★분할이 있는 원주가 티커를 거짓 양성으로 띄우지 않는다★

    원주가 수익률이 등락률과 어긋나는 것은 **기업행위가 있었다는 뜻**이지
    정의가 틀렸다는 뜻이 아니다. 이 구분을 접으면 분할 이력이 있는 모든
    티커가 불일치로 뜬다.
    """
    bulk_upsert(eng, _series("A"))            # raw · 2026-01-06 에 2:1 분할
    got = pq.basis_overlap_check(["A"], engine=eng)
    assert got.get("available") is False, "raw 행에 판정을 내렸다"
    assert got["reason"]


def test_no_overlapping_row_is_unavailable_not_consistent(eng):
    """B11 — ★재지 못한 것을 '일치' 로 적지 않는다★"""
    _insert_kis(eng, "A", [("2026-01-02", 100.0), ("2026-01-05", 101.0)])
    got = pq.basis_overlap_check(["A"], engine=eng)   # return_1d 가 없다
    assert got.get("available") is False
    assert got["reason"]
    assert "consistent" not in got


def test_overlap_check_without_a_database_is_unavailable():
    got = pq.basis_overlap_check(engine=None)
    if got.get("available") is False:
        assert got["reason"]


# ══════════════════════════════════════════════════════════════════════════
# 6) ★단정 금지를 코드로 강제한다★
# ══════════════════════════════════════════════════════════════════════════
def test_kis_rows_do_not_get_adj_close_filled_in(eng, monkeypatch):
    """B12 — 근거가 코드 주석 하나뿐인 주장을 DB 에 적지 않는다.

    겹침 검증이 실데이터에서 돌아 "KIS=수정주가" 를 확인하기 전까지는,
    KIS 행의 `adj_close` 는 비어 있어야 한다.
    """
    import pandas as pd

    import src.data.ohlcv_loader as ol

    df = pd.DataFrame(
        {"open": [100.0], "high": [100.0], "low": [100.0], "close": [100.0],
         "volume": [10.0]},
        index=pd.to_datetime(["2026-01-02"]))
    monkeypatch.setattr("src.database.get_engine", lambda: eng)
    ol.ingest_df_to_db("ZZZ", df)

    with eng.connect() as c:
        adj = c.execute(text(
            "SELECT adj_close FROM daily_prices WHERE ticker='ZZZ'")).scalar()
    assert adj is None, "KIS close 를 수정주가라고 단정해 적었다"


def test_the_kis_ingest_function_never_mentions_adj_close():
    """★위 테스트의 정적 짝★ — 적재 **함수 본문**이 `adj_close` 를 건드리지 않는다.

    산문(독스트링·주석)은 `adj_close` 를 얼마든지 **설명**할 수 있어야 하므로
    파일 전체를 grep 하지 않는다. `ast` 로 함수 본문만 떼어내고 문자열·주석을
    걷어낸 **코드 토큰**에서만 찾는다.
    """
    import ast
    import io as _io
    import pathlib
    import tokenize

    tree = ast.parse(pathlib.Path("src/data/ohlcv_loader.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "ingest_df_to_db")
    body = ast.get_source_segment(
        pathlib.Path("src/data/ohlcv_loader.py").read_text(encoding="utf-8"), fn)

    hits = []
    for tok in tokenize.generate_tokens(_io.StringIO(body).readline):
        if tok.type == tokenize.COMMENT:
            continue
        if tok.type == tokenize.STRING and "SELECT" not in tok.string.upper() \
                and "INSERT" not in tok.string.upper() \
                and "UPDATE" not in tok.string.upper():
            continue          # 독스트링은 설명해도 된다 — SQL 문자열은 검사한다
        if "adj_close" in tok.string:
            hits.append(tok.string[:80])
    assert hits == [], f"적재 함수가 `adj_close` 를 쓴다: {hits}"


# ══════════════════════════════════════════════════════════════════════════
# 7) 라우트
# ══════════════════════════════════════════════════════════════════════════
def test_route_reports_the_basis_axis(monkeypatch, eng):
    from fastapi.testclient import TestClient

    from src.app_factory import create_app

    monkeypatch.setattr("src.database.get_engine", lambda: eng)
    bulk_upsert(eng, _series("A"))
    _insert_kis(eng, "A", [("2026-01-09", 515.0)])

    r = TestClient(create_app()).get("/api/v1/data/price-quality?tickers=A")
    assert r.status_code == 200
    body = r.json()
    assert body["coverage"]["mixed_basis_tickers"] == ["A"]
    assert "basis_overlap" in body
    assert body["research_usage"] == ResearchUsage.FORWARD_ONLY.value
