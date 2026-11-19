"use client";
/**
 * 매매일지 › 백테스트와 견주기 (설계 W5 §4.5)
 * ==========================================================================
 * 방금 분석한 체결을, 내가 돌린 분봉 백테스트 가운데 하나와 견준다. 설정은 그 백테스트의 것을 ★그대로★ 다시 보낸다
 * (서버가 준 요청을 고치지 않는다 — 같은 설정이라 시행 수가 늘지 않는다).
 *
 * - 목록은 내 것만이고 마지막으로 돌린 것이 먼저다(분봉 화면에서 넘어오면 방금 돌린 것이 맨 위다).
 * - 못 읽으면 빈 목록이 아니라 사유. 돌린 백테스트가 없으면 어디서 돌리는지 안내한다.
 * - 올린 체결은 서버에 저장되지 않는다. 비용은 고른 백테스트의 비용 가정으로 계산한다(파일의 수수료·세금 열이 있으면 그 값이 먼저).
 */
import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { divergence, listTrials, type Divergence, type TrialRow } from "@/entities/intraday";
import type { FillRow } from "@/entities/trade-journal";
import { DivergenceResult } from "@/features/divergence-result";
import { ContextFacts } from "@/features/intraday-day-types";
import { HypothesisLine } from "@/features/intraday-verdict";
import { Notice, RetryFail, Section } from "@/shared/ui/tx";

const WINDOWS = [1, 5, 15] as const;
/** `Result` → 던지는 함수(React Query 가 실패를 실패로 본다). 사유는 서버 문장 그대로다. */
const unwrap = <T,>(fn: () => Promise<{ ok: true; value: T } | { ok: false; status: number; error: string }>) => async (): Promise<T> => {
  const r = await fn();
  if (!r.ok) throw new Error(r.error);
  return r.value;
};
type Run = { kind: "idle" } | { kind: "pending" } | { kind: "fail"; status: number; error: string } | { kind: "done"; r: Divergence };

/** 실행 전 가설(G3)이 남은 시행은 고르기 줄에 '적은 때'를 짧게 붙인다(글은 고른 뒤 아래 줄에 — 서버 문장 그대로). 없거나 읽지 못했으면 붙이지 않는다. */
const hypothesisMark = (t: TrialRow): string => {
  const h = t.hypothesis;
  if (!h || h.text === null) return "";
  return h.before_results === true ? " · 가설: 결과를 보기 전" : h.before_results === false ? " · 가설: 결과를 본 뒤" : " · 가설: 적은 때 미상";
};
const label = (t: TrialRow) =>
  `${t.rule_label ?? t.request.rule.kind} · ${t.request.tickers.slice(0, 3).join(", ")}${t.request.tickers.length > 3 ? ` 외 ${t.request.tickers.length - 3}종목` : ""} · ${t.request.from} ~ ${t.request.to} · ${t.runs.toLocaleString("ko-KR")}회 실행${hypothesisMark(t)}`;

