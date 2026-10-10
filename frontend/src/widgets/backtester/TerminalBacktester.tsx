"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { ChevronDown } from "lucide-react";
import { backtestRunApi } from "@/entities/backtest-run/api";
import { getScreenerHandoff, clearScreenerHandoff, type ScreenerStrategyHandoff } from "@/shared/lib/screenerHandoff";
import { getMacroHandoff, clearMacroHandoff, type MacroBacktestHandoff } from "@/entities/macro/handoff";
import {
  listSavedStrategies, saveBacktestStrategy, deleteSavedStrategy,
  mergeStrategy, type SavedBacktestStrategy,
} from "@/entities/backtest/strategyLibrary";
import type { BacktestStrategy } from "@/entities/backtest/strategy";
import { Notice, PageHead } from "@/shared/ui/tx";
import BuyConditionPanel from "./panels/BuyConditionPanel";
import SellConditionPanel from "./panels/SellConditionPanel";
import UniversePanel from "./panels/UniversePanel";
import CapitalPanel from "./panels/CapitalPanel";
import ConditionSummary, { stepGroups, type StepId } from "./panels/ConditionSummary";
import { applyMacroConfig, initialStrategy, strategyToRun } from "./strategyModel";

// ═══════════════════════════════════════════════════════════════════════════════
// 백테스트 편집기 (BU3 · ADR-003) — 설계 순서 넷 → 고른 단계만 펼침 → 오른쪽 요약 · 실행 하나
//   · ★요청은 한 바이트도 바꾸지 않는다★ 전략 모델·`strategyToRun`·기본값 그대로 — `e2e/backtest-requests.spec.ts` 골든이 건다.
//     바뀐 것은 자리(돈·기간·비용을 매수에서 ④ 로)와 그리기뿐.
//   · 실행하면 진행 화면(`/backtest/runs/{id}/loading`)으로 간다 — 이 화면 아래에 결과를 그리지 않는다. 옛 "결과가 여기에
//     표시돼요" 자리는 결과가 한 번도 뜬 적 없는 거짓 약속이라 지웠다(BU3).
//   · 실행 실패는 alert(무엇·어떻게) + 원문은 "자세히". 번호(1~4)는 참인 순서라서 쓴다.
// ═══════════════════════════════════════════════════════════════════════════════

const STEPS: Array<{ id: StepId; name: string }> = [
  { id: "buy", name: "무엇을 살까" },
  { id: "sell", name: "언제 팔까" },
  { id: "universe", name: "어디서 고를까" },
  { id: "capital", name: "돈·기간·비용" },
];

/** 단계 머리의 "지금" 줄 — 사용자가 넣은 설정을 되읽는다(판단이 아니다). 오른쪽 요약과 같은 `stepGroups` 한 곳에서 꺼낸다. */
const NOW_ROWS: Record<StepId, Array<[group: string, row: string]>> = {
  buy: [["매수 조건", "조건식"], ["매수 조건", "우선순위"], ["매수 비중", "최대 보유"], ["매수 비중", "방식"]],
  sell: [["목표가 / 손절가", "목표가"], ["목표가 / 손절가", "손절가"], ["조건 매도", "조건식"]],
  universe: [["매매 대상 종목", "선택한 매매 대상"], ["유니버스", "시총군"], ["업종 선택", "포함 업종 수"]],
  capital: [["포트 기본", "투자금"], ["포트 기본", "기간"], ["포트 기본", "수수료"], ["포트 기본", "리밸런싱"]],
};
function nowRows(s: BacktestStrategy, step: StepId) {
  const groups = stepGroups(s, step);
  return NOW_ROWS[step].map(([g, r]) => groups.find((x) => x.label === g)?.rows.find((y) => y.label === r))
    .filter((x): x is NonNullable<typeof x> => !!x);
}

