"use client";
/**
 * 기업 웨이브의 결과 (BL3 W3) — 샌드박스 · 역DCF · 가치 분포 · 재무 심층 · 위험 심층 · 매크로 민감도 · 테제 점검
 * ==========================================================================
 * 수는 서버 view 그대로 그린다(다시 계산하지 않는다). 이 웨이브에서 눈에 띄게 그리는 것은 풋볼필드 하나다 —
 * 방법마다 적정가 범위를 한 줄씩 놓고 현재가를 세로선으로 그어, "어느 방법으로 보면 비싸고 어느 방법이면 싼지" 를 한눈에.
 * 가정의 출처(연습용·기본값)는 칩으로 곁에 둔다 — 숫자가 어디서 왔는지 숫자 옆에서 말한다.
 */
import type { ReactNode } from "react";

type Dict = Record<string, unknown>;
const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const won = (v: unknown) => (num(v) === null ? "—" : `${Math.round(v as number).toLocaleString("ko-KR")}원`);
const fx = (v: unknown, d = 2, u = "") => (num(v) === null ? "—" : `${(v as number).toFixed(d)}${u}`);
const sg = (v: unknown, d = 1, u = "") =>
  (num(v) === null ? "—" : `${(v as number) >= 0 ? "+" : "−"}${Math.abs(v as number).toFixed(d)}${u}`);

function KV({ rows }: { rows: [string, ReactNode][] }) {
  return <dl className="pg-kv">{rows.map(([k, v]) => (<div key={k}><dt>{k}</dt><dd>{v}</dd></div>))}</dl>;
}

/** 기업 머리줄 — 이름·코드·현재가와 그 출처. 모든 기업 결과의 첫 줄. */
function Head({ v }: { v: Dict }) {
  return (
    <p className="pg-co-head">
      <b>{String(v.name ?? v.code)}</b> <span className="pg-muted">{String(v.code ?? "")}</span>
      {num(v.price) !== null && <> · 현재가 {won(v.price)} <span className="pg-muted">({String(v.price_source ?? "출처 미상")})</span></>}
    </p>
  );
}

/** 출처 문구 → 칩 톤. 합성·기본값은 '모름' 톤 — 실측처럼 보이지 않게. */
const srcTone = (s: string) => (/연습용|mock|기본값|확인 안 됨/.test(s) ? "unknown" : /표준|근사|도출/.test(s) ? "assumed" : "confirmed");

// ── 가치평가 샌드박스 ───────────────────────────────────────────────────────

type Band = { id: string; label: string; available?: boolean; lo?: number | null; hi?: number | null; mid?: number | null; note?: string };

/** 풋볼필드 — 방법별 범위 막대 + 현재가 세로선. 범위가 없는 방법은 막대 대신 사유 한 줄. */
function FootballField({ bands, price }: { bands: Band[]; price: number | null }) {
  const ok = bands.filter((b) => b.available && num(b.lo) !== null && num(b.hi) !== null);
  const xs = [...ok.flatMap((b) => [b.lo as number, b.hi as number]), ...(price !== null ? [price] : [])];
  if (!xs.length) return <p className="pg-note">범위를 낸 방법이 없어요.</p>;
  const lo = Math.min(...xs), hi = Math.max(...xs), pad = (hi - lo) * 0.06 || hi * 0.05 || 1;
  const x0 = lo - pad, span = hi + pad - x0;
  const at = (x: number) => `${((x - x0) / span) * 100}%`;
  return (
    <div className="pg-ff" role="img"
         aria-label={`방법별 적정가 범위 ${ok.map((b) => `${b.label} ${won(b.lo)}~${won(b.hi)}`).join(", ")}${price !== null ? ` · 현재가 ${won(price)}` : ""}`}>
      {bands.map((b) => (
        <div key={b.id} className="pg-ff-row">
          <span className="pg-ff-name" title={b.note ?? ""}>{b.label}</span>
          <span className="pg-ff-track">
            {b.available && num(b.lo) !== null && num(b.hi) !== null ? (
              <>
                <i className={`pg-ff-bar${price !== null && (b.hi as number) < price ? " pg-ff-bar--below" : ""}`}
                   style={{ left: at(b.lo as number), width: `max(3px, calc(${at(b.hi as number)} - ${at(b.lo as number)}))` }} />
                {num(b.mid) !== null && <i className="pg-ff-mid" style={{ left: at(b.mid as number) }} />}
              </>
            ) : <em className="pg-ff-na">범위 없음{b.note ? ` — ${b.note}` : ""}</em>}
            {price !== null && <i className="pg-ff-price" style={{ left: at(price) }} aria-hidden="true" />}
          </span>
          <span className="pg-ff-val">{b.available && num(b.lo) !== null ? `${Math.round((b.lo as number) / 1000).toLocaleString("ko-KR")}~${Math.round((b.hi as number) / 1000).toLocaleString("ko-KR")}천` : "—"}</span>
        </div>
      ))}
      {price !== null && <p className="pg-ff-legend"><span className="pg-ff-key" aria-hidden="true" />세로선이 현재가 {won(price)} · 막대 안 눈금은 기준값 · 흐린 막대는 현재가보다 낮은 범위</p>}
    </div>
  );
}

