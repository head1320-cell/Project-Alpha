"""기업 뷰 배선 — ★만들어 놓고 부르지 않았다(네 번째)★ (S5)
==============================================================================
설계: `docs/superpowers/specs/2026-08-28-investment-decision-layer-design.md` §2.3
선행: S4 `company_views()`(`8fb867c`)

S4 가 다리를 놓았지만 **부르는 곳이 없었다.** 이 파일이 그 배선을 못 박는다.

## ★기본값이 거짓인 것이 계약이다★

`AnalyzeRequest.conditional` 이 이미 답을 적어 뒀다 — *"켜지 않으면 이 파일의
동작은 한 글자도 같다 — **응답 키조차 늘지 않는다**"*. 같은 규율을 쓴다.

## ★공시가 거짓말을 할 참이었다★

`optimize` 의 `extra_views_used` 는 `len(extra_views) − (conditional 스킵)` 이었다.
회사 뷰가 같은 목록에 실리면 그 수가 회사 뷰까지 세고, 그 숫자를 받는 문장이
*"조건부 μ 를 자산 N개의 절대 뷰로 태웠습니다"* 다 — 매크로가 하지 않은 일을
했다고 적는다. 두 겹으로 막는다: **별도 인자**(의도가 코드에 드러남)와
**source 로 세기**(누가 다시 섞어도 공시가 안 오염됨).
"""

from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

import src.engine.company_views as cv  # noqa: E402

TICKERS = ["005930", "000660", "035420"]
ANALYZE = "/api/v1/allocation/analyze"
DECIDE = "/api/v1/allocation/rebalance-decision"


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from src.app_factory import create_app
    return TestClient(create_app())


def _analyze(client, **kw) -> dict:
    body = {"tickers": TICKERS, "model": "bl", "lookback_days": 300}
    body.update(kw)
    r = client.post(ANALYZE, json=body)
    assert r.status_code == 200, r.text
    return r.json()


# ══════════════════════════════════════════════════════════════════════════
# X1·X2 ★opt-in★
# ══════════════════════════════════════════════════════════════════════════
def test_by_default_not_even_the_response_key_appears(client):
    """★`conditional` 이 이미 답한 계약★ — 켜지 않으면 응답 키조차 늘지 않는다."""
    assert "company_views" not in _analyze(client)


def test_by_default_the_weights_are_unchanged(client):
    """★기본값에서 배분 동작은 바뀌지 않는다★ — 플래그를 **명시적으로 끈** 호출과
    아예 안 보낸 호출의 가중치가 같아야 한다."""
    a = _analyze(client)
    b = _analyze(client, use_company_views=False)
    assert a["weights"] == b["weights"]


def test_turning_it_on_produces_the_block(client):
    """★짝★ 항상 끄는 구현을 배제한다."""
    body = _analyze(client, use_company_views=True)
    blk = body["company_views"]
    assert blk["requested"] is True
    assert blk["applied"] >= 1, blk
    assert all(v["source"] == cv.SOURCE for v in blk["views"])


def test_the_block_carries_its_grade_and_labels(client):
    """★결과에 등급을 적는다★ — forward_only · mock 여부 · 포화 수.

    ★예전 단언 `saturated == applied`("E0 산물은 전부 포화한다")는 불변식이 아니라
    그날의 관측이었다★ (BE, 2026-09-24). 가격 창이 `datetime.now()` 로 잡혀 mock
    가격이 날마다 바뀌고, 그날 `|z|` 가 1 미만인 뷰가 하나 생기자 `2 == 3` 으로
    깨졌다 — 코드는 한 줄도 안 바뀌었다. 참인 불변식은 *"블록이 포화한 뷰를
    정직하게 센다"* 이다.
    """
    blk = _analyze(client, use_company_views=True)["company_views"]
    assert blk["research_usage"] == "forward_only"
    assert blk["any_mock"] is True                      # KIS_USE_MOCK=1
    views = blk["views"]
    assert views, "뷰가 없으면 아래 세기는 공허하다"
    assert blk["saturated"] == sum(1 for v in views if abs(v["z"]) >= cv.Z_FULL)
    assert blk["saturated"] == sum(1 for v in views if v["confidence_saturated"])
    assert blk["note"]


