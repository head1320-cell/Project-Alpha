/**
 * 분봉 백테스트의 문 — 전부 로그인 필요 · 계산만 한다(주문 경로에 닿지 않는다).
 * 실패는 `Result` 로 — 서버 사유 그대로(상한 초과 · 어긋난 설정), 닿지 못하면 status 0, 로그인이 끝났으면 401.
 */
import { getWithAuth, postJson } from "@/shared/api/apiBase";
import { call, type Result } from "@/shared/api/result";
import type { Coverage, ResultList, SimulateRequest, Simulation, Templates, ValidateRequest, Validation } from "./types";

const BASE = "/api/v1/intraday";

export const getTemplates = (): Promise<Result<Templates>> => call<Templates>(getWithAuth(`${BASE}/templates`));

/** 기간과 종목을 주지 않으면 서버가 최근 한 달을 답한다. */
export const getCoverage = (q: { from?: string; to?: string; tickers?: string[] } = {}): Promise<Result<Coverage>> => {
  const params = new URLSearchParams();
  if (q.from) params.set("from", q.from);
  if (q.to) params.set("to", q.to);
  if (q.tickers?.length) params.set("tickers", q.tickers.join(","));
  const tail = params.toString();
  return call<Coverage>(getWithAuth(`${BASE}/coverage${tail ? `?${tail}` : ""}`));
};

export const simulate = (body: SimulateRequest): Promise<Result<Simulation>> => call<Simulation>(postJson(`${BASE}/simulate`, body));
export const validate = (body: ValidateRequest): Promise<Result<Validation>> => call<Validation>(postJson(`${BASE}/validate`, body));
/** 캔버스의 '분봉 결과 조회' 노드가 고를 목록 — 내 것만. */
export const listResults = (): Promise<Result<ResultList>> => call<ResultList>(getWithAuth(`${BASE}/results`));
