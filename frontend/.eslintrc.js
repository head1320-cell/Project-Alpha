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

module.exports = {
  root: true,
  extends: ["next/core-web-vitals"],
  rules: {
    "import/no-restricted-paths": ["error", { zones }],

    // 이 저장소는 lint 를 한 번도 돌린 적이 없어 기존 위반이 쌓여 있다.
    // FSD 가드레일을 CI 에 넣는 것이 이번 목적이므로, 무관한 기존 항목은 경고로 남겨
    // 보이게만 하고 차단하지 않는다(12건 JSX 따옴표 · 16건 hook deps).
    // exhaustive-deps 를 기계적으로 "고치면" 동작이 바뀔 수 있어 별도 작업으로 둔다.
    "react/no-unescaped-entities": "warn",
  },
  overrides: [
    {
      // app/ 은 Next 라우팅 계층 — 모든 하위 계층을 조립하는 것이 역할이므로 peer 개념이 없다.
      files: ["src/app/**"],
      rules: { "import/no-restricted-paths": "off" },
    },
  ],
};
