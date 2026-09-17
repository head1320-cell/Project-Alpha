"""비용 모델 레지스트리 — ★넷이 아니라 열넷이었다★ (AK2)
==============================================================================
설계: `docs/plans` AK · 어휘 `src/domain/cost_model.py` · 요율 출처
`src/data/market_rules.py` · 롤업 `src/engine/run_evidence.rollup`
(★`pit_evidence`·`decision_evidence`·`estimator_evidence`·`multiplicity_evidence`
와 **같은 함수**★)

## 왜 이 모듈이 생겼나

채점표 #6 은 *"비용 모델이 **넷**이고 수수료 기본값이 10배 다르다"* 고 적었다.
실측(2026-09-15) 결과:

1. **열넷이다.** 그리고 API 스키마 기본값끼리도 갈라져서 ★같은 백테스트를
   `stage11` 로 부르면 1.5bp, `screener`·`legacy` 로 부르면 15bp★ 다.
   요청을 어느 문으로 넣느냐가 수수료를 10배 바꾼다.
2. **슬리피지는 안 갈린다.** 전 자리가 `0.0005`(5bp)로 일치한다 — ★없는 갈등을
   만들지 않는다★.
3. **더 큰 것은 불일치가 아니라 누락이었다.** 실행 준비실(`execution_plan`)은
   `market_rules` 에서 증권거래세 18bp·스프레드·시장충격을 전부 계산하는데
   백테스트 쪽은 셋이 전부 0 이었다. ★18bp 매도세는 두 수수료 후보 어느 쪽보다
   크다.★ AK4 에서 그 셋이 **옵트인**으로 생겼다(기본은 여전히 꺼짐).

## ★이 모듈이 주장하지 않는 것★

- **비용 모델을 통일했다고 말하지 않는다.** 열넷은 그대로 열넷이고, 기본값
  불일치도 그대로다 — ★15bp 도 1.5bp 도 이 저장소가 재본 적이 없어서★ 안 재본
  값으로 수렴시키면 불일치가 **거짓 합의**가 된다.
- **어느 요율이 옳다고 말하지 않는다.** `market_rules` 스스로 근사라고 적었다.
- **다 찾았다고 말하지 않는다.** 여기 있는 것은 **기본값을 스스로 정하는** 자리이고,
  파라미터를 그냥 넘겨받는 자리(`dag_runner`·`counterfactual_analyzer`)는 없다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.domain.cost_model import (
    COMPONENTS,
    STATE_CHARGED,
    STATE_UNMEASURABLE,
    CostPolicy,
    round_trip_bps,
)
from src.engine.run_evidence import AXIS_DEGRADED, AXIS_OK, AXIS_UNKNOWN, rollup

_NOTE = (
    "이 판정은 **어느 자리가 어떤 비용을 보는가**만 말합니다. ★비용 모델을 "
    "단일 출처로 통일하지 않았습니다★ — 15bp 도 1.5bp 도 이 저장소가 재본 적이 "
    "없어, 안 재본 값으로 수렴시키면 불일치가 거짓 합의가 됩니다. 세금·스프레드·"
    "시장충격은 `kis_backtest_engine` 에서 **옵트인**으로 켤 수 있고 기본은 "
    "꺼져 있습니다.")

_OFF = "off"


@dataclass(frozen=True)
class CostSite:
    """비용 기본값을 **스스로 정하는** 한 자리."""

    key: str
    site: str
    label: str
    commission_bps: float | None = None
    slippage_bps: float | None = None
    components: dict[str, str] = field(default_factory=dict)
    decision_touching: bool = False
    #: 요율이 **어디서 오나**. ★`literal` 은 그 파일에 숫자가 박혀 있다는 뜻★ 이고
    #: `market_rules` 는 설정 계층을 읽는다는 뜻이다 — 후자만이 한 곳에서 고쳐진다.
    rate_source: str = "literal"
    note: str = ""


def _c(*charged: str) -> dict[str, str]:
    """성분 상태 dict — 적은 것만 `charged`, 나머지는 `off`."""
    return {name: (STATE_CHARGED if name in charged else _OFF) for name in COMPONENTS}


_BASIC = _c("commission", "slippage")

# ═══════════════════════════════════════════════════════════════════════════
# 레지스트리 — 2026-09-15 실측
# ═══════════════════════════════════════════════════════════════════════════

COST_SITES: tuple[CostSite, ...] = (
    CostSite(
        key="kis_backtest_engine",
        site="src/kis_backtest_engine.py:BacktestConfig",
        label="메인 백테스트 엔진", commission_bps=15.0, slippage_bps=5.0,
        components=_c("commission", "slippage"),
        note=("저장소의 주 백테스트 경로. ★AK 에서 세금·스프레드·충격이 옵트인으로 "
              "생겼다★(`charge_sell_tax`·`charge_spread`·`charge_market_impact`) — "
              "기본은 꺼져 있어 기존 실행의 수치가 안 움직인다. 켜면 "
              "`market_rules` 의 **같은 요율**을 쓴다."),
    ),
    CostSite(
        key="kis_backtest_engine_fn",
        site="src/kis_backtest_engine.py:run_backtest",
        label="엔진 편의 함수", commission_bps=15.0, slippage_bps=5.0,
        components=_BASIC,
        note="같은 엔진의 함수형 진입점이 기본값을 **또** 적는다 — 한쪽만 고치면 갈린다.",
    ),
    CostSite(
        key="kis_portfolio_analyzer",
        site="src/kis_portfolio_analyzer.py:PortfolioRebalancer",
        label="포트폴리오 분석기", commission_bps=15.0, slippage_bps=None,
        components=_c("commission"),
        note=("리밸런싱 회전율에 수수료만 매긴다. ★슬리피지조차 없다★ — "
              "이 작업에서 손대지 않았고, 그 사실을 여기 적는다."),
    ),
    CostSite(
        key="graph_runner",
        site="src/engine/graph_runner.py:run_backtest",
        label="그래프 러너", commission_bps=15.0, slippage_bps=5.0,
        components=_BASIC,
        note="DAG 전략 시뮬레이터. 엔진과 값은 같지만 **자기 기본값을 따로 적는다**.",
    ),
    CostSite(
        key="realism_engine",
        site="src/engine/realism_engine.py:RealismConfig",
        label="리얼리즘 엔진", commission_bps=1.5, slippage_bps=5.0,
        components=_c("commission", "slippage", "impact"),
        note=("★수수료가 메인 엔진의 1/10 이다★. 대신 시장충격을 **기본 켜고** "
              "돈다(`enable_market_impact=True`) — 저장소에서 충격을 기본으로 "
              "부과하는 유일한 자리다. 세금·스프레드는 여전히 없다."),
    ),
    CostSite(
        key="multi_strategy_backtest",
        site="src/engine/multi_strategy_backtest.py:BacktestConfig",
        label="멀티 전략 백테스트", commission_bps=1.5, slippage_bps=5.0,
        components=_BASIC,
        note="리얼리즘 엔진과 같은 1.5bp. 메인 엔진과 비교하면 10배 차이다.",
    ),
    CostSite(
        key="multibacktest_schema",
        site="src/engine/multibacktest_schema.py:DDL",
        label="멀티백테스트 표 기본값", commission_bps=1.5, slippage_bps=None,
        components=_c("commission"),
        note=("★DB 컬럼 DEFAULT 가 또 하나의 기본값이다★ — 클라이언트가 값을 "
              "안 보내면 여기 값이 남고, 그것은 코드 어디에도 안 적혀 있다."),
    ),
    CostSite(
        key="execution_plan",
        site="src/engine/execution_plan.py:build_plan",
        label="실행 준비실(주문 전 비용 추정)", commission_bps=1.5, slippage_bps=None,
        components=_c("commission", "tax", "spread", "impact"),
        decision_touching=True, rate_source="market_rules",
        note=("★유일하게 `market_rules` 를 읽는 자리★ — 수수료 + 증권거래세 18bp"
              "(매도 편도) + 스프레드 절반 + `k·√참여율` 충격. 슬리피지는 없다"
              "(주문 전 추정이라 체결 미끄러짐을 아직 모른다). "
              "`rebalance_decision` 의 비용 블록이 이 경로를 탄다."),
    ),
    CostSite(
        key="stage11_routes",
        site="src/api/stage11_routes.py:commission_rate",
        label="Stage11 라우트 기본값", commission_bps=1.5, slippage_bps=5.0,
        components=_BASIC,
        note="★요청이 값을 안 실으면 여기 기본값이 엔진으로 간다★",
    ),
    CostSite(
        key="stage12_routes",
        site="src/api/stage12_routes.py:commission_rate",
        label="Stage12 라우트 기본값", commission_bps=1.5, slippage_bps=5.0,
        components=_BASIC,
        note="리얼리즘 경로의 라우트 기본값.",
    ),
    CostSite(
        key="screener_routes",
        site="src/api/screener_routes.py:commission_rate",
        label="스크리너 백테스트 라우트", commission_bps=15.0, slippage_bps=5.0,
        components=_BASIC,
        note=("★같은 백테스트를 이 문으로 넣으면 수수료가 10배다★ — "
              "`stage11` 은 1.5bp, 여기는 15bp. 요청이 값을 실으면 그것이 이기지만, "
              "안 실으면 문에 따라 답이 달라진다."),
    ),
    CostSite(
        key="legacy_schemas",
        site="src/api/legacy_schemas.py:commission_rate",
        label="레거시 요청 스키마(4곳)", commission_bps=15.0, slippage_bps=5.0,
        components=_BASIC,
        note="한 파일에서 같은 기본값을 **네 번** 적는다 — 넷이 갈라질 수 있다.",
    ),
    CostSite(
        key="graph_schema",
        site="src/models/graph_schema.py:slippage_rate",
        label="그래프 요청 스키마", commission_bps=None, slippage_bps=5.0,
        components=_c("slippage"),
        note="슬리피지만 자기 기본값을 적는다(수수료는 러너가 정한다).",
    ),
    CostSite(
        key="market_rules",
        site="src/data/market_rules.py:commission_bp",
        label="시장 규칙 설정 계층(단일 출처 자처)", commission_bps=1.5,
        slippage_bps=None, rate_source="market_rules",
        components=_c("commission", "tax", "spread", "impact"),
        note=("★단일 설정 계층을 자처하나 읽는 곳이 둘뿐이다★ — "
              "`execution_plan` 과 (AK 이후) `kis_backtest_engine` 의 옵트인 경로. "
              "슬리피지는 여기 없다(체결 미끄러짐은 규칙이 아니라 관측이다)."),
    ),
)

#: ★같은 요청이 문에 따라 다른 답을 낸다★ — 기계가 읽는 표.
DISAGREEMENTS: tuple[dict[str, Any], ...] = (
    {
        "component": "commission",
        "values_bps": (15.0, 1.5),
        "ratio": 10.0,
        "sites": ("kis_backtest_engine", "screener_routes", "legacy_schemas",
                  "graph_runner", "kis_portfolio_analyzer",
                  "realism_engine", "multi_strategy_backtest",
                  "stage11_routes", "stage12_routes", "multibacktest_schema"),
        "reason": ("★같은 백테스트를 `stage11` 로 부르면 1.5bp, `screener`·"
                   "`legacy` 로 부르면 15bp★ 다. 요청이 값을 실으면 그것이 "
                   "이기지만, 안 실으면 **문이 수수료를 정한다**. 어느 쪽이 옳은지 "
                   "이 저장소는 재지 않았다 — `market_rules` 는 1.5bp 라고 적지만 "
                   "스스로 '근사' 라고 밝힌다."),
    },
)

#: `market_rules` 가 주는데 백테스트가 안 쓰던 것들. ★상태를 가른다★
UNAPPLIED_RULES: tuple[dict[str, str], ...] = (
    {"rule": "sell_tax_bp", "status": "opt_in",
     "reason": ("증권거래세+농특세 18bp(매도 편도). ★두 수수료 후보 어느 쪽보다 "
                "크다★ — AK 에서 `charge_sell_tax` 로 켤 수 있게 됐고 기본은 꺼짐.")},
    {"rule": "spread_bp_default", "status": "opt_in",
     "reason": ("호가 스프레드 프록시 5bp(편도 절반 부과). AK 에서 `charge_spread` "
                "로 켤 수 있게 됐고 기본은 꺼짐.")},
    {"rule": "impact_coeff", "status": "opt_in",
     "reason": ("시장충격 `k·√참여율`. AK 에서 `charge_market_impact` 로 켤 수 "
                "있게 됐고 기본은 꺼짐. ★참여율을 못 구하면 0 이 아니라 미상★.")},
    {"rule": "tick_size / is_on_tick / round_to_tick", "status": "absent",
     "reason": ("호가 단위는 **비용이 아니라 체결 가능성**이다 — 체결 모델 변경은 "
                "별건이라 이 작업의 범위 밖이다. `execution_plan` 만 경고한다.")},
    {"rule": "price_limit_pct", "status": "absent",
     "reason": ("가격제한(±30%)은 그날 체결 가능 범위를 정한다 — 역시 체결 모델이다. "
                "백테스트는 제한가를 넘는 체결을 막지 않는다.")},
    {"rule": "board_lot", "status": "absent",
     "reason": ("매매 단위. 현재 전부 1주라 실효가 없지만, ETF·우선주 예외가 "
                "데이터 계층에 생기면 그때는 수량이 달라진다.")},
    {"rule": "shortable", "status": "absent",
     "reason": ("차입 가능여부가 미연동이라 언제나 `None` 이다 — 롱온리 백테스트에는 "
                "실효가 없지만, ★미상이지 '가능' 이 아니다★.")},
)


# ═══════════════════════════════════════════════════════════════════════════
# 축 · 롤업
# ═══════════════════════════════════════════════════════════════════════════

def site_axis(site: CostSite) -> dict[str, Any]:
    """한 자리 → 축. ★못 재는 것과 안 보는 것을 가른다★

    · 못 잰 성분이 하나라도 있으면 `unknown` — **통과가 아니다**.
    · 안 보는 성분이 있으면 `degraded` — **관측된 결함**이다.
    · 다섯을 다 부과하면 `ok`.
    """
    states = site.components
    foggy = sorted(n for n, s in states.items() if s == STATE_UNMEASURABLE)
    missing = sorted(n for n, s in states.items() if s not in (STATE_CHARGED,
                                                               STATE_UNMEASURABLE))
    common = {"site": site.site, "components": dict(states),
              "commission_bps": site.commission_bps,
              "rate_source": site.rate_source,
              "slippage_bps": site.slippage_bps,
              "decision_touching": site.decision_touching,
              "missing": missing, "unmeasurable": foggy}
    if foggy:
        return {"state": AXIS_UNKNOWN,
                "reason": (f"못 잰 성분이 있습니다({' · '.join(foggy)}) — "
                           f"★0 원이 '비용이 없다' 로 읽히면 안 됩니다.★"), **common}
    if missing:
        return {"state": AXIS_DEGRADED,
                "reason": (f"보지 않는 성분이 있습니다({' · '.join(missing)}) — "
                           f"★안 보는 비용은 0 원이 아니라 부재입니다.★"), **common}
    return {"state": AXIS_OK, "reason": None, **common}


def _policy_of(site: CostSite) -> CostPolicy:
    charged = {n for n, s in site.components.items() if s == STATE_CHARGED}
    return CostPolicy(
        commission_bps=site.commission_bps or 0.0,
        slippage_bps=site.slippage_bps or 0.0,
        charge_tax="tax" in charged, tax_bps=18.0 if "tax" in charged else None,
        charge_spread="spread" in charged,
        spread_bps=5.0 if "spread" in charged else None,
        charge_impact=False,   # 참여율에 달려 있어 비교에서 제외한다
    )


def registry_evidence() -> dict[str, Any]:
    """저장소 전체의 비용 모델 상태 한 장.

    ★실행 하나에 대한 판정이 아니다★ — *"이 저장소가 어디서 비용을 정하고
    무엇을 빠뜨리는가"* 라는 **구조**에 대한 관측이다.
    """
    axes = {s.key: site_axis(s) for s in COST_SITES}
    labels = {s.key: s.label for s in COST_SITES}
    return {
        **rollup(axes, labels),
        "disagreements": [dict(d) for d in DISAGREEMENTS],
        "unapplied_rules": [dict(r) for r in UNAPPLIED_RULES],
        # ★같은 왕복을 각 모델로 재면 몇 bp인가★ — 비교가 한 자에서 나와야 한다.
        "round_trips": [{"key": s.key, "label": s.label,
                         "round_trip_bps": round_trip_bps(_policy_of(s))["round_trip_bps"]}
                        for s in COST_SITES],
        "decision_touching": [s.key for s in COST_SITES if s.decision_touching],
        "note": _NOTE,
    }
