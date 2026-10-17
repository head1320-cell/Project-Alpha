"""★그때 알 수 있던 재무★ — `financials_vintages` 의 as-of 리더 (V3)

## 무엇이 문제인가

V2(`3cd436a`)가 정정공시를 `financials_vintages` 에 나란히 쌓게 했다. 그런데
**쌓기만 하고 읽는 길이 없다.** 지금 재무 PIT 은 여전히 `pit_store.py:33-35`
의 **고정 시차 추정**(연간 90일 · 분기 45일)이고, 저장소가 그것을 스스로 적어
뒀다 — `company_snapshot_builder.py:158`:

    "이 날짜는 **실제 공표일이 아니라 정적 시차 규칙**(연간 90일 · 분기 45일)으로
     추정한 가용일입니다."

이 파일은 그 자리에 **실측 접수일 기반 조회**를 놓는다.

## ★같은 판정을 두 벌 만들지 않는다★

매크로는 이미 `pit_macro.latest_vintage_per_period` 로 "기간별 최신 빈티지" 를
고른다. 재무도 **정확히 같은 판정**이고 축 이름만 다르다:

    매크로   valid=관측기간        transaction=공표시각
    재무     valid=(연도,보고서)   transaction=(접수일, 접수번호)

복제하면 두 벌이 갈라진다 — `pit_macro` 가 그 함수를 공용으로 끌어올린 이유가
그것이다(*"복제하면 두 벌이 갈라진다 … 한쪽만 빠져도 조용히 거짓 PIT 를 만든다"*).
아래 ④가 **실제로 그 함수를 쓰는지**를 관측한다.

## 왜 로더와 순수 함수를 가르나

백테스트는 봉마다 as-of 를 묻는다. 봉마다 DB 를 때리면 종목 × 봉 만큼 쿼리가
나간다. P1 이 매크로에서 쓴 구조를 그대로 쓴다 — **읽기 1회**(`load_vintages`)
+ **봉마다 순수 필터**(`vintages_as_of`). `history_as_of` 는 그 둘의 편의 조합이다.

## 이 파일이 거는 계약

① `rcept_dt <= as_of` 인 행만 본다 — 접수 전 공시는 존재하지 않는다.
② 기간별로 **그 시점 최신** 빈티지 하나. 정정 전이면 원본, 정정 후면 정정본.
③ ★미상 ≠ 없음★ — 못 읽으면 `(None, 사유)`, 읽었는데 없으면 `([], None)`.
④ ★`financials_history` 로 폴백하지 않는다★ — 폴백하면 룩어헤드가 PIT 로 위장한다.
⑤ 행 모양이 `load_history` 와 호환된다 — 기존 파생 팩터가 그대로 돈다.
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


@pytest.fixture
def mem_engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    dh.ensure_history_table(eng)
    assert dh.ensure_vintage_table(eng), "빈티지 테이블을 만들지 못했다"
    dh._VINTAGE_SKIPPED["no_rcept"] = 0
    yield eng
    eng.dispose()


@pytest.fixture
def bare_engine():
    """★빈티지 테이블이 **없는** 엔진★ — "못 읽었다" 와 "없다" 를 가르는 데 쓴다."""
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    dh.ensure_history_table(eng)
    yield eng
    eng.dispose()


def _fs(*, rcept_no: str, rcept_dt: str, revenue: float,
        year: str = "2024", reprt: str = "11011",
        net_income: float = 100.0) -> FinancialStatement:
    fs = FinancialStatement(corp_code="00126380", corp_name="삼성전자",
                            bsns_year=year, reprt_code=reprt)
    fs.revenue, fs.net_income = revenue, net_income
    fs.total_equity, fs.total_assets, fs.total_liabilities = 500.0, 2000.0, 1500.0
    fs.rcept_no, fs.rcept_dt = rcept_no, rcept_dt
    return fs


def _seed(engine, *statements) -> None:
    for fs in statements:
        assert dh.upsert_statement(engine, TICKER, fs), f"적재 실패: {fs.rcept_no}"


#: 2024 연간 — 3/14 원본(매출 1000) → 6/20 정정(매출 900). ★하향 정정★ 이라
#: 원본을 그대로 쓰면 실적을 과대평가한다.
ORIGINAL = dict(rcept_no="20250314000777", rcept_dt="2025-03-14", revenue=1000.0)
RESTATED = dict(rcept_no="20250620000999", rcept_dt="2025-06-20", revenue=900.0)


# ═══════════════════════════════════════════════════════════════════════════════
# ① as-of 필터 — ★이 작업의 알맹이★
# ═══════════════════════════════════════════════════════════════════════════════

def test_before_the_restatement_the_original_value_is_returned(mem_engine):
    """★알맹이★ 정정일 **전** 시점에서는 그때 알던 값(원본)이 나온다.

    이것이 되지 않으면 백테스트는 2025-04 시점에 2025-06 에야 알려진 정정값을
    쓰게 된다 — 정의 그대로의 룩어헤드다.
    """
    _seed(mem_engine, _fs(**ORIGINAL), _fs(**RESTATED))
    rows, reason = dh.history_as_of(TICKER, "2025-04-01", engine=mem_engine)
    assert reason is None, reason
    assert len(rows) == 1, rows
    assert rows[0]["revenue"] == 1000.0, f"정정본이 새어 들어왔다: {rows[0]}"
    assert rows[0]["rcept_no"] == ORIGINAL["rcept_no"], rows[0]


def test_after_the_restatement_the_corrected_value_is_returned(mem_engine):
    """★짝★ 이것이 없으면 "항상 최초 빈티지" 구현도 위 테스트를 통과한다."""
    _seed(mem_engine, _fs(**ORIGINAL), _fs(**RESTATED))
    rows, reason = dh.history_as_of(TICKER, "2025-07-01", engine=mem_engine)
    assert reason is None, reason
    assert len(rows) == 1, rows
    assert rows[0]["revenue"] == 900.0, f"정정을 반영하지 않았다: {rows[0]}"
    assert rows[0]["rcept_no"] == RESTATED["rcept_no"], rows[0]


def test_before_the_first_filing_nothing_is_known(mem_engine):
    """★접수 전에는 존재하지 않는다★ 빈 목록이지 실패가 아니다."""
    _seed(mem_engine, _fs(**ORIGINAL), _fs(**RESTATED))
    rows, reason = dh.history_as_of(TICKER, "2025-01-01", engine=mem_engine)
    assert reason is None, reason
    assert rows == [], rows


def test_the_filing_date_itself_is_included(mem_engine):
    """★경계★ `rcept_dt <= as_of` — 접수일 당일은 포함이다.

    ★이 함수가 답하지 않는 것★ — 접수 **시각**(시:분)은 모른다. DART 는 18시까지
    접수를 받으므로 장마감 후 접수분이 같은 날에 섞일 수 있다. 그 안전 여유는
    호출자가 **보이는 자리에서** 준다(예: 직전 거래일을 as_of 로 넘긴다).
    여기서 몰래 하루를 빼면 반대로 "왜 하루 늦나" 를 아무도 못 찾는다.
    """
    _seed(mem_engine, _fs(**ORIGINAL))
    on_day, _ = dh.history_as_of(TICKER, "2025-03-14", engine=mem_engine)
    prev_day, _ = dh.history_as_of(TICKER, "2025-03-13", engine=mem_engine)
    assert len(on_day) == 1, on_day
    assert prev_day == [], prev_day


# ═══════════════════════════════════════════════════════════════════════════════
# ② 기간별로 따로 고른다
# ═══════════════════════════════════════════════════════════════════════════════

def test_each_period_picks_its_own_latest_vintage(mem_engine):
    """★기간 구분 없이 전체에서 하나만 고르는 구현을 배제한다★"""
    _seed(mem_engine,
          _fs(rcept_no="20240315000001", rcept_dt="2024-03-15", revenue=800.0, year="2023"),
          _fs(**ORIGINAL),                                       # 2024 연간 원본
          _fs(**RESTATED))                                       # 2024 연간 정정
    rows, reason = dh.history_as_of(TICKER, "2025-07-01", engine=mem_engine)
    assert reason is None, reason
    got = {(r["year"], r["reprt"]): r["revenue"] for r in rows}
    assert got == {(2023, "11011"): 800.0, (2024, "11011"): 900.0}, got


def test_periods_come_back_in_chronological_order(mem_engine):
    """★정렬★ `financials_history` 리더 8곳이 조용히 깨진 원인이 정렬 부재였다.

    이 함수는 그 실수를 물려받지 않는다 — `seq` 오름차순을 계약으로 못 박는다.
    """
    _seed(mem_engine,
          _fs(rcept_no="20250314000700", rcept_dt="2025-03-14", revenue=1.0,
              year="2024", reprt="11011"),
          _fs(rcept_no="20230515000100", rcept_dt="2023-05-15", revenue=2.0,
              year="2023", reprt="11013"),
          _fs(rcept_no="20240814000200", rcept_dt="2024-08-14", revenue=3.0,
              year="2024", reprt="11012"))
    rows, _ = dh.history_as_of(TICKER, "2025-12-31", engine=mem_engine)
    seqs = [r["seq"] for r in rows]
    assert seqs == sorted(seqs), f"연대순이 아니다: {[(r['year'], r['reprt']) for r in rows]}"
    assert [r["revenue"] for r in rows] == [2.0, 3.0, 1.0], rows


def test_a_same_day_restatement_is_broken_by_the_receipt_sequence(mem_engine):
    """★같은 날 두 번 접수★ 접수일만으로는 순서가 갈리지 않는다.

    `rcept_no` 는 `YYYYMMDD` + 그날의 접수순번이라(V1 의 `filing_date_of` 가 이미
    앞 8자리에 기대고 있다) 접수번호가 그날 안의 순서를 준다. 접수일만 비교하면
    같은 날 정정이 **행 순서(=미정)** 에 따라 갈린다.
    """
    _seed(mem_engine,
          _fs(rcept_no="20250314000100", rcept_dt="2025-03-14", revenue=1000.0),
          _fs(rcept_no="20250314000900", rcept_dt="2025-03-14", revenue=900.0))
    rows, _ = dh.history_as_of(TICKER, "2025-03-14", engine=mem_engine)
    assert len(rows) == 1, rows
    assert rows[0]["revenue"] == 900.0, f"그날의 나중 접수분이 아니다: {rows[0]}"


# ═══════════════════════════════════════════════════════════════════════════════
# ③ ★미상 ≠ 없음★
# ═══════════════════════════════════════════════════════════════════════════════

def test_an_unreadable_table_is_unknown_not_empty(bare_engine):
    """★가장 중요한 구별★ 빈티지 테이블이 없으면 `(None, 사유)` 다.

    `[]` 를 돌려주면 소비자는 "빈티지가 없구나" 로 읽고 조용히 추정 시차로
    넘어간다 — **하지 않은 진술**이고, 룩어헤드가 PIT 라벨을 달게 된다.
    """
    rows, reason = dh.history_as_of(TICKER, "2025-07-01", engine=bare_engine)
    assert rows is None, f"못 읽었는데 목록을 돌려줬다: {rows}"
    assert reason and "financials_vintages" in reason, reason


def test_an_empty_table_is_empty_not_unknown(mem_engine):
    """★짝★ 이것이 없으면 "항상 None" 구현도 위 테스트를 통과한다."""
    rows, reason = dh.history_as_of(TICKER, "2025-07-01", engine=mem_engine)
    assert rows == [], rows
    assert reason is None, reason


def test_a_malformed_as_of_is_refused_not_silently_widened(mem_engine):
    """★잘못된 as_of 를 통과시키지 않는다★ 문자열 비교라 조용히 전부/전무가 된다.

    `"2025"` 는 모든 `"2025-03-14"` 보다 작아 **아무것도 안 나오고**,
    `"2025-13-99"` 는 모든 것보다 커 **전부 나온다**. 둘 다 그럴듯한 답이라
    아무도 눈치채지 못한다.
    """
    _seed(mem_engine, _fs(**ORIGINAL))
    for bad in ("2025", "2025-3-14", "20250314", "", None, "2025-13-01", "2025-02-30"):
        rows, reason = dh.history_as_of(TICKER, bad, engine=mem_engine)
        assert rows is None, f"{bad!r} 를 통과시켰다: {rows}"
        assert reason, f"{bad!r} 를 거절하면서 사유를 안 줬다"


def test_the_pure_filter_rejects_a_malformed_as_of_loudly():
    """순수 함수는 **예외**로 거절한다 — `accumulate_for_bars` 와 같은 규율."""
    with pytest.raises(ValueError):
        dh.vintages_as_of([], "2025-13-01")


@pytest.mark.parametrize("bad_dt", ["", "   ", "2025/01/01", "2025-1-1", "2025-13-01"])
def test_a_row_without_a_usable_filing_date_cannot_answer_an_as_of_question(
        mem_engine, bad_dt):
    """★`vintage_id` 가 빈 행을 버리는 매크로 가드와 같은 판단★

    transaction time 이 없는 행은 as-of 질문에 답할 수 없다. 통과시키면
    "언제부터 알았는지 모르는 값" 이 PIT 값으로 위장한다.

    ★나쁜 행을 **자기 기간에 혼자** 둔다★ — 정상 행과 같은 기간에 두면 어차피
    스탬프 비교에서 져서, 가드가 없어도 이 테스트가 통과한다(처음에 그렇게
    썼다가 고쳤다). 혼자 있으면 가드가 없을 때 **그 행이 그대로 나온다.**
    """
    _seed(mem_engine, _fs(**ORIGINAL))                          # 2024 연간 — 정상
    with mem_engine.begin() as c:                               # 2023 연간 — 접수일 불량
        c.execute(text(
            "INSERT INTO financials_vintages (ticker, bsns_year, reprt_code, rcept_no,"
            " rcept_dt, revenue) VALUES (:t, '2023', '11011', 'X', :d, 99999.0)"),
            {"t": TICKER, "d": bad_dt})
    rows, reason = dh.history_as_of(TICKER, "2025-07-01", engine=mem_engine)
    assert reason is None, reason
    assert [r["revenue"] for r in rows] == [1000.0], (
        f"접수일이 {bad_dt!r} 인 행이 as-of 답에 들어왔다: {rows}")


# ═══════════════════════════════════════════════════════════════════════════════
# ④ ★financials_history 로 폴백하지 않는다★
# ═══════════════════════════════════════════════════════════════════════════════

def test_it_never_falls_back_to_the_overwrite_table(mem_engine):
    """★침묵 폴백 금지★ `financials_history` 는 "지금 값" 이라 as-of 를 답할 수 없다.

    빈티지가 비었을 때 그쪽을 읽으면 **현재 개정본**이 과거 봉에 들어간다 —
    막으려던 룩어헤드 그 자체가 PIT 라벨을 달고 돌아온다.
    """
    with mem_engine.begin() as c:
        c.execute(text(
            "INSERT INTO financials_history (ticker, bsns_year, reprt_code, revenue)"
            " VALUES (:t, '2024', '11011', 777.0)"), {"t": TICKER})
    assert dh.history_snapshot(TICKER, "2024", "11011", engine=mem_engine) is not None, \
        "폴백 대상이 비어 있으면 이 테스트가 공허해진다"

    rows, reason = dh.history_as_of(TICKER, "2025-07-01", engine=mem_engine)
    assert reason is None, reason
    assert rows == [], f"덮어쓰기 테이블에서 폴백했다: {rows}"


def test_another_ticker_does_not_leak(mem_engine):
    _seed(mem_engine, _fs(**ORIGINAL))
    rows, reason = dh.history_as_of("000660", "2025-07-01", engine=mem_engine)
    assert reason is None and rows == [], rows


# ═══════════════════════════════════════════════════════════════════════════════
# ⑤ ★같은 판정을 공유한다★ — 복제하면 두 벌이 갈라진다
# ═══════════════════════════════════════════════════════════════════════════════

def test_it_uses_the_shared_latest_vintage_rule(mem_engine, monkeypatch):
    """★관측 가능하게 못 박는다★ 공용 규칙을 바꾸면 재무 쪽 답도 바뀌어야 한다.

    "부르기만 하고 결과는 버리는" 구현을 배제하려고, 규칙을 **틀린 답**으로
    바꿔치기하고 그것이 실제로 나오는지 본다.
    """
    from src.data import pit_macro

    called = {"n": 0}

    def _first_instead_of_latest(items, **kw):
        called["n"] += 1
        period_of = kw.get("period_of") or (lambda o: o.observation_period)
        best: dict = {}
        for it in items:
            best.setdefault(period_of(it), it)      # ★최초★ — 일부러 틀린 규칙
        return [best[k] for k in sorted(best, key=str)]

    monkeypatch.setattr(pit_macro, "latest_vintage_per_period", _first_instead_of_latest)

    _seed(mem_engine, _fs(**ORIGINAL), _fs(**RESTATED))
    rows, _ = dh.history_as_of(TICKER, "2025-07-01", engine=mem_engine)
    assert called["n"] >= 1, "공용 규칙을 부르지 않았다 — 판정이 복제돼 있다"
    assert rows[0]["revenue"] == 1000.0, (
        f"공용 규칙을 바꿨는데 답이 그대로다 — 결과를 버리고 자체 판정을 쓴다: {rows}")


def test_the_shared_rule_still_answers_the_macro_shape_unchanged():
    """★동작 불변★ 재무를 위해 일반화했다고 매크로 판정이 달라지면 안 된다."""
    from src.data.pit_macro import MacroObservation, latest_vintage_per_period

    obs = [
        MacroObservation(series_id="X", observation_period="2024-01-01",
                         value=1.0, release_timestamp="2024-02-01", vintage_id="v1",
                         retrieved_at="2024-09-01"),
        MacroObservation(series_id="X", observation_period="2024-01-01",
                         value=2.0, release_timestamp="2024-03-01", vintage_id="v2",
                         retrieved_at="2024-09-01"),
        MacroObservation(series_id="X", observation_period="2024-02-01",
                         value=3.0, release_timestamp="2024-03-01", vintage_id="v3",
                         retrieved_at="2024-09-01"),
    ]
    got = latest_vintage_per_period(obs)
    assert [o.observation_period for o in got] == ["2024-01-01", "2024-02-01"]
    assert [o.value for o in got] == [2.0, 3.0]


# ═══════════════════════════════════════════════════════════════════════════════
# ⑥ 로더 / 순수 필터 분리 — 봉마다 DB 를 때리지 않는다
# ═══════════════════════════════════════════════════════════════════════════════

def test_the_pure_filter_needs_no_database(mem_engine):
    """★읽기 1회 + 봉마다 순수 필터★ P1 이 매크로에서 쓴 구조 그대로."""
    _seed(mem_engine, _fs(**ORIGINAL), _fs(**RESTATED))
    loaded, reason = dh.load_vintages(TICKER, engine=mem_engine)
    assert reason is None and len(loaded) == 2, (loaded, reason)

    mem_engine.dispose()          # ★DB 를 치우고 나서★ 봉마다 답이 나와야 한다
    assert dh.vintages_as_of(loaded, "2025-04-01")[0]["revenue"] == 1000.0
    assert dh.vintages_as_of(loaded, "2025-07-01")[0]["revenue"] == 900.0
    assert dh.vintages_as_of(loaded, "2025-01-01") == []


def test_the_pure_filter_does_not_mutate_its_input(mem_engine):
    """봉마다 부르는 자리라 입력을 갉아먹으면 두 번째 봉부터 답이 달라진다."""
    _seed(mem_engine, _fs(**ORIGINAL), _fs(**RESTATED))
    loaded, _ = dh.load_vintages(TICKER, engine=mem_engine)
    before = [dict(r) for r in loaded]
    for as_of in ("2025-01-01", "2025-04-01", "2025-07-01", "2025-04-01"):
        dh.vintages_as_of(loaded, as_of)
    assert [dict(r) for r in loaded] == before, "입력이 변형됐다"


def test_loading_an_unreadable_table_is_unknown(bare_engine):
    rows, reason = dh.load_vintages(TICKER, engine=bare_engine)
    assert rows is None and reason, (rows, reason)


# ═══════════════════════════════════════════════════════════════════════════════
# ⑦ 행 모양 — 기존 파생 팩터가 그대로 돈다
# ═══════════════════════════════════════════════════════════════════════════════

def test_rows_carry_the_same_shape_as_load_history_plus_provenance(mem_engine):
    """★소비자가 갈아끼울 수 있어야 한다★ `load_history` 행의 상위집합이다."""
    _seed(mem_engine, _fs(**ORIGINAL))
    rows, _ = dh.history_as_of(TICKER, "2025-07-01", engine=mem_engine)
    r = rows[0]
    for key in (*dh._FIELDS, "year", "reprt", "month", "seq"):
        assert key in r, f"`load_history` 에 있는 {key} 가 없다"
    assert r["year"] == 2024 and r["reprt"] == "11011" and r["month"] == 12
    assert r["seq"] == 2024 * 12 + 12
    assert r["rcept_no"] == ORIGINAL["rcept_no"] and r["rcept_dt"] == ORIGINAL["rcept_dt"], r
    assert isinstance(r["revenue"], float)


def test_the_existing_derived_factors_run_on_as_of_rows(mem_engine):
    """★모양이 맞다는 것을 실제로 돌려서 본다★ 키 목록 비교는 계약이 아니다."""
    _seed(mem_engine,
          _fs(rcept_no="20230315000001", rcept_dt="2023-03-15", revenue=800.0,
              year="2022", net_income=50.0),
          _fs(rcept_no="20240315000001", rcept_dt="2024-03-15", revenue=900.0,
              year="2023", net_income=80.0),
          _fs(**ORIGINAL))
    rows, _ = dh.history_as_of(TICKER, "2025-07-01", engine=mem_engine)
    assert len(rows) == 3, rows
    factors = dh._compute_history_factors(rows)
    # ★불리언이 아니라 1.0/0.0 플래그다★ — 저장소의 기존 계약이고, 그걸 여기서
    # 바꾸지 않는다(소비자 3곳이 이미 숫자로 읽는다).
    assert factors["ni_positive_3y"] == 1.0, factors
    assert factors["ni_growth_yoy"] == pytest.approx(25.0), factors   # 80 → 100
    assert factors["asset_growth_yoy"] is not None, factors


def test_an_unplaceable_report_code_is_dropped_not_guessed(mem_engine):
    """월 축에 놓을 수 없는 보고서 코드는 버린다 — `load_history` 와 같은 처리."""
    _seed(mem_engine, _fs(**ORIGINAL))
    with mem_engine.begin() as c:
        c.execute(text(
            "INSERT INTO financials_vintages (ticker, bsns_year, reprt_code, rcept_no,"
            " rcept_dt, revenue) VALUES (:t, '2024', '99999', 'Y', '2025-01-01', 5.0)"),
            {"t": TICKER})
    rows, reason = dh.history_as_of(TICKER, "2025-07-01", engine=mem_engine)
    assert reason is None, reason
    assert [r["revenue"] for r in rows] == [1000.0], rows
