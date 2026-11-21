"use client";
/**
 * 공용 표 (U1 · ADR 007 §5) — 낱 `<table>` 하나를 밀도 토큰으로 그린다
 * ==========================================================================
 * 규칙은 `table.ts`(순수) 한 곳이고 이 파일은 그리기와 줄 초점만 맡는다. 정렬 · 쪽 · 고른 줄의 ★상태는 부르는 쪽★이 든다
 * (저장 · 요청과 얽혀 있어서다) — 표는 받은 줄을 받은 순서대로 그린다.
 *
 *  · 표의 뜻은 표 그대로다: `<th scope="col">` · 표 이름(`aria-label`) · 정렬 머리의 `aria-sort`. 격자 역할(`role="grid"`)은 쓰지 않는다
 *    — 칸 단위 조작이 없다(설계 §5.1).
 *  · 줄 초점: 고를 수 있는 표(`onSelect`)의 줄은 ★하나만 탭 순서★에 있고(나머지는 -1) ↑ ↓ Home End PageUp PageDown 이 초점을 옮긴다.
 *    Enter · Space · 누르기가 고른다. 칸 안의 단추에서 난 키는 건드리지 않는다. 고른 줄은 `aria-current`(줄 전체의 바탕).
 *    `followFocus` 는 상세 판이 옆에 열려 있을 때 쓴다 — 고른 줄이 있으면 초점이 옮겨 간 줄을 곧바로 고른다(줄을 넘기며 견준다).
 *    고른 줄이 없으면(판이 닫혀 있으면) 초점만 옮긴다.
 *  · 값이 없는 칸은 `Na`(`N/A`)이고 사유는 `note`(표 아래 보이는 한 줄 · 표의 설명으로 이어짐)에 한 번 적는다 — 칸마다 되풀이하지 않는다.
 *  · 클래스: 새 구조는 `tx-table*`. 화면이 스펙과 맺은 옛 클래스는 `className` · `rowClassName` · 열의 `className` 으로 같은 요소에 남긴다.
 *  · 붙는 열(`sticky`)은 앞에서부터 이어진 열만 · 마지막 붙는 열을 뺀 열은 `width`(px)를 준다(왼쪽 자리 = 앞 열 폭의 합).
 */
import { useId, useRef, useState, type CSSProperties, type KeyboardEvent, type ReactNode, type Ref } from "react";
import { UNKNOWN_TEXT, num } from "@/shared/lib/krFormat";
import { ariaSort, pageNumbers, rowByKey, type SortState } from "./table";

export interface Column<T> {
  id: string;
  /** 머리에 보이는 글자 — 단위는 여기에 적는다(칸마다 되풀이하지 않는다). */
  header: string;
  /** 머리 글자를 낭독기에만 남긴다(동작 열). */
  headerHidden?: boolean;
  /** 수 칸 — 오른쪽 맞춤 + 고정폭 숫자. */
  num?: boolean;
  sortable?: boolean;
  /** 가로로 구를 때 왼쪽에 붙는다. */
  sticky?: boolean;
  /** 열의 폭(px) — 붙는 열의 자리 계산에 쓴다. */
  width?: number;
  /** 남는 폭을 먹는 열(하나만) — 열이 적을 때 이름과 수가 멀어지지 않게 한다. */
  fill?: boolean;
  /** 머리 칸과 몸 칸에 함께 붙는 클래스(화면의 계약 클래스). */
  className?: string;
  /** `index` 는 받은 줄 안의 자리(0부터)다. */
  cell: (row: T, index: number) => ReactNode;
}

export interface DataTableProps<T> {
  /** 표 이름 — 낭독기가 표를 고를 때 읽는다. */
  label: string;
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  sort?: SortState | null;
  onSort?: (col: string) => void;
  selectedKey?: string | null;
  onSelect?: (key: string, row: T) => void;
  followFocus?: boolean;
  /** 표 아래 보이는 한 줄(값 없음의 사유 등). 표의 설명으로 이어진다. */
  note?: ReactNode;
  className?: string;
  wrapClassName?: string;
  /** 구르는 상자 — 쪽을 넘긴 뒤 맨 위로 올릴 때 쓴다. */
  wrapRef?: Ref<HTMLDivElement>;
  rowClassName?: string;
  rowAttrs?: (row: T) => Record<string, string>;
}

/** 칸 안의 조작 요소 — 여기서 난 누르기는 줄을 고르지 않는다. */
const INNER = "button, a, input, select, textarea, label, summary";

function colClass<T>(c: Column<T>): string {
  return [c.num ? "num" : "", c.sticky ? "tx-col-sticky" : "", c.fill ? "tx-col-fill" : "", c.className ?? ""].filter(Boolean).join(" ");
}

/** 붙는 열의 왼쪽 자리(`--tx-col-left`) — 앞에 있는 붙는 열의 폭을 더한다. 붙일지는 CSS 가 정한다(좁은 화면에서는 붙이지 않는다). */
function stickyStyles<T>(columns: Column<T>[]): (CSSProperties | undefined)[] {
  let left = 0;
  return columns.map((c) => {
    if (!c.sticky && c.width === undefined) return undefined;
    const s: CSSProperties = {};
    if (c.width !== undefined) { s.width = c.width; s.minWidth = c.width; }
    if (c.sticky) { (s as Record<string, string>)["--tx-col-left"] = `${left}px`; left += c.width ?? 0; }
    return s;
  });
}

