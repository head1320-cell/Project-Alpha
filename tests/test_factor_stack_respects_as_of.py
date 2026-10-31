"""팩터 계층이 `as_of` 를 **지킨다** — 선언만 하지 않는다.

★착수 0단계 실측 — 선언과 계산이 어긋났다★

`rebalance-decision` 에 `as_of=2024-06-30` 을 주면:

  · 가격·수익률(`_load_clean_returns(as_of=)`)        → 잘랐다
  · `asset_factor_betas(names)`                        → **인자 자체가 없었다**
  · `portfolio_monthly_returns(target)`                → 없었다
  · `build_factor_risk_model(names)`                   → 없었다
  · `factor_covariance(resolve_proxies()["resolved"])` → 없었다
  · 응답 `research_context`                            → `information_cutoff: 2024-06-30`

즉 "2024-06-30 시점의 팩터 노출" 을 물으면 **오늘 데이터로 계산한 값을 그 날짜
라벨로** 돌려줬다. 벤치마크 §5 가 non-negotiable 이라 한 hidden date 이고,
S1 이 막으려던 것의 반대편이다 — 없는 절단일을 지어내진 않았지만 **지키지 않는
절단일을 선언**했다.

★저장소가 이미 알고 있었다★ `macro_sensitivity._monthly_returns` 의 독스트링이
"창의 끝은 오늘 (결함 B 와 같은 함정)" 이라고 적어 두고 있었다.

★이 가드는 직전 슬라이스 덕분에 가능하다★ mock 을 날짜 주소화하기 전에는 어느
창을 요청해도 같은 값이 나와서 이 결함을 **테스트할 수 없었다**.
"""
from __future__ import annotations

import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402

_W = {"005930": 60.0, "000660": 40.0}
_CODES = ["005930", "000660"]


# ── 1. ★창의 끝이 실제로 옮겨진다★ ─────────────────────────────────────
def test_monthly_returns_window_ends_at_as_of():
    from src.engine.valuation.macro_sensitivity import _monthly_returns
    past = _monthly_returns("005930", as_of="2024-06-30")
    assert str(past.index[-1])[:7] == "2024-06", str(past.index[-1])


def test_two_different_past_dates_give_different_series():
    """★'오늘과만 다르다' 면 상수를 넣어도 통과한다★ 과거끼리도 갈려야 한다."""
    from src.engine.valuation.macro_sensitivity import _monthly_returns
    a = _monthly_returns("005930", as_of="2024-06-30")
    b = _monthly_returns("005930", as_of="2025-06-30")
    assert str(a.index[-1])[:7] != str(b.index[-1])[:7]
    assert float(a.iloc[-1]) != float(b.iloc[-1])


def test_no_as_of_still_ends_today():
    """★짝 — 기본 동작 불변★ 기존 호출자는 하나도 바뀌지 않는다."""
    from datetime import date

    from src.engine.valuation.macro_sensitivity import _monthly_returns
    cur = _monthly_returns("005930")
    assert str(cur.index[-1])[:7] == date.today().strftime("%Y-%m")


# ── 2. ★세 엔진 각각★ 하나만 배선해도 통과하지 않게 따로 건다 ─────────
def test_portfolio_monthly_returns_respects_as_of():
    from src.engine.factor_risk import portfolio_monthly_returns
    past = portfolio_monthly_returns(_W, as_of="2024-06-30")
    cur = portfolio_monthly_returns(_W)
    assert past["available"] and cur["available"]
    assert past["months"][-1] == "2024-06", past["months"][-1]
    assert past["variance"] != cur["variance"]


def test_asset_factor_betas_respects_as_of():
    """★관측 가능한 것으로 건다★ 회귀 창의 길이와 구간이 실제로 옮겨진다.

    처음에는 베타 **값**을 비교했고, 자산 경로만 배선 해제하는 프로브로 격리를
    시도했다. 두 번 다 실패했고 이유가 드러났다:

      · 매크로 계열이 자산 창보다 **먼저 끝난다**(현재 데이터에서 2023-12).
        그래서 교집합을 묶는 것은 매크로 쪽이고, 자산 수익률을 2024-06 으로
        잘라도 `n_months`·`span`·베타가 **하나도 바뀌지 않는다.**
      · 즉 "자산 경로 배선 해제" 는 이 구성에서 **equivalent mutant** 다.
        억지로 잡히게 만들지 않고 그렇게 적는다.

    자산 경로 자체는 `_monthly_returns` 수준에서 이미 걸려 있다(위 세 테스트).
    배선을 유지하는 이유는 매크로가 자산 창을 넘어서는 실데이터에서 의미가
    생기기 때문이다. 여기서는 **매크로 절단이 창을 옮긴다**는 것을 건다.
    """
    from src.engine.factor_exposure import asset_factor_betas
    past, cur = asset_factor_betas(_CODES, as_of="2024-06-30"), asset_factor_betas(_CODES)
    assert past["available"] and cur["available"]
    assert past["sample"]["n_months"] < cur["sample"]["n_months"], (
        past["sample"], cur["sample"])

    def _span(out):
        for row in out["assets"].values():
            for fit in (row.get("betas") or {}).values():
                if fit.get("span"):
                    return fit["span"]
        return None

    sp, sc = _span(past), _span(cur)
    assert sp and sc, "span 이 없다 — 가드가 공허하다"
    assert sp[1] < sc[1], f"회귀 창의 끝이 옮겨지지 않았다: {sp} vs {sc}"
    assert sp[1] <= "2024-06", sp


