"use client";
/**
 * 고객 (CF 3부 PB3) — `/clients`. PB 가 관리하는 고객(★별칭만★)과 고객별 설계 문서.
 * ==========================================================================
 * ★서버가 판정한다★ — 본인 고객만 보인다(남의 고객은 404) · 별칭·문서 이름의 개인정보 모양은 서버가 거르고, 그 사유를 그대로 보인다.
 * 실명은 모양으로 알 수 없어 화면이 적지 말라고 안내한다. 지우는 단추는 없다 — 보관(목록에서 숨김 · 읽기만)과 다시 꺼내기.
 * 모르는 칸은 '모름'(기본값으로 채우지 않는다). 고객은 `?client=` 로 고른다 — 목록에 없는 고객이면 그렇다고 말한다(지어내지 않음).
 * '정기 점검으로 새 문서' 는 캔버스(`/allocation?client=&new=review`)가 이 고객의 사실을 고객 노드에 넣어 연다 — 저장은 캔버스의 칩.
 */
import Link from "next/link";
import { useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  RISK_PLAIN, SOURCE_PLAIN, archiveClient, createClient, getClient, listClients, unarchiveClient, updateClient,
  type ClientFacts, type PbClient, type PbClientDetail, type ProfileSource, type RiskTolerance,
} from "@/entities/pb-client";
import { useSession } from "@/entities/session";
import type { Result } from "@/shared/api/result";
import { loginHref } from "@/shared/lib/nextPath";
import { Notice, PageHead, RetryFail } from "@/shared/ui/tx";

const TITLE = "고객";
const LEDE = "관리하는 고객과 고객별 설계 문서예요. 고객 정보는 비중을 바꾸지 않아요 — 점검하고 기록하는 데 써요.";
const NO_PII = "별칭만 적어요 — 실명·연락처·주민번호·계좌번호는 적지 않아요. 전화·이메일·긴 숫자 모양은 서버가 받지 않고, 실명은 모양으로 알 수 없어 PB 가 지켜요.";

const unwrap = <T,>(fn: () => Promise<Result<T>>) => async (): Promise<T> => {
  const r = await fn();
  if (!r.ok) throw new Error(r.error);
  return r.value;
};
const day = (iso: string | null) => (iso ? iso.slice(0, 10) : "모름");
const riskText = (c: PbClient) => (c.risk_tolerance ? RISK_PLAIN[c.risk_tolerance] : "성향 모름");
const ageText = (c: PbClient) => (c.assessed_age_days === null ? "평가일 모름" : `평가한 지 ${c.assessed_age_days}일`);

export function ClientsView() {
  const { session, retry } = useSession();
  return (
    <div className="tx-page cl-page">
      <PageHead title={TITLE} lede={LEDE} />
      {session.kind === "loading" ? <p className="tx-sec-sub" aria-busy="true">계정을 확인하는 중이에요.</p>
        : session.kind === "unknown" ? <RetryFail title="계정 정보를 확인하지 못했어요" onRetry={() => void retry()}>{session.reason}</RetryFail>
        : session.kind === "signed_out" ? (
          <section className="tx-sec cl-signed-out">
            <p className="cl-strong">로그인하면 내 고객을 볼 수 있어요.</p>
            <p className="tx-sec-sub">고객 자료는 이 서버의 내 계정에만 있어요 — 다른 PB 는 보지 못해요.</p>
            <Link href={loginHref("/clients")} className="tx-btn tx-btn--main">로그인</Link>
          </section>
        ) : session.mustChange ? (
          <section className="tx-sec cl-must" role="alert">
            <p className="cl-strong">비밀번호를 먼저 바꿔 주세요.</p>
            <Link href="/settings#password" className="tx-btn tx-btn--main">비밀번호 바꾸러 가기</Link>
          </section>
        ) : <Clients />}
    </div>
  );
}

