"use client";
/**
 * 백테스트 › 분봉 규칙의 '하루 유형' 절 — 학습 · 내 모형 · 고른 모형 (설계 2026-11-16 §3 T1 · 구현 계획 §5.4)
 * ==========================================================================
 * 새 화면이 아니라 같은 화면의 절이다(ADR 006 §7). 규칙 설정 · 판정과 따로 돈다 — ★학습은 시행이 아니다★(시행 횟수를 늘리지 않는다).
 * ★도구는 유형 수를 고르지 않는다★ — 분 수(N)와 유형 수(k)는 사용자가 정하고, 화면은 서버의 상한만 보인다.
 * 기간의 처음 값은 규칙 설정 기간의 ★바로 앞 같은 길이★다 — 이 모형을 조건으로 쓰는 규칙은 학습 기간 뒤에서 돌려야 하기 때문이다.
 * 거절은 서버 사유 그대로이고, 표본이 모자랄 때는 어느 사유로 몇 표본을 뺐는지까지 보인다(세부를 버리지 않는다).
 */
import { useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import {
  getDayType, listDayTypes, trainDayTypes, type DayTypeAnswer, type DayTypeLimits, type DayTypeList, type DayTypeRefusal,
} from "@/entities/intraday";
import { DayTypeModelView } from "@/features/intraday-day-types";
import { loginHref } from "@/shared/lib/nextPath";
import { Notice, RetryFail, Section } from "@/shared/ui/tx";
import { parseTickers } from "./form";

const HERE = "/backtest/intraday";
const SUB = "장 시작 구간(첫 봉부터 정한 분 수)의 가격 경로가 닮은 표본끼리 e-means 로 묶습니다. 표본 하나는 종목 하나의 하루입니다. "
  + "묶음은 모양의 요약이며 그 뒤의 움직임이나 수익을 예측하지 않습니다. 학습은 시행으로 세지 않습니다.";

type DtForm = { tickers: string; from: string; to: string; minutes: string; k: string };
type View =
  | { kind: "idle" } | { kind: "pending" }
  | { kind: "fail"; status: number; error: string; refusal: DayTypeRefusal | null; again: () => void }
  | { kind: "done"; value: DayTypeAnswer; from: "train" | "pick" };

const ISO = /^\d{4}-\d{2}-\d{2}$/;
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/** 규칙 설정 기간의 바로 앞 같은 길이 — 읽을 수 없는 기간이면 빈칸(지어내지 않는다). */
export function precedingPeriod(from: string, to: string): { from: string; to: string } {
  if (!ISO.test(from) || !ISO.test(to) || from > to) return { from: "", to: "" };
  const a = new Date(`${from}T00:00:00`), b = new Date(`${to}T00:00:00`);
  const span = Math.round((b.getTime() - a.getTime()) / 86_400_000) + 1;
  const end = new Date(a); end.setDate(end.getDate() - 1);
  const start = new Date(end); start.setDate(start.getDate() - (span - 1));
  return { from: iso(start), to: iso(end) };
}

function problemsOf(f: DtForm, lim: DayTypeLimits | null): string[] {
  const out: string[] = [];
  const tickers = parseTickers(f.tickers);
  if (!tickers.length) out.push("종목코드를 하나 이상 넣으십시오.");
  if (lim && tickers.length > lim.tickers) out.push(`종목은 ${lim.tickers}개까지입니다.`);
  if (!ISO.test(f.from) || !ISO.test(f.to)) out.push("학습 기간의 시작일과 종료일을 넣으십시오.");
  else if (f.from > f.to) out.push("시작일이 종료일보다 늦습니다.");
  const n = Number(f.minutes), k = Number(f.k);
  if (!lim) out.push("상한을 아직 받지 못했습니다.");
  else {
    if (!Number.isInteger(n) || n < lim.minutes[0] || n > lim.minutes[1]) out.push(`분 수는 ${lim.minutes[0]} 이상 ${lim.minutes[1]} 이하의 정수여야 합니다.`);
    if (!Number.isInteger(k) || k < lim.k[0] || k > lim.k[1]) out.push(`유형 수는 ${lim.k[0]} 이상 ${lim.k[1]} 이하의 정수여야 합니다.`);
  }
  return out;
}

export function DayTypeSection({ tickers, from, to }: { tickers: string; from: string; to: string }) {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["intraday", "day-types"], queryFn: async () => {
    const r = await listDayTypes();
    if (!r.ok) throw Object.assign(new Error(r.error), { status: r.status });
    return r.value;
  }, staleTime: 0, retry: false });
  const [form, setForm] = useState<DtForm>(() => ({ tickers, ...precedingPeriod(from, to), minutes: "30", k: "6" }));
  const [view, setView] = useState<View>({ kind: "idle" });
  const lim = list.data?.limits ?? null;
  const problems = problemsOf(form, lim);
  const shownKey = view.kind === "done" ? view.value.model.key : null;

  const train = async () => {
    if (problems.length) return;
    setView({ kind: "pending" });
    const r = await trainDayTypes({ tickers: parseTickers(form.tickers), from: form.from, to: form.to,
                                    minutes: Number(form.minutes), k: Number(form.k) });
    setView(r.ok ? { kind: "done", value: r.value, from: "train" }
      : { kind: "fail", status: r.status, error: r.error, refusal: r.refusal, again: () => void train() });
    if (r.ok) void qc.invalidateQueries({ queryKey: ["intraday", "day-types"] });
  };
  const pick = async (key: string) => {
    setView({ kind: "pending" });
    const r = await getDayType(key);
    setView(r.ok ? { kind: "done", value: r.value, from: "pick" }
      : { kind: "fail", status: r.status, error: r.error, refusal: null, again: () => void pick(key) });
  };
  const set = (patch: Partial<DtForm>) => { setForm({ ...form, ...patch }); };

  return (
    <Section title="하루 유형" sub={SUB}>
      <div className="tj-map itd-dt">
        <div className="itd-dt-form">
          <label className="tj-field">
            <span className="tj-label">종목코드<i className="tj-req">필수</i></span>
            <textarea className="tj-input itd-dt-tickers" rows={2} autoComplete="off" spellCheck={false} value={form.tickers}
                      placeholder="예: 005930, 000660" onChange={(e) => set({ tickers: e.target.value })} />
          </label>
          <div className="tj-fields tj-fields--pair">
            <label className="tj-field"><span className="tj-label">학습 시작일<i className="tj-req">필수</i></span>
              <input className="tj-input itd-dt-from" type="date" value={form.from} max={form.to || undefined} onChange={(e) => set({ from: e.target.value })} /></label>
            <label className="tj-field"><span className="tj-label">학습 종료일<i className="tj-req">필수</i></span>
              <input className="tj-input itd-dt-to" type="date" value={form.to} min={form.from || undefined} onChange={(e) => set({ to: e.target.value })} /></label>
          </div>
          <div className="tj-fields tj-fields--pair">
            <label className="tj-field"><span className="tj-label">장 시작 구간(분)<i className="tj-req">필수</i></span>
              <input className="tj-input itd-dt-minutes" inputMode="numeric" autoComplete="off" value={form.minutes} onChange={(e) => set({ minutes: e.target.value })} /></label>
            <label className="tj-field"><span className="tj-label">유형 수<i className="tj-req">필수</i></span>
              <input className="tj-input itd-dt-k" inputMode="numeric" autoComplete="off" value={form.k} onChange={(e) => set({ k: e.target.value })} /></label>
          </div>
          <p className="itd-hint itd-dt-limits">
            {lim ? `분 ${lim.minutes[0]}~${lim.minutes[1]} · 유형 ${lim.k[0]}~${lim.k[1]}개 · 유형 하나에 표본 ${lim.min_samples_per_type}개 이상 · `
              + `종목 ${lim.tickers}개 · 기간 ${lim.range_days}일까지 · 학습 기간은 규칙을 판정할 기간보다 앞이어야 합니다.` : "상한을 불러오는 중"}
          </p>
          <div className="tj-run-row">
            <button type="button" className="tx-btn tx-btn--main itd-dt-train" disabled={problems.length > 0 || view.kind === "pending"} onClick={() => void train()}>
              {view.kind === "pending" ? "계산 중" : "학습"}
            </button>
            {problems.length ? <ul className="tj-map-miss itd-dt-problems">{problems.map((p) => <li key={p}>{p}</li>)}</ul> : null}
          </div>
        </div>

        <MyModels list={list} shownKey={shownKey} onPick={(key) => void pick(key)} />

        {view.kind === "fail" ? <Failure v={view} /> : null}
        {view.kind === "done" ? (
          <>
            {view.from === "train" && !view.value.created
              ? <p className="itd-dt-reused">같은 표본 · 같은 설정의 모형이 이미 있어 그 모형을 보입니다. 다시 학습하지 않았습니다.</p> : null}
            {!view.value.stored ? (
              <Notice tone="danger" title="모형을 저장하지 못했습니다.">
                <span data-server>{view.value.store_reason}</span> 이 모형은 목록에 남지 않습니다.
              </Notice>
            ) : null}
            <DayTypeModelView answer={view.value} />
          </>
        ) : null}
      </div>
    </Section>
  );
}

