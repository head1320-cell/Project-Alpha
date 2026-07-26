"use client";
// FinancialsDeepTab — FDD 실무: QoE(NI vs OCF)·Red Flag·NWC·자본배치 워터폴·듀폰(보조).
// 마운트 시 1콜(financialDeep). 미적재면 note 그대로 렌더(정직).
import { useEffect, useState } from "react";
import { companyApi, type FinancialDeep } from "@/entities/company";

const eokF = (v: number | null | undefined) =>
  v == null ? "—" : `${Math.round(v).toLocaleString()}억`;

export function MiniLine({ years, series }: {
  years: number[];
  series: { vals: (number | null)[]; cls: string; dash?: boolean }[];
}) {
  const all = series.flatMap((s) => s.vals.filter((v): v is number => v != null));
  if (!all.length) return <div className="ca-cp-note">데이터 없음</div>;
  const lo = Math.min(...all), hi = Math.max(...all), span = hi - lo || 1;
  const X = (i: number) => (i / Math.max(1, years.length - 1)) * 100;
  const Y = (v: number) => 30 - ((v - lo) / span) * 28;
  return (
    <svg viewBox="0 0 100 34" className="ca-fd-mini" preserveAspectRatio="none">
      {series.map((s, k) => (
        <polyline key={k} className={s.cls} fill="none"
          strokeDasharray={s.dash ? "2 1.5" : undefined}
          points={s.vals.map((v, i) => (v == null ? "" : `${X(i)},${Y(v)}`)).join(" ")} />
      ))}
    </svg>
  );
}

