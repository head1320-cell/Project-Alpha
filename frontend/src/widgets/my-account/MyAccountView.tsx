"use client";
/**
 * 내 계좌 (BV9) — `/my-account`. 연결한 한국투자증권 계좌 하나를 골라 주문이 어디로 가는지 보고, 주문을 내고, 멈춘다.
 * ==========================================================================
 * ★답 문장 = 서버 값★(모드 · 비상 정지 · 연습용 게이트) — `entities/broker-account/orderPath.answerSentence`.
 * ★이 화면만의 한 가지 = 주문이 가는 길★(OrderPath) — 서버 `execute_signal` 의 순서를 네 역으로.
 * 세션 넷은 설정 화면과 같은 판정(`useSession`) · 임시 비밀번호면 계좌를 묻지 않는다(서버도 막는다).
 * 계좌는 `?account=` 로 고른다 — 주소의 계좌가 내 목록에 없으면 그렇다고 말하고 첫 계좌를 보인다(표시한 대체).
 * 계좌를 바꾸면 화면을 새로 세운다(key) — 쿼리 키도 계좌 id 를 품어서 옛 계좌 숫자가 새 계좌 자리에 남지 않는다.
 */
import Link from "next/link";
import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  answerSentence, getAccountKill, getAccountMode, getBalance, getReadiness, listAccountOrders, listBrokerAccounts,
  type BrokerAccount,
} from "@/entities/broker-account";
import { macroApi } from "@/entities/macro/api";
import { useSession } from "@/entities/session";
import { loginHref } from "@/shared/lib/nextPath";
import { priceWon } from "@/shared/lib/krFormat";
import { Answer, Notice, PageHead, RetryFail, type Chip } from "@/shared/ui/tx";
import { BalanceCard } from "./BalanceCard";
import { KillSheet } from "./KillSheet";
import { OrderForm } from "./OrderForm";
import { OrderList } from "./OrderList";
import { OrderPath, type Trace } from "./OrderPath";
import { unwrap } from "./parts";

const TITLE = "내 계좌";
const LEDE = "한국투자증권 계좌로 주문을 연습하고, 실계좌로 가기 전에 무엇이 남았는지 봐요.";

export function MyAccountView() {
  const { session, retry } = useSession();
  return (
    <div className="tx-page ma">
      {session.kind === "loading" ? (
        <><PageHead title={TITLE} lede={LEDE} /><p className="tx-sec-sub" aria-busy="true">계정을 확인하는 중이에요.</p></>
      ) : session.kind === "unknown" ? (
        <><PageHead title={TITLE} lede={LEDE} />
          <RetryFail title="계정 정보를 확인하지 못했어요" onRetry={() => void retry()}>{session.reason}</RetryFail></>
      ) : session.kind === "signed_out" ? (
        <><PageHead title={TITLE} lede={LEDE} />
          <section className="tx-sec ma-signed-out">
            <p className="ma-strong">로그인하면 내 계좌를 볼 수 있어요.</p>
            <p className="tx-sec-sub">계정은 관리자에게 받아요. 증권 계좌는 로그인한 뒤 설정에서 연결해요.</p>
            <Link href={loginHref("/my-account")} className="tx-btn tx-btn--main">로그인</Link>
          </section></>
      ) : session.mustChange ? (
        <><PageHead title={TITLE} lede={LEDE} />
          <section className="tx-sec ma-must" role="alert">
            <p className="ma-strong">비밀번호를 먼저 바꿔 주세요.</p>
            <p className="tx-sec-sub">관리자가 준 임시 비밀번호로는 계좌가 열리지 않아요.</p>
            <Link href="/settings#password" className="tx-btn tx-btn--main">비밀번호 바꾸러 가기</Link>
          </section></>
      ) : (
        <Accounts />
      )}
    </div>
  );
}

function Accounts() {
  const router = useRouter();
  const want = useSearchParams().get("account");
  const q = useQuery({ queryKey: ["broker-accounts"], queryFn: unwrap(listBrokerAccounts), staleTime: 0 });
  const list = q.data?.accounts ?? [];
  const found = list.find((a) => a.account_id === want) ?? null;
  const cur = found ?? list[0] ?? null;
  const pick = list.length > 1 && cur ? (
    <label className="ma-acct-l">
      <span className="ma-label">계좌</span>
      <select className="ma-input ma-acct" value={cur.account_id}
              onChange={(e) => router.replace(`/my-account?account=${encodeURIComponent(e.target.value)}`)}>
        {list.map((a) => <option key={a.account_id} value={a.account_id}>{a.label} ({a.is_paper ? "모의투자" : "실계좌"})</option>)}
      </select>
    </label>
  ) : null;

  return (
    <>
      <PageHead title={TITLE} lede={LEDE} actions={pick} />
      {q.isError ? (
        <RetryFail title="증권 계좌 목록을 불러오지 못했어요" onRetry={() => void q.refetch()}>{q.error.message}</RetryFail>
      ) : !q.data ? (
        <p className="tx-sec-sub" aria-busy="true">계좌 목록을 불러오는 중이에요.</p>
      ) : !cur ? (
        <section className="tx-sec ma-empty">
          <p className="ma-strong">연결한 증권 계좌가 없어요.</p>
          <p className="tx-sec-sub">설정의 ‘내 증권 계좌’에서 한국투자증권 계좌를 연결하면 여기서 주문을 연습할 수 있어요.</p>
          <Link href="/settings#broker" className="tx-btn tx-btn--main">설정에서 계좌 연결하기</Link>
        </section>
      ) : (
        <>
          {want !== null && !found ? (
            <div className="ma-fallback"><Notice tone="warn" title="주소의 계좌를 찾지 못해 첫 계좌를 보여 드려요." /></div>
          ) : null}
          <AccountView key={cur.account_id} acc={cur} />
        </>
      )}
    </>
  );
}

