"""AS2 · ★표의 자리★ — 관측은 뜻을 주지 않는다
==============================================================================
대상: `src/domain/kis_rt_cd.py` · 증거 파일 `docs/specs/kis-rt-cd-evidence.json`

## 이 모듈이 지키는 한 가지

★코드를 100번 본다고 그 뜻을 알게 되지 않는다.★ 그래서 등급을 하나로 두되
**관측 등급(`K1`)이 적용선 아래**에 있게 한다 — 수집기가 아무리 돌아도 책임
소재는 사람이 문서를 보고 `K2` 이상으로 적기 전까지 `unknown` 이다.

`src/data/source_registry.py` 와 `docs/specs/ecos-frequency-evidence.json` 의
관계를 그대로 잇는다: 사실은 파이썬에, **그 사실의 증거**는 체크인된 JSON 에,
그리고 ★확신이 모자라면 적용하지 않는다★.

## ★여기서 재지 않는 것★

- **코드의 뜻을 재지 않는다.** 표가 비어 있고, 비어 있는 것이 정직한 상태다.
- **`msg1` 을 해석하지 않는다.** 문구 패턴 매칭은 ★어휘로 걸기★다(AR 이 거부).
"""
from __future__ import annotations

import ast
import json
import pathlib

import pytest

from src.domain.kis_failure import FAULT_PROVIDER, FAULT_SELF, FAULT_UNKNOWN
from src.domain.kis_rt_cd import (
    CODE_GRADES,
    DEFAULT_MIN_GRADE,
    EVIDENCE_PATH,
    OBSERVED_GRADE,
    code_key,
    enriched_label,
    fault_from_table,
    fold_observations,
    gap_list,
    load_evidence,
    meaning_of,
    table_summary,
)

_MODULE = pathlib.Path("src/domain/kis_rt_cd.py")


def _write_evidence(tmp_path, monkeypatch, codes, *, floor=DEFAULT_MIN_GRADE):
    doc = {"schema": 1, "min_grade_to_apply": floor, "why_empty": "테스트",
           "codes": codes}
    p = tmp_path / "ev.json"
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("KIS_RT_CD_EVIDENCE_PATH", str(p))
    return p


# ── ★열쇠는 둘이다★ ────────────────────────────────────────────────────

def test_the_key_is_both_codes():
    assert code_key("1", "APBK0013") == "1/APBK0013"


def test_a_missing_msg_cd_is_marked_unknown_in_the_key():
    """★미상 ≠ 없음★ — 열쇠에서도 그 사실이 사라지지 않는다."""
    key = code_key("1", None)
    assert key != "1/"
    assert key == code_key("1", "")          # 빈 문자열도 미상이다
    assert "1" in key


def test_two_different_msg_cds_are_two_different_keys():
    """★짝★ — rt_cd 만으로 접으면 서로 다른 사실이 한 칸에 합쳐진다."""
    assert code_key("1", "A") != code_key("1", "B")


# ── ★등급이 적용선 아래면 적용하지 않는다★ ──────────────────────────────

def test_the_observed_grade_is_below_the_apply_floor():
    """★이 프로그램의 정직성 핵심★ — 관측만으로는 뜻이 되지 않는다."""
    assert CODE_GRADES.index(OBSERVED_GRADE) < CODE_GRADES.index(DEFAULT_MIN_GRADE)


def test_an_observed_only_entry_does_not_decide_the_fault(tmp_path, monkeypatch):
    """변이 a — `K1` 이 fault 를 정하면 죽는다."""
    _write_evidence(tmp_path, monkeypatch, {
        "1/APBK0013": {"rt_cd": "1", "msg_cd": "APBK0013",
                       "meaning": "장 종료", "fault": FAULT_SELF,
                       "grade": OBSERVED_GRADE},
    })
    assert meaning_of("1", "APBK0013") is None
    assert fault_from_table("1", "APBK0013")["fault"] == FAULT_UNKNOWN


def test_a_documented_entry_does_decide_the_fault(tmp_path, monkeypatch):
    """★짝★ — 적용선을 넘으면 실제로 말한다(공허한 분기가 아니다)."""
    _write_evidence(tmp_path, monkeypatch, {
        "1/APBK0013": {"rt_cd": "1", "msg_cd": "APBK0013",
                       "meaning": "장 종료", "fault": FAULT_SELF,
                       "grade": "K2", "evidence_source": "KIS 문서"},
    })
    got = meaning_of("1", "APBK0013")
    assert got is not None and got["meaning"] == "장 종료"
    assert fault_from_table("1", "APBK0013")["fault"] == FAULT_SELF


