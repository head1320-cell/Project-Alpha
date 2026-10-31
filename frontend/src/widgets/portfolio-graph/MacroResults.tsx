"use client";
/**
 * 거시·타이밍 노드의 결과 (BK W3) — 경기 국면 · 타이밍 신호 · ★노출 조절★ · 시점별 시뮬레이션
 * ==========================================================================
 * 노출 조절의 그림이 이 웨이브의 유일한 새 시각 요소다: **같은 100% 막대 두 줄** — 위는 조절 전 종목들,
 * 아래는 같은 종목이 줄어든 만큼 빗금 친 현금 칸. 줄어든 폭이 눈으로 보인다. 수는 서버 view 그대로.
 */
import type { ReactNode } from "react";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

type Dict = Record<string, unknown>;
const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const pct = (v: unknown, d = 1) => (num(v) === null ? "—" : `${(v as number).toFixed(d)}%`);
const STATE = { risk_on: "위험-온", risk_off: "위험-오프", unavailable: "판단 불가" } as Record<string, string>;
const LEG = [["baseline", "기준"], ["timing_only", "타이밍만"], ["timing_macro", "타이밍 + 국면"]] as const;
const FOLLOW_LEG: Record<string, string> = { timing: "timing_only", timing_macro: "timing_macro" };
const SEG = ["var(--pg-st-build)", "var(--pg-st-signal)", "var(--pg-st-check)", "var(--pg-st-belief)", "var(--pg-st-act)", "var(--pg-st-data)"];

function KV({ rows }: { rows: [string, ReactNode][] }) {
  return <dl className="pg-kv">{rows.map(([k, v]) => (<div key={k}><dt>{k}</dt><dd>{v}</dd></div>))}</dl>;
}

export function RegimeResult({ v }: { v: Dict }) {
  const probs = (v.phase_probabilities as Record<string, number> | null) ?? {};
  return (
    <>
      <KV rows={[["국면", String(v.regime ?? "미확인")], ["권고", String(v.recommended_mode ?? "—")],
                 ["스트레스", `${num(v.stress_score)?.toFixed(0) ?? "—"}/100`], ["신뢰도", pct((num(v.confidence) ?? 0) * 100, 0)],
                 ["기준일", String(v.as_of ?? "—")], ["스냅샷", String(v.snapshot_id ?? "—")],
                 ["쓸 수 있는 곳", v.research_usage === "backtest_eligible" ? "과거 검증까지" : "지금 시점만"]]} />
      {Object.keys(probs).length > 0 && (
        <>
          <h4 className="pg-h4">국면 확률</h4>
          <table className="pg-table"><tbody>
            {Object.entries(probs).sort((a, b) => b[1] - a[1]).map(([k, p]) => (
              <tr key={k}><td className="pg-td-name">{k}</td>
                <td className="pg-td-bar"><span className="pg-bar" style={{ width: `${Math.min(100, p * 100)}%` }} /></td>
                <td className="pg-td-num">{pct(p * 100, 0)}</td></tr>
            ))}
          </tbody></table>
        </>
      )}
    </>
  );
}

export function TimingResult({ v }: { v: Dict }) {
  const c = (v.composite as Dict) ?? {};
  const fs = (v.factor_states as Dict[]) ?? [];
  return (
    <>
      <KV rows={[["합친 판단", STATE[String(c.state)] ?? String(c.state)], ["권하는 노출", num(c.exposure) === null ? "— (계산하지 못했어요)" : pct((c.exposure as number) * 100, 0)],
                 ["켜짐 · 꺼짐 · 못 읽음", `${String(c.on_count)} · ${String(c.off_count)} · ${String(c.unavailable_count)}`]]} />
      <ul className="pg-sig">
        {fs.map((f) => (
          <li key={String(f.factor_id)} className={`pg-sig-row pg-sig--${String(f.state)}`}>
            <span className="pg-sig-dot" aria-hidden="true" /><span className="pg-sig-name">{String(f.label)}</span>
            <span className="pg-sig-state">{STATE[String(f.state)] ?? String(f.state)}</span>
          </li>
        ))}
      </ul>
      {c.explanation ? <p className="pg-note">{String(c.explanation)}</p> : null}
    </>
  );
}

