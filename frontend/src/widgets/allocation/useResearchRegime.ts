"use client";
// 리서치 국면 단일 진실 — **붙어 있는 스냅샷이 이기고, 라이브는 라벨된 폴백이다.**
//
// 왜 훅으로 한 번만 쓰는가
// ─────────────────────────────────────────────────────────────────────────────
// Phase 3b 까지 AAS 는 국면을 세 곳에서 각자 조회했다:
//   ContextStrip · GoalGate · app/allocation/journal/page.tsx — 전부 useQuery(["macro","regime"]).
// 같은 값을 세 번 파생하면 (1) 중복 작업이고 (2) 세 화면이 서로 다른 말을 할 수 있다.
// 우선순위 규칙을 여기 한 곳에 두고 세 곳이 소비한다.
//
// 스냅샷은 **선택**이다 — 게이트는 스터디가 생기기 전에 열리므로 붙은 스냅샷이 없을 수 있다.
// 그래서 "스냅샷이 없으면 이 사이트는 국면을 못 쓴다"가 아니라 "라이브로 폴백하고 화면에
// 어느 쪽인지 밝힌다"가 정답이다. source 를 반환하는 이유가 그것이다.
import { useQuery } from "@tanstack/react-query";
import { macroApi, type RegimeState } from "@/entities/macro/api";
import { regimeSnapshotApi } from "@/entities/regime-snapshot/api";
import type { DataStatus, ResearchUsage } from "@/entities/regime-snapshot/model";
import { useAllocation } from "./AllocationProvider";

/** 지금 보고 있는 국면이 어디서 왔는가 — UI 가 반드시 표시해야 한다. */
export type RegimeSource = "snapshot" | "live" | "none";

export interface ResearchRegime {
  source: RegimeSource;
  regime: string | null;
  /** 0..1 로 정규화 (라이브는 0-1/0-100 이 섞여 오므로 여기서 통일) */
  confidence: number | null;
  recommendedMode: string | null;
  stressScore: number | null;
  /** 스냅샷일 때 판정 기준시점. 라이브면 null(=지금). */
  asOf: string | null;
  dataStatus: DataStatus | null;
  researchUsage: ResearchUsage | null;
  snapshotId: string | null;
  modelVersion: string | null;
  engineVersion: string | null;
  codeVersion: string | null;
  isLoading: boolean;
}

/** 라이브 confidence 는 0-1 과 0-100 이 섞여 온다 — 기존 ContextStrip 휴리스틱을 보존. */
function normalizeConfidence(v: number | null | undefined): number | null {
  if (v == null) return null;
  return v <= 1.5 ? v : v / 100;
}

export function useResearchRegime(): ResearchRegime {
  const { attachedSnapshotId } = useAllocation();

  // 스냅샷 — 0M 스테이지·ContextStrip 과 같은 queryKey 를 써서 캐시를 공유한다(중복 fetch 0).
  const snapQ = useQuery({
    queryKey: ["regime-snapshot", attachedSnapshotId],
    queryFn: () => (attachedSnapshotId ? regimeSnapshotApi.get(attachedSnapshotId) : Promise.resolve(null)),
    enabled: !!attachedSnapshotId,
  });

  // 라이브 — 매크로 탭과 같은 queryKey. 스냅샷이 붙어 있어도 계속 캐시를 공유하되,
  // 아래 우선순위에서 지지 않도록 스냅샷이 있으면 참조하지 않는다.
  const liveQ = useQuery({
    queryKey: ["macro", "regime"],
    queryFn: () => macroApi.regime().catch(() => null),
  });

  // ── 우선순위 1: 붙어 있는 스냅샷 ──
  if (attachedSnapshotId) {
    const s = snapQ.data;
    if (s) {
      return {
        source: "snapshot",
        regime: s.regime ?? null,
        confidence: normalizeConfidence(s.confidence),
        recommendedMode: s.recommended_mode ?? null,
        stressScore: s.stress_score ?? null,
        asOf: s.as_of || null,
        dataStatus: s.data_status ?? null,
        researchUsage: s.research_usage ?? null,
        snapshotId: s.snapshot_id,
        modelVersion: s.model_version ?? null,
        engineVersion: s.engine_version ?? null,
        codeVersion: s.code_version ?? null,
        isLoading: false,
      };
    }
    // ID 는 있는데 아직 못 읽었다 / 사라졌다 — 라이브로 슬쩍 바꿔치지 않는다.
    // 그러면 사용자는 고정된 국면을 보고 있다고 믿으면서 실제로는 오늘 값을 본다.
    return {
      source: "snapshot", regime: null, confidence: null, recommendedMode: null,
      stressScore: null, asOf: null, dataStatus: null, researchUsage: null,
      snapshotId: attachedSnapshotId, modelVersion: null, engineVersion: null,
      codeVersion: null, isLoading: snapQ.isLoading,
    };
  }

  // ── 우선순위 2: 라이브 폴백 ──
  const st = (liveQ.data ?? null) as RegimeState | null;
  const kr = st?.markets?.kr ?? st;
  if (!kr) {
    return {
      source: "none", regime: null, confidence: null, recommendedMode: null,
      stressScore: null, asOf: null, dataStatus: null, researchUsage: null,
      snapshotId: null, modelVersion: null, engineVersion: null, codeVersion: null,
      isLoading: liveQ.isLoading,
    };
  }
  return {
    source: "live",
    regime: kr.regime ?? null,
    confidence: normalizeConfidence(kr.confidence),
    recommendedMode: st?.recommended_mode ?? kr.recommended_mode ?? null,
    stressScore: st?.stress_score ?? null,
    asOf: null,                     // 라이브는 "지금" — 기준시점을 꾸며 내지 않는다
    dataStatus: null,
    researchUsage: null,
    snapshotId: null,
    modelVersion: null, engineVersion: null, codeVersion: null,
    isLoading: liveQ.isLoading,
  };
}
