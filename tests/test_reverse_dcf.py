"""역DCF — 시장이 믿고 있는 가정을 되짚는다 (P2-2 커밋 ①)

`compute_dcf` 는 가정 → 내재가치다. 역DCF 는 그 역함수이므로 **첫 테스트는 왕복**이다:
성장률 g 로 정방향을 돌려 나온 주가를 역DCF 에 넣으면 g 가 다시 나와야 한다. 그것이
아니면 이 모듈은 근을 찾는 척하는 것이다.

★스텁을 쓰는 이유★ `FinancialStatement.fcf` 는 **property** 라 값을 심을 수 없다
(`dart_client.py:47`). 적자·마이너스 FCF 경로는 실데이터에서만 열리는데(mock 은 항상
흑자다 — CLAUDE.md) 그 경로가 정확히 이 모듈에서 가장 위험한 자리이므로, `compute_dcf`
가 실제로 읽는 속성만 가진 스텁으로 **재현 가능하게** 만든다.
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from types import SimpleNamespace  # noqa: E402

import pytest  # noqa: E402

from src.engine.valuation.reverse_dcf import (  # noqa: E402
    _solve,
    reverse_dcf,
)
from src.engine.valuation.valuation_models import ValuationParams, compute_dcf  # noqa: E402


def _fs(*, fcf=15_750_000_000_000.0, shares=5_969_782_550,
        equity=364_000_000_000_000.0, liabilities=102_000_000_000_000.0,
        revenue=315_000_000_000_000.0, roe=8.0) -> SimpleNamespace:
    """`compute_dcf` 가 실제로 읽는 속성만 — 실측 mock 삼성전자 규모."""
    return SimpleNamespace(fcf=fcf, shares_outstanding=shares, total_equity=equity,
                           total_liabilities=liabilities, revenue=revenue, roe=roe)


PARAMS = ValuationParams()


def _forward(fs, g: float) -> float:
    r = compute_dcf(fs, PARAMS, fcf_growth_rates=[g] * PARAMS.projection_years)
    assert r.available
    return float(r.intrinsic_value_per_share)


# ── 1. ★왕복★ 정방향의 답을 넣으면 그 가정이 나온다 ────────────────────────
@pytest.mark.parametrize("g", [0.00, 0.05, 0.1142, 0.25])
def test_the_solver_recovers_the_growth_that_produced_the_price(g):
    fs = _fs()
    price = _forward(fs, g)
    out = reverse_dcf(fs, PARAMS, price)

    assert out["available"] is True, out["reason"]
    # 계단함수라 정확히 g 로 떨어지지는 않는다 — 계단 하나(Δg≈1.7e-6) 폭 안이면 된다.
    assert out["implied_growth_pct"] == pytest.approx(g * 100, abs=0.01)


def test_the_market_price_is_actually_reproduced(_=None):
    """★"정확히 풀었다" 고 말하지 않는다★ 달성치와 목표의 격차를 함께 낸다."""
    fs = _fs()
    out = reverse_dcf(fs, PARAMS, 71000.0)
    assert out["available"]
    assert out["achieved_price"] == pytest.approx(71000.0, abs=2.0)
    # 실측 계단 폭은 Δg≈1.7e-6 당 1원 — xtol 1e-7 이면 원 단위 아래로 떨어진다.
    assert abs(out["price_gap_won"]) <= 2.0


# ── 2. ★짝★ 비싸면 더 높은 성장을 함의한다 ──────────────────────────────────
def test_a_higher_price_implies_higher_growth():
    fs = _fs()
    a = reverse_dcf(fs, PARAMS, 40000.0)
    b = reverse_dcf(fs, PARAMS, 90000.0)
    assert a["available"] and b["available"]
    assert b["implied_growth_pct"] > a["implied_growth_pct"]


def test_the_current_assumption_equivalent_reproduces_the_base_dcf():
    """★내부 정합성★ 시장가가 우리 DCF 값과 같으면 내재 성장률 = 현재 가정이다.

    두 숫자가 서로 다른 경로에서 나오므로, 일치는 우연이 아니라 solver 가 옳다는 증거다.
    """
    fs = _fs()
    base = compute_dcf(fs, PARAMS)
    out = reverse_dcf(fs, PARAMS, float(base.intrinsic_value_per_share))
    assert out["available"]
    assert out["implied_growth_pct"] == pytest.approx(out["current_growth_pct"], abs=0.02)
    assert out["gap_pp"] == pytest.approx(0.0, abs=0.02)


# ── 3. ★적자·마이너스 FCF 는 숫자가 아니라 사유★ ───────────────────────────
@pytest.mark.parametrize("kw", [{"fcf": -1_000_000_000_000.0}, {"fcf": 0.0},
                                {"shares": 0}, {"shares": None}])
def test_a_company_with_no_positive_fcf_gets_a_reason_not_a_number(kw):
    """★mock 은 항상 흑자라 이 경로는 실데이터에서만 열린다★ (CLAUDE.md)

    근이 존재하지 않는 경우이므로 브래킷 끝값을 답으로 내밀지 않는다.
    """
    out = reverse_dcf(_fs(**kw), PARAMS, 71000.0)
    assert out["available"] is False
    assert out["implied_growth_pct"] is None
    assert out["reason"] and "역산의 대상이 없습니다" in out["reason"]


def test_a_missing_price_is_refused():
    for price in (None, 0.0, -1.0):
        out = reverse_dcf(_fs(), PARAMS, price)
        assert out["available"] is False and out["reason"]


# ── 4. ★근이 없으면 방향을 말한다★ 빈 답이 아니다 ──────────────────────────
def test_a_price_above_the_bracket_reports_the_direction():
    out = reverse_dcf(_fs(), PARAMS, 5_000_000.0)
    assert out["available"] is False
    assert out["direction"] == "above_bracket"
    assert out["implied_growth_pct"] is None
    assert "브래킷 상단" in out["reason"]


def test_a_price_below_a_raised_bracket_reports_the_other_direction():
    """★기본 브래킷에서는 이 가지가 구조적으로 도달 불가다★

    `per_share = max(0, …)` 이므로 하단 값은 0 이고 주가는 항상 양수라
    `f(g_lo) > 0` 이 될 수 없다. 바닥을 올린 브래킷으로만 열린다 — 그래서 여기서
    명시적으로 연다(가지가 있는데 한 번도 안 밟히는 상태를 남기지 않는다).
    """
    out = reverse_dcf(_fs(), PARAMS, 30000.0, bracket=(0.20, 0.50))
    assert out["available"] is False
    assert out["direction"] == "below_bracket"
    assert "브래킷 하단" in out["reason"]


def test_an_inverted_bracket_is_refused():
    out = reverse_dcf(_fs(), PARAMS, 71000.0, bracket=(0.5, -0.5))
    assert out["available"] is False and "뒤집" in out["reason"]


# ── 5. ★단조가 아니면 풀지 않는다★ ─────────────────────────────────────────
def test_a_non_monotone_curve_is_refused_rather_than_solved():
    """brentq 는 부호변화만 본다 — 단조가 아니면 근이 유일하지 않다."""
    hump = _solve(lambda x: -((x - 0.5) ** 2), -1.0, (0.0, 1.0), 21, "테스트")
    assert hump["ok"] is False
    assert hump["monotonic"] is False
    assert "단조증가하지 않습니다" in hump["reason"]


def test_a_non_monotone_valuation_engine_stops_the_whole_solve(monkeypatch):
    """엔진이 비단조로 바뀌면 역DCF 는 숫자를 내지 않는다(통합 경로)."""
    from src.engine.valuation.valuation_models import ValuationResult

    def _humped(fs, params, fcf_growth_rates=None):
        g = (fcf_growth_rates or [0.0])[0]
        return ValuationResult("DCF", round(100000 - (g - 0.1) ** 2 * 1e6, 0))
    monkeypatch.setattr("src.engine.valuation.reverse_dcf.compute_dcf", _humped)

    out = reverse_dcf(_fs(), PARAMS, 71000.0)
    assert out["available"] is False
    assert out["monotonic"] is False


def test_the_monotonicity_check_reports_unsolvable_points():
    """브래킷 안에 산출 불가 지점이 있으면 그것도 사유다."""
    sol = _solve(lambda x: None if x > 0.2 else 1.0, 1.0, (0.0, 0.5), 11, "테스트")
    assert sol["ok"] is False
    assert "산출할 수 없는" in sol["reason"]


# ── 6. 영구성장률 축 — 진짜 절벽 아래에서만 푼다 ────────────────────────────
def test_the_terminal_growth_axis_stays_below_the_wacc_cliff():
    """★이 축에서는 `(wacc - g) > 0.001` 이 진짜 절벽이다★ TV 가 0 으로 떨어진다."""
    out = reverse_dcf(_fs(), PARAMS, 71000.0)
    assert out["available"]
    tg = out["implied_terminal_growth_pct"]
    assert tg is not None, out["terminal_growth_reason"]
    assert tg < out["wacc_pct"], "영구성장률이 WACC 를 넘으면 TV 가 발산·붕괴한다"


def test_the_terminal_axis_agrees_with_the_assumption_at_the_base_price():
    fs = _fs()
    base = compute_dcf(fs, PARAMS)
    out = reverse_dcf(fs, PARAMS, float(base.intrinsic_value_per_share))
    assert out["implied_terminal_growth_pct"] == pytest.approx(
        PARAMS.terminal_growth_rate * 100, abs=0.05)


# ── 7. ★마진은 라벨 없이 나오지 않는다★ ────────────────────────────────────
def test_the_margin_never_appears_without_its_flat_revenue_label():
    """매출 고정은 **우리가 넣은 가정**이지 시장이 함의한 것이 아니다.

    라벨 없이 "시장내재 마진" 이라 부르면 그것이 조용한 날조다.
    """
    out = reverse_dcf(_fs(), PARAMS, 71000.0)
    m = out["implied_fcf_margin_pct"]
    assert m is not None
    assert m["assumes_flat_revenue"] is True
    assert "매출 구동 DCF" in m["note"]
    assert isinstance(m["value_pct"], float)


def test_no_revenue_means_no_margin_rather_than_a_zero():
    out = reverse_dcf(_fs(revenue=None), PARAMS, 71000.0)
    assert out["available"] is True
    assert out["implied_fcf_margin_pct"] is None


def test_the_fcf_path_carries_its_unit():
    out = reverse_dcf(_fs(), PARAMS, 71000.0)
    path = out["implied_fcf_path"]
    assert path["unit"] == "억원"
    assert len(path["values"]) == PARAMS.projection_years
    # 양의 내재 성장률이면 궤적은 증가한다.
    assert path["values"][-1] > path["values"][0]


# ── 8. ★`load_statement` 추출이 `evaluate` 를 바꾸지 않았다★ ────────────────
#
# 바이트 동일성은 캡처로 한 번 확인했다(추출 전후 f1efe23b… / 15,094 B). 골든 파일을
# 저장소에 남기는 대신, **추출이 되돌려지면 빨개지는 구조적 가드**를 건다 — 준비
# 구간이 다시 `evaluate` 안으로 복사되면 아래 셋이 전부 red 다.

def _engine():
    from src.data.dart_client import DARTClient
    from src.engine.valuation.valuation_models import ValuationEngine
    return ValuationEngine(DARTClient())


def test_evaluate_goes_through_load_statement(monkeypatch):
    """준비 구간이 `evaluate` 안으로 되돌아오면 이 가드가 빨개진다."""
    calls = []
    real = type(_engine()).load_statement

    def _spy(self, code, price, **kw):
        calls.append((code, price, kw))
        return real(self, code, price, **kw)
    monkeypatch.setattr("src.engine.valuation.valuation_models.ValuationEngine."
                        "load_statement", _spy)

    _engine().evaluate("005930", 71000.0)
    assert calls, "evaluate 가 load_statement 를 타지 않는다 — 준비 구간이 복제됐다"


def test_evaluate_reports_no_data_when_the_statement_is_unavailable(monkeypatch):
    monkeypatch.setattr(
        "src.engine.valuation.valuation_models.ValuationEngine.load_statement",
        lambda self, code, price, **kw: {
            "available": False, "fs": None, "corp_name": None,
            "is_mock": True, "reason": "테스트"})

    u = _engine().evaluate("005930", 71000.0)
    assert u.verdict == "데이터 없음"
    assert u.models == []
    assert u.is_mock is True          # 사유가 mock 이었다는 사실을 잃지 않는다
    assert u.intrinsic_value == 0


def test_the_mock_gate_moved_with_the_extraction(monkeypatch):
    """★역DCF 가 이 함수를 타는 한 같은 방어를 공짜로 받는다★

    운영에서 DART 가 실패해 합성 재무로 폴백하면 RIM/DCF/DDM 이 조용히 계산되던
    버그가 있었고, 그 방어가 `load_statement` 안에 있다. 새 경로가 그 구멍을 다시
    열지 않는지 확인한다.
    """
    from src.engine.valuation.reverse_dcf import reverse_dcf_for

    monkeypatch.setattr("src.data.mock_gate.mock_allowed", lambda: False)

    loaded = _engine().load_statement("005930", 71000.0)
    if loaded["available"]:
        pytest.skip("이 환경의 재무가 mock 이 아니다 — 게이트를 태울 수 없다")
    assert "mock" in loaded["reason"]

    out = reverse_dcf_for("005930", 71000.0)
    assert out["available"] is False
    assert out["reason"] == loaded["reason"], "역DCF 가 mock 게이트를 우회했다"
