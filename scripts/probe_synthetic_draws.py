"""누가 난수를 뽑는가 — GET 라우트를 훑으며 ★난수 진입점이 `src/` 에서 불린 자리★를 기록한다.

    KIS_USE_MOCK=0 DATABASE_URL=sqlite:////tmp/x.db python scripts/probe_synthetic_draws.py [--json]

- 환경은 호출자가 정한다(`KIS_USE_MOCK` · `DATABASE_URL` · 키). 이 도구는 프록시 변수만 지우고 외부 연결을 막는다.
- 훑는 것: 인자 없는 GET 전부 + 종목 코드 하나만 받는 GET(`005930` 으로 채움).
- 기록: 난수를 뽑은 순간의 호출 사슬에 있던 `src/` 함수마다 횟수와 그때의 경로. 키는 등록부(`src/data/synthetic_registry.py`)와 같은 모양이다.
- 읽는 법: 운영 게이트(`KIS_USE_MOCK` ≠ 1)에서 등록부의 `synthetic`·`primitive` 자리가 하나라도 나오면 ★지어낸 값이 나간 것★이다.
  `simulation` 자리(몬테카를로 등)는 나와도 된다. mock 게이트에서는 `synthetic` 자리가 나와야 정상이다(덫이 살아 있다는 증거).
- ★못 보는 것★: POST 등 사용자가 실행하는 분석 · 인자가 더 필요한 경로 · 웹소켓 · 이미 만들어 둔 RNG 객체의 재사용 ·
  난수 없이 해시·상수로 만든 값. "0건"은 '이 도구가 훑은 범위'의 관측이지 전체에 대한 증명이 아니다 —
  나머지는 `tests/test_synthetic_registry.py` 가 자리마다 직접 불러서 본다.
- `tests/test_synthetic_registry.py` 가 이 파일을 하위 프로세스로 돌린다(앱 전역 캐시를 pytest 프로세스에 남기지 않으려고).
"""
from __future__ import annotations

import collections
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
#: 경로 인자를 이 이름으로 받는 GET 은 종목 코드로 채워 부른다. 다른 인자가 있는 경로는 건너뛴다(센다).
FILL = {"code": "005930", "ticker": "005930", "stock_code": "005930", "symbol": "005930", "stock": "005930"}


def main(argv: list[str]) -> int:
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "tests"))
    sys.path.insert(0, str(ROOT / "scripts"))
    import probe_external_calls as ext

    from synthetic_scan import drop_proxy_env, install_tripwire

    drop_proxy_env()
    external: collections.Counter = collections.Counter()
    ext.install(lambda host, where: external.update([host]))

    cur = {"route": "(startup)"}
    draws: dict[str, dict] = collections.OrderedDict()

    def record(frames: tuple[str, ...]) -> None:
        for key in frames:
            d = draws.setdefault(key, {"n": 0, "routes": []})
            d["n"] += 1
            if cur["route"] not in d["routes"] and len(d["routes"]) < 5:
                d["routes"].append(cur["route"])

    install_tripwire(record, root=ROOT)

    import logging
    logging.disable(logging.CRITICAL)
    import main_api
    from fastapi.testclient import TestClient

    from route_walk import flat_routes
    from src.data.mock_gate import mock_allowed
    from src.data.synthetic_registry import SITES

    app = main_api.app
    paths, skipped = set(), set()
    for r in flat_routes(app):
        if "GET" not in (getattr(r, "methods", None) or ()):
            continue
        params = re.findall(r"{([^}:]+)(?::[^}]+)?}", r.path)
        if not all(p in FILL for p in params):
            skipped.add(r.path)
            continue
        path = r.path
        for p in params:
            path = re.sub(r"{" + p + r"(?::[^}]+)?}", FILL[p], path)
        paths.add(path)

    t0 = time.time()
    status: collections.Counter = collections.Counter()
    errors: list[str] = []
    with TestClient(app) as c:
        for p in sorted(paths):
            cur["route"] = p
            try:
                status[str(c.get(p).status_code // 100) + "xx"] += 1
            except Exception as e:  # noqa: BLE001 — 경로 하나의 예외가 재기를 멈추지 않는다
                errors.append(f"{p}: {type(e).__name__}")
    out = {
        "mock": os.getenv("KIS_USE_MOCK"), "mock_allowed": mock_allowed(), "routes_called": len(paths),
        "routes_skipped": len(skipped), "status": dict(status), "route_errors": errors, "seconds": round(time.time() - t0, 1),
        "draws": [{"site": k, "kind": SITES[k].kind if k in SITES else None, **v} for k, v in draws.items()],
        "external_attempts": dict(external),
    }
    if "--json" in argv:
        print("PROBE_JSON " + json.dumps(out, ensure_ascii=False))
        return 0
    print(f"KIS_USE_MOCK={out['mock']} (mock_allowed={out['mock_allowed']}) · GET {len(paths)}개(건너뜀 {len(skipped)}) · "
          f"{out['seconds']}s · 상태 {out['status']} · 경로 예외 {len(errors)}")
    for d in out["draws"]:
        if d["kind"] is not None:      # 등록된 자리만 — 사슬의 나머지 프레임(라우트 함수 등)은 소음이다
            print(f"  {d['n']:7d}  [{d['kind']}]  {d['site']}  ← {', '.join(d['routes'][:2])}")
    bad = [d for d in out["draws"] if d["kind"] in ("synthetic", "primitive")]
    print(f"합성 자리에서 난수를 뽑은 곳 {len(bad)}곳" + (" — ★운영 게이트에서는 0 이어야 한다★" if not out["mock_allowed"] and bad else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
