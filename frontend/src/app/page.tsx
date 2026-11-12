/**
 * 첫 화면(/) — BU8a (계획 "BU8 상세" · ADR-003). 셸 밖 브랜드 페이지, 서버 컴포넌트 + 움직이는 섬.
 * ==========================================================================
 * 사용자 결정: 히어로 = 서버가 지금 내는 답 한 문장 · 노란 연습용 띠는 영구 제거 · 남기는 띠는 히어로 · 스튜디오 · 리서치 경로뿐 ·
 * ★포트폴리오 설계 스튜디오(캔버스)가 메인 도구라는 것을 설명하는 페이지★ · 모션·그래픽 대폭 강화(핀트·솔루션퀀트 같은 제품 랜딩) ·
 * 개정 2: "더 다양하게 꾸미고, 히어로의 글·그림·바탕·움직임을 더 다듬어 줘".
 *
 *  ① 히어로 — 한 문장 + 단추 둘 + 근거 짚기 + 서버가 지금 내는 답(홈과 같은 `MacroAnswer`) + 아래로 걸친 스튜디오 기본 흐름 그림
 *     (`HeroCanvas` — 노드 이름·선·관문은 서버 카탈로그 그대로, 숫자 없음). 바탕은 캔버스 점 무늬 + 포인터를 따라 밝아지는 점(`HeroFx`).
 *  ② 스튜디오 둘러보기 — 실제 스튜디오 캡처 위에서 네 단계를 비추며 다가간다(`StudioTour`).
 *  ③ 도구 허브(어두운 띠) — 다섯 도구가 실제 캔버스 노드 이름과 함께 스튜디오로 이어진다(`ToolHub`).
 *  ④ 리서치 경로 — 참인 순서 1~7, 선이 그려지며 차례로 나타난다. 저장소 용어는 닫힌 자세히 안에만. 끝은 파란 마무리 카드.
 * 모션은 전부 transform·opacity·선 그리기 · 스크롤 이벤트를 듣지 않는다(IntersectionObserver) · 감속 모션이면 처음부터 다 보인 채로 멈춰 있다.
 */

import Link from "next/link";
import { MacroAnswer } from "@/widgets/home/MacroAnswer";
import { EvidencePointer, HeroCanvas, HeroFx, InView, StudioTour, ToolHub } from "@/widgets/landing";

/**
 * 리서치 경로(스펙 v2.1 §5 의 근거 경로) — 실제로 순서가 있는 일이라 번호를 쓴다.
 * `rec` 은 그 단계가 다음 단계로 넘기는 **신원**이다(값이 아니다). 저장소 용어라 닫힌 자세히 안에만 보인다.
 */
const PATH: { t: string; d: string; href?: string; rec: string }[] = [
  { t: "현재 국면 판정", d: "경기·물가 국면의 방향을 판정합니다", href: "/macro", rec: "판정한 시각" },
  { t: "판정 스냅샷 저장", d: "당시의 판정을 기록으로 저장합니다", rec: "snapshot_id" },
  { t: "설계에서 참조", d: "값을 복사하지 않고 저장한 기록을 참조합니다", href: "/allocation?from=macro", rec: "값 대신 snapshot_id 를 참조합니다" },
  { t: "타이밍 규칙", d: "비중 확대·축소 시점을 규칙으로 정합니다", href: "/allocation?from=timing", rec: "name@version" },
  { t: "스트레스 테스트", d: "사전 정의한 충격 시나리오를 적용합니다", href: "/allocation?from=stress", rec: "pack_id@해시" },
  { t: "포트폴리오 최적화·백테스트", d: "비중을 산출하고 과거 데이터로 시뮬레이션합니다", href: "/allocation?from=optimize", rec: "run_id" },
  { t: "결정 기록", d: "결정 근거를 기록하고 사후 검토합니다", href: "/allocation?from=journal", rec: "결정 → run_id → snapshot_id 사슬" },
];

function Brand() {
  return (
    <span className="ld-brand">
      <span className="ld-logo" aria-hidden>
        <svg viewBox="0 0 24 24"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" /></svg>
      </span>
      Project Alpha
    </span>
  );
}

