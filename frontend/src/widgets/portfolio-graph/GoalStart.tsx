"use client";
/**
 * 목표로 시작 (BM C4 · 처음 쓰는 사람) — 무엇을 하려는지 → 종목 → 기간, 세 번 묻고 흐름을 조립한다
 * ==========================================================================
 * ★규칙을 새로 정하지 않는다★ — 흐름은 이미 있는 템플릿(`goalDoc`), 기간 선택지는 서버 x-ui 프리셋(수익률 노드의 `lookback_days`).
 * 고르지 않으면 서버 기본값. 시작하면 캔버스가 그 흐름으로 바뀌고(되돌리기로 돌아갈 수 있다) 곧바로 계산한다.
 * 네이티브 `<dialog>` — 초점 가두기·Esc 는 브라우저가.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { X } from "lucide-react";
import { fieldsOf, GOALS, parseTickers, type GoalKey, type NodeCatalogEntry } from "@/entities/portfolio-graph";

const DEFAULT_TICKERS = "005930, 000660, 035420";

export function GoalStart({ open, onClose, catalog, onStart }: {
  open: boolean; onClose: () => void; catalog: NodeCatalogEntry[];
  onStart: (goal: GoalKey, tickers: string[], lookbackDays: number | null) => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [step, setStep] = useState(0);
  const [goal, setGoal] = useState<GoalKey | null>(null);
  const [text, setText] = useState(DEFAULT_TICKERS);
  const [lookback, setLookback] = useState<number | null>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) { d.showModal(); setStep(0); setGoal(null); setText(DEFAULT_TICKERS); setLookback(null); }
    if (!open && d.open) d.close();
  }, [open]);

  const g = GOALS.find((x) => x.key === goal);
  const parsed = parseTickers(text);
  const tickers = g?.tickers === "one" ? parsed.tickers.slice(0, 1) : parsed.tickers;
  const tickersOk = g?.tickers === "one" ? tickers.length === 1 : tickers.length >= 2;
  /** 기간 선택지 — 서버가 준 프리셋만. 없으면 이 질문을 건너뛴다(지어내지 않는다). */
  const periods = useMemo(() => {
    const f = fieldsOf(catalog.find((c) => c.type === "returns")?.params_schema ?? null).find((x) => x.name === "lookback_days");
    return (f?.ui.presets ?? []).filter((p) => typeof p.value === "number") as { label: string; value: number }[];
  }, [catalog]);
  const steps = g?.period && periods.length ? 3 : 2;

  return (
    <dialog ref={ref} className="pg-goal" aria-label="목표로 시작" onClose={onClose}
            onClick={(e) => { if (e.target === ref.current) onClose(); }}>
      <header className="pg-goal-head">
        <p className="pg-goal-step">{step + 1} / {goal ? steps : 3}</p>
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
            <span>{g.tickers === "one" ? "종목 코드 하나" : "종목 코드를 쉼표로 — 두 개 이상"}</span>
            <input className="pg-goal-input" value={text} onChange={(e) => setText(e.target.value)} autoFocus
                   aria-describedby="pg-goal-tickers-help" />
          </label>
          <div className="pg-goal-chips" aria-live="polite">
            {tickers.map((t) => <span key={t} className="pg-goal-chip">{t}</span>)}
          </div>
          <p id="pg-goal-tickers-help" className="pg-goal-help">
            {parsed.rejected.length ? `‘${parsed.rejected.join(", ")}’은 종목 코드로 읽지 못해 뺐어요. ` : ""}
            {g.tickers === "one" && parsed.tickers.length > 1 ? "첫 번째 종목만 써요. " : ""}
            종목 이름은 계산하면 이야기 탭에 나와요.
          </p>
          <div className="pg-goal-actions">
            <button type="button" className="pg-btn pg-btn--ghost" onClick={() => setStep(0)}>이전</button>
            {steps === 3
              ? <button type="button" className="pg-btn pg-btn--primary pg-goal-next" disabled={!tickersOk} onClick={() => setStep(2)}>다음</button>
              : <button type="button" className="pg-btn pg-btn--primary pg-goal-go" disabled={!tickersOk}
                        onClick={() => onStart(g.key, tickers, null)}>이 흐름으로 시작</button>}
          </div>
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
          <div className="pg-goal-actions">
            <button type="button" className="pg-btn pg-btn--ghost" onClick={() => setStep(1)}>이전</button>
            <button type="button" className="pg-btn pg-btn--primary pg-goal-go" onClick={() => onStart(g.key, tickers, lookback)}>
              이 흐름으로 시작
            </button>
          </div>
        </section>
      )}
    </dialog>
  );
}
