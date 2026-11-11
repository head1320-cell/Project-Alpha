"use client";
/**
 * 설정 (BS1) — 계정 · 비밀번호 · 화면 테마 · (관리자) 계정 관리. 토스식 한 줄 목록.
 * ==========================================================================
 * ★공개 가입은 없다★ — 계정은 관리자가 여기서 발급하고, 임시 비밀번호는 한 번만 보인다(서버도 한 번만 준다).
 * ★모름 ≠ 로그아웃★ — `useSession` 네 상태를 그대로 쓴다(프로필 카드와 같은 판정).
 * 비밀번호 규칙은 입력하는 동안 미리 보이지만 판정은 서버가 한다 — 거절 사유는 서버 문구 그대로.
 */
import Link from "next/link";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { setToken } from "@/shared/api/authToken";
import { loginHref } from "@/shared/lib/nextPath";
import { ROLE_KO, useSession } from "@/entities/session";
import { DARK_EXCEPTIONS, THEMES, useTheme } from "@/shared/theme";
import { changePassword, issueAccount, listAccounts, resetAccount, type Account } from "./api";
import { BrokerAccounts } from "./BrokerAccounts";
import { passwordRules } from "./passwordRules";

const day = (iso: string | null) => (iso ? iso.slice(0, 10) : null);
/** 서버 `auth_routes._USERNAME` 과 같은 모양 — 어긋나면 서버의 422 사유가 그대로 보인다. */
const USERNAME = /^[A-Za-z0-9._-]{1,64}$/;

function Person() {
  return (
    <svg viewBox="0 0 24 24" width="26" height="26" aria-hidden="true" className="pf-person">
      <circle cx="12" cy="8" r="4" /><path d="M4 21c0-4.4 3.6-8 8-8s8 3.6 8 8" />
    </svg>
  );
}

export function SettingsView() {
  const { session, retry, refresh, logout } = useSession();
  const signedIn = session.kind === "signed_in";
  const initial = signedIn ? Array.from(session.username.trim())[0]?.toUpperCase() ?? null : null;
  const pwRef = useRef<HTMLFormElement>(null);

  // 로그인 화면이 `#password` 로 보냈다 — 바꿀 칸으로 곧장.
  useEffect(() => {
    if (!signedIn || typeof window === "undefined" || window.location.hash !== "#password") return;
    pwRef.current?.scrollIntoView({ block: "nearest" }); // 가운데로 끌면 맨 위 이름 카드가 잘렸다(스크린샷)
    pwRef.current?.querySelector<HTMLInputElement>('input[name="current-password"]')?.focus();
  }, [signedIn]);

  return (
    <div className="set">
      <h1 className="set-title">설정</h1>

      {session.kind === "loading" ? (
        <section className="set-card set-head" aria-busy="true"><p className="set-sub">계정 확인 중</p></section>
      ) : session.kind === "unknown" ? (
        <section className="set-card set-unknown" role="alert">
          <p className="set-strong">계정 정보 확인 실패</p>
          <p className="set-sub">{session.reason} 로그인은 그대로 두었습니다.</p>
          <button type="button" className="set-btn set-retry" onClick={() => void retry()}>재시도</button>
        </section>
      ) : session.kind === "signed_out" ? (
        <section className="set-card set-signed-out">
          <p className="set-strong">{session.note ?? "로그인하면 계정과 비밀번호를 볼 수 있습니다."}</p>
          <p className="set-sub">계정은 관리자에게 받습니다. 따로 가입하는 곳은 없습니다.</p>
          <Link href={loginHref("/settings")} className="set-btn set-btn--primary">로그인</Link>
        </section>
      ) : (
        <>
          <section className="set-card set-head" aria-label="내 계정">
            <span className="set-avatar" aria-hidden="true">{initial ?? <Person />}</span>
            <div className="set-head-t">
              <strong className="set-name">{session.username}</strong>
              <span className="set-role">{ROLE_KO[session.role] ?? session.role}</span>
              <span className="set-sub">
                {session.mustChange ? "관리자가 준 임시 비밀번호로 들어왔습니다"
                  : day(session.changedAt) ? `비밀번호를 바꾼 날 ${day(session.changedAt)}` : "비밀번호를 바꾼 적 없음"}
              </span>
            </div>
          </section>
          {session.mustChange ? (
            <p className="set-must" role="alert">
              비밀번호를 먼저 변경하십시오 — 바꾸기 전에는 계좌·주문·감사 화면이 열리지 않습니다.
            </p>
          ) : null}
          <PasswordForm formRef={pwRef} username={session.username} onChanged={() => void refresh()}
                        adminWarning={session.role === "admin" && session.adminPassword?.state === "default" ? session.adminPassword.reason : null} />
          {/* 임시 비밀번호면 숨긴다 — 서버도 바꾸기 전에는 계좌 경로를 403 으로 막는다. */}
          {session.mustChange ? null : <BrokerAccounts />}
        </>
      )}

      <ThemeSection />

      {signedIn && session.role === "admin" && !session.mustChange ? <AdminAccounts me={session.username} /> : null}

      {signedIn ? (
        <section className="set-sec">
          <button type="button" className="set-btn set-logout" onClick={logout}>로그아웃</button>
        </section>
      ) : null}
    </div>
  );
}

