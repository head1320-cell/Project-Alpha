"use client";
/**
 * '시장 국면' 절 안의 선택 하위 절 '하루 유형 비중 더하기' — 고른 하루 유형의 20거래일 합친 비중을 국면의 셋째 특징으로 (설계 2026-11-17 §6 · 구현 계획 §7.6 · K5)
 * ==========================================================================
 * 새 화면이 아니라 같은 절 안이다(ADR 006 §7). 지수 · 국면 수 · 기간은 위의 국면 칸을 그대로 쓴다 — 바뀌면 앞의 진행과 답을 지운다.
 * ★모형 · 유형 · 바구니는 비어서 시작한다★ — 도구는 고르지 않는다. 유형은 하나 이상 · 전부는 안 된다(전부면 비중이 늘 1 이라 나눌 것이 없다 —
 * 그 안내는 서버의 거절 문장과 같다). 모형 목록은 내 모형만이고 칸에 들어갈 때마다 다시 읽는다(못 읽으면 빈 목록이 아니라 그 사유).
 *
 * 두 걸음이다:
 *  ① '비중 세기' — 서버가 한 부름의 예산 안에서 날짜 순으로 세어 남긴다. 남은 날이 있으면 화면이 이어 부른다(배경 스레드 없음 · '멈춤'으로 그친다).
 *     센 값은 유형과 무관하다(모든 유형의 이름표) — 유형을 바꿔도 다시 세지 않는다. 진행 줄의 수는 서버의 답 그대로다.
 *  ② '국면 보기' — 읽기만 하는 문 하나가 지수만의 국면(시장 국면 문의 답 그대로)과 비중을 더한 국면을 함께 준다. 덜 센 날은 더한 답에서만 미상이다.
 * 결과: 같은 날들의 두 띠(같은 부품 `RegimeBand`) · 그날 국면이 쓴 비중의 그림 · 서버 사실 줄 · 국면별 중심 · 더한 답의 사실 · 한계 문장(서버 글 그대로).
 * ★두 띠의 차이는 관측이다★ — 어느 쪽이 맞는다거나 국면을 더 맞힌다는 말을 화면이 하지 않는다. 거절은 서버 사유 그대로 · 실패는 재시도.
 */
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import {
  countDayTypeShare, getDayTypeInput, modelLabel, NO_MODELS, useDayTypeModels,
  type DayTypeCountsAnswer, type DayTypeInputAnswer, type MarketIndex, type ShareRefusal,
} from "@/entities/intraday";
import { RegimeBand, RegimeCenters, RegimeFacts, ShareStrip } from "@/features/intraday-market-regime";
import { loginHref } from "@/shared/lib/nextPath";
import { Notice, RetryFail } from "@/shared/ui/tx";

const HERE = "/backtest/intraday";
/** 서버의 거절 문장과 같은 글(`day_type_share.REFUSALS` — E2E 가 견준다). */
export const ALL_TYPES = "모든 하루 유형을 고르면 비중이 늘 1 이라 국면을 나누지 못합니다. 일부만 고르십시오.";
const NO_TYPES = "하루 유형을 하나 이상 고르십시오.";
const n = (v: number) => v.toLocaleString("ko-KR");

type Progress =
  | { kind: "idle" }
  | { kind: "running" | "stopping" | "stopped" | "done"; key: string; last: DayTypeCountsAnswer | null };
type View = { kind: "idle" } | { kind: "pending"; key: string } | { kind: "done"; key: string; value: DayTypeInputAnswer };
type Fail = { status: number; error: string; refusal: ShareRefusal | null; again: () => void };

/** 쉼표 · 빈칸으로 나눈 종목 — 앞뒤 빈칸을 걷고 겹친 것을 뺀다(순서는 넣은 그대로). 상한은 서버가 거절한다. */
export function basketOf(text: string): string[] {
  return [...new Set(text.split(/[\s,]+/).map((t) => t.trim()).filter(Boolean))];
}

