"use client";
/**
 * CaseBar — 연구 케이스 컨텍스트 바 (M1-U)
 * ==========================================================================
 * `/macro`(국면·매크로 브레인)와 `/allocation/*`(실행 엔진) **양쪽 상단**에 같은
 * 컴포넌트를 붙인다. 두 화면을 잇는 것은 링크가 아니라 **같은 케이스를 보고 있다는
 * 사실**이고, 그 사실을 화면이 계속 말하지 않으면 사용자는 두 도구를 쓰는 것이지
 * 하나의 연구를 하는 것이 아니게 된다.
 *
 * ★왜 `shared/ui` 가 아니라 `features/` 인가 (측정으로 정한 자리)★
 * 청사진은 `CatalogueShell`·`ArchiveDrawer`·`RegimeRibbon` 전례를 들어 `shared/ui`
 * 라고 적었는데, 그 셋은 전부 **props 만 받는 프레젠테이션 컴포넌트**다. CaseBar 는
 * 케이스·사슬·능력 레벨을 스스로 조회해야 하고, `.eslintrc.js` 가 `shared → entities`
 * 를 차단한다. 그리고 `entities/case` 가 `entities/macro`(capability)를 부르는 것도
 * 같은 계층 peer 금지에 걸린다 — 조립은 위 계층이 해야 한다. features 가 그 자리다.
 *
 * ★ContextStrip 과 중복하지 않는다★
 * AAS 의 ContextStrip 은 **이 세션이 붙인** 스냅샷을, CaseBar 는 **서버 케이스가
 * 고정한** MES 를 낸다. 둘은 다를 수 있고, 다르면 그것이 정보다 — `sessionSnapshotId`
 * 를 받아 **불일치할 때만** 한 줄 경고한다. 같은 칩을 두 번 그리지 않는다.
 */

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge } from "@/shared/ui/shadcn/badge";
import { getActiveCaseId, setActiveCaseId } from "@/shared/lib/caseStorage";
import { caseApi, type CaseChain, type ResearchCase } from "@/entities/case/api";
import { studiosApi, type Capability } from "@/entities/macro/studios";

/** 능력 레벨 배지의 색 — 강한 주장일수록 밝게, 그러나 **색만으로 말하지 않는다**. */
function levelVariant(level: string): "bull" | "neutral" | "warn" {
  if (level === "L0") return "bull";
  if (level === "L3") return "warn";
  return "neutral";
}

function CaseCreateForm({ onDone }: { onDone: (caseId: string) => void }) {
  const [name, setName] = useState("");
  const [question, setQuestion] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const qc = useQueryClient();

  const m = useMutation({
    mutationFn: () => caseApi.create({ name: name.trim(), question: question.trim() }),
    onSuccess: (res) => {
      if (!res.created || !res.case_id) {
        // 저장 실패를 성공으로 위장하지 않는다 — 사유를 그 자리에 적는다.
        setMsg(res.message || "케이스가 저장되지 않았습니다.");
        return;
      }
      qc.invalidateQueries({ queryKey: ["research-cases"] });
      onDone(res.case_id);
    },
    onError: (e) => setMsg(e instanceof Error ? e.message : "케이스 생성에 실패했습니다."),
  });

  const ready = name.trim().length > 0 && question.trim().length > 0;

  return (
    <form
      className="as-case-form"
      onSubmit={(e) => { e.preventDefault(); if (ready) m.mutate(); }}
    >
      <label className="as-case-fl">
        이름
        <input className="as-case-fi" value={name} maxLength={200}
               onChange={(e) => setName(e.target.value)} placeholder="예) 2026 상반기 방어 전환" />
      </label>
      <label className="as-case-fl">
        {/* ★질문이 Case 를 Study 와 구분한다★ 서버가 필수로 강제하므로 화면도 강제한다. */}
        연구 질문
        <input className="as-case-fi as-case-fi-q" value={question} maxLength={2000}
               onChange={(e) => setQuestion(e.target.value)}
               placeholder="예) 신용스프레드 확대 국면에서 방어 전환이 실제로 유효했는가?" />
      </label>
      <button type="submit" className="as-case-btn" disabled={!ready || m.isPending}>
        {m.isPending ? "만드는 중…" : "케이스 만들기"}
      </button>
      {msg && <span className="as-case-msg" role="status">{msg}</span>}
    </form>
  );
}