export default function TerminalBacktester() {
  const [s, setS] = useState<BacktestStrategy>(initialStrategy);
  const [step, setStep] = useState<StepId>("buy");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [handoff, setHandoff] = useState<ScreenerStrategyHandoff | null>(null);
  const [macroHandoff, setMacroHandoffState] = useState<MacroBacktestHandoff | null>(null);
  const [saved, setSaved] = useState<SavedBacktestStrategy[]>([]);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);

  useEffect(() => {
    const h = getScreenerHandoff();
    if (h) setHandoff(h);
    // 매크로 전략 백테스트 이식 → mode별(conditions/asset_alloc/engine) 백테스터 구성 프리필
    const mh = getMacroHandoff();
    if (mh?.config) {
      setMacroHandoffState(mh);
      setS((prev) => applyMacroConfig(prev, mh.config));
    }
    setSaved(listSavedStrategies());
  }, []);

  const handleSaveStrategy = () => {
    saveBacktestStrategy(s);
    setSaved(listSavedStrategies());
    setSaveMsg(`‘${s.name || "내 전략"}’을 저장했어요 — 새로고침해도 남아요`);
    setTimeout(() => setSaveMsg(null), 4000);
  };
  const handleLoadStrategy = (item: SavedBacktestStrategy) => {
    setS(mergeStrategy(initialStrategy(), item.strategy));
    setSaveMsg(`‘${item.name}’을 불러왔어요`);
    setTimeout(() => setSaveMsg(null), 3000);
  };
  const handleDeleteStrategy = (id: string) => {
    deleteSavedStrategy(id);
    setSaved(listSavedStrategies());
  };

  const router = useRouter();
  // 실행 → durable BacktestRun 생성 → 진행 화면으로 이동(결과는 고정 URL 에서). 유효 run_id 를 받기 전엔 옮겨 가지 않는다.
  const run = async () => {
    setLoading(true); setErr(null);
    try {
      const config = strategyToRun(s, handoff, macroHandoff?.config ?? null) as unknown as Record<string, unknown>;
      const stratName = String(config.strategy_name ?? handoff?.conditionSummary?.[0] ?? "백테스트").slice(0, 100);
      const { run_id } = await backtestRunApi.create({ config, strategy_name: stratName });
      router.push(`/backtest/runs/${run_id}/loading`);
    } catch (e) {
      setErr((e as Error).message || "백테스트 생성 실패");
      setLoading(false);
    }
  };

  const macroCfg = macroHandoff?.config;
  const macroMode = macroCfg?.mode === "conditions" ? "조건식(고칠 수 있어요)"
    : macroCfg?.mode === "asset_alloc" ? "ETF 자산배분" : "동적 엔진(최적화형)";

  return (
    <div className="tpage-fade tx-page tx-page--wide bte">
      <PageHead title="백테스트" lede="전략을 지난 데이터로 돌려 봐요. 순서대로 정하고 실행해요." />

      {handoff && (
        <div className="bte-handoff tscreener-handoff">
          <Notice tone="warn" title={`종목 찾기에서 넘어온 조건 ${handoff.conditionSummary.length}개로 종목을 골라요`}>
            {handoff.resultCount > 0 ? `넘어올 때 ${handoff.resultCount.toLocaleString("ko-KR")}종목이 맞았어요.` : null}
            <ul className="tx-chips" aria-label="넘어온 조건">
              {handoff.conditionSummary.map((c, i) => <li key={i} className="tx-chip" data-tone="plain">{c}</li>)}
            </ul>
            <div className="scr-retry">
              <button type="button" className="tx-btn tx-btn--sub tscreener-handoff-clear"
                onClick={() => { clearScreenerHandoff(); setHandoff(null); }}>넘어온 조건 지우기</button>
            </div>
          </Notice>
        </div>
      )}

      {macroCfg && (
        <div className="bte-handoff tscreener-handoff">
          <Notice tone="warn" title={`매크로 분석에서 넘어온 전략 ‘${macroCfg.name}’ · ${macroMode}`}>
            {`${macroCfg.universe_codes?.length ?? macroCfg.basket?.length ?? 0}종목으로 실행해요.`}
            <ul className="tx-chips" aria-label="넘어온 설정">
              {macroCfg.mode === "conditions" && (macroCfg.buy_conditions || []).map((c, i) => (
                <li key={i} className="tx-chip" data-tone="plain">{c.expr} ≥ {c.rhs ?? 0}</li>))}
              {macroCfg.mode === "asset_alloc" && (macroCfg.basket || []).map((b, i) => (
                <li key={i} className="tx-chip" data-tone="plain">{b.name} {b.weight_pct}%</li>))}
              {macroCfg.mode === "engine" && <li className="tx-chip" data-tone="plain">{macroCfg.note}</li>}
            </ul>
            <div className="scr-retry">
              <button type="button" className="tx-btn tx-btn--sub tscreener-handoff-clear"
                onClick={() => { clearMacroHandoff(); setMacroHandoffState(null); }}>넘어온 전략 지우기</button>
            </div>
          </Notice>
        </div>
      )}

      <div className="tbt-config-row bte-grid">
        <div className="tbt-config-main bte-steps">
          {STEPS.map((st, i) => {
            const open = step === st.id;
            return (
              <section key={st.id} className="bte-step" data-step={st.id}>
                <button type="button" data-act={`step-${st.id}`} aria-expanded={open} aria-controls={`bte-body-${st.id}`}
                  className={`tbt-mode${open ? " active" : ""}`} onClick={() => setStep(st.id)}>
                  <span className="bte-step-n">{i + 1}</span>
                  <span className="bte-step-main">
                    <span className="bte-step-t">{st.name}</span>
                    <span className="bte-step-now">
                      {nowRows(s, st.id).map((r) => <span key={r.label}><b>{r.label}</b>{r.value}</span>)}
                    </span>
                  </span>
                  <ChevronDown className="bte-step-go" size={20} aria-hidden />
                </button>
                {open && (
                  <div className="bte-step-body" id={`bte-body-${st.id}`}>
                    {st.id === "buy" && <BuyConditionPanel s={s} set={setS} />}
                    {st.id === "sell" && <SellConditionPanel s={s} set={setS} />}
                    {st.id === "universe" && <UniversePanel s={s} set={setS} />}
                    {st.id === "capital" && <CapitalPanel s={s} set={setS} />}
                  </div>
                )}
              </section>
            );
          })}
        </div>

        <aside className="tbt-right-col bte-side" aria-label="요약과 실행">
          <div className="tbt-action-box bte-act">
            <button type="button" onClick={run} disabled={loading} data-act="run" className="tbt-run tx-btn tx-btn--main">
              {loading ? "실행을 시작하는 중이에요" : "백테스트 실행"}
            </button>
            <p className="bte-run-note">실행하면 진행 화면으로 옮겨 가요. 결과는 그 화면에서 볼 수 있어요.</p>
            {err && (
              <Notice tone="danger" title="실행을 시작하지 못했어요">
                설정은 그대로예요. 잠시 뒤 다시 실행해 주세요.
                <details className="scr-err-detail"><summary>자세히</summary><code>{err}</code></details>
              </Notice>
            )}

            <div className="bte-save">
              <input value={s.name} onChange={(e) => setS((x) => ({ ...x, name: e.target.value }))} aria-label="전략 이름"
                placeholder="전략 이름" className="tbt-action-name bte-input" data-act="strategy-name" />
              <button type="button" onClick={handleSaveStrategy} data-act="save" className="tbt-action-save tx-btn tx-btn--sub">
                저장
              </button>
            </div>
            {saveMsg && <p className="tbt-action-msg bte-msg" role="status">{saveMsg}</p>}

            {saved.length > 0 && (
              <>
                <p className="bte-saved-h">저장한 전략 {saved.length}개</p>
                <ul className="tbt-saved-list bte-saved">
                  {saved.map((item) => (
                    <li key={item.id} className="tbt-saved-item">
                      <button type="button" data-act="load" className="tbt-saved-load"
                        aria-label={`${item.name} 불러오기`} onClick={() => handleLoadStrategy(item)}>{item.name}</button>
                      <button type="button" aria-label={`${item.name} 지우기`} className="tbt-saved-del"
                        onClick={() => handleDeleteStrategy(item.id)}>✕</button>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>

          <ConditionSummary s={s} step={step} />
        </aside>
      </div>
    </div>
  );
}
