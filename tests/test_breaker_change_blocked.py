"""AU · ★이 변경은 아직 허용되지 않았다★ — 산문이 아니라 문
==============================================================================
선례: `tests/test_distribution_blocked.py`(★인가 확인 전까지 유통 표면을
만들지 않는다★를 테스트로 박아 둔 파일)

## 왜 이 파일이 산출물인가

AR·AS·AT 이 차례로 *"breaker 가 무엇을 세는지 바꾸지 않았다"* 고 적었다 —
HISTORY 에 **네 번**. ★산문은 내일 누군가 그냥 바꿔도 아무것도 깨지지
않는다.★ 이 파일이 그 결정을 **깨질 수 있게** 만든다.

`COUNTED_BY_BREAKER` 에서 `business` 를 빼려면 먼저 문이 열려야 하고, 문은
`(rt_cd, msg_cd)` 코드마다 ⑴ 뜻이 표에 있고 ⑵ 표가 KIS 장애가 아니라고 말하고
⑶ 충분히 관측됐고 ⑷ 그 관측이 합성이 아닐 때만 열린다.

## ★검출기가 실제로 검출하는지도 잰다★

`test_distribution_blocked.py` 의 관용구를 그대로 따른다: *"지금 없다"* 만
재면 **검출기가 고장 나도 통과**한다. 그래서 심어 둔 것을 잡는지 함께 잰다.
"""
from __future__ import annotations

import json
import pathlib

from src.domain.breaker_change_gate import (
    CHANGE_ALLOWED,
    CHANGE_BLOCKED,
    gate_summary,
    may_stop_counting,
)
from src.domain.kis_failure import (
    COUNTED_BY_BREAKER,
    KIND_BUSINESS,
    KIND_TRANSPORT,
)
from src.domain.kis_rt_cd import EVIDENCE_PATH

_GATE_SRC = pathlib.Path("src/domain/breaker_change_gate.py")


# ── ★오늘의 사실 — 업무 응답은 여전히 세어진다★ ───────────────────────

def test_business_is_still_counted_by_the_breaker():
    """★이 테스트를 고치려면 먼저 문을 열어야 한다★

    `COUNTED_BY_BREAKER` 에서 `business` 를 빼는 것은 실거래 호출 경로 동작
    변경이다(CLAUDE.md §6). 증거 없이 빼면 ★그 안의 진짜 장애까지 같이
    빠진다★ — `business` 는 의미가 아니라 모양(HTTP 200 + rt_cd≠0)이다.
    """
    assert KIND_BUSINESS in COUNTED_BY_BREAKER


def test_the_registry_did_not_quietly_change_shape():
    """★짝★ — 위 단언만 있으면 다른 종류가 사라져도 통과한다."""
    assert COUNTED_BY_BREAKER == frozenset({KIND_TRANSPORT, KIND_BUSINESS})


def test_the_gate_is_closed_in_this_repository():
    """★표가 비어 있으므로 어느 코드도 통과하지 못한다★

    이것이 AS 의 빈 표가 왜 중요한지에 대한 기계적 증명이다.
    """
    assert gate_summary([])["state"] == CHANGE_BLOCKED


def test_the_checked_in_table_exempts_no_code():
    """체크인된 증거 파일로 실제로 재 본다(테스트용 임시 파일이 아니라)."""
    doc = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    exempt = [key for key, entry in doc["codes"].items()
              if isinstance(entry, dict) and entry.get("outage") is False]
    assert exempt == [], f"표가 면제 후보를 담고 있다: {exempt}"


def test_the_evidence_file_documents_the_outage_field():
    """★문이 읽는 칸이 문서화돼 있어야 사람이 채울 수 있다★"""
    doc = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    assert "outage" in doc["fields"]
    assert "breaker" in doc["fields"]["outage"]


# ── ★검출기가 실제로 검출하는가★ ──────────────────────────────────────

def test_a_planted_exempt_code_would_be_caught(tmp_path, monkeypatch):
    """★위 두 테스트가 고장 나 있지 않다는 증명★

    조건을 모두 갖춘 코드를 심으면 문이 **열린다**. 이것이 없으면
    `return blocked` 한 줄짜리 게이트가 모든 검사를 통과한다.
    """
    p = tmp_path / "ev.json"
    p.write_text(json.dumps({
        "schema": 1, "min_grade_to_apply": "K2", "why_empty": "심은 것",
        "codes": {"1/PLANT": {"rt_cd": "1", "msg_cd": "PLANT",
                              "meaning": "심은 코드", "outage": False,
                              "grade": "K2", "evidence_source": "테스트"}},
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("KIS_RT_CD_EVIDENCE_PATH", str(p))

    from src.domain.breaker_change_gate import MIN_OBSERVATIONS

    out = may_stop_counting("1", "PLANT", observation={
        "rt_cd": "1", "msg_cd": "PLANT", "count": MIN_OBSERVATIONS,
        "execution_mode": "live"})
    assert out["state"] == CHANGE_ALLOWED, out


def test_the_planted_code_is_gone_again_outside_the_patch():
    """심은 것이 실제 파일로 새지 않았다."""
    doc = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    assert "1/PLANT" not in doc["codes"]


# ── ★문은 말할 뿐 막지 않는다★ ───────────────────────────────────────

def test_the_gate_is_not_wired_into_the_call_path():
    """★관측·기록은 자유, 동작 변경은 승인 사항★ (CLAUDE.md §3)

    이 문이 `_request` 나 `record_failure` 에 연결되면, 표를 채우는 순간
    **아무도 승인하지 않은 동작 변경**이 조용히 일어난다.
    """
    client = pathlib.Path("src/execution/kis_client.py").read_text(encoding="utf-8")
    assert "breaker_change_gate" not in client
    assert "may_stop_counting" not in client


def test_the_gate_does_not_import_the_breaker():
    """반대 방향도 막는다 — 도메인이 실행 계층을 알지 못한다.

    ★어휘가 아니라 구조로 건다★ — 처음엔 원문을 통째로 grep 했더니
    docstring 이 `COUNTED_BY_BREAKER` 를 **설명하는** 것까지 잡혔다. 설명은
    의존이 아니다(AR 이 문구 매칭을 거부한 것과 같은 이유).
    """
    import ast

    tree = ast.parse(_GATE_SRC.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
    assert not any("execution" in m for m in imported), imported
    assert not any("kis_client" in m for m in imported), imported
