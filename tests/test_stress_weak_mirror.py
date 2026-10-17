"""BU7a — 위험 점검 화면의 "취약" 기준 문장이 서버 스트레스 판정과 같은지.

화면(`frontend/src/widgets/risk/StressCheck.tsx` 의 `STRESS_WEAK_PCT`)은 "종합점수가 N% 넘게 떨어지면 ‘취약’으로 셌어요"
라고 말한다. 서버(`src/engine/stress_test_analyzer.py::stress_test`)의 `survived` 판정이 따로 바뀌면 화면이 틀린 기준을 말한다 —
★서버 동작이 진실이고 화면 상수는 거울이다★. 소스 글자가 아니라 경계 양쪽 값을 넣어 판정을 본다.
"""
from __future__ import annotations

import pathlib
import re
from types import SimpleNamespace

from src.engine import stress_test_analyzer as sta

TSX = pathlib.Path(__file__).resolve().parents[1] / "frontend" / "src" / "widgets" / "risk" / "StressCheck.tsx"


def _front() -> float:
    m = re.search(r"export const STRESS_WEAK_PCT = ([\d.]+);", TSX.read_text(encoding="utf-8"))
    assert m, "STRESS_WEAK_PCT 를 찾지 못했다 — 이름을 바꿨다면 이 테스트도 함께"
    return float(m.group(1))


def _survived(monkeypatch, shock: float) -> bool:
    monkeypatch.setattr(sta, "_stock_shock", lambda item, scenario: shock)
    it = SimpleNamespace(stock_code="000000", corp_name="가", composite_score=60)
    out = sta.stress_test([it], scenario="rate_hike_200bp")
    rows = out["casualties"] + out["survivors"]
    return rows[0]["survived"]


def test_front_threshold_is_where_the_server_flips(monkeypatch):
    k = _front()
    assert _survived(monkeypatch, -(k - 0.1)) is True
    assert _survived(monkeypatch, -(k + 0.1)) is False
    # 짝: 경계에서 먼 값도 같은 쪽 — 판정이 그 경계에서만 바뀐다(공허한 비교가 아니다).
    assert _survived(monkeypatch, -(k / 2)) is True
    assert _survived(monkeypatch, -(k * 3)) is False
