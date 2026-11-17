"use client";
/**
 * 내 하루 유형 모형 목록 — 직접 구성 편집기의 모형 칸(T2)과 국면 나눔의 '하루 유형 비율' 칸(K2b · 화면과 캔버스 판)이 같이 쓴다 (K2c)
 * ==========================================================================
 * 목록은 ★내 모형만★이다(서버가 거른다 · 운영 게이트에서는 합성 모형이 빠지고 그 수와 사유가 온다).
 * 칸에 들어갈 때마다 `reload` 로 다시 읽는다 — 같은 화면의 '하루 유형' 절에서 막 학습한 모형이 바로 보이게.
 * ★읽지 못하면 빈 목록이 아니라 그 사유다★(`models: null` + `note`) — 못 읽은 것을 '모형 없음'으로 접지 않는다.
 * 전에는 두 feature 가 이 훅을 줄 단위로 같게 따로 가졌다(K2b) — feature 끼리는 서로 들일 수 없어 entities 로 내렸다.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { listDayTypes } from "./api";
import type { DayTypeSummary } from "./types";

/** 모형이 하나도 없을 때의 안내 — 모형은 백테스트 › 분봉 규칙의 '하루 유형' 절에서 학습한다(캔버스에서도 같은 문장). */
export const NO_MODELS = "학습한 하루 유형 모형이 없습니다. 백테스트 › 분봉 규칙의 ‘하루 유형’에서 먼저 학습합니다.";

/** 고르기 목록의 한 줄 — 열쇠 앞 여덟 자리 · 학습 기간 · 유형 수 · 분 수(합성이면 그렇다고). 글자는 서버 값 그대로다. */
export const modelLabel = (m: DayTypeSummary): string =>
  `${m.key.slice(0, 8)} · ${m.first_day}~${m.last_day} · 유형 ${m.k}개 · ${m.minutes}분${m.synthetic ? " · 합성" : ""}`;

/** `models` 가 `null` 이면 목록을 읽지 못한 것이고 `note` 가 그 사유다. 배열이면 읽은 것(빈 배열 = 정말 없음 · `note` 는 숨긴 합성 모형의 사유). */
export type DayTypeModelList = { models: DayTypeSummary[] | null; note: string | null };

export function useDayTypeModels(): DayTypeModelList & { reload: () => void } {
  const [state, setState] = useState<DayTypeModelList>({ models: null, note: null });
  const alive = useRef(true);
  const reload = useCallback(() => {
    void listDayTypes().then((r) => {
      if (!alive.current) return;
      if (!r.ok) return setState({ models: null, note: r.error });
      if (!r.value.available) return setState({ models: null, note: r.value.reason });
      setState({ models: r.value.models, note: r.value.hidden_synthetic ? r.value.hidden_reason : null });
    });
  }, []);
  useEffect(() => {
    alive.current = true;
    reload();
    return () => { alive.current = false; };
  }, [reload]);
  return { ...state, reload };
}
