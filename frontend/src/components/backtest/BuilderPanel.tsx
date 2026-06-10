"use client";

import { useState, useRef, useEffect, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { useBuilderStore } from "@/lib/builder/store";
import { PRESET_STRATEGIES } from "@/lib/builder/presets";
import { IndicatorPanel } from "@/components/builder/IndicatorPanel";
import { ConditionPanel } from "@/components/builder/ConditionPanel";
import { RiskPanel, MetaPanel, PreviewPanel } from "@/components/builder/Panels";
import {
  Tabs, Spinner, Section, Field, ErrorMsg,
} from "@/components/ui";
import { Upload, RotateCcw, FileCode, Sparkles, BookOpen } from "lucide-react";
import Link from "next/link";
import dynamic from "next/dynamic";

// React Flow는 SSR 불가 → dynamic import
const StrategyCanvas = dynamic(
  () => import("@/components/builder/StrategyCanvas"),
  { ssr: false, loading: () => <div style={{ padding: 40, textAlign: "center" }}>캔버스 로딩 중...</div> },
);

const STEP_LABELS = ["지표 선택", "진입 조건", "청산 조건", "리스크 관리", "메타 정보"];

function BuilderContent() {
  const searchParams = useSearchParams();
  const tabParam = searchParams.get("tab");
  const [tab, setTab] = useState(0);

  useEffect(() => {
    if (tabParam === "dsl") setTab(1);
    else if (tabParam === "yaml") setTab(2);
    else if (tabParam === "library") setTab(3);
    else if (tabParam === "canvas") setTab(4);
    else setTab(0);
  }, [tabParam]);

  return (
    <>
      {/* 노드 캔버스는 전체 화면 → PageContent 밖에서 렌더링 */}
      {tab === 4 ? (
        <>
          <div style={{ padding: "0 24px", maxWidth: 1320, margin: "0 auto" }}>
            <Tabs tabs={["비주얼 빌더", "DSL 커스텀", "YAML 가져오기", "전략 라이브러리", "노드 캔버스"]} active={tab} onChange={setTab} />
          </div>
          <NodeCanvasTab />
        </>
      ) : (
        <div className="builder-panel-content">
          <Tabs tabs={["비주얼 빌더", "DSL 커스텀", "YAML 가져오기", "전략 라이브러리", "노드 캔버스"]} active={tab} onChange={setTab} />
          <div style={{ marginTop: 20 }}>
            {tab === 0 && <VisualBuilderTab />}
            {tab === 1 && <DSLTab />}
            {tab === 2 && <YamlImportTab />}
            {tab === 3 && <LibraryTab />}
          </div>
        </div>
      )}
    </>
  );
}

// ── Tab 0: Visual Builder (3-column layout) ──────────────────────────────────
function VisualBuilderTab() {
  const { metadata } = useBuilderStore();
  const [step, setStep] = useState(0);

  return (
    <div className="grid gap-4" style={{ gridTemplateColumns: "260px 1fr 360px", minHeight: 600 }}>

      {/* Left: Step navigation */}
      <div className="card" style={{ padding: 12 }}>
        <div className="label" style={{ marginBottom: 10 }}>설계 단계</div>
        <div className="flex flex-col gap-1">
          {STEP_LABELS.map((label, i) => (
            <button key={label} onClick={() => setStep(i)}
              className="flex items-center gap-3 transition-all"
              style={{
                padding: "8px 12px", borderRadius: 4,
                background: step === i ? "var(--accent-light)" : "transparent",
                border: "1px solid " + (step === i ? "var(--accent)" : "transparent"),
                color: step === i ? "var(--accent)" : "var(--text-secondary)",
                cursor: "pointer", textAlign: "left", fontSize: 13,
              }}>
              <span style={{
                width: 22, height: 22, borderRadius: "50%",
                background: step === i ? "var(--accent)" : "var(--border)",
                color: step === i ? "white" : "var(--text-muted)",
                display: "inline-flex", alignItems: "center", justifyContent: "center",
                fontSize: 11, fontWeight: 700,
              }}>{i + 1}</span>
              <span style={{ fontWeight: step === i ? 600 : 500 }}>{label}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Center: Step content */}
      <div className="card" style={{ padding: 20, overflow: "auto" }}>
        <div className="flex items-center justify-between mb-3">
          <h2 style={{ fontSize: 16, fontWeight: 700, color: "var(--text-primary)" }}>
            {STEP_LABELS[step]}
          </h2>
          <span className="badge-info">{step + 1} / {STEP_LABELS.length}</span>
        </div>

        {step === 0 && <IndicatorPanel />}
        {step === 1 && <ConditionPanel section="entry" />}
        {step === 2 && <ConditionPanel section="exit" />}
        {step === 3 && <RiskPanel />}
        {step === 4 && <MetaPanel />}

        <div className="flex justify-between mt-4">
          <button className="btn-ghost" onClick={() => setStep(Math.max(0, step - 1))} disabled={step === 0}>
            ← 이전
          </button>
          <button className="btn-primary" onClick={() => setStep(Math.min(STEP_LABELS.length - 1, step + 1))}
            disabled={step === STEP_LABELS.length - 1}>
            다음 →
          </button>
        </div>
      </div>

      {/* Right: Live preview */}
      <div className="card" style={{ overflow: "hidden" }}>
        <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--border)", background: "var(--bg-section)" }}>
          <div className="label">실시간 미리보기</div>
          <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 2 }}>
            {metadata.name || "이름 없는 전략"}
          </div>
        </div>
        <div style={{ height: 540 }}>
          <PreviewPanel />
        </div>
      </div>
    </div>
  );
}

