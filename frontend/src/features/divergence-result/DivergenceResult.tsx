"use client";
/**
 * 괴리 보고 — 올린 체결 ↔ 같은 규칙의 시뮬레이션 체결 (설계 W5 §4)
 * ==========================================================================
 * 답하는 물음은 하나다: **백테스트가 가정한 체결과 실제 체결이 얼마나 다른가.**
 *
 * ★모든 숫자는 서버 값이다★ — 이 파일은 고르고 서식만 입힌다. 문장은 관측만 한다(권고를 만들지 않는다).
 * ★미상은 0 이 아니다★ — 짝이 없으면 차이는 N/A + 사유, 한쪽의 비용을 모르면 비용 후 차이도 N/A + 사유다.
 * 허용 시간은 사용자의 선언(가정)이라, 창을 바꿨을 때의 건수를 늘 함께 보인다.
 * 합성 분봉 위의 시뮬레이션이면 판 맨 위에 적는다. 따로 뺀 줄(기간 밖 · 다른 종목 · 시각 없음 · 읽지 못함)은 세어 적는다.
 */
import type { Divergence, DivergenceAlone, DivergencePair, DivergenceReport, PnlGap, PriceGap, Side } from "@/entities/intraday";
import { UNKNOWN_TEXT, num, signedWon } from "@/shared/lib/krFormat";
import { Answer, Notice, Section, type Chip } from "@/shared/ui/tx";

const SIDE_KO: Record<Side, string> = { buy: "매수", sell: "매도" };
const n0 = (v: number) => v.toLocaleString("ko-KR");
const won0 = (v: number) => `${num(v)}원`;
const qty = (v: number) => v.toLocaleString("ko-KR", { maximumFractionDigits: 4 });
/** 불리함 — 양수가 불리(부호를 그대로 보인다). 틱은 소수 첫째 자리, bp 는 소수 첫째 자리.
 *  ★색을 입히지 않는다★: '+' 가 불리라서 등락 색(오름 빨강 · 내림 파랑)을 입히면 부호와 색이 서로 다른 말을 한다. 색은 손익 칸에만 쓴다. */
const ticks1 = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(1)}틱`;
const bp1 = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(1)}bp`;
const pnlDir = (v: number | null): "up" | "down" | "flat" | undefined => (v === null ? undefined : Math.abs(v) < 1e-9 ? "flat" : v > 0 ? "up" : "down");
const stamp = (iso: string) => (iso.length > 10 ? iso.slice(0, 16).replace("T", " ") : iso);
const has = (g: PriceGap): g is Exclude<PriceGap, { n: 0 }> => g.n > 0;

function sentence(d: DivergenceReport, assumedTicks: number | null): string {
  if (!has(d.price_gap)) return "짝지은 체결 없음";
  const t = d.price_gap.mean.ticks;
  const head = `짝지은 ${n0(d.price_gap.n)}건의 체결가`;
  const base = assumedTicks === null ? "시뮬레이션 체결가" : `가정(슬리피지 ${assumedTicks}틱)`;
  if (Math.abs(t) < 0.05) return `${head}는 ${base}와 평균이 같았습니다.`;
  return `${head}는 ${base}보다 평균 ${Math.abs(t).toFixed(1)}틱 ${t > 0 ? "불리" : "유리"}했습니다.`;
}

export function DivergenceResult({ r }: { r: Divergence }) {
  if (r.empty || !r.divergence || !r.pnl) {
    return (
      <div className="dv-result dv-empty">
        <Notice tone="warn" title="견줄 시뮬레이션이 없습니다."><span data-server>{r.empty?.message ?? UNKNOWN_TEXT}</span></Notice>
      </div>
    );
  }
  const d = r.divergence;
  const slip = typeof r.request.costs.slippage_ticks === "number" ? r.request.costs.slippage_ticks : null;
  const synthetic = r.origin?.grade === "E0";
  const chips: Chip[] = [
    ...(synthetic ? [{ label: "합성 분봉", tone: "practice" } as Chip] : []),
    { label: d.mode === "daily" ? "하루 단위" : `허용 시간 ${d.window_minutes}분 · 가정`, tone: "assumed" } as Chip,
  ];
  return (
    <div className="dv-result" data-mode={d.mode}>
      <p className="tx-sr" role="status">괴리 계산 완료: 짝지은 체결 {n0(d.counts.matched)}건</p>
      {synthetic ? (
        <div className="dv-synthetic">
          <Notice tone="warn" title="합성 분봉 위의 시뮬레이션입니다.">계산 장치를 확인하는 용도이며 실제 시세와 견준 결과가 아닙니다.</Notice>
        </div>
      ) : null}
      {d.degraded ? <div className="dv-degraded"><Notice tone="warn" title="체결 시각이 없는 파일입니다."><span data-server>{d.degraded.message}</span></Notice></div> : null}
      <Answer sentence={sentence(d, slip)} chips={chips}
              figures={[
                { label: "짝지은 체결", value: `${n0(d.counts.matched)}건` },
                { label: "놓친 신호", value: `${n0(d.counts.sim_only)}건` },
                { label: "규칙 밖 매매", value: `${n0(d.counts.actual_only)}건` },
                { label: "비용 전 손익 차이", value: signedWon(r.pnl.gap.gross) },
              ]} />
      <PriceGapTable g={d.price_gap} d={d} />
      {d.mode === "timed" ? <Windows d={d} /> : null}
      <Pnl p={r.pnl} />
      <Lists d={d} />
      <SetAside d={d} r={r} />
    </div>
  );
}