export function CaseBar({ sessionSnapshotId = null }: { sessionSnapshotId?: string | null }) {
  const [caseId, setCaseId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  // localStorage 는 서버 렌더에 없다 — 마운트 후에 읽는다(하이드레이션 불일치 방지).
  useEffect(() => { setCaseId(getActiveCaseId()); }, []);

  const capQ = useQuery<Capability>({
    queryKey: ["macro", "capability"],
    queryFn: () => studiosApi.capability(),
    staleTime: 60_000,
  });

  const listQ = useQuery({
    queryKey: ["research-cases", "open"],
    queryFn: () => caseApi.list("open", 50),
    staleTime: 30_000,
  });

  const chainQ = useQuery<CaseChain>({
    queryKey: ["research-cases", "chain", caseId],
    queryFn: () => caseApi.chain(caseId as string),
    enabled: !!caseId,
  });

  const pick = (id: string | null) => { setActiveCaseId(id); setCaseId(id); setCreating(false); };

  const cases: ResearchCase[] = listQ.data?.available ? listQ.data.cases : [];
  const active = chainQ.data?.case ?? cases.find((c) => c.case_id === caseId) ?? null;

  // ★"고른 케이스를 못 읽었다" 와 "고른 케이스가 없다" 는 다른 사실이다★
  // 첫 구현은 둘을 한 화면("케이스 없음")으로 그렸다 — 새 스펙이 그것을 잡았다.
  // 포인터가 있으면 **식별자는 안다.** 아는 것은 그리고, 모르는 것(질문·포인터들)은
  // 사유와 함께 비운다. 이 저장소가 반복해 적어 온 `없음 ≠ 못 읽음` 의 같은 사례다.
  const unresolved = !!caseId && !active;

  // ★세션 스냅샷과 케이스 고정이 다르면 그 사실을 말한다★
  // 같은 칩을 두 번 그리는 대신, 두 값이 갈라졌을 때만 한 줄 낸다.
  const mesId = active?.active_mes_id ?? null;
  const diverged = !!(sessionSnapshotId && mesId && sessionSnapshotId !== mesId);

  const tpvId = active?.active_tpv_id ?? null;
  const tpv = chainQ.data?.targets.available
    ? chainQ.data.targets.items.find((t) => t.tpv_id === tpvId) ?? null
    : null;

  return (
    <div className="as-case" role="region" aria-label="연구 케이스 컨텍스트">
      <div className="as-case-row">
        <span className="as-case-k">CASE</span>

        {active ? (
          <>
            <span className="as-case-id num" title={active.name}>{active.case_id}</span>
            <span className="as-case-q">{active.question}</span>
          </>
        ) : unresolved ? (
          <>
            <span className="as-case-id num">{caseId}</span>
            <span className="as-case-q as-case-unres">
              이 케이스의 내용을 불러오지 못했습니다 — 질문·고정 증거·목표를 여기서 읽을 수 없습니다.
            </span>
          </>
        ) : (
          // ★지어낸 id 를 그리지 않는다★ 케이스가 없으면 없다고 적는다.
          <span className="as-case-none">케이스 없음 — 이 화면의 작업은 아직 어느 연구에도 묶이지 않습니다.</span>
        )}

        {/* 케이스 선택 — 네이티브 select(저장소 관례. A3 가 Select 프리미티브를 기각한 근거 그대로) */}
        <label className="as-case-pick">
          <span className="as-case-picklab">케이스</span>
          <select className="as-case-sel" value={caseId ?? ""}
                  onChange={(e) => pick(e.target.value || null)}>
            <option value="">— 선택 안 함 —</option>
            {cases.map((c) => (
              <option key={c.case_id} value={c.case_id}>{c.name}</option>
            ))}
          </select>
        </label>
        <button type="button" className="as-case-btn as-case-new"
                onClick={() => setCreating((v) => !v)} aria-expanded={creating}>
          {creating ? "취소" : "+ 새 케이스"}
        </button>

        <span className="as-case-fill" />

        {/* MES — 케이스가 고정한 매크로 증거. 세션이 붙인 것과 다를 수 있다. */}
        {mesId ? (
          <span className="as-case-mes num">MES {mesId}<em className="as-case-src">PINNED</em></span>
        ) : (
          <span className="as-case-na">MES 미고정</span>
        )}

        {/* TPV — 실행 가능 여부는 배지 + 사유. 색만으로 말하지 않는다. */}
        {tpvId ? (
          <span className="as-case-tpv num">
            TPV {tpvId}
            {tpv && (
              <Badge variant={tpv.status === "executable" ? "bull" : "warn"} className="as-case-tpvb">
                {tpv.status === "executable" ? "실행 가능" : "연구 전용"}
              </Badge>
            )}
          </span>
        ) : (
          <span className="as-case-na">목표 버전 없음</span>
        )}

        {/* 능력 레벨 — ★사유 없는 배지는 그리지 않는다 (M1-C)★ */}
        {capQ.data ? (
          <span className="as-case-cap">
            <Badge variant={levelVariant(capQ.data.level)} className="as-case-capb">
              {capQ.data.level} {capQ.data.label}
            </Badge>
          </span>
        ) : capQ.isLoading ? (
          <span className="as-case-na">능력 레벨 확인 중…</span>
        ) : (
          <span className="as-case-na">능력 레벨을 읽지 못했습니다</span>
        )}
      </div>

      {creating && <CaseCreateForm onDone={pick} />}

      {/* 경고·한계는 접지 않는다 (A5 가 그은 경계). */}
      <div className="as-case-warns" role="status">
        {capQ.data?.blocked_level && capQ.data.blocked_reason && (
          <div className="as-case-warn as-case-warn-cap">
            <b className="as-case-warn-l">{capQ.data.blocked_level} 미도달</b>
            <span className="as-case-warn-r">{capQ.data.blocked_reason}</span>
          </div>
        )}
        {diverged && (
          <div className="as-case-warn as-case-warn-div">
            <b className="as-case-warn-l">증거 불일치</b>
            <span className="as-case-warn-r">
              이 세션이 붙인 스냅샷({sessionSnapshotId})과 케이스가 고정한 매크로 증거({mesId})가 다릅니다.
            </span>
          </div>
        )}
        {unresolved && (
          <div className="as-case-warn as-case-warn-missing">
            <b className="as-case-warn-l">케이스를 읽지 못했습니다</b>
            <span className="as-case-warn-r">
              {chainQ.isError
                ? `선택한 케이스(${caseId})를 서버에서 가져오지 못했습니다 — 삭제되었거나 저장소를 읽을 수 없습니다.`
                : chainQ.isLoading
                  ? `선택한 케이스(${caseId})를 불러오는 중입니다.`
                  : `선택한 케이스(${caseId})가 열린 케이스 목록에 없습니다.`}
            </span>
          </div>
        )}
        {listQ.data && !listQ.data.available && (
          <div className="as-case-warn as-case-warn-store">
            <b className="as-case-warn-l">저장소 장애</b>
            <span className="as-case-warn-r">{listQ.data.reason}</span>
          </div>
        )}
        {listQ.isError && (
          <div className="as-case-warn as-case-warn-net">
            <b className="as-case-warn-l">네트워크 오류</b>
            <span className="as-case-warn-r">
              케이스 목록에 닿지 못했습니다 — 케이스가 없는 것과 다릅니다.
            </span>
          </div>
        )}
      </div>

      {/* ★포인터는 브라우저 로컬, 케이스는 서버★ 라벨이 그 경계를 지킨다. */}
      <div className="as-case-foot">
        활성 케이스 선택은 이 브라우저에만 저장됩니다 — 케이스 자체는 서버에 있습니다.
      </div>
    </div>
  );
}

export default CaseBar;
