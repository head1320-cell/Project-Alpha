"use client";
/**
 * 판 배치의 상태 — 켬 · 지금 배치 · 이름 붙인 배치 · 사유 글 (G6 2a-1 · 계획 §9.1 · §9.2)
 * ==========================================================================
 * ★이 브라우저에만 남는다★(서버 0줄) — 열쇠 셋: `ws.<화면>`(지금 배치 · 꼴 v1) · `ws.<화면>.on`("1" 일 때만 켬) · `ws.<화면>.saved`(이름 붙인 배치).
 * '기본 배치'(끄기)는 켬만 지운다 — 다시 켜면 마지막 배치가 돌아온다. 읽기 · 쓰기는 try/catch 이고 ★실패를 숨기지 않는다★:
 * 고쳐 읽은 것 · 읽지 못한 것은 사유 글(`notes`)로, 쓰지 못한 것은 '이번 화면에서만 씁니다' 글로 화면에 선다(판 배치를 켰을 때 작업 공간 위 막대).
 * 처음 값은 `useState(load)` — 서버 그림에서는 꺼짐이고, 판 배치는 계정 확인 뒤에 서므로 수화와 어긋나지 않는다(G5 `useSplitPane` 과 같은 길).
 */
import { useState } from "react";
import {
  defaultLayout, exportFile, importFile, readLayout, readSaved, removeNamed, renameNamed, saveNamed, savedText,
  type ImportResult, type Layout, type Named, type NamedResult, type ScreenSpec,
} from "./layout";

export const keysOf = (screen: string) => ({ layout: `ws.${screen}`, on: `ws.${screen}.on`, saved: `ws.${screen}.saved` });
const WRITE_FAIL = "이 브라우저에 배치를 남기지 못했습니다. 이번 화면에서만 씁니다.";
const NAMED_FAIL = "이 브라우저에 저장하지 못했습니다. 이름 붙인 배치는 바뀌지 않았습니다.";

type State = { on: boolean; layout: Layout; saved: Named[]; notes: string[]; failed: boolean };

function load(spec: ScreenSpec): State {
  const empty: State = { on: false, layout: defaultLayout(spec), saved: [], notes: [], failed: false };
  if (typeof window === "undefined") return empty;
  const k = keysOf(spec.screen);
  let on = false;
  let rawLayout: string | null = null;
  let rawSaved: string | null = null;
  try {
    on = window.localStorage.getItem(k.on) === "1";
    rawLayout = window.localStorage.getItem(k.layout);
    rawSaved = window.localStorage.getItem(k.saved);
  } catch {
    return { ...empty, notes: ["이 브라우저의 저장을 읽지 못했습니다. 판 배치를 켜도 이번 화면에서만 씁니다."] };
  }
  const r = readLayout(rawLayout, spec);
  const s = readSaved(rawSaved, spec);
  const first = spec.presets.find((p) => p.id === spec.first)?.name ?? "";
  const notes: string[] = [];
  if (r.fallback) notes.push(`저장된 배치를 읽지 못해 처음 배치(${first})로 열었습니다. 사유: ${r.notes.join(" ")}`);
  else if (r.notes.length) notes.push(`저장된 배치를 고쳐 열었습니다. ${r.notes.join(" ")}`);
  notes.push(...s.notes);
  return { on, layout: r.layout, saved: s.items, notes, failed: false };
}

function put(key: string, value: string | null): boolean {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
    return true;
  } catch {
    return false;
  }
}

export type WorkspaceState = ReturnType<typeof useWorkspace>;

export function useWorkspace(spec: ScreenSpec) {
  const [st, setSt] = useState<State>(() => load(spec));
  const k = keysOf(spec.screen);

  /** 지금 배치를 바꾼다 — persist 면 남긴다(끄는 동안은 그리기만). 사용자가 바꾼 뒤에는 읽기 때의 사유 글을 걷는다(고친 배치가 남는다). */
  const setLayout = (next: Layout, persist = true) => {
    const ok = persist ? put(k.layout, JSON.stringify(next)) : true;
    setSt((s) => ({ ...s, layout: next, notes: persist ? [] : s.notes, failed: s.failed || !ok }));
  };
  const setOn = (on: boolean) => {
    const ok = put(k.on, on ? "1" : null);
    setSt((s) => ({ ...s, on, failed: s.failed || !ok }));
  };
  /** 배치를 통째로 바꾸고 켠다(처음 배치 · 이름 붙인 배치 · 가져오기). */
  const adopt = (layout: Layout) => {
    const ok = put(k.layout, JSON.stringify(layout)) && put(k.on, "1");
    setSt((s) => ({ ...s, on: true, layout, notes: [], failed: s.failed || !ok }));
  };
  const applyPreset = (id: string) => {
    const p = spec.presets.find((x) => x.id === id);
    if (p) adopt(readLayout(p.layout, spec).layout);
  };
  const applySaved = (name: string) => {
    const n = st.saved.find((x) => x.name === name);
    if (n) adopt(readLayout(n.layout, spec).layout);
  };
  /** 이름 붙인 배치 목록을 바꾼다 — 남기지 못하면 바꾸지 않고 사유를 돌려준다(저장했다고 말하지 않는다). */
  const commitSaved = (r: NamedResult): NamedResult => {
    if (!r.ok) return r;
    if (!put(k.saved, savedText(spec, r.items))) return { ok: false, reason: NAMED_FAIL };
    setSt((s) => ({ ...s, saved: r.items }));
    return r;
  };
  const saveAs = (name: string) => commitSaved(saveNamed(st.saved, name, st.layout));
  const rename = (from: string, to: string) => commitSaved(renameNamed(st.saved, from, to));
  const remove = (name: string) => commitSaved({ ok: true, items: removeNamed(st.saved, name) });
  const exportText = () => exportFile(spec, st.layout, st.saved);
  /** 가져오기 — 엄격(사유가 있으면 아무것도 바꾸지 않는다). 통과하면 지금 배치 · 이름 붙인 배치를 바꾸고 켠다. */
  const importText = (text: string): ImportResult => {
    const r = importFile(text, spec, st.saved);
    if (!r.ok) return r;
    if (!put(k.saved, savedText(spec, r.saved))) return { ok: false, reasons: [NAMED_FAIL] };
    adopt(r.current);
    setSt((s) => ({ ...s, saved: r.saved }));
    return r;
  };

  const notes = st.failed ? [...st.notes, WRITE_FAIL] : st.notes;
  return { spec, on: st.on, layout: st.layout, saved: st.saved, notes, setLayout, setOn, applyPreset, applySaved, saveAs, rename, remove, exportText, importText };
}
