// ═══════════════════════════════════════════════════════════════════════════════
// 팩터 샘플링 주기 ↔ 리밸런싱 주기 충돌 판정 (스펙 §8.1 요구 13)
//
// ★등급표를 여기에 하드코딩하지 않는다★
// 백엔드 `timing_rules_v2.FREQUENCY_RANKS` 가 유일한 진실이고, 카탈로그 응답
// (`frequency_ranks`)으로 내려온다. 여기에 같은 표를 복제하면 두 진실이 생겨서
// 파이썬 쪽이 바뀔 때 UI 판정만 조용히 옛 규칙으로 남는다.
//
// 등급을 모르는 주기는 **경고를 지어내지 않는다** — 백엔드 `frequency_conflicts` 와 같은
// 판단이다. 다만 "모른다" 와 "충돌 없음" 은 다른 사실이라 호출자가 구분할 수 있게 돌려준다.
// ═══════════════════════════════════════════════════════════════════════════════

export type FrequencyVerdict =
  | { kind: "aligned" }
  /** 팩터가 리밸런싱보다 잦다 — 신호 대부분이 버려진다. */
  | { kind: "factor_faster"; factorFreq: string; rebalance: string }
  /** 리밸런싱이 팩터보다 잦다 — 같은 값을 반복 적용한다. */
  | { kind: "rebalance_faster"; factorFreq: string; rebalance: string }
  /** 등급을 모르는 주기 — 판정하지 않는다(없는 경고를 만들지 않기 위해). */
  | { kind: "unknown"; factorFreq: string; rebalance: string };

const FREQ_LABEL: Record<string, string> = {
  day: "일간", overnight: "오버나이트", week: "주간",
  month: "월간", month_end: "월말", quarter: "분기",
};

/** 사람이 읽는 주기 이름. 모르는 값은 원문 그대로 — 라벨을 지어내지 않는다. */
export function frequencyLabel(freq: string): string {
  return FREQ_LABEL[freq?.toLowerCase()] ?? freq ?? "—";
}

export function frequencyVerdict(
  factorFreq: string | undefined,
  rebalance: string | undefined,
  ranks: Record<string, number> | undefined,
): FrequencyVerdict {
  const f = (factorFreq ?? "").toLowerCase();
  const r = (rebalance ?? "").toLowerCase();
  const a = ranks?.[f];
  const b = ranks?.[r];
  if (a === undefined || b === undefined) {
    return { kind: "unknown", factorFreq: f, rebalance: r };
  }
  if (a === b) return { kind: "aligned" };
  // 등급이 낮을수록 잦다 (day=1 … quarter=4)
  return a < b
    ? { kind: "factor_faster", factorFreq: f, rebalance: r }
    : { kind: "rebalance_faster", factorFreq: f, rebalance: r };
}

/** 경고 문구 — 왜 문제인지까지 말한다("어긋남" 만으로는 무엇을 고칠지 알 수 없다). */
export function frequencyWarningText(v: FrequencyVerdict): string | null {
  if (v.kind === "aligned") return null;
  const f = frequencyLabel(v.factorFreq);
  const r = frequencyLabel(v.rebalance);
  if (v.kind === "unknown") {
    return `주기 정렬을 판정할 수 없습니다 (팩터 ${f} · 리밸런싱 ${r}). ` +
      "등급을 모르는 주기라 경고를 지어내지 않습니다.";
  }
  if (v.kind === "factor_faster") {
    return `팩터는 ${f}으로 갱신되는데 리밸런싱은 ${r}입니다 — ` +
      "그 사이의 신호 변화는 반영되지 않고 버려집니다.";
  }
  return `리밸런싱은 ${r}인데 팩터는 ${f}으로만 갱신됩니다 — ` +
    "같은 값이 반복 적용되어 거래만 늘고 신호는 새로 들어오지 않습니다.";
}
