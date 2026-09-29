"use client";
/**
 * 신호·후보 노드의 결과 (BK W2) — 스크리너 · 점수 · 점수→비중 · 중립화 · 묶음 합치기
 * 수는 서버 view 그대로 — 다시 계산하지 않는다.
 */
import type { ReactNode } from "react";
import { RobustnessView } from "./RobustnessResults";

type Dict = Record<string, unknown>;
const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const pct = (v: unknown, d = 2) => (num(v) === null ? "—" : `${(v as number).toFixed(d)}%`);
const fx = (v: unknown, d = 2) => (num(v) === null ? "—" : (v as number).toFixed(d));

function KV({ rows }: { rows: [string, ReactNode][] }) {
  return <dl className="pg-kv">{rows.map(([k, v]) => (<div key={k}><dt>{k}</dt><dd>{v}</dd></div>))}</dl>;
}

function Bars({ values, labels, unit }: { values: Record<string, number>; labels?: Record<string, string>; unit: string }) {
  const rows = Object.entries(values);
  const max = Math.max(1e-9, ...rows.map(([, v]) => Math.abs(v)));
  return (
    <table className="pg-table"><tbody>
      {rows.map(([k, v]) => (
        <tr key={k}>
          <td className="pg-td-name" title={k}>{labels?.[k] ?? k}</td>
          <td className="pg-td-bar"><span className={`pg-bar${v < 0 ? " pg-bar--neg" : ""}`} style={{ width: `${(Math.abs(v) / max) * 100}%` }} /></td>
          <td className="pg-td-num">{unit === "%" ? pct(v) : fx(v, 3)}</td>
        </tr>
      ))}
    </tbody></table>
  );
}

export function ScreenerResult({ v }: { v: Dict }) {
  const items = (v.items as Dict[]) ?? [];
  const ds = (v.data_source as Dict) ?? {};
  return (
    <>
      <KV rows={[["후보 범위", String(v.universe ?? "—")], ["본 종목", String(v.total_evaluated ?? "—")],
                 ["통과", String(v.total_passed ?? "—")],
                 ["데이터", ds.fully_real ? "실데이터" : `합성 포함 (재무 ${String(ds.fundamentals ?? "?")} · 시세 ${String(ds.market_data ?? "?")})`]]} />
      <h4 className="pg-h4">넘긴 종목</h4>
      <table className="pg-table">
        <thead><tr><th>종목</th><th className="pg-td-num">종합</th><th className="pg-td-num">PER</th><th className="pg-td-num">ROE</th></tr></thead>
        <tbody>{items.map((it) => (
          <tr key={String(it.stock_code)}>
            <td className="pg-td-name">{String(it.corp_name ?? it.stock_code)}</td>
            <td className="pg-td-num">{fx(it.composite_score, 1)}</td>
            <td className="pg-td-num">{fx(it.per, 1)}</td>
            <td className="pg-td-num">{fx(it.roe, 1)}</td>
          </tr>
        ))}</tbody>
      </table>
    </>
  );
}

export function ScoresResult({ v }: { v: Dict }) {
  const scores = (v.scores as Record<string, number>) ?? {};
  const top = Object.fromEntries(Object.entries(scores).slice(0, 15));
  const factors = (v.factors as Dict[] | undefined) ?? null;
  return (
    <>
      {v.expr ? <KV rows={[["식", <code key="e" className="pg-code">{String(v.expr)}</code>], ["기준일", String(v.as_of_effective ?? "—")]]} /> : null}
      {factors && (
        <KV rows={factors.map((f) => [String(f.label), f.covered ? `${f.direction === 1 ? "높을수록" : "낮을수록"} · ${String(f.n)}종목` : "값 부족 — 빠짐"] as [string, ReactNode])} />
      )}
      <h4 className="pg-h4">점수 상위 {Object.keys(top).length}</h4>
      <Bars values={top} labels={v.labels as Record<string, string>} unit="score" />
    </>
  );
}

