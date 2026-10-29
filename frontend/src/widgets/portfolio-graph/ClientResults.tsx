"use client";
/**
 * 고객·계좌·목표·보유 진단 결과 (CF 3부 PB1) — ★서버 응답을 그대로 옮긴다★(다시 재지 않는다).
 * 판정 못 함은 판정 못 함으로 · 구간은 구간으로 · 모르는 격차는 모른다고. 이 노드들은 비중을 바꾸지 않는다(관측만).
 */
import type { ReactNode } from "react";

type Dict = Record<string, unknown>;

const RISK: Record<string, string> = { conservative: "안정형", moderate_conservative: "안정추구형", moderate: "위험중립형",
  moderate_aggressive: "적극투자형", aggressive: "공격투자형" };
const SOURCE: Record<string, string> = { survey: "설문", user_declared: "고객이 말함", default: "기본값", unknown: "모름" };
const LIMIT: Record<string, string> = { risky_asset_max_pct: "위험자산 비중 상한(%)", annual_contribution_krw: "연간 납입 한도(원)",
  total_contribution_krw: "총 납입 한도(원)", min_holding_days: "의무 보유 기간(일)" };
const VERDICT: Record<string, [string, string]> = { pass: ["confirmed", "넘지 않음"], breach: ["failed", "넘음"],
  undetermined: ["assumed", "판정 못 함"] };

