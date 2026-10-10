/**
 * 첫 화면 히어로 그림 · 스튜디오 기본 흐름 (BU8a 개정 2 — 사용자: "히어로의 이미지·배경·모션·그래픽·애니메이션을 더 다듬어줘")
 * ==========================================================================
 * ★지어낸 그림이 아니다★ 노드 이름은 서버 노드 카탈로그의 쉬운 이름(`plain_label`), 선은 실제로 이어지는 포트끼리다
 * (보내는 노드의 출력 타입 = 받는 노드의 입력 타입). 관문 이름·순서는 서버 관문 목록(`gates`) 그대로다.
 * e2e/landing.spec 이 `GET /api/v1/allocation/graph/node-types` 와 대조한다 — 카탈로그가 바뀌면 여기도 바꾼다.
 * ★숫자를 그리지 않는다★ 성과처럼 보이는 값이 없다. 선 색은 스튜디오와 같은 포트 타입 색이다.
 *
 * 움직임은 CSS 만(globals BU8a 절): 창이 떠오르고 → 노드가 열마다 놓이고 → 선이 그려지고 → 값이 흐르고 → 관문이 차례로 켜진다.
 * 감속 모션이면 처음부터 다 그려 둔 채 멈춘다. 좁은 화면에서는 창이 넓은 그림의 한 부분만 보여 주고 천천히 옆으로 훑는다.
 * 서버 컴포넌트다(훅 없음) — 좌표와 선 경로는 모듈을 읽을 때 한 번 계산한다.
 */
import { Workflow } from "lucide-react";

type Stage = "data" | "belief" | "build" | "check";
const STAGE_KO: Record<Stage, string> = { data: "데이터", belief: "생각 정하기", build: "비중 정하기", check: "확인하기" };
type HeroNode = { id: string; label: string; stage: Stage; x: number; y: number; col: number; ins: string[]; outs: string[] };

const NW = 168;
const NH = 66;
/** 스튜디오 기본 흐름 — 종목·내 생각 → 수익률 → 비중 계산 → 확인하기 셋. 이름은 카탈로그 `plain_label`. */
export const HERO_NODES: HeroNode[] = [
  { id: "views", label: "내 생각 넣기", stage: "belief", x: 40, y: 46, col: 0, ins: [], outs: ["Views"] },
  { id: "universe", label: "종목 고르기", stage: "data", x: 40, y: 170, col: 0, ins: [], outs: ["Universe"] },
  { id: "returns", label: "수익률 불러오기", stage: "data", x: 330, y: 170, col: 1, ins: ["Universe"], outs: ["Returns"] },
  { id: "optimizer", label: "비중 계산", stage: "build", x: 620, y: 108, col: 2, ins: ["Views", "Returns"], outs: ["Weights"] },
  { id: "risk", label: "흔들림 나눠 보기", stage: "check", x: 900, y: 24, col: 3, ins: ["Weights"], outs: ["RiskReport"] },
  { id: "scenario_stress", label: "상황에 넣어 보기", stage: "check", x: 900, y: 117, col: 3, ins: ["Weights"], outs: ["StressReport"] },
  { id: "backtest", label: "과거로 돌려 보기", stage: "check", x: 900, y: 210, col: 3, ins: ["Weights", "Returns"], outs: ["BacktestResult"] },
];
/** [보내는 노드, 받는 노드, 포트 타입] — 타입은 보내는 쪽 출력과 받는 쪽 입력에 실제로 있다. */
export const HERO_WIRES: [string, string, string][] = [
  ["universe", "returns", "Universe"],
  ["views", "optimizer", "Views"],
  ["returns", "optimizer", "Returns"],
  ["optimizer", "risk", "Weights"],
  ["optimizer", "scenario_stress", "Weights"],
  ["optimizer", "backtest", "Weights"],
  ["returns", "backtest", "Returns"],
];
/** 서버 관문 목록(`workflow_gates` · 카탈로그 `gates`)과 같은 키·이름·순서. */
export const HERO_GATES: { key: string; label: string }[] = [
  { key: "data", label: "데이터" }, { key: "pit", label: "시점" }, { key: "signal", label: "신호" }, { key: "build", label: "비중 계산" },
  { key: "cost", label: "거래비용" }, { key: "oos", label: "처음 보는 기간" }, { key: "economic", label: "돈이 되는지" }, { key: "live", label: "모의·실계좌" },
];

