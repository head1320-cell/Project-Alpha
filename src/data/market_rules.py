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

import os


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
    시장·시점별 상이 — env로 조정. 매수엔 미부과."""
    return _envf("KR_SELL_TAX_BP", 18.0)


def spread_bp_default() -> float:
    """스프레드 비용 프록시 (편도, bp). 종목별 실측 스프레드 미보유 시 기본값."""
    return _envf("KR_SPREAD_BP", 5.0)


# ── 시장 충격 (제곱근 모델 계수) ──────────────────────────────────────────────
def impact_coeff() -> float:
    """시장충격 계수 k: impact_bp = k × 100 × sqrt(참여율). 기본 10 → 참여율 1%면 ~10bp."""
    return _envf("KR_IMPACT_COEFF", 10.0)


# ── 호가 단위 (틱사이즈) — KRX 가격대별 표 (2023 개정 근사) ────────────────────
# (상한가격, 틱). 가격 ≤ 상한이면 해당 틱. 마지막은 그 이상.
_TICK_TABLE: list[tuple[float, float]] = [
    (2000, 1), (5000, 5), (20000, 10), (50000, 50),
    (200000, 100), (500000, 500), (float("inf"), 1000),
]


def tick_size(price: float) -> float:
    """가격에 해당하는 KRX 호가 단위. 설정 표 기반(하드코딩 로직 아님)."""
    for ub, tick in _TICK_TABLE:
        if price <= ub:
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
        "tick_table": [{"up_to": (None if ub == float("inf") else ub), "tick": t} for ub, t in _TICK_TABLE],
        "source": "KRX 공개 규칙 근사 (env 오버라이드 가능) — 실 정산은 브로커 확정값",
    }
