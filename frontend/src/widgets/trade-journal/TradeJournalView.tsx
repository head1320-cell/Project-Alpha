"use client";
/**
 * 매매일지 (v1) — `/trade-journal`. 체결 내역 파일 → 열 맞추기 → 결과. 세 단계가 한 화면에 위에서 아래로 쌓인다.
 * ==========================================================================
 * 설계: `docs/superpowers/specs/2026-11-14-trade-journal-design.md`.
 * ★파일은 이 브라우저에서 읽는다★ — 서버로는 맞춘 줄만 보내고(계좌번호 같은 다른 열은 나가지 않는다) 서버는 저장하지 않는다.
 * ★낡은 결과를 남기지 않는다★ — 파일이나 설정을 바꾸면 앞의 결과를 지우고 재계산이 필요하다고 말한다(옛 숫자가 새 설정 아래 남지 않게).
 * 세션 넷은 내 계좌 화면과 같은 판정(`useSession`). 로그인이 필요한 까닭: 개인의 매매 기록이 지나가는 문이라 익명으로 열어 두지 않는다.
 */
import Link from "next/link";
import { useRef, useState, type DragEvent } from "react";
import {
  SAMPLE_CSV, SAMPLE_NAME, DELIMITER_KO, analyzeTrades, decodeBytes, distinctValues, guessMapping, guessSide, normalizeRows, parseTable,
  type Encoding, type Journal, type Mapping, type SideChoice, type Table,
} from "@/entities/trade-journal";
import { useSession } from "@/entities/session";
import { loginHref } from "@/shared/lib/nextPath";
import { Notice, PageHead, RetryFail, Section } from "@/shared/ui/tx";
import { JournalResult } from "./JournalResult";
import { MapStep, SIDE_LIMIT, problemsOf, rateToBp, type Settings } from "./MapStep";

const TITLE = "매매일지";
const LEDE = "체결 내역 파일로 왕복 거래의 승률·손익비·비용을 집계합니다. 관측값만 보여 주며 종목이나 매매 시점을 권하지 않습니다.";
const MAX_BYTES = 20 * 1024 * 1024;
const HERE = "/trade-journal";

type Loaded = { name: string; encoding: Encoding; table: Table; sample: boolean };
type Run =
  | { kind: "idle" } | { kind: "pending" }
  | { kind: "fail"; status: number; error: string }
  | { kind: "done"; journal: Journal; lines: number[]; skipped: number; padded: number; sample: boolean };

export function TradeJournalView() {
  const { session, retry } = useSession();
  return (
    <div className="tx-page tj">
      <PageHead title={TITLE} lede={LEDE} />
      {session.kind === "loading" ? (
        <p className="tx-sec-sub" aria-busy="true">계정 확인 중</p>
      ) : session.kind === "unknown" ? (
        <RetryFail title="계정 정보 확인 실패" onRetry={() => void retry()}>{session.reason}</RetryFail>
      ) : session.kind === "signed_out" ? (
        <section className="tx-sec tj-signed-out">
          <p className="tj-strong">로그인하면 매매일지를 사용할 수 있습니다.</p>
          <p className="tx-sec-sub">개인의 매매 기록을 다루므로 로그인한 계정만 분석을 요청할 수 있습니다. 올린 체결 내역은 계산에만 쓰고 서버에 저장하지 않습니다.</p>
          <Link href={loginHref(HERE)} className="tx-btn tx-btn--main">로그인</Link>
        </section>
      ) : session.mustChange ? (
        <section className="tx-sec tj-must" role="alert">
          <p className="tj-strong">비밀번호를 먼저 변경하십시오.</p>
          <p className="tx-sec-sub">관리자가 발급한 임시 비밀번호로는 매매일지를 사용할 수 없습니다.</p>
          <Link href="/settings#password" className="tx-btn tx-btn--main">비밀번호 바꾸러 가기</Link>
        </section>
      ) : (
        <Journal_ />
      )}
    </div>
  );
}

/** 열 어림 + 매수·매도 값 어림으로 처음 설정을 만든다. 수수료·세금은 파일에 열이 있을 때만 '파일의 열', 아니면 모름·세율표. */
function initialSettings(table: Table): Settings {
  const mapping = guessMapping(table.headers);
  return {
    mapping, sides: sidesFor(table, mapping, {}),
    feeMode: mapping.fee !== null ? "file" : "unknown", ratePct: "",
    taxMode: mapping.tax !== null ? "file" : "table", unknownAs: "none",
  };
}

/** 매수·매도 열의 값마다 뜻을 어림한다 — 이미 사용자가 정한 값은 그대로 두고, 어림하지 못한 값은 비워 둔다. */
function sidesFor(table: Table, mapping: Mapping, kept: Record<string, SideChoice>): Record<string, SideChoice> {
  if (mapping.side === null) return {};
  const out: Record<string, SideChoice> = {};
  for (const v of distinctValues(table, mapping.side, SIDE_LIMIT).values) {
    const g = kept[v] ?? guessSide(v);
    if (g) out[v] = g;
  }
  return out;
}

