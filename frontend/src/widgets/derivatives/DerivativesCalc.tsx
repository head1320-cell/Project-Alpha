"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// 파생상품 계산기(BU7c · 사용자 결정 "있는 계산기를 탭으로 연결")
// ─────────────────────────────────────────────────────────────────────────────
// 옛 화면은 다섯 탭 중 옵션만 계산했고, 몬테카를로 탭의 "10,000 / ON / ON" 카드는 결과처럼 보이는 상수였다.
// 서버에는 채권(`/analyze-bond`)·선물 헤지(`/calculate-hedge`)·신용 위험(`/calculate-cva`) 계산기가 이미 있었다 — 그것을 탭으로 잇는다.
// 서버가 계산하지 않는 모형(변동성 곡면·금리 모형·몬테카를로)은 한 탭에 "설명만 있어요"로 모은다(가짜 결과 카드 없음).
// 탭은 주소 `?tab=` 와 같이 움직인다(옛 주소 `vol-surface`·`xva`·`rates`·`mc` 도 받는다).
// ═══════════════════════════════════════════════════════════════════════════════
import { useRouter, useSearchParams } from "next/navigation";
import { Chips, PageHead, Tabs } from "@/shared/ui/tx";
import { OptionCalc } from "./OptionCalc";
import { BondCalc } from "./BondCalc";
import { HedgeCalc } from "./HedgeCalc";
import { CvaCalc } from "./CvaCalc";

type Tab = "option" | "bond" | "hedge" | "cva" | "models";
const TABS: { value: Tab; label: string }[] = [
  { value: "option", label: "옵션" }, { value: "bond", label: "채권" }, { value: "hedge", label: "선물 헤지" },
  { value: "cva", label: "신용 위험(CVA)" }, { value: "models", label: "아직 계산하지 않는 모형" },
];
const OLD: Record<string, Tab> = { "vol-surface": "models", xva: "cva", rates: "models", mc: "models" };
export function tabOf(q: string | null): Tab {
  if (!q) return "option";
  return (TABS.find((t) => t.value === q)?.value) ?? OLD[q] ?? "option";
}

export function DerivativesCalc() {
  const sp = useSearchParams();
  const router = useRouter();
  const tab = tabOf(sp.get("tab"));
  const pick = (t: Tab) => router.replace(t === "option" ? "/derivatives" : `/derivatives?tab=${t}`, { scroll: false });

  return (
    <div className="dv tx-page">
      <PageHead title="파생상품 계산기" lede="옵션·채권·선물 헤지·신용 위험을 넣은 값으로 계산해요. 시장 데이터를 불러오지 않아요." />
      <Chips label="이 계산기의 전제" items={[
        { label: "모든 칸은 넣은 값(가정)이에요", tone: "assumed" },
        { label: "계산은 서버가 하고 화면은 풀이만 해요", tone: "info" },
      ]} />
      <Tabs label="계산기 고르기" tabs={TABS} value={tab} onChange={pick}>
        {tab === "option" ? <OptionCalc /> : tab === "bond" ? <BondCalc /> : tab === "hedge" ? <HedgeCalc /> : tab === "cva" ? <CvaCalc /> : <ModelsInfo />}
      </Tabs>
    </div>
  );
}

const MODELS: { id: string; name: string; what: string; need: string; formula: string }[] = [
  { id: "vol-surface", name: "변동성 곡면", what: "행사가와 만기에 따라 시장이 매긴 변동성(내재변동성)을 한 면으로 그려요. SABR 모형으로 사이 값과 바깥 값을 메워요.",
    need: "옵션 시장 호가가 필요해요. 이 저장소에는 아직 옵션 호가를 적재하지 않아요.", formula: "σ_imp(K, T)" },
  { id: "rates", name: "금리 모형", what: "Hull-White 1요인 모형으로 단기 금리의 움직임을 그리고, 채권·스왑 가격을 시장 곡선에 맞춰요.",
    need: "금리 곡선과 스왑션 변동성 데이터, 그리고 맞추기(캘리브레이션) 계산기가 필요해요. 서버에 이 계산 경로가 없어요.", formula: "dr = (θ(t) − a·r) dt + σ dW" },
  { id: "mc", name: "몬테카를로", what: "가격 경로를 많이 만들어 경로에 따라 값이 달라지는 상품(아시안·배리어 옵션 등)을 평가해요.",
    need: "이 화면에서 부를 서버 계산 경로가 없어요. 옛 화면의 경로 수·기법 카드는 계산 결과가 아니어서 지웠어요.", formula: "dS = μ S dt + σ S dW" },
];

function ModelsInfo() {
  return (
    <div className="dv-calc" data-calc="models">
      <section className="tx-sec">
        <h2 className="tx-sec-t">아직 계산하지 않는 모형</h2>
        <p className="tx-sec-sub">설명만 있어요. 이 화면은 아래 모형으로 계산하지 않고, 결과처럼 보이는 숫자도 두지 않아요.</p>
        <ul className="dv-models">
          {MODELS.map((m) => (
            <li key={m.id} className="dv-model" data-model={m.id}>
              <h3 className="dv-h3">{m.name}</h3>
              <p>{m.what}</p>
              <p className="dv-model-need"><b>계산하려면</b> {m.need}</p>
              <p className="dv-model-f"><span data-mono>{m.formula}</span></p>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
