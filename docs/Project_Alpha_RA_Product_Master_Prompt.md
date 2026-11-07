# Project Alpha — 리테일 자문(RA) 제품 아키텍처 마스터 프롬프트 (원문 보관)

> 접수 2026-09-12 · ★사용자가 준 원문이다. 고치지 않는다.★
> `docs/` 루트의 외부 제공 브리프(`Project_Alpha_GSQuant_Architectural_Benchmark.md` ·
> `Project_Alpha_Macro_Research_Spec.md` · `Project_Alpha_Dynamic_Portfolio_Design_Brief.md` ·
> `Project_Alpha_CTO_QuantPM_Master_Prompt.md`)와 같은 자리·같은 이유로 둔다 —
> **나중에 "무엇을 요구받았는지" 를 원문으로 대조**할 수 있어야 한다.
>
> 이 요구에 대한 응답은 아래 넷이다:
> - 규칙 [`specs/2026-09-12-ra-product-rules.md`](specs/2026-09-12-ra-product-rules.md)
> - 증거 [`specs/2026-09-12-ra-benchmark-evidence-matrix.md`](specs/2026-09-12-ra-benchmark-evidence-matrix.md)
> - 갭 [`specs/2026-09-12-ra-gap-analysis.md`](specs/2026-09-12-ra-gap-analysis.md)
> - 도메인 [`specs/2026-09-12-ra-domain-architecture.md`](specs/2026-09-12-ra-domain-architecture.md)
> - 로드맵 [`../docs/plans/2026-09-12-ra-product-roadmap.md`](plans/2026-09-12-ra-product-roadmap.md)

## ★원문을 그대로 따르지 않은 세 곳★

원문을 보관하는 이유의 절반은 **어긋난 곳을 숨기지 않기 위해서**다. 세 곳에서
원문과 다르게 했고, 각각 사용자 승인을 받았다.

| 원문 요구 | 실제로 한 것 | 왜 |
|---|---|---|
| `CLAUDE.md` 를 **새로 만들라** | 기존 `CLAUDE.md` 를 **유지**하고 규칙은 별도 문서로. CLAUDE.md 에는 링크 한 개만 덧붙임 | 기존 파일이 mock 게이트·실거래 6중 안전장치 등 ★불변식★을 99/100줄로 담고 있다. 덮어쓰면 원문 자신의 규칙 4번(NO DESTRUCTIVE REFACTORING)을 어긴다 |
| `docs/evidence-matrix.md` 등 **평평한 경로** | `docs/specs/2026-09-12-ra-*.md` (저장소 관례: 날짜 접두사·한국어·★마커★) | 기존 스펙 40여 종과 같은 목소리로 읽히게. 매핑 표는 로드맵 문서에 있다 |
| `PUBLICLY_VERIFIED` 등 **새 증거 어휘** | `SRC_VERIFIED`/`SRC_INFERRED`/`SRC_UNKNOWN` 으로 접두사 격리 | `CLAUDE.md` §2 가 새 어휘 생성을 금한다. 이미 `E0~E5`(데이터 출처)·`L0~L3`(모델 역량, **방향 반대**)가 DB 에 값으로 있고 한 번 충돌했다 |

---

## 원문

