"use client";
/**
 * 고객 한 장 — PB 화면 (CF 3부 PB4) · `/clients/<cid>/sheets/<sid>`.
 * ==========================================================================
 * 한 장(`ClientSheet` — 서버가 다시 계산해 옮긴 것) · 인쇄(브라우저의 인쇄 → PDF 로 저장도 같은 길) · 고객 AI 미리 묻기(근거는 이 한 장의 줄뿐 ·
 * 투자 판단은 고객용 고정 문장) · 지우기(고객에게 보여 준 적 없는 것만 — 서버가 판정) · 고객 주소(PB6 — 유통 관문 뒤).
 * 인쇄하면 메뉴·도구·주소·묻기는 숨고 한 장만 남는다.
 */
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ClientSheet, SheetAsk, askSheet, deleteSheet, getSheet } from "@/entities/pb-client";
import { useSession } from "@/entities/session";
import type { Result } from "@/shared/api/result";
import { loginHref } from "@/shared/lib/nextPath";
import { RetryFail } from "@/shared/ui/tx";
import { SharePanel } from "./SharePanel";

const unwrap = <T,>(fn: () => Promise<Result<T>>) => async (): Promise<T> => {
  const r = await fn();
  if (!r.ok) throw new Error(r.error);
  return r.value;
};

export function SheetView({ cid, sid }: { cid: string; sid: string }) {
  const { session, retry } = useSession();
  const here = `/clients/${cid}/sheets/${sid}`;
  return (
    <div className="tx-page cs-page">
      {session.kind === "loading" ? <p className="tx-sec-sub" aria-busy="true">계정을 확인하는 중이에요.</p>
        : session.kind === "unknown" ? <RetryFail title="계정 정보를 확인하지 못했어요" onRetry={() => void retry()}>{session.reason}</RetryFail>
        : session.kind === "signed_out" ? (
          <section className="tx-sec cl-signed-out">
            <p className="cl-strong">로그인하면 이 한 장을 볼 수 있어요.</p>
            <Link href={loginHref(here)} className="tx-btn tx-btn--main">로그인</Link>
          </section>
        ) : <Body cid={cid} sid={sid} />}
    </div>
  );
}

function Body({ cid, sid }: { cid: string; sid: string }) {
  const router = useRouter();
  const q = useQuery({ queryKey: ["pb-sheet", cid, sid], queryFn: unwrap(() => getSheet(cid, sid)), staleTime: 0, retry: false });
  const [err, setErr] = useState<string | null>(null);
  const back = `/clients?client=${encodeURIComponent(cid)}`;
  if (q.isLoading) return <p className="tx-sec-sub" aria-busy="true">한 장을 여는 중이에요.</p>;
  if (q.isError) {
    return (
      <section className="tx-sec">
        <p className="cl-strong">이 한 장을 열지 못했어요 — {(q.error as Error).message}</p>
        <Link href="/clients" className="tx-btn tx-btn--sub">고객으로</Link>
      </section>
    );
  }
  const x = q.data!;
  async function remove() {
    if (!window.confirm("이 한 장을 지울까요? 고객에게 보여 준 적 없는 한 장만 지울 수 있어요.")) return;
    const r = await deleteSheet(cid, sid);
    if (!r.ok) { setErr(r.error); return; }
    router.replace(back);
  }
  return (
    <>
      <div className="cs-tools">
        <Link href={back} className="cs-back">← {x.client_alias}</Link>
        <div className="cs-tools-act">
          <button type="button" className="tx-btn tx-btn--main cs-print" onClick={() => window.print()}>인쇄 · PDF로 저장</button>
          {!x.shared && !x.client_archived && (
            <button type="button" className="tx-btn tx-btn--sub cs-delete" onClick={() => void remove()}>지우기</button>
          )}
        </div>
        {x.shared && <p className="cs-tools-note">고객에게 보여 준 한 장이라 지울 수 없어요 — 무엇을 보여 줬는지가 남아요.</p>}
        {err && <p className="cl-err" role="alert">{err}</p>}
      </div>
      <ClientSheet sheet={x.sheet} />
      <SharePanel cid={cid} sid={sid} archived={x.client_archived} />
      <SheetAsk title="고객 AI 미리 묻기" sub="고객이 이 한 장에 물으면 어떻게 답하는지 미리 봐요. 근거는 이 한 장에 적힌 줄뿐이고, 투자 판단은 답하지 않아요."
                ask={(question, prev) => askSheet(cid, sid, question, prev)} />
    </>
  );
}
