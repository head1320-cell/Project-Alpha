"""사용자가 준 비중의 **부호**는 라우트 경계에서 지워지지 않는다.

직전 슬라이스는 분석 **엔진** 7곳을 고쳤다. 그런데 그 엔진들에 값을 넣어 주는
**경계**가 여전히 숏을 잘라 내고 있었다 — 열거 grep 이 `head -30` 에서 잘렸고
나는 그것을 완전한 목록으로 취급했다.

★착수 0단계 실측★ 클램프가 **하류의 폭발을 가리고 있었다**:

    PortfolioAnalyzer(returns, weights)      # kis_portfolio_analyzer.py:193
        롱온리 60/40      → {A: 0.6,  B: 0.4}
        달러중립 100/−100 → {A: inf,  B: −inf}      ← w / w.sum()
        근사중립 100/−99  → {A: 100.0, B: −99.0}    ← 1.0 으로 나눴다

`/analyze` 의 `max(w, 0)` 을 먼저 걷었다면 `inf` 가 나갔을 것이다. 그래서
`PortfolioAnalyzer` 를 먼저 고치고 경계를 걷는다.

★값을 핀한다★ 지난 슬라이스에서 "200 이고 error 아님" 류 가드가 **세 번** 통과했다.
상태코드는 가드가 아니다.
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import math  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from src.kis_portfolio_analyzer import PortfolioAnalyzer  # noqa: E402


def _returns(n: int = 300) -> pd.DataFrame:
    rng = np.random.default_rng(3)
    return pd.DataFrame(rng.normal(0.0005, 0.012, size=(n, 2)), columns=["A", "B"])


# ═══════════════════════════════════════════════════════════════════════════
# 1. PortfolioAnalyzer — ★inf 발생지★
# ═══════════════════════════════════════════════════════════════════════════

def test_a_dollar_neutral_book_no_longer_normalizes_to_infinity():
    """★0단계 실측을 뒤집는다★ `w / w.sum()` 은 Σw≈0 에서 무너진다."""
    a = PortfolioAnalyzer(returns=_returns(), weights={"A": 100.0, "B": -100.0})
    w = a.weights.to_dict()
    assert all(math.isfinite(v) for v in w.values()), f"유한하지 않다: {w}"
    assert w["A"] == pytest.approx(0.5)
    assert w["B"] == pytest.approx(-0.5)


def test_a_near_neutral_book_is_not_left_at_a_hundred_times_scale():
    """★조용한 비정규화★ 100/−99 는 net 이 1.0 이라 예외 없이 통과하면서
    비중이 **100배**로 남았다 — 폭발보다 잡기 어려운 실패다."""
    a = PortfolioAnalyzer(returns=_returns(), weights={"A": 100.0, "B": -99.0})
    w = a.weights.to_dict()
    assert abs(w["A"]) < 1.0 and abs(w["B"]) < 1.0, f"정규화되지 않았다: {w}"
    assert sum(abs(v) for v in w.values()) == pytest.approx(1.0)


def test_the_diversification_ratio_measures_the_sum_of_the_parts():
    """분자 `Σ(vol·w)` 를 **부호대로** 더하면 중립 북에서 0 에 붙는다.

    처음 이 가드를 `0 < dr < 10` 으로 썼는데 변이 프로브가 **green** 이었다 —
    부호대로 합산한 값이 0.028299 라 그 범위 안에 있었기 때문이다. 범위는
    가드가 아니다. 실측으로 값을 핀한다.

    ★1.0 이 구조적 바닥이다★ 분산투자비율은 "개별 위험의 합 ÷ 포트폴리오 위험"
    이고 위험은 열등가법적이므로 1 미만이 될 수 없다. 0.0283 은 포트폴리오가
    부분들의 합보다 35배 더 위험하다는 뜻이 되어 성립하지 않는다.
    """
    m = PortfolioAnalyzer(returns=_returns(),
                          weights={"A": 100.0, "B": -100.0}).analyze()
    dr = m.diversification_ratio
    assert math.isfinite(dr), dr
    assert dr >= 1.0, f"분산투자비율이 구조적 바닥 아래다 — 분자를 부호대로 더했다: {dr}"
    assert dr == pytest.approx(1.4345, abs=5e-4)


@pytest.mark.parametrize("w,expected", [
    ({"A": 60.0, "B": 40.0}, {"A": 0.6, "B": 0.4}),
    ({"A": 100.0}, {"A": 1.0}),
    ({"A": 30.0, "B": 30.0}, {"A": 0.5, "B": 0.5}),
])
def test_long_only_normalization_is_unchanged(w, expected):
    """★짝 — 롱온리는 값까지 그대로★ `Σ|w| ≡ Σw` 이므로."""
    a = PortfolioAnalyzer(returns=_returns(), weights=w)
    for k, v in expected.items():
        assert a.weights[k] == pytest.approx(v)


def test_long_only_diversification_ratio_is_unchanged():
    """★짝★ 분자를 `abs` 로 바꾼 것이 롱온리를 건드리지 않았는지."""
    m = PortfolioAnalyzer(returns=_returns(), weights={"A": 60.0, "B": 40.0}).analyze()
    assert m.diversification_ratio == pytest.approx(1.3640, abs=5e-4)


# ═══════════════════════════════════════════════════════════════════════════
# 2. /analyze — 클램프가 걷혔는지 **값**으로 확인한다
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from src.app_factory import create_app
    return TestClient(create_app())


_T = ["005930", "000660"]


def _rc(client, weights: dict | None = None) -> dict:
    body: dict = {"tickers": _T}
    if weights:
        body["weights"] = weights
    r = client.post("/api/v1/allocation/analyze", json=body)
    assert r.status_code == 200, r.text
    return r.json()["risk_contributions"]


def test_an_all_short_book_is_not_silently_replaced_by_equal_weights(client):
    """★조용한 대체★ 예전에는 `Σw <= 0` 이 걸려 `user_w = None` 이 되고,
    그러면 분석기가 **균등가중**을 쓴다 — 사용자가 준 것과 다른 포트폴리오를
    분석해 놓고 그렇게 말하지 않았다.

    실측: 균등 {9.56, 10.20} · 전액숏 −60/−40 {13.94, 6.14}.
    """
    equal = _rc(client)
    short_book = _rc(client, {"005930": -60.0, "000660": -40.0})
    assert short_book != equal, "전액 숏 북이 균등가중으로 바꿔치기됐다"
    assert short_book["005930"] == pytest.approx(13.94, abs=0.05)
    assert short_book["000660"] == pytest.approx(6.14, abs=0.05)


def test_that_all_short_book_matches_its_long_mirror(client):
    """★짝 — 그리고 그 값이 옳다★ 포트폴리오 P 와 −P 는 위험이 같다.
    위 가드가 "균등만 아니면 통과" 가 되지 않게 값의 **의미**를 건다."""
    assert _rc(client, {"005930": -60.0, "000660": -40.0}) == \
        _rc(client, {"005930": 60.0, "000660": 40.0})


def test_a_neutral_book_keeps_its_short_leg_in_the_risk_split(client):
    """클램프가 남아 있으면 숏 다리의 기여가 **정확히 0** 이 된다
    (비중이 {1.0, 0.0} 으로 정규화되므로)."""
    rc = _rc(client, {"005930": 100.0, "000660": -100.0})
    assert rc["000660"] != pytest.approx(0.0, abs=1e-6), "숏 다리가 지워졌다"
    assert rc["005930"] == pytest.approx(10.41, abs=0.05)
    assert rc["000660"] == pytest.approx(11.00, abs=0.05)


def test_analyze_long_only_risk_split_is_unchanged(client):
    """★짝★ 롱온리는 값까지 그대로."""
    rc = _rc(client, {"005930": 60.0, "000660": 40.0})
    assert rc["005930"] == pytest.approx(13.94, abs=0.05)
    assert rc["000660"] == pytest.approx(6.14, abs=0.05)


# ═══════════════════════════════════════════════════════════════════════════
# 3. /stress-correlation · /scenario-run · /timing · VaR · 슬리브
# ═══════════════════════════════════════════════════════════════════════════

def test_stress_correlation_does_not_swap_an_all_short_book_for_equal_weights(client):
    """`if w.sum() <= 0: w = np.ones(n)` 이 바로 그 바꿔치기였다."""
    def base_vol(weights):
        r = client.post("/api/v1/allocation/stress-correlation",
                        json={"tickers": _T, "weights": weights})
        assert r.status_code == 200, r.text
        return r.json()["base"]["port_vol_pct"]

    assert base_vol({"005930": -60.0, "000660": -40.0}) == \
        pytest.approx(base_vol({"005930": 60.0, "000660": 40.0}), abs=1e-6), \
        "전액 숏 북이 균등가중으로 바뀌었다 (롱 거울과 위험이 같아야 한다)"


def test_scenario_run_keeps_the_short_in_its_rows(client):
    """★4번째 복사본★ 엔진은 이미 숏을 다루는데 이 래퍼가 롱온리로 만들어 넘겼다."""
    r = client.post("/api/v1/allocation/scenario-run",
                    json={"holdings": {"005930": 80.0, "000660": -30.0},
                          "pack_id": "semi_selloff"})
    assert r.status_code == 200, r.text
    rows = {x["stock_code"]: x["weight_pct"] for x in r.json()["rows"]}
    assert set(rows) == {"005930", "000660"}, "숏 종목이 표에서 빠졌다"
    assert rows["000660"] < 0, "숏이 롱으로 뒤집혔다"


def test_the_timing_realized_vol_stops_deleting_the_short_ticker():
    """★목록 필터가 비중 클램프보다 먼저였다★

    `tickers = [t for t, w in weights_pct.items() if w > 0]` 이 숏 **종목 자체**를
    지웠다. 그러면 2종목 바스켓이 1종목이 되고, `_aligned_returns` 가 빈 목록을
    돌려주어 실현변동성이 **통째로 None** 이 된다 — 목표변동성 오버레이가 조용히
    꺼지는 경로다.

    ★첫 가드는 `if "EFA" in w:` 였고 프로브가 green 이었다★ 조건부 단언은
    가드가 아니다. 무조건으로 바꾼다.

    ★못 재는 것은 적는다★ mock 의 ETF 계열은 상관이 ~0 이라 부호가 분산에
    미치는 영향(±2w₁w₂σ₁₂)을 여기서 가를 수 없다 — 80/−20 과 80/+20 이 같은
    값을 낸다. 그래서 값이 아니라 **숏이 계산에 들어갔는지**를 건다.
    """
    from src.api.timing_routes import _timing_realized_vol_pct
    v = _timing_realized_vol_pct({"SPY": 80.0, "EFA": -20.0}, "us")
    assert v is not None, "숏 종목이 지워져 실현변동성이 계산되지 않았다"
    assert v == pytest.approx(23.349, abs=0.01)


def test_the_timing_basket_keeps_a_short(client):
    """`_on_basket` — 응답의 `holdings` 에 숏이 부호 그대로 실린다."""
    r = client.post("/api/v1/allocation/timing", json={
        "market": "us",
        "canaries": [{"kind": "asset", "id": "SPY", "signal": "score_13612"}],
        "holdings": {"SPY": 80.0, "EFA": -20.0},
    })
    assert r.status_code == 200, r.text
    hold = {h["ticker"]: h["weight"] for h in r.json()["holdings"]}
    assert hold["EFA"] < 0, f"숏 다리가 롱으로 뒤집혔다: {hold}"


def test_the_var_routes_normalization_is_covered_statically_not_here():
    """★건너뛰지 않고, 왜 여기서 못 재는지 적는다★

    `/calculate-portfolio-var` 는 `MarketDataLoader` 를 쓰는데 그 로더에는
    mock 폴백이 없어서(`ValueError: No data found for ticker`) 이 환경에서
    500 이 된다. 라우트를 종단으로 태울 수 없다.

    그래서 이 두 줄은 **정적 가드**(`test_no_weight_sign_loss.py`)가 지킨다 —
    경계에서 net 정규화를 하면 CI 가 실패한다. 런타임으로 못 재는 것을
    `pytest.skip` 으로 덮으면 "통과했다" 는 인상만 남는다.
    """
    import ast
    import pathlib
    src = pathlib.Path("src/api/risk_routes.py").read_text()
    tree = ast.parse(src)
    # `weights / np.abs(weights).sum()` 이어야 하고 `weights / weights.sum()` 이면 안 된다.
    bad = [n for n in ast.walk(tree)
           if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div)
           and isinstance(n.right, ast.Call)
           and isinstance(n.right.func, ast.Attribute) and n.right.func.attr == "sum"
           and isinstance(n.right.func.value, ast.Name)
           and n.right.func.value.id == "weights"]
    assert not bad, f"경계에서 net 정규화가 남아 있다 (줄 {[n.lineno for n in bad]})"
    assert "np.abs(weights).sum()" in src, "gross 정규화가 사라졌다"


def test_a_pair_sleeve_survives_the_combine(client):
    """★`PairSpreadRequest(long_code, short_code)` 가 있는 모듈이★
    결합 단계에서 숏을 지우고 있었다."""
    r = client.post("/api/v1/allocation/combine-sleeves", json={
        "sleeves": [{"name": "pair", "weights": {"005930": 50.0, "000660": -50.0}},
                    {"name": "long", "weights": {"035420": 100.0}}],
        "method": "risk_parity",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("error") is not True, body
    cw = body["combined_weights_pct"]
    assert "000660" in cw, "페어 슬리브의 숏 다리가 사라졌다"
    assert cw["000660"] < 0, "숏이 롱으로 뒤집혔다"
    assert cw["005930"] == pytest.approx(-cw["000660"], abs=0.01), \
        "페어의 두 다리 크기가 같아야 한다"


def test_a_short_sleeve_still_carries_risk(client):
    """슬리브 **배분**도 사용자가 준 값이라 부호가 미지수다.

    클램프가 남아 있으면 숏 슬리브의 비중이 0 이 되어 리스크 기여가 **정확히 0**
    이 된다(비중이 {1.0, 0.0} 으로 정규화되므로).

    ★못 재는 것은 적는다★ 대각에 가까운 mock 공분산에서는 `rc = w·(Σw)/σ` 가
    `w²` 에 비례해 **부호가 값을 바꾸지 않는다** — 그래서 롱숏과 롱온리가 같은
    값을 낸다. 여기서 가르는 것은 부호가 아니라 **숏이 계산에 들어갔는지**다.
    """
    body = {"sleeves": [{"name": "a", "weights": {"005930": 100.0}},
                        {"name": "b", "weights": {"000660": 100.0}}],
            "weights": {"a": 120.0, "b": -20.0}}
    r = client.post("/api/v1/allocation/sleeve-analytics", json=body)
    assert r.status_code == 200, r.text
    rc = r.json()["risk_contribution_pct"]
    assert rc["b"] != pytest.approx(0.0, abs=1e-9), "숏 슬리브가 지워졌다"
    assert rc["b"] == pytest.approx(2.7, abs=0.05)
    assert rc["a"] == pytest.approx(97.3, abs=0.05)


def test_a_long_only_sleeve_combine_is_unchanged(client):
    """★짝★ 롱온리 결합은 합 100%·전부 양수 그대로."""
    r = client.post("/api/v1/allocation/combine-sleeves", json={
        "sleeves": [{"name": "a", "weights": {"005930": 60.0, "000660": 40.0}},
                    {"name": "b", "weights": {"035420": 100.0}}],
        "method": "risk_parity",
    })
    cw = r.json()["combined_weights_pct"]
    assert all(v > 0 for v in cw.values())
    assert sum(cw.values()) == pytest.approx(100.0, abs=0.05)
