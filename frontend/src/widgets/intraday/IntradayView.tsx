"use client";
/**
 * 분봉 백테스트 — 백테스트 › 분봉 규칙(`/backtest/intraday` · ADR 006 §7 — 따로 있던 화면이 백테스트 메뉴 안의 모드가 됐다). 데이터 → 규칙 → 포지션·위험 → 비용 가정 → 결과 → 판정이 한 화면에 위에서 아래로 쌓인다.
 * ==========================================================================
 * 설계: `docs/superpowers/specs/2026-11-14-intraday-minute-simulator-design.md` §7.2 · §8.
 * ★도구는 규칙을 추천하지 않는다★ — 종목·기간·틀·매개변수는 사용자가 정하고, 화면은 그 규칙이 과거 분봉에서 무엇을 남겼는지와
 * 그 숫자를 어디까지 읽을 수 있는지만 보인다. 주문은 내지 않는다(계산만).
 * ★합성 분봉이면 화면 맨 위에 그렇게 적는다★ — 적재 범위나 결과에 합성이 한 줄이라도 섞이면 알림이 고정된다.
 * ★낡은 결과를 남기지 않는다★ — 설정을 바꾸면 앞의 결과와 판정을 지우고 재계산이 필요하다고 말한다.
 * 로그인이 필요한 까닭: 무엇을 시험하는지가 드러나고, 시행 횟수를 사용자별로 기록한다.
 * ★넓고 높은 화면에서는 두 칸(G5)★ — 왼쪽 설정 · 오른쪽 결과와 분석이 각자 구르고 실행 줄은 설정 칸 바닥에 붙는다(계획 문서 §6). 언제 나누는지는
 * `splitPane.ts` 의 SPLIT_QUERY 하나 · 그 밖은 지금과 같은 한 열(같은 DOM 순서 · 같은 간격). 배치만 바꾼다 — 계산 · 시행 기록 · 서버 0줄.
 * ★판 배치(G6 2a-1 · 계획 §9)★ — '배치' 메뉴로 켜면 같은 절들이 판 여섯(설정 · 결과 · 봉과 체결 · 판정 · 하루 유형 · 시장 국면)이 되어 열 · 칸 · 탭에 선다
 * (`shared/ui/workspace` · `workspaceSpec.ts`). 상태와 처리기는 여기 하나 그대로이고 판은 같은 조각을 그린다 — 배치를 바꿔도 시행 · 계산은 늘지 않는다.
 * 끈 화면(기본 배치)은 G5 그대로 + 결과 칸 막대의 '배치' 단추 하나(골든 `e2e/golden/intraday-dom.json`).
 */
import { useQuery } from "@tanstack/react-query";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { expandRule, getCoverage, getTemplates, simulate, validate, type Coverage, type SimulateRequest, type Validation } from "@/entities/intraday";
import { useSession } from "@/entities/session";
import { fromParams, useRuleCheck } from "@/features/intraday-rule-editor";
import { Verdict } from "@/features/intraday-verdict";
import { BACKTEST_MODES } from "@/shared/lib/modes";
import { loginHref } from "@/shared/lib/nextPath";
import { useMediaQuery } from "@/shared/lib/useMediaQuery";
import { Splitter } from "@/shared/ui/split/Splitter";
import { ModeSwitch, Notice, PageHead, RetryFail, Section } from "@/shared/ui/tx";
import { LayoutMenu, LayoutSheet, Workspace, useWorkWidth, useWorkspace, type WorkspaceApi, type WorkspaceState } from "@/shared/ui/workspace";
import { BarsSection } from "./BarsSection";
import { DayTypeSection } from "./DayTypeSection";
import { MarketRegimeSection } from "./MarketRegimeSection";
import { build, buildGrid, initialForm, parseTickers, recentPeriod, templateOf, type Form } from "./form";
import { IntradayResult, type Sim } from "./IntradayResult";
import type { Move } from "./RuleSection";
import { GridForm, SetupForm, type CoverageState } from "./SetupForm";
import { SET_MIN, SET_STEP, SPLIT_QUERY } from "./splitPane";
import { useSplitPane } from "./useSplitPane";
import { INTRADAY_WS } from "./workspaceSpec";