def test_lowering_the_grade_takes_the_fault_back(tmp_path, monkeypatch):
    """변이 b — 적용선을 무시하면 죽는다. 같은 항목, 등급만 다르다."""
    entry = {"rt_cd": "1", "msg_cd": "X", "meaning": "m", "fault": FAULT_PROVIDER}
    _write_evidence(tmp_path, monkeypatch, {"1/X": {**entry, "grade": "K3"}})
    assert fault_from_table("1", "X")["fault"] == FAULT_PROVIDER
    _write_evidence(tmp_path, monkeypatch, {"1/X": {**entry, "grade": "K1"}})
    assert fault_from_table("1", "X")["fault"] == FAULT_UNKNOWN


@pytest.mark.parametrize("bad", ["K9", "", None, "verified", 2])
def test_a_grade_outside_the_vocabulary_is_not_applied(tmp_path, monkeypatch, bad):
    """★어휘 밖의 값은 사실이 아니다★ (ECOS 선례)."""
    _write_evidence(tmp_path, monkeypatch, {
        "1/X": {"rt_cd": "1", "msg_cd": "X", "meaning": "m",
                "fault": FAULT_PROVIDER, "grade": bad},
    })
    assert meaning_of("1", "X") is None


@pytest.mark.parametrize("bad", ["provider ", "관측", "", None, "self!"])
def test_a_fault_outside_the_vocabulary_is_not_applied(tmp_path, monkeypatch, bad):
    """등급이 충분해도 **어휘 밖의 책임 소재**는 사실이 되지 못한다."""
    _write_evidence(tmp_path, monkeypatch, {
        "1/X": {"rt_cd": "1", "msg_cd": "X", "meaning": "m",
                "fault": bad, "grade": "K2"},
    })
    assert fault_from_table("1", "X")["fault"] == FAULT_UNKNOWN


def test_an_unknown_code_says_why_it_is_unknown(tmp_path, monkeypatch):
    """★사유 없는 미상은 금지★ (CLAUDE.md §4)."""
    _write_evidence(tmp_path, monkeypatch, {})
    got = fault_from_table("1", "APBK0013")
    assert got["fault"] == FAULT_UNKNOWN
    assert got["reason"] and isinstance(got["reason"], str)


# ── ★없거나 깨져도 죽지 않는다★ ────────────────────────────────────────

@pytest.mark.parametrize("body", ["", "{", "[]", '{"codes": 7}', "null"])
def test_a_broken_evidence_file_does_not_raise(tmp_path, monkeypatch, body):
    """변이 i — 여기서 터지면 이 모듈을 임포트하는 경로가 함께 죽는다."""
    p = tmp_path / "ev.json"
    p.write_text(body, encoding="utf-8")
    monkeypatch.setenv("KIS_RT_CD_EVIDENCE_PATH", str(p))
    codes, floor = load_evidence()
    assert codes == {}
    assert floor in CODE_GRADES


def test_a_missing_evidence_file_does_not_raise(tmp_path, monkeypatch):
    monkeypatch.setenv("KIS_RT_CD_EVIDENCE_PATH", str(tmp_path / "없음.json"))
    assert load_evidence()[0] == {}


def test_the_checked_in_evidence_file_is_empty_and_says_why():
    """★비어 있는 것이 결함이 아니라 정직한 현재 상태다★"""
    doc = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    assert doc["codes"] == {}, "표를 채웠다면 이 테스트가 아니라 등급을 고쳐라"
    assert doc["min_grade_to_apply"] == DEFAULT_MIN_GRADE
    assert "403" in doc["why_empty"], "왜 비었는지가 실측을 가리켜야 한다"
    assert set(doc["grades"]) == set(CODE_GRADES)


# ── ★라벨에 표를 입힌다★ ───────────────────────────────────────────────

def test_enriched_label_keeps_the_original_keys(tmp_path, monkeypatch):
    from src.domain.kis_failure import KIND_BUSINESS, failure_label

    _write_evidence(tmp_path, monkeypatch, {})
    base = failure_label(KIND_BUSINESS, rt_cd="1", msg_cd="X")
    out = enriched_label(base)
    assert set(base) <= set(out)
    assert out["kind"] == KIND_BUSINESS


