# RA 제품 축 도메인 아키텍처 — ★타입은 정의하고, 스키마는 바꾸지 않는다★

> 설계 2026-09-12 · 기준 커밋 `564e035` · ★프로덕션 코드는 한 줄도 바뀌지 않았다.★
> 선행: [갭 분석](2026-09-12-ra-gap-analysis.md) · [증거 매트릭스](2026-09-12-ra-benchmark-evidence-matrix.md) ·
> [규칙](2026-09-12-ra-product-rules.md) · 구조 [`architecture.md`](architecture.md) ·
> 저장 [`DATA_PLATFORM_SPEC.md`](DATA_PLATFORM_SPEC.md)

## 0. 설계 원칙 — ★새로 만들기 전에 이미 있는 것을 덮는다★

갭 분석이 반복해서 내놓은 모양은 *"기계는 있는데 표면이 없다"* 였다. 그래서 이
문서의 다섯 타입은 **엔진을 새로 만들지 않는다**. 하는 일은 셋뿐이다.

1. **이름을 준다** — 지금 요청 인자로 떠다니는 것(`risk_aversion`·`horizon_days`)에
   신원을 준다.
2. **덮는다** — 다섯 갈래 카탈로그를 통합하지 않고 **공통 뷰**를 얹는다.
3. **열거한다** — 자유 문자열이던 사유를 **코드로** 만든다.

★경계★ — CLAUDE.md §3 이 못 박은 대로 **Macro → Allocation 동작 · 최적화기 의미 ·
국면-배분 정책 변경은 별도 승인 사항**이다. 아래에 그 경로를 건드리는 항목은
`승인 필요` 로 표시했고, 이 문서는 **표시만** 한다.

**단위 규약** — 비중은 ★퍼센트★다(`allocation_routes._w_dict` 가 `round(w*100, 2)`
로 낸다). 새 타입도 같은 단위를 쓴다. 섞으면 `target_versions.py` 가 고쳤던 종류의
결함이 돌아온다.

---

## 1. `InvestorProfile` — 요청 인자를 ★영속 신원★ 으로

### 지금

`investment_decision.decide()` 와 `rebalance_policy.rebalance_decision()` 이
`risk_aversion` · `horizon_days`(기본 `DEFAULT_HORIZON_DAYS = 63`)를 **매 요청마다**
받는다. 같은 사람에게 같은 값이 쓰인다는 보장이 없다. 계좌 유형 개념은 없다.

### 제안

```python
# src/domain/investor_profile.py  (제안 — 아직 없는 파일)
from __future__ import annotations
from dataclasses import dataclass, field

#: 계좌 유형. ★세제·상품 제약이 계좌마다 다르므로 배분 제약의 입력이다.★
ACCOUNT_GENERAL = "general"          # 일반 위탁
ACCOUNT_PENSION_SAVINGS = "pension_savings"   # 연금저축
ACCOUNT_IRP = "irp"                  # 개인형 퇴직연금
ACCOUNT_ISA = "isa"                  # 개인종합자산관리계좌
ACCOUNT_TYPES = (ACCOUNT_GENERAL, ACCOUNT_PENSION_SAVINGS, ACCOUNT_IRP, ACCOUNT_ISA)

#: 위험 성향. ★숫자 하나로 뭉개지 않는다★ — 등급과 그 근거를 함께 든다.
RISK_TOLERANCE_LEVELS = ("conservative", "moderate_conservative",
                         "moderate", "moderate_aggressive", "aggressive")


@dataclass(frozen=True)
class InvestorProfile:
    profile_id: str
    owner_id: str                       # 인증 주체(★P-1 전에는 채울 수 없다★)
    account_type: str                   # ACCOUNT_TYPES
    risk_tolerance: str                 # RISK_TOLERANCE_LEVELS
    horizon_days: int | None            # None = 미상. ★63 으로 지어내지 않는다★
    target_retirement_year: int | None   # 글라이드패스 입력. 없으면 None
    risk_aversion: float | None          # 효용 계산용 λ. 등급에서 파생하되 원본을 남긴다
    #: ★어떻게 정해졌나★ — 설문/사용자 직접 입력/기본값 중 무엇인지
    source: str = "unknown"              # survey | user_declared | default | unknown
    assessed_at: str | None = None       # ISO. 성향은 낡는다 — 언제 쟀는지가 필요하다
    constraints: dict[str, float] = field(default_factory=dict)  # 계좌 제약 오버라이드
```

