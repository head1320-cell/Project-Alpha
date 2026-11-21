/**
 * 공용 표의 순수 규칙 (U1 · ADR 007 §5) — 정렬 · 정렬 표시 · 쪽 · 줄 초점 이동 · 내보내기
 * ==========================================================================
 * React 를 들이지 않는다 — 순수 스펙(`e2e/table-logic.spec.ts`)이 브라우저 없이 가져온다. 그리는 쪽은 `DataTable.tsx`.
 *
 *  · ★값이 없는 줄은 어느 방향에서도 끝★ — 미상은 가장 작은 값이 아니다('미상 ≠ 0' · CLAUDE.md §4).
 *    유한한 수만 값이다: 빈 값 · NaN · 무한대 · 글자는 미상으로 본다(글자를 수로 바꿔 읽지 않는다 — 지어내지 않는다).
 *  · 같은 값 · 값 없는 줄끼리는 들어온 순서 그대로(안정 정렬) — 서버가 준 순서가 두 번째 열쇠다.
 *  · 줄 초점은 끝에서 멈춘다(돌아가지 않는다) — 줄을 넘기며 견주는 사람이 끝을 안다.
 */

export type SortDir = "asc" | "desc";
export interface SortState { col: string; dir: SortDir }

/** 정렬에 쓰는 수 — 유한한 수가 아니면 null(미상). */
export function sortNumber(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/** 한 열로 정렬한 새 배열. 값이 없는 줄은 어느 방향에서도 끝 · 같은 값은 들어온 순서 그대로. */
export function sortRows<T>(rows: readonly T[], get: (row: T) => unknown, dir: SortDir): T[] {
  return rows
    .map((row, i) => ({ row, i, v: sortNumber(get(row)) }))
    .sort((a, b) => {
      if (a.v === null || b.v === null) return a.v === null && b.v === null ? a.i - b.i : a.v === null ? 1 : -1;
      return (dir === "desc" ? b.v - a.v : a.v - b.v) || a.i - b.i;
    })
    .map((x) => x.row);
}

/** 머리를 눌렀을 때의 다음 정렬 — 같은 열이면 방향을 뒤집고, 다른 열이면 그 열의 내림차순부터. */
export function nextSort(cur: SortState, col: string): SortState {
  return cur.col === col ? { col, dir: cur.dir === "desc" ? "asc" : "desc" } : { col, dir: "desc" };
}

/** 머리 칸의 `aria-sort` — 정렬 중인 열만 방향을 말한다. 정렬할 수 없는 열에는 속성을 달지 않는다(undefined). */
export function ariaSort(sortable: boolean, col: string, sort: SortState | null): "ascending" | "descending" | "none" | undefined {
  if (!sortable) return undefined;
  if (!sort || sort.col !== col) return "none";
  return sort.dir === "asc" ? "ascending" : "descending";
}

/**
 * 저장해 둔 정렬을 되살린다 — 꼴이 맞고(열 이름 · 방향) ★지금 표에서 정렬할 수 있는 열★일 때만. 아니면 기본 정렬.
 * 모르는 열 · 지금 표에 없는 열(표시 열에서 뺐다 · 값이 전부 없어 숨겼다)로 정렬하지 않는다 — 보이지 않는 열의 순서를 지어내지 않는다.
 */
export function restoreSort(raw: unknown, cols: readonly string[], fallback: SortState): SortState {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return fallback;
  const { col, dir } = raw as Record<string, unknown>;
  return typeof col === "string" && cols.includes(col) && (dir === "asc" || dir === "desc") ? { col, dir } : fallback;
}

/** 쪽의 수 — 줄이 없어도 한 쪽이다. */
export function pageCount(total: number, size: number): number {
  return Math.max(1, Math.ceil(total / size));
}

/** 쪽 번호(0부터)를 범위 안으로. 수가 아니면 첫 쪽. */
export function clampPage(page: number, total: number, size: number): number {
  if (!Number.isFinite(page)) return 0;
  return Math.max(0, Math.min(pageCount(total, size) - 1, Math.trunc(page)));
}

/** 그 쪽의 줄(범위 밖의 쪽은 끝 쪽). */
export function pageSlice<T>(rows: readonly T[], page: number, size: number): T[] {
  const p = clampPage(page, rows.length, size);
  return rows.slice(p * size, (p + 1) * size);
}

/** 쪽 단추의 차례 — 첫 쪽 · 끝 쪽 · 지금 쪽 둘레 둘씩, 그 사이는 줄임 하나(null). */
export function pageNumbers(count: number, cur: number): (number | null)[] {
  const out: (number | null)[] = [];
  for (let i = 0; i < count; i++) {
    if (i === 0 || i === count - 1 || Math.abs(i - cur) <= 2) out.push(i);
    else if (out[out.length - 1] !== null) out.push(null);
  }
  return out;
}

/** 키 하나 → 초점이 갈 줄(0부터). 이 표가 다루지 않는 키 · 줄이 없는 표는 null(부르는 쪽이 기본 동작을 막지 않는다). */
export function rowByKey(key: string, index: number, count: number, step = 10): number | null {
  if (count <= 0) return null;
  const to = key === "ArrowDown" ? index + 1 : key === "ArrowUp" ? index - 1 : key === "PageDown" ? index + step : key === "PageUp" ? index - step
    : key === "Home" ? 0 : key === "End" ? count - 1 : null;
  return to === null ? null : Math.max(0, Math.min(count - 1, to));
}

/** 표 계산 프로그램이 식으로 읽는 첫 글자 — 글 칸이 이것으로 시작하면 작은따옴표로 글임을 못 박는다(수 칸은 건드리지 않는다). */
const FORMULA_LEAD = /^[=+\-@\t\r]/;

function csvCell(v: unknown): string {
  if (v === null || v === undefined) return "";                        // 값 없음은 빈칸 — 0 이 아니다
  const s = typeof v === "string" && FORMULA_LEAD.test(v) ? `'${v}` : String(v);
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/** CSV 한 벌 — 맨 앞에 BOM(엑셀이 한글을 읽는다) · 줄은 CRLF · 머리 줄이 첫 줄. */
export function toCsv(header: readonly string[], rows: readonly (readonly unknown[])[]): string {
  return "﻿" + [header, ...rows].map((r) => r.map(csvCell).join(",")).join("\r\n");
}
