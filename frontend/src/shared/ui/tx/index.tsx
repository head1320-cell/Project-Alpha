"use client";
/**
 * BU0 · 토스식 공용 부품 (ADR-003 · 스펙 §7.1)
 * ==========================================================================
 * 캔버스 밖 탭이 같은 말로 그리게 하는 조각들. ★평범한 props 만 받는다★ — FSD 상 `shared` 는 `entities`·`widgets` 를
 * import 하지 않으므로, 서버 응답을 받아 문장을 만드는 일은 소비하는 위젯이 하고 여기는 그리기만 한다.
 *
 * - `Answer` 의 문장은 ★서버 값으로만★ 만든다(ADR-003 §2.6). 이 부품은 받은 문장을 그대로 그린다.
 * - 등락(`Stat` 의 delta)은 색 + 부호(▲▼) + 글자를 함께 쓴다 — 색만으로 말하지 않는다. 미상은 "몰라요".
 * - `Unknown` 은 사유가 필수다(타입으로 강제). 사유 없는 "몰라요" 는 만들 수 없다.
 * - 클래스(`tx-*`)는 E2E 계약이다(`e2e/dev-ui.spec.ts`).
 */
import Link from "next/link";
import { useId, useRef, type KeyboardEvent, type ReactNode } from "react";
import { AlertTriangle, ChevronRight, FlaskConical, Info } from "lucide-react";
import { UNKNOWN_TEXT, type Direction } from "@/shared/lib/krFormat";

// ── 머리 ────────────────────────────────────────────────────────────────────

export function PageHead({ title, lede, actions }: { title: string; lede?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="tx-head">
      <div className="tx-head-main">
        <h1 className="tx-h1">{title}</h1>
        {lede ? <p className="tx-lede">{lede}</p> : null}
      </div>
      {actions ? <div className="tx-head-act">{actions}</div> : null}
    </header>
  );
}

// ── 근거 칩 ─────────────────────────────────────────────────────────────────

/** 캔버스 "믿어도 되나요?" 와 같은 어휘 — practice(연습용 데이터) · assumed(가정) · unknown(모름) · unmeasured(재지 않음). */
/** plain = 판단이 아닌 사실(판정 이름·적재 수) — 중립 색. */
export type ChipTone = "practice" | "assumed" | "unknown" | "unmeasured" | "ok" | "info" | "plain";
export type Chip = { label: string; tone: ChipTone };

export function Chips({ items, label = "이 답의 근거" }: { items: Chip[]; label?: string }) {
  if (!items.length) return null;
  return (
    <ul className="tx-chips" aria-label={label}>
      {items.map((c, i) => <li key={`${c.tone}-${i}`} className="tx-chip" data-tone={c.tone}>{c.label}</li>)}
    </ul>
  );
}

// ── 답 한 문장 ──────────────────────────────────────────────────────────────

export type Figure = { label: string; value: ReactNode };

export function Answer({ sentence, figures = [], chips = [], action }: {
  sentence: ReactNode; figures?: Figure[]; chips?: Chip[]; action?: ReactNode;
}) {
  return (
    <section className="tx-answer" aria-label="한 줄 답">
      <p className="tx-answer-s">{sentence}</p>
      {figures.length ? (
        <dl className="tx-figs">
          {figures.map((f) => <div key={f.label} className="tx-fig"><dt>{f.label}</dt><dd>{f.value}</dd></div>)}
        </dl>
      ) : null}
      <Chips items={chips} />
      {action ? <div className="tx-answer-act">{action}</div> : null}
    </section>
  );
}

// ── 절 · 목록 행 ────────────────────────────────────────────────────────────

export function Section({ title, sub, aside, children }: {
  title?: string; sub?: ReactNode; aside?: ReactNode; children: ReactNode;
}) {
  return (
    <section className="tx-sec">
      {title || aside ? (
        <header className="tx-sec-head">
          <div>
            {title ? <h2 className="tx-sec-t">{title}</h2> : null}
            {sub ? <p className="tx-sec-sub">{sub}</p> : null}
          </div>
          {aside ? <div className="tx-sec-aside">{aside}</div> : null}
        </header>
      ) : null}
      <div className="tx-sec-body">{children}</div>
    </section>
  );
}

/** 목록 한 줄. href 면 링크, onClick 이면 단추, 둘 다 없으면 그냥 줄(누를 수 없음 — 화살표도 없다). */
export function ListRow({ title, sub, right, href, onClick, className }: {
  title: ReactNode; sub?: ReactNode; right?: ReactNode; href?: string; onClick?: () => void;
  /** 화면 계약 클래스를 더할 때(예: 홈의 `.dash-mod`). */
  className?: string;
}) {
  const extra = className ? ` ${className}` : "";
  const body = (
    <>
      <span className="tx-row-main">
        <span className="tx-row-t">{title}</span>
        {sub ? <span className="tx-row-sub">{sub}</span> : null}
      </span>
      {right ? <span className="tx-row-right">{right}</span> : null}
      {href || onClick ? <ChevronRight className="tx-row-go" size={18} aria-hidden /> : null}
    </>
  );
  if (href) return <Link href={href} className={`tx-row tx-row--go${extra}`}>{body}</Link>;
  if (onClick) return <button type="button" className={`tx-row tx-row--go${extra}`} onClick={onClick}>{body}</button>;
  return <div className={`tx-row${extra}`}>{body}</div>;
}

