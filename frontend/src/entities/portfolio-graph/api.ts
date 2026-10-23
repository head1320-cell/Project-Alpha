/**
 * 포트폴리오 그래프 API — ★계산은 백엔드가 한다★ (ADR 002)
 * `/api/v1/allocation/graph/*`. 문은 불러온 파일이 틀려도 422 가 아니라 노드별 명명
 * 오류를 200 으로 돌려준다 — 여기서 HTTP 오류는 "서버에 닿지 못했다" 뿐이다.
 */
import { extractErrorDetail, getWithAuth, postJson } from "@/shared/api/apiBase";
import type { AskRecord, AskTarget, AssistAsk, AssistNarrate, AssistSuggest, BranchEvidence, GraphDoc, NarrateFact, NodeCatalog, RunEvent, RunReport, SaveResult, ValidateReport } from "./types";

const BASE = "/api/v1/allocation/graph";
/** AI 도우미(AI0) — 로그인 경로. 화면(포트폴리오 설계)은 열려 있고 AI 만 로그인이라 접두사가 다르다. */
const ASSIST = "/api/v1/assist/canvas";

/** 못 보인 이유를 서버 말 그대로 — HTTP 실패도 사유 문장으로 바꾼다(조용히 숨기지 않는다). */
const assistFailed = (reason_code: string, reason: string) =>
  ({ available: false as const, source: "unavailable" as const, reason_code, reason });

/** AI 도우미 경로 하나를 부른다 — ★던지지 않는다★: 401 은 "로그인이 끝났어요", 그 밖 HTTP 는 서버 detail, 네트워크·형식 오류도 사유 문장. */
async function assistCall<T>(path: string, body: unknown): Promise<T | ReturnType<typeof assistFailed>> {
  let res: Response;
  try { res = await postJson(`${ASSIST}/${path}`, body); } catch { return assistFailed("network", "서버에 닿지 못했어요"); }
  const json = await res.json().catch(() => null);
  if (res.status === 401) return assistFailed("signed_out", "로그인이 끝났어요. 다시 로그인해 주세요");
  if (!res.ok) return assistFailed(`http_${res.status}`, extractErrorDetail(json, `서버가 ${res.status} 오류로 답했어요`));
  if (!json || typeof json.available !== "boolean") return assistFailed("bad_body", "서버 답의 형식을 읽을 수 없어요");
  return json as T;
}

async function readJson<T>(res: Response, what: string): Promise<T> {
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    throw new Error(`${what} 실패 (HTTP ${res.status}) — ${extractErrorDetail(body, "사유 없음")}`);
  }
  return body as T;
}

export const portfolioGraphApi = {
  nodeTypes: async (): Promise<NodeCatalog> =>
    readJson<NodeCatalog>(await getWithAuth(`${BASE}/node-types`), "노드 카탈로그 조회"),
  validate: async (doc: GraphDoc): Promise<ValidateReport> =>
    readJson<ValidateReport>(await postJson(`${BASE}/validate`, doc), "그래프 검증"),
  /** `targets` 를 주면 그 노드들과 조상만 계산한다(BL1 "여기까지 계산") — 관문 판정은 없다.
   *  `progressId` 를 주면 서버가 노드 진행을 그 곁줄에 흘린다(CF5a — `followProgress`). ★주소는 그대로★ 두고 머리글로 보낸다
   *  (`/run` 주소를 가로채는 곳이 많다 — 질의 문자열이 붙으면 그 패턴이 조용히 빗나간다). 보고서는 같다. */
  run: async (doc: GraphDoc, targets?: string[], progressId?: string): Promise<RunReport> =>
    readJson<RunReport>(await postJson(targets?.length ? `${BASE}/run?targets=${encodeURIComponent(targets.join(","))}` : `${BASE}/run`, doc,
                                       progressId ? { "X-Graph-Progress": progressId } : undefined),
                        "그래프 실행"),
  /** 진행 곁줄(CF5a, SSE) — `end` 면 끝, 끊기거나(`end` 없이 닫힘)·`timeout`·HTTP 오류면 던진다(화면이 "진행을 받지 못했어요"라고 말한다). */
  followProgress: async (rid: string, onEvent: (ev: RunEvent) => void, signal?: AbortSignal): Promise<void> => {
    const r = await getWithAuth(`${BASE}/progress/${encodeURIComponent(rid)}`, { signal });
    if (!r.ok || !r.body) throw new Error(`진행 곁줄 실패 (HTTP ${r.status})`);
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) throw new Error("진행 곁줄이 끝을 알리지 않고 닫혔어요");
      buf += dec.decode(value, { stream: true });
      const parts = buf.split("\n\n");
      buf = parts.pop() ?? "";
      for (const part of parts) {
        const line = part.split("\n").find((l) => l.startsWith("data:"));
        if (!line) continue;
        let ev: RunEvent;
        try { ev = JSON.parse(line.slice(5).trim()) as RunEvent; } catch { continue; }
        if (ev.type === "end") return;
        if (ev.type === "timeout") throw new Error("진행 곁줄이 계산 시작을 기다리다 끝났어요");
        onEvent(ev);
      }
    }
  },
  /** 저장은 여기서만 — 서버가 다시 계산해 미리보기 해시가 같을 때만 한 번 쓴다(BK0). */
  save: async (doc: GraphDoc, nodeId: string, previewHash: string): Promise<SaveResult> =>
    readJson<SaveResult>(await postJson(`${BASE}/save`, { graph: doc, node_id: nodeId, preview_hash: previewHash }), "노드 저장"),
  /** 갈래 비교의 다중 비교 보정(BO O3) — 과거 성과 곡선들 → PSR·DSR. 표시만, 저장하지 않는다. */
  branchEvidence: async (series: { label: string; equity: number[] }[]): Promise<BranchEvidence> =>
    readJson<BranchEvidence>(await postJson(`${BASE}/branch-evidence`, { series }), "갈래 보정 계산"),
  /** AI 노드 추천(AI1) — ★누를 때만★ 부른다. 던지지 않는다: 키 없음·한도·거절·로그인 끝·네트워크 모두 `available:false` + 사유. */
  assistSuggest: (doc: GraphDoc): Promise<AssistSuggest> => assistCall<AssistSuggest>("suggest", doc),
  /** AI 풀어 쓰기(AI2) — ★누를 때만★. 설명·봉인은 `/run` 이 준 그대로 보낸다(서버가 지금 그래프로 확인한다). 던지지 않는다. */
  assistNarrate: (doc: GraphDoc, facts: NarrateFact[]): Promise<AssistNarrate> =>
    assistCall<AssistNarrate>("narrate", { graph: doc, facts }),
  assistAsk: (doc: GraphDoc, target: AskTarget, question: string, previous: { question: string; answer: string } | null,
              facts: NarrateFact[], records: AskRecord[]): Promise<AssistAsk> =>
    assistCall<AssistAsk>("ask", { graph: doc, target, question, previous, facts, records }),
};
