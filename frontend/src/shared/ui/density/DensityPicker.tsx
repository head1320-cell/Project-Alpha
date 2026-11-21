"use client";
/**
 * 밀도 고르기 (ADR 007 §7 · U1-e) — 자동 · 촘촘 · 보통 · 넉넉
 * ==========================================================================
 * 고르면 이 브라우저에 남기고(`alpha_density` — 자동이면 지운다) ★그 자리에서★ `html` 의 속성을 다시 단다(다음 화면 이동을 기다리지 않는다).
 * 정하는 규칙은 `resolveDensity` 하나다 — 첫 그림 전 조각 · 셸의 맞춤 훅과 같은 차례다.
 *  · 손가락 화면(`pointer: coarse`) · 고객 화면(`lock`)은 넉넉으로 고정한다 — 그때는 고르는 칸 대신 그 사실을 글자로 적는다(듣지 않는 조작을 두지 않는다).
 *  · 경로 표에 없는 화면에서는 그리지 않는다 — 밀도가 걸리지 않는 화면이다.
 * 서버 그림 · 수화 때는 저장값을 읽지 않고 '자동'으로 그린다. 수화하며 이 브라우저의 값으로 바꾼다(`useSyncExternalStore`).
 * 처음 놓인 자리는 종목 찾기의 결과 도구 줄이다 — 첫 화면이 촘촘해지는 조각에서 되돌릴 길(ADR 007 §7 의 2026-11-21 정정). 셸로 올리는 것은 U6.
 */
import { useSyncExternalStore } from "react";
import { usePathname } from "next/navigation";
import { Segmented } from "@/shared/ui/tx";
import { DENSITIES, DENSITY_EVENT, applyDensity, readDensityPref, resolveDensity, tierRoute, writeDensityPref, type DensityPref } from "./density";

const OPTIONS: { value: DensityPref; label: string }[] = [{ value: "auto", label: "자동" }, ...DENSITIES.map(([value, label]) => ({ value, label }))];
const COARSE = "(pointer: coarse)";

function subscribePref(notify: () => void) {
  window.addEventListener("storage", notify);
  window.addEventListener(DENSITY_EVENT, notify);
  return () => { window.removeEventListener("storage", notify); window.removeEventListener(DENSITY_EVENT, notify); };
}
function subscribeCoarse(notify: () => void) {
  const mq = window.matchMedia?.(COARSE);
  if (!mq) return () => undefined;
  mq.addEventListener?.("change", notify);
  return () => mq.removeEventListener?.("change", notify);
}
function readCoarse(): boolean {
  try { return !!window.matchMedia?.(COARSE).matches; } catch { return false; }
}
const autoPref = (): DensityPref => "auto";
const notCoarse = () => false;

export function DensityPicker({ className }: { className?: string }) {
  const path = usePathname() ?? "";
  const pref = useSyncExternalStore(subscribePref, readDensityPref, autoPref);
  const coarse = useSyncExternalStore(subscribeCoarse, readCoarse, notCoarse);
  const route = tierRoute(path);
  if (!route) return null;
  const cls = `tx-density${className ? ` ${className}` : ""}`;
  if (route.lock || coarse) {
    return <p className={`${cls} tx-density--fixed`}>밀도 넉넉 · {route.lock ? "고객 화면은" : "손가락 화면은"} 고정합니다</p>;
  }
  const pick = (next: DensityPref) => {
    writeDensityPref(next);
    applyDensity(document.documentElement, resolveDensity(path, next, readCoarse()));
  };
  return (
    <div className={cls}>
      <span className="tx-density-k" aria-hidden="true">밀도</span>
      <Segmented label="밀도" options={OPTIONS} value={pref} onChange={pick} />
    </div>
  );
}
