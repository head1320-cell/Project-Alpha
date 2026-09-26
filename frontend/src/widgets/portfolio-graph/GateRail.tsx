"use client";
/**
 * 증거 관문 레일 — ★이 화면의 단 하나의 강한 요소★ (BJ2 · 목업 승인본)
 * ==========================================================================
 * CLAUDE.md 관문 순서의 8역. 판정은 서버(`src/domain/workflow_gates.py`)가 하고 이 컴포넌트는
 * 그리기만 한다. ★건너뛴 구간은 레일 자체가 끊긴다★ — "건너뛴 관문은 통과한 관문이 아니다" 를
 * 모양으로. 역을 누르면 쉬운 말 사유(확인·가정·몰라요·실패)가 펼쳐진다.
 * 계산 전이거나 결과가 낡았으면 판정을 그리지 않는다(예전 판정은 지금 그래프의 것이 아니다).
 */
import type { GateReport, GateState } from "@/entities/portfolio-graph";
import { usePortfolioGraph } from "./store";

const STATE_TEXT: Record<GateState | "idle", string> = {
  confirmed: "확인", assumed: "가정", partial: "절반 확인", unknown: "몰라요",
  skipped: "건너뜀", failed: "실패", idle: "계산 전",
};
const REASON_TEXT: Record<string, string> = {
  confirmed: "확인", assumed: "가정", partial: "절반", unknown: "몰라요", skipped: "건너뜀", failed: "실패",
};

/** 계산 전에도 역 이름은 보인다 — 서버 판정과 같은 순서·이름(판정 없이 이름만). */
const IDLE_STATIONS = [
  ["data", "데이터"], ["pit", "시점"], ["signal", "신호"], ["build", "비중 계산"],
  ["cost", "거래비용"], ["oos", "처음 보는 기간"], ["economic", "돈이 되는지"], ["live", "모의·실계좌"],
] as const;

export function GateRail({ report, note = null }: { report: GateReport | null; note?: string | null }) {
  const open = usePortfolioGraph((s) => s.openGate);
  const setOpen = usePortfolioGraph((s) => s.setOpenGate);
  const gates = report?.gates ?? IDLE_STATIONS.map(([key, label]) => ({ key, label, state: "idle" as const, reasons: [] }));
  const openGate = report?.gates.find((g) => g.key === open);
  const openIndex = gates.findIndex((g) => g.key === open);
  const passes = (st: string) => st === "confirmed" || st === "assumed" || st === "partial";
  /** 선은 두 역 사이의 것 — 둘 다 지나왔을 때만 잇는다(건너뛴 관문은 통과한 관문이 아니다). */
  const link = (i: number) => (!report || i === 0 ? "" : passes(gates[i - 1].state) && passes(gates[i].state)
    ? " pg-stn--link-on" : " pg-stn--link-off");

  return (
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
          <button type="button" className="pg-gate-close" onClick={() => setOpen(null)}>닫기</button>
        </div>
      )}
    </section>
  );
}
