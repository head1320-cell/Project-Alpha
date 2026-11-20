/**
 * 판 배치의 순수 규칙 — 꼴 v1 · 읽기(고쳐 읽고 사유) · 옮기기 · 닫기 · 다시 열기 · 접기 · 폭 · 칸 높이 · 이름 붙인 배치 · 파일 (G6 2a-1 · 설계 §5 · 계획 §9.2)
 * ==========================================================================
 * ★화면 · 브라우저 · 저장소를 모른다★ — 같은 입력에 같은 답(시험 `e2e/ws-layout.spec.ts`). 받은 배치는 바꾸지 않고 새 객체를 돌려준다.
 * 꼴: 열 1 ~ 3 · 열마다 칸 1 ~ 2 · 판은 탭과 닫힌 판을 통틀어 정확히 한 번 · 남는 폭 열(w = null) 정확히 하나 · 아래 칸 높이 h 0.2 ~ 0.8(0.05 걸음).
 * ★침묵 폴백 금지★: 내 저장을 읽을 때 고친 것은 모두 사유 글로 남기고(`notes`), 가져오기(`strictLayout` · `importFile`)는 사유가 하나라도 있으면 거절한다.
 * 도구는 배치를 고르거나 권하지 않는다 — 처음 배치의 이름은 쓰임의 묘사다.
 */

/**
 * 판 하나. `titled` — 판 안 첫 절이 판 이름과 같은 글을 제목으로 단다(예: '판정' 판의 '판정' 절). 그러면 같은 이름의 제목이 둘 서지 않게
 * 쌓기에서는 판 이름을 남기고 그 절 제목을 그리지 않으며(부제는 남는다) 탭에서는 낭독용 판 이름을 빼고 절 제목을 쓴다 — CSS 만(판 안 구조는 그대로).
 * 판 이름과 다른 제목의 절이면 달지 않는다(달면 그 절의 제목이 사라진다 — 화면 시험이 같은 글인지 건다).
 */
export type PanelSpec = { id: string; name: string; min: number; closable: boolean; titled?: boolean };
export type Area = { tabs: string[]; active: string; h?: number };
export type Col = { w: number | null; rows: Area[] };
export type Layout = { v: 1; screen: string; cols: Col[]; closed: string[] };
export type Preset = { id: string; name: string; layout: Layout };
/**
 * 화면의 판 배치 설정. `colNew` — 판을 새 열로 옮길 때의 폭(그 판의 최소 폭보다 작으면 최소 폭). 없으면 최소 폭 그대로.
 * 최소 폭은 '판이 깨지지 않는 바닥'(잰 값)이고 새 열의 폭은 '처음 놓을 자리'(화면의 설계 값)라 둘을 가른다.
 */
export type ScreenSpec = { screen: string; panels: PanelSpec[]; presets: Preset[]; first: string; colNew?: number };
export type Named = { name: string; layout: Layout };
export type At = { col: number; row: number };
export type Target =
  | { kind: "tab"; col: number; row: number; index: number }
  | { kind: "col"; index: number }
  | { kind: "row"; col: number; pos: "top" | "bottom" };

export const MAX_COLS = 3;
export const MAX_ROWS = 2;
export const H_MIN = 0.2;
export const H_MAX = 0.8;
export const H_NEW = 0.5;
export const BAR_W = 16;
export const MAX_NAMED = 8;
export const NAME_MAX = 20;
export const FILE_MAX = 64 * 1024;
export const FILE_KIND = "project-alpha.workspace";

const ORD = ["첫째", "둘째", "셋째"];

/** 받침으로 조사를 고른다 — 한글이 아니면 받침 없는 쪽. (으)로 는 ㄹ 받침도 '로'. */
function batchim(word: string): number {
  const ch = word.trim().slice(-1);
  const code = ch.charCodeAt(0) - 0xac00;
  return code >= 0 && code <= 11171 ? code % 28 : 0;
}
export const ro = (word: string): string => { const j = batchim(word); return j === 0 || j === 8 ? "로" : "으로"; };
export const eul = (word: string): string => (batchim(word) === 0 ? "를" : "을");

