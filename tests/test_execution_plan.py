"""실행 준비실 검증 (Full Expansion P4)

핵심 주장:
  market_rules — 틱사이즈 표·매도세 편도·설정 계층(하드코딩 로직 아님)
  오더 diff    — 현재→목표 비중차 → buy/sell 수량·금액, 매도 우선 우선순위·단계
  비용         — 수수료(양편)·세금(매도만)·스프레드·충격(참여율 sqrt) 분해
  참여율       — 거래대금 대비 참여율 · 유동성 경고
  pre-trade    — pass/warning/block, block이면 can_approve=False
  워크플로     — draft→reviewed→approved(pre-trade block 시 거부)→paper_submitted,
                자동 시뮬 없음(체결은 수동 입력), 감사 로그 기록
"""
import os

os.environ.setdefault("KIS_USE_MOCK", "1")

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from src.data import market_rules as mr  # noqa: E402
from src.engine.execution_plan import build_plan, pre_trade_checks  # noqa: E402


# ── market_rules ──────────────────────────────────────────────────────────────
def test_tick_size_table():
    assert mr.tick_size(1500) == 1
    assert mr.tick_size(3000) == 5
    assert mr.tick_size(12000) == 10
    assert mr.tick_size(70000) == 100
    assert mr.tick_size(300000) == 500
    assert mr.tick_size(1000000) == 1000
    assert mr.round_to_tick(12345, "up") == 12350
    assert mr.is_on_tick(12340) and not mr.is_on_tick(12345)


def test_rules_snapshot_shape():
    r = mr.rules_snapshot()
    assert "commission_bp" in r and "sell_tax_bp" in r and "tick_table" in r
    assert "브로커" in r["source"]


# ── 오더 diff + 비용 ──────────────────────────────────────────────────────────
PRICES = {"005930": 70000, "000660": 130000, "035420": 200000, "051910": 400000}
ADV = {c: 5e10 for c in PRICES}   # 500억 — 참여율 낮게


def _px(c):
    return PRICES.get(c)


def _adv(c):
    return ADV.get(c)


def test_order_diff_sides_and_priority():
    plan = build_plan(
        current_weights={"005930": 50, "000660": 50},
        target_weights={"005930": 30, "035420": 70},
        portfolio_value=1e9, price_of=_px, adv_of=_adv)
    sides = {o["stock_code"]: o["side"] for o in plan["orders"]}
    assert sides["005930"] == "sell"   # 50→30 축소
    assert sides["000660"] == "sell"   # 50→0 청산
    assert sides["035420"] == "buy"    # 0→70 신규
    # 매도 우선(현금 확보) — 우선순위 1~2가 sell
    top2 = sorted(plan["orders"], key=lambda o: o["priority"])[:2]
    assert all(o["side"] == "sell" for o in top2)
    assert all(o["stage"] == 1 for o in top2)


def test_cost_breakdown_tax_only_on_sell():
    plan = build_plan({"005930": 0}, {"005930": 100}, 1e9, price_of=_px, adv_of=_adv)
    buy = plan["orders"][0]
    assert buy["side"] == "buy" and buy["cost_breakdown"]["tax"] == 0   # 매수 무세금
    assert buy["cost_breakdown"]["commission"] > 0

    plan2 = build_plan({"005930": 100}, {"005930": 0}, 1e9, price_of=_px, adv_of=_adv)
    sell = plan2["orders"][0]
    assert sell["side"] == "sell" and sell["cost_breakdown"]["tax"] > 0   # 매도 세금


def test_participation_and_liquidity_warning():
    # ADV 아주 작게 → 참여율 폭증 → 경고
    plan = build_plan({"005930": 0}, {"005930": 100}, 1e9,
                      price_of=_px, adv_of=lambda c: 1e8)   # 1억 ADV
    o = plan["orders"][0]
    assert o["participation_pct"] > 100
    assert any("참여율" in w for w in o["warnings"])


