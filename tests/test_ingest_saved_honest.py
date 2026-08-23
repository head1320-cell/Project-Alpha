"""ingest_universe의 '저장' 카운터가 실제 ffl: 영속 증가분을 반영하는지 —
평가된 아이템 수(evaluated_actual)를 '저장'으로 보고해 '저장 2,349인데 유니버스 불변'
같은 오해를 유발하던 문제 수정."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import src.data.snapshot_db as sdb  # noqa: E402


def test_ingested_count_returns_int_safely():
    assert isinstance(sdb.ingested_count(), int) and sdb.ingested_count() >= 0


class _Res:
    total_evaluated = 3
    evaluated_actual = 3
    failures = 0


class _SC:
    def run(self, **k):
        return _Res()


def test_saved_reflects_ffl_delta_not_evaluated(monkeypatch):
    import src.engine.screener as scr
    monkeypatch.setattr(scr, "resolve_universe", lambda u: ["A", "B", "C"])
    monkeypatch.setattr(scr, "ValuationScreener", _SC)
    # ffl: 종목 수: 시작 10 → 청크 후 13 (3종목 새로 영속)
    seq = iter([10, 13])
    monkeypatch.setattr(sdb, "ingested_count", lambda: next(seq, 13))
    monkeypatch.setattr(sdb, "count", lambda: 999)

    r = sdb.ingest_universe(["A", "B", "C"])
    assert r["saved"] == 3          # 실제 새로 영속된 ffl: 종목 수
    assert r["evaluated"] == 3      # 평가 자체는 별도 필드로 보존


def test_saved_zero_when_no_new_persist(monkeypatch):
    """평가는 됐지만(evaluated 3) 실제 영속이 0이면 '저장 0' — 정직."""
    import src.engine.screener as scr
    monkeypatch.setattr(scr, "resolve_universe", lambda u: ["A", "B", "C"])
    monkeypatch.setattr(scr, "ValuationScreener", _SC)
    monkeypatch.setattr(sdb, "ingested_count", lambda: 884)   # 불변
    monkeypatch.setattr(sdb, "count", lambda: 999)

    r = sdb.ingest_universe(["A", "B", "C"])
    assert r["saved"] == 0 and r["evaluated"] == 3
