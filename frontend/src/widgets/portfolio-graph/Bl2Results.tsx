"use client";
/**
 * 마법사에서 옮긴 계산 노드의 결과 (BL2b) — 프런티어 · 국면 앙상블/설명 · 세 갈래 · 전략 건강 · 묶음 분석 · 알파 둘
 * ==========================================================================
 * 수는 서버 view 그대로 그린다(다시 계산하지 않는다). 계산하지 못한 칸은 비워 두지 않고 "—" 와 사유를 적는다.
 */
import type { ReactNode } from "react";
import { FrontierPlot } from "./MiniPlots";
import { PerfLabel, type PerfLabelValue } from "@/shared/ui/PerfLabel";
import { RobustnessView } from "./RobustnessResults";
import { usePortfolioGraph } from "./store";
import { topoOrder } from "@/entities/portfolio-graph";

type Dict = Record<string, unknown>;
const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const pct = (v: unknown, d = 1) => (num(v) === null ? "—" : `${(v as number).toFixed(d)}%`);
const sgn = (v: unknown, d = 3) => (num(v) === null ? "—" : `${(v as number) >= 0 ? "+" : "−"}${Math.abs(v as number).toFixed(d)}`);

function KV({ rows }: { rows: [string, ReactNode][] }) {
  return <dl className="pg-kv">{rows.map(([k, v]) => (<div key={k}><dt>{k}</dt><dd>{v}</dd></div>))}</dl>;
}

const REGIME_KO: Record<string, string> = {
  Goldilocks: "골디락스(성장↑·물가↓)", Reflation: "리플레이션(성장↑·물가↑)",
  Stagflation: "스태그플레이션(성장↓·물가↑)", Disinflation: "디스인플레이션(성장↓·물가↓)",
};
const rk = (r: unknown) => REGIME_KO[String(r)] ?? String(r ?? "—");

// ── 효율적 프런티어 ─────────────────────────────────────────────────────────

export function FrontierResult({ v }: { v: Dict }) {
  const all = (v.curve as Dict[]) ?? [];
  // 그릴 수 있는 경계 점(흔들림·수익 둘 다 수)만 — 읽는 줄·표 쌍둥이와 같은 순서다.
  const onCurve = all.filter((r) => num(r.volatility) !== null && num(r.return) !== null);
  const curve = onCurve.map((r) => ({ x: r.volatility as number, y: r.return as number }));
  const cloud = v.cloud as { returns?: number[]; volatilities?: number[] } | null;
  // 구름 좌표는 서버가 이미 % 로 준다(곡선과 같은 단위) — 다시 곱하지 않는다.
  const dots = (cloud?.volatilities ?? []).map((x, i) => ({ x, y: (cloud?.returns ?? [])[i] }))
    .filter((_, i) => i % 3 === 0).filter((p) => num(p.x) !== null && num(p.y) !== null);
  const pt = v.point as { return: number; volatility: number } | null;
  const best = all.reduce<Dict | null>((b, r) => (b && (num(b.sharpe) ?? -1e9) >= (num(r.sharpe) ?? -1e9) ? b : r), null);
  const bestAt = best ? onCurve.indexOf(best) : -1;                // 읽는 줄의 처음 자리 = 아래 KV 의 "가장 좋은 점" 과 같은 점
  const read = onCurve.map((r, i) => ({ head: `${i + 1}번째 점`, cells: [
    { key: "vol", label: "변동성", text: pct(r.volatility) }, { key: "ret", label: "수익", text: pct(r.return) },
    { key: "sharpe", label: "샤프", text: num(r.sharpe) === null ? "N/A" : (r.sharpe as number).toFixed(2) },
  ] }));
  return (
    <>
      {/* 직접 SVG (ADR 004 · 2026-11-10) — 값은 호버가 아니라 읽는 줄(←→)·표 쌍둥이에 늘 있다 */}
      <div className="pg-chart pg-frontier">
        <FrontierPlot dots={dots} curve={curve} point={pt && num(pt.volatility) !== null && num(pt.return) !== null ? { x: pt.volatility, y: pt.return } : null}
          rows={read} initial={bestAt >= 0 ? bestAt : 0}
          label={`변동성 대비 수익 경계 ${all.length}점${pt ? ` · 연결한 비중 연 ${pt.return}% · 변동성 ${pt.volatility}%` : ""}`} />
      </div>
      <KV rows={[
        ["곡선", `${all.length}점`],
        ["가장 좋은 점", best ? `연 ${pct(best.return)} · 변동성 ${pct(best.volatility)}` : "—"],
        ["연결한 비중", pt ? <><span className="pg-dot-point" aria-hidden="true" />연 {pct(pt.return)} · 변동성 {pct(pt.volatility)}</>
                       : "비중을 연결하면 곡선 위에 표시합니다"],
      ]} />
      {cloud === null && <p className="pg-warn">무작위 조합 구름은 그리지 못했습니다 — {String(v.cloud_reason ?? "사유 미상")}</p>}
    </>
  );
}

