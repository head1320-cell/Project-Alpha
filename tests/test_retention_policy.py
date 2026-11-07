"""보존 정책의 불변식을 ★코드로★ 건다 (X)

## 왜 문서만으로는 부족한가

`DATA_PLATFORM_SPEC.md` §5 가 *"보존/삭제 정책이 없다 … 결정된 적은 없다"* 고
적어 뒀다. X 가 그것을 정했는데, ★이 저장소의 규율은 "수치는 문서가 아니라 코드가
진실" 이다★ — 문서만 두면 다음 사람이 못 보고, 문서는 반드시 낡는다.

그래서 정책 중 **되돌릴 수 없는 부분**만 테스트로 못 박는다:

    ★원천 관측과 감사 기록에는 삭제가 생기면 안 된다.★

## ★리터럴만 보면 거의 다 놓친다★ (실측이 설계를 뒤집었다)

계획은 "`DELETE FROM <표>` 리터럴을 찾는다" 였다. 실제로 세어 보니 저장소의
삭제문 18곳 중 **16곳이 `DELETE FROM {_TABLE}`** 이다 — 모듈 상수를 f-string 으로
끼운다. 리터럴만 보는 가드는 그 16곳을 전부 통과시킨다. 그래서 `ast` 로 모듈
최상위 문자열 상수를 읽어 **이름을 풀어서** 판정한다.

## 왜 그 표들인가 — 지우면 **능력을 잃는다**

    financials_vintages · macro_observations   ★재수집 불가★ 제공자가 과거
        접수본을 다시 주지 않는다. 지우면 as-of 조회(V·P·T·U)가 통째로 죽는다.
    daily_prices                                재수집은 되지만 **상장폐지 종목은
        못 받는다** → 생존편향이 되돌아온다.
    investor_flows                              KIS 는 ★최근 ~30영업일만★ 준다.
    live_* · reconciliation_history             실거래 감사 기록. 보존 요구가
        **바깥에서** 올 수 있고, 이 저장소가 판단할 문제가 아니다.

## ★이것은 삭제 경로가 아니라 삭제를 막는 가드다★

사용자 결정은 "정책만 문서로, 삭제 코드는 만들지 않는다" 였다. 이 파일은 그
결정을 **집행**한다.
"""
from __future__ import annotations

import ast
import io
import os
import pathlib
import re
import tokenize

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.data.retention import (  # noqa: E402
    AUDIT,
    CLASSIFIED,
    DECISION_RECORD,
    KEEP_FOREVER,
    PROTECTED,
    REGENERABLE,
    USER_OWNED,
)

_ROOTS = (pathlib.Path("src"), pathlib.Path("scripts"))
_DECLARATION = "retention.py"
_DOC = pathlib.Path("docs/specs/RETENTION_POLICY.md")

#: 문서가 보호 목록을 적는 구간. 코드와 **같은 집합**인지 대조하는 데 쓴다.
_DOC_BEGIN = "<!-- PROTECTED-LIST:START -->"
_DOC_END = "<!-- PROTECTED-LIST:END -->"

#: `DELETE FROM x` · `TRUNCATE TABLE x` · f-string 형태 `DELETE FROM {_TABLE}`.
_DELETE = re.compile(
    r"(?:DELETE\s+FROM|TRUNCATE\s+TABLE)\s+(\{?)([A-Za-z_][A-Za-z_0-9]*)\}?", re.I)

#: 표가 **선언되는** 두 표기. ★한쪽만 세면 반드시 빠진다★ — 이 저장소는
#: 이미 인덱스에서 같은 실수를 했다(`DATA_PLATFORM_SPEC.md` §2).
_CREATE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"'`]?(\{?)([A-Za-z_][A-Za-z_0-9]*)\}?",
    re.I)
_TABLENAME = re.compile(r"__tablename__\s*=\s*[\"']([A-Za-z_][A-Za-z_0-9]*)[\"']")

#: ★전체 교체 헬퍼는 테이블명을 인자로 받는다★ — 이름으로 막는다.
_BULK = re.compile(r"_bulk_refresh_table\s*\([^)]*?[\"']([A-Za-z_][A-Za-z_0-9]*)[\"']",
                   re.S)