function PasswordForm({ formRef, username, onChanged, adminWarning }: {
  formRef: React.RefObject<HTMLFormElement | null>; username: string; onChanged: () => void; adminWarning: string | null;
}) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const rules = passwordRules(next, { current, username, confirm });
  const ready = current.length > 0 && rules.every((r) => r.ok);
  const rulesId = useId();

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!ready || busy) return;
    setBusy(true); setError(null); setDone(false);
    const r = await changePassword(current, next);
    setBusy(false);
    if (!r.ok) { setError(r.error); return; }
    setToken(r.value.access_token);
    setCurrent(""); setNext(""); setConfirm("");
    setDone(true);
    onChanged();
  };

  return (
    <section className="set-sec" aria-labelledby="set-pw-h">
      <h2 className="set-h" id="set-pw-h">비밀번호</h2>
      <form ref={formRef} id="password" className="set-card set-pw" onSubmit={submit} noValidate>
        {adminWarning ? <p className="set-warn">{adminWarning}</p> : null}
        <input type="text" name="username" autoComplete="username" value={username} readOnly hidden />
        <label className="set-field">
          <span className="set-label">지금 비밀번호</span>
          <input className="set-input" name="current-password" type="password" autoComplete="current-password"
                 value={current} onChange={(e) => setCurrent(e.target.value)} />
        </label>
        <label className="set-field">
          <span className="set-label">새 비밀번호</span>
          <input className="set-input" name="new-password" type="password" autoComplete="new-password"
                 aria-describedby={rulesId} value={next} onChange={(e) => setNext(e.target.value)} />
        </label>
        <label className="set-field">
          <span className="set-label">새 비밀번호 확인</span>
          <input className="set-input" name="confirm-password" type="password" autoComplete="new-password"
                 value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        </label>
        <ul className="set-rules" id={rulesId} aria-label="새 비밀번호 규칙">
          {rules.map((r) => (
            <li key={r.id} className="set-rule" data-rule={r.id} data-ok={String(r.ok)}>
              <span className="set-rule-mark" aria-hidden="true">{r.ok ? "✓" : "·"}</span>
              {r.text}<span className="sr-only">{r.ok ? " — 충족" : " — 미충족"}</span>
            </li>
          ))}
        </ul>
        {error ? <p className="set-error" role="alert">{error}</p> : null}
        {done ? <p className="set-done" role="status">비밀번호를 바꿨습니다 — 다른 곳에 남아 있던 로그인은 모두 끝났습니다.</p> : null}
        <button type="submit" className="set-btn set-btn--primary set-pw-submit" disabled={!ready || busy}>
          {busy ? "바꾸는 중…" : "비밀번호 바꾸기"}
        </button>
      </form>
    </section>
  );
}

function ThemeSection() {
  const theme = useTheme((s) => s.theme);
  const setTheme = useTheme((s) => s.setTheme);
  return (
    <section className="set-sec" aria-labelledby="set-theme-h">
      <h2 className="set-h" id="set-theme-h">화면</h2>
      <div className="set-card">
        <div className="set-row">
          <span className="set-label set-label--row" id="set-theme-l">화면 테마</span>
          <div className="set-seg" role="group" aria-labelledby="set-theme-l">
            {THEMES.map(([k, l]) => (
              <button key={k} type="button" className={`set-seg-b${theme === k ? " on" : ""}`} aria-pressed={theme === k}
                      data-theme={k} onClick={() => setTheme(k)}>{l}</button>
            ))}
          </div>
        </div>
        {theme !== "light" ? (
          <p className="set-sub set-theme-note">
            {DARK_EXCEPTIONS.map((x) => x.label).join("·")}은 밝게만 보입니다. 나머지는 고른 테마를 따릅니다.
          </p>
        ) : null}
        <p className="set-sub">이 브라우저에만 남습니다.</p>
      </div>
    </section>
  );
}

type Issued = { username: string; temp: string; kind: "new" | "reset" };

