"use client";
/**
 * '시장 국면별로 나눠 보기' 절 안의 '하루 유형 비율' — 방금 남은 시행의 표본을 내 하루 유형 모형으로 배정해 국면별로 센다 (구현 계획 §7.3 · K2b)
 * ==========================================================================
 * ★읽기만이다★ — 서버는 시행 줄 · 모형 줄 · 적재된 분봉을 읽고 국면을 계산할 뿐 시행을 남기지 않는다(시행 수 불변).
 * 지수 · 국면 수는 이 절 위의 칸(국면별 성과 나눔과 같은 칸)을 쓴다 — 바뀌면 부모가 이 부품을 새로 그려 앞의 답을 지운다.
 * ★모형은 비어서 시작한다★ — 도구는 모형을 고르지 않는다. 목록은 내 모형만(서버가 거른다 · 운영에서는 합성 모형이 빠지고 그 수와 사유가 온다)이고
 * 칸에 들어갈 때마다 다시 읽는다(같은 화면의 '하루 유형' 절에서 막 학습한 모형이 바로 보이게). 읽지 못하면 빈 목록이 아니라 그 사유를 보인다.
 * 국면 수나 모형이 비면 묻지 않는다 · 거절 · 없음은 서버 사유 그대로 · 실패는 재시도.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { getRegimeDayTypes, listDayTypes, type DayTypeSummary, type MarketIndex, type RegimeDayTypesAnswer } from "@/entities/intraday";
import { RegimeDayTypesTable } from "@/features/intraday-regime-day-types";
import { modelLabel, NO_MODELS } from "@/features/intraday-rule-editor";
import { Section } from "@/shared/ui/tx";
import { RegimeRequestFailure } from "./RegimeRequestFailure";

const SUB = "이 시행의 종목과 기간의 표본(종목 하나의 하루)을 내 하루 유형 모형으로 배정해 그날 시가 전에 알던 국면별로 셉니다. "
  + "시행을 새로 남기지 않습니다. 같은 날의 두 이름표를 겹쳐 센 관측이며 어느 쪽이 다른 쪽을 예측한다는 뜻이 아닙니다.";

type View =
  | { kind: "idle" } | { kind: "pending" }
  | { kind: "fail"; status: number; error: string; again: () => void }
  | { kind: "done"; value: RegimeDayTypesAnswer };
type Listed = { models: DayTypeSummary[] | null; note: string | null };

function useMyModels(): Listed & { reload: () => void } {
  const [state, setState] = useState<Listed>({ models: null, note: null });
  const alive = useRef(true);
  const reload = useCallback(() => {
    void listDayTypes().then((r) => {
      if (!alive.current) return;
      if (!r.ok) return setState({ models: null, note: r.error });
      if (!r.value.available) return setState({ models: null, note: r.value.reason });
      setState({ models: r.value.models, note: r.value.hidden_synthetic ? r.value.hidden_reason : null });
    });
  }, []);
  useEffect(() => {
    alive.current = true;
    reload();
    return () => { alive.current = false; };
  }, [reload]);
  return { ...state, reload };
}

export function RegimeDayTypesPart({ trialKey, index, k, model, setModel }: {
  trialKey: string; index: MarketIndex; k: string; model: string; setModel: (key: string) => void;
}) {
  const { models, note, reload } = useMyModels();
  const [view, setView] = useState<View>({ kind: "idle" });
  const problems = [...(k ? [] : ["국면 수를 고르십시오."]), ...(model ? [] : ["하루 유형 모형을 고르십시오."])];
  const known = models?.find((m) => m.key === model) ?? null;

  const run = async () => {
    if (!k || !model) return;
    setView({ kind: "pending" });
    const r = await getRegimeDayTypes(trialKey, { index, k: Number(k), model });
    setView(r.ok ? { kind: "done", value: r.value } : { kind: "fail", status: r.status, error: r.error, again: () => void run() });
  };

  return (
    <Section title="하루 유형 비율" sub={SUB} level={3}>
      <div className="itd-rdt">
        <div className="itd-rdt-form">
          {/* 칸 하나 — 모형 이름(열쇠 · 학습 기간 · 유형 수 · 분 수)이 다 보이게 넓게(`.tj-fields` 의 180px 칸이면 잘린다) */}
          <div className="tj-fields itd-rdt-fields">
            <label className="tj-field"><span className="tj-label">하루 유형 모형<i className="tj-req">필수</i></span>
              <select className="tj-input itd-rdt-model" value={model} onFocus={reload}
                      onChange={(e) => { setModel(e.target.value); setView({ kind: "idle" }); }}>
                <option value="">고르십시오</option>
                {/* 고른 열쇠가 다시 읽은 목록에 없을 수 있다 — 지우지 않고 앞 여덟 자리로 남긴다(판정은 서버가 한다). */}
                {model && !known ? <option value={model}>{model.slice(0, 8)}</option> : null}
                {(models ?? []).map((m) => <option key={m.key} value={m.key}>{modelLabel(m)}</option>)}
              </select>
            </label>
          </div>
          {note ? <p className="itd-why itd-rdt-list-note" role="status"><span data-server>{note}</span></p> : null}
          {models !== null && models.length === 0 ? <p className="itd-why itd-rdt-no-models" role="status">{NO_MODELS}</p> : null}
          <div className="tj-run-row">
            <button type="button" className="tx-btn tx-btn--main itd-rdt-run" disabled={problems.length > 0 || view.kind === "pending"}
                    onClick={() => void run()}>
              {view.kind === "pending" ? "세는 중" : "하루 유형 비율 보기"}
            </button>
            {problems.length ? <ul className="tj-map-miss itd-rdt-problems">{problems.map((p) => <li key={p}>{p}</li>)}</ul> : null}
          </div>
        </div>
        {view.kind === "fail" ? <RegimeRequestFailure status={view.status} error={view.error} again={view.again} /> : null}
        {view.kind === "done" ? <RegimeDayTypesTable a={view.value} /> : null}
      </div>
    </Section>
  );
}
