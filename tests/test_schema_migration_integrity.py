"""컬럼 마이그레이션 경로를 ★한 벌로★ 모은다 (W)

## 무엇이 문제인가

`ALTER TABLE … ADD COLUMN` 은 SQLite 에서 `IF NOT EXISTS` 를 못 쓴다. 그래서
**"이미 있음" 과 "진짜 실패" 가 같은 예외로** 오고, 관례상 삼킨다.
`src/data/schema_add_columns.py` 가 그 함정을 이미 적어 뒀다:

    1번만 하면 **못 붙은 컬럼을 붙었다고 믿고 이후 조회가 통째로 깨진다.**
    ★두 단계가 다 필요하다★ — 붙이고, 실제로 붙었는지 `SELECT` 로 확인한다.

그리고 그 두 단계를 하는 **공용 헬퍼가 이미 있다**(`add_columns`).

## ★재서 나온 것★

    확인 없이 삼킨다 : krx_ingest · dart_history · kis_flows           ← 3곳
    확인은 하되 사본 : scenario_packs_store · timing_rules · backtest_runs(×2)
    헬퍼를 쓴다      : regime_snapshots · company_snapshots

★이 세션이 같은 부류를 두 번 겪었다★ — H1 의 인덱스 불일치(붙은 줄 알았는데
아니었다), T 의 `vintage_probe_at`(그것 때문에 별도 가드를 따로 써야 했다).
그래서 **인스턴스가 아니라 부류를 죽인다**: 마이그레이션 경로를 하나로 만들고,
여기서 그 하나만 남았는지 **전수로** 건다.

`test_synthetic_store_gate.py`(G3)의 전수 트립와이어와 같은 기법이다.
"""
from __future__ import annotations

import os
import pathlib
import re

os.environ.setdefault("KIS_USE_MOCK", "1")

#: `ALTER TABLE … ADD COLUMN` — f-string·변수 테이블명까지 잡는다.
_ALTER = re.compile(r"ALTER\s+TABLE\s+[^\"']*?ADD\s+COLUMN", re.I)

_SRC = pathlib.Path("src")
#: ★유일하게 허용된 자리★ 여기 말고는 없어야 한다.
_HOME = _SRC / "data" / "schema_add_columns.py"


def _code_lines(src: str) -> dict[int, str]:
    """주석을 **뺀** 줄 → 코드 텍스트. ★설명 주석에 걸리지 않게★

    ★이 세션이 같은 오탐을 이미 겪었다★ — V4 의 트립와이어가 자기 설명 주석의
    `prepare_panel` 이라는 **단어**에 걸려 순서를 거꾸로 읽었다. 여기서도 첫
    실행에서 `ohlcv_loader.py:380` 이 잡혔는데, 그것은 이 패턴을 **설명하는
    주석**이었다(`ensure_table 은 CREATE TABLE … + ALTER TABLE ADD COLUMN × 4 를`).

    정규식으로 `#` 을 자르지 않는다 — 문자열 안의 `#` 에 속는다. `tokenize` 가
    주석을 정확히 알려 주므로 그것을 쓴다.
    """
    import io
    import tokenize
    lines = dict(enumerate(src.splitlines(), 1))
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                row = tok.start[0]
                if row in lines:
                    lines[row] = lines[row].replace(tok.string, "")
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass          # ★파싱 실패는 검사를 끄지 않는다★ 원문 그대로 본다
    return lines


def _offenders() -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    for path in sorted(_SRC.rglob("*.py")):
        if path == _HOME:
            continue
        hits = [i for i, line in _code_lines(path.read_text(encoding="utf-8")).items()
                if _ALTER.search(line)]
        if hits:
            out[str(path)] = sorted(hits)
    return out


# ═══════════════════════════════════════════════════════════════════════════
# ① ★전수★ — 마이그레이션 경로는 하나뿐이다
# ═══════════════════════════════════════════════════════════════════════════

def test_only_one_module_may_add_columns():
    """★부류를 죽인다★ 여섯 번째 사본이 생기면 여기서 걸린다.

    새 컬럼이 필요하면 `schema_add_columns.add_columns()` 를 부른다 — 그 함수가
    붙이고 **실제로 쓸 수 있는지 확인해 `bool` 을 돌려준다**. 직접 `ALTER` 를
    쓰면 그 확인이 빠지고, 못 붙은 컬럼을 붙었다고 믿게 된다.
    """
    bad = _offenders()
    assert not bad, (
        "컬럼 마이그레이션은 `schema_add_columns.add_columns()` 하나로만 합니다 — "
        f"직접 ALTER 를 쓰는 곳: {bad}")


