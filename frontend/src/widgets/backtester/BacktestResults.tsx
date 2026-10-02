"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// BacktestResults — 백테스트 결과 (스펙 §5, 고정 URL·새로고침 가능) · BU4 토스화
//   답 한 문장(서버 값) + 이 수치가 무엇인지(PerfLabel) + 근거 → 자산곡선 → 낙폭 → 핵심 지표 6 → 지표 모두 보기 →
//   월별 → 기여도 → 종목별 → 거래 기록 → 데이터와 한계.
//   엔진이 반환한 지표를 그린다. 없는 지표는 생략하되, **사유를 데이터로 증명할 수 있는 결측**(벤치마크 미지정 ·
//   체결 0건)은 '산출 불가' 로 보인다 — absentReason(). ★산출 불가는 접지 않는다★ 핵심 지표 바로 아래에 둔다.
// ═══════════════════════════════════════════════════════════════════════════════
import React, { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown } from "lucide-react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Line, LineChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { backtestRunApi, STAGE_LABELS, type RunFull } from "@/entities/backtest-run/api";
import type { BacktestStatistics, BacktestTrade, MonthlyReturn, ScreenToBacktestResult, SymbolPerf } from "@/entities/backtest/bridgeModel";
import { Card, CardContent, CardHeader, CardTitle } from "@/shared/ui/shadcn/card";
import { useChartAnimation } from "@/shared/ui/chartStyle";
import { PerfLabel } from "@/shared/ui/PerfLabel";
import { Notice, PageHead } from "@/shared/ui/tx";

// ★Card 로 감싸면서 지킨 것★ `.brun-card` / `.brun-card-t`(H2) 는 같은 노드에 그대로 둔다(E2E 계약 — backtest.spec 이
//  `.brun-card-t` 의 텍스트로 절을 찾는다). 여백의 주인은 하나: `.brun-card` 는 0, 머리·몸통(`rs-card-h`·`rs-card-b`)이 가진다.

type Stat = keyof BacktestStatistics;
interface MetricDef { k: Stat; label: string; tip: string; suffix?: string; digits?: number; signed?: boolean }
// 엔진이 실제 산출하는 지표만 묶음으로 배치. 결측 처리 규칙은 absentReason() 참고.
const METRIC_GROUPS: { title: string; metrics: MetricDef[] }[] = [
  { title: "수익", metrics: [
    { k: "total_return_pct", label: "총수익률", tip: "기간 전체에서 불어난 비율", suffix: "%", signed: true },
    { k: "cagr", label: "연평균 수익률", tip: "해마다 복리로 몇 % 불었는지(CAGR)", suffix: "%", signed: true },
    { k: "best_period_pct", label: "가장 좋았던 구간", tip: "한 구간에서 가장 크게 오른 비율", suffix: "%", signed: true },
    { k: "worst_period_pct", label: "가장 나빴던 구간", tip: "한 구간에서 가장 크게 내린 비율", suffix: "%", signed: true },
  ] },
  { title: "위험", metrics: [
    { k: "max_drawdown_pct", label: "최대 낙폭", tip: "고점에서 가장 깊이 내려간 비율(MDD)", suffix: "%" },
    { k: "avg_drawdown_pct", label: "평균 낙폭", tip: "내려간 구간들의 평균 깊이", suffix: "%" },
    { k: "max_drawdown_days", label: "가장 긴 회복 기간", tip: "고점을 되찾기까지 가장 오래 걸린 날 수", suffix: "일", digits: 0 },
    { k: "volatility_pct", label: "변동성(연)", tip: "수익률이 한 해에 얼마나 출렁이는지(연율 표준편차)", suffix: "%" },
    { k: "downside_deviation_pct", label: "하방 변동성", tip: "손실 쪽 출렁임만 잰 값(Sortino 분모)", suffix: "%" },
    { k: "ulcer_index", label: "얼서 지수", tip: "낙폭의 깊이와 길이를 함께 잰 값 — 낮을수록 덜 아팠어요", digits: 2 },
    { k: "var_pct", label: "95% VaR", tip: "95% 신뢰수준에서 이보다 크게 잃지 않는다는 추정", suffix: "%" },
    { k: "cvar_pct", label: "95% CVaR", tip: "VaR 를 넘는 날들의 평균 손실(꼬리)", suffix: "%" },
  ] },
  { title: "위험 대비 수익", metrics: [
    { k: "sharpe_ratio", label: "샤프 지수", tip: "출렁임 1 만큼에 얻은 초과수익", digits: 2 },
    { k: "sortino_ratio", label: "소르티노 지수", tip: "손실 쪽 출렁임 1 만큼에 얻은 초과수익", digits: 2 },
    { k: "calmar_ratio", label: "칼마 비율", tip: "연평균 수익률 ÷ 최대 낙폭", digits: 2 },
    { k: "omega", label: "오메가", tip: "이익 쪽 확률 가중 합 ÷ 손실 쪽(1 보다 크면 이익 쪽이 커요)", digits: 2 },
    { k: "gain_to_pain", label: "이익 대 손실", tip: "벌어들인 것의 합 ÷ 잃은 것의 합", digits: 2 },
    { k: "tail_ratio", label: "꼬리 비율", tip: "상위 5% 수익 ÷ 하위 5% 손실 크기", digits: 2 },
    { k: "recovery_factor", label: "회복 계수", tip: "총수익 ÷ 최대 낙폭", digits: 2 },
    { k: "information_ratio", label: "정보 비율", tip: "벤치마크를 넘은 수익 ÷ 그 차이의 출렁임(IR)", digits: 2 },
  ] },
  { title: "분포", metrics: [
    { k: "skew", label: "왜도", tip: "수익률 분포가 어느 쪽으로 기울었는지(양수 = 큰 이익 쪽 꼬리)", digits: 2 },
    { k: "kurtosis", label: "첨도", tip: "꼬리가 얼마나 두꺼운지 — 높을수록 극단값이 잦아요", digits: 2 },
  ] },
  { title: "거래", metrics: [
    { k: "num_trades", label: "거래 수", tip: "사고 판 한 쌍을 한 번으로 센 수", digits: 0 },
    { k: "win_rate", label: "이긴 거래 비율", tip: "이익으로 끝난 거래의 비율", suffix: "%" },
    { k: "profit_factor", label: "손익비", tip: "총이익 ÷ 총손실", digits: 2 },
    { k: "payoff_ratio", label: "평균 손익 배율", tip: "평균 이익 ÷ 평균 손실", digits: 2 },
    { k: "avg_trade_return", label: "거래당 평균 수익", tip: "한 번 거래의 평균 수익률", suffix: "%", signed: true },
    { k: "expectancy", label: "거래당 기댓값", tip: "한 번 거래에서 기대되는 손익(원)", digits: 0, signed: true },
    { k: "avg_win", label: "평균 이익", tip: "이익 거래의 평균 손익(원)", digits: 0 },
    { k: "avg_loss", label: "평균 손실", tip: "손실 거래의 평균 손익(원)", digits: 0 },
    { k: "kelly_pct", label: "켈리 비율", tip: "켈리 공식이 말하는 한 번 거래의 비중", suffix: "%" },
  ] },
  { title: "비용", metrics: [
    { k: "total_commission", label: "수수료 합계", tip: "낸 수수료를 모두 더한 값(원)", digits: 0 },
    { k: "total_slippage", label: "슬리피지 합계", tip: "체결가 차이로 잃은 값을 모두 더한 값(원)", digits: 0 },
  ] },
];
/** 펼쳐 두는 핵심 지표 6 — 수익·위험·위험 대비·거래 각 축에서 하나 이상. 나머지는 "지표 모두 보기" 안. */
const KEY_METRICS: Stat[] = ["total_return_pct", "cagr", "max_drawdown_pct", "volatility_pct", "sharpe_ratio", "num_trades"];
const METRIC_BY_KEY = new Map(METRIC_GROUPS.flatMap((g) => g.metrics).map((m) => [m.k, m] as const));