const TITLE = "백테스트";
const LEDE = "정한 규칙을 과거 분봉에서 돌려 시뮬레이션 체결의 승률·손익비·비용을 집계하고, 그 숫자를 어디까지 읽을 수 있는지 관문으로 점검합니다. 규칙이나 종목을 권하지 않으며 주문을 내지 않습니다.";
const HERE = "/backtest/intraday";
const COVERAGE_DAYS = 31;

type Run<T> = { kind: "idle" } | { kind: "pending" } | { kind: "fail"; status: number; error: string } | { kind: "done"; value: T };

/** 두 칸일 때 결과 칸 맨 위의 문장 — 결과가 아직 없는 까닭. 실패는 실패 알림이 따로 말한다. */
const EMPTY_TEXT = {
  idle: "실행 결과가 이 자리에 나옵니다. 설정을 정하고 실행하십시오.",
  stale: "설정이 변경돼 앞의 결과를 지웠습니다. 다시 실행하십시오.",
  pending: "계산 중입니다.",
} as const;

/** 판 배치의 그리기 — 넓은 창(G5 와 같은 문턱)은 열 · 칸 · 탭, 좁은 창은 같은 상자 안 한 열로 쌓기. 끈 화면은 null. */
type WsMode = "tabs" | "stack" | null;

