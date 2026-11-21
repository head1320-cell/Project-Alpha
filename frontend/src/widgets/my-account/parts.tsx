"use client";
/** 내 계좌(BV9) 화면 조각 — 서버 Result 를 react-query 로 받는 도우미 · 종목 이름(stock_master) · 시각 서식. */
import { useQuery } from "@tanstack/react-query";
import { allocationApi } from "@/entities/allocation/api";
import type { Result } from "@/shared/api/result";

/** Result → react-query: 실패는 서버 사유를 담은 Error 로 던진다(화면이 `error.message` 로 그대로 보인다). */
export const unwrap = <T,>(fn: () => Promise<Result<T>>) => async (): Promise<T> => {
  const r = await fn();
  if (!r.ok) throw new Error(r.error);
  return r.value;
};

/**
 * 종목 이름 — ★stock_master 가 정한 이름만★(`/allocation/resolve-names`). 서버가 코드를 그대로 돌려주면 모르는 코드다.
 * 실패면 `failed`(이름을 지어내지 않는다 — 코드만 보인다).
 */
export function useNames(codes: string[]) {
  const key = [...new Set(codes)].sort();
  const q = useQuery({
    queryKey: ["names", key], enabled: key.length > 0,
    queryFn: () => allocationApi.resolveNames(key),
  });
  const known = (c: string): string | null => {
    const n = q.data?.[c];
    return n && n !== c ? n : null;
  };
  return { known, failed: q.isError, pending: q.isPending && key.length > 0 };
}

/** "2026-10-09 12:01:00" 이나 ISO → "10월 9일 12:01". 모르면 null. */
export function when(iso: string | null | undefined): string | null {
  const m = iso?.match(/^\d{4}-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);
  return m ? `${Number(m[1])}월 ${Number(m[2])}일 ${m[3]}:${m[4]}` : null;
}