export function ScoresToWeightsResult({ v }: { v: Dict }) {
  return (
    <>
      {!v.has_sigma && <p className="pg-warn">공분산이 없어 ‘흔들림 나눠 보기’에는 쓸 수 없어요 — 수익률을 이어 주세요.</p>}
      <h4 className="pg-h4">비중</h4>
      <Bars values={(v.weights as Record<string, number>) ?? {}} labels={v.labels as Record<string, string>} unit="%" />
    </>
  );
}

export function NeutralizeResult({ v }: { v: Dict }) {
  const before = (v.before as Record<string, number>) ?? {};
  const after = (v.after as Record<string, number>) ?? {};
  const labels = (v.labels as Record<string, string>) ?? {};
  const names = Array.from(new Set([...Object.keys(before), ...Object.keys(after)]));
  return (
    <>
      <p className="pg-note">연구용 비중이에요 — 중립화는 사후 변환이라 실행 목표로 쓰지 않아요.</p>
      <table className="pg-table">
        <thead><tr><th>종목</th><th className="pg-td-num">전</th><th className="pg-td-num">후</th></tr></thead>
        <tbody>{names.map((n) => (
          <tr key={n}><td className="pg-td-name">{labels[n] ?? n}</td><td className="pg-td-num">{pct(before[n])}</td>
            <td className={`pg-td-num${(after[n] ?? 0) < 0 ? " pg-neg" : ""}`}>{pct(after[n])}</td></tr>
        ))}</tbody>
      </table>
    </>
  );
}

export function SleeveResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  return (
    <>
      <h4 className="pg-h4">묶음 비중</h4>
      <Bars values={(r.sleeve_allocation as Record<string, number>) ?? {}} unit="%" />
      <KV rows={Object.entries((r.risk_contribution_pct as Record<string, number>) ?? {}).map(([k, x]) => [`${k} 위험 기여`, pct(x)] as [string, ReactNode])} />
      <h4 className="pg-h4">합친 종목 비중</h4>
      <Bars values={(r.combined_weights_pct as Record<string, number>) ?? {}} labels={v.labels as Record<string, string>} unit="%" />
    </>
  );
}

/** 전략 합치기(BM C2) — 전략별 몫·위험 분담·변동성, 전략 사이 상관, 합친 종목 비중. 모르는 칸은 "—". */
/**
 * 방법 비교 (BS4, 관측) — 같은 흐름·같은 공분산 위에서 방법마다 몫(막대) · 합친 흔들림 · 분산 효과 · 실질 개수.
 * ★어느 방법이 낫다는 판정이 아니다★ 서버 문구(`note`)를 그대로 보이고, 못 잰 줄은 사유를 보인다.
 */
function MethodCompare({ mc, names }: { mc: Dict | undefined; names: string[] }) {
  if (!mc) return null;
  if (!mc.available) return <p className="pg-help pg-mc-na">방법을 비교하지 못했어요 — {String(mc.reason ?? "사유 없음")}</p>;
  const rows = (mc.rows as Dict[] | undefined) ?? [];
  const color = (i: number) => `var(--cat-${(i % 10) + 1})`;
  return (
    <section className="pg-mc" aria-label="방법 비교">
      <h4 className="pg-h4">방법 비교</h4>
      <p className="pg-help pg-mc-note">{String(mc.note ?? "")}</p>
      <ul className="pg-mc-legend" aria-hidden="true">
        {names.map((n, i) => <li key={n}><i style={{ background: color(i) }} />{n}</li>)}
      </ul>
      <ol className="pg-mc-list">
        {rows.map((r) => {
          const on = r.method === mc.current;
          const fb = (r.fallback as Dict | undefined)?.used === true;
          const shares = (r.shares as Record<string, number> | undefined) ?? {};
          return (
            <li key={String(r.method)} className={`pg-mc-row${on ? " on" : ""}`} data-method={String(r.method)}
                data-current={on ? "1" : "0"} data-available={r.available ? "1" : "0"}>
              <div className="pg-mc-head">
                <b>{String(r.label ?? r.method)}</b>
                {on && <span className="pg-mc-chip pg-mc-chip--on">지금</span>}
                {fb && <span className="pg-mc-chip pg-mc-chip--fb" title={String((r.fallback as Dict).reason ?? "")}>대신 계산</span>}
              </div>
              {r.available ? (
                <>
                  <div className="pg-mc-bar" role="img"
                       aria-label={names.map((n) => `${n} ${pct(shares[n], 1)}`).join(", ")}>
                    {names.map((n, i) => (num(shares[n]) ?? 0) > 0 && (
                      <span key={n} className="pg-mc-seg" style={{ width: `${shares[n]}%`, background: color(i) }} title={`${n} ${pct(shares[n], 1)}`} />
                    ))}
                  </div>
                  <dl className="pg-mc-nums">
                    <div><dt>흔들림(연)</dt><dd>{pct(r.vol_pct, 1)}</dd></div>
                    <div><dt>분산 효과</dt><dd>{fx(r.div_ratio, 2)}배</dd></div>
                    <div><dt>실질 개수</dt><dd>{fx(r.effective_n, 1)}개</dd></div>
                  </dl>
                </>
              ) : <p className="pg-mc-reason">{String(r.reason ?? "사유 없음")}</p>}
            </li>
          );
        })}
      </ol>
    </section>
  );
}

