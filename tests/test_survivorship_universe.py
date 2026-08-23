"""_screen_to_backtest_core의 all_asof/top200_asof 유니버스 분기가 as_of_date를
screener.run()에 전달하는지 확인.

배경: 생존편향 보정 유니버스(상장폐지 종목 포함)를 선택해도, 그 뒤 screener.run()이
as_of_date 없이 호출되면 상장폐지 종목은 오늘자 라이브 재무가 없어 "데이터 없음"으로
다시 걸러져 보정이 무력화된다. bsns_year look-ahead bias 수정(PIT 경로)이 선행된
상태에서만 이 전달이 의미를 갖는다.
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

from src.api.screener_routes import ScreenToBacktestRequest, _screen_to_backtest_core  # noqa: E402

_AST = {"logic": "AND", "conditions": [], "groups": []}


class _FakeItem:
    def __init__(self, code):
        self.stock_code = code
        self.corp_name = f"종목{code}"
        self.composite_score = 50.0


class _FakeResult:
    def __init__(self, items):
        self.items = items


class _FakeScreener:
    def __init__(self):
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        limit = kwargs.get("limit", 10)
        return _FakeResult([_FakeItem(f"{100000 + i:06d}") for i in range(min(limit, 50))])


class _FakeRunBacktest:
    def __init__(self):
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return {"error": False, "result": {
            "statistics": {}, "equity_curve": [], "equity_dates": [],
            "drawdown_curve": [], "monthly_returns": [], "trades": [],
        }}


def _run(monkeypatch, **req_kwargs):
    fake = _FakeScreener()
    fake_bt = _FakeRunBacktest()
    monkeypatch.setattr("src.api.screener_routes.get_screener", lambda: fake)
    monkeypatch.setattr("src.kis_backtest_engine.run_backtest", fake_bt)
    req = ScreenToBacktestRequest(filter_ast=_AST, buy_conditions=None, sell_conditions=None,
                                  **req_kwargs)
    out = _screen_to_backtest_core(req)
    assert not out.get("error"), out.get("message")
    return fake, fake_bt, out


def test_all_asof_passes_as_of_date(monkeypatch):
    monkeypatch.setattr("src.engine.universe_select.tickers_asof", lambda d: ["005930", "000660"])
    fake, _bt, _out = _run(monkeypatch, universe="all_asof", start_date="2020-06-15")
    assert fake.calls[0]["as_of_date"] == "2020-06-15"
    assert fake.calls[0]["universe"] == ["005930", "000660"]


def test_top200_asof_passes_as_of_date(monkeypatch):
    monkeypatch.setattr("src.engine.universe_select.top_mktcap_asof", lambda d, n: ["005930"])
    fake, _bt, _out = _run(monkeypatch, universe="top200_asof", start_date="2019-03-01")
    assert fake.calls[0]["as_of_date"] == "2019-03-01"


def test_normal_universe_leaves_as_of_date_none(monkeypatch):
    fake, _bt, _out = _run(monkeypatch, universe="kospi200")
    assert fake.calls[0].get("as_of_date") is None


def test_all_asof_fallback_still_sets_as_of_date(monkeypatch):
    # 시점 데이터 없어 all_listed로 폴백해도 as_of_date는 여전히 전달돼야 함 —
    # 폴백 유니버스 평가에도 PIT 경로가 적용되도록.
    monkeypatch.setattr("src.engine.universe_select.tickers_asof", lambda d: [])
    fake, _bt, _out = _run(monkeypatch, universe="all_asof", start_date="2020-06-15")
    assert fake.calls[0]["universe"] == "all_listed"
    assert fake.calls[0]["as_of_date"] == "2020-06-15"
