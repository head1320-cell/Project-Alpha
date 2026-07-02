"""유니버스 그룹 확장 — KRX 공식 상장 수 대응 (ST 외 리츠·외국주 등 포함, ETF/ETN/ELW 제외)."""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import src.data.stock_master as sm  # noqa: E402

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
    """합성 마스터 플래그 주입 — 파일 경로/전역 캐시를 임시로 대체."""
    monkeypatch.setattr(sm, "_master_flags_path", lambda: str(tmp_path / "flags.json"))
    sm.save_master_flags(SYMS)
    monkeypatch.setattr(sm, "_MASTER_FLAGS", None)  # 지연 로드 강제


def test_kospi_includes_reits_and_foreign(monkeypatch, tmp_path):
    _inject(monkeypatch, tmp_path)
    u = set(sm.build_master_universe("kospi"))
    assert u == {"100001", "100002", "100003", "100004"}  # RT/FS 포함, EF/EN 제외


def test_kosdaq_and_all_listed(monkeypatch, tmp_path):
    _inject(monkeypatch, tmp_path)
    assert set(sm.build_master_universe("kosdaq")) == {"200001", "200002"}
    assert len(sm.build_master_universe("all_listed")) == 6  # 2시장 합, ETF/ETN/ELW 제외


def test_etf_universe_unchanged(monkeypatch, tmp_path):
    _inject(monkeypatch, tmp_path)
    assert set(sm.build_master_universe("etf")) == {"100005", "100006"}


def test_master_composition(monkeypatch, tmp_path):
    _inject(monkeypatch, tmp_path)
    comp = sm.master_composition()
    assert comp["KOSPI"] == {"ST": 2, "RT": 1, "FS": 1, "EF": 1, "EN": 1}
    assert comp["KOSDAQ"] == {"ST": 2, "EW": 1}


def test_composition_empty_without_master(monkeypatch, tmp_path):
    monkeypatch.setattr(sm, "_master_flags_path", lambda: str(tmp_path / "none.json"))
    monkeypatch.setattr(sm, "_MASTER_FLAGS", None)
    assert sm.master_composition() == {}