// ── Tab 1: DSL ────────────────────────────────────────────────────────────────
function DSLTab() {
  const [buy, setBuy]   = useState("ma(5) crosses_above ma(20)");
  const [sell, setSell] = useState("ma(5) crosses_below ma(20)");
  const [name, setName] = useState("나만의 전략");

  const PRESETS = [
    { label: "골든크로스", buy: "ma(5) crosses_above ma(20)", sell: "ma(5) crosses_below ma(20)" },
    { label: "RSI 반등",  buy: "rsi(14) < 30 AND close > ma(60)", sell: "rsi(14) > 70" },
    { label: "MACD 크로스", buy: "macd crosses_above macd_signal", sell: "macd crosses_below macd_signal" },
    { label: "망치형 + RSI", buy: "hammer > 0 AND rsi(14) < 40", sell: "shooting_star < 0" },
  ];

  return (
    <div className="grid gap-4" style={{ gridTemplateColumns: "1fr 360px" }}>
      <div className="flex flex-col gap-4">
        <div className="card-md flex flex-col gap-3">
          <Section title="DSL 수식 입력">
            <Field label="전략 이름">
              <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <Field label="매수 조건 (Entry)" hint="예: ma(5) crosses_above ma(20)">
              <input className="input" style={{ fontFamily: "monospace" }} value={buy} onChange={(e) => setBuy(e.target.value)} />
            </Field>
            <Field label="매도 조건 (Exit)" hint="예: rsi(14) > 70 OR ma(5) crosses_below ma(20)">
              <input className="input" style={{ fontFamily: "monospace" }} value={sell} onChange={(e) => setSell(e.target.value)} />
            </Field>
          </Section>
        </div>

        <div className="card-md">
          <div className="label" style={{ marginBottom: 8 }}>예제 수식</div>
          <div className="flex flex-wrap gap-2">
            {PRESETS.map((p) => (
              <button key={p.label} className="btn-ghost" style={{ fontSize: 12 }}
                onClick={() => { setBuy(p.buy); setSell(p.sell); }}>
                {p.label}
              </button>
            ))}
          </div>
        </div>

        <div className="card-md">
          <div className="label" style={{ marginBottom: 8 }}>지표 / 캔들 레퍼런스</div>
          <div style={{ background: "var(--bg-section)", padding: 12, borderRadius: 4, fontSize: 12, fontFamily: "monospace", lineHeight: 1.8 }}>
            <div><strong style={{ color: "var(--accent)" }}>지표:</strong> ma(n), ema(n), rsi(n), macd, bb_upper(n), bb_lower(n), atr(n), volume, change, disparity(n)</div>
            <div><strong style={{ color: "var(--success)" }}>강세 캔들:</strong> hammer, engulfing, morning_star, three_white_soldiers</div>
            <div><strong style={{ color: "var(--danger)" }}>약세 캔들:</strong> shooting_star, dark_cloud_cover, evening_star, three_black_crows</div>
            <div><strong style={{ color: "var(--warning)" }}>연산자:</strong> {">"}, {"<"}, {">="}, {"<="}, ==, AND, OR, crosses_above, crosses_below</div>
          </div>
        </div>

        <Link href={`/backtest?tab=dsl&buy=${encodeURIComponent(buy)}&sell=${encodeURIComponent(sell)}&name=${encodeURIComponent(name)}`}>
          <button className="btn-primary" style={{ width: "100%" }}>이 DSL로 백테스트 →</button>
        </Link>
      </div>

      <div className="card" style={{ overflow: "hidden" }}>
        <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--border)", background: "var(--bg-section)" }}>
          <div className="label">DSL 미리보기</div>
        </div>
        <pre style={{
          padding: 16, fontSize: 12, lineHeight: 1.7,
          fontFamily: "monospace", background: "var(--bg-section)",
          margin: 0, overflow: "auto", maxHeight: 500,
        }}>
{`# Strategy: ${name}

class ${name.replace(/[^a-zA-Z0-9]/g, "_")}Strategy:
    name = "${name}"

    def generate_signal(self, code, name):
        df = data_fetcher.get_daily_prices(code, 100)
        if df.empty:
            return Signal(code, name, Action.HOLD, 0)

        # Entry condition
        if ${buy}:
            return Signal(code, name, Action.BUY, 0.8,
                          "DSL 매수 조건 충족")

        # Exit condition
        if ${sell}:
            return Signal(code, name, Action.SELL, 0.8,
                          "DSL 매도 조건 충족")

        return Signal(code, name, Action.HOLD, 0)
`}
        </pre>
      </div>
    </div>
  );
}