const clone = (l: Layout): Layout => ({ v: 1, screen: l.screen, closed: [...l.closed],
  cols: l.cols.map((c) => ({ w: c.w, rows: c.rows.map((a) => (a.h === undefined ? { tabs: [...a.tabs], active: a.active } : { tabs: [...a.tabs], active: a.active, h: a.h })) })) });

const panelOf = (spec: ScreenSpec, id: string): PanelSpec | undefined => spec.panels.find((p) => p.id === id);
const nameOf = (spec: ScreenSpec, id: string): string => panelOf(spec, id)?.name ?? id;

/** 칸의 이름 — 자리로 부른다(`첫째 열` · `둘째 열 위 칸` · `둘째 열 아래 칸`). */
export function areaName(layout: Layout, col: number, row: number): string {
  const c = layout.cols[col];
  const base = `${ORD[col] ?? `${col + 1}번째`} 열`;
  if (!c || c.rows.length < 2) return base;
  return `${base} ${row === 0 ? "위" : "아래"} 칸`;
}

/** 처음 배치(spec.first)의 사본. */
export function defaultLayout(spec: ScreenSpec): Layout {
  const p = spec.presets.find((x) => x.id === spec.first) ?? spec.presets[0];
  return clone(p.layout);
}

/** 열의 최소 폭 — 그 열의 모든 탭(가려진 탭 포함) 가운데 가장 큰 판 최소 폭. */
export function colMin(c: Col, spec: ScreenSpec): number {
  let m = 0;
  for (const a of c.rows) for (const id of a.tabs) m = Math.max(m, panelOf(spec, id)?.min ?? 0);
  return m;
}

const quantH = (h: number): number => Math.round(h * 20) / 20;
const isH = (h: unknown): h is number => typeof h === "number" && Number.isFinite(h) && h >= H_MIN - 1e-9 && h <= H_MAX + 1e-9 && Math.abs(h * 20 - Math.round(h * 20)) < 1e-9;
const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

/** 남는 폭 열이 정확히 하나가 되게 — 없으면 마지막 열. (옮기기 · 접기 뒤에 부른다 · 사유 없음: 사용자가 고른 조작의 결과다) */
function oneFlex(l: Layout, spec: ScreenSpec): void {
  const flex = l.cols.map((c, i) => (c.w === null ? i : -1)).filter((i) => i >= 0);
  if (flex.length === 0 && l.cols.length) l.cols[l.cols.length - 1].w = null;
  if (flex.length > 1) for (const i of flex.slice(0, -1)) l.cols[i].w = colMin(l.cols[i], spec);
}

/** 빈 칸 · 빈 열을 접는다 — 칸이 하나 남은 열은 높이 비율을 지운다. */
function collapse(l: Layout, spec: ScreenSpec): void {
  for (const c of l.cols) {
    c.rows = c.rows.filter((a) => a.tabs.length > 0);
    if (c.rows.length === 1) delete c.rows[0].h;
    if (c.rows.length === 2 && c.rows[1].h === undefined) c.rows[1].h = H_NEW;
  }
  l.cols = l.cols.filter((c) => c.rows.length > 0);
  oneFlex(l, spec);
}

/** 판이 있는 자리. 닫혀 있거나 없으면 null. */
export function locate(layout: Layout, id: string): { col: number; row: number; index: number } | null {
  for (let c = 0; c < layout.cols.length; c++) {
    for (let r = 0; r < layout.cols[c].rows.length; r++) {
      const i = layout.cols[c].rows[r].tabs.indexOf(id);
      if (i >= 0) return { col: c, row: r, index: i };
    }
  }
  return null;
}

export type ReadResult = { layout: Layout; notes: string[]; fallback: boolean };

/**
 * 저장된 배치 읽기 — 꼴이 무너졌으면 처음 배치 + 사유(`fallback`) · 내용이 틀렸으면 고쳐 읽고 사유(`notes`). 저장이 없으면(null) 처음 배치 · 사유 없음.
 * 사유 글은 조각이다(머리 문장은 부르는 쪽이 붙인다 — 저장 · 가져오기가 다르게 말한다). 자리는 ★저장된 꼴의 자리★로 말한다.
 */
