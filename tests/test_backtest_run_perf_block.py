"""`run_full` 의 `perf` 블록 — 화면이 세지 않도록 서버가 낸다 (2026-11-09 · 결과 화면 성과 그림 문법 §3.2)

- 끝난 실행: `perf.drawdown_pct` = 저장된 비율 ×100(엔진은 비율로 저장하고 통계는 %) · `periods`·`drawdowns` = 같은 곡선의 `quant_metrics` 재계산.
- 낙폭 곡선이 없는 결과: `drawdown_pct: None`(0 배열이 아니다).
- 끝나지 않은 실행 / result 없음: `perf: None` — 화면이 "주지 않았어요" 라고 말한다.
- 기존 키는 그대로(짝 — `test_perf_label_wiring` 과 같은 규율).
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("KIS_USE_MOCK", "1")

DATES = ["2023-01-02", "2023-01-03", "2023-02-01", "2023-02-02", "2024-01-02"]
EQ = [100.0, 103.0, 98.0, 108.0, 112.0]
DD = [0.0, 0.0, -0.0485, 0.0, 0.0]       # 엔진 저장 꼴 — 비율


def _row(result):
    return {"run_id": "R-1", "status": "completed", "strategy_name": "테스트", "is_mock_data": True,
            "is_pit_verified": None, "result": result}


def _done():
    return _row({"backtest": {"statistics": {"max_drawdown_pct": 4.85}, "equity_curve": EQ, "equity_dates": DATES,
                              "drawdown_curve": DD}})


def test_a_finished_run_ships_drawdown_in_percent_and_periods_from_the_same_curve(monkeypatch):
    from src.api import backtest_run_routes as rr
    from src.engine.quant_metrics import drawdown_episodes, period_returns
    monkeypatch.setattr(rr.br, "get_run", lambda rid, strict=False: _done())
    perf = rr.run_full("R-1")["perf"]
    assert perf["unit"] == "krw"
    assert perf["drawdown_pct"] == pytest.approx([d * 100 for d in DD], abs=1e-3)
    assert abs(min(perf["drawdown_pct"])) == pytest.approx(4.85, abs=0.01)          # 통계와 같은 단위
    assert perf["periods"] == period_returns(DATES, EQ)
    assert perf["drawdowns"] == drawdown_episodes(DATES, EQ, top=3)
    assert len(perf["periods"]["yearly"]) == 2 and perf["periods"]["yearly"][0]["partial"] is True


def test_a_result_without_a_drawdown_curve_says_none_not_zeros(monkeypatch):
    from src.api import backtest_run_routes as rr
    row = _done()
    del row["result"]["backtest"]["drawdown_curve"]
    monkeypatch.setattr(rr.br, "get_run", lambda rid, strict=False: row)
    perf = rr.run_full("R-1")["perf"]
    assert perf["drawdown_pct"] is None
    assert perf["periods"]["yearly"], "곡선은 있으니 기간별 수익은 있다"


@pytest.mark.parametrize("row", [
    {"run_id": "R-1", "status": "simulating", "strategy_name": "테스트", "is_mock_data": True, "result": None},
    {"run_id": "R-1", "status": "completed", "strategy_name": "테스트", "is_mock_data": True, "result": {"total_return_pct": 1.0}},
])
def test_an_unfinished_or_curveless_run_has_perf_none(monkeypatch, row):
    from src.api import backtest_run_routes as rr
    monkeypatch.setattr(rr.br, "get_run", lambda rid, strict=False: dict(row))
    assert rr.run_full("R-1")["perf"] is None


def test_existing_keys_are_untouched(monkeypatch):
    from src.api import backtest_run_routes as rr
    row = _done()
    monkeypatch.setattr(rr.br, "get_run", lambda rid, strict=False: dict(row))
    body = rr.run_full("R-1")
    for k, v in row.items():
        assert body[k] == v, f"{k} 가 바뀌었다"
    assert body["result"]["backtest"]["drawdown_curve"] == DD, "저장 결과는 그대로(비율) — 바꾼 것이 아니라 더한 것"


# ── 경로 배선 — ★E2E 가 잡은 결함(2026-11-09)★ ───────────────────────────────
# `_perf_block` 을 `@router.get("/runs/{run_id}")` 와 `run_full` 사이에 끼워 넣어 데코레이터가 헬퍼를 받았다 — GET 이 body 를
# 요구해 422 를 내고 `run_full` 은 경로에서 빠졌다. 함수를 직접 부르는 위 시험은 전부 통과했다(라우트 표를 안 봤다).
def test_the_full_run_get_route_still_points_at_run_full_and_a_missing_id_is_404(monkeypatch):
    from fastapi.testclient import TestClient

    from src.api import backtest_run_routes as rr
    from src.app_factory import create_app
    from tests.route_walk import flat_routes

    app = create_app()
    hits = [r for r in flat_routes(app) if r.path == "/api/v1/backtest/runs/{run_id}" and "GET" in (r.methods or ())]
    assert [r.endpoint.__name__ for r in hits] == ["run_full"]
    monkeypatch.setattr(rr.br, "get_run", lambda rid, strict=False: None)
    res = TestClient(app).get("/api/v1/backtest/runs/bt_missing")
    assert res.status_code == 404, res.text                       # 422(body 요구) 가 아니다