function AdminAccounts({ me }: { me: string }) {
  const [rows, setRows] = useState<Account[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [role, setRole] = useState<"analyst" | "admin">("analyst");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [issued, setIssued] = useState<Issued | null>(null);
  const [asking, setAsking] = useState<string | null>(null);

  const load = useCallback(async () => {
    const r = await listAccounts();
    if (r.ok) { setRows(r.value.users); setLoadError(null); } else { setLoadError(r.error); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const nameOk = USERNAME.test(name);
  const issue = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!nameOk || busy) return;
    setBusy(true); setError(null);
    const r = await issueAccount(name, role);
    setBusy(false);
    if (!r.ok) { setError(r.error); return; }
    setIssued({ username: r.value.username, temp: r.value.temporary_password, kind: "new" });
    setName("");
    void load();
  };
  const reset = async (u: string) => {
    setAsking(null); setError(null);
    const r = await resetAccount(u);
    if (!r.ok) { setError(r.error); return; }
    setIssued({ username: u, temp: r.value.temporary_password, kind: "reset" });
    void load();
  };

  return (
    <section className="set-sec set-admin" aria-labelledby="set-admin-h">
      <h2 className="set-h" id="set-admin-h">계정 관리</h2>
      <p className="set-sub set-sub--lead">
        계정은 여기서만 만듭니다 — 로그인하면 계좌·주문 화면이 열리기 때문에 누구나 가입하는 길은 두지 않았습니다.
      </p>
      <form className="set-card set-issue-form" onSubmit={issue} noValidate>
        <label className="set-field">
          <span className="set-label">새 계정 아이디</span>
          <input className="set-input" name="new-username" autoComplete="off" spellCheck={false}
                 value={name} onChange={(e) => setName(e.target.value.trim())} aria-invalid={name.length > 0 && !nameOk} />
          {name.length > 0 && !nameOk ? <span className="set-hint">영문·숫자·. _ - 만, 64자까지 쓸 수 있습니다.</span> : null}
        </label>
        <div className="set-row">
          <span className="set-label set-label--row" id="set-role-l">역할</span>
          <div className="set-seg set-seg--2" role="group" aria-labelledby="set-role-l">
            {(["analyst", "admin"] as const).map((k) => (
              <button key={k} type="button" className={`set-seg-b${role === k ? " on" : ""}`} aria-pressed={role === k}
                      onClick={() => setRole(k)}>{ROLE_KO[k]}</button>
            ))}
          </div>
        </div>
        {role === "admin" ? <p className="set-sub">관리자는 실주문·실행 모드·다른 계정까지 다룰 수 있습니다.</p> : null}
        {error ? <p className="set-error" role="alert">{error}</p> : null}
        <button type="submit" className="set-btn set-btn--primary set-issue" disabled={!nameOk || busy}>
          {busy ? "만드는 중…" : "계정 만들기"}
        </button>
      </form>

      {issued ? <IssuedCard issued={issued} onClose={() => setIssued(null)} /> : null}

      <div className="set-card set-list">
        {loadError ? <p className="set-error" role="alert">계정 목록 조회 실패 — {loadError}</p>
          : rows === null ? <p className="set-sub">조회 중</p>
          : rows.map((a) => (
            <div key={a.username} className="set-acct" data-username={a.username}>
              <div className="set-acct-t">
                <strong className="set-acct-name">{a.username}{a.username === me ? <span className="set-sub"> (나)</span> : null}</strong>
                <span className="set-acct-meta">
                  <span className="set-chip">{ROLE_KO[a.role] ?? a.role}</span>
                  {a.must_change_password ? <span className="set-chip set-chip--warn">바꿀 차례</span>
                    : day(a.password_changed_at) ? <span className="set-sub">바꾼 날 {day(a.password_changed_at)}</span>
                    : <span className="set-sub">바꾼 적 없음</span>}
                </span>
              </div>
              {asking === a.username ? (
                <div className="set-confirm" role="group" aria-label={`${a.username} 비밀번호 초기화 확인`}>
                  <span className="set-sub">그 사람의 로그인이 모두 끝납니다.</span>
                  <button type="button" className="set-btn set-btn--sm set-btn--danger" onClick={() => void reset(a.username)}>초기화</button>
                  <button type="button" className="set-btn set-btn--sm" onClick={() => setAsking(null)}>취소</button>
                </div>
              ) : (
                <button type="button" className="set-btn set-btn--sm set-reset" onClick={() => setAsking(a.username)}>비밀번호 초기화</button>
              )}
            </div>
          ))}
      </div>
    </section>
  );
}

function IssuedCard({ issued, onClose }: { issued: Issued; onClose: () => void }) {
  const [copied, setCopied] = useState<"idle" | "ok" | "fail">("idle");
  const copy = async () => {
    try { await navigator.clipboard.writeText(issued.temp); setCopied("ok"); } catch { setCopied("fail"); }
  };
  return (
    <div className="set-card set-issued" role="status">
      <p className="set-strong">
        {issued.kind === "new" ? `${issued.username} 계정을 만들었습니다` : `${issued.username} 비밀번호를 초기화했습니다`}
      </p>
      <p className="set-label">임시 비밀번호</p>
      <div className="set-issued-row">
        <code className="set-issued-pw">{issued.temp}</code>
        <button type="button" className="set-btn set-btn--sm set-copy" onClick={() => void copy()}>
          {copied === "ok" ? "복사했습니다" : "복사"}
        </button>
      </div>
      {copied === "fail" ? <p className="set-error">복사 실패 — 글자를 직접 골라 복사하십시오.</p> : null}
      <p className="set-sub">
        이 창을 닫으면 다시 볼 수 없습니다. 받을 사람에게 안전하게 전하십시오 — 처음 로그인하면 비밀번호를 바꾸게 됩니다.
      </p>
      <button type="button" className="set-btn set-issued-close" onClick={onClose}>다 전했습니다 · 닫기</button>
    </div>
  );
}
