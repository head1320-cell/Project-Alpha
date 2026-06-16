"use client";
// /insights-lab — Company Analysis 후보 디자인 비교 (A Terminal / B Briefing / C Cockpit)
//   목업 전용. 대표 데이터(sampleData)로 렌더 — 선택된 후보를 /insights 로 프로덕션화 예정.
import { useState } from "react";
import { COMPANIES, byCode } from "@/components/insights-lab/sampleData";
import CandidateTerminal from "@/components/insights-lab/CandidateTerminal";
import CandidateBriefing from "@/components/insights-lab/CandidateBriefing";
import CandidateCockpit from "@/components/insights-lab/CandidateCockpit";

const CANDS = [
  { id: "C", label: "Cockpit", desc: "하이브리드 (추천)" },
  { id: "A", label: "Terminal", desc: "고밀도 탭형" },
  { id: "B", label: "Briefing", desc: "내러티브 스크롤" },
] as const;
type CandId = typeof CANDS[number]["id"];

export default function InsightsLabPage() {
  const [cand, setCand] = useState<CandId>("C");
  const [code, setCode] = useState("005930");
  const company = byCode(code);

  return (
    <div className="ca-lab">
      <div className="ca-lab-bar">
        <div className="ca-lab-title">Company Analysis — 후보 비교 <span className="ca-lab-note">목업 · 대표 데이터</span></div>
        <div className="ca-lab-switch">
          {CANDS.map((x) => (
            <button key={x.id} className={`ca-lab-cand${cand === x.id ? " on" : ""}`} onClick={() => setCand(x.id)}>
              <b>{x.id}</b> {x.label}<span>{x.desc}</span>
            </button>
          ))}
        </div>
        <select className="ca-lab-ticker" value={code} onChange={(e) => setCode(e.target.value)}>
          {COMPANIES.map((c) => <option key={c.code} value={c.code}>{c.name} ({c.code})</option>)}
        </select>
      </div>

      <div className="ca-lab-stage">
        {cand === "A" && <CandidateTerminal company={company} onPick={setCode} />}
        {cand === "B" && <CandidateBriefing company={company} />}
        {cand === "C" && <CandidateCockpit company={company} onPick={setCode} />}
      </div>
    </div>
  );
}
