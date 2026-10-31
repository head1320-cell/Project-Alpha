"use client";
/**
 * 그림(PNG) 찍기 (CF 3부 R7) — 규칙은 `entities/portfolio-graph/exportImage`, 여기는 화면에서 찍는 일만.
 * ==========================================================================
 * ★html-to-image 는 누를 때 `import()`★ — 캔버스 첫 로드에 넣지 않는다.
 * ★같은 문서면 같은 그림★ — 찍는 동안만 보통 확대 모양(`data-zoom="mid"` · `--pg-z: 1`)으로 두고, 화면 상태 클래스(고름·흐림·원인 길·빛)를 떼었다가
 * `finally` 에서 그대로 되돌린다(`.pg-exporting` 은 그 동안 전환·움직임을 꺼서 중간 모양이 찍히지 않게). 겹침은 `filter` 로 거른다.
 * 글꼴은 그림에 쓴 글자가 든 `@font-face` 조각만 data URL 로 넣는다 — 받지 못한 조각은 세어 돌려준다(말없이 다른 글꼴로 그리지 않는다).
 */
import { bandHeight, bandMetrics, EXPORT_VIEW_STATE, exportSize, keepForExport, pickFontFaces, type Bounds } from "@/entities/portfolio-graph";

/**
 * 카드·묶음·갈래 틀의 경계(캔버스 좌표) — 감싸개의 캔버스 자리(translate)와 레이아웃 크기(offsetWidth·Height)로 잰다.
 * 화면 상자(`getBoundingClientRect`)를 확대로 나누면 확대·이동마다 소수점 아래가 달라져 그림이 1픽셀 아래로 밀렸다(같은 문서인데 바이트가 다름 — 재서 찾음).
 */
function flowBounds(viewport: HTMLElement): Bounds | null {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const el of Array.from(viewport.querySelectorAll<HTMLElement>(".react-flow__node"))) {
    const w = el.offsetWidth, h = el.offsetHeight;
    if (!w || !h) continue;                                                // 접힌 상자 안의 숨은 카드
    const t = new DOMMatrixReadOnly(getComputedStyle(el).transform);
    x0 = Math.min(x0, t.e); y0 = Math.min(y0, t.f);
    x1 = Math.max(x1, t.e + w); y1 = Math.max(y1, t.f + h);
  }
  return Number.isFinite(x0) ? { x: x0, y: y0, width: x1 - x0, height: y1 - y0 } : null;
}

