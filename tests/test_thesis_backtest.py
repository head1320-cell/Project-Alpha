"""논지 → 신호 → 백테스트 — 배선과 퇴화 판정 (P3-1 커밋 ①)

★이 파일이 거는 것★
  1. opt-in 이 **자동으로** 켜지고 그 사실이 라벨로 남는다 — 끄면 kill 조건이
     조용히 무시된다(실측 0/130).
  2. 진입 규칙이 실제로 진입을 만든다 — 없으면 백테스트가 통째로 공허하다.
  3. ★퇴화를 성공으로 보고하지 않는다★ 거래 0건은 "손실 없음" 이 아니라
     "논지가 검증되지 않음" 이다.

★합성 입력을 쓰지 않는다★ 이 세션에서 합성 입력만 쓰다 결함 둘을 놓쳤으므로,
신호 판정은 실제 로더와 실제 `ConditionStrategy` 를 태운다.
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402

from src.engine.company_thesis import OPT_IN_FLAG  # noqa: E402
from src.engine.thesis_backtest import (  # noqa: E402
    DEGENERATE_NEVER_EXITS,
    DEGENERATE_NO_ENTRY,
    ENTRY_CONDITION,
    ENTRY_TOKEN,
    build_backtest_request,
    diagnose_signals,
)

CODE = "005930"
START, END = "2024-01-01", "2024-06-30"
BARS = 130          # ★실측★ 달라지면 상류(mock 로더)가 바뀐 것이다

# 실제 ROE 는 19.27 — 임계값을 사이에 두고 항상 참 / 항상 거짓을 만든다.
THR_ALWAYS_TRUE = 25.0
THR_ALWAYS_FALSE = 8.0


def _thesis(thr: float = THR_ALWAYS_FALSE, field: str = "roe") -> dict:
    return {"claim": "반도체 사이클 저점에서 ROE 가 정상화된다",
            "kill_conditions": [{"kind": "field", "field": field,
                                 "op": "lt", "value": thr}]}


def _build(thesis: dict, **kw) -> dict:
    return build_backtest_request(thesis, code=CODE, start_date=START,
                                  end_date=END, **kw)


def _diag(built: dict) -> dict:
    return diagnose_signals(built["request"]["sell_conditions"], code=CODE,
                            start_date=START, end_date=END,
                            allow_snapshot=built["lookahead"])


@pytest.fixture(scope="module")
def bars() -> int:
    from src.data.ohlcv_loader import load_ohlcv_unified
    df = load_ohlcv_unified(CODE, START, END, prefer="auto")
    if df is None or len(df) == 0:
        pytest.skip("이 환경에서 시세를 낼 수 없다")
    return int(len(df))


# ── 1. ★자동 opt-in 과 그 라벨★ ────────────────────────────────────────────
def test_a_lookahead_kill_turns_the_opt_in_on_automatically():
    """★끄면 kill 조건이 조용히 무시된다★ 실측 0/130 — 가장 나쁜 결과다."""
    b = _build(_thesis())
    assert b["available"] is True, b["reason"]
    assert b["request"][OPT_IN_FLAG] is True
    assert b["auto_enabled_opt_in"] is True
    assert b["lookahead"] is True
    assert OPT_IN_FLAG in b["lookahead_reason"]
    assert "조용히 무시" in b["lookahead_reason"]


def test_a_clean_kill_does_not_turn_it_on(monkeypatch):
    """★짝★ tier 1 만이면 켜지 않는다 — 필요 없는 근사를 켜지 않는다."""
    monkeypatch.setattr("src.engine.company_thesis.history_loaded", lambda code: True)
    b = _build(_thesis())
    assert b["request"][OPT_IN_FLAG] is False
    assert b["auto_enabled_opt_in"] is False
    assert b["lookahead"] is False and b["lookahead_reason"] is None


def test_nothing_liftable_builds_no_request_at_all():
    """★돌리지도 기록하지도 않는다★ 올릴 조건이 없으면 그냥 바이앤홀드다."""
    b = _build({"claim": "x", "kill_conditions": []})
    assert b["available"] is False and b["reason"]
    assert b["request"] is None


def test_a_screen_only_kill_builds_no_request():
    b = _build(_thesis(field="momentum_12_1", thr=0.0))
    assert b["available"] is False and b["request"] is None
    assert b["lift"]["excluded"], "제외 사유가 함께 나온다"


# ── 2. ★진입 규칙★ ────────────────────────────────────────────────────────
def test_the_entry_condition_is_attached_because_a_thesis_has_none():
    """매수 조건이 0개면 한 번도 진입하지 않는다 — 백테스트가 통째로 공허해진다."""
    b = _build(_thesis())
    assert b["request"]["buy_conditions"] == [ENTRY_CONDITION]
    assert "진입 규칙" in b["entry"]["note"]


def test_the_entry_token_is_an_existing_base_token():
    """★새 토큰 0★ 진입을 위해 어휘를 늘리지 않는다."""
    from src.kis_strategies.factor_tokens import BASE_TOKENS
    assert ENTRY_TOKEN in BASE_TOKENS


def test_the_entry_actually_produces_entries(bars):
    """★실측으로 검산★ 진입만 태우면 전 봉 BUY 다."""
    assert bars == BARS, f"봉 수가 {BARS} 에서 바뀌었다: {bars} — 상류를 먼저 본다"
    d = diagnose_signals([], code=CODE, start_date=START, end_date=END,
                         allow_snapshot=False)
    assert d["available"] is True
    assert d["buy_bars"] == bars and d["sell_bars"] == 0


# ── 3. ★퇴화를 성공으로 보고하지 않는다★ ──────────────────────────────────
def test_an_always_true_kill_never_enters_and_says_so(bars):
    """★거래 0건은 '손실 없음' 이 아니라 '검증 안 됨' 이다★"""
    d = _diag(_build(_thesis(THR_ALWAYS_TRUE)))
    assert d["sell_bars"] == bars
    assert d["buy_bars"] == 0, "매도 우선이라 진입 자체가 없다"
    assert d["degenerate"] == DEGENERATE_NO_ENTRY
    assert "검증되지 않음" in d["reason"]


def test_an_always_false_kill_is_pure_buy_and_hold_and_says_so(bars):
    """★짝★ 반대쪽 퇴화도 잡는다 — 한 쪽만 잡으면 절반이 조용히 지나간다."""
    d = _diag(_build(_thesis(THR_ALWAYS_FALSE)))
    assert d["sell_bars"] == 0 and d["buy_bars"] == bars
    assert d["degenerate"] == DEGENERATE_NEVER_EXITS
    assert "바이앤홀드" in d["reason"]


def test_a_snapshot_constant_condition_is_reported_as_constant(bars):
    """★상수가 look-ahead 의 관측 가능한 형태다★ 라벨이 아니라 측정이다."""
    for thr in (THR_ALWAYS_TRUE, THR_ALWAYS_FALSE):
        row = _diag(_build(_thesis(thr)))["rows"][0]
        assert row["available"] is True
        assert row["constant_over_window"] is True
        assert row["lookahead"] is True
        assert row["total_bars"] == bars
        assert row["reason"]
    assert _diag(_build(_thesis(THR_ALWAYS_TRUE)))["rows"][0]["always_true"] is True
    assert _diag(_build(_thesis(THR_ALWAYS_FALSE)))["rows"][0]["always_false"] is True


def test_the_opt_in_being_off_makes_the_kill_silently_inert(bars):
    """★이것이 자동 opt-in 의 근거다★ 참인 조건조차 0건이 된다(실측 0/130)."""
    conds = _build(_thesis(THR_ALWAYS_TRUE))["request"]["sell_conditions"]
    off = diagnose_signals(conds, code=CODE, start_date=START, end_date=END,
                           allow_snapshot=False)
    assert off["sell_bars"] == 0, "꺼져 있으면 참인 kill 조건도 발동하지 않는다"
    on = diagnose_signals(conds, code=CODE, start_date=START, end_date=END,
                          allow_snapshot=True)
    assert on["sell_bars"] == bars, "켜면 발동한다 — 둘의 차이가 함정의 크기다"


def test_an_empty_price_window_is_a_reason_not_a_crash(monkeypatch):
    """★mock 로더는 **요청한 범위를 무엇이든 만들어 낸다**★ (이 세션의 결함 B 가
    바로 그것이었다 — 2099년을 물으면 2099년 봉을 준다). 그러므로 빈 창은 먼 미래
    날짜가 아니라 로더를 직접 비워서 확인한다."""
    import pandas as pd
    monkeypatch.setattr("src.engine.thesis_backtest._load_bars",
                        lambda *a, **kw: pd.DataFrame())
    d = diagnose_signals([], code=CODE, start_date=START, end_date=END,
                         allow_snapshot=False)
    assert d["available"] is False and d["reason"]


def test_a_dead_loader_answers_with_a_reason(monkeypatch):
    def _boom(*a, **kw):
        raise RuntimeError("시세 불가")
    monkeypatch.setattr("src.engine.thesis_backtest._load_bars", _boom)
    d = diagnose_signals([], code=CODE, start_date=START, end_date=END,
                         allow_snapshot=False)
    assert d["available"] is False and "RuntimeError" in d["reason"]


# ── 4. ★있는 다리에 올린다 — 새 스키마 0★ ─────────────────────────────────
def test_the_payload_validates_as_the_existing_request_model():
    """★새 스키마를 만들지 않는다★ 기존 요청 모델이 그대로 받아야 한다."""
    from src.api.screener_routes import ScreenToBacktestRequest
    req = ScreenToBacktestRequest(**_build(_thesis())["request"])
    assert req.custom_tickers == [CODE]
    assert req.strategy_name == "Condition"
    assert req.sell_conditions and req.buy_conditions
    assert getattr(req, OPT_IN_FLAG) is True
    assert req.max_positions == 1


def test_the_empty_filter_passes_the_screener_untouched():
    """단일 종목 경로는 필터를 지어내지 않는다 — 빈 그룹이 유효하다."""
    from src.engine.filter_ast import parse_group
    ast = parse_group(_build(_thesis())["request"]["filter_ast"])
    assert ast.is_empty() is True
    assert ast.validate() is None


def test_only_settings_can_be_overridden_not_the_universe():
    """★단일 종목 계약★ 유니버스를 인자로 열면 다른 슬라이스가 된다."""
    ok = _build(_thesis(), initial_capital=50_000_000)
    assert ok["available"] is True
    assert ok["request"]["initial_capital"] == 50_000_000

    bad = _build(_thesis(), universe="kospi200")
    assert bad["available"] is False and "덮어쓸 수 없는" in bad["reason"]
    assert bad["request"] is None


def test_the_lifted_conditions_come_from_the_p2_5_engine():
    """★조건 변환을 다시 쓰지 않는다★ P2-5 의 산출을 그대로 싣는다."""
    from src.engine.company_thesis import thesis_to_sell_conditions
    t = _thesis()
    assert _build(t)["request"]["sell_conditions"] == \
        thesis_to_sell_conditions(t, code=CODE)["conditions"]
