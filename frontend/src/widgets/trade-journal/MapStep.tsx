"use client";
/**
 * 매매일지 ② 열 맞추기 — 파일의 열을 서버가 받는 칸에 대응시킨다.
 * ==========================================================================
 * 어림(`guessMapping`)은 처음 한 번 골라 둘 뿐이다 — 전부 고칠 수 있고, 고른 대로만 보낸다.
 * ★기본값을 지어 넣지 않는다★ — 수수료율의 기본은 '모름'(0 이 아니다), 시장을 모르는 종목의 기본은 '미상으로 둠'이다.
 * 매수·매도 열의 값은 하나하나 뜻을 정해야 한다(어림하지 못한 값은 사용자가 고른다 — 입금·출금 같은 줄은 '제외').
 */
import { useMemo, useRef, type KeyboardEvent } from "react";
import {
  FIELD_KO, REQUIRED, distinctValues, normalizeRows, type FieldKey, type Mapping, type SideChoice, type Table,
} from "@/entities/trade-journal";
import { num } from "@/shared/lib/krFormat";
import { Section } from "@/shared/ui/tx";
import { INSTRUMENT_KO, MARKET_KO } from "./format";

export type FeeMode = "file" | "rate" | "unknown";
export type TaxMode = "file" | "table";
export type UnknownAs = "none" | "KOSPI" | "KOSDAQ";
export type Settings = {
  mapping: Mapping; sides: Record<string, SideChoice>;
  feeMode: FeeMode; ratePct: string; taxMode: TaxMode; unknownAs: UnknownAs;
};

export const SIDE_LIMIT = 12;

/** 수수료율 글자(%) → bp. 0 이상 10 이하의 수만. 아니면 `null`. */
export function rateToBp(text: string): number | null {
  const t = text.trim();
  if (!/^\d+(\.\d+)?$/.test(t)) return null;
  const pctValue = Number(t);
  return pctValue <= 10 ? Math.round(pctValue * 100 * 1e6) / 1e6 : null;
}

/** 지금 설정으로는 분석할 수 없는 사유들(없으면 빈 배열). */
export function problemsOf(table: Table, s: Settings): string[] {
  const out: string[] = [];
  const missing = REQUIRED.filter((f) => s.mapping[f] === null);
  if (missing.length) out.push(`필수 열 미지정: ${missing.map((f) => FIELD_KO[f]).join(" · ")}`);
  if (s.mapping.side !== null) {
    const { values, more } = distinctValues(table, s.mapping.side, SIDE_LIMIT);
    if (more) out.push(`매수·매도 열의 값이 ${SIDE_LIMIT}가지를 넘습니다. 열을 다시 지정하십시오.`);
    else {
      const open = values.filter((v) => !s.sides[v]);
      if (open.length) out.push(`매수·매도 값 미지정: ${open.map((v) => v || "(빈칸)").join(" · ")}`);
    }
  }
  if (s.feeMode === "file" && s.mapping.fee === null) out.push("수수료 열 미지정");
  if (s.feeMode === "rate" && rateToBp(s.ratePct) === null) out.push("수수료율은 0 이상 10 이하의 수(%)로 입력하십시오.");
  if (s.taxMode === "file" && s.mapping.tax === null) out.push("세금 열 미지정");
  return out;
}

type Opt<T extends string> = { value: T; label: string };

