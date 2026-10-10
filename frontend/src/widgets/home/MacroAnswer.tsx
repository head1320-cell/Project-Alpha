"use client";
/**
 * 지금 서버가 내는 경제 흐름 답 한 문장 + 숫자 셋 + 근거 칩 (BU1 홈에서 꺼냄 · BU8a 첫 화면도 같은 부품)
 * ==========================================================================
 * ★답 문장은 서버 값으로만 만든다(ADR-003 §2.6)★ 문장은 서버 `recommended_mode` 를 한국어로 옮긴 것이고,
 * 모르는 값이면 판단 없이 잰 값(스트레스)만 말한다. 화면이 임계값으로 새 판단을 만들지 않는다.
 * ★연습용 표시는 서버 게이트로만★ `GET /macro/connection-status` 의 `mock_allowed`(= mock_gate)·`bok_configured`.
 * ★실패를 빈 칸으로 두지 않는다★ 실패는 alert + 다시 시도. 함정: 같은 queryKey(`["macro","regime"]`)를 다른 화면도 쓴다 —
 * 실패를 `null` 로 캐시하는 소비자가 다시 생겨도 여기서 `null` 은 실패로 그린다.
 *
 * 두 화면이 같은 부품을 쓰므로 문장·칩 규칙은 한곳에만 있다. 화면마다 다른 것은 감싸는 클래스와 행동 단추뿐이다
 * (홈은 주 단추, 첫 화면은 주 단추가 따로 있어 보조 단추).
 */
import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { macroApi, type RegimeState } from "@/entities/macro/api";
import { MODE_KO, regimeFig, sourceChip, when } from "@/entities/macro/regimeKo";
import { LoadingState } from "@/shared/ui/States";
import { Answer, Notice, Unknown, type Chip, type Figure } from "@/shared/ui/tx";

export function MacroAnswer({ className, action }: { className: string; action?: ReactNode }) {
  const q = useQuery({ queryKey: ["macro", "regime"], queryFn: () => macroApi.regime() });
  const cs = useQuery({ queryKey: ["macro", "connection-status"], queryFn: () => macroApi.connectionStatus() });
  const st: RegimeState | null | undefined = q.data;

  if (q.isLoading) return <div className={className}><LoadingState label="매크로 분석을 불러오는 중이에요" /></div>;
  if (q.isError || !st) {
    return (
      <div className={className}>
        <Notice tone="danger" title="매크로 분석을 불러오지 못했어요">
          서버에 닿지 못했거나 계산이 실패했어요. 잠시 뒤 다시 시도해 주세요.
          <div className="home-act">
            <button type="button" className="tx-btn tx-btn--sub home-retry" onClick={() => { void q.refetch(); }}>다시 시도</button>
          </div>
        </Notice>
      </div>
    );
  }

  const stress = Math.round(st.stress_score);
  const mode = MODE_KO[st.recommended_mode];
  const sentence = mode ? `지금 경제 흐름은 ‘${mode}’ 단계예요` : `지금 시장 스트레스는 ${stress}/100이에요`;
  const us = st.markets?.us;
  const figures: Figure[] = [
    { label: "시장 스트레스", value: `${stress}/100` },
    { label: "한국", value: regimeFig(st) },
    { label: "미국", value: us ? regimeFig(us) : <Unknown reason="미국 국면을 받지 못했어요" /> },
  ];
  const at = when(st.timestamp);
  // `ev` = 어떤 근거인지(출처 · 잰 모형 · 기준 시각) — 첫 화면 '근거 짚기' 가 이 칩들을 짚는다. 글자·색은 그대로다.
  const chips: Chip[] = [
    ...sourceChip({ data: cs.data, isError: cs.isError, isLoading: cs.isLoading }).map((c) => ({ ...c, ev: "source" })),
    { label: "국면 확률은 축 모형 하나로 쟀어요", tone: "info", ev: "model" },
    ...(at ? [{ label: at, tone: "plain" as const, ev: "asof" }] : []),
  ];
  return (
    <div className={className}>
      <Answer sentence={sentence} figures={figures} chips={chips} action={action} />
    </div>
  );
}
