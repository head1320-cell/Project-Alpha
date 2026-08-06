"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// AllocationProvider — Multi-Stage Wizard 전역 상태 (전략 수립 파이프라인 공유)
//   app/allocation/layout.tsx가 마운트 — App Router에서 layout은 자식 라우트
//   전환에도 유지되므로 게이트 ↔ 각 스테이지 이동 시 유니버스·뷰·가중치·결과가
//   증발하지 않는다 (스크린샷의 "Session이나 상태 관리 툴(Context API)" 채택 —
//   워크스페이스 다중화 시 zustand 승격은 R3 문서화).
//   + 위저드 확장: goal(진입 목표)·stageComplete[]·isResultStale·ensureFreshRun·
//     sessionStorage(goal/pos/wip) 하이드레이트·persist → 중간 새로고침 비파괴.
// ═══════════════════════════════════════════════════════════════════════════════
import React, { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { UseQueryResult } from "@tanstack/react-query";
import {
  allocationApi, type AllocationModel, type AllocationViewInput, type AnalyzeResult,
  type ConstraintsInput, type StressResult, type StressScenarioMeta,
  type TimingResult, type XrayResult,
} from "@/entities/allocation/api";
import { saveStudy, type AllocationStudy } from "@/entities/allocation/storage";
import { researchApi } from "@/entities/research/api";
import type { TacticalStrategy } from "@/entities/macro/analysisModel";
import type { Holding } from "./PortfolioBuilder";
import type { TimelineEvent } from "./ResearchTimeline";
import { buildAnalyzeRequest, freshnessOf, signatureOf, type ResultFreshness } from "./analyzeSignature";
import { PortfolioProvider, SS_WIP, usePortfolio } from "./slices/PortfolioContext";
import { RunProvider, useRun } from "./slices/RunContext";
import { ScenarioProvider, useScenario } from "./slices/ScenarioContext";
import { DEFAULT_TIMING, TimingProvider, useTiming, type TimingConfig } from "./slices/TimingContext";

// 타이밍 설정 타입·기본값의 소유는 타이밍 슬라이스다. 여기서 다시 내보내는 것은 **경로
// 호환**을 위해서다 — 소비자(`app/allocation/timing/page.tsx`·`timingPresets.ts`)가 이미
// 이 모듈에서 가져다 쓰고 있고, 슬라이스를 나눈 것이 그들의 import 를 깰 이유는 없다.
export { DEFAULT_TIMING };
export type { TimingConfig };

export const MODELS: { id: AllocationModel; label: string }[] = [
  { id: "mvo", label: "MVO" },
  { id: "bl", label: "Black-Litterman" },
  { id: "risk_parity", label: "Risk Parity" },
  { id: "hrp", label: "HRP" },
  { id: "min_var", label: "Min Var" },
  { id: "max_div", label: "Max Div" },
  { id: "min_cvar", label: "Min CVaR" },
];

export const COV_ONLY: AllocationModel[] = ["risk_parity", "hrp", "min_var", "max_div", "min_cvar"];

// ── 7단계 순차 리서치 파이프라인 (레퍼런스: Portfolio Visualizer 위저드 / Aladdin / Venn) ──
// 00 Overview·06 Journal은 북엔드, 01~05는 3 매크로 페이즈(SETUP/LOGIC/VALIDATION).
export type PhaseKey = "setup" | "logic" | "validation";
export interface StageMeta {
  n: string; href: string; label: string; title: string; desc: string;
  intent: string;            // "이 단계에서 할 일" — StageChrome이 렌더
  phase?: PhaseKey;          // 북엔드(overview/journal)는 undefined
}
// ★인덱스가 아니라 href 가 스테이지의 신원이다★
// 예전에는 stageComplete·PHASES.steps·WizardTracker 부제가 전부 배열 위치로 스테이지를
// 가리켰다. 그 상태에서 스테이지를 중간에 하나 끼우면 **타입 에러 없이** 완료 배지와
// 페이즈 소속과 부제가 한 칸씩 밀린다(실제로 stageComplete[9] 가 하드코딩돼 있었다).
// `as const` 로 href 리터럴을 뽑아 Record 키로 쓰면 컴파일러가 누락을 잡는다.
export const STAGES = [
  // phase: undefined 를 **명시**한다 — 생략하면 as const 가 이 객체에서 phase 키를 아예
  // 없애 버려 union 접근(s.phase)이 컴파일되지 않는다. 겸사겸사 "북엔드"임이 데이터에 드러난다.
  { n: "00", href: "/allocation/overview", label: "OVERVIEW", title: "Overview", desc: "전체 워크플로우 요약 — 각 단계로 드릴다운", intent: "현재 포트폴리오를 한눈에 점검하고 필요한 단계로 이동하세요.", phase: undefined },
  { n: "0M", href: "/allocation/macro", label: "MACRO PHASE", title: "Macro Phase", desc: "매크로 국면 스냅샷 — 리서치 컨텍스트로 고정", intent: "Macro 탭에서 넘어온 국면 스냅샷을 확인하고 리서치 컨텍스트로 붙이세요 (선택).", phase: "setup" },
  { n: "01", href: "/allocation/construct", label: "CONSTRUCT", title: "Construct", desc: "자산 구성 — 직접 구성 · 팩터 빌더 · 매크로 전략", intent: "자산을 2개 이상 담거나(직접) 팩터로 자동 구성하고 비중을 맞추세요.", phase: "setup" },
  { n: "02", href: "/allocation/alphalab", label: "ALPHA LAB", title: "Alpha Lab", desc: "알파 표현식 · lint · IC/ICIR 검증 · 레지스트리", intent: "독립 알파를 정의·검증하고 레지스트리로 관리하세요 (선택).", phase: "logic" },
  { n: "03", href: "/allocation/thesis", label: "THESIS", title: "Thesis", desc: "거시 테제 → Black-Litterman 뷰 + 신뢰도", intent: "거시 테제를 자산·방향·신뢰도로 변환하세요 (선택).", phase: "logic" },
  { n: "04", href: "/allocation/timing", label: "TIMING", title: "Timing", desc: "카나리 신호 + 마켓타이밍 — 위험 국면 게이트", intent: "카나리 자산·지표와 추세 필터로 위험-온/오프를 판단하세요 (선택).", phase: "logic" },
  { n: "05", href: "/allocation/optimize", label: "OPTIMIZE", title: "Optimize", desc: "모델·λ·τ + 효율적 프론티어 + 배분 흐름", intent: "엔진과 위험회피(λ)를 조정해 최적 배분을 산출하세요.", phase: "logic" },
  { n: "06", href: "/allocation/stress", label: "STRESS", title: "Stress", desc: "민감도 + 시나리오 severity + 상관-국면 스트레스", intent: "시나리오·충격·상관국면으로 배분의 견고성을 검증하세요.", phase: "validation" },
  { n: "07", href: "/allocation/explain", label: "ATTRIBUTION", title: "Attribution", desc: "사전 기대 vs 사후 실측 — 수익·기여·비용·리스크 귀인", intent: "결정 시점의 기대와 실제 결과를 대조해 귀인하세요 (런 기록 필요).", phase: "validation" },
  { n: "08", href: "/allocation/execution", label: "EXECUTION", title: "Execution", desc: "실행 준비실 — 오더 diff·비용 추정·pre-trade·승인 워크플로", intent: "목표 배분으로의 주문 차이·비용·pre-trade를 점검하고 승인 워크플로를 진행하세요 (실 주문 없음).", phase: "validation" },
  { n: "09", href: "/allocation/journal", label: "JOURNAL", title: "Journal", desc: "의사결정 기록 + ResearchRun — Macro View→Changed→Reason→Result→Review", intent: "이번 의사결정을 기록하고 사후 검증을 예약하세요.", phase: undefined },
] as const satisfies readonly StageMeta[];

/** 스테이지 신원 = href. 인덱스가 아니다. */
export type StageHref = (typeof STAGES)[number]["href"];

/** 북엔드(overview·journal)는 phase 가 없는 스테이지 — 위치가 아니라 이 속성으로 판별한다. */
export const BOOKENDS = STAGES.filter((s) => !s.phase).map((s) => s.href) as StageHref[];

export interface PhaseMeta { key: PhaseKey; label: string; ko: string; steps: StageHref[] }
export const PHASES: PhaseMeta[] = [
  { key: "setup", label: "SETUP", ko: "설정", steps: ["/allocation/macro", "/allocation/construct"] },
  { key: "logic", label: "LOGIC", ko: "설계", steps: ["/allocation/alphalab", "/allocation/thesis", "/allocation/timing", "/allocation/optimize"] },
  { key: "validation", label: "VALIDATION", ko: "검증", steps: ["/allocation/stress", "/allocation/explain", "/allocation/execution"] },
];

// A pathname is a known Allocation Studio route iff it is the gate or exactly one of the
// stage hrefs. Guards against stale sessionStorage `lastPos` (e.g. a renamed/removed route
// like the old /allocation/optimizer) producing a dead URL → hard 404 on Resume.
export function isKnownAllocationRoute(pathname: string | null | undefined): boolean {
  if (!pathname) return false;
  if (pathname === "/allocation") return true;
  return STAGES.some((s) => pathname === s.href);
}

export function stageIndex(pathname: string): number {
  // 가장 긴(정확) 매칭 우선. 게이트(/allocation)는 어떤 스테이지도 매칭 안 됨 → 0 폴백
  // (게이트 라우트는 layout의 isGate 분기에서 stageIndex를 소비하지 않으므로 무해).
  let best = -1; let bestLen = -1;
  STAGES.forEach((s, i) => {
    if (pathname === s.href || pathname.startsWith(s.href + "/")) {
      if (s.href.length > bestLen) { best = i; bestLen = s.href.length; }
    }
  });
  return best >= 0 ? best : 0;
}

export interface AllocationGoal { id: string; label: string }

// 매크로 탭에서 불러온 자산배분 전략의 출처 마커 (원 전략 비중 = 최적화 비교 기준선)
export interface LoadedStrategy {
  id: string; name: string; family: string; market: "kr" | "us";
  signal: string; weights: Record<string, number>;
}

// sessionStorage 키 (localStorage 스터디와 별개 — 세션 한정, 중간 새로고침 재개용)
const SS_GOAL = "alpha_alloc_goal";
// `SS_WIP` 는 `slices/PortfolioContext` 가 소유한다 — 같은 블롭을 두 곳이 읽으므로
// 키 문자열이 두 벌 있으면 언젠가 갈라진다. 여기서는 import 해서 쓴다.
const SS_POS = "alpha_alloc_pos";
// 붙여 둔 스냅샷의 **ID 만** 세션에 남긴다. 본문은 서버가 진실이고 여기 복사하지 않는다 —
// 새로고침 후에도 같은 ID 로 서버에서 다시 읽어 오므로 재현이 성립한다.
const SS_SNAP = "alpha_alloc_snapshot";
// `alpha_alloc_ruleset` 은 타이밍 슬라이스가 소유한다(전용 키 — 공유 블롭이 아니다).

interface AllocationCtx {
  holdings: Holding[];
  setHoldingsReset: (next: Holding[]) => void;
  holdingsMap: Record<string, number>;
  holdingsKey: string;
  views: AllocationViewInput[];
  setViewsLogged: (next: AllocationViewInput[]) => void;
  model: AllocationModel;
  setModel: (m: AllocationModel) => void;
  delta: number;
  setDelta: (v: number) => void;
  tau: number;
  setTau: (v: number) => void;
  result: AnalyzeResult | null;
  scenario: string;
  bump: number;
  setBump: (v: number) => void;
  severity: number;
  setSeverity: (v: number) => void;
  pickScenario: (id: string) => void;
  scenarios: StressScenarioMeta[];
  /**
   * 선택된 **시나리오 팩 신원** (스펙 §4 ⑦, Phase 9).
   * `scenario` 와 다른 것이다 — 저것은 `/stress` 가 실행할 수 있는 id 로 국내팩을 담지
   * 못한다. 국내팩을 고르면 `scenario` 는 그대로인데 화면은 국내팩 결과를 보이므로,
   * 컨텍스트 스트립이 `scenario` 를 읽으면 **활성 시나리오를 잘못 적는다**.
   */
  scenarioPackId: string;
  setScenarioPackId: (id: string) => void;
  /**
   * 되돌린 런이 **기록 당시** 쓴 팩 해시 (Phase 10b). 런을 열지 않았으면 null.
   * 지금 팩의 해시와 다르면 그 사이 충격 정의가 바뀐 것이다 — 조용히 현재 값을 보여주면
   * 사용자는 재현됐다고 믿는다(7c 가 룰셋 버전에 대해 세운 규칙과 같다).
   */
  runPackHash: string | null;
  // ── 타이밍(카나리·마켓타이밍) ──
  timingCfg: TimingConfig;
  setTimingCfg: (next: TimingConfig) => void;
  timingQ: UseQueryResult<TimingResult | null>;
  /**
   * 타이밍 **권고 배분으로 교체** — 파괴적이다(전략 비중이 사라진다).
   * ★스펙 §8 이 금지하는 것은 *조용한* 덮어쓰기다★ 이 동작은 사용자가 명시적으로 누르고,
   * 화면이 "무엇을 교체하는지" 를 먼저 보여준다. 그래서 남긴다 — 위험-오프일 때 권고 배분은
   * 방어자산(IEF/SHY)으로 **교체**하는 것이라, 노출 배율로는 재현할 수 없는 능력이다.
   */
  applyTiming: () => void;
  /**
   * 비파괴 타이밍 오버레이 (스펙 §8, Phase 10c). 전략 비중은 **그대로 두고** 노출만 줄인다.
   * Optimize 가 이것을 명시적 입력으로 받아 before/after 를 보여준다.
   */
  timingOverlay: { exposure: number; source: "canary" } | null;
  applyTimingOverlay: () => void;
  clearTimingOverlay: () => void;
  timeline: TimelineEvent[];
  logEvent: (msg: string) => void;
  canRun: boolean;
  pending: boolean;
  lastRun: string;
  analyzeError: string | null;
  runAnalyze: (over?: { model?: AllocationModel; tau?: number; views?: AllocationViewInput[] }) => void;
  xrayQ: UseQueryResult<XrayResult | null>;
  stressQ: UseQueryResult<StressResult | null>;
  saveStudyFull: (name: string, fields: Partial<Pick<AllocationStudy,
    "note" | "macro_view" | "changed" | "reason">>) => void;
  loadStudy: (s: AllocationStudy) => void;
  /**
   * 기록된 ResearchRun 을 위저드로 되돌린다 (Phase 4c).
   * inputs 로 입력을 복원하고 런의 스냅샷을 다시 붙인다 — 그래야 "그때의 맥락"이 함께 온다.
   * 성공 시 true. 런을 못 읽으면 false(조용히 성공한 척하지 않는다).
   */
  reopenRun: (runId: string) => Promise<boolean>;
  studiesVersion: number;
  bumpStudies: () => void;
  // ── 매크로 전략 로드 (매크로 탭 자산배분 전략 → AAS) ──
  loadedStrategy: LoadedStrategy | null;
  loadStrategy: (strat: TacticalStrategy, market: "kr" | "us") => void;
  clearLoadedStrategy: () => void;
  // ── ResearchRun (P1 재현성) ──
  // 활성 스터디 신원 (스펙 §4 ① — 지금까지 loadStudy 는 이름을 타임라인에만 남겼다)
  activeStudy: { id: string; name: string } | null;

  // ── Macro Phase 스냅샷 (Phase 3b) ──
  // ★ID 만 들고 있는다★ — 스냅샷 본문은 서버가 소유하고 react-query 가 캐시한다.
  // 브라우저 상태에 본문을 복사해 두면 새로고침·공유 시 재현이 깨진다(스펙 금지사항).
  attachedSnapshotId: string | null;
  attachSnapshot: (id: string) => void;
  detachSnapshot: () => void;

  /**
   * 분석에 쓰인 타이밍 룰셋의 신원 — 스냅샷과 같은 취급을 받는다(둘 다 재현 좌표다).
   * 버전이 없으면 어떤 룰이었는지 나중에 알 수 없으므로 id 만으로는 부족하다.
   */
  activeRuleSet: { id: string; version: number | null } | null;
  setActiveRuleSet: (r: { id: string; version: number | null } | null) => void;

  activeRunId: string | null;
  recordRun: (name: string) => Promise<string | null>;   // 현재 결과를 런으로 기록
  runsVersion: number;                                    // 목록 갱신 신호
  // ── Alpha Lab (P2) ──
  alphaTouched: boolean;                                  // 검증/저장 1회 이상 → 스테이지 완료
  markAlphaTouched: () => void;
  // ── Execution Readiness (P4) ──
  executionTouched: boolean;                              // 계획 미리보기 1회 이상 → 스테이지 완료
  markExecutionTouched: () => void;
  // ── 제약 최적화 (P3) ──
  constraints: ConstraintsInput | null;                   // null = 무제약(기존 동작)
  setConstraints: (c: ConstraintsInput | null) => void;
  // ── 위저드 확장 ──
  goal: AllocationGoal | null;
  setGoal: (g: AllocationGoal | null) => void;
  lastPos: string | null;                 // 마지막 방문 스테이지 href (Resume용)
  noteVisit: (href: string) => void;      // layout이 pathname 변경 시 호출
  stageComplete: Record<StageHref, boolean>;  // href 별 완료 (단일 소스) — 인덱스 아님
  isResultStale: boolean;                 // freshness.kind !== "fresh" 의 파생 별칭(기존 소비자용)
  /** ★결과 신선도 — missing(숫자 없음)과 superseded(숫자 있고 낡음)를 구분한다★ (A1e)
   *  배너·스테퍼가 "뭔가 바뀜"이 아니라 무엇이 바뀌었는지 말할 수 있게 changed 를 싣는다. */
  freshness: ResultFreshness;
  ensureFreshRun: () => void;             // 다음 단계 진입 시 stale이면 재최적화
}

const Ctx = createContext<AllocationCtx | null>(null);

export function useAllocation(): AllocationCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAllocation must be used within AllocationProvider");
  return v;
}

