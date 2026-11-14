// ═══════════════════════════════════════════════════════════════════════════════
// ESLint — FSD 의존 규칙을 빌드 타임에 강제.
//
// 계층 순서(위 → 아래): app → widgets → features → entities → shared
//   · 역방향 금지: 아래 계층이 위 계층을 import 할 수 없다.
//   · 동일 계층 슬라이스 간 직접 import 금지(peer): 공통 로직은 shared/entities 로 내린다.
//
// zone 목록은 실제 디렉터리를 읽어 생성한다 — 슬라이스를 추가해도 설정을 고칠 필요가 없다.
// (import/no-restricted-paths 는 eslint-config-next 가 가져오는 eslint-plugin-import 제공.
//  새 의존성 없음.)
//
// ESLint 9 flat config(2026-11-08 · Next 16 — `next lint` 와 `.eslintrc` 가 없어졌다). 규칙·zone 은 예전 `.eslintrc.js` 그대로.
//
// 한계: 이 규칙은 type-only import 를 구분하지 못한다(@typescript-eslint 미설치).
// entity 간 **타입만** 참조하는 두 곳은 런타임 결합이 없어 허용하고, 해당 줄에
// eslint-disable 주석으로 근거를 남겼다. 런타임 peer import 는 전부 막힌다.
// ═══════════════════════════════════════════════════════════════════════════════
const fs = require("fs");
const path = require("path");

const LAYERS = ["app", "widgets", "features", "entities", "shared"]; // 높음 → 낮음
const SLICED = ["widgets", "features", "entities"];

const slicesOf = (layer) => {
  try {
    return fs
      .readdirSync(path.join(__dirname, "src", layer), { withFileTypes: true })
      .filter((d) => d.isDirectory())
      .map((d) => d.name);
  } catch {
    return [];
  }
};

const zones = [];

// 역방향(upward) 금지
LAYERS.forEach((low, i) => {
  LAYERS.slice(0, i).forEach((high) => {
    zones.push({
      target: `./src/${low}`,
      from: `./src/${high}`,
      message: `FSD 위반: ${low} 는 ${high} 를 import 할 수 없습니다 (의존 방향은 위→아래만).`,
    });
  });
});

// 동일 계층 슬라이스 간(peer) 금지 — 자기 슬라이스만 예외
SLICED.forEach((layer) => {
  slicesOf(layer).forEach((slice) => {
    zones.push({
      target: `./src/${layer}/${slice}`,
      from: `./src/${layer}`,
      except: [`./${slice}`],
      message: `FSD 위반: ${layer}/${slice} 가 같은 계층의 다른 슬라이스를 직접 import 했습니다. 공통 로직은 shared 또는 entities 로 내리세요.`,
    });
  });
});

const nextCoreWebVitals = require("eslint-config-next/core-web-vitals");

module.exports = [
  ...nextCoreWebVitals,
  {
    rules: {
      "import/no-restricted-paths": ["error", { zones }],

      // 이 저장소는 lint 를 한 번도 돌린 적이 없어 기존 위반이 쌓여 있다.
      // FSD 가드레일을 CI 에 넣는 것이 이번 목적이므로, 무관한 기존 항목은 경고로 남겨
      // 보이게만 하고 차단하지 않는다(12건 JSX 따옴표 · 16건 hook deps).
      // exhaustive-deps 를 기계적으로 "고치면" 동작이 바뀔 수 있어 별도 작업으로 둔다.
      "react/no-unescaped-entities": "warn",

      // ★Next 16 의 eslint-plugin-react-hooks 7 이 새로 가져온 React Compiler 규칙★ — 올리자마자 기존 코드에서 94건(2026-11-08).
      // 위와 같은 원칙으로 **지금 걸리는 일곱 규칙만** 경고로 둔다(보이게 · 차단 안 함). 기계적으로 고치면 동작이 바뀔 수 있다.
      // 걸리는 것이 없는 나머지 컴파일러 규칙은 오류 그대로 — 새 코드는 막힌다. 이 경고들은 컴파일러가 그 컴포넌트를 건너뛰는 자리다(5c).
      "react-hooks/set-state-in-effect": "warn",
      "react-hooks/refs": "warn",
      "react-hooks/immutability": "warn",
      "react-hooks/static-components": "warn",
      "react-hooks/purity": "warn",
      "react-hooks/preserve-manual-memoization": "warn",
      "react-hooks/use-memo": "warn",

      // ADR 004(2026-11-10): 차트 라이브러리는 ★차트 파일(`charts.tsx` · `*.charts.tsx`)에서만★ import 한다. 경계가 정해져 있어야
      // 늦게 받기(lazyChart) · 버전 올리기 · 교체 때 손댈 곳이 정해진다. 다른 파일은 그 파일이 내보내는 부품을 받는다(아래 예외 블록).
      "no-restricted-imports": ["error", { paths: [{
        name: "recharts",
        message: "recharts 는 차트 파일(charts.tsx · *.charts.tsx)에서만 import 하세요 — ADR 004. 다른 파일은 그 부품을 lazyChart 로 받아요.",
      }] }],

      // React 19(2026-11-08): 함수 컴포넌트가 `ref` 를 prop 으로 받는다 — forwardRef 는 필요 없고 앞으로 폐기된다. 되돌아오지 않게 막는다.
      "no-restricted-syntax": ["error", {
        selector: "CallExpression[callee.name='forwardRef'], CallExpression[callee.property.name='forwardRef']",
        message: "React 19 에서는 forwardRef 대신 `ref` 를 prop 으로 받으세요(function X({ ref, ...props }: React.ComponentProps<...>)).",
      }],
    },
  },
  {
    // 차트 파일 — recharts 를 import 해도 되는 유일한 자리(ADR 004).
    // ★단 `Tooltip` 은 여기서도 못 쓴다★(ADR 004 §6 · 2026-11-10) — 값은 호버가 아니라 늘 보이는 읽는 줄에(`shared/ui/chart/ChartReadout`).
    files: ["src/**/charts.tsx", "src/**/*.charts.tsx"],
    rules: { "no-restricted-imports": ["error", { paths: [{
      name: "recharts", importNames: ["Tooltip"],
      message: "recharts 의 Tooltip 은 쓰지 않아요 — 값은 읽는 줄·표 쌍둥이에(ReadoutFrame · ADR 004 §2.4 · §6).",
    }] }] },
  },
  {
    // app/ 은 Next 라우팅 계층 — 모든 하위 계층을 조립하는 것이 역할이므로 peer 개념이 없다.
    files: ["src/app/**"],
    rules: { "import/no-restricted-paths": "off" },
  },
  // (BL4) AAS 컨텍스트 슬라이스 경계 규칙은 마법사(`src/widgets/allocation/slices`)와 함께 지웠다 — 캔버스 상태는
  // `widgets/portfolio-graph/store` 하나(zustand)라 슬라이스가 없다.
];
