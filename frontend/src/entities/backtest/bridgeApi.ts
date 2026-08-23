// 스크리너 → 백테스터 브릿지 API.
// (src/shared/api/screenerApi.ts에서 분리 — 내용 불변)

import { API_BASE, extractErrorDetail } from "@/shared/api/apiBase";
import type {
  BacktestConditionPayload,
  ScreenToBacktestBody,
  ScreenToBacktestResult,
  TokenSupportMap,
} from "./bridgeModel";

export const backtestBridgeApi = {
// 커스텀 전략(BuilderState) 백테스트 — 빌더에서 만든 임의 전략 실행
  customBacktest: async (body: {
    universe: string; max_tickers: number;
    spec: unknown;  // BuilderState
    start_date: string; end_date: string; initial_capital: number;
  }): Promise<ScreenToBacktestResult> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/screen-to-backtest`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        universe: body.universe,
        filter_ast: { logic: "AND", conditions: [{ kind: "field", field: "per", op: "gt", value: 0 }], groups: [] },
        liquidity_floor: "standard",
        max_tickers: body.max_tickers,
        strategy_name: "__custom__",
        strategy_params: { spec: body.spec },
        start_date: body.start_date, end_date: body.end_date,
        initial_capital: body.initial_capital,
      }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      throw new Error(extractErrorDetail(err, `Custom backtest failed: ${r.status}`));
    }
    return r.json();
  },

  strategies: async (): Promise<{ strategies: Array<{ id: string; label: string }> }> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/backtest-strategies`);
    if (!r.ok) throw new Error(`Strategies failed: ${r.status}`);
    return r.json();
  },
  screenToBacktest: async (body: ScreenToBacktestBody): Promise<ScreenToBacktestResult> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/screen-to-backtest`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      // 프록시/백엔드가 실어보낸 사유(detail)를 그대로 노출 — "502"만 보이던 문제 해결.
      // 504=시간초과(분석 과대), 502=백엔드 연결불가 등 메시지로 구분됨. 422(입력값 검증 실패)는
      // detail이 배열로 오므로 extractErrorDetail로 사람이 읽을 수 있게 변환.
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      throw new Error(extractErrorDetail(err, `Screen-to-backtest failed: ${r.status}`));
    }
    return r.json();
  },

  // SSE 스트리밍 백테스트 — screen-to-backtest 의 진행률판. 단계(screening→loading k/total→
  // simulating→done)를 onProgress 로 흘리고 최종 결과 반환. 스트림이라 프록시 하드 타임아웃
  // 면제 → 긴 실데이터 백테스트도 안 끊기고 진행바 표시됨.
  screenToBacktestStream: async (
    body: ScreenToBacktestBody,
    onProgress?: (evt: { phase: string; done?: number; total?: number; count?: number }) => void,
    signal?: AbortSignal,
  ): Promise<ScreenToBacktestResult> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/screen-to-backtest-stream`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal,
    });
    if (!r.ok || !r.body) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      throw new Error(extractErrorDetail(err, `Screen-to-backtest failed: ${r.status}`));
    }
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    let result: ScreenToBacktestResult | null = null;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const parts = buf.split("\n\n");
      buf = parts.pop() ?? "";
      for (const part of parts) {
        const dataLine = part.split("\n").find((l) => l.startsWith("data:"));
        if (!dataLine) continue;
        let obj: { type: string; phase?: string; done?: number; total?: number; count?: number; data?: ScreenToBacktestResult; message?: string };
        try { obj = JSON.parse(dataLine.slice(5).trim()); } catch { continue; }
        if (obj.type === "progress") onProgress?.({ phase: obj.phase ?? "", done: obj.done, total: obj.total, count: obj.count });
        else if (obj.type === "result") result = obj.data ?? null;
        else if (obj.type === "error") throw new Error(obj.message || "stream error");
      }
    }
    if (!result) throw new Error("스트림 결과 없음");
    return result;
  },

  fillPriceTypes: async (): Promise<{ groups: Array<{ id: string; label: string; types: Array<{ id: string; label: string }> }> }> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/fill-price-types`);
    if (!r.ok) throw new Error(`Fill price types failed: ${r.status}`);
    return r.json();
  },

  // 조건식 팩터 토큰 지원 맵 — 픽커 배지용 (백엔드 단일 소스)
  conditionTokens: async (): Promise<TokenSupportMap> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/condition-tokens`);
    if (!r.ok) throw new Error(`Condition tokens failed: ${r.status}`);
    return r.json();
  },

  // 논리 조건식 검증 (젠포트 '조건식 검증하기') — 파서가 단일 진실 공급원
  validateLogic: async (expr: string, nConditions: number):
    Promise<{ ok: boolean; lookback?: number; empty?: boolean; error?: string }> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/condition-logic/validate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expr, n_conditions: nConditions }),
    });
    if (!r.ok) throw new Error(`Logic validate failed: ${r.status}`);
    return r.json();
  },

  // 자유 산술 팩터식 검증 (직접 입력·우선순위식)
  validateExpr: async (expr: string):
    Promise<{ ok: boolean; lookback?: number; tokens?: string[]; unknown_tokens?: string[]; error?: string }> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/factor-expr/validate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expr }),
    });
    if (!r.ok) throw new Error(`Expr validate failed: ${r.status}`);
    return r.json();
  },

  // 자연어 → 백테스터 조건식 (젠포트 AI 버튼)
  conditionNl: async (query: string): Promise<{
    conditions: BacktestConditionPayload[];
    skipped: Array<{ field: string; reason: string }>;
    explanation?: string; source?: string; note?: string;
  }> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/condition-nl`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    });
    if (!r.ok) throw new Error(`Condition NL failed: ${r.status}`);
    return r.json();
  },

  sectors: async (): Promise<{ sectors: Array<{ id: string; label: string; size: number; sample: string[] }> }> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/sectors`);
    if (!r.ok) throw new Error(`Sectors failed: ${r.status}`);
    return r.json();
  },
};