function Journal_() {
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<Loaded | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [run, setRun] = useState<Run>({ kind: "idle" });
  const [stale, setStale] = useState(false);
  const [over, setOver] = useState(false);

  const load = (name: string, bytes: ArrayBuffer, sample = false) => {
    setRun({ kind: "idle" });
    setStale(false);
    const decoded = decodeBytes(bytes);
    const table = parseTable(decoded.text);
    if ("error" in table) { setFile(null); setSettings(null); setFileError(`‘${name}’ 읽기 실패: ${table.error}`); return; }
    setFileError(null);
    setFile({ name, encoding: decoded.encoding, table, sample });
    setSettings(initialSettings(table));
  };
  const pick = async (f: File | undefined | null) => {
    if (!f) return;
    if (f.size > MAX_BYTES) { setFile(null); setSettings(null); setRun({ kind: "idle" }); setFileError(`‘${f.name}’ 읽기 실패: 파일이 20MB 를 넘습니다. 기간을 나눠 내보내십시오.`); return; }
    load(f.name, await f.arrayBuffer());
  };
  const onDrop = (e: DragEvent) => { e.preventDefault(); setOver(false); void pick(e.dataTransfer.files?.[0]); };

  const change = (next: Settings) => {
    if (!file || !settings) return;
    // 매수·매도 열을 바꾸면 그 열의 값으로 다시 어림한다(앞 열의 대응을 새 열에 끌고 가지 않는다).
    const sides = next.mapping.side !== settings.mapping.side ? sidesFor(file.table, next.mapping, {}) : next.sides;
    setSettings({ ...next, sides });
    if (run.kind !== "idle") { setRun({ kind: "idle" }); setStale(true); }
  };

  const problems = file && settings ? problemsOf(file.table, settings) : [];
  const analyze = async () => {
    if (!file || !settings || problems.length) return;
    const n = normalizeRows(file.table, { mapping: settings.mapping, sides: settings.sides, feeFromFile: settings.feeMode === "file", taxFromFile: settings.taxMode === "file" });
    setRun({ kind: "pending" });
    setStale(false);
    const assume = settings.taxMode === "table" && settings.unknownAs !== "none" ? settings.unknownAs : null;
    const r = await analyzeTrades({
      fills: n.fills,
      commission_bp: settings.feeMode === "rate" ? rateToBp(settings.ratePct) : null,
      unknown_market: assume, unknown_instrument: assume ? "stock" : null,
    });
    setRun(r.ok ? { kind: "done", journal: r.value, lines: n.lines, skipped: n.skipped, padded: n.padded, sample: file.sample }
      : { kind: "fail", status: r.status, error: r.error });
  };

  const t = file?.table;
  return (
    <>
      <Section title="체결 내역 파일" sub="증권사 HTS·MTS 에서 내보낸 체결 내역(CSV · 탭 구분 텍스트)을 선택합니다. 열 이름이 첫 줄에 있어야 합니다.">
        <div className="tj-file">
          <div className={`tj-drop${over ? " tj-drop--over" : ""}`} onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)} onDrop={onDrop}>
            <p className="tj-drop-t">파일을 여기에 끌어 놓거나 선택하십시오.</p>
            <div className="tj-drop-act">
              <button type="button" className="tx-btn tx-btn--main" onClick={() => input.current?.click()}>파일 선택</button>
              <button type="button" className="tx-btn tx-btn--sub tj-sample" onClick={() => load(SAMPLE_NAME, new TextEncoder().encode(SAMPLE_CSV).buffer as ArrayBuffer, true)}>예시 불러오기</button>
            </div>
            <input ref={input} className="tj-file-input tx-sr" type="file" accept=".csv,.tsv,.txt,text/csv,text/plain" aria-label="체결 내역 파일"
                   onChange={(e) => { void pick(e.target.files?.[0]); e.target.value = ""; }} />
          </div>
          <ul className="tj-plain-list tj-file-notes">
            <li>파일은 이 브라우저에서 읽습니다. 서버에는 아래에서 맞춘 열만 보내며, 서버는 저장하지 않습니다.</li>
            <li>필수 열: 체결 일시 · 종목 · 매수·매도 · 수량 · 단가. 선택 열: 수수료 · 세금 · 시장 · 종목명.</li>
            <li>국내 주식·ETF 의 현금 매매만 다룹니다. 한 번에 20,000줄까지 분석합니다.</li>
          </ul>
          {fileError ? <div className="tj-file-fail"><Notice tone="danger" title="파일 읽기 실패">{fileError}</Notice></div> : null}
          {file && t ? (
            <p className="tj-read tj-file-meta">
              <b>{file.name}</b> · {file.encoding} · {DELIMITER_KO[t.delimiter]} 구분 · {t.rows.length.toLocaleString("ko-KR")}줄 · 열 {t.headers.length}개
              {file.sample ? " · 예시용 임의 숫자(실제 종목·시세 아님)" : ""}
            </p>
          ) : null}
        </div>
      </Section>

      {file && settings ? (
        <MapStep table={file.table} settings={settings} onChange={change} problems={problems} pending={run.kind === "pending"} stale={stale} onRun={() => void analyze()} />
      ) : null}

      {run.kind === "fail" ? (
        <div className="tj-run-fail">
          {run.status === 401 ? (
            <Notice tone="danger" title="로그인 세션이 만료됐습니다.">
              다시 로그인한 뒤 파일을 다시 선택하십시오. <Link href={loginHref(HERE)} className="tj-link">로그인</Link>
            </Notice>
          ) : run.status === 400 || run.status === 422 ? (
            <Notice tone="danger" title="분석 요청 거절"><span data-server>{run.error}</span></Notice>
          ) : (
            <RetryFail title="분석 실패" onRetry={() => void analyze()}><span data-server>{run.error}</span></RetryFail>
          )}
        </div>
      ) : null}

      {run.kind === "done" ? <JournalResult journal={run.journal} extra={{ lines: run.lines, skipped: run.skipped, padded: run.padded, sample: run.sample }} /> : null}
    </>
  );
}