export default function Landing() {
  return (
    <div className="ld">
      <header className="ld-head">
        <div className="ld-wrap ld-head-in">
          <Brand />
          <Link href="/login" className="ld-login">로그인</Link>
        </div>
      </header>

      <main>
        {/* ① 히어로 — 처음 열 때 한 번 차례로 떠오른다(제목 낱말 → 설명 → 단추 → 근거 짚기 → 답 카드 → 아래 스튜디오 그림이 그려진다). */}
        <section className="ld-hero" aria-labelledby="ld-h1">
          <HeroFx />
          <div className="ld-wrap">
            <div className="ld-hero-in">
              <div className="ld-hero-copy">
                <h1 id="ld-h1">
                  <span className="ld-line"><span style={{ ["--i" as string]: 0 }}>근거가</span> <span style={{ ["--i" as string]: 1 }}>보이는</span></span>
                  <span className="ld-line"><span style={{ ["--i" as string]: 2 }}>포트폴리오</span> <span style={{ ["--i" as string]: 3 }}>설계</span></span>
                </h1>
                <p className="ld-lede ld-rise" style={{ ["--i" as string]: 3 }}>
                  유니버스부터 위험 점검까지 노드를 연결해 하나의 설계로 구성합니다. 수치마다 출처와 미측정 항목을 함께 표시합니다.
                </p>
                <div className="ld-hero-cta ld-rise" style={{ ["--i" as string]: 4 }}>
                  <Link href="/allocation" className="tx-btn tx-btn--main ld-btn">포트폴리오 설계 시작</Link>
                  <Link href="/dashboard" className="tx-btn tx-btn--sub ld-btn">홈으로</Link>
                </div>
                <EvidencePointer className="ld-rise" style={{ ["--i" as string]: 5 }} />
              </div>
              <div className="ld-live-wrap">
                <div className="ld-live ld-rise" style={{ ["--i" as string]: 5 }}>
                  <p className="ld-live-k"><span className="ld-live-dot" aria-hidden />서버 실시간 응답</p>
                  <MacroAnswer className="ld-live-a" action={<Link href="/macro" className="tx-btn tx-btn--sub">매크로 분석 보기</Link>} />
                  <p className="ld-live-note">홈·매크로 분석과 동일한 계산입니다. 화면을 열 때마다 서버에서 다시 조회합니다.</p>
                </div>
              </div>
            </div>
            <HeroCanvas />
          </div>
        </section>

        {/* ② 스튜디오 둘러보기 — 메인 도구를 실제 화면으로 설명한다. */}
        <section className="ld-band ld-studio" aria-labelledby="ld-studio-h">
          <div className="ld-wrap">
            <InView className="ld-hg">
              <h2 id="ld-studio-h" className="ld-h2">포트폴리오 설계 스튜디오</h2>
              <p className="ld-sub">종목부터 점검까지 노드를 연결해 하나의 설계를 구성합니다. 네 단계를 실제 화면으로 안내합니다.</p>
            </InView>
            <StudioTour />
          </div>
        </section>

        {/* ③ 도구 허브 — 어두운 띠. 다섯 도구가 스튜디오로 이어진다(실제 캔버스 노드 이름과 함께). */}
        <section className="ld-band ld-band--ink" aria-labelledby="ld-hub-h">
          <div className="ld-wrap">
            <InView className="ld-hg">
              <h2 id="ld-hub-h" className="ld-h2">모든 도구가 스튜디오로 연결됩니다</h2>
              <p className="ld-sub">다섯 도구는 단독으로도 사용할 수 있고, 스튜디오에서는 노드 하나로 연결됩니다.</p>
            </InView>
            <ToolHub />
          </div>
        </section>

        {/* ④ 리서치 경로 — 참인 순서(1~7). 화면에 들어오면 선이 그려지며 단계가 차례로 나타난다. */}
        <section className="ld-band ld-path" aria-labelledby="ld-path-h">
          <div className="ld-wrap">
            <InView className="ld-hg">
              <h2 id="ld-path-h" className="ld-h2">리서치 진행 순서</h2>
              <p className="ld-sub">앞 단계는 값을 복사하지 않고 기록 번호(ID)만 전달합니다. 따라서 이후에 열어도 당시의 근거를 참조합니다.</p>
            </InView>
            <InView as="ol" className="ld-steps">
              {PATH.map((s, i) => {
                const inner = (
                  <>
                    <span className="ld-step-n">{i + 1}</span>
                    <span className="ld-step-t">{s.t}</span>
                    <span className="ld-step-d">{s.d}</span>
                  </>
                );
                return (
                  <li key={s.t} className="ld-step" style={{ ["--i" as string]: i }}>
                    {s.href ? <Link href={s.href} className="ld-step-a">{inner}</Link> : <div className="ld-step-a">{inner}</div>}
                  </li>
                );
              })}
            </InView>
            <p className="ld-note">매크로 판단은 타이밍 규칙을 대체하지 않습니다. 단방향 오버레이로만 적용되어, 끄면 결과가 원래대로 복원됩니다.</p>
            <details className="ld-rec">
              <summary>단계별 기록 보기</summary>
              <dl className="ld-rec-list">
                {PATH.map((s) => (
                  <div key={s.t} className="ld-rec-row"><dt>{s.t}</dt><dd><code>{s.rec}</code></dd></div>
                ))}
              </dl>
            </details>
            {/* 마무리 카드 — 같은 주 단추(같은 이름 · 같은 곳). 오른쪽 작은 흐름 그림은 장식이다(aria-hidden). */}
            <InView className="ld-end">
              <div className="ld-end-copy">
                <h3 className="ld-end-t">종목 하나부터 설계를 시작하십시오</h3>
                <p className="ld-end-d">노드를 배치하면 절차 탭이 다음 단계 노드를 제안합니다. 수치마다 근거가 함께 기록됩니다.</p>
                <Link href="/allocation" className="tx-btn tx-btn--main ld-btn">포트폴리오 설계 시작</Link>
              </div>
              <svg className="ld-end-art" viewBox="0 0 260 140" aria-hidden>
                <path className="ld-end-w" d="M 52 40 C 100 40, 100 92, 148 92" pathLength={1} />
                <path className="ld-end-w" d="M 52 104 C 100 104, 100 92, 148 92" pathLength={1} />
                <path className="ld-end-w" d="M 172 92 C 196 92, 196 70, 220 70" pathLength={1} />
                <path className="ld-end-p" d="M 52 40 C 100 40, 100 92, 148 92" pathLength={1} />
                <path className="ld-end-p" d="M 52 104 C 100 104, 100 92, 148 92" pathLength={1} style={{ animationDelay: "1.1s" }} />
                <path className="ld-end-p" d="M 172 92 C 196 92, 196 70, 220 70" pathLength={1} style={{ animationDelay: "0.6s" }} />
                <rect className="ld-end-n" x="14" y="26" width="38" height="28" rx="9" />
                <rect className="ld-end-n" x="14" y="90" width="38" height="28" rx="9" />
                <rect className="ld-end-n ld-end-n--core" x="148" y="76" width="24" height="32" rx="9" />
                <rect className="ld-end-n" x="220" y="56" width="30" height="28" rx="9" />
              </svg>
            </InView>
          </div>
        </section>
      </main>
    </div>
  );
}
