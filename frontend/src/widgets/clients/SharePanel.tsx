"use client";
/**
 * 고객 주소 (CF 3부 PB6) — PB 한 장 화면의 판. ★유통 관문 뒤★.
 * ==========================================================================
 * 관문이 닫혀 있으면 서버 사유 + 빠진 인가 기록 칸을 보이고 만들기·잠김 풀기·한 장 바꾸기를 끈다(서버도 403 으로 막는다 — 화면은 미리 말할 뿐).
 * 끄기와 목록은 관문과 무관하게 늘 된다. ★주소는 만들 때 한 번만 보인다★ — 서버가 토큰을 다시 내지 않는다. PIN 은 주소와 다른 길로.
 */
import { useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  LICENSE_PLAIN, SHARE_DAYS, createLink, listLinks, reopenLink, revokeLink, switchLinkSheet,
  type ShareLink, type ShareLinkState,
} from "@/entities/pb-client";
import type { Result } from "@/shared/api/result";

const STATE_PLAIN: Record<ShareLinkState, string> = {
  open: "열림", locked: "잠김", expired: "만료", revoked: "꺼짐", archived: "보관한 고객",
};
const ymd = (iso: string | null) => (iso ? iso.slice(0, 10) : "—");

const unwrap = <T,>(fn: () => Promise<Result<T>>) => async (): Promise<T> => {
  const r = await fn();
  if (!r.ok) throw new Error(r.error);
  return r.value;
};

function Row({ l, sid, closed, act }: {
  l: ShareLink; sid: string; closed: boolean; act: (what: "revoke" | "reopen" | "switch", l: ShareLink) => void;
}) {
  const live = l.state === "open" || l.state === "locked";
  const when = l.state === "revoked" ? `끈 날 ${ymd(l.revoked_at)}` : `${l.state === "expired" ? "만료한 날" : "만료"} ${ymd(l.expires_at)}`;
  return (
    <li className="cs-share-row" data-link-id={l.link_id} data-state={l.state}>
      <div className="cs-share-row-main">
        <span className="cs-share-state">{STATE_PLAIN[l.state]}</span>
        <span className="cs-share-title">{l.sheet_id === sid ? "이 한 장" : (l.sheet_title ?? l.sheet_id)}</span>
      </div>
      <p className="cs-share-row-sub">
        만든 날 {ymd(l.created_at)} · {when} · 열람 {l.views}번{l.last_viewed_at ? ` · 마지막 ${ymd(l.last_viewed_at)}` : ""}
        {l.failures ? ` · PIN 틀림 ${l.failures}번` : ""}
      </p>
      <div className="cs-share-acts">
        {l.state === "locked" && (
          <button type="button" className="tx-btn tx-btn--sub cs-share-btn cs-share-reopen" disabled={closed} onClick={() => act("reopen", l)}>잠김 풀기</button>
        )}
        {live && l.sheet_id !== sid && (
          <button type="button" className="tx-btn tx-btn--sub cs-share-btn cs-share-switch" disabled={closed} onClick={() => act("switch", l)}>이 한 장으로 바꾸기</button>
        )}
        {l.state !== "revoked" && l.state !== "expired" && (
          <button type="button" className="tx-btn tx-btn--sub cs-share-btn cs-share-revoke" onClick={() => act("revoke", l)}>끄기</button>
        )}
      </div>
    </li>
  );
}

