/**
 * BacktestRun API Client (Backtest Run Workflow)
 * ==========================================================================
 * /api/v1/backtest/runs* — durable run creation + status polling + result fetch.
 * The Backtest button creates a run and navigates to a dedicated loading page; the
 * loading page polls status until completed, then the results page fetches the full run.
 * State is server-persisted, so refresh / direct URL / network blips recover.
 */

import { API_BASE } from "@/lib/apiBase";
import type { ScreenToBacktestResult } from "@/lib/screenerApi";

export type RunStatus =
  | "draft" | "queued" | "validating" | "loading_data" | "simulating"
  | "calculating_metrics" | "persisting_results" | "completed"
  | "failed" | "cancelled" | "expired";

export const TERMINAL: RunStatus[] = ["completed", "failed", "cancelled", "expired"];
export const STAGE_ORDER: RunStatus[] = [
  "queued", "validating", "loading_data", "simulating",
  "calculating_metrics", "persisting_results", "completed",
];

export interface RunStatusLite {
  run_id: string;
  status: RunStatus;
  progress_percent: number;
  current_stage: string;
  status_message: string;
  strategy_name: string;
  created_at: number;
  started_at: number | null;
  completed_at: number | null;
  error_code: string | null;
  error_message: string | null;
  correlation_id: string | null;
  is_mock_data: boolean | null;
  is_pit_verified: boolean | null;
  engine_version: string | null;
}

export interface RunFull extends RunStatusLite {
  input_snapshot: Record<string, unknown> | null;
  parameter_snapshot: Record<string, unknown> | null;
  result: ScreenToBacktestResult | null;
}

// HTTP 상태 코드를 실은 에러 — 로딩 페이지가 404(진짜 없음)와 5xx/네트워크(일시적, 재시도)를
// 구분해 폴링을 이어갈 수 있게 한다.
export class ApiError extends Error {
  httpStatus: number;
  constructor(message: string, httpStatus: number) {
    super(message);
    this.name = "ApiError";
    this.httpStatus = httpStatus;
  }
}

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let detail = `${r.status}`;
    try { detail = (await r.json())?.detail ?? detail; } catch { /* keep status */ }
    throw new ApiError(String(detail), r.status);
  }
  return r.json();
}

/** 상태 폴링 요청 상한(ms). 프록시 예산은 300초(app/api/backend/[...path]/route.ts)라
 *  브라우저가 중단하지 않으면 폴링 하나가 5분을 점유할 수 있다 — 1초 주기 폴링에선
 *  그 자체가 정지로 보이므로, 훨씬 짧게 끊고 다음 tick이 새로 요청하게 한다. */
export const STATUS_TIMEOUT_MS = 20_000;

async function fetchWithTimeout(url: string, ms: number): Promise<Response> {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), ms);
  try {
    return await fetch(url, { signal: ctl.signal });
  } finally {
    clearTimeout(t);
  }
}

export const backtestRunApi = {
  create: async (body: { config: Record<string, unknown>; strategy_name?: string; requested_by?: string }):
    Promise<{ run_id: string; status: RunStatus }> =>
    j(await fetch(`${API_BASE}/api/v1/backtest/runs`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    })),

  status: async (runId: string): Promise<RunStatusLite> =>
    j(await fetchWithTimeout(`${API_BASE}/api/v1/backtest/runs/${runId}/status`, STATUS_TIMEOUT_MS)),

  get: async (runId: string): Promise<RunFull> =>
    j(await fetch(`${API_BASE}/api/v1/backtest/runs/${runId}`)),

  cancel: async (runId: string): Promise<{ ok: boolean; status: RunStatus }> =>
    j(await fetch(`${API_BASE}/api/v1/backtest/runs/${runId}/cancel`, { method: "POST" })),

  retry: async (runId: string): Promise<{ run_id: string; status: RunStatus; retried_from: string }> =>
    j(await fetch(`${API_BASE}/api/v1/backtest/runs/${runId}/retry`, { method: "POST" })),

  list: async (): Promise<{ runs: RunStatusLite[] }> =>
    j(await fetch(`${API_BASE}/api/v1/backtest/runs`)),
};

// Activity timeline stages (loading page) — label per lifecycle stage.
export const STAGE_LABELS: Record<string, string> = {
  queued: "대기열 등록",
  validating: "전략 설정 검증",
  loading_data: "시점(PIT) 데이터 로딩",
  simulating: "주문·체결 시뮬레이션",
  calculating_metrics: "성과·리스크 지표 계산",
  persisting_results: "재현 가능한 결과 저장",
  completed: "완료",
  failed: "실패", cancelled: "취소됨", expired: "만료됨",
};