const fontData = new Map<string, Promise<string>>();
function asDataUrl(url: string): Promise<string> {
  let p = fontData.get(url);
  if (!p) {
    p = fetch(url).then((r) => {
      if (!r.ok) throw new Error(`${r.status}`);
      return r.blob();
    }).then((b) => new Promise<string>((ok, bad) => {
      const fr = new FileReader();
      fr.onload = () => ok(String(fr.result));
      fr.onerror = () => bad(fr.error);
      fr.readAsDataURL(b);
    }));
    p.catch(() => fontData.delete(url));                                   // 실패는 기억하지 않는다 — 다음 누름에 다시
    fontData.set(url, p);
  }
  return p;
}
/** 쓴 글자가 든 글꼴 조각만 data URL 로 바꾼 CSS · 받지 못한 조각 수. */
async function usedFontCSS(text: string): Promise<{ css: string; missed: number }> {
  const faces: { unicodeRange: string; rule: CSSFontFaceRule; base: string }[] = [];
  for (const sheet of Array.from(document.styleSheets)) {
    let rules: CSSRuleList;
    try { rules = sheet.cssRules; } catch { continue; }                     // 다른 출처 시트는 읽을 수 없다
    for (const r of Array.from(rules)) {
      if (r instanceof CSSFontFaceRule) faces.push({ unicodeRange: r.style.getPropertyValue("unicode-range"), rule: r, base: sheet.href ?? location.href });
    }
  }
  let missed = 0;
  const parts = await Promise.all(pickFontFaces(faces, text).map(async (f) => {
    let css = f.rule.cssText;
    try {
      for (const m of Array.from(css.matchAll(/url\((["']?)([^"')]+)\1\)/g))) {
        css = css.replace(m[0], `url("${await asDataUrl(new URL(m[2], f.base).href)}")`);
      }
      return css;
    } catch {
      missed++;
      return "";
    }
  }));
  return { css: parts.filter(Boolean).join("\n"), missed };
}

function download(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);                                           // 문서에 붙어 있어야 파일 이름이 지켜진다(JSON 내보내기와 같은 방식)
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

/** 캔버스(`.pg-canvas`)를 그래프 전체 그림 + 아래 띠로 찍어 내려받는다. 실패하면 던진다(부르는 쪽이 까닭을 말한다). */
export async function exportPng(canvasEl: HTMLElement, lines: string[], fileName: string): Promise<{ fontsMissed: number }> {
  const viewport = canvasEl.querySelector<HTMLElement>(".react-flow__viewport");
  if (!viewport) throw new Error("캔버스를 찾지 못했어요");
  const prevZoom = canvasEl.dataset.zoom;
  const prevZ = canvasEl.style.getPropertyValue("--pg-z");
  const removed: [Element, string][] = [];
  canvasEl.classList.add("pg-exporting");
  canvasEl.dataset.zoom = "mid";
  canvasEl.style.setProperty("--pg-z", "1");
  for (const c of EXPORT_VIEW_STATE) {
    for (const el of Array.from(viewport.querySelectorAll(`.${CSS.escape(c)}`))) { el.classList.remove(c); removed.push([el, c]); }
  }
  let shot: HTMLCanvasElement;
  let scale: number;
  let fontsMissed = 0;
  try {
    const { toCanvas } = await import("html-to-image");
    const b = flowBounds(viewport);
    if (!b) throw new Error("그릴 카드가 없어요");
    const size = exportSize(b);
    scale = size.scale;
    const font = await usedFontCSS(viewport.textContent ?? "");
    fontsMissed = font.missed;
    shot = await toCanvas(viewport, {
      width: size.w, height: size.h, pixelRatio: 1, skipAutoScale: true, fontEmbedCSS: font.css,
      backgroundColor: getComputedStyle(canvasEl).backgroundColor,
      filter: (node) => !(node instanceof Element) || keepForExport(node.getAttribute("class") ?? ""),
      style: { width: `${size.w}px`, height: `${size.h}px`, transformOrigin: "0 0", transform: `translate(${size.x}px, ${size.y}px) scale(${size.scale})` },
    });
  } finally {
    for (const [el, c] of removed) el.classList.add(c);
    if (prevZoom) canvasEl.dataset.zoom = prevZoom; else delete canvasEl.dataset.zoom;
    if (prevZ) canvasEl.style.setProperty("--pg-z", prevZ); else canvasEl.style.removeProperty("--pg-z");
    canvasEl.classList.remove("pg-exporting");
  }
  // 아래 띠 — 페이지에 올라온 글꼴로 그린다(띠 글자가 든 조각을 먼저 불러 둔다).
  const css = getComputedStyle(canvasEl);
  const m = bandMetrics(scale);
  const out = document.createElement("canvas");
  out.width = shot.width;
  out.height = shot.height + bandHeight(lines.length, scale);
  const g = out.getContext("2d");
  if (!g) throw new Error("그림판을 열지 못했어요");
  g.drawImage(shot, 0, 0);
  g.fillStyle = css.getPropertyValue("--pg-paper").trim() || "#ffffff";
  g.fillRect(0, shot.height, out.width, out.height - shot.height);
  g.fillStyle = css.getPropertyValue("--pg-card-line").trim() || "#d1d6db";
  g.fillRect(0, shot.height, out.width, Math.max(1, Math.round(m.font / 13)));
  const face = `"Pretendard Variable", Pretendard, -apple-system, "Apple SD Gothic Neo", "Noto Sans KR", sans-serif`;
  g.textBaseline = "middle";
  for (const [i, line] of lines.entries()) {
    const font = `${i === 0 ? 700 : 500} ${m.font}px ${face}`;
    await document.fonts.load(font, line);
    g.font = font;
    g.fillStyle = (i === 0 ? css.getPropertyValue("--pg-ink") : css.getPropertyValue("--pg-body")).trim() || "#191f28";
    g.fillText(line, m.pad, shot.height + m.pad + m.line * (i + 0.5));
  }
  const blob = await new Promise<Blob | null>((ok) => out.toBlob(ok, "image/png"));
  if (!blob) throw new Error("PNG 로 바꾸지 못했어요");
  download(blob, fileName);
  return { fontsMissed };
}
