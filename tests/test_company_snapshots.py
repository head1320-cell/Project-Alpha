"""CompanySnapshot 저장소 계약 (P2-1 커밋 ①)

이 그릇이 메우는 구멍: Company 탭은 매번 다시 계산하고, 어떤 가정·어떤 시점의 재무로
그 판단이 나왔는지 남지 않는다. 남은 언더라이팅 업그레이드 넷(역DCF·확률 밸류에이션·
매크로 민감도·논지)은 전부 **저장할 곳이 없어서** 못 얹힌다.

관례: in-memory SQLite + monkeypatch (실DB·실네트워크 0) — `test_regime_snapshots.py`
와 동일.

핵심 주장:
  create/get   — snapshot_id 발급, 섹션 왕복 보존
  ★열 매핑★    — 섹션이 **자기 값**을 읽는다(이웃 열을 읽지 않는다)
  불변성        — 갱신 경로가 **없다**. 같은 종목을 다시 굳히면 새 ID 가 나온다
  정직성        — DB 미가용 시 `None`/`[]`, `None` 섹션과 빈 섹션을 구분
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import src.data.company_snapshots as cs  # noqa: E402

CODE = "005930"
AS_OF = "2026-08-22"


@pytest.fixture
def mem_cs(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    monkeypatch.setattr(cs, "_engine", lambda: eng)
    monkeypatch.setattr(cs, "_inited", False)
    yield eng
    eng.dispose()


def _create(**kw) -> str | None:
    body = {
        "code": CODE, "as_of": AS_OF, "price": 71000.0, "price_source": "caller",
        "data_status": "mock", "research_usage": "forward_only",
    }
    body.update(kw)
    return cs.create_snapshot(**body)


# ── 1. 왕복 ─────────────────────────────────────────────────────────────────
def test_create_and_get_roundtrip(mem_cs):
    sid = _create(quality={"roic_wacc": {"spread_pct": 3.2}},
                  valuation={"intrinsic_value": 83000, "verdict": "저평가"})
    assert sid and sid.startswith("cs_")

    got = cs.get_snapshot(sid)
    assert got is not None
    assert got["code"] == CODE and got["as_of"] == AS_OF
    assert got["price"] == 71000.0 and got["price_source"] == "caller"
    assert got["research_usage"] == "forward_only"
    assert got["quality"]["roic_wacc"]["spread_pct"] == 3.2
    assert got["valuation"]["verdict"] == "저평가"
    # 재현 좌표가 서버에서 스탬프된다 — 클라이언트가 주장하지 않는다.
    assert got["model_version"] == cs.MODEL_VERSION
    assert got["engine_version"] == cs.ENGINE_VERSION
    assert got["snapshot_version"] == cs.SNAPSHOT_VERSION
    assert got["code_version"]


def test_a_missing_snapshot_is_none_not_an_empty_shell(mem_cs):
    assert cs.get_snapshot("cs_nope") is None


# ── 2. ★열 매핑★ 섹션이 이웃 열을 읽지 않는다 ───────────────────────────────
def test_every_section_reads_back_its_own_value(mem_cs):
    """섹션마다 **구분 가능한** 값을 넣고 각자가 자기 값을 읽는지 본다.

    ★이 테스트가 지키는 것은 INSERT 의 열 목록과 바인딩 이름이 **짝을 유지하는가**다★
    처음에는 "위치 인덱스 함정(M1-S)" 을 막는다고 적었는데, 프로브로 재 보니 아니었다 —
    `_col_list()` 하나가 SELECT 문과 `zip` 을 **둘 다** 만들기 때문에 그 목록을 뒤집어도
    양쪽이 함께 뒤집혀 매핑이 그대로 맞는다(구조적으로 못 어긋난다). 실제로 빨개지는
    프로브는 `create_snapshot` 의 `cols` 만 뒤집는 것, 즉 열 목록과 `:name` 바인딩이
    갈라지는 경우다. 가드는 진짜였고 **가드에 붙인 설명이 틀렸다.**
    """
    marked = {s: {"marker": s} for s in cs._SECTIONS}
    sid = _create(**marked)
    got = cs.get_snapshot(sid)
    for s in cs._SECTIONS:
        assert got[s] == {"marker": s}, f"{s} 가 다른 열을 읽었다: {got[s]}"


def test_the_column_list_covers_every_stored_section(mem_cs):
    assert set(cs._SECTIONS) <= set(cs._col_list())
    # SELECT 문과 이름 목록이 같은 출처에서 나온다.
    assert cs._cols() == ", ".join(cs._col_list())


# ── 3. ★불변★ 갱신 경로가 없다 ──────────────────────────────────────────────
def test_the_module_offers_no_update_path():
    """불변식을 주석이 아니라 **공개 API 의 모양**으로 강제한다.

    재무가 정정되었다면 그것은 새로운 사실이지 기존 기록의 수정이 아니다.
    """
    mutators = [n for n in dir(cs)
                if n.startswith(("update_", "set_", "patch_", "edit_"))]
    assert mutators == [], f"갱신 경로가 생겼다: {mutators}"


def test_snapshotting_the_same_code_twice_yields_two_records(mem_cs):
    a = _create(quality={"v": 1})
    b = _create(quality={"v": 2})
    assert a != b
    # 첫 스냅샷이 덮이지 않는다 — 두 시점의 판단이 나란히 남는다.
    assert cs.get_snapshot(a)["quality"] == {"v": 1}
    assert cs.get_snapshot(b)["quality"] == {"v": 2}


def test_delete_is_the_only_way_to_remove(mem_cs):
    sid = _create()
    assert cs.delete_snapshot(sid) is True
    assert cs.get_snapshot(sid) is None
    assert cs.delete_snapshot(sid) is False


# ── 4. 목록 — 큰 섹션을 빼고 요약만 ─────────────────────────────────────────
def test_list_is_newest_first_and_omits_the_bulky_sections(mem_cs):
    old = _create(financials=[{"year": 2024}], quality={"a": 1})
    new = _create(financials=[{"year": 2025}])
    # created_at 이 같은 초에 들어갈 수 있으므로 정렬 기준을 명시적으로 벌린다.
    with mem_cs.begin() as c:
        c.execute(text("UPDATE company_snapshots SET created_at = 1 WHERE snapshot_id = :s"),
                  {"s": old})

    rows = cs.list_snapshots()
    assert [r["snapshot_id"] for r in rows] == [new, old]
    # ★페이로드 비대 방지★ 목록은 섹션 본문을 주지 않고 **담겼는지**만 말한다.
    assert "financials" not in rows[0]
    assert rows[0]["sections_present"] == ["financials"]
    assert rows[1]["sections_present"] == ["financials", "quality"]


def test_list_can_be_scoped_to_one_code(mem_cs):
    mine = _create()
    _create(code="000660")
    rows = cs.list_snapshots(code=CODE)
    assert [r["snapshot_id"] for r in rows] == [mine]


# ── 5. 정직성 — 담지 않은 섹션과 빈 섹션은 다른 사실 ────────────────────────
def test_an_unstored_section_is_none_not_an_empty_dict(mem_cs):
    """`None` = 굳히지 않았다 · `{}` = 계산했는데 비었다. 뭉치면 호출부가 재계산한다."""
    sid = _create(quality={}, risk=None)
    got = cs.get_snapshot(sid)
    assert got["quality"] == {}
    assert got["risk"] is None


def test_a_dead_database_answers_quietly_instead_of_faking_a_snapshot(monkeypatch):
    """앱은 계속 돌고, 정직 보고는 API 가 한다 — 가짜 스냅샷을 지어내지 않는다."""
    def _boom():
        raise RuntimeError("DB 없음")
    monkeypatch.setattr(cs, "_engine", _boom)
    monkeypatch.setattr(cs, "_inited", False)

    assert _create() is None
    assert cs.get_snapshot("cs_x") is None
    assert cs.list_snapshots() == []
    assert cs.delete_snapshot("cs_x") is False


def test_a_changed_database_url_reinitialises_the_table(monkeypatch, tmp_path):
    """★`_inited` 만 보면 DB 가 바뀌었을 때 INSERT 가 'no such table' 로 죽는다★

    `regime_snapshots` 가 실측으로 겪은 결함이고, `_inited_for` 가 그 방어다.

    ★가드가 보는 것은 엔진이 아니라 **URL 문자열**이다★ 처음에는 in-memory 엔진 둘로
    이 테스트를 짰는데, 둘 다 URL 이 `sqlite://` 라 가드가 전환을 못 보고 red 였다.
    가드의 결함이 아니라 테스트의 결함이다 — 이 가드가 막으려는 것은 `DATABASE_URL`
    이 바뀌는 경우이고 그때는 문자열이 실제로 달라진다. 그래서 **파일 DB 둘**로 잰다.
    (같은 URL 의 서로 다른 엔진은 여전히 구분하지 못한다. `regime_snapshots` 도
    마찬가지이고, 두 저장소를 갈라 놓으면서까지 강화할 이유가 없다.)
    """
    first = create_engine(f"sqlite:///{tmp_path / 'a.db'}")
    second = create_engine(f"sqlite:///{tmp_path / 'b.db'}")
    try:
        monkeypatch.setattr(cs, "_engine", lambda: first)
        monkeypatch.setattr(cs, "_inited", False)
        monkeypatch.setattr(cs, "_inited_for", None)
        assert _create() is not None

        # 같은 프로세스에서 다른 DB 로 갈아탄다 — 표가 없으므로 다시 만들어야 한다.
        monkeypatch.setattr(cs, "_engine", lambda: second)
        assert _create() is not None
    finally:
        first.dispose()
        second.dispose()
