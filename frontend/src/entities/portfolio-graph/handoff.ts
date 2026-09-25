/**
 * 캔버스 → 마법사 도구 다리 — ★숫자가 아니라 입력을 넘긴다★ (BI4 · 사용자 결정)
 * ==========================================================================
 * 마법사(Stress·Timing·Execution …)는 자기 세션의 보유·뷰·모델로 `/analyze` 를 **다시**
 * 부른다. 그래서 캔버스는 최적 비중 숫자를 넘기지 않고 그 숫자를 만든 **입력**을 넘긴다 —
 * 같은 입력이면 같은 함수가 같은 수를 낸다(BI2 골든). 숫자를 넘기면 마법사 화면의 다른
 * 패널(프런티어·MC)과 서로 다른 계산이 한 화면에 섞인다.
 *
 * ★마법사 세션에 자리가 없는 설정은 넘어가지 않는다★ — 그 사실을 `notCarried` 문장으로
 * 돌려주고, 화면은 넘기기 **전에** 보여 준다(침묵 금지).
 */
import type { GraphDoc, NodeRunResult } from "./types";

/** 마법사가 `/analyze` 에 보내지 않는 칸의 서버 기본값 — 다르면 넘어가지 않는다. */
const WIZARD_DEFAULTS = { lookback_days: 756, benchmark: "KOSPI" } as const;

export interface HandoffView {
  assets: string[];
  direction: 1 | -1;
  magnitude_pct: number;
  confidence: number;
  label?: string;
}

export interface HandoffPayload {
  tickers: string[];
  labels: Record<string, string>;
  /** 현재 비중(%) — 유니버스에 없으면 균등. */
  weightsPct: Record<string, number>;
  weightsSource: "universe" | "equal";
  views: HandoffView[];
  model: string;
  delta?: number;
  tau?: number;
  constraints: Record<string, unknown> | null;
  notCarried: string[];
}

export interface HandoffResult {
  payload: HandoffPayload | null;
  /** 넘길 수 없을 때 사유. */
  reason: string | null;
}

const num = (v: unknown): number | undefined => (typeof v === "number" && Number.isFinite(v) ? v : undefined);

