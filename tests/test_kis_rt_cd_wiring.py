"""AS · ★표가 표면에 닿는다★ — 아무도 안 부르는 계약은 계약이 아니다
==============================================================================
대상: `api_failure_probe._last_failure` → `GET /kill-switch/readiness`

이 저장소에는 **배선은 됐지만 아무도 소비하지 않는** 모듈이 있고
(`exposure_taxonomy` 의 docstring 이 스스로 그렇게 적는다), 그것은 계약이
아니라 장식이다. `kis_rt_cd.enriched_label` 이 같은 신세가 되지 않게 소비자를
못 박는다.

★오늘은 아무것도 바뀌지 않는다★ — 표가 비어 있기 때문이다. 바뀌는 것은
**표가 채워졌을 때** 그것이 표면까지 간다는 사실이고, 그 짝을 함께 잰다.
"""
from __future__ import annotations

import json

import pytest

from src.domain.kis_failure import FAULT_SELF, FAULT_UNKNOWN, KIND_BUSINESS


class _Breaker:
    def __init__(self):
        self.state = "CLOSED"
        self.failure_count = 0

    def call_allowed(self):
        return True


class _Client:
    def __init__(self, msg_cd="A"):
        self.circuit_breaker = _Breaker()
        self.last_failure_kind = KIND_BUSINESS
        self.last_failure_rt_cd = "1"
        self.last_failure_msg_cd = msg_cd
        self.last_failure_status = 200


@pytest.fixture()
def evidence(tmp_path, monkeypatch):
    p = tmp_path / "ev.json"

    def write(codes):
        p.write_text(json.dumps(
            {"schema": 1, "min_grade_to_apply": "K2", "why_empty": "테스트",
             "codes": codes}, ensure_ascii=False), encoding="utf-8")

    write({})
    monkeypatch.setenv("KIS_RT_CD_EVIDENCE_PATH", str(p))
    return write


def _probe(client):
    from src.execution.api_failure_probe import probe

    return probe(client=client)


def test_the_last_failure_carries_the_key(evidence):
    """AS1 의 열쇠가 표면까지 온다."""
    lf = _probe(_Client())["last_failure"]
    assert lf["rt_cd"] == "1" and lf["msg_cd"] == "A"


def test_an_empty_table_leaves_the_fault_unknown(evidence):
    """★오늘의 동작 — 표가 비어 있으므로 아무것도 바뀌지 않는다★"""
    lf = _probe(_Client())["last_failure"]
    assert lf["fault"] == FAULT_UNKNOWN
    assert lf["table"]["meaning"] is None
    assert lf["table"]["reason"]


def test_a_filled_table_reaches_the_surface(evidence):
    """★짝 — 표가 채워지면 표면이 그것을 말한다★ (공허한 배선이 아니다)."""
    evidence({"1/A": {"rt_cd": "1", "msg_cd": "A", "meaning": "장 종료",
                      "fault": FAULT_SELF, "grade": "K2",
                      "evidence_source": "KIS 문서"}})
    lf = _probe(_Client())["last_failure"]
    assert lf["fault"] == FAULT_SELF
    assert lf["table"]["meaning"] == "장 종료"


def test_an_observed_only_table_does_not_reach_the_surface(evidence):
    """변이 a·b — `K1` 은 적용선 아래다. 같은 항목, 등급만 다르다."""
    evidence({"1/A": {"rt_cd": "1", "msg_cd": "A", "meaning": "장 종료",
                      "fault": FAULT_SELF, "grade": "K1"}})
    assert _probe(_Client())["last_failure"]["fault"] == FAULT_UNKNOWN


def test_a_different_msg_cd_is_a_different_code(evidence):
    """★열쇠가 둘인 이유★ — rt_cd 만 맞아도 다른 코드다."""
    evidence({"1/A": {"rt_cd": "1", "msg_cd": "A", "meaning": "장 종료",
                      "fault": FAULT_SELF, "grade": "K2"}})
    assert _probe(_Client(msg_cd="B"))["last_failure"]["fault"] == FAULT_UNKNOWN


def test_no_failure_means_no_block(evidence):
    """★없으면 지어내지 않는다★ (AR4 의 계약을 그대로 둔다)."""
    client = _Client()
    client.last_failure_kind = None
    assert _probe(client)["last_failure"] is None


def test_the_breaker_count_is_untouched_by_the_table(evidence):
    """★표가 채워져도 세는 것은 바뀌지 않는다★ — 별도 승인 사항이다."""
    from src.domain.kis_failure import COUNTED_BY_BREAKER, KIND_TRANSPORT

    evidence({"1/A": {"rt_cd": "1", "msg_cd": "A", "meaning": "장 종료",
                      "fault": FAULT_SELF, "grade": "K2"}})
    assert COUNTED_BY_BREAKER == frozenset({KIND_TRANSPORT, KIND_BUSINESS})
