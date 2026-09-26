"use client";
/**
 * 매크로 웨이브의 결과 (BL3 W2) — 수익률 곡선 · 지표 대시보드 · 국면 합의 · 국면 예측 적중률 · 장기 관계 · 스튜디오 모델
 * ==========================================================================
 * 수는 서버 view 그대로 그린다(다시 계산하지 않는다). 재지 못한 칸은 0 이 아니라 "—" 와 사유다.
 * 이 웨이브에서 눈에 띄게 그리는 것은 곡선 하나다 — 뒤집힌 구간을 곡선 위에 칠해 "어디가 역전인지" 를 보여 준다.
 */
import type { ReactNode } from "react";
import { CartesianGrid, Line, LineChart, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

type Dict = Record<string, unknown>;
const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const fx = (v: unknown, d = 2, unit = "") => (num(v) === null ? "—" : `${(v as number).toFixed(d)}${unit}`);
const big = (v: unknown) => (num(v) === null ? "—" : (v as number).toLocaleString("ko-KR", { maximumFractionDigits: Math.abs(v as number) >= 1000 ? 0 : 2 }));
const sg = (v: unknown, d = 2, unit = "") =>
  (num(v) === null ? "—" : `${(v as number) >= 0 ? "+" : "−"}${Math.abs(v as number).toFixed(d)}${unit}`);

function KV({ rows }: { rows: [string, ReactNode][] }) {
  return <dl className="pg-kv">{rows.map(([k, v]) => (<div key={k}><dt>{k}</dt><dd>{v}</dd></div>))}</dl>;
}

/** 작은 추이선 — 값이 둘 미만이면 그리지 않고 비운다(선 하나를 지어내지 않는다). */
function Spark({ values, w = 72, h = 20 }: { values: number[]; w?: number; h?: number }) {
  const vs = values.filter((x) => Number.isFinite(x));
  if (vs.length < 2) return <span className="pg-spark pg-spark--empty" aria-hidden="true" />;
  const lo = Math.min(...vs), hi = Math.max(...vs), rg = hi - lo || 1, st = w / (vs.length - 1);
  const pts = vs.map((v, i) => `${(i * st).toFixed(1)},${(h - 1 - ((v - lo) / rg) * (h - 2)).toFixed(1)}`).join(" ");
  return (
    <svg className="pg-spark" width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true">
      <polyline points={pts} fill="none" stroke="var(--pg-blue)" strokeWidth={1.4} strokeLinejoin="round" />
    </svg>
  );
}

const REGIME_KO: Record<string, string> = {
  Goldilocks: "골디락스(성장↑·물가↓)", Reflation: "리플레이션(성장↑·물가↑)",
  Stagflation: "스태그플레이션(성장↓·물가↑)", Disinflation: "디스인플레이션(성장↓·물가↓)",
};
const rk = (r: unknown) => REGIME_KO[String(r)] ?? String(r ?? "—");
const TOOL_KO: Record<string, string> = { axis: "성장·물가 축", markov: "상태 전환", cluster: "군집" };

// ── 수익률 곡선 ─────────────────────────────────────────────────────────────

export function YieldCurveResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const pts = ((r.points as Dict[]) ?? []).map((p) => ({ t: String(p.label), y: num(p.yield_pct) }));
  // 뒤집힌 구간 = 만기가 긴 점의 금리가 앞 점보다 낮은 이웃 쌍. 서버의 역전 판정(2Y·10Y)과 별개로 모양을 보여 준다.
  const dips = pts.slice(1).map((p, i) => ({ a: pts[i], b: p }))
    .filter(({ a, b }) => a.y !== null && b.y !== null && (b.y as number) < (a.y as number));
  const inv = Boolean(r.inversion);
  return (
    <>
      <div className={`pg-chart pg-curve${inv ? " pg-curve--inv" : ""}`} role="img"
           aria-label={`수익률 곡선 ${pts.map((p) => `${p.t} ${fx(p.y)}%`).join(", ")}${inv ? " · 역전" : ""}`}>
        <ResponsiveContainer width="100%" height={170}>
          <LineChart data={pts} margin={{ top: 10, right: 14, bottom: 4, left: 0 }}>
            <CartesianGrid stroke="var(--pg-line)" strokeDasharray="2 4" vertical={false} />
            {dips.map(({ a, b }) => (
              <ReferenceArea key={`${a.t}-${b.t}`} x1={a.t} x2={b.t} fill="var(--pg-fail-soft)" fillOpacity={0.9} ifOverflow="extendDomain" />
            ))}
            <XAxis dataKey="t" tick={{ fontSize: 11 }} />
            <YAxis width={40} tick={{ fontSize: 11 }} unit="%" domain={["auto", "auto"]} />
            <Tooltip formatter={(x: number) => `${x.toFixed(2)}%`} />
            <Line dataKey="y" name="금리" stroke="var(--pg-blue)" strokeWidth={2.2} dot={{ r: 3.5 }} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <KV rows={[
        ["10년 − 2년", <span key="s" className={num(r.spread_2y10y_bp) !== null && (r.spread_2y10y_bp as number) < 0 ? "pg-neg" : ""}>
          {sg(r.spread_2y10y_bp, 0, "bp")}</span>],
        ["판정", inv ? "역전 — 짧은 금리가 더 높아요" : "정상 — 긴 금리가 더 높아요"],
      ]} />
      {dips.length > 0 && <p className="pg-note"><span className="pg-dot-inv" aria-hidden="true" />칠한 구간은 만기가 길어지는데 금리가 낮아지는 곳이에요.</p>}
      <p className="pg-note"><span className="pg-tag pg-tag--assumed">경험칙</span> {String(r.interpretation ?? "")}</p>
    </>
  );
}

