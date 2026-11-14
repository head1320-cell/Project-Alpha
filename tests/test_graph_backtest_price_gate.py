"""그래프 백테스트는 ★운영에서 시세를 지어내지 않는다★ (2026-11-14 · 합성값 전수 감사 §3)

## 무엇이 문제였나

`dag_runner._load_ohlcv` 는 DB 에 시세가 없으면 게이트 없이 `_generate_gbm`(난수 시세)으로 넘어갔다.
관측(운영 게이트 · 빈 DB): `POST /api/v1/backtest/graph` → `success: true` · "DAG 백테스트 완료: 005930, 200일, 1회 거래" ·
수익률 14.51% — ★지어낸 시세 위의 성과가 라벨 없이 나갔다.★ 씨앗이 `hash(symbol)` 이라 프로세스마다 값도 달랐다.
`graph_runner`(호출자 없음)에도 같은 폴백이 있었다.

## 이 파일이 거는 계약

① 운영에서 시세가 없으면 ★계산하지 않는다★ — 실패 + 사유. 생성기는 불리지 않는다.
② 운영에서 시세가 있으면 그 시세로 계산하고 출처를 적는다(짝).
③ mock 에서는 합성 시세로 계산하되 ★합성이라고 적는다★(짝).
④ mock 의 합성 시세는 프로세스가 달라도 같다.
"""
from __future__ import annotations

import subprocess
import sys

import pytest
from sqlalchemy import create_engine, text

import src.engine.dag_runner as dag
import src.engine.graph_runner as legacy
from src.models.graph_schema import GraphBacktestRequest

SYMBOL = "005930"


@pytest.fixture
def engine(tmp_path, monkeypatch):
    eng = create_engine(f"sqlite:///{tmp_path / 'prices.db'}")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE daily_prices (ticker TEXT, trade_date TEXT, open REAL, high REAL, "
                       "low REAL, close REAL, volume REAL)"))
    monkeypatch.setattr("src.database.get_sync_engine", lambda: eng)
    return eng


def _seed(eng, n: int = 80, ticker: str = SYMBOL) -> list[float]:
    """난수가 아닌 시세 — 톱니 모양이라 RSI 가 문턱을 넘나든다. 넣은 종가를 돌려준다."""
    closes = [10_000.0 + 400.0 * ((i % 10) - 5) for i in range(n)]
    with eng.begin() as c:
        for i, px in enumerate(closes):
            c.execute(text("INSERT INTO daily_prices VALUES (:t, :d, :o, :h, :l, :c, :v)"),
                      {"t": ticker, "d": f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}", "o": px, "h": px + 50,
                       "l": px - 50, "c": px, "v": 1_000_000})
    return closes


def _request(lookback: int = 200) -> GraphBacktestRequest:
    return GraphBacktestRequest(nodes=[
        {"id": "d", "type": "dataSource", "position": {"x": 0, "y": 0},
         "data": {"type": "datasource", "symbol": SYMBOL, "lookback": lookback}},
        {"id": "i", "type": "indicator", "position": {"x": 1, "y": 0},
         "data": {"type": "indicator", "indicatorId": "rsi", "label": "RSI", "params": {"period": 5}}},
        {"id": "c", "type": "condition", "position": {"x": 2, "y": 0},
         "data": {"type": "condition", "operator": "<", "compareValue": 40}},
        {"id": "a", "type": "action", "position": {"x": 3, "y": 0}, "data": {"type": "action", "action": "BUY"}},
    ], edges=[{"source": "d", "target": "i"}, {"source": "i", "target": "c"}, {"source": "c", "target": "a"}])


def _forbid(monkeypatch, module, name: str) -> list:
    """생성기를 부르면 기록한다 — 결과만 보면 '만든 뒤 버리는' 구현이 통과한다."""
    calls: list = []
    real = getattr(module, name)

    def spy(*a, **k):
        calls.append(a)
        return real(*a, **k)

    monkeypatch.setattr(module, name, spy)
    return calls


# ══ ① 운영 · 시세 없음 — 계산하지 않는다 ══════════════════════════════════════

