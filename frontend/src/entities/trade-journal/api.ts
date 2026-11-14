/**
 * 매매일지 라우트 — `POST /api/v1/trade-journal/analyze` (로그인 필요 · 서버는 저장하지 않는다).
 * 실패는 `Result` 로 — 서버 사유 그대로(상한 초과·빈 요청), 닿지 못하면 status 0, 로그인이 끝났으면 401.
 */
import { postJson } from "@/shared/api/apiBase";
import { call, type Result } from "@/shared/api/result";
import type { AnalyzeRequest, Journal } from "./types";

export const analyzeTrades = (body: AnalyzeRequest): Promise<Result<Journal>> =>
  call<Journal>(postJson("/api/v1/trade-journal/analyze", body));
