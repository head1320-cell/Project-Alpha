"use client";
/**
 * 실거래 [안전] 탭 (ST3b) — 운영 계좌를 멈추고 여는 장치가 지금 어떤 상태이고, 지난번에 무엇을 했는지.
 * ==========================================================================
 * 실계좌 관문(관리자) · 비상 정지 이력 · 자동 비상 정지 준비 상태(+ KIS 응답 코드 표) · 일 손익 · 최근 감사 기록.
 * ★이 탭을 열 때만 읽는다★ — 지금 탭의 요청·폴링(BU9a 골든)은 그대로다. 읽기는 모두 로그인 GET 이고 절마다 따로 실패한다.
 * 서버 문장(사유·요약)은 `data-server` 로 그대로 싣는다. 미상 ≠ 0.
 */
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import type { GateState } from "@/entities/trading/liveGate";
import {
  readAudit, readAuditSummary, readDailyPnl, readKillEvents, readKisCodes, readReadiness,
  type KillEvent, type PnlRow,
} from "@/entities/trading/safety";
import type { Result } from "@/shared/api/result";
import { krDateTime, num, priceWon } from "@/shared/lib/krFormat";
import { RetryFail } from "@/shared/ui/tx";
import { GateSection } from "./GateSection";

/** Result → 던지는 queryFn(react-query 가 isError 로 들고 다니게). */
const q = <T,>(f: () => Promise<Result<T>>) => async () => {
  const r = await f();
  if (!r.ok) throw new Error(r.error);
  return r.value;
};
const opts = { staleTime: 0, retry: false, refetchOnWindowFocus: false } as const;

export const SOURCE_KO: Record<string, string> = {
  manual: "관리자가 손으로", manual_admin: "관리자가 손으로",
  auto_dd: "누적 손실 자동 정지", auto_cb: "하루 손실 자동 정지", auto_risk: "시장 위험 자동 정지", auto_api: "증권사 연결 실패 자동 정지",
};
export const ACTION_STATE_KO: Record<string, string> = { done: "했어요", skipped: "하지 않았어요", failed: "실패했어요", unknown: "몰라요" };
const MODE_KO: Record<string, string> = { SHADOW: "기록만", PAPER: "모의 체결", LIVE: "실계좌" };
const SEV_ORDER = ["CRITICAL", "ERROR", "WARN", "INFO"] as const;
const SEV_KO: Record<string, string> = { CRITICAL: "심각", ERROR: "오류", WARN: "주의", INFO: "알림" };

/** 서버 열거값 번역 — 모르는 값은 원문(지어내지 않는다). */
const ko = (map: Record<string, string>, v: string | null | undefined) =>
  v == null ? <span>몰라요</span> : map[v] ? <span>{map[v]}</span> : <span data-server>{v}</span>;

export function SafetyTab({ isAdmin, signedIn, gate, onChanged }: {
  isAdmin: boolean; signedIn: boolean; gate: UseQueryResult<GateState>; onChanged: () => void;
}) {
  return (
    <div className="lvs">
      {isAdmin ? <GateSection gate={gate} onChanged={onChanged} /> : null}
      {signedIn ? (
        <>
          <KillHistory />
          <ReadinessSec />
          <PnlSec />
          <AuditSec />
        </>
      ) : (
        <p className="tx-sec-sub lvs-login">로그인하면 비상 정지 이력과 감사 기록을 볼 수 있어요.</p>
      )}
    </div>
  );
}

function Sec({ id, title, sub, children }: { id: string; title: string; sub: string; children: React.ReactNode }) {
  return (
    <section className="tx-sec lvs-sec" data-sec={id} aria-labelledby={`lvs-${id}`}>
      <header className="tx-sec-head"><div>
        <h2 className="tx-sec-t" id={`lvs-${id}`}>{title}</h2>
        <p className="tx-sec-sub">{sub}</p>
      </div></header>
      <div className="tx-sec-body">{children}</div>
    </section>
  );
}

const Loading = ({ what }: { what: string }) => <p className="tx-sec-sub" aria-busy="true">{what}을 불러오는 중이에요.</p>;

// ── 비상 정지 이력 ──────────────────────────────────────────────────────────

function KillHistory() {
  const r = useQuery({ queryKey: ["live", "safety", "kill-events"], queryFn: q(readKillEvents), ...opts });
  return (
    <Sec id="kill-events" title="비상 정지 이력" sub="운영 계좌에 걸었던 비상 정지와, 그때 서버가 실제로 한 조치예요. 최근 20건까지 보여요.">
      {r.isError ? <RetryFail title="비상 정지 이력을 불러오지 못했어요" onRetry={() => void r.refetch()}>{r.error.message}</RetryFail>
        : !r.data ? <Loading what="비상 정지 이력" />
        : !r.data.events.length ? <p className="tx-sec-sub lvs-empty">운영 계좌에 비상 정지를 건 적이 없어요.</p>
        : <ol className="lvs-kills">{r.data.events.map((e) => <KillRow key={e.event_id} e={e} />)}</ol>}
    </Sec>
  );
}