export function DayTypeShareSection({ index, k, from, to, periodProblems, historyDays }: {
  index: MarketIndex; k: string; from: string; to: string; periodProblems: string[]; historyDays: number;
}) {
  const { models, note, reload } = useDayTypeModels();
  const [model, setModel] = useState("");
  const [types, setTypes] = useState<number[]>([]);
  const [basket, setBasket] = useState("");
  const [progress, setProgress] = useState<Progress>({ kind: "idle" });
  const [view, setView] = useState<View>({ kind: "idle" });
  const [fail, setFail] = useState<Fail | null>(null);
  const stop = useRef(false);
  const alive = useRef(true);
  const latest = useRef("");                 // 지금 칸의 세기 열쇠 — 칸이 바뀌면 돌던 세기는 다음 답에서 그친다(남의 입력으로 계속 세지 않는다)
  useEffect(() => () => { alive.current = false; }, []);

  const known = models?.find((m) => m.key === model) ?? null;
  const tickers = basketOf(basket);
  const allChosen = known !== null && types.length >= known.k;
  // 진행과 답은 그것을 낳은 입력에 묶는다 — 위의 칸(지수 · 기간 · 국면 수)이 바뀌면 열쇠가 달라져 앞의 것이 사라진다.
  const countKey = JSON.stringify([index, from, to, model, tickers]);
  const viewKey = JSON.stringify([index, k, from, to, model, [...types].sort((a, b) => a - b), tickers]);
  const shown = progress.kind !== "idle" && progress.key === countKey ? progress : null;
  const result = view.kind === "done" && view.key === viewKey ? view.value : null;
  const pending = view.kind === "pending" && view.key === viewKey;
  const counting = shown !== null && (shown.kind === "running" || shown.kind === "stopping");
  useEffect(() => { latest.current = countKey; }, [countKey]);

  const countProblems = [...periodProblems, ...(model ? [] : ["하루 유형 모형을 고르십시오."]), ...(tickers.length ? [] : ["바구니 종목을 넣으십시오."])];
  const runProblems = [...countProblems, ...(k ? [] : ["국면 수를 고르십시오."]), ...(types.length ? [] : [NO_TYPES])];

  const count = async () => {
    if (countProblems.length || counting) return;
    const key = countKey;
    stop.current = false;
    setFail(null);
    setProgress((p) => ({ kind: "running", key, last: p.kind !== "idle" && p.key === key ? p.last : null }));
    for (;;) {
      const r = await countDayTypeShare({ model, tickers, index, from, to });
      if (!alive.current || latest.current !== key) return;
      if (!r.ok) {
        setProgress((p) => ({ kind: "stopped", key, last: p.kind !== "idle" && p.key === key ? p.last : null }));
        setFail({ status: r.status, error: r.error, refusal: r.refusal, again: () => void count() });
        return;
      }
      if (r.value.done) return setProgress({ kind: "done", key, last: r.value });
      if (stop.current) return setProgress({ kind: "stopped", key, last: r.value });
      setProgress({ kind: "running", key, last: r.value });
    }
  };

  const run = async () => {
    if (runProblems.length || allChosen) return;
    const key = viewKey;
    setFail(null);
    setView({ kind: "pending", key });
    const r = await getDayTypeInput({ index, k: Number(k), from, to, model, types: [...types].sort((a, b) => a - b), tickers });
    if (!alive.current) return;
    if (!r.ok) {
      setView({ kind: "idle" });
      setFail({ status: r.status, error: r.error, refusal: r.refusal, again: () => void run() });
      return;
    }
    setView({ kind: "done", key, value: r.value });
  };

  const toggle = (t: number, on: boolean) => {
    setTypes((cur) => (on ? [...cur.filter((x) => x !== t), t] : cur.filter((x) => x !== t)));
    setView({ kind: "idle" });
  };

  return (
    <div className="itd-mrs">
      <h3 className="itd-mrs-title">하루 유형 비중 더하기(선택)</h3>
      <p className="itd-mrs-sub">
        고른 하루 유형이 바구니 종목의 표본 가운데 차지한 몫을 20거래일 동안 합쳐 국면의 셋째 특징으로 더합니다.
        그날의 국면은 전 거래일까지의 비중을 씁니다. 지수 · 국면 수 · 기간은 위의 칸을 그대로 씁니다.
      </p>
      <div className="itd-mrs-form">
        <div className="tj-fields itd-mrs-fields">
          <label className="tj-field"><span className="tj-label">하루 유형 모형<i className="tj-req">필수</i></span>
            <select className="tj-input itd-mrs-model" value={model} onFocus={reload}
                    onChange={(e) => { setModel(e.target.value); setTypes([]); setView({ kind: "idle" }); setFail(null); }}>
              <option value="">고르십시오</option>
              {model && !known ? <option value={model}>{model.slice(0, 8)}</option> : null}
              {(models ?? []).map((m) => <option key={m.key} value={m.key}>{modelLabel(m)}</option>)}
            </select>
          </label>
          <label className="tj-field"><span className="tj-label">바구니 종목<i className="tj-req">필수</i></span>
            <input className="tj-input itd-mrs-tickers" autoComplete="off" placeholder="예: 005930, 000660" value={basket}
                   onChange={(e) => { setBasket(e.target.value); setView({ kind: "idle" }); }} />
            <span className="itd-hint">쉼표로 나눕니다{tickers.length ? ` · ${n(tickers.length)}종목` : ""}</span>
          </label>
        </div>
        {note ? <p className="itd-why itd-mrs-models-note" role="status"><span data-server>{note}</span></p> : null}
        {models !== null && models.length === 0 ? <p className="itd-why itd-mrs-no-models" role="status">{NO_MODELS}</p> : null}
        {known ? (
          <fieldset className="itd-mrs-typeset">
            <legend className="tj-label">비중에 넣을 유형(하나 이상 · 전부는 안 됨)</legend>
            <div className="itd-mrs-types">
              {Array.from({ length: known.k }, (_, i) => i + 1).map((t) => (
                <label key={t} className="itd-mrs-type-label">
                  <input type="checkbox" className="itd-mrs-type" data-type={t} checked={types.includes(t)}
                         onChange={(e) => toggle(t, e.target.checked)} />
                  <span>유형 {t}</span>
                </label>
              ))}
            </div>
          </fieldset>
        ) : null}
        {allChosen ? <p className="itd-why itd-mrs-all" role="status">{ALL_TYPES}</p> : null}
        <p className="itd-hint itd-mrs-limits">
          {`비중 세기는 판정 시작일의 ${n(historyDays)} 달력일 앞부터 기간 안 마지막 거래일 전까지의 거래일을 셉니다. `
            + "센 값은 남아 다음에는 바뀐 날만 다시 셉니다. 유형을 바꿔도 다시 세지 않습니다."}
        </p>
        <div className="tj-run-row">
          <button type="button" className="tx-btn tx-btn--sub itd-mrs-count" disabled={countProblems.length > 0 || counting} onClick={() => void count()}>
            {counting ? "세는 중" : shown?.kind === "stopped" && shown.last && !shown.last.done ? "이어 세기" : "비중 세기"}
          </button>
          {counting ? (
            <button type="button" className="tx-btn tx-btn--sub itd-mrs-stop" disabled={shown?.kind === "stopping"}
                    onClick={() => { stop.current = true; setProgress((p) => (p.kind === "running" ? { ...p, kind: "stopping" } : p)); }}>
              멈춤
            </button>
          ) : null}
          <button type="button" className="tx-btn tx-btn--main itd-mrs-run" disabled={runProblems.length > 0 || allChosen || pending} onClick={() => void run()}>
            {pending ? "계산 중" : "국면 보기"}
          </button>
          {runProblems.length ? <ul className="tj-map-miss itd-mrs-problems">{runProblems.map((p) => <li key={p}>{p}</li>)}</ul> : null}
        </div>
        {shown ? <CountProgress p={shown} /> : null}
      </div>
      {fail ? <Failure f={fail} /> : null}
      {result ? <ShareAnswerView a={result} /> : null}
    </div>
  );
}