function MyModels({ list, shownKey, onPick }: { list: UseQueryResult<DayTypeList, Error>; shownKey: string | null; onPick: (key: string) => void }) {
  if (list.isPending) return <p className="tx-sec-sub" aria-busy="true">내 모형 불러오는 중</p>;
  if (list.isError) return <RetryFail title="내 모형 불러오기 실패" onRetry={() => void list.refetch()}><span data-server>{list.error.message}</span></RetryFail>;
  const d = list.data;
  if (!d.available) return <Notice tone="danger" title="내 모형을 읽지 못했습니다."><span data-server>{d.reason}</span></Notice>;
  return (
    <div className="itd-dt-mine">
      <h3 className="itd-dt-h">내 모형</h3>
      {d.models.length === 0 ? <p className="itd-why itd-dt-none">학습한 모형이 없습니다.</p> : (
        <ul className="itd-dt-list">
          {d.models.map((m) => (
            <li key={m.key}>
              <button type="button" className="itd-dt-pick" aria-pressed={shownKey === m.key} data-key={m.key} onClick={() => onPick(m.key)}>
                <span>{m.first_day} ~ {m.last_day}</span>
                <span>{m.tickers.join(", ")}</span>
                <span>{m.minutes}분 · 유형 {m.k}개 · 표본 {m.samples.toLocaleString("ko-KR")}개</span>
                {m.synthetic ? <span className="itd-dt-synth">합성</span> : null}
              </button>
            </li>
          ))}
        </ul>
      )}
      {d.hidden_synthetic ? <p className="itd-why itd-dt-hidden"><span data-server>{d.hidden_reason}</span> ({d.hidden_synthetic}개)</p> : null}
    </div>
  );
}

