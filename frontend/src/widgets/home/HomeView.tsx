"use client";
/**
 * BU1 · 홈 — 답 한 문장 + 근거 칩 (계획 "BU1 상세" · ADR-003)
 * ==========================================================================
 * ★답 문장은 서버 값으로만 만든다(ADR-003 §2.6)★ 문장은 서버 `recommended_mode` 를 한국어로 옮긴 것이고,
 * 모르는 값이면 판단 없이 잰 값(스트레스)만 말한다. 화면이 임계값으로 새 판단을 만들지 않는다.
 * ★연습용 표시는 서버 게이트로만★ `GET /macro/connection-status` 의 `mock_allowed`(= mock_gate)·`bok_configured`.
 * ★실패·빈·모름을 섞지 않는다★ 실패는 alert + 다시 시도, 빈 결과는 할 일 하나, 모름은 "몰라요" + 사유.
 *
 * 답 문장 부품(`MacroAnswer`)은 첫 화면(BU8a)도 쓰므로 따로 뺐다 — 번역표·칩 규칙은 그 파일 머리에.
 */
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { macroApi } from "@/entities/macro/api";
import { screenerApiAdvanced } from "@/entities/screener/api/ast";
import { API_BASE } from "@/shared/api/apiBase";
import { num, priceWon } from "@/shared/lib/krFormat";
import { LoadingState } from "@/shared/ui/States";
import { Chips, ListRow, Notice, PageHead, Section, Unknown, type Chip } from "@/shared/ui/tx";
import { MacroAnswer } from "./MacroAnswer";

/** 하는 일 순서 — 포트폴리오 설계가 제품의 중심(BK·BL)이라 맨 위. 설명은 하는 일 한 줄(수를 세지 않는다 — 세면 낡는다). */
const TODO = [
  { label: "포트폴리오 설계", href: "/allocation", sub: "종목·비중·점검을 한 화면에서 이어 설계해요" },
  { label: "종목 찾기", href: "/screener", sub: "조건을 걸어 종목을 골라요" },
  { label: "백테스트", href: "/backtest", sub: "전략을 지난 데이터로 돌려 봐요" },
  { label: "매크로 분석", href: "/macro", sub: "경기와 물가가 어느 쪽으로 가는지 봐요" },
  { label: "기업 분석", href: "/insights", sub: "한 종목의 가치와 재무를 자세히 봐요" },
  { label: "위험 점검", href: "/risk-tools", sub: "충격이 오면 얼마나 잃을지 재 봐요" },
];

/** 홈 점수 표의 요청 — 바꾸면 화면 설명(아래 절 sub)도 같이 바꾼다. */
const PICKS_REQ = {
  universe: "kospi200",
  filter_ast: { logic: "AND" as const, conditions: [{ kind: "field" as const, field: "per", op: "gt" as const, value: 0 }], groups: [] },
  sort_by: "composite_score", ascending: false, limit: 8, liquidity_floor: "relaxed" as const,
};

type SnapStatus = { persist_enabled: boolean; db_rows: number };

function Retry({ onClick }: { onClick: () => void }) {
  return <button type="button" className="tx-btn tx-btn--sub home-retry" onClick={onClick}>다시 시도</button>;
}

function Picks() {
  const q = useQuery({ queryKey: ["home", "picks"], queryFn: () => screenerApiAdvanced.runAdvanced(PICKS_REQ) });
  const cs = useQuery({ queryKey: ["macro", "connection-status"], queryFn: () => macroApi.connectionStatus() });
  const items = q.data?.items.slice(0, 5) ?? [];
  const chips: Chip[] = [];
  if (cs.data?.mock_allowed) chips.push({ label: "연습용 시세", tone: "practice" });
  const ing = q.data?.ingested_count, size = q.data?.universe_size;
  if (typeof ing === "number" && typeof size === "number") chips.push({ label: `재무 적재 ${num(ing)}/${num(size)}`, tone: "plain" });

  return (
    <div className="home-picks">
      <Section title="점수 높은 종목" sub="코스피 200 중 PER 이 양수인 종목을 종합점수 순으로" aside={<Chips items={chips} label="이 목록의 근거" />}>
        {q.isLoading ? <LoadingState label="종목 점수를 불러오는 중이에요" />
          : q.isError ? (
            <Notice tone="danger" title="종목 점수를 불러오지 못했어요">
              스크리너 계산에 닿지 못했어요.
              <div className="home-act"><Retry onClick={() => { void q.refetch(); }} /></div>
            </Notice>
          ) : items.length === 0 ? (
            <div className="home-empty">
              <p>점수를 낼 종목이 아직 없어요. 데이터가 적재됐는지 먼저 확인해 주세요.</p>
              <Link href="/admin/data" className="tx-btn tx-btn--sub">데이터 상태 보기</Link>
            </div>
          ) : (
            <>
              {items.map((it) => (
                <ListRow key={it.stock_code} href={`/insights?code=${it.stock_code}`}
                         title={it.corp_name}
                         sub={<><span className="home-code">{it.stock_code}</span>{it.verdict ? <> · {it.verdict}</> : null}</>}
                         right={<span className="home-pick-r"><span>{priceWon(it.current_price)}</span>
                           <span className="home-score">종합 {num(it.composite_score, 1)}</span></span>} />
              ))}
              {/* BU2 다리 — 보이는 그 종목 그대로 캔버스 종목 고르기 노드로(캔버스가 stock_master 로 다시 확인한다) */}
              <div className="home-act">
                <Link href={`/allocation?tickers=${items.map((it) => it.stock_code).join(",")}`} className="tx-btn tx-btn--sub home-bridge">
                  이 {items.length}종목 설계에 넣기
                </Link>
              </div>
            </>
          )}
      </Section>
    </div>
  );
}

function DataRow() {
  const q = useQuery({
    queryKey: ["screener", "snapshot-status"],
    queryFn: async (): Promise<SnapStatus> => {
      const r = await fetch(`${API_BASE}/api/v1/screener/snapshot-status`);
      if (!r.ok) throw new Error(`snapshot-status ${r.status}`);
      return r.json();
    },
  });
  const right = q.isLoading ? "…" : q.isError || !q.data ? <Unknown reason="적재 현황을 불러오지 못했어요" /> : `${num(q.data.db_rows)}행`;
  const sub = q.data && !q.data.persist_enabled ? "종목 스냅샷 · 영속 저장이 꺼져 있어요" : "종목 스냅샷(재무 + 가격)";
  return (
    <div className="home-data">
      <Section title="데이터">
        <ListRow className="dash-mod-stat" href="/admin/data" title="적재된 종목 스냅샷" sub={sub} right={right} />
      </Section>
    </div>
  );
}

export function HomeView() {
  return (
    <div className="tx-page home">
      <PageHead title="홈" lede="시장 흐름을 보고, 오늘 할 일을 골라요." />
      <MacroAnswer className="home-macro" action={<Link href="/macro" className="tx-btn tx-btn--main">매크로 분석 보기</Link>} />
      <div className="home-grid">
        <div className="home-todo">
          <Section title="무엇을 할까요">
            {TODO.map((m) => <ListRow key={m.href} className="dash-mod" href={m.href} title={m.label} sub={m.sub} />)}
          </Section>
        </div>
        <Picks />
      </div>
      <DataRow />
    </div>
  );
}