function CountProgress({ p }: { p: Exclude<Progress, { kind: "idle" }> }) {
  const last = p.last;
  const state = p.kind === "done" ? "다 셌습니다."
    : p.kind === "stopping" ? "멈추는 중입니다. 지금 세는 묶음이 끝나면 멈춥니다."
      : p.kind === "stopped" ? `멈췄습니다.${last && !last.done ? ` 남은 날 ${n(last.remaining_days)}일은 이어 세기로 셉니다.` : ""}`
        : `세는 중입니다.${last ? ` 남은 날 ${n(last.remaining_days)}일.` : ""}`;
  return (
    <div className="itd-mrs-progress" data-state={p.kind} data-done={p.kind === "done" ? "true" : "false"} role="status">
      {last ? (
        <>
          <progress className="itd-mrs-bar" max={Math.max(1, last.needed_days)} value={last.counted_days} aria-label="비중 세기 진행" />
          <span className="itd-mrs-progress-text">센 날 {n(last.counted_days)} / 필요한 날 {n(last.needed_days)}</span>
        </>
      ) : null}
      <span className="itd-mrs-progress-state">{state}</span>
      {last && last.stale_days ? <span className="itd-mrs-progress-stale">{`다시 셀 날 ${n(last.stale_days)}일(분봉 파일이나 장 운영 시각이 바뀐 날)`}</span> : null}
    </div>
  );
}

