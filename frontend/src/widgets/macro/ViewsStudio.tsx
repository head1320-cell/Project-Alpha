"use client";
/**
 * 05 VIEWS — 뷰 컴파일러 (M1-U)
 * ==========================================================================
 * 프론티어(CLQT: 공시문·검색 트렌드를 LLM 이 뷰로 바꾸는 것)는 이 환경에서 미가용이다
 * — LLM 키도 트렌드 API 도 없다. 그래서 여기서 짓는 것은 **사용자가 명시한 뷰**를
 * `Ak ≤ b` 로 컴파일하고 모순을 검사하는 결정론적 부분뿐이고, 텍스트→뷰 단계는
 * `available:false` + 사유로 남는다.
 *
 * ★없는 근거로 만든 뷰가 포트폴리오를 움직이는 것이 이 화면에서 가장 위험하다★
 * 그래서 화면은 뷰의 출처를 사용자 입력으로만 두고, 자동 생성을 흉내내지 않는다.
 *
 * ★`feasible: null` 을 "실현가능" 으로 그리지 않는다★ 시나리오 없이 검사하지 않은
 * 것과 검사해서 통과한 것은 다른 사실이고, 서버가 이미 `null` 로 갈라 두었다.
 */

import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { LoadingState, ErrorState, UnavailableState } from "@/shared/ui/States";
import { studiosApi, type StudioResult, type ViewSpec } from "@/entities/macro/studios";
import { FrontierCard, StudioOutcome } from "./StudioPanel";

const DEFAULT_ASSETS = "069500,229200,148070,132030";

interface Draft { asset: string; direction: 1 | -1; value: string }

export function ViewsStudio() {
  const [assetsText, setAssetsText] = useState(DEFAULT_ASSETS);
  const [drafts, setDrafts] = useState<Draft[]>([{ asset: "069500", direction: 1, value: "0.02" }]);
  const [res, setRes] = useState<StudioResult | null>(null);

  const listQ = useQuery({
    queryKey: ["macro", "studios"],
    queryFn: () => studiosApi.list(),
    staleTime: 60_000,
  });
  const d = listQ.data?.studios.find((s) => s.id === "agentic-mcp") ?? null;

  const assets = assetsText.split(/[,\s]+/).map((s) => s.trim()).filter(Boolean);

  const m = useMutation({
    mutationFn: () => {
      const views: ViewSpec[] = drafts
        .filter((x) => x.asset.trim() && x.value.trim() !== "" && Number.isFinite(Number(x.value)))
        .map((x) => ({ asset: x.asset.trim(), direction: x.direction, value: Number(x.value) }));
      return studiosApi.compileViews(assets, views);
    },
    onSuccess: setRes,
  });

  const setDraft = (i: number, patch: Partial<Draft>) =>
    setDrafts((ds) => ds.map((x, j) => (j === i ? { ...x, ...patch } : x)));

  return (
    <div className="ms-studio tpage-fade">
      <header className="ms-head">
        <h1 className="ms-h1">{d?.label ?? "VIEWS"}</h1>
        {d && <p className="ms-q">{d.question}</p>}
      </header>

      {listQ.isLoading && <LoadingState label="스튜디오 계약을 불러오는 중" />}
      {listQ.isError && (
        <ErrorState label="스튜디오 목록에 닿지 못했습니다"
          sub="서버가 미가용이라고 답한 것과 다릅니다 — 응답 자체를 받지 못했습니다." />
      )}
      {d && <FrontierCard d={d} />}

      <section className="ms-card ms-card-sub">
        <h2 className="ms-card-t">대체 엔진{d ? ` — ${d.substitute.name}` : ""}</h2>
        {d && <p className="ms-card-s">{d.substitute.summary}</p>}

        <form className="ms-views" onSubmit={(e) => { e.preventDefault(); m.mutate(); }}>
          <label className="ms-vf">
            유니버스 (쉼표 구분)
            <input className="ms-vi ms-vi-w" value={assetsText}
                   onChange={(e) => setAssetsText(e.target.value)} />
          </label>

          {drafts.map((x, i) => (
            <div key={i} className="ms-vrow">
              <label className="ms-vf">
                자산
                <input className="ms-vi" value={x.asset}
                       onChange={(e) => setDraft(i, { asset: e.target.value })} />
              </label>
              <label className="ms-vf">
                방향
                <select className="ms-vi" value={x.direction}
                        onChange={(e) => setDraft(i, { direction: Number(e.target.value) === -1 ? -1 : 1 })}>
                  <option value={1}>기대수익 ≥</option>
                  <option value={-1}>기대수익 ≤</option>
                </select>
              </label>
              <label className="ms-vf">
                값 (소수, 예 0.02 = 2%)
                <input className="ms-vi num" value={x.value} inputMode="decimal"
                       onChange={(e) => setDraft(i, { value: e.target.value })} />
              </label>
              <button type="button" className="ms-vdel"
                      aria-label={`${i + 1}번 뷰 삭제`}
                      onClick={() => setDrafts((ds) => ds.filter((_, j) => j !== i))}>×</button>
            </div>
          ))}

          <div className="ms-vacts">
            <button type="button" className="ms-vbtn"
                    onClick={() => setDrafts((ds) => [...ds, { asset: "", direction: 1, value: "" }])}>
              + 뷰 추가
            </button>
            <button type="submit" className="ms-vbtn ms-vbtn-run" disabled={m.isPending || !assets.length}>
              {m.isPending ? "컴파일 중…" : "제약으로 컴파일"}
            </button>
          </div>
        </form>

        {m.isError && (
          <ErrorState label="컴파일 요청에 닿지 못했습니다"
            sub="서버가 미가용이라고 답한 것과 다릅니다 — 응답 자체를 받지 못했습니다." />
        )}
        {res && <StudioOutcome res={res} />}
        {res?.available && res.outputs.feasible === null && (
          // 서버의 note 가 이미 같은 말을 하지만, 이 한 줄은 **검사 결과 자리**에 놓인다 —
          // 빈 자리를 남기면 "검사했고 문제없음" 으로 읽힌다.
          <UnavailableState
            label="실현가능성 — 검사하지 않았습니다"
            reason="시나리오를 주지 않았습니다. 모순이 없다는 뜻이 아니라, 확인하지 않았다는 뜻입니다." />
        )}
      </section>
    </div>
  );
}

export default ViewsStudio;
