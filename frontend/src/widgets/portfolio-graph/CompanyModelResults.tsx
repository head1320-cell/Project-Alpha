"use client";
/**
 * 기업 분석 현업 모델의 결과 (BL3 W3b) — EVA·가치 동인 · 가치의 층 · 배수·PEG · 영업 동인 몬테카를로
 * ==========================================================================
 * 수는 서버 view 그대로 그린다(다시 계산하지 않는다). 모든 모델 아래에 같은 모양의 '입력 표' — 관측·근사·가정·미상을 칩으로.
 * 이 웨이브에서 눈에 띄게 그리는 것은 '가치의 층' 하나다: 세로 눈금 위에 자산·수익력·성장까지의 층을 긋고 현재가 선을 겹쳐,
 * 지금 가격이 어느 층에 걸쳐 있는지(= 무엇을 믿고 사는 값인지)를 한눈에.
 */
import type { ReactNode } from "react";

type Dict = Record<string, unknown>;
const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const won = (v: unknown) => (num(v) === null ? "—" : `${Math.round(v as number).toLocaleString("ko-KR")}원`);
const eok = (v: unknown) => (num(v) === null ? "—" : `${Math.round((v as number) / 1e8).toLocaleString("ko-KR")}억`);
const pc = (v: unknown, d = 1) => (num(v) === null ? "—" : `${((v as number) * 100).toFixed(d)}%`);
const k = (v: unknown) => (num(v) === null ? "—" : `${Math.round((v as number) / 1000).toLocaleString("ko-KR")}천`);

function KV({ rows }: { rows: [string, ReactNode][] }) {
  return <dl className="pg-kv">{rows.map(([a, b]) => (<div key={a}><dt>{a}</dt><dd>{b}</dd></div>))}</dl>;
}

function Head({ v }: { v: Dict }) {
  return (
    <p className="pg-co-head">
      <b>{String(v.name ?? v.code)}</b> <span className="pg-muted">{String(v.code ?? "")}</span>
      {num(v.price) !== null && <> · 현재가 {won(v.price)} <span className="pg-muted">({String(v.price_source ?? "출처 미상")})</span></>}
    </p>
  );
}

const BASIS_TONE: Record<string, string> = { 관측: "confirmed", 근사: "assumed", 가정: "assumed", 미상: "unknown" };

/** 입력 표 — 모든 모델이 같은 모양. 값이 수면 비율(0~1 은 %), 목록이면 이어 쓰고, 글이면 그대로. */
function InputsTable({ r }: { r: Dict }) {
  const rows = (r.inputs as Dict[]) ?? [];
  if (!rows.length) return null;
  const show = (x: unknown, unit?: unknown) => (Array.isArray(x) ? x.map(String).join(" · ")
    : num(x) === null ? String(x ?? "—")
      : unit === "원" ? (Math.abs(x as number) >= 1e8 ? eok(x) : won(x))
        : unit === "%" ? `${(x as number).toFixed(2)}%`
          : unit ? `${(x as number).toLocaleString("ko-KR", { maximumFractionDigits: 2 })}${String(unit)}`
            : Math.abs(x as number) < 1.5 ? pc(x, 2) : (x as number).toLocaleString("ko-KR", { maximumFractionDigits: 2 }));
  return (
    <table className="pg-table pg-inputs">
      <caption>이 값은 무엇으로 만들었나</caption>
      <tbody>{rows.map((i) => (
        <tr key={String(i.key)}>
          <td className="pg-td-name">{String(i.label)}</td>
          <td className="pg-td-num">{show(i.value, i.unit)}</td>
          <td><span className={`pg-tag pg-tag--${BASIS_TONE[String(i.basis)] ?? "unknown"}`} title={String(i.source ?? "")}>{String(i.basis)}</span></td>
        </tr>
      ))}</tbody>
    </table>
  );
}

function HistoryNote({ r }: { r: Dict }) {
  return r.history_note ? <p className="pg-warn">{String(r.history_note)}</p> : null;
}

// ── 가치의 층 ───────────────────────────────────────────────────────────────

type Floor = { key: string; label: string; value: number | null; reason?: string | null };