/** 거래가 한 건도 없으면 통째로 성립하지 않는 지표들 — 사유를 데이터로 증명할 수 있다. */
const TRADE_QUALITY_KEYS = new Set([
  "win_rate", "profit_factor", "payoff_ratio", "avg_trade_return",
  "expectancy", "avg_win", "avg_loss", "kelly_pct",
]);

/**
 * ★없는 지표를 어떻게 다룰 것인가★
 *
 * 지금까지는 값이 없으면 조용히 뺐다(아래 `avail` 필터). 그러면 화면에서는 그 지표가
 * **원래 없는 것**처럼 보인다. 계산에 실패한 것과 애초에 정의되지 않는 것이 같은 모습이 된다.
 *
 * 그렇다고 없는 값 전부에 "없음"을 붙이면 이번엔 반대쪽으로 틀린다 — 이유를 모르면서
 * 아는 척하게 된다. 사유를 못 대는 "없음"은 그 자체로 지어낸 정보다.
 *
 * 그래서 **사유를 데이터로 증명할 수 있는 것만** 노출한다. 아래 두 규칙은 둘 다 화면이
 * 이미 들고 있는 값으로 판정된다(벤치마크 곡선의 유무, 체결 건수). 나머지는 지금처럼 생략한다.
 */
function absentReason(
  k: string,
  hasBenchmark: boolean,
  tradeCount: number | null,
): string | null {
  if (k === "information_ratio" && !hasBenchmark) {
    return "벤치마크를 지정하지 않아 추적오차를 계산할 수 없어요.";
  }
  if (tradeCount === 0 && TRADE_QUALITY_KEYS.has(k)) {
    return "이 기간에 체결이 한 건도 없어 거래 통계가 나오지 않아요.";
  }
  return null;
}

const num = (v: number | null | undefined) => (v == null || !Number.isFinite(v) ? null : v);

/**
 * 매크로 룩어헤드를 진단 문장으로. ★안 쓴 실행은 아무 말도 하지 않는다★
 *
 * 매크로 토큰을 쓰지 않은 백테스트에 "매크로 룩어헤드 없음" 이라고 적으면,
 * 확인해서 없는 것과 애초에 해당 없는 것이 같아 보인다.
 *
 * 반대로 **썼는데 라이브로 평가된** 토큰은 반드시 말한다 — 그것이 룩어헤드이고,
 * 그 사실이 화면에 없으면 사용자는 결과를 시점 정합된 것으로 읽는다.
 */
function macroHonesty(ml: ScreenToBacktestResult["macro_lookahead"]): string[] {
  if (!ml || (ml.pit + ml.live + ml.blocked) === 0) return [];
  const out: string[] = [];
  const names = (p: string) =>
    Object.entries(ml.tokens).filter(([, v]) => v.path === p).map(([k]) => k);

  const live = names("live");
  if (live.length > 0) {
    out.push(
      `매크로 룩어헤드 — ${live.join(" · ")} 은(는) 빈티지가 없어 현재 개정본으로 ` +
      `평가됐어요. 이 토큰이 쓰인 조건은 그 시점에 알 수 없던 값을 봐요.`,
    );
  }
  const blocked = names("blocked");
  if (blocked.length > 0) {
    out.push(
      `매크로 미평가 — ${blocked.join(" · ")} 은(는) 값을 얻지 못해 해당 조건이 ` +
      `평가되지 않았어요(${ml.tokens[blocked[0]].reason}).`,
    );
  }
  // 개정이 판정을 실제로 뒤집었는가 — ★레그 기준이라는 말을 함께 싣는다★
  for (const [tok, v] of Object.entries(ml.tokens)) {
    const r = v.revision;
    if (!r) continue;
    if (r.flip_pct == null) {
      out.push(`${tok} — 개정 영향은 측정하지 못했어요(${r.reason}).`);
    } else if (r.flip > 0) {
      out.push(
        `${tok} — 데이터 개정이 이 토큰 조건의 판정을 ${r.bars}봉 중 ${r.flip}봉` +
        `(${r.flip_pct}%)에서 뒤집었어요. 매크로 레그 기준이며 최종 신호가 ` +
        `갈린 비율은 아니에요.`,
      );
    }
  }
  if (live.length === 0 && blocked.length === 0 && ml.pit > 0) {
    out.push(`매크로 ${ml.pit}개 토큰은 모두 그 시점의 빈티지로 평가됐어요.`);
  }
  return out;
}
/**
 * 재무 공시일의 출처를 진단 문장으로. ★안 쓴 실행은 아무 말도 하지 않는다★
 *
 * `macroHonesty` 와 같은 규율이다. 다만 세는 단위가 **(종목, 기간)** 이라
 * 종목 이름을 나열하지 않는다 — 수백 개가 될 수 있다. 대신 사유별 건수와
 * 예시 종목 몇 개를 말한다.
 *
 * ★"실측 100%" 라도 값 축은 남는다는 말을 함께 싣는다★ 비율 하나만 보이면
 * "PIT 완료" 로 읽힌다.
 */
