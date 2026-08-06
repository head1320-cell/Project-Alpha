// ═══════════════════════════════════════════════════════════════════════════════
// 분석 요청 서명 — 결과가 지금 입력으로 나온 것인지 판정하는 단일 소스 (A1c·A1d·A1e)
// ─────────────────────────────────────────────────────────────────────────────
// ★왜 별도 모듈인가★
// 예전에는 AllocationProvider 안에 **두 개의 객체 리터럴**이 있었다 — stale 판정용
// `currentSig` 와 실제로 보내는 `req`. 주석은 "동일 키 순서/값이어야 한다"고 적어 두었지만,
// 그건 규약일 뿐 강제가 아니었고 이미 두 곳이 어긋나 있었다:
//   · currentSig 는 `constraints`(null 가능), req 는 `constraints ?? undefined`
//   · currentSig 는 runAnalyze 가 받는 `over` 오버라이드를 반영하지 않음
// 이런 종류의 어긋남은 타입 에러를 내지 않고, stale 판정이 틀려도 빨개지는 테스트가 없다.
// 그래서 서명을 **요청에서 파생**시킨다. 요청을 만드는 함수가 하나뿐이면 어긋날 자리가 없다.
// ═══════════════════════════════════════════════════════════════════════════════

import type {
  AllocationModel,
  AllocationViewInput,
  ConstraintsInput,
} from "@/entities/allocation/api";

/** 서명에 필요한 입력만. 전체 컨텍스트를 받지 않는 이유는 화면 없이 테스트하기 위해서다. */
export interface SignatureInputs {
  tickers: string[];
  weights: Record<string, number>;
  views: AllocationViewInput[];
  model: AllocationModel;
  delta: number;
  tau: number;
  constraints: ConstraintsInput | null;
}

/** runAnalyze 가 호출 시점에 덮어쓰는 값들(엔진 전환·τ 확정·뷰 커밋). */
export interface AnalyzeOverrides {
  model?: AllocationModel;
  tau?: number;
  views?: AllocationViewInput[];
}

/** 서버로 나가는 요청 본문 — mutateAnalyze 가 받는 모양 그대로. */
export interface AnalyzeRequestCore {
  tickers: string[];
  weights: Record<string, number>;
  views: AllocationViewInput[];
  model: AllocationModel;
  delta: number;
  tau: number;
  constraints?: ConstraintsInput;
}

/**
 * 엔진이 "유효한 뷰"로 세는 것과 같은 판정.
 * 엔진 쪽 근거: `build_user_views()` 는 대상 자산이 유니버스에 없거나 크기가 0 이면
 * 그 뷰를 스킵한다(allocation_studio.py:74-78). 이 필터가 엔진과 어긋나면
 * "뷰가 있다고 보고 λ 를 서명에 넣었는데 엔진은 뷰를 버린" 상태가 되어 영원히 stale 이 된다.
 * `tests/test_allocation_delta_sensitivity.py::test_view_with_zero_magnitude_is_not_a_valid_view`
 * 가 이 동치를 고정한다.
 */
export function validViews(views: AllocationViewInput[]): AllocationViewInput[] {
  return views.filter((v) => v.assets.length > 0 && v.magnitude_pct > 0);
}

/** 서버로 보낼 요청을 만든다. 여기가 요청의 유일한 출처다. */
export function buildAnalyzeRequest(
  s: SignatureInputs,
  over?: AnalyzeOverrides,
): AnalyzeRequestCore {
  return {
    tickers: s.tickers,
    weights: s.weights,
    views: validViews(over?.views ?? s.views),
    model: over?.model ?? s.model,
    delta: s.delta,
    tau: over?.tau ?? s.tau,
    constraints: s.constraints ?? undefined,
  };
}