// ── 국면 앙상블 · 국면 설명 ─────────────────────────────────────────────────

const TOOL_KO: Record<string, string> = { axis: "성장·물가 축", markov: "상태 전환", cluster: "군집" };

export function EnsembleResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const regimes = (r.regimes as string[]) ?? [];
  const tools = (r.tools as Record<string, Dict>) ?? {};
  const agree = (r.agreement as Dict) ?? {};
  return (
    <>
      <p className={`pg-model-type pg-model-type--${agree.unanimous ? "hist" : "hypo"}`}>{String(agree.note ?? "")}</p>
      {/* 국면이 행, 방법이 열 — 국면 이름이 길어 열 머리에 두면 뭉개진다. 각 방법이 고른 칸은 굵게. */}
      <table className="pg-table pg-ensemble">
        <thead><tr><th>국면</th>{Object.keys(tools).map((k) => <th key={k} className="pg-td-num">{TOOL_KO[k] ?? k}</th>)}</tr></thead>
        <tbody>
          {regimes.map((g) => (
            <tr key={g}>
              <td className="pg-td-name">{rk(g)}</td>
              {Object.entries(tools).map(([k, t]) => {
                const p = t.available ? num((t.probs as Dict)?.[g]) : null;
                return <td key={k} className={`pg-td-num${t.available && t.argmax === g ? " pg-strong" : ""}`}>{p === null ? "—" : `${(p * 100).toFixed(0)}%`}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {Object.entries(tools).filter(([, t]) => !t.available).map(([k, t]) => (
        <p key={k} className="pg-warn">{TOOL_KO[k] ?? k}은 계산하지 못했습니다 — {String(t.reason ?? "사유 미상")}</p>
      ))}
      <p className="pg-note">{String(r.note ?? "")} 관측 {String(r.n_obs ?? "—")}개월.</p>
    </>
  );
}

const pp = (v: unknown) => (num(v) === null ? "—" : `${((v as number) * 100).toFixed(0)}%`);

export function RegimeExplainResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const tr = (r.transitions as Dict) ?? {};
  const dr = (r.drivers as Dict) ?? {};
  const span = (r.span as Dict) ?? {};
  const fc = (tr.forecast as Dict) ?? {};
  const drivers = ((dr.drivers as Dict[]) ?? []).slice().sort((a, b) => Math.abs(num(b.phi) ?? 0) - Math.abs(num(a.phi) ?? 0)).slice(0, 6);
  const mean = (fc.mean as Record<string, number>) ?? {};
  const ci = (fc.ci90 as Record<string, [number, number]>) ?? {};
  const rows = (tr.rows as Dict[]) ?? [];
  const regimes = (tr.regimes as string[]) ?? rows.map((x) => String(x.from));
  // ★Shapley 는 합이 맞아야 한다★ 기준 + 기여 합 = 이 국면의 확률. 어긋남(효율성 잔차)을 숨기지 않는다.
  const base = num(dr.baseline), prob = num(dr.probability), sumPhi = num(dr.sum_phi), resid = num(dr.efficiency_residual);
  return (
    <>
      <KV rows={[
        ["지금 국면", tr.available ? rk(tr.current) : `— ${String(tr.reason ?? "")}`],
        ["지속 기간", num(tr.run_length_months) === null ? "—" : `${String(tr.run_length_months)}개월`],
        ["관측 창", <span key="w" className="pg-regime-window">{String(span.first ?? "?")} ~ {String(span.last ?? "?")} · {String(span.n_months ?? "—")}개월
          {span.truncated ? ` (요청 ${String(span.requested ?? "?")}개월보다 짧습니다${num(span.dropped_incomplete) ? ` · 미완결 ${String(span.dropped_incomplete)}개월 제외` : ""})` : ""}</span>],
      ]} />
      {drivers.length > 0 && (
        <>
          <h4 className="pg-h4">이 국면을 만든 지표 (확률 {pp(prob)} · 기준 {pp(base)})</h4>
          <table className="pg-table pg-shapley">
            <tbody>{drivers.map((d, i) => (
              <tr key={i}><td className="pg-td-name">{String(d.label ?? d.feature ?? d.name ?? "—")}</td>
                <td className={`pg-td-num${(num(d.phi) ?? 0) < 0 ? " pg-neg" : ""}`}>{num(d.phi) === null ? "—" : `${sgn((d.phi as number) * 100, 1)}%p`}</td></tr>
            ))}</tbody>
          </table>
          {base !== null && prob !== null && sumPhi !== null && (
            <p className="pg-note pg-shapley-sum">기준 {pp(base)} + 기여 합 {sgn(sumPhi * 100, 1)}%p = {pp(base + sumPhi)}
              {resid !== null && Math.abs(resid) > 1e-6 ? ` · 모델 확률 ${pp(prob)} 과 ${sgn(resid * 100, 2)}%p 어긋납니다` : ` · 모델 확률 ${pp(prob)} 과 맞습니다`}</p>
          )}
        </>
      )}
      {rows.length > 0 && (
        <>
          <h4 className="pg-h4">다음 달 전환 확률 (90% 신용구간)</h4>
          <div className="pg-scroll-x">
            <table className="pg-table pg-regime-matrix">
              <thead><tr><th>지금 → 다음</th>{regimes.map((g) => <th key={g} className="pg-td-num">{rk(g).split("(")[0]}</th>)}<th className="pg-td-num">관측</th></tr></thead>
              <tbody>{rows.map((row) => {
                const m = (row.mean as Record<string, number>) ?? {};
                const c = (row.ci90 as Record<string, [number, number]>) ?? {};
                return (
                  <tr key={String(row.from)} data-shrunk={row.shrunk ? "1" : "0"}>
                    <td className="pg-td-name">{rk(row.from).split("(")[0]}</td>
                    {regimes.map((g) => (
                      <td key={g} className="pg-td-num">{pp(m[g])}<span className="pg-ci">{c[g] ? ` ${pp(c[g][0])}~${pp(c[g][1])}` : ""}</span></td>
                    ))}
                    <td className="pg-td-num">{String(row.n ?? "—")}개월</td>
                  </tr>
                );
              })}</tbody>
            </table>
          </div>
          {rows.filter((row) => row.shrunk).map((row) => (
            <p key={String(row.from)} className="pg-warn pg-regime-sparse">{rk(row.from)}에서 전이한 관측이 적습니다 — 값이 사전분포에 가까워 구간이 넓습니다{row.reason ? ` (${String(row.reason)})` : ""}.</p>
          ))}
          {tr.note ? <p className="pg-note">{String(tr.note)}</p> : null}
        </>
      )}
      {fc.available ? (
        <>
          <h4 className="pg-h4">{String(fc.k ?? "")}개월 뒤 국면 확률 (90% 구간)</h4>
          <table className="pg-table pg-regime-fc"><tbody>{Object.entries(mean).sort((a, b) => b[1] - a[1]).map(([g, p]) => (
            <tr key={g}><td className="pg-td-name">{rk(g)}</td><td className="pg-td-num">{pp(p)}</td>
              <td className="pg-td-num pg-ci">{ci[g] ? `${pp(ci[g][0])} ~ ${pp(ci[g][1])}` : "—"}</td></tr>
          ))}</tbody></table>
        </>
      ) : <p className="pg-warn">전환 예측을 하지 못했습니다 — {String(fc.reason ?? "사유 미상")}</p>}
    </>
  );
}

// ── 세 갈래 시나리오 ────────────────────────────────────────────────────────

const LEG_KO: Record<string, string> = { baseline: "현 비중 유지", timing_only: "타이밍만", timing_macro: "타이밍 + 국면" };
const STATE_KO: Record<string, string> = { risk_on: "위험-온", risk_off: "위험-오프", unavailable: "판단 불가", partial: "일부" };

export function ThreeWayResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const sc = (r.scenario as Dict) ?? {};
  const legs = (r.legs as Record<string, Dict>) ?? {};
  return (
    <>
      <p className="pg-model-type pg-model-type--hypo">{String(sc.label ?? "")} · {String(sc.shock_basis ?? "")}</p>
      <table className="pg-table pg-threeway">
        <thead><tr><th>대안</th><th>판정</th><th className="pg-td-num">노출</th><th className="pg-td-num">손실</th></tr></thead>
        <tbody>{Object.entries(legs).map(([k, g]) => (
          <tr key={k}>
            <td className="pg-td-name">{LEG_KO[k] ?? k}</td>
            <td>{STATE_KO[String(g.state)] ?? String(g.state)}{g.state === "unavailable" && g.reason ? <span className="pg-pick-sub pg-3w-na"> — {String(g.reason)}</span> : null}</td>
            <td className="pg-td-num">{num(g.exposure) === null ? "—" : pct((g.exposure as number) * 100, 0)}</td>
            <td className={`pg-td-num${(num(g.shock_pct) ?? 0) < 0 ? " pg-neg" : ""}`}>{num(g.shock_pct) === null ? "미계산" : pct(g.shock_pct, 2)}</td>
          </tr>
        ))}</tbody>
      </table>
      <p className="pg-note">{String(r.composition_note ?? "")}</p>
    </>
  );
}

// ── 전략 건강 · 묶음 분석 ───────────────────────────────────────────────────

const HEALTH_KO: Record<string, string> = { healthy: "건강", watch: "지켜보기", de_risk: "줄이기", paused: "멈춤", retired: "폐기" };

export function HealthResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const items = (r.items as Dict[]) ?? [];
  if (!items.length) return <p className="pg-help">등록된 알파가 없습니다 — 상단 ‘알파’ 서랍에서 등록하면 여기에 상태가 표시됩니다.</p>;
  return (
    <>
      <table className="pg-table">
        <thead><tr><th>알파</th><th>상태</th><th className="pg-td-num">측정 불가 신호</th></tr></thead>
        <tbody>{items.map((it) => (
          <tr key={String(it.alpha_id)}>
            <td className="pg-td-name">{String(it.name)}</td>
            <td>{HEALTH_KO[String(it.status)] ?? String(it.status)}</td>
            <td className="pg-td-num">{((it.signals as Dict[]) ?? []).filter((s) => s.status === "unmeasured").length}</td>
          </tr>
        ))}</tbody>
      </table>
      <p className="pg-note">{String(r.note ?? "")}</p>
    </>
  );
}

/** 견고성 비교의 '묶음 N' 이 캔버스의 어느 노드인지 — 지금 이어진 선에서 읽는다(파라미터에 이름을 적어 두면 선을 바꿀 때 낡는다). */
function useSleeveLegend(ports: string[]): [string, string][] {
  const selected = usePortfolioGraph((s) => s.selectedId);
  const edges = usePortfolioGraph((s) => s.edges);
  const nodes = usePortfolioGraph((s) => s.nodes);
  const catalog = usePortfolioGraph((s) => s.catalog);
  return ports.map((port, i) => {
    const e = edges.find((x) => x.target === selected && x.targetHandle === port);
    const n = e ? nodes.find((x) => x.id === e.source) : undefined;
    const title = n ? catalog?.find((c) => c.type === n.data.kind)?.plain_label ?? n.data.kind : "연결된 노드 없음";
    // 캔버스 카드의 번호와 같은 번호(흐름 순서) — 같은 종류를 둘 이으면 이름만으로는 가를 수 없다.
    const no = n ? topoOrder(nodes.map((x) => x.id), edges).indexOf(n.id) + 1 : 0;
    return [`그룹 ${i + 1}`, no ? `${no}번 ${title}` : title];
  });
}

/** 견고성 비교(BR R1b — BL2b 묶음 분석을 올림) — 같이 무너지나 + 예전 표(상관·군집·위험 몫). */
export function SleeveAnalyticsResult({ v }: { v: Dict }) {
  const legend = useSleeveLegend((v.ports as string[] | undefined) ?? []);
  const r = (v.result as Dict) ?? {};
  const names = (r.sleeves as string[]) ?? Object.keys((r.correlation as Dict) ?? {});
  const corr = (r.correlation as Record<string, Record<string, number>>) ?? {};
  const rc = (r.risk_contribution_pct as Record<string, number>) ?? {};
  const tail = (r.tail_dependency as Dict) ?? {};
  return (
    <>
      {legend.length ? (
        <ul className="pg-rob-legend" aria-label="그룹과 연결된 노드">
          {legend.map(([k, t]) => <li key={k}><b>{k}</b>{t}</li>)}
        </ul>
      ) : null}
      <RobustnessView rob={v.robustness as Dict | undefined} />
      <h4 className="pg-h4">그룹 간 상관 · 위험 기여 비중</h4>
      <KV rows={[["평균 상관", num(r.avg_correlation) === null ? "—" : (r.avg_correlation as number).toFixed(2)],
                 ["군집", `${String(r.n_clusters ?? "—")}개`],
                 ["동반 하락 정도", num(tail.lower_tail_coexceedance) === null ? "—" : `${(tail.lower_tail_coexceedance as number).toFixed(2)} (1 = 서로 무관)`]]} />
      <table className="pg-table pg-corr">
        <thead><tr><th />{names.map((n) => <th key={n} className="pg-td-num">{n}</th>)}<th className="pg-td-num">위험 기여 비중</th></tr></thead>
        <tbody>{names.map((a) => (
          <tr key={a}><td className="pg-td-name">{a}</td>
            {names.map((b) => <td key={b} className="pg-td-num">{num(corr[a]?.[b]) === null ? "—" : corr[a][b].toFixed(2)}</td>)}
            <td className="pg-td-num">{pct(rc[a])}</td></tr>
        ))}</tbody>
      </table>
    </>
  );
}

// ── 알파 검증 · 알파 포트폴리오 ─────────────────────────────────────────────

export function AlphaValidateResult({ v, prov }: { v: Dict; prov: Dict }) {
  const r = (v.result as Dict) ?? {};
  const ic = (r.ic as Dict) ?? {};
  const oos = (r.is_oos as Dict) ?? {};
  const ls = (r.long_short as Dict) ?? {};
  const q = ((r.quantiles as Dict)?.ann_return_pct as number[]) ?? [];
  const decay = (r.decay as Record<string, number | null>) ?? {};
  const top = (r.latest_scores_top as Dict[]) ?? [];
  const max = Math.max(1, ...q.map((x) => Math.abs(x)));
  const src = v.expr_source as Dict | null;
  return (
    <>
      <p className="pg-model-type pg-model-type--hypo">{src ? `등록된 알파 ‘${String(src.name)}’ v${String(src.version)}` : "식으로 검증"} · {String(r.expr ?? "")}</p>
      <KV rows={[
        // ★IC 가 없으면 약세로 칠하지 않는다★ — 못 잰 것과 음수는 다른 사실이다.
        ["평균 IC", <span key="ic" className={`pg-av-ic${(num(ic.mean) ?? 0) < 0 ? " pg-neg" : ""}`}>{num(ic.mean) === null ? "— (측정 불가)" : sgn(ic.mean)}</span>],
        ["ICIR", sgn(ic.icir, 2)], ["t 값", sgn(ic.t_stat, 2)], ["적중률", pct(ic.hit_rate, 0)],
        ["롱숏", <>{prov.perf_label ? <PerfLabel value={prov.perf_label as PerfLabelValue} /> : null}
                  {` 총 ${pct(ls.total_return_pct)} · 샤프 ${sgn(ls.sharpe, 2)} · 최대 낙폭 ${pct(ls.mdd_pct)}`}</>],
        ["기간", `${String(r.period_start ?? "?")} ~ ${String(r.period_end ?? "?")} · ${String(r.n_periods ?? "—")}번`],
      ]} />
      {/* ★DECAY 와 앞/뒤 절반은 다른 질문이다★ — 보유 기간별 IC(얼마나 오래 가나) · 기간 분할 IC(시간이 지나도 버티나). */}
      {Object.keys(decay).length > 0 && (
        <>
          <h4 className="pg-h4">보유 기간별 IC (신호 지속성)</h4>
          <table className="pg-table pg-av-decay"><tbody>{Object.entries(decay).map(([k, x]) => (
            <tr key={k}><td className="pg-td-name">{k.replace("m", "개월")}</td>
              <td className={`pg-td-num${(num(x) ?? 0) < 0 ? " pg-neg" : ""}`}>{num(x) === null ? "— (측정 불가)" : sgn(x)}</td></tr>
          ))}</tbody></table>
        </>
      )}
      <h4 className="pg-h4">앞 절반 / 뒤 절반 IC (시간이 지나도 버티나)</h4>
      <table className="pg-table pg-av-isoos"><tbody>
        <tr><td className="pg-td-name">앞 절반</td><td className={`pg-td-num${(num(oos.is_ic) ?? 0) < 0 ? " pg-neg" : ""}`}>{num(oos.is_ic) === null ? "— (측정 불가)" : sgn(oos.is_ic)}</td></tr>
        <tr><td className="pg-td-name">뒤 절반</td><td className={`pg-td-num${(num(oos.oos_ic) ?? 0) < 0 ? " pg-neg" : ""}`}>{num(oos.oos_ic) === null ? "— (측정 불가)" : sgn(oos.oos_ic)}</td></tr>
        <tr><td className="pg-td-name">나눈 방식</td><td className="pg-td-num">{String(oos.split ?? "—")}</td></tr>
      </tbody></table>
      {top.length > 0 && (
        <p className="pg-note pg-av-stale">상위 종목 점수는 표본 마지막 날({String(r.period_end ?? "미상")}) 값입니다 — 오늘 기준 비중은 ‘알파 포트폴리오’ 노드에서 산출합니다.
          {" "}{top.slice(0, 5).map((t) => String(t.name ?? t.ticker)).join(", ")}</p>
      )}
      {q.length > 0 && (
        <>
          <h4 className="pg-h4">점수 분위별 연 수익 (낮은 점수 → 높은 점수)</h4>
          <table className="pg-table"><tbody>{q.map((x, i) => (
            <tr key={i}><td className="pg-td-name">{i + 1}분위</td>
              <td className="pg-td-bar"><span className={`pg-bar${x < 0 ? " pg-bar--neg" : ""}`} style={{ width: `${(Math.abs(x) / max) * 100}%` }} /></td>
              <td className={`pg-td-num${x < 0 ? " pg-neg" : ""}`}>{pct(x)}</td></tr>
          ))}</tbody></table>
        </>
      )}
      <p className="pg-note">과거 표본의 순위 상관입니다 — 거래 비용을 빼지 않았고, 앞으로의 예측력을 말해 주지 않습니다.</p>
    </>
  );
}

export function AlphaPortfolioResult({ v, bars }: { v: Dict; bars: ReactNode }) {
  const excluded = (v.excluded as Dict[]) ?? [];
  const warnings = (v.warnings as string[]) ?? [];
  const pairs = (v.pairwise as Dict[]) ?? [];
  return (
    <>
      <KV rows={[["유효 알파 수", num(v.effective_n) === null ? "—" : (v.effective_n as number).toFixed(1)],
                 ["기준일", String(v.as_of_effective ?? "오늘")]]} />
      {/* ★경고·제외 사유는 접지 않는다★ — 같은 베팅을 두 번 한 것, 빠진 알파가 있는 것은 결과를 읽는 방식을 바꾼다. */}
      {warnings.map((w, i) => <p key={`w${i}`} className="pg-warn pg-ap-warn">{w}</p>)}
      {excluded.map((e, i) => <p key={`x${i}`} className="pg-warn pg-ap-warn">뺀 알파 {String(e.alpha_id)} — {String(e.reason)}</p>)}
      {pairs.length > 0 && (
        <table className="pg-table pg-ap-corr">
          <thead><tr><th>두 알파</th><th className="pg-td-num">순위 상관</th></tr></thead>
          <tbody>{pairs.map((x, i) => (
            <tr key={i} className={x.duplicate ? "dup" : ""}>
              <td className="pg-td-name">{String(x.a)} · {String(x.b)}{x.duplicate ? " (사실상 같은 베팅)" : ""}</td>
              <td className="pg-td-num">{num(x.rho) === null ? String(x.reason ?? "정의 불가") : sgn(x.rho, 2)}</td>
            </tr>
          ))}</tbody>
        </table>
      )}
      {bars}
      <p className="pg-note">{String(v.note ?? "")}</p>
    </>
  );
}
