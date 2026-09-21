"""AT1 · ★연속 실패 다섯 회가 무엇이었나★ — 구성 어휘
==============================================================================
대상: `src/domain/failure_streak.py` · 종류 어휘 `src/domain/kis_failure.py`

## 왜 이 모듈이 생겼나

`auto_api` 는 *"KIS API 연속 실패 (5회)"* 로 킬스위치를 겨냥한다. 그런데 AR 이
드러낸 대로 그 5회에는 **장 종료 같은 정상 업무 응답이 섞여 들어간다** —
`_request` 가 `rt_cd != "0"` 에서도 `record_failure()` 를 부르기 때문이다.
그러니 5회가 전부 업무 응답이었다면 그 발동은 **틀린 진단**이다.

그런데 판정 자리에서는 그것을 알 수 없었다. ★`record_failure()` 는 인자를 받지
않아 breaker 가 눈먼 채로 세고★, 종류는 `last_failure_kind` 한 칸뿐이며,
감사 로그는 7개 호출부 중 주문·취소 **둘**만 본다.

## ★이 모듈이 지키는 두 가지★

1. **구성이 그 숫자를 설명하지 못하면 그렇게 말한다.** 기록한 개수와 센 개수가
   다르면 ★다른 집합을 설명하고 있는 것★이고, 조용히 내면 거짓이 된다.
2. **빈 것에 대해 전칭을 주장하지 않는다.** 파이썬에서 `all([])` 은 `True` 라,
   ★0회 중 0회가 업무 응답★ 이 "전부 업무 응답" 으로 읽힌다.

## ★이 모듈이 주장하지 않는 것★

- **책임 소재를 말하지 않는다.** `business` 의 뜻은 여전히 미상이다(AS —
  `rt_cd` 표가 비어 있다). 구성은 *"무엇이 몇 번"* 이지 *"누구 탓"* 이 아니다.
- **발동해야 하는지 말하지 않는다.** 판정은 `should_auto_trigger` 가 하고 이
  모듈은 그 옆에 붙는 문장만 만든다.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from src.domain.failure_streak import (
    STREAK_UNKNOWN_REASON,
    streak_composition,
    streak_phrase,
)
from src.domain.kis_failure import (
    KIND_BUSINESS,
    KIND_TOKEN,
    KIND_TRANSPORT,
    KIND_UNKNOWN,
)

_MODULE = pathlib.Path("src/domain/failure_streak.py")


# ── ★무엇이 몇 번★ ─────────────────────────────────────────────────────

def test_it_counts_each_kind():
    c = streak_composition([KIND_BUSINESS, KIND_BUSINESS, KIND_TRANSPORT])
    assert c["by_kind"] == {KIND_BUSINESS: 2, KIND_TRANSPORT: 1}
    assert c["n_recorded"] == 3


def test_the_dominant_kind_is_the_most_common():
    c = streak_composition([KIND_BUSINESS, KIND_BUSINESS, KIND_TRANSPORT])
    assert c["dominant"] == KIND_BUSINESS


def test_all_business_is_true_only_when_every_one_is():
    assert streak_composition([KIND_BUSINESS] * 5)["all_business"] is True
    assert streak_composition([KIND_BUSINESS, KIND_TRANSPORT])["all_business"] is False


def test_an_empty_streak_does_not_claim_all_business():
    """★공허한 참 금지★ — 파이썬에서 `all([])` 은 `True` 다.

    0회 중 0회가 업무 응답인 것을 "전부 업무 응답" 으로 읽으면, 아무 일도 없는
    상태가 ★가장 강한 주장★이 된다.
    """
    c = streak_composition([])
    assert c["all_business"] is False
    assert c["n_recorded"] == 0
    assert c["dominant"] is None


def test_business_count_is_reported_separately():
    c = streak_composition([KIND_BUSINESS, KIND_BUSINESS, KIND_TOKEN])
    assert c["business_n"] == 2


def test_it_reports_how_many_the_breaker_actually_counts():
    """★기술이지 정책이 아니다★ — 토큰 실패는 breaker 를 타지 않는다(AR)."""
    c = streak_composition([KIND_BUSINESS, KIND_TRANSPORT, KIND_TOKEN])
    assert c["counted_n"] == 2


@pytest.mark.parametrize("bad", ["망가짐", "", None, 7, "BUSINESS"])
def test_a_kind_outside_the_vocabulary_becomes_unknown(bad):
    """★어휘 밖의 값은 사실이 아니다★ — 버리지도 않고 믿지도 않는다."""
    c = streak_composition([bad])
    assert c["by_kind"] == {KIND_UNKNOWN: 1}
    assert c["n_recorded"] == 1


def test_an_unknown_kind_is_not_counted_as_business():
    """변이 d — 미상을 관측으로 바꾸면 죽는다."""
    c = streak_composition([KIND_UNKNOWN] * 5)
    assert c["business_n"] == 0
    assert c["all_business"] is False


# ── ★구성이 그 숫자를 설명하는가★ ──────────────────────────────────────

def test_it_describes_the_count_when_the_numbers_agree():
    c = streak_composition([KIND_BUSINESS] * 5, count=5)
    assert c["describes_count"] is True
    assert c["reason"] is None


def test_it_refuses_to_describe_a_count_it_does_not_match():
    """★다른 집합을 설명하고 있으면 그렇게 말한다★

    링이 넘쳤거나 누가 `failure_count` 를 직접 건드렸을 수 있다. 조용히
    구성을 내면 "5회 중 3회가 업무 응답" 이라는 **틀린 비율**이 만들어진다.
    """
    c = streak_composition([KIND_BUSINESS] * 3, count=5)
    assert c["describes_count"] is False
    assert c["reason"]


def test_an_unknown_count_is_not_a_match(caplog):
    """★미상 ≠ 일치★ — 셀 수 없었던 것을 "맞다" 로 읽지 않는다."""
    c = streak_composition([KIND_BUSINESS] * 3, count=None)
    assert c["describes_count"] is None
    assert c["reason"] == STREAK_UNKNOWN_REASON


def test_all_business_still_reports_when_it_does_not_describe_the_count():
    """관측한 것은 관측한 것이다 — 라벨이 붙을 뿐 사라지지 않는다."""
    c = streak_composition([KIND_BUSINESS] * 3, count=5)
    assert c["business_n"] == 3
    assert c["describes_count"] is False


# ── ★판정 옆에 붙는 문장★ ──────────────────────────────────────────────

def test_the_phrase_names_the_composition():
    phrase = streak_phrase(streak_composition([KIND_BUSINESS] * 5, count=5))
    assert "5" in phrase
    assert phrase.strip()


def test_the_phrase_of_an_all_business_streak_says_the_meaning_is_unknown():
    """★AS 의 표가 비어 있다★ — 업무 응답이라고 해서 거절이라고 단정하지 않는다."""
    phrase = streak_phrase(streak_composition([KIND_BUSINESS] * 5, count=5))
    assert "미상" in phrase


def test_the_phrase_says_so_when_it_cannot_describe_the_count():
    """변이 c — 넘친 링이 사실 행세하면 죽는다."""
    phrase = streak_phrase(streak_composition([KIND_BUSINESS] * 2, count=5))
    assert "미상" in phrase or "설명" in phrase
    assert "2회가 업무 응답" not in phrase


def test_an_empty_streak_phrase_does_not_claim_a_composition():
    phrase = streak_phrase(streak_composition([], count=0))
    assert "전부" not in phrase


def test_the_phrase_of_a_mixed_streak_does_not_say_all():
    mixed = streak_composition([KIND_BUSINESS] * 4 + [KIND_TRANSPORT], count=5)
    assert "전부" not in streak_phrase(mixed)


def test_the_phrase_is_never_empty():
    """★사유 없는 미상은 금지★ — 어떤 입력에도 말할 것이 있다."""
    for kinds, count in (([], 0), ([], None), ([KIND_UNKNOWN], 1),
                         ([KIND_BUSINESS], 9)):
        assert streak_phrase(streak_composition(kinds, count=count)).strip()


def test_the_phrase_takes_a_composition_not_raw_kinds():
    """★두 축을 섞지 않는다★ — 접는 것과 말하는 것은 다른 일이다."""
    with pytest.raises((TypeError, AttributeError, KeyError)):
        streak_phrase([KIND_BUSINESS, KIND_BUSINESS])


# ── ★책임 소재를 말하지 않는다★ ────────────────────────────────────────

def test_the_composition_never_carries_a_fault():
    """변이 l — 구성이 책임 소재를 단정하면 죽는다(AS 의 표가 비어 있다)."""
    c = streak_composition([KIND_BUSINESS] * 5, count=5)
    assert "fault" not in c


def test_the_module_does_not_import_the_table():
    """구성은 종류(AR)로 세는 것이지 뜻(AS)으로 세는 것이 아니다."""
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
    assert "src.domain.kis_rt_cd" not in imported


def test_the_module_imports_no_database_or_network():
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    for banned in ("requests", "sqlalchemy", "httpx", "urllib"):
        assert banned not in imported, banned
