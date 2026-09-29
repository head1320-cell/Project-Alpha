"use client";
/**
 * 견고성 — 같이 무너지나 (BR R1). 전략 합치기의 한 절 · 견고성 비교 노드의 본문.
 * ★수는 서버 view(`robustness`) 그대로★ — 다시 계산하지 않는다. 모르는 칸은 "—" 와 서버 사유.
 * 가로축은 "n거래일 전" — 시세 로더에 날짜가 없어 날짜를 지어내지 않는다(서버 `axis: trading_days_ago`).
 * 색만으로 가르지 않는다: 추이는 한 번에 한 계열(칩으로 고름) · 띠는 면, 값은 선 · 막대마다 글자 값.
 */
import { useId, useState } from "react";
import { PerfLabel, type PerfLabelValue } from "@/shared/ui/PerfLabel";

type Dict = Record<string, unknown>;
const num = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const fx = (v: unknown, d = 2) => (num(v) ? v.toFixed(d) : "—");
const pct = (v: unknown, d = 1) => (num(v) ? `${v.toFixed(d)}%` : "—");
const signed = (v: unknown, d = 0) => (num(v) ? `${v > 0 ? "+" : ""}${v.toFixed(d)}%` : "—");

type Pair = { a: string; b: string } & Dict;
type Rolling = { available: boolean; reason?: string; window: number; ago: number[]; pairs: (Pair & {
  values: (number | null)[]; lo: (number | null)[]; hi: (number | null)[]; current: number | null; max: number | null; n_empty: number })[];
  avg: (number | null)[]; avg_current: number | null; avg_max: number | null; note?: string };

/** 모르는 절 — 무엇을 못 쟀는지와 서버 사유 한 줄(빈 표·0 을 그리지 않는다). */
function Unknown({ text, reason }: { text: string; reason?: unknown }) {
  return <p className="pg-help">{text} — {String(reason ?? "사유 없음")}</p>;
}

/** 상관 추이 — 세로축은 늘 -1~1(쌍끼리·시점끼리 같은 눈금) · 띠 = 표본 오차 95%. */
function Trend({ r }: { r: Rolling }) {
  const opts = [{ key: "avg", label: "평균", values: r.avg, lo: null as (number | null)[] | null, hi: null as (number | null)[] | null },
    ...r.pairs.map((p, i) => ({ key: `p${i}`, label: `${p.a}·${p.b}`, values: p.values, lo: p.lo, hi: p.hi }))];
  const [pick, setPick] = useState(opts.length > 2 ? "avg" : "p0");
  const s = opts.find((o) => o.key === pick) ?? opts[0];
  const W = 340, H = 112, pad = 6;
  const n = s.values.length;
  const X = (i: number) => pad + (i / Math.max(1, n - 1)) * (W - 2 * pad);
  const Y = (v: number) => pad + (1 - (v + 1) / 2) * (H - 2 * pad);
  // 값이 없는 창(흔들림 없음)은 선을 끊는다 — 건너뛰어 이으면 없는 관계를 그린다.
  const runs: number[][] = [];
  s.values.forEach((v, i) => {
    if (!num(v)) return;
    const cur = runs[runs.length - 1];
    if (cur && cur[cur.length - 1] === i - 1) cur.push(i); else runs.push([i]);
  });
  const pt = (i: number, v: number) => `${X(i).toFixed(1)},${Y(v).toFixed(1)}`;
  const lines = runs.map((r) => r.map((i) => pt(i, s.values[i] as number)).join(" "));
  const bands = s.lo && s.hi ? runs.filter((r) => r.every((i) => num(s.hi![i]) && num(s.lo![i]))).map((r) =>
    [...r.map((i) => pt(i, s.hi![i] as number)), ...[...r].reverse().map((i) => pt(i, s.lo![i] as number))].join(" ")) : [];
  const got = s.values.filter(num);
  const last = [...s.values].reverse().find(num);
  return (
    <>
      {opts.length > 2 && (
        <div className="pg-rob-picks" role="group" aria-label="볼 쌍">
          {opts.map((o) => (
            <button key={o.key} type="button" className={`pg-chip pg-chip--sm${pick === o.key ? " on" : ""}`}
                    aria-pressed={pick === o.key} onClick={() => setPick(o.key)}>{o.label}</button>
          ))}
        </div>
      )}
      <svg className="pg-rob-trend" viewBox={`0 0 ${W} ${H + 16}`} role="img"
           aria-label={`${s.label} 상관 추이 — 지금 ${fx(last)} · 최고 ${fx(got.length ? Math.max(...got) : null)} · 최저 ${fx(got.length ? Math.min(...got) : null)}`}>
        <line x1={pad} x2={W - pad} y1={Y(0)} y2={Y(0)} className="pg-risk-zero" />
        {bands.map((b, k) => <polygon key={`b${k}`} points={b} className="pg-rob-band" />)}
        {lines.map((l, k) => <polyline key={`l${k}`} points={l} className="pg-rob-line" />)}
        <text x={pad} y={H + 13} className="pg-floors-t">{r.ago[0]}거래일 전</text>
        <text x={W - pad} y={H + 13} textAnchor="end" className="pg-floors-t">오늘</text>
        <text x={W - pad} y={Y(1) + 9} textAnchor="end" className="pg-floors-t">1</text>
        <text x={W - pad} y={Y(-1) - 2} textAnchor="end" className="pg-floors-t">−1</text>
      </svg>
      <dl className="pg-kv">
        <div><dt>지금</dt><dd>{fx(last)}</dd></div>
        <div><dt>이 기간 최고 · 최저</dt><dd>{got.length ? `${Math.max(...got).toFixed(2)} · ${Math.min(...got).toFixed(2)}` : "—"}</dd></div>
      </dl>
      {s.lo === null && <p className="pg-help">평균은 모든 쌍의 창 상관 평균이에요 — 표본 오차 띠는 쌍을 고르면 보여요.</p>}
      <p className="pg-help">{r.note}</p>
    </>
  );
}