export function readLayout(raw: unknown, spec: ScreenSpec): ReadResult {
  const fail = (why: string): ReadResult => ({ layout: defaultLayout(spec), notes: [why], fallback: true });
  if (raw === null || raw === undefined) return { layout: defaultLayout(spec), notes: [], fallback: false };
  let v: unknown = raw;
  if (typeof raw === "string") {
    try { v = JSON.parse(raw); } catch { return fail("JSON 꼴이 아닙니다."); }
  }
  if (!isObj(v)) return fail("배치 꼴이 아닙니다.");
  if (v.v !== 1) return fail(v.v === undefined ? "꼴 판(v)이 없습니다." : `꼴 판(v${String(v.v)})을 읽지 못합니다.`);
  if (v.screen !== spec.screen) return fail(`다른 화면(‘${String(v.screen)}’)의 배치입니다.`);
  const cols = v.cols;
  if (!Array.isArray(cols) || cols.length < 1 || cols.length > MAX_COLS) return fail(`열은 1 ~ 3개여야 합니다(받은 수 ${Array.isArray(cols) ? cols.length : 0}).`);
  for (const c of cols) {
    if (!isObj(c) || !Array.isArray(c.rows) || c.rows.length < 1 || c.rows.length > MAX_ROWS) return fail("칸은 열마다 1 ~ 2개여야 합니다.");
    for (const a of c.rows) {
      if (!isObj(a) || !Array.isArray(a.tabs) || !a.tabs.every((t) => typeof t === "string") || typeof a.active !== "string") return fail("칸의 꼴(탭 · 앞 탭)이 틀립니다.");
    }
  }
  const notes: string[] = [];
  const known = new Set(spec.panels.map((p) => p.id));
  const seen = new Set<string>();
  const rawCols = cols as Record<string, unknown>[];
  // 사유의 자리 이름은 ★저장된 꼴의 자리★(접기 전)로 — 사용자가 남긴 배치를 가리킨다
  const asStored: Layout = { v: 1, screen: spec.screen, closed: [], cols: rawCols.map((c) => ({ w: null, rows: c.rows as Area[] })) };
  const colName = (i: number) => areaName({ ...asStored, cols: asStored.cols.map((c) => ({ ...c, rows: c.rows.slice(0, 1) })) }, i, 0);
  const badWidth = new Set<number>();
  const shaped: Col[] = rawCols.map((c, ci) => {
    const rows = (c.rows as Record<string, unknown>[]).map((a, ri) => {
      const tabs: string[] = [];
      for (const t of a.tabs as string[]) {
        if (!known.has(t)) { notes.push(`모르는 판 ‘${t}’를 뺐습니다.`); continue; }
        if (seen.has(t)) { notes.push(`겹친 판 ‘${nameOf(spec, t)}’의 뒤 자리를 뺐습니다.`); continue; }
        seen.add(t);
        tabs.push(t);
      }
      let active = a.active as string;
      if (tabs.length && !tabs.includes(active)) {
        notes.push(`앞 탭이 그 칸에 없어 첫 탭으로 고쳤습니다(${areaName(asStored, ci, ri)}).`);
        active = tabs[0];
      }
      const area: Area = { tabs, active: tabs.length ? active : "" };
      if (ri === 1) area.h = a.h as number;          // 위 칸의 h 는 쓰지 않는다(읽지 않음)
      return area;
    });
    const w = c.w;
    if (w === null) return { w: null, rows };
    if (typeof w === "number" && Number.isFinite(w) && w > 0) return { w, rows };
    badWidth.add(ci);
    return { w: 0, rows };
  });
  // 닫힌 판
  const closed: string[] = [];
  const closedRaw = v.closed;
  if (closedRaw !== undefined && !Array.isArray(closedRaw)) notes.push("닫힌 판 목록의 꼴이 틀려 비웠습니다.");
  const toFirst: string[] = [];
  for (const t of Array.isArray(closedRaw) ? closedRaw : []) {
    if (typeof t !== "string" || !known.has(t)) { notes.push(`모르는 판 ‘${String(t)}’를 뺐습니다.`); continue; }
    if (seen.has(t)) { notes.push(`겹친 판 ‘${nameOf(spec, t)}’의 뒤 자리를 뺐습니다.`); continue; }
    seen.add(t);
    if (!panelOf(spec, t)!.closable) { notes.push(`닫을 수 없는 판 ‘${nameOf(spec, t)}’${eul(nameOf(spec, t))} 첫 칸에 다시 열었습니다.`); toFirst.push(t); continue; }
    closed.push(t);
  }
  // 빠진 판 — 닫기 있는 판은 닫힌 판으로 · 닫기 없는 판은 첫 칸에
  for (const p of spec.panels) {
    if (seen.has(p.id)) continue;
    if (p.closable) { notes.push(`빠진 판 ‘${p.name}’${eul(p.name)} 닫힌 판으로 두었습니다.`); closed.push(p.id); }
    else { notes.push(`빠진 판 ‘${p.name}’${eul(p.name)} 첫 칸에 두었습니다.`); toFirst.push(p.id); }
  }
  if (toFirst.length) {
    const first = shaped.find((c) => c.rows.some((a) => a.tabs.length)) ?? shaped[0];
    const area = first.rows.find((a) => a.tabs.length) ?? first.rows[0];
    area.tabs.push(...toFirst);
    if (!area.tabs.includes(area.active)) area.active = area.tabs[0];
  }
  // 아래 칸 높이 — 두 칸이 모두 남는 열만 본다(빈 칸은 접힌다)
  for (const c of shaped) {
    if (c.rows.length !== 2 || !c.rows[0].tabs.length || !c.rows[1].tabs.length) continue;
    const h = c.rows[1].h;
    if (isH(h)) { c.rows[1].h = quantH(h); continue; }
    const fixed = typeof h === "number" && Number.isFinite(h) ? Math.min(H_MAX, Math.max(H_MIN, quantH(h))) : H_NEW;
    notes.push(`아래 칸 높이를 고쳤습니다(받은 값 ${h === undefined ? "없음" : String(h)} · 고친 값 ${fixed} · 0.2 ~ 0.8 · 0.05 걸음).`);
    c.rows[1].h = fixed;
  }
  // 빈 칸 · 빈 열 접기(자리 이름은 저장된 꼴의 것으로 남겨 둔다)
  const kept: { col: Col; i: number }[] = [];
  shaped.forEach((c, i) => {
    c.rows = c.rows.filter((a) => a.tabs.length > 0);
    if (c.rows.length === 1) delete c.rows[0].h;
    if (c.rows.length) kept.push({ col: c, i });
  });
  if (!kept.length) return fail("남는 판이 없습니다.");
  // 폭 — 양의 수가 아니면 최소 폭 · 남는 폭 열은 정확히 하나
  for (const { col, i } of kept) {
    if (badWidth.has(i)) { notes.push(`열 폭이 양의 수가 아니어서 최소 폭으로 고쳤습니다(${colName(i)}).`); col.w = colMin(col, spec); }
  }
  const flex = kept.filter(({ col }) => col.w === null);
  if (flex.length === 0) { notes.push("남는 폭 열이 없어 마지막 열을 남는 폭으로 했습니다."); kept[kept.length - 1].col.w = null; }
  if (flex.length > 1) {
    const fixed = flex.slice(0, -1);
    for (const { col } of fixed) col.w = colMin(col, spec);
    notes.push(`남는 폭 열이 여럿이라 마지막 하나만 남겼습니다(${fixed.map(({ i }) => colName(i)).join(" · ")}은 최소 폭).`);
  }
  return { layout: { v: 1, screen: spec.screen, cols: kept.map(({ col }) => col), closed }, notes, fallback: false };
}

