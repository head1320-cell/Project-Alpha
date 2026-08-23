"""확률적 밸류에이션 P10~P90 (P2-3 커밋 ①)

지금 Company 는 적정가를 **점 하나**로 낸다. 이 모듈은 그것을 확률 진술로 바꾼다.
그러므로 가장 중요한 테스트는 "분위수가 나온다" 가 아니라 **"폭이 정직한가"** 다:
클램프로 좁히지 않는가 · 모델 불일치를 평균이 지우지 않는가 · 가정인 폭을 가정이라
적는가.

★스텁을 쓰는 이유★ `FinancialStatement.fcf` 는 property 라 값을 심을 수 없고
(`dart_client.py:47`), TV 발산·모델 미가용 같은 경계는 실데이터에서만 열린다.
`compute_*` 가 실제로 읽는 속성만 가진 스텁으로 재현 가능하게 만든다.
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from types import SimpleNamespace  # noqa: E402

import pytest  # noqa: E402

from src.engine.valuation.valuation_distribution import (  # noqa: E402
    SEED,
    repo_widths,
    valuation_distribution,
)
from src.engine.valuation.valuation_models import ValuationParams  # noqa: E402


def _fs(**kw) -> SimpleNamespace:
    """실측 mock 삼성전자 규모 — `compute_rim`/`dcf`/`ddm` 이 읽는 속성."""
    base = dict(
        fcf=15_750_000_000_000.0, shares_outstanding=5_969_782_550,
        total_equity=364_000_000_000_000.0, total_liabilities=102_000_000_000_000.0,
        revenue=315_000_000_000_000.0, net_income=32_000_000_000_000.0,
        roe=8.79, eps=5360.0, bps=60975.0, dps=1500.0,
        operating_profit=26_000_000_000_000.0, total_assets=466_000_000_000_000.0,
        # ★속성으로 읽히므로 없으면 `or 30` 이 안 먹고 AttributeError 로 모델이
        # 통째로 죽는다★ 처음 빠뜨렸더니 RIM·DDM 이 available:false 로 나왔다.
        payout_ratio=28.0, dividend_yield=2.1, roa=6.9, debt_ratio=28.0,
    )
    base.update(kw)
    return SimpleNamespace(**base)


PARAMS = ValuationParams(risk_free_rate=0.0457, market_premium=0.06, beta=1.11,
                         terminal_growth_rate=0.02, projection_years=10)
N = 400   # 테스트는 빠르게 — 성질은 표본 수와 무관하다


def _dist(**kw):
    kw.setdefault("n", N)
    return valuation_distribution(_fs(), PARAMS, 71000.0, **kw)


# ── 1. ★결정론★ 재현 좌표가 응답에 남는다 ──────────────────────────────────
def test_the_same_seed_gives_the_same_distribution():
    a, b = _dist(), _dist()
    assert a["unified"] == b["unified"]
    assert a["seed"] == SEED


def test_a_different_seed_gives_a_different_distribution():
    a = _dist()
    b = _dist(seed=SEED + 1)
    assert a["unified"]["p50"] != b["unified"]["p50"]
    assert b["seed"] == SEED + 1


# ── 2. 분위수 순서와 중심 ───────────────────────────────────────────────────
def test_the_percentiles_are_ordered_and_centred_on_the_base_case():
    from src.engine.valuation.valuation_distribution import _models_for
    from src.engine.valuation.valuation_models import weighted_intrinsic

    out = _dist()
    u = out["unified"]
    assert u["p10"] <= u["p25"] <= u["p50"] <= u["p75"] <= u["p90"]

    base = weighted_intrinsic(_models_for(_fs(), PARAMS), PARAMS)
    # 중앙값이 기본 가정 근처여야 한다 — 아니면 표본이 한쪽으로 쏠린 것이다.
    assert u["p10"] < base < u["p90"]


# ── 3. ★모델 불일치가 통합에 접히지 않는다★ (이 슬라이스의 핵심) ────────────
def test_the_per_model_distributions_survive_the_weighted_average():
    """★실측: 모델 불일치(약 3배)가 파라미터 불확실성(±16%)보다 크다★

    통합값 하나만 내면 더 큰 쪽이 사라진다. 평균이 그것을 지우기 때문이다.
    """
    out = _dist()
    by = out["by_model"]
    assert set(by) == {"RIM", "DCF", "DDM"}
    for m in by.values():
        assert m["available"] is True
        assert m["p10"] <= m["p50"] <= m["p90"]

    # 세 모델의 중앙값이 실제로 다르다 — 통합이 그것을 가리고 있었다.
    medians = {k: v["p50"] for k, v in by.items()}
    assert len(set(medians.values())) == 3, medians

    dis = out["model_disagreement"]
    assert dis["spread_ratio"] > 1.5, dis
    # ★그리고 불일치가 통합 분포의 폭보다 크다★ — 그것이 이 필드의 존재 이유다.
    unified_ratio = out["unified"]["p90"] / out["unified"]["p10"]
    assert dis["spread_ratio"] > unified_ratio, (dis["spread_ratio"], unified_ratio)


# ── 4. ★폭을 넓히면 분포가 넓어진다★ (인위적 축소가 없다는 짝 단언) ─────────
def test_doubling_the_widths_widens_the_distribution():
    narrow = _dist()
    w = repo_widths()
    for k in ("rf", "g", "erp", "beta"):
        w[k] = {**w[k], "sigma": w[k]["sigma"] * 2}
    wide = valuation_distribution(_fs(), PARAMS, 71000.0, n=N, widths=w)

    n_spread = narrow["unified"]["p90"] - narrow["unified"]["p10"]
    w_spread = wide["unified"]["p90"] - wide["unified"]["p10"]
    assert w_spread > n_spread * 1.5, (n_spread, w_spread)


# ── 5. ★클램프가 아니라 기각★ 경계에 질량이 쌓이지 않는다 ──────────────────
def test_terminal_growth_violations_are_rejected_and_counted():
    """`g ≥ ke − _TV_GAP` 은 TV 발산 조건이다 — `valuation_sandbox` 와 같은 상수.

    경계로 클램프하면 그 값에 표본이 쌓여 분포가 인위적으로 좁아진다. 버리고 센다.
    """
    # ke 를 낮추고(β·erp↓) g 를 ke 근처로 올려 발산 구간을 실제로 밟는다.
    tight = ValuationParams(risk_free_rate=0.02, market_premium=0.01, beta=0.3,
                            terminal_growth_rate=0.021, projection_years=10)
    out = valuation_distribution(_fs(), tight, 71000.0, n=N)

    assert out["n_rejected"] > 0, "발산 구간을 하나도 안 밟았다 — 프로브가 무효다"
    assert out["rejections"]["terminal_growth_above_ke"] > 0
    assert out["n_used"] + out["n_rejected"] == out["n_requested"]

    if out["available"]:
        # 경계값에 질량이 쌓이지 않았다 — 같은 값이 표본의 태반을 차지하면 클램프다.
        u = out["unified"]
        assert u["p10"] < u["p90"], "분포가 한 점으로 무너졌다"


def test_too_few_valid_samples_answers_with_a_reason_not_quantiles():
    """★적은 표본에서 뽑은 P10 은 분위수가 아니라 잡음이다★

    ★처음 이 테스트는 하한을 전혀 지키지 않았다★ 표본을 **전부** 기각시키는
    파라미터를 써서 `n_used == 0` 이었고, 그러면 하한이 있든 없든 unavailable 이라
    "하한 제거" 프로브가 green 이었다. 하한의 진짜 일은 **중간 구간** — 분위수를
    계산할 수는 있지만 믿을 수 없는 표본 수다.

    격자 스캔으로 그 구간을 찾았다(n=400): g=0.045→202개(50%) · g=0.050→109개(27%,
    턱걸이 통과) · **g=0.052→84개(21%, 막힘)** · g=0.058→30개(8%).
    그래서 여기서는 **84개가 유효한데도** 숫자를 내지 않는 것을 건다.
    """
    thin = ValuationParams(risk_free_rate=0.02, market_premium=0.03, beta=1.0,
                           terminal_growth_rate=0.052, projection_years=10)
    out = valuation_distribution(_fs(), thin, 71000.0, n=N)

    assert out["available"] is False
    assert out["unified"] is None
    # ★유효 표본이 0 이 아니다★ 분위수를 낼 수는 있었지만 내지 않았다는 것이 요점이다.
    assert 0 < out["n_used"] < N
    assert out["reason"] and "유효 표본" in out["reason"]
    assert str(out["n_used"]) in out["reason"]
    # 몇 개가 왜 버려졌는지 함께 말한다 — 안 적으면 되짚을 수 없다.
    assert out["rejections"]["terminal_growth_above_ke"] > 0


def test_a_sample_count_just_above_the_floor_still_answers():
    """★짝★ 하한이 자의적 거부가 아니라 **선**임을 보인다 — 27% 는 통과한다."""
    ok = ValuationParams(risk_free_rate=0.02, market_premium=0.03, beta=1.0,
                         terminal_growth_rate=0.050, projection_years=10)
    out = valuation_distribution(_fs(), ok, 71000.0, n=N)
    assert out["available"] is True, out["reason"]
    assert out["n_rejected"] > 0, "기각이 하나도 없으면 하한 근처가 아니다"


# ── 6. 현재 주가의 분위 — 그림을 확률 진술로 바꾸는 한 줄 ───────────────────
def test_the_price_percentile_moves_with_the_price():
    lo = valuation_distribution(_fs(), PARAMS, 20000.0, n=N)["unified"]["price_percentile"]
    hi = valuation_distribution(_fs(), PARAMS, 60000.0, n=N)["unified"]["price_percentile"]
    assert 0.0 <= lo <= hi <= 100.0
    assert hi > lo


def test_no_price_means_no_percentile_rather_than_a_zero():
    out = valuation_distribution(_fs(), PARAMS, None, n=N)
    assert out["available"] is True
    assert "price_percentile" not in out["unified"]


# ── 7. ★가정인 폭을 가정이라고 적는다★ ─────────────────────────────────────
def test_no_width_claims_to_be_measured():
    """★처음에는 β 만 `measured:false` 로 두려 했다★

    그러면 나머지 셋이 측정된 것처럼 읽힌다. `_KE_STEPS` 는 누군가 고른 탐색
    범위이지 추정 표준오차가 아니다 — 넷 다 가정이다.
    """
    w = _dist()["widths"]
    for key in ("rf", "g", "erp", "beta", "rf_g_correlation"):
        assert w[key]["measured"] is False, f"{key} 가 측정된 것처럼 나온다"
        assert w[key]["source"]
    assert "측정된 것은 하나도 없다" in w["note"]


def test_the_widths_are_derived_from_the_repo_not_hardcoded(monkeypatch):
    """★짝★ `_KE_STEPS` 를 넓히면 분포도 함께 넓어진다 — 상수를 베끼지 않았다."""
    narrow = _dist()["unified"]
    monkeypatch.setattr("src.engine.company_analytics._KE_STEPS",
                        (-0.05, -0.025, 0.0, 0.025, 0.05))
    wide = _dist()["unified"]
    assert (wide["p90"] - wide["p10"]) > (narrow["p90"] - narrow["p10"])


def test_the_beta_width_names_why_it_is_an_assumption():
    b = repo_widths()["beta"]
    assert "표준오차를 노출하지 않는다" in b["source"]


# ── 8. ★지배 파라미터가 우리가 가장 모르는 값이다★ ─────────────────────────
def test_the_dominant_driver_is_reported_with_every_parameter_spread():
    """계획할 때는 rf 가 지배할 것으로 봤는데 실측은 β 였다 — 그리고 β 는
    폭이 순수한 가정인 유일한 항목이다. 둘을 함께 읽어야 한다."""
    d = _dist()["dominant_driver"]
    assert d["available"] is True
    assert d["driver"] in ("rf", "g", "erp", "beta")
    assert set(d["spread_by_param"]) == {"rf", "g", "erp", "beta"}
    assert d["spread_by_param"][d["driver"]] == max(d["spread_by_param"].values())


# ── 9. 결합 표본은 일변량 격자보다 넓다 ─────────────────────────────────────
def test_the_joint_sample_is_wider_than_the_one_at_a_time_grid():
    """격자는 한 번에 하나씩 흔든다 — 넷을 동시에 뽑으면 당연히 더 넓다.

    그 사실을 숨기면 "격자와 왜 다르냐" 는 물음에 답할 수 없다.
    """
    ke = _dist()["induced_ke"]
    assert ke["p10"] < ke["base_pct"] < ke["p90"]
    grid_half_pct = repo_widths()["rf"]["half_width_90"] * 100
    assert (ke["p90"] - ke["p10"]) / 2 > grid_half_pct * 0.8
    assert "격자" in ke["note"]


# ── 10. 산출 불가는 사유 ────────────────────────────────────────────────────
def test_a_company_with_no_computable_value_gets_a_reason():
    dead = _fs(fcf=0.0, shares_outstanding=0, total_equity=0.0, eps=None,
               bps=None, dps=None, net_income=0.0)
    out = valuation_distribution(dead, PARAMS, 71000.0, n=N)
    assert out["available"] is False
    assert out["reason"]


def test_a_missing_statement_is_refused():
    out = valuation_distribution(None, PARAMS, 71000.0, n=N)
    assert out["available"] is False and out["reason"]


def test_the_sample_count_is_capped():
    from src.engine.valuation.valuation_distribution import MAX_N
    out = valuation_distribution(_fs(), PARAMS, 71000.0, n=10**9)
    assert out["n_requested"] == MAX_N
