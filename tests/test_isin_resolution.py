"""식별자 해소 — ★"모른다" 에도 종류가 있다★
==============================================================================
감사: `docs/specs/2026-08-26-data-extraction-audit.md` §3.3
자매: `tests/test_instrument_master_store.py` (파일 → DB 순서)

## 이 파일이 막는 것

`isin_of()` 는 **소비자가 0** 이었고, 유일한 실소비자
(`krx_mdc.backfill_flows_krx`)는 같은 조회를 **인라인으로 다시** 썼다. 그래서
"이 ISIN 이 쓸 수 있는 값인가" 를 세 곳이 **두 가지 규칙**으로 판정했다:

    kis_master_parser        len == 12 이면 저장, 아니면 ""
    instrument_master_store  ★비어 있지 않으면 유효★   ← 혼자 다르다
    krx_mdc                  len == 12

파서가 이미 걸러 주므로 살아 있는 사고는 아니었다. 그러나 다른 출처의 마스터가
들어오는 순간 `isin_of` 는 11자 쓰레기를 유효한 조회 키로 돌려준다.

그리고 `stats["no_isin"]` 은 **세 가지 다른 사실**을 한 숫자로 뭉갰다 — 티커가
마스터에 없음 · ISIN 이 빔 · ISIN 길이가 틀림(=파서·출처 결함). 셋째가 둘째로
뭉개지면 파서 버그가 영원히 보이지 않는다.

★읽기 순서는 바꾸지 않는다★ 파일 → DB 는 그대로다. 여기서 늘리는 것은
**관측 가능성**이지 정책이 아니다.
"""

from __future__ import annotations

import json
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402

import src.data.instrument_master_store as ims  # noqa: E402
import src.data.krx_mdc as km  # noqa: E402
import src.data.stock_master as sm  # noqa: E402

#: 길이가 제각각인 네 종류 — 세 가지 실패와 하나의 성공.
_MIXED = {
    "005930": {"name": "삼성전자", "isin": "KR7005930003", "group_code": "ST"},
    "999999": {"name": "ISIN 없음", "isin": "", "group_code": "ST"},
    "888888": {"name": "짧은 ISIN", "isin": "KR700593000", "group_code": "ST"},  # 11자
}


@pytest.fixture
def eng():
    return create_engine("sqlite://", connect_args={"check_same_thread": False})


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, eng, tmp_path):
    """프로세스 공용 DB·모듈 전역 캐시를 건드리지 않는다."""
    monkeypatch.setattr(ims, "_engine", lambda engine=None: eng)
    monkeypatch.setattr(sm, "_master_flags_path",
                        lambda: str(tmp_path / "absent.json"))
    sm._MASTER_FLAGS = None
    yield
    sm._MASTER_FLAGS = None


# ══════════════════════════════════════════════════════════════════════════
# A1·A2 ★세 가지 "모른다" 가 서로 다른 사유를 갖는다★
# ══════════════════════════════════════════════════════════════════════════
def test_the_three_failures_are_told_apart(eng):
    """한 문자열로 뭉개면 어디를 고쳐야 하는지 알 수 없다 — 고치는 사람이 다르다."""
    ims.save(_MIXED, engine=eng)

    absent = ims.isin_status("NOT_A_TICKER")
    blank = ims.isin_status("999999")
    short = ims.isin_status("888888")

    kinds = {absent["kind"], blank["kind"], short["kind"]}
    assert len(kinds) == 3, f"세 실패가 뭉개졌다: {kinds}"
    reasons = {absent["reason"], blank["reason"], short["reason"]}
    assert len(reasons) == 3, f"사유가 뭉개졌다: {reasons}"
    assert all(r for r in reasons), "사유 없는 실패는 금지다"
    assert absent["isin"] is blank["isin"] is short["isin"] is None

    # 길이 문제는 **길이를 말한다** — "없다" 와 구별되어야 고칠 수 있다.
    assert "11" in short["reason"] and str(ims.ISIN_LENGTH) in short["reason"]


def test_a_valid_isin_passes_without_a_reason(eng):
    """★짝★ 없으면 위 테스트가 '항상 거부' 구현으로도 통과한다."""
    ims.save(_MIXED, engine=eng)
    ok = ims.isin_status("005930")
    assert ok["isin"] == "KR7005930003"
    assert ok["reason"] is None and ok["kind"] == ims.KIND_OK


# ══════════════════════════════════════════════════════════════════════════
# A3 ★합성하지 않는다 — 그리고 규칙이 하나다★
# ══════════════════════════════════════════════════════════════════════════
def test_isin_of_rejects_a_malformed_key_instead_of_passing_it_on(eng):
    """11자를 조회 키로 넘기면 KRX MDC 가 **조용히 빈 결과**를 낸다."""
    ims.save(_MIXED, engine=eng)
    assert ims.isin_of("888888") is None
    assert ims.isin_of("999999") is None
    assert ims.isin_of("NOT_A_TICKER") is None
    assert ims.isin_of("005930") == "KR7005930003"


def test_isin_of_and_isin_status_cannot_disagree(eng):
    """★단일 판정★ 두 함수가 각자 규칙을 가지면 다시 갈라진다."""
    ims.save(_MIXED, engine=eng)
    for tk in (*_MIXED, "NOT_A_TICKER"):
        assert ims.isin_of(tk) == ims.isin_status(tk)["isin"]