# ═══════════════════════════════════════════════════════════════════════════
# 소스를 읽는 법 — 주석은 빼고, 상수는 풀어서
# ═══════════════════════════════════════════════════════════════════════════

def _code_lines(src: str) -> dict[int, str]:
    """주석을 **뺀** 줄. ★W 에서 트립와이어가 자기 설명 주석에 걸렸다★

    이 파일도 같은 위험이 있다 — 보호 표 이름을 **설명하는** 주석은 위반이 아니다.
    `tokenize` 가 주석을 정확히 알려 주므로 정규식으로 `#` 을 자르지 않는다
    (문자열 안의 `#` 에 속는다).
    """
    lines = dict(enumerate(src.splitlines(), 1))
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                row = tok.start[0]
                if row in lines:
                    lines[row] = lines[row].replace(tok.string, "")
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    return lines


def _module_constants(src: str) -> dict[str, str]:
    """모듈 최상위 `NAME = "문자열"`. ★`_TABLE` 을 실제 표 이름으로 푼다★"""
    out: dict[str, str] = {}
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return out
    for node in tree.body:
        targets: list[ast.Name] = []
        if isinstance(node, ast.Assign):
            targets = [t for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target]
        value = getattr(node, "value", None)
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            for t in targets:
                out[t.id] = value.value
    return out


def _deletion_sites_in(src: str) -> list[tuple[int, str, str | None]]:
    """`(줄, 소스에 적힌 이름, 풀린 표 이름 또는 None)`.

    `None` 은 ★이름을 알 수 없는 삭제★다 — 인자로 받은 테이블명처럼. 그것은
    따로 테스트한다(`test_only_the_known_helper_deletes_a_table_it_cannot_name`).
    """
    consts = _module_constants(src)
    sites = []
    for line_no, line in _code_lines(src).items():
        for m in _DELETE.finditer(line):
            braced, name = bool(m.group(1)), m.group(2)
            resolved = consts.get(name) if braced else name
            sites.append((line_no, name, resolved))
    return sites


def _source_files(*, include_declaration: bool = True) -> list[pathlib.Path]:
    out = [p for root in _ROOTS for p in root.rglob("*.py")]
    if not include_declaration:
        out = [p for p in out if p.name != _DECLARATION]
    return sorted(out)


def _declared_tables_in(src: str) -> set[str]:
    """`CREATE TABLE …` 과 `__tablename__` 둘 다에서 표 이름을 모은다.

    ★주석을 먼저 뺀다★ — `ohlcv_loader` 의 설명 주석이 `CREATE TABLE IF NOT
    EXISTS` 를 문장으로 적어 두어, 빼지 않으면 `IF` 라는 표가 있다고 믿는다
    (실제로 겪었다).
    """
    body = "\n".join(_code_lines(src).values())
    consts = _module_constants(src)
    out = set()
    for braced, name in _CREATE.findall(body):
        resolved = consts.get(name) if braced else name
        if resolved:
            out.add(resolved)
    out |= set(_TABLENAME.findall(body))
    return out


def _declared_tables() -> dict[str, str]:
    """표 이름 → 선언한 파일(먼저 만난 것)."""
    out: dict[str, str] = {}
    for path in _source_files():
        for t in sorted(_declared_tables_in(path.read_text(encoding="utf-8"))):
            out.setdefault(t, str(path))
    return out


def _all_deletion_sites() -> dict[str, list[tuple[int, str, str | None]]]:
    found = {}
    for path in _source_files():
        sites = _deletion_sites_in(path.read_text(encoding="utf-8"))
        if sites:
            found[str(path)] = sites
    return found


# ═══════════════════════════════════════════════════════════════════════════
# ① ★전수★ — 보호 표에는 삭제가 없다
# ═══════════════════════════════════════════════════════════════════════════

def test_no_deletion_on_protected_tables():
    """★지우면 되돌릴 수 없다★ 원천 빈티지와 감사 기록은 재수집되지 않는다."""
    bad = {path: [(n, t) for n, _raw, t in sites if t in PROTECTED]
           for path, sites in _all_deletion_sites().items()}
    bad = {k: v for k, v in bad.items() if v}
    assert not bad, (
        "보존 정책상 삭제가 금지된 표에 DELETE/TRUNCATE 가 생겼습니다 "
        f"(docs/specs/RETENTION_POLICY.md): {bad}")


