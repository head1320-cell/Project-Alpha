"""한국 시장 규칙 설정 계층 (Full Expansion P4)
==============================================================================
지시서 §0: "한국 시장 규칙·수수료·세금·공매도 가능여부·틱사이즈·가격제한 등을
하드코딩하지 말고 데이터/설정 계층으로 관리하라."

이 모듈이 그 단일 설정 계층. 값은 env로 오버라이드 가능하며, 기본값은 공개된
KRX 규칙 근사(정직 라벨). 실 운영 시 브로커·규정 변경을 여기서만 바꾼다.

주의(정직): 세율·수수료·틱 표는 시점에 따라 바뀜 — 여기 기본값은 근사이며
실제 체결·정산은 브로커 확정값을 따라야 함. v1은 사전 추정(pre-trade estimate)용.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any


def _envf(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, default))
    except (TypeError, ValueError):
        return default


# ── 수수료·세금 (bp = 0.01%) ─────────────────────────────────────────────────
def commission_bp() -> float:
    """매매 수수료 (편도, bp). 기본 1.5bp(0.015%) — 브로커별 상이."""
    return _envf("KR_COMMISSION_BP", 1.5)


def sell_tax_bp() -> float:
    """매도 시 증권거래세+농특세 합계 (bp). 2024 기준 코스피 ~18bp·코스닥 ~18bp 근사.
    시장·시점별 상이 — env로 조정. 매수엔 미부과.

    ★이 고정값은 2024년 한 해의 값이다★ — 거래일·시장·상품에 맞는 값은 `sell_tax_bp_on()` 이 출처와 함께 준다.
    이 함수는 그대로 둔다(읽는 엔진의 결과가 바뀌지 않게)."""
    return _envf("KR_SELL_TAX_BP", 18.0)


# ── 매도세의 시점·시장·상품별 표 ─────────────────────────────────────────────
#: 체크인된 증거 파일(확인한 칸만 · 미확인 구간은 그 파일의 `unknown` 에 사유와 함께).
#: `SELL_TAX_EVIDENCE_PATH` 로 덮어쓸 수 있다 — 갓 고친 파일을 운영 파일을 건드리지 않고 시험해 보기 위한 것이다.
SELL_TAX_EVIDENCE_PATH = Path(__file__).resolve().parents[2] / "docs" / "specs" / "sell-tax-schedule-evidence.json"

#: 이 표가 다루는 시장 · 상품. 그 밖은 값을 만들지 않는다.
SELL_TAX_MARKETS = ("KOSPI", "KOSDAQ", "KONEX")
SELL_TAX_INSTRUMENTS = ("stock", "etf")

_SELL_TAX_MESSAGES = {
    "bad_date": "거래일을 읽지 못해 매도세를 정할 수 없습니다.",
    "unknown_market": "이 시장의 매도세는 표에 없습니다(코스피·코스닥·코넥스만 다룹니다).",
    "unknown_instrument": "이 상품의 매도세는 확인하지 못했습니다(주식·ETF 만 다룹니다).",
    "outside_schedule": "이 거래일의 매도세는 확인하지 못한 구간입니다.",
    "below_grade_floor": "이 구간의 근거가 적용선에 못 미쳐 매도세를 적용하지 않습니다.",
    "no_evidence_file": "매도세 증거 파일을 읽지 못했습니다.",
}


def _trade_date(value: Any) -> date | None:
    """`date` · `datetime` · `YYYY-MM-DD` · `YYYYMMDD` → `date`. 그 밖은 `None`(어림해 읽지 않는다)."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def sell_tax_bp_on(trade_date: Any, market: str, instrument: str = "stock") -> dict:
    """그 거래일·시장·상품의 매도세(bp) — ★값과 출처를 함께★ 돌려준다.

    `bp` 는 증권거래세 + 농어촌특별세의 합이고 `parts` 가 그 구성이다. 면제(ETF)는 `bp == 0` 이라는 ★값★이고,
    확인하지 못한 구간·시장·상품은 `bp is None` + `reason` 이다 — 가까운 구간의 값으로 채우지 않는다.
    표의 근거는 보도·안내 자료 요약(`grade: T1`)이다 — 쓰는 쪽은 이 값을 '추론'(관측이 아니다)으로 표시해야 한다.
    기준일은 매매체결일이다(증거 파일의 `date_basis`).
    """
    mkt = str(market or "").strip().upper()
    inst = str(instrument or "").strip().lower()

    def no(reason: str, **extra) -> dict:
        return {"available": False, "bp": None, "parts": None, "market": mkt, "instrument": inst, "grade": None,
                "period": None, "sources": [], "note": None, "reason": reason,
                "message": _SELL_TAX_MESSAGES[reason], **extra}

    day = _trade_date(trade_date)
    if day is None:
        return no("bad_date")
    if mkt not in SELL_TAX_MARKETS:
        return no("unknown_market")
    if inst not in SELL_TAX_INSTRUMENTS:
        return no("unknown_instrument")
    override = os.getenv("SELL_TAX_EVIDENCE_PATH", "").strip()      # 부르는 시점에 읽는다
    try:
        doc = json.loads((Path(override) if override else SELL_TAX_EVIDENCE_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return no("no_evidence_file")

    iso = day.isoformat()
    row = next((r for r in doc.get("schedule", [])
                if r["market"] == mkt and r["instrument"] == inst
                and r["from"] <= iso and (r["to"] is None or iso <= r["to"])), None)
    if row is None:
        return no("outside_schedule")
    period = {"from": row["from"], "to": row["to"]}
    grades = list(doc.get("grades", {}))
    if grades.index(row["grade"]) < grades.index(doc.get("min_grade_to_apply", grades[-1])):
        return no("below_grade_floor", grade=row["grade"], period=period)
    parts = {"transaction_tax_bp": row["transaction_tax_bp"], "rural_special_tax_bp": row["rural_special_tax_bp"]}
    known = doc.get("sources", {})
    return {"available": True, "bp": parts["transaction_tax_bp"] + parts["rural_special_tax_bp"], "parts": parts,
            "market": mkt, "instrument": inst, "grade": row["grade"], "period": period,
            "sources": [{"title": known[s]["title"], "url": known[s]["url"]} for s in row["sources"]],
            "note": row.get("note") or None, "reason": None, "message": None}


# ── 장 운영 시각 (정규장 · 종가 단일가) ──────────────────────────────────────────
#: 체크인된 증거 파일. `SESSION_RULES_EVIDENCE_PATH` 로 덮어쓸 수 있다(매도세 표와 같은 이유).
SESSION_RULES_EVIDENCE_PATH = Path(__file__).resolve().parents[2] / "docs" / "specs" / "krx-session-rules-evidence.json"

_SESSION_MESSAGES = {
    "no_evidence_file": "장 운영 규칙 증거 파일을 읽지 못했습니다.",
    "bad_rules": "장 운영 규칙 증거 파일의 시각을 읽지 못했습니다.",
    "below_grade_floor": "장 운영 규칙의 근거가 적용선에 못 미쳐 적용하지 않습니다.",
}


def _hhmm(value: Any) -> str | None:
    """`"09:00"` → `"0900"`. 그 밖은 `None`(어림해 읽지 않는다)."""
    try:
        return datetime.strptime(str(value).strip(), "%H:%M").strftime("%H%M")
    except ValueError:
        return None


def session_rules() -> dict:
    """정규장의 시작·종가 단일가 시작·끝(`"HHMM"`) — ★값과 출처를 함께★ 돌려준다.

    시각은 코드에 없다 — 증거 파일이 갖는다. 파일을 읽지 못하거나 시각이 읽히지 않으면 값 없이 사유만 준다
    (기본 시각으로 채우지 않는다). 근거는 보도·증권사 안내 요약(`grade: T1`)이라, 쓰는 쪽은 이 시각으로 붙인 표시를
    '시각으로 추론'한 것으로 다뤄야 한다 — 그날 실제로 그렇게 운영됐는지는 이 표가 알지 못한다(`special_days` · `unknown`).
    """
    def no(reason: str, **extra) -> dict:
        return {"available": False, "open": None, "closing_auction_from": None, "close": None, "grade": None,
                "sources": [], "note": None, "special_days": None, "unknown": [], "reason": reason,
                "message": _SESSION_MESSAGES[reason], **extra}

    override = os.getenv("SESSION_RULES_EVIDENCE_PATH", "").strip()     # 부르는 시점에 읽는다
    try:
        doc = json.loads((Path(override) if override else SESSION_RULES_EVIDENCE_PATH).read_text(encoding="utf-8"))
        row = doc["regular_session"]
        grades = list(doc["grades"])
        below = grades.index(row["grade"]) < grades.index(doc.get("min_grade_to_apply", grades[-1]))
    except (OSError, ValueError, KeyError, TypeError):
        return no("no_evidence_file")
    if below:
        return no("below_grade_floor", grade=row["grade"])
    opens, auction, closes = (_hhmm(row.get(k)) for k in ("open", "closing_auction_from", "close"))
    if None in (opens, auction, closes) or not opens < auction < closes:
        return no("bad_rules")
    known = doc.get("sources", {})
    return {"available": True, "open": opens, "closing_auction_from": auction, "close": closes, "grade": row["grade"],
            "sources": [{"title": known[s]["title"], "url": known[s]["url"]} for s in row.get("sources", []) if s in known],
            "note": row.get("note") or None, "special_days": doc.get("special_days"),
            "unknown": list(doc.get("unknown", [])), "reason": None, "message": None}


def spread_bp_default() -> float:
    """스프레드 비용 프록시 (편도, bp). 종목별 실측 스프레드 미보유 시 기본값."""
    return _envf("KR_SPREAD_BP", 5.0)


# ── 시장 충격 (제곱근 모델 계수) ──────────────────────────────────────────────
def impact_coeff() -> float:
    """시장충격 계수 k. ★`impact_bp = k × sqrt(참여율)`★ — 참여율은 주문금액/거래대금.

    기본 10 이면 참여율 1%에서 1bp, 25%에서 5bp, 100%에서 10bp.

    ★이 문장은 AK 에서 고쳤다★ — 예전에는 `impact_bp = k × 100 × sqrt(참여율)` 에
    *"참여율 1%면 ~10bp"* 라고 적혀 있었는데, 그 **공식과 예시가 서로 안 맞고**
    (k×100×√0.01 = 100bp) 둘 다 유일한 구현과도 안 맞았다
    (`execution_plan.py:89` 은 `k*sqrt(p)/1e4` 를 비율로 쓰므로 1bp). 세 값이
    전부 달랐다. 코드를 바꾸면 `execution_plan` 의 비용 추정이 100배 움직이므로
    ★구현에 맞춰 문서를 고쳤다★ — 계수 자체는 측정된 적이 없는 설정값이다.
    """
    return _envf("KR_IMPACT_COEFF", 10.0)


# ── 호가 단위 (틱사이즈) — KRX 가격대별 표 (2023-01-25 개정) ──────────────────
# (경계가격, 틱). ★가격 < 경계(미만)이면 해당 틱★ — 정확히 2,000원은 5원 단위다.
# BD(2026-09-24): 예전에는 `<=`(이하)였고 실주문 경로(`OrderExecutor`)는 `<` 라
# 여섯 경계에서 갈렸다. 증권사 안내·개편 보도가 전부 "미만" 이고 사용자가 KRX
# 원문대로 확정했다(★KRX 1차 문서는 이 환경에서 403 이라 직접 확인하지 못했다★).
# `OrderExecutor._get_tick_size` 가 이 표를 읽는다 — ★표는 여기 하나뿐이다★.
_TICK_TABLE: list[tuple[float, float]] = [
    (2000, 1), (5000, 5), (20000, 10), (50000, 50),
    (200000, 100), (500000, 500), (float("inf"), 1000),
]


def tick_size(price: float) -> float:
    """가격에 해당하는 KRX 호가 단위. 설정 표 기반(하드코딩 로직 아님)."""
    for ub, tick in _TICK_TABLE:
        if price < ub:
            return tick
    return 1000


def is_on_tick(price: float) -> bool:
    t = tick_size(price)
    return abs(round(price / t) * t - price) < 1e-6


def round_to_tick(price: float, direction: str = "nearest") -> float:
    t = tick_size(price)
    if direction == "up":
        return float(int((price + t - 1e-9) / t) * t)
    if direction == "down":
        return float(int(price / t) * t)
    return float(round(price / t) * t)


# ── 매매 단위 (수량 단위) ─────────────────────────────────────────────────────
def board_lot(_stock_code: str | None = None) -> int:
    """최소 매매 수량 단위. KRX 주식은 대부분 1주 (2014년 이후). ETF·우선주도 1주.
    종목별 예외는 향후 데이터 계층에서 매핑 — 현재 전부 1(정직 기본)."""
    return int(_envf("KR_BOARD_LOT", 1))


# ── 가격 제한 (상·하한가) ─────────────────────────────────────────────────────
def price_limit_pct() -> float:
    """일일 가격제한폭 %. KRX 주식 ±30%. (ETF·신규상장 등 예외는 별도 — 정직 근사.)"""
    return _envf("KR_PRICE_LIMIT_PCT", 30.0)


# ── 공매도 가능 여부 (데이터 계층 placeholder) ────────────────────────────────
def shortable(_stock_code: str) -> bool | None:
    """공매도 가능 여부. v1은 데이터 미연동 → None(미상). 하드코딩 금지 원칙상
    True/False를 임의 단정하지 않고 '미상'을 정직 반환 — Execution이 경고로 처리."""
    return None


def rules_snapshot() -> dict:
    """현재 적용 중인 규칙 스냅샷 (UI·감사 로그 표기용)."""
    return {
        "commission_bp": commission_bp(),
        "sell_tax_bp": sell_tax_bp(),
        "spread_bp": spread_bp_default(),
        "impact_coeff": impact_coeff(),
        "board_lot": board_lot(),
        "price_limit_pct": price_limit_pct(),
        # ★`below` = 미만★ — `up_to` 는 "이하" 로 읽혀 경계를 거꾸로 말했다(BD).
        "tick_table": [{"below": (None if ub == float("inf") else ub), "tick": t} for ub, t in _TICK_TABLE],
        "source": "KRX 공개 규칙 근사 (env 오버라이드 가능) — 실 정산은 브로커 확정값",
    }
