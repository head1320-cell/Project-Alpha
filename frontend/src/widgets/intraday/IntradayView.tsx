"use client";
/**
 * 분봉 백테스트 — `/intraday`. 데이터 → 규칙 → 포지션·위험 → 비용 가정 → 결과 → 판정이 한 화면에 위에서 아래로 쌓인다.
 * ==========================================================================
 * 설계: `docs/superpowers/specs/2026-11-14-intraday-minute-simulator-design.md` §7.2 · §8.
 * ★도구는 규칙을 추천하지 않는다★ — 종목·기간·틀·매개변수는 사용자가 정하고, 화면은 그 규칙이 과거 분봉에서 무엇을 남겼는지와
 * 그 숫자를 어디까지 읽을 수 있는지만 보인다. 주문은 내지 않는다(계산만).
 * ★합성 분봉이면 화면 맨 위에 그렇게 적는다★ — 적재 범위나 결과에 합성이 한 줄이라도 섞이면 알림이 고정된다.
 * ★낡은 결과를 남기지 않는다★ — 설정을 바꾸면 앞의 결과와 판정을 지우고 재계산이 필요하다고 말한다.
 * 로그인이 필요한 까닭: 무엇을 시험하는지가 드러나고, 시행 횟수를 사용자별로 기록한다.
 */
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useMemo, useState } from "react";
import { getCoverage, getTemplates, simulate, validate, type Coverage, type Validation } from "@/entities/intraday";
import { useSession } from "@/entities/session";
import { loginHref } from "@/shared/lib/nextPath";
import { Notice, PageHead, RetryFail, Section } from "@/shared/ui/tx";
import { build, buildGrid, initialForm, parseTickers, recentPeriod, templateOf, type Form } from "./form";
import { IntradayResult, type Sim } from "./IntradayResult";
import { GridForm, SetupForm, type CoverageState } from "./SetupForm";
import { Verdict } from "./Verdict";

const TITLE = "분봉 백테스트";
const LEDE = "정한 규칙을 과거 분봉에서 돌려 모의 체결의 승률·손익비·비용을 집계하고, 그 숫자를 어디까지 읽을 수 있는지 관문으로 점검합니다. 규칙이나 종목을 권하지 않으며 주문을 내지 않습니다.";
const HERE = "/intraday";
const COVERAGE_DAYS = 31;

type Run<T> = { kind: "idle" } | { kind: "pending" } | { kind: "fail"; status: number; error: string } | { kind: "done"; value: T };

export function IntradayView() {
  const { session, retry } = useSession();
  return (
    <div className="tx-page tj itd">
      <PageHead title={TITLE} lede={LEDE} />
      {session.kind === "loading" ? (
        <p className="tx-sec-sub" aria-busy="true">계정 확인 중</p>
      ) : session.kind === "unknown" ? (
        <RetryFail title="계정 정보 확인 실패" onRetry={() => void retry()}>{session.reason}</RetryFail>
      ) : session.kind === "signed_out" ? (
        <section className="tx-sec tj-signed-out itd-signed-out">
          <p className="tj-strong">로그인하면 분봉 백테스트를 사용할 수 있습니다.</p>
          <p className="tx-sec-sub">어떤 규칙을 시험하는지가 드러나고 시행 횟수를 계정별로 기록하므로 로그인한 계정만 실행할 수 있습니다.</p>
          <Link href={loginHref(HERE)} className="tx-btn tx-btn--main">로그인</Link>
        </section>
      ) : session.mustChange ? (
        <section className="tx-sec tj-must" role="alert">
          <p className="tj-strong">비밀번호를 먼저 변경하십시오.</p>
          <p className="tx-sec-sub">관리자가 발급한 임시 비밀번호로는 분봉 백테스트를 사용할 수 없습니다.</p>
          <Link href="/settings#password" className="tx-btn tx-btn--main">비밀번호 바꾸러 가기</Link>
        </section>
      ) : (
        <Workbench />
      )}
    </div>
  );
}

/** 서버가 답한 실패를 그대로 던진다 — react-query 가 상태 번호와 사유를 함께 들고 있게. */
class Refused extends Error {
  constructor(readonly status: number, message: string) { super(message); }
}
const unwrap = <T,>(fn: () => Promise<{ ok: true; value: T } | { ok: false; status: number; error: string }>) => async (): Promise<T> => {
  const r = await fn();
  if (!r.ok) throw new Refused(r.status, r.error);
  return r.value;
};
const failOf = (e: unknown): { status: number; error: string } =>
  e instanceof Refused ? { status: e.status, error: e.message } : { status: 0, error: "서버 연결 실패" };

