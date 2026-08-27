"""가격 출처와 수정주가 정직성 — ★모르는 것을 추정하지 않는다★
==============================================================================
감사: `docs/specs/2026-08-26-data-extraction-audit.md` §3.1

## 이 파일이 막는 것

`daily_prices` 에 writer 가 둘이다:

    krx_ingest.bulk_upsert        → OHLCV + return_1d + …
    ohlcv_loader.ingest_df_to_db  → OHLCV                  ← return_1d 없음

`rebuild_adj_close()` 는 `return_1d` 체인(`adj[t-1] = adj[t]/(1+r[t]/100)`)으로
분할·증자 점프를 지운다. ★예전에는 등락률이 없으면 원주가 비율로 폴백했고, 그
폴백이 지우려던 점프를 **다시 집어넣었다**.★

`return_1d` 가 없다는 것은 **그날 기업행위가 있었는지 모른다**는 뜻이다. 없었다면
원주가 비율이 맞고 있었다면 틀리는데, 구분할 방법이 없다 → 추정하지 않는다.

## 픽스처가 분할을 **실제로** 담는다

1000원 → 500원(2:1 분할)에서 원주가 비율은 −50% 지만 등락률은 −0.2% 다.
그 하루로 두 규칙이 완전히 갈린다 — 폴백은 adj 를 반토막 내고, 체인은 잇는다.
★이 픽스처가 없으면 "폴백 제거" 변이가 살아남는다.★
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from src.data.krx_ingest import (  # noqa: E402
    SOURCE_KIS,
    SOURCE_KRX,
    bulk_upsert,
    ensure_table,
    rebuild_adj_close,
)
from src.data.price_quality import (  # noqa: E402
    UNADJUSTED_CHAIN_BROKEN,
    UNADJUSTED_NOT_REBUILT,
    adj_close_coverage,
)


@pytest.fixture
def eng():
    e = create_engine("sqlite://", connect_args={"check_same_thread": False})
    ensure_table(e)
    return e


def _row(ticker, date, close, fluc=None, **kw):
    return {"ticker": ticker, "date": date, "close": close, "open": close,
            "high": close, "low": close, "volume": 100,
            "trading_value": 1000, "fluc_rt": fluc, **kw}


def _split_series():
    """2:1 분할이 낀 5거래일. ★원주가는 반토막, 등락률은 −0.2%★"""
    return [
        _row("A", "2026-01-02", 1000.0, 0.5),
        _row("A", "2026-01-05", 1010.0, 1.0),
        _row("A", "2026-01-06", 500.0, -0.2),      # ← 분할일 (1010 → 505 기준)
        _row("A", "2026-01-07", 505.0, 1.0),
        _row("A", "2026-01-08", 510.0, 0.99),
    ]


def _adj(eng, ticker="A"):
    with eng.connect() as c:
        return [(str(r[0])[:10], r[1]) for r in c.execute(text(
            "SELECT trade_date, adj_close FROM daily_prices WHERE ticker=:t "
            "ORDER BY trade_date"), {"t": ticker})]


# ══════════════════════════════════════════════════════════════════════════
# 1) 출처가 행에 남는다
# ══════════════════════════════════════════════════════════════════════════
def test_two_writers_record_different_sources(eng, monkeypatch):
    """★짝★ 두 값이 서로 **달라야** 한다 — 상수 하나면 구분이 안 된다."""
    bulk_upsert(eng, [_row("A", "2026-01-02", 1000.0, 0.5)])

    import src.database as db
    monkeypatch.setattr(db, "get_engine", lambda: eng, raising=False)
    import pandas as pd

    from src.data.ohlcv_loader import ingest_df_to_db
    df = pd.DataFrame({"open": [10.0], "high": [10.0], "low": [10.0],
                       "close": [10.0], "volume": [1]},
                      index=pd.DatetimeIndex(["2026-01-02"]))
    ingest_df_to_db("B", df)

    with eng.connect() as c:
        got = dict(c.execute(text("SELECT ticker, source FROM daily_prices")).all())
    assert got == {"A": SOURCE_KRX, "B": SOURCE_KIS}
    assert SOURCE_KRX != SOURCE_KIS


def test_rows_written_before_the_column_existed_keep_null_source(eng):
    """★소급 추정 금지★ 기존 행의 출처는 **모르는 것**이고 NULL 이 그 사실이다."""
    with eng.begin() as c:
        c.execute(text("INSERT INTO daily_prices (ticker, trade_date, close) "
                       "VALUES ('OLD', '2026-01-02', 100)"))
    with eng.connect() as c:
        src = c.execute(text("SELECT source FROM daily_prices WHERE ticker='OLD'")
                        ).scalar()
    assert src is None


# ══════════════════════════════════════════════════════════════════════════
# 2) ★체인이 끊기면 추정하지 않는다★ — 그리고 이어지면 점프를 지운다
# ══════════════════════════════════════════════════════════════════════════
def test_full_return_chain_removes_a_split_jump(eng):
    """★짝의 한쪽★ 등락률이 다 있으면 `adj` 가 분할을 건너 **연속**이다.

    이것이 없으면 "언제나 NULL" 로도 아래 테스트가 통과한다.
    """
    bulk_upsert(eng, _split_series())
    assert rebuild_adj_close(eng) == 5
    got = [v for _d, v in _adj(eng)]
    assert all(v is not None for v in got), "등락률이 다 있는데 끊겼다"
    # 분할일 전후(인덱스 1→2)에서 원주가는 1010 → 500 (−50.5%) 지만
    # 조정 후에는 등락률 −0.2% 만큼만 움직여야 한다.
    # `rebuild_adj_close` 는 4자리로 반올림해 저장한다 — 그만큼 허용한다.
    step = got[2] / got[1] - 1.0
    assert step == pytest.approx(-0.002, abs=1e-5), \
        f"분할 점프가 남아 있다: {step:+.4f}"


def test_missing_return_1d_breaks_the_chain_instead_of_guessing(eng):
    """★핵심★ 마지막 봉의 등락률이 없으면 그 아래가 **전부 NULL** 이다.

    예전 폴백(`adj[i] = adj[i+1] × close_i/close_next`)이면 값이 채워지고,
    분할일에서 반토막 난 값이 들어간다.
    """
    rows = _split_series()
    rows[-1]["fluc_rt"] = None                 # KIS 경로가 append 한 상황
    bulk_upsert(eng, rows)
    rebuild_adj_close(eng)

    got = [v for _d, v in _adj(eng)]
    assert got[-1] is not None, "앵커(최신 봉)는 close 로 채워진다"
    assert all(v is None for v in got[:-1]), \
        f"끊긴 아래가 추정됐다: {got}"


def test_chain_break_nulls_only_below_the_gap(eng):
    """★전멸이 아니다★ 끊긴 지점 **위쪽**은 살아 있어야 한다."""
    rows = _split_series()
    rows[1]["fluc_rt"] = None                  # 두 번째 봉의 등락률만 제거
    bulk_upsert(eng, rows)
    rebuild_adj_close(eng)

    got = [v for _d, v in _adj(eng)]
    # rows[1].fluc_rt 가 없으면 adj[0] 을 만들 수 없다. 1..4 는 살아 있다.
    assert got[0] is None
    assert all(v is not None for v in got[1:]), f"위쪽까지 지웠다: {got}"


def test_rebuild_counts_only_the_rows_it_filled(eng):
    rows = _split_series()
    rows[1]["fluc_rt"] = None
    bulk_upsert(eng, rows)
    assert rebuild_adj_close(eng) == 4          # 5행 중 1행은 NULL


# ══════════════════════════════════════════════════════════════════════════
# 3) 커버리지가 빠진 것을 이름으로 낸다
# ══════════════════════════════════════════════════════════════════════════
def test_coverage_counts_add_up_and_names_the_unadjusted(eng):
    rows = _split_series()
    rows[-1]["fluc_rt"] = None
    bulk_upsert(eng, rows)
    bulk_upsert(eng, [_row("B", "2026-01-02", 50.0, 0.1)])
    rebuild_adj_close(eng)

    cov = adj_close_coverage(engine=eng)
    assert cov["available"] is True
    assert cov["adjusted"] + cov["unadjusted"] == cov["rows"]
    assert "A" in cov["unadjusted_tickers"], "미조정 티커를 이름으로 내지 않는다"
    assert cov["reasons"][UNADJUSTED_CHAIN_BROKEN]["rows"] == 4
    assert cov["reasons"][UNADJUSTED_CHAIN_BROKEN]["note"]


def test_coverage_separates_not_rebuilt_from_chain_broken(eng):
    """★'계산 안 함' 과 '데이터 없음' 은 다른 사실이다★"""
    bulk_upsert(eng, _split_series())          # 재료는 있으나 rebuild 를 안 돌린다
    cov = adj_close_coverage(engine=eng)
    assert cov["unadjusted"] == 5
    assert UNADJUSTED_NOT_REBUILT in cov["reasons"]
    assert UNADJUSTED_CHAIN_BROKEN not in cov["reasons"]


def test_coverage_does_not_guess_the_source_of_legacy_rows(eng):
    """NULL 출처를 'krx' 로 추정하면 통계가 거짓말을 한다."""
    with eng.begin() as c:
        c.execute(text("INSERT INTO daily_prices (ticker, trade_date, close) "
                       "VALUES ('OLD', '2026-01-02', 100)"))
    cov = adj_close_coverage(engine=eng)
    assert "unknown" in cov["by_source"]
    assert SOURCE_KRX not in cov["by_source"]


def test_coverage_without_a_database_is_unavailable_not_zero():
    """★재지 못한 것을 0 으로 적지 않는다★ 0 은 '조정된 행이 없다' 는 판단이다."""
    cov = adj_close_coverage(engine=None)
    if cov.get("available") is False:
        assert cov["reason"]
        assert "adjusted_pct" not in cov


# ══════════════════════════════════════════════════════════════════════════
# 4) ★미사용 엔드포인트를 값으로 선언한다★
# ══════════════════════════════════════════════════════════════════════════
def test_not_ingested_reason_differs_from_an_unverified_endpoint():
    """키를 넣으면 풀리는 문제와 코드를 써야 풀리는 문제를 구분한다."""
    from src.data.source_registry import status
    ni = status("VKOSPI")
    assert ni["available"] is False and ni["not_ingested"] is True
    assert "수집 코드가 없습니다" in ni["reason"]

    other = status("KR_CPI")            # ECOS — 미검증이지만 수집 코드는 있다
    assert other.get("not_ingested") is False
    assert ni["reason"] != other["reason"]


def test_not_ingested_keys_match_the_unused_krx_endpoints():
    """★선언 ↔ 현실 대조★

    `get_extra()` 를 배선하면 이 테스트가 red 가 되어 `NOT_INGESTED_KEYS` 에서
    빼도록 강제한다(`regime_axes.AXIS_PATH_USES_VINTAGE` 와 같은 패턴).
    """
    import pathlib

    from src.data.krx_client import EXTRA_ENDPOINTS
    from src.data.source_registry import _BY_KEY, NOT_INGESTED_KEYS

    declared = {_BY_KEY[k].endpoint for k in NOT_INGESTED_KEYS if k in _BY_KEY}
    assert declared == set(EXTRA_ENDPOINTS.values()), (
        "선언한 미수집 계열과 `EXTRA_ENDPOINTS` 가 어긋난다")

    root = pathlib.Path(__file__).resolve().parents[1]
    callers = []
    for sub in ("src", "scripts"):
        for f in (root / sub).rglob("*.py"):
            if f.name == "krx_client.py":
                continue
            # ★설명 문구는 호출이 아니다★ 이 규칙을 설명하는 **문자열 상수**가
            # 스스로를 호출부로 오탐해 red 가 됐다(실제로 겪었다 — 주석만 걸렀더니
            # 통과하지 못했다). 그래서 설명 쪽에서 호출 문법을 지웠고, 여기서는
            # 호출 문법만 본다.
            for line in f.read_text(encoding="utf-8").splitlines():
                if ".get_extra(" in line and not line.lstrip().startswith("#"):
                    callers.append(f"{f}: {line.strip()}")
                    break
    assert not callers, (
        f"`get_extra` 호출부가 생겼다 — `NOT_INGESTED_KEYS` 를 비울 것: {callers}")