// ── 숫자 하나 ───────────────────────────────────────────────────────────────

const GLYPH: Record<Direction, string> = { up: "▲", down: "▼", flat: "", unknown: "" };
const SAID: Record<Direction, string> = { up: "올랐어요", down: "내렸어요", flat: "그대로예요", unknown: "변화를 몰라요" };

/** 잰 값 하나 + (있으면) 등락. delta.text 는 호출자가 krFormat 으로 만든 글자(+2.1%p 등) — 미상이면 dir "unknown". */
export function Stat({ label, value, delta }: {
  label: string; value: ReactNode; delta?: { text: string; dir: Direction };
}) {
  return (
    <div className="tx-stat">
      <span className="tx-stat-l">{label}</span>
      <span className="tx-stat-v">{value}</span>
      {delta ? (
        <span className="tx-delta" data-dir={delta.dir} aria-label={`${delta.dir === "unknown" ? UNKNOWN_TEXT : delta.text} — ${SAID[delta.dir]}`}>
          {GLYPH[delta.dir] ? <span aria-hidden>{GLYPH[delta.dir]} </span> : null}
          {delta.dir === "unknown" ? UNKNOWN_TEXT : delta.text}
        </span>
      ) : null}
    </div>
  );
}

// ── 고르기: 분할 단추 · 탭 ──────────────────────────────────────────────────

type Opt<T extends string> = { value: T; label: string };

/** 화살표·Home·End 로 다음 항목에 초점을 옮기고 고른다(로빙 tabindex — 묶음 하나가 Tab 한 번). */
function rove<T extends string>(e: KeyboardEvent, opts: Opt<T>[], cur: T, pick: (v: T) => void, refs: (HTMLButtonElement | null)[]) {
  const i = opts.findIndex((o) => o.value === cur);
  const n = opts.length;
  const to = e.key === "ArrowRight" || e.key === "ArrowDown" ? (i + 1) % n
    : e.key === "ArrowLeft" || e.key === "ArrowUp" ? (i - 1 + n) % n
    : e.key === "Home" ? 0 : e.key === "End" ? n - 1 : -1;
  if (to < 0) return;
  e.preventDefault();
  pick(opts[to].value);
  refs[to]?.focus();
}

export function Segmented<T extends string>({ label, options, value, onChange }: {
  label: string; options: Opt<T>[]; value: T; onChange: (v: T) => void;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  return (
    <div className="tx-seg" role="radiogroup" aria-label={label}>
      {options.map((o, i) => {
        const on = o.value === value;
        return (
          <button key={o.value} ref={(el) => { refs.current[i] = el; }} type="button" role="radio" aria-checked={on}
                  tabIndex={on ? 0 : -1} className={`tx-seg-opt${on ? " tx-seg-opt--on" : ""}`}
                  onClick={() => onChange(o.value)} onKeyDown={(e) => rove(e, options, value, onChange, refs.current)}>
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

/** 탭 목록 + 패널. 패널은 고른 것 하나만 그린다(나머지는 마운트하지 않는다). */
export function Tabs<T extends string>({ label, tabs, value, onChange, children }: {
  label: string; tabs: Opt<T>[]; value: T; onChange: (v: T) => void; children: ReactNode;
}) {
  const base = useId();
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  return (
    <div className="tx-tabs">
      <div className="tx-tablist" role="tablist" aria-label={label}>
        {tabs.map((t, i) => {
          const on = t.value === value;
          return (
            <button key={t.value} ref={(el) => { refs.current[i] = el; }} type="button" role="tab" id={`${base}-t-${t.value}`}
                    aria-selected={on} aria-controls={`${base}-p`} tabIndex={on ? 0 : -1}
                    className={`tx-tab${on ? " tx-tab--on" : ""}`} data-tab={t.value}
                    onClick={() => onChange(t.value)} onKeyDown={(e) => rove(e, tabs, value, onChange, refs.current)}>
              {t.label}
            </button>
          );
        })}
      </div>
      <div className="tx-tabpanel" role="tabpanel" id={`${base}-p`} aria-labelledby={`${base}-t-${value}`} tabIndex={0}>
        {children}
      </div>
    </div>
  );
}

// ── 알림 · 모름 ─────────────────────────────────────────────────────────────

/** practice = 연습용 데이터 · warn = 가정·주의 · danger = 실패·위험(화면 낭독기가 바로 읽는다). */
export function Notice({ tone, title, children }: { tone: "practice" | "warn" | "danger"; title: string; children?: ReactNode }) {
  const Icon = tone === "practice" ? FlaskConical : tone === "danger" ? AlertTriangle : Info;
  return (
    <div className="tx-notice" data-tone={tone} role={tone === "danger" ? "alert" : "note"}>
      <Icon className="tx-notice-i" size={18} aria-hidden />
      <div>
        <p className="tx-notice-t">{title}</p>
        {children ? <div className="tx-notice-b">{children}</div> : null}
      </div>
    </div>
  );
}

/** "몰라요" + 왜 모르는지. ★사유가 필수다★ — 0 이나 빈칸으로 그리지 않는다(미상 ≠ 0). */
export function Unknown({ reason }: { reason: ReactNode }) {
  return (
    <span className="tx-unknown">
      <span className="tx-unknown-v">{UNKNOWN_TEXT}</span>
      <span className="tx-unknown-why">{reason}</span>
    </span>
  );
}
