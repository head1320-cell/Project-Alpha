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
    why: (s) => `실패하거나 막힌 노드가 ${s.failed}개예요 — 처음 막힌 곳부터 거슬러 볼 수 있어요`,
    where: "다음엔 실패한 노드를 오른쪽 클릭 → ‘원인 따라가기’로도 돼요" },
  { id: "wire_check", label: "전달 점검 보기", applies: (s) => s.computed && s.wire_issues > 0,
    why: (s) => `빠지거나 바뀐 것이 있는 선이 ${s.wire_issues}개예요 — 무엇이 빠졌는지 볼 수 있어요`,
    where: "다음엔 선을 눌러 오른쪽 창 ‘선’ 탭에서 봐요" },
  { id: "run", label: "계산하기", applies: (s) => !s.computed && s.ready_to_run,
    why: () => "절차를 다 채웠어요 — 계산하면 노드마다 결과와 설명이 나와요",
    where: "다음엔 Ctrl+Enter 로도 계산해요" },
  { id: "layout", label: "자동 정리", applies: (s) => s.overlapping,
    why: () => "카드가 겹쳐 있어요 — 흐름 순서대로 다시 놓을 수 있어요",
    where: "다음엔 Ctrl+K ‘자동 정리’로도 돼요" },
  { id: "branch", label: "갈래 만들기", applies: (s) => s.computed && s.branches === 0 && s.weight_nodes > 0,
    why: () => "설정을 바꾼 설계를 나란히 비교할 수 있어요",
    where: "다음엔 노드를 고르고 Ctrl+K ‘갈래’로도 돼요" },
  { id: "strategy_add", label: "전략 더하기", applies: (s) => s.weight_nodes === 1,
    why: () => "비중을 내는 방식이 하나예요 — 다른 방식을 더해 견줘 볼 수 있어요",
    where: "다음엔 도구 막대 [전략 추가]로도 돼요" },
  { id: "compare", label: "견고성 비교", applies: (s) => s.weight_nodes >= 2 && !s.robustness,
    why: (s) => `비중 노드가 ${s.weight_nodes}개예요 — 위기 때 같이 무너지는지 볼 수 있어요`,
    where: "다음엔 비중 노드 여럿을 고르고 Ctrl+K ‘견고성 비교’로도 돼요" },
  { id: "story_ai", label: "AI 로 풀어 쓰기", applies: (s) => s.computed && s.fresh,
    why: () => "계산 결과를 읽는 순서로 풀어 쓴 글을 받아 볼 수 있어요",
    where: "다음엔 오른쪽 창 ‘이야기’ 탭 맨 위에서 해요" },
  { id: "ask_ai", label: "노드에게 묻기", applies: (s) => s.computed,
    why: () => "노드를 고르면 그 계산 결과에 대해 물어볼 수 있어요",
    where: "다음엔 노드를 고르면 오른쪽 창 아래 칸에서 물어요" },
  { id: "records", label: "기록함", applies: (s) => s.backtest,
    why: () => "과거로 돌려 본 기록을 모아 볼 수 있어요",
    where: "다음엔 도구 막대 [기록함]으로 열어요" },
  { id: "lanes", label: "단계 레인", applies: (s) => !s.lanes && s.nodes >= 6,
    why: (s) => `노드가 ${s.nodes}개예요 — 어느 단계인지 세로 띠로 볼 수 있어요`,
    where: "다음엔 ‘보기’ 메뉴 → 단계 레인 보기로도 돼요" },
  { id: "minimap", label: "미니맵", applies: (s) => !s.minimap && s.nodes >= 8,
    why: (s) => `노드가 ${s.nodes}개예요 — 전체를 작은 지도로 볼 수 있어요`,
    where: "다음엔 도구 막대의 지도 단추로 켜요" },
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
