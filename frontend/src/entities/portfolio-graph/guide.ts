/**
 * 길잡이(AI5) — 캔버스의 도구를 쓰게 이끄는 코치(스펙 §AI5 · 사용자 결정 2026-10-23: 규칙 줄 + 누르면 AI). ★도구 안내만 — 투자 판단은 말하지 않는다★.
 * ==========================================================================
 * - `GUIDE_TOOLS` — 도구 id·이름(서버 `src/services/canvas_assist/guide.py` 의 `FEATURES` 와 같은 id·이름·순서 — 패리티 테스트) +
 *   적용 조건(화면 상태로) + ★다음엔 어디서 하나★(도구를 쓰게 이끄는 것이 길잡이의 일이다 — [해 보기] 뒤 안내 줄에 붙는다).
 * - 순서 = 규칙 우선순위: 고칠 것(원인·전달 점검) → 계산 → 정리 → 비교(갈래·전략·견고성) → AI 읽기 → 기록 → 보기.
 * - `guideState` 는 서버로도 간다(AI 길잡이) — 수·참거짓만, 설정값·종목 없음. 막힌 관문은 서버 `GATES` 키만.
 */

export type GuideId = "cause" | "wire_check" | "run" | "layout" | "branch" | "strategy_add" | "compare" | "story_ai" | "ask_ai"
  | "records" | "lanes" | "minimap";

/** 화면이 센 지금 상태 — 서버 `GuideState` 와 같은 칸(더하면 422). */
export interface GuideState {
  computed: boolean;
  /** 계산 결과가 지금 그래프의 것인가(낡은 노드 없음). */
  fresh: boolean;
  /** 절차를 다 채웠고 설정 오류가 없다 — 계산할 수 있다. */
  ready_to_run: boolean;
  nodes: number;
  failed: number;
  wire_issues: number;
  weight_nodes: number;
  branches: number;
  robustness: boolean;
  overlapping: boolean;
  lanes: boolean;
  minimap: boolean;
  backtest: boolean;
  gates_blocked: string[];
}

export interface GuideTool {
  id: GuideId;
  label: string;
  applies: (s: GuideState) => boolean;
  /** 규칙 길잡이의 '왜' 한 줄 — 상태의 수만 쓴다. */
  why: (s: GuideState) => string;
  /** [해 보기] 뒤에 붙는 '다음엔 어디서' — 길잡이는 도구가 어디 있는지 가르친다. */
  where: string;
}

export const GUIDE_TOOLS: GuideTool[] = [
  { id: "cause", label: "원인 따라가기", applies: (s) => s.computed && s.failed > 0,
    why: (s) => `실패하거나 막힌 노드가 ${s.failed}개입니다 — 최초 실패 지점부터 원인 경로를 확인할 수 있습니다`,
    where: "다음엔 실패한 노드를 오른쪽 클릭 → ‘원인 따라가기’로도 됩니다" },
  { id: "wire_check", label: "전달 점검 보기", applies: (s) => s.computed && s.wire_issues > 0,
    why: (s) => `누락·변경이 있는 선이 ${s.wire_issues}개입니다 — 누락 항목을 확인할 수 있습니다`,
    where: "이후에는 선을 눌러 오른쪽 창 ‘선’ 탭에서 확인합니다" },
  { id: "run", label: "계산하기", applies: (s) => !s.computed && s.ready_to_run,
    why: () => "절차를 다 채웠습니다 — 계산하면 노드마다 결과와 설명이 나옵니다",
    where: "다음엔 Ctrl+Enter 로도 계산합니다" },
  { id: "layout", label: "자동 정리", applies: (s) => s.overlapping,
    why: () => "카드가 겹쳐 있습니다 — 흐름 순서대로 다시 놓을 수 있습니다",
    where: "다음엔 Ctrl+K ‘자동 정리’로도 됩니다" },
  { id: "branch", label: "대안 만들기", applies: (s) => s.computed && s.branches === 0 && s.weight_nodes > 0,
    why: () => "설정을 바꾼 설계를 비교할 수 있습니다",
    where: "이후에는 노드를 선택하고 Ctrl+K ‘대안’으로도 실행할 수 있습니다" },
  { id: "strategy_add", label: "전략 더하기", applies: (s) => s.weight_nodes === 1,
    why: () => "비중 산출 방식이 하나입니다 — 다른 방식을 추가해 비교할 수 있습니다",
    where: "다음엔 도구 막대 [전략 추가]로도 됩니다" },
  { id: "compare", label: "견고성 비교", applies: (s) => s.weight_nodes >= 2 && !s.robustness,
    why: (s) => `비중 노드가 ${s.weight_nodes}개입니다 — 위기 시 동반 하락 여부를 분석할 수 있습니다`,
    where: "이후에는 비중 노드 여러 개를 선택하고 Ctrl+K ‘견고성 비교’로도 실행할 수 있습니다" },
  { id: "story_ai", label: "AI 로 풀어 쓰기", applies: (s) => s.computed && s.fresh,
    why: () => "계산 결과를 읽는 순서대로 정리한 AI 해설을 받을 수 있습니다",
    where: "다음엔 오른쪽 창 ‘이야기’ 탭 맨 위에서 합니다" },
  { id: "ask_ai", label: "노드에게 묻기", applies: (s) => s.computed,
    why: () => "노드를 선택하면 해당 계산 결과에 대해 질의할 수 있습니다",
    where: "이후에는 노드를 선택하면 오른쪽 창 하단에서 질의합니다" },
  { id: "records", label: "기록함", applies: (s) => s.backtest,
    why: () => "백테스트 기록을 모아 확인할 수 있습니다",
    where: "다음엔 도구 막대 [기록함]으로 엽니다" },
  { id: "lanes", label: "단계 레인", applies: (s) => !s.lanes && s.nodes >= 6,
    why: (s) => `노드가 ${s.nodes}개입니다 — 단계별 세로 띠로 표시할 수 있습니다`,
    where: "다음엔 ‘보기’ 메뉴 → 단계 레인 보기로도 됩니다" },
  { id: "minimap", label: "미니맵", applies: (s) => !s.minimap && s.nodes >= 8,
    why: (s) => `노드가 ${s.nodes}개입니다 — 전체를 미니맵으로 확인할 수 있습니다`,
    where: "다음엔 도구 막대의 지도 단추로 킵니다" },
];

export const toolOf = (id: string) => GUIDE_TOOLS.find((t) => t.id === id) ?? null;

/** 지금 적용되는 도구 — 우선순위 순. */
export function applicableTools(s: GuideState): GuideId[] {
  return GUIDE_TOOLS.filter((t) => t.applies(s)).map((t) => t.id);
}

/** 규칙 길잡이 — 적용되고 이번 방문에 [다음에] 하지 않은 첫 도구. 없으면 null. */
export function ruleGuide(s: GuideState, dismissed: ReadonlySet<string>): GuideTool | null {
  return GUIDE_TOOLS.find((t) => t.applies(s) && !dismissed.has(t.id)) ?? null;
}