export function CompanyValuationResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const u = (r.unified as Dict) ?? {};
  const ff = (r.football_field as { bands?: Band[] }) ?? {};
  const sens = (r.sensitivity as { ke_axis?: number[]; g_axis?: number[]; grid?: number[][] }) ?? {};
  const mid = Math.floor((sens.ke_axis?.length ?? 0) / 2), midg = Math.floor((sens.g_axis?.length ?? 0) / 2);
  return (
    <>
      <Head v={v} />
      <FootballField bands={ff.bands ?? []} price={num(v.price)} />
      <KV rows={[
        ["합친 적정가", won(u.value)],
        // 적정가가 없으면(0 이하) 서버 괴리율은 0 이다 — '차이 없음' 이 아니라 정의 불가라 적지 않는다
        ["지금 가격 − 적정가", num(u.gap_pct) === null || !((num(u.value) ?? 0) > 0) ? "— (적정가 없음)" : `${sg(u.gap_pct, 1, "%")} (적정가 기준)`],
      ]} />
      <table className="pg-table pg-assume">
        <caption>가정</caption>
        <tbody>{((r.assumptions as Dict[]) ?? []).map((a) => (
          <tr key={String(a.key)}>
            <td className="pg-td-name">{String(a.label)}</td>
            <td className="pg-td-num">{a.key === "years" ? `${String(a.value)}년` : a.key === "beta" ? fx(a.value, 2)
              : fx(num(a.value) === null ? null : (a.value as number) * 100, 2, "%")}</td>
            <td><span className={`pg-tag pg-tag--${srcTone(String(a.source ?? ""))}`}>{String(a.source ?? "출처 미상")}</span></td>
          </tr>
        ))}</tbody>
      </table>
      {(sens.grid ?? []).length > 0 && (
        <table className="pg-table pg-sens">
          <caption>할인율(행) × 영구성장률(열)이 바뀌면</caption>
          <thead><tr><th />{(sens.g_axis ?? []).map((g) => <th key={g} className="pg-td-num">{fx(g * 100, 1, "%")}</th>)}</tr></thead>
          <tbody>{(sens.grid ?? []).map((row, i) => (
            <tr key={i}>
              <th className="pg-td-num">{fx((sens.ke_axis ?? [])[i] * 100, 2, "%")}</th>
              {row.map((c, j) => <td key={j} className={`pg-td-num${i === mid && j === midg ? " pg-strong pg-sens-base" : ""}`}>{Math.round(c / 1000).toLocaleString("ko-KR")}천</td>)}
            </tr>
          ))}</tbody>
        </table>
      )}
    </>
  );
}

// ── 역DCF ───────────────────────────────────────────────────────────────────

function GrowthBars({ implied, current }: { implied: number | null; current: number | null }) {
  const mx = Math.max(Math.abs(implied ?? 0), Math.abs(current ?? 0), 1);
  const row = (label: string, x: number | null, tone = "") => (
    <div className="pg-bar-row">
      <span className="pg-bar-name">{label}</span>
      <span className="pg-bar-track"><i className={tone} style={{ width: `${x === null ? 0 : (Math.abs(x) / mx) * 100}%` }} /></span>
      <span className="pg-bar-pct">{x === null ? "모름" : sg(x, 1, "%")}</span>
    </div>
  );
  return <div className="pg-bars">{row("시장이 믿는", implied)}{row("지금까지", current, "mute")}</div>;
}

export function ReverseDcfResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  return (
    <>
      <Head v={v} />
      <GrowthBars implied={num(r.implied_growth_pct)} current={num(r.current_growth_pct)} />
      <KV rows={[["할인율(WACC)", fx(r.wacc_pct, 2, "%")], ["기본 가정의 DCF 값", won(r.base_dcf_price)],
                 ["마지막 해 현금흐름 마진", fx(((r.implied_fcf_margin_pct as Dict) ?? {}).value_pct, 1, "%")]]} />
      {r.current_growth_reason ? <p className="pg-warn">지금까지의 성장률을 재지 못했어요 — {String(r.current_growth_reason)}</p> : null}
      <p className="pg-note">{String(r.note ?? "").replace(/\*\*/g, "")}</p>
    </>
  );
}

// ── 가치 분포 ───────────────────────────────────────────────────────────────

