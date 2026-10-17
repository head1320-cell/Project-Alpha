"""빈티지를 **소급해 채운다** — `vintage_gap` · `backfill_vintages` (로드맵 3단계)

## 무엇이 문제인가

V4 가 재무 공시일에 `measured`/`estimated` 라벨을 달았지만 **모든 실행이 "전부
추정"** 이다. `existing_keys()` 가 `(종목, 연도, 보고서)` 3-튜플이라
`financials_history` 에 이미 있는 기간은 재조회되지 않고, 그래서 V1/V2 이전에
적재된 기간에는 **빈티지 행이 영원히 안 생긴다.**

## ★로드맵의 미상이 잘못된 질문이었다★

로드맵은 *"보고서 목록 조회로 `rcept_dt` 만 받을 수 있는지 실호출로 보지 못했다"*
를 블로커로 적었다. 재보니 그 질문이 **불필요하다** — `dart_client.py:368` 이
이미 `fnlttSinglAcnt.json` 응답에서 `rcept_no` 를 꺼내고 `rcept_dt` 는 거기서
`filing_date_of()` 로 **로컬 파생**한다. 추가 호출이 없다.

진짜 블로커는 resume 키였고, 그것은 **기존 경로를 고치지 않고** 갭만 골라 다시
받는 형제 함수로 푼다 — `refetch_revenue_null()` 이 이미 쓰는 패턴이다.

## ★이 파일이 지키는 것 — 세 결과를 뭉치지 않는다★

    성공                 → 빈티지가 생기고 다음부터 갭이 아니다 (수렴)
    접수번호 없음         → **시도 흔적**을 남기고 다시 묻지 않는다 (항구적 부재)
    조회 실패(None·예외)  → ★흔적을 남기지 않는다★ — 일시적일 수 있다

셋을 한 칸에 세면 "제공자가 안 준다" 와 "우리가 못 받았다" 가 같아지고, 처방이
정반대인데 구별이 사라진다. 그리고 일시적 실패를 항구적으로 표시하면 되찾을 수
있는 데이터를 **영영 잃는다**.
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from src.data import dart_history as dh  # noqa: E402
from src.data.dart_client import FinancialStatement  # noqa: E402

TICKER = "005930"
OTHER = "000660"


def _fs(*, year="2024", reprt="11011", rcept_no="20250314000777",
        rcept_dt="2025-03-14", revenue=1000.0) -> FinancialStatement:
    fs = FinancialStatement(corp_code="00126380", corp_name="삼성전자",
                            bsns_year=year, reprt_code=reprt)
    fs.revenue, fs.net_income = revenue, 100.0
    fs.total_equity, fs.total_assets, fs.total_liabilities = 500.0, 2000.0, 1500.0
    fs.rcept_no, fs.rcept_dt = rcept_no, rcept_dt
    return fs


def _history_only(engine, ticker: str, year: str, reprt: str = "11011") -> None:
    """★빈티지 없이 본문만 적재된 기간★ — V1/V2 이전 상태를 재현한다."""
    fs = _fs(year=year, reprt=reprt)
    fs.rcept_no = fs.rcept_dt = None          # 접수번호 없이 들어온 옛 적재
    assert dh.upsert_statement(engine, ticker, fs)


@pytest.fixture
def eng():
    e = create_engine("sqlite://", connect_args={"check_same_thread": False},
                      poolclass=StaticPool)
    dh.ensure_history_table(e)
    assert dh.ensure_vintage_table(e), "빈티지 테이블을 만들지 못했다"
    dh._VINTAGE_SKIPPED["no_rcept"] = 0
    yield e
    e.dispose()


class _Client:
    """DART 대역 — 후보마다 무엇을 돌려줄지 지정한다."""

    is_configured = True

    def __init__(self, by_key: dict | None = None, default=None):
        self.by_key = by_key or {}
        self.default = default
        self.calls: list[tuple] = []

    def get_financial_statement_full(self, corp, year, reprt_code="11011"):
        self.calls.append((corp, str(year), str(reprt_code)))
        got = self.by_key.get((str(year), str(reprt_code)), self.default)
        if isinstance(got, Exception):
            raise got
        return got


@pytest.fixture(autouse=True)
def _corp(monkeypatch):
    monkeypatch.setattr("src.data.dart_client.get_corp_code", lambda tk: f"C{tk}")


def _probe_at(engine, ticker, year, reprt="11011"):
    with engine.connect() as conn:
        return conn.execute(text(
            "SELECT vintage_probe_at FROM financials_history "
            "WHERE ticker=:t AND bsns_year=:y AND reprt_code=:r"),
            {"t": ticker, "y": year, "r": reprt}).scalar()


def _vintage_rows(engine) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text(
            f"SELECT COUNT(*) FROM {dh.VINTAGE_TABLE}")).scalar() or 0)


# ═══════════════════════════════════════════════════════════════════════════
# ①② 갭 질의 — 빈티지 있는 기간은 빼고, 없는 기간은 넣는다
# ═══════════════════════════════════════════════════════════════════════════

def test_a_period_with_a_vintage_is_not_a_gap(eng):
    assert dh.upsert_statement(eng, TICKER, _fs(year="2024"))   # 빈티지까지 생김
    assert _vintage_rows(eng) == 1, "픽스처가 빈티지를 안 만들었다"
    assert dh.vintage_gap(eng) == [], dh.vintage_gap(eng)


def test_a_period_without_a_vintage_is_a_gap(eng):
    """★짝★ 항상-빈-목록 구현을 배제한다."""
    _history_only(eng, TICKER, "2023")
    assert dh.vintage_gap(eng) == [(TICKER, "2023", "11011")], dh.vintage_gap(eng)


def test_only_the_gap_is_returned(eng):
    assert dh.upsert_statement(eng, TICKER, _fs(year="2024"))
    _history_only(eng, TICKER, "2023")
    _history_only(eng, OTHER, "2023")
    got = dh.vintage_gap(eng)
    assert sorted(got) == [(OTHER, "2023", "11011"), (TICKER, "2023", "11011")], got


# ═══════════════════════════════════════════════════════════════════════════
# ③④ 시도 흔적 — ★미상 ≠ 없음★ 이지만 영원히 묻지도 않는다
# ═══════════════════════════════════════════════════════════════════════════

def test_a_probed_period_leaves_the_gap(eng):
    _history_only(eng, TICKER, "2023")
    dh.mark_vintage_probed(eng, TICKER, "2023", "11011")
    assert dh.vintage_gap(eng) == [], dh.vintage_gap(eng)


def test_retry_probed_reopens_it(eng):
    """★영구 배제가 아니다★ — 제공자가 나중에 채울 수 있다."""
    _history_only(eng, TICKER, "2023")
    dh.mark_vintage_probed(eng, TICKER, "2023", "11011")
    assert dh.vintage_gap(eng, retry_probed=True) == [(TICKER, "2023", "11011")]


def test_a_probe_mark_does_not_claim_the_vintage_is_absent(eng):
    """흔적은 **시도**를 적는 것이지 "빈티지가 없다" 는 선언이 아니다."""
    _history_only(eng, TICKER, "2023")
    dh.mark_vintage_probed(eng, TICKER, "2023", "11011")
    assert _probe_at(eng, TICKER, "2023"), "시각이 안 찍혔다"
    assert _vintage_rows(eng) == 0, "시도했다고 빈 빈티지를 만들면 안 된다"


# ═══════════════════════════════════════════════════════════════════════════
# ⑤⑥⑦ 세 결과를 뭉치지 않는다
# ═══════════════════════════════════════════════════════════════════════════

def test_a_successful_refetch_creates_the_vintage_and_converges(eng):
    _history_only(eng, TICKER, "2023")
    client = _Client(default=_fs(year="2023"))
    stats = dh.backfill_vintages(engine=eng, client=client)
    assert stats["saved"] == 1, stats
    assert _vintage_rows(eng) == 1
    assert dh.vintage_gap(eng) == [], "채웠는데 다음 실행에도 후보다 — 수렴하지 않는다"


def test_a_response_without_a_receipt_number_is_marked_and_converges(eng):
    """★항구적 부재★ — 흔적을 남기고 다시 묻지 않는다(쿼터를 태우지 않는다)."""
    _history_only(eng, TICKER, "2023")
    no_rcept = _fs(year="2023")
    no_rcept.rcept_no = no_rcept.rcept_dt = None
    stats = dh.backfill_vintages(engine=eng, client=_Client(default=no_rcept))
    assert stats["no_rcept"] == 1, stats
    assert _probe_at(eng, TICKER, "2023"), "흔적이 안 남았다"
    assert dh.vintage_gap(eng) == [], "다음 실행에도 후보다 — 영원히 재조회된다"


@pytest.mark.parametrize("outcome", [None, RuntimeError("일시적 네트워크 오류")])
def test_a_transient_failure_leaves_no_mark(eng, outcome):
    """★일시적 실패를 항구적으로 표시하면 되찾을 수 있는 데이터를 영영 잃는다★"""
    _history_only(eng, TICKER, "2023")
    stats = dh.backfill_vintages(engine=eng, client=_Client(default=outcome))
    assert stats["failed"] == 1, stats
    assert _probe_at(eng, TICKER, "2023") is None, "일시적 실패에 흔적을 남겼다"
    assert dh.vintage_gap(eng) == [(TICKER, "2023", "11011")], "다시 시도하지 않는다"


def test_the_three_outcomes_are_counted_separately(eng):
    """하나로 뭉치면 '제공자가 안 준다' 와 '우리가 못 받았다' 가 같아진다."""
    _history_only(eng, TICKER, "2021")
    _history_only(eng, TICKER, "2022")
    _history_only(eng, TICKER, "2023")
    no_rcept = _fs(year="2022")
    no_rcept.rcept_no = no_rcept.rcept_dt = None
    client = _Client(by_key={
        ("2023", "11011"): _fs(year="2023"),
        ("2022", "11011"): no_rcept,
        ("2021", "11011"): None,
    })
    stats = dh.backfill_vintages(engine=eng, client=client)
    assert (stats["saved"], stats["no_rcept"], stats["failed"]) == (1, 1, 1), stats


# ═══════════════════════════════════════════════════════════════════════════
# ⑧⑨ 쿼터와 순서
# ═══════════════════════════════════════════════════════════════════════════

def test_max_calls_is_respected_and_recorded(eng):
    for y in ("2021", "2022", "2023"):
        _history_only(eng, TICKER, y)
    client = _Client(default=_fs())
    stats = dh.backfill_vintages(engine=eng, client=client, max_calls=2)
    assert stats["calls"] == 2, stats
    assert stats.get("stopped_at_quota") is True, stats
    assert len(client.calls) == 2


def test_the_newest_years_come_first(eng):
    """★쿼터가 끊겨도 가치 있는 쪽부터★ — 백테스트는 최근을 더 자주 본다."""
    for y in ("2019", "2024", "2021"):
        _history_only(eng, TICKER, y)
    assert [y for _, y, _ in dh.vintage_gap(eng)] == ["2024", "2021", "2019"]


# ═══════════════════════════════════════════════════════════════════════════
# ⑩ 컬럼이 없으면 ★조용히 전량 재조회하지 않는다★
# ═══════════════════════════════════════════════════════════════════════════

def test_a_missing_probe_column_fails_loudly(eng, monkeypatch):
    """붙은 줄 알고 진행하면 최악의 경우 **매 실행 전량 재조회**가 된다.

    ★이 테스트는 두 번 겨냥을 고쳤다★
    ① 처음엔 컬럼을 지우기만 했는데 `ensure_history_table()` 의 `ALTER` 가
       **다시 붙여 놓아** 통과하지 못했다 — 정상 경로는 스스로 치유된다.
    ② 그래서 마이그레이션을 no-op 으로 만들어 "삼켜져서 못 붙은" 상황을 흉내냈다.
       W 가 그 `ALTER` 를 `schema_add_columns.add_columns()` 로 옮기면서 확인이
       **그 안으로** 들어갔으므로, 이제는 그 헬퍼가 `False` 를 내는 상황
       (권한·방언 문제로 진짜 못 붙는 경우)을 직접 만든다.

    ★가드가 막는 것은 여전히 같다★ — 컬럼 없이 진행해 흔적을 못 남기는 것.
    """
    monkeypatch.setattr("src.data.schema_add_columns.add_columns",
                        lambda *a, **k: False)
    out = dh.backfill_vintages(engine=eng, client=_Client(default=_fs()))
    assert out.get("error"), out
    assert "vintage_probe_at" in (out.get("message") or ""), out


def test_the_migration_heals_the_column_on_the_normal_path(eng):
    """★위 가드가 정상 경로를 막지 않는다★ — 지워도 마이그레이션이 다시 붙인다."""
    with eng.begin() as conn:
        conn.execute(text("ALTER TABLE financials_history "
                          "RENAME COLUMN vintage_probe_at TO gone"))
    ok = dh.ensure_history_table(eng)
    assert ok[dh.PROBE_COLUMN] is True, "마이그레이션이 컬럼을 되살리지 못했다"


def test_ensure_reports_each_column_by_name(eng):
    """★어느 컬럼이 없는지 이름으로 안다★ — 통짜 bool 이면 고칠 곳을 모른다."""
    ok = dh.ensure_history_table(eng)
    assert set(ok) == {c for c, _ in dh._MIGRATE_COLUMNS}, ok
    assert all(ok.values()), ok


def test_the_column_check_is_not_vacuous(eng):
    """★테스트의 테스트★ — 멀쩡한 스키마에서는 통과한다."""
    _history_only(eng, TICKER, "2023")
    out = dh.backfill_vintages(engine=eng, client=_Client(default=_fs(year="2023")))
    assert not out.get("error"), out


# ═══════════════════════════════════════════════════════════════════════════
# ⑪⑬ 기존 경로를 오염시키지 않는다
# ═══════════════════════════════════════════════════════════════════════════

def test_existing_keys_is_still_a_three_tuple(eng):
    """★로드맵이 걱정한 '매 실행 전량 재조회' 는 이 키를 바꿀 때 생긴다★"""
    assert dh.upsert_statement(eng, TICKER, _fs(year="2024"))
    keys = dh.existing_keys(eng)
    assert keys == {(TICKER, "2024", "11011")}, keys
    assert all(len(k) == 3 for k in keys)


def test_the_body_is_not_rewritten(eng, monkeypatch):
    """★대상은 접수일이다★ 본문을 다시 쓰면 다른 경로의 갱신을 덮을 수 있다."""
    _history_only(eng, TICKER, "2023")
    called = []
    monkeypatch.setattr(dh, "upsert_statement",
                        lambda *a, **k: called.append(a) or True)
    dh.backfill_vintages(engine=eng, client=_Client(default=_fs(year="2023")))
    assert called == [], "backfill_vintages 가 본문을 다시 썼다"


# ═══════════════════════════════════════════════════════════════════════════
# ⑫ 진척도 — ★0 과 미상을 구별한다★
# ═══════════════════════════════════════════════════════════════════════════

def test_vintage_stats_reports_the_gap(eng):
    assert dh.upsert_statement(eng, TICKER, _fs(year="2024"))
    _history_only(eng, TICKER, "2023")
    out = dh.vintage_stats(engine=eng)
    assert out["gap_periods"] == 1, out
    assert out["rows"] == 1, out


def test_an_unreadable_gap_is_none_not_zero(eng):
    """★미상 ≠ 0★ — 0 이면 "다 채웠다" 로 읽힌다."""
    with eng.begin() as conn:
        conn.execute(text("DROP TABLE financials_history"))
    out = dh.vintage_stats(engine=eng)
    assert out["gap_periods"] is None, out
    assert out["reason"], "사유 없는 미상"
