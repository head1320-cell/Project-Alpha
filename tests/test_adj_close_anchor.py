"""수정주가 앵커 — ★KIS 행 하나가 전체 역사를 지우지 않는다★
==============================================================================
설계: `/root/.claude/plans` Phase 3 · 선행: `test_price_quality_gate` · `test_price_basis`

## 이 파일이 막는 것

`rebuild_adj_close` 는 앵커를 **무조건 최신 봉**에 놓았다. `ohlcv_loader` 가 넣는
KIS 행에는 `return_1d` 가 없으므로, 그런 행이 최신 봉이면 체인이 **첫 걸음에서**
끊기고 그 아래가 전부 `NULL` 이 됐다 — 아래 행들의 등락률 체인은 멀쩡한데도.

    실측: KRX 5행 + KIS 최신봉 1개 → ★5행 조정이 1행으로★

그리고 `load_ohlcv_unified(prefer="auto")` 와 `prewarm_ohlcv` 가 최신 KIS 봉을
적재하므로 **그것이 운영의 기본 상태였다.**

`adj[i] = adj[i+1] / (1 + return_1d[i+1]/100)` 이므로 앵커 자신에게 등락률이
있어야 아래로 한 걸음이라도 갈 수 있다. 앵커는 **그런 행 중 가장 최신**이다.

## ★`price_basis` 를 보지 않는다★

"basis 가 `adjusted` 면 앵커 금지" 로도 짤 수 있었지만 두 가지 이유로 버렸다:

1. `source`·`price_basis` 는 최근에 생긴 컬럼이라 **레거시 행은 전부 NULL** 이다.
   basis 로 고르면 그 배포가 앵커를 전부 잃는다 (A7 이 이것을 막는다).
2. 그 규칙은 *"KIS 는 수정주가를 준다"* 라는 **아직 검증되지 않은** 가정에 기댄다.
   `return_1d` 규칙은 그 가정과 무관하게 옳다.
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import src.data.price_quality as pq  # noqa: E402
from src.data.krx_ingest import (  # noqa: E402
    bulk_upsert,
    ensure_table,
    rebuild_adj_close,
)

_DATES = ["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"]
_CLOSES = [1000.0, 1010.0, 500.0, 505.0, 510.0]        # 2026-01-06 이 2:1 분할
_FLUC = [0.5, 1.0, -0.2, 1.0, 0.99]

#: ★A1 이 지키는 값★ KRX 전용 티커의 재구성 결과. 앵커 규칙이 바뀌어도 이 값은
#: 그대로여야 한다 — 개수만 보면 앵커를 엉뚱한 데 놓아도 통과한다.
_KRX_ONLY_ADJ = [496.0421, 501.0025, 500.0005, 505.0005, 510.0]


@pytest.fixture
def eng():
    e = create_engine("sqlite://", connect_args={"check_same_thread": False},
                      poolclass=StaticPool)
    ensure_table(e)
    yield e
    e.dispose()


def _krx(eng, ticker="A", fluc=None, n=5):
    fluc = _FLUC if fluc is None else fluc
    bulk_upsert(eng, [
        {"ticker": ticker, "date": d, "close": c, "open": c, "high": c, "low": c,
         "volume": 1, "trading_value": 1, "fluc_rt": f}
        for d, c, f in zip(_DATES[:n], _CLOSES[:n], fluc[:n], strict=True)])


def _kis(eng, ticker, date, close, *, basis="adjusted"):
    """`ohlcv_loader.ingest_df_to_db` 가 넣는 모양 — ★`return_1d` 가 없다★"""
    with eng.begin() as c:
        c.execute(text(
            "INSERT INTO daily_prices (ticker, trade_date, close, source, "
            "price_basis) VALUES (:t, :d, :c, 'kis', :b)"),
            {"t": ticker, "d": date, "c": close, "b": basis})


def _adj(eng, ticker="A"):
    with eng.connect() as c:
        return [r[0] for r in c.execute(text(
            "SELECT adj_close FROM daily_prices WHERE ticker=:t "
            "ORDER BY trade_date"), {"t": ticker})]


# ══════════════════════════════════════════════════════════════════════════
# 1) ★기존 동작이 값까지 그대로다★
# ══════════════════════════════════════════════════════════════════════════
def test_krx_only_values_are_unchanged(eng):
    """A1 — 개수가 아니라 **값**을 못 박는다.

    개수만 보면 앵커를 엉뚱한 행에 놓아도 통과한다. 앵커가 옮겨지면 계열 전체가
    상수배로 어긋나므로 값이 그것을 잡는다.
    """
    _krx(eng)
    assert rebuild_adj_close(eng, tickers=["A"]) == 5
    assert _adj(eng) == pytest.approx(_KRX_ONLY_ADJ)


def test_legacy_rows_without_basis_or_source_behave_identically(eng):
    """A7 ★레거시★ — 규칙이 `price_basis` 에 의존하면 이 테스트가 죽는다.

    `source`·`price_basis` 는 최근에 생긴 컬럼이라 기존 배포의 행은 전부 NULL 이다.
    basis 로 앵커를 고르면 그 배포의 모든 티커가 앵커를 잃는다.
    """
    _krx(eng)
    with eng.begin() as c:
        c.execute(text("UPDATE daily_prices SET source=NULL, price_basis=NULL"))
    assert rebuild_adj_close(eng, tickers=["A"]) == 5
    assert _adj(eng) == pytest.approx(_KRX_ONLY_ADJ)


# ══════════════════════════════════════════════════════════════════════════
# 2) ★핵심 — KIS 최신봉이 역사를 지우지 않는다★
# ══════════════════════════════════════════════════════════════════════════
def test_a_kis_bar_on_top_no_longer_destroys_the_history(eng):
    """A2 ★핵심★ 예전에는 5행 → 1행이었다."""
    _krx(eng)
    _kis(eng, "A", "2026-01-09", 515.0)
    assert rebuild_adj_close(eng, tickers=["A"]) == 5, "KIS 행이 역사를 지웠다"
    assert _adj(eng)[:5] == pytest.approx(_KRX_ONLY_ADJ), "앵커가 옮겨져 척도가 틀어졌다"


def test_rows_above_the_anchor_stay_null(eng):
    """A3 — 앵커 위(더 최신)를 추정하지 않는다.

    그 행의 조정 상태를 우리는 모른다. `close` 를 베껴 넣으면 Phase 2 가 하지
    않기로 한 단정이 된다.
    """
    _krx(eng)
    _kis(eng, "A", "2026-01-09", 515.0)
    rebuild_adj_close(eng, tickers=["A"])
    assert _adj(eng)[-1] is None, "앵커 위를 채웠다"


def test_two_kis_bars_on_top_still_leave_the_history_intact(eng):
    """A2 짝 — 한 행짜리 특수 처리가 아니다."""
    _krx(eng)
    _kis(eng, "A", "2026-01-09", 515.0)
    _kis(eng, "A", "2026-01-12", 520.0)
    assert rebuild_adj_close(eng, tickers=["A"]) == 5
    assert _adj(eng)[-2:] == [None, None]


def test_the_anchor_is_the_newest_usable_row_not_an_older_one(eng):
    """A9 ★짝★ — 없으면 "가장 오래된 쓸 수 있는 행" 구현으로도 A2 가 통과한다.

    앵커가 `2026-01-08`(최신 KRX 봉)이면 그 행의 `adj` 는 `close` 와 같다.
    더 과거로 내려갔다면 그 값이 달라진다.
    """
    _krx(eng)
    _kis(eng, "A", "2026-01-09", 515.0)
    rebuild_adj_close(eng, tickers=["A"])
    assert _adj(eng)[4] == pytest.approx(510.0), "앵커가 최신 쓸 수 있는 행이 아니다"


# ══════════════════════════════════════════════════════════════════════════
# 3) 체인이 끊기는 규칙은 그대로다
# ══════════════════════════════════════════════════════════════════════════
def test_a_gap_in_the_middle_still_breaks_everything_below(eng):
    """A4 — 중간 결측에서 아래를 추정하지 않는다(변경 없음)."""
    _krx(eng, fluc=[0.5, 1.0, None, 1.0, 0.99])
    rebuild_adj_close(eng, tickers=["A"])
    got = _adj(eng)
    # rows[2].fluc 이 없으면 adj[1] 을 만들 수 없다 → 0,1 은 NULL, 2..4 는 살아 있다.
    assert got[0] is None and got[1] is None, f"끊긴 아래가 추정됐다: {got}"
    assert all(v is not None for v in got[2:]), f"위쪽까지 지웠다: {got}"


def test_a_kis_row_in_the_middle_does_not_break_the_chain(eng):
    """A5 — ★KIS 가 KRX 행을 덮어도 `return_1d` 는 남는다★ (실측)

    UPSERT 가 `return_1d` 를 건드리지 않으므로 중간 KIS 행은 링크를 유지한다.
    문제는 언제나 **앵커 위치** 하나였다.
    """
    _krx(eng)
    with eng.begin() as c:
        c.execute(text("UPDATE daily_prices SET source='kis', price_basis='adjusted' "
                       "WHERE ticker='A' AND trade_date='2026-01-06'"))
    assert rebuild_adj_close(eng, tickers=["A"]) == 5
    assert _adj(eng) == pytest.approx(_KRX_ONLY_ADJ)


def test_the_sentinel_return_is_not_a_usable_link(eng):
    """A8 — `-99.0` 이하는 값이 아니라 "없음" 표시다.

    앵커 선택과 링크 판정이 **같은 규칙**을 써야 한다. 갈라지면 앵커를 세워 놓고
    첫 걸음에서 끊기는 옛 결함이 다른 모양으로 되살아난다.
    """
    _krx(eng, fluc=[0.5, 1.0, -0.2, 1.0, -99.9])
    rebuild_adj_close(eng, tickers=["A"])
    got = _adj(eng)
    assert got[-1] is None, "센티넬 행이 앵커가 됐다"
    assert got[-2] == pytest.approx(505.0), "앵커가 그 아래로 내려가지 않았다"


# ══════════════════════════════════════════════════════════════════════════
# 4) ★앵커가 없으면 전량 NULL — 그리고 상태가 정확해진다★
# ══════════════════════════════════════════════════════════════════════════
def test_a_ticker_with_no_returns_gets_no_anchor(eng):
    """A6 — 등락률이 하나도 없으면 앵커를 세울 근거가 없다.

    ★예전 값이 거짓이었던 것은 아니다★ `adj(최신)=close(최신)` 는 정규화 관례이고
    구성상 참이다. 다만 그 한 점으로는 **수익률을 하나도 계산할 수 없고**, 그
    한 점 때문에 상태가 `chain_broken`("그 구간 재적재")으로 잡혀 **틀린 조치**를
    안내했다. 진실은 "KRX 데이터가 아예 없다" 이다.
    """
    _kis(eng, "K", "2026-01-02", 100.0)
    _kis(eng, "K", "2026-01-05", 101.0)
    assert rebuild_adj_close(eng, tickers=["K"]) == 0
    assert _adj(eng, "K") == [None, None]

    cov = pq.adj_close_coverage(["K"], engine=eng)
    assert cov["by_ticker"]["K"] == pq.STATE_RAW, "여전히 chain_broken 으로 잡힌다"
    assert pq.RAW_NO_RETURN_DATA in cov["raw_reasons"]


def test_a_single_row_with_a_return_is_still_anchored(eng):
    """A6 짝 — "앵커 없음" 이 과잉 적용되지 않는다."""
    _krx(eng, n=1)
    assert rebuild_adj_close(eng, tickers=["A"]) == 1
    assert _adj(eng) == pytest.approx([1000.0])


# ══════════════════════════════════════════════════════════════════════════
# 5) ★불변 논증을 테스트로 못 박는다★
# ══════════════════════════════════════════════════════════════════════════
def test_adj_close_has_no_consumer_outside_the_research_panel():
    """★이 변경이 배분에 무해하다는 근거 — ★M9 에서 다시 한 논증★

    원래 근거는 "`adj_close` 를 읽는 코드가 0건" 이었다. M9(`research_panel`)이
    **소비자를 하나 만들었으므로** 이 테스트가 red 가 됐고, 설계대로 논증을
    다시 했다. 통과시키려고 테스트를 고친 것이 아니다.

    ## 새 논증

    소비자는 `src/engine/research_panel.py::_default_price_loader` 하나이고,
    도달 경로는 `real_panel()` → `panel_for(real=True)` → **연구 CLI 두 개**
    (`scripts/regime_control.py --real` · `scripts/regime_signal_gate.py --real`)
    뿐이다. 라우트·엔진·배분 경로는 이 함수를 부르지 않는다 — 그 사실을
    **산문이 아니라 아래 짝 테스트가 정적으로 강제**한다.

    따라서 앵커 규칙이 틀리면 **연구 패널이 틀린다**(그리고 그 리포트는 E0/E3
    등급과 `coverage` 를 달고 나온다). 배분 비중·주문·실계좌 경로는 여전히
    `adj_close` 를 읽지 않으므로 원래 무해성 논증은 **그 범위에서 그대로 유효**하다.

    ★허용 목록은 침묵 면제가 아니다★ 여기 이름을 더하려면 위와 같은 논증을
    적어야 하고, 짝 테스트가 그 주장을 검사한다.

    산문은 `adj_close` 를 얼마든지 **설명**할 수 있어야 하므로 grep 하지 않는다.
    `tokenize` 로 주석·독스트링을 걷어내고 **코드 토큰과 SQL 문자열**에서만 찾는다
    (`test_price_basis` 가 쓴 것과 같은 방식).
    """
    import io as _io
    import pathlib
    import tokenize

    #: 이 컬럼의 주인들 — 재구성이 쓰고 품질 보고가 읽는다.
    OWNERS = {"src/data/krx_ingest.py", "src/data/price_quality.py"}
    #: 스키마 선언은 소비가 아니다.
    SCHEMA = "src/kis_models.py"
    #: ★연구 전용 소비자 (M9)★ — 위 독스트링의 논증과 아래 짝 테스트가 근거다.
    RESEARCH = {"src/engine/research_panel.py"}

    hits = []
    for path in sorted(list(pathlib.Path("src").rglob("*.py"))
                       + list(pathlib.Path("scripts").rglob("*.py"))):
        rel = path.as_posix()
        if rel in OWNERS or rel == SCHEMA or rel in RESEARCH:
            continue
        src = path.read_text(encoding="utf-8")
        if "adj_close" not in src:
            continue
        try:
            toks = list(tokenize.generate_tokens(_io.StringIO(src).readline))
        except (tokenize.TokenError, IndentationError, SyntaxError):
            continue
        for tok in toks:
            if tok.type == tokenize.COMMENT:
                continue
            if tok.type == tokenize.NAME:
                # ★정확히 그 식별자여야 한다★ `adj_close_coverage`(보고 함수)는
                # 이 컬럼을 **읽는 소비자가 아니라** 품질 보고의 이름이다.
                if tok.string == "adj_close":
                    hits.append(f"{rel}:{tok.start[0]}: {tok.string}")
                continue
            if tok.type == tokenize.STRING:
                up = tok.string.upper()
                if not any(k in up for k in ("SELECT", "INSERT", "UPDATE")):
                    continue          # 독스트링은 설명해도 된다
                if "adj_close" in tok.string:
                    hits.append(f"{rel}:{tok.start[0]}: SQL {tok.string[:50]}")
    assert hits == [], (
        "`adj_close` 소비자가 생겼다 — 불변 논증을 다시 할 것:\n" + "\n".join(hits))


def test_the_research_panel_price_path_is_unreachable_from_allocation():
    """★짝 — 위 논증이 주장이 아니라 계약이 되게 한다★

    "연구 전용이라 배분에 무해하다" 는 문장은 코드가 지키지 않으면 언제든 거짓이
    된다. 라우트·배분 경로가 `real_panel`/`panel_for(real=True)` 를 부르기
    시작하면 앵커 규칙이 실제 비중을 움직이게 되고, 그때 허용 목록의 근거가
    사라진다.

    정적 임포트와 동적 임포트를 **둘 다** 본다(K11 이 가르쳐 준 사각지대).
    """
    import io as _io
    import pathlib
    import re
    import tokenize

    #: 배분·주문·라우트 경로 — 여기서 실 패널을 부르면 안 된다.
    WATCH = ("src/api", "src/engine/allocation", "src/engine/regime_adaptive",
             "src/engine/realism_engine.py", "src/engine/multi_strategy",
             "src/engine/trading_engine.py", "src/engine/order")
    dyn = re.compile(r"import_module\s*\(\s*[\"'][^\"']*research_panel"
                     r"|__import__\s*\(\s*[\"'][^\"']*research_panel")

    offenders = []
    for path in sorted(pathlib.Path("src").rglob("*.py")):
        rel = path.as_posix()
        if not any(rel.startswith(w) for w in WATCH):
            continue
        src = path.read_text(encoding="utf-8")
        if dyn.search(src):
            offenders.append(f"{rel}: 동적 임포트")
        if "research_panel" not in src:
            continue
        try:
            toks = list(tokenize.generate_tokens(_io.StringIO(src).readline))
        except (tokenize.TokenError, IndentationError, SyntaxError):
            continue
        for tok in toks:
            if tok.type == tokenize.NAME and tok.string in ("real_panel", "panel_for"):
                offenders.append(f"{rel}:{tok.start[0]}: {tok.string}")
    assert offenders == [], (
        "배분·라우트 경로가 연구 패널을 부른다 — `adj_close` 무해성 논증이 "
        "깨졌다:\n" + "\n".join(offenders))