function Quantiles({ q, price, lo, hi, label }: { q: Dict; price: number | null; lo: number; hi: number; label: string }) {
  const at = (x: unknown) => `${((((num(x) ?? lo) - lo) / (hi - lo || 1)) * 100).toFixed(2)}%`;
  return (
    <div className="pg-q-row">
      <span className="pg-ff-name">{label}</span>
      <span className="pg-ff-track">
        {q.available === false || num(q.p10) === null ? <em className="pg-ff-na">분포 없음</em> : (
          <>
            <i className="pg-q-outer" style={{ left: at(q.p10), width: `calc(${at(q.p90)} - ${at(q.p10)})` }} />
            <i className="pg-q-inner" style={{ left: at(q.p25), width: `calc(${at(q.p75)} - ${at(q.p25)})` }} />
            <i className="pg-ff-mid" style={{ left: at(q.p50) }} />
          </>
        )}
        {price !== null && <i className="pg-ff-price" style={{ left: at(price) }} aria-hidden="true" />}
      </span>
      <span className="pg-ff-val">{num(q.p50) === null ? "—" : `${Math.round((q.p50 as number) / 1000).toLocaleString("ko-KR")}천`}</span>
    </div>
  );
}

export function ValuationDistributionResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const u = (r.unified as Dict) ?? {};
  const by = (r.by_model as Record<string, Dict>) ?? {};
  const price = num(v.price);
  const xs = [u, ...Object.values(by)].flatMap((q) => [num(q.p10), num(q.p90)]).filter((x): x is number => x !== null);
  if (price !== null) xs.push(price);
  const lo = Math.min(...xs) * 0.95, hi = Math.max(...xs) * 1.05;
  const widths = (r.widths as Record<string, Dict>) ?? {};
  const assumed = Object.values(widths).length > 0 && !Object.values(widths).some((w) => w.measured);
  return (
    <>
      <Head v={v} />
      <div className="pg-ff pg-dist" role="img" aria-label={`적정가 P10 ${won(u.p10)} · P50 ${won(u.p50)} · P90 ${won(u.p90)} · 현재가 백분위 ${fx(u.price_percentile, 0)}`}>
        <Quantiles q={u} price={price} lo={lo} hi={hi} label="합친 분포" />
        {Object.entries(by).map(([k, q]) => <Quantiles key={k} q={q} price={price} lo={lo} hi={hi} label={k} />)}
        <p className="pg-ff-legend">진한 띠 25~75% · 옅은 띠 10~90% · 세로선 현재가</p>
      </div>
      <KV rows={[["현재가의 백분위", num(u.price_percentile) === null ? "—" : `${fx(u.price_percentile, 1)}번째`],
                 ["모델끼리 갈린 정도", `${fx(((r.model_disagreement as Dict) ?? {}).spread_ratio, 2)}배`],
                 ["쓴 표본", `${String(r.n_used ?? "—")} / ${String(r.n_requested ?? "—")}`]]} />
      {assumed && <p className="pg-note"><span className="pg-tag pg-tag--assumed">가정</span> 가정마다 흔드는 폭은 잰 값이 아니라 정한 값이에요.</p>}
    </>
  );
}

// ── 재무 심층 · 위험 심층 ───────────────────────────────────────────────────

export function FinancialDeepResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const flags = (((r.qoe as Dict) ?? {}).red_flags as unknown[]) ?? [];
  const years = (((r.qoe as Dict) ?? {}).years as unknown[]) ?? [];
  return (
    <>
      <Head v={v} />
      <KV rows={[["본 기간", `${years.length}년`], ["이익의 질 경고", `${flags.length}개`]]} />
      {flags.length > 0 && <ul className="pg-list">{flags.map((f, i) => <li key={i}>{typeof f === "string" ? f : JSON.stringify(f)}</li>)}</ul>}
    </>
  );
}

export function RiskDeepResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const a = (r.altman as Dict) ?? {};
  const comps = (a.components as Dict[]) ?? [];
  const mx = Math.max(0.01, ...comps.map((c) => Math.abs(num(c.contribution) ?? 0)));
  const b = (r.beneish as Dict) ?? {};
  const stress = (((r.rate_stress as Dict) ?? {}).rows as Dict[]) ?? [];
  return (
    <>
      <Head v={v} />
      <KV rows={[["Altman Z", `${fx(a.z, 2)} · ${String(a.zone ?? "—")}`],
                 ["이익 조작 지표(Beneish)", b.available === false ? `모름 — ${String(b.note ?? "")}` : `${fx(b.m_score, 2)} ${String(b.flag ?? "")}`]]} />
      <div className="pg-bars">{comps.map((c) => (
        <div key={String(c.id)} className="pg-bar-row">
          <span className="pg-bar-name" title={String(c.label)}>{String(c.label)}</span>
          <span className="pg-bar-track"><i style={{ width: `${(Math.abs(num(c.contribution) ?? 0) / mx) * 100}%` }} /></span>
          <span className="pg-bar-pct">{fx(c.contribution, 2)}</span>
        </div>
      ))}</div>
      {stress.length > 0 && (
        <table className="pg-table pg-stress">
          <caption>할인율이 오르면 적정가는</caption>
          <tbody>{stress.map((s) => (
            <tr key={String(s.shock_bp)}><td>+{String(s.shock_bp)}bp</td><td className="pg-td-num">{won(s.unified_value)}</td></tr>
          ))}</tbody>
        </table>
      )}
    </>
  );
}

