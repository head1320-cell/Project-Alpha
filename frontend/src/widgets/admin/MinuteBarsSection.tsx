"use client";
/**
 * 데이터 상태 › 분봉 적재 (ADR 006 §7 — 분봉 적재 범위를 '백테스트 › 분봉 규칙' 안에만 두지 않고 적재 현황 화면에도 둔다)
 * ==========================================================================
 * 분봉은 DB 표가 아니라 일파일이다 — '표별 적재'에 섞지 않고 절을 따로 둔다. 같은 문(`GET /api/v1/intraday/coverage`)을 읽는다.
 * ★값이 없으면 0 이 아니라 사유★: 로그인 전에는 묻지 않고 그렇게 말하고, 적재가 없으면 서버 사유를, 읽지 못하면 실패를 보인다.
 * ★합성이면 합성이라고 적는다★ — 모의 모드의 수집기가 만든 분봉은 '적재됨'으로만 읽히면 안 된다.
 */
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { getCoverage, type Coverage } from "@/entities/intraday";
import { useSession } from "@/entities/session";
import { num } from "@/shared/lib/krFormat";
import { Notice, RetryFail } from "@/shared/ui/tx";

class Refused extends Error {}

async function recent(): Promise<Coverage> {
  const r = await getCoverage();                 // 기간을 주지 않으면 서버가 최근 한 달을 답한다
  if (!r.ok) throw new Refused(r.error);
  return r.value;
}

function Loaded({ c }: { c: Coverage }) {
  const s = c.summary;
  if (c.empty) return <p className="dsx-reason" data-server>{c.empty.message}</p>;
  const facts = [
    `달력 ${num(s.calendar_days)}일 가운데 적재된 날 ${num(s.loaded_days)}일`, `봉 ${num(s.bars)}개`,
    ...(s.blocked_days ? [`운영 게이트가 막은 날 ${num(s.blocked_days)}일`] : []),
    ...(s.unreadable_days ? [`읽지 못한 날 ${num(s.unreadable_days)}일`] : []),
    ...(s.not_checked_days ? [`아직 확인하지 않은 날 ${num(s.not_checked_days)}일`] : []),
    `결함 ${num(s.defect_total)}건`,
  ];
  return (
    <>
      <p className="dsx-reason dsx-minute-read">{c.from} ~ {c.to} · {facts.join(" · ")}</p>
      <dl className="dsx-minute-src">
        <div data-k="kis"><dt>실제 분봉(제공자 응답)</dt><dd>{num(s.sources.kis)}행</dd></div>
        <div data-k="synthetic"><dt>합성 분봉(모의 모드)</dt><dd>{num(s.sources.synthetic)}행</dd></div>
        <div data-k="unknown"><dt>출처 미상</dt><dd>{num(s.sources.unknown)}행</dd></div>
      </dl>
      {s.sources.synthetic > 0 ? (
        <Notice tone="practice" title="합성 분봉이 섞여 있습니다.">
          모의 모드에서 만든 분봉입니다. 계산 장치를 확인하는 용도이며 예측력이나 수익의 증거가 아닙니다.
        </Notice>
      ) : null}
    </>
  );
}

export function MinuteBarsSection() {
  const { session } = useSession();
  const signedIn = session.kind === "signed_in";
  const q = useQuery({ queryKey: ["intraday", "coverage", "recent"], queryFn: recent, enabled: signedIn, staleTime: 0, retry: false });
  return (
    <section className="tx-sec dsx-minute" aria-labelledby="dsx-min-h">
      <h2 id="dsx-min-h" className="tx-sec-t">분봉 적재</h2>
      <p className="tx-sec-sub">최근 한 달의 분봉 일파일입니다. 분봉은 표가 아니라 일파일로 적재되며 ‘백테스트 › 분봉 규칙’이 읽습니다.</p>
      {session.kind === "loading" ? <p className="dsx-wait">계정 확인 중</p>
        : !signedIn ? <p className="dsx-reason">로그인하면 분봉 적재 범위를 조회할 수 있습니다.</p>
        : q.isError ? <RetryFail title="분봉 적재 범위 조회 실패" onRetry={() => void q.refetch()}><span data-server>{q.error.message}</span></RetryFail>
        : !q.data ? <p className="dsx-wait">분봉 적재 범위 조회 중</p>
        : <Loaded c={q.data} />}
      <p className="dsx-minute-go"><Link href="/backtest/intraday">백테스트 › 분봉 규칙에서 날짜별로 보기</Link></p>
    </section>
  );
}
