"""factors 적재 유니버스 dedup — 지수 유니버스가 all_listed와 겹쳐 종목이 두 번
평가되던 낭비 제거. 지수 먼저(빠른 부분 가용) + all_listed는 남은 종목만."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")


def test_factors_ingest_dedups_codes(monkeypatch):
    import src.data.snapshot_db as sdb
    import src.engine.screener as scr

    universes = {"kospi200": ["A", "B"], "kosdaq150": ["C"], "all_listed": ["A", "B", "C", "D", "E"]}
    monkeypatch.setattr(scr, "resolve_universe", lambda u: list(universes.get(u, [])))

    seen_calls: list[list[str]] = []

    def fake_ingest(codes, progress_cb=None):
        seen_calls.append(list(codes))
        return {"universe": codes, "saved": len(codes), "failures": 0,
                "total": len(codes), "aborted": None}

    monkeypatch.setattr(sdb, "ingest_universe", fake_ingest)

    from src.api.data_routes import _ingest_run
    _ingest_run("factors")

    flat = [c for call in seen_calls for c in call]
    assert sorted(flat) == ["A", "B", "C", "D", "E"]   # 각 코드 정확히 1회 (합집합 = 전종목)
    assert len(flat) == len(set(flat))                 # 중복 평가 0
    assert seen_calls[0] == ["A", "B"]                 # 지수 유니버스 먼저(부분 가용)
