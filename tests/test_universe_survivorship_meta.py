"""유니버스가 **생존편향을 보정했는가** (`universe`)

로드맵 0단계의 넷 중 마지막. 그리고 ★계획에 없던 결함★을 이 자리에서 실측했다.

## 침묵 폴백

`_screen_to_backtest_core` 는 `all_asof`(그 시점 거래 종목 — 상장폐지 포함)와
`top200_asof`(시총 상위 재구성)를 지원한다. 그런데 그 조회가 빈 값을 내면
**오늘자 프리셋**(`all_listed`/`kospi200`)으로 조용히 떨어졌다:

    _universe = _asof if _asof else "all_listed"

요청한 사람은 상장폐지 종목이 포함된 유니버스로 돌았다고 믿는데, 실제로는
**오늘 살아남은 종목만** 본 것이다. 그것이 정확히 생존편향이고, 화면에는
아무 표시가 없었다.

★사용자 결정: 동작은 그대로 두고 라벨을 단다★ — 폴백을 막으면 지금 도는
백테스트가 멈춘다. CLAUDE.md 의 폴백 4조건(의미가 알려짐 · 라벨 · 동등 품질로
위장 불가 · 관측 가능)을 만족시키는 최소 변경이다.

## 네 값 — ★보정 여부는 예/아니오가 아니다★

    corrected       그 시점 거래 종목을 실제로 세웠다
    approximated    시총 상위 재구성 — 소스 주석이 이미 "근사" 라고 적었다
    not_corrected   오늘 기준 멤버십이다(프리셋·폴백)
    unknown         사용자가 준 목록이라 **알 수 없다** (★미상 ≠ 보정★)
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402

import src.engine.universe_select as US  # noqa: E402
from src.api.screener_routes import (  # noqa: E402
    ScreenToBacktestRequest,
    _screen_to_backtest_core,
)
from src.engine.universe_select import (  # noqa: E402
    SURVIVORSHIP_APPROXIMATED,
    SURVIVORSHIP_CORRECTED,
    SURVIVORSHIP_NOT_CORRECTED,
    SURVIVORSHIP_UNKNOWN,
    survivorship_of,
)

_AST = {"logic": "AND", "conditions": [], "groups": []}


class _FakeItem:
    def __init__(self, code):
        self.stock_code = code
        self.corp_name = f"종목{code}"
        self.composite_score = 50.0


class _FakeScreener:
    def __init__(self):
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return type("R", (), {"items": [_FakeItem(f"{100000 + i:06d}") for i in range(3)]})()


@pytest.fixture
def route(monkeypatch):
    fake = _FakeScreener()
    monkeypatch.setattr("src.api.screener_routes.get_screener", lambda: fake)
    monkeypatch.setattr("src.kis_backtest_engine.run_backtest", lambda **kw: {
        "error": False,
        "result": {"statistics": {}, "equity_curve": [], "equity_dates": [],
                   "drawdown_curve": [], "monthly_returns": [], "trades": []}})
    return fake


def _call(**kw) -> dict:
    req = ScreenToBacktestRequest(filter_ast=_AST, buy_conditions=None,
                                  sell_conditions=None, **kw)
    return _screen_to_backtest_core(req)


# ═══════════════════════════════════════════════════════════════════════════
# 순수 분류기 — ★어휘의 주인은 `universe_select` 다★
# ═══════════════════════════════════════════════════════════════════════════

def test_the_classifier_separates_the_four_values():
    assert survivorship_of("all_asof")[0] == SURVIVORSHIP_CORRECTED
    assert survivorship_of("top200_asof")[0] == SURVIVORSHIP_APPROXIMATED
    assert survivorship_of("preset")[0] == SURVIVORSHIP_NOT_CORRECTED
    assert survivorship_of("custom_tickers")[0] == SURVIVORSHIP_UNKNOWN


def test_only_the_corrected_value_has_no_reason():
    """★깨끗하지 않은 것에는 반드시 사유가 붙는다★ 처방이 각각 다르다."""
    assert survivorship_of("all_asof")[1] is None
    for mode in ("top200_asof", "preset", "custom_tickers", "granular"):
        assert survivorship_of(mode)[1], f"{mode} 에 사유가 없다"


def test_a_fallback_is_never_corrected():
    """★폴백은 보정이 아니다★ 요청이 무엇이었든 결과는 오늘자 멤버십이다."""
    for mode in ("all_asof", "top200_asof"):
        value, reason = survivorship_of(mode, fell_back=True)
        assert value == SURVIVORSHIP_NOT_CORRECTED, (mode, value)
        assert "폴백" in reason, reason


def test_an_unknown_mode_is_not_quietly_corrected():
    """모르는 모드를 `corrected` 로 낙관하지 않는다."""
    value, reason = survivorship_of("모르는모드")
    assert value == SURVIVORSHIP_UNKNOWN, value
    assert reason, "사유 없는 미상"


# ═══════════════════════════════════════════════════════════════════════════
# 라우트 배선 — ★분기마다 실제로 라벨이 붙는가★
# ═══════════════════════════════════════════════════════════════════════════

def test_asof_universe_reports_corrected(route, monkeypatch):
    monkeypatch.setattr(US, "tickers_asof", lambda d: ["000660", "005930"])
    uv = _call(universe="all_asof", start_date="2023-01-02")["universe"]
    assert uv["survivorship"] == SURVIVORSHIP_CORRECTED, uv
    assert uv["requested"] == "all_asof", uv
    assert uv["effective"] == "all_asof", uv
    assert uv["asof_date"] == "2023-01-02", uv


def test_a_silent_fallback_is_no_longer_silent(route, monkeypatch):
    """★이 파일의 이유★ — 폴백이 일어난 사실과 그 결과가 응답에 남는다."""
    monkeypatch.setattr(US, "tickers_asof", lambda d: [])
    uv = _call(universe="all_asof", start_date="2023-01-02")["universe"]
    assert uv["survivorship"] == SURVIVORSHIP_NOT_CORRECTED, uv
    assert uv["requested"] == "all_asof", uv
    assert uv["effective"] == "all_listed", "폴백한 실제 유니버스가 안 보인다"
    assert uv["fell_back"] is True, uv
    assert "상장폐지" in (uv["reason"] or ""), uv["reason"]


def test_the_fallback_still_happens(route, monkeypatch):
    """★동작은 바꾸지 않았다★ 라벨만 더했다 — 스크리너는 여전히 프리셋으로 돈다."""
    monkeypatch.setattr(US, "tickers_asof", lambda d: [])
    _call(universe="all_asof", start_date="2023-01-02")
    assert route.calls[0]["universe"] == "all_listed"


def test_top200_asof_is_approximated_not_corrected(route, monkeypatch):
    """★근사 재구성을 보정이라 부르지 않는다★ 소스 주석이 이미 그렇게 적었다."""
    monkeypatch.setattr(US, "top_mktcap_asof", lambda d, n: ["005930"] * 3)
    uv = _call(universe="top200_asof", start_date="2023-01-02")["universe"]
    assert uv["survivorship"] == SURVIVORSHIP_APPROXIMATED, uv
    assert uv["fell_back"] is False, uv


def test_top200_fallback_degrades_further(route, monkeypatch):
    monkeypatch.setattr(US, "top_mktcap_asof", lambda d, n: [])
    uv = _call(universe="top200_asof", start_date="2023-01-02")["universe"]
    assert uv["survivorship"] == SURVIVORSHIP_NOT_CORRECTED, uv
    assert uv["effective"] == "kospi200", uv


def test_a_plain_preset_says_it_is_todays_membership(route):
    uv = _call(universe="kospi200")["universe"]
    assert uv["survivorship"] == SURVIVORSHIP_NOT_CORRECTED, uv
    assert uv["effective"] == "kospi200", uv
    assert uv["fell_back"] is False, "폴백이 아닌데 폴백으로 적혔다"


def test_custom_tickers_are_unknown_not_uncorrected(route):
    """★미상 ≠ 보정 안 됨★ 사용자 목록이 시점 구성인지 우리는 모른다."""
    uv = _call(universe="kospi200", custom_tickers=["005930", "000660"])["universe"]
    assert uv["survivorship"] == SURVIVORSHIP_UNKNOWN, uv
    assert uv["requested"] == "custom_tickers", uv


def test_effective_differs_from_requested_only_on_fallback(route, monkeypatch):
    """★`effective ≠ requested` 그 자체가 폴백의 증거다★"""
    monkeypatch.setattr(US, "tickers_asof", lambda d: ["000660"])
    ok = _call(universe="all_asof", start_date="2023-01-02")["universe"]
    assert ok["requested"] == ok["effective"], ok
    monkeypatch.setattr(US, "tickers_asof", lambda d: [])
    bad = _call(universe="all_asof", start_date="2023-01-02")["universe"]
    assert bad["requested"] != bad["effective"], bad


def test_the_label_rides_along_with_the_screened_count(route):
    """몇 종목이 실제로 돌았는지 함께 본다 — 라벨만으로는 규모를 모른다."""
    uv = _call(universe="kospi200")["universe"]
    assert uv["tickers_screened"] == 3, uv
