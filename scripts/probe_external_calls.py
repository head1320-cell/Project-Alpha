"""누가 외부로 나가는가 — 기동과 인자 없는 GET 전부를 돌리며 ★비로컬 소켓 연결·이름 풀이★를 기록한다(연결은 거부).

    python scripts/probe_external_calls.py [--idle 2] [--json]

- 환경은 호출자가 정한다(`KIS_USE_MOCK` · `LIFECYCLE_DAEMONS` · `DATABASE_URL`). 이 도구는 값을 바꾸지 않는다 — ★프록시 변수만 지운다★:
  프록시가 로컬 주소이면 모든 외부 호출이 '로컬 연결'로 보여 아무것도 못 본다(2026-11-13 첫 탐침이 그래서 0건이라고 잘못 말했다).
- 잡는 것: `socket.connect` · `socket.getaddrinfo` 의 비로컬 대상(requests · httpx · urllib · yfinance · DB 드라이버 모두 여기를 지난다).
- ★못 보는 것★: 인자가 있는 경로 · POST 등 사용자가 실행하는 분석 · 키가 있어야 도는 데몬 · 이미 열려 있던 연결.
  "0건" 은 '기동 + 인자 없는 GET' 범위의 관측이지 전체에 대한 증명이 아니다.
- `tests/test_mock_no_external_calls.py` 가 이 파일을 하위 프로세스로 돌린다(앱 전역 캐시를 pytest 프로세스에 남기지 않으려고).
"""
from __future__ import annotations

import collections
import json
import os
import socket
import sys
import threading
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_PROXY_VARS = ("http_proxy", "https_proxy", "all_proxy", "no_proxy")


def is_local(host) -> bool:
    h = str(host)
    return h in ("localhost", "testserver", "::1", "0.0.0.0", "") or h.startswith("127.") or h.startswith("/")


def _where() -> str:
    for f in reversed(traceback.extract_stack()[:-3]):
        name = f.filename.replace("\\", "/")
        if "/src/" in name and str(ROOT).replace("\\", "/") in name or name.endswith("main_api.py"):
            return f"{name.split(str(ROOT).replace(chr(92), '/') + '/')[-1]}:{f.lineno} {f.name}"
    return "?"


def install(record, setattr_fn=setattr) -> None:
    """소켓 두 진입점을 가로챈다. `record(host, where)` 를 부르고 연결은 거부한다.
    `setattr_fn` — pytest 의 `monkeypatch.setattr` 를 넘기면 시험이 끝날 때 되돌려진다."""
    real_connect, real_gai = socket.socket.connect, socket.getaddrinfo

    def connect(self, addr):
        host = addr[0] if isinstance(addr, tuple) else addr
        if not is_local(host):
            record(str(host), _where())
            raise OSError(101, "probe: external connection blocked")
        return real_connect(self, addr)

    def getaddrinfo(host, *a, **k):
        if not is_local(host):
            record(str(host), _where())
            raise socket.gaierror(-3, "probe: external lookup blocked")
        return real_gai(host, *a, **k)

    setattr_fn(socket.socket, "connect", connect)
    setattr_fn(socket, "getaddrinfo", getaddrinfo)


def main(argv: list[str]) -> int:
    idle = float(argv[argv.index("--idle") + 1]) if "--idle" in argv else 2.0
    for k in list(os.environ):
        if k.lower() in _PROXY_VARS:
            del os.environ[k]
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "tests"))
    seen: dict = collections.OrderedDict()
    lock = threading.Lock()
    cur = {"route": "(startup)"}

    def record(host: str, where: str) -> None:
        with lock:
            k = (host, where, cur["route"])
            seen[k] = seen.get(k, 0) + 1

    install(record)
    import logging
    logging.disable(logging.CRITICAL)
    import main_api
    from fastapi.testclient import TestClient

    from route_walk import flat_routes
    app = main_api.create_app() if hasattr(main_api, "create_app") else main_api.app
    t0 = time.time()
    errors: list[str] = []
    with TestClient(app) as c:
        paths = sorted({r.path for r in flat_routes(app)
                        if "GET" in (getattr(r, "methods", None) or ()) and "{" not in r.path})
        for p in paths:
            cur["route"] = p
            try:
                c.get(p)
            except Exception as e:  # noqa: BLE001 — 경로 하나의 예외가 재기를 멈추지 않는다
                errors.append(f"{p}: {type(e).__name__}")
        cur["route"] = "(idle)"
        time.sleep(idle)
    out = {"mock": os.getenv("KIS_USE_MOCK"), "daemons": os.getenv("LIFECYCLE_DAEMONS"), "routes_called": len(paths),
           "route_errors": errors, "seconds": round(time.time() - t0, 1),
           "attempts": [{"host": h, "where": w, "route": r, "count": n} for (h, w, r), n in seen.items()]}
    if "--json" in argv:
        print("PROBE_JSON " + json.dumps(out, ensure_ascii=False))
    else:
        print(f"KIS_USE_MOCK={out['mock']} LIFECYCLE_DAEMONS={out['daemons']} · GET {len(paths)}개 · {out['seconds']}s · 경로 예외 {len(errors)}")
        for a in out["attempts"]:
            print(f"  {a['host']} · {a['where']} · {a['route']} · {a['count']}")
        print(f"외부 시도 {len(out['attempts'])}건(서로 다른 것)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
