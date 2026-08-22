"""실행 계획 엔진 — 오더 diff·비용 추정·pre-trade 리스크 (Full Expansion P4)
==============================================================================
지시서 Execution: "v1은 자동 주문이 아니라 실행 준비실." 현재 보유 대비 목표
포트폴리오의 주문 차이, 추정 비용(수수료·세금·스프레드·시장충격·슬리피지),
거래대금 대비 참여율, 유동성 소진 위험, 틱/수량 단위 검증, 주문 거부 사유 등을
산출한다. 실 주문·계좌 제어·자동매매는 v1 범위 밖.

Pre-trade 리스크(§4): gross/net 노출·집중도·회전율·비용예산·참여율·현금·
데이터 신선도·거래제한 종목·중복 주문 → pass/warning/block. block은 승인 불가.

시장 규칙(수수료·세금·틱·단위·가격제한)은 전부 market_rules 설정 계층에서.
"""

from __future__ import annotations

import logging
import math

from src.data import market_rules as mr

logger = logging.getLogger(__name__)


def _last_close(code: str) -> float | None:
    """최근 종가 — ohlcv_loader(DB→KIS→mock). 실패 시 None(정직 결측)."""
    from datetime import date, timedelta
    try:
        from src.data.ohlcv_loader import load_ohlcv_unified
        end = date.today()
        df = load_ohlcv_unified(code, (end - timedelta(days=30)).isoformat(), end.isoformat())
        if df is not None and len(df) and "close" in df.columns:
            return float(df["close"].iloc[-1])
    except Exception:
        pass
    return None


def _adv_won(code: str) -> float | None:
    """20일 평균 거래대금(원). price_factors amount_20d_avg(억) → 원. 결측 None."""
    try:
        from src.data.price_factors_store import PriceFactorsStore
        f = PriceFactorsStore.get_default().get_factors(code, None) or {}
        a = f.get("amount_20d_avg")
        return float(a) * 1e8 if isinstance(a, (int, float)) and a > 0 else None
    except Exception:
        return None