```ts
// frontend/src/entities/investor-profile/types.ts (제안)
export type AccountType = 'general' | 'pension_savings' | 'irp' | 'isa';
export type RiskTolerance =
  | 'conservative' | 'moderate_conservative'
  | 'moderate' | 'moderate_aggressive' | 'aggressive';

export interface InvestorProfile {
  profileId: string;
  ownerId: string;
  accountType: AccountType;
  riskTolerance: RiskTolerance;
  horizonDays: number | null;
  targetRetirementYear: number | null;
  riskAversion: number | null;
  source: 'survey' | 'user_declared' | 'default' | 'unknown';
  assessedAt: string | null;
  constraints: Record<string, number>;
}
```

★`horizon_days: None` 을 63 으로 채우지 않는다★ — CLAUDE.md §4 의 `미상 ≠ 0`.
호출부가 기본값을 쓰기로 정하면 **그 사실을 결과에 라벨로 남긴다**.

| 이번에 하는 것 | 이번에 ★안 하는 것★ |
|---|---|
| 타입과 어휘 정의 | `users`·`portfolios` 테이블 변경 |
| `decide()` 인자와의 대응 관계 기술 | `decide()` 시그니처 변경(★승인 필요 — 결정 경로★) |

---

## 2. `SignalDefinition` — 다섯 카탈로그를 ★덮는 뷰★

### 지금

| 카탈로그 | 모듈 | 메타 |
|---|---|---|
| 스크리너 필드 | `engine/filter_ast.py` `FieldMeta` | id·label·category·unit·higher_better·전형 범위 |
| 타이밍 규칙 | `engine/timing_factors.py` `TimingRule` | ★11필드★ — 관측창·진입/청산·리밸런싱·비용·**PIT 타임스탬프** |
| 알파 DSL | `engine/alpha_lab.py` `FIELDS` | id·라벨·그룹·수식 |
| 전략 토큰 | `kis_strategies/factor_tokens.py` | 토큰명 + **미지원 사유 상수** |
| 알파 수명주기 | `data/alpha_registry.py` | draft→…→approved |
| 출처 등급 | `data/source_registry.py` | `E0~E3` · `verified_live` |

★`TimingRule` 이 가장 풍부하므로 그것을 상위 스키마의 뼈대로 삼는다.★

### 제안

```python
# src/domain/signal_definition.py (제안)
SIGNAL_KINDS = ("screener_field", "timing_rule", "alpha_expr", "strategy_token")


@dataclass(frozen=True)
class SignalDefinition:
    signal_id: str
    kind: str                    # SIGNAL_KINDS — 어느 카탈로그에서 왔나
    label: str
    category: str                # FieldMeta.category | TimingRule.signal_family
    #: ★공표 지연과 개정 정책★ — timing_factor_meta 가 이미 출처에서 파생시킨다
    release_lag: str | None = None
    revision_policy: str | None = None
    observation_window: dict | None = None      # TimingRule 과 같은 모양
    point_in_time_timestamp: str | None = None   # 룩어헤드 감사용
    #: ★증거 축은 기존 어휘를 쓴다★ — source_registry.EVIDENCE_GRADES (E0~E3)
    evidence_grade: str | None = None
    #: 왜 못 쓰는가. factor_tokens 의 미지원 사유 상수를 그대로 옮긴다
    unavailable_reason: str | None = None
    owner_module: str = ""        # ★단일 출처를 가리킨다 — 값을 복사하지 않는다★
```

★`evidence_grade` 는 `E0~E3` 다★ — 회사 조사용 `SRC_*` 와 **다른 축**이다
([규칙](2026-09-12-ra-product-rules.md) §2). 섞지 않는다.