def test_enriched_label_does_not_invent_a_fault_from_an_empty_table(
        tmp_path, monkeypatch):
    from src.domain.kis_failure import KIND_BUSINESS, failure_label

    _write_evidence(tmp_path, monkeypatch, {})
    out = enriched_label(failure_label(KIND_BUSINESS, rt_cd="1", msg_cd="X"))
    assert out["fault"] == FAULT_UNKNOWN
    assert out["table"]["meaning"] is None


def test_enriched_label_uses_the_table_when_it_is_good_enough(
        tmp_path, monkeypatch):
    from src.domain.kis_failure import KIND_BUSINESS, failure_label

    _write_evidence(tmp_path, monkeypatch, {
        "1/X": {"rt_cd": "1", "msg_cd": "X", "meaning": "잔고 부족",
                "fault": FAULT_SELF, "grade": "K2",
                "evidence_source": "KIS 문서"},
    })
    out = enriched_label(failure_label(KIND_BUSINESS, rt_cd="1", msg_cd="X"))
    assert out["fault"] == FAULT_SELF
    assert out["table"]["meaning"] == "잔고 부족"
    assert out["table"]["evidence_source"] == "KIS 문서"


def test_enriched_label_never_touches_a_non_business_kind(tmp_path, monkeypatch):
    """★종류를 넘어서지 않는다★ — 표는 `rt_cd` 의 표이지 전송 오류의 표가 아니다."""
    from src.domain.kis_failure import KIND_TRANSPORT, failure_label

    _write_evidence(tmp_path, monkeypatch, {
        "1/X": {"rt_cd": "1", "msg_cd": "X", "meaning": "m",
                "fault": FAULT_SELF, "grade": "K2"},
    })
    base = failure_label(KIND_TRANSPORT, rt_cd="1", msg_cd="X")
    out = enriched_label(base)
    assert out["fault"] == base["fault"] == FAULT_PROVIDER


def test_enriched_label_does_not_mutate_its_input(tmp_path, monkeypatch):
    from src.domain.kis_failure import KIND_BUSINESS, failure_label

    _write_evidence(tmp_path, monkeypatch, {
        "1/X": {"rt_cd": "1", "msg_cd": "X", "meaning": "m",
                "fault": FAULT_SELF, "grade": "K2"},
    })
    base = failure_label(KIND_BUSINESS, rt_cd="1", msg_cd="X")
    before = dict(base)
    enriched_label(base)
    assert base == before


# ── ★본 것을 접는다★ ───────────────────────────────────────────────────

def _row(rt_cd="1", msg_cd="X", mode="paper", ts="2026-09-01T00:00:00",
         msg1="장 종료"):
    return {"timestamp": ts, "execution_mode": mode,
            "failure": {"kind": "business", "rt_cd": rt_cd, "msg_cd": msg_cd,
                        "kis_msg": msg1}}


def test_fold_counts_and_keeps_first_and_last():
    folded = fold_observations([
        _row(ts="2026-09-03T00:00:00"),
        _row(ts="2026-09-01T00:00:00"),
        _row(ts="2026-09-02T00:00:00"),
    ])
    assert len(folded) == 1
    one = folded[0]
    assert one["count"] == 3
    assert one["first_seen"] == "2026-09-01T00:00:00"
    assert one["last_seen"] == "2026-09-03T00:00:00"


def test_fold_does_not_merge_execution_modes():
    """변이 f — 모의와 실계좌를 합치면 그 수치는 아무것도 뜻하지 않는다."""
    folded = fold_observations([_row(mode="paper"), _row(mode="live")])
    assert len(folded) == 2
    assert {f["execution_mode"] for f in folded} == {"paper", "live"}


def test_fold_marks_an_unknown_execution_mode_rather_than_dropping_it():
    """★짝 — 모드를 모르는 행도 사라지지 않는다★"""
    folded = fold_observations([{"timestamp": "2026-09-01T00:00:00",
                                 "failure": {"kind": "business", "rt_cd": "1",
                                             "msg_cd": "X"}}])
    assert len(folded) == 1
    assert folded[0]["execution_mode"] not in ("paper", "live")


def test_fold_keeps_the_sample_message_verbatim():
    """★해석하지 않고 그대로 남긴다★ — 해석은 사람이 문서를 보고 한다."""
    folded = fold_observations([_row(msg1="모의투자 장운영일이 아닙니다")])
    assert folded[0]["sample_msg1"] == "모의투자 장운영일이 아닙니다"


def test_fold_ignores_rows_without_a_failure_block():
    folded = fold_observations([{"timestamp": "t"}, _row(), {"failure": None}])
    assert len(folded) == 1