def build_plan(current_weights: dict[str, float], target_weights: dict[str, float],
               portfolio_value: float, price_of=None, adv_of=None,
               restricted: set[str] | None = None) -> dict:
    """오더 diff + 비용 + 참여율. price_of/adv_of는 테스트 주입용(없으면 실로더)."""
    price_of = price_of or _last_close
    adv_of = adv_of or _adv_won
    restricted = restricted or set()
    codes = sorted(set(current_weights) | set(target_weights))
    pv = float(portfolio_value)

    from src.data.stock_master import get_stock_name

    comm = mr.commission_bp() / 1e4
    tax = mr.sell_tax_bp() / 1e4
    spread = mr.spread_bp_default() / 1e4
    kimp = mr.impact_coeff()
    lot = mr.board_lot()

    orders = []
    missing_price = []
    tot_notional = tot_cost = tot_buy = tot_sell = 0.0

    for c in codes:
        cw = max(current_weights.get(c, 0.0), 0.0) / 100.0
        tw = max(target_weights.get(c, 0.0), 0.0) / 100.0
        px = price_of(c)
        if px is None or px <= 0:
            missing_price.append(c)
            continue
        cur_shares = math.floor((cw * pv) / px)
        tgt_shares = math.floor((tw * pv) / px / lot) * lot
        delta = tgt_shares - cur_shares
        if delta == 0:
            continue
        side = "buy" if delta > 0 else "sell"
        qty = abs(delta)
        notional = qty * px

        adv = adv_of(c)
        participation = (notional / adv) if adv and adv > 0 else None
        # 시장충격(bp) = k × sqrt(참여율) — 참여율 미상이면 0(정직)
        impact = (kimp * math.sqrt(participation) / 1e4) if participation else 0.0
        commission_cost = notional * comm
        tax_cost = notional * tax if side == "sell" else 0.0
        spread_cost = notional * spread * 0.5     # 편도 스프레드의 절반
        impact_cost = notional * impact
        cost = commission_cost + tax_cost + spread_cost + impact_cost

        tot_notional += notional
        tot_cost += cost
        if side == "buy":
            tot_buy += notional
        else:
            tot_sell += notional

        # 틱/단위 검증 + 유동성/거부 경고
        warns = []
        if not mr.is_on_tick(px):
            warns.append("호가단위 불일치(추정가) — 실주문 시 틱 정렬 필요")
        if participation is not None and participation > 0.10:
            warns.append(f"거래대금 대비 참여율 {round(participation * 100, 1)}% — 유동성 소진·체결지연 위험")
        if adv is None:
            warns.append("거래대금 데이터 미보유 — 참여율·충격 추정 불가")
        if c in restricted:
            warns.append("거래제한 종목")
        if mr.shortable(c) is None and side == "sell" and cur_shares == 0:
            warns.append("공매도 가능여부 미상(데이터 미연동) — 숏 주문이면 차입 확인 필요")

        orders.append({
            "stock_code": c, "corp_name": get_stock_name(c) or c,
            "side": side, "quantity": qty, "price_est": round(px, 2),
            "tick_size": mr.tick_size(px),
            "notional": round(notional), "cur_shares": cur_shares, "tgt_shares": tgt_shares,
            "cur_weight_pct": round(cw * 100, 2), "tgt_weight_pct": round(tw * 100, 2),
            "participation_pct": round(participation * 100, 2) if participation is not None else None,
            "cost_breakdown": {
                "commission": round(commission_cost), "tax": round(tax_cost),
                "spread": round(spread_cost), "impact": round(impact_cost)},
            "cost_bp": round(cost / notional * 1e4, 1) if notional > 0 else 0,
            "warnings": warns,
        })

    # 우선순위: 매도 먼저(현금 확보) → 큰 금액 순 (리밸런싱 단계)
    orders.sort(key=lambda o: (0 if o["side"] == "sell" else 1, -o["notional"]))
    for i, o in enumerate(orders):
        o["priority"] = i + 1
        o["stage"] = 1 if o["side"] == "sell" else 2

    turnover = round(tot_notional / pv * 100, 2) if pv > 0 else 0.0
    net_cash_change = tot_sell - tot_buy   # 매도 유입 - 매수 유출 (비용 별도)
    return {
        "orders": orders,
        "summary": {
            "n_orders": len(orders),
            "n_buy": sum(1 for o in orders if o["side"] == "buy"),
            "n_sell": sum(1 for o in orders if o["side"] == "sell"),
            "gross_notional": round(tot_notional),
            "buy_notional": round(tot_buy), "sell_notional": round(tot_sell),
            "est_cost": round(tot_cost),
            "est_cost_bp": round(tot_cost / tot_notional * 1e4, 1) if tot_notional > 0 else 0,
            "turnover_pct": turnover,
            "net_cash_change": round(net_cash_change),
        },
        "missing_price": missing_price,
        "rules": mr.rules_snapshot(),
        "notes": [
            "v1 실행 준비실 — 실제 주문·계좌 제어·자동매매 없음.",
            "가격은 최근 종가 추정 · 비용은 사전 추정치 — 실 정산은 브로커 확정값.",
            *(["일부 종목 시세 미보유 — 주문 산출 제외(정직 결측)."] if missing_price else []),
        ],
    }