// ── 지표 대시보드 ───────────────────────────────────────────────────────────

/** z 막대 — 가운데가 5년 평균, 좌우 끝이 ±3σ. 방향은 위치로만 말한다(색은 하나). z 가 없으면 막대 대신 '모름'. */
function ZBar({ z }: { z: number | null }) {
  if (z === null) return <span className="pg-zbar pg-zbar--none">모름</span>;
  const c = Math.max(-3, Math.min(3, z));
  const w = (Math.abs(c) / 3) * 50;
  return (
    <span className="pg-zbar" role="img" aria-label={`5년 평균에서 ${sg(z, 1)} 표준편차`}>
      <i style={{ width: `${w}%`, left: c < 0 ? `${50 - w}%` : "50%" }} />
    </span>
  );
}

export function MacroDashboardResult({ v }: { v: Dict }) {
  const themes = (v.themes as Dict[]) ?? [];
  return (
    <>
      {themes.map((t) => (
        <div key={String(t.key)} className="pg-dash-theme">
          <h4 className="pg-dash-h">{String(t.label)}</h4>
          <table className="pg-table pg-dash">
            <tbody>{((t.indicators as Dict[]) ?? []).map((i) => (
              <tr key={String(i.id)}>
                <td className="pg-td-name" title={String(i.id)}>{String(i.name ?? i.id)}</td>
                <td className="pg-td-num pg-nowrap">{big(i.latest)}{i.unit ? <span className="pg-unit"> {String(i.unit)}</span> : null}</td>
                {/* 방향에 색을 입히지 않는다 — 실업률이 내려가는 것과 GDP 가 내려가는 것은 좋고 나쁨이 반대다 */}
                <td className="pg-td-num pg-nowrap pg-muted">{sg(i.delta, 2)}</td>
                <td className="pg-td-z"><ZBar z={num(i.z_score)} /></td>
                <td className="pg-td-spark"><Spark values={(i.spark as number[]) ?? []} /></td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      ))}
      <p className="pg-note">막대 가운데가 최근 5년 평균, 양 끝이 ±3 표준편차예요. 추이선은 최근 24개 관측이에요.</p>
    </>
  );
}

// ── 국면 합의 ───────────────────────────────────────────────────────────────

export function ConsensusResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const per = (r.per_tool as Record<string, string>) ?? {};
  const reasons = (r.reasons as Record<string, string>) ?? {};
  const dis = (r.disagreement as Dict) ?? {};
  return (
    <>
      <p className={`pg-model-type pg-model-type--${r.consensus ? "hist" : "hypo"}`}>
        {r.tie ? "표가 갈려 결론이 없어요" : r.consensus ? `모두 ${rk(r.verdict)}` : `다수 ${rk(r.verdict)} · 갈림`}
      </p>
      <table className="pg-table pg-consensus"><tbody>
        {Object.keys({ ...per, ...reasons }).map((k) => (
          <tr key={k}>
            <td className="pg-td-name">{TOOL_KO[k] ?? k}</td>
            <td className={per[k] ? (per[k] === r.verdict ? "pg-strong" : "") : "pg-muted"}>
              {per[k] ? rk(per[k]) : `판정 못 함 — ${reasons[k] ?? "사유 미상"}`}
            </td>
          </tr>
        ))}
      </tbody></table>
      <KV rows={[["답한 방법", `${String(r.n_available ?? 0)}개`], ["갈림 정도", fx(dis.score, 2)]]} />
      <p className="pg-note">{String(r.note ?? "")} 세 방법을 평균 내지 않아요.</p>
    </>
  );
}

// ── 국면 예측 적중률 ────────────────────────────────────────────────────────

function Meter({ label, value, max, text, tone }: { label: string; value: number | null; max: number; text: string; tone?: string }) {
  const w = value === null ? 0 : Math.max(0, Math.min(1, value / max)) * 100;
  return (
    <div className="pg-bar-row">
      <span className="pg-bar-name">{label}</span>
      <span className="pg-bar-track"><i className={tone ?? ""} style={{ width: `${w}%` }} /></span>
      <span className="pg-bar-pct">{text}</span>
    </div>
  );
}

export function CoverageResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const cov = num(r.coverage), tgt = num(r.target);
  const mine = num(r.mean_set_size), base = num(r.baseline_mean_set_size);
  const mx = Math.max(mine ?? 0, base ?? 0, 1);
  return (
    <>
      <div className="pg-bars">
        <Meter label="목표" value={tgt} max={1} text={tgt === null ? "—" : `${(tgt * 100).toFixed(0)}%`} tone="mute" />
        <Meter label="실측" value={cov} max={1} text={cov === null ? "—" : `${(cov * 100).toFixed(1)}%`} />
      </div>
      <p className="pg-note">적중률은 목표 근처로 나오게 만들어져요 — 비교는 아래 집합 크기로 해요.</p>
      <div className="pg-bars">
        <Meter label="전이 모형" value={mine} max={mx} text={fx(mine, 2, "개")} />
        <Meter label="기저율" value={base} max={mx} text={fx(base, 2, "개")} tone="mute" />
      </div>
      <KV rows={[
        ["기저율 대비 집합 축소", num(r.set_size_skill_pct) === null ? "— (기준선 없음)" : sg(r.set_size_skill_pct, 1, "%")],
        ["채점", `${String(r.n_eval ?? "—")}회 · 맞힘 ${String(r.hits ?? "—")} · 놓침 ${String(r.misses ?? "—")}`],
        ["방식", r.walk_forward ? "그 시점 이전 경로만 써서 예측" : "확인되지 않음"],
      ]} />
    </>
  );
}

// ── 장기 관계 ───────────────────────────────────────────────────────────────

export function LongRunResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const ev = (r.evidence as Dict) ?? {};
  const ts = (ev.trace_stat as number[]) ?? [];
  const cv = (ev.crit_95 as number[]) ?? [];
  return (
    <>
      <p className={`pg-model-type pg-model-type--${r.model === "vecm" ? "hist" : "hypo"}`}>
        {r.model === "vecm" ? `오차수정 모형(VECM) · 균형 ${String(r.coint_rank)}개` : r.model === "diff_var" ? "차분 VAR · 장기 균형 없음" : String(r.model ?? "—")}
      </p>
      <p className="pg-note">{String(r.reason ?? "")}</p>
      {ts.length > 0 && (
        <table className="pg-table pg-trace">
          <thead><tr><th>균형 수 ≤</th><th className="pg-td-num">검정값</th><th className="pg-td-num">95% 기준</th><th>판정</th></tr></thead>
          <tbody>{ts.map((t, i) => (
            <tr key={i}>
              <td>{i}</td><td className="pg-td-num">{fx(t, 1)}</td><td className="pg-td-num">{fx(cv[i], 1)}</td>
              <td className={t > (cv[i] ?? Infinity) ? "pg-strong" : "pg-muted"}>{t > (cv[i] ?? Infinity) ? "기각" : "기각 못 함"}</td>
            </tr>
          ))}</tbody>
        </table>
      )}
      <KV rows={[["관측", `${String((r.span as Dict)?.n ?? "—")}개월`]]} />
      <p className="pg-note">쓴 계열 {((r.used as string[]) ?? []).length}개 — {((r.used as string[]) ?? []).join(", ") || "—"}</p>
      {r.missing_note ? <p className="pg-warn">{String(r.missing_note)}</p> : null}
    </>
  );
}

