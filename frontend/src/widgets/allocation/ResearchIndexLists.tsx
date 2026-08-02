"use client";
// ResearchIndex 의 목록부(최근 런 · 최근 스터디) — `next/dynamic` 으로 떼어내려고 분리했다.
//
// ★왜 나눴나 — 실측 때문이다★
// 색인 전체를 정적으로 두면 /allocation/overview 의 First Load JS 가 233 → 242 kB 로
// 늘었다(ADR 001 한도 4 kB 초과). 이분해 보니 localStorage 저장소도, 맥락 블록도 아니고
// **조회 계층(useQuery + researchApi + AsyncState) 이 페이지 청크로 딸려 들어온 것**이었다.
// 신원과 다음 할 일은 첫 화면에 즉시 있어야 하지만, 목록은 데이터가 도착해야 의미가 있다.
// 그래서 경계를 여기에 둔다 — P2b 의 EvidenceDrawer 와 같은 처치다.
import React from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { researchApi } from "@/entities/research/api";
import { listStudies, type AllocationStudy } from "@/entities/allocation/storage";
import { AsyncState, type AsyncStatus } from "@/shared/ui/States";
import { EvidenceBadge } from "@/shared/ui/evidence";

const ts = (sec: number) => new Date(sec * 1000).toISOString().slice(0, 16).replace("T", " ");

export default function ResearchIndexLists({ activeRunId, studiesVersion }: {
  activeRunId: string | null; studiesVersion: number;
}) {
  const runsQ = useQuery({
    queryKey: ["research-runs", "index"],
    queryFn: () => researchApi.list(undefined, 8),
    staleTime: 30_000,
  });

  const [studies, setStudies] = React.useState<AllocationStudy[]>([]);
  React.useEffect(() => { setStudies(listStudies()); }, [studiesVersion]);

  const runs = runsQ.data?.runs ?? [];
  // ★없음과 조회 불가는 다른 사실이다★ DB 가 죽어서 못 읽은 것을 "런 없음" 으로 그리면
  // 연구자는 자기 기록이 사라졌다고 오해한다.
  const runsStatus: AsyncStatus =
    runsQ.isLoading ? { kind: "loading", label: "런 목록을 불러오는 중" }
    : runsQ.isError ? { kind: "unavailable", reason: "런 저장소를 조회하지 못했습니다(DB 미가용일 수 있습니다). 런이 없다는 뜻은 아닙니다." }
    : runs.length === 0 ? { kind: "empty", label: "아직 기록된 런이 없습니다", reason: "최적화 후 '이 결정을 런으로 기록' 을 누르면 재현 단위가 서버에 남습니다." }
    : { kind: "ready" };

  return (
    <>
      <div className="as-ri-sec">
        <div className="as-ri-sec-h">
          <span>최근 런</span>
          {/* 행마다 딥링크를 달지 않는 이유는 ResearchIndex 상단 주석에 있다(D6). */}
          <Link href="/allocation/journal" className="as-ri-more">저널에서 전체 목록 보기 →</Link>
        </div>
        <AsyncState status={runsStatus}>
          <ul className="as-ri-runs">
            {runs.map((r) => (
              <li key={r.run_id} className={`as-ri-run${r.run_id === activeRunId ? " on" : ""}`}>
                {/* ★이제 진짜로 그 런을 연다★ (D6)
                    이전에는 행이 클릭 불가였다 — 서버는 단건 조회를 주는데 **주소가
                    없어서** 링크할 데가 없었기 때문이다. `?run=` 이 생겨 이 링크는
                    새로고침·공유에도 같은 런을 가리킨다. */}
                <Link href={`/allocation/journal?run=${encodeURIComponent(r.run_id)}`}
                  className="as-ri-run-id num">{r.run_id}</Link>
                <span className="as-ri-run-nm">{r.name || r.kind}</span>
                <span className="as-ri-run-t num">{ts(r.created_at)}</span>
                {r.snapshot?.coverage?.source === "mock" && <em className="as-ri-run-mock">합성</em>}
              </li>
            ))}
          </ul>
        </AsyncState>
      </div>

      <div className="as-ri-sec">
        <div className="as-ri-sec-h">
          <span>최근 스터디</span>
          <EvidenceBadge kind="caution" reason="이 목록은 서버가 아니라 이 브라우저에만 있습니다. 다른 기기·시크릿 창에서는 보이지 않고, 저장소를 비우면 사라집니다.">
            브라우저 로컬
          </EvidenceBadge>
        </div>
        {studies.length === 0
          ? <div className="as-empty">아직 저장된 스터디가 없습니다 — 09 JOURNAL 에서 첫 기록을 남기세요.</div>
          : (
            <ul className="as-ri-studies">
              {studies.slice(0, 5).map((s) => (
                <li key={s.id} className="as-ri-study">
                  <span className="as-ri-study-nm">{s.name}</span>
                  <span className="num">{s.savedAt.slice(0, 16).replace("T", " ")}</span>
                  <span className="num">{Object.keys(s.holdings).length}종목</span>
                </li>
              ))}
            </ul>
          )}
      </div>
    </>
  );
}
