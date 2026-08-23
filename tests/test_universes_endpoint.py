"""GET /universes — 마스터 적재 시 실크기, 미적재 시 프리셋 폴백 (199/130 분모 버그 수정 검증)."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import src.data.stock_master as sm  # noqa: E402
from src.api.screener_routes import screener_universes  # noqa: E402

# 합성 마스터 (test_universe_groups.py와 동일 데이터 — 테스트 파일 간 import 없이 자립)
SYMS = [
    {"ticker": "100001", "name": "코스피보통주", "market": "KOSPI", "group_code": "ST"},
    {"ticker": "100002", "name": "코스피우선주", "market": "KOSPI", "group_code": "ST"},
    {"ticker": "100003", "name": "코스피리츠",   "market": "KOSPI", "group_code": "RT"},
    {"ticker": "100004", "name": "코스피외국주", "market": "KOSPI", "group_code": "FS"},
    {"ticker": "100005", "name": "코스피ETF",   "market": "KOSPI", "group_code": "EF", "is_etf": True},
    {"ticker": "100006", "name": "코스피ETN",   "market": "KOSPI", "group_code": "EN"},
    {"ticker": "200001", "name": "코스닥주권",   "market": "KOSDAQ", "group_code": "ST"},
    {"ticker": "200002", "name": "코스닥스팩",   "market": "KOSDAQ", "group_code": "ST"},
    {"ticker": "200003", "name": "코스닥ELW",   "market": "KOSDAQ", "group_code": "EW"},
]


def _inject(monkeypatch, tmp_path):
    monkeypatch.setattr(sm, "_master_flags_path", lambda: str(tmp_path / "flags.json"))
    sm.save_master_flags(SYMS)
    monkeypatch.setattr(sm, "_MASTER_FLAGS", None)


def _sizes() -> dict:
    d = screener_universes()
    return {p["id"]: p["size"] for p in d["presets"]}


def test_fallback_to_presets_without_master(monkeypatch, tmp_path):
    monkeypatch.setattr(sm, "_master_flags_path", lambda: str(tmp_path / "none.json"))
    monkeypatch.setattr(sm, "_MASTER_FLAGS", None)
    sizes = _sizes()
    assert sizes["kospi200"] == 130          # 하드코딩 프리셋 폴백 (샌드박스 = 마스터 없음)
    assert "kospi" not in sizes              # 마스터 없으면 시장 전체 항목 미노출


def test_master_aware_sizes(monkeypatch, tmp_path):
    _inject(monkeypatch, tmp_path)
    sizes = _sizes()
    assert sizes["kospi"] == 4               # ST2+RT1+FS1 (합성 마스터)
    assert sizes["kosdaq"] == 2
    assert sizes["all_listed"] == 6
    assert sizes["etf"] == 2                 # EF+EN — 프리셋 40 대신 마스터 실크기
