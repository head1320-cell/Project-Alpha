"use client";
/**
 * 한 장에게 묻기 (CF 3부 PB4 PB 미리 묻기 · PB6 고객 AI 가 같은 것을 쓴다) — ★서버가 검사한 문장만★ 그린다.
 * ==========================================================================
 * 문장마다 기댄 사실 줄을 칩('사실 N' — 누르면 그 줄)으로 · 답할 수 없으면 서버 고정 문장 그대로 · 못 물으면(키·한도) 사유 그대로.
 * 직전 문답 하나만 함께 보낸다(AI3 와 같은 결정). 묻는 길(`ask`)은 부르는 화면이 정한다 — PB 는 로그인 경로, 고객은 고객 세션 경로.
 */
import { useState, type FormEvent } from "react";
import type { Result } from "@/shared/api/result";
import type { SheetAnswer } from "./api";

export function SheetAsk({ ask, title, sub }: {
  ask: (q: string, prev: { question: string; answer: string } | null) => Promise<Result<SheetAnswer>>;
  title: string; sub: string;
}) {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [last, setLast] = useState<{ question: string; reply: SheetAnswer } | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const question = q.trim();
    if (!question || busy) return;
    setBusy(true);
    setErr(null);
    const prev = last?.reply.available && last.reply.answer
      ? { question: last.question, answer: last.reply.answer.sentences.map((s) => s.text).join(" ") } : null;
    const r = await ask(question, prev);
    setBusy(false);
    if (!r.ok) { setErr(r.error); return; }
    setLast({ question, reply: r.value });
    setOpen(null);
  }

  const reply = last?.reply;
  return (
    <section className="cs-ask" aria-label={title}>
      <h2 className="cs-h2">{title}</h2>
      <p className="cs-sub">{sub}</p>
      <form className="cs-ask-form" onSubmit={submit}>
        <input className="cs-ask-input" value={q} maxLength={300} placeholder="예: 가장 큰 비중은 어느 종목이에요?"
               aria-label="질문" onChange={(e) => setQ(e.target.value)} />
        <button type="submit" className="tx-btn tx-btn--main cs-ask-go" disabled={busy || !q.trim()}>{busy ? "묻는 중" : "묻기"}</button>
      </form>
      {err && <p className="cs-ask-err" role="alert">{err}</p>}
      {reply && !reply.available && <p className="cs-ask-unavailable" role="status">지금은 답할 수 없어요 — {reply.reason}</p>}
      {reply?.available && reply.answer && (
        <div className="cs-ask-reply" aria-live="polite">
          <p className="cs-ask-q">{last!.question}</p>
          {reply.answer.sentences.length > 0 && (
            <div className="cs-ask-answer">
              {reply.answer.sentences.map((s, i) => (
                <p key={i}>
                  {s.text}{" "}
                  {s.fact_ids.map((f) => (
                    <button key={f} type="button" className="cs-ask-fact" aria-expanded={open === f} onClick={() => setOpen(open === f ? null : f)}>
                      사실 {f.replace(/^f/, "")}
                    </button>
                  ))}
                </p>
              ))}
            </div>
          )}
          {open && reply.facts?.[open] && (
            <p className="cs-ask-line">{reply.facts[open].where ? `${reply.facts[open].where} · ` : ""}{reply.facts[open].part} — {reply.facts[open].text}</p>
          )}
          {!reply.answer.answerable && reply.answer.cannot && <p className="cs-ask-cannot">{reply.answer.cannot}</p>}
          {reply.notice && <p className="cs-ask-notice">{reply.notice}</p>}
        </div>
      )}
    </section>
  );
}
