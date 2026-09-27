"use client";
/**
 * 리스크·파생·신용 노드의 결과 (BL3 W4)
 * ==========================================================================
 * 수는 서버 view 그대로 그린다(다시 계산하지 않는다). 모든 결과 아래에 W3b 와 같은 '입력 표'(관측·근사·가정 칩).
 * 이 웨이브에서 눈에 띄게 그리는 것은 **몬테카를로 손익 분포** 하나다 — VaR 선 왼쪽의 손실 꼬리만 진하게 칠하고,
 * 선에 금액을 붙인다(드문 날의 손실이 곧 결론). 나머지는 조용한 표·막대·선. 색은 중립 — 손실을 빨강으로 겁주지 않는다.
 */
import type { ReactNode } from "react";

import { InputsTable } from "./CompanyModelResults";

type Dict = Record<string, unknown>;
const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const pc = (v: unknown, d = 1) => (num(v) === null ? "—" : `${((v as number) * 100).toFixed(d)}%`);
const fx = (v: unknown, d = 2) => (num(v) === null ? "—" : (v as number).toLocaleString("ko-KR", { maximumFractionDigits: d }));
/** 금액 — 억 이상은 억, 아래는 만 원. */
export const krw = (v: unknown) => {
  const x = num(v);
  if (x === null) return "—";
  return Math.abs(x) >= 1e8 ? `${(x / 1e8).toLocaleString("ko-KR", { maximumFractionDigits: 2 })}억 원`
    : `${Math.round(x / 1e4).toLocaleString("ko-KR")}만 원`;
};

function KV({ rows }: { rows: [string, ReactNode][] }) {
  return <dl className="pg-kv">{rows.map(([a, b]) => (<div key={a}><dt>{a}</dt><dd>{b}</dd></div>))}</dl>;
}

/** 무엇을 쟀나 — 계열·표본 한 줄. */
function Meta({ v }: { v: Dict }) {
  const m = (v.meta as Dict) ?? {};
  return (
    <p className="pg-co-head">
      <b>{String(m.label ?? m.series ?? "")}</b>
      {m.start ? <span className="pg-muted"> · {String(m.start)} ~ {String(m.end)} ({String(m.obs)}일)</span> : null}
    </p>
  );
}

/** 문장 헤드라인 — 큰 숫자 하나와 그것이 무엇인지. */
function Lead({ value, children }: { value: string; children: ReactNode }) {
  return (
    <div className="pg-risk-lead">
      <span className="pg-risk-big">{value}</span>
      <span className="pg-risk-say">{children}</span>
    </div>
  );
}

/** 나란한 가로 막대 — 값은 서버 수 그대로, 길이만 최댓값 기준. */
function Bars({ rows }: { rows: { name: string; value: number | null; text: string }[] }) {
  const mx = Math.max(1e-12, ...rows.map((r) => Math.abs(r.value ?? 0)));
  return (
    <div className="pg-bars pg-risk-bars">
      {rows.map((r) => (
        <div key={r.name} className="pg-bar-row">
          <span className="pg-bar-name" title={r.name}>{r.name}</span>
          <span className="pg-bar-track"><i style={{ width: `${(Math.abs(r.value ?? 0) / mx) * 100}%` }} /></span>
          <span className="pg-risk-bar-v">{r.text}</span>
        </div>
      ))}
    </div>
  );
}

/** 선 그림 — 여러 계열을 같은 축에. `zero` 면 0 기준선. */
function Lines({ series, label, zero, fmt }: {
  series: { name: string; values: (number | null)[]; tone: "a" | "b" }[]; label: string; zero?: boolean; fmt: (x: number) => string;
}) {
  const W = 340, H = 120, pad = 4;
  const all = series.flatMap((s) => s.values.filter((x): x is number => num(x) !== null));
  if (!all.length) return null;
  let lo = Math.min(...all), hi = Math.max(...all);
  if (zero) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
  const span = hi - lo || 1;
  const n = Math.max(...series.map((s) => s.values.length));
  const X = (i: number) => pad + (i / Math.max(1, n - 1)) * (W - 2 * pad);
  const Y = (v: number) => pad + (1 - (v - lo) / span) * (H - 2 * pad);
  const path = (vals: (number | null)[]) => vals.map((v, i) => (num(v) === null ? "" : `${X(i).toFixed(1)},${Y(v as number).toFixed(1)}`))
    .filter(Boolean).join(" ");
  return (
    <svg className="pg-risk-lines" viewBox={`0 0 ${W} ${H + 14}`} role="img" aria-label={label}>
      {zero && <line x1={pad} x2={W - pad} y1={Y(0)} y2={Y(0)} className="pg-risk-zero" />}
      {series.map((s) => <polyline key={s.name} points={path(s.values)} className={`pg-risk-line pg-risk-line--${s.tone}`} />)}
      <text x={pad} y={H + 12} className="pg-floors-t">{fmt(lo)}</text>
      <text x={W - pad} y={H + 12} textAnchor="end" className="pg-floors-t">최고 {fmt(hi)}</text>
    </svg>
  );
}

