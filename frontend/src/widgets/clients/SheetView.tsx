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
      {session.kind === "loading" ? <p className="tx-sec-sub" aria-busy="true">계정 확인 중</p>
        : session.kind === "unknown" ? <RetryFail title="계정 정보 확인 실패" onRetry={() => void retry()}>{session.reason}</RetryFail>
        : session.kind === "signed_out" ? (
          <section className="tx-sec cl-signed-out">
            <p className="cl-strong">로그인하면 이 한 장을 조회할 수 있습니다.</p>
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
  if (q.isLoading) return <p className="tx-sec-sub" aria-busy="true">한 장 로딩 중</p>;
  if (q.isError) {
    return (
      <section className="tx-sec">
        <p className="cl-strong">이 한 장 열기 실패 — {(q.error as Error).message}</p>
        <Link href="/clients" className="tx-btn tx-btn--sub">고객으로</Link>
      </section>
    );
  }
  const x = q.data!;
  async function remove() {
    if (!window.confirm("이 한 장을 삭제하시겠습니까? 고객에게 보여 준 적 없는 한 장만 지울 수 있습니다.")) return;
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
            <button type="button" className="tx-btn tx-btn--sub cs-delete" onClick={() => void remove()}>삭제</button>
          )}
        </div>
        {x.shared && <p className="cs-tools-note">고객에게 공유한 한 장이라 삭제할 수 없습니다 — 공유 내역이 기록으로 남습니다.</p>}
        {err && <p className="cl-err" role="alert">{err}</p>}
      </div>
      <ClientSheet sheet={x.sheet} />
      <SharePanel cid={cid} sid={sid} archived={x.client_archived} />
      <SheetAsk title="고객 AI 미리 묻기" sub="고객이 이 한 장에 질의했을 때의 응답을 사전 확인합니다. 근거는 이 한 장에 기재된 내용뿐이며, 투자 판단은 답하지 않습니다."
                ask={(question, prev) => askSheet(cid, sid, question, prev)} />
    </>
  );
}
