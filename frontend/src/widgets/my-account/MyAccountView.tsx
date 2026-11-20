"use client";
/**
 * 내 계좌 (BV9) — `/my-account`. 연결한 한국투자증권 계좌 하나를 골라 주문이 어디로 가는지 보고, 주문을 내고, 멈춘다.
 * ==========================================================================
 * ★답 문장 = 서버 값★(모드 · 비상 정지 · 연습용 게이트) — `entities/broker-account/orderPath.answerSentence`.
 * ★이 화면만의 한 가지 = 주문이 가는 길★(OrderPath) — 서버 `execute_signal` 의 순서를 네 역으로.
 * 세션 넷은 설정 화면과 같은 판정(`useSession`) · 임시 비밀번호면 계좌를 묻지 않는다(서버도 막는다).
 * 계좌는 `?account=` 로 고른다 — 주소의 계좌가 내 목록에 없으면 그렇다고 말하고 첫 계좌를 보인다(표시한 대체).
 * 계좌를 바꾸면 화면을 새로 세운다(key) — 쿼리 키도 계좌 id 를 품어서 옛 계좌 숫자가 새 계좌 자리에 남지 않는다.
 * 맨 아래 절 ‘규칙 가동’(W5b)은 캔버스가 남긴 가동 요청을 이 계좌에서 재생한다 — 새 화면이 아니라 이 화면 안이다(ADR 006 §7).
 * ★판 배치(G6 2a-2 · 계획 §10)★ — 넓은 창 머리 오른쪽의 '배치' 메뉴로 켜면 절 넷(주문 제출 · 최근 주문 · 잔고 · 규칙 가동)이 판이 되어 열 · 칸 · 탭에 선다
 * (`shared/ui/workspace` · `workspaceSpec.ts`). 상태와 처리기는 그대로이고 판은 같은 부품을 그린다 — 배치를 바꿔도 계좌로 가는 쓰기는 없다(시험이 건다).
 * 문장 띠(비상 정지 단추 · 모드 문장 · 칩)와 주문 전송 경로는 판이 아니라 판 밖이다: 탭 보기에서 문장 띠만 창 위에 붙고(늘 보인다) 경로는 판 위에서 페이지와 함께 구른다
 * (고정 띠는 1440 × 900 의 판을 62px 로 만들었다 — 잰 값 · 계획 §10.1). 끈 화면(기본 배치)은 지금 그대로 + '배치' 단추 하나(골든 `e2e/golden/account-dom.json`).
 */
import Link from "next/link";
import { useState, type CSSProperties, type ReactNode } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import {
  answerSentence, getAccountKill, getAccountMode, getBalance, getReadiness, listAccountOrders, listBrokerAccounts,
  type BrokerAccount,
} from "@/entities/broker-account";
import { macroApi } from "@/entities/macro/api";
import { useSession } from "@/entities/session";
import { ACCOUNT_MODES } from "@/shared/lib/modes";
import { loginHref } from "@/shared/lib/nextPath";
import { priceWon } from "@/shared/lib/krFormat";
import { useMediaQuery } from "@/shared/lib/useMediaQuery";
import { Answer, ModeSwitch, Notice, PageHead, RetryFail, type Chip } from "@/shared/ui/tx";
import { LayoutMenu, LayoutSheet, Workspace, useWorkspace, type WorkspaceState } from "@/shared/ui/workspace";
import { BalanceCard } from "./BalanceCard";
import { KillSheet } from "./KillSheet";
import { OrderForm } from "./OrderForm";
import { OrderList } from "./OrderList";
import { OrderPath, type Trace } from "./OrderPath";
import { RuleArming } from "./RuleArming";
import { unwrap } from "./parts";
import { useBoxHeight } from "./useBox";
import { ACCOUNT_QUERY, ACCOUNT_WS } from "./workspaceSpec";

const TITLE = "내 계좌";
const LEDE = "한국투자증권 계좌로 주문을 연습하고, 실계좌 전환 전 남은 요건을 확인합니다.";

/** 판 배치의 그리기 — 넓은 창(분봉과 같은 문턱)은 열 · 칸 · 탭, 좁은 창은 같은 상자 안 한 열로 쌓기. 끈 화면은 null. */
type WsMode = "tabs" | "stack" | null;
type AccountList = { accounts: BrokerAccount[] };

/** 머리 + 모드 전환 줄(ADR 006 §7) — 세션이 어떤 상태든 매매일지로 가는 길은 같은 자리에 있다. */
function Head({ actions }: { actions?: ReactNode }) {
  return (
    <>
      <PageHead title={TITLE} lede={LEDE} actions={actions} />
      <ModeSwitch label="내 계좌 모드" modes={ACCOUNT_MODES} current="/my-account" />
    </>
  );
}

