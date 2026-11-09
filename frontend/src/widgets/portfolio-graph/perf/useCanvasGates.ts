/**
 * 캔버스의 관문 판정(서버 `gates`)을 성과 시트의 질문 띠에 넘긴다 (2026-11-09 · 캔버스 성과 그림 문법 §4.1 시트 ①)
 * 결과가 낡았거나(BT5) 부분 계산이라 판정이 없으면 null — 띠가 "관문 판정이 없어요" 라고 말한다. 예전 판정을 지금 결과에 붙이지 않는다.
 * 이 훅만 캔버스 스토어를 안다 — 시트·부품은 `gates` 를 값으로 받는다(다른 도구는 제 관문을 넘기면 된다).
 */
import type { Gate } from "@/entities/portfolio-graph";
import { usePortfolioGraph } from "../store";

export const useCanvasGates = (): Gate[] | null =>
  usePortfolioGraph((s) => (s.reportStale ? null : (s.report?.gates?.gates ?? null)));
