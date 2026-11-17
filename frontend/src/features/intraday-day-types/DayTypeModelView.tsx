"use client";
/**
 * 하루 유형 모형 하나 — 사실 줄 · 손실 줄 · 난수 시드 일치도 줄 · 유형 그림 · 유형 표 · 서버의 한계 문장.
 * ==========================================================================
 * ★서버 글자 그대로★ — 손실 · 일치도의 문장과 보이는 숫자, 출처 등급 문장, 뺀 표본의 사유, 한계 문장은 서버가 지은 것을 싣는다(`data-server`).
 * 화면이 다시 반올림하거나 해석을 덧붙이지 않는다. 합성 분봉으로 학습한 모형이면 맨 위에 그렇게 적는다.
 * 유형은 장 시작 구간의 모양을 묶은 것이다 — 이 화면은 순위 · 추천 · '좋은 유형'을 말하지 않는다.
 */
import type { DayTypeAnswer } from "@/entities/intraday";
import { Notice } from "@/shared/ui/tx";
import { DayTypeChart } from "./DayTypeChart";
import { DayTypeTable } from "./DayTypeTable";
import { clock } from "./format";

export function DayTypeModelView({ answer }: { answer: DayTypeAnswer }) {
  const m = answer.model;
  const ex = m.excluded;
  const dates = m.days.length;
  return (
    <div className="itd-dt-model" data-key={m.key} data-synthetic={m.synthetic ? "true" : "false"}>
      {m.synthetic ? (
        <Notice tone="practice" title="합성 분봉으로 학습한 모형입니다.">
          <span data-server>{m.grade_reason}</span>
        </Notice>
      ) : null}
      <dl className="itd-dt-facts">
        <div><dt>학습 기간</dt><dd>{m.first_day} ~ {m.last_day} · 날 {dates.toLocaleString("ko-KR")}일</dd></div>
        <div><dt>종목</dt><dd>{m.tickers.join(", ")}</dd></div>
        <div><dt>장 시작 구간</dt><dd>첫 봉부터 {m.minutes}분</dd></div>
        <div><dt>유형 수</dt><dd>{m.k}개 · e-means · 난수 시드 {m.seed}</dd></div>
        <div><dt>학습한 표본</dt><dd>{m.samples.toLocaleString("ko-KR")}개(종목 하나의 하루가 표본 하나)</dd></div>
        <div><dt>첫 봉 시각</dt><dd>{m.starts.map((s) => `${clock(s.start)} ${s.samples.toLocaleString("ko-KR")}개`).join(" · ")}</dd></div>
        <div className="itd-dt-excluded"><dt>뺀 표본</dt><dd>
          {ex.total === 0 ? "없음" : (
            <ul>{Object.entries(ex.by_reason).map(([code, n]) => (
              <li key={code} data-reason={code}><span data-server>{ex.messages[code] ?? code}</span> {n.toLocaleString("ko-KR")}개</li>
            ))}</ul>
          )}
        </dd></div>
        {m.synthetic ? null : <div><dt>출처 등급</dt><dd><span data-server>{m.grade_reason ?? "등급을 매기지 않았습니다."}</span></dd></div>}
      </dl>
      <p className="itd-dt-loss" data-server>{m.loss.note}</p>
      <p className="itd-dt-agree" data-same={m.agreement.same ? "true" : "false"}>
        <span data-server>{m.agreement.note}</span>
        <span className="itd-dt-ari"> 시드별 조정 랜드 지수(시드 {m.agreement.seeds[0]} 대비): {m.agreement.seeds.slice(1).map((s, i) => `${s} ${m.agreement.shown[i]}`).join(" · ")}</span>
      </p>
      <DayTypeChart types={m.types} minutes={m.minutes} />
      <DayTypeTable model={m} />
      <ul className="itd-dt-notes">{answer.notes.map((n) => <li key={n} data-server>{n}</li>)}</ul>
    </div>
  );
}