function Clients() {
  const want = useSearchParams().get("client");
  const [tab, setTab] = useState<"active" | "archived">("active");
  const list = useQuery({ queryKey: ["pb-clients", tab], queryFn: unwrap(() => listClients(tab === "archived")), staleTime: 0 });
  return (
    <div className="cl-grid">
      <section className="tx-sec cl-listbox" aria-label="고객 목록">
        <div className="cl-list-tabs" role="group" aria-label="보이는 고객">
          {(["active", "archived"] as const).map((t) => (
            <button key={t} type="button" className="cl-list-tab" data-tab={t} aria-pressed={tab === t} onClick={() => setTab(t)}>
              {t === "active" ? "지금 고객" : "보관한 고객"}
            </button>
          ))}
        </div>
        {list.isLoading ? <p className="tx-sec-sub" aria-busy="true">고객을 불러오는 중이에요.</p>
          : list.isError ? <RetryFail title="고객을 불러오지 못했어요" onRetry={() => void list.refetch()}>{(list.error as Error).message}</RetryFail>
          : (list.data?.clients ?? []).length === 0 ? (
            <p className="cl-empty">{tab === "active" ? "아직 고객이 없어요 — 아래에서 별칭으로 더해요." : "보관한 고객이 없어요."}</p>
          ) : (
            <ul className="cl-list">
              {list.data!.clients.map((c) => (
                <li key={c.client_id}>
                  <Link href={`/clients?client=${encodeURIComponent(c.client_id)}`} className="cl-item" data-client-id={c.client_id}
                        aria-current={c.client_id === want ? "true" : undefined}>
                    <span className="cl-item-alias">{c.alias}</span>
                    <span className="cl-item-sub">{riskText(c)} · {ageText(c)} · 문서 {c.doc_count}개</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
      </section>
      <div className="cl-main">
        {want ? <Detail key={want} cid={want} /> : (
          <section className="tx-sec cl-detail-empty"><p className="tx-sec-sub">고객을 고르면 그 고객의 정보와 설계 문서가 보여요.</p></section>
        )}
      </div>
      <AddClient />
    </div>
  );
}

function FactsForm({ init, submitLabel, onSubmit, className, err }: {
  init: Partial<ClientFacts>; submitLabel: string; onSubmit: (f: ClientFacts) => void; className: string; err: string | null;
}) {
  const [alias, setAlias] = useState(init.alias ?? "");
  const [risk, setRisk] = useState<RiskTolerance | "">(init.risk_tolerance ?? "");
  const [source, setSource] = useState<ProfileSource>(init.profile_source ?? "unknown");
  const [date, setDate] = useState(init.assessed_at ?? "");
  const [horizon, setHorizon] = useState(init.horizon_years == null ? "" : String(init.horizon_years));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    onSubmit({ alias, risk_tolerance: risk || null, profile_source: source, assessed_at: date || null,
               horizon_years: horizon === "" ? null : Number(horizon) });
  };
  const p = className;
  return (
    <form className={`cl-form ${p}-form`} onSubmit={submit}>
      <label className="cl-field cl-field--wide"><span className="cl-label">별칭</span>
        <input className={`cl-input ${p}-alias`} value={alias} maxLength={40} required placeholder="예: 고객 A-12 · 2026 은퇴 준비"
               onChange={(e) => setAlias(e.target.value)} />
      </label>
      <label className="cl-field"><span className="cl-label">위험 성향</span>
        <select className={`cl-input ${p}-risk`} value={risk} onChange={(e) => setRisk(e.target.value as RiskTolerance | "")}>
          <option value="">모름</option>
          {(Object.keys(RISK_PLAIN) as RiskTolerance[]).map((k) => <option key={k} value={k}>{RISK_PLAIN[k]}</option>)}
        </select>
      </label>
      <label className="cl-field"><span className="cl-label">성향 출처</span>
        <select className={`cl-input ${p}-source`} value={source} onChange={(e) => setSource(e.target.value as ProfileSource)}>
          {(Object.keys(SOURCE_PLAIN) as ProfileSource[]).map((k) => <option key={k} value={k}>{SOURCE_PLAIN[k]}</option>)}
        </select>
      </label>
      <label className="cl-field"><span className="cl-label">평가일</span>
        <input type="date" className={`cl-input ${p}-date`} value={date} onChange={(e) => setDate(e.target.value)} />
      </label>
      <label className="cl-field"><span className="cl-label">투자 기간(년)</span>
        <input type="number" min={0} max={80} step="any" className={`cl-input ${p}-horizon`} value={horizon} placeholder="모름"
               onChange={(e) => setHorizon(e.target.value)} />
      </label>
      <div className="cl-form-act">
        <button type="submit" className={`tx-btn tx-btn--main ${p}-go`}>{submitLabel}</button>
      </div>
      {err && <p className={`cl-err ${p}-error`} role="alert">{err}</p>}
    </form>
  );
}

function AddClient() {
  const qc = useQueryClient();
  const [err, setErr] = useState<string | null>(null);
  const [n, setN] = useState(0);
  return (
    <section className="tx-sec cl-add" aria-label="고객 더하기">
      <h2 className="tx-sec-t">고객 더하기</h2>
      <Notice tone="warn" title="실명·연락처는 적지 않아요">{NO_PII}</Notice>
      <FactsForm key={n} init={{}} submitLabel="더하기" className="cl-add" err={err} onSubmit={async (f) => {
        const r = await createClient(f);
        if (!r.ok) { setErr(r.error); return; }
        setErr(null);
        setN((x) => x + 1);
        await qc.invalidateQueries({ queryKey: ["pb-clients"] });
      }} />
    </section>
  );
}

function Detail({ cid }: { cid: string }) {
  const router = useRouter();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["pb-client", cid], queryFn: unwrap(() => getClient(cid)), staleTime: 0, retry: false });
  const [err, setErr] = useState<string | null>(null);
  const [editErr, setEditErr] = useState<string | null>(null);
  if (q.isLoading) return <section className="tx-sec cl-detail" aria-busy="true"><p className="tx-sec-sub">고객을 여는 중이에요.</p></section>;
  if (q.isError) {
    return (
      <section className="tx-sec cl-detail cl-detail--missing">
        <p className="cl-strong">이 고객을 열지 못했어요 — {(q.error as Error).message}</p>
        <button type="button" className="tx-btn tx-btn--sub" onClick={() => router.replace("/clients")}>목록으로</button>
      </section>
    );
  }
  const c = q.data as PbClientDetail;
  const refresh = async () => { await qc.invalidateQueries({ queryKey: ["pb-client", cid] }); await qc.invalidateQueries({ queryKey: ["pb-clients"] }); };
  const act = async (fn: () => Promise<Result<unknown>>) => {
    const r = await fn();
    if (!r.ok) { setErr(r.error); return; }
    setErr(null);
    await refresh();
  };
  return (
    <section className="tx-sec cl-detail" aria-label={`고객 ${c.alias}`}>
      <header className="cl-detail-head">
        <h2 className="tx-sec-t cl-detail-alias">{c.alias}</h2>
        {c.archived && <span className="cl-badge">보관함 · 읽기만</span>}
      </header>
      <dl className="cl-facts">
        <div><dt>위험 성향</dt><dd>{c.risk_tolerance ? RISK_PLAIN[c.risk_tolerance] : "모름"}</dd></div>
        <div><dt>성향 출처</dt><dd>{SOURCE_PLAIN[c.profile_source]}</dd></div>
        <div><dt>평가일</dt><dd>{c.assessed_at ? `${c.assessed_at} · ${c.assessed_age_days}일 지났어요` : "모름"}</dd></div>
        <div><dt>투자 기간</dt><dd>{c.horizon_years === null ? "모름" : `${c.horizon_years}년`}</dd></div>
      </dl>
      <div className="cl-acts">
        {!c.archived && <Link href={`/allocation?client=${encodeURIComponent(cid)}&new=review`} className="tx-btn tx-btn--main cl-new-review">정기 점검으로 새 문서</Link>}
        {c.archived
          ? <button type="button" className="tx-btn tx-btn--sub cl-unarchive" onClick={() => void act(() => unarchiveClient(cid))}>다시 꺼내기</button>
          : <button type="button" className="tx-btn tx-btn--sub cl-archive" onClick={() => void act(() => archiveClient(cid))}>보관</button>}
      </div>
      {err && <p className="cl-err" role="alert">{err}</p>}
      <h3 className="cl-h3">설계 문서</h3>
      {c.docs.length === 0 ? <p className="cl-empty">아직 문서가 없어요 — ‘정기 점검으로 새 문서’ 로 만들어요.</p> : (
        <ul className="cl-docs">
          {c.docs.map((d) => (
            <li key={d.doc_id} className="cl-doc" data-doc-id={d.doc_id}>
              <span className="cl-doc-name">{d.name}</span>
              <span className="cl-doc-when">고친 날 {day(d.updated_at)}</span>
              <Link href={`/allocation?client=${encodeURIComponent(cid)}&doc=${encodeURIComponent(d.doc_id)}`} className="cl-doc-open">캔버스에서 열기</Link>
            </li>
          ))}
        </ul>
      )}
      {!c.archived && (
        <details className="cl-edit">
          <summary>고객 정보 고치기</summary>
          <FactsForm init={c} submitLabel="고친 것 저장" className="cl-edit" err={editErr} onSubmit={async (f) => {
            const r = await updateClient(cid, f);
            if (!r.ok) { setEditErr(r.error); return; }
            setEditErr(null);
            await refresh();
          }} />
        </details>
      )}
    </section>
  );
}
