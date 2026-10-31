"use client";
/**
 * 고객 한 장 (CF 3부 PB4 · PB6 고객 화면이 같은 것을 쓴다) — ★서버가 다시 계산해 옮긴 한 장을 그리기만 한다★.
 * ==========================================================================
 * 숫자는 한 장 JSON 의 것 그대로(비중 막대의 폭은 그 % 를 그대로 쓴 그림일 뿐 — 새 숫자를 쓰지 않는다). 계산 못 한 단계도 빠지지 않고
 * '계산 못 함 + 사유'. '몰라요'·'가정' 은 숨기지 않는다. 연습용(합성) 데이터면 맨 위 띠. 인쇄하면 한 장만(도구·메뉴는 인쇄 CSS 가 숨긴다).
 * 단계 묶음은 노드 종류로만 가른다 — 고객·계좌·목표 / 이번 점검의 결정 / 어떻게 만들었나(그 밖). 묶음은 읽는 순서일 뿐 판단이 아니다.
 */
import type { Sheet, SheetStep, SheetTrust } from "./api";

const CLIENT_KINDS = new Set(["client_profile", "account", "goal", "holdings_check"]);
const DECISION_KINDS = new Set(["rebalance_decision", "order_preview", "target_version", "decision_journal"]);
const TRUST: Record<string, string> = { confirmed: "확인", assumed: "가정", unknown: "몰라요", failed: "실패" };

const day = (iso: string) => iso.slice(0, 10);

function Step({ s }: { s: SheetStep }) {
  const ex = s.explain;
  return (
    <li className="cs-step" data-status={s.status} data-node-id={s.node_id}>
      <p className="cs-step-name">{s.label}</p>
      {ex ? (
        <>
          {ex.title && <p className="cs-step-title">{ex.title}</p>}
          {ex.headline?.text && <p className="cs-step-head">{ex.headline.label ? `${ex.headline.label}: ` : ""}{ex.headline.text}</p>}
          {(ex.facts ?? []).length > 0 && <ul className="cs-facts">{ex.facts!.map((f, i) => <li key={i}>{f}</li>)}</ul>}
        </>
      ) : (
        <p className="cs-step-failed">{s.status === "blocked" ? "앞 단계 때문에 계산하지 못했어요" : "계산하지 못했어요"} — {s.reason}</p>
      )}
    </li>
  );
}

function Steps({ title, steps }: { title: string; steps: SheetStep[] }) {
  if (!steps.length) return null;
  return (
    <section className="cs-sec">
      <h2 className="cs-h2">{title}</h2>
      <ol className="cs-steps">{steps.map((s) => <Step key={s.node_id} s={s} />)}</ol>
    </section>
  );
}

/** `audience` — PB 화면은 "노드" 를 말해도 되지만 고객 화면(PB6 `/c`)에서는 중립 문장으로. 숫자·단계는 같다. */
export function ClientSheet({ sheet, audience = "pb" }: { sheet: Sheet; audience?: "pb" | "client" }) {
  const client = sheet.steps.filter((s) => CLIENT_KINDS.has(String(s.type)));
  const decide = sheet.steps.filter((s) => DECISION_KINDS.has(String(s.type)));
  const build = sheet.steps.filter((s) => !CLIENT_KINDS.has(String(s.type)) && !DECISION_KINDS.has(String(s.type)));
  const trust: { where: string; t: SheetTrust }[] = sheet.steps.flatMap((s) => (s.explain?.trust ?? []).map((t) => ({ where: s.label, t })));
  const unmeasured: { where: string; u: string }[] = sheet.steps.flatMap((s) => (s.explain?.unmeasured ?? []).map((u) => ({ where: s.label, u })));
  return (
    <article className="cs-sheet" aria-label={sheet.title}>
      <header className="cs-head">
        <h1 className="cs-title">{sheet.title}</h1>
        <p className="cs-meta"><span className="cs-alias">{sheet.client_alias}</span> · 계산한 날 {day(sheet.computed_at)}</p>
      </header>
      {sheet.practice && <p className="cs-practice" role="note">{sheet.practice_note}</p>}
      <section className="cs-sec cs-weights-sec">
        <h2 className="cs-h2">내 포트폴리오 비중</h2>
        <p className="cs-sub">{audience === "client" ? "이번 점검에서 정한 비중이에요." : `${sheet.focus.label} 노드가 정한 비중이에요.`}</p>
        <ol className="cs-weights">
          {sheet.focus.weights.map((w) => (
            <li key={w.code} className="cs-weight" data-code={w.code}>
              <span className="cs-weight-name">{w.name}<span className="cs-weight-code">{w.code}</span></span>
              <span className="cs-weight-bar" aria-hidden="true"><span style={{ width: `${Math.max(0, Math.min(100, w.pct))}%` }} /></span>
              <span className="cs-weight-pct">{w.pct}%</span>
            </li>
          ))}
        </ol>
      </section>
      <Steps title="고객·계좌·목표" steps={client} />
      <Steps title="어떻게 만들었나" steps={build} />
      <Steps title="이번 점검의 결정" steps={decide} />
      {trust.length > 0 && (
        <section className="cs-sec">
          <h2 className="cs-h2">믿어도 되나</h2>
          <ul className="cs-trust">
            {trust.map(({ where, t }, i) => (
              <li key={i} data-state={t.state}><span className="cs-tag">{TRUST[t.state] ?? t.state}</span><span>{t.text}<span className="cs-where">{where}</span></span></li>
            ))}
          </ul>
        </section>
      )}
      {unmeasured.length > 0 && (
        <section className="cs-sec">
          <h2 className="cs-h2">재지 않은 것</h2>
          <ul className="cs-unmeasured">{unmeasured.map(({ where, u }, i) => <li key={i}>{u}<span className="cs-where">{where}</span></li>)}</ul>
        </section>
      )}
      <footer className="cs-foot">{sheet.note} 투자 판단은 담당 PB와 상담해 주세요.</footer>
    </article>
  );
}
