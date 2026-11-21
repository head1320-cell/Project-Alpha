"use client";
/**
 * 봉과 체결 — 시행 하나의 하루를 시행 설정으로 다시 계산한 봉과 체결 (G4 · 구현 계획 §5)
 * ==========================================================================
 * 문 하나(`GET /intraday/trials/{trial_key}/day`)를 부르고 그대로 그린다 — 화면은 체결 · 손익 · 정합을 셈하지 않는다.
 *   · 날짜는 그 시행의 날 전부(날마다 거래 수) · 종목은 그 시행의 종목 전부. 처음 고른 날 · 종목은 서버가 정한다(첫 거래일 · 그날 첫 체결 종목).
 *   · 정합 줄: 다시 계산한 그날 값이 시행 줄에 남은 그날 값과 같은지(서버 판정 · 문장 그대로). 다르면 그리되 그렇다고 적는다.
 *   · 읽는 줄 · 표 쌍둥이: 봉의 값 · 모양 · 그 봉의 체결(수량 · 가격 · 종류 · 그 봉 거래량 대비 · 매도면 그 왕복의 비용 후 손익).
 * 캔버스 판에서도 쓸 수 있게 feature 에 둔다(이번 조각은 화면의 절 하나에만 놓는다).
 */
import { useEffect, useMemo, useState } from "react";
import { getTrialDay, type TrialDay, type TrialDayFill, type TrialDayResult } from "@/entities/intraday";
import type { TradeRow } from "@/entities/trade-journal";
import { num, pct, signedWon } from "@/shared/lib/krFormat";
import { CandleChart } from "@/shared/ui/chart/CandleChart";
import type { ReadRow } from "@/shared/ui/chart/ChartReadout";
import type { CandleBar, CandleFill } from "@/shared/ui/chart/candleGeo";
import { Notice, RetryFail } from "@/shared/ui/tx";

const CHECK_CHIP = { same: "실행 결과와 같음", different: "실행 결과와 다름", unknown: "견주지 못함" } as const;
const GRADE = { E0: "합성 분봉(E0)", E3: "실데이터(E3)" } as const;

/** 그 왕복의 비용 후 손익 — 서버 줄 그대로. 없으면 0 이 아니라 미상이고, 무엇을 몰랐는지는 줄의 빈 칸(수수료 · 매도세)으로 적는다(사유를 지어내지 않는다). */
function netText(t: TradeRow): string {
  if (t.net !== null) return `이 왕복 비용 후 ${signedWon(t.net)}`;
  const unknown = [t.fees === null ? "수수료" : null, t.taxes === null ? "매도세" : null].filter(Boolean);
  return unknown.length ? `이 왕복 비용 후 손익 미상(${unknown.join(" · ")} 미상)` : "이 왕복 비용 후 손익 미상";
}

function fillText(f: TrialDayFill, volume: number, trades: TradeRow[]): string {
  const side = f.side === "buy" ? "매수" : "매도";
  const share = volume > 0 ? `그 봉 거래량의 ${pct(f.quantity / volume)}` : "그 봉 거래량 없음";
  const parts = [`${side} ${num(f.quantity)}주 ${num(f.price)}원`, f.kind_label ?? f.kind, share];
  if (f.side === "sell") {
    const closed = trades.find((t) => t.closed_at.slice(11, 19) === f.time);
    if (closed) parts.push(netText(closed));
  }
  return parts.join(" · ");
}

function rowsOf(day: TrialDay<TradeRow>, bars: CandleBar[]): ReadRow[] {
  return bars.map((b) => {
    const here = day.fills.filter((f) => f.time === b.time);
    const shape = b.close > b.open ? "양봉" : b.close < b.open ? "음봉" : "보합";
    return {
      head: b.time.slice(0, 5),
      cells: [
        { key: "open", label: "시가", text: num(b.open) }, { key: "high", label: "고가", text: num(b.high) },
        { key: "low", label: "저가", text: num(b.low) }, { key: "close", label: "종가", text: num(b.close) },
        { key: "volume", label: "거래량", text: num(b.volume) }, { key: "shape", label: "모양", text: shape },
        { key: "fills", label: "체결", text: here.length ? here.map((f) => fillText(f, b.volume, day.trades)).join(" / ") : "없음" },
      ],
    };
  });
}