def test_saturation_is_decided_by_z_not_assumed(monkeypatch):
    """★짝★ — 포화는 `|z| ≥ Z_FULL` 로 **판정**된다. 상수로 가정하지 않는다.

    같은 분포에서 가격만 바꿔 `z` 를 1 아래·위로 둔다 — 포화 여부가 따라 바뀐다.
    """
    dist = {"available": True, "corp_name": "테스트",
            "unified": {"available": True, "p10": 90.0, "p50": 100.0, "p90": 110.0},
            "base_assumptions": {"years": 3.0}}
    from src.engine.valuation import valuation_distribution as vd
    monkeypatch.setattr(vd, "valuation_distribution_for",
                        lambda code, price, **kw: dict(dist))
    out = {}
    for price in (95.0, 80.0):      # z = (100-95)/10 = 0.5 · (100-80)/10 = 2.0
        views, reasons = cv.company_views(["000001"], {"000001": price})
        assert views, reasons
        out[price] = views[0]["confidence_saturated"]
    assert out == {95.0: False, 80.0: True}, out


# ══════════════════════════════════════════════════════════════════════════
# X3·X4 ★뷰가 실제로 μ 에 닿는다★
# ══════════════════════════════════════════════════════════════════════════
def test_the_views_actually_move_the_bl_weights(client):
    """배선했다는 말이 아니라 **가중치가 달라진다**는 사실로 증명한다."""
    off = _analyze(client, model="bl")["weights"]
    on = _analyze(client, model="bl", use_company_views=True)["weights"]
    assert off != on


def test_a_covariance_only_model_is_left_alone(client):
    """★정직★ `risk_parity` 는 μ 를 안 쓰므로 뷰를 태워도 가중치가 같다 —
    "회사 뷰를 반영했다" 가 모든 모델에서 참인 것처럼 보이지 않게 한다."""
    off = _analyze(client, model="risk_parity")["weights"]
    on = _analyze(client, model="risk_parity", use_company_views=True)["weights"]
    assert off == on


# ══════════════════════════════════════════════════════════════════════════
# X5 ★as_of 는 거절되고 그 사실이 응답에 실린다★
# ══════════════════════════════════════════════════════════════════════════
def test_a_pinned_as_of_yields_no_views_and_says_why(client):
    """조용히 빈 목록을 내면 "회사 뷰를 반영했다" 로 오독된다."""
    blk = _analyze(client, use_company_views=True,
                   as_of="2025-06-30")["company_views"]
    assert blk["applied"] == 0 and blk["views"] == []
    assert set(blk["reasons"]) == set(TICKERS)
    assert all(r["kind"] == cv.KIND_NO_VINTAGE for r in blk["reasons"].values())


# ══════════════════════════════════════════════════════════════════════════
# X6·X7·X8 ★공시 숫자★ (엔진 수준 — 라우트를 거치지 않고 정확히 건다)
# ══════════════════════════════════════════════════════════════════════════
def _R(n_assets: int = 3, rows: int = 400) -> np.ndarray:
    rng = np.random.default_rng(7)
    return rng.normal(0.0004, 0.012, size=(rows, n_assets))


def _cond_view(name: str) -> dict:
    return {"assets": [name], "direction": 1, "magnitude_pct": 3.0,
            "confidence": 40, "source": "conditional"}


def _co_view(name: str) -> dict:
    return {"assets": [name], "direction": -1, "magnitude_pct": 2.0,
            "confidence": 30, "source": cv.SOURCE}


def test_the_conditional_count_ignores_company_views():
    """★핵심★ 둘을 함께 켜도 조건부 공시가 회사 뷰를 세지 않는다."""
    from src.engine.allocation_studio import optimize

    names = ["a", "b", "c"]
    out = optimize("bl", names, _R(),
                   extra_views=[_cond_view("a"), _cond_view("b")],
                   company_views=[_co_view("c")])
    assert out["extra_views_used"] == 2
    assert out["company_views_used"] == 1


def test_the_conditional_count_is_unchanged_when_only_conditional_views_exist():
    """★짝★ 기본값(회사 뷰 없음)에서 숫자가 예전과 같다."""
    from src.engine.allocation_studio import optimize

    names = ["a", "b", "c"]
    out = optimize("bl", names, _R(), extra_views=[_cond_view("a"), _cond_view("b")])
    assert out["extra_views_used"] == 2
    assert out["company_views_used"] == 0


def test_mixing_them_into_one_list_still_does_not_pollute_the_disclosure():
    """★2차 방어★ 별도 인자(1차)를 우회해 회사 뷰를 `extra_views` 에 밀어 넣어도
    각 공시가 **제 몫만** 센다 — 출처로 세기 때문이다."""
    from src.engine.allocation_studio import optimize

    out = optimize("bl", ["a", "b", "c"], _R(),
                   extra_views=[_cond_view("a"), _co_view("c")])
    assert out["extra_views_used"] == 1
    assert out["company_views_used"] == 1


