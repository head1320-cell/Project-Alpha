"""_screen_to_backtest_core의 스크리닝 단계 progress_cb 배선 검증.

배경: _run_advanced_core는 screener.run()에 progress_cb를 넘겨 스크리닝 진행률을
SSE로 흘려보내지만, _screen_to_backtest_core는 이 배선이 누락돼 있었음 — 대형
유니버스(universe_eval_cap 상향)를 스크리닝하는 동안 SSE 커넥션이 완전히 무음
상태가 됨(이미 문서화된 "network error" 실패 모드와 동일 메커니즘). screener.run()의
콜백 시그니처는 위치인자 3개(done, total, misses)이고 _screen_to_backtest_core의
_emit은 dict 하나를 받으므로, 이 둘을 잇는 어댑터 클로저가 실제로 전달되는지 확인한다.
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
    def __call__(self, **kwargs):
        return {"error": False, "result": {
            "statistics": {}, "equity_curve": [], "equity_dates": [],
            "drawdown_curve": [], "monthly_returns": [], "trades": [],
        }}


def test_progress_cb_passed_to_screener_run(monkeypatch):
    fake = _FakeScreener()
    monkeypatch.setattr("src.api.screener_routes.get_screener", lambda: fake)
    monkeypatch.setattr("src.kis_backtest_engine.run_backtest", _FakeRunBacktest())

    events = []
    req = ScreenToBacktestRequest(filter_ast=_AST, buy_conditions=None, sell_conditions=None,
                                  universe="kospi200")
    out = _screen_to_backtest_core(req, progress_cb=lambda e: events.append(e))
    assert not out.get("error"), out.get("message")

    assert "progress_cb" in fake.calls[0]
    screen_cb = fake.calls[0]["progress_cb"]
    assert callable(screen_cb)


def test_screening_progress_cb_adapts_to_phase_event(monkeypatch):
    fake = _FakeScreener()
    monkeypatch.setattr("src.api.screener_routes.get_screener", lambda: fake)
    monkeypatch.setattr("src.kis_backtest_engine.run_backtest", _FakeRunBacktest())

    events = []
    req = ScreenToBacktestRequest(filter_ast=_AST, buy_conditions=None, sell_conditions=None,
                                  universe="kospi200")
    _screen_to_backtest_core(req, progress_cb=lambda e: events.append(e))

    # 스크리너가 내부적으로 (done, total, misses) 형태로 호출했다고 가정하고 직접 호출
    screen_cb = fake.calls[0]["progress_cb"]
    events.clear()
    screen_cb(5, 10, 0)
    assert {"phase": "screening", "done": 5, "total": 10} in events


def test_unary_call_without_progress_cb_unaffected(monkeypatch):
    # progress_cb=None(기존 unary 경로) — 어댑터가 붙어도 무해하게 완주하는지 확인
    fake = _FakeScreener()
    monkeypatch.setattr("src.api.screener_routes.get_screener", lambda: fake)
    monkeypatch.setattr("src.kis_backtest_engine.run_backtest", _FakeRunBacktest())

    req = ScreenToBacktestRequest(filter_ast=_AST, buy_conditions=None, sell_conditions=None,
                                  universe="kospi200")
    out = _screen_to_backtest_core(req)
    assert not out.get("error"), out.get("message")
    # progress_cb는 여전히 전달되지만 (어댑터가 무조건 붙으므로), 호출해도 예외 없이 무해
    screen_cb = fake.calls[0]["progress_cb"]
    screen_cb(1, 2, 0)