def test_fold_ignores_non_business_kinds():
    """표는 `rt_cd` 의 표다 — 전송 오류를 코드 표에 넣지 않는다."""
    rows = [_row(), {"timestamp": "t", "execution_mode": "live",
                     "failure": {"kind": "transport", "rt_cd": None,
                                 "msg_cd": None}}]
    assert len(fold_observations(rows)) == 1


def test_fold_of_nothing_is_nothing():
    assert fold_observations([]) == []


# ── ★빈틈 목록이 이 프로그램의 산출물이다★ ─────────────────────────────

def test_every_observed_code_is_a_gap_while_the_table_is_empty(
        tmp_path, monkeypatch):
    """★표가 비어 있으면 gaps 가 곧 observed 다 — 그것이 지금의 진실이다★"""
    _write_evidence(tmp_path, monkeypatch, {})
    folded = fold_observations([_row(msg_cd="A"), _row(msg_cd="B")])
    gaps = gap_list(folded)
    assert len(gaps) == 2
    assert {g["msg_cd"] for g in gaps} == {"A", "B"}


def test_a_documented_code_is_not_a_gap(tmp_path, monkeypatch):
    """변이 j — 필터가 실제로 무언가를 거른다(공허한 분기가 아니다)."""
    _write_evidence(tmp_path, monkeypatch, {
        "1/A": {"rt_cd": "1", "msg_cd": "A", "meaning": "m",
                "fault": FAULT_SELF, "grade": "K2"},
    })
    folded = fold_observations([_row(msg_cd="A"), _row(msg_cd="B")])
    gaps = gap_list(folded)
    assert [g["msg_cd"] for g in gaps] == ["B"]


def test_an_observed_only_entry_is_still_a_gap(tmp_path, monkeypatch):
    """★관측해 두었다고 아는 것이 아니다★ — `K1` 항목은 여전히 할 일이다."""
    _write_evidence(tmp_path, monkeypatch, {
        "1/A": {"rt_cd": "1", "msg_cd": "A", "grade": OBSERVED_GRADE,
                "observed": {"count": 99}},
    })
    assert [g["msg_cd"] for g in gap_list(fold_observations([_row(msg_cd="A")]))] == ["A"]


def test_gaps_carry_the_counts_so_the_work_can_be_ordered(tmp_path, monkeypatch):
    _write_evidence(tmp_path, monkeypatch, {})
    folded = fold_observations([_row(msg_cd="A"), _row(msg_cd="A"), _row(msg_cd="B")])
    gaps = gap_list(folded)
    assert [g["count"] for g in gaps] == [2, 1]     # 많이 본 것이 먼저


# ── ★표의 현재 상태를 말한다★ ──────────────────────────────────────────

def test_table_summary_reports_emptiness_with_a_reason(tmp_path, monkeypatch):
    _write_evidence(tmp_path, monkeypatch, {})
    s = table_summary()
    assert s["size"] == 0
    assert s["min_grade"] == DEFAULT_MIN_GRADE
    assert s["why_empty"]


def test_table_summary_counts_only_applicable_entries(tmp_path, monkeypatch):
    """★`K1` 항목은 표의 크기가 아니다★ — 세어 두면 채워진 것처럼 보인다."""
    _write_evidence(tmp_path, monkeypatch, {
        "1/A": {"rt_cd": "1", "msg_cd": "A", "meaning": "m",
                "fault": FAULT_SELF, "grade": "K2"},
        "1/B": {"rt_cd": "1", "msg_cd": "B", "grade": OBSERVED_GRADE},
    })
    s = table_summary()
    assert s["size"] == 1
    assert s["observed_only"] == 1


# ── ★순수★ ─────────────────────────────────────────────────────────────

def test_the_module_imports_no_database_or_network():
    """이 계층은 SQL 도 HTTP 도 알지 못한다(CLAUDE.md §3)."""
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    for banned in ("requests", "sqlalchemy", "httpx", "urllib"):
        assert banned not in imported, banned


def test_the_module_does_not_pattern_match_korean_messages():
    """변이 e — ★어휘로 걸면 안 된다★(AR 이 거부한 바로 그것)."""
    src = _MODULE.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and any(
                isinstance(op, ast.In) for op in node.ops):
            left = node.left
            if isinstance(left, ast.Constant) and isinstance(left.value, str):
                assert not any("가" <= ch <= "힣" for ch in left.value), (
                    f"한국어 문구를 매칭하고 있다: {left.value!r}")