/** 옵티마이저 노드 하나에서 거꾸로 유니버스·수익률·추정·뷰를 찾아 입력을 모은다. */
export function buildHandoff(doc: GraphDoc, optimizerId: string,
                             results: Record<string, NodeRunResult> | null): HandoffResult {
  const byId = new Map(doc.nodes.map((n) => [n.id, n]));
  const opt = byId.get(optimizerId);
  if (!opt || opt.type !== "optimizer") return { payload: null, reason: "옵티마이저 노드가 아닙니다." };
  const res = results?.[optimizerId];
  if (!res || res.status !== "ok") {
    return { payload: null, reason: "이 옵티마이저가 현재 그래프로 성공한 실행 결과가 없습니다 — 먼저 실행하세요." };
  }
  const into = (target: string, port: string) =>
    doc.edges.find((e) => e.target === target && e.target_port === port);
  const retEdge = into(optimizerId, "returns");
  const ret = retEdge ? byId.get(retEdge.source) : undefined;
  const uniEdge = ret ? into(ret.id, "universe") : undefined;
  const uni = uniEdge ? byId.get(uniEdge.source) : undefined;
  const estEdge = into(optimizerId, "belief");
  const est = estEdge ? byId.get(estEdge.source) : undefined;
  const viewEdge = into(optimizerId, "views");
  const viewNode = viewEdge ? byId.get(viewEdge.source) : undefined;
  if (!ret || !uni) return { payload: null, reason: "옵티마이저 위쪽에서 수익률·유니버스 노드를 찾지 못했습니다." };

  const optView = (res.view ?? {}) as {
    names?: string[]; labels?: Record<string, string>; model?: string;
    params?: { delta?: number; tau?: number };
  };
  // ★유니버스가 아니라 실제로 계산에 들어간 종목★ — 수익률 노드가 제외한 종목은 넘기지 않는다.
  const tickers = optView.names ?? ((uni.params.tickers as string[] | undefined) ?? []);
  const notCarried: string[] = [];
  const declared = (uni.params.tickers as string[] | undefined) ?? [];
  const dropped = declared.filter((t) => !tickers.includes(t));
  if (dropped.length) notCarried.push(`수익률 노드가 제외한 종목 ${dropped.join(", ")} 은 넘기지 않습니다.`);

  const rawW = (uni.params.weights ?? null) as Record<string, number> | null;
  let weightsPct: Record<string, number>;
  let weightsSource: HandoffPayload["weightsSource"];
  const sum = rawW ? tickers.reduce((s, t) => s + Math.abs(num(rawW[t]) ?? 0), 0) : 0;
  if (rawW && sum > 0) {
    weightsPct = Object.fromEntries(tickers.map((t) => [t, ((num(rawW[t]) ?? 0) / sum) * 100]));
    weightsSource = "universe";
  } else {
    weightsPct = Object.fromEntries(tickers.map((t) => [t, 100 / Math.max(1, tickers.length)]));
    weightsSource = "equal";
    notCarried.push("유니버스에 현재 비중이 없어 마법사에는 균등 비중으로 넘깁니다.");
  }

  const views: HandoffView[] = [];
  for (const v of ((viewNode?.params.views as Record<string, unknown>[] | undefined) ?? [])) {
    if (Array.isArray(v.assets) && v.assets.length && !v.weights) {
      views.push({
        assets: v.assets as string[],
        direction: v.direction === -1 ? -1 : 1,
        magnitude_pct: num(v.magnitude_pct) ?? 2,
        confidence: num(v.confidence) ?? 50,
        ...(typeof v.label === "string" ? { label: v.label } : {}),
      });
    } else {
      notCarried.push("부호 있는 조합(weights) 뷰는 마법사에 자리가 없어 넘어가지 않습니다.");
    }
  }

  const lb = num(ret.params.lookback_days);
  if (lb !== undefined && lb !== WIZARD_DEFAULTS.lookback_days) {
    notCarried.push(`lookback ${lb}일 — 마법사는 ${WIZARD_DEFAULTS.lookback_days}일(서버 기본값)로 계산합니다.`);
  }
  if (ret.params.as_of) notCarried.push(`절단일 ${String(ret.params.as_of)} — 마법사는 오늘 기준으로 계산합니다.`);
  const bm = uni.params.benchmark;
  if (typeof bm === "string" && bm !== WIZARD_DEFAULTS.benchmark) {
    notCarried.push(`벤치마크 ${bm} — 마법사는 ${WIZARD_DEFAULTS.benchmark} 로 계산합니다.`);
  }
  if (est && Object.values(est.params).some((v) => v !== undefined && v !== false && v !== "hard"
      && v !== "live" && v !== "M")) {
    notCarried.push("추정 설정(조건부 μ/Σ 등)은 마법사로 넘어가지 않습니다 — 마법사는 표본 추정으로 계산합니다.");
  }
  notCarried.push("마법사는 자기 세션에 붙은 국면 스냅샷·케이스 증거·타이밍 오버레이를 함께 씁니다.");

  return {
    payload: {
      tickers,
      labels: optView.labels ?? {},
      weightsPct,
      weightsSource,
      views,
      // ★실제로 쓴 값★(결과의 model·params) — 캔버스에서 비워 둔 칸(서버 기본값)을 넘기지
      // 않으면 마법사가 자기 세션의 δ·τ 를 써서 다른 수가 나온다.
      model: String(optView.model ?? opt.params.model ?? "mvo"),
      delta: num(optView.params?.delta) ?? num(opt.params.delta),
      tau: num(optView.params?.tau) ?? num(opt.params.tau),
      constraints: (opt.params.constraints as Record<string, unknown> | undefined) ?? null,
      notCarried: [...new Set(notCarried)],
    },
    reason: null,
  };
}