/** 가져오기 — 사유가 하나라도 있으면 거절(고쳐 읽지 않는다). */
export function strictLayout(raw: unknown, spec: ScreenSpec): { ok: true; layout: Layout } | { ok: false; reasons: string[] } {
  if (raw === null || raw === undefined) return { ok: false, reasons: ["배치가 없습니다."] };
  const r = readLayout(raw, spec);
  return r.notes.length ? { ok: false, reasons: r.notes } : { ok: true, layout: r.layout };
}

export type MoveResult = { ok: true; layout: Layout; at: At } | { ok: false; reason: string };

/** 판을 옮긴다 — 자리(`target`)는 ★옮기기 전 배치의 좌표★다. 판 메뉴와 끌어 놓기가 이 함수 하나를 부른다. */
export function move(layout: Layout, id: string, target: Target, spec: ScreenSpec): MoveResult {
  if (!panelOf(spec, id)) return { ok: false, reason: "모르는 판입니다." };
  if (layout.closed.includes(id)) return { ok: false, reason: "닫힌 판은 옮길 수 없습니다. 먼저 다시 여십시오." };
  const src = locate(layout, id);
  if (!src) return { ok: false, reason: "모르는 판입니다." };
  const l = clone(layout);
  const from = l.cols[src.col].rows[src.row];
  from.tabs.splice(src.index, 1);
  if (from.active === id) from.active = from.tabs[Math.min(src.index, from.tabs.length - 1)] ?? "";
  if (target.kind === "tab") {
    const area = l.cols[target.col]?.rows[target.row];
    if (!area) return { ok: false, reason: "그런 칸이 없습니다." };
    area.tabs.splice(Math.max(0, Math.min(target.index, area.tabs.length)), 0, id);
    area.active = id;
  } else if (target.kind === "col") {
    if (target.index < 0 || target.index > l.cols.length) return { ok: false, reason: "그런 칸이 없습니다." };
    l.cols.splice(target.index, 0, { w: Math.max(panelOf(spec, id)!.min, spec.colNew ?? 0), rows: [{ tabs: [id], active: id }] });
  } else {
    const c = l.cols[target.col];
    if (!c) return { ok: false, reason: "그런 칸이 없습니다." };
    if (c.rows.length !== 1) return { ok: false, reason: "칸은 열마다 둘까지입니다." };
    if (c.rows[0].tabs.length === 0) return { ok: false, reason: "그 칸에는 이 판 하나뿐입니다." };
    const fresh: Area = { tabs: [id], active: id };
    const old = c.rows[0];
    c.rows = target.pos === "top" ? [fresh, { ...old, h: H_NEW }] : [old, { ...fresh, h: H_NEW }];
  }
  collapse(l, spec);
  if (l.cols.length > MAX_COLS) return { ok: false, reason: "열은 셋까지입니다." };
  const at = locate(l, id)!;
  return { ok: true, layout: l, at: { col: at.col, row: at.row } };
}

