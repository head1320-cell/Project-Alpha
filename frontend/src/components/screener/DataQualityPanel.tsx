"use client";

import { useState, useEffect } from "react";
import { ShieldCheck, AlertCircle, Loader2, Database } from "lucide-react";
import {
  dataQualityApi, type FilterGroupNode, type DataQualityReport,
} from "@/lib/screenerApi";

// ═══════════════════════════════════════════════════════════════════════════════
// DataQualityPanel — 스크리닝 결과 데이터 품질 (4순위 QA)
// ═══════════════════════════════════════════════════════════════════════════════

export function DataQualityPanel({ group, universe, liquidityFloor }: {
  group: FilterGroupNode;
  universe: string;
  liquidityFloor: string;
}) {
  const [report, setReport] = useState<DataQualityReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [masterCount, setMasterCount] = useState<number | null>(null);

  useEffect(() => {
    dataQualityApi.masterStats().then(s => setMasterCount(s.total_resolvable)).catch(() => {});
  }, []);

  useEffect(() => {
    if (!group.conditions.length) return;
    setLoading(true);
    dataQualityApi.check({ universe, filter_ast: group, liquidity_floor: liquidityFloor, limit: 50 })
      .then(setReport).catch(() => {}).finally(() => setLoading(false));
  }, [group, universe, liquidityFloor]);

  const healthColor = (h: string) =>
    h === "excellent" ? "#16a34a" : h === "good" ? "#65a30d" : h === "fair" ? "#d97706" : "#dc2626";
  const healthLabel = (h: string) =>
    h === "excellent" ? "우수" : h === "good" ? "양호" : h === "fair" ? "보통" : h === "poor" ? "미흡" : "데이터 없음";

  if (!report && !loading) return null;

  return (
    <div className="card-md p-4" style={{ borderLeft: "3px solid #16a34a" }}>
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <span style={{ background: "#dcfce7", color: "#16a34a", width: 22, height: 22, borderRadius: 6, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <ShieldCheck size={13} />
          </span>
          <span className="text-sm font-bold" style={{ color: "#16a34a" }}>데이터 품질 검증</span>
          <span className="text-[10px] text-secondary">데이터 인프라 QA</span>
        </div>
        {masterCount && (
          <div className="text-[10px] text-secondary flex items-center gap-1">
            <Database size={10} /> 종목 마스터 {masterCount.toLocaleString()}개
          </div>
        )}
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-[11px] text-secondary">
          <Loader2 size={12} className="animate-spin" /> 품질 검사 중...
        </div>
      )}

      {report && (
        <div className="animate-fade-in">
          {/* 핵심 지표 */}
          <div className="grid grid-cols-4 gap-2 mb-3">
            <div className="bg-light rounded-lg p-2 text-center">
              <div className="text-[9px] text-secondary uppercase tracking-wider">품질 점수</div>
              <div className="text-sm font-mono font-bold" style={{ color: healthColor(report.health) }}>
                {report.avg_score}
              </div>
            </div>
            <div className="bg-light rounded-lg p-2 text-center">
              <div className="text-[9px] text-secondary uppercase tracking-wider">건강도</div>
              <div className="text-sm font-bold" style={{ color: healthColor(report.health) }}>
                {healthLabel(report.health)}
              </div>
            </div>
            <div className="bg-light rounded-lg p-2 text-center">
              <div className="text-[9px] text-secondary uppercase tracking-wider">종목명 해소</div>
              <div className="text-sm font-mono font-bold" style={{ color: report.unknown_names === 0 ? "#16a34a" : "#d97706" }}>
                {(100 - report.unknown_pct).toFixed(0)}%
              </div>
            </div>
            <div className="bg-light rounded-lg p-2 text-center">
              <div className="text-[9px] text-secondary uppercase tracking-wider">이상치</div>
              <div className="text-sm font-mono font-bold" style={{ color: report.issues_total === 0 ? "#16a34a" : "#d97706" }}>
                {report.issues_total}건
              </div>
            </div>
          </div>

          {/* 데이터 출처 */}
          <div className="flex items-center gap-2 mb-2 flex-wrap">
            <span className="text-[10px] text-secondary">데이터 출처:</span>
            <span className="text-[10px] px-2 py-0.5 rounded-full font-medium" style={{ background: report.data_source.fundamentals === "dart_real" ? "#dcfce7" : "#f1f1f6", color: report.data_source.fundamentals === "dart_real" ? "#15803d" : "#71718a" }}>
              펀더멘털 {report.data_source.fundamentals === "dart_real" ? "실데이터(DART)" : "mock"}
            </span>
            <span className="text-[10px] px-2 py-0.5 rounded-full font-medium" style={{ background: report.data_source.market_data === "kis_real" ? "#dcfce7" : "#f1f1f6", color: report.data_source.market_data === "kis_real" ? "#15803d" : "#71718a" }}>
              시세 {report.data_source.market_data === "kis_real" ? "실데이터(KIS)" : "mock"}
            </span>
          </div>

          {/* 문제 종목 */}
          {report.problem_items.length > 0 ? (
            <div className="mt-2 pt-2 border-t border-default">
              <div className="text-[10px] text-secondary mb-1 flex items-center gap-1">
                <AlertCircle size={10} /> 점검 필요 종목 (상위 {Math.min(3, report.problem_items.length)})
              </div>
              {report.problem_items.slice(0, 3).map((p, i) => (
                <div key={i} className="flex items-center justify-between py-0.5 text-[10px]">
                  <span className="font-medium">{p.corp_name}</span>
                  <span className="text-secondary">
                    {p.issues.length > 0 ? p.issues[0] : `결측: ${p.missing.join(", ")}`}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <div className="mt-2 text-[10px]" style={{ color: "#16a34a" }}>
              ✓ 모든 종목 데이터 정상 (이상치·결측 없음)
            </div>
          )}
        </div>
      )}
    </div>
  );
}
