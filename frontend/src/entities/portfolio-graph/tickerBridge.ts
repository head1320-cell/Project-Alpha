/**
 * "설계에 넣기" 다리 (BU2) — `/allocation?tickers=005930,000660` 을 캔버스 문서로
 * ==========================================================================
 * ★종목은 stock_master 로 확인된 것만 싣는다(CLAUDE.md §4 — 가짜 종목코드 금지)★
 * `POST /api/v1/allocation/resolve-names` 가 이름을 돌려준 코드(`labels[c] !== c`)만 남긴다. 확인 요청이 실패하면 아무것도 싣지 않고
 * 그렇다고 말한다 — 확인하지 못한 코드를 "일단 넣기" 하지 않는다(침묵 폴백 금지).
 * 6자리 숫자만, 순서 유지·중복 제거, 최대 30개(서버 `AnalyzeRequest.tickers` max_length=30).
 */
import { API_BASE } from "@/shared/api/apiBase";
import type { GraphDoc } from "./types";
import { tickersDoc } from "./templates";
import { goalDoc } from "./goals";

export const MAX_BRIDGE_TICKERS = 30;

/** 주소의 `tickers` 값 → 6자리 코드(순서 유지·중복 제거·최대 30). 형식이 아닌 것은 `bad`, 30 을 넘어 뺀 것은 `over` 로 센다. */
export function parseTickers(raw: string | null): { codes: string[]; bad: number; over: number } {
  if (!raw) return { codes: [], bad: 0, over: 0 };
  const parts = raw.split(",").map((x) => x.trim()).filter(Boolean);
  const codes: string[] = [];
  let bad = 0;
  for (const p of parts) {
    if (!/^\d{6}$/.test(p)) { bad += 1; continue; }
    if (!codes.includes(p)) codes.push(p);
  }
  return { codes: codes.slice(0, MAX_BRIDGE_TICKERS), bad, over: Math.max(0, codes.length - MAX_BRIDGE_TICKERS) };
}

export type BridgeBoot = { doc: GraphDoc; note: string } | { doc: null; note: string };

/** 뺀 것을 종류별로 말한다 — 명단에 없는 코드 · 코드 모양이 아닌 값 · 상한을 넘은 코드(조용히 버리지 않는다). */
function droppedTail(unknown: number, bad: number, over: number): string {
  const parts = [
    unknown ? `알 수 없는 코드 ${unknown}개` : "",
    bad ? `코드 모양이 아닌 값 ${bad}개` : "",
    over ? `${MAX_BRIDGE_TICKERS}개를 넘은 코드 ${over}개` : "",
  ].filter(Boolean);
  return parts.length ? ` ${parts.join(" · ")}는 뺐어요.` : "";
}

export async function bridgeFromTickers(raw: string | null): Promise<BridgeBoot | null> {
  const { codes, bad, over } = parseTickers(raw);
  if (!codes.length && !bad) return null;
  if (!codes.length) return { doc: null, note: `가져올 종목이 없어요.${droppedTail(0, bad, over)}` };
  let labels: Record<string, string>;
  try {
    const r = await fetch(`${API_BASE}/api/v1/allocation/resolve-names`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ codes }),
    });
    if (!r.ok) throw new Error(String(r.status));
    labels = ((await r.json()) as { labels?: Record<string, string> }).labels ?? {};
  } catch {
    return { doc: null, note: "종목 이름을 확인하지 못해 가져오지 않았어요. 잠시 뒤 다시 넘겨 주세요." };
  }
  const known = codes.filter((c) => typeof labels[c] === "string" && labels[c] !== c);
  const tail = droppedTail(codes.length - known.length, bad, over);
  if (!known.length) return { doc: null, note: `가져올 종목이 없어요.${tail}` };
  return { doc: tickersDoc(known), note: `종목 찾기에서 가져온 ${known.length}종목으로 기본 흐름을 열었어요.${tail}` };
}

/**
 * 기업 분석 → 캔버스 다리 (BU6a+) — `/allocation?company=005930` 을 "기업 하나 깊게" 흐름(`goalDoc("company")`)으로.
 * 가정을 넣어야 하는 모형(합산가치·의사결정 나무·실물옵션)은 캔버스에서 사람이 넣는다 — 이 다리는 그 자리까지 데려다줄 뿐 값을 채우지 않는다.
 * ★`?tickers=` 와 같은 규칙★ — stock_master 로 이름이 확인된 코드만 싣고, 확인 요청이 실패하면 싣지 않고 말한다.
 */
export async function bridgeFromCompany(raw: string | null): Promise<BridgeBoot | null> {
  if (raw === null) return null;
  const code = raw.trim();
  if (!/^\d{6}$/.test(code)) return { doc: null, note: "기업 코드 모양이 아니라 가져오지 않았어요." };
  try {
    const r = await fetch(`${API_BASE}/api/v1/allocation/resolve-names`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ codes: [code] }),
    });
    if (!r.ok) throw new Error(String(r.status));
    const labels = ((await r.json()) as { labels?: Record<string, string> }).labels ?? {};
    const name = labels[code];
    if (typeof name !== "string" || name === code) return { doc: null, note: `알 수 없는 코드 ${code}라 가져오지 않았어요.` };
    return { doc: goalDoc("company", [code], null), note: `기업 분석에서 넘어온 ${name}(${code})로 ‘기업 하나 깊게’ 흐름을 열었어요. 가정이 필요한 모형은 노드 추가에서 고르세요.` };
  } catch {
    return { doc: null, note: "종목 이름을 확인하지 못해 가져오지 않았어요. 잠시 뒤 다시 넘겨 주세요." };
  }
}
