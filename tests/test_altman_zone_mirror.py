"""BU6b — 기업 분석 화면의 알트만 Z 구간 막대 경계가 서버의 구간 판정과 같은지.

화면(`frontend/src/widgets/company/RiskDeepTab.tsx` 의 `ALTMAN_EDGES`)은 0~5 축에 경계 눈금을 긋고, 구간 이름은
서버 `risk_deep` 이 준 `zone` 글자를 그대로 쓴다. 경계가 따로 바뀌면 점은 "회색지대" 칸에 있는데 서버는 "안전" 이라고
말하는 화면이 된다 — ★서버 동작이 진실이고 화면 상수는 거울이다★. 소스 글자가 아니라 경계 양쪽 값을 넣어 판정을 본다.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from src.engine import company_analytics as ca

TSX = pathlib.Path(__file__).resolve().parents[1] / "frontend" / "src" / "widgets" / "company" / "RiskDeepTab.tsx"


def _front_edges() -> list[float]:
    m = re.search(r"export const ALTMAN_EDGES = \[([^\]]*)\] as const;", TSX.read_text(encoding="utf-8"))
    assert m, "ALTMAN_EDGES 를 찾지 못했다 — 이름을 바꿨다면 이 테스트도 함께"
    return [float(x) for x in m.group(1).split(",")]


class _Store:
    """z = 매출/총자산(다섯 요소 중 x5 만 남긴다) — 원하는 z 를 정확히 만든다."""
    def __init__(self, z: float):
        self.z = z

    def get_raw_financials(self, code):  # noqa: ARG002
        return {"total_assets": 100.0, "current_assets": 10.0, "current_liabilities": 10.0, "net_income": 0.0,
                "operating_profit": 0.0, "market_cap": 0.0, "total_liabilities": 1.0, "revenue": self.z * 100.0}


def _zone(monkeypatch, z: float) -> str:
    from src.data import fundamentals_store as fs
    monkeypatch.setattr(fs.FundamentalsStore, "get_default", classmethod(lambda cls: _Store(z)))
    monkeypatch.setattr(ca, "_annual_rows", lambda code: [])
    monkeypatch.setattr(ca, "resolve_default_params", lambda code: {"rf": 0.03, "beta": 1.0, "erp": 0.06, "g": 0.02, "years": 10})
    monkeypatch.setattr(ca, "_mcap", lambda code: None)

    class _Eng:
        def evaluate(self, *a, **k):
            raise RuntimeError("stub")
    monkeypatch.setattr(ca, "_engine", lambda: _Eng())
    out = ca.risk_deep("000000", 1000.0)["altman"]
    assert out["z"] == pytest.approx(z, abs=0.01)  # 서버는 z 를 소수 둘째 자리로 반올림해 낸다(판정은 반올림 전 값)
    return out["zone"]


def test_front_edges_are_the_server_zone_boundaries(monkeypatch):
    lo, hi = _front_edges()
    eps = 1e-3
    below, grey_lo, grey_hi, above = (_zone(monkeypatch, v) for v in (lo - eps, lo + eps, hi - eps, hi + eps))
    # 경계 아래와 위는 다른 구간이고, 두 경계 사이는 한 구간이다 — 화면 눈금이 서버 판정이 바뀌는 자리에 있다.
    assert below != grey_lo
    assert grey_lo == grey_hi
    assert grey_hi != above
    # 짝: 경계에서 멀리 떨어진 값은 경계 근처 값과 같은 구간이다(판정이 경계에서만 바뀐다 — 공허한 비교가 아니다).
    assert _zone(monkeypatch, lo / 2) == below
    assert _zone(monkeypatch, hi * 1.5) == above


def test_server_zone_labels_name_the_same_numbers():
    """구간 이름 글자에도 같은 숫자가 들어 있다(화면은 이 글자를 그대로 보인다)."""
    lo, hi = _front_edges()
    src = pathlib.Path(ca.__file__).read_text(encoding="utf-8")
    assert f"{lo}~{hi}" in src
