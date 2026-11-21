/**
 * 분봉 화면의 판 배치 — 판 여섯 · 처음 배치 셋 (G6 2a-1 · 설계 §4.1 · §5.4)
 * ==========================================================================
 * 판은 큰 단위다 — 숫자와 그 단서(출처 등급 · 체결 가정에서 센 것 · 분봉만으로는 알 수 없는 것)가 한 판 안에 있다. 봉과 체결만 따로 판이 되는 까닭:
 * 자기 출처 · 정합 줄 · 사실 줄을 지닌다(G4). 설정 · 결과는 닫지 않는다(실행 단추 · 결과의 자리).
 * 최소 폭(판이 깨지지 않는 바닥): 설정 440 · 결과 640 은 G5 의 잰 값. 나머지 넷은 G5 와 같은 방법으로 잰 값(2026-11-20 · 1920 × 1080 · 계획 §9.2a ·
 * HISTORY) — 판을 셋째 열에 혼자 두고 그 열을 16px 씩 줄여, 정해진 스크롤 틀(봉 차트 · 표의 넘김 상자 · 국면 표) 밖에서 판 상자를 넘는 요소가 생기거나
 * 판 자체가 가로로 구르기 시작하는 폭 + 16. 판 내용은 가장 넓은 상태(실행 뒤 차트 · 판정 뒤 · 학습 뒤 · 국면 보기 뒤)로 잰다.
 * 새 열 폭(colNew 480 — 설계 값 · 잰 값 아님): 처음 배치의 고정 열 폭과 같다. 잰 최소 폭(144 ~ 272)으로 새 열을 열면 좁아 바로 넓혀야 해서 둘을 갈랐다.
 * '차트 위'의 아래 칸 0.4(잰 값 · 2026-11-20 · 계획 §9.2a): 1920 × 1080 에서 아래 칸에 결과 머리 카드(185px)가 다 들어가는 가장 작은 5% 걸음이고 2560 × 1440 에서
 * 위 칸에 차트 틀(300px)이 다 보이는 가장 큰 걸음이다. 처음 계획의 0.5 는 1920 × 1080 의 위 칸에 차트를 64px 만 보였다(절 머리 · 고르기 · 정합 줄 · 범례가 212px).
 * 1920 × 1080 에서도 0.4 의 위 칸은 차트 틀 300px 가운데 128px 만 보인다 — 칸 구분선이나 '이 칸만 크게'로 넓힌다(시험 · HISTORY 의 잰 값).
 * titled: 판 안 첫 절이 판 이름을 제목으로 다는 판(봉과 체결 · 판정 · 하루 유형 · 시장 국면 — 판정은 실행 결과가 있을 때) — 같은 이름의 제목이 둘 서지 않는다.
 * 처음 배치의 이름은 쓰임의 묘사이고 도구가 고르거나 권하지 않는다. 처음 켤 때는 '두 열'(G5 두 칸과 같은 자리).
 */
import type { Layout, ScreenSpec } from "@/shared/ui/workspace/layout";

const L = (cols: Layout["cols"], closed: string[] = []): Layout => ({ v: 1, screen: "intraday", cols, closed });

export const INTRADAY_WS: ScreenSpec = {
  screen: "intraday",
  panels: [
    { id: "setup", name: "설정", min: 440, closable: false },
    { id: "result", name: "결과", min: 640, closable: false },
    { id: "bars", name: "봉과 체결", min: 240, closable: true, titled: true },        // 잰 값 — 224 에서 차트의 '보이는 구간' 줄이 3px 넘친다(봉은 제 스크롤 틀 안)
    { id: "verdict", name: "판정", min: 144, closable: true, titled: true },          // 잰 값 — 128 에서 판이 가로로 14px 구른다(표는 넘김 상자 안)
    { id: "daytype", name: "하루 유형", min: 256, closable: true, titled: true },     // 잰 값 — 240 에서 모형 사실 줄(학습 기간 · 종목 …)이 6px 넘친다
    { id: "regime", name: "시장 국면", min: 272, closable: true, titled: true },      // 잰 값 — 256 에서 사실 줄(BIC · 일치도 · 전환 · 적합)이 10px 넘친다
  ],
  presets: [
    { id: "two", name: "두 열", layout: L([
      { w: 480, rows: [{ tabs: ["setup"], active: "setup" }] },
      { w: null, rows: [{ tabs: ["result", "bars", "verdict", "daytype", "regime"], active: "result" }] },
    ]) },
    { id: "three", name: "세 열", layout: L([
      { w: 480, rows: [{ tabs: ["setup"], active: "setup" }] },
      { w: null, rows: [{ tabs: ["result", "verdict"], active: "result" }] },
      { w: 480, rows: [{ tabs: ["bars", "daytype", "regime"], active: "bars" }] },
    ]) },
    { id: "chart", name: "차트 위", layout: L([
      { w: 480, rows: [{ tabs: ["setup"], active: "setup" }] },
      { w: null, rows: [{ tabs: ["bars"], active: "bars" }, { tabs: ["result", "verdict", "daytype", "regime"], active: "result", h: 0.4 }] },
    ]) },
  ],
  first: "two",
  colNew: 480,
};
