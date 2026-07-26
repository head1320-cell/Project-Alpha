// 필터 AST 기반 고급 실행 + 필드 카탈로그 + 매크로 가이던스.
// (src/shared/api/screenerApi.ts에서 분리 — 내용 불변)

import { API_BASE } from "@/shared/api/apiBase";
import type { AdvancedRunRequest, MacroGuidance, ScreenerResponse, TechnicalIndicatorCatalog } from "../model";
import type { FieldsCatalog, FilterConditionNode, FilterGroupNode } from "@/shared/model";

export const screenerApiAdvanced = {
  fields: async (): Promise<FieldsCatalog> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/fields`);
    if (!r.ok) throw new Error(`Fields fetch failed: ${r.status}`);
    return r.json();
  },

  runAdvanced: async (req: AdvancedRunRequest): Promise<ScreenerResponse> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/run-advanced`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
    if (!r.ok) throw new Error(`Advanced run failed: ${r.status}`);
    return r.json();
  },

  count: async (req: AdvancedRunRequest): Promise<{
    total_evaluated: number; total_passed: number; elapsed_seconds: number;
  }> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/count`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
    if (!r.ok) throw new Error(`Count failed: ${r.status}`);
    return r.json();
  },

  // 자연어 → 필터 AST 변환 (Claude + 키워드 룰 fallback)
  nl2ast: async (query: string): Promise<{
    ast: FilterGroupNode;
    explanation: string;
    confidence: number;
    source: "claude" | "mock";
    error: string | null;
  }> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/nl2ast`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    });
    if (!r.ok) throw new Error(`NL2AST failed: ${r.status}`);
    return r.json();
  },

  nl2astExamples: async (): Promise<{ examples: string[] }> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/nl2ast/examples`);
    if (!r.ok) throw new Error(`Examples failed: ${r.status}`);
    return r.json();
  },

  // 기술적 지표 카탈로그 (RSI/MACD/볼린저 등 — 스크리너 technical 필터용)
  indicators: async (): Promise<TechnicalIndicatorCatalog> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/indicators`);
    if (!r.ok) throw new Error(`Indicators failed: ${r.status}`);
    return r.json();
  },

  // 젠포트 팩터 이름 → 스크리너 필드 id 매핑 (백테스터 FactorPickerModal 픽 → 스크리닝 필드)
  factorFieldMap: async (): Promise<{ map: Record<string, string>; total: number }> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/factor-field-map`);
    if (!r.ok) throw new Error(`Factor field map failed: ${r.status}`);
    return r.json();
  },

  // SSE 스트리밍 실행 — 종목별 평가 진행(done/total/misses)을 onProgress 로 흘려보내고 최종 결과 반환
  runAdvancedStream: async (
    req: AdvancedRunRequest,
    onProgress?: (done: number, total: number, misses: number) => void,
    signal?: AbortSignal,
  ): Promise<ScreenerResponse> => {
    const r = await fetch(`${API_BASE}/api/v1/screener/run-advanced-stream`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req), signal,
    });
    if (!r.ok || !r.body) throw new Error(`Stream failed: ${r.status}`);
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    let result: ScreenerResponse | null = null;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const parts = buf.split("\n\n");
      buf = parts.pop() ?? "";
      for (const part of parts) {
        const dataLine = part.split("\n").find((l) => l.startsWith("data:"));
        if (!dataLine) continue;
        let obj: { type: string; done?: number; total?: number; misses?: number; data?: ScreenerResponse; message?: string };
        try { obj = JSON.parse(dataLine.slice(5).trim()); } catch { continue; }
        if (obj.type === "progress") onProgress?.(obj.done ?? 0, obj.total ?? 0, obj.misses ?? 0);
        else if (obj.type === "result") result = obj.data ?? null;
        else if (obj.type === "error") throw new Error(obj.message || "stream error");
      }
    }
    if (!result) throw new Error("스트림 결과 없음");
    return result;
  },
};

// 기술적 지표 카탈로그 타입

export async function fetchMacroGuidance(): Promise<MacroGuidance> {
  const r = await fetch(`${API_BASE}/api/v1/screener/macro-guidance`);
  if (!r.ok) throw new Error(`Macro guidance failed: ${r.status}`);
  return r.json();
}

// 추천 필터 → FilterConditionNode 변환