export default function FinancialsDeepTab({ code }: { code: string }) {
  const [d, setD] = useState<FinancialDeep | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    companyApi.financialDeep(code).then(setD).catch((e) => setErr(String(e?.message ?? e)));
  }, [code]);

  if (err) return <div className="ca-cp-note">재무 심화 로드 실패 — {err}</div>;
  if (!d) return <div className="ca-cp-note">재무 심화 불러오는 중…</div>;
  if (!d.available) return <div className="ca-cp-note">{d.note}</div>;

  const q = d.qoe;
  const wf = d.waterfall;
  const lastIdx = wf.years.length - 1;

  return (
    <div>
      {/* QoE — 이익의 질 */}
      <section className="ca-cp-sec">
        <h4>이익의 질 (QoE) <span className="ca-cp-sub">순이익(실선) vs 영업현금흐름(파랑) · 억원</span></h4>
        <MiniLine years={q.years}
          series={[{ vals: q.ni, cls: "ca-fd-ni" }, { vals: q.ocf, cls: "ca-fd-ocf" }]} />
        <div className="ca-fd-legend">
          최근연도 NI <b>{eokF(q.ni[q.ni.length - 1])}</b> · OCF <b>{eokF(q.ocf[q.ocf.length - 1])}</b> ·
          괴리(OCF−NI) <b>{eokF(q.gap[q.gap.length - 1])}</b> ·
          발생액/자산 <b>{q.accruals[q.accruals.length - 1] ?? "—"}%</b>
        </div>
        <div style={{ marginTop: 8 }}>
          {q.red_flags.length
            ? q.red_flags.map((f) => (
              <span key={f.rule} className={`ca-fd-flag ${f.severity}`}>⚑ {f.msg}</span>))
            : <span className="ca-fd-flag ok">✓ 회계적 경고 신호 없음 (규칙 R1~R3 기준)</span>}
        </div>
      </section>

      <div className="ca-vt-grid">
        {/* NWC */}
        <section className="ca-cp-sec">
          <h4>운전자본 (NWC) <span className="ca-cp-sub">유동자산−유동부채 · NWC/매출%</span></h4>
          <MiniLine years={d.nwc.years} series={[{ vals: d.nwc.nwc, cls: "ca-fd-ni" }]} />
          <table className="ca-fd-tbl">
            <thead><tr><th></th>{d.nwc.years.map((y) => <th key={y}>{String(y).slice(2)}</th>)}</tr></thead>
            <tbody>
              <tr><td>NWC(억)</td>{d.nwc.nwc.map((v, i) => <td key={i}>{Math.round(v).toLocaleString()}</td>)}</tr>
              <tr><td>NWC/매출%</td>{d.nwc.nwc_to_rev_pct.map((v, i) => <td key={i}>{v ?? "—"}</td>)}</tr>
            </tbody>
          </table>
        </section>

        {/* 자본배치 워터폴 (최근연도) */}
        <section className="ca-cp-sec">
          <h4>자본 배치 <span className="ca-cp-sub">{wf.years[lastIdx]}년 · OCF 사용처 · {wf.note}</span></h4>
          <WaterfallBars ocf={wf.ocf[lastIdx]} capex={wf.capex[lastIdx]}
            dividends={wf.dividends[lastIdx]}
            repay={Math.max(0, -(wf.debt_delta[lastIdx] ?? 0))}
            residual={wf.residual[lastIdx]} />
          {(wf.debt_delta[lastIdx] ?? 0) > 0 && (
            <div className="ca-cp-sub" style={{ marginTop: 6 }}>
              해당 연도 부채 순증 +{Math.round(wf.debt_delta[lastIdx] as number).toLocaleString()}억 (조달) — 상환 지출 없음
            </div>
          )}
        </section>
      </div>

      {/* ROIC vs WACC */}
      {d.roic_wacc && (
        <section className="ca-cp-sec">
          <h4>Value Creation <span className="ca-cp-sub">ROIC − WACC 스프레드 · {d.roic_wacc.note}</span></h4>
          <div className="ca-fd-legend">
            ROIC <b>{d.roic_wacc.roic}%</b> − WACC <b>{d.roic_wacc.wacc}%</b> ={" "}
            <b style={{ color: d.roic_wacc.spread > 0 ? "#0e7c4a" : "#b0325a" }}>
              {d.roic_wacc.spread > 0 ? "+" : ""}{d.roic_wacc.spread}%p
            </b>{" "}· {d.roic_wacc.verdict}
          </div>
        </section>
      )}

      {/* 듀폰 (보조 — 접이식) */}
      <details className="ca-cp-sec">
        <summary style={{ cursor: "pointer", fontSize: 13, fontWeight: 600 }}>
          듀폰 3단 분해 (보조) <span className="ca-cp-sub">순이익률 × 자산회전율 × 레버리지 = ROE</span>
        </summary>
        <table className="ca-fd-tbl" style={{ marginTop: 10 }}>
          <thead><tr><th></th>{d.dupont.years.map((y) => <th key={y}>{String(y).slice(2)}</th>)}</tr></thead>
          <tbody>
            <tr><td>순이익률%</td>{d.dupont.net_margin.map((v, i) => <td key={i}>{v ?? "—"}</td>)}</tr>
            <tr><td>자산회전율</td>{d.dupont.asset_turnover.map((v, i) => <td key={i}>{v ?? "—"}</td>)}</tr>
            <tr><td>레버리지</td>{d.dupont.leverage.map((v, i) => <td key={i}>{v ?? "—"}</td>)}</tr>
            <tr style={{ fontWeight: 600 }}><td>ROE%</td>{d.dupont.roe.map((v, i) => <td key={i}>{v ?? "—"}</td>)}</tr>
          </tbody>
        </table>
      </details>
    </div>
  );
}

function WaterfallBars({ ocf, capex, dividends, repay, residual }: {
  ocf: number; capex: number; dividends: number; repay: number; residual: number;
}) {
  const items = [
    { label: "OCF", v: ocf, cls: "src" },
    { label: "CapEx", v: -capex, cls: "use" },
    { label: "배당", v: -dividends, cls: "use" },
    { label: "부채상환", v: -repay, cls: "use" },
    { label: "잔여현금", v: residual, cls: residual >= 0 ? "src" : "use" },
  ];
  const maxAbs = Math.max(...items.map((it) => Math.abs(it.v)), 1);
  return (
    <div>
      {items.map((it) => (
        <div key={it.label} className="ca-fd-wf-row">
          <span className="ca-fd-wf-label">{it.label}</span>
          <div className="ca-fd-wf-track">
            <div className={`ca-fd-wf-bar ${it.cls}`}
              style={{ width: `${(Math.abs(it.v) / maxAbs) * 100}%` }} />
          </div>
          <b className="ca-fd-wf-val">{it.v >= 0 ? "" : "−"}{Math.round(Math.abs(it.v)).toLocaleString()}억</b>
        </div>
      ))}
    </div>
  );
}
