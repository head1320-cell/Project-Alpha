"use client";
/**
 * 메뉴 단추(WAI-ARIA APG Menu Button) — 판 메뉴 · '배치' 메뉴가 쓴다 (G6 2a-1 · 계획 §9.1)
 * ==========================================================================
 * 단추: Enter · Space · ↓ 로 열고 첫 항목에 초점 · ↑ 로 열고 끝 항목에 초점 · 누르면 열고 닫는다.
 * 메뉴: ↓ ↑(둘러 돎) · Home · End · Enter · Space(고르기) · Escape(닫고 단추로 초점) · Tab(닫고 다음 요소로 — 단추에서 이어 간다).
 * aria-disabled 항목은 초점은 받되 고를 수 없다(APG) — 까닭 글은 aria-describedby 로 잇고, 이름(aria-label)은 항목 글만이다(까닭이 이름에 섞이지 않게).
 * ★메뉴는 document.body 에 portal + position: fixed★ — 칸의 넘침 상자에 잘리지 않고 판 머리의 쌓임 맥락에 갇히지 않는다(아래가 모자라면 위로 ·
 * 창 안으로). 바깥을 누르거나 창 크기가 바뀌거나 ★구르기가 단추를 옮기면★ 닫는다(자리가 어긋난 메뉴를 남기지 않는다) — 메뉴를 놓을 때 잰 단추 자리와 견준다.
 * 단추를 옮기지 않은 구르기(판 안 · 붙은 막대 아래 칸 · 메뉴 자신 · 화면 밖 단추를 누를 때 브라우저가 단추를 화면 안으로 굴린 것)로는 닫지 않는다 —
 * 그 마지막 구르기의 알림은 메뉴가 열린 뒤 다음 그림에 와서, 구르기마다 닫던 때는 화면 밖 단추의 메뉴가 열자마자 닫혔다(2026-11-20 · `e2e/workspace-intraday.spec.ts`).
 * 닫힌 동안 DOM 에는 단추 하나뿐이다.
 */
