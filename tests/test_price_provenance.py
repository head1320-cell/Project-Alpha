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
    RAW_NOT_REBUILT,
    STATE_ADJUSTED,
    STATE_CHAIN_BROKEN,
    STATE_RAW,
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
    """★핵심★ 등락률이 없는 지점 아래는 **전부 NULL** 이다.

    예전 폴백(`adj[i] = adj[i+1] × close_i/close_next`)이면 값이 채워지고,
    분할일에서 반토막 난 값이 들어간다.

    ★주의 — 이것은 KIS 행이 붙은 상황이 **아니다**★ (예전 주석이 그렇게 적었다).
    여기 픽스처는 `bulk_upsert` 로 넣은 **KRX 행의 등락률을 지운 것**이다. 둘은
    다른 상황이고 결과도 다르다:

        KRX 행의 등락률 결측 → 그 행은 앵커가 될 수 없다(체인을 못 잇는다)
        KIS 행 append        → `return_1d` 자체가 없다 → 마찬가지로 앵커가 아니다

    어느 쪽이든 앵커는 **등락률을 쓸 수 있는 가장 최신 행**으로 내려간다.
    여기서는 그런 행이 없으므로(마지막만 지웠고 그 아래는 살아 있다) 앵커가
    `rows[-2]` 로 내려가고, 지운 행만 NULL 이 된다.
    """
    rows = _split_series()
    rows[-1]["fluc_rt"] = None                 # ★KRX 행의 등락률을 지운다★
    bulk_upsert(eng, rows)
    rebuild_adj_close(eng)

    got = [v for _d, v in _adj(eng)]
    assert got[-1] is None, "등락률 없는 행이 앵커가 됐다"
    assert all(v is not None for v in got[:-1]), \
        f"앵커가 쓸 수 있는 행으로 내려가지 않았다: {got}"


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
    """★적재 → 재구성 → 보고까지 실제 파이프라인으로 센다★

    `test_price_quality_gate.py` 는 상태 **규칙**을 못 박고, 여기는 그 규칙이
    `bulk_upsert` + `rebuild_adj_close` 의 실제 산출 위에서 같은 답을 내는지 본다.
    끊긴 행 수 4 를 **정확히** 적는다 — 합만 보면 raw 와 chain_broken 사이에서
    잘못 나눠도 통과한다.
    """
    rows = _split_series()
    rows[-1]["fluc_rt"] = None
    bulk_upsert(eng, rows)
    bulk_upsert(eng, [_row("B", "2026-01-02", 50.0, 0.1)])
    rebuild_adj_close(eng)

    cov = adj_close_coverage(engine=eng)
    assert cov["available"] is True
    assert sum(cov["row_states"].values()) == cov["rows"]
    assert "A" in cov["unadjusted_tickers"], "미조정 티커를 이름으로 내지 않는다"
    # ★이 숫자는 앵커 수정(Phase 3)으로 바뀌었다 — 개선의 결과다★
    #   예전: 앵커가 최신 봉 고정 → 등락률 없는 그 행만 조정되고 아래 4행이 끊김
    #         (adjusted 2 / chain_broken 4)
    #   지금: 앵커가 "등락률을 쓸 수 있는 가장 최신 행"(2026-01-07)으로 내려가
    #         아래 4행이 되살아나고, 등락률 없는 최신 행 1개만 NULL 이다.
    # ★정확한 수를 유지한다★ 합만 보면 raw 와 chain_broken 사이에서 잘못 나눠도
    # 통과한다(변이 ⑦⑧ 이 그것이다).
    assert cov["row_states"][STATE_CHAIN_BROKEN] == 1
    assert cov["row_states"][STATE_ADJUSTED] == 5      # A 4행 + B 1행
    assert cov["state_notes"][STATE_CHAIN_BROKEN]