/** 닫기 — 닫기 있는 판만. 앞 탭이었으면 그 자리의 이웃이 앞 탭. */
export function close(layout: Layout, id: string, spec: ScreenSpec): { ok: true; layout: Layout } | { ok: false; reason: string } {
  const p = panelOf(spec, id);
  if (!p) return { ok: false, reason: "모르는 판입니다." };
  if (!p.closable) return { ok: false, reason: "닫을 수 없는 판입니다." };
  const src = locate(layout, id);
  if (!src) return { ok: false, reason: "닫힌 판입니다." };
  const l = clone(layout);
  const a = l.cols[src.col].rows[src.row];
  a.tabs.splice(src.index, 1);
  if (a.active === id) a.active = a.tabs[Math.min(src.index, a.tabs.length - 1)] ?? "";
  l.closed.push(id);
  collapse(l, spec);
  return { ok: true, layout: l };
}

/** 다시 열기 — 마지막 열의 위 칸 · 앞 탭. */
export function reopen(layout: Layout, id: string, spec: ScreenSpec): MoveResult {
  if (!layout.closed.includes(id)) return { ok: false, reason: "닫힌 판이 아닙니다." };
  void spec;
  const l = clone(layout);
  l.closed = l.closed.filter((x) => x !== id);
  const c = l.cols.length - 1;
  const a = l.cols[c].rows[0];
  a.tabs.push(id);
  a.active = id;
  return { ok: true, layout: l, at: { col: c, row: 0 } };
}

