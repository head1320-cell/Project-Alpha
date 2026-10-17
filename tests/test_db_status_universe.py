"""db-status universe_progress — 시장별 마스터 대비 적재 진행 (엔진 유무와 무관하게 키 존재)."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.api.data_routes import db_status  # noqa: E402


def test_universe_progress_key_present():
    out = db_status()
    up = out.get("universe_progress")
    assert isinstance(up, dict)
    assert "progress" in up and "composition" in up
    # 샌드박스(마스터 미적재): progress 는 빈 dict — 크래시 없이 정직
    for v in (up["progress"] or {}).values():
        assert set(v.keys()) == {"master", "ingested"}