function KillRow({ e }: { e: KillEvent }) {
  const open = !e.resolved_at;
  const recs = e.actions?.records ?? [];
  return (
    <li className="lvs-kill" data-open={open ? "true" : "false"}>
      <span className="lvs-kill-dot" aria-hidden />
      <div className="lvs-kill-b">
        <p className="lvs-kill-t">
          {krDateTime(e.triggered_at) ?? "언제인지 몰라요"} · {ko(SOURCE_KO, e.trigger_source)}
          {open ? <> · <strong>지금 걸려 있어요</strong></>
            : <> · {krDateTime(e.resolved_at) ?? "언제인지 모르는 때"}에 {e.resolved_by ?? "누군가"} 님이 풀었어요</>}
        </p>
        <p className="lvs-kill-why">사유 <span data-server>{e.trigger_reason ?? "적혀 있지 않아요"}</span>
          {" · "}취소한 미체결 {e.n_orders_cancelled == null ? "몰라요" : `${num(e.n_orders_cancelled)}건`}</p>
        {recs.length ? (
          <ul className="lvs-acts" aria-label="이 정지가 한 조치">
            {recs.map((a) => (
              <li key={a.action} className="lvs-act" data-state={a.state}>
                <span className="lvs-act-n">{a.label ? <span data-server>{a.label}</span> : <span data-server>{a.action}</span>}</span>
                <span className="lvs-act-s">{ko(ACTION_STATE_KO, a.state)}</span>
                {a.reason ? <span className="lvs-act-why" data-server>{a.reason}</span> : null}
              </li>
            ))}
          </ul>
        ) : <p className="tx-sec-sub">이 정지가 한 조치를 서버가 기록하지 않았어요.</p>}
      </div>
    </li>
  );
}

// ── 자동 비상 정지 준비 상태 ────────────────────────────────────────────────

const TRIGGER_KO: Record<string, string> = {
  auto_dd: "누적 손실이 한도를 넘으면", auto_cb: "하루 손실이 한도를 넘으면", auto_risk: "시장 위험 점수가 높으면", auto_api: "증권사 연결이 계속 실패하면",
};

function ReadinessSec() {
  const r = useQuery({ queryKey: ["live", "safety", "readiness"], queryFn: q(readReadiness), ...opts });
  const codes = useQuery({ queryKey: ["live", "safety", "kis-codes"], queryFn: q(readKisCodes), ...opts });
  const d = r.data;
  return (
    <Sec id="readiness" title="자동 비상 정지 준비 상태" sub="서버가 스스로 비상 정지를 걸 수 있는 조건 넷이에요. 잴 재료가 없는 조건은 한도를 넘어도 걸리지 않아요.">
      {r.isError ? <RetryFail title="자동 비상 정지 준비 상태를 불러오지 못했어요" onRetry={() => void r.refetch()}>{r.error.message}</RetryFail>
        : !d ? <Loading what="준비 상태" />
        : (
          <>
            <p className="lvs-ready-ans">
              조건 {num(d.armed.length + d.inoperable.length)}개 중 <strong>{num(d.armed.length)}개</strong>가 지금 걸 수 있어요.
            </p>
            {d.account_state_reason ? <p className="lv-err" data-server>{d.account_state_reason}</p> : null}
            <ul className="lvs-ready">
              {[...d.armed.map((t) => ({ ...t, ok: true })), ...d.inoperable.map((t) => ({ ...t, ok: false }))].map((t) => (
                <li key={t.trigger} className="lvs-ready-row" data-ok={t.ok ? "true" : "false"} data-trigger={t.trigger}>
                  <span className="lvs-ready-mark">{t.ok ? "걸 수 있어요" : "걸 수 없어요"}</span>
                  <span className="lvs-ready-n">{TRIGGER_KO[t.trigger] ? TRIGGER_KO[t.trigger] : <span data-server>{t.trigger}</span>}</span>
                  {t.reason ? <span className="lvs-ready-why" data-server>{t.reason}</span> : null}
                </li>
              ))}
            </ul>
            {d.note ? <p className="tx-sec-sub" data-server>{d.note}</p> : null}
          </>
        )}
      <div className="lvs-codes" data-part="kis-codes">
        <p className="lvs-codes-h">증권사 응답 코드 뜻 표</p>
        {codes.isError ? <RetryFail title="증권사 응답 코드 표를 불러오지 못했어요" onRetry={() => void codes.refetch()}>{codes.error.message}</RetryFail>
          : !codes.data ? <Loading what="응답 코드 표" />
          : (
            <>
              <p className="tx-sec-sub">
                뜻을 아는 코드 {num(codes.data.table.size)}개 · 본 적 있는 코드 {num(codes.data.observed.length)}개 · 그중 뜻을 모르는 코드 {num(codes.data.gaps.length)}개
              </p>
              {codes.data.gate?.reason ? <p className="tx-sec-sub" data-server>{codes.data.gate.reason}</p> : null}
              {codes.data.table.why_empty ? (
                <details className="lvs-more"><summary>표가 비어 있는 이유</summary><p data-server>{codes.data.table.why_empty}</p></details>
              ) : null}
            </>
          )}
      </div>
    </Sec>
  );
}

