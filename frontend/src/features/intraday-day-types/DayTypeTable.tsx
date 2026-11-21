"use client";
/**
 * 유형 표 — 유형마다 표본 수 · 비중 · 끝값 · 최저 · 최고 · 흩어짐, 그리고 그 유형으로 묶인 표본(날 · 종목) 목록.
 * 표본이 없는 유형도 0 으로 보인다(센 값이다) · 흩어짐은 표본이 없으면 미상(N/A — 0 이 아니다).
 * 값은 서버 값 그대로이고 글자만 여기서 짓는다(같은 서식 함수를 그림의 읽는 줄과 함께 쓴다).
 */
import { useId } from "react";
import type { DayTypeModel } from "@/entities/intraday";
import { pct } from "@/shared/lib/krFormat";
import { bpSize, bpText, clock } from "./format";

export function DayTypeTable({ model }: { model: DayTypeModel }) {
  const note = useId();
  // 설명은 표 밖 문단으로 — 표는 좁은 화면에서 제 상자 안에서 가로로 움직이고, 설명 글은 절의 폭에서 줄을 바꾼다.
  return (
    <>
    <p className="itd-dt-caption" id={note}>유형별 표본. 흩어짐은 그 유형 표본들이 중심 경로에서 떨어진 정도(RMS · bp)입니다.</p>
    <div className="tj-scroll-x itd-dt-table-wrap">
      <table className="pg-table itd-dt-table" aria-describedby={note}>
        <thead>
          <tr>
            <th>유형</th><th className="pg-td-num">표본</th><th className="pg-td-num">비중</th><th className="pg-td-num">끝값</th>
            <th className="pg-td-num">최저</th><th className="pg-td-num">최고</th><th className="pg-td-num">흩어짐</th><th>표본 목록</th>
          </tr>
        </thead>
        <tbody>
          {model.types.map((t) => {
            const members = model.members.filter((m) => m.type === t.type);
            return (
              <tr key={t.type} data-type={t.type}>
                <td>유형 {t.type}</td>
                <td className="pg-td-num itd-dt-n">{t.samples.toLocaleString("ko-KR")}</td>
                <td className="pg-td-num">{pct(t.share)}</td>
                <td className="pg-td-num">{bpText(t.end)}</td>
                <td className="pg-td-num">{bpText(t.low)}</td>
                <td className="pg-td-num">{bpText(t.high)}</td>
                <td className="pg-td-num itd-dt-spread">{bpSize(t.spread)}</td>
                <td>
                  {members.length ? (
                    <details className="itd-dt-members">
                      <summary>보기({members.length.toLocaleString("ko-KR")})</summary>
                      <ul>{members.map((m) => <li key={`${m.date}-${m.ticker}`}>{m.date} · {m.ticker} · 첫 봉 {clock(m.start)}</li>)}</ul>
                    </details>
                  ) : <span className="itd-why">표본 없음</span>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
    </>
  );
}