// ══ 리스크 ═════════════════════════════════════════════════════════════════

export function VarEsResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const n = (r.normal as Dict) ?? {}, e = (r.ewma as Dict) ?? {}, h = (r.historical as Dict) ?? {};
  const comps = (r.components as Dict[] | null) ?? null;
  const cl = num(r.confidence_level) ?? 0.99;
  return (
    <>
      <Meta v={v} />
      <Lead value={krw(h.var_amount)}>하루 동안 {pc(cl, 0)} 확률로 손실이 이 금액을 넘지 않았어요 — 과거 그대로</Lead>
      <h4 className="pg-h4">세 방법을 나란히 (합치지 않아요)</h4>
      <Bars rows={[
        { name: "과거 그대로", value: num(h.var_amount), text: krw(h.var_amount) },
        { name: "정규분포", value: num(n.var_amount), text: krw(n.var_amount) },
        { name: "EWMA", value: num(e.var_amount), text: krw(e.var_amount) },
      ]} />
      <KV rows={[
        ["그 너머 평균 손실(ES) · 정규", krw(n.es_amount)],
        ["그 너머 평균 손실(ES) · EWMA", krw(e.es_amount)],
        ["선을 넘은 날", `${fx(h.n_beyond, 0)}일 / ${fx(h.n_obs, 0)}일`],
      ]} />
      {comps ? (
        <>
          <h4 className="pg-h4">어느 종목이 손실 위험을 만드나</h4>
          <Bars rows={comps.map((c) => ({ name: String(c.label ?? c.name), value: num(c.amount), text: krw(c.amount) }))} />
          <p className="pg-note">정규·표본 공분산으로 나눈 값이에요 — 더하면 평균 항을 뺀 정규 VaR 가 돼요.</p>
        </>
      ) : r.components_reason ? <p className="pg-note">{String(r.components_reason)}</p> : null}
      <InputsTable r={r} />
    </>
  );
}

/** ★이 웨이브의 한 곳★ 손익 분포 — VaR 선 왼쪽(손실 꼬리)만 진하게, 선과 ES 에 금액. */
function LossTail({ h, varAmt, esAmt }: { h: Dict; varAmt: number | null; esAmt: number | null }) {
  const centers = (h.bin_centers as number[]) ?? [];
  const counts = (h.counts as number[]) ?? [];
  if (!centers.length || !counts.length) return null;
  const W = 340, H = 128, pad = 6, top = 22;
  const step = centers.length > 1 ? centers[1] - centers[0] : 1;
  const lo = centers[0] - step / 2, hi = centers[centers.length - 1] + step / 2, span = hi - lo || 1;
  const mx = Math.max(1, ...counts);
  const X = (x: number) => pad + ((x - lo) / span) * (W - 2 * pad);
  const bw = (W - 2 * pad) / counts.length;
  const vLine = varAmt !== null ? -varAmt : null;
  const eLine = esAmt !== null ? -esAmt : null;
  const inRange = (x: number | null) => x !== null && x >= lo && x <= hi;
  return (
    <svg className="pg-risk-tail" viewBox={`0 0 ${W} ${H + top + 16}`} role="img"
         aria-label={`모의 손익 분포 — VaR ${krw(varAmt)} 선 왼쪽이 손실 꼬리, 꼬리 평균(ES) ${krw(esAmt)}`}>
      {counts.map((c, i) => {
        const hgt = (c / mx) * H;
        const tail = vLine !== null && centers[i] <= vLine;
        return <rect key={i} x={pad + i * bw + 0.5} y={top + H - hgt} width={Math.max(1, bw - 1)} height={hgt}
                     className={tail ? "pg-risk-bin pg-risk-bin--tail" : "pg-risk-bin"} />;
      })}
      {inRange(eLine) && (
        <line x1={X(eLine as number)} x2={X(eLine as number)} y1={top + 8} y2={top + H} className="pg-risk-es" />
      )}
      {inRange(vLine) && (
        <>
          <line x1={X(vLine as number)} x2={X(vLine as number)} y1={top - 4} y2={top + H} className="pg-risk-var" />
          <text x={X(vLine as number) + 4} y={top + 6} className="pg-risk-var-t">VaR {krw(varAmt)}</text>
        </>
      )}
      <line x1={pad} x2={W - pad} y1={top + H} y2={top + H} className="pg-floors-base" />
      <text x={pad} y={top + H + 13} className="pg-floors-t">{krw(lo)}</text>
      <text x={W - pad} y={top + H + 13} textAnchor="end" className="pg-floors-t">+{krw(hi)}</text>
    </svg>
  );
}