// ── 매크로 민감도 ───────────────────────────────────────────────────────────

export function MacroSensitivityResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const rows = (r.rows as Dict[]) ?? [];
  const st = (r.statistical as Dict) ?? null;
  return (
    <>
      <Head v={v} />
      <table className="pg-table pg-msens">
        <caption>금리 충격 → 적정가 (할인율 공식 그대로)</caption>
        <tbody>{rows.map((x) => (
          <tr key={String(x.shock)}>
            <td className="pg-td-name">{String(x.shock)}</td>
            <td className={`pg-td-num${(num(x.value_pct) ?? 0) < 0 ? " pg-neg" : ""}`}>{x.available ? sg(x.value_pct, 1, "%") : "—"}</td>
            <td className="pg-td-num pg-muted">{x.available ? won(x.value_won) : String(x.reason ?? "")}</td>
          </tr>
        ))}</tbody>
      </table>
      {num(((r.asymmetry as Dict) ?? {}).ratio) !== null && (
        <p className="pg-note">오를 때와 내릴 때 크기가 {fx(((r.asymmetry as Dict) ?? {}).ratio, 2)}배 달라요 — 한 방향만 재면 이 사실이 사라져요.</p>
      )}
      {((r.unavailable as Dict[]) ?? []).map((x, i) => (
        <p key={i} className="pg-warn">{String(x.shock)} → {String(x.target)}: {String(x.reason ?? "").replace(/\*\*/g, "")}</p>
      ))}
      {st && (
        <table className="pg-table pg-msens-stat">
          <caption>과거에 같이 움직인 정도 <span className="pg-tag pg-tag--assumed">상관 ≠ 인과</span></caption>
          <thead><tr><th>계열</th><th className="pg-td-num">기울기</th><th className="pg-td-num">t</th><th className="pg-td-num">R²</th></tr></thead>
          <tbody>{((st.rows as Dict[]) ?? []).map((x) => (
            <tr key={String(x.series)}>
              <td className="pg-td-name">{String(x.series)}</td>
              <td className="pg-td-num">{x.available ? fx(x.beta, 2) : "—"}</td>
              <td className="pg-td-num">{x.available ? fx(x.t_stat, 2) : "—"}</td>
              <td className="pg-td-num">{x.available ? fx(x.r_squared, 3) : String(x.reason ?? "—")}</td>
            </tr>
          ))}</tbody>
        </table>
      )}
    </>
  );
}

// ── 테제 점검 ───────────────────────────────────────────────────────────────

const OP: Record<string, string> = { lt: "<", lte: "≤", gt: ">", gte: "≥", eq: "=", ne: "≠", between: "사이" };
const TIER: Record<string, [string, string]> = {
  backtestable: ["과거 검증 가능", "confirmed"],
  screen_only_backtest_lookahead: ["근사 검증 · 미래 정보 섞임", "assumed"],
  screen_only: ["지금 점검만", "unknown"],
};

export function ThesisCheckResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const kc = (r.kill_conditions as Dict) ?? {};
  const rows = (kc.rows as Dict[]) ?? [];
  return (
    <>
      <Head v={v} />
      {r.claim ? <blockquote className="pg-claim">{String(r.claim)}</blockquote> : null}
      <table className="pg-table pg-thesis">
        <caption>버릴 조건</caption>
        <tbody>{rows.map((x, i) => {
          const c = (x.condition as Dict) ?? {};
          const [label, tone] = TIER[String(x.tier)] ?? ["분류 못 함", "unknown"];
          return (
            <tr key={i}>
              <td className="pg-td-name">{String(c.field ?? "?")} {OP[String(c.op)] ?? String(c.op ?? "")} {String(c.value ?? "")}</td>
              <td>{x.valid ? <span className={`pg-tag pg-tag--${tone}`}>{label}</span> : <span className="pg-tag pg-tag--failed">{String(x.reason ?? "무효")}</span>}</td>
            </tr>
          );
        })}</tbody>
      </table>
      {((r.overdue_catalysts as string[]) ?? []).length > 0 && (
        <p className="pg-warn">기한이 지난 촉매: {((r.overdue_catalysts as string[]) ?? []).join(", ")}</p>
      )}
      <p className="pg-note">저장하지 않아요 — 논지를 다듬는 동안 기록이 쌓이지 않게요.</p>
    </>
  );
}