/** 앞 탭 — 그 판이 있는 칸만. 없는 판이면 그대로. */
export function activate(layout: Layout, id: string): Layout {
  const at = locate(layout, id);
  if (!at) return layout;
  const l = clone(layout);
  l.cols[at.col].rows[at.row].active = id;
  return l;
}

/** 배치가 펼쳐지는 데 드는 폭 — 열 최소 폭의 합 + 열 사이 구분선. */
export function needWidth(layout: Layout, spec: ScreenSpec): number {
  return layout.cols.reduce((s, c) => s + colMin(c, spec), 0) + BAR_W * (layout.cols.length - 1);
}

/** 작업 폭에 열이 다 들어가는가. 폭을 모르면(무한) 들어간다고 본다. */
export function fits(layout: Layout, work: number, spec: ScreenSpec): boolean {
  if (!Number.isFinite(work)) return true;
  return needWidth(layout, spec) <= work;
}

/** 그릴 때만 — 들어가지 않으면 오른쪽 열을 앞 열의 위 칸 탭으로 합친다. 받은(저장한) 배치는 그대로 · 합친 열 수를 돌려준다. */
export function fold(layout: Layout, work: number, spec: ScreenSpec): { layout: Layout; folded: number } {
  const l = clone(layout);
  let folded = 0;
  while (l.cols.length > 1 && !fits(l, work, spec)) {
    const last = l.cols.pop()!;
    const prev = l.cols[l.cols.length - 1];
    for (const a of last.rows) prev.rows[0].tabs.push(...a.tabs);
    oneFlex(l, spec);
    folded++;
  }
  return { layout: l, folded };
}

const clampW = (w: number, min: number, max: number): number => Math.round(Math.min(Math.max(min, max), Math.max(min, w)));

/** 그릴 폭 — 고정 폭 열은 왼쪽부터 [최소, 남은 열을 최소로 남긴 최대] 로 · 남는 폭 열은 null(1fr). 저장 폭은 바꾸지 않는다. */
export function colWidths(layout: Layout, work: number, spec: ScreenSpec): (number | null)[] {
  const n = layout.cols.length;
  const avail = Number.isFinite(work) ? work - BAR_W * (n - 1) : Number.POSITIVE_INFINITY;
  const mins = layout.cols.map((c) => colMin(c, spec));
  const out: (number | null)[] = layout.cols.map(() => null);
  for (let i = 0; i < n; i++) {
    const w = layout.cols[i].w;
    if (w === null) continue;
    let rest = 0;
    for (let j = 0; j < n; j++) if (j !== i) rest += out[j] ?? mins[j];
    out[i] = clampW(w, mins[i], avail - rest);
  }
  return out;
}

/** 열 사이 구분선(c | c+1)이 다스리는 열 — 남는 폭 열 쪽을 보는 열. 범위는 남는 폭 열을 그 최소까지 줄인 폭. */
export function colSplit(layout: Layout, c: number, widths: (number | null)[], work: number, spec: ScreenSpec):
  { col: number; side: "start" | "end"; min: number; max: number; value: number } {
  const flex = layout.cols.findIndex((x) => x.w === null);
  const ctrl = flex > c ? c : c + 1;
  const side: "start" | "end" = flex > c ? "start" : "end";
  const n = layout.cols.length;
  let others = 0;
  for (let j = 0; j < n; j++) if (j !== ctrl) others += j === flex ? colMin(layout.cols[j], spec) : (widths[j] ?? colMin(layout.cols[j], spec));
  const min = colMin(layout.cols[ctrl], spec);
  const max = Number.isFinite(work) ? Math.round(work - BAR_W * (n - 1) - others) : Number.POSITIVE_INFINITY;
  return { col: ctrl, side, min, max, value: widths[ctrl] ?? min };
}

/** 칸 사이 구분선의 키 — 값은 아래 칸의 비율. ↑ 넓힘 · ↓ 좁힘 5% · Home 최소 · End 최대. 다른 키는 null. */
export function rowByKey(key: string, h: number): number | null {
  const p = Math.round(h * 100);
  const next = key === "ArrowUp" ? p + 5 : key === "ArrowDown" ? p - 5 : key === "Home" ? H_MIN * 100 : key === "End" ? H_MAX * 100 : null;
  if (next === null) return null;
  return Math.min(H_MAX * 100, Math.max(H_MIN * 100, Math.round(next / 5) * 5)) / 100;
}

