"use client";
/**
 * 규칙 가동 (W5b) — 내 계좌 화면의 절. 받은 가동 요청 → 가동(재생) → 가상 체결.
 * ==========================================================================
 * ★요청은 가동이 아니다★: 요청은 캔버스의 ‘가동 요청’ 노드가 남긴 한 줄이고, 가동 · 정지는 이 절에서만 한다.
 * 가동은 실행 모드 ‘기록 전용’에서만 열린다 — 증권사로는 아무것도 나가지 않는다. 적재된 하루의 분봉을 봉 단위로 다시 흘리고,
 * 그 체결은 시뮬레이터가 계산한 ★가상★ 체결이다(줄마다 표식). 신호는 이 계좌의 주문 경로를 지나 ‘기록 전용’ 주문으로 남는다.
 *
 * 화면이 정하지 않는 것:
 *  · 설정 — 서버가 시행 기록에서만 읽는다(본문은 시행 열쇠와 날짜뿐).
 *  · 관문 — 표시만 한다. 미달 · 미상이 있어도 가동을 막지 않는다(받은 결정). 판정이 없으면 서버 사유를 그대로 적는다.
 *  · 멈춘 까닭 — 서버 문장 그대로(`data-server`).
 * 못 읽음은 빈 목록이 아니다 — 서버가 `available: false` 와 사유를 주면 그 사유를 보인다.
 * 가동 줄마다 ‘관제’ 판을 편다(W5c — `RuleMonitor`): 주문 · 체결 · 실현손익 · 한도까지 남은 폭 · 백테스트와 같은지. 읽기만 한다.
 */
import Link from "next/link";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  MODE_KO, RUN_STATUS_KO, STATUS_KO, advanceRuleRun, barTime, getRuleRun, listArmRequests, listRuleRuns, removeArmRequest, startRuleRun,
  stopRuleRun, type AccountKill, type ArmRequest, type ExecMode, type GateCounts, type RuleRun, type RunFill, type RunReply,
} from "@/entities/broker-account";
import { getCoverage, getTemplates } from "@/entities/intraday";
import { num, priceWon } from "@/shared/lib/krFormat";
import { Notice, RetryFail } from "@/shared/ui/tx";
import { RuleMonitor } from "./RuleMonitor";
import { unwrap, useNames, when } from "./parts";

/** 한 번에 미는 봉 수 — 재생을 눈으로 따라갈 만한 걸음(서버는 1 이상의 정수면 받는다). */
const STEP_BARS = 30;

const gateLine = (c: GateCounts) => `통과 ${num(c.ok)} · 미달 ${num(c.degraded)} · 미상 ${num(c.unknown)}`;
const sideKo = (s: string) => (s === "buy" ? "매수" : s === "sell" ? "매도" : null);
/** 요청을 남긴 시각(초 단위 시각) → 보는 사람의 시간대로. 모르면 null. */
function stamp(sec: number | null): string | null {
  if (typeof sec !== "number" || !Number.isFinite(sec)) return null;
  const d = new Date(sec * 1000);
  const two = (n: number) => String(n).padStart(2, "0");
  return `${d.getMonth() + 1}월 ${d.getDate()}일 ${two(d.getHours())}:${two(d.getMinutes())}`;
}

/** 지금 모드와 비상 정지 — 조회 중이면 `undefined`, 조회 실패면 `null`(둘을 '미사용'으로 접지 않는다). */
type Gate = { mode: ExecMode | null | undefined; kill: AccountKill | null | undefined };

/**
 * 비상 정지를 화면의 말로 — ‘주문이 가는 길’과 같은 갈래다. 서버의 `active` 는 운영자 전역 정지와 ★상태 조회 실패★도 센다
 * (닫힌 실패). 이 계좌가 건 정지(`event`)가 아니면 '사용'이라고 하지 않고 차단이라고 말한다.
 */
function killText(kill: Gate["kill"]): string {
  if (kill === undefined) return "확인 중";
  if (kill === null) return "확인 실패";
  return kill.active && kill.event ? "사용" : kill.active ? "주문 차단 중" : "미사용";
}