/** 세로 눈금 위의 층들 + 현재가 선. 라벨이 겹치지 않게 최소 간격으로 민다. */
function Floors({ floors, price }: { floors: Floor[]; price: number | null }) {
  const H = 210, top = 12, bottom = 18, barX = 18, barW = 34;
  const vals = [...floors.map((f) => f.value).filter((x): x is number => x !== null), ...(price !== null ? [price] : [])];
  const mx = Math.max(...vals, 1) * 1.08;
  const y = (x: number) => top + (H - top - bottom) * (1 - Math.max(0, x) / mx);
  const marks = [...floors.filter((f) => f.value !== null).map((f) => ({ id: f.key, text: `${f.label} ${won(f.value)}`, at: y(f.value as number), price: false })),
    ...(price !== null ? [{ id: "price", text: `현재가 ${won(price)}`, at: y(price), price: true }] : [])]
    .sort((a, b) => a.at - b.at);
  const placed: number[] = [];
  for (const m of marks) {
    const prev = placed[placed.length - 1];
    placed.push(prev !== undefined && m.at - prev < 15 ? prev + 15 : m.at);
  }
  return (
    <svg className="pg-floors" viewBox={`0 0 320 ${H}`} role="img"
         aria-label={`가치의 층: ${floors.map((f) => `${f.label} ${f.value === null ? "모름" : won(f.value)}`).join(", ")}${price !== null ? ` · 현재가 ${won(price)}` : ""}`}>
      <rect x={barX} y={top} width={barW} height={H - top - bottom} rx={4} className="pg-floors-well" />
      {price !== null && <rect x={barX} y={y(price)} width={barW} height={H - bottom - y(price)} rx={0} className="pg-floors-fill" />}
      {marks.map((m, i) => (
        <g key={m.id}>
          <line x1={barX - 4} x2={barX + barW + 4} y1={m.at} y2={m.at} className={m.price ? "pg-floors-price" : "pg-floors-line"} />
          <path d={`M ${barX + barW + 6} ${m.at} L ${barX + barW + 14} ${placed[i]}`} className="pg-floors-leader" />
          <text x={barX + barW + 18} y={placed[i] + 4} className={m.price ? "pg-floors-t pg-floors-t--price" : "pg-floors-t"}>{m.text}</text>
        </g>
      ))}
      <line x1={barX - 6} x2={barX + barW + 6} y1={H - bottom} y2={H - bottom} className="pg-floors-base" />
      <text x={barX} y={H - 3} className="pg-floors-t pg-floors-zero">0원</text>
    </svg>
  );
}

export function ValueLayersResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const L = Object.fromEntries(((r.layers as Dict[]) ?? []).map((x) => [String(x.key), x]));
  const floors: Floor[] = [
    { key: "asset", label: "자산", value: num(L.asset?.per_share), reason: L.asset?.reason as string },
    { key: "epv", label: "수익력", value: num(L.epv?.per_share), reason: L.epv?.reason as string },
    { key: "full", label: "성장까지", value: num(r.full_per_share) },
  ];
  const w = ((r.inputs as Dict[]) ?? []).find((i) => i.key === "weights")?.value as number[] | undefined;
  return (
    <>
      <Head v={v} />
      <Floors floors={floors} price={num(v.price)} />
      {floors.filter((f) => f.value === null).map((f) => <p key={f.key} className="pg-warn">{f.label}층을 재지 못했어요 — {f.reason ?? "사유 미상"}</p>)}
      <KV rows={[
        ["성장이 더한 몫", num(L.growth?.per_share) === null ? "—" : won(L.growth?.per_share)],
        ["확률로 묶은 값", num(r.weighted_per_share) === null ? `— ${String(r.weighted_reason ?? "")}` : won(r.weighted_per_share)],
        ["가중(자산·수익력·성장까지)", w ? w.map((x) => pc(x, 0)).join(" · ") : "—"],
      ]} />
      {r.franchise ? <p className="pg-note">{String(r.franchise)}</p> : null}
      <HistoryNote r={r} />
      <InputsTable r={r} />
    </>
  );
}

// ── EVA · 가치 동인 ─────────────────────────────────────────────────────────