def test_factor_risk_model_respects_as_of():
    from src.engine.factor_risk_model import build_factor_risk_model
    past = build_factor_risk_model(_CODES, as_of="2024-06-30")
    cur = build_factor_risk_model(_CODES)
    assert past["available"] and cur["available"], (past.get("reason"), cur.get("reason"))
    assert past["diagnostics"] != cur["diagnostics"]


# ── 3. ★계열 절단★ ─────────────────────────────────────────────────────
def test_macro_series_are_cut_at_as_of():
    from src.engine.factor_exposure import _macro_series_map, truncate_series
    sm, _ = _macro_series_map()
    assert sm, "매크로 계열이 없다 — 가드가 공허하다"
    name = next(k for k, v in sm.items() if len(getattr(v, "timestamps", []) or []) > 30)
    cut, ok = truncate_series(sm[name], "2024-06-30")
    assert ok
    assert len(cut.timestamps) < len(sm[name].timestamps)
    assert all(str(t)[:10] <= "2024-06-30" for t in cut.timestamps)


def test_an_empty_series_counts_as_honored():
    """★실측★ 61계열 중 31개가 빈 계열이었다. 자를 것이 없는 것을 '실패' 로 세면
    실제로는 전부 잘린 경우에도 '못 지켰다' 고 보고하게 된다."""
    from src.engine.factor_exposure import truncate_series

    class _Empty:
        timestamps: list = []
        values: list = []

    _, ok = truncate_series(_Empty(), "2024-06-30")
    assert ok is True


def test_honored_is_scoped_to_the_series_actually_used():
    """★쓰지도 않은 계열 때문에 '못 지켰다' 고 말하면 그것도 거짓이다★"""
    from src.engine.factor_exposure import resolve_proxies
    p = resolve_proxies(as_of="2024-06-30")
    assert p["available"] and p["resolved"]
    assert p["as_of_honored"] is True, "쓰인 계열이 전부 잘렸는데 못 지켰다고 말한다"


# ── 4. ★지킨 절단일만 선언한다★ ───────────────────────────────────────
@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from src.app_factory import create_app
    return TestClient(create_app())


def _rc(client, as_of=None) -> dict:
    body = {"tickers": ["005930", "000660", "035420"],
            "holdings": {"005930": 50.0, "000660": 30.0, "035420": 20.0},
            "portfolio_value": 1e8, "model": "mvo",
            "factor_exposure": True, "factor_risk": True}
    if as_of:
        body["as_of"] = as_of
    r = client.post("/api/v1/allocation/rebalance-decision", json=body)
    assert r.status_code == 200, r.text
    return r.json()["research_context"]


def test_the_response_declares_the_cutoffs_it_actually_honored(client):
    rc = _rc(client, "2024-06-30")
    assert rc["cutoffs_declared"] == {"market_data_as_of": "2024-06-30",
                                      "macro_data_as_of": "2024-06-30"}, rc


def test_it_still_says_what_it_did_not_cut(client):
    """★짝 — 전부 declared 로 밀어 넣으면 그것도 거짓이다★
    재무는 이 경로에서 자르지 않으므로 `unspecified` 로 남아야 한다."""
    rc = _rc(client, "2024-06-30")
    assert rc["cutoffs_unspecified"] == ["fundamental_data_as_of"], rc


def test_without_an_as_of_nothing_is_declared(client):
    """★짝 — 기본 동작 불변★ as_of 가 없으면 절단을 주장하지 않는다."""
    rc = _rc(client)
    assert rc["cutoffs_declared"] == {}
    assert set(rc["cutoffs_unspecified"]) == {
        "market_data_as_of", "fundamental_data_as_of", "macro_data_as_of"}


# ── 5. ★거짓 선언 금지★ 못 지켰으면 declared 에 넣지 않는다 ────────────
def test_an_unhonored_cutoff_is_not_declared():
    """★이 짝이 없으면 "항상 지켰다" 로 고쳐도 통과한다★ (변이 프로브가 green 이었다)

    잘 수 없는 계열(타임스탬프와 값의 길이가 다름)을 주입하면 `as_of_honored` 가
    False 여야 하고, 그러면 상류가 `macro_data_as_of` 를 선언하지 않는다.
    """
    from src.engine.factor_exposure import resolve_proxies

    class _Broken:
        timestamps = ["2020-01-31", "2020-02-29", "2020-03-31"]
        values = [1.0]                       # 길이 불일치 — 자를 수 없다

    sm, _ = _resolve_map()
    broken = {k: _Broken() for k in sm}
    p = resolve_proxies(broken, as_of="2024-06-30")
    assert p["as_of_honored"] is False, "자를 수 없었는데 지켰다고 말한다"


def _resolve_map():
    from src.engine.factor_exposure import _macro_series_map
    return _macro_series_map()


def test_the_route_does_not_declare_macro_when_as_of_never_reached_it(client):
    """★공허한 참을 배제한다★ `as_of` 를 안 넘기면 `as_of_honored` 가 공허하게
    True 가 되는데, 그것을 "지켰다" 로 읽으면 절단하지 않은 것을 선언하게 된다.
    요청한 절단일이 실제로 내려갔는지까지 확인해야 한다."""
    rc = _rc(client, "2024-06-30")
    assert rc["cutoffs_declared"].get("macro_data_as_of") == "2024-06-30"
    # 그리고 그 판정이 `prox["as_of"]` 일치에 달려 있다는 것을 엔진 수준에서 건다.
    from src.engine.factor_exposure import resolve_proxies
    assert resolve_proxies()["as_of"] is None, "as_of 를 안 넘겼는데 값이 실렸다"