def test_the_bulk_refresh_helper_is_never_pointed_at_a_protected_table():
    """★그 함수는 테이블명을 인자로 받는다★

    `screener_pipeline._bulk_refresh_table` 은 `TRUNCATE`(실패 시 `DELETE`) 후
    다시 채운다. 지금 호출부는 `market_snapshot_*` 둘뿐이라 안전하지만,
    `daily_prices` 를 넘기면 **그대로 지운다**. 이름으로 막는다.
    """
    bad = {}
    for path in _source_files():
        src = "\n".join(_code_lines(path.read_text(encoding="utf-8")).values())
        hits = [t for t in _BULK.findall(src) if t in PROTECTED]
        if hits:
            bad[str(path)] = hits
    assert not bad, f"보호 표를 전체 교체 헬퍼에 넘기는 곳: {bad}"


# ═══════════════════════════════════════════════════════════════════════════
# ② ★테스트의 테스트★ — 공허하지도, 오탐하지도 않는다
# ═══════════════════════════════════════════════════════════════════════════

def _protected_hits(src: str) -> list[str | None]:
    return [t for _n, _raw, t in _deletion_sites_in(src) if t in PROTECTED]


def test_the_guard_catches_a_literal_deletion():
    src = (
        'from sqlalchemy import text\n'
        'def purge(c):\n'
        '    c.execute(text("DELETE FROM daily_prices WHERE 1=1"))\n'
        '    c.execute(text("TRUNCATE TABLE macro_observations"))\n'
        '    c.execute(text("delete from financials_vintages"))\n')
    assert sorted(_protected_hits(src)) == [
        "daily_prices", "financials_vintages", "macro_observations"]


def test_the_guard_resolves_a_table_name_constant():
    """★가장 중요한 짝★ — 저장소의 삭제문 대부분이 이 모양이다.

    리터럴만 보는 가드는 이것을 **통과시킨다**. 그래서 이 테스트가 없으면
    ①은 거의 아무것도 막지 못한다.
    """
    src = ('_TABLE = "financials_vintages"\n'
           'def purge(c):\n'
           '    c.execute(text(f"DELETE FROM {_TABLE}"))\n')
    assert _protected_hits(src) == ["financials_vintages"], (
        "상수를 풀지 못했다 — 가드가 리터럴만 보고 있다")


def test_the_guard_ignores_an_unprotected_table():
    """★짝★ 결정 기록·재생성 가능 표는 지울 수 있다 — 막으면 기존 CRUD 가 깨진다."""
    src = ('_TABLE = "backtest_runs"\n'
           'def delete_run(c, i):\n'
           '    c.execute(text(f"DELETE FROM {_TABLE} WHERE id = :i"), {"i": i})\n'
           '    c.execute(text("DELETE FROM local_portfolio_state"))\n')
    assert _protected_hits(src) == []


def test_a_comment_mentioning_a_protected_table_is_not_a_violation():
    """★설명 주석은 위반이 아니다★ (W 에서 같은 오탐을 겪었다)"""
    src = ('# ★daily_prices 는 DELETE FROM daily_prices 를 하면 안 된다★\n'
           'X = 1  # TRUNCATE TABLE macro_observations 도 마찬가지다\n')
    assert _protected_hits(src) == [], "주석에 오탐했다"


def test_an_unresolvable_name_is_reported_as_unknown_not_as_safe():
    """★미상 ≠ 안전★ 이름을 못 풀면 `None` 으로 남기고 ⑥이 따로 센다."""
    src = ('def refresh(c, table_name):\n'
           '    c.execute(text(f"TRUNCATE TABLE {table_name}"))\n')
    assert [t for _n, _raw, t in _deletion_sites_in(src)] == [None]


def test_the_bulk_guard_catches_a_protected_argument():
    """④의 테스트의 테스트."""
    src = '_bulk_refresh_table(engine, "daily_prices", rows)\n'
    assert [t for t in _BULK.findall(src) if t in PROTECTED] == ["daily_prices"]


def test_the_scan_actually_reads_files():
    """★스캔이 빈 목록이면 ① 은 언제나 통과한다★"""
    assert len(_source_files()) > 50
    assert len(_all_deletion_sites()) >= 5, "삭제문을 하나도 못 찾았다 — 스캔이 죽었다"