function AllocationComposition({ children }: { children: React.ReactNode }) {
  // ★기반 슬라이스를 읽는다★ 이 슬라이스의 상태는 여기서 선언되지 않는다 — 조립 계층은
  // 날것의 상태를 **합성**할 뿐이고, 소유는 `PortfolioProvider` 다.
  const {
    holdings, setHoldings, holdingsMap, holdingsKey,
    views, setViews, model, setModel, delta, setDelta, tau, setTau,
    constraints, setConstraints, hydrated,
  } = usePortfolio();
  const {
    timingCfg, setTimingCfg, timingQ,
    timingOverlay, setTimingOverlay,
    activeRuleSet, persistActiveRuleSet,
  } = useTiming();
  const {
    scenario, setScenario, scenarioPackId, setScenarioPackId, runPackHash, setRunPackHash,
    bump, setBump, severity, setSeverity, scenarios, stressQ,
  } = useScenario();
  const {
    result, setResult, lastRun, markRunNow, pending, analyzeError, mutateAnalyze,
    lastReqRef, xrayQ, activeRunId, setActiveRunId, runsVersion, bumpRuns,
    activeStudy, setActiveStudy, studiesVersion, bumpStudies,
  } = useRun();

  // ── 조립 계층이 직접 소유하는 상태 ──
  // 어느 슬라이스에도 속하지 않거나(타임라인·위저드), 슬라이스 하나로 좁히면 오히려
  // 서로를 참조하게 되는 것들이다. 나누는 것이 목적이 아니라 경계가 성립하는 것이 목적이다.
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [goal, setGoalState] = useState<AllocationGoal | null>(null);
  const [loadedStrategy, setLoadedStrategy] = useState<LoadedStrategy | null>(null);
  const [attachedSnapshotId, setAttachedSnapshotId] = useState<string | null>(null);
  const [alphaTouched, setAlphaTouched] = useState(false);
  const [executionTouched, setExecutionTouched] = useState(false);
  const [lastPos, setLastPos] = useState<string | null>(null);

  const logEvent = (msg: string) =>
    setTimeline((l) => [{ t: new Date().toTimeString().slice(0, 5), msg }, ...l].slice(0, 40));


  // ── sessionStorage 하이드레이트 (마운트 1회, 클라이언트 전용 — SSR 불일치 회피) ──
  useEffect(() => {
    // `hydrated` 는 더 이상 여기서 세우지 않는다 — 기반 슬라이스가 자기 복원을 마치고 올린다.
    if (typeof window === "undefined") return;
    try {
      const g = sessionStorage.getItem(SS_GOAL);
      if (g) setGoalState(JSON.parse(g));
      // 붙여 둔 스냅샷 ID 복원 — 본문이 아니라 ID 뿐이라 서버가 여전히 진실이다.
      const snap = sessionStorage.getItem(SS_SNAP);
      if (snap) setAttachedSnapshotId(snap);
      const p = sessionStorage.getItem(SS_POS);
      // Only restore a Resume target that is still a real route (stale/renamed → drop it,
      // never resurface a dead URL that would 404).
      if (p && isKnownAllocationRoute(p)) setLastPos(p);
      else if (p) sessionStorage.removeItem(SS_POS);
      const w = sessionStorage.getItem(SS_WIP);
      if (w) {
        const wip = JSON.parse(w);
        // holdings·views·model·delta·tau·constraints 는 PortfolioProvider 가, timingCfg·
        // timingOverlay 는 TimingProvider 가 같은 블롭에서 자기 몫으로 복원한다 — 여기서
        // 또 세팅하면 같은 값을 두 번 쓰게 된다. 남는 건 어느 슬라이스도 갖지 않는 이것뿐.
        if (wip.loadedStrategy && typeof wip.loadedStrategy === "object") setLoadedStrategy(wip.loadedStrategy);
      }
    } catch { /* 파싱 실패는 무시 — 빈 상태로 시작 */ }
  }, []);

  // ── 작업셋 persist (하이드레이트 이후에만 — 하이드레이트 전 빈 상태로 덮어쓰기 방지) ──
  // ★쓰기는 여기 한 곳뿐이다★ 슬라이스마다 같은 키에 쓰면 서로를 덮어쓴다. `hydrated` 는
  // **가장 바깥** 슬라이스가 올리는데, React 는 자식 이펙트를 먼저 돌리므로 이 플래그가
  // 서는 시점에는 모든 슬라이스의 복원이 이미 끝나 있다 — 순서가 우연이 아니라 보장이다.
  useEffect(() => {
    if (!hydrated || typeof window === "undefined") return;
    try { sessionStorage.setItem(SS_WIP, JSON.stringify({ holdings, views, model, delta, tau, timingCfg, loadedStrategy, constraints, timingOverlay })); }
    catch { /* 용량 초과 등 무시 */ }
  }, [hydrated, holdings, views, model, delta, tau, timingCfg, loadedStrategy, constraints, timingOverlay]);

  // ── 종목명 해소 (초기 구성 시 코드 대신 이름 표시 — 게이트 시드/관심그룹/직접코드 공통) ──
  //   이름이 코드 그대로인 홀딩만 배치 해소 → 이름만 패치(비중·키 불변 → 재분석 없음).
  const resolvedNamesRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    const pend = holdings
      .filter((h) => h.name === h.code || /^\d{6}$/.test(h.name))
      .map((h) => h.code)
      .filter((c) => c && !resolvedNamesRef.current.has(c));
    if (!pend.length) return;
    pend.forEach((c) => resolvedNamesRef.current.add(c));
    allocationApi.resolveNames(pend).then((labels) => {
      setHoldings((prev) => {
        let changed = false;
        const next = prev.map((h) => {
          const nm = labels[h.code];
          if (nm && nm !== h.code && nm !== h.name) { changed = true; return { ...h, name: nm }; }
          return h;
        });
        return changed ? next : prev;
      });
    }).catch(() => { /* 해소 실패는 코드 폴백 유지 */ });
    // `setHoldings` 는 컨텍스트를 건너온 `useState` 세터라 실제로는 불변이지만, lint 는
    // 그걸 알 수 없다 — 넣어 두는 편이 정직하고 재실행도 늘지 않는다.
  }, [holdings, setHoldings]);

  const canRun = holdings.length >= 2;

  // ★서명은 요청에서 파생된다 — 손으로 두 번 적지 않는다★ (A1c)
  // 예전에는 여기에 stale 판정용 리터럴과 runAnalyze 의 req 리터럴이 따로 있었고, 주석이
  // "동일해야 한다"고 부탁하고 있었다. 부탁은 강제가 아니라서 이미 두 곳이 어긋나 있었다
  // (constraints 의 null/undefined, over 오버라이드 미반영). 이제 요청을 만드는 함수가
  // 하나뿐이고 서명은 그 결과에서 뽑으므로 어긋날 자리가 없다. λ 의 조건부 포함 규칙과
  // 그 근거(엔진 실측)는 analyzeSignature.ts 에 있다.
  const sigInputs = useMemo(() => ({
    tickers: holdings.map((h) => h.code),
    weights: holdingsMap,
    views, model, delta, tau, constraints,
  }), [holdings, holdingsMap, views, model, delta, tau, constraints]);

  const currentReq = useMemo(() => buildAnalyzeRequest(sigInputs), [sigInputs]);
  // ★여기는 useMemo 를 쓰지 않는다★
  // 비교 대상인 `lastReqRef` 는 ref 라서 반응형이 아니다. memo 로 감싸면 의존성 배열에
  // 적을 수 있는 것이 없고, 억지로 `pending` 같은 값을 넣어 재계산을 유도하게 된다 —
  // 그건 의존성이 아니라 렌더 트리거이고, lint 가 정확히 그렇게 지적한다.
  // 매 렌더 계산하는 편이 정직하고 싸다(작은 객체 하나의 stringify + 문자열 비교).
  const freshness: ResultFreshness = freshnessOf(!!result, lastReqRef.current, currentReq);
  /** 기존 소비자 6곳이 계속 쓰는 파생 별칭 — 의미는 "fresh 가 아니다". */
  const isResultStale = freshness.kind !== "fresh";

  const runAnalyze = (over?: { model?: AllocationModel; tau?: number; views?: AllocationViewInput[] }) => {
    if (!canRun || pending) return;
    const req = buildAnalyzeRequest(sigInputs, over);
    const key = signatureOf(req);
    if (key === lastReqRef.current) return; // 동일 요청 중복 방지
    lastReqRef.current = key;
    mutateAnalyze(req);
    logEvent(`재최적화 — ${req.model.toUpperCase()} · λ ${delta.toFixed(1)} · τ ${req.tau} · 뷰 ${req.views.length}개`);
  };

  // 다음 단계 진입(특히 VALIDATION) 시 결과가 낡았으면 자동 재최적화 (dedupe라 무해)
  const ensureFreshRun = () => { if (canRun && !pending && isResultStale) runAnalyze(); };

  const pickScenario = (id: string) => {
    setScenario(id);
    // `/stress` 로 실행되는 팩을 골랐다면 활성 팩도 같은 것이다. 국내팩은 다른 엔진이라
    // 스트레스 화면이 `setScenarioPackId` 를 직접 부른다(여기서 알 수 없다).
    setScenarioPackId(id);
    const label = scenarios.find((x) => x.id === id)?.label || id;
    logEvent(`시나리오 전환 — ${label}`);
  };

  const setHoldingsReset = (next: Holding[]) => {
    setHoldings(next);
    setResult(null);
    lastReqRef.current = "";
    setLoadedStrategy(null);   // 수동 편집·타 소스 로드는 매크로 전략 출처를 해제
  };

  // 매크로 탭 자산배분 전략 → AAS 포트폴리오. 원 전략 비중을 마커에 보존(비교 기준선).
  const loadStrategy = (strat: TacticalStrategy, market: "kr" | "us") => {
    const hold: Holding[] = (strat.holdings || [])
      .filter((h) => h.weight > 0)
      .map((h) => ({ code: h.ticker, name: h.label || h.ticker, weight: h.weight }));
    setHoldingsReset(hold);   // 마커 초기화 후
    setLoadedStrategy({       // 이 전략으로 재설정
      id: strat.id, name: strat.name, family: strat.family ?? "momentum", market,
      signal: strat.signal, weights: Object.fromEntries(hold.map((h) => [h.code, h.weight])),
    });
    logEvent(`매크로 전략 불러오기 — ${strat.name} (${strat.holdings?.length ?? 0}자산)`);
  };
  const clearLoadedStrategy = () => setLoadedStrategy(null);

  // ── ResearchRun 기록 — 서버측 opt-in 경로: analyze를 record_run=true로 재실행해
  //    서버가 계산한 결과를 서버가 스탬프(inputs/outputs 정합 + code_version 보존).
  //    스터디(localStorage 초안)와 별개의, DB 영속 재현성 단위.
  const recordRun = async (name: string): Promise<string | null> => {
    if (!canRun) return null;
    try {
      const data = await allocationApi.analyze({
        tickers: holdings.map((h) => h.code),
        weights: holdingsMap,
        views: views.filter((v) => v.assets.length > 0 && v.magnitude_pct > 0),
        model, delta, tau,
        constraints: constraints ?? undefined,
        record_run: true, run_name: name.trim() || undefined,
        // ★런이 "어떤 국면 아래에서 내린 결정인지"를 서버에 함께 남긴다★
        //   이게 없으면 나중에 런을 다시 열어도 맥락을 복원할 수 없다.
        regime_snapshot_id: attachedSnapshotId ?? undefined,
        // 스냅샷과 나란히 — 런의 snapshot 에 함께 박혀야 재열기 때 같은 룰로 돌아온다.
        timing_rule_set_id: activeRuleSet?.id ?? undefined,
        timing_rule_set_version: activeRuleSet?.version ?? undefined,
        // 검증에 쓴 시나리오 팩 — 해시는 보내지 않는다(서버가 스탬프한다).
        scenario_pack_id: scenarioPackId || undefined,
      });
      if (data.error) return null;
      setResult(data);
      markRunNow();
      const rid = data.run_id ?? null;
      if (rid) {
        setActiveRunId(rid);
        bumpRuns();
        logEvent(`런 기록 — ${name.trim() || rid} (${model.toUpperCase()})`);
      } else {
        logEvent("런 기록 실패 — DB 미가용");
      }
      return rid;
    } catch {
      logEvent("런 기록 실패 — 네트워크 오류");
      return null;
    }
  };

  const applyTiming = () => {
    const data = timingQ.data;
    if (!data || data.error || !data.holdings?.length) return;
    setHoldingsReset(data.holdings
      .filter((h) => h.weight > 0)
      .map((h) => ({ code: h.code, name: h.label || h.code, weight: h.weight })));
    logEvent(`타이밍 권고 배분으로 **교체** — ${data.canary.signal === "risk_on" ? "위험-온" : "위험-오프"}`);
  };

  /**
   * 타이밍 판정을 **노출 배율**로만 받아 둔다 — 보유 종목은 손대지 않는다.
   *
   * 노출 = 1 − 현금비중. 타이밍이 위험-오프면 권고 배분의 현금이 커지므로 노출이 내려간다.
   * ★1 을 넘길 수 없다★ 오버레이가 노출을 **키울 수** 있으면 "리스크 관리" 가 조용히
   * 레버리지가 된다 — `macro_overlay.combine()` 이 매크로 쪽에서 지키는 것과 같은 일방향 규칙.
   */
  const applyTimingOverlay = () => {
    const data = timingQ.data;
    if (!data || data.error) return;
    const cash = Number(data.cash_pct ?? 0);
    const exposure = Math.max(0, Math.min(1, 1 - (Number.isFinite(cash) ? cash : 0) / 100));
    setTimingOverlay({ exposure, source: "canary" });
    logEvent(`타이밍 오버레이 적용 — 노출 ${(exposure * 100).toFixed(0)}% (전략 비중 유지)`);
  };

  const clearTimingOverlay = () => {
    setTimingOverlay(null);
    logEvent("타이밍 오버레이 해제");
  };

  const setViewsLogged = (next: AllocationViewInput[]) => {
    if (next.length > views.length) logEvent("테제(뷰) 추가");
    else if (next.length < views.length) logEvent("테제(뷰) 삭제");
    setViews(next);
  };

  const loadStudy = (s: AllocationStudy) => {
    setHoldings(Object.entries(s.holdings).map(([code, weight]) => ({
      code, weight, name: s.names?.[code] || result?.labels?.[code] || code,
    })));
    setViews(s.views || []);
    setModel(s.model);
    setDelta(s.delta);
    setTau(s.tau);
    setResult(null);
    lastReqRef.current = "";
    setLoadedStrategy(null);
    setActiveStudy({ id: s.id, name: s.name });
    logEvent(`스터디 로드 — ${s.name}`);
  };

  // ── 런 되돌리기 ──────────────────────────────────────────────────────────────
  // 지금까지 ResearchRunsPanel 은 기록·비교·삭제만 했고 **되돌리는 경로가 없었다**.
  // 재현성은 "저장했다"가 아니라 "다시 열어서 같은 것을 본다"로 증명된다.
  const reopenRun = async (runId: string): Promise<boolean> => {
    let run: Awaited<ReturnType<typeof researchApi.get>> | null = null;
    try {
      run = await researchApi.get(runId);
    } catch {
      run = null;
    }
    if (!run) {
      logEvent(`런 되돌리기 실패 — ${runId} 를 읽을 수 없습니다`);
      return false;
    }
    const inp = (run.inputs ?? {}) as {
      tickers?: string[]; weights?: Record<string, number>;
      views?: AllocationViewInput[]; model?: AllocationModel;
      delta?: number; tau?: number; constraints?: ConstraintsInput | null;
      regime_snapshot_id?: string | null;
      timing_rule_set_id?: string | null;
      timing_rule_set_version?: number | null;
      scenario_pack_id?: string | null;
    };

    // 비중은 inputs.weights 우선, 없으면 균등(티커만 남은 옛 런) — 0 으로 채우지 않는다.
    const labels = (run.outputs?.labels ?? {}) as Record<string, string>;
    const codes = inp.tickers ?? Object.keys(inp.weights ?? {});
    const even = codes.length ? 100 / codes.length : 0;
    setHoldingsReset(codes.map((code) => ({
      code, name: labels[code] || code,
      weight: inp.weights?.[code] ?? even,
    })));

    setViews(inp.views ?? []);
    if (inp.model) setModel(inp.model);
    if (typeof inp.delta === "number") setDelta(inp.delta);
    if (typeof inp.tau === "number") setTau(inp.tau);
    setConstraints(inp.constraints ?? null);
    setLoadedStrategy(null);

    // 결과는 비운다 — 복원된 입력에 대해 아직 계산하지 않았으므로 stale 이 정직한 상태다.
    setResult(null);
    lastReqRef.current = "";

    // ★런의 스냅샷을 다시 붙인다★ — 링크가 없으면 맥락 없이 입력만 돌아온 것이다.
    const sid = inp.regime_snapshot_id
      ?? ((run.snapshot as { regime_snapshot_id?: string | null })?.regime_snapshot_id ?? null);
    if (sid) attachSnapshot(sid);
    else detachSnapshot();

    // ★룰셋도 같은 방식으로 되돌린다★ inputs 우선, 없으면 snapshot 에 박힌 값.
    const snapObj = (run.snapshot ?? {}) as {
      timing_rule_set_id?: string | null; timing_rule_set_version?: number | null;
      scenario_pack_id?: string | null; scenario_pack_hash?: string | null };
    const rsId = inp.timing_rule_set_id ?? snapObj.timing_rule_set_id ?? null;
    const rsVer = inp.timing_rule_set_version ?? snapObj.timing_rule_set_version ?? null;
    setActiveRuleSet(rsId ? { id: rsId, version: rsVer } : null);

    // ★시나리오 팩은 id 와 **그때의 해시**를 함께 되돌린다★ (Phase 10b)
    //   id 만 복원하면 계수가 바뀐 뒤에도 같은 팩으로 보인다 — 컨텍스트 스트립이 두 값을
    //   대조해 "그때와 다른 팩" 이라고 말할 수 있어야 하고, 그 판단은 여기서 하지 않는다.
    const spId = inp.scenario_pack_id ?? snapObj.scenario_pack_id ?? null;
    setScenarioPackId(spId ?? "");
    setRunPackHash(snapObj.scenario_pack_hash ?? null);

    setActiveRunId(run.run_id);
    logEvent(`런 되돌리기 — ${run.name || run.run_id}${sid ? ` (국면 ${sid})` : " (국면 링크 없음)"}`);
    return true;
  };

  const saveStudyFull: AllocationCtx["saveStudyFull"] = (name, fields) => {
    const names: Record<string, string> = {};
    holdings.forEach((h) => { names[h.code] = h.name; });
    const pf = result?.summary?.portfolio;
    const topW = result
      ? Object.entries(result.weights.optimized).sort((a, b) => b[1] - a[1]).slice(0, 3)
          .map(([c, w]) => `${result.labels[c] || c} ${w.toFixed(1)}%`).join(" · ")
      : "";
    const result_summary = pf
      ? `기대수익 ${pf.expected_return_pct}% · 변동성 ${pf.volatility_pct}% · Sharpe ${pf.sharpe}${topW ? ` | ${topW}` : ""}`
      : undefined;
    const saved = saveStudy(name, {
      holdings: holdingsMap, names, views, model, delta, tau,
      result_summary, ...fields,
    });
    // 저장 직후가 곧 "이 스터디 안에 있다" — saveStudy 가 돌려주는 신원을 쓴다(새로 만들지 않는다).
    setActiveStudy({ id: saved.id, name: saved.name });
    logEvent(`스터디 저장 — ${name.trim() || "이름 없음"}`);
    bumpStudies();
  };

  // ── 위저드 상태 ──
  const setGoal = (g: AllocationGoal | null) => {
    setGoalState(g);
    try {
      if (typeof window !== "undefined") {
        if (g) sessionStorage.setItem(SS_GOAL, JSON.stringify(g));
        else sessionStorage.removeItem(SS_GOAL);
      }
    } catch { /* ignore */ }
  };
  const attachSnapshot = (id: string) => {
    setAttachedSnapshotId(id);
    try { if (typeof window !== "undefined") sessionStorage.setItem(SS_SNAP, id); } catch { /* ignore */ }
    logEvent(`매크로 국면 스냅샷 연결 — ${id}`);
  };
  // 상태+저장은 슬라이스가, 타임라인 기록은 여기가 — 로그가 슬라이스로 내려가면 슬라이스가
  // 서로를 알게 된다.
  const setActiveRuleSet = (r: { id: string; version: number | null } | null) => {
    persistActiveRuleSet(r);
    logEvent(r
      ? `타이밍 룰셋 연결 — ${r.id}${r.version != null ? ` v${r.version}` : " (버전 미상)"}`
      : "타이밍 룰셋 해제");
  };
  const detachSnapshot = () => {
    setAttachedSnapshotId(null);
    try { if (typeof window !== "undefined") sessionStorage.removeItem(SS_SNAP); } catch { /* ignore */ }
    logEvent("매크로 국면 스냅샷 해제");
  };

  const noteVisit = (href: string) => {
    if (!isKnownAllocationRoute(href)) return;   // never record a route we can't route back to
    setLastPos(href);
    try { if (typeof window !== "undefined") sessionStorage.setItem(SS_POS, href); } catch { /* ignore */ }
  };

  // href 키 — 스테이지를 추가하면 이 Record 에 항목이 빠졌다고 tsc 가 잡아 준다.
  const stageComplete = useMemo<Record<StageHref, boolean>>(() => ({
    "/allocation/overview":  !!result,
    "/allocation/macro":     !!attachedSnapshotId,
    "/allocation/construct": holdings.length >= 2,
    "/allocation/alphalab":  alphaTouched,
    "/allocation/thesis":    views.length > 0,
    "/allocation/timing":    !!timingQ.data && !timingQ.data.error,
    "/allocation/optimize":  !!result,
    "/allocation/stress":    !!result,
    "/allocation/explain":   !!result,
    "/allocation/execution": executionTouched,
    "/allocation/journal":   timeline.some((e) => e.msg.startsWith("스터디 저장") || e.msg.startsWith("런 기록")),
  }), [result, holdings.length, views.length, timeline, timingQ.data, alphaTouched, executionTouched, attachedSnapshotId]);

  const value: AllocationCtx = {
    holdings, setHoldingsReset, holdingsMap, holdingsKey,
    views, setViewsLogged,
    model, setModel, delta, setDelta, tau, setTau,
    result, scenario, bump, setBump, severity, setSeverity, pickScenario, scenarios,
    scenarioPackId, setScenarioPackId, runPackHash,
    timingCfg, setTimingCfg, timingQ, applyTiming,
    timingOverlay, applyTimingOverlay, clearTimingOverlay,
    timeline, logEvent,
    canRun, pending, lastRun, analyzeError,
    runAnalyze, xrayQ, stressQ,
    saveStudyFull, loadStudy, reopenRun, studiesVersion, bumpStudies,
    loadedStrategy, loadStrategy, clearLoadedStrategy,
    activeStudy, attachedSnapshotId, attachSnapshot, detachSnapshot,
    activeRuleSet, setActiveRuleSet,
    activeRunId, recordRun, runsVersion,
    alphaTouched, markAlphaTouched: () => setAlphaTouched(true),
    executionTouched, markExecutionTouched: () => setExecutionTouched(true),
    constraints, setConstraints,
    goal, setGoal, lastPos, noteVisit, stageComplete, isResultStale, freshness, ensureFreshRun,
  };

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

