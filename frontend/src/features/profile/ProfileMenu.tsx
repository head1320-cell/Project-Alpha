"use client";
/**
 * 머리 줄 프로필 (BR R3) — 동그라미 하나, 누르면 아래로 카드가 펼쳐진다(토스).
 * ==========================================================================
 * 카드에는 세 가지만: 이름·역할 · 화면 테마 · 로그인/로그아웃. 국면 배지는 머리 줄에서 뺐다(국면은 /macro).
 * Esc·바깥 누르기로 닫고 연 단추로 초점을 돌려준다. 바깥 누르기는 잡는 단계의 pointerdown 으로 본다 —
 * 캔버스 판(d3-zoom)이 mousedown 을 멈춰 거품 단계로는 오지 않는다(BQ Q2 에서 배운 것).
 */
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { ROLE_KO, useSession } from "./session";
import { darkReady, DARK_READY, THEMES, useTheme } from "./theme";

function Person() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" className="pf-person">
      <circle cx="12" cy="8" r="4" /><path d="M4 21c0-4.4 3.6-8 8-8s8 3.6 8 8" />
    </svg>
  );
}

export function ProfileMenu() {
  const pathname = usePathname() ?? "";
  const { session, retry, logout } = useSession();
  const theme = useTheme((s) => s.theme);
  const setTheme = useTheme((s) => s.setTheme);
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const btn = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const key = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setOpen(false);
      btn.current?.focus();
    };
    const down = (e: PointerEvent) => { if (!wrap.current?.contains(e.target as Node)) setOpen(false); };
    window.addEventListener("keydown", key, true);
    window.addEventListener("pointerdown", down, true);
    return () => { window.removeEventListener("keydown", key, true); window.removeEventListener("pointerdown", down, true); };
  }, [open]);

  const signedIn = session.kind === "signed_in";
  const initial = signedIn ? Array.from(session.username.trim())[0]?.toUpperCase() ?? null : null;
  const role = signedIn ? (ROLE_KO[session.role] ?? session.role) : null;
  const label = signedIn ? `내 계정 — ${session.username}${role ? ` (${role})` : ""}`
    : session.kind === "loading" ? "내 계정 — 확인하는 중"
    : session.kind === "unknown" ? "내 계정 — 확인하지 못했어요" : "내 계정 — 로그인 안 됨";
  const ready = darkReady(pathname);

  return (
    <div className="pf" ref={wrap}>
      <button ref={btn} type="button" className="pf-avatar" data-state={session.kind} aria-expanded={open}
              aria-controls="pf-card" aria-label={label} title={label} onClick={() => setOpen((v) => !v)}>
        {initial ?? <Person />}
      </button>
      {open && (
        <div id="pf-card" className="pf-card" role="dialog" aria-label="내 계정">
          <div className="pf-who">
            <span className="pf-avatar pf-avatar--lg" aria-hidden="true">{initial ?? <Person />}</span>
            <div className="pf-who-t">
              {signedIn ? (
                <><strong className="pf-name">{session.username}</strong>{role ? <span className="pf-role">{role}</span> : null}</>
              ) : session.kind === "unknown" ? (
                <><strong className="pf-name">계정 정보를 확인하지 못했어요</strong><span className="pf-sub">{session.reason}</span></>
              ) : session.kind === "loading" ? (
                <strong className="pf-name">확인하는 중이에요</strong>
              ) : (
                <><strong className="pf-name">로그인 안 됨</strong>
                  {session.note ? <span className="pf-sub pf-note" role="status">{session.note}</span> : null}</>
              )}
            </div>
          </div>

          <div className="pf-sec">
            <p className="pf-h" id="pf-theme-h">화면 테마</p>
            <div className="pf-seg" role="group" aria-labelledby="pf-theme-h">
              {THEMES.map(([k, l]) => (
                <button key={k} type="button" className={`pf-seg-b${theme === k ? " on" : ""}`} aria-pressed={theme === k}
                        data-theme={k} onClick={() => setTheme(k)}>{l}</button>
              ))}
            </div>
            {!ready && theme !== "light" ? (
              <p className="pf-sub pf-theme-note">
                이 화면은 아직 밝게만 볼 수 있어요 — {DARK_READY.map((r) => r.label).join("·")}에서 어둡게 보여요.
              </p>
            ) : null}
          </div>

          <div className="pf-sec pf-actions">
            {signedIn ? (
              <button type="button" className="pf-logout" onClick={logout}>로그아웃</button>
            ) : session.kind === "unknown" ? (
              <button type="button" className="pf-retry" onClick={() => void retry()}>다시 시도</button>
            ) : session.kind === "signed_out" ? (
              <Link href="/login" className="pf-login" onClick={() => setOpen(false)}>로그인</Link>
            ) : null}
          </div>
        </div>
      )}
    </div>
  );
}
