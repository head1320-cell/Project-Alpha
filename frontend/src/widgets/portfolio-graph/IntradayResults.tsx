"use client";
/**
 * 분봉 백테스트 노드 둘의 결과 — 설정(요청 요약) · 결과 조회(판정 요약)
 * ==========================================================================
 * 설계 `docs/superpowers/specs/2026-11-14-canvas-intraday-nodes-design.md` §7.2
 * 실행은 단추, 읽기는 노드다. 결과 판은 화면(백테스트 › 분봉 규칙)과 ★같은 판정 부품★(`features/intraday-verdict`)을 쓴다 —
 * 관문 일곱의 상태와 사유는 서버 값 그대로이고 종합 점수를 만들지 않는다. 합성 분봉이면 맨 위에 적는다.
 * 여기서 새 수를 만들지 않는다 — 고르고 서식만 입힌다. 미상은 0 이 아니라 N/A 다.
 */
import type { ReactNode } from "react";
import type { Breakeven, Brief, Validation } from "@/entities/intraday";
import { Verdict, bp1 } from "@/features/intraday-verdict";
import { UNKNOWN_TEXT, num, signedWon } from "@/shared/lib/krFormat";
import { Notice } from "@/shared/ui/tx";

type Dict = Record<string, unknown>;
const dict = (v: unknown): Dict => (v && typeof v === "object" ? (v as Dict) : {});
const count = (v: unknown, unit: string): string => (typeof v === "number" && Number.isFinite(v) ? `${num(v)}${unit}` : UNKNOWN_TEXT);

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
        ["종목", `${num(tickers.length)}개${v.tickers_from === "universe" ? " · 연결한 종목 묶음" : ""}`],
        ["기간", `${String(r.from)} ~ ${String(r.to)}`],
        ["분봉이 적재된 날", `달력 ${count(days.calendar, "일")} 가운데 ${count(days.loaded, "일")}`],
        ["수수료율(편도)", typeof fee === "number" ? bp1(fee) : "미상"],
        ["계산량", `${count(work.total, "")} · 상한 ${count(work.limit, "")}`],
      ]} />
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

export function IntradayLoadResult({ v }: { v: Dict }) {
  const view = v as unknown as Validation & { trial_key: string; result_at: number; runs: number };
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
        ["종목 · 기간", `${num(tickers.length)}개 · ${String(r.from)} ~ ${String(r.to)}`],
        ["거래", s ? `${num(s.trades)}건` : UNKNOWN_TEXT],
        ["비용 전 실현손익", <span key="g" className="pg-itd-gross">{signedWon(s?.gross_total ?? null)}</span>],
        ["비용 후 실현손익", <span key="n" className="pg-itd-net">{signedWon(s?.net_total ?? null)}</span>],
        ["손익분기 편도 비용", <span key="b" className="pg-itd-breakeven">{bp1(b?.bp)}</span>],
        ["실제로 든 편도 비용", bp1(b?.spent_bp)],
        ["건너뛴 종목·일", skipped === null ? UNKNOWN_TEXT : `${num(skipped)}건`],
        ["실행", <span key="t" className="pg-itd-when">{stamp(view.result_at)} · 같은 설정 {count(view.runs, "회째")}</span>],
      ]} />
      <p className="pg-note">실행할 때 남긴 요약입니다. 다시 계산하지 않았고, 시행 횟수는 그때의 값입니다. 거래 목록과 손익 곡선은 ‘백테스트 › 분봉 규칙’ 화면에서 확인합니다.</p>
      <p className="pg-itd-h">이 실행의 관문 일곱</p>
      <Verdict v={view} labels={{}} />
    </div>
  );
}