# ═══════════════════════════════════════════════════════════════════════════
# ③ 삭제하는 표는 ★전부 분류돼 있어야 한다★
# ═══════════════════════════════════════════════════════════════════════════

def test_every_deletion_site_names_a_classified_table():
    """새 표를 지우는 코드가 생기면 **분류부터 하게** 만든다.

    분류되지 않은 표를 지우는 것은 "지워도 되는지 판단한 적이 없다" 는 뜻이다.
    """
    unclassified = {}
    for path, sites in _all_deletion_sites().items():
        hits = sorted({t for _n, _raw, t in sites if t and t not in CLASSIFIED})
        if hits:
            unclassified[path] = hits
    assert not unclassified, (
        "분류되지 않은 표를 지웁니다 — `src/data/retention.py` 에 부류와 사유를 "
        f"먼저 적으세요: {unclassified}")


def test_only_the_known_helper_deletes_a_table_it_cannot_name():
    """★이름을 모르는 삭제는 하나뿐이어야 한다★

    `_bulk_refresh_table` 은 테이블명을 인자로 받으므로 정적으로 풀 수 없다 —
    그래서 ④가 호출부를 따로 본다. **다른 곳에 같은 모양이 생기면** 그 가드가
    닿지 않으므로 여기서 먼저 잡는다.
    """
    unknown = sorted({path for path, sites in _all_deletion_sites().items()
                      if any(t is None for _n, _raw, t in sites)})
    assert unknown == ["src/screener_pipeline.py"], (
        "테이블명을 동적으로 받는 삭제가 새로 생겼습니다 — 호출부 가드를 "
        f"함께 넓히세요: {unknown}")


# ═══════════════════════════════════════════════════════════════════════════
# ④ ★선언된 표는 전부 분류돼 있다★ — 새 표가 생기면 보존 판단을 강제한다
# ═══════════════════════════════════════════════════════════════════════════

def test_every_declared_table_is_classified():
    """★인스턴스가 아니라 부류를 죽인다★

    삭제 코드가 생긴 **뒤에** 잡는 것보다, 표가 생길 때 한 줄 적게 하는 편이
    싸다. 계획은 알려진 표만 적으려 했는데 실측해 보니 ORM 쪽 여섯(`users`·
    `portfolios`·`trade_log`·`risk_snapshots`·`model_monitor_runs`·`stocks`)이
    통째로 빠져 있었다 — `CREATE TABLE` 만 세면 보이지 않는다.
    """
    declared = _declared_tables()
    missing = sorted((t, where) for t, where in declared.items()
                     if t not in CLASSIFIED)
    assert not missing, (
        "표는 선언됐는데 보존 분류가 없습니다 — `src/data/retention.py` 에 "
        f"부류와 사유를 적으세요: {missing}")


def test_every_classified_table_is_actually_declared():
    """★짝★ 반대 방향. 지어낸 이름이나 사라진 표가 분류에 남으면 정책이 낡는다."""
    stale = sorted(set(CLASSIFIED) - set(_declared_tables()))
    assert not stale, f"분류에는 있는데 선언이 없는 표: {stale}"


def test_the_declaration_scan_sees_both_spellings():
    """★한쪽 표기만 세면 반드시 빠진다★ (이 저장소가 인덱스에서 겪은 실수)"""
    ddl = _declared_tables_in('_T = "vin"\nDDL = "CREATE TABLE IF NOT EXISTS {_T} (a INT)"\n')
    assert ddl == {"vin"}, ddl
    orm = _declared_tables_in('class S(Base):\n    __tablename__ = "stocks"\n')
    assert orm == {"stocks"}, orm


def test_the_declaration_scan_ignores_prose_about_ddl():
    """`ohlcv_loader` 의 설명 주석이 실제로 `IF` 라는 표를 만들어 냈었다."""
    prose = '#: `ensure_table` 은 `CREATE TABLE IF NOT EXISTS` + ALTER 를 부른다\nX = 1\n'
    assert _declared_tables_in(prose) == set()


def test_the_declaration_scan_is_not_empty():
    """★공허 배제★ 수집이 죽으면 위 두 테스트가 언제나 통과한다."""
    declared = _declared_tables()
    assert len(declared) > 30, len(declared)
    for must in ("daily_prices", "users", "live_orders", "market_snapshot_equity"):
        assert must in declared, must


