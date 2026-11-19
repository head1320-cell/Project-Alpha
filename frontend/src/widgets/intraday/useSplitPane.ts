"use client";
/**
 * 분봉 화면 두 칸의 상태 — 선호 폭 · 접힘(브라우저에 남김)과 지금 작업 칸 폭(잼). 규칙은 `splitPane.ts`(순수).
 * 작업 칸은 설정 칸 목록을 읽은 뒤에야 그려지므로 ★콜백 ref(`measure`)로★ 잰다(늦게 붙는 요소도 잰다 — useMeasuredWidth 는 처음 그릴 때의 ref 만 본다).
 * 재기 전에는 선호 폭 그대로 그린다(작업 칸을 아주 넓다고 보고) — 잰 뒤 한 번 clamp 한다.
 * 저장은 사용자별 편의라 실패해도 화면은 그린다(이번 화면에서만 쓴다) — 공유 상태가 아니다.
 */
import { useCallback, useRef, useState } from "react";
import { DEFAULT_SPLIT, SPLIT_KEY, paneMax, paneWidth, readSplit, type SplitPref } from "./splitPane";

function load(): SplitPref {
  if (typeof window === "undefined") return DEFAULT_SPLIT;
  try { return readSplit(window.localStorage.getItem(SPLIT_KEY)); } catch { return DEFAULT_SPLIT; }
}

function store(p: SplitPref): void {
  try { window.localStorage.setItem(SPLIT_KEY, JSON.stringify({ w: p.w, open: p.open })); } catch { /* 남기지 못해도 이번 화면은 그대로 */ }
}

export function useSplitPane() {
  const [pref, setPref] = useState<SplitPref>(load);
  const [work, setWork] = useState(0);
  const ro = useRef<ResizeObserver | null>(null);
  const measure = useCallback((el: HTMLDivElement | null) => {
    ro.current?.disconnect();
    ro.current = null;
    if (!el) return;
    const read = () => { const cw = el.clientWidth; if (cw > 0) setWork((prev) => (Math.abs(prev - cw) < 1 ? prev : cw)); };
    read();
    if (typeof ResizeObserver === "undefined") return;
    ro.current = new ResizeObserver(read);
    ro.current.observe(el);
  }, []);
  const known = work > 0 ? work : Number.POSITIVE_INFINITY;
  /** 바꾼 선호 — done 이면 남긴다(끄는 동안은 그리기만). */
  const set = useCallback((next: SplitPref, done: boolean) => { setPref(next); if (done) store(next); }, []);
  return { pref, set, measure, width: paneWidth(pref.w, known), max: paneMax(known) };
}
