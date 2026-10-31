/**
 * 그림(PNG) 내보내기 규칙 (CF 3부 R7 — 사용자 결정 7 · 2026-10-31 "그래프 전체 · 쓴 글자 범위만 글꼴 · 띠 = 이름·때 + 결과의 성격")
 * ==========================================================================
 * 순수 규칙만 둔다(시험이 직접 부른다) — 크기 · 파일 이름 · 띠 문장 · 거를 것 · 글꼴 고르기. 찍기(html-to-image)는 `features/portfolio-graph-io/exportPng`.
 * ★그림은 캔버스 밖으로 돌아다닌다★ — 띠가 그 그림이 무엇인지(이름·때)와 결과의 성격(연습용 · 예전 결과 · 계산 전)을 말한다. '실데이터'라고 쓰지 않는다.
 */
import { exportFileName } from "./format";

export interface Bounds { x: number; y: number; width: number; height: number }

/** 경계 둘레 여백(캔버스 좌표). */
export const EXPORT_PAD = 40;
/** 마지막 그림의 긴 변 상한(픽셀) — 메신저·문서에 붙여도 무겁지 않게. */
export const EXPORT_MAX_PX = 4096;
/** 작은 그래프는 2배로(글자가 선명하게). */
const EXPORT_SHARP = 2;

/** 그림에 넣지 않는 겹침 — 문서가 아니거나(유령·초안) 손으로 고치는 도구(안내선·단계 띠·도구줄·꺾는 점·손잡이·알약). */
export const EXPORT_SKIP = ["pg-ghosts", "pg-drafts", "pg-guides", "pg-lanes", "pg-edge-tb", "react-flow__node-toolbar", "pg-waypoint",
                            "react-flow__resize-control", "pg-node-resize", "pg-wire-type", "pg-slot-grip"];
/** 찍는 동안 떼었다가 되돌리는 화면 상태 — 고름 · 흐림 · 원인 길 · 끌어 넣기 빛(같은 문서면 같은 그림). */
export const EXPORT_VIEW_STATE = ["selected", "pg-node--selected", "pg-wire--picked", "pg-dim", "pg-edge--faint", "pg-on-path", "pg-edge--path",
                                  "pg-on-cause", "pg-cause-root", "pg-edge--cause", "pg-group--drop", "pg-wire--drop"];

/** 경계 → 그림 크기와 변환. 픽셀/캔버스 = min(2, 상한 ÷ 긴 변) — 작은 그래프는 2배 선명, 큰 그래프는 긴 변이 상한에 맞는다. */
export function exportSize(b: Bounds): { w: number; h: number; scale: number; x: number; y: number } {
  const bw = b.width + 2 * EXPORT_PAD, bh = b.height + 2 * EXPORT_PAD;
  const scale = Math.min(EXPORT_SHARP, EXPORT_MAX_PX / Math.max(bw, bh));
  return { w: Math.round(bw * scale), h: Math.round(bh * scale), scale, x: (EXPORT_PAD - b.x) * scale, y: (EXPORT_PAD - b.y) * scale };
}

/** 띠 글자 크기(픽셀) — 그림이 크게 줄어도 읽을 수 있게 1배 아래로 줄이지 않는다. */
export const bandMetrics = (scale: number) => {
  const s = Math.max(1, scale);
  return { font: 13 * s, line: 20 * s, pad: 12 * s };
};
export function bandHeight(lines: number, scale: number): number {
  const m = bandMetrics(scale);
  return Math.round(m.pad * 2 + lines * m.line);
}

export function pngFileName(name: string | undefined, now = new Date()): string {
  return exportFileName(name, now).replace(/\.json$/, ".png");
}

const two = (v: number) => String(v).padStart(2, "0");
/** 띠 문장 — 늘 이름·때, 있을 때만 결과의 성격. */
export function captionLines(r: { name?: string; now: Date; computed: boolean; practice: boolean; stale: boolean }): string[] {
  const d = r.now;
  const when = `${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())} ${two(d.getHours())}:${two(d.getMinutes())}`;
  const out = [`‘${r.name || "이름 없는 설계"}’ · ${when} 내보냄`];
  if (!r.computed) out.push("계산 전이에요 — 카드에 결과가 없어요");
  if (r.computed && r.practice) out.push("연습용(합성) 데이터로 계산한 결과예요 — 실제 시세가 아니에요");
  if (r.computed && r.stale) out.push("바꾼 뒤 다시 계산하지 않은 예전 결과가 섞여 있어요");
  return out;
}
/** 받은 뒤 알림 — 띠에 적은 성격을 그대로 말한다(띠는 그림 안이라 화면에서 다시 알린다). */
export function exportNote(lines: string[]): string {
  const nature = lines.slice(1);
  return nature.length ? `그림(PNG)을 받았어요. 그림 아래에 적었어요: ${nature.join(" · ")}.` : "그림(PNG)을 받았어요.";
}

/** html-to-image `filter` — 겹침 클래스가 하나라도 있으면 뺀다. */
export function keepForExport(className: string): boolean {
  const cls = className.split(/\s+/);
  return !EXPORT_SKIP.some((c) => cls.includes(c));
}

/** `U+AC00-AC47, U+B000, U+B1??` → [시작, 끝] 목록. 빈 글은 '모든 글자'(null). */
function parseRange(range: string): [number, number][] | null {
  const parts = range.split(",").map((p) => p.trim().replace(/^U\+/i, "")).filter(Boolean);
  if (!parts.length) return null;
  return parts.map((p) => {
    if (p.includes("?")) return [parseInt(p.replace(/\?/g, "0"), 16), parseInt(p.replace(/\?/g, "F"), 16)];
    const [a, b] = p.split("-");
    return [parseInt(a, 16), parseInt(b ?? a, 16)];
  });
}
/** 그림에 쓴 글자가 든 글꼴 조각만(같은 이름의 동적 서브셋이 수십 개라 다 넣으면 느리다). 범위가 없는 글꼴은 늘 넣는다. */
export function pickFontFaces<T extends { unicodeRange: string }>(faces: T[], text: string): T[] {
  const cps = [...new Set(Array.from(text, (ch) => ch.codePointAt(0)!))];
  return faces.filter((f) => {
    const ranges = parseRange(f.unicodeRange);
    return !ranges || cps.some((c) => ranges.some(([a, b]) => c >= a && c <= b));
  });
}
