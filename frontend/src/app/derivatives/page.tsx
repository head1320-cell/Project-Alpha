"use client";

import { useState, useEffect, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { api } from "@/shared/api/legacyApi";
import {
  PageHeader, PageContent, Tabs, Spinner, Section, Field, FormRow, ErrorMsg, StatCard,
} from "@/shared/ui/primitives";   // 배럴(@/shared/ui) 대신 직접 — 아래 주석 참고
import { Play } from "lucide-react";

function DerivativesContent() {
  const searchParams = useSearchParams();
  const tabParam = searchParams.get("tab");
  const [tab, setTab] = useState(0);

  useEffect(() => {
    const map: Record<string, number> = { "vol-surface": 1, xva: 2, rates: 3, mc: 4 };
    if (tabParam && map[tabParam] !== undefined) setTab(map[tabParam]);
  }, [tabParam]);

  return (
    <>
      <PageHeader
        title="파생상품 평가"
        subtitle="옵션 이론가는 블랙-숄즈(유럽형)로 계산해요 — 나머지 탭은 설명만 있고 계산은 아직 없어요"
        breadcrumb={[{ label: "홈", href: "/dashboard" }, { label: "파생상품 평가" }]}
      />
      <PageContent>
        <Tabs
          tabs={["옵션 프라이싱", "변동성 표면", "XVA / CVA", "금리 모델", "Monte Carlo"]}
          active={tab} onChange={setTab}
        />
        <div style={{ marginTop: 20 }}>
          {tab === 0 && <OptionPricingTab />}
          {tab === 1 && <VolSurfaceTab />}
          {tab === 2 && <XVATab />}
          {tab === 3 && <RatesTab />}
          {tab === 4 && <MonteCarloTab />}
        </div>
      </PageContent>
    </>
  );
}

// ── Tab 0: Option Pricing ─────────────────────────────────────────────────────
// 서버(`FICCEngine.bs_greeks`)가 주는 키 그대로 — 대문자다. 예전 화면은 소문자·없는 키(vanna·volga)를 읽어 아무것도 그리지 못했다.
const GREEKS: [string, string][] = [
  ["Price", "이론가"], ["Delta", "델타"], ["Gamma", "감마"],
  ["Theta", "세타 (1일)"], ["Vega", "베가 (변동성 1%p)"], ["Rho", "로 (금리 1%p)"],
];

function OptionPricingTab() {
  const [spot, setSpot]     = useState(100);
  const [strike, setStrike] = useState(100);
  const [vol, setVol]       = useState(0.25);
  const [rate, setRate]     = useState(0.035);
  const [ttm, setTtm]       = useState(0.25);
  const [opt, setOpt]       = useState<"call" | "put">("call");
  const [result, setResult] = useState<Record<string, number> | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError]   = useState("");

  async function run() {
    // 서버 엔진은 S·T·σ ≤ 0 이면 모든 값을 0 으로 돌려준다(침묵 폴백) — 보내기 전에 막는다.
    if (!(spot > 0 && strike > 0 && vol > 0 && ttm > 0)) {
      setResult(null);
      setError("가격·행사가·변동성·만기는 0보다 커야 계산할 수 있어요.");
      return;
    }
    setLoading(true); setError("");
    try {
      const r = await api.optionPrice({
        S: spot, K: strike, sigma: vol, r: rate, T: ttm, option_type: opt,
      }) as Record<string, number>;
      setResult(r);
    } catch (e) { setError((e as Error).message); }
    setLoading(false);
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="card-md">
        <Section title="옵션 입력 (블랙-숄즈, 유럽형)">
          <FormRow cols={3}>
            <Field label="기초자산가 (S)"><input className="input" type="number" value={spot}   onChange={(e) => setSpot(Number(e.target.value))} /></Field>
            <Field label="행사가 (K)">    <input className="input" type="number" value={strike} onChange={(e) => setStrike(Number(e.target.value))} /></Field>
            <Field label="옵션 타입">
              <select className="select" value={opt} onChange={(e) => setOpt(e.target.value as "call" | "put")}>
                <option value="call">Call</option>
                <option value="put">Put</option>
              </select>
            </Field>
          </FormRow>
          <FormRow cols={3}>
            <Field label="변동성 (σ)">    <input className="input" type="number" value={vol}  step={0.01} onChange={(e) => setVol(Number(e.target.value))} /></Field>
            <Field label="무위험이자율 (r)"><input className="input" type="number" value={rate} step={0.005} onChange={(e) => setRate(Number(e.target.value))} /></Field>
            <Field label="만기 (T, 연)">  <input className="input" type="number" value={ttm}  step={0.05} onChange={(e) => setTtm(Number(e.target.value))} /></Field>
          </FormRow>
        </Section>
      </div>

      <button className="btn-primary" onClick={run} disabled={loading}>
        {loading ? <Spinner size={14} /> : <Play size={14} />} 프라이싱 실행
      </button>

      {error && <ErrorMsg msg={error} />}

      {result && (
        <div className="grid grid-cols-4 gap-3 animate-slide-up" data-testid="option-greeks">
          {GREEKS.map(([k, label]) => (
            typeof result[k] === "number" && (
              <StatCard key={k} label={label} value={result[k].toFixed(4)} trend="neutral" />
            )
          ))}
        </div>
      )}
    </div>
  );
}

