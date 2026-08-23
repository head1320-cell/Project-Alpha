"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// RegimeEnsemblePanel — 국면을 **세 도구로 따로** 본다 (A7-3)
// ─────────────────────────────────────────────────────────────────────────────
// 0M 은 지금까지 국면 확률의 출처가 하나였다 — 성장·물가 축에 가우시안 CDF 를 씌운
// 파라메트릭 방법. 잘 동작하지만 가정이 하나다(축이 정규분포이고 서로 독립이다).
// `src/engine/regime_ensemble.py` 가 여기에 산업 표준 둘을 나란히 붙였다:
// Hamilton(1989) 상태전환과 가우시안 혼합 군집. `statsmodels` · `scikit-learn` 은
// 이미 설치돼 있었고, 없던 것은 **화면**이었다.
//
// ★평균내지 않는다★
// 세 확률을 하나로 합치면 어느 모형이 무슨 말을 했는지 사라진다. 축은 Goldilocks
// 인데 상태전환 모형이 아직 Reflation 에 머물러 있다면 그건 "전환 초입" 이라는
// 정보이지, 평균이 가리키는 어중간한 지점이 아니다. 그래서 세 칸을 나란히 두고
// `agreement` 는 **일치 여부만** 말한다.
//
// ★미가용에 막대를 그리지 않는다★
// 표본 부족·미수렴·라이브러리 부재는 서버가 `{available:false, reason}` 로 준다.
// 균등분포(0.25씩 넷)를 그리면 화면에는 "네 국면이 똑같이 가능" 으로 읽히는데,
// 실제로는 아무것도 추정하지 못한 것이다. 타입도 그렇게 막혀 있다 —
// `available` 로 좁히지 않으면 `probs` 를 읽을 수 없다.
//
// ★전체 리로드 없이 전파★ 새로고침은 react-query 무효화만 한다. `router.refresh()`
// 도 이동도 없다 — 스냅샷 미리보기 상태(Provider)가 살아 있어야 한다.
// ═══════════════════════════════════════════════════════════════════════════════
import React, { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import {
  macroApi, REGIME_COLORS,
  type MarkovDetail, type Regime, type RegimeTool,
} from "@/entities/macro/api";
import { EvidenceBadge } from "@/shared/ui/evidence";
import { LoadingState } from "@/shared/ui/States";
import { RegimeRibbon } from "@/shared/ui/RegimeRibbon";
import { RegimeGraph } from "./RegimeGraph";
import { RegimeTransitionMatrix } from "./RegimeTransitionMatrix";
import { RegimeDriverWaterfall } from "./RegimeDriverWaterfall";

const TOOL_LABEL: Record<string, { name: string; how: string }> = {
  axis:    { name: "축-확률",           how: "성장·물가 축 z + 불확실성(se) → 사분면 확률" },
  markov:  { name: "상태전환 (Markov)", how: "Hamilton(1989) 2상태 — 전이확률·지속성" },
  cluster: { name: "군집 (GMM)",        how: "가우시안 혼합 — 경계를 긋지 않고 뭉치는 모양" },
};

const KO: Record<string, string> = {
  Goldilocks: "골디락스", Reflation: "리플레이션",
  Stagflation: "스태그플레이션", Disinflation: "디스인플레이션",
};

const ORDER: Array<"axis" | "markov" | "cluster"> = ["axis", "markov", "cluster"];

function ToolCard({ id, tool, regimes }: { id: string; tool: RegimeTool; regimes: Regime[] }) {
  const meta = TOOL_LABEL[id];
  return (
    <div className={`as-rge-tool${tool.available ? "" : " na"}`}>
      <div className="as-rge-tool-h">
        <b className="as-rge-tool-n">{meta.name}</b>
        {tool.available && (
          <span className="as-rge-pick" style={{
            background: REGIME_COLORS[tool.argmax]?.bg,
            color: REGIME_COLORS[tool.argmax]?.fg,
            borderColor: REGIME_COLORS[tool.argmax]?.border,
          }}>{KO[tool.argmax] ?? tool.argmax}</span>
        )}
      </div>

      {/* 미가용: 숫자도 막대도 없다. 사유만 있다. */}
      {!tool.available ? (
        <EvidenceBadge kind="unavailable" reason={tool.reason}>추정 불가</EvidenceBadge>
      ) : (
        <div className="as-rge-bars">
          {regimes.map((r) => {
            const p = tool.probs[r] ?? 0;
            return (
              <div className="as-rge-bar" key={r}>
                <span className="as-rge-bar-l">{KO[r] ?? r}</span>
                <span className="as-rge-track">
                  <i style={{ width: `${(p * 100).toFixed(1)}%`, background: REGIME_COLORS[r]?.border }} />
                </span>
                <span className="as-rge-bar-v num">{(p * 100).toFixed(0)}%</span>
              </div>
            );
          })}
        </div>
      )}

      <div className="as-rge-how">{tool.available ? tool.note : meta.how}</div>
    </div>
  );
}

type TabId = "probs" | "shift" | "why";
const TABS: { id: TabId; label: string }[] = [
  { id: "probs", label: "확률 비교" },
  { id: "shift", label: "전환 위험" },
  { id: "why", label: "왜 이 국면인가" },
];

export function RegimeEnsemblePanel({ market = "kr", months = 60 }: { market?: string; months?: number }) {
  const qc = useQueryClient();
  const [tab, setTab] = useState<TabId>("probs");

  const q = useQuery({
    queryKey: ["macro", "regime-ensemble", market, months],
    queryFn: () => macroApi.regimeEnsemble(market, months),
  });
  const exQ = useQuery({
    queryKey: ["macro", "regime-explain", market, months],
    queryFn: () => macroApi.regimeExplain(market, months, 3),
  });

  const data = q.data ?? null;
  const axis = data?.tools.axis;
  const markov = data?.tools.markov;
  const ex = exQ.data ?? null;

  // 미가용 사유를 한곳에 모은다 — 탭 바깥에 띄우기 위해서다.
  const naTools = data
    ? (ORDER.filter((k) => !data.tools[k].available)
        .map((k) => [k, data.tools[k]] as const)
        .filter((e): e is [typeof ORDER[number], { available: false; reason: string }] =>
          !e[1].available))
    : [];
  const exNa = ex && !ex.transitions.available ? ex.transitions.reason : null;

  return (
    <section className="as-card as-rge">
      <div className="as-card-title">
        MULTI-TOOL REGIME ANALYSIS
        <span className="as-note-inline">
          세 방법을 나란히 — 평균내지 않습니다. 갈리는 것 자체가 정보입니다
        </span>
        <button type="button" className="as-rge-refresh"
          onClick={() => qc.invalidateQueries({ queryKey: ["macro", "regime-ensemble"] })}
          disabled={q.isFetching}>
          <RefreshCw size={12} aria-hidden="true" />
          {q.isFetching ? "다시 계산 중…" : "다시 계산"}
        </button>
      </div>

      {q.isLoading && <LoadingState label="세 국면 모형을 적합하는 중" />}

      {!q.isLoading && q.isError && (
        <EvidenceBadge kind="unavailable" reason="매크로 지표를 불러오지 못했습니다 — 국면 모형을 돌릴 입력이 없습니다">
          국면 앙상블 미가용
        </EvidenceBadge>
      )}

      {/* ★리본은 상시★ 탭 뒤에 숨기지 않는다 — 시간 맥락은 어느 탭을 보고 있든
          함께 읽혀야 하고, 한 줄이라 세로 공간도 거의 쓰지 않는다. */}
      {ex && ex.transitions.available && (
        <RegimeRibbon
          points={ex.transitions.path}
          span={ex.span}
          runLength={ex.transitions.run_length_months}
          occupancy={ex.transitions.occupancy}
        />
      )}

      {/* ★미가용 사유는 탭 **바깥**에 요약한다★ A5 가 그은 경계(설명은 접고 사유는
          접지 않는다)를 탭에도 적용한다 — 탭을 바꿔야만 보이는 경고는 없는 경고다. */}
      {(naTools.length > 0 || exNa) && (
        <div className="as-rge-na" role="status">
          {naTools.map(([k, t]) => (
            <span className="as-rge-na-i" key={k}>
              <b>{TOOL_LABEL[k]?.name ?? k}</b> 미가용 — {t.reason}
            </span>
          ))}
          {exNa && <span className="as-rge-na-i"><b>전환 위험·드라이버</b> 미가용 — {exNa}</span>}
        </div>
      )}

      {data && (
        <>
          <div className="as-rge-tabs" role="tablist" aria-label="국면 분석 보기">
            {TABS.map((t) => (
              <button key={t.id} type="button" role="tab" id={`as-rge-tab-${t.id}`}
                aria-selected={tab === t.id} aria-controls={`as-rge-p-${t.id}`}
                className={`as-rge-tab${tab === t.id ? " on" : ""}`}
                onClick={() => setTab(t.id)}>
                {t.label}
              </button>
            ))}
          </div>

          {tab === "probs" && (
            <div className="as-rge-panel" role="tabpanel" id="as-rge-p-probs"
              aria-labelledby="as-rge-tab-probs">
              <div className="as-rge-tools">
                {ORDER.map((k) => (
                  <ToolCard key={k} id={k} tool={data.tools[k]} regimes={data.regimes} />
                ))}
              </div>

              <div className={`as-rge-agree${data.agreement.unanimous === false ? " split" : ""}`}
                role="status">
                <b>{data.agreement.unanimous === true ? "세 방법 일치"
                  : data.agreement.unanimous === false ? "방법마다 다름"
                  : "판정한 도구 없음"}</b>
                <span>{data.agreement.note}</span>
                {Object.entries(data.agreement.picks).map(([k, v]) => (
                  <span className="as-rge-agree-p" key={k}>
                    {TOOL_LABEL[k]?.name ?? k}: {KO[v] ?? v}
                  </span>
                ))}
              </div>

              {/* 전이 그래프 — Markov 가 가용할 때만. 빈 그래프를 그리지 않는다. */}
              {markov?.available ? (
                <RegimeGraph
                  probs={axis?.available ? axis.probs : markov.probs}
                  probsSource={axis?.available ? "축-확률" : "상태전환"}
                  markov={markov.detail as unknown as MarkovDetail}
                  regimes={data.regimes}
                />
              ) : (
                <EvidenceBadge kind="unavailable"
                  reason={markov && !markov.available ? markov.reason : "상태전환 결과가 없습니다"}>
                  전이 그래프 미가용
                </EvidenceBadge>
              )}
            </div>
          )}

          {tab === "shift" && (
            <div className="as-rge-panel" role="tabpanel" id="as-rge-p-shift"
              aria-labelledby="as-rge-tab-shift">
              {exQ.isLoading && <LoadingState label="전이 사후분포를 추정하는 중" />}
              {ex && <RegimeTransitionMatrix tr={ex.transitions} />}
              {!exQ.isLoading && !ex && (
                <EvidenceBadge kind="unavailable" reason="전환 위험을 불러오지 못했습니다">
                  전이행렬 미가용
                </EvidenceBadge>
              )}
            </div>
          )}

          {tab === "why" && (
            <div className="as-rge-panel" role="tabpanel" id="as-rge-p-why"
              aria-labelledby="as-rge-tab-why">
              {exQ.isLoading && <LoadingState label="Shapley 분해를 계산하는 중" />}
              {ex && <RegimeDriverWaterfall dr={ex.drivers} />}
              {!exQ.isLoading && !ex && (
                <EvidenceBadge kind="unavailable" reason="드라이버 분해를 불러오지 못했습니다">
                  분해 미가용
                </EvidenceBadge>
              )}
            </div>
          )}

          <div className="as-rge-foot num">
            시장 {data.market.toUpperCase()} · 축 시계열 {data.n_obs}개월
          </div>
        </>
      )}
    </section>
  );
}
