"""매크로 탭 대개편 (CIO 리팩토링) — 핵심 계약 TDD.

① 사분면 명명 통일: Goldilocks(성장↑물가↓)/Reflation(성장↑물가↑)/Stagflation/Disinflation
   ('Deflation' 제거 — 물가 z<0은 상승 둔화이지 하락이 아님. 모듈 간 상충 명명도 단일화)
② 축 분해(breakdown): 지표별 변환 z·가중·기여 + 불확실성(se) — "CPI +2.17σ인데 축 -0.28"
   모순의 근본 해결(표시 z와 축 입력 z의 일치·투명화) + 레벨/모멘텀 블렌드
③ 스트레스 v2: 장단기 금리차(역전 패널티) + 실질금리 z 반영 — "긴축인데 Normal 44" 수정
④ 국면 확률: P(사분면) 4종 합=1, 신뢰도=최대확률 (정적 % → 확률 분포)
⑤ 매크로 임베딩 자산배분: 국면 스코어 → 4계절 틸트 + 기여 분해 + MC 신뢰구간
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.engine import regime_axes as ra  # noqa: E402


class _S:
    def __init__(self, values, source="mock"):
        self.values = values
        self.source = source
        self.latest = values[-1] if values else None
        self.z_score = None
        self.mom_pct = None
        self.trend = "flat"


# ── ① 사분면 명명 ──

def test_quadrant_unified_names():
    assert ra.quadrant(1, -1) == "Goldilocks"
    assert ra.quadrant(1, 1) == "Reflation"
    assert ra.quadrant(-1, 1) == "Stagflation"
    assert ra.quadrant(-1, -1) == "Disinflation"   # Deflation 아님 (물가 상승 둔화)


# ── ② 축 분해 + 모멘텀 블렌드 ──

def _mk_series(vals):
    return {"CPIAUCSL": _S(vals), "T10YIE": _S([2.0 + 0.01 * i for i in range(len(vals))])}


def test_axis_detail_components_and_se():
    # CPI 지수: YoY 안정 상승 (지수 100 → 매월 +0.3%)
    vals = [100 * (1.003 ** i) for i in range(80)]
    d = ra.compute_axis_detail(_mk_series(vals), ra.US_INFLATION)
    assert set(d) >= {"score", "se", "components"}
    assert d["se"] >= 0
    comps = {c["key"]: c for c in d["components"]}
    assert "CPIAUCSL" in comps
    c = comps["CPIAUCSL"]
    assert set(c) >= {"z", "z_mom", "weight", "contribution", "transform"}
    assert c["transform"] == "yoy"    # 축 입력은 YoY 변환 z (레벨 z 아님 — 표시 일치용)
    # 가중 기여 합 == score
    assert abs(sum(x["contribution"] for x in d["components"]) - d["score"]) < 1e-2


def test_axis_momentum_blend_reacts_to_deceleration():
    """레벨은 역사 대비 높지만(z>0) 최근 하락 반전 → 모멘텀 블렌드 축 < 순수 레벨 축.

    단일 지표(level)로 격리 — 'CPI가 높아도 감속이면 물가 축이 내려간다'는 계약."""
    vals = [float(i) for i in range(74)] + [72.0, 71.0, 70.0, 69.0, 68.0, 67.0]  # 상승 후 반락
    smap = {"X": _S(vals)}
    axis_def = [("X", "level", 1, 1.0)]
    level_only = ra.compute_axis_detail(smap, axis_def, momentum_weight=0.0)["score"]
    blended = ra.compute_axis_detail(smap, axis_def)["score"]
    assert level_only > 0, "레벨 z는 여전히 양수여야 (역사 대비 높은 수준)"
    assert blended < level_only, "하락 반전 국면에서 모멘텀 블렌드가 축을 낮춰야"


# ── ③ 스트레스 v2 ──

def _stress_series(spread_10y2y=1.2, real_rate_z_high=False):
    n = 80
    dgs2 = [3.0] * n
    dgs10 = [3.0 + spread_10y2y] * n
    t10yie = [2.2] * n
    if real_rate_z_high:  # 실질금리 급등 = 기대인플레 급락 (스프레드는 유지 — 역전 보존)
        t10yie = [2.2] * (n - 6) + [2.2 - 0.3 * i for i in range(1, 7)]
    vix = [15.0] * n
    return {"DGS2": _S(dgs2), "DGS10": _S(dgs10), "T10YIE": _S(t10yie), "VIXCLS": _S(vix)}


def test_stress_penalizes_inversion_and_real_rate():
    from src.engine.regime_analyzer import RegimeAnalyzer
    an = RegimeAnalyzer.__new__(RegimeAnalyzer)   # collector 불필요 (순수 계산)
    calm, _ = an._compute_stress(_stress_series(spread_10y2y=1.5))
    inverted, comp = an._compute_stress(_stress_series(spread_10y2y=-0.6, real_rate_z_high=True))
    assert "yield_curve" in comp and "real_rate" in comp
    assert inverted > calm + 10, f"역전+실질금리 긴축인데 스트레스 증가 미미: {calm}→{inverted}"
    assert inverted >= 55, "긴축 상태가 Normal(≈44)로 나오면 안 됨"


# ── ④ 국면 확률 ──

def test_quadrant_probabilities_sum_to_one():
    probs = ra.quadrant_probs(growth=0.8, inflation=-0.5, se_g=0.4, se_i=0.4)
    assert abs(sum(probs.values()) - 1.0) < 1e-3   # 표시용 4자리 라운딩 허용
    assert set(probs) == {"Goldilocks", "Reflation", "Stagflation", "Disinflation"}
    assert max(probs, key=probs.get) == "Goldilocks"   # g>0, i<0
    assert 0 < probs["Goldilocks"] < 1


# ── ⑤ 매크로 임베딩 자산배분 ──

def test_macro_allocation_regime_direction():
    from src.engine.macro_allocation import macro_embedded_allocation
    # Disinflation(성장↓·물가↓) → 채권(TLT/IEF) 비중 > 주식(SPY/QQQ)
    dis = macro_embedded_allocation(growth=-1.2, inflation=-1.0, stress=45, se_g=0.3, se_i=0.3)
    w = {h["us_ticker"]: h["weight"] for h in dis["holdings"]}
    bonds = w.get("TLT", 0) + w.get("IEF", 0)
    equity = w.get("SPY", 0) + w.get("QQQ", 0)
    assert bonds > equity, f"Disinflation인데 채권({bonds}) ≤ 주식({equity})"
    assert abs(sum(w.values()) - 100.0) < 0.5
    # Reflation(성장↑·물가↑) → 원자재 확대, 장기채 축소
    ref = macro_embedded_allocation(growth=1.2, inflation=1.0, stress=45, se_g=0.3, se_i=0.3)
    w2 = {h["us_ticker"]: h["weight"] for h in ref["holdings"]}
    assert w2.get("DBC", 0) + w2.get("GLD", 0) > w.get("DBC", 0) + w.get("GLD", 0)
    assert w2.get("TLT", 0) < w.get("TLT", 0)


def test_macro_allocation_stress_derisks():
    from src.engine.macro_allocation import macro_embedded_allocation
    lo = macro_embedded_allocation(growth=1.0, inflation=0.0, stress=30, se_g=0.3, se_i=0.3)
    hi = macro_embedded_allocation(growth=1.0, inflation=0.0, stress=85, se_g=0.3, se_i=0.3)
    cash = lambda r: next((h["weight"] for h in r["holdings"] if h["us_ticker"] == "BIL"), 0)  # noqa: E731
    assert cash(hi) > cash(lo), "고스트레스에서 현금성 비중이 늘어야"


def test_macro_allocation_attribution_and_bands():
    from src.engine.macro_allocation import macro_embedded_allocation
    r = macro_embedded_allocation(growth=0.9, inflation=-0.4, stress=55, se_g=0.35, se_i=0.35)
    # 기여 분해: 자산별 (base + growth + inflation + stress 기여 == 최종) 항등
    for a in r["attribution"]:
        recon = a["base"] + a["growth"] + a["inflation"] + a["stress"]
        assert abs(recon - a["final"]) < 0.51, f"{a['ticker']} 기여 분해 불일치"
    # MC 신뢰구간: p10 <= p50 <= p90, 시드 고정 재현
    for b in r["bands"]:
        assert b["p10"] <= b["p50"] <= b["p90"]
    r2 = macro_embedded_allocation(growth=0.9, inflation=-0.4, stress=55, se_g=0.35, se_i=0.35)
    assert r["bands"] == r2["bands"], "MC가 시드 고정으로 재현돼야"


def test_recommend_includes_macro_allocation():
    from src.engine.macro_recommender import recommend
    out = recommend("kr")
    assert "macro_allocation" in out, "매크로 임베딩 배분이 추천 응답에 포함돼야"
    ma = out["macro_allocation"]
    assert ma["holdings"] and "attribution" in ma and "bands" in ma
    assert "regime_probs" in out and abs(sum(out["regime_probs"].values()) - 1.0) < 1e-3