// ── Tab 1: Vol Surface ────────────────────────────────────────────────────────
function VolSurfaceTab() {
  return (
    <div className="card-md">
      <Section title="변동성 표면 (Implied Volatility Surface)">
        <p style={{ fontSize: 13, color: "var(--text-secondary)" }}>
          기간 구조와 행사가 구조에 따른 내재변동성 표면을 시각화합니다.
          SABR 모델로 fitting하여 외삽/내삽이 가능합니다.
        </p>
        <div className="badge-warning" style={{ display: "inline-block", padding: "4px 10px", marginTop: 8 }}>
          개발 중 — 옵션 시장 데이터 연동 필요
        </div>
      </Section>
    </div>
  );
}

// ── Tab 2: XVA / CVA ──────────────────────────────────────────────────────────
function XVATab() {
  return (
    <div className="card-md">
      <Section title="XVA / CVA 계산">
        <p style={{ fontSize: 13, color: "var(--text-secondary)" }}>
          Hull-White 1F 금리 모델 기반 CVA (Credit Valuation Adjustment) 계산 및 PFE (Potential Future Exposure) 시뮬레이션.
        </p>
        <div style={{
          padding: 12, background: "var(--bg-section)", borderRadius: 4,
          fontFamily: "monospace", fontSize: 13, marginTop: 8,
        }}>
          <strong>CVA</strong> = (1 - R) × Σ EE(t) × dPD(t) × DF(t)
        </div>
        <div className="badge-warning" style={{ display: "inline-block", padding: "4px 10px", marginTop: 12 }}>
          UI 개발 중 — 백엔드 엔진 동작 중
        </div>
      </Section>
    </div>
  );
}

// ── Tab 3: Rates Models ───────────────────────────────────────────────────────
function RatesTab() {
  return (
    <div className="card-md">
      <Section title="금리 모델 (Hull-White 1F · SABR)">
        <p style={{ fontSize: 13, color: "var(--text-secondary)" }}>
          Hull-White 1Factor 모델과 SABR 변동성 모델을 사용하여 시장 데이터에 대한 캘리브레이션을 수행합니다.
          QuantLib과 연동되어 채권/스왑 가격 결정과 그릭 계산을 지원합니다.
        </p>
        <div className="grid grid-cols-2 gap-3 mt-3">
          <div className="card-sm">
            <div className="label">Hull-White 1F</div>
            <div style={{ fontSize: 12, marginTop: 4 }}>dr = (θ(t) - ar) dt + σ dW</div>
          </div>
          <div className="card-sm">
            <div className="label">SABR</div>
            <div style={{ fontSize: 12, marginTop: 4 }}>dF = α F^β dW₁, dα = ν α dW₂, ⟨dW₁,dW₂⟩ = ρ dt</div>
          </div>
        </div>
      </Section>
    </div>
  );
}

// ── Tab 4: Monte Carlo ────────────────────────────────────────────────────────
function MonteCarloTab() {
  return (
    <div className="card-md">
      <Section title="Monte Carlo 시뮬레이션">
        <p style={{ fontSize: 13, color: "var(--text-secondary)" }}>
          GBM (Geometric Brownian Motion) 기반 경로 시뮬레이션으로 path-dependent 옵션과 exotic 상품을 평가합니다.
          백테스트에서 다중 시나리오 분석에도 활용됩니다.
        </p>
        <div className="grid grid-cols-3 gap-3 mt-3">
          <StatCard label="기본 경로 수" value="10,000" trend="neutral" />
          <StatCard label="Antithetic" value="ON" trend="neutral" />
          <StatCard label="Stratified Sampling" value="ON" trend="neutral" />
        </div>
      </Section>
    </div>
  );
}

export default function DerivativesPage() {
  return (
    <Suspense fallback={<div style={{ padding: 40 }}><Spinner /></div>}>
      <DerivativesContent />
    </Suspense>
  );
}
