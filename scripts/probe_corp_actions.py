#!/usr/bin/env python3
"""기업행위(분할·증자·감자) 엔드포인트를 ★실호출로 확인하는 자리★
==============================================================================
문서: `docs/plans/2026-09-06-quant-db-infra-roadmap.md` 2단계

## 왜 이 스크립트가 있나

로드맵 2단계의 **첫 작업**은 설계가 아니라 확인이다:

> "어느 제공자의 어느 엔드포인트가 분할·증자를 주는가" 에 대해 **실호출 응답
> 한 건**이 저장소에 증거로 남는다. 없으면 "그 데이터는 우리가 못 받는다" 도
> **결론이다** — 그때 1단계는 A 안으로 간다.

★그런데 개발 컨테이너에서는 그 확인이 불가능하다★ — 이그레스 프록시가
`opendart.fss.or.kr` 과 `data.krx.co.kr` 을 **둘 다** 403(CONNECT tunnel failed)
으로 막고, 공식 가이드 페이지도 같은 이유로 열리지 않으며, `DART_API_KEY` 도 없다.

★그것은 "못 받는다" 가 아니라 "여기서는 확인할 수 없다" 다.★ 둘을 섞으면
1단계의 A/B 설계를 **근거 없이** 고르게 된다. 그래서 판정하는 대신
`scripts/explain_hot_queries.py` 와 같은 방식으로 **한 명령으로 재게** 만들어 둔다.

## ★엔드포인트 이름을 이 파일에 적지 않는다★

가이드를 못 읽었으므로 후보 이름을 적으면 **추측이 저장소에 사실처럼 남는다**.
이름은 아래 페이지에서 확인해 `--endpoint` 로 넘긴다:

    https://opendart.fss.or.kr/guide/main.do?apiGrpCd=DS005   (주요사항보고서 주요정보)

`tests/test_probe_corp_actions.py` 가 이 파일에 엔드포인트 리터럴이 없는지 건다.

## 무엇을 하나

  · 호출은 `DartClient._get()` 을 **재사용**한다 — 스로틀·디스크 캐시·쿼터
    집계·오류 기록이 이미 거기 있다. 요청 경로를 새로 만들지 않는다.
  · 성공하면 원본 JSON 을 `docs/evidence/dart/<endpoint>-<날짜>.json` 에 저장하고
    **필드 이름과 첫 행**을 찍는다 → 그것이 로드맵이 요구한 "증거 한 건" 이다.
  · 실패하면 DART 가 준 `status`·`message` 를 **그대로** 찍는다. `_get` 은 실패를
    `None` 으로 삼키므로 사유는 `dart_usage()["last_error"]` 에서 읽는다.
    ★사유를 지어내지 않는다★ — 기록이 없으면 없다고 적는다.

## 사용

    python -m scripts.probe_corp_actions --endpoint <이름> --corp-code 00126380 \\
           --param bgn_de=20240101 --param end_de=20241231
    python -m scripts.probe_corp_actions --selftest     # 네트워크·키 불필요
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

os.environ.setdefault("KIS_USE_MOCK", "1")

#: 증거를 남기는 자리 — ★스펙이 이 경로를 가리킨다★
DEFAULT_OUT_DIR = os.path.join("docs", "evidence", "dart")

_NO_REASON = ("사유가 기록되지 않았습니다 — DART 응답을 받기 전에 끊겼거나 "
              "예외였습니다. 로그를 보세요.")


def _rows_of(data: dict) -> list:
    """DART 응답의 행 목록. ★모양을 추측하지 않는다★ — 없으면 빈 리스트."""
    got = data.get("list")
    return got if isinstance(got, list) else []


def _save_evidence(out_dir: str, endpoint: str, data: dict) -> str:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(
        out_dir, f"{endpoint}-{datetime.now().strftime('%Y%m%d')}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
    return path


def probe(client, endpoint: str, params: dict, *,
          out_dir: str = DEFAULT_OUT_DIR) -> int:
    """엔드포인트 하나를 실호출하고 결과를 증거로 남긴다. 0=성공, 1=실패."""
    if not client.is_configured:
        print("★DART_API_KEY 가 설정되지 않았습니다★ — 호출하지 않았습니다.")
        print("  `.env` 의 `DART_API_KEY` 를 채운 뒤 다시 실행하세요.")
        return 1

    print(f"호출: {endpoint}  params={params}")
    data = client._get(endpoint, dict(params))

    if not data:
        # ★실패도 결론이다 — 다만 어느 실패인지 말해야 결론이 된다★
        from src.data.dart_client import dart_usage
        last = (dart_usage() or {}).get("last_error")
        if last:
            print(f"★실패★ status={last.get('status')}  "
                  f"message={last.get('message')}")
            print("  (013=조회된 데이터 없음 · 020=일 한도 초과 · "
                  "100=필수값 누락 · 101=인증키 오류 — DART 가 준 코드 그대로입니다)")
        else:
            print(f"★실패★ {_NO_REASON}")
        print("응답이 없어 증거를 저장하지 않았습니다.")
        return 1

    path = _save_evidence(out_dir, endpoint, data)
    rows = _rows_of(data)
    print(f"★성공★ 증거를 저장했습니다: {path}")
    print(f"  status={data.get('status')}  message={data.get('message')}  "
          f"행 {len(rows)}개")
    if rows and isinstance(rows[0], dict):
        print(f"  필드: {', '.join(sorted(rows[0]))}")
        print("  첫 행:")
        for k in sorted(rows[0]):
            print(f"    {k} = {rows[0][k]!r}")
    else:
        print("  ★행이 없습니다★ — 이 응답은 스키마에 대해 아무것도 말하지 않습니다.")
    print("\n이 파일을 `docs/specs/DATA_PLATFORM_SPEC.md` §7-3 에 붙이면 "
          "로드맵 2단계의 첫 작업이 끝납니다.")
    return 0


def _selftest() -> int:
    """★스크립트 자체가 도는지 본다★ — 가짜 응답으로 성공·실패 경로를 한 번씩.

    네트워크도 키도 쓰지 않는다. 여기서 나오는 값은 합성이라 **어느 엔드포인트가
    존재하는지에 대해 아무것도 말하지 않는다.**
    """
    import tempfile

    class _Fake:
        def __init__(self, payload):
            self.is_configured = True
            self._payload = payload

        def _get(self, endpoint, params):
            return self._payload

    print("★셀프테스트 — 합성 응답★ 엔드포인트의 존재를 말하지 않습니다.\n")
    with tempfile.TemporaryDirectory() as tmp:
        ok = probe(_Fake({"status": "000", "message": "정상",
                          "list": [{"rcept_no": "20240101000001",
                                    "corp_code": "00126380"}]}),
                   "selftestEndpoint", {"corp_code": "00126380"}, out_dir=tmp)
        if ok != 0:
            print("셀프테스트 실패: 성공 경로가 0 을 내지 않았습니다.")
            return 1
        saved = os.listdir(tmp)
        if not saved:
            print("셀프테스트 실패: 증거 파일이 저장되지 않았습니다.")
            return 1
        print(f"\n(저장 확인: {saved})\n")

        print("── 실패 경로 ──")
        bad = probe(_Fake(None), "selftestEndpoint", {}, out_dir=tmp)
        if bad != 1:
            print("셀프테스트 실패: 실패 경로가 1 을 내지 않았습니다.")
            return 1
    print("\n★셀프테스트 통과★ 실제 확인은 키가 있는 환경에서 "
          "`--endpoint` 로 하세요.")
    return 0


def _kv(items: list[str] | None) -> dict:
    out: dict = {}
    for it in items or []:
        if "=" not in it:
            raise SystemExit(f"--param 은 k=v 형식입니다: {it!r}")
        k, v = it.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--endpoint", help="DART 엔드포인트 이름 (가이드에서 확인)")
    ap.add_argument("--corp-code", help="DART 고유번호 8자리 (종목코드 아님)")
    ap.add_argument("--param", action="append",
                    help="추가 파라미터 k=v (여러 번)")
    ap.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    ap.add_argument("--selftest", action="store_true",
                    help="합성 응답으로 스크립트 자체를 검증(네트워크·키 불필요)")
    args = ap.parse_args()

    if args.selftest:
        return _selftest()
    if not args.endpoint:
        ap.error("--endpoint 가 필요합니다 (또는 --selftest). "
                 "이름은 https://opendart.fss.or.kr/guide/main.do?apiGrpCd=DS005 "
                 "에서 확인하세요 — 이 저장소는 추측한 이름을 담지 않습니다.")

    params = _kv(args.param)
    if args.corp_code:
        params["corp_code"] = args.corp_code

    from src.data.dart_client import DartClient
    return probe(DartClient(), args.endpoint, params, out_dir=args.out_dir)


if __name__ == "__main__":
    sys.exit(main())