export function PortfolioCombineResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const rows = (v.strategies as Dict[] | undefined) ?? [];
  const corr = v.correlation as { labels: string[]; matrix: (number | null)[][] } | null | undefined;
  return (
    <>
      <h4 className="pg-h4">전략별 몫</h4>
      <table className="pg-table pg-strat-table">
        <thead><tr><th>전략</th><th>몫</th><th>위험 분담</th><th>흔들림(연)</th><th>종목</th></tr></thead>
        <tbody>
          {rows.map((s) => (
            <tr key={String(s.port)} data-port={String(s.port)}>
              <td className="pg-td-name">{String(s.label)}</td>
              <td className="pg-td-num">{pct(s.share_pct, 1)}</td>
              <td className="pg-td-num">{pct(s.risk_pct, 1)}</td>
              <td className="pg-td-num">{pct(s.vol_pct, 1)}</td>
              <td className="pg-td-num">{num(s.n_holdings) === null ? "—" : String(s.n_holdings)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <MethodCompare mc={v.method_compare as Dict | undefined} names={rows.map((s) => String(s.label))} />
      <h4 className="pg-h4">전략 사이 상관</h4>
      {corr ? (
        <table className="pg-table pg-corr-table">
          <thead><tr><th />{corr.labels.map((l) => <th key={l} scope="col">{l}</th>)}</tr></thead>
          <tbody>
            {corr.labels.map((l, i) => (
              <tr key={l}><th scope="row">{l}</th>
                {corr.matrix[i].map((x, j) => (i === j || num(x) === null
                  ? <td key={j} className="pg-td-num" title={i === j ? undefined : "흔들림이 없는 전략이 있어 잴 수 없어요"}>{i === j ? "" : "—"}</td>
                  // 발산 색 — 세기 = |ρ|, 같은 방향 파랑 · 반대 방향 빨강. 글자 값이 늘 함께 있다(색만으로 읽지 않는다).
                  : <td key={j} className={`pg-td-num ${(x as number) < 0 ? "neg" : "pos"}`}
                        style={{ ["--pg-heat" as string]: `${Math.round(Math.abs(x as number) * 32)}%` }}>{fx(x, 2)}</td>))}
              </tr>
            ))}
          </tbody>
        </table>
      ) : <p className="pg-help">상관을 재지 못했어요 — {String(v.correlation_reason ?? "사유 없음")}</p>}
      <RobustnessView rob={v.robustness as Dict | undefined} />
      <h4 className="pg-h4">합친 종목 비중</h4>
      <Bars values={(r.combined_weights_pct as Record<string, number>) ?? {}} labels={v.labels as Record<string, string>} unit="%" />
    </>
  );
}
