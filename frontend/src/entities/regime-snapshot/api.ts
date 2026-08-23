// RegimeSnapshot API 클라이언트 — 동일출처 런타임 프록시(/api/backend) 경유.
//
// 실패는 정직하게: 조회 실패는 null, 생성 실패는 detail 을 담은 Error.
// 스냅샷을 못 만들었는데 만든 척하면 재현성 주장 전체가 무너진다.

import { API_BASE, extractErrorDetail, postJson } from "@/shared/api/apiBase";
import type { CreateFromCurrentResult, RegimeSnapshot, RegimeSnapshotSummary } from "./model";

const BASE = "/api/v1/regime-snapshots";

async function readJson(r: Response): Promise<unknown> {
  return r.json().catch(() => null);
}

export const regimeSnapshotApi = {
  /** 지금 국면을 스냅샷으로 굳힌다. Macro 탭의 "Allocation Studio에서 열기". */
  async createFromCurrent(market: "kr" | "us" = "kr"): Promise<CreateFromCurrentResult> {
    const r = await postJson(`${BASE}/from-current?market=${market}`, {});
    const body = (await readJson(r)) as CreateFromCurrentResult | null;
    if (!r.ok) {
      throw new Error(extractErrorDetail(body, `스냅샷 생성 실패 (HTTP ${r.status})`));
    }
    // recorded=false 는 HTTP 200 이지만 저장되지 않은 것 — 호출자가 구분할 수 있게 그대로 넘긴다.
    return body ?? { recorded: false, snapshot_id: null };
  },

  /** 단건 (관측치 신원 포함). 없으면 null. */
  async get(snapshotId: string): Promise<RegimeSnapshot | null> {
    const r = await fetch(`${API_BASE}${BASE}/${encodeURIComponent(snapshotId)}`);
    if (!r.ok) return null;
    return (await readJson(r)) as RegimeSnapshot | null;
  },

  /** 최신순 요약 목록. */
  async list(limit = 50): Promise<RegimeSnapshotSummary[]> {
    const r = await fetch(`${API_BASE}${BASE}?limit=${limit}`);
    if (!r.ok) return [];
    const body = (await readJson(r)) as { snapshots?: RegimeSnapshotSummary[] } | null;
    return body?.snapshots ?? [];
  },

  /** 두 스냅샷 차이 — 국면이 언제 어떻게 바뀌었는지. */
  async compare(a: string, b: string): Promise<unknown | null> {
    const q = new URLSearchParams({ a, b }).toString();
    const r = await fetch(`${API_BASE}${BASE}/compare?${q}`);
    if (!r.ok) return null;
    return readJson(r);
  },
};