export function McVarResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const multi = r.kind === "multi";
  const varAmt = num(multi ? r.mc_var_amount : r.var_amount);
  const esAmt = num(multi ? r.mc_es_amount : r.es_amount);
  const cl = num(r.confidence_level) ?? 0.99;
  const hp = num(r.holding_period_days) ?? 1;
  return (
    <>
      <Meta v={v} />
      <Lead value={krw(varAmt)}>{hp}일 동안 {pc(cl, 0)} 확률로 손실이 이 금액을 넘지 않았어요 — 모의 경로 {fx(r.n_simulations, 0)}개</Lead>
      {r.histogram ? <LossTail h={r.histogram as Dict} varAmt={varAmt} esAmt={esAmt} /> : null}
      {r.histogram ? <p className="pg-ff-legend">진한 막대 = VaR 보다 더 잃은 경로(손실 꼬리) · 점선 = 꼬리의 평균(ES)</p> : null}
      <KV rows={[
        ["꼬리의 평균 손실(ES)", krw(esAmt)],
        ["추정 오차(표준오차)", `±${krw(r.var_std_error)}`],
        ...(multi ? [["섞어서 줄어든 위험", `${krw(r.diversification_benefit)} (${fx(r.diversification_benefit_pct, 1)}%)`] as [string, ReactNode]] : []),
      ]} />
      <InputsTable r={r} />
    </>
  );
}

export function VolModelsResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const cv = (r.current_volatility as Dict) ?? {};
  const g = (r.garch as Dict) ?? {};
  const ms = (r.model_selection as Dict) ?? {};
  const vs = (r.vol_series as Dict) ?? {};
  const ann = (xs: unknown) => ((xs as number[]) ?? []).map((x) => (num(x) === null ? null : (x as number) * Math.sqrt(252)));
  return (
    <>
      <Meta v={v} />
      <Lead value={pc(cv.garch_annual)}>지금의 연 변동성(GARCH) — EWMA 는 {pc(cv.ewma_annual)}</Lead>
      <Lines label="GARCH 와 EWMA 의 연 변동성 흐름" fmt={(x) => pc(x, 0)}
             series={[{ name: "GARCH", values: ann(vs.garch), tone: "a" }, { name: "EWMA", values: ann(vs.ewma), tone: "b" }]} />
      <p className="pg-ff-legend"><span className="pg-risk-key pg-risk-key--a" />GARCH <span className="pg-risk-key pg-risk-key--b" />EWMA</p>
      <KV rows={[
        ["GARCH 장기 평균", pc(g.long_run_vol_annual)],
        ["충격이 반으로 줄기까지", num(g.half_life_days) === null ? "—" : `${fx(g.half_life_days, 1)}일`],
        ["표본 안 적합(AIC · BIC)", `${String(ms.aic_winner ?? "—")} · ${String(ms.bic_winner ?? "—")}`],
      ]} />
      <p className="pg-note">AIC·BIC 는 이 표본에 얼마나 맞는지예요 — 앞날을 더 잘 맞힌다는 뜻이 아니에요.</p>
      <InputsTable r={r} />
    </>
  );
}

export function HoldingVarResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const rows = (r.results as Dict[]) ?? [];
  return (
    <>
      <Meta v={v} />
      <table className="pg-table pg-scen">
        <thead><tr><th>신뢰수준</th><th className="pg-td-num">보유</th><th className="pg-td-num">VaR</th><th className="pg-td-num">ES</th></tr></thead>
        <tbody>{rows.map((x) => (
          <tr key={`${String(x.confidence_level)}-${String(x.holding_period_days)}`}>
            <td>{pc(x.confidence_level, 0)}</td>
            <td className="pg-td-num">{String(x.holding_period_days)}일</td>
            <td className="pg-td-num">{krw(x.var_amount)}</td>
            <td className="pg-td-num">{krw(x.es_amount)}</td>
          </tr>
        ))}</tbody>
      </table>
      <p className="pg-note">하루 값 × √보유일 — 날마다 독립이라는 가정이에요.</p>
      <InputsTable r={r} />
    </>
  );
}