def test_missing_price_honest():
    plan = build_plan({}, {"999999": 100}, 1e9, price_of=lambda c: None, adv_of=_adv)
    assert "999999" in plan["missing_price"]
    assert any("미보유" in n for n in plan["notes"])


# ── pre-trade ─────────────────────────────────────────────────────────────────
def test_pretrade_block_stops_approval():
    plan = build_plan({"005930": 50, "000660": 50}, {"035420": 100}, 1e9,
                      price_of=_px, adv_of=_adv)
    pt = pre_trade_checks(plan, limits={"turnover_cap_pct": 10})   # 회전율 100% > 10 → block
    assert pt["overall"] == "block" and pt["can_approve"] is False
    assert any(c["status"] == "block" and c["name"] == "회전율" for c in pt["checks"])


def test_pretrade_pass_allows_approval():
    plan = build_plan({"005930": 50}, {"005930": 55}, 1e9, price_of=_px, adv_of=_adv)
    pt = pre_trade_checks(plan, limits={})
    assert pt["can_approve"] is True


def test_pretrade_cash_tolerance():
    # 완전투자 리밸런싱은 매수≈매도라 비용만큼만 음수 → block이 아니라 warning (승인 가능)
    plan = build_plan({"005930": 50, "000660": 50}, {"005930": 30, "000660": 70},
                      1e9, price_of=_px, adv_of=_adv)
    pt_small = pre_trade_checks(plan, limits={"cash_after_pct": -0.1})
    cash = next(c for c in pt_small["checks"] if c["name"] == "현금")
    assert cash["status"] == "warning" and pt_small["can_approve"] is True
    # 유의미 초과(타깃 합 >> 현금)는 여전히 block
    pt_big = pre_trade_checks(plan, limits={"cash_after_pct": -25.0})
    cash_big = next(c for c in pt_big["checks"] if c["name"] == "현금")
    assert cash_big["status"] == "block" and pt_big["can_approve"] is False


# ── 워크플로 + 감사 ───────────────────────────────────────────────────────────
@pytest.fixture
def mem_store(monkeypatch):
    import src.data.execution_store as es
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    monkeypatch.setattr(es, "_engine", lambda: eng)
    monkeypatch.setattr(es, "_inited", False)
    yield es
    eng.dispose()


def test_workflow_and_audit(mem_store):
    es = mem_store
    plan = build_plan({"005930": 50}, {"005930": 55}, 1e9, price_of=_px, adv_of=_adv)
    pt = pre_trade_checks(plan, limits={})
    pid = es.create_plan("테스트 계획", plan, pt)
    assert pid and es.get_plan(pid)["status"] == "draft"

    # draft → approved 직행 불가 (reviewed 경유)
    assert es.transition(pid, "approved")["ok"] is False
    assert es.transition(pid, "reviewed")["ok"] is True
    assert es.transition(pid, "approved")["ok"] is True
    assert es.transition(pid, "paper_submitted")["ok"] is True
    # paper_submitted 이후 자동 진행 없음 — 수동 체결로만
    r = es.record_fills(pid, [{"stock_code": "005930", "filled_qty": 100, "avg_price": 70000}])
    assert r["ok"] is True and r["plan"]["status"] in ("filled", "partially_filled")
    # 감사 로그에 전 과정 기록
    audit = es.get_plan(pid)["audit"]
    actions = [a["action"] for a in audit]
    assert "created" in actions and "transition" in actions and "fills" in actions


def test_workflow_block_cannot_approve(mem_store):
    es = mem_store
    plan = build_plan({"005930": 50, "000660": 50}, {"035420": 100}, 1e9, price_of=_px, adv_of=_adv)
    pt = pre_trade_checks(plan, limits={"turnover_cap_pct": 10})
    pid = es.create_plan("블록 계획", plan, pt)
    es.transition(pid, "reviewed")
    r = es.transition(pid, "approved")
    assert r["ok"] is False and "block" in r["reason"]   # §4: block은 승인 불가
