"""매크로 민감도 — 서술이 아니라 수치 (P2-4 커밋 ②)

설계 문서 C.3 이 요구한 것은 `+100bp 10Y → 적정가치 −8.4%` 같은 **수치**다.
그러므로 이 파일이 거는 것은 세 가지다: 충격이 실제로 전파되는가 · **비대칭**을
지우지 않는가 · **낼 수 없는 것**을 낼 수 있는 척하지 않는가.

★스텁을 쓰는 이유★ `FinancialStatement.fcf` 는 property 라 값을 심을 수 없다.
다만 **상류 형식에 대한 가정은 하지 않는다** — 이 세션에서 합성 입력만 쓰다가
결함 둘을 놓쳤으므로, 실제 경로 확인은 `test_macro_sensitivity_wiring.py` 가 한다.
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from types import SimpleNamespace  # noqa: E402

import pytest  # noqa: E402

from src.engine.valuation.macro_sensitivity import (  # noqa: E402
    DEFAULT_RATE_SHOCKS_BP,
    macro_sensitivity,
)
from src.engine.valuation.valuation_models import ValuationParams  # noqa: E402


def _fs(**kw) -> SimpleNamespace:
    base = dict(
        fcf=15_750_000_000_000.0, shares_outstanding=5_969_782_550,
        total_equity=364_000_000_000_000.0, total_liabilities=102_000_000_000_000.0,
        revenue=315_000_000_000_000.0, net_income=32_000_000_000_000.0,
        roe=8.79, eps=5360.0, bps=60975.0, dps=1500.0,
        operating_profit=26_000_000_000_000.0, total_assets=466_000_000_000_000.0,
        payout_ratio=28.0, dividend_yield=2.1, roa=6.9, debt_ratio=28.0,
    )
    base.update(kw)
    return SimpleNamespace(**base)


PARAMS = ValuationParams(risk_free_rate=0.0457, market_premium=0.06, beta=1.11,
                         terminal_growth_rate=0.02, projection_years=10)


def _rows(out) -> dict:
    return {r["shock"]: r for r in out["rows"]}


# ── 1. 충격이 실제로 전파된다 ───────────────────────────────────────────────
def test_a_rate_shock_moves_the_value_in_the_right_direction():
    out = macro_sensitivity(_fs(), PARAMS)
    assert out["available"] is True, out["reason"]
    rows = _rows(out)

    up = rows["+100bp 10Y"]
    down = rows["-100bp 10Y"]
    # 금리가 오르면 할인율이 오르고 적정가치는 내린다.
    assert up["value_pct"] < 0 and up["direction"] == "하락"
    assert down["value_pct"] > 0 and down["direction"] == "상승"


def test_the_method_says_it_is_not_a_statistical_estimate():
    """★통계 추정이 아니라 모델의 항등식이다★ 표본도 표준오차도 없다."""
    out = macro_sensitivity(_fs(), PARAMS)
    assert out["method"] == "structural_exact"
    for r in out["rows"]:
        assert r["method"] == "structural_exact"
        assert "rf" in r["channel"]
        # 통계 산출물이 아니므로 이런 필드가 있으면 안 된다.
        assert "n_obs" not in r and "t_stat" not in r
    assert "시장이 그렇게 반응한다는 주장이 아니" in out["note"]


def test_the_shock_is_exact_not_sampled():
    """같은 입력이면 정확히 같은 값 — 난수가 개입하지 않는다."""
    a = macro_sensitivity(_fs(), PARAMS)
    b = macro_sensitivity(_fs(), PARAMS)
    assert a["rows"] == b["rows"]


# ── 2. ★비대칭을 지우지 않는다★ ────────────────────────────────────────────
def test_both_directions_are_reported_separately():
    """★한 방향만 재면 볼록성이 사라진다★ 실측 −100bp +11.62% vs +100bp −9.54%."""
    out = macro_sensitivity(_fs(), PARAMS)
    rows = _rows(out)
    assert set(rows) == {"-100bp 10Y", "+100bp 10Y"}

    up_mag = abs(rows["+100bp 10Y"]["value_pct"])
    down_mag = abs(rows["-100bp 10Y"]["value_pct"])
    assert up_mag != down_mag, "양방향이 같은 크기면 비대칭이 사라진 것이다"


def test_the_asymmetry_is_quantified_not_just_implied():
    out = macro_sensitivity(_fs(), PARAMS)
    a = out["asymmetry"]
    assert a is not None
    assert a["max_abs_pct"] > a["min_abs_pct"]
    assert a["ratio"] > 1.0
    assert "볼록성" in a["note"]


def test_a_single_shock_direction_yields_no_asymmetry_claim():
    """방향이 하나뿐이면 비대칭을 **주장하지 않는다** — 잴 상대가 없다."""
    out = macro_sensitivity(_fs(), PARAMS, rate_shocks_bp=(100,))
    assert out["available"] is True
    assert out["asymmetry"] is None


# ── 3. ★모델별 반응을 통합이 지우지 않는다★ ────────────────────────────────
def test_each_model_reports_its_own_response():
    """실측: 같은 −100bp 에 DCF +25.82% vs RIM +6.32% — 4배 차이다."""
    out = macro_sensitivity(_fs(), PARAMS)
    for r in out["rows"]:
        by = r["by_model_pct"]
        assert set(by) == {"RIM", "DCF", "DDM"}, by
        # 세 모델이 실제로 다르게 반응한다 — 통합이 그것을 가리고 있었다.
        assert len(set(by.values())) == 3, by

    down = _rows(out)["-100bp 10Y"]["by_model_pct"]
    assert abs(down["DCF"]) > abs(down["RIM"]), "DCF 가 금리에 가장 민감해야 한다"


def test_the_base_value_is_reported_per_model_too():
    out = macro_sensitivity(_fs(), PARAMS)
    assert out["base_value"] > 0
    assert set(out["base_by_model"]) == {"RIM", "DCF", "DDM"}


# ── 4. ★낼 수 없는 것을 낼 수 있는 척하지 않는다★ ──────────────────────────
def test_the_channels_that_do_not_exist_say_why():
    """★빈칸이 아니라 사유가 언더라이팅의 정보다★

    EPS·EBIT 는 밸류에이션 모델의 **입력**이지 출력이 아니고, 유가 계열은 수집기에
    아예 없다. 연간 재무 10행으로 매크로→EPS 회귀를 지어내는 것이 날조다.
    """
    out = macro_sensitivity(_fs(), PARAMS)
    un = {u["shock"]: u for u in out["unavailable"]}
    assert set(un) == {"GDP −2σ", "USD +10%", "Oil +30%"}

    for u in un.values():
        assert u["available"] is False
        assert u["reason"]
        # 값을 0 으로 채우지 않는다.
        assert "value_pct" not in u

    assert "입력" in un["GDP −2σ"]["reason"]
    assert "유가 계열" in un["Oil +30%"]["reason"]
    assert un["Oil +30%"]["target"] == "EBIT"


# ── 5. 산출 불가는 사유 ─────────────────────────────────────────────────────
def test_a_company_with_no_computable_value_gets_a_reason():
    dead = _fs(fcf=0.0, shares_outstanding=0, total_equity=0.0,
               eps=None, bps=None, dps=None, net_income=0.0)
    out = macro_sensitivity(dead, PARAMS)
    assert out["available"] is False
    assert out["rows"] == [] and out["reason"]


def test_a_missing_statement_is_refused():
    out = macro_sensitivity(None, PARAMS)
    assert out["available"] is False and out["reason"]


def test_a_shock_that_drives_the_rate_negative_is_refused_not_clamped():
    """★클램프하면 충격이 실제보다 작게 보인다★ 음수 금리는 사유로 답한다."""
    low = ValuationParams(risk_free_rate=0.005, market_premium=0.06, beta=1.0,
                          terminal_growth_rate=0.002, projection_years=10)
    out = macro_sensitivity(_fs(), low, rate_shocks_bp=(-200, 100))
    rows = _rows(out)
    neg = rows["-200bp 10Y"]
    assert neg["available"] is False
    assert "음수" in neg["reason"]
    assert neg.get("value_pct") is None
    # 나머지 충격은 멀쩡히 나온다.
    assert rows["+100bp 10Y"]["available"] is True


def test_the_default_shocks_are_symmetric_in_magnitude():
    """기본값이 한쪽으로 치우쳐 있으면 비대칭 측정 자체가 성립하지 않는다."""
    assert sorted(abs(bp) for bp in DEFAULT_RATE_SHOCKS_BP) == [100, 100]
    assert min(DEFAULT_RATE_SHOCKS_BP) < 0 < max(DEFAULT_RATE_SHOCKS_BP)
