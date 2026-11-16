"use client";
/**
 * 캔버스 설정 판의 '직접 구성' 칸 — 분봉 설정 노드의 조건 나무 셋 (자유 조건식 f3)
 * ==========================================================================
 * 서버 x-ui `widget: "intraday_rule"`. 화면(백테스트 › 분봉 규칙)과 ★같은 편집 부품 · 같은 검사★를 쓴다 — 지표와 연산의 이름 · 범위는
 * 서버의 문법 표에서 오고, 규칙의 글과 거절 사유는 서버 문장 그대로다. ★도구는 조건을 추천하지 않는다★ — 조건은 비어서 시작한다.
 * 노드의 매개변수에는 지은 나무가 그대로 실린다(쓰지 않는 자리는 싣지 않는다). 빈 칸이 있는 채로 계산하면 노드가 서버의 사유로 실패한다 —
 * 그 전에 이 칸이 어느 자리에 빈 칸이 몇 곳인지 말한다.
 */
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { getTemplates } from "@/entities/intraday";
import { RuleCheckView, RuleEditor, fromParams, issuesOf, toParams, useRuleCheck } from "@/features/intraday-rule-editor";
import { RetryFail } from "@/shared/ui/tx";

const record = (v: unknown): Record<string, unknown> => (v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {});

export function IntradayRuleField({ value, onChange }: { value: unknown; onChange: (v: unknown) => void }) {
  const templates = useQuery({
    queryKey: ["intraday", "templates"],
    queryFn: async () => { const r = await getTemplates(); if (!r.ok) throw new Error(r.error); return r.value; },
    staleTime: 0, retry: false,
  });
  const drafts = useMemo(() => fromParams(record(value)), [value]);
  const grammar = templates.data?.grammar ?? null;
  const issues = grammar ? issuesOf(drafts, grammar) : [];
  const check = useRuleCheck(grammar && issues.length === 0 ? { kind: "custom", params: toParams(drafts) } : null);
  if (templates.isPending) return <p className="pg-note pg-itd-rule-wait" aria-busy="true">조건 편집기 불러오는 중</p>;
  if (templates.isError || !grammar) {
    return <RetryFail title="조건 편집기 불러오기 실패" onRetry={() => void templates.refetch()}><span data-server>{templates.error?.message ?? ""}</span></RetryFail>;
  }
  return (
    <div className="pg-itd-rule">
      <RuleEditor grammar={grammar} value={drafts} onChange={(next) => onChange(toParams(next))} />
      {issues.length ? (
        <ul className="pg-itd-rule-issues" role="status">{issues.map((text) => <li key={text}>{text}</li>)}</ul>
      ) : null}
      <RuleCheckView check={check} />
    </div>
  );
}