export function FrtbResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const se = (r.stressed_es as Dict) ?? {};
  const he = (r.historical_es as Dict) ?? {};
  const found = r.stress_window_found === true;
  return (
    <>
      <Meta v={v} />
      <Lead value={krw(r.imcc_capital_charge)}>규제 공식(IMA)으로 계산한 자본 — 승인 모델이 아니에요</Lead>
      {!found && <p className="pg-warn">표본이 짧아 250일 스트레스 구간을 찾지 못했어요 — 스트레스 ES 자리에 현재 ES 를 그대로 뒀어요.</p>}
      <table className="pg-table pg-sotp">
        <tbody>
          <tr><td>현재 ES 97.5% (과거 그대로)</td><td className="pg-td-num">{krw(he.es_amount)}</td></tr>
          <tr><td>스트레스 ES {found ? <span className="pg-muted">({String(se.stress_window_start)} ~ {String(se.stress_window_end)})</span> : <span className="pg-muted">(구간 없음)</span>}</td>
              <td className="pg-td-num">{krw(se.stressed_es_975)}</td></tr>
          <tr><td>유동성 기간 반영</td><td className="pg-td-num">{krw(r.stressed_es_lh_adjusted)}</td></tr>
          <tr><td>규제 승수 × {fx(r.multiplier, 1)}</td><td className="pg-td-num">{krw(r.imcc_capital_charge)}</td></tr>
        </tbody>
      </table>
      <InputsTable r={r} />
    </>
  );
}

export function RollingSharpeResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  return (
    <>
      <Meta v={v} />
      <Lead value={fx(r.current)}>최근 {String(r.window)}일의 샤프 비율</Lead>
      <Lines label="롤링 샤프 비율의 흐름" zero fmt={(x) => fx(x)} series={[{ name: "샤프", values: (r.values as number[]) ?? [], tone: "a" }]} />
      <KV rows={[["구간 평균", fx(r.mean)], ["가장 낮을 때 · 높을 때", `${fx(r.min)} · ${fx(r.max)}`]]} />
      <InputsTable r={r} />
    </>
  );
}

export function DccResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const d = (r.dcc_garch as Dict) ?? {};
  const dyn = (r.dynamic_correlations as Record<string, number[]>) ?? {};
  const stats = (d.correlation_stats as Record<string, Dict>) ?? {};
  const labels = ((v.meta as Dict)?.labels as Record<string, string>) ?? {};
  const nice = (pair: string) => pair.split("_vs_").map((c) => labels[c] ?? c).join(" · ");
  return (
    <>
      <Meta v={v} />
      <KV rows={[["상관의 지속성", fx(d.dcc_persistence)]]} />
      <table className="pg-table pg-scen">
        <thead><tr><th>종목 쌍</th><th>흐름</th><th className="pg-td-num">평균</th><th className="pg-td-num">범위</th></tr></thead>
        <tbody>{Object.entries(dyn).map(([pair, vals]) => {
          const st = stats[pair] ?? {};
          return (
            <tr key={pair}>
              <td className="pg-td-name">{nice(pair)}</td>
              <td><Lines label={`${nice(pair)} 상관의 흐름`} fmt={(x) => fx(x)} series={[{ name: pair, values: vals, tone: "a" }]} /></td>
              <td className="pg-td-num">{fx(st.mean)}</td>
              <td className="pg-td-num">{fx(st.min)} ~ {fx(st.max)}</td>
            </tr>
          );
        })}</tbody>
      </table>
      <p className="pg-note">상관은 함께 움직인 정도예요 — 한쪽이 다른 쪽을 움직인다는 뜻이 아니에요.</p>
      <InputsTable r={r} />
    </>
  );
}

// ══ 파생·신용 계산기 ═══════════════════════════════════════════════════════

function Cells({ rows }: { rows: [string, string][] }) {
  return (
    <div className="pg-opt pg-calc">
      {rows.map(([k, val]) => (
        <div key={k} className="pg-opt-cell"><span className="pg-opt-k">{k}</span><b className="pg-opt-v">{val}</b></div>
      ))}
    </div>
  );
}