function fundamentalsHonesty(fp: ScreenToBacktestResult["fundamentals_pit"]): string[] {
  if (!fp) return [];
  const total = fp.measured + fp.estimated + fp.unknown;
  if (total === 0 && !fp.tickers?.no_financials) return [];
  const out: string[] = [];

  if (fp.unknown > 0) {
    const r = fp.reasons?.vintage_table_unreadable;
    out.push(
      `재무 공시일 미상 — ${fp.unknown}개 (종목, 기간)에서 빈티지 유무를 확인하지 ` +
      `못해 정적 시차로 추정했어요${r?.reason ? ` (${r.reason})` : ""}.`,
    );
  }
  if (fp.estimated > 0) {
    const r = fp.reasons?.ticker_has_no_vintages ?? fp.reasons?.no_vintage_for_period;
    const eg = r?.sample_tickers?.length ? ` 예: ${r.sample_tickers.join(" · ")}` : "";
    out.push(
      `재무 공시일 추정 — ${fp.estimated}개 (종목, 기간)이 실제 접수일 대신 정적 ` +
      `시차(연간 ${fp.lag_days.annual}일 · 분기 ${fp.lag_days.quarterly}일)로 ` +
      `평가됐어요. 늦게 공시된 보고서라면 그만큼 아직 공표되지 않은 재무를 ` +
      `본 것이에요.${eg}`,
    );
  }
  if (fp.measured > 0) {
    out.push(
      `재무 공시일 실측 — ${fp.measured}개 (종목, 기간)은 DART 접수일` +
      `${fp.same_day_guard_days > 0 ? ` + ${fp.same_day_guard_days}일` : ""} 기준으로 ` +
      `평가됐어요${fp.measured_pct == null ? "" : ` (${fp.measured_pct}%)`}.`,
    );
  }
  if (fp.tickers?.no_financials > 0) {
    out.push(
      `재무 미적재 — ${fp.tickers.no_financials}개 종목은 적재된 재무가 없어 PIT ` +
      `재무 조건이 **평가되지 않았어요**(조건이 거짓이었다는 뜻이 아니에요).`,
    );
  }
  // ★날짜만 실측이라는 사실★ — 추정 기간이 하나라도 있으면 값 축이 남는다.
  if (fp.estimated + fp.unknown > 0 && fp.value_note) out.push(fp.value_note);
  return out;
}

/**
 * 이 백테스트가 **무슨 가격을 봤는가**. ★안 잰 실행은 아무 말도 하지 않는다★
 *
 * `macroHonesty` 와 같은 규율이다. 원주가와 수정주가가 섞인 계열로 계산한
 * 수익률은 정의가 섞인 수익률이고, 분할일 하나가 수십 % 수익률로 잡혀
 * 공분산·팩터 추정을 흔든다 — 그 사실이 화면에 없으면 아무도 모른다.
 *
 * ★깨끗할 때도 한 줄 말한다★ — 재서 깨끗한 것과 안 잰 것을 구별하려면
 * 침묵이 아니라 문장이 필요하다.
 */
function priceHonesty(pb: ScreenToBacktestResult["price_basis"]): string[] {
  if (!pb || pb.tickers === 0) return [];
  const out: string[] = [];
  const sample = (xs: string[]) => (xs.length ? ` 예: ${xs.join(" · ")}` : "");

  const mixed = pb.basis?.mixed ?? 0;
  if (mixed > 0) {
    out.push(
      `가격 정의 혼합 — ${mixed}종목의 종가에 원주가와 수정주가가 섞여 ` +
      `있어요. 소스 경계에서 계열이 점프하며, 그 점프는 기업행위가 아니라 ` +
      `누적 수정계수 전체예요.${sample(pb.mixed_tickers)}`,
    );
  }
  const bad = pb.unadjusted_tickers?.length ?? 0;
  if (bad > 0) {
    out.push(
      `수정주가 아님 — ${bad}종목이 원주가이거나 수정 체인이 끊겨 있어요. ` +
      `분할·병합일의 수익률이 실제 손익이 아니에요.${sample(pb.unadjusted_tickers)}`,
    );
  }
  const foggy = (pb.basis?.unlabeled ?? 0) + (pb.basis?.unknown ?? 0);
  if (foggy > 0) {
    out.push(
      `가격 정의 미상 — ${foggy}종목은 정의를 확인하지 못했어요(레거시 행이거나 ` +
      `품질 태그가 없어요). ★확인 결과 문제없음이 아니라 확인하지 못한 ` +
      `것이에요.★${sample(pb.unlabeled_tickers)}`,
    );
  }
  if (pb.state === "ok") {
    out.push(`가격 정의 — ${pb.tickers}종목 전부가 수정주가이고 정의가 균일해요.`);
  }
  // ★제외는 완화이지 해결이 아니다★ 그 사실을 함께 말한다.
  // 0건이면 아무 말도 하지 않는다 — 안 뺀 것과 뺄 것이 없었던 것은 같다.
  if (pb.excluded?.count > 0) {
    out.push(
      `가격 정의 정책 — ${pb.excluded.count}종목을 백테스트에서 **제외**했어요` +
      `${pb.excluded.tickers.length ? ` (예: ${pb.excluded.tickers.join(" · ")})` : ""}. ` +
      `데이터가 고쳐진 것이 아니라 유니버스가 줄었어요 — 위 혼합 개수는 ` +
      `제외 전 기준이고, 그래서 이 실행은 "검증됨" 이 되지 않아요.`,
    );
  } else if (pb.policy === "pass_labeled" && (pb.basis?.mixed ?? 0) > 0) {
    out.push(
      `가격 정의 정책 — 혼합 종목을 **그대로 쓰도록** 선택했어요` +
      `(price_basis_policy=pass_labeled). 위 점프가 수익률에 그대로 들어가요.`,
    );
  }
  return out;
}

