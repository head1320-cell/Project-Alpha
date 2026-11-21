"use client";
/**
 * 갱신 시각 줄 — 주기 조회 화면의 '마지막 수신' (U2 · 설계 문서 §5.1)
 * ==========================================================================
 * 'N초마다 다시 읽습니다 · 마지막 수신 hh:mm:ss'(이 기기 시각) — 값이 바뀌었다고 번쩍이는 대신 글자로 말한다(ADR 007 §7).
 * ★낭독하지 않는다★ `aria-live` · `role="status"` 를 달지 않는다(주기마다 읽히면 화면 낭독기 사용자를 방해한다) — 보이는 글자만.
 * `updatedAt` 은 TanStack Query 의 `dataUpdatedAt`(마지막으로 성공한 응답을 받은 때)이라 실패하는 동안에는 그 시각에 멈춘다 —
 * 조회 중이라고 글자를 바꾸지 않는다. 옛 클래스(예: 실거래의 `lv-polled`)는 `className` 으로 같은 요소에 남긴다.
 */
import { freshnessText } from "./provenance";

export function Freshness({ updatedAt, intervalMs, className, as = "p" }: {
  updatedAt: number;
  intervalMs?: number | null;
  className?: string;
  /** 문장 안에 놓일 때는 span(예: 머리의 동작 줄) — 기본은 p. */
  as?: "p" | "span";
}) {
  const Tag = as;
  return <Tag className={className ? `tx-fresh ${className}` : "tx-fresh"}>{freshnessText({ updatedAt, intervalMs })}</Tag>;
}