```text
MASTER PROMPT: FINTECH QUANT PLATFORM ARCHITECTURE & MODULAR ROADMAP SPECIFICATION

ROLE DEFINITION
You are a Senior Fintech Product Architect, Quant Portfolio Engineer, Financial Data
Engineer, and Regulatory-Aware UX Designer.

Your task is to analyze the existing codebase in the current working directory,
benchmark the core business models, algorithm structures, and user experiences of 4
leading Korean fintech/robo-advisor platforms (SolutionQuant, AI Quantec, Quantit, and
fint/December & Company), and integrate their key strengths into a unified, modular
domain architecture for this project.

To prevent context window degradation and unauthorized codebase destruction, you must
execute this task in a DOCUMENTATION-FIRST & PHASE-GATED approach. Do NOT write or
refactor core application source code in your initial turn. First, explore the project,
create system rules, write comprehensive `.md` specification files, and request human
approval before code implementation.

1. BENCHMARKING KNOWLEDGE BASE & TARGET FEATURE MAP

A. SolutionQuant
 * Core Strengths: Alternative data integration (unstructured/textual/financial),
   Signal Registry, concentrated high-conviction portfolios (e.g., KOSPI/KOSDAQ growth
   scoring), and risk control focusing on factor/sector concentration rather than
   simple diversification.
 * Target Modules to Design: `AlternativeDataAdapter`, `SignalRegistry`,
   `ConcentrationRiskEngine` (HHI, factor exposure limits, liquidity constraints).

B. AI Quantec
 * Core Strengths: `Q-Engine` (strategy builder), `Q-X` (24/7 real-time market risk
   monitoring middleware that dynamically shifts exposure to defensive assets during
   stress), portfolio diagnostic reports for existing user holdings, and B2B2C API
   delivery to financial institutions (e.g., NH Investment & Securities).
 * Target Modules to Design: `PortfolioDiagnosticEngine`, `RiskMonitorMiddleware`,
   `AdvisorAPIAdapter`.

C. Quantit (Plantit)
 * Core Strengths: End-to-end automated pipeline connecting data ingestion ->
   backtesting -> strategy definition -> execution, dynamic rebalancing, monthly
   contribution plans, and TDF-style (Target-Date Fund) glide-path de-risking for
   retirement accounts (IRP).
 * Target Modules to Design: `DataToExecutionTrace`, `DynamicRebalancingEngine`,
   `ContributionScheduler`, `GlidePathEngine`, `DailyNAVReconciliation`.

D. fint / December & Company
 * Core Strengths: `ISAAC` (decision engine) & `PREFACE` (personalized execution
   engine), multi-account hub (General, Pension Savings, IRP, ISA), "Why My Asset Moved
   Today" daily asset change explanation UX, and an open Strategy Marketplace (fint
   Selection) offering third-party manager strategies.
 * Target Modules to Design: `MultiAccountHub`, `DailyExplanationEngine`,
   `StrategyMarketplace` (`StrategyProvider`, `StrategySubscription`,
   `StrategyEvaluationScorecard`).

2. STRICT OPERATIONAL CONSTRAINTS & REGULATORY GUARDRAILS

1. PAPER-TRADING DEFAULT: All order generation and execution features MUST default to
   simulation or paper-trading mode (`PaperExecutionAdapter`). Real broker account
   execution code is strictly forbidden until explicit license/regulatory verification
   is completed.
2. EVIDENCE MANAGEMENT: Every claim, strategy logic, or system feature must tag its
   evidence level:
   * `PUBLICLY_VERIFIED`: Confirmed via official sites, regulatory disclosures, or
     Koscom RA Testbed official records.
   * `INFERRED`: Reasonably deduced from public press or industry standards, but not
     officially confirmed.
   * `UNKNOWN`: Unverified internal algorithms or trade secrets. Do NOT hallucinate
     unverified logic as fact.
3. TESTBED VS LIVE DISCONNECTED: You must strictly distinguish between Koscom RA
   Testbed returns, backtest returns, paper trading returns, and live account returns.
   Never project past performance as future returns in UI components.
4. NO DESTRUCTIVE REFACTORING: Respect existing codebase patterns, folder structures,
   and domain entities. Propose migration plans in documentation before modifying
   existing schemas.

3. IMMEDIATE TASK EXECUTION (PHASE 1: EXPLORE & DOCUMENT)

Step 3.1: Repository Exploration
 1. Examine directory tree, `package.json`, `pyproject.toml`, `requirements.txt`,
    `docker-compose.yml`, `.env.example`, and `README.md`.
 2. Inspect `frontend`, `backend`, `database`, `infra`, and existing domain
    entities/modules (auth, portfolio, market data, backtest, risk, reporting,
    execution).

Step 3.2: Create `CLAUDE.md` (System Rules File)
 * Mandatory paper-trading default rule.
 * Evidence tagging standards (`PUBLICLY_VERIFIED`, `INFERRED`, `UNKNOWN`).
 * Verification checklist (`npm test` / `pytest` commands).
 * Coding conventions, type safety, and async error-handling guidelines.

Step 3.3: Generate System Specification Documents
 1. `docs/evidence-matrix.md`  — Evidence breakdown for the 4 companies across
    (Business Model, Asset Allocation, Risk Architecture, UX).
 2. `docs/gap-analysis.md`     — Table evaluating current project status
    (`complete`/`partial`/`missing`) across 8 core domains.
 3. `docs/domain-architecture.md` — Unified domain model with TypeScript/Python type
    definitions for: `InvestorProfile`, `SignalDefinition`, `StrategyMetadata`,
    `RebalanceProposal`, `DailyExplanationLog`.
 4. `docs/implementation-roadmap.md` —
    Phase 0: Setup & Architecture (Current)
    Phase 1: Quant Core & Risk Engine (Signal Registry, Q-X Risk Monitor, Paper Engine)
    Phase 2: Diagnostics & Rebalancing (Portfolio Diagnostic, Dynamic Rebalance, Glide Path)
    Phase 3: Client Experience & Explanation ("Why Asset Moved Today", Multi-Account Hub, Reports)
    Phase 4: Platform & Marketplace (Strategy Marketplace, B2B Advisor API)

4. FIRST RESPONSE OUTPUT REQUIREMENTS
 1. Do NOT modify any existing application source code files.
 2. Create `CLAUDE.md` and the 4 documentation files in `docs/`.
 3. Output a summary report containing:
    A. Existing Project Assessment
    B. Benchmarking & Evidence Summary Matrix
    C. Proposed Unified Architecture & Domain Schemas
    D. Proposed MVP Scope & Next Step Approval Request

Ask for my approval to proceed to Phase 1 Code Implementation.
```
