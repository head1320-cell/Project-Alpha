"""Phase 7 step 5 — timing_rule_sets 버전화 + 런 재현성.

왜 카운터만으로는 부족한가
──────────────────────────────────────────────────────────────────────────────
스펙 §4 는 rule version 을 **"재현성 ID"** 로 분류한다(데이터 스냅샷·엔진 버전과 나란히).
그런데 버전 번호만 올리고 내용을 제자리에서 덮어쓰면, 런이 "규칙 v2 로 계산했다" 고
기록해도 v2 의 **내용은 이미 사라져 있다**. 그러면 재열기는 복원이 아니라 추측이 된다.
그래서 버전별 내용을 불변 행으로 남기고, 런은 그 (set_id, version) 을 가리킨다.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from src.data import timing_rules as tr


@pytest.fixture(autouse=True)
def _db(monkeypatch):
    """in-memory SQLite 로 격리 — tests/test_research_run_snapshot_link.py 와 같은 방식.

    `_inited` 를 내려야 _ensure 가 다시 돌아 ALTER/검증 경로를 지난다.
    """
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    monkeypatch.setattr(tr, "_engine", lambda: eng)
    monkeypatch.setattr(tr, "_inited", False)
    monkeypatch.setattr(tr, "_has_version", False)
    yield eng
    eng.dispose()


def _save(name="세트", rules=None, **kw):
    return tr.save_rule_set(name, "kr", rules if rules is not None else [{"factor_id": "curve_slope"}], **kw)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. 버전 부여
# ═══════════════════════════════════════════════════════════════════════════════
def test_new_rule_set_starts_at_version_1():
    sid = _save()
    assert sid, "DB 미가용이면 이 테스트는 의미가 없다"
    assert tr.get_rule_set(sid)["version"] == 1


def test_updating_a_rule_set_bumps_the_version():
    sid = _save(rules=[{"factor_id": "curve_slope"}])
    assert tr.save_rule_set("세트", "kr", [{"factor_id": "avg_abs_momentum"}], set_id=sid) == sid
    assert tr.get_rule_set(sid)["version"] == 2
    assert tr.save_rule_set("세트", "kr", [{"factor_id": "disparity"}], set_id=sid) == sid
    assert tr.get_rule_set(sid)["version"] == 3


def test_versions_are_monotonic_per_set_not_global():
    """세트마다 독립 카운터 — 다른 세트를 저장해도 내 버전이 뛰지 않는다."""
    a = _save("A")
    b = _save("B")
    tr.save_rule_set("B", "kr", [{"factor_id": "disparity"}], set_id=b)
    tr.save_rule_set("B", "kr", [{"factor_id": "vol_breakout"}], set_id=b)
    assert tr.get_rule_set(a)["version"] == 1
    assert tr.get_rule_set(b)["version"] == 3


def test_list_rule_sets_exposes_the_version():
    sid = _save("목록용")
    got = [s for s in tr.list_rule_sets(limit=200) if s["set_id"] == sid]
    assert got and got[0]["version"] == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 2. ★버전 내용의 불변 보존★ — 재현성의 핵심
# ═══════════════════════════════════════════════════════════════════════════════
def test_an_old_version_is_still_retrievable_after_an_update():
    """v1 로 계산한 런을 열었을 때 v1 의 규칙을 그대로 복원할 수 있어야 한다."""
    sid = _save(rules=[{"factor_id": "curve_slope", "params": {"series_id": "T10Y2Y"}}])
    tr.save_rule_set("세트", "kr", [{"factor_id": "avg_abs_momentum"}], set_id=sid)

    v1 = tr.get_rule_set_version(sid, 1)
    assert v1 is not None, "v1 이 사라지면 런의 rule version 은 재현성 ID 가 아니다"
    assert v1["rules"] == [{"factor_id": "curve_slope", "params": {"series_id": "T10Y2Y"}}]
    assert v1["version"] == 1

    v2 = tr.get_rule_set_version(sid, 2)
    assert v2["rules"] == [{"factor_id": "avg_abs_momentum"}]


def test_old_version_survives_many_updates():
    sid = _save(rules=[{"factor_id": "curve_slope"}])
    for fid in ("disparity", "vol_breakout", "channel_breakout"):
        tr.save_rule_set("세트", "kr", [{"factor_id": fid}], set_id=sid)
    assert tr.get_rule_set(sid)["version"] == 4
    assert tr.get_rule_set_version(sid, 1)["rules"] == [{"factor_id": "curve_slope"}]
    assert tr.get_rule_set_version(sid, 3)["rules"] == [{"factor_id": "vol_breakout"}]


def test_unknown_version_is_none_not_a_silent_fallback():
    """★없는 버전에 최신본을 돌려주면 조용히 틀린 규칙으로 런을 복원한다★"""
    sid = _save()
    assert tr.get_rule_set_version(sid, 99) is None
    assert tr.get_rule_set_version("tr_nope", 1) is None


def test_list_versions_is_ordered_and_complete():
    sid = _save(rules=[{"factor_id": "curve_slope"}])
    tr.save_rule_set("세트", "kr", [{"factor_id": "disparity"}], set_id=sid)
    vs = tr.list_rule_set_versions(sid)
    assert [v["version"] for v in vs] == [1, 2]


def test_deleting_a_set_removes_its_version_history():
    """세트를 지우면 이력도 함께 사라진다 — 고아 이력이 남으면 삭제가 삭제가 아니다."""
    sid = _save()
    tr.save_rule_set("세트", "kr", [{"factor_id": "disparity"}], set_id=sid)
    assert tr.delete_rule_set(sid) is True
    assert tr.get_rule_set_version(sid, 1) is None
    assert tr.list_rule_set_versions(sid) == []


def test_updating_a_missing_set_creates_no_version_row():
    """존재하지 않는 set_id 갱신은 실패(None)이고, 이력도 남기지 않는다."""
    assert tr.save_rule_set("없음", "kr", [], set_id="tr_missing_xyz") is None
    assert tr.list_rule_set_versions("tr_missing_xyz") == []


# ═══════════════════════════════════════════════════════════════════════════════
# 3. verify-and-degrade — ALTER 가 실패해도 조회 전체가 깨지지 않는다
# ═══════════════════════════════════════════════════════════════════════════════
def test_reads_still_work_when_the_version_column_is_unavailable(monkeypatch):
    """★backtest_runs.py:104~122 패턴★ ALTER 가 안 붙었는데 SELECT 가 그 열을 참조하면
    규칙 세트 조회가 통째로 깨진다(수정 전보다 나쁨). 버전 기능만 끄고 나머지는 살린다."""
    sid = _save("degrade")
    assert sid
    monkeypatch.setattr(tr, "_has_version", False)
    got = tr.get_rule_set(sid)
    assert got is not None, "버전 열이 없어도 세트 조회는 살아 있어야 한다"
    assert got["name"] == "degrade"
    assert got["version"] is None, "모르는 값을 1 로 지어내지 않는다"
    assert tr.list_rule_sets(limit=200) != []


# ═══════════════════════════════════════════════════════════════════════════════
# HTTP 표면 (Phase 7c) — 룰셋 신원을 화면이 정직하게 그릴 수 있으려면 필요한 두 가지
# ═══════════════════════════════════════════════════════════════════════════════
def _client():
    from fastapi.testclient import TestClient

    from src.app_factory import create_app
    return TestClient(create_app())


def test_save_returns_the_version_it_wrote():
    """★저장 응답에 버전이 없으면 호출자가 재현 좌표를 들 수 없다★

    id 만으로는 "어떤 룰이었는지" 를 지목하지 못한다 — 룰셋은 갱신될 수 있기 때문이다.
    """
    with _client() as c:
        r = c.post("/api/v1/allocation/timing-rules", json={
            "name": "t", "market": "kr",
            "rules": [{"factor_id": "avg_abs_momentum", "universe": ["SPY"]}]})
        assert r.status_code == 200, r.text
        body = r.json()
        assert "version" in body, "저장 응답에 버전이 없다"
        assert body["version"] == 1 or body["version"] is None


def test_a_degraded_version_column_reports_none_not_one(monkeypatch):
    """버전 열을 못 쓰는 DB 에서는 버전이 **None** 이어야 한다 — 1 로 지어내지 않는다.

    ★픽스처에서 `_has_version=False` 로 두는 것으로는 이 경로가 재현되지 않는다★
    `_ensure()` 가 테이블을 version 열까지 포함해 새로 만들고 그 플래그를 True 로 되돌린다.
    (같은 함정을 regime_snapshots 픽스처에서도 겪었다 — 초기화 함수가 플래그를 다시 쓴다면
    픽스처가 미리 내려 둔 값은 아무 의미가 없다.) 그래서 초기화가 끝난 **뒤에** 내린다.
    """
    sid = tr.save_rule_set("t", "kr", [{"factor_id": "disparity"}])
    assert sid and tr.get_rule_set(sid)["version"] == 1     # 정상 경로
    monkeypatch.setattr(tr, "_has_version", False)          # 이제 열을 못 쓴다고 치자
    assert tr.get_rule_set(sid)["version"] is None, "버전을 모르는데 1 이라고 답했다"


def test_versions_endpoint_lists_only_versions_that_exist():
    """없는 세트는 빈 목록 — 현재 버전으로 대신 채우지 않는다."""
    with _client() as c:
        r = c.get("/api/v1/allocation/timing-rules/tr_does_not_exist/versions")
        assert r.status_code == 200, r.text
        assert r.json()["versions"] == []


def test_updating_a_deleted_rule_set_says_so_instead_of_blaming_the_database():
    """★두 실패를 같은 말로 보고하지 않는다★

    `save_rule_set` 은 "갱신할 세트가 없다" 와 "저장소를 못 쓴다" 를 똑같이 None 으로 준다.
    둘 다 503 으로 보고하면, 룰셋이 삭제된 사용자는 **고칠 수 있는 문제**를 인프라 장애로
    오해하고 그대로 막힌다(그리고 이 경로는 실제로 막혔다 — 갱신 실패 → 복구 수단 없음).
    """
    with _client() as c:
        r = c.post("/api/v1/allocation/timing-rules", json={
            "name": "t", "market": "kr", "set_id": "tr_gone",
            "rules": [{"factor_id": "disparity", "universe": ["SPY"]}]})
        assert r.status_code == 422, f"{r.status_code}: {r.text}"
        assert "tr_gone" in r.text and "찾을 수 없습니다" in r.text
