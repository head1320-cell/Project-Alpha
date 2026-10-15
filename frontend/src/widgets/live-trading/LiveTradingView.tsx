"use client";
/**
 * 실거래 (BU9b) — `/admin/live-trading`. 서버 `.env` 운영 계좌의 주문이 어디로 가는지 보고, 멈추고, 실계좌 관문을 관리한다.
 * ==========================================================================
 * ★요청은 옛 화면과 바이트 그대로★(BU9a 골든 `e2e/golden/live-trading-requests.json`): 읽기 넷을 10초마다 함께 ·
 * 쓰기는 고정 본문(`entities/trading/operator`) · 쓰기 뒤엔 결과와 상관없이 다시 읽기. 더한 것은 ★확인 단계★(모의 체결 · 풀기)와
 * ★실패를 사유와 함께★ 보이기뿐이다(사용자 결정 2026-10-10 · ADR-003 §2.7). 켜진 모드 단추는 눌린 채 잠근다(같은 모드 재전송 없음).
 * ★이 화면만의 한 가지 = 주문이 가는 길★(/내 계좌와 같은 그림 — 운영 계좌도 같은 `execute_signal` 을 지난다).
 * 답 문장 = 서버 값(`sentence.ts`). 미상 ≠ 0. 읽기 넷은 세션과 상관없이 나간다(잔고·주문은 서버가 로그인을 본다).
 */
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { macroApi } from "@/entities/macro/api";
import { useSession } from "@/entities/session";
import { getLiveGate } from "@/entities/trading/liveGate";
import { readOperator, type OpKill, type OpModeName } from "@/entities/trading/operator";
import { loginHref } from "@/shared/lib/nextPath";
import { krDateTime, num, priceWon } from "@/shared/lib/krFormat";
import { Answer, Notice, PageHead, RetryFail, Tabs, type Chip } from "@/shared/ui/tx";
import { Holdings } from "./Holdings";
import { OperatorOrders } from "./OperatorOrders";
import { OperatorPath } from "./OperatorPath";
import { KillSheets, LiveSheet } from "./OperatorSheets";
import { RealismTab } from "./RealismTab";
import { SafetyTab } from "./SafetyTab";
import { opSentence } from "./sentence";

const TITLE = "실거래";
const LEDE = "운영 계좌로 주문이 어디로 가는지 보고, 멈추고, 실계좌 관문을 관리해요.";

/** 탭 — 주소 `?tab=` 와 같이 움직인다(기본 지금). 답 문장과 [비상 정지] 는 탭 위에 늘 보인다(사용자 결정 "탭 셋"). */
type Tab = "now" | "safety" | "realism";
const TABS: { value: Tab; label: string }[] = [
  { value: "now", label: "지금" }, { value: "safety", label: "안전" }, { value: "realism", label: "현실성 점검" },
];
export const tabOf = (v: string | null): Tab => (TABS.find((t) => t.value === v)?.value ?? "now");
export const POLL_MS = 10_000;

/** 이 브라우저 시계로 마지막으로 읽은 때 — "06:37:36". */
const clock = (t: number) => { const d = new Date(t); const two = (v: number) => String(v).padStart(2, "0");
  return `${two(d.getHours())}:${two(d.getMinutes())}:${two(d.getSeconds())}`; };

