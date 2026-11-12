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
const LEDE = "관리하는 고객과 고객별 설계 문서입니다. 고객 정보는 비중을 바꾸지 않습니다 — 점검하고 기록하는 데 씁니다.";
const NO_PII = "별칭만 입력합니다 — 실명·연락처·주민번호·계좌번호는 입력하지 않습니다. 전화·이메일·긴 숫자 형식은 서버가 거부하며, 실명은 형식으로 식별할 수 없어 PB 가 준수해야 합니다.";

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
      {session.kind === "loading" ? <p className="tx-sec-sub" aria-busy="true">계정 확인 중</p>
        : session.kind === "unknown" ? <RetryFail title="계정 정보 확인 실패" onRetry={() => void retry()}>{session.reason}</RetryFail>
        : session.kind === "signed_out" ? (
          <section className="tx-sec cl-signed-out">
            <p className="cl-strong">로그인하면 내 고객을 조회할 수 있습니다.</p>
            <p className="tx-sec-sub">고객 자료는 이 서버의 내 계정에만 있습니다 — 다른 PB 는 보지 못합니다.</p>
            <Link href={loginHref("/clients")} className="tx-btn tx-btn--main">로그인</Link>
          </section>
        ) : session.mustChange ? (
          <section className="tx-sec cl-must" role="alert">
            <p className="cl-strong">비밀번호를 먼저 변경하십시오.</p>
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
              {t === "active" ? "활성 고객" : "보관 고객"}
            </button>
          ))}
        </div>
        {list.isLoading ? <p className="tx-sec-sub" aria-busy="true">고객 조회 중</p>
          : list.isError ? <RetryFail title="고객 조회 실패" onRetry={() => void list.refetch()}>{(list.error as Error).message}</RetryFail>
          : (list.data?.clients ?? []).length === 0 ? (
            <p className="cl-empty">{tab === "active" ? "아직 고객이 없습니다 — 아래에서 별칭으로 더합니다." : "보관한 고객 없음"}</p>
          ) : (
            <ul className="cl-list">
              {list.data!.clients.map((c) => (
                <li key={c.client_id}>
                  <Link href={`/clients?client=${encodeURIComponent(c.client_id)}`} className="cl-item" data-client-id={c.client_id}
                        aria-current={c.client_id === want ? "true" : undefined}>
                    <span className="cl-item-alias">{c.alias}</span>
                    <span className="cl-item-sub">{riskText(c)} · {ageText(c)} · 문서 {c.doc_count}개{c.last_sheet_at ? ` · 마지막 한 장 ${day(c.last_sheet_at)}` : ""}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
      </section>
      <div className="cl-main">
        {want ? <Detail key={want} cid={want} /> : (
          <section className="tx-sec cl-detail-empty"><p className="tx-sec-sub">고객을 고르면 그 고객의 정보와 설계 문서가 보입니다.</p></section>
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
        <input className={`cl-input ${p}-alias`} value={alias} maxLength={40} required placeholder="예: A-12 · 2026 은퇴 준비"
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
      <Notice tone="warn" title="실명·연락처는 입력하지 않습니다">{NO_PII}</Notice>
      <FactsForm key={n} init={{}} submitLabel="더하기" className="cl-add" err={err} onSubmit={async (f) => {
        const r = await createClient(f);
        if (!r.ok) { setErr(r.error); return; }
        setErr(null);
        setN((x) => x + 1);
        await qc.cancelQueries({ queryKey: ["pb-clients"] });      // 처음 목록 읽기에 얹히지 않게(아래 Detail.refresh 와 같은 까닭)
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
  if (q.isLoading) return <section className="tx-sec cl-detail" aria-busy="true"><p className="tx-sec-sub">고객 로딩 중</p></section>;
  if (q.isError) {
    return (
      <section className="tx-sec cl-detail cl-detail--missing">
        <p className="cl-strong">이 고객 열기 실패 — {(q.error as Error).message}</p>
        <button type="button" className="tx-btn tx-btn--sub" onClick={() => router.replace("/clients")}>목록으로</button>
      </section>
    );
  }
  const c = q.data as PbClientDetail;
  // 처음 목록 읽기가 아직 오는 중이면 다시 읽기가 그 읽기(고치기 전 값)에 얹힌다 — 먼저 끊고 새로 읽는다.
  const refresh = async () => {
    await qc.cancelQueries({ queryKey: ["pb-clients"] });
    await qc.invalidateQueries({ queryKey: ["pb-client", cid] });
    await qc.invalidateQueries({ queryKey: ["pb-clients"] });
  };
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
        <div><dt>평가일</dt><dd>{c.assessed_at ? `${c.assessed_at} · ${c.assessed_age_days}일 지났습니다` : "모름"}</dd></div>
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
      {c.docs.length === 0 ? <p className="cl-empty">아직 문서가 없습니다 — ‘정기 점검으로 새 문서’ 로 만듭니다.</p> : (
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
      <h3 className="cl-h3">고객 한 장</h3>
      {(c.sheets ?? []).length === 0 ? <p className="cl-empty">아직 한 장이 없습니다 — 캔버스에서 계산한 뒤 위 칩의 ‘한 장’ 으로 만듭니다.</p> : (
        <ul className="cl-docs">
          {c.sheets.map((x) => (
            <li key={x.sheet_id} className="cl-doc cl-sheet" data-sheet-id={x.sheet_id}>
              <span className="cl-doc-name">{x.title}{x.practice && <span className="cl-practice">합성</span>}</span>
              <span className="cl-doc-when">{x.shared ? "고객에게 보여 줌" : `만든 날 ${day(x.created_at)}`}</span>
              <Link href={`/clients/${encodeURIComponent(cid)}/sheets/${encodeURIComponent(x.sheet_id)}`} className="cl-doc-open">한 장 보기</Link>
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
