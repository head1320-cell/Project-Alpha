/**
 * perf — 두 곡선 맞추기 (2026-11-09 · 성과 그림 문법 ③ §3.1)
 * `POST /api/v1/perf/compare` 는 순수하다(저장소 없음): 두 곡선을 보내면 서버가 날짜 합집합/순번으로 맞추고 차이(%p)·해마다 차이·지표
 * 차이를 돌려준다. 비교 화면과 현실성 탭이 제 손으로 빼지 않고 이 문을 부른다(캔버스 비교 노드와 같은 함수).
 */
import { API_BASE } from "@/shared/api/apiBase";
import type { CompareResponse } from "@/shared/ui/perf/perfView";

export type { CompareResponse } from "@/shared/ui/perf/perfView";

export interface CompareSide {
  label: string;
  dates: string[];
  equity: (number | null)[];
  stats?: Record<string, unknown> | null;
  periods?: unknown | null;
}
export interface CompareRequest { a: CompareSide; b: CompareSide; base?: 1 | 100; metrics?: "page" | "node" | null }

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) {
    const body = await r.json().catch(() => null) as { detail?: unknown } | null;
    const detail = body?.detail;
    throw Object.assign(new Error(typeof detail === "string" && detail ? detail : `서버가 ${r.status} 로 답했습니다.`), { httpStatus: r.status });
  }
  return r.json() as Promise<T>;
}

export const perfApi = {
  compare: async (body: CompareRequest): Promise<CompareResponse> =>
    j(await fetch(`${API_BASE}/api/v1/perf/compare`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    })),
};
