"use client";
/**
 * 알파 목록 서랍 (BL2 · 마법사 02 ALPHA LAB 의 레지스트리에서 옮김)
 * ==========================================================================
 * 알파 식을 등록하고, 단계를 올리고(초안 → 실험 → 검증 단계 → 승인), 내리거나 지운다. ★단계 요건은 서버가 판단한다★ —
 * 검증 단계는 검증 기록(run)이 있어야, 승인은 승인 메모가 있어야 올라간다. 이 화면은 서버의 거절 사유를 그대로 보인다.
 * 검증 계산 자체는 캔버스의 ‘알파 검증’ 노드가 한다(계산은 노드, 기록 관리는 서랍).
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { alphaApi, type AlphaDef, type AlphaStatus, type LintResult } from "@/entities/alpha/api";

/** 상태 이름은 레지스트리의 단계일 뿐이다 — ‘검증 단계’ 는 검증 기록이 붙었다는 뜻이지 알파가 유효하다는 판정이 아니다. */
const STATUS_KO: Record<AlphaStatus, string> = {
  draft: "초안", experimental: "실험", validated: "검증 단계", approved: "승인", retired: "폐기",
};
const NEXT: Partial<Record<AlphaStatus, AlphaStatus>> = { draft: "experimental", experimental: "validated", validated: "approved" };
const TAG: Record<AlphaStatus, string> = {
  draft: "unknown", experimental: "unknown", validated: "assumed", approved: "confirmed", retired: "failed",
};

function AddAlpha() {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [expr, setExpr] = useState("");
  const [lint, setLint] = useState<LintResult | null>(null);
  const check = useMutation({ mutationFn: () => alphaApi.lint(expr.trim()), onSuccess: setLint });
  const add = useMutation({
    mutationFn: () => alphaApi.upsert({ name: name.trim(), expr: expr.trim() }),
    onSuccess: (r) => { if (!r.error) { setName(""); setExpr(""); setLint(null); qc.invalidateQueries({ queryKey: ["records", "alphas"] }); } },
  });
  const ready = name.trim().length > 0 && expr.trim().length > 0;
  return (
    <details className="pg-rec-add">
      <summary>새 알파 등록</summary>
      <label className="pg-rec-field">이름<input className="pg-field-input" value={name} onChange={(e) => setName(e.target.value)} /></label>
      <label className="pg-rec-field">식
        <textarea className="pg-field-input pg-rec-expr" rows={2} value={expr} spellCheck={false}
                  placeholder="예: zscore(roe) - zscore(vol_60d)"
                  onChange={(e) => { setExpr(e.target.value); setLint(null); }} />
      </label>
      <div className="pg-rec-actions">
        <button type="button" className="pg-btn" disabled={!expr.trim() || check.isPending} onClick={() => check.mutate()}>식 점검</button>
        <button type="button" className="pg-btn pg-btn--primary" disabled={!ready || add.isPending || (lint !== null && !lint.ok)}
                onClick={() => add.mutate()}>초안으로 등록</button>
      </div>
      {check.isError && <p className="pg-field-err">점검하지 못했어요 — {(check.error as Error).message}</p>}
      {lint && (lint.ok && lint.issues.length === 0
        ? <p className="pg-save-msg" role="status">식에 문제가 없어요 · 쓰는 값 {lint.fields.join(", ") || "없음"}</p>
        : <ul className="pg-checks" role="status">{lint.issues.map((i, k) => (
            <li key={k}><span className={`pg-tag pg-tag--${i.level === "error" ? "failed" : i.level === "warn" ? "assumed" : "unknown"}`}>
              {i.level === "error" ? "막힘" : i.level === "warn" ? "주의" : "참고"}</span><span>{i.message}</span></li>
          ))}</ul>)}
      {add.data?.error && <p className="pg-warn" role="status">등록하지 않았어요 — {add.data.message ?? "사유 미상"}</p>}
      {add.isError && <p className="pg-field-err">등록하지 못했어요 — {(add.error as Error).message}</p>}
    </details>
  );
}