// ── 스튜디오 모델 ───────────────────────────────────────────────────────────

/** 엔진 출력 키 → 쉬운 이름. 모르는 키는 원래 이름 그대로(지어내지 않는다). */
const OUT_KO: Record<string, string> = {
  series: "쓴 계열", series_used: "쓴 계열", k_factors: "요인 수", explained_var: "설명한 분산 몫", loadings: "요인 적재",
  latest: "마지막 값", factors: "요인", level: "수준", slope: "기울기", curvature: "곡률", lambda: "감쇠 λ",
  tenors: "만기(년)", n_series: "계열 수", nodes: "지표", edges: "선후 관계", target: "대상",
};
const plain = (x: unknown) => String(x ?? "").replace(/★|\*\*/g, "");

/** 엔진마다 출력 모양이 다르다 — 수는 수로, 수열은 추이선+마지막 값으로, 간선은 화살표로. 모르는 모양은 원자료. */
function Outputs({ o }: { o: Dict }) {
  const rows: [string, ReactNode][] = [];
  const tables: ReactNode[] = [];
  for (const [k, x] of Object.entries(o)) {
    const label = OUT_KO[k] ?? k;
    if (num(x) !== null) rows.push([label, fx(x, 4)]);
    else if (Array.isArray(x) && x.length > 0 && x.every((y) => num(y) !== null)) {
      rows.push([label, <span key={k} className="pg-spark-cell"><Spark values={x as number[]} />{fx((x as number[])[x.length - 1], 3)}</span>]);
    } else if (k === "edges" && Array.isArray(x)) {
      tables.push(
        <div key={k} className="pg-edges">
          {x.length === 0 ? <p className="pg-note">유의한 선후 관계가 없었어요.</p>
            : (x as Dict[]).map((e, i) => (
              <div key={i} className="pg-edge-row">{String(e.source ?? e.from ?? "?")} → {String(e.target ?? e.to ?? "?")}
                {num(e.p_value) !== null ? <span className="pg-muted"> · p {fx(e.p_value, 3)}</span> : null}</div>
            ))}
        </div>,
      );
    } else if (x && typeof x === "object" && !Array.isArray(x)) {
      const ent = Object.entries(x as Dict).filter(([, y]) => Array.isArray(y) || num(y) !== null).slice(0, 12);
      if (ent.length) {
        tables.push(
          <table key={k} className="pg-table pg-studio-tab"><caption>{label}</caption><tbody>
            {ent.map(([n, y]) => <tr key={n}><td className="pg-td-name">{n}</td>
              <td className="pg-td-num">{Array.isArray(y) ? (y as unknown[]).map((z) => fx(z, 3)).join(" · ") : fx(y, 3)}</td></tr>)}
          </tbody></table>,
        );
      }
    } else if (Array.isArray(x) && x.every((y) => typeof y === "string")) {
      rows.push([label, (x as string[]).join(", ")]);
    }
  }
  return <>{rows.length > 0 && <KV rows={rows} />}{tables}</>;
}

export function StudioResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const s = (v.studio as Dict) ?? {};
  return (
    <>
      <p className="pg-note"><b>{String(s.question ?? "")}</b></p>
      <KV rows={[["돌린 엔진", String(r.engine ?? s.substitute ?? "—")]]} />
      <p className="pg-note pg-studio-frontier">프런티어 엔진 ‘{String(s.frontier ?? "—")}’ — 이 노드는 돌리지 않아요. 돌릴 수 있는지는 매크로 화면의 능력 사다리가 판정해요.</p>
      <Outputs o={(r.outputs as Dict) ?? {}} />
      {r.note ? <p className="pg-warn">{plain(r.note)}</p> : null}
    </>
  );
}