export function MyAccountView() {
  const { session, retry } = useSession();
  const working = session.kind !== "loading" && session.kind !== "unknown" && session.kind !== "signed_out" && !session.mustChange;
  // 계좌 목록은 뿌리에서 한 번 묻는다 — 판 배치는 계좌가 있을 때만 선다(빈 화면에 판을 세우지 않는다) · 아래 Accounts 가 같은 답을 받아 쓴다(관찰자 하나)
  const list = useQuery({ queryKey: ["broker-accounts"], queryFn: unwrap(listBrokerAccounts), staleTime: 0, enabled: working });
  const wide = useMediaQuery(ACCOUNT_QUERY);
  // 판 배치(G6)의 켬 · 배치 · 이름 붙인 배치는 이 브라우저에 남는다 — 작업대는 계정 확인 뒤에 서므로 서버 그림 · 수화와 어긋나지 않는다
  const ws = useWorkspace(ACCOUNT_WS);
  const has = (list.data?.accounts.length ?? 0) > 0;
  const wsMode: WsMode = working && has && ws.on ? (wide ? "tabs" : "stack") : null;
  return (
    <div className="tx-page ma" data-ws={wsMode ?? undefined}>
      {session.kind === "loading" ? (
        <><Head /><p className="tx-sec-sub" aria-busy="true">계정 확인 중</p></>
      ) : session.kind === "unknown" ? (
        <><Head />
          <RetryFail title="계정 정보 확인 실패" onRetry={() => void retry()}>{session.reason}</RetryFail></>
      ) : session.kind === "signed_out" ? (
        <><Head />
          <section className="tx-sec ma-signed-out">
            <p className="ma-strong">로그인하면 내 계좌를 조회할 수 있습니다.</p>
            <p className="tx-sec-sub">계정은 관리자가 발급합니다. 증권 계좌는 로그인 후 설정에서 연결합니다.</p>
            <Link href={loginHref("/my-account")} className="tx-btn tx-btn--main">로그인</Link>
          </section></>
      ) : session.mustChange ? (
        <><Head />
          <section className="tx-sec ma-must" role="alert">
            <p className="ma-strong">비밀번호를 먼저 변경하십시오.</p>
            <p className="tx-sec-sub">관리자가 발급한 임시 비밀번호로는 계좌를 사용할 수 없습니다.</p>
            <Link href="/settings#password" className="tx-btn tx-btn--main">비밀번호 바꾸러 가기</Link>
          </section></>
      ) : (
        <Accounts q={list} ws={ws} wsMode={wsMode} menu={has && wide && !ws.on} />
      )}
    </div>
  );
}

function Accounts({ q, ws, wsMode, menu }: {
  q: UseQueryResult<AccountList>; ws: WorkspaceState; wsMode: WsMode;
  /** 끈 화면의 '배치' 단추를 머리에 둘지 — 넓은 창 · 계좌가 있을 때 · 판 배치를 끈 때만(켠 화면에서는 작업 공간 위 막대에 선다). */
  menu: boolean;
}) {
  const router = useRouter();
  const want = useSearchParams().get("account");
  // 배치 관리 시트는 판 배치를 끄고 켜도 같은 자리에 둔다(가져오기가 판 배치를 켜도 시트와 결과 문장이 남는다)
  const [manage, setManage] = useState(false);
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
  // 폭은 0(막지 않음) — 판 넷의 최소 폭으로는 세 열도 탭 보기의 가장 좁은 본문 폭에 들어간다(workspaceSpec · 순수 시험이 건다)
  const layoutMenu = menu ? <LayoutMenu ws={ws} work={0} onManage={() => setManage(true)} /> : null;
  const actions = pick || layoutMenu ? <>{pick}{layoutMenu}</> : null;

  return (
    <>
      <Head actions={actions} />
      {q.isError ? (
        <RetryFail title="증권 계좌 목록 조회 실패" onRetry={() => void q.refetch()}>{q.error.message}</RetryFail>
      ) : !q.data ? (
        <p className="tx-sec-sub" aria-busy="true">계좌 목록 조회 중</p>
      ) : !cur ? (
        <section className="tx-sec ma-empty">
          <p className="ma-strong">연결한 증권 계좌 없음</p>
          <p className="tx-sec-sub">설정의 ‘내 증권 계좌’에서 한국투자증권 계좌를 연결하면 여기서 주문을 연습할 수 있습니다.</p>
          <Link href="/settings#broker" className="tx-btn tx-btn--main">설정에서 계좌 연결하기</Link>
        </section>
      ) : (
        <>
          {want !== null && !found ? (
            <div className="ma-fallback"><Notice tone="warn" title="주소의 계좌를 찾지 못해 첫 계좌를 표시합니다." /></div>
          ) : null}
          <AccountView key={cur.account_id} acc={cur} ws={ws} wsMode={wsMode} onManage={() => setManage(true)} />
        </>
      )}
      {manage ? <LayoutSheet ws={ws} onClose={() => setManage(false)} /> : null}
    </>
  );
}

