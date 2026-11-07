"use client";
/**
 * BU0 · 머리 줄 찾기 — 종목·화면을 한 칸에서 (`/` 키)
 * ==========================================================================
 * - 화면: 메뉴에 있는 이름(관리 화면은 관리자에게만)으로 이동한다. 네트워크 없이 바로 찾는다.
 * - 종목: 기존 `GET /api/v1/screener/stock-search`(→ `stock_master.search_stocks`)로 찾고 `/insights?code=` 로 간다.
 *   새 종목 판정 로직은 만들지 않는다(CLAUDE.md §4 — 종목 식별은 stock_master 가 단일 진실 공급원).
 * - ★빈 결과와 실패를 섞지 않는다★ 검색 요청이 실패하면 "맞는 종목이 없어요"가 아니라 "종목 검색에 닿지 못했어요"라고
 *   말한다(침묵 폴백 금지). 화면 찾기는 그대로 된다.
 * - 키보드: `/` 로 열고(입력 중이 아닐 때) ↑↓ 로 고르고 Enter 로 가고 Esc 로 닫는다. combobox + listbox(ARIA 1.2).
 */
import { useRouter } from "next/navigation";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Search } from "lucide-react";
import { API_BASE } from "@/shared/api/apiBase";

export type ScreenLink = { label: string; href: string };
type Stock = { code: string; name: string };
type Lookup = { q: string; state: "loading" } | { q: string; state: "ok"; items: Stock[] } | { q: string; state: "error" };
type Item = { kind: "screen"; label: string; href: string } | { kind: "stock"; label: string; code: string; href: string };

const norm = (s: string) => s.replace(/\s+/g, "").toLowerCase();

/** 입력 중인 칸이면 `/` 를 가로채지 않는다(글자 '/' 를 쓰는 중일 수 있다). */
function typing(t: EventTarget | null) {
  const el = t as HTMLElement | null;
  if (!el) return false;
  return el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName);
}

export function ShellSearch({ screens }: { screens: ScreenLink[] }) {
  const router = useRouter();
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [lookup, setLookup] = useState<Lookup | null>(null);

  // `/` 로 찾기 칸에 초점 — 캔버스 등 다른 단축키와 겹치지 않게 입력 중일 때는 두지 않는다.
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key !== "/" || e.metaKey || e.ctrlKey || e.altKey || typing(e.target)) return;
      e.preventDefault();
      input.current?.focus();
      setOpen(true);
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);

  // 바깥을 누르면 닫는다(잡는 단계 — 캔버스가 mousedown 을 멈춰도 닿게).
  useEffect(() => {
    if (!open) return;
    const down = (e: PointerEvent) => { if (!wrap.current?.contains(e.target as Node)) setOpen(false); };
    window.addEventListener("pointerdown", down, true);
    return () => window.removeEventListener("pointerdown", down, true);
  }, [open]);

  // 종목 찾기 — 140ms 쉬고 묻는다. 늦게 온 답이 새 질문을 덮지 않게 질문을 함께 적어 둔다.
  useEffect(() => {
    const t = q.trim();
    if (!t) { setLookup(null); return; }
    let live = true;
    const h = setTimeout(() => {
      setLookup({ q: t, state: "loading" });
      fetch(`${API_BASE}/api/v1/screener/stock-search?q=${encodeURIComponent(t)}&limit=6`)
        .then((r) => { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
        .then((b: { items?: Stock[] }) => { if (live) setLookup({ q: t, state: "ok", items: Array.isArray(b.items) ? b.items : [] }); })
        .catch(() => { if (live) setLookup({ q: t, state: "error" }); });
    }, 140);
    return () => { live = false; clearTimeout(h); };
  }, [q]);

  const items: Item[] = useMemo(() => {
    const t = norm(q);
    if (!t) return [];
    const sc: Item[] = screens.filter((s) => norm(s.label).includes(t)).slice(0, 4)
      .map((s) => ({ kind: "screen", label: s.label, href: s.href }));
    const st: Item[] = lookup && lookup.state === "ok" && lookup.q === q.trim()
      ? lookup.items.map((s) => ({ kind: "stock", label: s.name, code: s.code, href: `/insights?code=${s.code}` })) : [];
    return [...sc, ...st];
  }, [q, screens, lookup]);

  useEffect(() => { setActive(0); }, [q]);

  const go = (it: Item) => {
    setOpen(false);
    setQ("");
    input.current?.blur();
    router.push(it.href);
  };

  const pending = !!q.trim() && (!lookup || lookup.q !== q.trim() || lookup.state === "loading");
  const failed = !!lookup && lookup.q === q.trim() && lookup.state === "error";
  const show = open && !!q.trim();
  const listId = `${id}-list`;
  const optId = (i: number) => `${id}-opt-${i}`;

  return (
    <div className="tx-find" ref={wrap}>
      <Search className="tx-find-i" size={16} aria-hidden />
      <input ref={input} className="tx-find-input" type="search" value={q} placeholder="종목·화면 찾기"
             role="combobox" aria-label="종목·화면 찾기" aria-expanded={show} aria-controls={listId} aria-autocomplete="list"
             aria-activedescendant={show && items.length ? optId(active) : undefined}
             onChange={(e) => { setQ(e.target.value); setOpen(true); }}
             onFocus={() => setOpen(true)}
             onKeyDown={(e) => {
               if (e.key === "Escape") { setOpen(false); setQ(""); input.current?.blur(); return; }
               if (!items.length) return;
               if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => (a + 1) % items.length); }
               else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => (a - 1 + items.length) % items.length); }
               else if (e.key === "Enter") { e.preventDefault(); go(items[Math.min(active, items.length - 1)]); }
             }} />
      <kbd className="tx-find-kbd" aria-hidden>/</kbd>
      {show && (
        <div className="tx-find-pop">
          <ul id={listId} role="listbox" aria-label="찾은 것" className="tx-find-list">
            {items.map((it, i) => (
              <li key={`${it.kind}-${it.href}`} id={optId(i)} role="option" aria-selected={i === active}
                  className={`tx-find-opt${i === active ? " tx-find-opt--on" : ""}`} data-kind={it.kind}
                  onPointerDown={(e) => e.preventDefault()} onClick={() => go(it)} onMouseEnter={() => setActive(i)}>
                <span className="tx-find-opt-t">{it.label}</span>
                <span className="tx-find-opt-sub">{it.kind === "stock" ? `${it.code} · 기업 분석` : "화면"}</span>
              </li>
            ))}
          </ul>
          {pending && <p className="tx-find-note" role="status">종목을 찾는 중이에요</p>}
          {failed && <p className="tx-find-note tx-find-note--err" role="alert">종목 검색에 닿지 못했어요. 화면 이름으로는 찾을 수 있어요.</p>}
          {!pending && !failed && !items.length && <p className="tx-find-note" role="status">‘{q.trim()}’ — 맞는 종목·화면이 없어요</p>}
        </div>
      )}
    </div>
  );
}
