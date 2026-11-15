"use client";
/**
 * 규칙 가동의 관제 (W5c) — 가동 줄 안에 펴는 판. 가동 하나를 두고 "지금 무슨 일이 일어났나"를 읽는다.
 * ==========================================================================
 * ★읽기만 한다★ — 가동 · 정지 · 비상 정지는 이 판에 없다(가동 줄과 ‘주문이 가는 길’이 한다). 숫자는 전부 서버 값이고 여기서는 고르고 서식만 입힌다.
 *
 *  · 주문 — 주문 기록에서 센 상태별 수. 거절은 주문 경로가 한 말과 함께(서버 문장 그대로). 주문 기록에 없는 신호가 있으면 그 수를 적는다.
 *  · 체결 — 가상(시뮬레이터가 계산) / 증권사 체결. ‘기록 전용’ 가동에는 증권사 체결이 없다.
 *  · 실현손익 — 매매일지 엔진(분봉 백테스트와 같은 계산). 미청산 수량은 평가하지 않는다. 거절된 신호의 가상 체결이 들어 있으면 그렇게 적는다.
 *  · 일 손실 한도 — 그 설정의 한도와 비용 전 실현손익 누계, 남은 폭. 한 번 닿으면 닿은 것이다(뒤의 청산으로 회복돼도).
 *  · 분봉 백테스트와 견주기 — 끝까지 돈 가동을 지금 적재된 봉으로 다시 계산해 견준 ★관측★. 같다 · 다르다 · 미상 · 견주지 않음.
 *  · 하루가 끝난 가동은 그날의 체결을 매매일지 결과와 ★같은 부품★으로 본다.
 *
 * 값이 없으면 0 이 아니라 사유(서버 문장 — `data-server`). 합성 분봉의 가동이면 판 맨 위에 적는다.
 * 도는 가동이면 주기적으로 다시 읽는다(실시간 푸시는 없다). 끝난 가동은 다시 묻지 않는다.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getRunMonitor, type RejectedSignal, type RuleRun, type RunMonitor } from "@/entities/broker-account";
import type { Journal } from "@/entities/trade-journal";
import { Basis, SummaryTable, Trades, amountWon, sign, signedWon } from "@/features/journal-result";
import { num } from "@/shared/lib/krFormat";
import { Notice, RetryFail } from "@/shared/ui/tx";
import { unwrap, useNames, when } from "./parts";

/** 도는 가동의 관제를 다시 읽는 간격. 재생은 사람이 밀지만, 비상 정지 · 실행 모드는 그 사이에도 바뀐다. */
export const MONITOR_POLL_MS = 5_000;

/** 주문 상태 → 건수 옆에 적는 말. 모르는 상태는 원문 그대로(`data-server`). */
const COUNT_KO: Record<string, string> = {
  SHADOW_LOGGED: "기록 전용", REJECTED: "거절", PENDING: "대기", SUBMITTED: "전송 완료", PARTIAL_FILL: "일부 체결", FILLED: "체결",
  CANCELLED: "취소", FAILED: "전송 실패",
};
/** 기록 전용 → 거절 → 그 밖(이름 순) — 화면마다 순서가 흔들리지 않게. */
const ORDER = ["SHADOW_LOGGED", "REJECTED"];
const byStatus = (m: Record<string, number>): [string, number][] =>
  Object.entries(m).sort(([a], [b]) => (ORDER.indexOf(a) + 1 || 99) - (ORDER.indexOf(b) + 1 || 99) || a.localeCompare(b));

const BACKTEST_KO: Record<string, { label: string; tone: "ok" | "practice" | "unknown" | "plain" }> = {
  same: { label: "백테스트와 같음", tone: "ok" },
  differs: { label: "백테스트와 다름", tone: "practice" },
  unknown: { label: "견줌 미상", tone: "unknown" },
  not_compared: { label: "견주지 않음", tone: "plain" },
};
const sideKo = (s: string) => (s === "buy" ? "매수" : s === "sell" ? "매도" : null);