function AccountView({ acc, ws, wsMode, onManage }: { acc: BrokerAccount; ws: WorkspaceState; wsMode: WsMode; onManage: () => void }) {
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
    ...(practice === true ? [{ label: "합성 데이터", tone: "practice" as const, ev: "source" }]
      : cs.isError ? [{ label: "합성 데이터인지 확인하지 못했습니다", tone: "unknown" as const, ev: "source" }] : []),
  ];
  const figures = [
    { label: "평가 자산", value: b?.state === "ok" ? priceWon(b.evaluated_total) : "N/A" },
    { label: "보유", value: b?.state === "ok" ? `${b.positions.length}종목` : "N/A" },
    { label: "최근 주문", value: orders.data ? `${orders.data.count}건` : "N/A" },
  ];
  const action = k?.active && k.event ? (
    <button type="button" className="tx-btn tx-btn--sub ma-kill-resolve-open" onClick={() => { setDone(null); setSheet("resolve"); }}>비상 정지 풀기</button>
  ) : k?.active ? null : (
    <button type="button" className="tx-btn ma-btn-danger ma-kill-open" onClick={() => { setDone(null); setSheet("kill"); }}>비상 정지</button>
  );
  const sentence = mode.isPending || kill.isPending
    ? `‘${acc.label}’ 상태 확인 중`
    : answerSentence(acc.label, mode.data?.mode ?? null, k, practice);
  // 붙는 문장 띠의 높이(판 배치) — 작업 공간 높이 = 창 − 띠
  const [measureStick, stickH] = useBoxHeight();

  // ── 화면 조각 — 기본 배치(지금 그대로)와 판 배치가 같은 조각을 그린다(같은 상태 · 같은 처리기 · 같은 클래스) ──
  const answer = <Answer sentence={sentence} figures={figures} chips={chips} action={action} />;
  const doneEl = done ? <p className="ma-kill-done" role="status">{done}</p> : null;
  const modeFail = mode.isError ? (
    <RetryFail title="실행 모드 확인 실패" onRetry={() => void mode.refetch()}>{mode.error.message}</RetryFail>
  ) : null;
  const pathEl = <OrderPath acc={acc} mode={mode} kill={kill} ready={ready} practice={practice} trace={trace} />;
  const balanceEl = <BalanceCard q={bal} />;
  const orderEl = (
    <OrderForm accountId={id} mode={mode.isError ? null : mode.data?.mode} killActive={kill.isError ? null : kill.data?.active}
               practice={practice} onTrace={setTrace}
               holdings={b?.state === "ok" ? b.positions : []} cash={b?.state === "ok" ? b.cash_krw : null} />
  );
  const ordersEl = <OrderList accountId={id} q={orders} />;
  const armingEl = <RuleArming accountId={id} mode={mode.isError ? null : mode.data?.mode} kill={kill.isError ? null : kill.data} />;
  const killSheet = (
    <KillSheet accountId={id} open={sheet} onClose={() => setSheet(null)}
               onDone={(s) => { setSheet(null); setDone(s); setTrace(null); void kill.refetch(); void mode.refetch(); }} />
  );

  if (wsMode) {
    const panel = (pid: string): ReactNode => {
      switch (pid) {
        case "order": return orderEl;
        case "orders": return ordersEl;
        case "balance": return balanceEl;
        case "arming": return armingEl;
        default: return null;
      }
    };
    // 탭 보기 · 쌓기는 같은 DOM(감싸개 › 띠 › 정지 결과 줄 › 모드 실패 › 경로 › 작업 공간) — 오가도 경로 · 판이 다시 서지 않는다. 붙는 것은 CSS(탭 보기만).
    return (
      <div className="ma-wsf" style={stickH > 0 ? ({ "--ma-stick-h": `${Math.round(stickH)}px` } as CSSProperties) : undefined}>
        <div className="ma-stick" ref={measureStick}>{answer}</div>
        {doneEl}
        {modeFail}
        {pathEl}
        <Workspace ws={ws} stacked={wsMode === "stack"} render={panel} onManage={onManage} />
        {killSheet}
      </div>
    );
  }

  return (
    <>
      {answer}
      {doneEl}
      {modeFail}
      {pathEl}
      <div className="ma-grid">
        {balanceEl}
        {orderEl}
        {ordersEl}
      </div>
      {armingEl}
      {killSheet}
    </>
  );
}
