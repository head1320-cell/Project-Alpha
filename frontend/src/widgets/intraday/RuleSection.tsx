"use client";
/**
 * 분봉 백테스트 ② 규칙 — 틀 일곱 + 직접 구성 (자유 조건식 설계 §6)
 * ==========================================================================
 * 틀을 고르면 매개변수 칸이, '직접 구성'을 고르면 조건 편집기가 뜬다. ★도구는 규칙을 추천하지 않는다★ — 조건은 사용자가 짓는다.
 * - 틀에서 출발: '이 틀을 조건으로 풀기'가 그 틀이 만드는 조건을 서버에서 받아 편집기에 싣는다(빈 화면에서 시작하지 않게).
 * - 검사: 조건을 다 채우면 서버가 검사해 규칙의 글 · 마디 수 · 거절 사유를 준다. ★검사는 시행으로 기록되지 않는다★(실행만 기록된다).
 * - 내 시행에서 불러오기: 내가 돌린 설정의 ★규칙만★ 편집기에 싣는다(종목 · 기간 · 포지션 · 비용은 건드리지 않는다).
 * 규칙의 글과 거절 사유는 서버 문장 그대로다(`data-server`).
 */
import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { listTrials, type Expanded, type SimulateRequest, type Templates } from "@/entities/intraday";
import { RuleEditor } from "@/features/intraday-rule-editor";
import { num } from "@/shared/lib/krFormat";
import { Notice, RetryFail, Section, Segmented } from "@/shared/ui/tx";
import { templateOf, withKind, type Form } from "./form";

/** 조건 검사의 상태 — 빈 칸이 있으면 묻지 않는다(`idle`). 거절(400)과 실패(그 밖)를 가른다. */
export type RuleCheck =
  | { kind: "idle" } | { kind: "pending" } | { kind: "ok"; value: Expanded }
  | { kind: "refused"; error: string } | { kind: "fail"; error: string; retry: () => void };
/** 규칙을 편집기로 옮기는 일(틀에서 풀기 · 시행에서 불러오기)의 상태. */
export type Move = { kind: "idle" } | { kind: "pending" } | { kind: "fail"; error: string };
type Rule = SimulateRequest["rule"];

const unwrap = <T,>(fn: () => Promise<{ ok: true; value: T } | { ok: false; status: number; error: string }>) => async (): Promise<T> => {
  const r = await fn();
  if (!r.ok) throw new Error(r.error);
  return r.value;
};

function CheckView({ check }: { check: RuleCheck }) {
  if (check.kind === "idle") return <p className="tj-note itd-check" data-state="idle">조건을 모두 채우면 검사 결과를 표시합니다.</p>;
  if (check.kind === "pending") return <p className="tj-note itd-check" data-state="pending" aria-busy="true">조건 검사 중</p>;
  if (check.kind === "refused") {
    return <div className="itd-check" data-state="refused"><Notice tone="danger" title="조건 검사 거절"><span data-server>{check.error}</span></Notice></div>;
  }
  if (check.kind === "fail") {
    return <div className="itd-check" data-state="fail"><RetryFail title="조건 검사 실패" onRetry={check.retry}><span data-server>{check.error}</span></RetryFail></div>;
  }
  const v = check.value;
  return (
    <div className="itd-check" data-state="ok" aria-live="polite">
      <p className="tj-read itd-rule-text" data-server>{v.text}</p>
      <p className="itd-hint itd-rule-size">마디 {num(v.nodes)}/{num(v.limits.nodes)} · 겹침 깊이 {num(v.depth)}/{num(v.limits.depth)}</p>
    </div>
  );
}