function Crisis({ c }: { c: Dict }) {
  const pairs = (c.pairs as Pair[]) ?? [];
  return (
    <>
      <p className="pg-note">
        {c.basis === "market" ? `시장(KODEX 200)이 가장 나빴던 ${String(c.crisis_days)}일` : `전략 평균이 가장 나빴던 ${String(c.crisis_days)}일`}을 위기일로 봤어요
        {c.small_sample ? " — 날이 적어 흔들리는 값이에요." : "."}
      </p>
      <table className="pg-table pg-rob-crisis">
        <thead><tr><th>쌍</th><th>평소 상관</th><th>위기일 상관</th><th>같이 떨어진 날</th></tr></thead>
        <tbody>{pairs.map((p) => (
          <tr key={`${p.a}-${p.b}`}>
            <td className="pg-td-name">{p.a}·{p.b}</td>
            <td className="pg-td-num">{fx(p.normal_rho)}</td>
            <td className="pg-td-num">{fx(p.crisis_rho)}</td>
            <td className="pg-td-num" title={p.reason ? String(p.reason) : undefined}>
              {num(p.co_drops) ? `${p.co_drops}일 · 평소 관계라면 약 ${fx(p.expected_co_drops, 0)}일` : "—"}
            </td>
          </tr>
        ))}</tbody>
      </table>
      <p className="pg-help">
        나쁜 날만 골라 재면 관계가 그대로여도 상관이 높아 보여요. 그래서 둘 다 제 가장 나쁜 10% 날에 함께 든 날을,
        전체 상관이 같은 보통 관계에서 기대되는 날 수와 나란히 봐요.
      </p>
      {c.note ? <p className="pg-help pg-rob-warn">{String(c.note)}{c.market_reason ? ` (${String(c.market_reason)})` : ""}</p> : null}
    </>
  );
}

function Shock({ s }: { s: Dict }) {
  if (!s.available) return <Unknown text="상관 충격을 넣지 못했어요" reason={s.reason} />;
  const rows = (s.scenarios as Dict[]) ?? [];
  const max = Math.max(1e-9, ...rows.flatMap((r) => [r.base_vol_pct, r.stressed_vol_pct].filter(num)));
  return (
    <>
      <p className="pg-note">지금 전략끼리 평균 상관 {fx(s.from_avg_rho)}</p>
      {rows.map((r) => (
        <div key={String(r.kind)} className="pg-rob-shock" data-kind={String(r.kind)}>
          <p className="pg-rob-shock-h">
            <span className={`pg-tag pg-tag--${r.kind === "assumed" ? "assumed" : "confirmed"}`}>{r.kind === "assumed" ? "가정" : "관측"}</span>
            {r.kind === "assumed" ? `상관이 ${fx(r.rho, 1)}로 치솟으면` : `실제로 본 가장 높은 상관 ${fx(r.rho)}이면`}
          </p>
          {r.available ? (
            <table className="pg-table"><tbody>
              <tr><td className="pg-td-name">지금 흔들림(연)</td>
                <td className="pg-td-bar"><span className="pg-bar pg-bar--muted" style={{ width: `${(Number(r.base_vol_pct) / max) * 100}%` }} /></td>
                <td className="pg-td-num">{pct(r.base_vol_pct)}</td></tr>
              <tr><td className="pg-td-name">충격 뒤</td>
                <td className="pg-td-bar"><span className="pg-bar" style={{ width: `${(Number(r.stressed_vol_pct) / max) * 100}%` }} /></td>
                <td className="pg-td-num">{pct(r.stressed_vol_pct)} <small>({signed(r.delta_vol_pct)})</small></td></tr>
              <tr><td className="pg-td-name">하루 VaR 95%</td><td />
                <td className="pg-td-num">{pct(r.base_var_pct, 2)} → {pct(r.stressed_var_pct, 2)}</td></tr>
            </tbody></table>
          ) : <p className="pg-help">{String(r.reason ?? "")}</p>}
        </div>
      ))}
      <p className="pg-help">상관만 바꾸고 각 전략의 흔들림은 그대로 둔 계산이에요 — 실제 위기에는 흔들림도 함께 커져요.</p>
    </>
  );
}