export function DataTable<T>({
  label, columns, rows, rowKey, sort = null, onSort, selectedKey = null, onSelect, followFocus = false, note, className, wrapClassName, wrapRef, rowClassName, rowAttrs,
}: DataTableProps<T>) {
  const noteId = useId();
  const body = useRef<HTMLTableSectionElement>(null);
  const [focusKey, setFocusKey] = useState<string | null>(null);
  const keys = rows.map(rowKey);
  // 탭 순서에 둘 줄 하나: 마지막으로 초점이 있던 줄 → 고른 줄 → 첫 줄(줄이 바뀌어 사라졌으면 다음 후보로).
  const tabKey = focusKey !== null && keys.includes(focusKey) ? focusKey : selectedKey !== null && keys.includes(selectedKey) ? selectedKey : keys[0] ?? null;
  const styles = stickyStyles(columns);

  const onRowKey = (e: KeyboardEvent<HTMLTableRowElement>, index: number, row: T) => {
    if (e.target !== e.currentTarget || !onSelect) return;               // 칸 안의 단추 · 입력에서 난 키는 그쪽 것이다
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(keys[index], row); return; }
    const to = rowByKey(e.key, index, rows.length);
    if (to === null) return;
    e.preventDefault();
    if (to === index) return;
    (body.current?.rows[to] as HTMLTableRowElement | undefined)?.focus();
    if (followFocus && selectedKey !== null) onSelect(keys[to], rows[to]);
  };

  return (
    <>
      <div ref={wrapRef} className={`tx-table-wrap${wrapClassName ? ` ${wrapClassName}` : ""}`}>
        <table className={`tx-table${className ? ` ${className}` : ""}`} aria-label={label} aria-describedby={note ? noteId : undefined}>
          <thead>
            <tr>
              {columns.map((c, i) => {
                const sortable = !!c.sortable && !!onSort;
                const dir = sortable && sort?.col === c.id ? sort.dir : null;
                return (
                  <th key={c.id} scope="col" className={colClass(c) || undefined} style={styles[i]} aria-sort={ariaSort(sortable, c.id, sort)}>
                    {sortable ? (
                      <button type="button" className="tx-th-sort" onClick={() => onSort!(c.id)}>
                        {c.header}{dir ? <span className="tx-th-arrow" aria-hidden="true">{dir === "desc" ? "▼" : "▲"}</span> : null}
                      </button>
                    ) : c.headerHidden ? <span className="tx-sr">{c.header}</span> : c.header}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody ref={body}>
            {rows.map((row, index) => {
              const key = keys[index];
              return (
                <tr key={key} className={rowClassName} data-row={key} {...rowAttrs?.(row)}
                    aria-current={selectedKey === key ? "true" : undefined}
                    tabIndex={onSelect ? (key === tabKey ? 0 : -1) : undefined}
                    onClick={onSelect ? (e) => { if (!(e.target as HTMLElement).closest(INNER)) onSelect(key, row); } : undefined}
                    onFocus={onSelect ? (e) => { if (e.target === e.currentTarget) setFocusKey(key); } : undefined}
                    onKeyDown={onSelect ? (e) => onRowKey(e, index, row) : undefined}>
                  {columns.map((c, i) => <td key={c.id} className={colClass(c) || undefined} style={styles[i]}>{c.cell(row, index)}</td>)}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {note ? <p className="tx-table-note" id={noteId}>{note}</p> : null}
    </>
  );
}

/** 값이 없는 칸 — `N/A`. 0 · 빈칸 · 줄표로 그리지 않는다('미상 ≠ 0'). 사유는 표의 `note` 에 한 번 적는다. */
export function Na() {
  return <span className="tx-na">{UNKNOWN_TEXT}</span>;
}

/** 값 + 그 아래 가는 막대(0 ~ 1). 막대는 장식이 아니라 같은 열 안에서의 자리다 — 한 색 · 낭독기에는 값만 읽힌다. `ratio` 가 없으면 막대를 그리지 않는다. */
export function BarValue({ ratio, children }: { ratio: number | null; children: ReactNode }) {
  const pct = ratio === null || !Number.isFinite(ratio) ? null : Math.round(Math.max(0, Math.min(1, ratio)) * 100);
  return (
    <span className="tx-bar">
      <span className="tx-bar-v">{children}</span>
      {pct === null ? null : <span className="tx-bar-fill" aria-hidden="true" style={{ width: `${pct}%` }} />}
    </span>
  );
}

/** 쪽 넘김 — 이전 · 쪽 번호(첫 쪽 · 끝 쪽 · 지금 쪽 둘레) · 다음 · 줄의 범위. `page` 는 0부터. 한 쪽뿐이면 부르는 쪽이 그리지 않는다. */
export function Pager({ label, page, count, total, size, onPage, className }: {
  label: string; page: number; count: number; total: number; size: number; onPage: (page: number) => void; className?: string;
}) {
  return (
    <nav className={`tx-pager${className ? ` ${className}` : ""}`} aria-label={label}>
      <button type="button" onClick={() => onPage(page - 1)} disabled={page <= 0}>이전</button>
      {pageNumbers(count, page).map((n, i) => n === null
        ? <span key={`gap${i}`} aria-hidden="true">…</span>
        : <button type="button" key={n} className={n === page ? "on" : undefined} aria-current={n === page ? "page" : undefined} onClick={() => onPage(n)}>{n + 1}</button>)}
      <button type="button" onClick={() => onPage(page + 1)} disabled={page >= count - 1}>다음</button>
      <span className="tx-pager-range">{num(page * size + 1)} ~ {num(Math.min(total, (page + 1) * size))} / {num(total)}</span>
    </nav>
  );
}
