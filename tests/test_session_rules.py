"""장 운영 시각은 ★코드에 박지 않고 증거 파일에서 읽는다★ — `market_rules.session_rules` (분봉 백테스트 설계 W4a · a2).

정규장 시작·끝·종가 단일가 시작은 분봉 품질 검사(정규장 안/밖)와 분봉 백테스트(단일가 구간 진입 마감)가 쓴다.
근거는 보도·증권사 안내(T1)이고 거래소 원문은 보지 못했다 — 그래서 값과 함께 등급·출처가 나가고,
파일을 읽지 못하면 ★시각을 지어내지 않고★ 값 없음 + 사유가 나간다.
"""
from __future__ import annotations

import json

import pytest

import src.data.market_rules as mr


def write_rules(tmp_path, monkeypatch, **changes) -> dict:
    doc = json.loads(mr.SESSION_RULES_EVIDENCE_PATH.read_text(encoding="utf-8"))
    for dotted, value in changes.items():
        node = doc
        *parents, leaf = dotted.split("__")
        for key in parents:
            node = node[key]
        node[leaf] = value
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("SESSION_RULES_EVIDENCE_PATH", str(path))
    return doc


def test_the_checked_in_file_gives_the_regular_session_with_grade_and_sources():
    out = mr.session_rules()
    assert out["available"] is True and out["reason"] is None
    assert (out["open"], out["closing_auction_from"], out["close"]) == ("0900", "1520", "1530")
    assert out["grade"] == "T1"
    assert out["sources"] and all(s["title"] and s["url"].startswith("https://") for s in out["sources"])


def test_the_times_come_from_the_file_not_from_the_code(tmp_path, monkeypatch):
    """짝 — 파일의 시각을 바꾸면 답이 따라 바뀐다(상수로 박은 구현을 배제한다)."""
    write_rules(tmp_path, monkeypatch, regular_session__open="10:00", regular_session__close="16:30",
                regular_session__closing_auction_from="16:20")
    out = mr.session_rules()
    assert (out["open"], out["closing_auction_from"], out["close"]) == ("1000", "1620", "1630")


def test_without_the_file_there_are_no_times_only_a_reason(tmp_path, monkeypatch):
    monkeypatch.setenv("SESSION_RULES_EVIDENCE_PATH", str(tmp_path / "missing.json"))
    out = mr.session_rules()
    assert out["available"] is False
    assert (out["open"], out["closing_auction_from"], out["close"]) == (None, None, None)
    assert out["reason"] == "no_evidence_file" and out["message"].endswith("니다.")


@pytest.mark.parametrize("field", ["open", "close", "closing_auction_from"])
def test_an_unreadable_time_is_refused_rather_than_guessed(tmp_path, monkeypatch, field):
    write_rules(tmp_path, monkeypatch, **{f"regular_session__{field}": "9시"})
    out = mr.session_rules()
    assert out["available"] is False and out["reason"] == "bad_rules"
    assert out["open"] is None and out["close"] is None


def test_times_out_of_order_are_refused(tmp_path, monkeypatch):
    write_rules(tmp_path, monkeypatch, regular_session__closing_auction_from="15:40")     # 폐장 뒤의 단일가 시작
    assert mr.session_rules()["reason"] == "bad_rules"


def test_a_row_below_the_grade_floor_is_not_applied(tmp_path, monkeypatch):
    write_rules(tmp_path, monkeypatch, min_grade_to_apply="T2")
    out = mr.session_rules()
    assert out["available"] is False and out["reason"] == "below_grade_floor"
    assert out["grade"] == "T1" and out["open"] is None


def test_what_the_file_does_not_know_is_passed_on_with_reasons():
    out = mr.session_rules()
    assert out["special_days"]["dates"] is None and out["special_days"]["dates_reason"]
    assert len(out["unknown"]) >= 3 and all(u["what"] and u["reason"] for u in out["unknown"])


def test_every_source_the_file_cites_exists():
    doc = json.loads(mr.SESSION_RULES_EVIDENCE_PATH.read_text(encoding="utf-8"))
    cited = set(doc["regular_session"]["sources"]) | set(doc["special_days"]["sources"])
    for row in doc["unknown"]:
        cited |= set(row["sources"])
    assert cited <= set(doc["sources"])
    assert doc["regular_session"]["grade"] in doc["grades"] and doc["min_grade_to_apply"] in doc["grades"]