function Workbench() {
  // 틀 목록과 '최근 한 달의 적재 범위'는 화면을 열 때 한 번 읽는다(기간을 주지 않으면 서버가 최근 한 달을 답한다).
  const templates = useQuery({ queryKey: ["intraday", "templates"], queryFn: unwrap(getTemplates), staleTime: 0, retry: false });
  const recent = useQuery({ queryKey: ["intraday", "coverage", "recent"], queryFn: unwrap(() => getCoverage()), staleTime: 0, retry: false });
  const [edited, setForm] = useState<Form | null>(null);
  const [asked, setAsked] = useState<Run<Coverage>>({ kind: "idle" });
  const [run, setRun] = useState<Run<Sim>>({ kind: "idle" });
  const [check, setCheck] = useState<Run<Validation>>({ kind: "idle" });
  const [stale, setStale] = useState(false);

  const t = templates.data ?? null;
  const start0 = useMemo(() => (t ? initialForm(t, recentPeriod(COVERAGE_DAYS)) : null), [t]);
  const form = edited ?? start0;
  const built = useMemo(() => (t && form ? build(form, t) : null), [t, form]);
  const grid = useMemo(() => (t && form ? buildGrid(form, t) : null), [t, form]);

  if (templates.isPending) return <p className="tx-sec-sub" aria-busy="true">설정 칸 불러오는 중</p>;
  if (templates.isError) {
    const f = failOf(templates.error);
    return f.status === 401
      ? <Notice tone="danger" title="로그인 세션이 만료됐습니다.">다시 로그인하십시오. <Link href={loginHref(HERE)} className="tj-link">로그인</Link></Notice>
      : <RetryFail title="설정 칸 불러오기 실패" onRetry={() => void templates.refetch()}><span data-server>{f.error}</span></RetryFail>;
  }
  if (!t || !form || !built || !grid) return null;

  // 적재 범위 — 사용자가 물은 것이 있으면 그것, 없으면 화면을 열 때 읽은 최근 한 달.
  const coverage: CoverageState = asked.kind !== "idle" ? asked
    : recent.isPending ? { kind: "pending" } : recent.isError ? { kind: "fail", ...failOf(recent.error) } : { kind: "done", value: recent.data };

  const change = (next: Form) => {
    setForm(next);
    if (run.kind !== "idle" || check.kind !== "idle") { setRun({ kind: "idle" }); setCheck({ kind: "idle" }); setStale(true); }
  };
  const askCoverage = async () => {
    setAsked({ kind: "pending" });
    const c = await getCoverage({ from: form.from, to: form.to, tickers: parseTickers(form.tickers).slice(0, t.limits.tickers) });
    setAsked(c.ok ? { kind: "done", value: c.value } : { kind: "fail", status: c.status, error: c.error });
  };
  const start = async () => {
    if (built.problems.length) return;
    setRun({ kind: "pending" });
    setCheck({ kind: "idle" });
    setStale(false);
    const r = await simulate(built.request);
    setRun(r.ok ? { kind: "done", value: r.value as Sim } : { kind: "fail", status: r.status, error: r.error });
  };
  const judge = async () => {
    if (built.problems.length || grid.problems.length) return;
    setCheck({ kind: "pending" });
    const r = await validate(grid.grid ? { ...built.request, walk_forward: grid.grid } : built.request);
    setCheck(r.ok ? { kind: "done", value: r.value } : { kind: "fail", status: r.status, error: r.error });
  };

  const synthetic = (coverage.kind === "done" && coverage.value.summary.sources.synthetic > 0)
    || (run.kind === "done" && run.value.origin?.grade === "E0") || (check.kind === "done" && check.value.gates?.on_synthetic === true);
  const labels = Object.fromEntries([...templateOf(t, form.kind).params, ...t.position].map((f) => [f.key, f.label]));
  const fail = (r: { status: number; error: string }, title: string, again: () => void) => (
    r.status === 401 ? <Notice tone="danger" title="로그인 세션이 만료됐습니다.">다시 로그인하십시오. <Link href={loginHref(HERE)} className="tj-link">로그인</Link></Notice>
      : r.status === 400 || r.status === 422 ? <Notice tone="danger" title={`${title} 거절`}><span data-server>{r.error}</span></Notice>
      : <RetryFail title={`${title} 실패`} onRetry={again}><span data-server>{r.error}</span></RetryFail>
  );

  return (
    <>
      {synthetic ? (
        <div className="itd-banner">
          <Notice tone="practice" title="합성 분봉: 장치 확인용이며 예측력·수익의 증거가 아닙니다.">
            모의 모드에서 만든 분봉이 섞여 있습니다. 이 화면의 숫자는 계산 장치가 도는지를 확인하는 용도로만 읽으십시오.
          </Notice>
        </div>
      ) : null}

      <SetupForm templates={t} form={form} onChange={change} coverage={coverage} onCoverage={() => void askCoverage()}
                 problems={built.problems} pending={run.kind === "pending"} stale={stale} onRun={() => void start()} />

      {run.kind === "fail" ? <div className="tj-run-fail itd-run-fail">{fail(run, "실행 요청", () => void start())}</div> : null}
      {run.kind === "done" ? <IntradayResult sim={run.value} /> : null}

      {run.kind === "done" && !run.value.empty ? (
        <Section title="판정" sub="같은 규칙을 표본외 구간 · 두 배의 비용 · 다른 슬리피지 가정 · 시행 횟수로 다시 봅니다. 판정을 볼 때마다 표본외 구간을 본 횟수가 기록됩니다.">
          <div className="tj-map itd-judge">
            <GridForm templates={t} form={form} onChange={(next) => { setForm(next); if (check.kind !== "idle") setCheck({ kind: "idle" }); }} cells={grid.cells} />
            <div className="tj-run-row">
              <button type="button" className="tx-btn tx-btn--main tj-run itd-judge-btn" disabled={grid.problems.length > 0 || check.kind === "pending"} onClick={() => void judge()}>
                {check.kind === "pending" ? "계산 중" : "판정"}
              </button>
              {grid.problems.length ? <ul className="tj-map-miss itd-grid-problems">{grid.problems.map((p) => <li key={p}>{p}</li>)}</ul>
                : <p className="tj-note">판정은 설정을 여러 번 다시 돌립니다. 종목 수 × 거래일 수 × 계산 횟수가 {t.limits.validate_work.toLocaleString("ko-KR")}을 넘으면 거절합니다.</p>}
            </div>
            {check.kind === "fail" ? <div className="itd-judge-fail">{fail(check, "판정 요청", () => void judge())}</div> : null}
          </div>
        </Section>
      ) : null}
      {check.kind === "done" ? <Verdict v={check.value} labels={labels} /> : null}
    </>
  );
}
