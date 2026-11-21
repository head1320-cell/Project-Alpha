"use client";
/**
 * 분봉 백테스트 노드의 결과 — 설정(요청 요약) · 결과 조회(판정 요약) · 가동 요청(무엇을 요청하는지)
 * ==========================================================================
 * 설계 `docs/superpowers/specs/2026-11-14-canvas-intraday-nodes-design.md` §7.2
 * 실행은 단추, 읽기는 노드다. 결과 판은 화면(백테스트 › 분봉 규칙)과 ★같은 판정 부품★(`features/intraday-verdict`)을 쓴다 —
 * 관문 일곱의 상태와 사유는 서버 값 그대로이고 종합 점수를 만들지 않는다. 합성 분봉이면 맨 위에 적는다.
 * 여기서 새 수를 만들지 않는다 — 고르고 서식만 입힌다. 미상은 0 이 아니라 N/A 다.
 */
import Link from "next/link";
import type { ReactNode } from "react";
import type { Breakeven, Brief, Validation } from "@/entities/intraday";
import { ContextFacts, factsOf } from "@/features/intraday-day-types";
import { RegimeSplitBlock } from "@/features/intraday-regime-split";
import { Verdict, bp1 } from "@/features/intraday-verdict";
import { UNKNOWN_TEXT, num, signedWon } from "@/shared/lib/krFormat";
import { Notice } from "@/shared/ui/tx";

type Dict = Record<string, unknown>;
const dict = (v: unknown): Dict => (v && typeof v === "object" ? (v as Dict) : {});
const count = (v: unknown, unit: string): string => (typeof v === "number" && Number.isFinite(v) ? `${num(v)}${unit}` : UNKNOWN_TEXT);

/** 규칙을 풀어 쓴 글 — 서버가 낸 글 그대로. 못 읽었으면 그 사유, 둘 다 없으면 미상. */
const ruleText = (v: Dict): ReactNode => {
  const said = typeof v.rule_text === "string" ? v.rule_text : typeof v.rule_text_reason === "string" ? v.rule_text_reason : null;
  return <span key="rt" className="pg-itd-rule-text" data-known={String(typeof v.rule_text === "string")} data-server>{said ?? UNKNOWN_TEXT}</span>;
};

function KV({ rows }: { rows: [string, ReactNode][] }) {
  return <dl className="pg-kv">{rows.map(([k, v]) => (<div key={k}><dt>{k}</dt><dd>{v}</dd></div>))}</dl>;
}

// ── 설정 ─────────────────────────────────────────────────────────────────────

export function IntradaySetupResult({ v }: { v: Dict }) {
  const r = dict(v.request), days = dict(v.days), work = dict(v.work), costs = dict(r.costs);
  const tickers = Array.isArray(r.tickers) ? r.tickers.map(String) : [];
  const fee = costs.commission_bp;
  return (
    <div className="pg-itd pg-itd-setup">
      <KV rows={[
        ["규칙 틀", String(v.rule_label ?? UNKNOWN_TEXT)],
        ["규칙", ruleText(v)],
        ["종목", `${num(tickers.length)}개${v.tickers_from === "universe" ? " · 연결한 종목 묶음" : ""}`],
        ["기간", `${String(r.from)} ~ ${String(r.to)}`],
        ["분봉이 적재된 날", `달력 ${count(days.calendar, "일")} 가운데 ${count(days.loaded, "일")}`],
        ["수수료율(편도)", typeof fee === "number" ? bp1(fee) : "미상"],
        ["계산량", `${count(work.total, "")} · 상한 ${count(work.limit, "")}`],
      ]} />
      <ContextFacts facts={factsOf(v.context)} />
      {days.loaded === 0 ? <p className="pg-note pg-itd-none">이 기간에 적재된 분봉이 없습니다. 실행하면 결과 없이 사유만 남습니다.</p> : null}
      <p className="pg-note">아직 실행하지 않았습니다. 설정 탭의 ‘분봉 백테스트 실행’을 누르면 계산하고, 실행마다 시행으로 기록합니다.</p>
    </div>
  );
}

// ── 결과 조회 ───────────────────────────────────────────────────────────────────

const stamp = (sec: unknown): string =>
  (typeof sec === "number" && Number.isFinite(sec)
    ? new Date(sec * 1000).toLocaleString("ko-KR", { year: "numeric", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })
    : UNKNOWN_TEXT);

/** 결과 조회 판에서 묻는 국면 나눔(K2c) — 화면의 절과 같은 부품 · 같은 문 · 이 노드의 시행 열쇠. 열쇠가 없는 답이면 이 문장을 보이고 묻지 않는다. */
const NO_TRIAL_KEY = "이 결과가 어느 시행의 것인지 적혀 있지 않아 국면별로 나눌 수 없습니다.";

