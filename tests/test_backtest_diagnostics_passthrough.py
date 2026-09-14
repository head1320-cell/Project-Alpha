"""엔진의 진단 라벨이 ★라우트를 통과해 화면까지 간다★ (`DIAGNOSTIC_KEYS`)

## 왜 이 파일이 있나 — ★공백이 아니라 단선이었다★

`kis_backtest_engine._build_result` 는 `signal_path`·`macro_lookahead`·
`fundamentals_pit` 을 결과에 싣는다. 프런트에는 그것을 읽는 타입과 렌더러가
있고(`bridgeModel.ts`·`BacktestResults.tsx`), 텔레메트리에는 그것을 집계하는
코드가 있다(`backtest_run_routes.py`). **그런데 가운데가 끊겨 있었다** —
`_screen_to_backtest_core` 가 반환 dict 를 키로 **손수 나열**하면서 그 셋을
빠뜨렸다. 그래서:

  · 결과 화면의 매크로·재무 정직성 문장이 **한 줄도 그려지지 않았고**
  · `tele["macro_lookahead"]` 는 `isinstance(dict)` 가 거짓이라 **키조차 안 생겼다**

★기존 테스트가 이 구간을 지나지 않았다★ — `test_macro_lookahead_meta.py` 는
엔진을 직접 부르고(`BacktestEngine(...).run()`), 라우트 테스트는 진단 키를
보지 않았다. 양쪽 다 초록인데 사용자 화면은 비어 있었다.

## 무엇을 못 박나 — ★인스턴스가 아니라 부류★

결함의 원인은 "라우트가 키를 손으로 센다" 는 **구조**다. 그래서 키 하나를
되살리는 대신 목록을 엔진에 두고(`DIAGNOSTIC_KEYS`) 라우트가 그것을 전개하게
했다. 이 파일은 그 계약을 양쪽에서 건다:

  ① 목록의 **모든** 키가 라우트 응답에 도달한다
  ② ★짝★ 목록에 없는 키는 복사되지 않는다 (통짜 `**bt` 로 때우면 죽는다)
  ③ ★트립와이어★ 엔진이 실제로 그 키들을 낸다 (엔진 쪽 이름이 바뀌면 여기서 깨진다)
  ④ 엔진이 키를 빠뜨려도 **키는 있고 값이 `None`** 이다 (미측정과 부재를 구별)
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from src.api.screener_routes import (  # noqa: E402
    ScreenToBacktestRequest,
    _screen_to_backtest_core,
)
from src.kis_backtest_engine import DIAGNOSTIC_KEYS  # noqa: E402

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
    def run(self, **kwargs):
        limit = kwargs.get("limit", 10)
        return _FakeResult([_FakeItem(f"{100000 + i:06d}") for i in range(min(limit, 3))])


#: 엔진이 낼 법한 최소 결과 + ★목록에 없는 키 하나★(②의 미끼)
def _fake_bt(**extra):
    out = {
        "error": False,
        "result": {"statistics": {}, "equity_curve": [], "equity_dates": [],
                   "drawdown_curve": [], "monthly_returns": [], "trades": []},
        "not_a_diagnostic": "이 키는 응답에 나타나면 안 된다",
    }
    out.update(extra)
    return out


def _call(monkeypatch, bt: dict, **req_kw) -> dict:
    monkeypatch.setattr("src.api.screener_routes.get_screener", lambda: _FakeScreener())
    monkeypatch.setattr("src.kis_backtest_engine.run_backtest", lambda **kw: bt)
    req = ScreenToBacktestRequest(filter_ast=_AST, buy_conditions=None,
                                  sell_conditions=None,
                                  universe=req_kw.pop("universe", "kospi200"), **req_kw)
    return _screen_to_backtest_core(req)


# ═══════════════════════════════════════════════════════════════════════════
# ① 목록의 모든 키가 도달한다
# ═══════════════════════════════════════════════════════════════════════════

def test_every_diagnostic_key_reaches_the_response(monkeypatch):
    """★키 하나를 고치는 게 아니라 목록 전체를 건다★"""
    sentinels = {k: {"sentinel": k} for k in DIAGNOSTIC_KEYS}
    out = _call(monkeypatch, _fake_bt(**sentinels))
    for k in DIAGNOSTIC_KEYS:
        assert k in out, f"진단 키 `{k}` 가 라우트에서 사라졌다 — 화면·텔레메트리가 눈이 먼다"
        assert out[k] == {"sentinel": k}, f"`{k}` 가 다른 값으로 바뀌었다: {out[k]!r}"


#: ★골든 스냅샷★ — 목록 자체를 못 박는다.
#:
#: ① 만으로는 **목록에서 키를 빼는** 변이가 살아남는다(검사할 키가 줄 뿐이다).
#: 그런데 키를 빼는 것이 곧 이 파일이 막으려는 결함이다 — 진단 하나가 조용히
#: 화면에서 사라지는 것. 그래서 목록을 여기 **글자로** 적는다.
#:
#: 이 스냅샷을 고쳐야 한다면 그것이 정상이다. 다만 같은 커밋에서 프런트 타입
#: (`bridgeModel.ts`)과 텔레메트리(`backtest_run_routes.py`)도 함께 고쳐야 한다는
#: 뜻이고, 이 테스트가 그 사실을 상기시키는 것이 목적이다.
EXPECTED_DIAGNOSTIC_KEYS = ("signal_path", "macro_lookahead", "fundamentals_pit",
                            "price_basis", "execution_assumption", "estimator_leakage")


def test_the_key_list_is_pinned():
    """★공허한 하네스는 증거가 아니다★ 목록이 비거나 줄면 ① 은 언제나 통과한다."""
    assert DIAGNOSTIC_KEYS == EXPECTED_DIAGNOSTIC_KEYS, (
        "진단 키 목록이 바뀌었다 — 프런트 타입과 텔레메트리도 함께 고쳤는지 확인하고 "
        "이 스냅샷을 갱신하세요."
    )
    assert len(set(DIAGNOSTIC_KEYS)) == len(DIAGNOSTIC_KEYS), "중복된 키"


# ═══════════════════════════════════════════════════════════════════════════
# ② ★짝★ — 목록에 없는 키는 새어 나가지 않는다
# ═══════════════════════════════════════════════════════════════════════════

def test_keys_outside_the_list_are_not_copied(monkeypatch):
    """★통짜 `**bt` 로 때우면 여기서 죽는다★

    ① 만으로는 "엔진 반환을 통째로 펼친다" 는 구현도 통과한다. 그러면 내부
    구조가 그대로 새어 나가고, 무엇이 계약인지 아무도 말할 수 없게 된다.
    """
    out = _call(monkeypatch, _fake_bt())
    assert "not_a_diagnostic" not in out, "목록에 없는 엔진 내부 키가 응답으로 새어 나갔다"


# ═══════════════════════════════════════════════════════════════════════════
# ③ ★트립와이어★ — 엔진이 실제로 그 키들을 낸다
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def frames(monkeypatch):
    """최소 실행용 합성 프레임 — ★숫자는 아무것도 말하지 않는다★ 키만 본다."""
    import numpy as np

    import src.data.ohlcv_loader as L
    import src.kis_strategies.condition_strategy  # noqa: F401 (전략 레지스트리 등록)

    rng = np.random.default_rng(11)
    idx = pd.bdate_range("2023-01-02", periods=320)
    out = {}
    for i in range(3):
        c = 10000 * np.exp(np.cumsum(rng.normal(0, .015, len(idx))))
        out[f"{i:06d}"] = pd.DataFrame(
            {"open": c * .995, "high": c * 1.01, "low": c * .99,
             "close": c, "volume": rng.integers(1e5, 1e6, len(idx))}, index=idx)
    monkeypatch.setattr(L, "load_ohlcv_unified",
                        lambda tk, s, e, prefer="auto": out.get(tk, pd.DataFrame()).copy())
    return out


def test_the_engine_really_emits_every_declared_key(frames):
    """★선언했다고 내는 것은 아니다★ 엔진을 돌려 키 존재를 확인한다.

    값은 보지 않는다 — 매크로를 안 쓴 실행의 `macro_lookahead` 는 `None` 이 정답이다.
    보는 것은 **키가 있는가** 이고, 그것이 라우트 전개의 전제다.
    """
    from src.kis_backtest_engine import BacktestConfig, BacktestEngine
    res = BacktestEngine(BacktestConfig(
        symbols=list(frames), strategy_name="Condition",
        strategy_params={
            "buy_conditions": [{"factor_token": "종가", "function_id": "pct",
                                "params": {"n": 5}, "op": "lte", "rhs": -3}],
            "sell_conditions": [{"factor_token": "종가", "function_id": "pct",
                                 "params": {"n": 5}, "op": "gte", "rhs": 5}]},
        start_date="2023-06-01", end_date="2024-03-01", max_positions=2)).run()
    assert not res.get("error"), res.get("message")
    missing = [k for k in DIAGNOSTIC_KEYS if k not in res]
    assert not missing, f"엔진이 선언한 진단 키를 내지 않는다: {missing}"


# ═══════════════════════════════════════════════════════════════════════════
# ④ 엔진이 빠뜨려도 키는 있고 값이 None — ★미측정과 부재를 구별한다★
# ═══════════════════════════════════════════════════════════════════════════

def test_a_missing_engine_key_becomes_an_explicit_none(monkeypatch):
    """에러 응답 등 진단이 없는 실행에서도 **키는 있다**.

    프런트가 `res.macro_lookahead` 를 읽을 때 "키가 없다" 와 "값이 없다" 를
    구별할 수 없으면, 통로가 또 끊겨도 같은 방식으로 조용해진다.
    """
    out = _call(monkeypatch, _fake_bt())
    for k in DIAGNOSTIC_KEYS:
        assert k in out, f"`{k}` 키가 아예 없다"
        assert out[k] is None, f"`{k}` 가 지어낸 값을 들고 있다: {out[k]!r}"