// ── 체결가 차이 ────────────────────────────────────────────────────────

function PriceGapTable({ g, d }: { g: PriceGap; d: DivergenceReport }) {
  return (
    <Section title="체결가 차이" sub="짝지은 체결마다 실제 체결가에서 시뮬레이션 체결가를 뺀 값입니다. 매수는 비싸게, 매도는 싸게 체결된 만큼을 불리함(+)으로 적습니다. 틱과 bp 의 기준은 시뮬레이션 체결가입니다.">
      {!has(g) ? (
        <p className="dv-none"><b>{UNKNOWN_TEXT}</b> <span data-server>{g.message}</span></p>
      ) : (
        <>
          <div className="tj-scroll-x">
            <table className="tj-table dv-gap">
              <thead><tr><th scope="col">불리함</th><th scope="col" className="tj-num">원</th><th scope="col" className="tj-num">틱</th><th scope="col" className="tj-num">bp</th></tr></thead>
              <tbody>
                <tr data-k="mean"><th scope="row">평균</th><td className="tj-num dv-mean-won">{signedWon(g.mean.won)}</td>
                  <td className="tj-num dv-mean-ticks">{ticks1(g.mean.ticks)}</td><td className="tj-num dv-mean-bp">{bp1(g.mean.bp)}</td></tr>
                <tr data-k="median"><th scope="row">중앙값</th><td className="tj-num">{signedWon(g.median.won)}</td>
                  <td className="tj-num">{ticks1(g.median.ticks)}</td><td className="tj-num">{bp1(g.median.bp)}</td></tr>
                <tr data-k="worst"><th scope="row">가장 불리한 체결</th><td className="tj-num dv-worst-won">{signedWon(g.worst.adverse)}</td>
                  <td className="tj-num">{ticks1(g.worst.ticks)}</td><td className="tj-num">{bp1(g.worst.bp)}</td></tr>
              </tbody>
            </table>
          </div>
          <p className="tj-read dv-split">불리 <b className="dv-n-adverse">{n0(g.adverse)}건</b> · 유리 <b className="dv-n-favorable">{n0(g.favorable)}건</b> · 같음 <b className="dv-n-even">{n0(g.even)}건</b>
            {" · "}가장 불리한 체결: <span data-mono>{g.worst.symbol}</span> {stamp(g.worst.sim_at)} {SIDE_KO[g.worst.side]}</p>
          {d.time_gap ? <p className="tj-read dv-time">시각 차이: 평균 {d.time_gap.mean_minutes.toFixed(1)}분 · 중앙값 {d.time_gap.median_minutes.toFixed(1)}분 · 최대 {n0(d.time_gap.max_minutes)}분</p> : null}
          {d.quantity_gap.differs > 0 ? <p className="tj-note dv-qty">수량이 다른 짝 {n0(d.quantity_gap.differs)}건: 시뮬레이션의 수량은 진입 금액과 참여율 상한으로 정한 값입니다.</p> : null}
        </>
      )}
    </Section>
  );
}

// ── 창 ─────────────────────────────────────────────────────────────