/**
 * 유니버스가 **생존편향을 보정했는가**. ★폴백을 조용히 넘기지 않는다★
 *
 * 시점 유니버스를 요청했는데 만들지 못하면 오늘자 프리셋으로 떨어진다 —
 * 그러면 상장폐지 종목이 통째로 빠지고, 살아남은 종목만으로 채점한 성과는
 * 위로 치우친다. 그 사실이 예전에는 화면 어디에도 없었다.
 */
function universeHonesty(uv: ScreenToBacktestResult["universe"]): string[] {
  if (!uv) return [];
  const out: string[] = [];
  if (uv.fell_back) {
    out.push(
      `유니버스 폴백 — ${uv.requested} 를 요청했지만 그 시점 유니버스를 만들지 ` +
      `못해 오늘자 ${uv.effective} 로 돌았어요. 상장폐지 종목이 빠져 ` +
      `생존편향이 그대로 남아 있어요.`,
    );
  } else if (uv.survivorship === "not_corrected") {
    out.push(
      `유니버스 생존편향 — 오늘 기준 멤버십(${uv.effective})이에요. 그 사이 ` +
      `상장폐지된 종목이 유니버스에 없어 성과가 위로 치우쳐요.`,
    );
  } else if (uv.survivorship === "approximated") {
    out.push(
      `유니버스 근사 — 시총 상위 재구성이에요(${uv.asof_date ?? "기준일 미상"}). ` +
      `상장폐지 종목은 포함되지만 실제 지수 편입 이력은 아니에요.`,
    );
  } else if (uv.survivorship === "unknown") {
    out.push(
      `유니버스 미상 — ${uv.reason ?? "보정 여부를 판정할 수 없어요."} ` +
      `★보정됐다는 뜻이 아니에요.★`,
    );
  } else {
    out.push(
      `유니버스 생존편향 보정 — ${uv.asof_date ?? "기준일"} 당시 거래된 ` +
      `${uv.tickers_screened}종목(이후 상장폐지 포함)으로 돌았어요.`,
    );
  }
  return out;
}

/**
 * 시점 정합 판정 — ★네 상태를 둘로 접지 않는다★. `brun-badge` 는 이제 이 판정 하나만 말한다(데이터 출처는 PerfLabel 과
 * "연습용 데이터" 칩이 말한다 — 축을 섞지 않는다). "검증" 이라는 말 대신 "확인" 을 쓴다(금지 표현 규칙과 같은 결).
 */
const PIT_BADGE: Record<string, { label: string; cls: string; tone: "ok" | "assumed" | "unknown" }> = {
  verified: { label: "시점 정합: 확인", cls: "real", tone: "ok" },
  partial: { label: "시점 정합: 일부", cls: "partial", tone: "assumed" },
  unverified: { label: "시점 정합: 확인 안 됨", cls: "warn", tone: "unknown" },
  unknown: { label: "시점 정합: 판정 불가", cls: "warn", tone: "unknown" },
};

const fmtStat = (v: number | null | undefined, m: MetricDef) => {
  const n = num(v);
  if (n == null) return "—";
  const s = m.suffix ?? "";
  const sign = m.signed && n > 0 ? "+" : "";
  return `${sign}${n.toLocaleString("ko-KR", { maximumFractionDigits: m.digits ?? 1 })}${s}`;
};
/** 등락 글자색 — ★한국식★ 오름 빨강(--tx-up-ink) · 내림 파랑(--tx-down-ink) · 0 은 색 없음. 늘 부호와 함께 쓴다. */
const col = (v: number | null | undefined) => {
  const n = num(v);
  return n == null || n === 0 ? undefined : n > 0 ? "var(--tx-up-ink)" : "var(--tx-down-ink)";
};
const signedPct = (v: number, digits = 1) => `${v > 0 ? "+" : ""}${v.toFixed(digits)}%`;
const ymd = (v: unknown) => (typeof v === "string" && /^\d{4}-\d{2}-\d{2}/.test(v) ? v.slice(0, 10).replace(/-/g, ".") : null);

