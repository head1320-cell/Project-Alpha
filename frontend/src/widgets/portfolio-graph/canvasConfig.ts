/**
 * 캔버스 설정 표 (CF 3부 E2a — `PortfolioCanvas.tsx` 에서 옮김 · 동작 불변)
 * ==========================================================================
 * 이 브라우저에 남기는 열쇠 · 상태 필터 · 오른쪽 창 탭 · 서랍 셋.
 */
import type { ReactNode } from "react";
import { Archive, ClipboardList, Sigma } from "lucide-react";
import type { NodeRunResult } from "@/entities/portfolio-graph";
import { AlphaSheetBody } from "./AlphaSheet";
import { ExecutionSheetBody } from "./ExecutionSheet";
import { RecordsSheetBody } from "./RecordsSheet";
import type { FilterKey } from "./store";

export const WIP_KEY = "alpha_pg_wip";
/** 왼쪽 판의 마지막 탭(BT2) — 이 브라우저에만. */
export const LEFT_TAB_KEY = "alpha_pg_left_tab";
/** 첫 방문 환영 줄(BN N2)을 본 적 있나 — 이 브라우저 localStorage. 못 읽거나 못 쓰면 "본 적 없음"(올 때마다 뜨되 닫을 수 있다). */
export const WELCOME_KEY = "alpha_pg_welcomed";
export function welcomeSeen(): boolean {
  try { return localStorage.getItem(WELCOME_KEY) === "1"; } catch { return false; }
}
export function markWelcomed() {
  try { localStorage.setItem(WELCOME_KEY, "1"); } catch { /* 적을 수 없으면 이번만 닫는다 */ }
}

export const FILTERS: [FilterKey, string][] = [
  ["failed", "실패"], ["blocked", "막힘"], ["practice", "연습용"], ["forward", "지금 시점 전용"], ["assumed", "가정 있음"],
];
export function matchFilter(k: FilterKey, r: NodeRunResult): boolean {
  return (k === "failed" && r.status === "failed") || (k === "blocked" && r.status === "blocked")
    || (k === "practice" && !!r.lineage?.practice) || (k === "forward" && r.lineage?.pit === "forward_only")
    || (k === "assumed" && !!r.explain?.trust?.some((t) => t.state === "assumed"));
}

export function readWip(): string | null {
  try { return typeof window === "undefined" ? null : sessionStorage.getItem(WIP_KEY); }
  catch { return null; }
}

export const TABS = [["story", "이야기"], ["settings", "설정"], ["detail", "자세히"], ["branches", "갈래"], ["wire", "선"]] as const;

export type DrawerKey = "execution" | "records" | "alphas";
/** 서랍 셋 — 예전 EXECUTION·JOURNAL·ALPHA LAB 화면의 기록 관리를 옮겼다(BL2). 계산은 노드, 기록 관리는 서랍. */
export const DRAWERS: { key: DrawerKey; label: string; sub: string; Icon: typeof Archive; Body: () => ReactNode }[] = [
  { key: "execution", label: "실행실", Icon: ClipboardList, Body: ExecutionSheetBody,
    sub: "저장한 실행 목표로 주문 계획을 만들고 검토·승인해요. 주문은 나가지 않아요." },
  { key: "records", label: "기록함", Icon: Archive, Body: RecordsSheetBody,
    sub: "판단 기록·연구 기록·실행 목표·국면 스냅샷을 다시 보고 고쳐요." },
  { key: "alphas", label: "알파", Icon: Sigma, Body: AlphaSheetBody,
    sub: "알파 식을 등록하고 단계를 올리거나 내려요." },
];
