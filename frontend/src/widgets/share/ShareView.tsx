"use client";
/**
 * 고객 화면 `/c` (CF 3부 PB6) — 담당 PB 가 보낸 주소 + PIN 으로 내 포트폴리오 한 장을 보고 묻는다. ★유통 관문 뒤★.
 * ==========================================================================
 * 메뉴 없는 단독 화면(`TerminalShell` 의 단독 목록) · 검색에 걸리지 않고(noindex) 리퍼러를 보내지 않는다(페이지 메타).
 * 주소의 조각(`#t=…`)에서 토큰을 읽어 이 탭에만 두고(sessionStorage) 주소창에서 지운다 — 화면을 보는 사람·방문 기록에 남지 않게.
 * 세션은 기억에만(새로 고치면 PIN 을 다시). 고객에게는 중립 문장만 — 관문·인가 같은 운영 사유는 보이지 않는다.
 *   401 → PIN 다시(주소·PIN 이 맞지 않음, 또는 세션 시간이 지남) · 403 → 지금은 열 수 없음 · 410·423 → 서버 문장 그대로(담당 PB 에게)
 */
import { useEffect, useState, type FormEvent } from "react";
import { ClientSheet, SheetAsk, askShared, openShare, readShared, type Sheet } from "@/entities/pb-client";

const KEY = "pa.share.t";
const CLOSED = "담당 PB 에게 물어 주세요 — 다시 열리면 같은 주소와 PIN 으로 볼 수 있어요.";
const EXPIRED = "시간이 지나 다시 PIN 을 넣어 주세요.";

type Phase =
  | { kind: "boot" }
  | { kind: "no_token" }
  | { kind: "pin"; note?: string }
  | { kind: "open"; session: string; sheet: Sheet; until: string | null }
  | { kind: "stop"; title: string; why: string };

function readToken(): string | null {
  const m = /(?:^#|&)t=([A-Za-z0-9_-]+)/.exec(window.location.hash);
  if (m) {
    try { sessionStorage.setItem(KEY, m[1]); } catch { /* 저장 못 하면 이번 화면에서만 쓴다 */ }
    window.history.replaceState(null, "", window.location.pathname + window.location.search);
    return m[1];
  }
  try { return sessionStorage.getItem(KEY); } catch { return null; }
}

/** 멈출 실패면 멈춤 화면, 아니면(401) null. */
function stopFor(status: number, error: string): Phase | null {
  if (status === 403) return { kind: "stop", title: "지금은 열 수 없어요", why: CLOSED };
  if (status === 410) return { kind: "stop", title: "끝난 주소예요", why: error };
  if (status === 423) return { kind: "stop", title: "잠긴 주소예요", why: error };
  return null;
}

export function ShareView() {
  const [token, setToken] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>({ kind: "boot" });
  const [pin, setPin] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    const t = readToken();
    setToken(t);
    setPhase(t ? { kind: "pin" } : { kind: "no_token" });
  }, []);

  async function open(e: FormEvent) {
    e.preventDefault();
    if (!token || busy || pin.length !== 6) return;
    setBusy(true);
    setErr(null);
    const s = await openShare(token, pin);
    if (!s.ok) {
      setBusy(false);
      const stop = stopFor(s.status, s.error);
      if (stop) setPhase(stop);
      else setErr(s.status === 401 ? s.error : "지금은 열지 못했어요 — 잠시 뒤에 다시 해 주세요.");
      return;
    }
    const got = await readShared(s.value.session);
    setBusy(false);
    setPin("");
    if (!got.ok) {
      setPhase(stopFor(got.status, got.error) ?? { kind: "pin", note: EXPIRED });
      return;
    }
    setPhase({ kind: "open", session: s.value.session, sheet: got.value.sheet, until: got.value.link_expires_at });
  }

  const ask = async (question: string, prev: { question: string; answer: string } | null) => {
    if (phase.kind !== "open") return { ok: false as const, status: 0, error: EXPIRED };
    const r = await askShared(phase.session, question, prev);
    if (!r.ok) {
      const stop = stopFor(r.status, r.error);
      if (stop) setPhase(stop);
      else if (r.status === 401) setPhase({ kind: "pin", note: EXPIRED });
    }
    return r;
  };

  return (
    <div className="sv-page">
      <header className="sv-head">
        <p className="sv-brand">내 포트폴리오 한 장</p>
        {phase.kind === "open" && (
          <button type="button" className="sv-close" onClick={() => setPhase({ kind: "pin" })}>닫기</button>
        )}
      </header>
      <main className="sv-main">
        {phase.kind === "boot" && <p className="sv-sub" aria-busy="true">주소를 읽는 중이에요.</p>}
        {phase.kind === "no_token" && (
          <section className="sv-card sv-missing">
            <h1 className="sv-h1">주소가 완전하지 않아요</h1>
            <p className="sv-sub">담당 PB 가 보낸 주소를 그대로 열어 주세요 — 주소 끝까지 함께 있어야 열려요.</p>
          </section>
        )}
        {phase.kind === "pin" && (
          <section className="sv-card sv-pin-card">
            <h1 className="sv-h1">PIN 을 넣어 주세요</h1>
            <p className="sv-sub">담당 PB 에게 따로 받은 숫자 6자리예요.</p>
            <form className="sv-pin-form" onSubmit={(e) => void open(e)}>
              <input className="sv-pin" value={pin} inputMode="numeric" autoComplete="one-time-code" maxLength={6}
                     aria-label="PIN 6자리" placeholder="숫자 6자리"
                     onChange={(e) => setPin(e.target.value.replace(/\D/g, "").slice(0, 6))} />
              <button type="submit" className="tx-btn tx-btn--main sv-open" disabled={busy || pin.length !== 6}>
                {busy ? "여는 중" : "열기"}
              </button>
            </form>
            {phase.note && <p className="sv-note" role="status">{phase.note}</p>}
            {err && <p className="sv-err" role="alert">{err}</p>}
          </section>
        )}
        {phase.kind === "stop" && (
          <section className="sv-card sv-stop" role="status">
            <h1 className="sv-h1">{phase.title}</h1>
            <p className="sv-sub">{phase.why}</p>
          </section>
        )}
        {phase.kind === "open" && (
          <>
            {phase.until && <p className="sv-until">이 주소는 {phase.until.slice(0, 10)}까지 열려요.</p>}
            <ClientSheet sheet={phase.sheet} audience="client" />
            <SheetAsk title="이 한 장에 묻기" sub="한 장에 적힌 내용으로만 답해요. 투자 판단은 담당 PB와 상담해 주세요." ask={ask} />
          </>
        )}
      </main>
      <footer className="sv-foot">이 화면은 담당 PB 가 보낸 주소와 PIN 으로만 열려요. 주소와 PIN 을 다른 사람과 나누지 마세요.</footer>
    </div>
  );
}