function StackBar({ weights, labels, cash, caption }: {
  weights: Record<string, number>; labels: Record<string, string>; cash: number | null; caption: string;
}) {
  const rows = Object.entries(weights).filter(([, w]) => w > 0).sort((a, b) => b[1] - a[1]);
  return (
    <div className="pg-stack">
      <span className="pg-stack-cap">{caption}</span>
      <div className="pg-stack-bar" role="img" aria-label={`${caption}: ${rows.map(([k, w]) => `${labels[k] ?? k} ${w.toFixed(1)}%`).join(", ")}${cash ? `, 현금 ${cash.toFixed(1)}%` : ""}`}>
        {rows.map(([k, w], i) => (
          <i key={k} style={{ width: `${w}%`, background: SEG[i % SEG.length] }} title={`${labels[k] ?? k} ${w.toFixed(1)}%`} />
        ))}
        {cash ? <i className="pg-stack-cash" style={{ width: `${cash}%` }} title={`현금 ${cash.toFixed(1)}%`} /> : null}
      </div>
    </div>
  );
}

export function OverlayResult({ v }: { v: Dict }) {
  const before = (v.before as Record<string, number>) ?? {};
  const after = (v.after as Record<string, number>) ?? {};
  const labels = (v.labels as Record<string, string>) ?? {};
  const legs = (v.legs as Record<string, Dict>) ?? {};
  const chosen = FOLLOW_LEG[String(v.follow)] ?? null;
  const cash = num(v.cash_pct);
  return (
    <>
      <div className="pg-exposure">
        <StackBar weights={before} labels={labels} cash={null} caption="조절 전" />
        <StackBar weights={after} labels={labels} cash={cash} caption="조절 후" />
        <p className="pg-exposure-sum">주식 {pct((num(v.exposure) ?? 0) * 100, 0)} · 현금 {cash === null ? "—" : pct(cash, 0)}</p>
      </div>
      {Object.keys(legs).length > 0 && (
        <div className="pg-legs" role="list" aria-label="세 판단">
          {LEG.filter(([k]) => legs[k]).map(([k, label]) => (
            <div key={k} role="listitem" className={`pg-leg${chosen === k ? " pg-leg--on" : ""}`}>
              <span className="pg-leg-k">{label}{chosen === k ? " · 적용" : ""}</span>
              <b>{pct((num(legs[k].exposure) ?? 0) * 100, 0)}</b>
              <span className="pg-leg-s">{STATE[String(legs[k].state)] ?? String(legs[k].state)}</span>
            </div>
          ))}
        </div>
      )}
      {v.conflict ? <p className="pg-warn">{String(v.conflict)}</p> : null}
      <KV rows={[["근거", String(v.source ?? "—")], ["적용 강도", pct(v.strength_pct, 0)],
                 ["목표 규칙 검사", v.status === "executable" ? "통과 — 데이터 출처는 실행 목표 노드가 다시 봐요" : `막힘 — ${String(v.status_reason ?? "")}`]]} />
    </>
  );
}

export function SimulationResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const pts = [...((r.points as Dict[]) ?? [])].reverse();
  const data = pts.map((p) => ({ d: String(p.as_of), e: (num(p.exposure) ?? 0) * 100 }));
  return (
    <>
      <p className={`pg-model-type pg-model-type--${r.backtest_eligible ? "hist" : "hypo"}`}>
        {r.backtest_eligible ? "과거 검증에 쓸 수 있는 신호" : "참고용 — 과거 검증이 아니에요"}
      </p>
      {r.warning ? <p className="pg-warn">{String(r.warning)}</p> : null}
      <div className="pg-chart" aria-label="시점별 노출">
        <ResponsiveContainer width="100%" height={140}>
          <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
            <XAxis dataKey="d" hide />
            <YAxis domain={[0, 100]} width={36} tick={{ fontSize: 10 }} unit="%" />
            <Tooltip formatter={(x: number) => `${x.toFixed(0)}%`} />
            <Line type="stepAfter" dataKey="e" name="노출" dot={false} stroke="var(--pg-blue)" strokeWidth={1.5} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <KV rows={[["시점 수", String(pts.length)], ["신호 바뀜", `${String(r.state_changes ?? 0)}번`],
                 ["못 읽은 시점", String(r.unavailable_count ?? 0)]]} />
    </>
  );
}