export function LiveTradingView() {
  const { session, retry } = useSession();
  const sp = useSearchParams();
  const router = useRouter();
  const tab = tabOf(sp.get("tab"));
  const pick = (t: Tab) => router.replace(t === "now" ? "/admin/live-trading" : `/admin/live-trading?tab=${t}`, { scroll: false });
  // ★옛 화면과 같은 횟수★ — 처음 한 번 + 10초마다(탭이 뒤에 있어도) · 실패해도 다시 묻지 않음 · 창 초점으로 더 읽지 않음.
  const snap = useQuery({
    queryKey: ["live", "operator"], queryFn: readOperator, staleTime: 0, retry: false,
    refetchInterval: POLL_MS, refetchIntervalInBackground: true, refetchOnWindowFocus: false,
  });
  const cs = useQuery({ queryKey: ["macro", "connection-status"], queryFn: () => macroApi.connectionStatus() });
  const practice = cs.data ? cs.data.mock_allowed : null;

  const signedIn = session.kind === "signed_in";
  const isAdmin = signedIn && session.role === "admin" && !session.mustChange;
  const gate = useQuery({ queryKey: ["live", "gate"], queryFn: async () => {
    const r = await getLiveGate();
    if (!r.ok) throw new Error(r.error);
    return r.value;
  }, enabled: isAdmin, staleTime: 0, retry: false });

  const [sheet, setSheet] = useState<"live" | "kill" | "resolve" | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [refused, setRefused] = useState<{ mode: string; reason: string } | null>(null);
  const refetch = () => void snap.refetch();

  const r = snap.data;
  const mode = { pending: !r, failed: !!r && !r.mode.ok, value: r?.mode.ok ? (r.mode.value.mode as OpModeName) : null };
  const kill = { pending: !r, failed: !!r && !r.kill.ok, value: r?.kill.ok ? (r.kill.value as OpKill) : null };
  const bal = r?.balance.ok ? r.balance.value : null;
  const orders = r?.orders.ok ? r.orders.value : null;
  const unauthorized = !!r && [r.balance, r.orders].some((x) => !x.ok && x.status === 401);
  const k = kill.value;

  const chips: Chip[] = [
    ...(practice === true ? [{ label: "연습용 데이터", tone: "practice" as const, ev: "source" }]
      : cs.isError ? [{ label: "연습용인지 확인하지 못했어요", tone: "unknown" as const, ev: "source" }] : []),
    ...(r?.mode.ok && r.mode.value.changed_by
      ? [{ label: `${r.mode.value.changed_by} 님이 ${krDateTime(r.mode.value.last_mode_change) ?? "언제인지 모르는 때"}에 모드를 바꿨어요`, tone: "plain" as const }]
      : []),
  ];
  const unknownMoney = bal === null;
  const held = bal ? (bal.n_positions ?? bal.positions?.length ?? null) : null;
  const figures = [
    { label: "평가 자산", value: unknownMoney ? "몰라요" : priceWon(bal.evaluated_total) },
    { label: "예수금", value: unknownMoney ? "몰라요" : priceWon(bal.cash_krw) },
    { label: "주식 평가액", value: unknownMoney ? "몰라요" : priceWon(bal.stock_value) },
    { label: "보유", value: held === null ? "몰라요" : `${num(held)}종목` },
    { label: "최근 주문", value: orders ? `${num(orders.count)}건` : "몰라요" },
  ];
  const action = !isAdmin ? null : k?.is_active ? (
    <button type="button" className="tx-btn tx-btn--sub lv-resolve-open" data-act="resolve"
            onClick={() => { setDone(null); setSheet("resolve"); }}>비상 정지 풀기</button>
  ) : (
    <button type="button" className="tx-btn lv-btn-danger lv-kill-open" data-act="kill-open"
            onClick={() => { setDone(null); setSheet("kill"); }}>비상 정지</button>
  );

  const head = (
    <PageHead title={TITLE} lede={LEDE} actions={
      <div className="lv-head-act">
        <span className="lv-polled" aria-live="polite">
          {snap.isFetching ? "새로 읽는 중이에요" : snap.dataUpdatedAt ? `10초마다 새로 읽어요 · 마지막 ${clock(snap.dataUpdatedAt)}` : "10초마다 새로 읽어요"}
        </span>
        <button type="button" className="tx-btn tx-btn--sub lv-refresh" data-act="refresh" onClick={refetch}>
          <RefreshCw size={14} aria-hidden /> 새로 고침
        </button>
      </div>
    } />
  );

  return (
    <div className="tx-page lv">
      {head}
      {session.kind === "signed_out" || unauthorized ? (
        <div className="live-auth-banner lv-auth" role="status">
          <span>로그인해야 운영 계좌의 잔고와 주문을 볼 수 있어요.</span>
          <Link href={loginHref("/admin/live-trading")} className="live-auth-banner__link tx-btn tx-btn--main lv-sm">로그인</Link>
        </div>
      ) : session.kind === "unknown" ? (
        <RetryFail title="계정 정보를 확인하지 못했어요" onRetry={() => void retry()}>{session.reason}</RetryFail>
      ) : signedIn && session.mustChange ? (
        <section className="tx-sec lv-must" role="alert">
          <p className="lv-strong">비밀번호를 먼저 바꿔 주세요.</p>
          <p className="tx-sec-sub">관리자가 준 임시 비밀번호로는 모드를 바꾸거나 비상 정지를 걸 수 없어요.</p>
          <Link href="/settings#password" className="tx-btn tx-btn--main">비밀번호 바꾸러 가기</Link>
        </section>
      ) : signedIn && !isAdmin ? (
        <div className="lv-readonly"><Notice tone="warn" title="관리자만 모드를 바꾸거나 비상 정지를 걸 수 있어요.">이 화면은 읽기만 해요.</Notice></div>
      ) : null}

      {mode.value === "LIVE" ? (
        <div className="lv-live-on"><Notice tone="warn" title="운영 계좌가 지금 실제 돈으로 주문해요.">비상 정지는 이 화면 위쪽 단추로 걸 수 있어요.</Notice></div>
      ) : null}

      <Answer sentence={opSentence(mode, kill, practice)} figures={figures} chips={chips} action={action} />
      {done ? <p className="lv-done" role="status">{done}</p> : null}
      {r && !r.mode.ok && r.mode.status !== 401 ? (
        <RetryFail title="실행 모드를 확인하지 못했어요" onRetry={refetch}>{r.mode.error}</RetryFail>
      ) : null}

      <Tabs label="실거래 보기" tabs={TABS} value={tab} onChange={pick}>
      {tab === "now" ? (
      <div className="lv-now">
      <OperatorPath mode={mode} kill={kill} practice={practice} isAdmin={isAdmin} gate={gate}
                    refused={refused}
                    onRefused={setRefused} onWritten={refetch} onLive={() => { setRefused(null); setSheet("live"); }}
                    onRetryKill={refetch} />

      <div className="lv-grid">
        <Holdings result={r?.balance ?? null} onRetry={refetch} />
        <OperatorOrders result={r?.orders ?? null} onRetry={refetch} />
      </div>
      </div>
      ) : tab === "safety" ? (
        <SafetyTab isAdmin={isAdmin} signedIn={signedIn && !session.mustChange} gate={gate} onChanged={refetch} />
      ) : (
        <RealismTab />
      )}
      </Tabs>

      {isAdmin ? (
        <>
          <LiveSheet open={sheet === "live"} gate={gate} onClose={() => setSheet(null)}
                     onSettled={(why) => { setSheet(null); setRefused(why ? { mode: "LIVE", reason: why } : null); refetch(); }} />
          <KillSheets open={sheet === "kill" || sheet === "resolve" ? sheet : null} onClose={() => setSheet(null)}
                      onDone={(said) => { setSheet(null); setDone(said); }} onSettled={refetch} />
        </>
      ) : null}
    </div>
  );
}
