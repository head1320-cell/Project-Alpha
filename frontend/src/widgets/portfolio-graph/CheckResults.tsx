"use client";
/**
 * 확인하기 노드의 결과 (BK W1) — 시나리오 충격 · 상관 스트레스 · 기대수익 민감도 · 팩터 성격
 * ==========================================================================
 * 수는 서버 view 그대로 그린다(다시 계산하지 않는다). 가정 충격과 실제 시세 재생은 모양부터
 * 다르다 — 재생은 낙폭 곡선, 가정은 종목별 충격 표.
 */
import type { ReactNode } from "react";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { PerfLabel, type PerfLabelValue } from "@/shared/ui/PerfLabel";

type Dict = Record<string, unknown>;
const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const pct = (v: unknown, d = 2) => (num(v) === null ? "—" : `${(v as number).toFixed(d)}%`);
const won = (v: unknown) => (num(v) === null ? "—" : `${Math.round(v as number).toLocaleString("ko-KR")}원`);

function KV({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="pg-kv">
      {rows.map(([k, v]) => (<div key={k}><dt>{k}</dt><dd>{v}</dd></div>))}
    </dl>
  );
}

function Drawdown({ r }: { r: Dict }) {
  const dates = (r.dates as string[]) ?? [];
  const p = (r.portfolio_dd as number[]) ?? [];
  const b = (r.benchmark_dd as number[] | undefined) ?? null;
  const step = Math.max(1, Math.floor(p.length / 300));
  const data = p.map((y, i) => ({ d: dates[i], p: y, b: b?.[i] ?? null })).filter((_, i) => i % step === 0);
  return (
    <div className="pg-chart" aria-label="낙폭 곡선">
      <ResponsiveContainer width="100%" height={150}>
        <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
          <XAxis dataKey="d" hide />
          <YAxis domain={["auto", 0]} width={40} tick={{ fontSize: 10 }} unit="%" />
          <Tooltip formatter={(x: number) => `${x?.toFixed?.(1)}%`} />
          <Line dataKey="p" name="이 비중" dot={false} stroke="var(--pg-fail)" strokeWidth={1.5} isAnimationActive={false} />
          {b && <Line dataKey="b" name={String(r.benchmark_label ?? "지수")} dot={false} stroke="var(--pg-mute)" strokeWidth={1} isAnimationActive={false} />}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function ShockRows({ rows }: { rows: Dict[] }) {
  return (
    <table className="pg-table pg-shock">
      <thead><tr><th>종목</th><th className="pg-td-num">비중</th><th className="pg-td-num">충격</th><th className="pg-td-num">기여</th></tr></thead>
      <tbody>
        {rows.map((x) => (
          <tr key={String(x.stock_code)}>
            <td className="pg-td-name">{String(x.corp_name ?? x.stock_code)}</td>
            <td className="pg-td-num">{pct(x.weight_pct, 1)}</td>
            <td className={`pg-td-num${(num(x.shock_pct) ?? 0) < 0 ? " pg-neg" : ""}`}>{pct(x.shock_pct, 1)}</td>
            <td className={`pg-td-num${(num(x.contribution_pct) ?? 0) < 0 ? " pg-neg" : ""}`}>{pct(x.contribution_pct, 2)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function ScenarioStressResult({ v, prov }: { v: Dict; prov: Dict }) {
  const pack = (v.pack as Dict) ?? {};
  const r = (v.result as Dict) ?? {};
  const historical = r.mode === "historical";
  const risk = r.risk_proxy as Dict | undefined;
  return (
    <>
      <p className={`pg-model-type pg-model-type--${historical ? "hist" : "hypo"}`}>{String(pack.model_type_label ?? "")}</p>
      {historical ? (
        <>
          {/* 기간 수익률·낙폭은 성과 숫자다 — 서버가 단 라벨(고정 비중 재생)을 숫자 바로 위에. */}
          {prov.perf_label ? <div className="pg-perf"><PerfLabel value={prov.perf_label as PerfLabelValue} /></div> : null}
          <KV rows={[
            ["기간", `${String(((r.dates as string[]) ?? [])[0] ?? "?")} ~ ${String(((r.dates as string[]) ?? []).slice(-1)[0] ?? "?")}`],
            ["최대 낙폭", pct(r.max_dd_pct, 1)], ["기간 수익률", pct(r.total_return_pct, 1)],
            ...(r.benchmark_max_dd_pct != null ? [[`${String(r.benchmark_label)} 최대 낙폭`, pct(r.benchmark_max_dd_pct, 1)] as [string, ReactNode]] : []),
          ]} />
          <Drawdown r={r} />
          {((r.dropped as string[]) ?? []).length > 0 && <p className="pg-warn">시세가 없어 뺀 종목: {(r.dropped as string[]).join(", ")}</p>}
        </>
      ) : (
        <>
          <KV rows={[
            ["추정 충격", pct(r.portfolio_shock_pct, 2)], ["강도 배율", `${String(r.severity ?? 1)}배`],
            ...(risk ? [["VaR 95% (근사)", pct(risk.var95_pct, 2)] as [string, ReactNode], ["CVaR 95% (근사)", pct(risk.cvar95_pct, 2)] as [string, ReactNode]] : []),
          ]} />
          <h4 className="pg-h4">종목별 충격</h4>
          <ShockRows rows={(r.rows as Dict[]) ?? []} />
          {((r.factor_attribution as Dict[]) ?? []).length > 0 && (
            <>
              <h4 className="pg-h4">어디서 왔나요 (팩터 기여)</h4>
              <table className="pg-table"><tbody>
                {(r.factor_attribution as Dict[]).map((f) => (
                  <tr key={String(f.factor)}><td className="pg-td-name">{String(f.label)}</td>
                    <td className={`pg-td-num${(num(f.contribution_pct) ?? 0) < 0 ? " pg-neg" : ""}`}>{pct(f.contribution_pct, 2)}</td></tr>
                ))}
              </tbody></table>
            </>
          )}
          {r.note ? <p className="pg-note">{String(r.note)}</p> : null}
        </>
      )}
    </>
  );
}

export function CorrStressResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const b = (r.base as Dict) ?? {};
  const s = (r.stressed as Dict) ?? {};
  const names = (r.names as string[]) ?? [];
  const labels = (r.labels as Record<string, string>) ?? {};
  const bc = (b.component_var as Record<string, number>) ?? {};
  const sc = (s.component_var as Record<string, number>) ?? {};
  const shift = (r.corr_shift as Dict) ?? {};
  return (
    <>
      <KV rows={[
        ["평균 상관", `${String(shift.from_avg_rho ?? "—")} → ${String(shift.to_avg_rho ?? "—")}`],
        ["변동성(연)", `${pct(b.port_vol_pct, 1)} → ${pct(s.port_vol_pct, 1)}`],
        ["VaR", `${won(b.var_amount)} → ${won(s.var_amount)}`],
        ["신뢰수준", pct(num(r.confidence_level) === null ? null : (r.confidence_level as number) * 100, 1)],
      ]} />
      <h4 className="pg-h4">종목별 기여 VaR</h4>
      <table className="pg-table">
        <thead><tr><th>종목</th><th className="pg-td-num">평소</th><th className="pg-td-num">위기</th></tr></thead>
        <tbody>{names.map((n) => (
          <tr key={n}><td className="pg-td-name">{labels[n] ?? n}</td><td className="pg-td-num">{won(bc[n])}</td><td className="pg-td-num">{won(sc[n])}</td></tr>
        ))}</tbody>
      </table>
    </>
  );
}

export function SensitivityResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const names = (r.names as string[]) ?? [];
  const labels = (r.labels as Record<string, string>) ?? {};
  const m = (r.matrix as number[][]) ?? [];
  const max = Math.max(0.01, ...m.flat().map((x) => Math.abs(x)));
  const short = (n: string) => labels[n] ?? n;
  return (
    <>
      <p className="pg-note">줄의 종목 기대수익을 올렸을 때 칸의 종목 비중이 몇 %p 바뀌는지예요.</p>
      <div className="pg-heat-wrap">
        <table className="pg-heat">
          <thead><tr><th aria-label="올린 종목" />{names.map((n) => <th key={n} scope="col">{short(n)}</th>)}</tr></thead>
          <tbody>{m.map((row, i) => (
            <tr key={names[i]}>
              <th scope="row">{short(names[i])}</th>
              {row.map((d, j) => (
                <td key={j} style={{ ["--pg-heat" as string]: `${Math.round((Math.abs(d) / max) * 40)}%` }}
                    className={d < 0 ? "neg" : d > 0 ? "pos" : ""}>{d > 0 ? "+" : ""}{d.toFixed(1)}</td>
              ))}
            </tr>
          ))}</tbody>
        </table>
      </div>
    </>
  );
}

export function FactorXrayResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const fs = (r.factors as Dict[]) ?? [];
  const at = (z: number) => `${((Math.max(-3, Math.min(3, z)) + 3) / 6) * 100}%`;
  return (
    <>
      <p className="pg-note">가운데가 유니버스 평균(0σ)이에요. 굵은 점이 이 비중, 세로 선이 {String(r.benchmark_label ?? "기준")}.</p>
      <ul className="pg-z">
        {fs.map((f) => {
          const z = num(f.portfolio_z) ?? 0;
          const b = num(f.benchmark_z) ?? 0;
          return (
            <li key={String(f.id)} className="pg-z-row">
              <span className="pg-z-name">{String(f.label)}</span>
              <span className="pg-z-track" aria-hidden="true">
                <i className="pg-z-bench" style={{ left: at(b) }} />
                <b className={`pg-z-dot${z < 0 ? " neg" : ""}`} style={{ left: at(z) }} />
              </span>
              <span className="pg-z-v">{z > 0 ? "+" : ""}{z.toFixed(2)}σ</span>
              {(num(f.coverage_pct) ?? 100) < 99.5 && <span className="pg-z-cov">{pct(f.coverage_pct, 0)}만</span>}
            </li>
          );
        })}
      </ul>
      {r.note ? <p className="pg-note">{String(r.note)}</p> : null}
    </>
  );
}
