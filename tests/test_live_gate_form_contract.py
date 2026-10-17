"""BU9b — 실계좌 관문 선언 화면이 서버 관문 판정과 같은 칸·같은 금지값을 말하는가.

화면(`frontend/src/entities/trading/liveGate.ts`)은 서버 `src/domain/live_gate.py` 를 import 할 수 없다. 그래서
① 화면이 보내는 칸 목록 `GATE_FIELDS` 가 서버 `AUTH_FIELDS` 와 같은 순서·같은 이름인지,
② 안내 글의 '모두에게 여는 값' 예(`WILDCARD_EXAMPLES`)가 서버가 실제로 거절하는 값(`_WILDCARDS`)인지 여기서 맞춘다.
한쪽만 바뀌면 화면이 빠진 칸을 보내거나, 서버가 받는 값을 '받지 않는다'고 거짓으로 말하게 된다.
"""
from __future__ import annotations

import re
from pathlib import Path

from src.domain import live_gate

FRONT = Path(__file__).resolve().parents[1] / "frontend" / "src" / "entities" / "trading" / "liveGate.ts"


def _array(name: str, text: str) -> list[str]:
    m = re.search(rf"export const {name} = \[([^\]]*)\]", text)
    assert m, f"{name} 를 {FRONT} 에서 찾지 못했다"
    return re.findall(r'"([^"]*)"', m.group(1))


def test_gate_fields_match_server_auth_fields() -> None:
    assert _array("GATE_FIELDS", FRONT.read_text(encoding="utf-8")) == list(live_gate.AUTH_FIELDS)


def test_gate_fields_check_is_not_vacuous() -> None:
    """짝 — 칸 하나를 바꾼 글이면 같지 않다(추출이 늘 같은 값을 돌려주는 공허한 비교가 아님)."""
    bent = FRONT.read_text(encoding="utf-8").replace('"scope"', '"range"')
    assert _array("GATE_FIELDS", bent) != list(live_gate.AUTH_FIELDS)


def test_wildcard_examples_are_refused_by_server() -> None:
    examples = _array("WILDCARD_EXAMPLES", FRONT.read_text(encoding="utf-8"))
    assert examples, "안내 글에 예가 하나는 있어야 한다"
    assert set(examples) <= set(live_gate._WILDCARDS)
    # 짝 — 서버가 실제로 그 값을 거절한다(판정 함수로).
    for w in examples:
        rec = live_gate.LiveAuthorization(basis="b", authority="a", reference_no="r", verified_at="2026-10-10",
                                          scope="s", allowed_users=(w,))
        assert "allowed_users" in rec.missing(), w
    ok = live_gate.LiveAuthorization(basis="b", authority="a", reference_no="r", verified_at="2026-10-10",
                                     scope="s", allowed_users=("minji",))
    assert ok.missing() == []
