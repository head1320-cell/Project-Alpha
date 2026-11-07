"use client";
/**
 * /login — 메뉴 없는 단독 한 화면 (BU8b · 사용자 결정: "메뉴 없는 단독 한 화면" · "폼 + '로그인이 여는 것' 지도")
 * ==========================================================================
 * ★이 화면은 계정을 만들지 않는다★ — 가입 표면은 만들지 않기로 했다(BS1 부터 관리자가 /settings 에서 발급).
 * 하는 일은 자격 증명을 `POST /api/v1/auth/login` 에 넘기고(본문 `{username, password}` 그대로) 토큰을 보관하는 것뿐이다.
 * 서버 권한·역할·로그인 동작은 바꾸지 않는다(사용자별 증권 계좌 연결은 별도 설계 BV).
 *
 * ★실패를 사람 말로, 원문은 지우지 않고 '원래 사유 보기' 안에★
 *  · 401 → "아이디 또는 비밀번호가 맞지 않아요." — 서버가 둘을 가르지 않는 것은 계정 열거를 막는 **의도**라 화면도 가르지 않는다.
 *  · 422(형식) → "아이디와 비밀번호를 다시 확인해 주세요." — 서버 detail 은 배열이라 `extractErrorDetail` 로 글자로 옮겨 원문 칸에.
 *  · 502/504(프록시) · 네트워크 실패 → "서버에 닿지 못했어요." — 502 원문에는 내부 백엔드 주소가 들어 있어 보이는 글에 두지 않는다.
 *  · 그 밖 → "로그인하지 못했어요(HTTP n)." + 원문.
 * ★돌아가기★ `?next=` 가 이 앱 안의 경로일 때만 그리로(`shared/lib/nextPath.ts`) — 아니면 홈(`/dashboard`).
 * 바깥 주소로 보내는 열린 리다이렉트를 만들지 않는다. 임시 비밀번호로 들어왔으면 먼저 바꾸는 칸으로(BS1, 그대로).
 * 계약: `input[name=username]`·`input[name=password]`·`.login-field__input` · `.login-submit` · `.login-error`(role=alert) —
 * settings·profile 스펙이 집는다.
 */
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { ROLE_KO, useSession } from "@/entities/session";
import { API_BASE, extractErrorDetail } from "@/shared/api/apiBase";
import { setToken } from "@/shared/api/authToken";
import { safeNext } from "@/shared/lib/nextPath";

import { AccessMap } from "./AccessMap";

type Fail = { say: string; raw: string | null };

function failOf(status: number | null, body: unknown): Fail {
  if (status === null) return { say: "서버에 닿지 못했어요. 잠시 뒤 다시 해 주세요.", raw: null };
  const raw = extractErrorDetail(body, "") || null;
  if (status === 401) return { say: "아이디 또는 비밀번호가 맞지 않아요.", raw };
  if (status === 422) return { say: "아이디와 비밀번호를 다시 확인해 주세요.", raw };
  if (status === 502 || status === 504) return { say: "서버에 닿지 못했어요. 잠시 뒤 다시 해 주세요.", raw };
  return { say: `로그인하지 못했어요(HTTP ${status}).`, raw };
}

function Brand() {
  return (
    <Link href="/" className="lg-brand" aria-label="Project Alpha 첫 화면">
      <span className="lg-logo" aria-hidden>
        <svg viewBox="0 0 24 24"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" /></svg>
      </span>
      Project Alpha
    </Link>
  );
}

export function LoginView() {
  const params = useSearchParams();
  const next = safeNext(params.get("next"));
  const { session } = useSession();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [fail, setFail] = useState<Fail | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setFail(null);
    let res: Response;
    try {
      res = await fetch(`${API_BASE}/api/v1/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
    } catch {
      setFail(failOf(null, null));
      setBusy(false);
      return;
    }
    const body = await res.json().catch(() => null);
    if (!res.ok || typeof body?.access_token !== "string") {
      setFail(res.ok ? { say: "로그인 응답에 토큰이 없어요.", raw: null } : failOf(res.status, body));
      setBusy(false);
      return;
    }
    setToken(body.access_token);
    // 관리자가 준 임시 비밀번호로 들어왔다 — 바꾸기 전에는 보호 화면이 열리지 않으니 곧장 바꾸는 칸으로(BS1).
    window.location.href = body.must_change_password === true ? "/settings#password" : next ?? "/dashboard";
  };

  return (
    <div className="lg">
      <header className="lg-head"><Brand /></header>
      <main className="lg-main">
        <form className="lg-form" onSubmit={submit} aria-busy={busy}>
          <h1 className="lg-h1">로그인</h1>
          <p className="lg-note">계정은 관리자에게 받아요. 따로 가입하는 곳은 없어요.</p>

          {session.kind === "signed_in" ? (
            <p className="lg-already" role="status">
              이미 <b>{session.username}</b>({ROLE_KO[session.role] ?? session.role}) 계정으로 로그인했어요.{" "}
              <Link href={next ?? "/dashboard"} className="lg-already-go">이어서 가기</Link>
            </p>
          ) : null}

          <label className="lg-field">
            <span className="lg-label">아이디</span>
            <input className="login-field__input lg-input" name="username" autoComplete="username" maxLength={64}
                   value={username} onChange={(e) => setUsername(e.target.value)} required autoFocus />
          </label>
          <label className="lg-field">
            <span className="lg-label">비밀번호</span>
            <input className="login-field__input lg-input" name="password" type="password" autoComplete="current-password"
                   value={password} onChange={(e) => setPassword(e.target.value)} required />
          </label>

          {fail ? (
            <div className="login-error lg-error" role="alert">
              <p className="lg-error-say">{fail.say}</p>
              {fail.raw ? (
                <details className="lg-raw">
                  <summary>원래 사유 보기</summary>
                  <p data-server>{fail.raw}</p>
                </details>
              ) : null}
            </div>
          ) : null}

          <button className="login-submit lg-submit" type="submit" disabled={busy}>
            {busy ? "확인하는 중이에요" : "로그인"}
          </button>

          <p className="lg-foot">
            로그인하지 않아도 연구 화면은 그대로 써요. <Link href="/dashboard" className="lg-home">홈으로</Link>
          </p>
        </form>
        <AccessMap />
      </main>
    </div>
  );
}
