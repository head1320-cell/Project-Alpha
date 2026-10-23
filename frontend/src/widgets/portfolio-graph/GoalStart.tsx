"use client";
/**
 * 목표로 시작 (BM C4 · 처음 쓰는 사람) — 무엇을 하려는지 → 종목 → 기간 → 위험 성향(BO O1)을 묻고 흐름을 조립한다
 * ==========================================================================
 * ★규칙을 새로 정하지 않는다★ — 흐름은 이미 있는 템플릿(`goalDoc`), 기간 선택지는 서버 x-ui 프리셋(수익률 노드의 `lookback_days`),
 * 위험 성향 선택지도 서버 프리셋(비중 노드의 `risk_aversion`)이다. 프리셋이 없으면 그 질문을 건너뛴다.
 * 고르지 않으면 서버 기본값. 시작하면 캔버스가 그 흐름으로 바뀌고(되돌리기로 돌아갈 수 있다) 곧바로 계산한다.
 * 네이티브 `<dialog>` — 초점 가두기·Esc 는 브라우저가.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { X } from "lucide-react";
import { fieldsOf, GOALS, parseTickers, type GoalKey, type NodeCatalogEntry } from "@/entities/portfolio-graph";
import { StockChip, TickerInput, useStockNames } from "./TickerInput";

const DEFAULT_TICKERS = "005930, 000660, 035420";

export function GoalStart({ open, onClose, catalog, onStart }: {
  open: boolean; onClose: () => void; catalog: NodeCatalogEntry[];
  onStart: (goal: GoalKey, tickers: string[], lookbackDays: number | null, riskAversion: number | null) => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [step, setStep] = useState(0);
  const [goal, setGoal] = useState<GoalKey | null>(null);
  const [text, setText] = useState(DEFAULT_TICKERS);
  const [lookback, setLookback] = useState<number | null>(null);
  const [risk, setRisk] = useState<number | null>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) { d.showModal(); setStep(0); setGoal(null); setText(DEFAULT_TICKERS); setLookback(null); setRisk(null); }
    if (!open && d.open) d.close();
  }, [open]);

  const g = GOALS.find((x) => x.key === goal);
  const parsed = parseTickers(text);
  const tickers = g?.tickers === "one" ? parsed.tickers.slice(0, 1) : parsed.tickers;
  const tickersOk = g?.tickers === "one" ? tickers.length === 1 : tickers.length >= 2;
  const names = useStockNames(step === 1 ? tickers : []);
  /** 기간 선택지 — 서버가 준 프리셋만. 없으면 이 질문을 건너뛴다(지어내지 않는다). */
  const periods = useMemo(() => {
    const f = fieldsOf(catalog.find((c) => c.type === "returns")?.params_schema ?? null).find((x) => x.name === "lookback_days");
    return (f?.ui.presets ?? []).filter((p) => typeof p.value === "number") as { label: string; value: number }[];
  }, [catalog]);
  /** 위험 성향 선택지 — 비중 노드의 서버 프리셋만(BO O1). */
  const risks = useMemo(() => {
    const f = fieldsOf(catalog.find((c) => c.type === "optimizer")?.params_schema ?? null).find((x) => x.name === "risk_aversion");
    return (f?.ui.presets ?? []).filter((p) => typeof p.value === "number") as { label: string; value: number }[];
  }, [catalog]);
  /** 이 목표가 거치는 질문 순서 — 0 목표 · 1 종목 · 2 기간 · 3 위험. 없는 질문은 건너뛴다. */
  const flow = [0, 1, ...(g?.period && periods.length ? [2] : []), ...(g?.risk && risks.length ? [3] : [])];
  const steps = flow.length;
  const pos = flow.indexOf(step);
  const next = flow[pos + 1];
  const prev = flow[pos - 1] ?? 0;
  const start = () => g && onStart(g.key, tickers, lookback, risk);
  const nav = (ok = true) => (
    <div className="pg-goal-actions">
      <button type="button" className="pg-btn pg-btn--ghost" onClick={() => setStep(prev)}>이전</button>
      {next !== undefined
        ? <button type="button" className="pg-btn pg-btn--primary pg-goal-next" disabled={!ok} onClick={() => setStep(next)}>다음</button>
        : <button type="button" className="pg-btn pg-btn--primary pg-goal-go" disabled={!ok} onClick={start}>이 흐름으로 시작</button>}
    </div>
  );

  return (
    <dialog ref={ref} className="pg-goal" aria-label="목표로 시작" onClose={onClose}
            onClick={(e) => { if (e.target === ref.current) onClose(); }}>
      <header className="pg-goal-head">
        <p className="pg-goal-step">{Math.max(pos, 0) + 1} / {goal ? steps : 4}</p>
        <button type="button" className="pg-sheet-x" aria-label="닫기" onClick={onClose}><X size={18} /></button>
      </header>
      {step === 0 && (
        <section>
          <h2 className="pg-goal-q">무엇을 해 볼까요?</h2>
          <div className="pg-goal-grid">
            {GOALS.map((x) => (
              <button key={x.key} type="button" className="pg-goal-card" data-goal={x.key} aria-pressed={goal === x.key}
                      onClick={() => { setGoal(x.key); if (x.tickers === "one") setText("005930"); setStep(1); }}>
                <b>{x.title}</b><span>{x.sub}</span>
              </button>
            ))}
          </div>
          <p className="pg-goal-foot">지금 캔버스는 되돌리기(Ctrl+Z)로 돌아갈 수 있어요.</p>
        </section>
      )}
      {step === 1 && g && (
        <section>
          <h2 className="pg-goal-q">{g.tickers === "one" ? "어느 기업을 볼까요?" : "어떤 종목으로 할까요?"}</h2>
          <label className="pg-goal-field">
            <span>{g.tickers === "one" ? "종목 코드 하나 — 또는 이름으로 찾기" : "종목 코드를 쉼표로, 또는 이름으로 찾기 — 두 개 이상"}</span>
            <TickerInput value={text} onText={setText}
                         inputProps={{ className: "pg-goal-input", autoFocus: true, "aria-describedby": "pg-goal-tickers-help" }} />
          </label>
          <div className="pg-goal-chips" aria-live="polite">
            {tickers.map((t) => <StockChip key={t} code={t} name={names[t]} className="pg-goal-chip" />)}
          </div>
          <p id="pg-goal-tickers-help" className="pg-goal-help">
            {parsed.rejected.length ? `‘${parsed.rejected.join(", ")}’은 종목 코드로 읽지 못해 뺐어요 — 이름이면 위의 후보에서 골라 주세요. ` : ""}
            {g.tickers === "one" && parsed.tickers.length > 1 ? "첫 번째 종목만 써요. " : ""}
          </p>
          {nav(tickersOk)}
        </section>
      )}
      {step === 2 && g && (
        <section>
          <h2 className="pg-goal-q">과거를 얼마나 길게 볼까요?</h2>
          <div className="pg-goal-periods" role="radiogroup" aria-label="기간">
            <button type="button" role="radio" aria-checked={lookback === null} className="pg-goal-period"
                    onClick={() => setLookback(null)}>기본값</button>
            {periods.map((p) => (
              <button key={p.value} type="button" role="radio" aria-checked={lookback === p.value} className="pg-goal-period"
                      data-days={p.value} onClick={() => setLookback(p.value)}>{p.label}</button>
            ))}
          </div>
          <p className="pg-goal-help">길수록 여러 국면이 들어가지만, 오래전 시장이 지금과 다를 수 있어요.</p>
          {nav()}
        </section>
      )}
      {step === 3 && g && (
        <section>
          <h2 className="pg-goal-q">위험을 얼마나 피할까요?</h2>
          <div className="pg-goal-periods pg-goal-risks" role="radiogroup" aria-label="위험 성향">
            <button type="button" role="radio" aria-checked={risk === null} className="pg-goal-risk"
                    onClick={() => setRisk(null)}>지금 방식 그대로</button>
            {risks.map((p) => (
              <button key={p.value} type="button" role="radio" aria-checked={risk === p.value} className="pg-goal-risk"
                      data-risk={p.value} onClick={() => setRisk(p.value)}>{p.label}</button>
            ))}
          </div>
          <p className="pg-goal-help">
            {risk === null
              ? "흐름에 들어 있는 계산 방식을 그대로 써요."
              : "‘위험 성향에 맞춰’ 방식으로 나눠요 — 많이 피할수록 흔들림이 작은 쪽, 덜 피할수록 기대 수익 쪽이에요. 세 값은 관례적인 크기라서 나에게 맞는지는 가정이에요. 나중에 설정에서 직접 정할 수 있어요."}
          </p>
          {nav()}
        </section>
      )}
    </dialog>
  );
}