def test_the_home_module_really_does_the_alter():
    """★공허한 검사 배제★ 허용된 자리에 실제로 그 문장이 있어야 한다."""
    assert _ALTER.search(_HOME.read_text(encoding="utf-8")), (
        f"{_HOME} 에 ALTER 가 없다 — 이 트립와이어의 전제가 사라졌다")


# ═══════════════════════════════════════════════════════════════════════════
# ② ★테스트의 테스트★ — 항상 통과하는 검사를 배제한다
# ═══════════════════════════════════════════════════════════════════════════

def test_the_tripwire_catches_a_plain_alter():
    for line in ('c.execute(text("ALTER TABLE foo ADD COLUMN bar INTEGER"))',
                 'conn.execute(text(f"ALTER TABLE {T} ADD COLUMN {col}"))',
                 "alter table x add column y"):
        assert _ALTER.search(line), f"트립와이어가 놓쳤다: {line!r}"


def test_the_tripwire_does_not_fire_on_unrelated_sql():
    """★오탐이 있으면 사람들이 검사를 끈다★"""
    for line in ('c.execute(text("CREATE TABLE IF NOT EXISTS foo (a INT)"))',
                 '"CREATE INDEX IF NOT EXISTS ix ON foo (a)"',
                 "# ALTER 는 예외를 낸다 — 설명 주석",
                 '"SELECT bar FROM foo LIMIT 1"'):
        assert not _ALTER.search(line), f"오탐: {line!r}"


def test_a_comment_that_merely_mentions_the_pattern_is_not_an_offence():
    """★내가 실제로 겪은 오탐을 그대로 재현한다★

    첫 실행에서 `ohlcv_loader.py` 의 **설명 주석**이 잡혔다. 그 문서를 지우거나
    말을 바꾸는 것이 아니라 **검사를 고쳐야** 한다 — 문서를 검사에 맞추기 시작하면
    문서가 거짓말을 하게 된다.
    """
    prose = ('#: `ensure_table` 은 `CREATE TABLE IF NOT EXISTS` + '
             '`ALTER TABLE ADD COLUMN` × 4 를 한다\n')
    assert _ALTER.search(prose), "이 줄이 원래 걸렸다는 전제가 사라졌다"
    assert not any(_ALTER.search(v) for v in _code_lines(prose).values()), (
        "주석을 걷어내고도 여전히 걸린다 — 오탐이 남았다")


def test_a_real_alter_survives_the_comment_stripping():
    """★짝★ 주석 제거가 코드까지 지우면 검사가 통째로 공허해진다."""
    code = 'c.execute(text("ALTER TABLE foo ADD COLUMN bar INT"))  # 붙인다\n'
    assert any(_ALTER.search(v) for v in _code_lines(code).values())


def test_the_scan_actually_reads_files():
    """★스캔이 빈 목록을 보고 있으면 ① 은 언제나 통과한다★"""
    files = list(_SRC.rglob("*.py"))
    assert len(files) > 50, f"소스를 {len(files)}개만 봤다 — 스캔이 잘못됐다"


# ═══════════════════════════════════════════════════════════════════════════
# 동작 — ★소스 텍스트가 아니라 결과를 본다★
#
# ①은 정적 검사다. 그것만으로는 "헬퍼를 부르기만 하고 결과를 버리는" 구현이
# 통과한다. 그래서 여기서는 실제로 돌려 **컬럼이 쓸 수 있는 상태로 끝나는지**와
# **못 쓸 때 조용하지 않은지**를 본다.
# ═══════════════════════════════════════════════════════════════════════════
import pytest  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402


def _eng():
    return create_engine("sqlite://", connect_args={"check_same_thread": False},
                         poolclass=StaticPool)


#: `(모듈, ensure 함수, 테이블, 확인할 컬럼들)`
_ENSURES = [
    ("src.data.krx_ingest", "ensure_table", "daily_prices",
     ("mktcap", "list_shares", "source", "price_basis")),
    ("src.data.dart_history", "ensure_history_table", "financials_history",
     ("dps", "vintage_probe_at")),
    ("src.data.kis_flows", "ensure_flows_table", "investor_flows", ()),
    ("src.data.backtest_runs", "_ensure", "backtest_runs",
     ("heartbeat_at", "telemetry")),
]