/** 가동을 시작할 수 없는 까닭(화면이 아는 것만) — 서버도 같은 것을 거절한다. 관문은 여기 없다(막지 않는다). */
function blockedWhy({ mode, kill }: Gate): string | null {
  if (mode === undefined || kill === undefined) return "실행 모드와 비상 정지 상태 확인 중";
  if (mode === null || kill === null) return "실행 모드나 비상 정지 상태를 확인하지 못해 가동할 수 없습니다.";
  if (kill.active && kill.event) return "비상 정지 중에는 가동할 수 없습니다.";
  if (kill.active) return "주문이 차단돼 있어 가동할 수 없습니다. 이 계좌에서 발동한 정지가 아닙니다. 운영자 정지이거나 상태 조회 실패입니다.";
  if (mode !== "SHADOW") return "실행 모드가 ‘기록 전용’이 아니어서 가동할 수 없습니다. ‘주문이 가는 길’에서 ‘기록 전용’으로 변경하십시오.";
  return null;
}

export function RuleArming({ accountId, mode, kill }: { accountId: string } & Gate) {
  const qc = useQueryClient();
  const reqs = useQuery({ queryKey: ["arm-requests"], queryFn: unwrap(listArmRequests), staleTime: 0, retry: false });
  const runs = useQuery({ queryKey: ["acct", accountId, "rule-runs"], queryFn: unwrap(() => listRuleRuns(accountId)), staleTime: 0, retry: false });
  const templates = useQuery({ queryKey: ["intraday", "templates"], queryFn: unwrap(getTemplates), staleTime: 60_000, retry: false });
  const [said, setSaid] = useState<{ text: string; raw?: string; fail?: boolean } | null>(null);
  const labelOf = (kind: string | null | undefined): string | null =>
    (kind ? templates.data?.templates.find((t) => t.kind === kind)?.label ?? null : null);
  const refresh = () => { void reqs.refetch(); void runs.refetch(); };
  /** 가동은 주문 줄을 남긴다 — 이 계좌의 조회(주문 목록 · 가동 · 가상 체결)를 함께 새로 읽는다. */
  const touched = () => void qc.invalidateQueries({ queryKey: ["acct", accountId] });

  const requestRows = reqs.data?.requests ?? [];
  const runRows = runs.data?.runs ?? [];
  const synthetic = requestRows.some((r) => r.trial.found === true && r.trial.synthetic) || runRows.some((r) => r.grade === "E0");
  const limits = runs.data?.limits;

  return (
    <section className="tx-sec ma-arm" aria-labelledby="ma-arm-h">
      <header className="tx-sec-head">
        <div>
          <h2 className="tx-sec-t" id="ma-arm-h">규칙 가동</h2>
          <p className="tx-sec-sub">
            분봉 백테스트로 실행한 설정을 이 계좌에서 봉 단위로 재생합니다. 실행 모드가 ‘기록 전용’일 때만 가동하며 증권사로 주문을 전송하지 않습니다.
          </p>
        </div>
        <div className="tx-sec-aside">
          <button type="button" className="tx-btn tx-btn--sub ma-sm ma-arm-refresh" onClick={refresh} disabled={reqs.isFetching || runs.isFetching}>새로 고침</button>
        </div>
      </header>
      <div className="tx-sec-body">
        {synthetic ? (
          <Notice tone="practice" title="합성 분봉으로 만든 요청이나 가동이 있습니다.">
            계산 장치를 확인하는 용도이며 예측력이나 수익의 증거가 아닙니다.
          </Notice>
        ) : null}
        {limits ? (
          <p className="ma-arm-limits">
            동시 가동 {num(limits.runs)}건 · 가동당 종목 {num(limits.tickers)}개 · 봉 간격이 {num(limits.gap_minutes)}분을 넘으면 중단
          </p>
        ) : null}
        {said ? (
          <p className={`ma-arm-msg${said.fail ? " ma-err" : ""}`} role={said.fail ? "alert" : "status"}>
            {said.text}{said.raw ? <> <span data-server>{said.raw}</span></> : null}
          </p>
        ) : null}

        <h3 className="ma-arm-h">받은 가동 요청{reqs.data?.available ? <span className="ma-arm-n">{num(requestRows.length)}</span> : null}</h3>
        {reqs.isError ? (
          <RetryFail title="가동 요청 목록 조회 실패" onRetry={() => void reqs.refetch()}><span data-server>{reqs.error.message}</span></RetryFail>
        ) : !reqs.data ? (
          <p className="tx-sec-sub" aria-busy="true">가동 요청 조회 중</p>
        ) : !reqs.data.available ? (
          <RetryFail title="가동 요청 목록 조회 실패" onRetry={() => void reqs.refetch()}><span data-server>{reqs.data.reason}</span></RetryFail>
        ) : requestRows.length === 0 ? (
          <div className="ma-arm-empty">
            <p className="tx-sec-sub">받은 가동 요청 없음. 캔버스의 ‘가동 요청’ 노드에서 남깁니다.</p>
            <Link href="/allocation" className="tx-btn tx-btn--sub ma-sm ma-arm-canvas">캔버스 열기</Link>
          </div>
        ) : (
          <ul className="ma-arm-l ma-arm-reqs">
            {requestRows.map((r) => (
              <RequestRow key={r.id} row={r} accountId={accountId} gate={{ mode, kill }} label={labelOf}
                          onStarted={(reply) => { setSaid({ text: `가동 ${reply.run.run_id}번을 시작했습니다. 아래 가동 기록에서 봉을 재생합니다.` }); touched(); }}
                          onRemoved={() => { setSaid({ text: "요청을 목록에서 뺐습니다." }); void reqs.refetch(); }}
                          onFail={(text, raw) => setSaid({ text, raw, fail: true })} />
            ))}
          </ul>
        )}

        <h3 className="ma-arm-h">가동 기록{runs.data?.available ? <span className="ma-arm-n">{num(runRows.length)}</span> : null}</h3>
        {runs.isError ? (
          <RetryFail title="가동 기록 조회 실패" onRetry={() => void runs.refetch()}><span data-server>{runs.error.message}</span></RetryFail>
        ) : !runs.data ? (
          <p className="tx-sec-sub" aria-busy="true">가동 기록 조회 중</p>
        ) : !runs.data.available ? (
          <RetryFail title="가동 기록 조회 실패" onRetry={() => void runs.refetch()}><span data-server>{runs.data.reason}</span></RetryFail>
        ) : runRows.length === 0 ? (
          <p className="tx-sec-sub ma-arm-none">가동 기록 없음</p>
        ) : (
          <ul className="ma-arm-l ma-arm-runs">
            {runRows.map((r) => (
              <RunRow key={r.run_id} run={r} accountId={accountId} label={labelOf}
                      onDone={(text) => { setSaid({ text }); touched(); }}
                      onFail={(text, raw) => { setSaid({ text, raw, fail: true }); touched(); }} />
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

// ── 받은 가동 요청 ───────────────────────────────────────────────────────────

/** 규칙을 풀어 쓴 글(서버 문장 그대로) — 이름표가 같은 규칙('직접 구성')을 가른다. 못 읽었으면 그 사유를 보인다. */
function RuleText({ text, reason }: { text: string | null | undefined; reason: string | null | undefined }) {
  const said = text ?? reason;
  return said ? <span className="ma-arm-text" data-known={String(Boolean(text))} data-server>{said}</span> : null;
}

function RequestRow({ row, accountId, gate, label, onStarted, onRemoved, onFail }: {
  row: ArmRequest; accountId: string; gate: Gate; label: (kind: string | null | undefined) => string | null;
  onStarted: (reply: RunReply) => void; onRemoved: () => void; onFail: (text: string, raw?: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [asking, setAsking] = useState(false);
  const t = row.trial;
  const remove = useMutation({
    mutationFn: unwrap(() => removeArmRequest(row.id)),
    onSuccess: () => { setAsking(false); onRemoved(); },
    onError: (e: Error) => { setAsking(false); onFail("요청을 목록에서 빼지 못했습니다.", e.message); },
  });
  const made = stamp(row.created_at);
  return (
    <li className="ma-arm-req" data-request={row.id} data-found={String(t.found)}>
      <div className="ma-arm-what">
        {t.found === true ? (
          <>
            <strong className="ma-arm-rule" data-server>{t.rule_label ?? label(t.rule_kind) ?? t.rule_kind ?? "규칙 미상"}</strong>
            <span>종목 {num(t.tickers.length)}개<span className="ma-code" data-mono>{t.tickers.slice(0, 3).join(" ")}{t.tickers.length > 3 ? " 외" : ""}</span></span>
            <span className="ma-arm-period">실행 기간 {t.from} ~ {t.to}</span>
            {t.synthetic ? <span className="tx-chip" data-tone="practice">합성 분봉</span> : null}
            <RuleText text={t.rule_text} reason={t.rule_text_reason} />
          </>
        ) : (
          <span className="ma-arm-gone" data-server>{t.reason}</span>
        )}
      </div>
      <div className="ma-arm-meta">
        <span className="ma-arm-gates" data-known={String(row.gates.known)}>
          관문 일곱 {row.gates.known && row.gates.counts ? gateLine(row.gates.counts) : <span data-server>{row.gates.reason ?? "미상"}</span>}
        </span>
        {row.note ? <span className="ma-arm-note">메모 {row.note}</span> : null}
        <span className="ma-arm-when">요청 {made ?? "시각 미상"}</span>
      </div>
      <div className="ma-arm-act">
        {t.found === true ? (
          <button type="button" className="tx-btn tx-btn--main ma-sm ma-arm-open" aria-expanded={open} onClick={() => { setAsking(false); setOpen((v) => !v); }}>
            {open ? "가동 준비 닫기" : "가동 준비"}
          </button>
        ) : null}
        {asking ? (
          <span className="ma-confirm tx-confirm ma-arm-confirm" role="group" aria-label="요청 빼기 확인">
            <span>이 요청을 목록에서 빼시겠습니까?</span>
            <button type="button" className="tx-btn tx-btn--main ma-sm ma-arm-remove-yes" disabled={remove.isPending} onClick={() => remove.mutate()}>빼기</button>
            <button type="button" className="tx-btn tx-btn--sub ma-sm ma-arm-remove-no" onClick={() => setAsking(false)}>그대로 두기</button>
          </span>
        ) : (
          <button type="button" className="tx-btn tx-btn--sub ma-sm ma-arm-remove" onClick={() => { setOpen(false); setAsking(true); }}>목록에서 빼기</button>
        )}
      </div>
      {open && t.found === true ? (
        <StartPanel row={row} trial={t} accountId={accountId} gate={gate}
                    onStarted={(reply) => { setOpen(false); onStarted(reply); }} />
      ) : null}
    </li>
  );
}

/** 가동 준비 — 날짜(그 설정의 실행 기간 가운데 분봉이 적재된 날)를 고르고, 지금 모드 · 비상 정지 · 관문 · 출처를 본 뒤 시작한다. */
function StartPanel({ row, trial, accountId, gate, onStarted }: {
  row: ArmRequest; trial: Extract<ArmRequest["trial"], { found: true }>; accountId: string; gate: Gate; onStarted: (reply: RunReply) => void;
}) {
  const cov = useQuery({
    queryKey: ["intraday", "coverage", trial.from, trial.to, trial.tickers.join(",")],
    queryFn: unwrap(() => getCoverage({ from: trial.from, to: trial.to, tickers: trial.tickers })), staleTime: 0, retry: false,
  });
  const days = (cov.data?.days ?? []).filter((d) => d.status === "loaded").map((d) => d.date);
  const [picked, setPicked] = useState<string | null>(null);
  const day = picked ?? days[days.length - 1] ?? null;
  const start = useMutation({ mutationFn: unwrap(() => startRuleRun(accountId, { trial_key: row.trial_key, day: day ?? "" })), onSuccess: onStarted });
  const why = blockedWhy(gate);
  const field = `ma-arm-day-${row.id}`;
  return (
    <div className="ma-arm-start tx-confirm" role="group" aria-label="가동 준비">
      {cov.isError ? (
        <RetryFail title="분봉 적재 범위 조회 실패" onRetry={() => void cov.refetch()}><span data-server>{cov.error.message}</span></RetryFail>
      ) : !cov.data ? (
        <p aria-busy="true">분봉 적재 범위 조회 중</p>
      ) : days.length === 0 ? (
        <p className="ma-arm-nodays">실행 기간에 분봉이 적재된 날 없음. 적재 범위는 ‘데이터 상태’ 화면에서 확인합니다.</p>
      ) : (
        <label className="ma-arm-day" htmlFor={field}>
          <span className="ma-label">가동할 날짜</span>
          <select id={field} className="ma-input ma-arm-day-pick" value={day ?? ""} onChange={(e) => { start.reset(); setPicked(e.target.value); }}>
            {days.map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
        </label>
      )}
      <dl className="ma-arm-facts">
        <div><dt>실행 모드</dt>
          <dd className="ma-arm-mode">{gate.mode ? MODE_KO[gate.mode] ?? <span data-server>{gate.mode}</span> : gate.mode === null ? "확인 실패" : "확인 중"}</dd></div>
        <div><dt>비상 정지</dt><dd className="ma-arm-kill">{killText(gate.kill)}</dd></div>
        <div><dt>관문 일곱</dt>
          <dd>{row.gates.known && row.gates.counts ? gateLine(row.gates.counts) : <span data-server>{row.gates.reason ?? "미상"}</span>}</dd></div>
        <div><dt>분봉 출처</dt><dd>{trial.synthetic ? "합성 분봉" : trial.grade === "E3" ? "적재된 실제 분봉" : "미상"}</dd></div>
      </dl>
      <p className="ma-arm-how">관문은 표시만 하며 가동을 차단하지 않습니다. 체결은 시뮬레이터가 계산한 가상 체결이고, 신호는 이 계좌의 주문 경로를 지나 ‘기록 전용’ 주문으로 남습니다.</p>
      {why ? <p className="ma-arm-block" role="note">{why}</p> : null}
      {start.isError ? <p className="ma-err ma-arm-refused" role="alert"><span data-server>{start.error.message}</span></p> : null}
      <div className="tx-confirm-act">
        <button type="button" className="tx-btn tx-btn--main ma-sm ma-arm-go" disabled={!!why || !day || start.isPending} onClick={() => start.mutate()}>
          {start.isPending ? "가동 시작 중" : "가동 시작"}
        </button>
      </div>
    </div>
  );
}

// ── 가동 기록 ───────────────────────────────────────────────────────────────

function RunRow({ run, accountId, label, onDone, onFail }: {
  run: RuleRun; accountId: string; label: (kind: string | null | undefined) => string | null;
  onDone: (text: string) => void; onFail: (text: string, raw?: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [watching, setWatching] = useState(false);
  const kind = run.request?.rule?.kind;
  /** 서버가 실제로 민 봉 수와 새 가상 체결 수를 그대로 말한다(누른 단추의 수가 아니다 — 하루가 먼저 끝날 수 있다). */
  const after = (reply: RunReply) => {
    const moved = reply.run.bars - run.bars;
    const fresh = reply.run.new_fills?.length ?? 0;
    const ended = reply.run.status === "running" ? "" : reply.run.status === "finished" ? " 하루의 끝까지 돌았습니다." : " 가동이 멈췄습니다.";
    onDone(`가동 ${run.run_id}번: 봉 ${num(moved)}개를 재생했습니다. 새 가상 체결 ${num(fresh)}건.${ended}`);
  };
  const step = useMutation({
    mutationFn: unwrap(() => advanceRuleRun(accountId, run.run_id, STEP_BARS)),
    onSuccess: (r: RunReply) => after(r), onError: (e: Error) => onFail(`가동 ${run.run_id}번을 재생하지 못했습니다.`, e.message),
  });
  const finish = useMutation({
    mutationFn: unwrap(() => advanceRuleRun(accountId, run.run_id)),
    onSuccess: (r: RunReply) => { setOpen(true); after(r); }, onError: (e: Error) => onFail(`가동 ${run.run_id}번을 재생하지 못했습니다.`, e.message),
  });
  const stop = useMutation({
    mutationFn: unwrap(() => stopRuleRun(accountId, run.run_id)),
    onSuccess: () => onDone(`가동 ${run.run_id}번을 정지했습니다.`), onError: (e: Error) => onFail(`가동 ${run.run_id}번을 정지하지 못했습니다.`, e.message),
  });
  const busy = step.isPending || finish.isPending || stop.isPending;
  const c = run.clock;
  const next = barTime(c?.next);
  const last = barTime(run.last_bar);
  return (
    <li className="ma-arm-run" data-run={run.run_id} data-status={run.status} data-active={String(run.active)}>
      <div className="ma-arm-what">
        <span className="ma-arm-id" data-mono>{run.run_id}번</span>
        <strong className="ma-arm-rule" data-server>{label(kind) ?? kind ?? "규칙 미상"}</strong>
        <span className="ma-arm-daytext">{run.day}</span>
        <span>종목 {num(run.tickers.length)}개</span>
        <span className="ma-arm-status">{RUN_STATUS_KO[run.status] ?? <span data-server>{run.status}</span>}</span>
        <span className="tx-chip" data-tone="plain">{MODE_KO[run.mode] ?? <span data-server>{run.mode}</span>}</span>
        {run.grade === "E0" ? <span className="tx-chip" data-tone="practice">합성 분봉</span>
          : run.grade !== "E3" ? <span className="tx-chip" data-tone="unknown">분봉 출처 미상</span> : null}
        <RuleText text={run.rule_text} reason={run.rule_text_reason} />
      </div>
      {c ? (
        <div className="ma-arm-progress">
          <span className="ma-arm-meter" role="progressbar" aria-label="재생한 봉" aria-valuemin={0} aria-valuemax={c.total} aria-valuenow={c.done}>
            <span className="ma-arm-meter-fill" style={{ width: `${c.total ? Math.min(100, (c.done / c.total) * 100) : 0}%` }} />
          </span>
          <span className="ma-arm-clock">봉 {num(c.done)} / {num(c.total)}{next ? ` · 다음 ${next}` : " · 남은 봉 없음"}</span>
        </div>
      ) : null}
      <div className="ma-arm-meta">
        <span className="ma-arm-last">마지막 봉 {last ?? "없음"}</span>
        <span className="ma-arm-bars">재생한 봉 {num(run.bars)}개</span>
        <span className="ma-arm-signals">신호 {num(run.signals)}건</span>
        {run.stop_message ? <span className="ma-arm-why" data-server>{run.stop_message}</span> : null}
      </div>
      <div className="ma-arm-act">
        {run.active ? (
          <>
            <button type="button" className="tx-btn tx-btn--sub ma-sm ma-arm-step" disabled={busy} onClick={() => step.mutate()}>다음 봉 {STEP_BARS}개</button>
            <button type="button" className="tx-btn tx-btn--main ma-sm ma-arm-finish" disabled={busy} onClick={() => finish.mutate()}>끝까지</button>
            <button type="button" className="tx-btn ma-btn-danger ma-sm ma-arm-stop" disabled={busy} onClick={() => stop.mutate()}>정지</button>
          </>
        ) : null}
        <button type="button" className="tx-btn tx-btn--sub ma-sm ma-arm-mon-open" aria-expanded={watching} onClick={() => setWatching((v) => !v)}>
          {watching ? "관제 닫기" : "관제"}
        </button>
        <button type="button" className="tx-btn tx-btn--sub ma-sm ma-arm-fills-open" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
          {open ? "가상 체결 닫기" : "가상 체결 보기"}
        </button>
      </div>
      {watching ? <RuleMonitor accountId={accountId} run={run} /> : null}
      {open ? <Fills accountId={accountId} runId={run.run_id} /> : null}
    </li>
  );
}

/** 가상 체결 — 줄마다 ‘가상’ 표식과 그 신호가 주문 경로에서 받은 답. 실제 체결이 아니다. 좁은 폭에서도 표식이 가려지지 않게 줄로 그린다(최근 주문과 같은 꼴). */
function Fills({ accountId, runId }: { accountId: string; runId: number }) {
  const q = useQuery({ queryKey: ["acct", accountId, "rule-run", runId], queryFn: unwrap(() => getRuleRun(accountId, runId)), staleTime: 0, retry: false });
  const fills: RunFill[] = q.data?.run.fills ?? [];
  const names = useNames(fills.map((f) => f.symbol));
  if (q.isError) return <RetryFail title="가상 체결 조회 실패" onRetry={() => void q.refetch()}><span data-server>{q.error.message}</span></RetryFail>;
  if (!q.data) return <p className="tx-sec-sub" aria-busy="true">가상 체결 조회 중</p>;
  if (fills.length === 0) return <p className="tx-sec-sub ma-arm-nofills">가상 체결 없음</p>;
  return (
    <div className="ma-arm-fills">
      <ul className="ma-arm-l ma-arm-fills-l" aria-label="가상 체결">
        {fills.map((f) => {
          const name = names.known(f.symbol);
          const side = sideKo(f.side);
          return (
            <li key={f.seq} className="ma-arm-fill" data-side={f.side}>
              <span className="ma-arm-fill-at">{when(f.executed_at) ?? <span data-server>{f.executed_at}</span>}</span>
              <span className="ma-arm-fill-what">
                <strong>{name ?? f.symbol}</strong>
                {name ? <span className="ma-code" data-mono>{f.symbol}</span> : null}
                <span className="ma-arm-fill-side">{side ?? <span data-server>{f.side}</span>}</span>
                <span className="ma-arm-fill-qty">{num(f.quantity)}주</span>
                <span className="ma-arm-fill-price">{priceWon(f.price)}</span>
              </span>
              <span className="ma-arm-fill-marks">
                <span className="tx-chip ma-arm-virtual" data-tone="assumed">가상</span>
                <span className="ma-arm-fill-order">
                  주문 경로 {f.order_status ? STATUS_KO[f.order_status] ?? <span data-server>{f.order_status}</span> : "기록 없음"}
                  {f.order_reason ? <span className="ma-code" data-server>{f.order_reason}</span> : null}
                </span>
              </span>
            </li>
          );
        })}
      </ul>
      <p className="ma-arm-cap">가상 체결은 시뮬레이터가 계산한 값이며 실제 체결이 아닙니다.</p>
    </div>
  );
}
