"use client";
/**
 * 종목 칸 (BN N2) — 코드 쉼표 목록은 그대로 받고, 마지막 토막이 코드가 아니면 서버 종목 검색으로 이름 후보를 보인다.
 * ==========================================================================
 * 고르면 그 토막이 코드로 바뀐다. 칩은 "이름 · 코드" — 이름은 서버(`stock_master`)가 준 것만, 모르면 "이름 모름",
 * 검색이 실패하면 "이름 확인 못 함"(없음과 다르다). 콤보박스(ARIA 1.2): ↑↓ 로 고르고 Enter 로 넣고 Esc 로 닫는다.
 */
import { useEffect, useId, useState, type InputHTMLAttributes } from "react";
import { isCode, lastToken, nameOf, parseTickers, searchStocks, type NameState, type StockHit } from "@/entities/portfolio-graph";

export function useStockNames(codes: string[]): Record<string, NameState> {
  const [map, setMap] = useState<Record<string, NameState>>({});
  const key = codes.join(",");
  useEffect(() => {
    let alive = true;
    for (const c of key ? key.split(",") : []) {
      void nameOf(c).then((s) => { if (alive) setMap((m) => ({ ...m, [c]: s })); });
    }
    return () => { alive = false; };
  }, [key]);
  return map;
}

export function nameLabel(s: NameState | undefined): string {
  if (!s || s.state === "loading") return "이름 찾는 중";
  if (s.state === "known") return s.name;
  if (s.state === "unknown") return "이름 모름";
  return "이름 확인 못 함";
}

/** "이름 · 코드" 칩 — 이름을 모르면 그렇다고 말한다(지어내지 않는다). */
export function StockChip({ code, name, className }: { code: string; name: NameState | undefined; className: string }) {
  const known = name?.state === "known";
  return (
    <span className={`${className}${known ? "" : ` ${className}--noname`}`} data-code={code} data-name={name?.state ?? "loading"}
          title={name?.state === "failed" ? name.reason : undefined}>
      <span className="pg-stock-name">{nameLabel(name)}</span> · <span className="pg-stock-code">{code}</span>
    </span>
  );
}

type Found = { token: string; hits: StockHit[] } | { token: string; error: string } | null;

export function TickerInput({ value, onText, onPick, inputProps }: {
  value: string; onText: (t: string) => void; onPick?: (t: string) => void;
  inputProps?: InputHTMLAttributes<HTMLInputElement>;
}) {
  const id = useId();
  const [found, setFound] = useState<Found>(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const { head, token } = lastToken(value);
  const searchable = !!token && !isCode(token);
  useEffect(() => {
    if (!searchable) return;
    const ac = new AbortController();
    const t = setTimeout(() => {
      searchStocks(token, 8, ac.signal)
        .then((r) => { setFound(r.ok ? { token, hits: r.items } : { token, error: r.reason }); setActive(0); })
        .catch(() => { /* 새 글자에 밀려 취소됨 */ });
    }, 180);
    return () => { clearTimeout(t); ac.abort(); };
  }, [token, searchable]);
  const cur = found && found.token === token ? found : null;
  const hits = cur && "hits" in cur ? cur.hits : [];
  const show = open && searchable && !!cur;
  const pick = (h: StockHit) => {
    const next = `${head}${h.code}, `;
    onText(next);
    onPick?.(next);
    setOpen(false);
  };
  return (
    <div className="pg-ticker">
      <input {...inputProps} value={value} role="combobox" aria-expanded={show} aria-autocomplete="list"
             aria-controls={`${id}-list`} aria-activedescendant={show && hits[active] ? `${id}-o${active}` : undefined}
             onChange={(e) => { onText(e.target.value); setOpen(true); }}
             onKeyDown={(e) => {
               if (show && hits.length && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
                 e.preventDefault();
                 setActive((a) => (a + (e.key === "ArrowDown" ? 1 : hits.length - 1)) % hits.length);
               } else if (show && hits.length && e.key === "Enter") {
                 e.preventDefault();
                 pick(hits[active]);
               } else if (show && e.key === "Escape") {
                 e.preventDefault();                      // 대화상자를 닫지 않고 목록만 닫는다
                 e.stopPropagation();
                 setOpen(false);
               } else inputProps?.onKeyDown?.(e);
             }}
             onBlur={(e) => { setOpen(false); inputProps?.onBlur?.(e); }} />
      {show && (
        <ul id={`${id}-list`} role="listbox" className="pg-suggest" aria-label="종목 후보">
          {"error" in cur! ? (
            <li className="pg-suggest-note pg-suggest-note--err" role="option" aria-disabled="true" aria-selected="false">
              {cur.error} — 종목 코드는 그대로 넣을 수 있어요.
            </li>
          ) : hits.length === 0 ? (
            <li className="pg-suggest-note" role="option" aria-disabled="true" aria-selected="false">‘{token}’으로 찾은 종목이 없어요.</li>
          ) : hits.map((h, i) => (
            <li key={h.code} id={`${id}-o${i}`} role="option" aria-selected={i === active} className="pg-suggest-item" data-code={h.code}
                onMouseDown={(e) => { e.preventDefault(); pick(h); }} onMouseEnter={() => setActive(i)}>
              <b>{h.name}</b><span>{h.code}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** 설정 탭의 종목 칸 — `ListField` 와 같은 규칙(입력 중에는 글자 그대로, Enter·벗어날 때 목록으로) + 이름 후보 + "이름 · 코드" 칩. */
export function TickerField({ value, onChange }: { value: unknown; onChange: (v: unknown) => void }) {
  const joined = Array.isArray(value) ? value.join(", ") : "";
  const [text, setText] = useState(joined);
  useEffect(() => { setText(joined); }, [joined]);
  const [left, setLeft] = useState<string[]>([]);
  // 코드로 읽히는 것만 넣는다(목표로 시작과 같은 규칙 `parseTickers`) — 이름 글자는 종목으로 넣지 않고 무엇을 뺐는지 말한다.
  const commit = (t: string) => {
    const { tickers, rejected } = parseTickers(t);
    setLeft(rejected);
    onChange(tickers.length ? tickers : undefined);
  };
  const codes = Array.isArray(value) ? value.filter((x): x is string => typeof x === "string") : [];
  const names = useStockNames(codes);
  return (
    <>
      <TickerInput value={text} onText={setText} onPick={commit}
                   inputProps={{ className: "pg-field-input", placeholder: "코드를 쉼표로, 또는 이름으로 찾기 (예: 삼성전자)",
                                 "aria-label": "종목", onBlur: () => commit(text),
                                 onKeyDown: (e) => { if (e.key === "Enter") commit(text); } }} />
      {left.length > 0 && (
        <p className="pg-ticker-note" role="status">‘{left.join(", ")}’은 종목 코드가 아니라 넣지 않았어요 — 이름이면 후보에서 골라 주세요.</p>
      )}
      {codes.length > 0 && (
        <div className="pg-stock-chips" aria-label="고른 종목">
          {codes.map((c) => <StockChip key={c} code={c} name={names[c]} className="pg-stock-chip" />)}
        </div>
      )}
    </>
  );
}
