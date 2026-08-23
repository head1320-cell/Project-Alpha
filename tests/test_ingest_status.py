"""ingest_universe 진행 콜백 + DART 쿼터 조기 중단 — 적재가 '조용히 멈춤'을 없앤다."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import src.data.snapshot_db as sdb  # noqa: E402

CODES = [f"9101{i:02d}" for i in range(5)]  # 합성 5종목 (mock 결정론 평가)


def test_progress_cb_reports_done_total(monkeypatch):
    calls: list[tuple] = []
    r = sdb.ingest_universe(CODES, progress_cb=lambda d, t, s, f: calls.append((d, t, s, f)))
    assert calls and calls[-1][0] == 5 and calls[-1][1] == 5   # done/total 도달
    assert r["total"] == 5
    assert r["aborted"] is None
    assert r["saved"] + r["failures"] >= 0                     # 집계 필드 존재


def test_quota_exhausted_aborts_early(monkeypatch):
    import src.data.dart_client as dc
    monkeypatch.setattr(dc, "dart_usage", lambda: {"quota_exhausted": True})
    calls: list[tuple] = []
    r = sdb.ingest_universe(CODES, progress_cb=lambda *a: calls.append(a))
    assert r["aborted"] and "한도" in r["aborted"]              # 사유가 결과에 명시
    assert calls == []                                          # 청크 실행 전 중단