export function RuleMonitor({ accountId, run }: { accountId: string; run: RuleRun }) {
  const q = useQuery({
    queryKey: ["acct", accountId, "rule-run", run.run_id, "monitor"],
    queryFn: unwrap(() => getRunMonitor<Journal>(accountId, run.run_id)),
    staleTime: 0, retry: false, refetchInterval: run.active ? MONITOR_POLL_MS : false,
  });
  if (q.isError) {
    return (
      <div className="ma-mon" data-run={run.run_id}>
        <RetryFail title="관제 조회 실패" onRetry={() => void q.refetch()}><span data-server>{q.error.message}</span></RetryFail>
      </div>
    );
  }
  if (!q.data) return <div className="ma-mon" data-run={run.run_id}><p className="tx-sec-sub" aria-busy="true">관제 조회 중</p></div>;
  const m = q.data.monitor;
  const live = q.data.run.active;
  return (
    <div className="ma-mon" data-run={run.run_id} data-live={String(live)} role="group" aria-label={`가동 ${run.run_id}번 관제`}>
      {q.data.run.grade === "E0" ? (
        <Notice tone="practice" title="합성 분봉으로 가동한 기록입니다.">계산 장치를 확인하는 용도이며 예측력이나 수익의 증거가 아닙니다.</Notice>
      ) : null}
      <p className="ma-mon-live">
        {live ? `가동 중: ${MONITOR_POLL_MS / 1000}초마다 다시 읽습니다.` : "끝난 가동: 다시 읽지 않습니다."}
      </p>
      <dl className="ma-mon-grid">
        <Orders o={m.orders} />
        <div className="ma-mon-cell ma-mon-fills">
          <dt>체결</dt>
          <dd>
            <span className="ma-mon-virtual">가상 {num(m.fills.virtual)}건</span>
            <span className="ma-mon-broker">증권사 체결 {m.fills.broker === null ? "미상" : `${num(m.fills.broker)}건`}</span>
          </dd>
          {m.fills.broker_reason ? <dd className="ma-mon-note" data-server>{m.fills.broker_reason}</dd> : null}
        </div>
        <Pnl p={m.pnl} />
        <Limit l={m.loss_limit} />
        <div className="ma-mon-cell ma-mon-kill" data-active={String(m.kill.active)}>
          <dt>비상 정지</dt>
          <dd>{m.kill.own ? "사용" : m.kill.active ? "주문 차단 중" : "미사용"}</dd>
          {m.kill.active && !m.kill.own ? <dd className="ma-mon-note">이 계좌에서 발동한 정지가 아닙니다. 운영자 정지이거나 상태 조회 실패입니다.</dd> : null}
        </div>
        <div className="ma-mon-cell ma-mon-feed">
          <dt>봉 지연</dt>
          <dd>{m.feed.lag_seconds === null ? "재지 않음" : `${num(m.feed.lag_seconds)}초`}</dd>
          {m.feed.lag_reason ? <dd className="ma-mon-note" data-server>{m.feed.lag_reason}</dd> : null}
        </div>
      </dl>
      {m.orders.rejected.length > 0 ? <Rejected rows={m.orders.rejected} /> : null}
      <Backtest b={m.backtest} />
      {m.journal ? <DayJournal j={m.journal} /> : null}
    </div>
  );
}

function Orders({ o }: { o: RunMonitor["orders"] }) {
  const rows = byStatus(o.by_status);
  return (
    <div className="ma-mon-cell ma-mon-orders" data-basis={o.basis}>
      <dt>주문</dt>
      <dd>
        <span className="ma-mon-signals">신호 {num(o.signals)}건</span>
        {rows.map(([status, n]) => (
          <span key={status} className="ma-mon-status" data-status={status}>
            {COUNT_KO[status] ?? <span data-server>{status}</span>} {num(n)}건
          </span>
        ))}
      </dd>
      {o.unrecorded ? <dd className="ma-mon-warn ma-mon-unrecorded">주문 기록에 없는 신호 {num(o.unrecorded)}건</dd> : null}
      {o.reason ? <dd className="ma-mon-note" data-server>{o.reason}</dd> : null}
    </div>
  );
}

function Pnl({ p }: { p: RunMonitor["pnl"] }) {
  if (!p.available) {
    return <div className="ma-mon-cell ma-mon-pnl" data-available="false"><dt>실현손익</dt><dd>값 없음</dd><dd className="ma-mon-note" data-server>{p.reason}</dd></div>;
  }
  const open = p.open_positions ?? 0;
  return (
    <div className="ma-mon-cell ma-mon-pnl" data-available="true">
      <dt>실현손익</dt>
      <dd>
        <span className="ma-mon-gross">비용 전 <b data-dir={sign(p.gross)}>{signedWon(p.gross)}</b></span>
        <span className="ma-mon-cost">비용 {p.cost === null ? "미상" : amountWon(p.cost)}</span>
        <span className="ma-mon-net">비용 후 {p.net === null ? "미상" : <b data-dir={sign(p.net)}>{signedWon(p.net)}</b>}</span>
      </dd>
      <dd className="ma-mon-sub">청산 {num(p.closed_trades ?? 0)}건 · 미청산 {num(open)}종목{open > 0 ? "(평가하지 않음)" : ""}</dd>
      {p.net_reason ? <dd className="ma-mon-note" data-server>{p.net_reason}</dd> : null}
      {/* 시장 · 상품이 체결 줄에 적힌 가동 때의 값이면 사유가 없다 — 옛 줄일 때만 서버가 말한다. */}
      {p.classification?.reason ? <dd className="ma-mon-note ma-mon-classified" data-server>{p.classification.reason}</dd> : null}
      {p.includes_rejected ? (
        <dd className="ma-mon-warn ma-mon-rejected-in">
          거절된 신호 {num(p.includes_rejected)}건의 가상 체결이 손익에 포함돼 있습니다. 실제 주문이었다면 없는 체결입니다.
        </dd>
      ) : null}
    </div>
  );
}