export function BacktestResults({ runId }: { runId: string }) {
  const router = useRouter();
  // 결과 페이지는 항상 DB의 현재 상태를 반영해야 한다 — 전역 기본 staleTime이 24h라
  // 캐시된 스냅샷을 그대로 그리면 이미 끝난 실행이 "loading_data 상태입니다"로 보인다.
  const q = useQuery({
    queryKey: ["btrun", "full", runId], queryFn: () => backtestRunApi.get(runId),
    retry: (count, e) => ((e as { httpStatus?: number })?.httpStatus === 404 ? false : count < 3),
    staleTime: 0,
    refetchOnMount: "always",
  });

  if (q.isLoading) return <div className="tx-page brun-shell rs"><div className="brun-loading">결과를 불러오는 중이에요</div></div>;
  if (q.isError || !q.data) {
    // 404(진짜 없음)만 확정 실패, 그 외(5xx/네트워크)는 일시적 → 다시 시도
    const gone = (q.error as { httpStatus?: number } | null)?.httpStatus === 404;
    return (
      <div className="tx-page brun-shell rs">
        <div className="brun-err rs-state">
          {gone ? (
            <Notice tone="warn" title="이 실행을 찾지 못했어요">
              만료되었거나 잘못된 링크일 수 있어요. 편집기에서 다시 실행해 주세요.
            </Notice>
          ) : (
            <Notice tone="danger" title="결과를 불러오지 못했어요">
              서버에 닿지 않았어요. 실행 결과는 그대로 남아 있으니 다시 시도해 주세요.
            </Notice>
          )}
          <div className="brun-err-actions rs-acts">
            {!gone && <button type="button" className="tx-btn tx-btn--main" onClick={() => q.refetch()}>다시 시도</button>}
            <Link href="/backtest" className="tx-btn tx-btn--sub">편집기로 돌아가기</Link>
          </div>
        </div>
      </div>
    );
  }

  const run = q.data;
  if (run.status !== "completed" || !run.result) {
    return (
      <div className="tx-page brun-shell rs">
        <div className="brun-err rs-state">
          <Notice tone="warn" title="이 실행은 아직 결과가 없어요">
            지금 단계: {STAGE_LABELS[run.status] ?? run.status}. 끝나면 이 주소에서 결과를 볼 수 있어요.
          </Notice>
          <div className="brun-err-actions rs-acts">
            <button type="button" className="tx-btn tx-btn--main" onClick={() => router.push(`/backtest/runs/${runId}/loading`)}>진행 상황 보기</button>
          </div>
        </div>
      </div>
    );
  }
  return <ResultsBody runId={runId} run={run} router={router} />;
}