/**
 * ★λ(delta)는 유효한 뷰가 있을 때만 서명에 들어간다★
 *
 * 무조건 넣으면: λ 슬라이더를 한 칸 움직일 때마다 파이프라인 전체가 "재계산 필요"가 된다.
 * 무조건 빼면: BL + 뷰 상태에서 최종 비중이 바뀌었는데도 결과가 최신이라고 말한다.
 * 둘 다 틀렸고, 실제로 이 저장소는 서명은 전자, 화면 문구는 후자로 **동시에** 틀려 있었다.
 *
 * 진실은 조건부이고 엔진에서 나온다 — delta 가 닿는 경로는 `pi = delta * S @ w_mkt` 한 줄뿐이며
 * 그 줄은 `if views:` 안에 있다(allocation_studio.py:225).
 *
 * 술어를 `model === "bl"` 로 더 좁히지 않은 이유도 실측이다: 공분산 전용 모델(min_var 등)에서
 * λ 는 **최종 비중**은 안 바꾸지만 `flow.view_applied` 는 바꾼다. 그 열은 explain 화면의
 * '② View(BL)' 컬럼과 배분 Sankey 로 **그려진다**. 모델로 좁히면 그 숫자가 낡은 채로 최신인 척한다.
 * 근거: tests/test_allocation_delta_sensitivity.py 4건.
 */
export function signatureOf(req: AnalyzeRequestCore): string {
  const { delta, ...rest } = req;
  return JSON.stringify(req.views.length > 0 ? { ...rest, delta } : rest);
}

/** 무엇이 바뀌어서 결과가 낡았는지 — 배너가 "뭔가 바뀜"이 아니라 그것을 적기 위해. */
export type ChangedGroup = "holdings" | "views" | "model" | "delta" | "tau" | "constraints";

const GROUP_LABEL: Record<ChangedGroup, string> = {
  holdings: "자산·비중",
  views: "뷰",
  model: "엔진",
  delta: "위험회피(λ)",
  tau: "불확실성(τ)",
  constraints: "제약",
};

export function changedLabels(groups: ChangedGroup[]): string {
  return groups.map((g) => GROUP_LABEL[g]).join(" · ");
}

/**
 * 이전 서명(문자열)과 현재 요청을 비교해 바뀐 그룹을 낸다.
 * 이전 서명은 signatureOf 가 만든 JSON 이므로 되파싱이 안전하다 — 파싱이 실패하면
 * (구버전 서명·손상) 빈 배열이 아니라 null 을 돌려서 "무엇이 바뀌었는지 모른다"를 구분한다.
 * 모르는 것을 아는 척하지 않는 편이 배너 문구를 정직하게 만든다.
 */
export function diffAgainstSignature(
  prevSig: string,
  cur: AnalyzeRequestCore,
): ChangedGroup[] | null {
  let prev: Partial<AnalyzeRequestCore>;
  try {
    prev = JSON.parse(prevSig) as Partial<AnalyzeRequestCore>;
  } catch {
    return null;
  }
  if (!prev || typeof prev !== "object") return null;

  const out: ChangedGroup[] = [];
  const eq = (a: unknown, b: unknown) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);

  if (!eq(prev.tickers, cur.tickers) || !eq(prev.weights, cur.weights)) out.push("holdings");
  if (!eq(prev.views, cur.views)) out.push("views");
  if (prev.model !== cur.model) out.push("model");
  // delta 는 서명에 없을 수 있다(뷰 0개). 없었다면 바뀌었다고 말할 근거가 없다.
  if (prev.delta !== undefined && prev.delta !== cur.delta) out.push("delta");
  if (prev.tau !== cur.tau) out.push("tau");
  if (!eq(prev.constraints, cur.constraints)) out.push("constraints");
  return out;
}

/**
 * 결과의 신선도. ★`stale` 하나로 뭉쳐 두면 두 개의 다른 상태가 같은 얼굴이 된다★
 *  · missing    — 계산한 적이 없거나 입력 리셋으로 결과를 비웠다. 화면에 숫자가 **없다**.
 *  · superseded — 결과는 그대로 있는데 입력이 그 뒤에 바뀌었다. 화면에 숫자가 **있고, 낡았다**.
 * 이 둘은 사용자가 해야 할 일도, 화면이 해야 할 말도 다르다. 이 저장소의
 * `0 ≠ 미계산 ≠ 산출 불가` 원칙을 한 계층 위로 올린 것이다.
 */
export type ResultFreshness =
  | { kind: "fresh" }
  | { kind: "missing" }
  | { kind: "superseded"; changed: ChangedGroup[] | null };

export function freshnessOf(
  hasResult: boolean,
  prevSig: string,
  cur: AnalyzeRequestCore,
): ResultFreshness {
  if (!hasResult) return { kind: "missing" };
  if (signatureOf(cur) === prevSig) return { kind: "fresh" };
  return { kind: "superseded", changed: diffAgainstSignature(prevSig, cur) };
}
