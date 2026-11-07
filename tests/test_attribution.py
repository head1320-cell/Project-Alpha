"""Attribution · Journal · Strategy Health 검증 (Full Expansion P5)

핵심 주장:
  attribution — 사전(저장 run) vs 사후(결정일 이후 가격 경로) 실측. look-ahead 없음.
                섹터/팩터 Brinson은 데이터 미보유 → basis="unavailable"(날조 금지).
                슬리피지·비용은 연결 실체결 있을 때만 실측.
  journal     — run_id 연결, 사후 review·의사결정 품질 편집, Attribution 스냅샷 첨부.
  health      — 등록부·검증 IC/ICIR로 healthy/watch/de_risk 판정, 미연동 신호는 unmeasured.
"""
import os
import time

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from src.engine.attribution import compute_attribution  # noqa: E402
from src.engine.strategy_health import strategy_health  # noqa: E402


# ── Attribution ───────────────────────────────────────────────────────────────
def _run(created_days_ago=90):
    return {
        "run_id": "rr_test_1", "kind": "allocation_analyze", "name": "테스트 런",
        "created_at": time.time() - created_days_ago * 86400,
        "inputs": {"tickers": ["005930", "000660"], "weights": {"005930": 60, "000660": 40}},
        "outputs": {
            "weights": {"optimized": {"005930": 60, "000660": 40}},
            "summary": {"portfolio": {"expected_return_pct": 10.0, "volatility_pct": 18.0},
                        "extra": {"var_pct": -2.5, "cvar_pct": -3.8}},
        },
    }


def _rising(code, s, e):    # 우상향 경로 (종목마다 다른 기울기)
    base = 100.0
    step = 0.5 if code == "005930" else 0.2
    return [base + step * i for i in range(60)]


def _bench(code, s, e):
    return [100.0 + 0.1 * i for i in range(60)]


def test_attribution_expost_real_when_prices_present():
    rep = compute_attribution(_run(), path_of=_rising, benchmark_path=[100 + 0.1 * i for i in range(60)])
    assert rep["coverage"]["has_expost"] is True
    assert rep["returns"]["portfolio_pct"] is not None
    assert rep["returns"]["basis"] == "real"
    assert rep["risk_compare"]["ex_post"]["vol_pct"] is not None
    # 사전 기대(연 10%)가 기간 스케일로 반영
    assert rep["expected_vs_actual"]["expected_return_annual_pct"] == 10.0
    assert rep["contribution"]["assets"]  # 종목별 기여 존재


def test_attribution_brinson_unavailable_honest():
    rep = compute_attribution(_run(), path_of=_rising)
    # 섹터/팩터/타이밍/헤지 Brinson은 데이터 미보유 → 정직 unavailable (날조 금지)
    assert rep["brinson_effects"]["basis"] == "unavailable"
    assert rep["brinson_effects"]["selection"] is None


def test_attribution_no_expost_when_no_prices():
    rep = compute_attribution(_run(), path_of=lambda c, s, e: None)
    assert rep["coverage"]["has_expost"] is False
    assert rep["returns"]["portfolio_pct"] is None
    assert rep["returns"]["basis"] in ("unavailable", "mock")
    assert rep["coverage"]["missing"]


def test_attribution_slippage_only_with_fills():
    # 체결 없음 → 슬리피지/체결품질 미측정
    rep0 = compute_attribution(_run(), path_of=_rising)
    assert rep0["fill_quality"]["basis"] == "unavailable"
    assert rep0["decomposition"]["basis"]["slippage"] == "unavailable"
    # 체결 있음(목표가와 다르게 체결) → 슬리피지 실측
    fills = [{"stock_code": "005930", "filled_qty": 100, "avg_price": 71000, "target_price": 70000}]
    rep1 = compute_attribution(_run(), path_of=_rising, fills=fills, expected_cost_bp=15.0)
    assert rep1["fill_quality"]["basis"] == "real"
    assert rep1["decomposition"]["basis"]["slippage"] == "real"
    assert rep1["decomposition"]["basis"]["cost"] == "real"


