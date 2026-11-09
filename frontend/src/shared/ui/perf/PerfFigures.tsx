"use client";
/**
 * 머리 — 서버 제목 · 헤드라인(hero) · 성과 라벨 · 요약 숫자 셋~넷 (2026-11-09 · 캔버스 성과 그림 문법 §4.1)
 * ★문장은 서버 explain 그대로★ 화면이 짓지 않는다. 요약 숫자는 `.pg-kv`(E2E 계약 · "총수익") 에 넣는다. 등락 숫자만 등락 잉크색.
 */
import type { ReactNode } from "react";
import { PerfLabel } from "@/shared/ui/PerfLabel";
import type { PerfView } from "./perfView";

export function PerfFigures({ view, fallbackTitle, action, noTitle = false }: {
  view: PerfView; fallbackTitle: string;
  /** 제목 줄 오른쪽의 단추(패널의 '크게 보기'). */
  action?: ReactNode;
  /** 시트 안에서는 시트 머리가 제목을 들고 있어 되풀이하지 않는다. */
  noTitle?: boolean;
}) {
  const ex = view.explain;
  const h = ex?.headline ?? null;
  return (
    <div className="pf-head">
      {!noTitle && (
        <div className="pf-title-row">
          <h3 className="pf-title">{ex?.title ?? fallbackTitle}</h3>
          {action}
        </div>
      )}
      {h && h.value !== null ? (
        <p className="pf-hero"><b>{h.text}</b><small>{h.label}</small></p>
      ) : (
        <p className="pg-note">헤드라인을 서버가 주지 않았어요 — 아래 숫자를 보세요.</p>
      )}
      {view.perfLabel ? <div className="pg-perf"><PerfLabel value={view.perfLabel} /></div> : null}
      <dl className="pg-kv pf-kv">
        {view.figures.map((f) => (
          <div key={f.key}><dt>{f.label}</dt><dd className={f.tone ? `pf-delta--${f.tone}` : undefined}>{f.text}</dd></div>
        ))}
      </dl>
    </div>
  );
}
