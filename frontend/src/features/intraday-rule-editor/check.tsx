"use client";
/**
 * 직접 구성한 조건의 검사 — 상태(`useRuleCheck`)와 그 보기(`RuleCheckView`)
 * ==========================================================================
 * 빈 칸이 없는 조건만 서버에 묻는다(`POST /intraday/rules/expand`). ★계산도 시행 기록도 없다★ — 같은 조건은 다시 묻지 않는다.
 * 규칙의 글 · 마디 수 · 거절 사유는 서버 문장 그대로다(`data-server`). 거절(400 · 422)과 실패(그 밖)를 가른다 —
 * 거절은 조건이 틀렸다는 답이고, 실패는 답을 못 받은 것이다(다시 물을 수 있다).
 * 화면(백테스트 › 분봉 규칙)과 캔버스의 분봉 설정 노드가 함께 쓴다.
 */
import { useQuery } from "@tanstack/react-query";
import { expandRule, type Expanded, type SimulateRequest } from "@/entities/intraday";
import { num } from "@/shared/lib/krFormat";
import { Notice, RetryFail } from "@/shared/ui/tx";

type Rule = SimulateRequest["rule"];

/** 조건 검사의 상태 — 빈 칸이 있으면 묻지 않는다(`idle`). */
export type RuleCheck =
  | { kind: "idle" } | { kind: "pending" } | { kind: "ok"; value: Expanded }
  | { kind: "refused"; error: string } | { kind: "fail"; error: string; retry: () => void };

/** 서버가 답한 실패 — 상태 번호와 사유를 함께 든다(거절과 실패를 가르는 데 쓴다). */
class Answered extends Error {
  constructor(readonly status: number, message: string) { super(message); }
}

/** `rule` 이 `null` 이면 묻지 않는다(빈 칸이 있다). 열쇠는 조건의 JSON 이다 — 같은 조건은 한 번만 묻는다. */
export function useRuleCheck(rule: Rule | null): RuleCheck {
  const asked = useQuery({
    queryKey: ["intraday", "expand", rule ? JSON.stringify(rule) : ""],
    queryFn: async (): Promise<Expanded> => {
      const r = await expandRule(rule as Rule);
      if (!r.ok) throw new Answered(r.status, r.error);
      return r.value;
    },
    enabled: rule !== null, staleTime: Infinity, retry: false,
  });
  if (rule === null) return { kind: "idle" };
  if (asked.isError) {
    const status = asked.error instanceof Answered ? asked.error.status : 0;
    const error = asked.error instanceof Answered ? asked.error.message : "서버 연결 실패";
    return status === 400 || status === 422 ? { kind: "refused", error } : { kind: "fail", error, retry: () => void asked.refetch() };
  }
  return asked.data ? { kind: "ok", value: asked.data } : { kind: "pending" };
}

export function RuleCheckView({ check }: { check: RuleCheck }) {
  if (check.kind === "idle") return <p className="tj-note itd-check" data-state="idle">조건을 모두 채우면 검사 결과를 표시합니다.</p>;
  if (check.kind === "pending") return <p className="tj-note itd-check" data-state="pending" aria-busy="true">조건 검사 중</p>;
  if (check.kind === "refused") {
    return <div className="itd-check" data-state="refused"><Notice tone="danger" title="조건 검사 거절"><span data-server>{check.error}</span></Notice></div>;
  }
  if (check.kind === "fail") {
    return <div className="itd-check" data-state="fail"><RetryFail title="조건 검사 실패" onRetry={check.retry}><span data-server>{check.error}</span></RetryFail></div>;
  }
  const v = check.value;
  return (
    <div className="itd-check" data-state="ok" aria-live="polite">
      <p className="tj-read itd-rule-text" data-server>{v.text}</p>
      <p className="itd-hint itd-rule-size">마디 {num(v.nodes)}/{num(v.limits.nodes)} · 겹침 깊이 {num(v.depth)}/{num(v.limits.depth)}</p>
    </div>
  );
}
