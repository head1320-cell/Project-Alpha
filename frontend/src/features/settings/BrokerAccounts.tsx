"use client";
/**
 * 설정 "내 증권 계좌" (BV8) — 연결 · 목록 · 연결 확인 · 지우기. 서버는 BV3·BV4(`/api/v1/broker-accounts`).
 * ==========================================================================
 * ★비밀은 화면에 다시 나타나지 않는다★ — 보내고 나면 칸을 모두 비우고, 목록은 서버가 가린 값(끝 네 자리)만 그린다.
 * ★계좌 종류는 기본 선택이 없다★ — 돈이 걸린 선택이라 고르게 한다(서버도 참·거짓만 받는다).
 * ★확인한 만큼만 말한다★ — 연습용 모드의 확인은 서버 문구 그대로 "묻지 않았어요"이지 "연결됐어요"가 아니다.
 * 실패는 서버 사유 그대로. 금고 키가 없는 503 은 사용자가 고칠 수 없으니 운영자에게 알리라는 줄을 따로 둔다.
 */
import { useCallback, useEffect, useState } from "react";
import {
  checkBrokerAccount, connectBrokerAccount, deleteBrokerAccount, listBrokerAccounts,
  type BrokerAccount, type BrokerCheck,
} from "./api";

const ACCOUNT_NO = /^\d{8}$/;
const PRODUCT = /^\d{2}$/;

/** "2026-10-09T08:00:00" → "10월 9일". 모르면 null. */
function monthDay(iso: string | null): string | null {
  const m = iso?.match(/^\d{4}-(\d{2})-(\d{2})/);
  return m ? `${Number(m[1])}월 ${Number(m[2])}일` : null;
}

type CheckView = BrokerCheck | { state: "error"; reason: string };

