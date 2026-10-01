"use client";
/**
 * 증거 관문 레일 — ★이 화면의 단 하나의 강한 요소★ (BJ2 · 목업 승인본 → BQ Q2 알약)
 * ==========================================================================
 * CLAUDE.md 관문 순서의 8역. 판정은 서버(`src/domain/workflow_gates.py`)가 하고 이 컴포넌트는
 * 그리기만 한다. ★건너뛴 구간은 레일 자체가 끊긴다★ — "건너뛴 관문은 통과한 관문이 아니다" 를
 * 모양으로. 역을 누르면 쉬운 말 사유(확인·가정·몰라요·실패)가 펼쳐진다.
 * 계산 전이거나 결과가 낡았으면 판정을 그리지 않는다(예전 판정은 지금 그래프의 것이 아니다).
 *
 * BQ Q2 — 레일이 한 행(약 150px)을 차지하던 것을 캔버스 위 가운데 떠 있는 **알약**으로 접었다.
 * 알약 = 서버 요약 수(`summary.confirmed/total`) + 관문 8개의 작은 점(레일과 같은 상태 클래스 — 색만이 아니라 모양도 다르다).
 * 누르면 지금의 레일 전체가 알약 아래 카드로 펼쳐지고, Esc·바깥 누르기로 접힌다. 펼침 여부는 이 브라우저에 남는다.
 * 새로 실패한 관문이 생기면 알약이 한 번 강조된다(감속 모션이면 없음).
 */
import { useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import type { GateReport, GateState, ProcedureSuggestion } from "@/entities/portfolio-graph";
import { usePortfolioGraph } from "./store";

const STATE_TEXT: Record<GateState | "idle", string> = {
  confirmed: "확인", assumed: "가정", partial: "절반 확인", unknown: "몰라요",
  skipped: "건너뜀", failed: "실패", idle: "계산 전",
};
const REASON_TEXT: Record<string, string> = {
  confirmed: "확인", assumed: "가정", partial: "절반", unknown: "몰라요", skipped: "건너뜀", failed: "실패",
};

/*
 * 계산 전에도 역 이름은 보인다 — 이름은 서버 카탈로그(`/node-types` 의 `gates`)에서 받는다(BT2).
 * 예전에는 화면이 이름 목록을 따로 들고 있어 서버와 어긋날 수 있었다.
 */

export const RAIL_KEY = "alpha_pg_rail";
const readOpen = () => { try { return localStorage.getItem(RAIL_KEY) === "open"; } catch { return false; } };
const saveOpen = (v: boolean) => { try { localStorage.setItem(RAIL_KEY, v ? "open" : "closed"); } catch { /* 이번 방문에만 */ } };
/** 이미 본 실패 관문 — 모드 전환으로 컴포넌트가 다시 그려져도 같은 결과로 또 강조하지 않게 이 페이지 동안 기억한다. */
let seenFailed = new Set<string>();
const reducedMotion = () => typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

export function GateRail({ report, note = null, byGate = null, nodeLabel, onFocusNode, onApply }: {
  report: GateReport | null;
  note?: string | null;
  /** 관문마다 잴 수 있게 하는 한 걸음(BT2 — 서버 절차의 `by_gate`). */
  byGate?: Record<string, ProcedureSuggestion | null> | null;
  nodeLabel?: (id: string) => string;
  onFocusNode?: (id: string) => void;
  onApply?: (s: ProcedureSuggestion) => void;
}) {
  const meta = usePortfolioGraph((s) => s.catalogMeta);
  const open = usePortfolioGraph((s) => s.openGate);
  const setOpen = usePortfolioGraph((s) => s.setOpenGate);
  const [expanded, setExpanded] = useState(false);
  const [alert, setAlert] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const alertTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => { setExpanded(readOpen()); }, []);
  const toggle = (v: boolean) => { setExpanded(v); saveOpen(v); if (!v) setOpen(null); };

  // 새로 실패한 관문 — 이전 판정에 없던 실패가 생기면 한 번 강조(같은 결과를 다시 계산하면 없다).
  useEffect(() => {
    if (!report) return;
    const now = new Set(report.gates.filter((g) => g.state === "failed").map((g) => g.key));
    const fresh = [...now].some((k) => !seenFailed.has(k));
    seenFailed = now;
    if (!fresh || reducedMotion()) return;
    // 끄는 타이머는 효과 정리에 묶지 않는다 — 개발 모드의 두 번 실행에서 정리가 타이머만 지우고 둘째 실행은 "새것 아님" 이라 강조가 켜진 채 남는다.
    setAlert(true);
    if (alertTimer.current) clearTimeout(alertTimer.current);
    alertTimer.current = setTimeout(() => setAlert(false), 1400);
  }, [report]);

  // Esc — 열린 관문 설명부터, 그다음 카드. 바깥을 누르면 카드를 접는다.
  useEffect(() => {
    if (!expanded) return;
    const key = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (usePortfolioGraph.getState().openGate) return;          // 캔버스의 Esc 가 관문 설명을 닫는다
      toggle(false);
    };
    const down = (e: PointerEvent) => { if (!wrap.current?.contains(e.target as Node)) toggle(false); };
    // 잡는 단계(capture)에서 본다 — 캔버스의 Esc 가 관문 설명을 먼저 닫아 버리면 카드까지 한 번에 접힌다.
    // 바깥 누르기도 잡는 단계에서 — 캔버스 판(d3-zoom)이 mousedown 을 멈춰 거품 단계로는 오지 않는다.
    window.addEventListener("keydown", key, true);
    window.addEventListener("pointerdown", down, true);
    return () => { window.removeEventListener("keydown", key, true); window.removeEventListener("pointerdown", down, true); };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 펼쳐 있을 때만
  }, [expanded]);

  const gates = report?.gates ?? (meta?.gates ?? []).map(({ key, label }) => ({ key, label, state: "idle" as const, reasons: [] }));
  const openGate = report?.gates.find((g) => g.key === open);
  const openIndex = gates.findIndex((g) => g.key === open);
  const passes = (st: string) => st === "confirmed" || st === "assumed" || st === "partial";
  /** 선은 두 역 사이의 것 — 둘 다 지나왔을 때만 잇는다(건너뛴 관문은 통과한 관문이 아니다). */
  const link = (i: number) => (!report || i === 0 ? "" : passes(gates[i - 1].state) && passes(gates[i].state)
    ? " pg-stn--link-on" : " pg-stn--link-off");
  const pillText = report ? `관문 ${report.summary.confirmed}/${report.summary.total} 확인`
    : note ? "관문은 전체를 계산해야 봐요" : "계산하면 관문을 확인해요";

  return (
    <div className="pg-rail-wrap" ref={wrap} data-open={expanded || undefined}>
      <button type="button" className="pg-rail-pill" aria-expanded={expanded} aria-controls="pg-rail-card" aria-label={`증거 관문 — ${pillText}`}
              data-alert={alert ? "new" : undefined} title="이 결과를 어디까지 믿을 수 있을까요 — 눌러서 관문 8개 보기"
              onClick={() => toggle(!expanded)}>
        <span className="pg-rail-pill-text">{pillText}</span>
        <span className="pg-rail-dots" aria-hidden="true">
          {gates.map((g) => (
            <span key={g.key} className={`pg-rail-dot pg-stn--${g.state}`} data-gate={g.key}><span className="pg-stn-dot" /></span>
          ))}
        </span>
        <ChevronDown size={15} aria-hidden="true" className={`pg-rail-chev${expanded ? " on" : ""}`} />
      </button>
      {expanded && (
        <div id="pg-rail-card" className="pg-rail-card">
          <section className="pg-rail" aria-label="증거 관문">
            <div className="pg-rail-head">
              <strong>이 결과를 어디까지 믿을 수 있을까요</strong>
              <span className="pg-rail-summary">
                {report ? `${report.summary.text} ${report.summary.note}`
                        : note ?? "계산하면 8개 관문 중 어디까지 확인됐는지 보여 드려요."}
              </span>
            </div>
            <ol className="pg-track">
              {gates.map((g, i) => (
                <li key={g.key} className={`pg-stn pg-stn--${g.state}${link(i)}${open === g.key ? " pg-stn--open" : ""}`} data-gate={g.key}>
                  <button type="button" disabled={!report} aria-expanded={open === g.key}
                          onClick={() => setOpen(open === g.key ? null : g.key)}>
                    <span className="pg-stn-dot" aria-hidden="true" />
                    <span className="pg-stn-name">{g.label}</span>
                    <span className="pg-stn-state">{STATE_TEXT[g.state]}</span>
                  </button>
                </li>
              ))}
            </ol>
            {openGate && (
              <div className="pg-gate-pop" role="dialog" aria-label={`${openGate.label} 관문`}
                   style={{ left: `calc(${((openIndex + 0.5) / gates.length) * 100}% - 180px)` }}>
                <h3>{openGate.label} · {STATE_TEXT[openGate.state]}</h3>
                <ul>
                  {openGate.reasons.map((r, i) => (
                    <li key={i}><span className={`pg-tag pg-tag--${r.state}`}>{REASON_TEXT[r.state] ?? r.state}</span><span>{r.text}</span></li>
                  ))}
                </ul>
                {!!openGate.node_ids?.length && onFocusNode && (
                  <div className="pg-gate-nodes">
                    <span className="pg-gate-nodes-h">이 관문을 판정한 노드</span>
                    {openGate.node_ids.map((id) => (
                      <button key={id} type="button" className="pg-gate-node" data-node={id}
                              onClick={() => { setOpen(null); onFocusNode(id); }}>{nodeLabel?.(id) ?? id}</button>
                    ))}
                  </div>
                )}
                {(openGate.state === "skipped" || openGate.state === "unknown") && byGate?.[openGate.key] && onApply && (
                  <button type="button" className="pg-gate-fix" title={byGate[openGate.key]!.text}
                          onClick={() => { const sug = byGate[openGate.key]!; setOpen(null); onApply(sug); }}>
                    ‘{byGate[openGate.key]!.label}’ 붙이기
                  </button>
                )}
                <button type="button" className="pg-gate-close" onClick={() => setOpen(null)}>닫기</button>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
