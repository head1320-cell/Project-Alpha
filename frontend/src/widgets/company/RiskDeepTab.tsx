"use client";
// RiskDeepTab — 리스크 드릴다운: Altman Z 기여 분해 · Beneish 실측 8지수 · 커버리지 추이 ·
// 금리충격 스트레스. 마운트 시 1콜(riskDeep). 근사/중립 지수는 basis 라벨로 정직 표기.
import { useEffect, useState } from "react";
import { companyApi, type RiskDeep } from "@/shared/api/screenerApi";
import { MiniLine } from "./FinancialsDeepTab";

const fmtW = (v: number | null | undefined) =>
  v == null ? "—" : `₩${Math.round(v).toLocaleString()}`;

const BASIS_LABEL: Record<string, string> = { real: "실측", approx: "근사", neutral: "중립" };

export default function RiskDeepTab({ code, price }: { code: string; price: number }) {
  const [d, setD] = useState<RiskDeep | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    companyApi.riskDeep(code, price).then(setD).catch((e) => setErr(String(e?.message ?? e)));
  }, [code, price]);

  if (err) return <div className="ca-cp-note">리스크 심화 로드 실패 — {err}</div>;
  if (!d) return <div className="ca-cp-note">리스크 심화 불러오는 중…</div>;

  const alt = d.altman;
  const maxContrib = Math.max(...alt.components.map((c) => Math.abs(c.contribution)), 0.01);

  return (
    <div>
      <div className="ca-vt-grid">
        {/* Altman Z 분해 */}
        <section className="ca-cp-sec">
          <h4>Altman Z-Score 분해
            <span className="ca-cp-sub">Z = {alt.z ?? "—"} · {alt.zone ?? ""}</span></h4>
          {alt.components.length ? alt.components.map((c) => (
            <div key={c.id} className="ca-fd-wf-row">
              <span className="ca-fd-wf-label" title={c.label}>{c.id.toUpperCase()}</span>
              <div className="ca-fd-wf-track">
                <div className={`ca-fd-wf-bar ${c.contribution >= 0 ? "src" : "use"}`}
                  style={{ width: `${(Math.abs(c.contribution) / maxContrib) * 100}%` }} />
              </div>
              <b className="ca-fd-wf-val">{c.contribution.toFixed(2)}</b>
            </div>
          )) : <div className="ca-cp-note">산출 불가 (재무 원천 부족)</div>}
          <div className="ca-cp-sub" style={{ marginTop: 6 }}>
            {alt.components.map((c) => `${c.id.toUpperCase()}=${c.label}(×${c.weight})`).join(" · ")}
          </div>
        </section>

        {/* Beneish 8지수 */}
        <section className="ca-cp-sec">
          <h4>Beneish M-Score
            <span className="ca-cp-sub">
              {d.beneish.available ? <>M = {d.beneish.m_score} · {d.beneish.flag}</> : d.beneish.note}
            </span></h4>
          {d.beneish.available && (
            <>
              <table className="ca-fd-tbl">
                <thead><tr><th>지수</th><th>값</th><th>산출</th></tr></thead>
                <tbody>
                  {d.beneish.indices.map((i) => (
                    <tr key={i.id}>
                      <td>{i.id.toUpperCase()} — {i.label}</td>
                      <td>{i.value}</td>
                      <td><span className={`ca-rd-basis ${i.basis}`}>{BASIS_LABEL[i.basis]}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="ca-cp-sub" style={{ marginTop: 6 }}>{d.beneish.note}</div>
            </>
          )}
        </section>
      </div>

      {/* 커버리지 추이 */}
      <section className="ca-cp-sec">
        <h4>차입 커버리지 추이 <span className="ca-cp-sub">{d.coverage.note}</span></h4>
        <MiniLine years={d.coverage.years}
          series={[{ vals: d.coverage.interest_coverage, cls: "ca-fd-ni" },
                   { vals: d.coverage.net_debt_to_ebitda, cls: "ca-fd-ocf", dash: true }]} />
        <table className="ca-fd-tbl">
          <thead><tr><th></th>{d.coverage.years.map((y) => <th key={y}>{String(y).slice(2)}</th>)}</tr></thead>
          <tbody>
            <tr><td>이자보상배율(검정)</td>
              {d.coverage.interest_coverage.map((v, i) => <td key={i}>{v ?? "—"}</td>)}</tr>
            <tr><td>순부채/EBITDA(파랑)</td>
              {d.coverage.net_debt_to_ebitda.map((v, i) => <td key={i}>{v ?? "—"}</td>)}</tr>
          </tbody>
        </table>
      </section>

      {/* 금리충격 스트레스 */}
      <section className="ca-cp-sec">
        <h4>금리충격 스트레스 <span className="ca-cp-sub">{d.rate_stress.note}</span></h4>
        <table className="ca-fd-tbl">
          <thead><tr><th>충격</th><th>이자보상배율</th><th>DCF 가치</th><th>통합 적정가</th></tr></thead>
          <tbody>
            {d.rate_stress.rows.map((r) => (
              <tr key={r.shock_bp}>
                <td>{r.shock_bp === 0 ? "기준" : `+${r.shock_bp}bp`}</td>
                <td>{r.interest_coverage ?? "—"}</td>
                <td>{fmtW(r.dcf_value)}</td>
                <td>{fmtW(r.unified_value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
