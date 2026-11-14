"use client";
/**
 * 매매일지 결과의 부품 — 비용 전·후 요약 · 비용 · 구간별 집계 · 손실 직후 · 큰 손실과 이익 · 거래 목록 · 값의 근거
 * ==========================================================================
 * 매매일지(`/trade-journal` — 올린 체결 내역)와 분봉 백테스트(`/intraday` — 모의 체결)가 ★같은 부품·같은 순서★로 결과를 그린다.
 * 두 화면의 숫자는 서버의 같은 엔진(`src/engine/trade_journal`)에서 나오므로 그리는 쪽도 하나여야 정의가 갈라지지 않는다.
 * 위젯이 위젯을 가져다 쓰지 않으므로(FSD) 여기 `features` 에 둔다. 클래스 이름(`tj-*`)은 E2E 계약이라 그대로다.
 *
 * ★모든 숫자는 서버 값이다★ — 고르고 서식만 입힌다(다시 계산하지 않는다 · 막대의 길이만 화면이 잰다).
 * ★미상은 N/A + 사유★ — 비용을 모르는 거래의 '비용 후'는 0 이 아니라 N/A 이고, 왜 모르는지 서버 사유를 옆에 적는다.
 */
import { useState, type ReactNode } from "react";
import type { BucketRow, CostBasis, Journal, PnlBasis, Summary, SymbolRow, TradeRow } from "@/entities/trade-journal";
import { UNKNOWN_TEXT, pct, pp } from "@/shared/lib/krFormat";
import { Notice, Section, Tabs, type Chip } from "@/shared/ui/tx";
import { BASIS_KO, INSTRUMENT_KO, MARKET_KO, amountWon, bpAsPct, holdText, qty, ratio2, sign, signedWon, whenText } from "./format";

export const PNL_KO: Record<PnlBasis, string> = { net: "비용 후", gross: "비용 전" };

// ── 근거 칩 ─────────────────────────────────────────────────────────────────

/** 손익 기준과 비용의 근거를 칩으로 — 관측 · 추론 · 가정 · 미상. */
export function costChips(j: Journal): Chip[] {
  const { fee, tax, commission_bp: bp } = j.basis;
  const out: Chip[] = [{ label: `${PNL_KO[j.basis.pnl_basis]} 기준`, tone: "plain" }];
  if (fee.unknown > 0) out.push({ label: "수수료 미상", tone: "unknown" });
  else if (fee.assumed > 0) out.push({ label: `수수료 가정 ${bpAsPct(bp)}`, tone: "assumed" });
  else if (fee.observed > 0) out.push({ label: "수수료 관측", tone: "plain" });
  if (tax.unknown > 0) out.push({ label: "매도세 미상", tone: "unknown" });
  else if (tax.assumed > 0) out.push({ label: "매도세 가정", tone: "assumed" });
  else if (tax.inferred > 0) out.push({ label: "매도세 추론", tone: "info" });
  else if (tax.observed > 0) out.push({ label: "매도세 관측", tone: "plain" });
  return out;
}

// ── 비용 전 | 비용 후 ───────────────────────────────────────────────────────

const ROWS: { k: string; label: string; fmt: (s: Summary) => string; tone?: (s: Summary) => "up" | "down" | "flat" }[] = [
  { k: "n", label: "거래 수", fmt: (s) => `${s.n.toLocaleString("ko-KR")}건` },
  { k: "win_rate", label: "승률", fmt: (s) => pct(s.win_rate) },
  { k: "avg_win", label: "평균 이익", fmt: (s) => signedWon(s.avg_win) },
  { k: "avg_loss", label: "평균 손실", fmt: (s) => signedWon(s.avg_loss === null ? null : -s.avg_loss) },
  { k: "payoff", label: "손익비", fmt: (s) => ratio2(s.payoff) },
  { k: "expectancy", label: "거래당 기대값", fmt: (s) => signedWon(s.expectancy), tone: (s) => sign(s.expectancy) },
  { k: "profit_factor", label: "Profit Factor(총이익÷총손실)", fmt: (s) => ratio2(s.profit_factor) },
  { k: "breakeven", label: "손익분기 승률", fmt: (s) => pct(s.breakeven_win_rate) },
  { k: "edge", label: "승률과 손익분기의 차", fmt: (s) => pp(s.edge_over_breakeven), tone: (s) => sign(s.edge_over_breakeven) },
  { k: "total", label: "실현손익 합계", fmt: (s) => signedWon(s.total), tone: (s) => sign(s.total) },
  { k: "streak", label: "최대 연속 손실", fmt: (s) => (s.max_losing_streak.count ? `${s.max_losing_streak.count}회 · ${signedWon(s.max_losing_streak.amount)}` : "없음") },
];