export function IntradayLoadResult({ v }: { v: Dict }) {
  const view = v as unknown as Validation & { trial_key?: string | null; result_at: number; runs: number };
  const s: Brief | null = view.summary ?? null;
  const b: Breakeven | null = view.breakeven ?? null;
  const r = dict(v.request), data = dict(v.data);
  const tickers = Array.isArray(r.tickers) ? r.tickers.map(String) : [];
  const skipped = typeof data.skipped_total === "number" ? data.skipped_total : null;
  return (
    <div className="pg-itd pg-itd-load" data-grade={view.origin?.grade ?? "unknown"}>
      {view.origin?.grade === "E0" ? (
        <Notice tone="practice" title="합성 분봉 위의 결과입니다.">
          계산 장치를 확인하는 용도이며 예측력이나 수익의 증거가 아닙니다.
        </Notice>
      ) : null}
      <KV rows={[
        ["규칙 틀", <span key="k" data-server>{view.template?.label ?? UNKNOWN_TEXT}</span>],
        ["규칙", ruleText(v)],
        ["종목 · 기간", `${num(tickers.length)}개 · ${String(r.from)} ~ ${String(r.to)}`],
        ["거래", s ? `${num(s.trades)}건` : UNKNOWN_TEXT],
        ["비용 전 실현손익", <span key="g" className="pg-itd-gross">{signedWon(s?.gross_total ?? null)}</span>],
        ["비용 후 실현손익", <span key="n" className="pg-itd-net">{signedWon(s?.net_total ?? null)}</span>],
        ["손익분기 편도 비용", <span key="b" className="pg-itd-breakeven">{bp1(b?.bp)}</span>],
        ["실제로 든 편도 비용", bp1(b?.spent_bp)],
        ["건너뛴 종목·일", skipped === null ? UNKNOWN_TEXT : `${num(skipped)}건`],
        ["실행", <span key="t" className="pg-itd-when">{stamp(view.result_at)} · 같은 설정 {count(view.runs, "회째")}</span>],
      ]} />
      <ContextFacts facts={factsOf(v.context)} />
      <p className="pg-note">실행할 때 남긴 요약입니다. 다시 계산하지 않았고, 시행 횟수는 그때의 값입니다. 거래 목록과 손익 곡선은 ‘백테스트 › 분봉 규칙’ 화면에서 확인합니다.</p>
      <p className="pg-itd-h">이 실행의 관문 일곱</p>
      <Verdict v={view} labels={{}} />
      {/* ★단추로만 묻는다★(캔버스 규칙 6 — 그래프 계산은 이 문을 부르지 않는다) · 다른 결과 노드를 고르면 `key` 가 앞의 답과 고른 칸을 지운다 */}
      <div className="pg-itd-rs">
        <RegimeSplitBlock key={view.trial_key ?? "no-trial"} trialKey={view.trial_key} level={3} missing={NO_TRIAL_KEY} narrow />
      </div>
    </div>
  );
}

// ── 가동 요청 (W5b) ─────────────────────────────────────────────────────────────

/** 요청 상태 — 서버의 세 값(남김 · 남기지 않음 · 미상)을 그대로 말한다. 못 읽음을 '없음'으로 접지 않는다. */
const REQUESTED: Record<string, string> = { true: "이미 남김", false: "남기지 않음", unknown: "미상 · 요청 기록을 읽지 못함" };

/**
 * ★요청은 가동이 아니다★ — 이 판은 무엇을 요청하게 되는지만 보인다(규칙 · 종목 · 기간 · 관문 수 · 요청 상태).
 * 가동 · 정지 · 비상 정지는 내 계좌에서만 한다. 관문은 표시만 한다(가동을 차단하지 않는다 — 설계 §12 D3).
 */
export function IntradayArmResult({ v }: { v: Dict }) {
  const tickers = Array.isArray(v.tickers) ? v.tickers.map(String) : [];
  const gates = dict(v.gates), counts = dict(gates.counts);
  const state = v.requested === true ? "true" : v.requested === false ? "false" : "unknown";
  const rows: [string, ReactNode][] = [
    ["규칙 틀", <span key="k" data-server>{String(v.rule_label ?? UNKNOWN_TEXT)}</span>],
    ["규칙", ruleText(v)],
    ["종목 · 기간", `${num(tickers.length)}개 · ${String(v.from)} ~ ${String(v.to)}`],
    ["같은 설정 실행", count(v.runs, "회")],
    ["관문 일곱", <span key="g" className="pg-itd-gates">{gates.known === true
      ? `통과 ${count(counts.ok, "")} · 미달 ${count(counts.degraded, "")} · 미상 ${count(counts.unknown, "")}` : "미상 · 판정 결과 없음"}</span>],
    ["요청 상태", <span key="s" className="pg-itd-state" data-requested={state}>{REQUESTED[state]}</span>],
  ];
  if (typeof v.note === "string" && v.note) rows.push(["메모", <span key="n" className="pg-itd-memo">{v.note}</span>]);
  return (
    <div className="pg-itd pg-itd-arm" data-requested={state} data-grade={typeof v.grade === "string" ? v.grade : "unknown"}>
      {v.synthetic === true ? (
        <Notice tone="practice" title="합성 분봉으로 실행한 설정입니다.">
          계산 장치를 확인하는 용도이며 예측력이나 수익의 증거가 아닙니다.
        </Notice>
      ) : null}
      <KV rows={rows} />
      <p className="pg-note">요청은 가동이 아닙니다. 설정 탭의 ‘가동 요청 남기기’는 요청 한 줄만 남기며, 가동 · 정지 · 비상 정지는 ‘내 계좌 › 규칙 가동’에서 직접 합니다.</p>
      <p className="pg-note">가동은 기록 전용 모드에서만 시작하며 증권사로 주문을 전송하지 않습니다. 관문은 표시만 하며 가동을 차단하지 않습니다.</p>
      <Link className="pg-itd-go" href="/my-account">내 계좌 › 규칙 가동</Link>
    </div>
  );
}