def _reset_once_flags(m) -> None:
    """★모듈 전역 1회 플래그를 푼다★

    ★전체 스위트에서만 깨져서 알게 된 것★ — `backtest_runs._ensure` 는
    `global _inited` 로 **한 번만** 돈다. 다른 테스트가 먼저 다른 엔진에 대해
    부르면 여기서는 곧바로 반환하고, 이 엔진에는 테이블이 안 생긴다.
    단독 실행은 통과하고 스위트에서만 실패했다 — 순서 의존이다.

    코드의 결함이 아니라 **이 테스트가 그 사실을 몰랐던 것**이라 여기서 푼다.
    """
    for flag in ("_inited",):
        if hasattr(m, flag):
            setattr(m, flag, False)


@pytest.mark.parametrize(("mod", "fn", "table", "cols"), _ENSURES)
def test_every_ensure_leaves_the_columns_usable(mod, fn, table, cols):
    """③ 붙었다고 **믿는** 것이 아니라 실제로 `SELECT` 가 통해야 한다."""
    import importlib
    m = importlib.import_module(mod)
    _reset_once_flags(m)
    eng = _eng()
    try:
        getattr(m, fn)(eng)
        if table and cols:
            with eng.connect() as c:
                c.execute(text(f"SELECT {', '.join(cols)} FROM {table} LIMIT 1"))
    finally:
        eng.dispose()


@pytest.mark.parametrize(("mod", "fn", "table", "cols"), _ENSURES)
def test_every_ensure_is_idempotent(mod, fn, table, cols):
    """⑦ 두 번 불러도 실패하지 않는다 — 기동 경로가 여러 번 부른다."""
    import importlib
    m = importlib.import_module(mod)
    _reset_once_flags(m)
    eng = _eng()
    try:
        getattr(m, fn)(eng)
        getattr(m, fn)(eng)
    finally:
        eng.dispose()


def test_a_healthy_schema_reports_true():
    """⑨ ★짝★ 항상-False 구현을 배제한다."""
    from src.data.schema_add_columns import add_columns
    eng = _eng()
    try:
        with eng.begin() as c:
            c.execute(text("CREATE TABLE t (a INTEGER)"))
        assert add_columns(eng, "t", [("b", "INTEGER")], label="t") is True
        assert add_columns(eng, "t", [("b", "INTEGER")], label="t") is True  # 멱등
    finally:
        eng.dispose()


def test_an_unusable_column_is_reported_not_swallowed(caplog):
    """④ ★못 붙었을 때 조용하지 않다★ — 로그에 컬럼 이름이 남는다.

    ★처음 쓴 판은 통과하지 못했고, 그것이 사실을 알려 줬다★ — 빈 DDL
    (`ALTER TABLE t ADD COLUMN nope`)을 "실패" 로 썼는데 SQLite 는 **타입 없는
    컬럼을 허용한다**. 그래서 진짜 실패(테이블 자체가 없다)로 바꿨다.
    """
    import logging

    from src.data.schema_add_columns import add_columns
    eng = _eng()
    try:
        with caplog.at_level(logging.WARNING):
            got = add_columns(eng, "no_such_table", [("nope", "INTEGER")],
                              label="no_such_table")
        assert got is False, "없는 테이블에 붙였는데 True 를 냈다"
        assert "nope" in caplog.text, caplog.text
    finally:
        eng.dispose()


def test_krx_names_the_unusable_column(caplog, monkeypatch):
    """⑤ ★넷 중 어느 것인지★ — 통짜 bool 이면 어디를 고칠지 모른다."""
    import logging

    import src.data.krx_ingest as ki
    real = __import__("src.data.schema_add_columns", fromlist=["add_columns"]).add_columns
    monkeypatch.setattr(
        "src.data.schema_add_columns.add_columns",
        lambda e, t, cols, **k: False if cols[0][0] == "price_basis" else real(e, t, cols, **k))
    eng = _eng()
    try:
        with caplog.at_level(logging.WARNING):
            ki.ensure_table(eng)
        assert "price_basis" in caplog.text, caplog.text
        assert "mktcap" not in caplog.text.split("price_basis")[0][-80:], caplog.text
    finally:
        eng.dispose()


def test_dart_reports_each_column_by_name():
    """⑥ 워크어라운드였던 `_has_probe_column` 이 헬퍼 결과로 대체됐다."""
    import src.data.dart_history as dh
    assert not hasattr(dh, "_has_probe_column"), "두 벌이 남아 있다"
    eng = _eng()
    try:
        ok = dh.ensure_history_table(eng)
        assert ok == {"dps": True, "vintage_probe_at": True}, ok
    finally:
        eng.dispose()