function Drawdown({ d, nDays }: { d: Dict; nDays: number }) {
  const rows = (d.strategies as Dict[]) ?? [];
  const pairs = (d.pairs as Pair[]) ?? [];
  const w = d.worst_window as Dict | null;
  const W = 340, rowH = 22, pad = 6, labelW = 72;
  const H = rows.length * rowH + 20;
  const X = (ago: number) => labelW + (1 - ago / Math.max(1, nDays - 1)) * (W - labelW - pad);
  const hatch = `pg-rob-hatch-${useId().replace(/[^a-zA-Z0-9]/g, "")}`;
  return (
    <>
      <svg className="pg-rob-dd" viewBox={`0 0 ${W} ${H}`} role="img"
           aria-label={`가장 크게 잃은 구간 — ${rows.map((r) => `${String(r.name)} ${num(r.max_drawdown_pct) ? `${r.max_drawdown_pct}%` : "없음"}`).join(" · ")}`}>
        <defs>
          <pattern id={hatch} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="6" className="pg-rob-hatch" />
          </pattern>
        </defs>
        {w && num(w.start_ago) && num(w.end_ago) && (
          <rect fill={`url(#${hatch})`} x={X(w.start_ago)} y={0} width={Math.max(2, X(w.end_ago) - X(w.start_ago))} height={rows.length * rowH}
                className="pg-rob-dd-worst" />
        )}
        {rows.map((r, i) => (
          <g key={String(r.name)}>
            <text x={0} y={i * rowH + 15} className="pg-rob-dd-name">{String(r.name).slice(0, 7)}</text>
            <line x1={labelW} x2={W - pad} y1={i * rowH + 11} y2={i * rowH + 11} className="pg-rob-dd-track" />
            {num(r.start_ago) && num(r.end_ago) && (
              <rect x={X(r.start_ago)} y={i * rowH + 5} width={Math.max(2, X(r.end_ago) - X(r.start_ago))} height={12} rx={3}
                    className="pg-rob-dd-bar" />
            )}
          </g>
        ))}
        <text x={labelW} y={H - 3} className="pg-floors-t">{nDays - 1}거래일 전</text>
        <text x={W - pad} y={H - 3} textAnchor="end" className="pg-floors-t">오늘</text>
      </svg>
      <table className="pg-table"><tbody>
        {rows.map((r) => (
          <tr key={String(r.name)}><td className="pg-td-name">{String(r.name)}</td>
            <td className="pg-td-num">{num(r.max_drawdown_pct) ? `${r.max_drawdown_pct}% · ${String(r.days)}거래일` : String(r.reason ?? "—")}</td></tr>
        ))}
        {pairs.map((p) => (
          <tr key={`${p.a}-${p.b}`}><td className="pg-td-name">{p.a}·{p.b} 겹침</td>
            <td className="pg-td-num">{num(p.overlap) ? `${Math.round(p.overlap * 100)}% (${String(p.overlap_days)}일 / ${String(p.union_days)}일)` : String(p.reason ?? "—")}</td></tr>
        ))}
      </tbody></table>
      {w ? (
        <>
          <p className="pg-note">합친 흐름이 가장 나빴던 {String(w.days)}거래일({String(w.start_ago)}~{String(w.end_ago)}거래일 전 · 빗금): 합침 {pct(w.combined_pct, 2)}</p>
          <table className="pg-table"><tbody>
            {Object.entries((w.returns_pct as Record<string, number>) ?? {}).map(([k, x]) => (
              <tr key={k}><td className="pg-td-name">{k}</td><td className="pg-td-num">{pct(x, 2)}</td></tr>
            ))}
          </tbody></table>
        </>
      ) : <p className="pg-help">{String(d.worst_window_reason ?? "")}</p>}
    </>
  );
}

