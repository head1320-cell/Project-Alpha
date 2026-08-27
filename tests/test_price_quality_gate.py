"""가격 품질 게이트 — ★모르는 것을 추정하지 않고, 임계값을 지어내지 않는다★
==============================================================================
설계: `docs/specs/2026-08-27-capability-states-matrix.md` §4

## 이 파일이 막는 것

1. ★`missing` 을 안 세는 것★ — 요청한 티커가 DB 에 아예 없으면 "존재하는 행만"
   보는 구현은 커버리지 100% 를 낸다. **공허한 참**이다.
2. ★백분율 임계값을 지어내는 것★ — 기존 계약(`derive_usage` ·
   `all(bool(o.vintage_id))`)은 전부-아니면-전무다. "95% 이상" 같은 숫자는
   근거를 댈 수 없다.
3. ★두 번째 등급 체계★ — 등급은 `pit_macro.derive_usage()` 를 **호출해서** 받아야
   한다. 여기서 자체 판정하면 매크로 팩터의 등급과 반드시 갈라진다.
4. ★`raw` 의 두 하위 사유를 접는 것★ — `not_rebuilt`(재구성만 돌리면 됨)와
   `no_return_data`(KRX 적재 필요)는 **고치는 사람이 다르다**.

## 픽스처가 분할을 실제로 담는다

1000 → 500(2:1) 에서 원주가 비율은 −50% 지만 등락률은 −0.2% 다. 그 하루가
"조정됨" 과 "원주가" 를 가른다.
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import src.data.price_quality as pq  # noqa: E402
from src.data.krx_ingest import (  # noqa: E402
    SOURCE_KRX,
    bulk_upsert,
    ensure_table,
    rebuild_adj_close,
)
from src.data.pit_macro import ForwardOnlyError, ResearchUsage  # noqa: E402


@pytest.fixture
def eng():
    """★`StaticPool` 이 필수다★ 인메모리 sqlite 의 기본 풀은 **스레드마다 별도
    연결**이라, TestClient 가 라우트를 스레드풀에서 돌리면 **빈 DB** 를 본다
    (실제로 라우트 테스트가 `unavailable` 로 떨어졌다).
    `tests/test_reverse_dcf_wiring.py` 의 관례를 그대로 따른다.
    """
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


# ══════════════════════════════════════════════════════════════════════════
# 1) 네 상태가 배타적이고 합이 맞는다
# ══════════════════════════════════════════════════════════════════════════
def test_ticker_states_are_exclusive_and_sum_to_requested(eng):
    """★티커 단위 배타★ 각 티커는 정확히 하나의 상태를 갖는다."""
    bulk_upsert(eng, _series("ADJ"))                       # 전부 조정 가능
    bulk_upsert(eng, _series("BRK", fluc=(0.5, 1.0, -0.2, 1.0, None)))
    bulk_upsert(eng, _series("RAWT"))
    # ★`RAWT` 만 재구성에서 뺀다★ 재구성이 돌면 앵커(최신 봉)는 **언제나**
    # `adj=close` 로 채워지므로, 돌린 티커는 최소 `chain_broken` 이다.
    # 즉 `raw` 는 "그 티커에 재구성이 돈 적이 없다" 를 뜻한다.
    rebuild_adj_close(eng, tickers=["ADJ", "BRK"])

    req = ["ADJ", "BRK", "RAWT", "GONE"]
    cov = pq.adj_close_coverage(req, engine=eng)
    st = cov["ticker_states"]
    assert sum(st.values()) == len(req), f"상태 합이 요청 수와 다르다: {st}"
    assert set(st) == set(pq.STATES)
    assert cov["by_ticker"] == {"ADJ": pq.STATE_ADJUSTED,
                                "BRK": pq.STATE_CHAIN_BROKEN,
                                "RAWT": pq.STATE_RAW,
                                "GONE": pq.STATE_MISSING}


def test_row_states_sum_to_rows(eng):
    """행 단위 셋(`missing` 은 정의상 행이 없다)은 전체 행 수와 같다."""
    bulk_upsert(eng, _series("ADJ"))
    bulk_upsert(eng, _series("BRK", fluc=(0.5, 1.0, -0.2, 1.0, None)))
    rebuild_adj_close(eng)
    cov = pq.adj_close_coverage(["ADJ", "BRK"], engine=eng)
    assert sum(cov["row_states"].values()) == cov["rows"]


# ══════════════════════════════════════════════════════════════════════════
# 2) ★`missing` — 없는 티커가 100% 로 보이지 않는다★
# ══════════════════════════════════════════════════════════════════════════
def test_a_ticker_with_no_rows_is_missing_not_invisible(eng):
    bulk_upsert(eng, _series("ADJ"))
    rebuild_adj_close(eng)
    cov = pq.adj_close_coverage(["ADJ", "GONE"], engine=eng)
    assert cov["ticker_states"][pq.STATE_MISSING] == 1
    assert cov["missing_tickers"] == ["GONE"]
    assert "GONE" in cov["unadjusted_tickers"]


def test_missing_is_declared_unmeasurable_without_a_ticker_list(eng):
    """★0 을 '없다' 로 읽지 않게 선언한다★ 티커를 안 주면 못 재는 값이다."""
    bulk_upsert(eng, _series("ADJ"))
    cov = pq.adj_close_coverage(engine=eng)
    assert cov["missing_measurable"] is False
    assert cov["ticker_states"][pq.STATE_MISSING] == 0

    cov2 = pq.adj_close_coverage(["ADJ"], engine=eng)
    assert cov2["missing_measurable"] is True


# ══════════════════════════════════════════════════════════════════════════
# 3) `raw` 의 두 하위 사유
# ══════════════════════════════════════════════════════════════════════════
def test_raw_reasons_are_separated(eng):
    """★고치는 사람이 다르다★ 재구성 미실행 vs 등락률 자체가 없음."""
    bulk_upsert(eng, _series("NOTRB"))            # 등락률 있음 · rebuild 안 함
    bulk_upsert(eng, _series("NORET", fluc=(None,) * 5))   # 등락률 자체가 없음
    cov = pq.adj_close_coverage(["NOTRB", "NORET"], engine=eng)
    assert cov["ticker_states"][pq.STATE_RAW] == 2
    assert cov["raw_reasons"][pq.RAW_NOT_REBUILT]["tickers"] == 1
    assert cov["raw_reasons"][pq.RAW_NO_RETURN_DATA]["tickers"] == 1
    assert cov["raw_reasons"][pq.RAW_NOT_REBUILT]["note"]


# ══════════════════════════════════════════════════════════════════════════
# 4) 출처 보존
# ══════════════════════════════════════════════════════════════════════════
def test_null_source_stays_unknown(eng):
    """★`NULL` 을 `krx` 로 추정하면 통계가 거짓말을 한다★"""
    with eng.begin() as c:
        c.execute(text("INSERT INTO daily_prices (ticker, trade_date, close) "
                       "VALUES ('OLD', '2026-01-02', 100)"))
    cov = pq.adj_close_coverage(["OLD"], engine=eng)
    assert pq.SOURCE_UNKNOWN in cov["by_source"]
    assert SOURCE_KRX not in cov["by_source"]


# ══════════════════════════════════════════════════════════════════════════
# 5) ★전부-아니면-전무★ — 임계값 없음
# ══════════════════════════════════════════════════════════════════════════
def test_every_ticker_adjusted_is_backtest_eligible(eng):
    """★짝의 한쪽★ 전부 조정되면 실제로 적격이 나온다."""
    bulk_upsert(eng, _series("ADJ"))
    rebuild_adj_close(eng)
    got = pq.price_usage(["ADJ"], engine=eng)
    assert got["usage"] == ResearchUsage.BACKTEST_ELIGIBLE.value
    assert got["reason"] is None


def test_one_broken_ticker_makes_the_whole_request_forward_only(eng):
    """★핵심★ 4/5 가 조정돼도 적격이 아니다 — 백분율 임계값이 없다."""
    bulk_upsert(eng, _series("ADJ"))
    bulk_upsert(eng, _series("BRK", fluc=(0.5, 1.0, -0.2, 1.0, None)))
    rebuild_adj_close(eng)
    got = pq.price_usage(["ADJ", "BRK"], engine=eng)
    assert got["usage"] == ResearchUsage.FORWARD_ONLY.value
    assert "BRK" in got["reason"]


def test_no_percentage_threshold_constant_exists():
    """★임계값을 지어내지 않았다★ 소스에 백분율 상수가 없어야 한다."""
    import pathlib
    src = (pathlib.Path(pq.__file__)).read_text(encoding="utf-8")
    for bad in ("0.95", "0.99", "95.0", "99.0", "MIN_COVERAGE", "THRESHOLD"):
        assert bad not in src, f"백분율 임계값처럼 보이는 상수가 생겼다: {bad}"


# ══════════════════════════════════════════════════════════════════════════
# 6) 세 등급이 서로 다르다
# ══════════════════════════════════════════════════════════════════════════
def test_no_rows_is_unavailable_not_forward_only(eng):
    """★'없다' 와 '있는데 부적격' 은 다른 사실이다★"""
    got = pq.price_usage(["GONE"], engine=eng)
    assert got["usage"] == ResearchUsage.UNAVAILABLE.value
    assert "행이 없습니다" in got["reason"]


def test_gate_raises_forward_only_error(eng):
    bulk_upsert(eng, _series("BRK", fluc=(0.5, 1.0, -0.2, 1.0, None)))
    rebuild_adj_close(eng)
    with pytest.raises(ForwardOnlyError) as e:
        pq.assert_prices_backtest_eligible(["BRK"], engine=eng)
    assert "적격하지 않습니다" in str(e.value)


def test_gate_passes_when_eligible(eng):
    """짝 — 게이트가 전부를 막아버리지 않는다."""
    bulk_upsert(eng, _series("ADJ"))
    rebuild_adj_close(eng)
    pq.assert_prices_backtest_eligible(["ADJ"], engine=eng)      # 예외 없음


# ══════════════════════════════════════════════════════════════════════════
# 7) ★등급 규칙을 복제하지 않는다★
# ══════════════════════════════════════════════════════════════════════════
def test_price_usage_goes_through_derive_usage(eng, monkeypatch):
    """★핵심 가드★ `derive_usage` 를 실제로 통과하는지 몽키패치로 확인한다.

    자체 판정으로 같은 답을 내는 구현도 위 테스트들을 통과한다 — 그러면 매크로
    팩터의 등급 규칙이 바뀔 때 가격만 옛 규칙으로 남는다.
    """
    bulk_upsert(eng, _series("ADJ"))
    rebuild_adj_close(eng)
    seen: list[dict] = []

    def spy(**kw):
        seen.append(kw)
        return ResearchUsage.FORWARD_ONLY          # 일부러 다른 답을 준다

    monkeypatch.setattr(pq, "derive_usage", spy)
    got = pq.price_usage(["ADJ"], engine=eng)
    assert seen, "`derive_usage` 를 부르지 않았다 — 등급 규칙을 복제하고 있다"
    assert set(seen[0]) == {"has_vintage", "depth_ok", "lag_known", "has_source"}
    assert seen[0]["lag_known"] is True, "가격은 공표지연이 없다"
    assert got["usage"] == ResearchUsage.FORWARD_ONLY.value, \
        "`derive_usage` 의 답을 따르지 않았다"


def test_depth_is_checked_against_start(eng):
    """`depth_ok` 가 실제로 `start` 와 비교된다."""
    bulk_upsert(eng, _series("ADJ"))
    rebuild_adj_close(eng)
    deep = pq.price_usage(["ADJ"], start="2026-01-02", engine=eng)
    assert deep["usage"] == ResearchUsage.BACKTEST_ELIGIBLE.value
    shallow = pq.price_usage(["ADJ"], start="2020-01-01", engine=eng)
    assert shallow["usage"] == ResearchUsage.FORWARD_ONLY.value
    assert "이력 길이" in shallow["reason"]


# ══════════════════════════════════════════════════════════════════════════
# 8) 라우트 · attrs
# ══════════════════════════════════════════════════════════════════════════
def test_route_reports_coverage_and_grade(monkeypatch, eng):
    from fastapi.testclient import TestClient

    from src.app_factory import create_app
    monkeypatch.setattr(pq, "_engine", lambda engine=None: eng)
    bulk_upsert(eng, _series("ADJ"))
    rebuild_adj_close(eng)

    c = TestClient(create_app())
    r = c.get("/api/v1/data/price-quality?tickers=ADJ")
    assert r.status_code == 200
    body = r.json()
    assert body["research_usage"] == ResearchUsage.BACKTEST_ELIGIBLE.value
    assert body["coverage"]["available"] is True

    # 티커를 안 주면 등급을 매기지 않는다 — 무엇에 대한 등급인지 정의되지 않는다
    r2 = c.get("/api/v1/data/price-quality")
    assert r2.status_code == 200 and r2.json()["research_usage"] is None


def test_route_is_honest_without_a_database(monkeypatch):
    from fastapi.testclient import TestClient

    from src.app_factory import create_app
    monkeypatch.setattr(pq, "_engine", lambda engine=None: None)
    c = TestClient(create_app())
    body = c.get("/api/v1/data/price-quality?tickers=ADJ").json()
    assert body["coverage"]["available"] is False
    assert body["coverage"]["reason"]
    assert body["research_usage"] == ResearchUsage.UNAVAILABLE.value


def test_attrs_tag_is_documented_as_non_authoritative():
    """★`attrs` 로 게이트를 세우지 말라고 코드가 말해야 한다★

    pandas 는 슬라이스·merge 에서 `attrs` 를 보존하지 않는다. 그 사실이 적혀
    있지 않으면 소비자가 `attrs` 만 믿고 게이트를 세운다.
    """
    import pathlib
    src = (pathlib.Path("src/data/ohlcv_loader.py")).read_text(encoding="utf-8")
    assert "adj_status" in src
    assert "보존은" in src or "보장되지 않는다" in src
    assert "price_usage" in src, "권위 있는 경로를 가리켜야 한다"