def test_coverage_separates_not_rebuilt_from_chain_broken(eng):
    """★'계산 안 함' 과 '중간에서 끊김' 은 다른 사실이다★

    재구성을 한 번도 돌리지 않은 티커는 `chain_broken` 이 아니라 `raw` 다 —
    체인이 끊긴 게 아니라 **시작한 적이 없다**. 고치는 방법도 다르다
    (`rebuild_adj_close()` 실행 vs 그 구간 KRX 재적재).
    """
    bulk_upsert(eng, _split_series())          # 재료는 있으나 rebuild 를 안 돌린다
    cov = adj_close_coverage(["A"], engine=eng)
    assert cov["row_states"][STATE_RAW] == 5
    assert cov["ticker_states"][STATE_RAW] == 1
    assert cov["ticker_states"][STATE_CHAIN_BROKEN] == 0, "미실행을 끊김으로 셌다"
    assert cov["raw_reasons"][RAW_NOT_REBUILT]["tickers"] == 1


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
# 4) ★미수집 선언은 **수집 경로에서 유도**된다★
# ──────────────────────────────────────────────────────────────────────────
# 이 섹션은 방향이 **뒤집혔다**. 예전에는 "`get_extra` 호출부가 0 이다" 를 못 박고
# *"배선하면 red 가 되어 `NOT_INGESTED_KEYS` 를 비우도록 강제한다"* 고 적어 뒀다.
# 배선이 들어왔고(`src/data/krx_extras.py`), 그 지시대로 두 테스트를 뒤집는다.
#
# ★호출부를 grep 으로 세는 방식은 버렸다★ — 소스에 문자열 하나만 넣어도 만족하는
# 공허한 검사다. 대신 **동작**을 본다: 수집 경로를 지우면 선언이 스스로 돌아오는가.
# ══════════════════════════════════════════════════════════════════════════
def test_the_two_causes_are_still_told_apart():
    """★키를 넣으면 풀리는 문제와 코드를 써야 풀리는 문제는 다르다★

    지금은 네 계열 모두 배선돼 있어 후자가 없다. 그래도 **구분이 표현 가능해야**
    한다 — 표현할 수 없게 되면 다음 미수집 계열이 조용히 뭉개진다.
    """
    import src.data.krx_client as kc
    from src.data.source_registry import status

    before = status("VKOSPI")
    assert before["not_ingested"] is False
    assert "수집 코드가 없습니다" not in before["reason"]

    kept = {k: v for k, v in kc.EXTRA_SERIES.items() if k != "VKOSPI"}
    original = kc.EXTRA_SERIES
    try:
        kc.EXTRA_SERIES = kept
        after = status("VKOSPI")
    finally:
        kc.EXTRA_SERIES = original

    assert after["not_ingested"] is True
    assert "수집 코드가 없습니다" in after["reason"]
    assert after["reason"] != status("KR_CPI")["reason"], (
        "미수집과 미검증이 같은 문구가 됐다 — 고치는 사람이 다르다")


def test_every_endpoint_has_a_collection_path():
    """★선언 ↔ 현실 대조★ (방향 반전)

    `EXTRA_ENDPOINTS` 에 경로만 있고 `EXTRA_SERIES` 에 접기 규칙이 없으면, 키를
    넣어도 값이 오지 않으면서 레지스트리는 조용하다. 둘이 갈라지지 않게 못 박는다.
    """
    from src.data.krx_client import (
        COLLAPSE_SINGLE,
        COLLAPSE_UNKNOWN,
        EXTRA_ENDPOINTS,
        EXTRA_SERIES,
    )
    from src.data.source_registry import _BY_KEY, KRX, not_ingested_keys

    kinds = {kind for kind, _rule, _name in EXTRA_SERIES.values()}
    assert kinds == set(EXTRA_ENDPOINTS), "접기 규칙과 엔드포인트가 어긋난다"
    for _kind, rule, _name in EXTRA_SERIES.values():
        assert rule in (COLLAPSE_SINGLE, COLLAPSE_UNKNOWN)

    # 등록 키는 전부 레지스트리에 있어야 한다 — 없으면 상태를 낼 수 없다.
    for key in EXTRA_SERIES:
        assert key in _BY_KEY and _BY_KEY[key].provider == KRX, key

    assert not_ingested_keys() == frozenset(), (
        "수집 경로가 있는데 미수집으로 선언돼 있다")


def test_emptying_the_pipeline_restores_the_declaration():
    """★유도 검증 — 가드를 손으로 무장해제할 수 없다★

    예전 `NOT_INGESTED_KEYS` 는 손으로 적은 frozenset 이라 **비우는 것만으로**
    가드가 풀렸다(직전 커밋의 Z2 변이가 그렇게 살아남았다). 이제 진실은 수집
    경로 쪽에 있다.
    """
    import src.data.krx_client as kc
    from src.data.source_registry import not_ingested_keys

    original = kc.EXTRA_SERIES
    try:
        kc.EXTRA_SERIES = {}
        restored = not_ingested_keys()
    finally:
        kc.EXTRA_SERIES = original

    assert restored == {"VKOSPI", "KR_MARGIN_BALANCE", "KR_SHORT_VOLUME",
                        "KR_LENDING_BALANCE"}
    assert not_ingested_keys() == frozenset(), "복원이 안 됐다"