★`owner_module` 이 핵심이다.★ 이 뷰는 값을 **복사해 보관하지 않는다** — 원본
카탈로그를 가리키고 조회 시 합친다. 복사하면 반드시 갈라진다(CLAUDE.md 헤더).

| 이번에 하는 것 | 이번에 ★안 하는 것★ |
|---|---|
| 공통 뷰 스키마 | 다섯 카탈로그 **통합 리팩터** |
| `E0~E3` 를 신호에 잇는 경로 설계 | `FIELD_BY_ID` 변경(★스크리너 3-레이어는 리팩터 대상이 아니다★) |

---

## 3. `StrategyMetadata` — 자기 알파 거버넌스를 ★제공자 축으로★

### 지금

`alpha_registry`(5단계 승격 · `usable_for_portfolio()` 게이트) + `strategy_health`
(`healthy`/`watch`/`de_risk`/`paused`/`retired`) + `Constraints.group_caps_pct`.
★전부 "자기 알파" 전제다★ — 제공자·구독·요율 개념이 없다.

### 제안

```python
# src/domain/strategy_metadata.py (제안)
MARKETPLACE_STATUS = ("internal", "candidate", "listed", "suspended", "delisted")


@dataclass(frozen=True)
class ConcentrationLimits:
    """★솔루션퀀트식 '분산이 아니라 집중을 규칙으로' 를 표현하는 자리.★

    새 엔진이 필요 없다 — 그대로 `constrained_opt.Constraints` 로 옮겨진다.
    """
    max_holdings: int | None = None          # 예: 10종목
    max_weight_pct: float | None = None      # 예: 25.0
    group_caps_pct: dict[str, float] = field(default_factory=dict)  # 예: {"upstream": 80.0}
    min_adv_participation_pct: float | None = None   # 유동성 하한


@dataclass(frozen=True)
class StrategyMetadata:
    strategy_id: str
    label: str
    provider_id: str                  # "internal" 또는 외부 운용사 id
    lifecycle_status: str             # alpha_registry.STATUSES 를 그대로 쓴다
    marketplace_status: str = "internal"   # MARKETPLACE_STATUS
    health_status: str | None = None  # strategy_health.STATUSES. ★미측정은 None★
    concentration: ConcentrationLimits = field(default_factory=ConcentrationLimits)
    signal_ids: tuple[str, ...] = ()   # SignalDefinition 참조
    #: ★수익률의 종류★ — 규칙 §3 의 4종 중 무엇인지. 섞어 적지 않는다
    performance_basis: str | None = None   # testbed | backtest | paper | live
```

★`marketplace_status` 와 `lifecycle_status` 를 분리한다.★ 전자는 *유통*이고
후자는 *검증*이다. 합치면 "검증 안 된 전략이 팔리는" 상태를 이름으로 막을 수 없다.
`auto_alpha` 가 `experimental` 천장을 둔 것과 같은 규율이다.

`StrategySubscription` · `StrategyEvaluationScorecard` 는 ★P-1(인증) 이후★에
설계한다 — 구독은 주체가 있어야 성립한다.

---

## 4. `RebalanceProposal` — ★거의 다 있다. 빠진 것은 사유의 이름뿐★

### 지금

`investment_decision._legs_from()` 이 이미 자산별로 이것을 낸다:

```
ticker · current_w · target_w · delta_w
half_width_pct · low_pct · high_pct · outside_band     ← 동적 밴드
constraint_binding · view_refs
```

회전율은 `Constraints.turnover_cap_pct`(`0.5·Σ|w−w_cur|`), 상태는
`execution_store` 의 9상태 기계, 페이퍼 여부는 `trading_engine` 의 모드 문자열.

**빠진 것 하나** — `rebalance_policy` 가 만드는 `reason` 이 ★자유 문자열★이다.

### 제안