function ResultsBody({ runId, run, router }: { runId: string; run: RunFull; router: ReturnType<typeof useRouter> }) {
  const anim = useChartAnimation();
  const res = run.result!;
  const bt = res.backtest;
  const stats = bt.statistics as BacktestStatistics;
  const cfg = (run.input_snapshot ?? {}) as Record<string, unknown>;
  const isMock = run.is_mock_data === true || !res.data_source?.fully_real;
  const macroLines = macroHonesty(res.macro_lookahead);
  const fundLines = fundamentalsHonesty(res.fundamentals_pit);
  const priceLines = priceHonesty(res.price_basis);
  const universeLines = universeHonesty(res.universe);
  // ★배지는 저장 컬럼이 아니라 판정을 읽는다★ `run.is_pit_verified` 는 오래도록
  // 아무도 쓰지 않아 늘 거짓이었고, 참/거짓 둘로는 "확인 못 함" 을 말할 수 없다.
  const pitBadge = PIT_BADGE[res.pit_evidence?.status ?? ""] ?? PIT_BADGE.unknown;
  const pitWhy = res.pit_evidence?.summary || "시점 정합을 판정할 자료가 없어요 — 확인됐다는 뜻이 아니에요.";
  // 결측 사유 판정에 쓰는 두 사실 — 둘 다 이미 화면이 들고 있는 값이다.
  const hasBenchmark = Boolean(bt.benchmark?.curve?.length);
  const tradeCount = num(stats.num_trades as number);
  const [retryErr, setRetryErr] = useState<string | null>(null);

  const equity = useMemo(() => (bt.equity_curve || []).map((v, i) => ({
    i, date: bt.equity_dates?.[i] ?? String(i), equity: v,
    bench: bt.benchmark?.curve?.[i] ?? null, dd: bt.drawdown_curve?.[i] ?? null,
  })), [bt]);
  const monthly = useMemo(() => (bt.monthly_returns || []).map((m, i) =>
    typeof m === "number" ? { month: String(i + 1), return_pct: m } : (m as MonthlyReturn)), [bt.monthly_returns]);
  const roundTrips = bt.round_trips && bt.round_trips.length ? bt.round_trips : bt.trades || [];

  // 같은 설정으로 다시 — 실패를 삼키지 않는다(예전 `catch { /* ignore */ }` 는 눌러도 아무 일이 없는 단추였다).
  const retry = async () => {
    setRetryErr(null);
    try { const r = await backtestRunApi.retry(runId); router.push(`/backtest/runs/${r.run_id}/loading`); }
    catch (e) { setRetryErr((e as Error).message || "알 수 없는 오류"); }
  };

  // ── 답 한 문장(서버 값만) ──
  const total = num(stats.total_return_pct as number);
  const from = ymd(cfg.start_date); const to = ymd(cfg.end_date);
  const period = from && to ? `${from}~${to}` : null;
  const sentence = total == null
    ? "이 전략의 총수익률을 받지 못했어요"
    : `이 전략은 ${period ? `${period} 동안 ` : ""}${signedPct(total)}였어요`;
  const benchRet = num(bt.benchmark?.total_return_pct);
  const benchLabel = bt.benchmark?.label;

  // ── 지표: 핵심 6 · 나머지 · 산출 불가 ──
  const has = (m: MetricDef) => num(stats[m.k] as number) != null;
  const keyDefs = KEY_METRICS.map((k) => METRIC_BY_KEY.get(k)!).filter(has);
  const restGroups = METRIC_GROUPS.map((g) => ({ ...g, metrics: g.metrics.filter((m) => has(m) && !KEY_METRICS.includes(m.k)) }))
    .filter((g) => g.metrics.length > 0);
  const restCount = restGroups.reduce((n, g) => n + g.metrics.length, 0);
  const explained = METRIC_GROUPS.flatMap((g) => g.metrics)
    .filter((m) => !has(m))
    .map((m) => ({ m, reason: absentReason(m.k, hasBenchmark, tradeCount) }))
    .filter((x): x is { m: MetricDef; reason: string } => x.reason != null);

  return (
    <div className="tpage-fade tx-page brun-shell brun-results rs">
      <PageHead title={run.strategy_name}
        lede={<>
          {[String(cfg.universe ?? ""), period, run.engine_version ? `엔진 ${run.engine_version}` : null].filter(Boolean).join(" · ")}
          <span className="rs-id" aria-label="실행 번호">{runId}</span>
        </>} />

      <section className="tx-answer rs-answer" aria-label="한 줄 답">
        <div className="rs-answer-top">
          <p className="tx-answer-s">{sentence}</p>
          {/* ★이 수치가 무엇인지 — 문장 바로 옆★ 응답이 말한 종류만(없으면 "미상"). */}
          <PerfLabel value={run.perf_label} />
        </div>
        {benchLabel && benchRet != null && (
          <p className="rs-answer-sub">
            같은 기간 {benchLabel} {signedPct(benchRet)}
            {num(bt.benchmark?.excess_return_pct) != null && <> · 차이 {signedPct(bt.benchmark!.excess_return_pct as number).replace("%", "%p")}</>}
          </p>
        )}
        <ul className="tx-chips" aria-label="이 답의 근거">
          {isMock && <li className="tx-chip" data-tone="practice">연습용 데이터</li>}
          <li className={`tx-chip brun-badge ${pitBadge.cls}`} data-tone={pitBadge.tone}>{pitBadge.label}</li>
        </ul>
        {/* 시점 정합의 사유는 툴팁이 아니라 보이는 줄로(ADR-001 툴팁 금지). */}
        <p className="rs-why">{pitWhy}</p>
        <div className="tx-answer-act rs-acts">
          <Link href="/backtest" className="tx-btn tx-btn--main">편집기에서 고치기</Link>
          <button type="button" className="tx-btn tx-btn--sub" onClick={retry}>같은 설정으로 다시 실행</button>
          <Link href={`/backtest/runs/${runId}/compare`} className="tx-btn tx-btn--sub">다른 실행과 비교</Link>
        </div>
        {retryErr && (
          <Notice tone="danger" title="다시 실행하지 못했어요">
            지금 결과는 그대로예요. 잠시 뒤 다시 눌러 주세요.
            <details className="scr-err-detail"><summary>자세히</summary><code>{retryErr}</code></details>
          </Notice>
        )}
      </section>

      {/* 곡선 먼저 — 숫자 33개보다 모양이 먼저 읽힌다 */}
      {equity.length > 1 && (
        <Card className="brun-card">
          <CardHeader className="rs-card-h">
            <CardTitle as="h2" className="brun-card-t">자산곡선{bt.benchmark ? <span className="brun-note">벤치마크 {bt.benchmark.label}와 함께</span> : null}</CardTitle>
          </CardHeader>
          <CardContent className="rs-card-b">
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={equity} margin={{ top: 6, right: 10, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="2 3" stroke="var(--tx-line)" vertical={false} />
              <XAxis dataKey="date" tick={{ fontSize: 12, fill: "var(--tx-sub)" }} minTickGap={60} stroke="var(--tx-line)" />
              <YAxis tick={{ fontSize: 12, fill: "var(--tx-sub)" }} width={48} stroke="var(--tx-line)" />
              <Tooltip formatter={(v: number) => v?.toLocaleString("ko-KR")} labelStyle={{ fontSize: 12 }} contentStyle={{ fontSize: 13, borderRadius: 10 }} />
              <Line isAnimationActive={anim} type="monotone" dataKey="equity" stroke="var(--tx-blue)" dot={false} strokeWidth={2} name="이 전략" />
              {bt.benchmark && <Line isAnimationActive={anim} type="monotone" dataKey="bench" stroke="var(--tx-mute)" dot={false} strokeDasharray="4 3" strokeWidth={1.4} name={bt.benchmark.label} />}
            </LineChart>
          </ResponsiveContainer>
          {bt.benchmark && (
            <p className="brun-benchrow">
              벤치마크 {num(bt.benchmark.total_return_pct) != null ? signedPct(bt.benchmark.total_return_pct as number) : "몰라요"}
              {num(bt.benchmark.excess_return_pct) != null && <> · 차이 <b style={{ color: col(bt.benchmark.excess_return_pct) }}>{signedPct(bt.benchmark.excess_return_pct as number).replace("%", "%p")}</b></>}
              {num(bt.benchmark.beta) != null && <> · 베타 {(bt.benchmark.beta as number).toFixed(2)}</>}
              {num(bt.benchmark.alpha_pct) != null && <> · 알파 {signedPct(bt.benchmark.alpha_pct as number)}</>}
            </p>
          )}
          </CardContent>
        </Card>
      )}

      {bt.drawdown_curve?.some((d) => d < 0) && (
        <Card className="brun-card">
          <CardHeader className="rs-card-h">
            <CardTitle as="h2" className="brun-card-t">낙폭<span className="brun-note">고점에서 얼마나 내려갔나요</span></CardTitle>
          </CardHeader>
          <CardContent className="rs-card-b">
          <ResponsiveContainer width="100%" height={150}>
            <AreaChart data={equity} margin={{ top: 6, right: 10, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="2 3" stroke="var(--tx-line)" vertical={false} />
              <XAxis dataKey="date" tick={{ fontSize: 12, fill: "var(--tx-sub)" }} minTickGap={60} stroke="var(--tx-line)" />
              <YAxis tick={{ fontSize: 12, fill: "var(--tx-sub)" }} width={48} stroke="var(--tx-line)" />
              <Tooltip formatter={(v: number) => `${v?.toFixed(1)}%`} contentStyle={{ fontSize: 13, borderRadius: 10 }} />
              <Area isAnimationActive={anim} type="monotone" dataKey="dd" stroke="var(--tx-down)" fill="var(--tx-down-soft)" strokeWidth={1.4} name="낙폭" />
            </AreaChart>
          </ResponsiveContainer>
          </CardContent>
        </Card>
      )}

      <Card className="brun-card rs-key">
        <CardHeader className="rs-card-h">
          <CardTitle as="h2" className="brun-card-t">핵심 지표</CardTitle>
        </CardHeader>
        <CardContent className="rs-card-b">
          <div className="brun-kpis rs-kpis rs-kpis--key">
            {keyDefs.map((m) => <Kpi key={m.k} m={m} v={stats[m.k] as number} />)}
          </div>
          {/* ★산출 불가는 접지 않는다★ — 왜 없는지가 숨으면 원래 없는 지표처럼 읽힌다. */}
          {explained.length > 0 && (
            <div className="rs-na">
              <p className="rs-sub-h">계산하지 못한 지표 {explained.length}개</p>
              <div className="brun-kpis rs-kpis">
                {explained.map(({ m, reason }) => (
                  <div key={m.k} className="brun-kpi brun-kpi-na">
                    <div className="brun-kpi-l">{m.label}</div>
                    {/* ★숫자를 그리지 않는다★ 0 이나 — 을 적으면 측정된 값처럼 읽힌다. */}
                    <span className="brun-kpi-nabadge">산출 불가</span>
                    <div className="brun-kpi-tip">{reason}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
          {restCount > 0 && (
            <details className="rs-all">
              <summary className="rs-more"><span>지표 모두 보기</span><span className="rs-more-n">{restCount}개 더</span><ChevronDown size={18} aria-hidden className="rs-more-i" /></summary>
              {restGroups.map((g) => (
                <div key={g.title} className="brun-mgroup">
                  <p className="brun-mgroup-t">{g.title}</p>
                  <div className="brun-kpis rs-kpis">
                    {g.metrics.map((m) => <Kpi key={m.k} m={m} v={stats[m.k] as number} />)}
                  </div>
                </div>
              ))}
            </details>
          )}
          {stats.eod_liquidated ? <p className="brun-note rs-foot">기간 끝에 {stats.eod_liquidated}종목을 마지막 거래일 종가로 정리했어요.</p> : null}
        </CardContent>
      </Card>

      {monthly.length > 0 && (
        <Card className="brun-card">
          <CardHeader className="rs-card-h">
            <CardTitle as="h2" className="brun-card-t">월별 수익률</CardTitle>
          </CardHeader>
          <CardContent className="rs-card-b">
          <ResponsiveContainer width="100%" height={150}>
            <BarChart data={monthly} margin={{ top: 6, right: 10, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="2 3" stroke="var(--tx-line)" vertical={false} />
              <XAxis dataKey="month" tick={{ fontSize: 12, fill: "var(--tx-sub)" }} minTickGap={20} stroke="var(--tx-line)" />
              <YAxis tick={{ fontSize: 12, fill: "var(--tx-sub)" }} width={40} stroke="var(--tx-line)" />
              <Tooltip formatter={(v: number) => `${v?.toFixed(2)}%`} contentStyle={{ fontSize: 13, borderRadius: 10 }} />
              <Bar isAnimationActive={anim} dataKey="return_pct" radius={[4, 4, 0, 0]}>
                {monthly.map((m, i) => <Cell key={i} fill={m.return_pct >= 0 ? "var(--tx-up)" : "var(--tx-down)"} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          </CardContent>
        </Card>
      )}

      {/* 기여도 — 엔진 산출 contribution_pct */}
      {bt.symbol_results && bt.symbol_results.some((s) => s.contribution_pct != null) && (
        <AttributionChart rows={bt.symbol_results} />
      )}

      {bt.symbol_results && bt.symbol_results.length > 0 && <SymbolTable rows={bt.symbol_results} />}

      {roundTrips.length > 0 && <TradesTable trades={roundTrips} />}

      {/* 데이터와 한계 — 정직 표기: 엔진 미산출 지표는 만들지 않음 */}
      <Card className="brun-card brun-diag">
        <CardHeader className="rs-card-h">
          <CardTitle as="h2" className="brun-card-t">데이터와 한계<span className="brun-note">이 결과를 읽을 때 알아야 할 것</span></CardTitle>
        </CardHeader>
        <CardContent className="rs-card-b">
        <ul className="brun-diag-list">
          {res.pit_evidence && res.pit_evidence.status !== "verified" &&
            <li>{pitBadge.label} — {res.pit_evidence.summary}</li>}
          {!res.pit_evidence && <li>시점 정합을 판정할 자료가 이 실행에 없어요 — 확인됐다는 뜻이 아니에요.</li>}
          {isMock && <li>연습용(합성) 데이터로 돌린 결과예요 — 절대 수치는 참고만 하고, 적재된 시세로 다시 돌려 보세요.</li>}
          {num(stats.num_trades as number) === 0 && <li>체결된 거래가 없어요 — 신호·대상·기간을 점검해 주세요.</li>}
          {universeLines.map((t, i) => <li key={`uv${i}`}>{t}</li>)}
          {priceLines.map((t, i) => <li key={`pb${i}`}>{t}</li>)}
          {macroLines.map((t, i) => <li key={`ml${i}`}>{t}</li>)}
          {fundLines.map((t, i) => <li key={`fp${i}`}>{t}</li>)}
          {res.pit_evidence && res.pit_evidence.status === "verified" &&
            <li className="brun-diag-omit">{res.pit_evidence.note}</li>}
          <li className="brun-diag-omit">롤링 지표·시점별 익스포저·거래별 MFE/MAE는 현재 엔진이 산출하지 않아 표시하지 않아요(추정치로 대체하지 않음).</li>
        </ul>
        </CardContent>
      </Card>
    </div>
  );
}

function Kpi({ m, v }: { m: MetricDef; v: number }) {
  return (
    <div className="brun-kpi">
      <div className="brun-kpi-l">{m.label}</div>
      <div className="brun-kpi-v num" style={{ color: m.signed ? col(v) : undefined }}>{fmtStat(v, m)}</div>
      {/* 설명은 hover 전용이던 title= 을 대신한다 — 키보드·터치에도 닿아야 한다. */}
      <div className="brun-kpi-tip">{m.tip}</div>
    </div>
  );
}

function AttributionChart({ rows }: { rows: SymbolPerf[] }) {
  const anim = useChartAnimation();
  const data = useMemo(() => {
    const withC = rows.filter((r) => r.contribution_pct != null);
    const sorted = [...withC].sort((a, b) => (b.contribution_pct as number) - (a.contribution_pct as number));
    const top = sorted.slice(0, 8);
    const bot = sorted.slice(-8).filter((r) => !top.includes(r));
    return [...top, ...bot].map((r) => ({
      name: r.corp_name || r.symbol, contribution: r.contribution_pct as number,
    }));
  }, [rows]);
  if (data.length === 0) return null;
  const h = Math.max(140, data.length * 26 + 30);
  return (
    <Card className="brun-card">
      <CardHeader className="rs-card-h">
        <CardTitle as="h2" className="brun-card-t">기여도<span className="brun-note">수익을 가장 많이 더하고 뺀 종목</span></CardTitle>
      </CardHeader>
      <CardContent className="rs-card-b">
      <ResponsiveContainer width="100%" height={h}>
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, bottom: 4, left: 8 }}>
          <CartesianGrid strokeDasharray="2 3" stroke="var(--tx-line)" horizontal={false} />
          <XAxis type="number" tick={{ fontSize: 12, fill: "var(--tx-sub)" }} tickFormatter={(v) => `${v}%`} stroke="var(--tx-line)" />
          <YAxis type="category" dataKey="name" tick={{ fontSize: 12, fill: "var(--tx-ink)" }} width={96} stroke="var(--tx-line)" />
          <Tooltip formatter={(v: number) => `${v.toFixed(2)}%`} contentStyle={{ fontSize: 13, borderRadius: 10 }} />
          <Bar isAnimationActive={anim} dataKey="contribution" radius={4}>
            {data.map((d, i) => <Cell key={i} fill={d.contribution >= 0 ? "var(--tx-up)" : "var(--tx-down)"} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}

const pctCell = (v: number | null | undefined) => (num(v) == null ? "—" : signedPct(v as number));

function SymbolTable({ rows }: { rows: SymbolPerf[] }) {
  const sorted = [...rows].sort((a, b) => (b.contribution_pct ?? b.total_return_pct) - (a.contribution_pct ?? a.total_return_pct));
  return (
    <Card className="brun-card">
      <CardHeader className="rs-card-h">
        <CardTitle as="h2" className="brun-card-t">종목별 성과<span className="brun-note">{rows.length}종목 · 기여도 순</span></CardTitle>
      </CardHeader>
      <CardContent className="rs-card-b">
      <div className="brun-tablewrap">
        <table className="brun-table">
          <thead><tr><th>종목</th><th>수익률</th><th>실현 손익(원)</th><th>거래</th><th>이긴 비율</th><th>보유일</th><th>기여도</th></tr></thead>
          <tbody>
            {sorted.slice(0, 40).map((r) => (
              <tr key={r.symbol}>
                <td>{r.corp_name || r.symbol}<span className="brun-code num">{r.symbol}</span></td>
                <td className="num" style={{ color: col(r.total_return_pct) }}>{pctCell(r.total_return_pct)}</td>
                <td className="num">{r.realized_pnl != null ? Math.round(r.realized_pnl).toLocaleString("ko-KR") : "—"}</td>
                <td className="num">{r.round_trips ?? r.num_trades}</td>
                <td className="num">{r.win_rate != null ? `${r.win_rate.toFixed(0)}%` : "—"}</td>
                <td className="num">{r.avg_hold_days != null ? Math.round(r.avg_hold_days) : "—"}</td>
                <td className="num" style={{ color: col(r.contribution_pct) }}>{pctCell(r.contribution_pct)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      </CardContent>
    </Card>
  );
}

function TradesTable({ trades }: { trades: BacktestTrade[] }) {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <Card className="brun-card">
      <CardHeader className="rs-card-h">
        <CardTitle as="h2" className="brun-card-t">거래 기록<span className="brun-note">{trades.length}건 · 줄을 누르면 자세히</span></CardTitle>
      </CardHeader>
      <CardContent className="rs-card-b">
      <details className="rs-trades">
        <summary className="rs-more"><span>거래 {trades.length}건 펼쳐 보기</span><ChevronDown size={18} aria-hidden className="rs-more-i" /></summary>
      <div className="brun-tablewrap">
        <table className="brun-table">
          <thead><tr><th>종목</th><th>산 날</th><th>판 날</th><th>산 값</th><th>판 값</th><th>수익률</th><th>판 이유</th></tr></thead>
          <tbody>
            {trades.slice(0, 200).map((t, i) => (
              <React.Fragment key={i}>
                <tr className="brun-trow" tabIndex={0} aria-expanded={open === i}
                  onClick={() => setOpen(open === i ? null : i)}
                  onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setOpen(open === i ? null : i); } }}>
                  <td>{t.corp_name || t.stock_code}</td>
                  <td className="num">{t.entry_date ?? "—"}</td>
                  <td className="num">{t.exit_date ?? "—"}</td>
                  <td className="num">{t.entry_price?.toLocaleString("ko-KR") ?? "—"}</td>
                  <td className="num">{t.exit_price?.toLocaleString("ko-KR") ?? "—"}</td>
                  <td className="num" style={{ color: col(t.return_pct) }}>{pctCell(t.return_pct)}</td>
                  <td className="brun-reason">{t.reason ?? "—"}</td>
                </tr>
                {open === i && (
                  <tr className="brun-tdetail"><td colSpan={7}>
                    <span>수량 {t.quantity?.toLocaleString("ko-KR") ?? "—"}</span>
                    <span>손익 {t.pnl != null ? `${Math.round(t.pnl).toLocaleString("ko-KR")}원` : "—"}</span>
                    <span>종목코드 {t.stock_code ?? "—"}</span>
                    {t.reason && <span>판 이유 {t.reason}</span>}
                  </td></tr>
                )}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </div>
      </details>
      </CardContent>
    </Card>
  );
}