export function CompareSection({ fills }: { fills: FillRow[] }) {
  const list = useQuery({ queryKey: ["intraday", "trials"], queryFn: unwrap(listTrials), staleTime: 0, retry: false });
  const [picked, setPicked] = useState<string | null>(null);
  const [minutes, setMinutes] = useState<number>(5);
  const [run, setRun] = useState<Run>({ kind: "idle" });

  const trials = list.data?.available ? list.data.trials : [];
  const cur = trials.find((t) => t.trial_key === picked) ?? trials[0] ?? null;
  const change = (fn: () => void) => { fn(); if (run.kind !== "idle") setRun({ kind: "idle" }); };
  const compare = async () => {
    if (!cur) return;
    setRun({ kind: "pending" });
    const r = await divergence<FillRow>({ ...cur.request, fills, window_minutes: minutes });
    setRun(r.ok ? { kind: "done", r: r.value } : { kind: "fail", status: r.status, error: r.error });
  };

  return (
    <div className="dv-wrap">
    <Section title="백테스트와 견주기" sub="이 체결을 내가 돌린 분봉 백테스트의 시뮬레이션 체결과 견줍니다. 체결가 차이, 놓친 신호, 규칙 밖 매매를 셉니다. 관측값만 보여 주며 규칙을 권하지 않습니다.">
      <div className="dv-compare">
        {list.isPending ? <p className="tx-sec-sub" aria-busy="true">분봉 백테스트 목록 조회 중</p> : null}
        {list.isError ? <RetryFail title="분봉 백테스트 목록 조회 실패" onRetry={() => void list.refetch()}><span data-server>{list.error.message}</span></RetryFail> : null}
        {list.data && !list.data.available ? (
          <Notice tone="warn" title="분봉 백테스트 목록을 읽지 못했습니다."><span data-server>{list.data.reason}</span></Notice>
        ) : null}
        {list.data?.available && trials.length === 0 ? (
          <div className="dv-no-trials">
            <Notice tone="warn" title="돌린 분봉 백테스트가 없습니다.">
              견줄 규칙을 먼저 한 번 실행하십시오. <Link href="/backtest/intraday" className="tj-link">백테스트 › 분봉 규칙</Link>
            </Notice>
          </div>
        ) : null}
        {cur ? (
          <>
            <div className="dv-pick">
              <label className="tj-field dv-trial-l">
                <span className="tj-label">견줄 분봉 백테스트</span>
                <select className="tj-input dv-trial" value={cur.trial_key} onChange={(e) => change(() => setPicked(e.target.value))}>
                  {trials.map((t) => <option key={t.trial_key} value={t.trial_key}>{label(t)}</option>)}
                </select>
              </label>
              <label className="tj-field dv-window-l">
                <span className="tj-label">짝짓기 허용 시간</span>
                <select className="tj-input dv-window" value={minutes} onChange={(e) => change(() => setMinutes(Number(e.target.value)))}>
                  {WINDOWS.map((w) => <option key={w} value={w}>{w}분</option>)}
                </select>
              </label>
            </div>
            {cur.rule_text ?? cur.rule_text_reason ? (
              <p className="dv-rule" data-known={String(Boolean(cur.rule_text))}>
                <span className="tj-label">고른 백테스트의 규칙</span>
                <span className="dv-rule-text" data-server>{cur.rule_text ?? cur.rule_text_reason}</span>
              </p>
            ) : null}
            <HypothesisLine h={cur.hypothesis} />{/* 고른 시행의 실행 전 가설(G3) — 없으면 줄이 없다 */}
            <ul className="tj-plain-list dv-notes">
              <li>허용 시간은 선언한 가정입니다. 결과에 1분·5분·15분에서의 건수를 함께 적습니다.</li>
              <li>비용은 고른 백테스트의 비용 가정으로 계산합니다. 파일에 수수료·세금 열을 지정했으면 그 값을 먼저 씁니다.</li>
              <li>규칙의 종목과 기간 안의 체결만 견줍니다. 올린 체결은 서버에 저장하지 않습니다.</li>
            </ul>
            <div className="tj-run-row">
              <button type="button" className="tx-btn tx-btn--main dv-run" disabled={run.kind === "pending"} onClick={() => void compare()}>{run.kind === "pending" ? "계산 중" : "견주기"}</button>
            </div>
          </>
        ) : null}
        {run.kind === "fail" ? (
          <div className="dv-run-fail">
            {run.status === 400 || run.status === 422
              ? <Notice tone="danger" title="견주기 요청 거절"><span data-server>{run.error}</span></Notice>
              : <RetryFail title="견주기 실패" onRetry={() => void compare()}><span data-server>{run.error}</span></RetryFail>}
          </div>
        ) : null}
      </div>
    </Section>
    {/* 견준 규칙이 하루 유형을 쓰면 그 모형의 학습 기간 · 종목 — 서버 문장 그대로(쓰지 않으면 그리지 않는다) */}
    {run.kind === "done" ? <><ContextFacts facts={run.r.context} /><DivergenceResult r={run.r} /></> : null}
    </div>
  );
}