```python
# src/domain/rebalance_reason.py (제안)
#: ★열거된 사유★ — 화면·리포트·감사가 같은 사건을 같은 이름으로 부른다
REASON_BAND_BREACH = "band_breach"           # 동적 밴드 이탈
REASON_UTILITY_GAIN = "utility_gain"         # 기대효용 개선 > 비용
REASON_REGIME_CHANGE = "regime_change"       # 국면 전환
REASON_VOLATILITY_SPIKE = "volatility_spike"
REASON_CALENDAR = "calendar"                 # 정기 리밸런싱
REASON_CONTRIBUTION = "contribution"         # 적립금 유입
REASON_GLIDE_PATH = "glide_path"             # 생애주기 디리스킹
REASON_CONSTRAINT_BINDING = "constraint_binding"
REASON_NONE_BELOW_COST = "none_below_cost"   # ★거래하지 않기로 한 것도 결정이다★
```

```ts
// frontend/src/entities/rebalance/types.ts (제안)
export type RebalanceReason =
  | 'band_breach' | 'utility_gain' | 'regime_change' | 'volatility_spike'
  | 'calendar' | 'contribution' | 'glide_path' | 'constraint_binding'
  | 'none_below_cost';

export interface RebalanceLeg {
  ticker: string;
  currentW: number; targetW: number; deltaW: number;   // ★퍼센트★
  halfWidthPct: number | null; lowPct: number | null; highPct: number | null;
  outsideBand: boolean;
}

export interface RebalanceProposal {
  proposalId: string;
  asOf: string;
  legs: RebalanceLeg[];
  reasons: RebalanceReason[];        // 복수일 수 있다
  turnoverPct: number | null;        // 미상이면 null
  executionMode: 'dry_run' | 'paper' | 'live';   // ★기본은 dry_run★
  planStatus: string | null;         // execution_store 상태기계
  pitEvidence: string | null;        // run_evidence: verified|partial|unverified|unknown
}
```

★`REASON_NONE_BELOW_COST` 를 빼지 않는다.★ *"비용보다 이득이 작아 거래하지 않았다"*
는 `rebalance_policy` 의 핵심 판단이고, 사유 목록에서 빠지면 **가장 자주 일어나는
결정이 기록되지 않는다**.

`executionMode` 와 `pitEvidence` 를 제안에 실어 ★화면이 "무엇을 근거로 한
제안인지" 를 항상 말하게 한다★ — 이것이 퀀팃식 `DataToExecutionTrace` 의 첫 칸이다.

| 이번에 하는 것 | 이번에 ★안 하는 것★ |
|---|---|
| 사유 상수 목록과 전달 타입 | `rebalance_policy`·`decide()` 수정(★승인 필요 — 배분 결정 경로★) |
| PIT 증거를 제안까지 나르는 **설계** | 그 배선 구현 |

---

## 5. `DailyExplanationLog` — 5효과에 ★가격·환·배당 축을 더한다★

### 지금

`attribution_decomposer.EFFECT_COLUMNS` 가 `allocation` · `selection` · `macro` ·
`netting` · `cost` 를 한국어 라벨과 함께 분해하고 `multibacktest_daily` 에 적재된다.
★전략 수준이고 백테스트 안이다.★ 환효과·배당효과는 저장소 어디에도 없다.

### 제안

```python
# src/domain/daily_explanation.py (제안)
#: 기존 5효과 — ★이름을 바꾸지 않는다★ (attribution_decomposer 가 단일 출처)
EFFECT_COLUMNS = ("allocation_effect", "selection_effect", "macro_effect",
                  "netting_effect", "cost_effect")

#: 보유 자산의 하루를 설명하려면 더 필요한 축
DRIVER_PRICE = "price"           # 기초자산 가격 변동
DRIVER_FX = "fx"                 # 환율 (해외자산 보유 시)
DRIVER_DIVIDEND = "dividend"     # 배당·분배금
DRIVER_REBALANCE = "rebalance"   # 그날의 매매
DRIVER_FEE = "fee"               # 보수·수수료·세금
DAILY_DRIVERS = (DRIVER_PRICE, DRIVER_FX, DRIVER_DIVIDEND, DRIVER_REBALANCE, DRIVER_FEE)


@dataclass(frozen=True)
class DailyExplanationLog:
    as_of: str                       # 거래일
    scope: str                       # portfolio | account | ticker
    scope_id: str
    total_change_krw: float | None
    total_change_pct: float | None
    #: 드라이버별 기여. ★미측정 축은 키를 빼지 말고 None 을 넣는다★
    drivers: dict[str, float | None] = field(default_factory=dict)
    #: 설명되지 않은 잔차. ★0 으로 만들지 않는다★
    residual_krw: float | None = None
    #: 결정론적 템플릿이 만든 한국어 요약. LLM 이 아니다
    summary_ko: str = ""
    #: 어느 축이 빠져서 잔차가 생겼나
    missing_drivers: tuple[str, ...] = ()
```