/** 칸 사이 구분선 끌기 — 위로 끈 만큼 아래 칸이 넓어진다(열 높이에 대한 비율 · 0.05 걸음 · [0.2, 0.8]). */
export function rowByDrag(h0: number, y0: number, y: number, height: number): number {
  if (!(height > 0)) return h0;
  return Math.min(H_MAX, Math.max(H_MIN, quantH(h0 + (y0 - y) / height)));
}

// ── 이름 붙인 배치 ───────────────────────────────────────────────────────────

/** 이름 검사 — 앞뒤 빈칸을 빼고 1 ~ 20자 · 제어 문자 없음. 맞으면 null. */
export function checkName(name: string): string | null {
  const t = name.trim();
  if (!t) return "이름을 적으십시오.";
  if ([...t].length > NAME_MAX) return "이름은 20자까지입니다.";
  if (/[\u0000-\u001f\u007f]/.test(t)) return "이름에 쓸 수 없는 글자가 있습니다.";
  return null;
}

export type NamedResult = { ok: true; items: Named[] } | { ok: false; reason: string };

/** 지금 배치에 이름을 붙여 남긴다 — 같은 이름은 바꾸고(자리 그대로) · 새 이름은 뒤에 · 8개 넘으면 거절. */
export function saveNamed(items: Named[], name: string, layout: Layout): NamedResult {
  const why = checkName(name);
  if (why) return { ok: false, reason: why };
  const t = name.trim();
  const i = items.findIndex((x) => x.name === t);
  if (i >= 0) return { ok: true, items: items.map((x, j) => (j === i ? { name: t, layout: clone(layout) } : x)) };
  if (items.length >= MAX_NAMED) return { ok: false, reason: "이름 붙인 배치는 8개까지입니다. 하나를 지운 뒤 저장하십시오." };
  return { ok: true, items: [...items, { name: t, layout: clone(layout) }] };
}

export function renameNamed(items: Named[], from: string, to: string): NamedResult {
  const why = checkName(to);
  if (why) return { ok: false, reason: why };
  const t = to.trim();
  if (t !== from && items.some((x) => x.name === t)) return { ok: false, reason: "같은 이름의 배치가 있습니다." };
  if (!items.some((x) => x.name === from)) return { ok: false, reason: "그런 이름의 배치가 없습니다." };
  return { ok: true, items: items.map((x) => (x.name === from ? { name: t, layout: x.layout } : x)) };
}

export const removeNamed = (items: Named[], name: string): Named[] => items.filter((x) => x.name !== name);

/** 저장된 이름 붙인 배치 읽기 — 읽지 못한 줄은 빼고 사유 · 고쳐 읽은 줄은 남기고 사유. */
export function readSaved(raw: string | null, spec: ScreenSpec): { items: Named[]; notes: string[] } {
  if (raw === null || raw === undefined) return { items: [], notes: [] };
  let v: unknown;
  try { v = JSON.parse(raw); } catch { return { items: [], notes: ["이름 붙인 배치를 읽지 못했습니다(JSON 꼴이 아닙니다)."] }; }
  if (!isObj(v) || v.v !== 1 || !Array.isArray(v.items)) return { items: [], notes: ["이름 붙인 배치의 꼴이 틀려 쓰지 않았습니다."] };
  if (v.screen !== spec.screen) return { items: [], notes: [`다른 화면(‘${String(v.screen)}’)의 이름 붙인 배치라 쓰지 않았습니다.`] };
  const items: Named[] = [];
  const notes: string[] = [];
  for (const it of v.items) {
    if (!isObj(it) || typeof it.name !== "string" || checkName(it.name) || items.some((x) => x.name === (it.name as string).trim())) {
      notes.push("이름 붙인 배치 하나의 이름이 맞지 않아 뺐습니다.");
      continue;
    }
    const name = it.name.trim();
    const r = readLayout(it.layout ?? null, spec);
    if (r.fallback || it.layout === undefined || it.layout === null) { notes.push(`이름 붙인 배치 ‘${name}’${eul(name)} 읽지 못해 뺐습니다.`); continue; }
    if (r.notes.length) notes.push(`이름 붙인 배치 ‘${name}’${eul(name)} 고쳐 읽었습니다: ${r.notes.join(" ")}`);
    if (items.length >= MAX_NAMED) { notes.push("이름 붙인 배치가 8개를 넘어 뒤의 것을 뺐습니다."); break; }
    items.push({ name, layout: r.layout });
  }
  return { items, notes };
}