export function EvaResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const years = ((r.years as Dict[]) ?? []).filter((y) => y.available);
  const mx = Math.max(1, ...years.map((y) => Math.abs(num(y.eva) ?? 0)));
  const vd = (r.value_driver as Dict) ?? {};
  const val = (r.valuation as Dict) ?? {};
  const noCl = years.some((y) => String(y.ic_method ?? "").includes("몰라"));
  return (
    <>
      <Head v={v} />
      <table className="pg-table pg-eva">
        <thead><tr><th>연도</th><th className="pg-td-num">ROIC</th><th className="pg-td-num">EVA</th><th /></tr></thead>
        <tbody>{years.map((y) => {
          const e = num(y.eva) ?? 0;
          return (
            <tr key={String(y.year)}>
              <td>{String(y.year)}</td>
              <td className="pg-td-num">{pc(y.roic)}</td>
              <td className={`pg-td-num${e < 0 ? " pg-neg" : ""}`}>{eok(y.eva)}</td>
              <td className="pg-td-bar"><span className={`pg-bar${e < 0 ? " pg-bar--neg" : ""}`} style={{ width: `${(Math.abs(e) / mx) * 100}%` }} /></td>
            </tr>
          );
        })}</tbody>
      </table>
      <KV rows={[
        ["자본비용(WACC)", pc(((r.latest as Dict) ?? {}).wacc)],
        ["EVA 로 본 주당 가치", num(val.per_share) === null ? `— ${String(val.per_share_reason ?? "")}` : won(val.per_share)],
        ["가치 동인 공식 주당", vd.available ? won(vd.per_share) : `— ${String(vd.reason ?? "")}`],
        ["성장이 가치를", vd.available ? (vd.growth_creates_value ? "만들어요" : "깎아요") : "—"],
      ]} />
      {noCl && <p className="pg-note">유동부채를 몰라 투하자본을 총자산으로 잡은 해가 있어요 — EVA 를 낮게 보는 쪽이에요.</p>}
      <HistoryNote r={r} />
      <InputsTable r={r} />
    </>
  );
}

// ── 배수 · PEG ──────────────────────────────────────────────────────────────

export function MultiplesResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const m = (r.matrix as { growth_axis?: number[]; peg_axis?: number[]; prices?: number[][]; nearest?: number[] | null }) ?? {};
  const j = (r.justified as Dict) ?? {};
  const peer = (r.peer as Dict) ?? {};
  const [ni, nj] = m.nearest ?? [-1, -1];
  const price = num(v.price);
  return (
    <>
      <Head v={v} />
      <KV rows={[["EPS", won(r.eps)], ["PER", num(r.per) === null ? "—" : `${(r.per as number).toFixed(1)}배`],
                 ["PEG", num(r.peg) === null ? `— ${String(r.peg_reason ?? "")}` : (r.peg as number).toFixed(2)]]} />
      <table className="pg-table pg-sens pg-peg">
        <caption>EPS 성장률(행) × PEG(열)이면 맞는 주가</caption>
        <thead><tr><th />{(m.peg_axis ?? []).map((p) => <th key={p} className="pg-td-num">{p.toFixed(2)}</th>)}</tr></thead>
        <tbody>{(m.prices ?? []).map((row, i) => (
          <tr key={i}>
            <th className="pg-td-num">{(m.growth_axis ?? [])[i]}%</th>
            {row.map((c, jx) => (
              <td key={jx} className={`pg-td-num${i === ni && jx === nj ? " pg-strong pg-sens-base" : ""}${price !== null && c < price ? " pg-muted" : ""}`}>{k(c)}</td>
            ))}
          </tr>
        ))}</tbody>
      </table>
      <p className="pg-note">굵은 칸이 현재가에 가장 가까운 조합이고, 흐린 칸은 현재가보다 낮은 가격이에요.</p>
      <table className="pg-table pg-just">
        <caption>정당한 배수</caption>
        <tbody>
          <tr><td className="pg-td-name">ROE 로 본 PBR</td><td className="pg-td-num">{num(j.pbr) === null ? "—" : `${(j.pbr as number).toFixed(2)}배`}</td><td className="pg-td-num">{won(j.pbr_price)}</td></tr>
          <tr><td className="pg-td-name">배당으로 본 PER</td><td className="pg-td-num">{num(j.per) === null ? "—" : `${(j.per as number).toFixed(1)}배`}</td><td className="pg-td-num">{won(j.per_price)}</td></tr>
          <tr><td className="pg-td-name">피어 PER 중앙값</td><td className="pg-td-num">{num(peer.per_median) === null ? "—" : `${(peer.per_median as number).toFixed(1)}배`}</td><td className="pg-td-num">{won(peer.per_price)}</td></tr>
        </tbody>
      </table>
      {j.reason ? <p className="pg-warn">{String(j.reason)}</p> : null}
      {j.pbr_note ? <p className="pg-note">{String(j.pbr_note)}</p> : null}
      <HistoryNote r={r} />
      <InputsTable r={r} />
    </>
  );
}