function Windows({ d }: { d: DivergenceReport }) {
  return (
    <Section title="허용 시간에 따른 건수" sub="시뮬레이션 체결과 실제 체결의 시각 차이가 허용 시간 안이면 짝으로 봅니다. 허용 시간은 근거가 있는 값이 아니라 선언한 가정이므로 다른 값에서의 건수를 함께 적습니다.">
      <div className="tj-scroll-x">
        <table className="tj-table dv-windows">
          <thead><tr><th scope="col">허용 시간</th><th scope="col" className="tj-num">짝지은 체결</th><th scope="col" className="tj-num">놓친 신호</th><th scope="col" className="tj-num">규칙 밖 매매</th></tr></thead>
          <tbody>
            {d.by_window.map((w) => (
              <tr key={w.minutes} data-minutes={w.minutes} data-chosen={w.chosen ? "" : undefined}>
                <th scope="row">{w.minutes}분{w.chosen ? " · 이번 계산" : ""}</th>
                <td className="tj-num">{n0(w.matched)}건</td><td className="tj-num">{n0(w.sim_only)}건</td><td className="tj-num">{n0(w.actual_only)}건</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="tj-note">분봉 한 칸(1분)보다 가는 시각 차이는 구분하지 못합니다. 짝짓기는 시각의 가까움만 보며 같은 뜻의 주문인지는 판단하지 않습니다.</p>
    </Section>
  );
}

// ── 손익 ────────────────────────────────────────────────────────────

function Pnl({ p }: { p: PnlGap }) {
  const net = (v: number | null) => (v === null ? UNKNOWN_TEXT : signedWon(v));
  return (
    <Section title="실현손익 견주기" sub="두 쪽을 같은 매매일지 계산으로 집계했습니다. 실제 쪽은 규칙의 종목과 기간 안의 체결만 셉니다. 차이는 실제에서 시뮬레이션을 뺀 값이며 원인별로 나누지 않습니다.">
      <div className="tj-scroll-x">
        <table className="tj-table dv-pnl">
          <thead><tr><th scope="col">구분</th><th scope="col" className="tj-num">거래</th><th scope="col" className="tj-num">비용 전</th><th scope="col" className="tj-num">비용 후</th></tr></thead>
          <tbody>
            <tr data-k="simulated"><th scope="row">시뮬레이션</th><td className="tj-num">{n0(p.simulated.trades)}건</td>
              <td className="tj-num dv-sim-gross" data-dir={pnlDir(p.simulated.gross)}>{signedWon(p.simulated.gross)}</td>
              <td className="tj-num dv-sim-net" data-dir={pnlDir(p.simulated.net)}>{net(p.simulated.net)}</td></tr>
            <tr data-k="actual"><th scope="row">실제 체결</th><td className="tj-num">{n0(p.actual.trades)}건</td>
              <td className="tj-num dv-act-gross" data-dir={pnlDir(p.actual.gross)}>{signedWon(p.actual.gross)}</td>
              <td className="tj-num dv-act-net" data-dir={pnlDir(p.actual.net)}>{net(p.actual.net)}</td></tr>
            <tr data-k="gap"><th scope="row">차이</th><td className="tj-num" />
              <td className="tj-num dv-gap-gross" data-dir={pnlDir(p.gap.gross)}>{signedWon(p.gap.gross)}</td>
              <td className="tj-num dv-gap-net" data-dir={pnlDir(p.gap.net)}>{net(p.gap.net)}</td></tr>
          </tbody>
        </table>
      </div>
      {p.net_reason ? <p className="tj-note dv-net-missing"><span data-server>{p.net_message}</span> 수수료율과 시장 구분 가정을 설정에 넣으면 비용 후를 계산합니다.</p> : null}
    </Section>
  );
}

// ── 목록 ────────────────────────────────────────────────────────────

function Lists({ d }: { d: DivergenceReport }) {
  const cut = (shown: number, total: number) => (total > shown ? <p className="tj-note">전체 {n0(total)}건 중 앞 {n0(shown)}건입니다.</p> : null);
  return (
    <Section title="체결 목록" sub="짝지은 체결과 한쪽에만 있는 체결입니다. 나뉘어 체결된 주문은 같은 분 안에서 수량 가중 평균가로 묶었습니다.">
      <details className="dv-list dv-list-matched" open={d.counts.matched > 0 && d.counts.matched <= 20}>
        <summary>짝지은 체결 {n0(d.counts.matched)}건</summary>
        {d.matched.length ? (
          <div className="tj-scroll-x">
            <table className="tj-table dv-pairs">
              <thead><tr><th scope="col">종목</th><th scope="col">방향</th><th scope="col">시뮬레이션</th><th scope="col">실제</th>
                <th scope="col" className="tj-num">시뮬레이션가</th><th scope="col" className="tj-num">실제가</th><th scope="col" className="tj-num">불리함</th><th scope="col" className="tj-num">틱</th><th scope="col" className="tj-num">수량</th></tr></thead>
              <tbody>{d.matched.map((m) => <PairRow key={`${m.symbol}-${m.side}-${m.sim_at}`} m={m} />)}</tbody>
            </table>
          </div>
        ) : null}
        {cut(d.matched.length, d.counts.matched)}
      </details>
      <Alone cls="dv-list-missed" title="놓친 신호" note="시뮬레이션에는 있고 올린 체결에는 짝이 없는 것입니다." rows={d.sim_only} total={d.counts.sim_only} cut={cut} />
      <Alone cls="dv-list-offrule" title="규칙 밖 매매" note="올린 체결에는 있고 시뮬레이션에는 짝이 없는 것입니다(규칙의 종목 안에서)." rows={d.actual_only} total={d.counts.actual_only} cut={cut} />
    </Section>
  );
}

function PairRow({ m }: { m: DivergencePair }) {
  return (
    <tr data-side={m.side}>
      <td data-mono>{m.symbol}</td><td>{SIDE_KO[m.side]}</td><td data-mono>{stamp(m.sim_at)}</td><td data-mono>{stamp(m.actual_at)}{m.parts > 1 ? ` · ${m.parts}줄` : ""}</td>
      <td className="tj-num">{won0(m.sim_price)}</td><td className="tj-num">{won0(m.actual_price)}</td>
      <td className="tj-num">{signedWon(m.adverse)}</td><td className="tj-num">{ticks1(m.ticks)}</td>
      <td className="tj-num">{qty(m.actual_quantity)}{Math.abs(m.quantity_diff) > 1e-9 ? ` (시뮬레이션 ${qty(m.sim_quantity)})` : ""}</td>
    </tr>
  );
}

function Alone({ cls, title, note, rows, total, cut }: {
  cls: string; title: string; note: string; rows: DivergenceAlone[]; total: number; cut: (shown: number, total: number) => React.ReactNode;
}) {
  return (
    <details className={`dv-list ${cls}`} open={total > 0 && total <= 20}>
      <summary>{title} {n0(total)}건</summary>
      <p className="tj-note">{note}</p>
      {rows.length ? (
        <div className="tj-scroll-x">
          <table className="tj-table dv-alone">
            <thead><tr><th scope="col">종목</th><th scope="col">방향</th><th scope="col">시각</th><th scope="col" className="tj-num">체결가</th><th scope="col" className="tj-num">수량</th></tr></thead>
            <tbody>
              {rows.map((x) => (
                <tr key={`${x.symbol}-${x.side}-${x.at}`} data-side={x.side}>
                  <td data-mono>{x.symbol}</td><td>{SIDE_KO[x.side]}</td><td data-mono>{stamp(x.at)}</td><td className="tj-num">{won0(x.price)}</td><td className="tj-num">{qty(x.quantity)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {cut(rows.length, total)}
    </details>
  );
}

// ── 따로 뺀 것 · 시행 ────────────────────────────────────────────────────

function SetAside({ d, r }: { d: DivergenceReport; r: Divergence }) {
  const a = d.set_aside;
  const parts = [`올린 줄 ${n0(d.inputs.actual_rows)}줄`, `견준 체결 ${n0(d.inputs.actual_fills)}건`, `시뮬레이션 체결 ${n0(d.inputs.sim_fills)}건`];
  const t = r.trial;
  return (
    <Section title="견주지 않은 줄과 기록" sub="계산에서 뺀 줄과 그 사유입니다. 조용히 버리지 않습니다.">
      <div className="dv-aside">
        <p className="tj-read">{parts.join(" · ")}</p>
        <ul className="tj-plain-list dv-aside-list">
          <li className="dv-aside-outside">기간 밖 <b>{n0(a.outside_period)}줄</b></li>
          <li className="dv-aside-other">규칙에 없는 종목 <b>{n0(a.other_symbols.rows)}줄</b>{a.other_symbols.symbols.length ? <> (<span data-mono>{a.other_symbols.symbols.slice(0, 8).join(", ")}</span>{a.other_symbols.symbols.length > 8 ? ` 외 ${n0(a.other_symbols.symbols.length - 8)}종목` : ""})</> : null}</li>
          {d.mode === "timed" ? <li className="dv-aside-untimed">체결 시각이 없는 줄 <b>{n0(a.untimed)}줄</b>{a.untimed > 0 ? " (손익에는 포함)" : ""}</li> : null}
          <li className="dv-aside-rejected">읽지 못한 줄 <b>{n0(d.rejected_total)}줄</b></li>
        </ul>
        {a.rejected.length ? (
          <ul className="tj-plain-list tj-rejects">
            {a.rejected.slice(0, 20).map((x) => <li key={x.row}><b>{x.row + 1}번째 체결 줄</b> <span data-server>{x.message}</span></li>)}
          </ul>
        ) : null}
        <p className="tj-note dv-trial" data-recorded={t?.recorded ? "" : undefined}>
          {t?.recorded
            ? `시뮬레이션은 시행으로 기록했습니다(이 설정 ${n0(t.runs ?? 0)}회째 실행${t.new ? " · 새 시행" : ""}). 올린 체결은 서버에 저장하지 않습니다.`
            : <>시행을 기록하지 못했습니다. <span data-server>{t?.message ?? ""}</span> 올린 체결은 서버에 저장하지 않습니다.</>}
        </p>
      </div>
    </Section>
  );
}