def test_a_plain_user_view_is_counted_by_neither():
    """★짝★ 사용자 뷰에는 `source` 칸이 없다 — 어느 공시에도 잡히면 안 된다."""
    from src.engine.allocation_studio import optimize

    out = optimize("bl", ["a", "b", "c"], _R(),
                   views=[{"assets": ["a"], "direction": 1,
                           "magnitude_pct": 5.0, "confidence": 50}])
    assert out["extra_views_used"] == 0
    assert out["company_views_used"] == 0


def test_a_skipped_company_view_is_not_counted_as_used():
    """유니버스에 없는 자산을 겨눈 회사 뷰는 스킵되고, 쓰인 수에서 빠진다."""
    from src.engine.allocation_studio import optimize

    out = optimize("bl", ["a", "b", "c"], _R(),
                   company_views=[_co_view("c"), _co_view("없는종목")])
    assert out["company_views_used"] == 1


# ══════════════════════════════════════════════════════════════════════════
# X9 ★결정 경로도 같은 헬퍼를 탄다★
# ══════════════════════════════════════════════════════════════════════════
def test_the_decision_route_records_what_mu_was_built_from(client, monkeypatch):
    """S3 가 만든 결정 기록이 μ 가 무엇으로 세워졌는지 말해야 한다."""
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    import src.data.investment_decisions as idec

    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    monkeypatch.setattr(idec, "_engine", lambda engine=None: eng)

    r = client.post(DECIDE, json={
        "tickers": TICKERS, "holdings": {t: 100 / 3 for t in TICKERS},
        "portfolio_value": 100_000_000, "model": "bl", "horizon_days": 63,
        "use_company_views": True, "record_decision": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["company_views"]["applied"] >= 1

    dec = idec.get_decision(body["dec_id"], engine=eng)
    assert dec["belief"]["company_views_used"] == body["company_views"]["applied"]


def test_the_decision_route_stays_quiet_by_default(client):
    """★짝★ 결정 라우트도 기본값에서는 키가 늘지 않는다."""
    r = client.post(DECIDE, json={
        "tickers": TICKERS, "holdings": {t: 100 / 3 for t in TICKERS},
        "portfolio_value": 100_000_000, "model": "bl", "horizon_days": 63})
    assert r.status_code == 200, r.text
    assert "company_views" not in r.json()


# ══════════════════════════════════════════════════════════════════════════
# X10 ★forward_only 가 백테스트로 새지 않는다★
# ══════════════════════════════════════════════════════════════════════════
def test_the_walk_forward_never_receives_company_views(monkeypatch):
    """★선언만 두지 않는다★ 회사 뷰는 `research_usage: forward_only` 다 —
    과거 시뮬레이션에 들어가면 그 자체가 룩어헤드다. 스파이로 직접 건다.
    """
    import src.engine.allocation_studio as st
    from src.engine.allocation_backtest import walk_forward

    seen: list[dict] = []
    real = st.optimize
    monkeypatch.setattr(st, "optimize",
                        lambda *a, **kw: (seen.append(kw), real(*a, **kw))[1])

    import pandas as pd
    idx = list(pd.bdate_range("2023-01-02", periods=320).date)
    rng = np.random.default_rng(3)
    out = walk_forward(["a", "b", "c"], rng.normal(0.0004, 0.012, size=(320, 3)),
                       idx, model="bl", rebalance="Q", min_train=63)
    assert not out.get("error"), out

    assert seen, "optimize 가 한 번도 불리지 않았다 — 테스트가 무의미하다"
    assert all(not kw.get("company_views") for kw in seen)


# ══════════════════════════════════════════════════════════════════════════
# X11·X12 ★가격과 사유★
# ══════════════════════════════════════════════════════════════════════════
def test_a_code_without_a_price_is_reported_as_a_reason(client, monkeypatch):
    """★조용한 누락 금지★ 가격을 못 구하면 뷰가 아니라 **사유**가 나온다."""
    monkeypatch.setattr("src.engine.company_snapshot_builder._resolve_price",
                        lambda code, price: (None, "unavailable"))
    blk = _analyze(client, use_company_views=True)["company_views"]
    assert blk["applied"] == 0
    assert set(blk["reasons"]) == set(TICKERS)
    assert all(r["kind"] == cv.KIND_NO_PRICE for r in blk["reasons"].values())


def test_the_price_source_is_reported_not_assumed():
    """가격이 어디서 왔는지 서버가 답한다 — 화면이 지어내지 않게."""
    prices, source = cv.prices_for(TICKERS)
    assert set(prices) == set(TICKERS)
    assert all(source[c] for c in prices)
    assert all(p > 0 for p in prices.values())