function Limit({ l }: { l: RunMonitor["loss_limit"] }) {
  if (l.limit === null || l.room === null) {
    return <div className="ma-mon-cell ma-mon-limit" data-known="false"><dt>일 손실 한도</dt><dd>값 없음</dd><dd className="ma-mon-note" data-server>{l.reason}</dd></div>;
  }
  const lost = Math.max(0, -(l.realized_gross ?? 0));
  const used = l.limit > 0 ? Math.min(1, lost / l.limit) : 0;
  return (
    <div className="ma-mon-cell ma-mon-limit" data-known="true" data-touched={String(l.touched)}>
      <dt>일 손실 한도</dt>
      <dd>
        <span className="ma-mon-limit-of">한도 {amountWon(l.limit)}</span>
        <span className="ma-mon-limit-sum">비용 전 누계 {signedWon(l.realized_gross)}</span>
        <span className="ma-mon-room">{l.room > 0 ? `남은 폭 ${amountWon(l.room)}` : l.room === 0 ? "남은 폭 없음" : `한도 초과 ${amountWon(l.room)}`}</span>
      </dd>
      <dd className="ma-mon-bar">
        <span className="ma-mon-meter" role="meter" aria-label="일 손실 한도 사용" aria-valuemin={0} aria-valuemax={l.limit} aria-valuenow={Math.min(l.limit, lost)}>
          <span className="ma-mon-meter-fill" style={{ width: `${used * 100}%` }} />
        </span>
      </dd>
      {l.touched ? <dd className="ma-mon-warn ma-mon-touched">한도에 닿았습니다. 그날은 새로 진입하지 않습니다.</dd> : null}
    </div>
  );
}

function Rejected({ rows }: { rows: RejectedSignal[] }) {
  const names = useNames(rows.map((r) => r.symbol));
  return (
    <div className="ma-mon-rejected">
      <h4 className="ma-mon-h">거절된 신호</h4>
      <ul className="ma-arm-l">
        {rows.map((r) => {
          const name = names.known(r.symbol);
          return (
            <li key={r.seq} className="ma-mon-no">
              <span className="ma-mon-no-what">
                <span className="ma-mon-no-at">{when(r.executed_at) ?? <span data-server>{r.executed_at}</span>}</span>
                <strong>{name ?? r.symbol}</strong>
                {name ? <span className="ma-code" data-mono>{r.symbol}</span> : null}
                <span>{sideKo(r.side) ?? <span data-server>{r.side}</span>} {num(r.quantity)}주</span>
              </span>
              <span className="ma-mon-no-why">
                {r.message ? <span data-server>{r.message}</span> : "사유 문장 없음"}
                {r.reason_code ? <span className="ma-code" data-server>{r.reason_code}</span> : null}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function Backtest({ b }: { b: RunMonitor["backtest"] }) {
  const ko = BACKTEST_KO[b.state];
  return (
    <p className="ma-mon-backtest" data-state={b.state}>
      <span className="tx-chip" data-tone={ko?.tone ?? "unknown"}>{ko?.label ?? <span data-server>{b.state}</span>}</span>
      <span data-server>{b.reason}</span>
      {b.backtest_fills !== null ? <span className="ma-mon-sub">가상 체결 {num(b.run_fills)}줄 · 백테스트 체결 {num(b.backtest_fills)}줄</span> : null}
    </p>
  );
}

/** 하루가 끝난 가동 — 그날의 체결을 매매일지 결과와 같은 부품으로(같은 엔진 · 같은 정의). */
function DayJournal({ j }: { j: Journal }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="ma-mon-journal">
      <button type="button" className="tx-btn tx-btn--sub ma-sm ma-mon-journal-open" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        {open ? "그날의 매매일지 닫기" : "그날의 매매일지 보기"}
      </button>
      {open ? (
        <div className="tj-result ma-mon-journal-body">
          <SummaryTable j={j} level={4} />
          <Trades j={j} level={4} />
          <Basis j={j} level={4} sub="이 결과는 재생한 하루의 가상 체결을 집계한 것입니다. 실제 체결이 아니며 향후 성과를 뜻하지 않습니다." />
        </div>
      ) : null}
    </div>
  );
}