const byId = new Map(HERO_NODES.map((n) => [n.id, n]));
const portY = (n: HeroNode, side: "ins" | "outs", type: string) => n.y + (NH * (n[side].indexOf(type) + 1)) / (n[side].length + 1);
const WIRES = HERO_WIRES.map(([from, to, t]) => {
  const a = byId.get(from)!;
  const b = byId.get(to)!;
  const sx = a.x + NW, sy = portY(a, "outs", t), ex = b.x, ey = portY(b, "ins", t);
  const dx = Math.max(36, (ex - sx) / 2);
  return { from, to, t, col: a.col, d: `M ${sx} ${sy} C ${sx + dx} ${sy}, ${ex - dx} ${ey}, ${ex} ${ey}` };
});

const SUMMARY =
  "포트폴리오 설계 스튜디오의 기본 흐름을 줄여 그린 그림이에요. 종목 고르기와 내 생각 넣기에서 시작해 수익률 불러오기와 비중 계산을 거쳐 " +
  "흔들림 나눠 보기, 상황에 넣어 보기, 과거로 돌려 보기로 값이 흘러요. 계산하면 데이터부터 모의·실계좌까지 관문 여덟 곳을 차례로 확인해요.";

export function HeroCanvas() {
  return (
    <figure className="ld-cv-fig">
      <div className="ld-cvp">
        <div className="ld-cv">
          <div className="ld-cv-head">
            <span className="ld-cv-title"><span className="ld-cv-ic" aria-hidden><Workflow size={15} strokeWidth={2} /></span>포트폴리오 설계</span>
            <ol className="ld-cv-gates" aria-label="계산하면 차례로 확인하는 관문">
              {HERO_GATES.map((g, i) => (
                <li key={g.key} className="ld-cv-gate" data-gate={g.key} data-label={g.label} style={{ ["--i" as string]: i }}>
                  <i aria-hidden />{g.label}
                </li>
              ))}
            </ol>
          </div>
          <div className="ld-cv-view">
            <svg className="ld-cv-svg" viewBox="0 0 1100 300" role="img" aria-label={SUMMARY}>
              <g className="ld-cv-wires">
                {WIRES.map((w, i) => (
                  <g key={`${w.from}-${w.to}-${w.t}`} style={{ ["--col" as string]: w.col, ["--i" as string]: i }}>
                    <path className="ld-cv-wire" d={w.d} pathLength={1} data-from={w.from} data-to={w.to} data-t={w.t} />
                    <path className="ld-cv-pkt" d={w.d} pathLength={1} data-t={w.t} />
                  </g>
                ))}
              </g>
              {HERO_NODES.map((n, i) => (
                <g key={n.id} transform={`translate(${n.x} ${n.y})`}>
                  <g className="ld-cv-node" data-node={n.id} data-stage={n.stage} style={{ ["--col" as string]: n.col, ["--i" as string]: i }}>
                    <rect className="ld-cv-card" width={NW} height={NH} rx={14} />
                    <circle className="ld-cv-st" cx={20} cy={22} r={4.5} />
                    <text className="ld-cv-k" x={31} y={26}>{STAGE_KO[n.stage]}</text>
                    <text className="ld-cv-t" x={16} y={50}>{n.label}</text>
                    {n.ins.map((t) => <circle key={`i-${t}`} className="ld-cv-port" data-t={t} cx={0} cy={portY(n, "ins", t) - n.y} r={5.5} />)}
                    {n.outs.map((t) => <circle key={`o-${t}`} className="ld-cv-port" data-t={t} cx={NW} cy={portY(n, "outs", t) - n.y} r={5.5} />)}
                  </g>
                </g>
              ))}
            </svg>
          </div>
        </div>
      </div>
      <figcaption className="ld-cv-cap">스튜디오의 기본 흐름을 줄여 그렸어요. 노드 이름과 관문은 스튜디오에 있는 그대로예요.</figcaption>
    </figure>
  );
}