/** 하나 고르기(라디오 묶음) — 아직 아무것도 고르지 않은 상태가 있어 공용 `Segmented` 대신 둔다(그때는 첫 항목이 Tab 을 받는다). */
function Pick<T extends string>({ label, options, value, onChange }: { label: string; options: Opt<T>[]; value: T | null; onChange: (v: T) => void }) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const cur = options.findIndex((o) => o.value === value);
  const onKey = (e: KeyboardEvent) => {
    const n = options.length, i = cur < 0 ? 0 : cur;
    const to = e.key === "ArrowRight" || e.key === "ArrowDown" ? (cur < 0 ? 0 : (i + 1) % n)
      : e.key === "ArrowLeft" || e.key === "ArrowUp" ? (i - 1 + n) % n : e.key === "Home" ? 0 : e.key === "End" ? n - 1 : -1;
    if (to < 0) return;
    e.preventDefault();
    onChange(options[to].value);
    refs.current[to]?.focus();
  };
  return (
    <div className="tx-seg tj-pick" role="radiogroup" aria-label={label}>
      {options.map((o, i) => {
        const on = i === cur;
        return (
          <button key={o.value} ref={(el) => { refs.current[i] = el; }} type="button" role="radio" aria-checked={on}
                  tabIndex={on || (cur < 0 && i === 0) ? 0 : -1} className={`tx-seg-opt${on ? " tx-seg-opt--on" : ""}`}
                  onClick={() => onChange(o.value)} onKeyDown={onKey}>
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

const SIDE_OPTS: Opt<SideChoice>[] = [{ value: "buy", label: "매수" }, { value: "sell", label: "매도" }, { value: "skip", label: "제외" }];
const FEE_OPTS: Opt<FeeMode>[] = [{ value: "file", label: "파일의 열" }, { value: "rate", label: "요율 입력" }, { value: "unknown", label: "모름" }];
const TAX_OPTS: Opt<TaxMode>[] = [{ value: "file", label: "파일의 열" }, { value: "table", label: "세율표로 추론" }];
const UNKNOWN_OPTS: Opt<UnknownAs>[] = [
  { value: "none", label: "미상으로 둠" }, { value: "KOSPI", label: "코스피 주식으로 가정" }, { value: "KOSDAQ", label: "코스닥 주식으로 가정" },
];
const MAIN: FieldKey[] = ["date", "time", "symbol", "name", "side", "quantity", "price"];
const EXTRA: FieldKey[] = ["market", "instrument"];

export function MapStep({ table, settings: s, onChange, problems, pending, stale, onRun }: {
  table: Table; settings: Settings; onChange: (next: Settings) => void; problems: string[]; pending: boolean; stale: boolean; onRun: () => void;
}) {
  const set = <K extends keyof Settings>(k: K, v: Settings[K]) => onChange({ ...s, [k]: v });
  const setCol = (f: FieldKey, raw: string) => set("mapping", { ...s.mapping, [f]: raw === "" ? null : Number(raw) });

  const column = (f: FieldKey) => (
    <label key={f} className="tj-field">
      <span className="tj-label">{FIELD_KO[f]}{REQUIRED.includes(f) ? <em className="tj-req">필수</em> : null}</span>
      <select className="tj-input tj-col" data-field={f} value={s.mapping[f] === null ? "" : String(s.mapping[f])} onChange={(e) => setCol(f, e.target.value)}>
        <option value="">선택 안 함</option>
        {table.headers.map((h, i) => <option key={i} value={i}>{h}</option>)}
      </select>
    </label>
  );

  const sideValues = s.mapping.side === null ? null : distinctValues(table, s.mapping.side, SIDE_LIMIT);
  const preview = normalizeRows({ ...table, rows: table.rows.slice(0, 5), lines: table.lines.slice(0, 5) },
    { mapping: s.mapping, sides: s.sides, feeFromFile: s.feeMode === "file", taxFromFile: s.taxMode === "file" });
  const padded = useMemo(() => normalizeRows(table, { mapping: s.mapping, sides: s.sides, feeFromFile: false, taxFromFile: false }).padded,
    [table, s.mapping, s.sides]);
  const cell = (v: number | string | null | undefined) => (v === null || v === undefined ? "" : typeof v === "number" ? num(v, Number.isInteger(v) ? 0 : 2) : v);
  const bad = (v: unknown) => typeof v === "string";
  const rateBp = rateToBp(s.ratePct);

  return (
    <Section title="열 맞추기" sub="파일의 열을 아래 칸에 대응시킵니다. 열 이름으로 미리 지정해 두었으니 확인하고 필요하면 변경하십시오.">
      <div className="tj-map">
        <div className="tj-fields">{MAIN.map(column)}</div>
        <p className="tj-note">체결 일시가 날짜와 시각 두 열로 나뉜 파일은 ‘체결 일시’에 날짜 열을, ‘체결 시각’에 시각 열을 지정합니다.</p>

        {sideValues ? (
          <div className="tj-block">
            <h3 className="tj-h3">매수·매도 값</h3>
            {sideValues.more ? <p className="tj-note">값이 {SIDE_LIMIT}가지를 넘습니다. 매수·매도 열이 맞는지 확인하십시오.</p> : (
              <ul className="tj-sides">
                {sideValues.values.map((v) => (
                  <li key={v} className="tj-side-row" data-value={v}>
                    <span className="tj-side-v" data-mono>{v || "(빈칸)"}</span>
                    <Pick label={`‘${v || "빈칸"}’의 뜻`} options={SIDE_OPTS} value={s.sides[v] ?? null} onChange={(c) => set("sides", { ...s.sides, [v]: c })} />
                  </li>
                ))}
              </ul>
            )}
            <p className="tj-note">입금·출금·배당처럼 체결이 아닌 줄은 ‘제외’로 지정합니다.</p>
          </div>
        ) : null}

        <div className="tj-block tj-cost-opts">
          <h3 className="tj-h3">비용</h3>
          <div className="tj-opt">
            <span className="tj-label">수수료</span>
            <div className="tj-fee-mode"><Pick label="수수료를 어디서 읽을지" options={FEE_OPTS} value={s.feeMode} onChange={(v) => set("feeMode", v)} /></div>
            {s.feeMode === "file" ? column("fee") : null}
            {s.feeMode === "rate" ? (
              <label className="tj-field tj-rate-l">
                <span className="tj-label">편도 수수료율(%)</span>
                <input className="tj-input tj-fee-rate" inputMode="decimal" autoComplete="off" placeholder="예: 0.015" value={s.ratePct}
                       aria-invalid={rateBp === null && s.ratePct !== ""} onChange={(e) => set("ratePct", e.target.value)} />
              </label>
            ) : null}
            <p className="tj-note">
              {s.feeMode === "file" ? "파일에 적힌 수수료를 그대로 씁니다(관측)."
                : s.feeMode === "rate" ? "체결 대금에 이 요율을 곱해 수수료로 봅니다(가정). 매수와 매도에 같은 요율을 적용합니다."
                : "수수료를 계산하지 않습니다. 비용 후 통계는 N/A 로 표시됩니다."}
            </p>
          </div>
          <div className="tj-opt">
            <span className="tj-label">매도세</span>
            <div className="tj-tax-mode"><Pick label="매도세를 어디서 읽을지" options={TAX_OPTS} value={s.taxMode} onChange={(v) => set("taxMode", v)} /></div>
            {s.taxMode === "file" ? column("tax") : null}
            <p className="tj-note">
              {s.taxMode === "file" ? "파일에 적힌 세금을 그대로 씁니다(관측)."
                : "거래일·시장·상품별 세율표로 매도세를 산출합니다(추론). 시장과 상품을 알 수 있는 종목만 산출합니다."}
            </p>
          </div>
          {s.taxMode === "table" ? (
            <div className="tj-opt">
              <div className="tj-fields tj-fields--pair">{EXTRA.map(column)}</div>
              <span className="tj-label">시장을 모르는 종목</span>
              <div className="tj-unknown-market"><Pick label="시장을 모르는 종목의 처리" options={UNKNOWN_OPTS} value={s.unknownAs} onChange={(v) => set("unknownAs", v)} /></div>
              <p className="tj-note">
                {s.unknownAs === "none" ? "파일과 종목 마스터로 시장을 알 수 없는 종목은 매도세를 미상으로 둡니다."
                  : "시장을 알 수 없는 종목을 지정한 시장의 주식으로 보고 매도세를 산출합니다(가정). ETF 는 매도세가 없으므로 ETF 가 섞여 있으면 세금이 과대 산출됩니다."}
              </p>
            </div>
          ) : null}
        </div>

        <div className="tj-block">
          <h3 className="tj-h3">미리 보기</h3>
          <p className="tj-note">지금 설정으로 서버에 보낼 줄의 앞 {preview.fills.length}건입니다. 이 밖의 열은 보내지 않습니다.</p>
          <div className="tj-scroll">
            <table className="tj-table tj-preview">
              <thead><tr><th scope="col">체결 일시</th><th scope="col">종목</th><th scope="col">매수·매도</th><th scope="col" className="tj-num">수량</th><th scope="col" className="tj-num">단가</th>
                {s.feeMode === "file" ? <th scope="col" className="tj-num">수수료</th> : null}{s.taxMode === "file" ? <th scope="col" className="tj-num">세금</th> : null}<th scope="col">시장</th></tr></thead>
              <tbody>
                {preview.fills.map((f, i) => (
                  <tr key={i}>
                    <td data-mono>{f.executed_at ?? ""}</td>
                    <td><span data-mono>{f.symbol ?? ""}</span>{f.name ? <span className="tj-sub" data-server> {f.name}</span> : null}</td>
                    <td>{f.side === "buy" ? "매수" : f.side === "sell" ? "매도" : "미지정"}</td>
                    <td className="tj-num" data-bad={bad(f.quantity) || undefined} data-mono>{cell(f.quantity)}</td>
                    <td className="tj-num" data-bad={bad(f.price) || undefined} data-mono>{cell(f.price)}</td>
                    {s.feeMode === "file" ? <td className="tj-num" data-mono>{cell(f.fee)}</td> : null}
                    {s.taxMode === "file" ? <td className="tj-num" data-mono>{cell(f.tax)}</td> : null}
                    <td>{[f.market ? MARKET_KO[f.market] : null, f.instrument ? INSTRUMENT_KO[f.instrument] : null].filter(Boolean).join(" · ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {padded > 0 ? <p className="tj-note tj-padded">숫자로만 된 6자리 미만 종목코드 {padded.toLocaleString("ko-KR")}줄은 앞자리 0 을 채웁니다(엑셀이 지운 0).</p> : null}
        </div>

        <div className="tj-run-row">
          <button type="button" className="tx-btn tx-btn--main tj-run" disabled={problems.length > 0 || pending} onClick={onRun}>{pending ? "계산 중" : "분석"}</button>
          {problems.length ? <ul className="tj-map-miss">{problems.map((p) => <li key={p}>{p}</li>)}</ul> : null}
          {!problems.length && stale ? <p className="tj-note tj-stale">설정이 변경됐습니다. 재계산이 필요합니다.</p> : null}
        </div>
      </div>
    </Section>
  );
}