export function SummaryTable({ j }: { j: Journal }) {
  const { gross, net, net_excluded: excluded } = j.summary;
  const feeUnknown = j.basis.fee.unknown;
  return (
    <Section title="비용 전과 비용 후" sub="같은 거래를 비용(수수료·매도세) 차감 전과 후로 집계했습니다. 본전 거래는 승도 패도 아니며 승률의 분모에 포함합니다.">
      <div className="tj-scroll-x">
      <table className="tj-table tj-sum">
        <thead><tr><th scope="col">지표</th><th scope="col" className="tj-num">비용 전</th><th scope="col" className="tj-num">비용 후</th></tr></thead>
        <tbody>
          {ROWS.map((r) => (
            <tr key={r.k} data-k={r.k}>
              <th scope="row">{r.label}</th>
              <td className="tj-num tj-sum-gross" data-dir={r.tone?.(gross)}>{r.fmt(gross)}</td>
              <td className="tj-num tj-sum-net" data-dir={net ? r.tone?.(net) : undefined}>{net ? r.fmt(net) : UNKNOWN_TEXT}</td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
      {excluded > 0 ? (
        <div className="tj-net-missing">
          <Notice tone="warn" title={net ? `비용 미상 거래 ${excluded.toLocaleString("ko-KR")}건은 비용 후 집계에서 제외했습니다.` : `비용 미상 거래 ${excluded.toLocaleString("ko-KR")}건: 비용 후 통계를 산출하지 않았습니다.`}>
            <ul className="tj-reasons">
              {feeUnknown > 0 ? <li>수수료 미상 체결 {feeUnknown.toLocaleString("ko-KR")}건: 파일에 수수료 값이 없고 수수료율도 입력하지 않았습니다.</li> : null}
              {j.basis.tax_unknown.map((u) => <li key={u.reason}>매도세 미상 체결 {u.count.toLocaleString("ko-KR")}건: <span data-server>{u.message}</span></li>)}
            </ul>
            곡선과 구간별 집계는 섞지 않고 {PNL_KO[j.basis.pnl_basis]} 기준으로 통일했습니다.
          </Notice>
        </div>
      ) : null}
      {gross.small_sample ? <p className="tj-note tj-small-sample">거래 30건 미만: 표본이 작아 한두 거래가 통계를 크게 바꿉니다.</p> : null}
    </Section>
  );
}

// ── 비용 ────────────────────────────────────────────────────────────────────

const tags = (counts: Partial<Record<CostBasis, number>>, order: CostBasis[]) =>
  order.filter((b) => (counts[b] ?? 0) > 0).map((b) => <span key={b} className="tj-basis-tag" data-basis={b}>{BASIS_KO[b]}</span>);

export function Costs({ j }: { j: Journal }) {
  const c = j.summary.costs;
  const gross = j.summary.gross.total;
  const net = c.total === null ? null : gross - c.total;
  const feeTags = tags(j.basis.fee, ["observed", "assumed", "unknown"]);
  const taxTags = tags(j.basis.tax, ["observed", "inferred", "assumed", "unknown"]);
  const read = c.total === null ? "비용 미상 체결이 있어 비용 합계와 비중을 산출하지 않았습니다."
    : c.share_of_gross !== null ? `비용은 비용 전 실현손익 ${signedWon(gross)}의 ${pct(c.share_of_gross)}입니다. 거래 대금 대비 ${c.bp_of_turnover === null ? UNKNOWN_TEXT : `${c.bp_of_turnover.toFixed(1)}bp`}, 거래당 ${amountWon(c.per_trade)}입니다.`
    : `비용 전 실현손익이 0 이하(${signedWon(gross)})여서 비용 비중은 산출하지 않았습니다. 거래 대금 대비 ${c.bp_of_turnover === null ? UNKNOWN_TEXT : `${c.bp_of_turnover.toFixed(1)}bp`}, 거래당 ${amountWon(c.per_trade)}입니다.`;
  return (
    <Section title="비용" sub="청산된 거래에 붙은 수수료와 매도세입니다. 유관기관 제비용과 양도소득세는 포함하지 않습니다.">
      <div className="tj-costs">
        <dl className="tj-cost-figs">
          <div data-k="fees"><dt>수수료 {feeTags}</dt><dd>{amountWon(c.fees)}</dd></div>
          <div data-k="taxes"><dt>매도세 {taxTags}</dt><dd>{amountWon(c.taxes)}</dd></div>
          <div data-k="total"><dt>비용 합계</dt><dd>{amountWon(c.total)}</dd></div>
          <div data-k="turnover"><dt>거래 대금(매수+매도)</dt><dd>{amountWon(c.turnover)}</dd></div>
        </dl>
        {c.total !== null && c.fees !== null && c.taxes !== null && net !== null ? <Waterfall gross={gross} fees={c.fees} taxes={c.taxes} net={net} /> : null}
        <p className="tj-read tj-costs-read">{read}</p>
      </div>
    </Section>
  );
}

/** 비용 전 손익 → 수수료 → 매도세 → 비용 후 손익. 막대는 같은 원 눈금 위에 놓인다(0 선 하나). 길이만 화면이 잰다. */
function Waterfall({ gross, fees, taxes, net }: { gross: number; fees: number; taxes: number; net: number }) {
  const mid = gross - fees;
  const lo = Math.min(0, gross, mid, net), hi = Math.max(0, gross, mid, net);
  const span = hi - lo || 1;
  const at = (v: number) => ((v - lo) / span) * 100;
  const bar = (a: number, b: number) => ({ left: `${at(Math.min(a, b))}%`, width: `${Math.max(0.6, Math.abs(at(a) - at(b)))}%` });
  const rows: { k: string; label: string; from: number; to: number; text: string; kind: "up" | "down" | "flat" | "cost" }[] = [
    { k: "gross", label: "비용 전 실현손익", from: 0, to: gross, text: signedWon(gross), kind: sign(gross) },
    { k: "fees", label: "수수료", from: gross, to: mid, text: signedWon(-fees), kind: "cost" },
    { k: "taxes", label: "매도세", from: mid, to: net, text: signedWon(-taxes), kind: "cost" },
    { k: "net", label: "비용 후 실현손익", from: 0, to: net, text: signedWon(net), kind: sign(net) },
  ];
  return (
    <ul className="tj-wf" aria-label="비용 전 실현손익에서 비용 후 실현손익까지">
      {rows.map((r) => (
        <li key={r.k} className="tj-wf-row" data-step={r.k}>
          <span className="tj-wf-lab">{r.label}</span>
          <span className="tj-wf-track" aria-hidden="true">
            <i className="tj-wf-zero" style={{ left: `${at(0)}%` }} />
            <i className={`tj-wf-bar tj-wf-bar--${r.kind}`} style={bar(r.from, r.to)} />
          </span>
          <span className="tj-wf-val" data-dir={r.kind === "cost" ? undefined : r.kind}>{r.text}</span>
        </li>
      ))}
    </ul>
  );
}

// ── 구간별 집계 ─────────────────────────────────────────────────────────────

type BucketTab = "holding" | "hour" | "weekday" | "daily" | "symbol";
const TABS: { value: BucketTab; label: string }[] = [
  { value: "holding", label: "보유 시간" }, { value: "hour", label: "진입 시간대" }, { value: "weekday", label: "요일" },
  { value: "daily", label: "일별" }, { value: "symbol", label: "종목" },
];
const TAB_NOTE: Record<BucketTab, string> = {
  holding: "첫 매수부터 청산까지의 시간입니다. 날짜가 바뀐 거래는 ‘하루 넘김’으로 따로 셉니다.",
  hour: "첫 매수 체결 시각의 시(時) 기준입니다.",
  weekday: "첫 매수 체결일의 요일 기준입니다.",
  daily: "청산일 기준입니다(그날 실현한 손익).",
  symbol: "손익 합계가 큰 순서입니다.",
};

function BucketList({ rows, name }: { rows: (BucketRow | SymbolRow)[]; name: (r: BucketRow | SymbolRow) => ReactNode }) {
  const max = Math.max(1e-9, ...rows.map((r) => Math.abs(r.total)));
  return (
    <ul className="tj-bucket-list">
      <li className="tj-bucket-head" aria-hidden="true"><span>구간</span><span className="tj-num">거래</span><span className="tj-num">승률</span><span /><span className="tj-num">손익 합계</span><span className="tj-num">거래당</span></li>
      {rows.map((r) => {
        const w = Math.min(50, (Math.abs(r.total) / max) * 50);
        const dir = sign(r.total);
        return (
          <li key={String(r.key)} className="tj-bucket-row" data-key={String(r.key)}>
            <span className="tj-bucket-lab">{name(r)}</span>
            <span className="tj-num">{r.n.toLocaleString("ko-KR")}건</span>
            <span className="tj-num">{r.n ? pct(r.win_rate) : UNKNOWN_TEXT}</span>
            <span className="tj-bucket-track" aria-hidden="true">
              {r.n && dir !== "flat" ? <i className={`tj-bucket-bar tj-bucket-bar--${dir}`} style={dir === "up" ? { left: "50%", width: `${w}%` } : { right: "50%", width: `${w}%` }} /> : null}
            </span>
            <span className="tj-num tj-bucket-val" data-dir={r.n ? dir : undefined}>{r.n ? signedWon(r.total) : UNKNOWN_TEXT}</span>
            <span className="tj-num tj-bucket-exp">{r.n ? signedWon(r.expectancy) : UNKNOWN_TEXT}</span>
          </li>
        );
      })}
    </ul>
  );
}

export function Buckets({ j }: { j: Journal }) {
  const [tab, setTab] = useState<BucketTab>("holding");
  const b = j.breakdowns;
  const rows = b[tab];
  const timeless = (tab === "holding" || tab === "hour") && b.without_time > 0;
  const name = (r: BucketRow | SymbolRow): ReactNode => {
    if (tab !== "symbol") return r.label;
    const s = r as SymbolRow;
    return s.name ? <>{s.name} <span className="tj-code" data-mono>{s.label}</span></> : <span data-mono>{s.label}</span>;
  };
  return (
    <Section title="구간별 집계" sub={`${PNL_KO[b.basis]} 실현손익 기준입니다. 막대는 구간의 손익 합계이고, 가운데 선이 0 입니다.`}>
      <div className="tj-buckets">
        <Tabs label="집계 기준" tabs={TABS} value={tab} onChange={setTab}>
          <p className="tj-note">{TAB_NOTE[tab]}</p>
          {rows.length ? <BucketList rows={rows} name={name} /> : <p className="tj-note">이 기준으로 집계할 거래가 없습니다.</p>}
          {timeless ? <p className="tj-note tj-timeless">체결 시각이 없는(날짜만 있는) 거래 {b.without_time.toLocaleString("ko-KR")}건은 이 집계에서 제외했습니다.</p> : null}
        </Tabs>
      </div>
    </Section>
  );
}

export function AfterLoss({ j }: { j: Journal }) {
  const a = j.breakdowns.after_loss;
  if (a.after.n + a.other.n === 0) return null;
  const row = (k: "after" | "other", label: string, r: BucketRow) => (
    <tr data-k={k}>
      <th scope="row">{label}</th>
      <td className="tj-num">{r.n.toLocaleString("ko-KR")}건</td>
      <td className="tj-num">{r.n ? pct(r.win_rate) : UNKNOWN_TEXT}</td>
      <td className="tj-num" data-dir={r.n ? sign(r.expectancy) : undefined}>{r.n ? signedWon(r.expectancy) : UNKNOWN_TEXT}</td>
      <td className="tj-num" data-dir={r.n ? sign(r.total) : undefined}>{r.n ? signedWon(r.total) : UNKNOWN_TEXT}</td>
    </tr>
  );
  return (
    <Section title="손실 직후의 진입" sub={`손실로 끝난 거래의 청산 뒤 ${a.within_minutes}분 안에 시작한 거래와 그 밖의 거래를 나눠 집계했습니다. 두 묶음의 차이는 관측값이며 원인을 뜻하지 않습니다.`}>
      <div className="tj-scroll-x">
      <table className="tj-table tj-after-loss">
        <thead><tr><th scope="col">묶음</th><th scope="col" className="tj-num">거래</th><th scope="col" className="tj-num">승률</th><th scope="col" className="tj-num">거래당</th><th scope="col" className="tj-num">손익 합계</th></tr></thead>
        <tbody>
          {row("after", `손실 청산 뒤 ${a.within_minutes}분 안에 진입`, a.after)}
          {row("other", "그 밖의 진입", a.other)}
        </tbody>
      </table>
      </div>
    </Section>
  );
}

// ── 거래 ────────────────────────────────────────────────────────────────────

const tradeName = (t: TradeRow) => (t.name ? <>{t.name} <span className="tj-code" data-mono>{t.symbol}</span></> : <span data-mono>{t.symbol}</span>);

export function Extremes({ j }: { j: Journal }) {
  const e = j.extremes;
  const list = (cls: string, title: string, rows: TradeRow[], none: string) => (
    <div className={cls}>
      <h3 className="tj-h3">{title}</h3>
      {rows.length ? (
        <ol className="tj-ext-list">
          {rows.map((t, i) => (
            <li key={`${t.symbol}-${t.closed_at}-${i}`}>
              <span className="tj-ext-name">{tradeName(t)}</span>
              <span className="tj-ext-when">{whenText(t.closed_at, t.has_time)} · 보유 {holdText(t.holding_seconds)}</span>
              <span className="tj-num tj-ext-val" data-dir={sign(t[e.basis])}>{signedWon(t[e.basis])}</span>
            </li>
          ))}
        </ol>
      ) : <p className="tj-note">{none}</p>}
    </div>
  );
  return (
    <Section title="가장 큰 손실과 이익" sub={`${PNL_KO[e.basis]} 실현손익 기준, 각 ${e.limit}건까지입니다.`}>
      <div className="tj-extremes">
        {list("tj-worst", "손실이 큰 거래", e.worst, "손실 거래 없음")}
        {list("tj-best", "이익이 큰 거래", e.best, "이익 거래 없음")}
      </div>
    </Section>
  );
}

export function Trades({ j }: { j: Journal }) {
  const more = j.trades_total > j.trades.length;
  return (
    <Section title="거래 목록" sub={more ? `청산 순서입니다. 전체 ${j.trades_total.toLocaleString("ko-KR")}건 중 앞 ${j.trades.length.toLocaleString("ko-KR")}건을 표시합니다(요약과 곡선은 전체 기준).` : "청산 순서입니다. 한 거래는 보유 수량이 0 에서 시작해 다시 0 이 될 때까지입니다."}>
      <div className="tj-scroll">
        <table className="tj-table tj-trades">
          <thead>
            <tr>
              <th scope="col">청산</th><th scope="col">종목</th><th scope="col" className="tj-num">수량</th><th scope="col" className="tj-num">매수 평균</th>
              <th scope="col" className="tj-num">매도 평균</th><th scope="col" className="tj-num">보유</th><th scope="col" className="tj-num">비용 전</th>
              <th scope="col" className="tj-num">비용</th><th scope="col" className="tj-num">비용 후</th>
            </tr>
          </thead>
          <tbody>
            {j.trades.map((t, i) => (
              <tr key={`${t.symbol}-${t.closed_at}-${i}`}>
                <td className="tj-when">{whenText(t.closed_at, t.has_time)}</td>
                <td>{tradeName(t)}</td>
                <td className="tj-num">{qty(t.quantity)}</td>
                <td className="tj-num">{amountWon(t.avg_buy)}</td>
                <td className="tj-num">{amountWon(t.avg_sell)}</td>
                <td className="tj-num">{holdText(t.holding_seconds)}</td>
                <td className="tj-num" data-dir={sign(t.gross)}>{signedWon(t.gross)}</td>
                <td className="tj-num">{amountWon(t.cost)}</td>
                <td className="tj-num" data-dir={sign(t.net)}>{signedWon(t.net)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Section>
  );
}

// ── 값의 근거 ───────────────────────────────────────────────────────────────

export function Basis({ j, sub = "이 결과는 올린 파일 안의 체결을 집계한 관측값입니다. 향후 성과를 뜻하지 않습니다." }: { j: Journal; sub?: string }) {
  const { fee, tax, tax_rates: rates } = j.basis;
  const n = (v: number) => v.toLocaleString("ko-KR");
  return (
    <Section title="값의 근거와 범위" sub={sub}>
      <div className="tj-basis">
        <dl className="tj-basis-list">
          <div><dt>수수료</dt><dd>관측(파일의 값) {n(fee.observed)}건 · 가정(입력한 수수료율{j.basis.commission_bp === null ? "" : ` ${bpAsPct(j.basis.commission_bp)}`}) {n(fee.assumed)}건 · 미상 {n(fee.unknown)}건</dd></div>
          <div><dt>매도세</dt><dd>관측(파일의 값) {n(tax.observed)}건 · 추론(세율표) {n(tax.inferred)}건 · 가정(지정한 시장) {n(tax.assumed)}건 · 미상 {n(tax.unknown)}건 · 매수(해당 없음) {n(tax.not_applicable)}건</dd></div>
        </dl>
        {rates.length ? (
          <>
            <h3 className="tj-h3">적용한 매도세율</h3>
            <p className="tj-note">증권거래세와 농어촌특별세의 합입니다. 세율표의 근거는 보도·안내 자료 요약(등급 T1)이며 법령 원문과 대조하지 않았습니다. 실제 정산과 다를 수 있습니다.</p>
            <div className="tj-scroll">
              <table className="tj-table tj-rates">
                <thead><tr><th scope="col">시장</th><th scope="col">상품</th><th scope="col" className="tj-num">세율</th><th scope="col">적용 구간</th><th scope="col">근거</th><th scope="col" className="tj-num">체결</th><th scope="col">출처</th></tr></thead>
                <tbody>
                  {rates.map((r) => (
                    <tr key={`${r.market}-${r.instrument}-${r.period.from}-${r.basis}`}>
                      <td>{MARKET_KO[r.market] ?? r.market}</td>
                      <td>{INSTRUMENT_KO[r.instrument] ?? r.instrument}</td>
                      <td className="tj-num">{r.bp}bp</td>
                      <td>{r.period.from} ~ {r.period.to ?? "현재"}</td>
                      <td>{BASIS_KO[r.basis]} · {r.grade}</td>
                      <td className="tj-num">{n(r.fills)}건</td>
                      <td><span className="tj-src">{r.sources.map((s, i) => <a key={s.url} href={s.url} target="_blank" rel="noreferrer" data-server>{`출처 ${i + 1}`}</a>)}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : null}
        <h3 className="tj-h3">이 도구가 다루지 않는 것</h3>
        <ul className="tj-not-covered tj-plain-list">{j.not_covered.map((s) => <li key={s} data-server>{s}</li>)}</ul>
      </div>
    </Section>
  );
}
