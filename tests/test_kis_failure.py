"""AR1 — KIS 실패 종류 어휘. ★차단 ≠ 실패 · 거절 ≠ 장애★

`KISClient._request` 는 전송 오류·비-2xx·`rt_cd != "0"`·레이트리밋을 **전부 같은
`RuntimeError`** 로 뭉갠다(예외 하위형이 하나도 없다). 그래서 지금:

    · `live_orders.reason_code` 가 무엇이 일어났든 언제나 `"api_error"` 다
    · 정상 업무 응답(장 종료·잔고 부족)이 KIS 장애와 **같은 카운터**에 들어간다
    · breaker 가 스스로 막은 것(`OPEN`)도 "실패" 처럼 보인다

★두 축을 섞지 않는다★ — **무엇이 일어났나**(kind) ⟂ **누구의 문제인가**(fault).

★그리고 이 저장소는 `rt_cd` 의 뜻을 모른다★ — 코드도 문서도 매핑 표가 없다.
그래서 `business` 의 책임 소재는 **단정하지 않고** `unknown` 이다.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from src.domain.kis_failure import (
    COUNTED_BY_BREAKER,
    FAILURE_KINDS,
    FAULT_PROVIDER,
    FAULT_SELF,
    FAULT_UNKNOWN,
    FAULTS,
    KIND_BLOCKED,
    KIND_BUSINESS,
    KIND_FAULT,
    KIND_HTTP_STATUS,
    KIND_LABELS,
    KIND_MALFORMED,
    KIND_TOKEN,
    KIND_TRANSPORT,
    KIND_UNKNOWN,
    classify,
    counts_toward_breaker,
    failure_label,
    fault_of,
)

_MODULE = pathlib.Path("src/domain/kis_failure.py")


# ── 레지스트리 ─────────────────────────────────────────────────────────────

def test_the_kinds_are_registered_and_labelled():
    """★테스트의 테스트★ — 레지스트리를 비우면 아래 전수 검사가 공허해진다."""
    assert set(FAILURE_KINDS) == {KIND_BLOCKED, KIND_TRANSPORT, KIND_HTTP_STATUS,
                                  KIND_MALFORMED, KIND_BUSINESS, KIND_TOKEN,
                                  KIND_UNKNOWN}
    assert set(KIND_LABELS) == set(FAILURE_KINDS)
    assert all(KIND_LABELS[k] for k in FAILURE_KINDS)


def test_every_kind_has_a_fault():
    """★총함수★ — 종류 하나가 책임 소재 없이 남으면 조용히 사라진다.

    ★이 테스트를 처음엔 약하게 썼다★ — `fault_of(kind) in FAULTS` 만 봤는데,
    `fault_of` 는 `.get(kind, FAULT_UNKNOWN)` 이라 **빠진 종류도 `unknown` 으로
    통과한다**. 변이 배터리에서 `KIND_MALFORMED` 를 표에서 지워도 죽지 않았다.
    주장(총함수)을 **키로** 확인한다.
    """
    assert set(KIND_FAULT) == set(FAILURE_KINDS), set(FAILURE_KINDS) ^ set(KIND_FAULT)
    for kind in FAILURE_KINDS:
        assert fault_of(kind) in FAULTS, kind


@pytest.mark.parametrize("kind,expected", [
    (KIND_MALFORMED, FAULT_PROVIDER),
    (KIND_HTTP_STATUS, FAULT_PROVIDER),
])
def test_the_provider_side_kinds_say_so(kind, expected):
    """★짝★ — 표에서 빠져 `unknown` 으로 접히는 것을 배제한다."""
    assert fault_of(kind) == expected


def test_an_unregistered_kind_is_not_taken_at_face_value():
    assert fault_of("망가짐") == FAULT_UNKNOWN


# ── ★차단은 실패가 아니다★ ──────────────────────────────────────────────

def test_a_blocked_call_is_our_own_refusal_not_a_provider_failure():
    assert classify(blocked=True) == KIND_BLOCKED
    assert fault_of(KIND_BLOCKED) == FAULT_SELF
    assert counts_toward_breaker(KIND_BLOCKED) is False


def test_blocked_wins_over_everything_else():
    """차단되면 호출 자체가 없었으므로 다른 단서는 의미가 없다."""
    assert classify(blocked=True, exception_name="ConnectionError",
                    status=500, rt_cd="1") == KIND_BLOCKED


# ── 전송 ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", ["ConnectionError", "Timeout", "ReadTimeout",
                                  "SSLError", "RequestException"])
def test_a_transport_exception_is_transport(name):
    assert classify(exception_name=name) == KIND_TRANSPORT


def test_transport_is_the_providers_problem_and_is_counted():
    assert fault_of(KIND_TRANSPORT) == FAULT_PROVIDER
    assert counts_toward_breaker(KIND_TRANSPORT) is True


# ── 본문·상태 ──────────────────────────────────────────────────────────────

def test_a_body_that_is_not_json_is_malformed():
    assert classify(json_ok=False, status=200) == KIND_MALFORMED


def test_malformed_is_not_counted_today():
    """★지금도 세지 않는다★ — 이 프로그램은 세는 것을 바꾸지 않는다."""
    assert counts_toward_breaker(KIND_MALFORMED) is False


def test_a_non_2xx_with_no_business_code_is_an_http_status_failure():
    assert classify(status=503, rt_cd=None) == KIND_HTTP_STATUS


@pytest.mark.parametrize("status", [200, 201, 299])
def test_a_2xx_without_other_clues_is_unknown(status):
    """★모르는 것을 정상으로 읽지 않는다★"""
    assert classify(status=status) == KIND_UNKNOWN


# ── ★업무 응답 — 뜻을 모른다★ ──────────────────────────────────────────

def test_a_non_zero_rt_cd_is_a_business_outcome():
    assert classify(status=200, rt_cd="1") == KIND_BUSINESS


def test_a_zero_rt_cd_is_not_a_failure_at_all():
    """★짝★ — 성공을 실패로 분류하지 않는다."""
    assert classify(status=200, rt_cd="0") == KIND_UNKNOWN


def test_the_repository_does_not_claim_who_is_at_fault_for_a_business_outcome():
    """★이 프로그램의 정직성 핵심★ — `rt_cd` 매핑 표가 저장소에 없다.

    `"장 종료"` 를 패턴 매칭해 "업무 거절" 이라고 단정하면 확인한 적 없는 것을
    주장하는 것이다. 그래서 책임 소재는 **미상**이고 사유가 왜인지 적는다.
    """
    assert fault_of(KIND_BUSINESS) == FAULT_UNKNOWN
    label = failure_label(KIND_BUSINESS, rt_cd="1", msg="장 종료")
    assert label["fault"] == FAULT_UNKNOWN
    assert label["fault_reason"]


def test_a_business_outcome_is_counted_by_the_breaker_today():
    """★이것이 안전 역전이다★ — 업무 응답이 장애와 같은 카운터에 들어간다.

    이 단언은 **지금 동작의 기술**이지 옳다는 뜻이 아니다. 바꾸는 것은 별도
    승인 사항이고, 이 프로그램은 그 사실이 **보이게** 할 뿐이다.
    """
    assert counts_toward_breaker(KIND_BUSINESS) is True


def test_the_business_label_carries_the_raw_code_and_message():
    label = failure_label(KIND_BUSINESS, rt_cd="1", status=200, msg="장 종료")
    assert label["rt_cd"] == "1" and label["status"] == 200
    assert label["kis_msg"] == "장 종료"


# ── 토큰 ───────────────────────────────────────────────────────────────────

def test_a_token_failure_is_its_own_kind_and_is_not_counted():
    """`_fetch_token` 은 `_request` 를 타지 않아 breaker 에 기록되지 않는다(실측)."""
    assert classify(token=True, status=401) == KIND_TOKEN
    assert fault_of(KIND_TOKEN) == FAULT_PROVIDER
    assert counts_toward_breaker(KIND_TOKEN) is False


# ── ★현재 동작의 기술★ ─────────────────────────────────────────────────

def test_the_counted_set_is_exactly_the_two_kinds_request_records_today():
    """★기술이지 정책이 아니다★ — 실제 코드와의 대조는 AST 트립와이어가 한다."""
    assert COUNTED_BY_BREAKER == frozenset({KIND_TRANSPORT, KIND_BUSINESS})


@pytest.mark.parametrize("kind", list(FAILURE_KINDS))
def test_counts_toward_breaker_agrees_with_the_set(kind):
    assert counts_toward_breaker(kind) is (kind in COUNTED_BY_BREAKER)


# ── 라벨 ───────────────────────────────────────────────────────────────────

def test_the_label_shape_is_pinned():
    label = failure_label(KIND_TRANSPORT)
    assert set(label) == {"kind", "label", "fault", "fault_reason",
                          "counted_by_breaker", "rt_cd", "msg_cd", "status",
                          "kis_msg", "note"}


def test_an_unregistered_kind_labels_as_unknown():
    assert failure_label("망가짐")["kind"] == KIND_UNKNOWN


def test_a_provider_fault_needs_no_excuse():
    """★짝★ — 언제나 사유가 붙는 구현을 배제한다."""
    assert failure_label(KIND_TRANSPORT)["fault_reason"] is None


def test_no_response_string_carries_markdown():
    """★평문 응답 규율★ — `**` 가 화면에 그대로 보인다(AB 가 세운 규칙)."""
    label = failure_label(KIND_BUSINESS, rt_cd="1")
    texts = [label["note"], label["fault_reason"] or "", label["label"]]
    assert not any("**" in t for t in texts), texts


def test_the_note_says_the_breaker_does_not_tell_kinds_apart():
    assert "카운터" in failure_label(KIND_BUSINESS)["note"]


# ── 계층 경계 ──────────────────────────────────────────────────────────────

def test_the_module_knows_nothing_about_http_or_storage():
    """★`src/domain/` 은 순수하다★ — `requests` 를 알지 못한다."""
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
    assert not (imported & {"requests", "httpx", "sqlalchemy", "src"}), imported
