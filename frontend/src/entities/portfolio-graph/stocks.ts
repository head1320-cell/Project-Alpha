/**
 * 종목 이름 찾기 (BN N2) — ★종목 식별은 서버 `stock_master` 가 단일 진실★
 * ==========================================================================
 * `GET /api/v1/screener/stock-search?q=` (`stock_master.search_stocks`) 만 부른다. 화면은 이름을 지어내지 않는다:
 * 서버가 코드를 모르면 "이름 모름", 검색 자체가 실패하면 **빈 목록이 아니라 실패**라고 말한다(없음 ≠ 못 찾음).
 * 캐시는 이 탭의 메모리뿐(편의) — 이름은 계산에 쓰이지 않는다(계산은 코드로).
 */
import { getWithAuth } from "@/shared/api/apiBase";

export interface StockHit { code: string; name: string }
export type SearchResult = { ok: true; items: StockHit[] } | { ok: false; reason: string };

export async function searchStocks(q: string, limit = 8, signal?: AbortSignal): Promise<SearchResult> {
  try {
    const r = await getWithAuth(`/api/v1/screener/stock-search?q=${encodeURIComponent(q)}&limit=${limit}`, { signal });
    if (!r.ok) return { ok: false, reason: `종목 검색이 응답하지 않았어요 (HTTP ${r.status})` };
    const body = await r.json().catch(() => null);
    const items = Array.isArray(body?.items) ? body.items : null;
    if (!items) return { ok: false, reason: "종목 검색 응답을 읽지 못했어요" };
    return { ok: true, items: items.filter((x: unknown): x is StockHit =>
      !!x && typeof (x as StockHit).code === "string" && typeof (x as StockHit).name === "string") };
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    return { ok: false, reason: "종목 검색에 닿지 못했어요" };
  }
}

/** 코드 → 이름. `null` = 서버가 모르는 코드(이름 모름), 없으면 아직 모름·실패. */
const names = new Map<string, string | null>();

export type NameState = { state: "known"; name: string } | { state: "unknown" } | { state: "loading" } | { state: "failed"; reason: string };

export async function nameOf(code: string): Promise<NameState> {
  if (names.has(code)) {
    const n = names.get(code)!;
    return n === null ? { state: "unknown" } : { state: "known", name: n };
  }
  const r = await searchStocks(code, 5);
  if (!r.ok) return { state: "failed", reason: r.reason };
  const hit = r.items.find((x) => x.code.toUpperCase() === code.toUpperCase());
  names.set(code, hit ? hit.name : null);
  return hit ? { state: "known", name: hit.name } : { state: "unknown" };
}

/** 쉼표 목록의 마지막 토막 — 이름 검색어. 6자리 코드면 검색하지 않는다(이미 코드다). */
export function lastToken(text: string): { head: string; token: string } {
  const m = /^(.*[,，\s])?([^,，\s]*)$/.exec(text);
  return { head: m?.[1] ?? "", token: (m?.[2] ?? "").trim() };
}
export const isCode = (t: string) => /^\d{6}$/.test(t);