function ShareAnswerView({ a }: { a: DayTypeInputAnswer }) {
  const synthetic = a.mock || a.model.synthetic || a.with_share.grade === "E0" || a.share?.grade === "E0";
  const empty = a.with_share.empty ?? a.index_only.empty;
  return (
    <div className="itd-mrs-result" data-index={a.index} data-k={a.k} data-types={a.types.join(",")}>
      <p className="itd-mrs-head">
        {a.name} · 국면 {a.k}개 · <span className="itd-mr-range">{a.from} ~ {a.to}</span> · {a.types.map((t) => `유형 ${t}`).join(" · ")} · 바구니 {n(a.tickers.length)}종목
      </p>
      {synthetic ? (
        <div className="itd-mrs-synth">
          <Notice tone="warn" title="합성 자료가 섞여 있습니다.">합성 지수 일봉이나 합성 분봉으로 계산한 답입니다. 국면과 비중은 장치 확인용이며 시장에 대한 진술이 아닙니다.</Notice>
        </div>
      ) : null}
      {empty ? (
        <div className="itd-mrs-empty" data-empty={empty.reason}>
          <Notice tone="danger" title="국면을 계산하지 않았습니다."><span data-server>{empty.message}</span></Notice>
        </div>
      ) : (
        <>
          <div className="itd-mrs-bands">
            <figure className="itd-mrs-band" data-which="index_only">
              <figcaption className="itd-mrs-band-cap">지수만</figcaption>
              <RegimeBand days={a.index_only.days} k={a.k} />
            </figure>
            <figure className="itd-mrs-band" data-which="with_share">
              <figcaption className="itd-mrs-band-cap">지수 + 하루 유형 비중</figcaption>
              <RegimeBand days={a.with_share.days} k={a.k} />
            </figure>
          </div>
          {a.share ? (
            <div className="itd-mrs-sharebox">
              <p className="itd-mr-cap">그날 국면이 쓴 하루 유형 비중(전 거래일까지 20거래일)</p>
              <ShareStrip days={a.share.days} />
            </div>
          ) : null}
          <ul className="itd-mrs-facts">{a.facts.map((f, i) => <li key={i} data-server>{f}</li>)}</ul>
          {a.with_share.centers?.length ? <RegimeCenters centers={a.with_share.centers} k={a.k} /> : null}
          <div className="itd-mrs-wsfacts">
            <p className="itd-mrs-wsfacts-cap">지수 + 하루 유형 비중의 국면 사실</p>
            <RegimeFacts a={a.with_share} />
          </div>
        </>
      )}
      <ul className="itd-mrs-notes">{a.notes.map((x, i) => <li key={i} data-server>{x}</li>)}</ul>
    </div>
  );
}

function Failure({ f }: { f: Fail }) {
  return (
    <div className="itd-mrs-fail">
      {f.status === 401 ? (
        <Notice tone="danger" title="로그인 세션이 만료됐습니다.">다시 로그인하십시오. <Link href={loginHref(HERE)} className="tj-link">로그인</Link></Notice>
      ) : f.status === 400 || f.status === 404 || f.status === 422 ? (
        <Notice tone="danger" title="요청 거절"><span data-server>{f.refusal?.reason ?? f.error}</span></Notice>
      ) : (
        <RetryFail title="요청 실패" onRetry={f.again}><span data-server>{f.refusal?.reason ?? f.error}</span></RetryFail>
      )}
    </div>
  );
}