# ═══════════════════════════════════════════════════════════════════════════
# ⑤ 분류가 공허하지 않다
# ═══════════════════════════════════════════════════════════════════════════

def test_the_classification_is_not_empty():
    assert len(KEEP_FOREVER) >= 3, KEEP_FOREVER
    assert len(AUDIT) >= 4, AUDIT
    assert PROTECTED == set(KEEP_FOREVER) | set(AUDIT), PROTECTED
    assert set(CLASSIFIED) == (set(KEEP_FOREVER) | set(AUDIT) |
                               set(DECISION_RECORD) | set(REGENERABLE) |
                               set(USER_OWNED))


def _blob_outside_the_declaration() -> str:
    return "\n".join(p.read_text(encoding="utf-8")
                     for p in _source_files(include_declaration=False))


def test_every_classified_table_exists_in_the_code():
    """★지어낸 표 이름을 분류하지 않는다★ 선언 파일 **밖**에서 쓰여야 한다."""
    blob = _blob_outside_the_declaration()
    missing = sorted(t for t in CLASSIFIED
                     if not re.search(rf"\b{re.escape(t)}\b", blob))
    assert not missing, f"분류에는 있는데 코드에 없는 표: {missing}"


def test_the_existence_check_excludes_the_declaration_itself():
    """★없으면 위 테스트가 공허하다★ — 선언 파일에는 모든 이름이 적혀 있다."""
    assert "KEEP_FOREVER" not in _blob_outside_the_declaration(), (
        "선언 파일이 스캔에 섞여 들어가 존재 검사가 자기 자신을 보고 있다")


def test_no_table_is_in_two_classes():
    """★부류가 겹치면 판정이 갈린다★"""
    groups = [set(KEEP_FOREVER), set(AUDIT), set(DECISION_RECORD),
              set(REGENERABLE), set(USER_OWNED)]
    for i, a in enumerate(groups):
        for b in groups[i + 1:]:
            assert not (a & b), f"두 부류에 동시에 있다: {sorted(a & b)}"


def test_every_classified_table_carries_a_reason():
    """★사유 없는 분류는 다음 사람이 못 뒤집는다★"""
    thin = {t: why for t, why in CLASSIFIED.items() if len(why.strip()) < 30}
    assert not thin, f"사유가 너무 얇다(뒤집으려면 근거가 보여야 한다): {thin}"


# ═══════════════════════════════════════════════════════════════════════════
# ⑥ 문서와 코드가 ★같은 목록★ 을 본다
# ═══════════════════════════════════════════════════════════════════════════

def _doc() -> str:
    return _DOC.read_text(encoding="utf-8")


def test_the_document_names_every_classified_table():
    """문서가 코드보다 적게 적으면 읽는 사람이 빠진 표를 지운다."""
    doc = _doc()
    missing = sorted(t for t in CLASSIFIED if t not in doc)
    assert not missing, f"{_DOC} 에 빠진 표: {missing}"


def test_the_document_points_at_the_code_as_the_source():
    """★단일 출처를 이름으로 가리킨다★ 문서가 목록을 따로 들면 갈라진다."""
    assert "src/data/retention.py" in _doc(), "문서가 단일 출처를 가리키지 않는다"


def _doc_protected_list() -> set[str]:
    doc = _doc()
    start, end = doc.index(_DOC_BEGIN) + len(_DOC_BEGIN), doc.index(_DOC_END)
    return set(re.findall(r"`([a-z][a-z0-9_]*)`", doc[start:end]))


def test_the_document_protected_list_is_exactly_the_code_list():
    """★갈라지면 둘 다 틀린다★ 문서의 '지우면 안 되는 표' 구간과 코드를 대조한다."""
    in_doc = _doc_protected_list()
    assert in_doc == PROTECTED, {
        "문서에만": sorted(in_doc - PROTECTED),
        "코드에만": sorted(PROTECTED - in_doc),
    }


def test_the_doc_list_marker_is_not_empty():
    """★마커가 비면 위 테스트가 '빈 집합 == 빈 집합' 으로 통과한다★"""
    assert len(_doc_protected_list()) >= 6