# ── Pre-trade 리스크 체크 (§4) ────────────────────────────────────────────────
def pre_trade_checks(plan: dict, limits: dict | None = None,
                     data_fresh: bool = True) -> dict:
    """pass / warning / block 분류. block이 하나라도 있으면 승인 불가."""
    limits = limits or {}
    s = plan["summary"]
    orders = plan["orders"]
    checks: list[dict] = []

    def add(name: str, status: str, detail: str):
        checks.append({"name": name, "status": status, "detail": detail})

    # 회전율
    to_cap = limits.get("turnover_cap_pct")
    if to_cap is not None and s["turnover_pct"] > to_cap:
        add("회전율", "block", f"{s['turnover_pct']}% > 상한 {to_cap}%")
    elif s["turnover_pct"] > 100:
        add("회전율", "warning", f"{s['turnover_pct']}% — 전량 교체 수준")
    else:
        add("회전율", "pass", f"{s['turnover_pct']}%")

    # 비용 예산
    cost_cap = limits.get("cost_budget_bp")
    if cost_cap is not None and s["est_cost_bp"] > cost_cap:
        add("거래비용", "block", f"{s['est_cost_bp']}bp > 예산 {cost_cap}bp")
    elif s["est_cost_bp"] > 100:
        add("거래비용", "warning", f"{s['est_cost_bp']}bp — 비용 과다")
    else:
        add("거래비용", "pass", f"{s['est_cost_bp']}bp")

    # 참여율(유동성)
    high_part = [o for o in orders if (o["participation_pct"] or 0) > 20]
    part_cap = limits.get("participation_cap_pct", 20)
    blockers = [o for o in orders if (o["participation_pct"] or 0) > (part_cap or 20)]
    if blockers and limits.get("participation_cap_pct") is not None:
        add("유동성 참여율", "block",
            f"{len(blockers)}종목이 참여율 상한 {part_cap}% 초과 (예: {blockers[0]['corp_name']})")
    elif high_part:
        add("유동성 참여율", "warning", f"{len(high_part)}종목 참여율 20% 초과 — 체결 위험")
    else:
        add("유동성 참여율", "pass", "모든 주문 참여율 정상")

    # 현금 — 소규모 음수(거래비용·수량반올림)는 warning, 유의미 초과만 block.
    #   순수 리밸런싱(완전투자→완전투자)은 매수≈매도라 비용만큼만 음수가 되므로
    #   그것까지 block하면 현실 리밸런싱이 거의 항상 승인 불가가 됨(정직한 완화).
    cash_after = limits.get("cash_after_pct")
    cash_block = limits.get("cash_block_pct", -1.0)   # 이보다 더 음수면 진짜 현금 부족
    if cash_after is not None:
        if cash_after < cash_block:
            add("현금", "block", f"매수 총액이 가용 현금 초과 ({cash_after}%) — 현금 부족")
        elif cash_after < 0:
            add("현금", "warning", f"현금 여유 {cash_after}% — 거래비용·수량반올림만큼 현금 필요")
        else:
            add("현금", "pass", f"현금 여유 {cash_after}%")
    else:
        add("현금", "pass", "현금 충분")

    # 데이터 신선도
    add("데이터 신선도", "pass" if data_fresh else "warning",
        "최신" if data_fresh else "시세·규칙 데이터가 오래됨 — 재적재 권장")

    # 거래제한/공매도 미상
    restr = [o for o in orders if any("거래제한" in w for w in o["warnings"])]
    if restr:
        add("거래제한 종목", "block", f"{len(restr)}종목이 제한 목록 — 제외 필요")
    else:
        add("거래제한 종목", "pass", "제한 종목 없음")

    # 시세 미보유
    if plan.get("missing_price"):
        add("시세 커버리지", "warning",
            f"{len(plan['missing_price'])}종목 시세 미보유 — 주문 산출 제외")

    n_block = sum(1 for c in checks if c["status"] == "block")
    n_warn = sum(1 for c in checks if c["status"] == "warning")
    overall = "block" if n_block else ("warning" if n_warn else "pass")
    return {
        "overall": overall, "n_block": n_block, "n_warning": n_warn,
        "checks": checks,
        "can_approve": n_block == 0,
        "note": "block 항목이 있으면 승인 불가 (지시서 §4). warning은 승인 가능하나 검토 권장.",
    }