function AccountView({ acc }: { acc: BrokerAccount }) {
  const id = acc.account_id;
  const fresh = { staleTime: 0 } as const;
  const mode = useQuery({ queryKey: ["acct", id, "mode"], queryFn: unwrap(() => getAccountMode(id)), ...fresh });
  const kill = useQuery({ queryKey: ["acct", id, "kill"], queryFn: unwrap(() => getAccountKill(id)), ...fresh });
  const ready = useQuery({ queryKey: ["acct", id, "ready"], queryFn: unwrap(() => getReadiness(id)), ...fresh });
  const bal = useQuery({ queryKey: ["acct", id, "balance"], queryFn: unwrap(() => getBalance(id)), staleTime: 30_000 });
  const orders = useQuery({ queryKey: ["acct", id, "orders"], queryFn: unwrap(() => listAccountOrders(id)), ...fresh });
  const cs = useQuery({ queryKey: ["macro", "connection-status"], queryFn: () => macroApi.connectionStatus() });
  const practice = cs.data ? cs.data.mock_allowed : null;
  const [trace, setTrace] = useState<Trace | null>(null);
  const [sheet, setSheet] = useState<"kill" | "resolve" | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const k = kill.data ?? null;
  const b = bal.data;
  const chips: Chip[] = [
    { label: acc.is_paper ? "모의투자 계좌" : "실계좌", tone: acc.is_paper ? "plain" : "assumed" },
    ...(practice === true ? [{ label: "연습용 데이터", tone: "practice" as const, ev: "source" }]
      : cs.isError ? [{ label: "연습용인지 확인하지 못했어요", tone: "unknown" as const, ev: "source" }] : []),
  ];
  const figures = [
    { label: "평가 자산", value: b?.state === "ok" ? priceWon(b.evaluated_total) : "몰라요" },
    { label: "보유", value: b?.state === "ok" ? `${b.positions.length}종목` : "몰라요" },
    { label: "최근 주문", value: orders.data ? `${orders.data.count}건` : "몰라요" },
  ];
  const action = k?.active && k.event ? (
    <button type="button" className="tx-btn tx-btn--sub ma-kill-resolve-open" onClick={() => { setDone(null); setSheet("resolve"); }}>비상 정지 풀기</button>
  ) : k?.active ? null : (
    <button type="button" className="tx-btn ma-btn-danger ma-kill-open" onClick={() => { setDone(null); setSheet("kill"); }}>비상 정지</button>
  );
  const sentence = mode.isPending || kill.isPending
    ? `‘${acc.label}’ 상태를 확인하는 중이에요.`
    : answerSentence(acc.label, mode.data?.mode ?? null, k, practice);

  return (
    <>
      <Answer sentence={sentence} figures={figures} chips={chips} action={action} />
      {done ? <p className="ma-kill-done" role="status">{done}</p> : null}
      {mode.isError ? (
        <RetryFail title="실행 모드를 확인하지 못했어요" onRetry={() => void mode.refetch()}>{mode.error.message}</RetryFail>
      ) : null}
      <OrderPath acc={acc} mode={mode} kill={kill} ready={ready} practice={practice} trace={trace} />
      <div className="ma-grid">
        <BalanceCard q={bal} />
        <OrderForm accountId={id} mode={mode.isError ? null : mode.data?.mode} killActive={kill.isError ? null : kill.data?.active}
                   practice={practice} onTrace={setTrace}
                   holdings={b?.state === "ok" ? b.positions : []} cash={b?.state === "ok" ? b.cash_krw : null} />
        <OrderList accountId={id} q={orders} />
      </div>
      <KillSheet accountId={id} open={sheet} onClose={() => setSheet(null)}
                 onDone={(s) => { setSheet(null); setDone(s); setTrace(null); void kill.refetch(); void mode.refetch(); }} />
    </>
  );
}