export function OptionCalcResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  return (
    <>
      <Cells rows={[["이론가", fx(r.Price, 4)], ["델타", fx(r.Delta, 4)], ["감마", fx(r.Gamma, 6)],
                    ["세타 (1일)", fx(r.Theta, 4)], ["베가 (변동성 1%p)", fx(r.Vega, 4)], ["로 (금리 1%p)", fx(r.Rho, 4)]]} />
      <InputsTable r={r} />
    </>
  );
}

export function BondCalcResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  return (
    <>
      <Cells rows={[["가격", fx(r.Price, 2)], ["수정 듀레이션", fx(r.Modified_Duration, 3)], ["맥컬리 듀레이션", fx(r.Macaulay_Duration, 3)],
                    ["볼록성", fx(r.Convexity, 3)], ["1bp 가치(DV01)", fx(r.DV01, 4)]]} />
      <InputsTable r={r} />
    </>
  );
}

export function FuturesHedgeResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const n = num(r.contracts_to_trade);
  return (
    <>
      <Lead value={n === null ? "—" : `${Math.abs(n)}계약 ${n < 0 ? "매도" : n > 0 ? "매수" : ""}`}>
        반올림 뒤 β {fx(r.current_beta, 3)} → {fx(r.beta_after_rounding, 3)} (목표 {fx(r.target_beta, 3)})
      </Lead>
      <KV rows={[
        ["계약 1개의 크기", krw(r.contract_value)],
        ["헤지 명목", krw(r.hedge_notional)],
        ["반올림 전 계약 수", fx(r.raw_contracts)],
        ["β 감소율 (반올림 뒤, 시장 위험만)", r.beta_reduction_after_rounding_pct == null ? "계산 안 함" : `${fx(r.beta_reduction_after_rounding_pct, 1)}%`],
      ]} />
      {r.reduction_reason ? <p className="pg-note">{String(r.reduction_reason)}</p>
        : <p className="pg-note">종목 고유의 위험은 선물로 줄지 않아요.</p>}
      <InputsTable r={r} />
    </>
  );
}

export function CvaCalcResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const u = (r.unilateral_cva as Dict) ?? {}, b = (r.bilateral_cva as Dict) ?? {};
  const st = (r.stressed_cva as Dict) ?? {}, pd = (r.pd_from_cds as Dict) ?? {};
  const ee = ((r.exposure_profile as Dict)?.ee_values as number[]) ?? [];
  return (
    <>
      <Lead value={krw(u.cva_amount)}>상대방이 부도날 위험의 값(CVA)</Lead>
      {ee.length > 0 && (
        <>
          <h4 className="pg-h4">기간별 기대 노출 <span className="pg-tag pg-tag--assumed">양식화</span></h4>
          <Lines label="기간별 기대 노출 — 거래 종류별로 정해진 모양" fmt={krw} series={[{ name: "EE", values: ee, tone: "a" }]} />
        </>
      )}
      <KV rows={[
        ["우리 쪽 부도 위험(DVA)", krw(b.dva_amount)],
        ["순값(BCVA)", krw(b.bcva_amount)],
        ["스프레드 충격 뒤 CVA", `${krw(st.stressed_cva)} (+${fx(st.stress_loss_pct, 1)}%)`],
        ["상대방 5년 부도 확률", pc(pd["5y_pd"], 2)],
        ["연 스프레드 환산", `${fx(u.cva_spread_bps, 1)}bp`],
      ]} />
      <InputsTable r={r} />
    </>
  );
}

export function IrcCalcResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const mig = (r.migration_analysis as Dict[]) ?? [];
  return (
    <>
      <Lead value={krw(r.irc_total)}>등급 강등·부도로 생길 수 있는 추가 위험 자본(IRC)</Lead>
      <KV rows={[
        ["등급 변화 → 스프레드 위험", krw(r.spread_risk_component)],
        ["부도 위험", krw(r.default_risk_component)],
        ["유동성 기간 반영", krw(r.irc_lh_adjusted)],
      ]} />
      <table className="pg-table pg-scen">
        <thead><tr><th>포지션</th><th>등급</th><th className="pg-td-num">99% 스프레드 손실</th></tr></thead>
        <tbody>{mig.map((m) => (
          <tr key={String(m.position)}>
            <td className="pg-td-name">{String(m.position)}</td><td>{String(m.current_rating)}</td>
            <td className="pg-td-num">{krw(m.credit_spread_var_99)}</td>
          </tr>
        ))}</tbody>
      </table>
      <InputsTable r={r} />
    </>
  );
}
