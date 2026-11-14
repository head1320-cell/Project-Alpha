"""매매일지 — 체결마다 수수료·세금과 ★그 근거★.

값만 내지 않는다. 그 값이 어디서 왔는지를 함께 낸다:

- **관측**(`observed`) — 올린 파일에 적혀 있던 값.
- **추론**(`inferred`) — 세율표(`market_rules.sell_tax_bp_on` — 보도 근거 T1)로 산출한 세금. 저장소의 증거 어휘(관측·측정·추론·가정·미상)를 따른다.
- **가정**(`assumed`) — 사용자가 넣은 수수료율, 또는 사용자가 "모르는 종목은 이렇게 본다"고 정한 시장으로 계산한 값.
- **미상**(`unknown`) — 모른다. ★값은 `None` 이고 0 이 아니다★ — 비용을 모르는 체결의 '비용 뒤 손익'은 계산하지 않는다.

세율표 파일을 읽는 것 말고는 입출력이 없다.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

from src.data.market_rules import SELL_TAX_INSTRUMENTS, SELL_TAX_MARKETS, sell_tax_bp_on
from src.engine.trade_journal.fills import Fill

OBSERVED = "observed"
INFERRED = "inferred"
ASSUMED = "assumed"
UNKNOWN = "unknown"
NOT_APPLICABLE = "not_applicable"       # 매수에는 매도세가 없다

#: 세금을 모르는 사유 → 화면 문장. 세율표가 답하지 못한 사유는 세율표의 문장을 그대로 쓴다.
TAX_UNKNOWN_MESSAGES: dict[str, str] = {
    "unknown_market_or_instrument": "종목의 시장·상품 구분을 알 수 없어 매도세를 계산하지 않았습니다.",
}


@dataclass(frozen=True)
class CostOptions:
    commission_bp: float | None = None          # 편도 수수료율(bp). None = 모름(0 과 다르다)
    unknown_market: str | None = None           # 시장을 모르는 종목을 이렇게 본다(사용자의 가정)
    unknown_instrument: str | None = None
    master: Callable[[str], dict | None] | None = None      # 종목 → 마스터 플래그(없으면 None)

    def __post_init__(self) -> None:
        bp = self.commission_bp
        if bp is not None and (isinstance(bp, bool) or not isinstance(bp, (int, float)) or not math.isfinite(bp) or bp < 0):
            raise ValueError(f"commission_bp 는 0 이상의 수여야 한다: {bp!r}")
        if self.unknown_market is not None and self.unknown_market not in SELL_TAX_MARKETS:
            raise ValueError(f"unknown_market 는 {SELL_TAX_MARKETS} 가운데 하나여야 한다: {self.unknown_market!r}")
        if self.unknown_instrument is not None and self.unknown_instrument not in SELL_TAX_INSTRUMENTS:
            raise ValueError(f"unknown_instrument 는 {SELL_TAX_INSTRUMENTS} 가운데 하나여야 한다: {self.unknown_instrument!r}")


@dataclass(frozen=True)
class FillCost:
    fee: float | None
    fee_basis: str
    tax: float | None
    tax_basis: str
    tax_bp: float | None = None
    tax_rate: dict | None = None        # 세율표의 답(등급 · 구간 · 출처) — 추론·가정일 때, 또는 세율표가 답하지 못했을 때
    tax_reason: str | None = None       # 미상의 사유

    @property
    def total(self) -> float | None:
        """수수료 + 세금. 둘 중 하나라도 모르면 `None`."""
        return None if self.fee is None or self.tax is None else self.fee + self.tax


def master_flags_of(symbol: str, options: CostOptions) -> dict:
    flags = options.master(symbol) if options.master is not None else None
    return flags if isinstance(flags, dict) else {}


def _master_market(flags: dict) -> str | None:
    market = str(flags.get("market") or "").strip().upper()
    return market if market in SELL_TAX_MARKETS else None


def _master_instrument(flags: dict) -> str | None:
    """마스터가 ★실제로 아는 것만★ — 'ETF 아님'은 주식이라는 뜻이 아니다(ETN·ELW 일 수 있다)."""
    group = str(flags.get("group_code") or "").strip().upper()
    if flags.get("is_etf") or group == "EF":
        return "etf"
    return "stock" if group == "ST" else None


def market_and_instrument(symbol: str, master: Callable[[str], dict | None] | None) -> tuple[str | None, str | None]:
    """종목 마스터가 ★아는★ 시장과 상품 — 모르면 `None`. 체결 줄이 없는 자리(분봉 백테스트)에서 같은 판정을 쓴다."""
    flags = master(symbol) if master is not None else None
    flags = flags if isinstance(flags, dict) else {}
    return _master_market(flags), _master_instrument(flags)


def classify(fill: Fill, options: CostOptions) -> tuple[str | None, str | None, bool]:
    """시장·상품을 체결 줄 → 종목 마스터 → 사용자의 가정 순으로 정한다. 셋째 값은 '사용자의 가정을 썼는가'."""
    known_market, known_instrument = market_and_instrument(fill.symbol, options.master)
    market = fill.market or known_market
    instrument = fill.instrument or known_instrument
    assumed = False
    if market is None and options.unknown_market is not None:
        market, assumed = options.unknown_market, True
    if instrument is None and options.unknown_instrument is not None:
        instrument, assumed = options.unknown_instrument, True
    return market, instrument, assumed


def cost_of(fill: Fill, options: CostOptions) -> FillCost:
    if fill.fee is not None:
        fee, fee_basis = fill.fee, OBSERVED
    elif options.commission_bp is not None:
        fee, fee_basis = fill.notional * options.commission_bp / 10_000, ASSUMED
    else:
        fee, fee_basis = None, UNKNOWN

    if fill.tax is not None:
        return FillCost(fee, fee_basis, fill.tax, OBSERVED)
    if fill.side == "buy":
        return FillCost(fee, fee_basis, 0.0, NOT_APPLICABLE)

    market, instrument, assumed = classify(fill, options)
    if market is None or instrument is None:
        return FillCost(fee, fee_basis, None, UNKNOWN, tax_reason="unknown_market_or_instrument")
    rate = sell_tax_bp_on(fill.at.date(), market, instrument)
    if not rate["available"]:
        return FillCost(fee, fee_basis, None, UNKNOWN, tax_rate=rate, tax_reason=rate["reason"])
    return FillCost(fee, fee_basis, fill.notional * rate["bp"] / 10_000, ASSUMED if assumed else INFERRED,
                    tax_bp=rate["bp"], tax_rate=rate)