export function BrokerAccounts() {
  const [rows, setRows] = useState<BrokerAccount[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [checks, setChecks] = useState<Record<string, CheckView>>({});
  const [checking, setChecking] = useState<string | null>(null);
  const [asking, setAsking] = useState<string | null>(null);
  const [rowError, setRowError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const r = await listBrokerAccounts();
    if (r.ok) { setRows(r.value.accounts); setLoadError(null); } else { setLoadError(r.error); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const check = async (id: string) => {
    setChecking(id);
    const r = await checkBrokerAccount(id);
    setChecking(null);
    setChecks((c) => ({ ...c, [id]: r.ok ? r.value : { state: "error", reason: r.error } }));
  };

  const remove = async (id: string) => {
    setAsking(null); setRowError(null);
    const r = await deleteBrokerAccount(id);
    if (!r.ok) { setRowError(r.error); return; }
    setChecks((c) => { const n = { ...c }; delete n[id]; return n; });
    void load();
  };

  return (
    <section className="set-sec set-broker" aria-labelledby="set-broker-h">
      <h2 className="set-h" id="set-broker-h">내 증권 계좌</h2>
      <p className="set-sub set-sub--lead">
        한국투자증권 계좌를 연결해요. 키는 서버에 암호화해 두고, 화면에는 끝 네 자리만 보여요.
      </p>

      <div className="set-card set-broker-list">
        {loadError ? (
          <div className="set-broker-loadfail" role="alert">
            <p className="set-error">증권 계좌 목록을 불러오지 못했어요. {loadError}</p>
            <button type="button" className="set-btn set-btn--sm set-broker-retry" onClick={() => void load()}>다시 시도</button>
          </div>
        ) : rows === null ? (
          <p className="set-sub" aria-busy="true">계좌 목록을 불러오는 중이에요.</p>
        ) : rows.length === 0 ? (
          <p className="set-sub set-broker-empty">아직 연결한 증권 계좌가 없어요. 아래에서 연결해요.</p>
        ) : rows.map((a) => {
          const result = checks[a.account_id];
          const day = monthDay(a.created_at);
          return (
            <div key={a.account_id} className="set-broker-row" data-account={a.account_id}>
              <div className="set-broker-row-t">
                <strong className="set-acct-name">{a.label}</strong>
                <span className="set-acct-meta">
                  <span className={`set-chip set-broker-kind-chip${a.is_paper ? "" : " set-chip--warn"}`}>
                    {a.is_paper ? "모의투자" : "실계좌"}
                  </span>
                  <span className="set-sub">계좌 <span data-mono>{a.account_no_masked}</span></span>
                  <span className="set-sub">키 끝 <span data-mono>{a.app_key_last4}</span></span>
                  {day ? <span className="set-sub">{day} 연결</span> : null}
                </span>
              </div>
              {asking === a.account_id ? (
                <div className="set-confirm set-broker-confirm" role="group" aria-label={`${a.label} 연결 끊기 확인`}>
                  <span className="set-sub">연결을 끊어요. 이 계좌로 낸 주문 기록은 남아요.</span>
                  <button type="button" className="set-btn set-btn--sm set-btn--danger set-broker-delete-yes"
                          onClick={() => void remove(a.account_id)}>지우기</button>
                  <button type="button" className="set-btn set-btn--sm set-broker-cancel" onClick={() => setAsking(null)}>취소</button>
                </div>
              ) : (
                <div className="set-broker-actions">
                  <button type="button" className="set-btn set-btn--sm set-broker-check" disabled={checking === a.account_id}
                          aria-busy={checking === a.account_id} onClick={() => void check(a.account_id)}>
                    {checking === a.account_id ? "확인하는 중" : "연결 확인"}
                  </button>
                  <button type="button" className="set-btn set-btn--sm set-broker-delete" onClick={() => setAsking(a.account_id)}>
                    지우기
                  </button>
                </div>
              )}
              {result ? <CheckResult result={result} /> : null}
            </div>
          );
        })}
        {rowError ? <p className="set-error" role="alert">지우지 못했어요. {rowError}</p> : null}
      </div>

      <ConnectForm onConnected={() => void load()} />
    </section>
  );
}

function CheckResult({ result }: { result: CheckView }) {
  const failed = result.state === "failed" || result.state === "error";
  return (
    <div className="set-broker-result" data-state={result.state} role={failed ? "alert" : "status"}>
      <p className={failed ? "set-error" : "set-sub"} data-server>{result.reason}</p>
      {"detail" in result && result.detail ? (
        <details className="set-broker-raw">
          <summary>원래 사유 보기</summary>
          <code data-server>{result.detail}</code>
        </details>
      ) : null}
    </div>
  );
}

function ConnectForm({ onConnected }: { onConnected: () => void }) {
  const [label, setLabel] = useState("");
  const [appKey, setAppKey] = useState("");
  const [secret, setSecret] = useState("");
  const [accountNo, setAccountNo] = useState("");
  const [product, setProduct] = useState("01");
  const [kind, setKind] = useState<"paper" | "real" | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ text: string; vault: boolean } | null>(null);

  const accountOk = ACCOUNT_NO.test(accountNo);
  const ready = label.trim() !== "" && appKey.trim() !== "" && secret !== "" && accountOk
    && PRODUCT.test(product) && kind !== null;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!ready || busy || kind === null) return;
    setBusy(true); setError(null);
    const r = await connectBrokerAccount({
      label: label.trim(), app_key: appKey.trim(), app_secret: secret, account_no: accountNo,
      is_paper: kind === "paper", account_prdt: product,
    });
    setBusy(false);
    if (!r.ok) { setError({ text: r.error, vault: r.status === 503 }); return; }
    // ★비밀을 상태에 남기지 않는다★ — 연결이 끝나면 칸을 모두 비운다.
    setLabel(""); setAppKey(""); setSecret(""); setAccountNo(""); setProduct("01"); setKind(null);
    onConnected();
  };

  return (
    <form className="set-card set-broker-form" onSubmit={submit} noValidate aria-busy={busy}>
      <p className="set-strong">계좌 연결하기</p>
      <label className="set-field">
        <span className="set-label">이름</span>
        <input className="set-input" name="broker-label" autoComplete="off" maxLength={64}
               value={label} onChange={(e) => setLabel(e.target.value)} />
        <span className="set-sub">목록에서 알아보는 이름이에요.</span>
      </label>
      <label className="set-field">
        <span className="set-label">앱 키</span>
        <input className="set-input" name="broker-app-key" autoComplete="off" spellCheck={false}
               value={appKey} onChange={(e) => setAppKey(e.target.value)} />
      </label>
      <label className="set-field">
        <span className="set-label">앱 시크릿</span>
        <input className="set-input" name="broker-app-secret" type="password" autoComplete="off" spellCheck={false}
               value={secret} onChange={(e) => setSecret(e.target.value)} />
      </label>
      <div className="set-broker-pair">
        <label className="set-field">
          <span className="set-label">계좌번호 앞 8자리</span>
          <input className="set-input" name="broker-account-no" inputMode="numeric" autoComplete="off" maxLength={8}
                 value={accountNo} onChange={(e) => setAccountNo(e.target.value.trim())}
                 aria-invalid={accountNo.length > 0 && !accountOk} />
          {accountNo.length > 0 && !accountOk ? <span className="set-hint">계좌번호는 숫자 8자리예요.</span> : null}
        </label>
        <label className="set-field">
          <span className="set-label">상품 코드</span>
          <input className="set-input" name="broker-account-prdt" inputMode="numeric" autoComplete="off" maxLength={2}
                 value={product} onChange={(e) => setProduct(e.target.value.trim())}
                 aria-invalid={!PRODUCT.test(product)} />
          <span className="set-sub">보통 01이에요.</span>
        </label>
      </div>
      <div className="set-row">
        <span className="set-label set-label--row" id="set-broker-kind-l">계좌 종류</span>
        <div className="set-seg set-seg--2 set-broker-kind" role="group" aria-labelledby="set-broker-kind-l">
          {([["paper", "모의투자"], ["real", "실계좌"]] as const).map(([k, l]) => (
            <button key={k} type="button" data-kind={k} className={`set-seg-b${kind === k ? " on" : ""}`}
                    aria-pressed={kind === k} onClick={() => setKind(k)}>{l}</button>
          ))}
        </div>
      </div>
      {kind === "real" ? (
        <p className="set-warn set-broker-real-note">
          실계좌로 주문하려면 운영자가 실계좌 관문을 열어야 해요. 연결만으로는 주문이 나가지 않아요.
        </p>
      ) : null}
      {error ? (
        <div role="alert">
          <p className="set-error" data-server>{error.text}</p>
          {error.vault ? (
            <p className="set-sub set-broker-vault">
              서버에 자격을 암호화할 키가 없어 아무것도 저장하지 않았어요. 운영자에게 알려 주세요.
            </p>
          ) : null}
        </div>
      ) : null}
      <button type="submit" className="set-btn set-btn--primary set-broker-submit" disabled={!ready || busy}>
        {busy ? "연결하는 중이에요" : "계좌 연결하기"}
      </button>
    </form>
  );
}