def test_prod_without_prices_fails_with_a_reason(engine, monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    made = _forbid(monkeypatch, dag, "_generate_gbm")
    out = dag.execute_dag_backtest(_request())
    assert out.success is False
    assert SYMBOL in out.message and "시세" in out.message
    assert out.equity_curve == [] and out.trades == []
    assert out.statistics.num_trades == 0 and out.statistics.total_return_pct == 0.0
    assert made == [], "운영에서 합성 시세 생성기를 불렀다"


def test_prod_without_prices_says_why_in_the_origin_block(engine, monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    origin = dag.execute_dag_backtest(_request()).data_origin
    assert origin["available"] is False and origin["source"] is None
    assert origin["is_mock"] is False and origin["reason"] == "not_loaded"
    assert origin["message"]


def test_prod_with_too_few_rows_is_also_a_refusal(engine, monkeypatch):
    """스무 줄이 안 되면 예전에는 조용히 합성으로 넘어갔다 — '조금 있다'가 '지어낸다'의 구실이 되면 안 된다."""
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    _seed(engine, n=19)
    made = _forbid(monkeypatch, dag, "_generate_gbm")
    out = dag.execute_dag_backtest(_request())
    assert out.success is False and made == []


def test_the_route_reports_the_refusal_without_a_cost_block(engine, monkeypatch):
    """돌지 않은 실행에 비용 블록을 붙이지 않는다(기존 계약) — 거절도 '돌지 않은 실행'이다."""
    from src.api.strategy_routes import graph_backtest
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    body = graph_backtest(_request().model_dump())
    assert body["success"] is False and "cost_model" not in body
    assert body["data_origin"]["reason"] == "not_loaded"


# ══ ② 운영 · 시세 있음 — 그 시세로(짝) ════════════════════════════════════════

def test_prod_with_prices_runs_on_them_and_names_the_source(engine, monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    closes = _seed(engine, n=80)
    made = _forbid(monkeypatch, dag, "_generate_gbm")
    out = dag.execute_dag_backtest(_request())
    assert out.success is True, out.message
    assert len(out.equity_curve) == len(closes)
    assert out.data_origin == {"available": True, "source": "daily_prices", "is_mock": False,
                               "reason": None, "message": None, "rows": len(closes)}
    assert made == []


def test_the_loader_returns_the_stored_closes(engine, monkeypatch):
    """출처 라벨만 맞고 값은 지어낸 구현을 배제한다 — 종가가 넣은 그대로여야 한다."""
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    closes = _seed(engine, n=40)
    df = dag._load_ohlcv(SYMBOL, 200)
    assert sorted(df["close"].tolist()) == sorted(closes)


# ══ ③ mock — 만들되 합성이라고 적는다(짝) ═════════════════════════════════════

def test_mock_without_prices_runs_on_synthetic_prices_and_says_so(engine, monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    made = _forbid(monkeypatch, dag, "_generate_gbm")
    out = dag.execute_dag_backtest(_request())
    assert out.success is True, out.message
    assert made, "mock 인데 생성기를 부르지 않았다 — 시험이 공허하다"
    assert out.data_origin["source"] == "synthetic" and out.data_origin["is_mock"] is True
    assert out.data_origin["available"] is True and "합성" in out.data_origin["message"]
    assert "합성" in out.message, "성과 문장만 읽는 사람이 합성임을 알 수 없다"


def test_mock_with_prices_still_prefers_the_stored_prices(engine, monkeypatch):
    """mock 이라고 실제 적재분을 버리지 않는다 — 합성은 '없을 때'의 대안이다."""
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    _seed(engine, n=80)
    out = dag.execute_dag_backtest(_request())
    assert out.data_origin["source"] == "daily_prices" and out.data_origin["is_mock"] is False
    assert "합성" not in out.message


# ══ ④ 결정성 — 프로세스가 달라도 같은 합성 시세 ══════════════════════════════

_PROBE = ("import sys; sys.path.insert(0, '.');"
          "import src.engine.{mod} as m; df = m.{fn}('005930', 30);"
          "print(repr(round(float(df['close'].iloc[-1]), 6)))")


@pytest.mark.parametrize("mod,fn", [("dag_runner", "_generate_gbm"), ("graph_runner", "_generate_dummy_ohlcv")])
def test_synthetic_prices_do_not_depend_on_the_process_hash_seed(mod, fn):
    """`hash(symbol)` 은 프로세스마다 다르다 — 그 씨앗으로는 같은 요청이 재시작마다 다른 성과를 낸다."""
    def run(seed: str) -> str:
        r = subprocess.run([sys.executable, "-c", _PROBE.format(mod=mod, fn=fn)], capture_output=True, text=True,
                           env={"PYTHONHASHSEED": seed, "KIS_USE_MOCK": "1", "PATH": ""}, timeout=120)
        assert r.returncode == 0, r.stderr[-400:]
        return r.stdout.strip().splitlines()[-1]
    assert run("1") == run("2")


# ══ 호출자 없는 옛 러너 — 같은 규칙 ═══════════════════════════════════════════

def test_the_legacy_runner_refuses_in_prod_too(engine, monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "0")
    made = _forbid(monkeypatch, legacy, "_generate_dummy_ohlcv")
    with pytest.raises(RuntimeError, match="시세"):
        legacy._load_ohlcv(SYMBOL, 200)
    assert made == []


def test_the_legacy_runner_still_generates_in_mock(engine, monkeypatch):
    monkeypatch.setenv("KIS_USE_MOCK", "1")
    df = legacy._load_ohlcv(SYMBOL, 60)
    assert len(df) == 60