def test_attribution_dependency_concentration():
    # 한 종목이 100% → HHI=1, 과집중 경고
    run = _run()
    run["outputs"]["weights"]["optimized"] = {"005930": 100}
    run["inputs"]["tickers"] = ["005930"]
    rep = compute_attribution(run, path_of=_rising)
    assert rep["dependency"]["basis"] == "real"
    assert rep["dependency"]["concentrated"] is True
    assert rep["dependency"]["top_name"] == "005930"


# ── Journal (in-memory SQLite) ────────────────────────────────────────────────
@pytest.fixture
def mem_journal(monkeypatch):
    import src.data.journal_store as js
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    monkeypatch.setattr(js, "_engine", lambda: eng)
    monkeypatch.setattr(js, "_inited", False)
    yield js
    eng.dispose()


def test_journal_run_link_and_review(mem_journal):
    js = mem_journal
    eid = js.create_entry("반도체 비중확대 결정", run_id="rr_test_1",
                          links={"execution_plan_id": "ep_1", "approvers": ["pm"]},
                          record={"thesis": "AI capex 확대", "decision": "반도체 +10%p"},
                          decision_quality="good_outcome_good_process")
    assert eid
    # run_id로 연결 조회 (Attribution ↔ Journal 링크)
    by_run = js.get_by_run("rr_test_1")
    assert by_run and by_run["entry_id"] == eid
    assert by_run["record"]["thesis"] == "AI capex 확대"
    # 사후 회고 편집
    r = js.update_review(eid, review="3개월 후 +8%p — 방향 적중", decision_quality="good_outcome_good_process")
    assert r["ok"] and r["entry"]["review"].startswith("3개월")


def test_journal_invalid_decision_quality_ignored(mem_journal):
    js = mem_journal
    eid = js.create_entry("x", decision_quality="완전엉터리값")
    assert js.get_entry(eid)["decision_quality"] is None   # 유효값만 저장(정직)


# ── Strategy Health ───────────────────────────────────────────────────────────
def test_health_status_from_ic_icir():
    alphas = [
        {"alpha_id": "a1", "name": "좋은알파", "status": "validated", "last_run_id": "r1"},
        {"alpha_id": "a2", "name": "붕괴알파", "status": "validated", "last_run_id": "r2"},
        {"alpha_id": "a3", "name": "미검증", "status": "experimental", "last_run_id": None},
        {"alpha_id": "a4", "name": "은퇴", "status": "retired", "last_run_id": "r4"},
    ]
    runs = {
        "r1": {"created_at": time.time(), "outputs": {"rank_ic": 0.06, "icir": 0.9}},
        "r2": {"created_at": time.time(), "outputs": {"rank_ic": -0.03, "icir": -0.4}},
    }
    h = strategy_health(alphas=alphas, run_getter=lambda rid: runs.get(rid))
    by = {it["alpha_id"]: it["status"] for it in h["items"]}
    assert by["a1"] == "healthy"
    assert by["a2"] == "de_risk"      # 음수 IC/ICIR → 성과 붕괴
    assert by["a3"] == "watch"        # 미검증
    assert by["a4"] == "retired"
    # de-risk 알파는 실행계획 반영용 목록에 노출
    assert any(d["alpha_id"] == "a2" for d in h["derisk_alphas"])
    # 미연동 신호는 정직하게 unmeasured
    a1 = next(it for it in h["items"] if it["alpha_id"] == "a1")
    assert any(s["status"] == "unmeasured" for s in a1["signals"])


def test_health_paused_reflected():
    alphas = [{"alpha_id": "a1", "name": "일시중지", "status": "approved", "last_run_id": "r1"}]
    runs = {"r1": {"created_at": time.time(), "outputs": {"rank_ic": 0.06, "icir": 0.9}}}
    h = strategy_health(alphas=alphas, run_getter=lambda rid: runs.get(rid), paused_ids={"a1"})
    assert h["items"][0]["status"] == "paused"
    assert h["derisk_alphas"][0]["alpha_id"] == "a1"   # paused도 실행계획 반영 대상