/** 서버 사유 문장의 강조 기호(`**` · `★` · 백틱)만 걷는다 — 뜻은 그대로. */
const plain = (v: unknown) => String(v ?? "").replace(/\*\*|★|`/g, "");
const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const fmt = (v: unknown, d = 1) => { const x = num(v); return x === null ? "모름" : Number.isInteger(x) ? x.toLocaleString("ko-KR") : x.toFixed(d); };

function KV({ rows, className }: { rows: [string, ReactNode][]; className?: string }) {
  return (
    <dl className={`pg-kv${className ? ` ${className}` : ""}`}>
      {rows.map(([k, v]) => (<div key={k}><dt>{k}</dt><dd>{v}</dd></div>))}
    </dl>
  );
}

export function ClientProfileResult({ v }: { v: Dict }) {
  const risk = typeof v.risk_tolerance === "string" ? RISK[v.risk_tolerance] ?? v.risk_tolerance : "모름";
  const src = typeof v.profile_source === "string" ? SOURCE[v.profile_source] ?? v.profile_source : "모름";
  const when = typeof v.assessed_at === "string" ? `${v.assessed_at} · ${fmt(v.assessed_age_days)}일 지났어요` : "모름";
  return (
    <>
      <KV className="pg-client-kv" rows={[
        ["별칭", typeof v.alias === "string" ? v.alias : "없음"], ["위험 성향", risk], ["성향 출처", src],
        ["평가일", when], ["투자 기간", num(v.horizon_years) === null ? "모름" : `${fmt(v.horizon_years)}년`],
      ]} />
      <p className="pg-note">성향·기간은 비중을 바꾸지 않아요 — 최적화기는 이 고객을 모른 채 계산해요.</p>
    </>
  );
}

function RiskyShare({ rs }: { rs: Dict | undefined }) {
  if (!rs) return null;
  const iv = rs.interval as Dict | undefined;
  if (!rs.available || !iv) {
    return <p className="pg-acct-risky pg-note">위험자산 비중을 재지 않았어요 — {plain(rs.reason ?? "사유 없음")}</p>;
  }
  const un = num(rs.unassigned_pct) ?? 0;
  return (
    <p className="pg-acct-risky">
      위험자산 비중 <b>{fmt(iv.lo)}~{fmt(iv.hi)}%</b>
      {un > 0 && <span className="pg-note"> — 자산군을 모르는 보유 {fmt(un)}% 만큼 구간이 넓어요(모름을 0으로 접지 않아요)</span>}
    </p>
  );
}

function Verdicts({ verdicts }: { verdicts: Dict[] }) {
  if (!verdicts.length) return null;
  return (
    <table className="pg-table pg-acct-table">
      <tbody>
        {verdicts.map((x, i) => {
          const lim = (x.limit as Dict) ?? {};
          const obs = x.observed as Dict | null;
          const [tone, label] = VERDICT[String(x.verdict)] ?? ["assumed", String(x.verdict)];
          const declared = num(lim.value) === null ? "선언 안 함"
            : `${fmt(lim.value)}${lim.source ? ` · ${String(lim.source)}` : ""}${lim.as_of ? ` · ${String(lim.as_of)}` : ""}`;
          const seen = obs ? (obs.lo === obs.hi ? fmt(obs.lo) : `${fmt(obs.lo)}~${fmt(obs.hi)}`) : "없음";
          return (
            <tr key={i} className="pg-acct-verdict" data-verdict={String(x.verdict)}>
              <td>
                <b>{LIMIT[String(x.kind)] ?? String(x.kind)}</b>
                <span className="pg-acct-why">선언한 값 {declared} · 잰 값 {seen}</span>
                {x.reason ? <span className="pg-acct-why">{plain(x.reason)}</span> : null}
              </td>
              <td className="pg-acct-tag"><span className={`pg-tag pg-tag--${tone}`}>{label}</span></td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export function AccountResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const verdicts = (r.verdicts as Dict[]) ?? [];
  return (
    <>
      <RiskyShare rs={r.risky_share as Dict | undefined} />
      <Verdicts verdicts={verdicts} />
      {!verdicts.length && <p className="pg-note">{String(r.note ?? "이 계좌 유형에는 이 저장소가 아는 한도가 없어요.")}</p>}
      {((r.ignored_limits as string[]) ?? []).length > 0 && (
        <p className="pg-note">이 계좌에 없는 한도라 보지 않은 것: {((r.ignored_limits as string[]) ?? []).map((k) => LIMIT[k] ?? k).join(", ")}</p>
      )}
      <p className="pg-note">{plain(r.optimizer_note)}</p>
    </>
  );
}

export function GoalResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const g = (r.glide as Dict) ?? {};
  const gap = (g.gap as Dict) ?? {};
  const contrib = (r.contribution as Dict) ?? {};
  const st = String(gap.state ?? "unknown");
  const target = num(g.target_pct);
  return (
    <>
      <KV rows={[
        ["남은 기간", num(g.years_remaining) === null ? `모름${g.years_reason ? ` — ${plain(g.years_reason)}` : ""}` : `${fmt(g.years_remaining)}년`],
        ["목표 위험자산 비중", <span key="t" className="pg-goal-target">
          {target === null ? `내지 않음${g.curve_reason ? ` — ${plain(g.curve_reason)}` : ""}` : `${fmt(target)}%`}</span>],
      ]} />
      <RiskyShare rs={r.risky_share as Dict | undefined} />
      {target !== null && (
        <p className="pg-goal-gap" data-state={st}>
          {st === "above" ? `지금 위험자산 비중이 목표보다 ${fmt(gap.lo)}~${fmt(gap.hi)}%p 많아요`
            : st === "below" ? `지금 위험자산 비중이 목표보다 ${fmt(-(num(gap.hi) ?? 0))}~${fmt(-(num(gap.lo) ?? 0))}%p 적어요`
            : `지금 비중과 목표의 차이는 몰라요 — ${plain(gap.reason)}`}
        </p>
      )}
      <p className="pg-note">
        {num(contrib.months) === null ? `적립만으로 좁히는 데 걸리는 개월: 내지 않음${contrib.reason ? ` — ${plain(contrib.reason)}` : ""}`
          : `적립 계획대로라면 격차를 좁히는 데 ${fmt(contrib.months)}개월(계획이지 실적이 아니에요)`}
      </p>
      <Verdicts verdicts={(((r.limits as Dict) ?? {}).verdicts as Dict[]) ?? []} />
      <p className="pg-note">{plain(r.optimizer_note)}</p>
    </>
  );
}

export function HoldingsCheckResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const labels = (v.labels as Record<string, string>) ?? {};
  const risk = (r.risk_contributions as Dict) ?? {};
  const liq = (r.liquidity as Dict) ?? {};
  const conc = (r.factor_concentration as Dict) ?? {};
  const pct = (risk.pct as Record<string, number>) ?? {};
  const rows = Object.entries(pct).sort((a, b) => b[1] - a[1]);
  return (
    <>
      <section className="pg-hold-risk">
        <h4 className="pg-h4">위험 기여(%)</h4>
        {risk.available ? (
          <>
            <table className="pg-table"><tbody>
              {rows.map(([k, x]) => <tr key={k}><td>{labels[k] && labels[k] !== k ? `${labels[k]} ` : ""}<span className="pg-code">{k}</span></td><td>{fmt(x)}%</td></tr>)}
            </tbody></table>
            <p className="pg-note">포트폴리오 변동성 {fmt(risk.portfolio_volatility_pct)}% · 공분산 출처 {String(risk.sigma_source ?? "모름")}</p>
          </>
        ) : <p className="pg-warn">재지 못했어요 — {plain(risk.reason ?? "사유 없음")}</p>}
      </section>
      <section className="pg-hold-conc">
        <h4 className="pg-h4">팩터 집중도</h4>
        {conc.available ? <p className="pg-note">실질 팩터 수 {fmt(conc.effective_factors)}개(팩터 {fmt(conc.n_factors)}개 중) — {plain(conc.note)}</p>
          : <p className="pg-warn">재지 못했어요 — {plain(conc.reason ?? "사유 없음")}</p>}
      </section>
      <section className="pg-hold-liq">
        <h4 className="pg-h4">유동성</h4>
        {liq.available ? <p className="pg-note">{Object.keys((liq.by_ticker as Dict) ?? {}).length}종목의 거래대금·시가총액을 봤어요 — {plain(liq.note)}</p>
          : <p className="pg-warn">재지 못했어요 — {plain(liq.reason ?? "사유 없음")}</p>}
      </section>
      <p className="pg-note">{plain(r.note)}</p>
    </>
  );
}