/** 이름 붙인 배치의 저장 꼴. */
export const savedText = (spec: ScreenSpec, items: Named[]): string => JSON.stringify({ v: 1, screen: spec.screen, items });

// ── 파일 ────────────────────────────────────────────────────────────────────

/** 내보내기 — 지금 배치 + 이름 붙인 배치. 판의 자리 · 열 폭 · 칸 높이 · 이름 붙인 배치의 이름만(계좌 · 종목 · 설정 없음 — 화면 시험이 건다). */
export function exportFile(spec: ScreenSpec, current: Layout, saved: Named[]): string {
  return `${JSON.stringify({ kind: FILE_KIND, v: 1, screen: spec.screen, current, saved }, null, 1)}\n`;
}

export type ImportResult = { ok: true; current: Layout; saved: Named[] } | { ok: false; reasons: string[] };
export const TOO_BIG = "파일이 64KB를 넘습니다.";

/** 가져오기 — 엄격: 사유가 하나라도 있으면 거절(지금 배치 그대로). 통과하면 이름 붙인 배치를 이름으로 합친다(파일이 이김). */
export function importFile(text: string, spec: ScreenSpec, existing: Named[]): ImportResult {
  if (new TextEncoder().encode(text).length > FILE_MAX) return { ok: false, reasons: [TOO_BIG] };
  let v: unknown;
  try { v = JSON.parse(text); } catch { return { ok: false, reasons: ["파일이 JSON 꼴이 아닙니다."] }; }
  if (!isObj(v) || v.kind !== FILE_KIND) return { ok: false, reasons: ["이 도구가 내보낸 배치 파일이 아닙니다."] };
  if (v.v !== 1) return { ok: false, reasons: [`파일의 꼴 판(v${String(v.v)})을 읽지 못합니다.`] };
  if (v.screen !== spec.screen) return { ok: false, reasons: [`다른 화면(‘${String(v.screen)}’)의 배치 파일입니다.`] };
  const reasons: string[] = [];
  const cur = strictLayout(v.current, spec);
  if (!cur.ok) reasons.push(...cur.reasons.map((r) => `지금 배치: ${r}`));
  const list = Array.isArray(v.saved) ? v.saved : null;
  if (!list) reasons.push("이름 붙인 배치 목록의 꼴이 틀립니다.");
  const incoming: Named[] = [];
  for (const it of list ?? []) {
    if (!isObj(it) || typeof it.name !== "string") { reasons.push("이름 붙인 배치 하나의 꼴이 틀립니다."); continue; }
    const why = checkName(it.name);
    if (why) { reasons.push(`이름 ‘${it.name}’: ${why}`); continue; }
    const name = it.name.trim();
    if (incoming.some((x) => x.name === name)) { reasons.push(`파일 안에 같은 이름(‘${name}’)이 둘 있습니다.`); continue; }
    const r = strictLayout(it.layout, spec);
    if (!r.ok) { reasons.push(...r.reasons.map((x) => `‘${name}’: ${x}`)); continue; }
    incoming.push({ name, layout: r.layout });
  }
  if (reasons.length || !cur.ok) return { ok: false, reasons };
  const merged = existing.map((x) => incoming.find((y) => y.name === x.name) ?? x);
  for (const y of incoming) if (!merged.some((x) => x.name === y.name)) merged.push(y);
  if (merged.length > MAX_NAMED) return { ok: false, reasons: [`합치면 이름 붙인 배치가 ${merged.length}개라 8개를 넘습니다.`] };
  return { ok: true, current: cur.layout, saved: merged };
}