// ── 일 손익 ────────────────────────────────────────────────────────────────

function PnlSec() {
  const r = useQuery({ queryKey: ["live", "safety", "daily-pnl"], queryFn: q(readDailyPnl), ...opts });
  return (
    <Sec id="daily-pnl" title="일 손익" sub="운영 계좌의 하루 끝 평가 자산과 수익률이에요. 날마다 그날의 실행 모드가 함께 적혀요.">
      {r.isError ? <RetryFail title="일 손익을 불러오지 못했어요" onRetry={() => void r.refetch()}>{r.error.message}</RetryFail>
        : !r.data ? <Loading what="일 손익" />
        : !r.data.pnl_history.length ? <p className="tx-sec-sub lvs-empty">기록된 날이 아직 없어요.</p>
        : (
          <div className="lvs-tbl-wrap">
            <table className="lvs-tbl">
              <thead><tr><th scope="col">날짜</th><th scope="col">모드</th><th scope="col">끝 평가 자산</th><th scope="col">하루 수익률</th><th scope="col">주문</th></tr></thead>
              <tbody>{r.data.pnl_history.map((p) => <PnlTr key={p.trade_date} p={p} />)}</tbody>
            </table>
          </div>
        )}
    </Sec>
  );
}

function PnlTr({ p }: { p: PnlRow }) {
  const ret = p.daily_return_pct;
  const dir = ret == null || ret === 0 ? "flat" : ret > 0 ? "up" : "down";
  return (
    <tr>
      <td>{p.trade_date}</td>
      <td>{ko(MODE_KO, p.execution_mode)}</td>
      <td className="num">{p.ending_equity_krw == null ? "몰라요" : priceWon(p.ending_equity_krw)}</td>
      <td className="num"><span className="tx-delta" data-dir={dir}>{ret == null ? "몰라요" : `${ret > 0 ? "+" : ret < 0 ? "−" : ""}${Math.abs(ret).toFixed(2)}%`}</span></td>
      <td className="num">{p.n_orders == null ? "몰라요" : `${num(p.n_orders)}건`}</td>
    </tr>
  );
}

// ── 최근 감사 기록 ──────────────────────────────────────────────────────────

function AuditSec() {
  const list = useQuery({ queryKey: ["live", "safety", "audit"], queryFn: q(readAudit), ...opts });
  const sum = useQuery({ queryKey: ["live", "safety", "audit-summary"], queryFn: q(readAuditSummary), ...opts });
  const s = sum.data;
  return (
    <Sec id="audit" title="최근 감사 기록" sub="운영 계좌에서 서버가 남긴 기록이에요. 누가 무엇을 했는지 지우지 않고 쌓아요.">
      {sum.isError ? <RetryFail title="오늘 요약을 불러오지 못했어요" onRetry={() => void sum.refetch()}>{sum.error.message}</RetryFail>
        : !s ? <Loading what="오늘 요약" />
        : s.error ? (
          <RetryFail title="오늘 요약을 서버가 읽지 못했어요" onRetry={() => void sum.refetch()}><span data-server>{s.error}</span></RetryFail>
        ) : (
          <p className="lvs-audit-sum">
            {s.date} 기록 {num(s.total_events ?? 0)}건
            {SEV_ORDER.map((k) => <span key={k} className="lvs-sev" data-sev={k} data-any={(s.by_severity?.[k] ?? 0) > 0 ? "true" : "false"}> · {SEV_KO[k]} {num(s.by_severity?.[k] ?? 0)}</span>)}
          </p>
        )}
      {list.isError ? <RetryFail title="감사 기록을 불러오지 못했어요" onRetry={() => void list.refetch()}>{list.error.message}</RetryFail>
        : !list.data ? <Loading what="감사 기록" />
        : !list.data.events.length ? (
          // 서버가 읽지 못하면 500 + 사유로 답한다(R1) — 그래서 여기 0건은 진짜 0건이다.
          <p className="tx-sec-sub lvs-empty">운영 계좌에 남은 감사 기록이 없어요.</p>
        ) : (
          <ol className="lvs-audit">
            {list.data.events.map((a) => (
              <li key={a.audit_id} className="lvs-audit-row" data-sev={a.severity ?? "unknown"}>
                <span className="lvs-audit-time">{krDateTime(a.timestamp) ?? "언제인지 몰라요"}</span>
                <span className="lvs-audit-sev">{ko(SEV_KO, a.severity)}</span>
                <span className="lvs-audit-what">
                  <span data-mono>{a.event_type}</span>{a.ticker ? <> · <span data-mono>{a.ticker}</span></> : null}
                  {a.message ? <> · <span data-server>{a.message}</span></> : null}
                </span>
                <span className="lvs-audit-who">{a.actor ?? "누군지 몰라요"}</span>
              </li>
            ))}
          </ol>
        )}
    </Sec>
  );
}
