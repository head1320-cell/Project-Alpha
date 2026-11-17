/**
 * 규칙이 쓴 하루 유형 모형의 사실 줄 (구현 계획 2026-11-16 §6 · T2)
 * ==========================================================================
 * 모형마다 학습 기간 · 종목 수 · 판정 종목과 같은지 · 합성이면 그렇다고 — ★서버 문장 그대로★ 싣는다(화면이 짓지 않는다).
 * 규칙이 하루 유형을 쓰지 않았으면 아무것도 그리지 않는다. 학습이 판정 시작일 전에 끝났는지는 서버가 이미 판정했다(아니면 거절).
 * 자리: 백테스트 › 분봉 규칙의 결과 · 매매일지의 견주기 · 캔버스의 분봉 설정 · 결과 조회 판(같은 부품 · 같은 클래스).
 */
import type { ContextFact } from "@/entities/intraday";

/** 모양을 모르는 값(캔버스 노드의 보기)에서 사실 줄만 고른다 — 열쇠와 문장 목록이 없는 줄은 그리지 않는다(지어내지 않는다). */
export const factsOf = (v: unknown): ContextFact[] =>
  Array.isArray(v)
    ? v.filter((f): f is ContextFact => !!f && typeof f === "object" && typeof (f as ContextFact).key === "string"
        && Array.isArray((f as ContextFact).sentences) && (f as ContextFact).sentences.every((s) => typeof s === "string"))
    : [];

export function ContextFacts({ facts }: { facts: ContextFact[] | undefined }) {
  if (!facts || facts.length === 0) return null;
  return (
    <section className="itd-ctx" aria-label="규칙이 쓴 하루 유형 모형">
      <h4 className="itd-ctx-title">규칙이 쓴 하루 유형 모형</h4>
      <ul className="itd-ctx-list">
        {facts.map((f) => (
          <li key={f.key} className="itd-ctx-item" data-key={f.key} data-same={String(f.same_tickers)} data-grade={f.grade ?? "unknown"}>
            {f.sentences.map((s) => <p key={s} className="itd-ctx-line" data-server>{s}</p>)}
          </li>
        ))}
      </ul>
    </section>
  );
}
