"""BV1 — 문서와 코드가 실계좌에 대해 서로 다른 말을 하지 않는다.

로드맵 ⑥ "인가 없이 켜지 않는다" 와 "하지 않을 것: 실계좌 집행 코드(인가 확인 전 금지)", 제품 규칙 §1
"실계좌 집행은 인가 확인 전까지 금지" 가 있었다. 사용자가 그 규칙을 알고 ★실계좌도 만든다★ 를 골랐다(2026-10-09).
코드가 실계좌를 만들기 시작하면서 문서가 옛 문장 그대로 남으면, 문서가 코드에 대해 거짓말을 한다.
그래서 세 자리가 ★관문 이름(`live_gate`)을 말하고, 사용자 결정 날짜를 적는다★ — 관문을 지우거나 이름을 바꾸면 여기가 빨개진다.
"""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROADMAP = ROOT / "docs/plans/2026-09-12-ra-product-roadmap.md"
RULES = ROOT / "docs/specs/2026-09-12-ra-product-rules.md"
GATE = ROOT / "src/domain/live_gate.py"


def _row(text: str, starts: str) -> str:
    rows = [line for line in text.splitlines() if line.startswith(starts)]
    assert len(rows) == 1, f"'{starts}' 로 시작하는 줄이 {len(rows)}개"
    return rows[0]


def test_the_gate_the_docs_name_exists():
    assert GATE.exists()
    assert "def live_gate(" in GATE.read_text(encoding="utf-8")


def test_the_roadmap_not_to_do_row_names_the_gate_and_the_decision():
    row = _row(ROADMAP.read_text(encoding="utf-8"), "| **실계좌 집행 코드**")
    assert "live_gate" in row
    assert "2026-10-09" in row


def test_the_roadmap_rule_six_still_says_nothing_turns_on_without_confirmation():
    """★짝★ — 결정을 적으며 ⑥ 자체를 지우지 않았다(켜는 것은 여전히 관문 뒤)."""
    text = ROADMAP.read_text(encoding="utf-8")
    assert "⑥ ★**인가 없이 켜지 않는다.**★" in text
    six = text[text.index("⑥ ★**인가 없이 켜지 않는다.**★"):][:900]
    assert "live_gate" in six


def test_the_product_rules_name_the_gate():
    text = RULES.read_text(encoding="utf-8")
    para = text[text.index("**아직 못 하는 것을 적어 둔다**"):][:1200]
    assert "live_gate" in para
    assert "2026-10-09" in para


def test_the_docs_say_the_kis_partnership_summary_is_unverified():
    """검색 요약을 사실처럼 적지 않는다 — '미검증' 표시가 함께 있다."""
    for path in (ROADMAP, RULES):
        text = path.read_text(encoding="utf-8")
        i = text.index("제휴")
        assert "미검증" in text[max(0, i - 400): i + 400], path.name