export function IntradayView() {
  const { session, retry } = useSession();
  const wide = useMediaQuery(SPLIT_QUERY);
  // 판 배치(G6)의 켬 · 배치 · 이름 붙인 배치는 이 브라우저에 남는다 — 작업대는 계정 확인 뒤에 서므로 서버 그림 · 수화와 어긋나지 않는다
  const ws = useWorkspace(INTRADAY_WS);
  const working = session.kind !== "loading" && session.kind !== "unknown" && session.kind !== "signed_out" && !session.mustChange;
  const wsMode: WsMode = working && ws.on ? (wide ? "tabs" : "stack") : null;
  const split = working && wide && !wsMode;
  return (
    <div className="tx-page tj itd" data-split={split ? "" : undefined} data-ws={wsMode ?? undefined}>
      <PageHead title={TITLE} lede={LEDE} />
      <ModeSwitch label="백테스트 모드" modes={BACKTEST_MODES} current={HERE} />
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
        <Workbench split={split} ws={ws} wsMode={wsMode} />
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

function Workbench({ split, ws, wsMode }: { split: boolean; ws: WorkspaceState; wsMode: WsMode }) {
  // 두 칸(G5): 설정 칸 폭 · 접힘은 이 브라우저에 남는다 · 실행하면 결과 칸을 맨 위로 · Enter 로 접으면 초점은 펴는 단추로.
  // 훅의 답은 풀어 받는다 — 묶음째 들고 그 한 칸을 `ref` 에 넘기면 React 컴파일러 린트가 묶음 전체를 ref 로 보아 렌더 중 읽기를 막는다(잰 값 · 경고 7건).
  const { pref, set: setSplit, measure, width: paneW, max: paneMaxW } = useSplitPane();
  const outRef = useRef<HTMLDivElement>(null);
  const toggleRef = useRef<HTMLButtonElement>(null);
  // 판 배치(G6): 끈 화면의 '배치' 메뉴가 처음 배치를 가르는 폭 = 작업 칸 폭(G5 의 재기는 그대로 두고 따로 잰다) · 실행하면 결과 판을 앞으로 내는 손잡이 ·
  // 배치 관리 시트(판 배치를 끄고 켜도 같은 자리에 둔다 — 가져오기가 판 배치를 켜도 시트와 그 결과 문장이 남는다).
  const [measureWork, workW] = useWorkWidth();
  const workRef = useCallback((el: HTMLDivElement | null) => { measure(el); measureWork(el); }, [measure, measureWork]);
  const wsApi = useRef<WorkspaceApi>(null);
  const [manage, setManage] = useState(false);
  // 틀 목록과 '최근 한 달의 적재 범위'는 화면을 열 때 한 번 읽는다(기간을 주지 않으면 서버가 최근 한 달을 답한다).
  const templates = useQuery({ queryKey: ["intraday", "templates"], queryFn: unwrap(getTemplates), staleTime: 0, retry: false });
  const recent = useQuery({ queryKey: ["intraday", "coverage", "recent"], queryFn: unwrap(() => getCoverage()), staleTime: 0, retry: false });
  const [edited, setForm] = useState<Form | null>(null);
  const [asked, setAsked] = useState<Run<Coverage>>({ kind: "idle" });
  const [run, setRun] = useState<Run<Sim>>({ kind: "idle" });
  const [check, setCheck] = useState<Run<Validation>>({ kind: "idle" });
  const [stale, setStale] = useState(false);
  // 실행 전 가설(G3) — 설정 밖에 둔다(시행 열쇠에 들지 않는다 · 바꿔도 결과를 지우지 않는다). 빈 글은 보내지 않는다(서버도 가설이 없는 것으로 본다).
  const [hypothesis, setHypothesis] = useState("");
  const withHypothesis = <T extends object>(body: T): T & { hypothesis?: string } => (hypothesis.trim() ? { ...body, hypothesis } : body);

  const t = templates.data ?? null;
  const start0 = useMemo(() => (t ? initialForm(t, recentPeriod(COVERAGE_DAYS)) : null), [t]);
  const form = edited ?? start0;
  const built = useMemo(() => (t && form ? build(form, t) : null), [t, form]);
  const grid = useMemo(() => (t && form ? buildGrid(form, t) : null), [t, form]);
  // 직접 구성한 조건의 검사 — 빈 칸이 없을 때만 서버에 묻는다. ★계산도 시행 기록도 없다★(같은 조건은 다시 묻지 않는다).
  const custom = t !== null && form !== null && templateOf(t, form.kind).custom;
  const toCheck = custom && built?.ruleReady ? built.request.rule : null;
  const ruleCheck = useRuleCheck(toCheck);
  const [move, setMove] = useState<Move>({ kind: "idle" });
  // 실행을 시작하면 결과 칸을 맨 위로(두 칸에서 앞 결과를 아래까지 읽던 자리에 새 결과가 묻히지 않게) · 한 열에서는 구르지 않는 칸이라 아무 일도 없다.
  useEffect(() => { if (run.kind === "pending") outRef.current?.scrollTo?.({ top: 0 }); }, [run.kind]);

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
    if (move.kind === "fail") setMove({ kind: "idle" });
    if (run.kind !== "idle" || check.kind !== "idle") { setRun({ kind: "idle" }); setCheck({ kind: "idle" }); setStale(true); }
  };
  // 서버가 거절한 조건으로는 실행하지 않는다(사유는 규칙 절에 서버 문장 그대로 뜬다).
  const problems = ruleCheck.kind === "refused" ? [...built.problems, "조건 검사에서 거절됐습니다. 규칙 절의 사유를 확인하십시오."] : built.problems;
  /** 규칙을 조건으로 풀어 편집기에 싣는다 — 틀에서 출발하기 · 내 시행에서 불러오기. 계산도 시행 기록도 없다. */
  const toCustom = async (given: SimulateRequest["rule"] | null) => {
    setMove({ kind: "pending" });
    const r = await expandRule(given ?? built.request.rule);
    if (!r.ok) { setMove({ kind: "fail", error: r.error }); return; }
    setMove({ kind: "idle" });
    change({ ...form, kind: r.value.rule.kind, custom: fromParams(r.value.rule.params), grid: { ...form.grid, rule: {} } });
  };
  const askCoverage = async () => {
    setAsked({ kind: "pending" });
    const c = await getCoverage({ from: form.from, to: form.to, tickers: parseTickers(form.tickers).slice(0, t.limits.tickers) });
    setAsked(c.ok ? { kind: "done", value: c.value } : { kind: "fail", status: c.status, error: c.error });
  };
  const start = async () => {
    if (problems.length) return;
    setRun({ kind: "pending" });
    setCheck({ kind: "idle" });
    setStale(false);
    const r = await simulate(withHypothesis(built.request));
    setRun(r.ok ? { kind: "done", value: r.value as Sim } : { kind: "fail", status: r.status, error: r.error });
  };
  const judge = async () => {
    if (problems.length || grid.problems.length) return;
    setCheck({ kind: "pending" });
    const r = await validate(withHypothesis(grid.grid ? { ...built.request, walk_forward: grid.grid } : built.request));
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
  // 두 칸에서 결과 칸이 빈 까닭(실행 전 · 설정을 바꿔 지운 뒤 · 계산 중). 실패와 결과는 그 자체가 말한다 · 한 열에서는 지금처럼 아무것도 두지 않는다.
  const empty = run.kind === "pending" ? "pending" : run.kind === "idle" ? (stale ? "stale" : "idle") : null;
  const open = pref.open;
  /** 구분선에서 Enter — 설정 칸을 접고(구분선도 숨는다) 초점을 펴는 단추로 옮긴다(숨은 요소에 초점이 남지 않게). */
  const collapse = () => {
    setSplit({ ...pref, open: false }, true);
    requestAnimationFrame(() => toggleRef.current?.focus());
  };

  // ── 화면 조각 — 기본 배치(G5 그대로)와 판 배치가 같은 조각을 그린다(같은 상태 · 같은 처리기 · 같은 클래스) ──
  const banner = synthetic ? (
    <div className="itd-banner">
      <Notice tone="practice" title="합성 분봉: 장치 확인용이며 예측력·수익의 증거가 아닙니다.">
        모의 모드에서 만든 분봉이 섞여 있습니다. 이 화면의 숫자는 계산 장치가 도는지를 확인하는 용도로만 읽으십시오.
      </Notice>
    </div>
  ) : null;
  /** 실행 단추 — 판 배치면 결과 판을 앞으로 내고 맨 위로(새 실행은 앞 결과 · 판정을 지운다 — G5 '실행하면 결과 칸을 맨 위로'와 같은 규칙). 끈 화면에는 손잡이가 없다. */
  const run_ = () => {
    if (!problems.length) wsApi.current?.reveal("result");
    void start();
  };
  const setupEl = (
    <SetupForm templates={t} form={form} onChange={change} coverage={coverage} onCoverage={() => void askCoverage()}
               problems={problems} pending={run.kind === "pending"} stale={stale} onRun={run_}
               ruleReady={built.ruleReady} check={ruleCheck} move={move} onToCustom={(rule) => void toCustom(rule)}
               hypothesis={hypothesis} onHypothesis={setHypothesis} />
  );
  const runFail = run.kind === "fail" ? <div className="tj-run-fail itd-run-fail">{fail(run, "실행 요청", () => void start())}</div> : null;
  const judgeSec = run.kind === "done" && !run.value.empty ? (
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
  ) : null;
  const verdictEl = check.kind === "done" ? <Verdict v={check.value} labels={labels} /> : null;
  // 하루 유형(T1) — 규칙 실행 · 판정과 따로 돈다(학습은 시행이 아니다). 처음 값만 규칙 설정에서 받는다.
  const dayTypeEl = <DayTypeSection tickers={form.tickers} from={form.from} to={form.to} />;
  // 시장 국면(K1) — 지수 일봉의 국면 소속 확률. 규칙 실행 · 판정과 따로 돈다(계산만 · 저장 없음). 처음 기간만 규칙 설정에서 받는다.
  const regimeEl = <MarketRegimeSection from={form.from} to={form.to} />;
  const sheet = manage ? <LayoutSheet ws={ws} onClose={() => setManage(false)} /> : null;

  if (wsMode) {
    const sim = run.kind === "done" ? run.value : null;
    /** 판이 빈 까닭 — 지어낸 내용 대신 문장 하나(실행 전 · 계산 중 · 실패 · 결과 없음). */
    const note = (text: string, state: string) => <p className="ws-empty" data-state={state}>{text}</p>;
    // 결과 판의 봉과 체결 자리 — 숫자와 그 단서를 떼지 않는다: 같은 절을 두 벌 그리지 않고 제 판을 가리킨다(닫혀 있으면 다시 연다)
    const pointer = (
      <div className="ws-elsewhere">
        <p className="ws-elsewhere-text">봉과 체결은 ‘봉과 체결’ 판에 있습니다.</p>
        <button type="button" className="tx-btn tx-btn--sub ws-elsewhere-go" onClick={() => wsApi.current?.reveal("bars", true)}>
          {ws.layout.closed.includes("bars") ? "봉과 체결 판 다시 열기" : "봉과 체결 판 보기"}
        </button>
      </div>
    );
    const panel = (id: string): ReactNode => {
      switch (id) {
        case "setup": return setupEl;
        case "result": return (
          <>
            {empty ? <p className="ws-empty" role="status" data-state={empty}>{EMPTY_TEXT[empty]}</p> : null}
            {runFail}
            {sim ? <IntradayResult sim={sim} barsSlot={pointer} /> : null}
          </>
        );
        case "bars":
          if (empty) return note(EMPTY_TEXT[empty], empty);
          if (!sim) return note("실행 요청이 실패해 그릴 하루가 없습니다.", "fail");
          if (sim.empty || !sim.journal) return note("결과가 없는 실행이라 그릴 하루가 없습니다.", "empty");
          if (sim.journal.summary.gross.n === 0) return note("청산된 거래가 없는 실행이라 봉과 체결을 그리지 않습니다.", "no_trades");
          return <BarsSection key={`bars-${sim.trial?.trial_key ?? "no-trial"}`} trialKey={sim.trial?.trial_key} />;
        case "verdict":
          if (!sim) return note("판정은 실행 결과가 나온 뒤에 할 수 있습니다.", run.kind);
          if (sim.empty) return note("결과가 없는 실행은 판정하지 않습니다.", "empty");
          return <>{judgeSec}{verdictEl}</>;
        case "daytype": return dayTypeEl;
        case "regime": return regimeEl;
        default: return null;
      }
    };
    return (
      <>
        {banner}
        <Workspace ws={ws} stacked={wsMode === "stack"} render={panel} api={wsApi} onManage={() => setManage(true)} />
        {sheet}
      </>
    );
  }

  return (
    <>
      {banner}

      {/* 작업 칸 — 한 열에서는 설정 다음에 결과가 같은 간격으로 이어지고, 두 칸에서는 [설정 | 구분선 | 결과와 분석]. 자리(null 포함)가 고정이라 창 크기를 넘나들어도 절들이 다시 생기지 않는다. */}
      <div className="itd-work" ref={workRef} data-set={split ? (open ? "open" : "closed") : undefined}
           style={split ? ({ "--itd-set-w": `${paneW}px` } as CSSProperties) : undefined}>
        <div className="itd-set" id="itd-set" role="region" aria-label="설정">
          {setupEl}
        </div>
        {split ? (
          <Splitter className="itd-split-bar" label="설정 창 폭" side="start" value={paneW} min={SET_MIN} max={paneMaxW} step={SET_STEP}
                    controls="itd-set" onChange={(w, done) => setSplit({ ...pref, w }, done)} onEnter={collapse} />
        ) : null}
        <div className="itd-out" ref={outRef} role="region" aria-label="결과와 분석">
          {split ? (
            <div className="itd-out-bar">
              <button ref={toggleRef} type="button" className="tx-btn tx-btn--sub itd-set-toggle" aria-expanded={open} aria-controls="itd-set"
                      onClick={() => setSplit({ ...pref, open: !open }, true)}>
                {open ? <PanelLeftClose size={16} aria-hidden /> : <PanelLeftOpen size={16} aria-hidden />}
                {open ? "설정 접기" : "설정 펴기"}
              </button>
              {/* 판 배치(G6) — 넓은 창에서만(한 열에는 판을 늘어놓을 폭이 없다) */}
              <LayoutMenu ws={ws} work={workW} onManage={() => setManage(true)} />
            </div>
          ) : null}
          {split && empty ? <p className="itd-out-empty" role="status" data-state={empty}>{EMPTY_TEXT[empty]}</p> : null}

          {runFail}
          {run.kind === "done" ? <IntradayResult sim={run.value} /> : null}

          {judgeSec}
          {verdictEl}

          {dayTypeEl}

          {regimeEl}
        </div>
      </div>
      {sheet}
    </>
  );
}
