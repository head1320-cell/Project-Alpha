"""백테스터 "평가 종목 상한"이 조건식 유무와 무관하게 스크리닝 후보 풀 크기를 결정하는지 확인.

회귀 배경: 예전엔 buy/sell_conditions가 비어있으면(기본 상태) eval_cap이 max_tickers(≤30)로
쪼그라들고, replenishment_pool_cap 기본값(100)이 사실상 전체 유니버스가 되어 "평가 종목
상한=전체"를 선택해도 100종목만 로드되는 버그가 있었음. screener_routes.py의 full_eval_on
게이팅 제거로 근본 수정 — 이 테스트는 그 수정을 고정한다.
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


def test_universe_eval_cap_applies_without_conditions_default(monkeypatch):
    # 조건식 없음(기본 상태) + universe_eval_cap 기본값(200) → 스크리너가 200 규모로 호출돼야
    # 함(예전 버그: max_tickers=10으로 축소 → replenishment_pool_cap=100이 사실상 유니버스가 됨).
    fake, _bt, _out = _run(monkeypatch)
    assert fake.calls[0]["limit"] == 200


def test_universe_eval_cap_applies_without_conditions_large(monkeypatch):
    # "평가 종목 상한=전체"에 해당하는 큰 값 선택 시, 조건식이 없어도 그 값이 그대로 적용돼야
    # 함(100 고정 버그의 정확한 재현 시나리오).
    fake, _bt, _out = _run(monkeypatch, universe_eval_cap=1000)
    assert fake.calls[0]["limit"] == 1000


def test_replenishment_pool_cap_only_tops_up_when_smaller(monkeypatch):
    # replenishment_pool_cap(100)이 eval_cap(1000)보다 작으면 top-up으로 무시되고 eval_cap이
    # 이김(원래 의도한 "약간의 보충" 동작).
    fake, _bt, _out = _run(monkeypatch, universe_eval_cap=1000, replenishment_pool_cap=100)
    assert fake.calls[0]["limit"] == 1000


def test_max_positions_independent_of_eval_cap(monkeypatch):
    # "평가 종목 상한"(스크리닝 후보 풀)이 커져도, 엔진에 전달되는 동시보유 한도
    # (max_positions, "대상 종목 수" 스테퍼 값)는 별개로 정확히 전달돼야 함 — 두 개념이
    # 섞이지 않는지 확인 (스크리닝 풀은 넓게, 실제 보유는 max_positions가 엔진 레벨에서 강제).
    fake, fake_bt, out = _run(monkeypatch, universe_eval_cap=1000, max_positions=7)
    assert fake.calls[0]["limit"] == 1000
    assert fake_bt.calls[0]["max_positions"] == 7
    # 스크리닝 후보 풀 자체는 넓게 유지(조건식 평가용) — fake 스크리너가 실제 반환한 개수(≤50)
    assert out["screened_count"] == 50
