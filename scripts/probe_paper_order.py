#!/usr/bin/env python3
"""모의투자 탐침 — 증권사가 체결을 어떻게 알려 주는지 **관측만** 한다 (설계 W5 §7)
==============================================================================
설계 `docs/superpowers/specs/2026-11-14-paper-trading-monitor-design.md` §7 ·
결과를 받은 뒤에야 '체결 받아 적기'(W5d)의 구현 계획을 쓴다.

## 왜 있나

이 저장소에는 ★체결을 받아 적는 코드가 없다★ — 모의투자 주문은 내고 나면 `SUBMITTED` 로 남고, 체결 수량 · 평균 체결가 ·
체결 시각은 영영 비어 있다. 채우려면 증권사의 주문·체결 조회가 무엇을 어떤 칸으로 주는지 알아야 하는데, 개발 환경은
증권사에 닿지 못한다. 그래서 ★사용자가 자기 모의투자 키로 자기 PC 에서★ 이 스크립트를 돌려 응답 원문을 보내 준다.

## 무엇을 하나

    python3 scripts/probe_paper_order.py                          # ① 읽기만: 잔고 → 주문·체결 조회
    python3 scripts/probe_paper_order.py --send --ticker 005930   # ② 모의투자 1주 시장가 매수를 낸 뒤 조회를 되풀이
    python3 scripts/probe_paper_order.py --send --ticker 005930 --side SELL   # ③ 그 1주를 되판다(매도 체결의 표본)

- ★기본은 읽기만 한다.★ `--send` 가 없으면 주문 경로를 만들지도 부르지도 않는다.
- ★주문은 제품의 주문 경로 한 길로만 나간다★(`execute_signal` — 감사 → 비상 정지 → 위험 검사 → 모드). 이 스크립트는
  증권사 주문 함수를 직접 부르지 않는다. 그래서 위험 검사가 거절하면(예: 장 운영 시간이 아님) 주문은 나가지 않고 그 사유가 남는다 —
  그것도 관측이다.
- ★수량은 1주로 고정★이고 종목은 사용자가 준다(도구는 종목을 고르지 않는다).
- ★모의투자가 아니면 아무 호출도 하지 않는다★: 모의 모드(`KIS_USE_MOCK=1`) · `KIS_IS_PAPER` 가 정확히 `1` 이 아님 ·
  클라이언트가 모의 서버를 가리키지 않음 · 계좌번호 없음. 판정할 수 없는 경우도 거절한다.
- 결과는 `probe_out/` 아래 JSON 파일 하나다(`.gitignore` 에 있다). ★비밀은 가린다★ — 계좌번호 · 앱 키 · 토큰은
  열쇠 이름으로도, 값에 섞여 있어도 `***` 로 바꾼다. 그래도 보내기 전에 한 번 열어 보십시오.

## 준비 (`.env`)

    KIS_USE_MOCK=0
    KIS_IS_PAPER=1
    KIS_APP_KEY=…        # 모의투자용 앱 키
    KIS_APP_SECRET=…
    KIS_ACCOUNT_NO=…     # 모의투자 계좌번호 앞 8자리
    KIS_ACCOUNT_PRDT=01

`--send` 는 장 운영 시간에 돌려야 체결을 볼 수 있다. 주문 줄과 감사 줄은 이 PC 의 DB(`live_orders` · `live_audit_trail`)에 남는다.

## ★이 스크립트가 아는 것과 모르는 것★

- 주문·체결 조회의 경로 · 서비스 코드(`tr_id`) · 요청 칸은 ★공식 문서로 확인하지 못한 후보★다(이 환경에서 문서 사이트가 열리지 않았다).
  후보마다 근거를 적어 두고 차례로 시도하며, ★실패한 후보의 응답도 버리지 않고 적는다★ — 무엇이 틀렸는지가 곧 알아내려는 것이다.
- 응답 칸의 뜻은 해석하지 않는다. 원문을 그대로 남긴다.
- 제품의 주문 서비스 코드(`VTTC0802U` 등)가 지금도 유효한지 모른다 — 바뀌었다는 2차 자료가 있다. `--send` 의 결과가 그 답이다.
- 하나도 관측하지 못했으면 그렇게 말한다(종료 코드 1). "0건 성공"이라고 하지 않는다.

종료 코드: 0 = 조회 응답을 하나라도 받았다 · 1 = 돌렸지만 조회 응답을 받지 못했다 · 2 = 돌리지 않았다(사유).
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import pathlib
import sys
import time
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MASK = "***"
#: 이름만으로 가리는 열쇠(대소문자 무시). 값은 보지 않는다.
SECRET_KEYS = frozenset({"cano", "acnt_prdt_cd", "acnt_no", "account_no", "appkey", "appsecret", "app_key", "app_secret",
                         "authorization", "access_token", "token", "hashkey", "approval_key"})
INQUIRY_PATH = "/uapi/domestic-stock/v1/trading/inquire-daily-ccld"
#: 주문·체결 조회의 서비스 코드 후보 — ★모의투자 계열(V…)만★. 차례로 시도하고 처음 답한 것에서 멈춘다.
INQUIRY_CANDIDATES: tuple[dict, ...] = (
    {"tr_id": "VTTC0081R", "basis": "검색 요약(2026-11-14): 공식 예제가 쓰는 값이라는 2차 자료 — 공식 문서 원문은 확인하지 못했습니다."},
    {"tr_id": "VTTC8001R", "basis": "옛 실전 코드(TTTC8001R)의 모의 대응값이라는 추정 — 근거 자료를 찾지 못했습니다."},
)
#: 요청 칸 — 기억과 2차 자료에 기댄 후보다(문서 미확인). 서버가 거절하면 그 문장이 틀린 칸을 알려 준다.
PARAMS_BASIS = "요청 칸의 이름과 값은 공식 문서로 확인하지 못한 후보입니다."

REFUSALS = {
    "mock_mode": "모의 모드(KIS_USE_MOCK=1)입니다. 가짜 클라이언트에는 탐침할 것이 없습니다. KIS_USE_MOCK=0 과 모의투자 키로 돌리십시오.",
    "not_declared_paper": "KIS_IS_PAPER 가 정확히 1 이 아닙니다. 이 스크립트는 모의투자라고 선언된 환경에서만 돕니다.",
    "no_credentials": "증권사 자격 정보가 없습니다.",
    "client_not_paper": "클라이언트가 모의투자용이 아니거나 판정할 수 없습니다. 아무 호출도 하지 않았습니다.",
    "endpoint_not_paper": "클라이언트의 서버 주소가 모의투자 서버가 아닙니다. 아무 호출도 하지 않았습니다.",
    "no_account": "계좌번호(KIS_ACCOUNT_NO)가 없습니다.",
    "ticker_required": "--send 에는 --ticker 가 필요합니다. 종목은 직접 정하십시오(도구가 고르지 않습니다).",
    "price_required": "지정가(LIMIT) 주문에는 --price 가 필요합니다.",
}


# ── 비밀 가리기 ─────────────────────────────────────────────────────────────

def mask(obj, secrets):
    """`obj` 의 사본에서 비밀을 가린다 — 열쇠 이름(`SECRET_KEYS`)으로, 그리고 값에 섞인 비밀 문자열로. 받은 것은 고치지 않는다."""
    needles = [s for s in (secrets or []) if isinstance(s, str) and len(s) >= 4]

    def walk(v, key=None):
        if key is not None and str(key).lower() in SECRET_KEYS and v not in (None, ""):
            return MASK
        if isinstance(v, dict):
            return {k: walk(x, k) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [walk(x) for x in v]
        if isinstance(v, str):
            for n in needles:
                if n in v:
                    v = v.replace(n, MASK)
            return v
        return v

    return walk(copy.deepcopy(obj))


# ── 인자 ────────────────────────────────────────────────────────────────────

def parse(argv):
    ap = argparse.ArgumentParser(description="모의투자 탐침 — 기본은 읽기만 합니다.")
    ap.add_argument("--send", action="store_true", help="모의투자 1주 주문을 제품의 주문 경로로 냅니다(없으면 읽기만)")
    ap.add_argument("--ticker", help="--send 에 쓸 종목코드(직접 정하십시오)")
    ap.add_argument("--side", choices=("BUY", "SELL"), default="BUY")
    ap.add_argument("--order-type", choices=("MARKET", "LIMIT"), default="MARKET")
    ap.add_argument("--price", type=float, default=None, help="지정가 주문의 가격")
    ap.add_argument("--days", type=int, default=1, help="조회할 일수(오늘 포함 · 기본 1)")
    ap.add_argument("--polls", type=int, default=6, help="--send 뒤 조회를 되풀이할 횟수(기본 6)")
    ap.add_argument("--interval", type=float, default=5.0, help="되풀이 간격(초 · 기본 5)")
    ap.add_argument("--today", default=None, help="조회 기준일 YYYY-MM-DD(기본: 오늘)")
    ap.add_argument("--out", default=None, help="결과 파일 경로(기본: probe_out/kis_paper_probe_<시각>.json)")
    return ap.parse_args(argv)


# ── 사전 점검 ────────────────────────────────────────────────────────────────

def _refuse(reason, extra=""):
    return {"reason": reason, "message": (REFUSALS[reason] + (" " + extra if extra else "")).strip()}


def preflight(args, env, client_factory, mock_allowed):
    """`(client, None)` 또는 `(None, 거절)`. ★거절이면 증권사에 아무것도 보내지 않았다.★"""
    from src.execution.client_realism import REASON_KIS_PAPER, client_is_simulated
    from src.execution.kis_client import KIS_BASE_URL_PAPER, KISCredentialsMissing

    if args.send and not (args.ticker or "").strip():
        return None, _refuse("ticker_required")
    if args.send and args.order_type == "LIMIT" and not (args.price and args.price > 0):
        return None, _refuse("price_required")
    if mock_allowed():
        return None, _refuse("mock_mode")
    if env.get("KIS_IS_PAPER") != "1":
        return None, _refuse("not_declared_paper")
    try:
        client = client_factory()
    except KISCredentialsMissing as e:
        return None, _refuse("no_credentials", str(e))
    simulated, why = client_is_simulated(client)
    if not simulated or why != REASON_KIS_PAPER:
        return None, _refuse("client_not_paper", f"(판정: {why})")
    if getattr(client, "base_url", None) != KIS_BASE_URL_PAPER:
        return None, _refuse("endpoint_not_paper")
    if not (getattr(client.creds, "account_no", "") or "").strip():
        return None, _refuse("no_account")
    return client, None


# ── 관측 ────────────────────────────────────────────────────────────────────

def _error(e) -> dict:
    """실패 하나를 적는다 — 종류와 증권사의 문장을 그대로(뜻을 단정하지 않는다)."""
    out = {"type": type(e).__name__, "message": str(e)}
    for k in ("kind", "rt_cd", "msg_cd", "status", "kis_msg"):
        if hasattr(e, k):
            out[k] = getattr(e, k)
    return out


def inquiry_params(client, start: date, end: date) -> dict:
    return {
        "CANO": client.creds.account_no, "ACNT_PRDT_CD": client.creds.account_prdt,
        "INQR_STRT_DT": start.strftime("%Y%m%d"), "INQR_END_DT": end.strftime("%Y%m%d"),
        "SLL_BUY_DVSN_CD": "00", "INQR_DVSN": "00", "PDNO": "", "CCLD_DVSN": "00",
        "ORD_GNO_BRNO": "", "ODNO": "", "INQR_DVSN_3": "00", "INQR_DVSN_1": "",
        "CTX_AREA_FK100": "", "CTX_AREA_NK100": "",
    }


def inquire(client, start: date, end: date) -> dict:
    """주문·체결 조회 한 차례 — 후보를 차례로 시도하고 처음 답한 것에서 멈춘다. 실패한 후보도 적는다."""
    tried, answered = [], None
    params = inquiry_params(client, start, end)
    for cand in INQUIRY_CANDIDATES:
        row = {"tr_id": cand["tr_id"], "basis": cand["basis"], "path": INQUIRY_PATH, "params": params, "params_basis": PARAMS_BASIS}
        try:
            row.update(ok=True, response=client._request("GET", INQUIRY_PATH, client._headers(cand["tr_id"]), params=params))
            answered = cand["tr_id"]
        except Exception as e:                                  # noqa: BLE001 — 무엇이든 관측으로 남긴다
            row.update(ok=False, error=_error(e))
        tried.append(row)
        if answered:
            break
    return {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "answered_by": answered, "tried": tried}


def balance(client) -> dict:
    try:
        return {"ok": True, "response": client.get_balance()}
    except Exception as e:                                      # noqa: BLE001
        return {"ok": False, "error": _error(e)}


def send_one_share(args, executor_factory) -> dict:
    """★제품의 주문 경로로★ 1주를 낸다 — 이 함수는 증권사 주문 함수를 부르지 않는다."""
    signal = {"ticker": args.ticker.strip(), "side": args.side, "quantity": 1, "order_type": args.order_type,
              "price": float(args.price) if args.order_type == "LIMIT" else None, "strategy_id": None}
    out = {"signal": signal, "path": "OrderExecutor.execute_signal (PAPER)", "result": None, "row": None, "error": None}
    try:
        executor = executor_factory()
        executor.set_mode("PAPER", actor="probe")
        out["result"] = executor.execute_signal(signal, actor="probe")
        coid = (out["result"] or {}).get("client_order_id")
        if coid:
            out["row"] = executor.get_order(coid)
    except Exception as e:                                      # noqa: BLE001
        out["error"] = _error(e)
    return out


# ── 실행 ────────────────────────────────────────────────────────────────────

def run(argv, *, env=None, client_factory=None, executor_factory=None, mock_allowed=None, sleep=time.sleep):
    """`(종료 코드, 보고)`. 인자는 시험이 대역을 끼우는 자리다 — 기본은 제품의 한 길(`get_kis_client` · `get_executor`)."""
    args = parse(argv)
    env = os.environ if env is None else env
    if client_factory is None:
        from src.execution.kis_client import get_kis_client as client_factory
    if executor_factory is None:
        from src.api.stage13_routes import get_executor as executor_factory
    if mock_allowed is None:
        from src.data.mock_gate import mock_allowed

    report = {"probe": "kis_paper_order", "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "sent": False,
              "skipped": None, "balance": None, "order": None, "inquiries": [], "observed": False, "summary": ""}
    client, refusal = preflight(args, env, client_factory, mock_allowed)
    if refusal:
        report.update(skipped=refusal, summary="돌리지 않았습니다: " + refusal["message"])
        return 2, report

    today = date.fromisoformat(args.today) if args.today else date.today()
    start = today - timedelta(days=max(1, args.days) - 1)
    report["endpoint"] = client.base_url
    report["balance"] = balance(client)
    if args.send:
        report["sent"] = True
        report["order"] = send_one_share(args, executor_factory)
    rounds = max(1, args.polls) if args.send else 1
    for i in range(rounds):
        if i:
            sleep(float(args.interval))
        report["inquiries"].append(inquire(client, start, today))
    report["observed"] = any(r["answered_by"] for r in report["inquiries"])
    report["summary"] = _summary(report)

    token = getattr(getattr(client, "token", None), "access_token", None)
    secrets = [client.creds.account_no, getattr(client.creds, "app_key", None), getattr(client.creds, "app_secret", None), token]
    report = mask(report, secrets)
    path = pathlib.Path(args.out) if args.out else pathlib.Path("probe_out") / f"kis_paper_probe_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    report["saved_to"] = str(path)
    return (0 if report["observed"] else 1), report


def _summary(report: dict) -> str:
    parts = []
    order = report.get("order")
    if order:
        res = order.get("result") or {}
        parts.append(f"주문: {res.get('status') or '결과 없음'}" + (f" ({res.get('message') or res.get('reason')})" if res.get("status") in ("REJECTED", "FAILED") else "")
                     if not order.get("error") else f"주문 경로 오류: {order['error']['message']}")
    answered = [r["answered_by"] for r in report["inquiries"] if r["answered_by"]]
    if answered:
        parts.append(f"주문·체결 조회: {len(answered)}회 응답(서비스 코드 {answered[-1]})")
    else:
        parts.append("주문·체결 조회: 응답을 받지 못했습니다. 후보가 전부 실패했고 무엇이 맞는지 확인하지 못했습니다.")
    return " · ".join(parts)


def main() -> int:
    code, report = run(sys.argv[1:])
    print(report["summary"])
    if report.get("saved_to"):
        print(f"결과 파일: {report['saved_to']} (비밀은 가렸습니다. 보내기 전에 한 번 열어 보십시오.)")
    for r in report.get("inquiries", [])[:1]:
        for t in r["tried"]:
            print(f"  {t['tr_id']}: {'응답' if t['ok'] else '실패 ' + str(t['error'].get('message'))}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