function More({ rob }: { rob: Dict }) {
  const eff = (rob.effective_n as Dict) ?? {};
  const div = (rob.diversification as Dict) ?? {};
  const st = (rob.stability as Dict) ?? {};
  return (
    <>
      <dl className="pg-kv">
        <div><dt>실질 독립 개수</dt><dd>{num(eff.value) ? `약 ${eff.value.toFixed(1)}개 / ${String(eff.n)}개` : "—"}</dd></div>
        <div><dt>분산 효과</dt><dd>{num(div.ratio) ? `${div.ratio.toFixed(2)}배 (1 = 효과 없음)` : "—"}</dd></div>
      </dl>
      {!num(eff.value) && eff.reason ? <p className="pg-help">{String(eff.reason)}</p> : null}
      {!num(div.ratio) && div.reason ? <p className="pg-help">{String(div.reason)}</p> : null}
      <h5 className="pg-rob-h5">앞 절반 대 뒤 절반 상관</h5>
      <table className="pg-table"><tbody>{((st.pairs as Pair[]) ?? []).map((p) => (
        <tr key={`${p.a}-${p.b}`} data-changed={p.changed === true ? "yes" : p.changed === false ? "no" : "unknown"}>
          <td className="pg-td-name">{p.a}·{p.b}</td>
          <td className="pg-td-num">{fx(p.first)} → {fx(p.second)}</td>
          <td className="pg-td-num">{p.changed === true ? "달라졌어요" : p.changed === false ? "비슷해요" : String(p.reason ?? "—")}</td>
        </tr>
      ))}</tbody></table>
      <p className="pg-help">{String(st.note ?? "")}</p>
    </>
  );
}

export function RobustnessView({ rob }: { rob: Dict | null | undefined }) {
  if (!rob) return null;
  if (!rob.available) return <section className="pg-rob" aria-label="견고성"><h4 className="pg-h4">견고성</h4><Unknown text="견고성을 재지 못했어요" reason={rob.reason} /></section>;
  const roll = rob.rolling as Rolling;
  const nDays = Number(rob.n_days);
  const story = (rob.story as string[]) ?? [];
  const shorts = Number(rob.shorts_dropped ?? 0);
  return (
    <section className="pg-rob" aria-label="견고성">
      <h4 className="pg-h4">견고성 — 같이 무너지나</h4>
      {/* 성과 종류는 응답이 선언한 것 그대로 — 없으면 PerfLabel 이 '모름'을 그린다(지어내지 않는다). */}
      <div className="pg-perf"><PerfLabel value={rob.perf_label as PerfLabelValue | undefined} scope="낙폭·흔들림" /></div>
      <ul className="pg-rob-story">{story.map((s) => <li key={s}>{s}</li>)}</ul>
      <p className="pg-help">
        지금 비중을 지난 {nDays}거래일 그대로 들고 있었다고 보고 쟀어요 — 실제 운용 기록이 아니고, 앞으로도 같다는 뜻도 아니에요.
        {rob.shares_basis === "equal" ? " 몫은 똑같이 나눴다고 봤어요." : ""}
        {shorts > 0 ? ` 숏 비중 ${shorts}개는 빼고 쟀어요.` : ""}
      </p>
      <details className="pg-rob-sec" open>
        <summary>상관 추이 <span>{roll.available ? `${roll.window}거래일 창` : "모름"}</span></summary>
        {roll.available ? <Trend r={roll} /> : <Unknown text="상관 추이를 보지 못했어요" reason={roll.reason} />}
      </details>
      <details className="pg-rob-sec">
        <summary>위기 때 상관</summary>
        <Crisis c={(rob.crisis as Dict) ?? {}} />
      </details>
      <details className="pg-rob-sec">
        <summary>상관 급등 충격</summary>
        <Shock s={(rob.shock as Dict) ?? { available: false, reason: "충격을 넣지 않았어요" }} />
      </details>
      <details className="pg-rob-sec">
        <summary>최악 구간 겹침</summary>
        <Drawdown d={(rob.drawdown as Dict) ?? {}} nDays={nDays} />
      </details>
      <details className="pg-rob-sec">
        <summary>더 보기 <span>실질 개수 · 분산 효과 · 안정성</span></summary>
        <More rob={rob} />
      </details>
    </section>
  );
}