/**
 * 조립 — 기반 슬라이스를 바깥에 두고 그 안에서 나머지를 합성한다.
 *
 * ★중첩 순서는 취향이 아니라 의존이다★ 타이밍·시나리오·런 슬라이스가 전부 보유 종목을
 * 읽으므로 `PortfolioProvider` 가 가장 바깥이어야 한다. 형제로 두면 보유를 prop 으로
 * 흘려보내야 하고, 그건 컨텍스트를 쓰는 이유를 지운다.
 *
 * 부수 효과 하나가 공짜로 따라온다 — React 는 자식 이펙트를 먼저 돌리므로, 가장 바깥이
 * 올리는 `hydrated` 가 서는 시점에는 모든 슬라이스의 sessionStorage 복원이 끝나 있다.
 * 작업셋 저장이 빈 상태를 덮어쓸 수 없는 이유가 타이머가 아니라 트리 구조다.
 *
 * ★`children` 을 그대로 통과시킨다★ 그래야 기반 상태가 바뀌어도 React 가 자식 서브트리를
 * 재조정하지 않는다(엘리먼트 동일성 유지). 소비자가 `useAllocation()` 으로 **전부** 구독하는
 * 동안에는 렌더 절감이 체감되지 않는다 — 그건 소비자가 좁은 슬라이스로 옮길 때의 이득이고,
 * 이 커밋의 범위가 아니다. 여기서 얻는 것은 구조다.
 */
export function AllocationProvider({ children }: { children: React.ReactNode }) {
  return (
    <PortfolioProvider>
      <TimingProvider>
        <ScenarioProvider>
          <RunProvider>
            <AllocationComposition>{children}</AllocationComposition>
          </RunProvider>
        </ScenarioProvider>
      </TimingProvider>
    </PortfolioProvider>
  );
}
