"use client";

/**
 * /login — 최소 로그인 화면 (AC7)
 * ==========================================================================
 * 백엔드 P-1 이 돈·PII 라우트를 잠갔으므로 토큰을 받아 오는 자리가 필요하다.
 * ★이 화면은 계정을 만들지 않는다★ — 가입 표면은 만들지 않기로 했고(운영 조치 — BS1 부터 관리자가 /settings 에서 발급),
 * 여기서 하는 일은 자격 증명을 `POST /api/v1/auth/login` 에 넘기고 토큰을 보관하는
 * 것뿐이다.
 *
 * ★실패 사유를 지어내지 않는다★ — 서버가 "아이디 또는 비밀번호가 올바르지 않습니다"
 * 하나로만 답하는 것은 계정 열거를 막기 위한 **의도**이고, 화면이 그것을 "비밀번호가
 * 틀렸습니다" 로 바꿔 말하면 없는 사실을 만든다. 서버 문구를 그대로 보여 준다.
 */

import { useState } from "react";

import { API_BASE } from "@/shared/api/apiBase";
import { setToken } from "@/shared/api/authToken";

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/v1/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      const body = await res.json().catch(() => null);
      if (!res.ok) {
        // 서버가 준 사유를 그대로 — 없으면 "모른다" 고 적는다.
        setError(body?.detail ?? `로그인 실패 (HTTP ${res.status}) — 사유를 받지 못했어요.`);
        return;
      }
      setToken(body.access_token);
      // 관리자가 준 임시 비밀번호로 들어왔다 — 바꾸기 전에는 보호 화면이 열리지 않으니 곧장 바꾸는 칸으로(BS1).
      window.location.href = body.must_change_password === true ? "/settings#password" : "/";
    } catch {
      setError("서버에 연결하지 못했어요 — 자격 증명 문제인지 여부는 알 수 없어요.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-page">
      <form className="login-card" onSubmit={submit}>
        <h1 className="login-card__title">로그인</h1>
        <p className="login-card__note">
          계좌·주문·감사 화면은 인증된 사용자만 볼 수 있어요. 연구·백테스트 화면은
          로그인 없이 그대로 동작해요.
        </p>
        <p className="login-card__note">계정은 관리자에게 받아요 — 따로 가입하는 곳은 없어요.</p>

        <label className="login-field">
          <span className="login-field__label">아이디</span>
          <input
            className="login-field__input"
            name="username"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
          />
        </label>

        <label className="login-field">
          <span className="login-field__label">비밀번호</span>
          <input
            className="login-field__input"
            name="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>

        {error && <p className="login-error" role="alert">{error}</p>}

        <button className="login-submit" type="submit" disabled={busy}>
          {busy ? "확인 중…" : "로그인"}
        </button>
      </form>
    </div>
  );
}