# ══════════════════════════════════════════════════════════════════════════
# A4 ★소비자가 단일 경로를 쓴다★ — 기록 스파이로 확인
# ══════════════════════════════════════════════════════════════════════════
def test_the_backfill_resolves_through_the_single_path(eng, monkeypatch):
    """★예외를 신호로 쓰지 않는다★

    `backfill_flows_krx` 의 종목 루프는 `except Exception` 으로 감싸여 있어
    assert 를 삼키고 `errors` 로 집계한다. 그래서 **기록 스파이**로 본다.
    """
    monkeypatch.setattr("src.data.stock_master.load_master_flags", lambda: _MIXED)
    seen: list[str] = []
    real = ims.isin_status

    def spy(ticker, *a, **k):
        seen.append(str(ticker))
        return real(ticker, *a, **k)

    monkeypatch.setattr(ims, "isin_status", spy)
    km.backfill_flows_krx("2024-01-01", "2024-01-02",
                          tickers=["005930", "999999", "888888"],
                          engine=eng, fetcher=lambda *a, **k: [])
    assert seen == ["005930", "999999", "888888"], (
        f"백필이 인라인 조회로 되돌아갔다: {seen}")


# ══════════════════════════════════════════════════════════════════════════
# A5 ★합계는 그대로, 내역이 늘어난다★
# ══════════════════════════════════════════════════════════════════════════
def test_the_backfill_reports_why_each_ticker_was_skipped(eng, monkeypatch):
    monkeypatch.setattr("src.data.stock_master.load_master_flags", lambda: _MIXED)
    stats = km.backfill_flows_krx("2024-01-01", "2024-01-02",
                                  tickers=["005930", "999999", "888888", "NOPE"],
                                  engine=eng, fetcher=lambda *a, **k: [])
    # ★합계 불변★ 기존 소비자(API·lifecycle)가 읽는 키의 의미가 바뀌면 안 된다.
    assert stats["no_isin"] == 3
    by = stats["no_isin_by_reason"]
    assert by == {ims.KIND_NO_MASTER: 1, ims.KIND_NO_ISIN: 1, ims.KIND_MALFORMED: 1}
    assert sum(by.values()) == stats["no_isin"], "내역과 합계가 어긋난다"


def test_a_healthy_master_reports_no_skips(eng, monkeypatch):
    """★짝★ 항상 건너뛰는 구현을 배제한다."""
    monkeypatch.setattr("src.data.stock_master.load_master_flags",
                        lambda: {"005930": _MIXED["005930"]})
    stats = km.backfill_flows_krx("2024-01-01", "2024-01-02", tickers=["005930"],
                                  engine=eng, fetcher=lambda *a, **k: [])
    assert stats["no_isin"] == 0
    assert sum(stats["no_isin_by_reason"].values()) == 0


# ══════════════════════════════════════════════════════════════════════════
# A6 ★어느 경로가 답했는지 관측 가능하다★
# ══════════════════════════════════════════════════════════════════════════
def test_the_origin_of_the_master_is_observable(tmp_path, eng, monkeypatch):
    """"마스터가 스테일한가" 를 물으려면 **파일이 답했는지 DB 가 답했는지**를
    알아야 한다. 예전에는 밖에서 볼 방법이 없었다."""
    assert sm.master_flags_origin() == "none"      # 파일도 DB 도 없다

    ims.save(_MIXED, engine=eng)
    sm._MASTER_FLAGS = None
    assert sm.master_flags_origin() == "db"

    path = tmp_path / "master_flags_cache.json"
    path.write_text(json.dumps({"stocks": {"111111": {"name": "파일에서"}}}),
                    encoding="utf-8")
    monkeypatch.setattr(sm, "_master_flags_path", lambda: str(path))
    sm._MASTER_FLAGS = None
    assert sm.master_flags_origin() == "file"


def test_observing_the_origin_does_not_change_the_read_order(tmp_path, eng,
                                                             monkeypatch):
    """★관측이 정책을 바꾸지 않는다★ 파일이 있으면 여전히 파일이 이긴다."""
    path = tmp_path / "master_flags_cache.json"
    path.write_text(json.dumps({"stocks": {"111111": {"name": "파일에서"}}}),
                    encoding="utf-8")
    monkeypatch.setattr(sm, "_master_flags_path", lambda: str(path))
    ims.save(_MIXED, engine=eng)
    sm._MASTER_FLAGS = None

    assert set(sm.load_master_flags()) == {"111111"}, "DB 가 파일을 덮었다"
    assert sm.master_flags_origin() == "file"


# ══════════════════════════════════════════════════════════════════════════
# A7 커버리지 리포트 — ★세지 말고 재라★
# ══════════════════════════════════════════════════════════════════════════
def test_coverage_counts_each_failure_separately(eng):
    ims.save(_MIXED, engine=eng)
    cov = ims.isin_coverage()
    assert cov["total"] == 3
    assert cov["with_isin"] == 1
    assert cov["no_isin"] == 1
    assert cov["malformed"] == 1
    assert cov["origin"] == "db"


def test_coverage_of_an_absent_master_is_zero_not_an_error():
    """마스터가 없는 것은 오류가 아니라 **사실**이다 — 이 환경이 그 상태다."""
    cov = ims.isin_coverage()
    assert cov["total"] == 0 and cov["with_isin"] == 0
    assert cov["origin"] == "none"
