"""전략 간 네팅 — ★지어낸 ×1.5 대신 실제 보유로 잰다★ (BG3 · R3 복원)
==============================================================================
스펙 `docs/superpowers/specs/2026-09-24-multistrategy-restore-r1-r3-design.md` §4.3 ·
재료 `strategy_registry.load_holdings`(등록 때 재실행에서 나온 일별 보유) ·
소비자 `multi_strategy_backtest` · `realism_engine`

## 왜 이 모듈이 생겼나

`multi_strategy_backtest` 는 2026-06-10 스냅샷 이식 때부터 `OrderNettingEngine` 을
만들었는데 **한 번도 부르지 않았고**, 모듈 자체가 저장소에 없었다(BF). 대신
절감액을 `(회전율 × 1.5 − 회전율) × 요율` 로 적었다 — ★지어낸 1.5★ 가 귀인과
화면에 "청산 효과" 로 실렸다.

## 정의

날짜 t 에 전략 s 의 슬리브가 종목 i 에 갖는 노출을 `x(s,i,t) = W(s,t) · h(s,i,t)`
로 둔다(W = 포트폴리오 안 전략 비중, h = 전략 자신의 종목 보유 비중).

    총거래  G(t) = Σ_s Σ_i | x(s,i,t) − x(s,i,t−1) |
    순거래  N(t) = Σ_i | Σ_s x(s,i,t) − Σ_s x(s,i,t−1) |
    절감    S(t) = (G(t) − N(t)) × (수수료 + 슬리피지) × equity(t−1)

G ≥ N 은 삼각부등식이라 절감은 음수가 되지 않는다.

## ★이 모듈이 주장하지 않는 것★

- **드리프트를 재지 않는다** — t−1 → t 사이 가격 변동으로 비중이 흘러가는 몫을
  무시한다(가정 ①).
- **전략 내부 요율을 쓰지 않는다** — 전략 수익률에 이미 녹아 있는 거래 비용은 각
  전략 실행의 요율로 부과됐지만, 절감은 **포트폴리오 요율**로 평가한다(가정 ②).
- **수익률에 더하지 않는다** — 네팅은 보고 전용이다(엔진 계약 그대로).
- **보유를 모르면 0 이라 하지 않는다** — `(None, 사유)`. 0 은 "상쇄가 없었다" 는
  관측이다.
"""
from __future__ import annotations

#: 결과에 싣는 근거 이름 — ★측정이지만 가정 둘 위에서★
NETTING_BASIS = "measured_holdings"

ASSUMPTIONS = (
    "t−1 → t 가격 변동에 따른 비중 drift 는 무시합니다(보유 비중을 그대로 비교).",
    "전략 내부 거래 비용은 각 전략 실행의 요율로 이미 부과됐지만, 절감은 "
    "포트폴리오의 수수료+슬리피지 요율로 평가합니다.",
)

_EPS = 1e-12


class OrderNettingEngine:
    """전략 슬리브 사이에서 상쇄되는 거래를 잰다."""

    def __init__(self, db_engine=None):
        self.engine = db_engine

    @staticmethod
    def _exposure(weight: float, h: dict) -> dict:
        return {tk: weight * float(v) for tk, v in h.items()}

    def savings(self, *, prev_weights: dict, cur_weights: dict, holdings: dict,
                prev_date: str, date: str, equity: float,
                rate: float) -> tuple[float | None, str | None]:
        """`(절감 원화, None)` 또는 ★`(None, 사유)`★ — 보유를 모르면 판정하지 않는다."""
        sids = [s for s in set(prev_weights) | set(cur_weights)
                if abs(float(prev_weights.get(s, 0) or 0)) > _EPS
                or abs(float(cur_weights.get(s, 0) or 0)) > _EPS]
        gross = 0.0
        net: dict[str, float] = {}
        for s in sids:
            hs = (holdings or {}).get(int(s)) or (holdings or {}).get(s) or {}
            hp, hc = hs.get(str(prev_date)[:10]), hs.get(str(date)[:10])
            if hp is None or hc is None:
                missing = str(prev_date)[:10] if hp is None else str(date)[:10]
                return None, (f"전략 {s} 의 {missing} 보유를 모릅니다(종가 부재 또는 "
                              "등록 구간 밖) — 이날 네팅을 판정하지 않습니다.")
            xp = self._exposure(float(prev_weights.get(s, 0) or 0), hp)
            xc = self._exposure(float(cur_weights.get(s, 0) or 0), hc)
            for tk in set(xp) | set(xc):
                d = xc.get(tk, 0.0) - xp.get(tk, 0.0)
                gross += abs(d)
                net[tk] = net.get(tk, 0.0) + d
        saved = max(0.0, gross - sum(abs(v) for v in net.values()))
        return saved * float(rate) * float(equity), None
