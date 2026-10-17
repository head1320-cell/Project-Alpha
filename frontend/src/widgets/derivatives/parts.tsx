"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// 파생상품 계산기 공용 부품(BU7c) — 숫자 칸 · 계산 상태(낡음 표시) · 결과 줄.
// ★빈 칸은 0 이 아니라 "값을 넣어 주세요"★ 옛 화면은 `Number("")` 가 0 이라 빈 칸으로 계산을 보냈다.
// ★입력을 바꾸면 결과에 낡았다고 쓴다★ 옛 화면은 입력을 바꿔도 이전 결과를 지금 값처럼 두었다.
// ★실패하면 옛 결과를 지운다★ react-query 변이는 새 요청을 시작할 때 결과를 비운다 — 실패 화면에 옛 숫자가 남지 않는다.
// ═══════════════════════════════════════════════════════════════════════════════
import { useState, type ReactNode } from "react";
import { useMutation } from "@tanstack/react-query";
import { Notice, RetryFail } from "@/shared/ui/tx";

export type Raw = Record<string, string>;
export const EMPTY = "값을 넣어 주세요";

/** 문자열 → 숫자. 빈 칸·숫자가 아님 → null(0 으로 바꾸지 않는다). */
export function parse(s: string): number | null {
  const t = s.replace(/,/g, "").trim();
  if (!t) return null;
  const v = Number(t);
  return Number.isFinite(v) ? v : null;
}

export function NumField({ id, label, unit, value, onChange, missing, hint, step }: {
  id: string; label: string; unit?: string; value: string; onChange: (v: string) => void; missing?: boolean; hint?: ReactNode; step?: string;
}) {
  return (
    <label className="dv-field" htmlFor={id}>
      <span className="dv-field-l">{label}</span>
      <span className="dv-field-box" data-missing={missing ? "1" : undefined}>
        <input id={id} className="input dv-input" type="number" inputMode="decimal" step={step ?? "any"} value={value}
          onChange={(e) => onChange(e.target.value)} aria-invalid={missing || undefined} />
        {unit ? <span className="dv-unit">{unit}</span> : null}
      </span>
      {missing ? <span className="dv-field-miss" role="status">{EMPTY}</span> : hint ? <span className="dv-field-hint">{hint}</span> : null}
    </label>
  );
}

/**
 * 계산 한 번 = 변이 한 번. `run` 은 빈 칸이 있으면 요청하지 않고 빈 칸 표시만 켠다.
 * `stale` = 마지막으로 계산한 입력과 지금 입력이 다르다(결과가 있을 때만 의미 있다).
 */
export function useCalc<B, R>(fn: (body: B) => Promise<R>) {
  const m = useMutation({ mutationFn: fn });
  const [ranWith, setRanWith] = useState<string | null>(null);
  const [tried, setTried] = useState(false);
  return {
    m, tried,
    run(raw: Raw, body: B | null) {
      setTried(true);
      if (body == null) { m.reset(); return; }
      setRanWith(JSON.stringify(raw));
      m.mutate(body);
    },
    stale(raw: Raw) { return !!m.data && ranWith != null && ranWith !== JSON.stringify(raw); },
  };
}

export function StaleNote({ onRerun }: { onRerun: () => void }) {
  return (
    <div className="dv-stale" role="status">
      <Notice tone="warn" title="입력이 바뀌었어요. 아래 결과는 이전 입력으로 계산한 값이에요.">
        <div className="ms-act"><button type="button" className="tx-btn tx-btn--sub" onClick={onRerun}>다시 계산하기</button></div>
      </Notice>
    </div>
  );
}

export function CalcFail({ what, error, onRetry }: { what: string; error: unknown; onRetry: () => void }) {
  return (
    <RetryFail title={`${what}을 계산하지 못했어요`} onRetry={onRetry}>
      <span data-server>{error instanceof Error ? error.message : String(error)}</span>
    </RetryFail>
  );
}

/** 결과 숫자 한 칸 — 값 + 한 줄 풀이(툴팁 아님, 보이는 글). */
export function Fig({ label, value, why, k }: { label: string; value: ReactNode; why?: ReactNode; k?: string }) {
  return (
    <div className="dv-fig" data-k={k}>
      <dt>{label}</dt>
      <dd><b className="dv-fig-v">{value}</b>{why ? <span className="dv-fig-why">{why}</span> : null}</dd>
    </div>
  );
}

export const won = (v: number, d = 0) => `${v.toLocaleString("ko-KR", { minimumFractionDigits: d, maximumFractionDigits: d })}원`;
export const sgn = (v: number, d: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(d)}`;