// ── 영업 동인 몬테카를로 ────────────────────────────────────────────────────

function Histogram({ counts, edges, price, q }: { counts: number[]; edges: number[]; price: number | null; q: Dict }) {
  const W = 320, H = 120, pad = 4;
  const lo = edges[0], hi = edges[edges.length - 1], span = hi - lo || 1;
  const mx = Math.max(1, ...counts);
  const x = (v: number) => pad + ((v - lo) / span) * (W - 2 * pad);
  const bw = (W - 2 * pad) / counts.length;
  return (
    <svg className="pg-hist" viewBox={`0 0 ${W} ${H + 16}`} role="img"
         aria-label={`주당 가치 분포 10% ${won(q.p10)} · 중앙 ${won(q.p50)} · 90% ${won(q.p90)}${price !== null ? ` · 현재가 ${won(price)}` : ""}`}>
      {counts.map((c, i) => (
        <rect key={i} x={pad + i * bw + 0.5} y={H - (c / mx) * H} width={Math.max(1, bw - 1)} height={(c / mx) * H}
              className={num(q.p10) !== null && num(q.p90) !== null && edges[i + 1] > (q.p10 as number) && edges[i] < (q.p90 as number) ? "pg-hist-bar pg-hist-bar--mid" : "pg-hist-bar"} />
      ))}
      {num(q.p50) !== null && <line x1={x(q.p50 as number)} x2={x(q.p50 as number)} y1={0} y2={H} className="pg-hist-med" />}
      {price !== null && price >= lo && price <= hi && <line x1={x(price)} x2={x(price)} y1={0} y2={H} className="pg-hist-price" />}
      <text x={pad} y={H + 13} className="pg-floors-t">{k(lo)}</text>
      <text x={W - pad} y={H + 13} textAnchor="end" className="pg-floors-t">{k(hi)}</text>
    </svg>
  );
}

export function DriverMcResult({ v }: { v: Dict }) {
  const r = (v.result as Dict) ?? {};
  const q = (r.quantiles as Dict) ?? {};
  const h = (r.histogram as { counts?: number[]; edges?: number[] }) ?? {};
  const c = (r.centers as Dict) ?? {};
  const price = num(v.price);
  return (
    <>
      <Head v={v} />
      {(h.counts ?? []).length > 0 && <Histogram counts={h.counts ?? []} edges={h.edges ?? []} price={price} q={q} />}
      <p className="pg-ff-legend">진한 막대 10~90% · 가운데 선 중앙값 · 주황 선 현재가{price !== null && (price < (h.edges ?? [0])[0] || price > (h.edges ?? [0]).slice(-1)[0]) ? " (범위 밖)" : ""}</p>
      <KV rows={[
        ["10% · 중앙 · 90%", `${won(q.p10)} · ${won(q.p50)} · ${won(q.p90)}`],
        ["현재가의 백분위", num(r.price_percentile) === null ? "—" : `${(r.price_percentile as number).toFixed(1)}번째`],
        ["흔들지 않았을 때", won(r.deterministic_per_share)],
        ["중심(성장·마진·재투자)", `${pc(c.growth)} · ${pc(c.margin)} · ${pc(c.reinvest)}`],
        ["경로", `${String(r.n_used ?? "—")} / ${String(r.n_requested ?? "—")}`],
      ]} />
      {num(r.negative_share) !== null && (r.negative_share as number) > 0 && (
        <p className="pg-note">경로의 {pc(r.negative_share, 0)} 는 주당 가치가 0 아래예요 — 부채가 기업가치보다 커요.</p>
      )}
      <p className="pg-note">{String(r.note ?? "").replace(/\*\*/g, "")}</p>
      <HistoryNote r={r} />
      <InputsTable r={r} />
    </>
  );
}