★설명 생성은 결정론적 템플릿이다 — LLM 이 아니다.★ 이유 셋: ⑴ 같은 입력에 같은
문장이 나와야 감사가 된다 ⑵ 잔차를 말로 덮을 수 없어야 한다 ⑶ 운영에서 키가 없어도
동작해야 한다. `services/narrative` 의 LLM 서술은 **별개**이고, 이 로그를 **입력으로**
쓸 수는 있다.

★`residual_krw` 를 0 으로 만들지 않는다.★ 설명되지 않은 부분이 남으면 남은 대로
보여 주고 `missing_drivers` 로 **왜 남았는지** 말한다. 이것이 "침묵 폴백 금지" 의
설명 축 번역이다.

---

## 6. 모듈 배치 제안

```
src/domain/                      ★신규 제안 — 순수 타입·어휘만. 엔진 없음★
  investor_profile.py
  signal_definition.py
  strategy_metadata.py
  rebalance_reason.py
  daily_explanation.py
```

★왜 `src/data/` 나 `src/engine/` 이 아닌가★ — 이 파일들은 **저장도 계산도 하지
않는다**. 어휘와 형태만 든다. `src/data/retention.py` 가 "선언은 여기, 집행은
테스트" 로 성립한 것과 같은 모양이다.

**프런트** — FSD 규약대로 `frontend/src/entities/<name>/types.ts`. CI 의
eslint FSD 규칙(역방향·동료 임포트 금지)을 그대로 받는다.

---

## 7. 마이그레이션 제안 — ★이번에 실행하지 않는다★

| 무엇 | 어떻게 | 선행 |
|---|---|---|
| 계좌 차원 | `portfolios` 는 PK 가 `(username, ticker)` 라 계좌가 안 들어간다. **새 테이블**(`investor_profiles` · `accounts`)을 더하고 기존 표는 **건드리지 않는다** | ★P-1 인증★ |
| 컬럼 추가 | `src/data/schema_add_columns.py::add_columns()` **하나만** 쓴다(반환값 확인 필수) | — |
| 보존 분류 | ★새 표를 만들면 `src/data/retention.py` 에 부류와 사유를 적어야 한다★ — 안 적으면 `tests/test_retention_policy.py` 가 실패한다 | — |
| alembic | ★도입하지 않는다★ — [인프라 로드맵](../plans/2026-09-06-quant-db-infra-roadmap.md)의 "하지 않을 것" 표에 다시 볼 조건과 함께 있다 | — |

---

## ★이 문서가 주장하지 않는 것★

- **구현한 것이 아니다.** `src/domain/` 은 **제안**이고 파일은 없다. 코드 0줄.
- **결정 경로를 바꾸지 않았다.** `decide()`·`rebalance_policy`·`constrained_solve`
  는 손대지 않았고, 손대려면 ★별도 승인★이다(CLAUDE.md §3).
- **4사의 내부 설계를 옮긴 것이 아니다.** 알고리즘 칸은 전부 `SRC_UNKNOWN` 이다
  ([매트릭스](2026-09-12-ra-benchmark-evidence-matrix.md)). 여기 있는 것은 **우리
  코드의 모양**이고, 벤치마크는 *무엇을 만들 값어치가 있는지*의 근거로만 쓰였다.
- **타입이 있으면 기능이 있다는 뜻이 아니다.** `GlidePathEngine`·`ContributionScheduler`
  는 여기에 타입조차 없다 — 로드맵 P2 의 **설계 대상**이다.
