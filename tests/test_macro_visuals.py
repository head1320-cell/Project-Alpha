"""매크로 시각화 데이터 엔진 (밸리AI 장점 흡수) — TDD.

① cycle_strips: 지표×월 변환 z 그리드 (사이클 분석 스트립)
② axis_history: 월별 축 스코어 + 지표별 기여 (하위요인 시계열 분해)
③ asset_strips: 자산군 가격 위치 백분위 스트립 (정직 — 시세 기반, 멀티플 아님)
④ kr_us_compare: KR vs US 지표 나란히 비교 (2국 정직 버전)
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.engine import macro_visuals as mv  # noqa: E402


class _S:
    def __init__(self, values, timestamps=None):
        self.values = values
        self.timestamps = timestamps or [f"2024-{(i % 12) + 1:02d}" for i in range(len(values))]
        self.source = "mock"


def _smap(n=80):
    import math
    cpi = [100 * (1.003 ** i) for i in range(n)]
    ip = [100 + 10 * math.sin(i / 9) for i in range(n)]
    r10 = [3.0 + 0.5 * math.sin(i / 12) for i in range(n)]
    return {"KR_CPI": _S(cpi), "KR_IP": _S(ip), "KR_10Y": _S(r10),
            "CPIAUCSL": _S(cpi), "INDPRO": _S(ip), "DGS10": _S(r10),
            "KOSPI": _S([2000 + 30 * i for i in range(n)]),
            "T10YIE": _S([2.2] * n), "USD_KRW": _S([1300 + i for i in range(n)]),
            "KR_LEADING_CYCLE": _S([100 + math.sin(i / 8) for i in range(n)])}


def test_cycle_strips_shape_and_transform():
    out = mv.cycle_strips(_smap(), market="kr", months=18)
    assert out["months"] and len(out["months"]) == 18
    assert out["indicators"], "지표 스트립이 비어있음"
    row = next(r for r in out["indicators"] if r["key"] == "KR_CPI")
    assert row["transform"] == "yoy"           # 지수형은 YoY z (레벨 z 금지)
    assert len(row["cells"]) == 18
    assert all(c is None or -6 < c < 6 for c in row["cells"])


def test_axis_history_components_stack():
    out = mv.axis_history(_smap(), market="kr", months=12)
    assert len(out["points"]) == 12
    p = out["points"][-1]
    assert set(p) >= {"t", "growth", "inflation", "growth_parts", "inflation_parts"}
    # 스택 항등: 기여 합 ≈ 축 스코어
    assert abs(sum(p["growth_parts"].values()) - p["growth"]) < 1e-6
    assert abs(sum(p["inflation_parts"].values()) - p["inflation"]) < 1e-6


def test_asset_strips_percentile_range(monkeypatch):
    import src.engine.macro_visuals as mvmod
    # 합성 월간 종가 — 최근이 역사 최고가인 자산
    monkeypatch.setattr(mvmod, "_monthly_closes",
                        lambda tk, mk, n: [100 + i for i in range(72)])
    out = mv.asset_strips(market="kr", months=12)
    assert out["assets"], "자산 스트립 비어있음"
    a = out["assets"][0]
    assert len(a["cells"]) == 12
    assert all(c is None or 0 <= c <= 100 for c in a["cells"])
    assert a["cells"][-1] and a["cells"][-1] > 90   # 최고가 → 백분위 상단
    assert "시세 기반" in out["note"]                # 정직 라벨(멀티플 아님)


def test_kr_us_compare_rows():
    out = mv.kr_us_compare(_smap())
    assert out["rows"]
    cpi = next(r for r in out["rows"] if "CPI" in r["label"])
    assert "kr" in cpi and "us" in cpi
    assert cpi["kr"] is None or -6 < cpi["kr"] < 6