// ── Tab 2: YAML Import ────────────────────────────────────────────────────────
function YamlImportTab() {
  const [content, setContent] = useState("");
  const [error, setError]     = useState("");
  const [valid, setValid]     = useState(false);
  const [validating, setVal]  = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  async function handleFile(file: File) {
    const text = await file.text();
    setContent(text);
    await validate(text);
  }

  async function validate(yaml: string) {
    if (!yaml.trim()) { setValid(false); setError(""); return; }
    setVal(true); setError("");
    try {
      const res = await fetch("/api/backend/api/v1/files/validate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: yaml }),
      });
      const data = await res.json();
      if (data.valid) {
        setValid(true);
      } else {
        setValid(false);
        setError(data.errors?.join(", ") ?? "검증 실패");
      }
    } catch (e) {
      setError((e as Error).message);
    }
    setVal(false);
  }

  return (
    <div className="card-md flex flex-col gap-3" style={{ maxWidth: 900 }}>
      <div className="flex items-center justify-between">
        <h2 style={{ fontSize: 16, fontWeight: 700 }}>.kis.yaml 파일 가져오기</h2>
        <div className="flex gap-2">
          <input ref={fileRef} type="file" accept=".yaml,.yml" hidden
            onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])} />
          <button className="btn-ghost" onClick={() => fileRef.current?.click()}>
            <Upload size={12} style={{ marginRight: 4, display: "inline" }} />
            파일 선택
          </button>
        </div>
      </div>

      <Field label="YAML 내용">
        <textarea className="input" style={{ height: 280, fontFamily: "monospace", fontSize: 12, lineHeight: 1.6, resize: "vertical" }}
          value={content}
          onChange={(e) => { setContent(e.target.value); validate(e.target.value); }}
          placeholder={`version: "1.0"\nmetadata:\n  name: 나의 전략\nstrategy:\n  id: my_strategy\n  ...`} />
      </Field>

      {validating && <div style={{ fontSize: 12, color: "var(--text-muted)" }}>검증 중...</div>}
      {valid && <div className="badge-success" style={{ display: "inline-block", padding: "4px 10px" }}>✓ 유효한 .kis.yaml</div>}
      {error && <ErrorMsg msg={error} />}

      <div className="flex gap-2 mt-2">
        <Link href={`/backtest?tab=yaml&content=${encodeURIComponent(content)}`}>
          <button className="btn-primary" disabled={!valid}>이 YAML로 백테스트 →</button>
        </Link>
      </div>
    </div>
  );
}

// ── Tab 3: Library ────────────────────────────────────────────────────────────
function LibraryTab() {
  const { loadState } = useBuilderStore();

  return (
    <div>
      <h2 style={{ fontSize: 16, fontWeight: 700, marginBottom: 12 }}>10개 KIS 검증 전략 프리셋</h2>
      <div className="grid grid-cols-3 gap-3">
        {PRESET_STRATEGIES.map((p) => (
          <div key={p.id} className="card card-hover" style={{ padding: 16 }}>
            <div className="flex items-center justify-between mb-2">
              <BookOpen size={16} style={{ color: "var(--accent)" }} />
              <span className="badge-info">{p.category ?? "기본"}</span>
            </div>
            <h3 style={{ fontSize: 14, fontWeight: 700, marginBottom: 4 }}>{p.name}</h3>
            <p style={{ fontSize: 12, color: "var(--text-secondary)", marginBottom: 12, lineHeight: 1.5 }}>
              {p.description ?? "프리셋 전략"}
            </p>
            <div className="flex gap-2">
              <button className="btn-ghost" style={{ flex: 1, fontSize: 12 }}
                onClick={() => loadState(p.state)}>
                빌더로 로드
              </button>
              <Link href={`/backtest?strategy=${encodeURIComponent(p.name)}`} style={{ flex: 1 }}>
                <button className="btn-primary" style={{ width: "100%", fontSize: 12 }}>백테스트</button>
              </Link>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Tab 4: Node Canvas (full-screen React Flow) ──────────────────────────────
function NodeCanvasTab() {
  return <StrategyCanvas />;
}

export function BuilderPanel() {
  return (
    <Suspense fallback={<div style={{ padding: 40, textAlign: "center" }}><Spinner size={20} /></div>}>
      <BuilderContent />
    </Suspense>
  );
}
