/**
 * 분봉 백테스트의 문 — 전부 로그인 필요 · 계산만 한다(주문 경로에 닿지 않는다).
 * 실패는 `Result` 로 — 서버 사유 그대로(상한 초과 · 어긋난 설정), 닿지 못하면 status 0, 로그인이 끝났으면 401.
 */
import { extractErrorDetail, getWithAuth, postJson } from "@/shared/api/apiBase";
import { call, type Result } from "@/shared/api/result";
import type {
  Coverage, DayTypeAnswer, DayTypeList, DayTypeRefusal, DayTypeRequest, Divergence, DivergenceRequest, Expanded, ResultList,
  SimulateRequest, Simulation, Templates, TrialList, ValidateRequest, Validation,
} from "./types";

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

/** 규칙을 조건 나무로 풀고 검사한다 — ★계산 · 시행 기록 없음★(편집 중의 검사는 시행이 아니다). 거절은 서버의 문장 그대로. */
export const expandRule = (rule: SimulateRequest["rule"]): Promise<Result<Expanded>> =>
  call<Expanded>(postJson(`${BASE}/rules/expand`, { rule }));
export const simulate = (body: SimulateRequest): Promise<Result<Simulation>> => call<Simulation>(postJson(`${BASE}/simulate`, body));
export const validate = (body: ValidateRequest): Promise<Result<Validation>> => call<Validation>(postJson(`${BASE}/validate`, body));
/** 캔버스의 '분봉 결과 조회' 노드가 고를 목록 — 내 것만. */
export const listResults = (): Promise<Result<ResultList>> => call<ResultList>(getWithAuth(`${BASE}/results`));
/** 올린 체결을 같은 규칙의 시뮬레이션과 견준다. ★서버는 올린 체결을 저장하지 않는다★ · 시뮬레이션 쪽은 시행으로 기록된다. */
export const divergence = <F,>(body: DivergenceRequest<F>): Promise<Result<Divergence>> =>
  call<Divergence>(postJson(`${BASE}/divergence`, body));
/** 내가 돌린 분봉 백테스트의 설정들(마지막으로 돌린 것이 먼저) — 괴리 보고가 고를 목록. 내 것만. */
export const listTrials = (): Promise<Result<TrialList>> => call<TrialList>(getWithAuth(`${BASE}/trials`));

// ── 하루 유형 모형(T1) ─────────────────────────────────────────────────────────────────
export type TrainResult = { ok: true; value: DayTypeAnswer } | { ok: false; status: number; error: string; refusal: DayTypeRefusal | null };

/** 학습 — 같은 표본 · 같은 설정이면 서버가 다시 학습하지 않고 그 모형을 돌려준다(`created: false`).
 *  거절은 사유 문장과 함께 ★세부를 버리지 않는다★ — 날이 모자랄 때 어느 사유로 몇 표본을 뺐는지 화면이 보여야 한다. */
export async function trainDayTypes(body: DayTypeRequest): Promise<TrainResult> {
  try {
    const r = await postJson(`${BASE}/day-types`, body);
    const js: unknown = await r.json().catch(() => null);
    if (!r.ok) {
      const detail = (js as { detail?: unknown } | null)?.detail;
      const refusal = detail && typeof detail === "object" && !Array.isArray(detail) && typeof (detail as { code?: unknown }).code === "string"
        ? detail as DayTypeRefusal : null;
      return { ok: false, status: r.status, error: extractErrorDetail(js, `서버가 ${r.status} 로 응답했습니다 — 사유 수신 실패`), refusal };
    }
    return { ok: true, value: js as DayTypeAnswer };
  } catch {
    return { ok: false, status: 0, error: "서버 연결 실패", refusal: null };
  }
}
/** 내 모형들(최신 순 · 요약). 운영에서는 합성 분봉으로 학습한 모형을 빼고 그 수를 알린다. */
export const listDayTypes = (): Promise<Result<DayTypeList>> => call<DayTypeList>(getWithAuth(`${BASE}/day-types`));
/** 내 모형 하나 — 남의 것 · 없는 것은 같은 404. */
export const getDayType = (key: string): Promise<Result<DayTypeAnswer>> =>
  call<DayTypeAnswer>(getWithAuth(`${BASE}/day-types/${encodeURIComponent(key)}`));