function AlphaRow({ a }: { a: AlphaDef }) {
  const qc = useQueryClient();
  const [note, setNote] = useState("");
  const [open, setOpen] = useState(false);
  const refresh = () => qc.invalidateQueries({ queryKey: ["records", "alphas"] });
  const move = useMutation({
    mutationFn: (to: AlphaStatus) => alphaApi.promote(a.alpha_id, to, note),
    onSuccess: (r) => { if (r.ok) { setOpen(false); setNote(""); refresh(); } },
  });
  const del = useMutation({ mutationFn: () => alphaApi.remove(a.alpha_id), onSuccess: refresh });
  const next = NEXT[a.status];
  return (
    <li className="pg-rec-item" data-alpha={a.alpha_id}>
      <div className="pg-rec-row">
        <b className="pg-rec-name">{a.name}</b>
        {a.is_template && <span className="pg-tag pg-tag--unknown">예시</span>}
        <span className={`pg-tag pg-tag--${TAG[a.status]}`}>{STATUS_KO[a.status]}</span>
      </div>
      <code className="pg-rec-code">{a.expr || a.description}</code>
      <p className="pg-pick-sub">v{a.version} · {a.last_run_id ? `검증 기록 ${a.last_run_id}` : "검증 기록 없음"}</p>
      {!a.is_template && (
        <div className="pg-rec-actions">
          {next && <button type="button" className="pg-btn" onClick={() => setOpen((o) => !o)}>{STATUS_KO[next]}(으)로 올리기</button>}
          {a.status !== "retired" && <button type="button" className="pg-btn" disabled={move.isPending} onClick={() => move.mutate("retired")}>폐기</button>}
          <button type="button" className="pg-btn" aria-label={`${a.name} 삭제`} disabled={del.isPending}
                  onClick={() => { if (window.confirm(`‘${a.name}’ 알파를 지울까요? 되돌릴 수 없어요.`)) del.mutate(); }}>지우기</button>
        </div>
      )}
      {open && next && (
        <div className="pg-rec-row">
          <input className="pg-field-input" value={note} aria-label="올리는 이유"
                 placeholder={next === "approved" ? "승인 메모 (꼭 적어야 해요)" : "올리는 이유 (선택)"} onChange={(e) => setNote(e.target.value)} />
          <button type="button" className="pg-btn pg-btn--primary" disabled={move.isPending} onClick={() => move.mutate(next)}>올리기</button>
        </div>
      )}
      {move.data && !move.data.ok && <p className="pg-warn" role="status">바꾸지 않았어요 — {move.data.reason ?? "사유 미상"}</p>}
      {move.isError && <p className="pg-field-err">바꾸지 못했어요 — {(move.error as Error).message}</p>}
    </li>
  );
}

export function AlphaSheetBody() {
  const q = useQuery({ queryKey: ["records", "alphas"], queryFn: () => alphaApi.registry() });
  const [show, setShow] = useState<AlphaStatus | "all">("all");
  const list = (q.data?.alphas ?? []).filter((a) => show === "all" || a.status === show);
  return (
    <>
      <AddAlpha />
      <div className="pg-chips" role="group" aria-label="단계로 거르기">
        {(["all", "draft", "experimental", "validated", "approved", "retired"] as const).map((s) => (
          <button key={s} type="button" aria-pressed={show === s} className={`pg-chip${show === s ? " on" : ""}`}
                  onClick={() => setShow(s)}>{s === "all" ? "전체" : STATUS_KO[s]}</button>
        ))}
      </div>
      {q.isLoading && <p className="pg-help" role="status">불러오는 중이에요.</p>}
      {q.isError && <p className="pg-field-err" role="alert">알파 목록을 불러오지 못했어요 — {(q.error as Error).message}. 알파가 없는 것과 달라요.</p>}
      {q.data && list.length === 0 && <p className="pg-help">{show === "all" ? "등록한 알파가 없어요 — 위에서 식을 등록해요." : "이 단계의 알파가 없어요."}</p>}
      {list.length > 0 && <ul className="pg-rec-list">{list.map((a) => <AlphaRow key={a.alpha_id} a={a} />)}</ul>}
      <p className="pg-note">검증 단계로 올리려면 캔버스의 ‘알파 검증’ 노드에서 ‘검증 기록 남기기’를 먼저 눌러요.</p>
    </>
  );
}