function TrialLoader({ onLoad, busy }: { onLoad: (rule: Rule) => void; busy: boolean }) {
  const [open, setOpen] = useState(false);
  const list = useQuery({ queryKey: ["intraday", "trials"], queryFn: unwrap(listTrials), enabled: open, staleTime: 0, retry: false });
  const rows = list.data?.available ? list.data.trials : [];
  return (
    <div className="itd-load">
      <div className="tj-run-row">
        <button type="button" className="tx-btn tx-btn--sub itd-load-btn" aria-expanded={open} disabled={busy} onClick={() => setOpen(!open)}>내 시행에서 불러오기</button>
        <p className="tj-note">규칙만 불러옵니다. 종목 · 기간 · 포지션 · 비용 설정은 변경하지 않습니다.</p>
      </div>
      {open && list.isPending ? <p className="tx-sec-sub" aria-busy="true">시행 목록 조회 중</p> : null}
      {open && list.isError ? <RetryFail title="시행 목록 조회 실패" onRetry={() => void list.refetch()}><span data-server>{list.error.message}</span></RetryFail> : null}
      {open && list.data && !list.data.available ? <Notice tone="warn" title="시행 목록을 읽지 못했습니다."><span data-server>{list.data.reason}</span></Notice> : null}
      {open && list.data?.available && rows.length === 0 ? <p className="tj-note itd-load-none">기록된 시행이 없습니다. 규칙을 한 번 실행하면 여기에 표시됩니다.</p> : null}
      {open && rows.length ? (
        <ul className="itd-load-list">
          {rows.map((r) => (
            <li key={r.trial_key}>
              <button type="button" className="itd-load-row" disabled={busy} onClick={() => { onLoad(r.request.rule); setOpen(false); }}>
                <b>{r.rule_label ?? r.request.rule.kind}</b>
                <span className="itd-load-text" data-server>{r.rule_text ?? r.rule_text_reason ?? ""}</span>
                <span className="itd-hint">{r.request.tickers.slice(0, 3).join(", ")}{r.request.tickers.length > 3 ? ` 외 ${num(r.request.tickers.length - 3)}종목` : ""} · {r.request.from} ~ {r.request.to} · {num(r.runs)}회 실행</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export function RuleSection({ templates: t, form, onChange, params, ruleReady, check, move, onToCustom }: {
  templates: Templates; form: Form; onChange: (next: Form) => void;
  /** 틀의 매개변수 칸 — 설정 화면이 다른 칸과 같은 부품으로 그려 넘긴다. */
  params: ReactNode;
  ruleReady: boolean; check: RuleCheck; move: Move;
  /** 규칙을 조건으로 풀어 편집기에 싣는다 — `null` 이면 지금 고른 틀과 매개변수다. */
  onToCustom: (rule: Rule | null) => void;
}) {
  const template = templateOf(t, form.kind);
  const extra = check.kind === "ok" ? check.value.notes.filter((n) => !template.notes.includes(n)) : [];
  const needsPrev = template.needs_prev === true || (template.custom && check.kind === "ok" && check.value.needs_prev);
  return (
    <Section title="규칙" sub="규칙 틀과 매개변수를 정하거나 조건을 직접 구성합니다. 신호는 봉 종가까지의 값으로 계산하고 다음 봉 시가에 체결합니다.">
      <div className="tj-map itd-rule">
        <div className="itd-kinds">
          <Segmented label="규칙 틀" options={t.templates.map((x) => ({ value: x.kind, label: x.label }))} value={form.kind}
                     onChange={(kind) => onChange(withKind(form, t, kind))} />
        </div>
        <p className="tj-read itd-rule-summary" data-server>{template.summary}</p>
        {template.custom ? (
          <>
            <RuleEditor grammar={t.grammar} value={form.custom} onChange={(custom) => onChange({ ...form, custom })} />
            <CheckView check={check} />
            <TrialLoader onLoad={onToCustom} busy={move.kind === "pending"} />
          </>
        ) : (
          <>
            <div className="tj-fields itd-params">{params}</div>
            <div className="tj-run-row itd-expand-row">
              <button type="button" className="tx-btn tx-btn--sub itd-expand" disabled={!ruleReady || move.kind === "pending"} onClick={() => onToCustom(null)}>
                {move.kind === "pending" ? "조건으로 푸는 중" : "이 틀을 조건으로 풀기"}
              </button>
              <p className="tj-note">이 틀이 만드는 조건을 ‘직접 구성’으로 옮겨 수정할 수 있습니다. 옮긴 규칙은 틀과 다른 시행으로 기록됩니다.</p>
            </div>
          </>
        )}
        {move.kind === "fail" ? <div className="itd-move-fail"><Notice tone="danger" title="조건으로 풀기 거절"><span data-server>{move.error}</span></Notice></div> : null}
        {template.notes.length || extra.length ? (
          <ul className="tj-plain-list itd-notes">{[...template.notes, ...extra].map((n) => <li key={n} data-server>{n}</li>)}</ul>
        ) : null}
        {needsPrev ? <p className="tj-note itd-needs-prev">전일 값은 앞선 적재일의 분봉에서 얻습니다. 닷새 안에 적재된 날이 없는 종목·일자는 건너뜁니다.</p> : null}
      </div>
    </Section>
  );
}
