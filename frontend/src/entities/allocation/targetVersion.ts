/**
 * TargetPortfolioVersion 클라이언트 — 실행·스트레스가 참조하는 **불변 목표 하나** (R0)
 * ==========================================================================
 * ★컴파일은 서버가 한다★ `final = base × exposure`, `cash = Σbase × (1−exposure)` 를
 * 프론트에서 다시 계산하지 않는다. 예전에는 `TimingOverlayPanel` 이 화면용으로 그 산수를
 * 갖고 있었고, 실행은 그 사실을 몰라 오버레이 이전 비중으로 주문을 냈다. 산수를 두 곳에
 * 두면 반드시 갈라지므로 여기서는 **요청하고 받아 쓰기만** 한다.
 */

import { API_BASE } from "@/shared/api/apiBase";
import { getActiveCaseId } from "@/shared/lib/caseStorage";

export type TargetStatus = "executable" | "research_only";

export interface TargetVersion {
  tpv_id?: string | null;
  saved?: boolean;
  dry_run?: boolean;
  message?: string;
  mode: string;
  base_weights: Record<string, number>;
  overlay: { exposure: number; source: string | null } | null;
  final_weights: Record<string, number>;
  cash_weight: number;
  status: TargetStatus;
  status_reason: string | null;
  run_id?: string | null;
  snapshot_id?: string | null;
  case_id?: string | null;
  mes_id?: string | null;
}

export interface TargetVersionRequest {
  base_weights: Record<string, number>;
  overlay?: { exposure: number; source: string | null } | null;
  neutralized?: boolean;
  run_id?: string | null;
  snapshot_id?: string | null;
  ruleset_version?: string | null;
  pack_id?: string | null;
  /** Case 사슬 (M1-V). 넣지 않으면 `create` 가 활성 케이스를 붙인다. */
  case_id?: string | null;
  /** 이 목표가 **어떤 매크로 증거 아래** 만들어졌는지. `snapshot_id` 와 다른 사실이다. */
  mes_id?: string | null;
  note?: string | null;
  /** 화면 표시용 — 컴파일만 하고 저장하지 않는다. */
  dry_run?: boolean;
}

export const targetVersionApi = {
  /** 목표를 컴파일해 영속화한다. 저장소가 죽어도 **컴파일 결과는 돌아온다**
   *  (`saved:false`) — 목표가 옳은 것과 기록된 것은 다른 사실이다. */
  create: async (req: TargetVersionRequest): Promise<TargetVersion> => {
    // ★활성 케이스를 여기서 한 번만 붙인다★ 호출부마다 붙이면 빠뜨리는 곳이 생기고,
    // 사슬은 한 군데만 비어도 끊긴 것으로 읽힌다. 케이스가 없으면 필드를 보내지 않는다
    // (없는 케이스를 지어내지 않는다).
    const active = getActiveCaseId();
    const body = (req.case_id === undefined && active) ? { ...req, case_id: active } : req;
    const r = await fetch(`${API_BASE}/api/v1/allocation/target-versions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(`target-version 생성 실패: ${r.status}`);
    return r.json();
  },

  get: async (tpvId: string): Promise<TargetVersion> => {
    const r = await fetch(`${API_BASE}/api/v1/allocation/target-versions/${tpvId}`);
    if (!r.ok) throw new Error(`target-version 조회 실패: ${r.status}`);
    return r.json();
  },
};