function DayView({ day, onPick, busy }: { day: TrialDay<TradeRow>; onPick: (q: { date?: string; ticker?: string }) => void; busy: boolean }) {
  const bars: CandleBar[] = useMemo(() => (day.bars ? day.bars.time.map((time, i) => ({
    time, open: day.bars!.open[i], high: day.bars!.high[i], low: day.bars!.low[i], close: day.bars!.close[i], volume: day.bars!.volume[i],
  })) : []), [day.bars]);
  const fills: CandleFill[] = useMemo(() => day.fills.map((f) => ({ time: f.time, side: f.side, quantity: f.quantity, price: f.price, label: f.kind_label ?? f.kind })), [day.fills]);
  const rows = useMemo(() => rowsOf(day, bars), [day, bars]);
  const placed = new Set(bars.map((b) => b.time));
  const unplaced = day.fills.filter((f) => !placed.has(f.time));
  const firstMark = bars.findIndex((b) => day.fills.some((f) => f.time === b.time));
  return (
    <div className="itd-day-view" aria-busy={busy}>
      <div className="itd-day-pick">
        <label className="itd-day-label">날짜
          <select className="itd-day-date tj-input" value={day.date ?? ""} onChange={(e) => onPick({ date: e.target.value })}>
            {day.choices.dates.map((d) => (
              <option key={d.date} value={d.date}>{d.trades === null ? `${d.date} · 거래 수 미상` : `${d.date} · 거래 ${num(d.trades)}건`}</option>
            ))}
          </select>
        </label>
        <label className="itd-day-label">종목
          <select className="itd-day-ticker tj-input" value={day.ticker ?? ""} onChange={(e) => onPick({ ticker: e.target.value })}>
            {day.choices.tickers.map((t) => <option key={t} value={t}>{t === day.ticker && day.name ? `${t} ${day.name}` : t}</option>)}
          </select>
        </label>
        {day.origin ? <span className="itd-day-origin">{day.origin.grade ? GRADE[day.origin.grade] : "출처 등급 미상"}</span> : null}
      </div>
      {day.check ? (
        <div className="itd-day-checkrow" data-status={day.check.status}>
          <span className="itd-day-chip">{CHECK_CHIP[day.check.status]}</span>
          <p className="itd-day-check" data-server>{day.check.message}</p>
        </div>
      ) : null}
      {day.empty ? <Notice tone="warn" title="이 하루를 다시 그리지 않았습니다."><span data-server>{day.empty.message}</span></Notice> : null}
      {day.skipped ? (
        <Notice tone="warn" title="이 날 이 종목은 계산에 쓰지 않았습니다."><span className="itd-day-skipped" data-server>{day.skipped.message}</span></Notice>
      ) : null}
      {bars.length ? (
        // 날 · 종목이 바뀌면 그림을 새로 세운다 — 읽는 자리 · 틀의 스크롤이 앞 날의 것으로 남지 않고 그날 첫 체결의 봉에서 다시 선다
        <CandleChart key={`${day.date}|${day.ticker}`} id="trial-day" label={`${day.date} ${day.ticker} 1분봉과 체결`} bars={bars} fills={fills}
                     rows={rows} priceText={(v) => num(v)} initial={firstMark >= 0 ? firstMark : undefined} />
      ) : null}
      <ul className="itd-day-counts">
        <li>이 종목의 체결 {num(day.fills.length)}건 · 같은 날 다른 종목의 체결 {num(day.others.fills)}건</li>
        {unplaced.length ? <li>봉에 없는 시각의 체결 {num(unplaced.length)}건은 그리지 않았습니다.</li> : null}
        {unplaced.map((f, i) => (
          <li key={`${f.time}-${f.side}-${i}`} className="itd-day-unplaced">
            {`${f.time.slice(0, 5)} ${f.side === "buy" ? "매수" : "매도"} ${num(f.quantity)}주 ${num(f.price)}원 · ${f.kind_label ?? f.kind}`}
          </li>
        ))}
      </ul>
      <ul className="itd-day-facts">{day.facts.map((f) => <li key={f} data-server>{f}</li>)}</ul>
    </div>
  );
}

export function TrialDayBlock({ trialKey, missing }: { trialKey: string | null | undefined; missing: string }) {
  const [q, setQ] = useState<{ date: string | null; ticker: string | null }>({ date: null, ticker: null });
  const [tick, setTick] = useState(0);
  const key = `${trialKey ?? ""}|${q.date ?? ""}|${q.ticker ?? ""}|${tick}`;
  const [got, setGot] = useState<{ key: string; r: TrialDayResult<TradeRow> } | null>(null);
  useEffect(() => {
    if (!trialKey) return;
    let live = true;
    getTrialDay<TradeRow>(trialKey, q).then((r) => { if (live) setGot({ key, r }); });
    return () => { live = false; };
  }, [trialKey, q, key]);

  if (!trialKey) return <p className="tj-note itd-day-missing">{missing}</p>;
  const busy = got?.key !== key;
  if (!got) return <p className="tj-note itd-day-loading" role="status">하루 보기를 불러오는 중입니다.</p>;
  if (!got.r.ok) {
    const { status, error } = got.r;
    if (status === 400 || status === 404 || status === 422) return <Notice tone="danger" title="요청 거절"><span data-server>{error}</span></Notice>;
    return <RetryFail title="하루 보기를 불러오지 못했습니다." onRetry={() => setTick((t) => t + 1)}><span data-server>{error}</span></RetryFail>;
  }
  const shown = got.r.value;
  return (
    <div className="itd-day">
      {busy ? <p className="tj-note itd-day-loading" role="status">고른 날을 불러오는 중입니다.</p> : null}
      <DayView day={shown} busy={busy} onPick={(p) => setQ({ date: p.date ?? shown.date, ticker: p.ticker ?? (p.date ? q.ticker : shown.ticker) })} />
    </div>
  );
}