function Failure({ v }: { v: Extract<View, { kind: "fail" }> }) {
  if (v.status === 401) {
    return <Notice tone="danger" title="로그인 세션이 만료됐습니다.">다시 로그인하십시오. <Link href={loginHref(HERE)} className="tj-link">로그인</Link></Notice>;
  }
  if (v.status === 400 || v.status === 404 || v.status === 422) {
    const r = v.refusal;
    return (
      <div className="itd-dt-refused">
        <Notice tone="danger" title={v.status === 404 ? "모형 없음" : "학습 거절"}><span data-server>{v.error}</span></Notice>
        {r && typeof r.samples === "number" && typeof r.needed === "number" ? (
          <p className="itd-dt-count">쓸 수 있는 표본 {r.samples.toLocaleString("ko-KR")}개 · 필요한 표본 {r.needed.toLocaleString("ko-KR")}개</p>
        ) : null}
        {r?.excluded && r.excluded.total > 0 ? (
          <ul className="itd-dt-why">
            {Object.entries(r.excluded.by_reason).map(([code, n]) => (
              <li key={code} data-reason={code}><span data-server>{r.excluded?.messages[code] ?? code}</span> {n.toLocaleString("ko-KR")}개</li>
            ))}
          </ul>
        ) : null}
      </div>
    );
  }
  return <RetryFail title="요청 실패" onRetry={v.again}><span data-server>{v.error}</span></RetryFail>;
}
