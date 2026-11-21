"use client";
/**
 * 차트 읽는 줄 — 값은 호버가 아니라 ★늘 보이는 줄★에 (2026-11-10 · ADR 004 §2.4)
 * ==========================================================================
 * 호버 툴팁은 터치·키보드로 읽을 수 없고(ADR 003 §2.4 "툴팁 금지") 스크린 리더에도 없다. 그래서 차트마다 셋을 둔다:
 *   · 읽는 줄(`.cr-read` · `aria-live`) — 고른 자리의 머리(날짜·이름)와 값들. 처음 자리는 부르는 쪽이 정한다(보통 마지막 점).
 *   · 키보드 — ←→ Home End (`useReadout` 의 `onKeyDown` 을 포커스 가능한 틀에 단다)
 *   · 표 쌍둥이(`details.cr-table`) — 그림이 보여 주는 값 ★전부★(솎지 않는다)
 * 글자는 부르는 쪽이 서버 값을 서식해 넘긴다 — 여기서는 셈하지 않는다.
 * ★이 파일은 차트 라이브러리를 import 하지 않는다★(경계 규칙 — `eslint.config.js` 의 `no-restricted-imports`).
 */
import { useCallback, useState, type KeyboardEvent, type ReactNode } from "react";

export interface ReadCell { key: string; label: string; text: string; /** 선 색(범례 구실) — 없으면 표식 없이 글자만 */ color?: string }
export interface ReadRow { head: string; cells: ReadCell[] }

/** 읽는 줄의 자리. `initial` 이 없으면 마지막 점. 자료 수가 바뀌어도 범위 안으로 자른다(없는 자리를 가리키지 않는다). */
export function useReadout(n: number, initial?: number) {
  const [picked, setPicked] = useState<number | null>(null);
  const idx = n <= 0 ? -1 : Math.min(n - 1, Math.max(0, picked ?? initial ?? n - 1));
  const setIdx = useCallback((i: number) => setPicked(i), []);
  const onKeyDown = (e: KeyboardEvent) => {
    if (n <= 0) return;
    const to = e.key === "ArrowLeft" ? idx - 1 : e.key === "ArrowRight" ? idx + 1 : e.key === "Home" ? 0 : e.key === "End" ? n - 1 : null;
    if (to === null) return;
    e.preventDefault();
    setPicked(Math.min(n - 1, Math.max(0, to)));
  };
  return { idx, setIdx, onKeyDown };
}

/** 읽는 줄 — 값이 없으면 빈칸이 아니라 그렇다고 말한다. */
export function ReadLine({ row, empty = "값 없음" }: { row: ReadRow | null; empty?: string }) {
  return (
    <p className="cr-read" aria-live="polite">
      {row ? (
        <>
          <b className="cr-head">{row.head}</b>
          {row.cells.map((c) => (
            <span key={c.key} className="cr-item">
              {c.color && <i className="cr-key" style={{ borderTopColor: c.color }} aria-hidden="true" />}
              {c.label} <b>{c.text}</b>
            </span>
          ))}
        </>
      ) : empty}
    </p>
  );
}

/** 표 쌍둥이 — 줄마다 머리 + 값들. 열은 첫 줄의 칸에서 온다(모든 줄이 같은 칸을 갖는다 — 부르는 쪽 약속). */
export function TableTwin({ headLabel, rows }: { headLabel: string; rows: ReadRow[] }) {
  if (!rows.length) return null;
  const cols = rows[0].cells;
  return (
    <details className="cr-table">
      <summary>표로 보기</summary>
      <div className="cr-scroll">
        <table className="pg-table">
          <thead><tr><th>{headLabel}</th>{cols.map((c) => <th key={c.key} className="pg-td-num">{c.label}</th>)}</tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={`${r.head}-${i}`}>
                <td>{r.head}</td>
                {cols.map((c, j) => <td key={c.key} className="pg-td-num">{r.cells[j]?.text ?? ""}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

/**
 * 그림(자식) + 읽는 줄 + 표 쌍둥이를 한 틀로 — 차트 라이브러리로 그린 그림에 쓴다(직접 SVG 그림은 svg 가 포커스를 받는다).
 * 틀이 포커스를 받고 ←→ Home End 로 자리를 옮긴다. 틀 안의 다른 조작부(표 펼치기)에서 누른 키는 가로채지 않는다.
 * `id` 는 `data-chart` 로 나간다(E2E 가 그림을 가리키는 이름).
 */
export function ReadoutFrame({ id, label, headLabel, rows, idx, onKeyDown, table = true, children }: {
  id: string; label: string; headLabel: string; rows: ReadRow[]; idx: number;
  onKeyDown: (e: KeyboardEvent) => void;
  /** false = 표 쌍둥이를 달지 않는다 — ★그 절에 같은 값을 다 적은 표가 이미 있을 때만★(겹쳐 달지 않는다). */
  table?: boolean; children: ReactNode;
}) {
  return (
    <div className="cr" data-chart={id} role="group" tabIndex={0} aria-label={`${label}. 화살표 키로 이동해 값을 읽습니다.`}
         onKeyDown={(e) => { if (e.target === e.currentTarget) onKeyDown(e); }}>
      {children}
      <ReadLine row={idx >= 0 ? rows[idx] ?? null : null} />
      {table && <TableTwin headLabel={headLabel} rows={rows} />}
    </div>
  );
}

/**
 * recharts 2.x 차트 이벤트(`onMouseMove` 의 첫 인자)에서 자리를 꺼낸다 — ★이 모양을 아는 한 곳★(ADR 004 §2.5 · 아래 `xFromChartEvent` 도 여기).
 * `<Tooltip>` 이 없어도 차트는 포인터 아래 자리를 `activeTooltipIndex` 로 알려 준다. 라이브러리를 올리거나 바꾸면 여기만 고친다.
 */
export function idxFromChartEvent(state: unknown): number | null {
  const i = (state as { activeTooltipIndex?: unknown } | null | undefined)?.activeTooltipIndex;
  return typeof i === "number" && Number.isFinite(i) && i >= 0 ? i : null;
}

/** 같은 이벤트에서 포인터의 가로 자리(차트 왼쪽 끝에서 px)를 꺼낸다 — 가로가 숫자 축이라 자리 번호가 오지 않는 그림에서 쓴다. */
export function xFromChartEvent(state: unknown): number | null {
  const x = (state as { chartX?: unknown } | null | undefined)?.chartX;
  return typeof x === "number" && Number.isFinite(x) ? x : null;
}

/** 차트 `onMouseMove` 에 다는 것 — 포인터 아래 자리로 읽는 줄을 옮긴다(자리가 없으면 그대로 둔다). */
export const followChart = (setIdx: (i: number) => void) => (state: unknown): void => {
  const i = idxFromChartEvent(state);
  if (i !== null) setIdx(i);
};
