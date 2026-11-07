"""통합 DB 점검 + 적재 트리거 엔드포인트 — 구조/응답 계약 (데이터·키 유무와 무관히 200)."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from fastapi.testclient import TestClient  # noqa: E402
from main_api import app  # noqa: E402

c = TestClient(app)


def test_db_status_structure():
    r = c.get("/api/v1/data/db-status")
    assert r.status_code == 200
    j = r.json()
    assert "config" in j and "tables" in j and "tools" in j
    assert set(j["config"]) >= {"kis_real", "dart_key", "krx_key", "bok_key", "fred_key"}
    assert "ingest_running" in j


def test_ingest_target_responds():
    # KRX 미설정(샌드박스) → 스레드 즉시 no-op. 엔드포인트는 started 리스트 반환.
    r = c.post("/api/v1/data/ingest/index")
    assert r.status_code == 200
    assert isinstance(r.json().get("started"), list)


def test_ingest_unknown_target_404():
    r = c.post("/api/v1/data/ingest/bogus")
    assert r.status_code == 404


# ── 재무 PIT 준비상태 — ★추정과 실측을 한 칸에 넣지 않는다★ (V4) ──────────────
#
# `"PIT 펀더멘털": financials_history rows > 0` 은 **추정 시차 표**를 근거로
# *PIT* 능력을 주장했다. V4 이후 실측 접수일 경로가 생겼으므로 둘을 가른다.
# 그리고 이 화면은 `measured_pct` 가 0 인 이유를 사용자가 찾으러 오는 자리다.

def _roster() -> dict:
    return c.get("/api/v1/data/db-status").json()["tools"]


def test_the_readiness_roster_distinguishes_estimated_from_measured_pit():
    """추정 시차 기반과 실측 접수일 기반이 다른 항목이다."""
    keys = set(_roster())
    assert "PIT 펀더멘털" not in keys, "옛 이름이 남아 둘을 뭉갠다"
    assert "PIT 펀더멘털(추정 시차)" in keys, keys


def test_every_readiness_value_stays_a_boolean():
    """★프런트가 `Object.values(tools).filter(Boolean)` 로 센다★

    (`DbStatusPanel.tsx:114`) 문자열 3-상태를 넣으면 `"unknown"` 이 **준비됨**으로
    세어진다. 미상은 여기가 아니라 `tables.financials_vintages` 가 든다.
    """
    for k, v in _roster().items():
        assert isinstance(v, bool), f"{k} 가 불리언이 아니다: {v!r}"


def test_an_unreadable_vintage_table_does_not_become_a_false_readiness():
    """★미상 ≠ 미준비★ 못 읽었으면 항목을 만들지 않는다 — 사유는 tables 에 있다.

    `False` 로 적으면 "확인했더니 없다" 로 읽힌다. 이 컨테이너에는 DB 가 없어
    빈티지 현황이 `rows: None` 이므로, 그 상태가 실제로 이 규칙을 타는지 본다.
    """
    j = c.get("/api/v1/data/db-status").json()
    vs = j["tables"].get("financials_vintages")
    if vs is None or vs.get("rows") is not None:
        import pytest
        pytest.skip("빈티지 현황을 읽을 수 있는 환경 — 이 규칙은 못 읽을 때의 것이다")
    assert "PIT 펀더멘털(실측 접수일)" not in j["tools"], j["tools"]
    assert vs.get("reason"), "못 읽었는데 사유가 없다"


def test_the_registry_and_the_roster_use_the_same_tool_name():
    """★이름이 두 곳에 있다★ 한쪽만 바꾸면 두 로스터가 갈라진다.

    `ingest_registry` 의 `tools` 는 `DbStatusPanel.tsx:289` 가 그대로 그린다.
    """
    from src.data.ingest_registry import DATASETS
    named = {t for d in DATASETS for t in d.tools}
    roster = set(_roster())
    assert "PIT 펀더멘털" not in named, "레지스트리에 옛 이름이 남아 있다"
    missing = {t for t in named if t.startswith("PIT 펀더멘털")} - roster
    assert not missing, f"레지스트리가 부르는 이름이 로스터에 없다: {missing}"
