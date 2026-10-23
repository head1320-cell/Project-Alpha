"use client";
/**
 * 전략·기업 노드의 결과 (BK W5) — 전략 묶음 · 기업 전망 · 가치평가 점수 · 결정 되짚기
 * ==========================================================================
 * 수는 서버 view 그대로다. ★재지 않은 칸은 0 이 아니라 "안 쟀어요"★ — 귀인 효과·체결 품질·브린슨 분해가
 * `null` 이면 그 이름을 적고 비워 둔다. 전략 묶음의 곡선은 계좌 금액, 낙폭은 같은 축의 아래 띠로 보인다.
 */
import type { ReactNode } from "react";
import { Area, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { PerfLabel } from "@/shared/ui/PerfLabel";
import type { PerfLabelValue } from "@/shared/ui/PerfLabel";

type Dict = Record<string, unknown>;
const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const pct = (v: unknown, d = 1) => (num(v) === null ? "—" : `${(v as number).toFixed(d)}%`);
const signed = (v: unknown, d = 1) => (num(v) === null ? "—" : `${(v as number) >= 0 ? "+" : ""}${(v as number).toFixed(d)}%`);
const won = (v: unknown) => (num(v) === null ? "—" : `${Math.round(v as number).toLocaleString("ko-KR")}원`);
const NOT_MEASURED = "안 쟀어요";

function KV({ rows }: { rows: [string, ReactNode][] }) {
  return <dl className="pg-kv">{rows.map(([k, v]) => (<div key={k}><dt>{k}</dt><dd>{v}</dd></div>))}</dl>;
}

function Bars({ rows, labels, fmt = (x) => pct(x, 2) }: {
  rows: [string, number][]; labels?: Record<string, string>; fmt?: (x: number) => string;
}) {
  const max = Math.max(1e-9, ...rows.map(([, v]) => Math.abs(v)));
  return (
    <table className="pg-table"><tbody>
      {rows.map(([k, v]) => (
        <tr key={k}><td className="pg-td-name" title={k}>{labels?.[k] ?? k}</td>
          <td className="pg-td-bar"><span className={`pg-bar${v < 0 ? " pg-bar--neg" : ""}`} style={{ width: `${(Math.abs(v) / max) * 100}%` }} /></td>
          <td className="pg-td-num">{fmt(v)}</td></tr>
      ))}
    </tbody></table>
  );
}

// ── 전략 묶음 ────────────────────────────────────────────────────────────────

const EFFECT: [string, string][] = [["allocation_effect_pct", "나누는 방식"], ["cost_effect_pct", "거래 비용"],
  ["netting_effect_pct", "주문 상계"], ["cash_effect_pct", "현금 이자"], ["macro_effect_pct", "매크로 조정"]];

export function StrategyBacktestResult({ v }: { v: Dict }) {
  const s = (v.summary as Dict) ?? {};
  const names = (v.strategy_names as Record<string, string>) ?? {};
  const curve = (v.curve as { date: string; equity: number; dd: number }[]) ?? [];
  const step = Math.max(1, Math.floor(curve.length / 300));
  const data = curve.filter((_, i) => i % step === 0 || i === curve.length - 1);
  const attr = (s.attribution as Dict) ?? {};
  const per = (v.period as Dict) ?? {};
  const srcs = ((v.sources as Dict)?.strategies as Dict[]) ?? [];
  const last = Object.entries((v.last_weights as Record<string, number>) ?? {}).map(([k, w]) => [k, w * 100] as [string, number])
    .sort((a, b) => b[1] - a[1]);
  return (
    <>
      {/* ★숫자 바로 위에 그 숫자의 신원★ — 원천 전략들의 mock 여부로 정한 라벨(서버 `_label_from_sources`). */}
      {v.perf_label ? <div className="pg-perf"><PerfLabel value={v.perf_label as PerfLabelValue} /></div> : null}
      <div className="pg-chart" aria-label="계좌 금액과 낙폭">
        <ResponsiveContainer width="100%" height={170}>
          <ComposedChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
            <XAxis dataKey="date" hide />
            <YAxis yAxisId="e" domain={["auto", "auto"]} width={52} tick={{ fontSize: 10 }}
                   tickFormatter={(x: number) => `${Math.round(x / 1e4).toLocaleString("ko-KR")}만`} />
            <YAxis yAxisId="d" orientation="right" domain={["dataMin", 0]} hide />
            <Tooltip formatter={(x: number, n: string) => (n === "낙폭" ? `${x.toFixed(1)}%` : won(x))} />
            <Area yAxisId="d" dataKey="dd" name="낙폭" stroke="none" fill="var(--pg-fail)" fillOpacity={0.14} isAnimationActive={false} />
            <Line yAxisId="e" dataKey="equity" name="계좌" dot={false} stroke="var(--pg-st-check)" strokeWidth={1.6} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <KV rows={[["기간", `${String(per.start)} ~ ${String(per.end)}${per.whole_record ? " · 함께 기록된 전체" : ""}`],
                 ["전체 수익", signed(s.total_return_pct)], ["연 수익", signed(s.annualized_return_pct)],
                 ["가장 크게 빠진 폭", pct(s.max_drawdown_pct)],
                 ["샤프 비율", num(s.sharpe_ratio_full) === null ? "계산 못 함" : (s.sharpe_ratio_full as number).toFixed(2)],
                 ["다시 나눈 횟수", `${String(s.n_rebalances ?? "—")}번`], ["거래일", `${String(v.n_trading_days ?? "—")}일`]]} />
      <h4 className="pg-h4">마지막 날 전략 비중</h4>
      <Bars rows={last} labels={names} />
      <h4 className="pg-h4">수익을 나눠 보면</h4>
      <table className="pg-table"><tbody>
        {EFFECT.map(([k, label]) => (
          <tr key={k}><td className="pg-td-name">{label}</td>
            <td className="pg-td-num">{num(attr[k]) === null ? <span className="pg-tag pg-tag--unknown">{NOT_MEASURED}</span> : signed(attr[k], 2)}</td></tr>
        ))}
      </tbody></table>
      <h4 className="pg-h4">전략 출처</h4>
      <ul className="pg-src">
        {srcs.map((x) => (
          <li key={String(x.strategy_id)}>
            <b>{String(x.name ?? `전략 ${String(x.strategy_id)}`)}</b>
            {x.registered === false ? <span className="pg-tag pg-tag--failed">등록 안 됨</span> : null}
            {x.is_mock_data === true ? <span className="pg-tag pg-tag--unknown">연습용 데이터</span>
              : x.is_mock_data === null ? <span className="pg-tag pg-tag--unknown">데이터 출처 미상</span> : null}
            {x.is_pit_verified === true ? <span className="pg-tag pg-tag--confirmed">시점 정합 확인</span> : <span className="pg-tag pg-tag--assumed">시점 정합 미확인</span>}
            {x.repro_equal === true ? <span className="pg-tag pg-tag--confirmed">다시 돌려 같음</span> : null}
          </li>
        ))}
      </ul>
      {((v.warnings as string[]) ?? []).map((w) => <p key={w} className="pg-warn">{w}</p>)}
    </>
  );
}

// ── 기업 전망 ────────────────────────────────────────────────────────────────

function Reasons({ reasons, labels, title }: { reasons: Record<string, unknown>; labels: Record<string, string>; title: string }) {
  const rows = Object.entries(reasons);
  if (!rows.length) return null;
  return (
    <>
      <h4 className="pg-h4">{title}</h4>
      <ul className="pg-list">{rows.map(([c, r]) => (
        <li key={c}>{labels[c] ?? c} <span className="pg-code">{c}</span> — {typeof r === "string" ? r : String((r as Dict)?.reason ?? "")}</li>
      ))}</ul>
    </>
  );
}

export function CompanyViewsResult({ v }: { v: Dict }) {
  const views = (v.views as Dict[]) ?? [];
  const labels = (v.labels as Record<string, string>) ?? {};
  return (
    <>
      <p className="pg-model-type pg-model-type--hypo">지금 시점에만 쓰는 전망이에요</p>
      <table className="pg-table">
        <thead><tr><th>종목</th><th>방향</th><th className="pg-td-num">연 크기</th><th className="pg-td-num">확신</th></tr></thead>
        <tbody>{views.map((x) => {
          const code = String(((x.assets as string[]) ?? [])[0] ?? "");
          return (
            <tr key={code}>
              <td className="pg-td-name" title={code}>{labels[code] ?? code}</td>
              <td className={x.direction === -1 ? "pg-neg" : ""}>{x.direction === -1 ? "내린다" : "오른다"}</td>
              <td className="pg-td-num">{pct(x.magnitude_pct)}</td>
              <td className="pg-td-num">{pct(x.confidence, 0)}{x.confidence_saturated ? " · 상한" : ""}</td>
            </tr>
          );
        })}</tbody>
      </table>
      {num(v.n_user_views) ? <p className="pg-note">내 생각 {String(v.n_user_views)}개와 함께 ‘비중 계산’으로 넘겨요.</p> : null}
      <Reasons reasons={(v.reasons as Record<string, unknown>) ?? {}} labels={labels} title="전망을 만들지 못한 종목" />
    </>
  );
}

// ── 가치평가 점수 ────────────────────────────────────────────────────────────

export function ValuationScoresResult({ v }: { v: Dict }) {
  const rows = (v.rows as Dict[]) ?? [];
  const scores = (v.scores as Record<string, number>) ?? {};
  const labels = (v.labels as Record<string, string>) ?? {};
  // 수를 모르는 종목은 순위에 넣지 않는다(0 으로 가운데에 세우지 않는다) — 아래에 따로 적는다.
  const ranked = Object.entries(scores).filter(([, s]) => typeof s === "number" && Number.isFinite(s)).sort((a, b) => b[1] - a[1]);
  const unscored = Object.entries(scores).filter(([, s]) => !(typeof s === "number" && Number.isFinite(s))).map(([c]) => c);
  const byCode = Object.fromEntries(rows.map((r) => [String(r.ticker), r]));
  const max = Math.max(1e-9, ...ranked.map(([, s]) => Math.abs(s)));
  return (
    <>
      <table className="pg-table">
        <thead><tr><th>종목 · 판정</th><th className="pg-td-bar">싼 정도</th><th className="pg-td-num">적정가 대비</th></tr></thead>
        <tbody>{ranked.map(([c, s]) => (
          <tr key={c}>
            <td className="pg-td-name" title={c}>{labels[c] ?? c}<span className="pg-verdict">{String(byCode[c]?.verdict ?? "—")}</span></td>
            <td className="pg-td-bar"><span className={`pg-bar${s < 0 ? " pg-bar--neg" : ""}`} style={{ width: `${(Math.abs(s) / max) * 100}%` }} /></td>
            <td className="pg-td-num">{s >= 0 ? `${s.toFixed(1)}% 싸요` : `${(-s).toFixed(1)}% 비싸요`}</td>
          </tr>
        ))}</tbody>
      </table>
      {unscored.length > 0 && <p className="pg-warn">점수를 내지 못한 종목: {unscored.map((c) => labels[c] ?? c).join(", ")}</p>}
      <p className="pg-note">점수는 −괴리율이에요. 적정가를 내지 못한 종목은 0으로 치지 않고 아래에 따로 적어요.</p>
      <Reasons reasons={(v.reasons as Record<string, unknown>) ?? {}} labels={labels} title="점수를 매기지 못한 종목" />
    </>
  );
}

// ── 결정 되짚기 ──────────────────────────────────────────────────────────────

export function AttributionResult({ v }: { v: Dict }) {
  const ret = (v.returns as Dict) ?? {};
  const eva = (v.expected_vs_actual as Dict) ?? {};
  const rc = (v.risk_compare as Dict) ?? {};
  const cov = (v.coverage as Dict) ?? {};
  const brin = (v.brinson_effects as Dict) ?? {};
  const assets = (((v.contribution as Dict)?.assets as Dict[]) ?? []).map((a) => [String(a.code), num(a.contribution_pct) ?? 0] as [string, number]);
  const unmeasured = [["selection", "종목 선택"], ["allocation", "업종 배분"], ["factor", "팩터"], ["hedge", "헤지"], ["timing", "타이밍"]]
    .filter(([k]) => brin[k] == null).map(([, l]) => l);
  if ((v.fill_quality as Dict)?.basis === "unavailable") unmeasured.push("체결 품질");
  return (
    <>
      <KV rows={[["결정한 날", String(v.decision_date)], ["되짚은 날", `${String(v.as_of)} (${String(v.elapsed_days)}일 뒤)`],
                 ["실제 수익", signed(ret.portfolio_pct, 2)],
                 [`${String(ret.benchmark_label ?? "비교 기준")} 대비`, num(ret.excess_pct) === null ? NOT_MEASURED : signed(ret.excess_pct, 2)],
                 ["기대했던 수익", num(eva.expected_return_pct) === null ? NOT_MEASURED : signed(eva.expected_return_pct, 2)],
                 ["기대와의 차이", num(eva.gap_pct) === null ? NOT_MEASURED : signed(eva.gap_pct, 2)],
                 ["흔들림 (기대 → 실제)", `${pct((rc.ex_ante as Dict)?.vol_pct)} → ${pct((rc.ex_post as Dict)?.vol_pct)}`],
                 ["가격을 잰 종목", `${String(cov.covered ?? 0)}/${String(cov.tickers ?? 0)}`]]} />
      {assets.length > 0 && (<><h4 className="pg-h4">종목별 기여</h4><Bars rows={assets} labels={(v.labels as Record<string, string>) ?? {}} /></>)}
      {unmeasured.length > 0 && (
        <>
          <h4 className="pg-h4">안 잰 것</h4>
          <div className="pg-chips-static">{unmeasured.map((u) => <span key={u} className="pg-tag pg-tag--unknown">{u}</span>)}</div>
          <p className="pg-note">벤치마크 구성종목 비중과 연결된 실제 체결이 있어야 잴 수 있어요 — 비슷한 값으로 채우지 않아요.</p>
        </>
      )}
    </>
  );
}
