/**
 * 목표로 시작 (BM C4 · 처음 쓰는 사람) — 무엇을 하려는지 → 종목 → 기간을 물어 이미 있는 템플릿을 조립한다.
 * ==========================================================================
 * ★규칙을 새로 정하지 않는다★ — 흐름은 기존 템플릿(또는 기업 노드 두 개)이고, 답은 그 노드들의 **기본 층 파라미터**에만 들어간다.
 * 기간 선택지는 서버 x-ui 프리셋(`returns.lookback_days`)에서 온다. 고르지 않은 칸은 서버 기본값(키를 넣지 않는다).
 */
import { GRAPH_FORMAT, GRAPH_VERSION, type GraphDoc } from "./types";
import { TEMPLATES } from "./templates";

export type GoalKey = "build" | "check" | "timing" | "company";

export interface Goal {
  key: GoalKey;
  title: string;
  sub: string;
  /** 종목을 몇 개 받나 — 기업 하나는 1. */
  tickers: "many" | "one";
  /** 기간 질문이 있나(수익률 노드가 있는 흐름만). */
  period: boolean;
  /** 위험 성향 질문이 있나(BO O1 — 비중을 새로 나누는 흐름만. 정한 비중을 점검하는 흐름에는 묻지 않는다). */
  risk: boolean;
}

export const GOALS: Goal[] = [
  { key: "build", title: "새 포트폴리오 만들기", sub: "종목을 고르면 비중을 나누고, 위험과 과거 성과를 함께 봐요.", tickers: "many", period: true, risk: true },
  { key: "check", title: "비중의 위험 점검", sub: "정한 비중이 하루에 얼마나 잃을 수 있는지, 위기 충격에서 어떤지 봐요.", tickers: "many", period: true, risk: false },
  { key: "timing", title: "타이밍 규칙 시험", sub: "타이밍 신호로 노출을 줄였을 때의 목표 비중과 주문 목록을 봐요. 주문은 나가지 않아요.", tickers: "many", period: true, risk: true },
  { key: "company", title: "기업 하나 깊게", sub: "한 기업의 적정가를 여러 모델로 보고, 가치가 어디쯤 몰려 있는지 봐요.", tickers: "one", period: false, risk: false },
];

const TEMPLATE_OF: Record<Exclude<GoalKey, "company">, string> = { build: "core", check: "risk", timing: "timing" };

/**
 * 답 → 문서. 템플릿의 유니버스 종목과 수익률 기간만 바꾼다(기간을 고르지 않았으면 그대로 — 서버 기본값).
 * 위험 성향(BO O1)을 골랐으면 비중 노드를 `mv_utility` + 그 λ 로 — 고르지 않았으면 템플릿 방식 그대로.
 */
export function goalDoc(goal: GoalKey, tickers: string[], lookbackDays: number | null,
                        riskAversion: number | null = null): GraphDoc {
  if (goal === "company") {
    const code = tickers[0];
    return {
      format: GRAPH_FORMAT, version: GRAPH_VERSION, meta: { name: "기업 하나 깊게" },
      nodes: [
        { id: "valuation", type: "company_valuation", params: { code }, position: { x: 0, y: 0 } },
        { id: "distribution", type: "valuation_distribution", params: { code }, position: { x: 0, y: 220 } },
      ],
      edges: [],
    };
  }
  const t = TEMPLATES.find((x) => x.key === TEMPLATE_OF[goal])!;
  const doc: GraphDoc = structuredClone(t.doc);
  doc.meta = { ...(doc.meta ?? {}), name: GOALS.find((g) => g.key === goal)!.title };
  for (const n of doc.nodes) {
    if (n.type === "universe") n.params = { ...n.params, tickers: [...tickers] };
    if (n.type === "returns" && lookbackDays !== null) n.params = { ...n.params, lookback_days: lookbackDays };
    if (n.type === "optimizer" && riskAversion !== null && GOALS.find((g) => g.key === goal)?.risk) {
      n.params = { ...n.params, model: "mv_utility", risk_aversion: riskAversion };
    }
  }
  return doc;
}

/** 종목 코드 글 → 목록. 6자리 숫자(국내) 또는 영문 대문자 티커만, 순서 유지·중복 제거. 나머지는 버리지 않고 따로 돌려준다. */
export function parseTickers(text: string): { tickers: string[]; rejected: string[] } {
  const parts = text.split(/[\s,，]+/).map((x) => x.trim()).filter(Boolean);
  const ok: string[] = [];
  const rejected: string[] = [];
  for (const p of parts) {
    const t = p.toUpperCase();
    if (/^\d{6}$/.test(t) || /^[A-Z][A-Z.]{0,5}$/.test(t)) { if (!ok.includes(t)) ok.push(t); } else rejected.push(p);
  }
  return { tickers: ok, rejected };
}