export function SharePanel({ cid, sid, archived }: { cid: string; sid: string; archived: boolean }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["pb-links", cid], queryFn: unwrap(() => listLinks(cid)), staleTime: 0, retry: false });
  const [pin, setPin] = useState("");
  const [days, setDays] = useState<number>(30);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [made, setMade] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const refresh = () => Promise.all([qc.invalidateQueries({ queryKey: ["pb-links", cid] }),
    qc.invalidateQueries({ queryKey: ["pb-sheet", cid, sid] })]);
  const gate = q.data?.gate;
  const closed = gate?.state !== "allowed";

  async function make(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setErr(null);
    const r = await createLink(cid, { sheet_id: sid, pin, days });
    setBusy(false);
    if (!r.ok) { setErr(r.error); void refresh(); return; }
    setPin("");
    setCopied(false);
    setMade(`${window.location.origin}/c#t=${r.value.token}`);
    void refresh();
  }

  async function act(what: "revoke" | "reopen" | "switch", l: ShareLink) {
    if (what === "revoke" && !window.confirm("이 주소를 끌까요? 고객이 바로 볼 수 없게 돼요.")) return;
    setErr(null);
    const r = what === "revoke" ? await revokeLink(cid, l.link_id)
      : what === "reopen" ? await reopenLink(cid, l.link_id) : await switchLinkSheet(cid, l.link_id, sid);
    if (!r.ok) setErr(r.error);
    void refresh();
  }

  async function copy() {
    if (!made) return;
    try { await navigator.clipboard.writeText(made); setCopied(true); } catch { setCopied(false); }
  }

  return (
    <section className="cs-share" aria-label="고객 주소">
      <h2 className="cs-h2">고객 주소</h2>
      <p className="cs-sub">고객이 이 한 장을 보고 묻도록 주소를 만들어요. 고객은 주소와 PIN 으로 열고, 언제든 끌 수 있어요.</p>
      {q.isLoading && <p className="cs-sub" aria-busy="true">주소 목록을 읽는 중이에요.</p>}
      {q.isError && <p className="cl-err" role="alert">주소 목록을 읽지 못했어요 — {(q.error as Error).message}</p>}
      {gate && closed && (
        <div className="cs-share-blocked" role="note">
          <p className="cs-share-blocked-why">유통 관문이 닫혀 있어 지금은 고객 주소를 만들 수 없어요.</p>
          {gate.reason && <p className="cs-share-blocked-reason">{gate.reason}</p>}
          {gate.missing.length > 0 && (
            <p className="cs-share-missing">빠진 인가 기록 — {gate.missing.map((m) => LICENSE_PLAIN[m] ?? m).join(" · ")}</p>
          )}
        </div>
      )}
      {gate && !closed && archived && <p className="cs-sub">보관한 고객이라 새 주소를 만들 수 없어요.</p>}
      {gate && (
        <form className="cs-share-form" onSubmit={make}>
          <label className="cs-share-field">
            <span className="cs-share-label">PIN 6자리</span>
            <input className="cs-share-pin" value={pin} inputMode="numeric" autoComplete="off" maxLength={6} placeholder="숫자 6자리"
                   onChange={(e) => setPin(e.target.value.replace(/\D/g, "").slice(0, 6))} disabled={closed || archived} />
          </label>
          <label className="cs-share-field">
            <span className="cs-share-label">열어 둘 기간</span>
            <select className="cs-share-days" value={days} onChange={(e) => setDays(Number(e.target.value))} disabled={closed || archived}>
              {SHARE_DAYS.map((d) => <option key={d} value={d}>{d}일</option>)}
            </select>
          </label>
          <button type="submit" className="tx-btn tx-btn--main cs-share-make" disabled={closed || archived || busy || pin.length !== 6}>
            {busy ? "만드는 중" : "주소 만들기"}
          </button>
        </form>
      )}
      {gate && !closed && !archived && (
        <p className="cs-share-hint">PIN 은 주소와 다른 길(전화·대면)로 알려 주세요. 같은 숫자·차례대로·되풀이는 쓸 수 없고, 5번 틀리면 잠겨요.</p>
      )}
      {err && <p className="cl-err cs-share-err" role="alert">{err}</p>}
      {made && (
        <div className="cs-share-once" role="status">
          <p className="cs-share-once-t">주소를 만들었어요 — 이 주소는 지금 한 번만 보여요.</p>
          <div className="cs-share-url-row">
            <input className="cs-share-url" readOnly value={made} aria-label="고객 주소" onFocus={(e) => e.currentTarget.select()} />
            <button type="button" className="tx-btn tx-btn--sub cs-share-copy" onClick={() => void copy()}>{copied ? "복사했어요" : "복사"}</button>
          </div>
          <button type="button" className="cs-share-done" onClick={() => setMade(null)}>주소를 옮겼어요 — 닫기</button>
        </div>
      )}
      {q.data && q.data.links.length > 0 && (
        <ul className="cs-share-list">
          {q.data.links.map((l) => <Row key={l.link_id} l={l} sid={sid} closed={closed} act={(w, x) => void act(w, x)} />)}
        </ul>
      )}
      {q.data && q.data.links.length === 0 && <p className="cs-sub cs-share-empty">아직 만든 주소가 없어요.</p>}
    </section>
  );
}