import { useCallback, useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";

export type MenuItem =
  | { kind: "item"; key: string; label: string; onSelect: () => void; disabled?: boolean; why?: string;
      role?: "menuitem" | "menuitemradio" | "menuitemcheckbox"; checked?: boolean }
  | { kind: "group"; key: string; label: string; items: MenuItem[] }
  | { kind: "sep"; key: string };

const GAP = 4;
const EDGE = 8;
/** 단추가 이만큼(px) 이상 옮겨야 움직인 것 — 메뉴는 정수 px 에 놓으므로 그보다 작은 어긋남은 자리를 바꾸지 않는다. */
const MOVED = 1;

export function MenuButton({ className, label, children, items, id }: {
  className: string;
  /** 단추의 이름 — 아이콘만 있는 단추일 때(보이는 글이 있으면 생략). */
  label?: string;
  children: ReactNode;
  items: MenuItem[];
  /** 단추의 고정 id — 화면이 바뀐 뒤에도 같은 단추로 초점을 돌려야 할 때(없으면 useId). */
  id?: string;
}) {
  const [open, setOpen] = useState<false | "first" | "last">(false);
  const btn = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement | null>(null);
  /** 메뉴를 놓을 때 잰 단추 자리(창 기준) — 구르기가 단추를 옮겼는지 이것과 견준다(구르기마다 다시 재지 않는다 · 메뉴가 없으면 null). */
  const anchor = useRef<{ x: number; y: number } | null>(null);
  const uid = useId();
  const btnId = id ?? `${uid}-b`;
  const menuId = `${uid}-m`;

  const close = (focusButton: boolean) => {
    setOpen(false);
    if (focusButton) btn.current?.focus();
  };

  /** 메뉴가 붙을 때 한 번 — 재어(메뉴 크기) 단추 아래(모자라면 위) · 창 안으로 놓고 첫(또는 끝) 항목에 초점 · 그때 잰 단추 자리를 남긴다(구르기 판정). 상태 없이 그 요소에 바로 적는다. */
  const place = useCallback((el: HTMLDivElement | null) => {
    menu.current = el;
    anchor.current = null;
    if (!el || !btn.current) return;
    const b = btn.current.getBoundingClientRect();
    anchor.current = { x: b.left, y: b.top };
    const m = el.getBoundingClientRect();
    const below = b.bottom + GAP;
    const top = below + m.height > window.innerHeight - EDGE ? Math.max(EDGE, b.top - GAP - m.height) : below;
    const left = Math.min(Math.max(EDGE, b.left), Math.max(EDGE, window.innerWidth - m.width - EDGE));
    el.style.top = `${Math.round(top)}px`;
    el.style.left = `${Math.round(left)}px`;
    el.style.visibility = "visible";
    const all = el.querySelectorAll<HTMLElement>("[role^='menuitem']");
    (el.dataset.from === "last" ? all[all.length - 1] : all[0])?.focus();
  }, []);

  // 바깥 누르기 · 단추를 옮긴 구르기 · 창 크기 → 닫기
  useEffect(() => {
    if (!open) return;
    const outside = (e: PointerEvent) => {
      const t = e.target as Node;
      if (menu.current?.contains(t) || btn.current?.contains(t)) return;
      close(false);
    };
    /** 메뉴를 놓은 뒤 단추가 움직였는가 — 놓은 자리나 단추를 모르면 움직인 것으로 본다(닫는다). */
    const moved = (): boolean => {
      const a = anchor.current;
      const b = btn.current?.getBoundingClientRect();
      return !a || !b || Math.abs(b.left - a.x) >= MOVED || Math.abs(b.top - a.y) >= MOVED;
    };
    const onScroll = () => { if (moved()) close(false); };
    const onResize = () => close(false);
    document.addEventListener("pointerdown", outside, true);
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onResize);
    return () => {
      document.removeEventListener("pointerdown", outside, true);
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", onResize);
    };
  }, [open]);

  const onButtonKey = (e: KeyboardEvent<HTMLButtonElement>) => {
    if (e.key === "ArrowDown" || e.key === "Enter" || e.key === " ") { e.preventDefault(); setOpen("first"); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setOpen("last"); }
  };

  const onMenuKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const all = Array.from(menu.current?.querySelectorAll<HTMLElement>("[role^='menuitem']") ?? []);
    const i = all.indexOf(document.activeElement as HTMLElement);
    const to = e.key === "ArrowDown" ? (i + 1) % all.length : e.key === "ArrowUp" ? (i - 1 + all.length) % all.length
      : e.key === "Home" ? 0 : e.key === "End" ? all.length - 1 : -1;
    if (to >= 0) { e.preventDefault(); all[to]?.focus(); return; }
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(true); return; }
    if (e.key === "Tab") { btn.current?.focus(); setOpen(false); }   // 기본 동작(다음 요소로)은 단추에서 이어 간다
  };

  const pick = (it: Extract<MenuItem, { kind: "item" }>) => {
    if (it.disabled) return;
    close(true);
    it.onSelect();
  };

  const render = (list: MenuItem[]): ReactNode => list.map((it) => {
    if (it.kind === "sep") return <div key={it.key} role="separator" className="ws-menu-sep" />;
    if (it.kind === "group") {
      return (
        <div key={it.key} role="group" aria-label={it.label} className="ws-menu-group">
          <p className="ws-menu-h" aria-hidden="true">{it.label}</p>
          {render(it.items)}
        </div>
      );
    }
    const role = it.role ?? "menuitem";
    const whyId = it.why ? `${menuId}-${it.key}-why` : undefined;
    return (
      <button key={it.key} type="button" role={role} tabIndex={-1} className="ws-menu-item" data-key={it.key} aria-label={it.why ? it.label : undefined}
              aria-checked={role === "menuitem" ? undefined : !!it.checked} aria-disabled={it.disabled || undefined} aria-describedby={whyId}
              onClick={() => pick(it)}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(it); } }}>
        <span className="ws-menu-label">{it.label}</span>
        {it.why ? <span className="ws-menu-why" id={whyId}>{it.why}</span> : null}
      </button>
    );
  });

  return (
    <>
      <button ref={btn} id={btnId} type="button" className={className} aria-label={label} aria-haspopup="menu" aria-expanded={!!open}
              aria-controls={open ? menuId : undefined} onClick={() => (open ? close(false) : setOpen("first"))} onKeyDown={onButtonKey}>
        {children}
      </button>
      {open && typeof document !== "undefined" ? createPortal(
        <div ref={place} id={menuId} role="menu" aria-labelledby={btnId} className="ws-menu" data-from={open} onKeyDown={onMenuKey}
             style={{ top: 0, left: 0, visibility: "hidden" }}>
          {render(items)}
        </div>, document.body) : null}
    </>
  );
}
