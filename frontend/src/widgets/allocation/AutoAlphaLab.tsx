"use client";
// ═══════════════════════════════════════════════════════════════════════════════
// AutoAlphaLab — 실험 후보 생성 샌드박스 (Full Expansion P6 — Experimental)
//   알파 DSL로 후보 표현식을 랜덤/유전 탐색·린트. ★자동 채택 금지★ — 후보를
//   에디터로 보내 검증하거나, experimental 상태로만 스테이징(실전 사용은 검증→승급 필요).
//   대체데이터·텍스트·RL은 미연결(정직 카탈로그).
// ═══════════════════════════════════════════════════════════════════════════════
import React, { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { experimentalApi, type AlphaCandidate } from "@/entities/experimental/api";

export function AutoAlphaLab({ onUseExpr }: { onUseExpr?: (expr: string) => void }) {
  const qc = useQueryClient();
  const [n, setN] = useState(12);
  const [mode, setMode] = useState<"random" | "genetic">("random");
  const [seed, setSeed] = useState(0);
  const [seedsText, setSeedsText] = useState("");
  const [picked, setPicked] = useState<Set<string>>(new Set());

  const genMut = useMutation({
    mutationFn: () => experimentalApi.autoAlpha({
      n, seed, mode, seeds: seedsText.split("\n").map((s) => s.trim()).filter(Boolean),
    }),
    onSuccess: () => setPicked(new Set()),
  });
  const stageMut = useMutation({
    mutationFn: () => experimentalApi.stage([...picked]),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["allocation", "strategy-health"] });
      qc.invalidateQueries({ queryKey: ["alpha", "registry"] });
    },
  });
  const catQ = useQuery({ queryKey: ["experimental", "catalog"], queryFn: () => experimentalApi.catalog().catch(() => null) });

  const res = genMut.data;
  const toggle = (expr: string) => setPicked((p) => {
    const nx = new Set(p); nx.has(expr) ? nx.delete(expr) : nx.add(expr); return nx;
  });

  return (
    <section className="as-card as-aa">
      <div className="as-card-title">AUTOALPHA 실험실 <span className="as-aa-exp">EXPERIMENTAL</span>
        <span className="as-note-inline">후보 생성기 — 자동 채택 없음</span>
      </div>

      {/* 거버넌스 배너 (항상 노출) */}
      <div className="as-aa-gov">
        ⚠ 실험 기능 — 생성된 후보는 <b>자동 채택되지 않습니다</b>. 검증(Alpha Lab) → validated → approved
        승급을 거쳐야 실전 사용 가능. 스테이징은 <b>experimental</b> 상태로만.
      </div>

      {/* 컨트롤 */}
      <div className="as-aa-ctrl">
        <label>개수<input className="num" type="number" min={1} max={50} value={n} onChange={(e) => setN(Math.max(1, Math.min(50, +e.target.value || 1)))} /></label>
        <label>시드<input className="num" type="number" min={0} value={seed} onChange={(e) => setSeed(Math.max(0, +e.target.value || 0))} /></label>
        <label>모드
          <select value={mode} onChange={(e) => setMode(e.target.value as "random" | "genetic")}>
            <option value="random">랜덤 탐색</option>
            <option value="genetic">유전(씨앗 변이)</option>
          </select>
        </label>
        <button className="as-fb-apply" disabled={genMut.isPending} onClick={() => genMut.mutate()}>
          {genMut.isPending ? "생성 중…" : "후보 생성"}
        </button>
      </div>
      {mode === "genetic" && (
        <textarea className="as-input as-aa-seeds" rows={2} placeholder="씨앗 표현식 (줄바꿈 구분) — 예: rank(mom_12m)"
          value={seedsText} onChange={(e) => setSeedsText(e.target.value)} spellCheck={false} />
      )}

      {res && (
        <>
          <div className="as-aa-meta num">
            생성 {res.generated}/{res.requested} · 모드 {res.mode} · 시도 {res.attempts}
          </div>
          <div className="as-aa-bias">🎯 선택편향: {res.selection_bias.note}</div>

          <div className="as-aa-list">
            {res.candidates.map((c: AlphaCandidate) => (
              <div key={c.expr} className={`as-aa-cand${picked.has(c.expr) ? " on" : ""}`}>
                <label className="as-aa-pick">
                  <input type="checkbox" checked={picked.has(c.expr)} onChange={() => toggle(c.expr)} />
                </label>
                <code className="as-aa-expr">{c.expr}</code>
                {c.warnings.length > 0 && <span className="as-aa-warn" title={c.warnings.map((w) => w.message).join("\n")}>⚠{c.warnings.length}</span>}
                {onUseExpr && <button className="as-chip sm" onClick={() => onUseExpr(c.expr)}>에디터로</button>}
              </div>
            ))}
          </div>

          <div className="as-aa-stage">
            <button className="as-fb-apply" disabled={!picked.size || stageMut.isPending} onClick={() => stageMut.mutate()}>
              선택 {picked.size}개 → experimental 스테이징
            </button>
            {stageMut.data && (
              <span className="as-note">
                {stageMut.data.n_staged}개 experimental 등록 · 검증 필요
                {stageMut.data.rejected.length > 0 && ` · 거부 ${stageMut.data.rejected.length}`}
              </span>
            )}
          </div>
        </>
      )}

      {/* 실험 기능 카탈로그 (연결/미연결 정직) */}
      {catQ.data && (
        <div className="as-aa-cat">
          <div className="as-card-title" style={{ marginTop: 6 }}>실험 기능 카탈로그</div>
          {catQ.data.features.map((f) => (
            <div key={f.id} className="as-aa-cat-row">
              <span className={`as-aa-cat-dot ${f.connected ? "on" : "off"}`} />
              <span className="as-aa-cat-lab">{f.label}</span>
              <span className={`as-aa-cat-badge ${f.connected ? "on" : "off"}`}>{f.connected ? "연결됨" : "미연결"}</span>
              <span className="as-aa-cat-desc">{f.desc}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
