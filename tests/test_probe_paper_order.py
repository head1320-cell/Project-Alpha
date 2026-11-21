"""모의투자 탐침 스크립트(`scripts/probe_paper_order.py`) — 설계 W5 §7

이 스크립트는 사용자가 **자기 모의투자 키로 자기 PC 에서** 돌린다(이 환경은 증권사에 닿지 못한다). 여기서 거는 것은
"무엇을 관측하나"가 아니라 ★안전 계약★이다 — 증권사 응답의 뜻은 탐침 결과를 받은 뒤에야 안다.

  ① 기본은 **읽기만** 한다 — `--send` 없이는 주문 경로를 만들지도 부르지도 않는다
  ② 모의투자가 아니면 아무 호출도 하지 않고 사유와 함께 끝낸다(모의 모드 · `KIS_IS_PAPER` 가 정확히 "1" 이 아님 ·
     클라이언트가 모의 서버를 가리키지 않음 · 계좌번호 없음) — 판정 불가도 거절이다
  ③ 주문은 ★제품의 주문 경로 한 길★(`execute_signal`)로만 나간다 — 스크립트가 `place_order` 를 직접 부르지 않는다(정적 + 동작)
  ④ 수량은 1주로 고정이다 · 종목은 사용자가 준다(도구가 고르지 않는다)
  ⑤ 저장하는 응답에서 비밀(계좌번호 · 앱 키 · 토큰)을 가린다 — 열쇠 이름으로도, 값에 섞인 것도
  ⑥ 조회 후보는 근거 등급을 달고, 실패한 후보도 버리지 않고 적는다 · 하나도 못 보면 '성공'이라고 말하지 않는다
"""
from __future__ import annotations

import ast
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import probe_paper_order as probe  # noqa: E402

from src.execution.kis_client import KIS_BASE_URL_PAPER, KIS_BASE_URL_REAL, KISCallError  # noqa: E402

ACCOUNT = "50123456"


class _Creds:
    def __init__(self, is_paper=True, account_no=ACCOUNT):
        self.is_paper, self.account_no, self.account_prdt = is_paper, account_no, "01"
        self.app_key, self.app_secret = "APPKEY-abcdef", "APPSECRET-uvwxyz"


class _Token:
    access_token = "TOKEN-123456"


class FakeClient:
    """증권사 클라이언트의 대역 — 부른 것을 전부 적는다. `place_order` 를 부르면 그 사실이 남는다."""

    def __init__(self, *, is_paper=True, account_no=ACCOUNT, base_url=KIS_BASE_URL_PAPER, inquiry=None):
        self.creds, self.base_url, self.token = _Creds(is_paper, account_no), base_url, _Token()
        self.calls: list[tuple] = []
        self.placed: list[dict] = []
        self._inquiry = inquiry or {}

    def _headers(self, tr_id):
        self.calls.append(("headers", tr_id))
        return {"tr_id": tr_id, "authorization": "Bearer TOKEN-123456", "appkey": self.creds.app_key}

    def _request(self, method, path, headers, params=None, json_body=None):
        self.calls.append((method, path, headers["tr_id"], dict(params or {})))
        answer = self._inquiry.get(headers["tr_id"])
        if isinstance(answer, Exception):
            raise answer
        if answer is None:
            raise KISCallError("KIS API 실패: rt_cd=1, msg=없는 서비스 코드", kind="business", rt_cd="1", status=200,
                               kis_msg="없는 서비스 코드", msg_cd="EGW00203")
        return answer

    def get_balance(self):
        self.calls.append(("balance",))
        return {"cash_krw": 10_000_000, "positions": [], "raw": {"output2": [{"CANO": ACCOUNT, "dnca_tot_amt": "10000000"}]}}

    def place_order(self, **kw):                         # 스크립트가 직접 부르면 안 된다
        self.placed.append(kw)
        return {"kis_order_no": "0000001", "raw": {}}


class FakeExecutor:
    """제품의 주문 실행기 대역 — 모드 전환과 신호를 적는다."""

    def __init__(self, client, result=None):
        self.kis, self.modes, self.signals = client, [], []
        self._result = result or {"client_order_id": "CO-probe", "status": "SUBMITTED", "mode": "PAPER", "kis_order_id": "0000001",
                                  "kis_response": {"kis_order_no": "0000001", "raw": {"output": {"ODNO": "0000001", "CANO": ACCOUNT}}}}

    def set_mode(self, mode, actor="user", confirm_token=None):
        self.modes.append((mode, actor, confirm_token))
        return {"new_mode": mode}

    def execute_signal(self, signal, account_state=None, regime_state=None, *, actor="system"):
        self.signals.append((dict(signal), actor))
        return dict(self._result)

    def get_order(self, client_order_id):
        return {"client_order_id": client_order_id, "status": "SUBMITTED", "kis_order_id": "0000001", "fills": []}


FILLS = {"rt_cd": "0", "msg1": "정상", "output1": [{"odno": "0000001", "pdno": "005930", "ord_qty": "1", "tot_ccld_qty": "1", "avg_prvs": "70100",
                                                    "ord_tmd": "090500", "cano": ACCOUNT}], "output2": {"tot_ord_qty": "1"}}


def run(argv, client, *, executor=None, env=None, mock=False, tmp_path=None):
    """스크립트를 대역과 함께 한 번 돌린다 → `(종료 코드, 보고, 실행기 공장이 불린 횟수)`."""
    made = []

    def executor_factory():
        made.append(1)
        return executor if executor is not None else FakeExecutor(client)

    out = tmp_path / "probe.json" if tmp_path else None
    code, report = probe.run(argv + (["--out", str(out)] if out else []), env={"KIS_IS_PAPER": "1", **(env or {})},
                             client_factory=lambda: client, executor_factory=executor_factory, mock_allowed=lambda: mock,
                             sleep=lambda s: None)
    return code, report, len(made)


# ── ① 기본은 읽기만 ────────────────────────────────────────────────────────

def test_without_send_nothing_is_ordered_and_the_order_path_is_never_built(tmp_path):
    client = FakeClient(inquiry={"VTTC0081R": FILLS})
    code, report, built = run([], client, tmp_path=tmp_path)
    assert code == 0 and built == 0 and client.placed == []
    assert report["order"] is None and report["sent"] is False
    assert [c[0] for c in client.calls if c[0] in ("POST",)] == []          # 쓰는 호출이 없다
    assert all(c[0] in ("headers", "GET", "balance") for c in client.calls)


def test_with_send_one_share_goes_through_the_products_order_path_only(tmp_path):
    client = FakeClient(inquiry={"VTTC0081R": FILLS})
    ex = FakeExecutor(client)
    code, report, built = run(["--send", "--ticker", "005930"], client, executor=ex, tmp_path=tmp_path)
    assert code == 0 and built == 1
    assert client.placed == []                                             # ★스크립트가 증권사 주문 함수를 직접 부르지 않는다★
    assert ex.modes == [("PAPER", "probe", None)]                          # 실계좌 확인 토큰을 넘기지 않는다
    assert ex.signals == [({"ticker": "005930", "side": "BUY", "quantity": 1, "order_type": "MARKET", "price": None, "strategy_id": None}, "probe")]
    assert report["sent"] is True and report["order"]["result"]["status"] == "SUBMITTED"


def test_the_quantity_cannot_be_raised_and_a_ticker_must_be_given():
    with pytest.raises(SystemExit):
        probe.parse(["--send", "--ticker", "005930", "--quantity", "100"])   # 그런 인자가 없다
    code, report, built = run(["--send"], FakeClient())
    assert code == 2 and built == 0 and report["skipped"]["reason"] == "ticker_required"


def test_a_limit_order_needs_a_price_and_a_market_order_takes_none(tmp_path):
    client = FakeClient(inquiry={"VTTC0081R": FILLS})
    code, report, built = run(["--send", "--ticker", "005930", "--order-type", "LIMIT"], client)
    assert code == 2 and built == 0 and report["skipped"]["reason"] == "price_required"
    ex = FakeExecutor(client)
    code, report, _ = run(["--send", "--ticker", "005930", "--order-type", "LIMIT", "--price", "70000", "--side", "SELL"], client, executor=ex, tmp_path=tmp_path)
    assert code == 0 and ex.signals[0][0] == {"ticker": "005930", "side": "SELL", "quantity": 1, "order_type": "LIMIT", "price": 70000.0, "strategy_id": None}


# ── ② 모의투자가 아니면 아무 호출도 하지 않는다 ─────────────────────────────────

@pytest.mark.parametrize("kw, env, mock, reason", [
    ({}, {}, True, "mock_mode"),                                             # 모의 모드 — 탐침할 증권사가 없다
    ({}, {"KIS_IS_PAPER": "0"}, False, "not_declared_paper"),
    ({}, {"KIS_IS_PAPER": ""}, False, "not_declared_paper"),                 # 비어 있음 ≠ "1"(제품의 기본값에 기대지 않는다)
    ({}, {"KIS_IS_PAPER": "true"}, False, "not_declared_paper"),
    ({"is_paper": False, "base_url": KIS_BASE_URL_REAL}, {}, False, "client_not_paper"),
    ({"is_paper": True, "base_url": KIS_BASE_URL_REAL}, {}, False, "endpoint_not_paper"),   # 표시는 모의인데 주소가 실서버
    ({"account_no": ""}, {}, False, "no_account"),
])
def test_anything_but_a_declared_paper_setup_is_refused_before_any_call(kw, env, mock, reason):
    client = FakeClient(**kw)
    code, report, built = run(["--send", "--ticker", "005930"], client, env=env, mock=mock)
    assert code == 2 and report["skipped"]["reason"] == reason and report["skipped"]["message"]
    assert client.calls == [] and client.placed == [] and built == 0        # 토큰도 받지 않았다


def test_an_unset_paper_flag_is_not_read_as_paper():
    """제품은 `KIS_IS_PAPER` 가 없으면 모의로 본다(안전한 쪽). 탐침은 그 기본값에 기대지 않는다 — 선언이 있어야 돈다."""
    client = FakeClient()
    code, report = probe.run([], env={}, client_factory=lambda: client, executor_factory=lambda: None, mock_allowed=lambda: False, sleep=lambda s: None)
    assert code == 2 and report["skipped"]["reason"] == "not_declared_paper" and client.calls == []


def test_an_unknown_client_is_refused_too():
    class Odd:                                                             # 자격 정보가 없는 무언가
        base_url = KIS_BASE_URL_PAPER
    built = []
    code, report = probe.run(["--send", "--ticker", "005930"], env={"KIS_IS_PAPER": "1"}, client_factory=lambda: Odd(),
                             executor_factory=lambda: built.append(1), mock_allowed=lambda: False, sleep=lambda s: None)
    assert code == 2 and report["skipped"]["reason"] == "client_not_paper" and built == []


def test_missing_credentials_are_a_reason_not_a_crash():
    from src.execution.kis_client import KISCredentialsMissing

    def no_client():
        raise KISCredentialsMissing("KIS_APP_KEY/KIS_APP_SECRET 미설정")

    code, report = probe.run([], env={"KIS_IS_PAPER": "1"}, client_factory=no_client, executor_factory=lambda: None,
                             mock_allowed=lambda: False, sleep=lambda s: None)
    assert code == 2 and report["skipped"]["reason"] == "no_credentials" and "KIS_APP_KEY" in report["skipped"]["message"]


# ── ③ 주문 경로는 하나 (정적) ────────────────────────────────────────────────

def test_the_script_never_calls_the_brokers_order_functions_itself():
    tree = ast.parse((ROOT / "scripts/probe_paper_order.py").read_text(encoding="utf-8"))
    called = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert not called & {"place_order", "cancel_order"}
    assert "execute_signal" in called                                      # 짝 — 검사가 호출을 실제로 본다
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert not names & {"KISClient", "MockKISClient", "KISCredentials", "OrderExecutor", "TradingEngine"}


# ── ⑤ 비밀을 가린다 ─────────────────────────────────────────────────────────

def test_secrets_are_masked_by_key_and_by_value():
    raw = {"CANO": ACCOUNT, "acnt_prdt_cd": "01", "nested": [{"note": f"계좌 {ACCOUNT}-01 조회", "odno": "0000001"}],
           "authorization": "Bearer TOKEN-123456", "appkey": "APPKEY-abcdef", "price": 70100, "ok": True, "none": None}
    got = probe.mask(raw, [ACCOUNT, "TOKEN-123456", "APPKEY-abcdef", ""])
    assert got["CANO"] == probe.MASK and got["acnt_prdt_cd"] == probe.MASK and got["authorization"] == probe.MASK and got["appkey"] == probe.MASK
    assert ACCOUNT not in json.dumps(got, ensure_ascii=False) and "TOKEN-123456" not in json.dumps(got)
    assert got["nested"][0]["odno"] == "0000001" and got["price"] == 70100 and got["ok"] is True and got["none"] is None   # 나머지는 그대로
    assert raw["CANO"] == ACCOUNT                                          # 받은 것을 고치지 않는다


def test_an_empty_secret_does_not_blank_everything():
    assert probe.mask({"msg": "정상처리"}, ["", None]) == {"msg": "정상처리"}


def test_the_saved_file_carries_no_secret(tmp_path):
    client = FakeClient(inquiry={"VTTC0081R": FILLS})
    code, report, _ = run(["--send", "--ticker", "005930"], client, tmp_path=tmp_path)
    text = (tmp_path / "probe.json").read_text(encoding="utf-8")
    assert code == 0 and json.loads(text)["probe"] == "kis_paper_order"
    for secret in (ACCOUNT, "TOKEN-123456", "APPKEY-abcdef", "APPSECRET-uvwxyz"):
        assert secret not in text
    assert "0000001" in text and "70100" in text                           # 관측값은 남는다


# ── ⑥ 조회 후보 ─────────────────────────────────────────────────────────────

def test_candidates_carry_their_basis_and_a_failed_one_is_recorded_not_dropped(tmp_path):
    client = FakeClient(inquiry={"VTTC8001R": FILLS})                       # 첫 후보는 실패하고 둘째가 답한다
    code, report, _ = run([], client, tmp_path=tmp_path)
    tried = report["inquiries"][0]["tried"]
    assert [t["tr_id"] for t in tried] == ["VTTC0081R", "VTTC8001R"] and all(t["basis"] for t in tried)
    assert tried[0]["ok"] is False and tried[0]["error"]["msg_cd"] == "EGW00203" and tried[0]["error"]["message"]
    assert tried[1]["ok"] is True and tried[1]["response"]["output1"][0]["avg_prvs"] == "70100"
    assert report["inquiries"][0]["answered_by"] == "VTTC8001R" and code == 0


def test_the_first_answer_ends_the_round_and_later_candidates_are_not_called(tmp_path):
    client = FakeClient(inquiry={"VTTC0081R": FILLS, "VTTC8001R": FILLS})
    _, report, _ = run([], client, tmp_path=tmp_path)
    assert [t["tr_id"] for t in report["inquiries"][0]["tried"]] == ["VTTC0081R"]
    assert [c[2] for c in client.calls if c[0] == "GET"] == ["VTTC0081R"]


def test_inquiry_requests_are_reads_on_the_paper_account_for_the_asked_days(tmp_path):
    client = FakeClient(inquiry={"VTTC0081R": FILLS})
    run(["--days", "3", "--today", "2026-11-16"], client, tmp_path=tmp_path)
    method, path, tr_id, params = [c for c in client.calls if c[0] == "GET"][0]
    assert (method, tr_id) == ("GET", "VTTC0081R") and path.endswith("/inquire-daily-ccld")
    assert params["CANO"] == ACCOUNT and params["INQR_STRT_DT"] == "20261114" and params["INQR_END_DT"] == "20261116"
    assert tr_id.startswith("V")                                           # 모의투자 계열의 서비스 코드만 쓴다


def test_every_candidate_is_a_paper_service_code():
    assert probe.INQUIRY_CANDIDATES and all(c["tr_id"].startswith("V") for c in probe.INQUIRY_CANDIDATES)


def test_after_sending_the_inquiry_is_repeated_as_asked(tmp_path):
    client = FakeClient(inquiry={"VTTC0081R": FILLS})
    slept = []
    code, report = probe.run(["--send", "--ticker", "005930", "--polls", "3", "--interval", "7", "--out", str(tmp_path / "p.json")],
                             env={"KIS_IS_PAPER": "1"}, client_factory=lambda: client, executor_factory=lambda: FakeExecutor(client),
                             mock_allowed=lambda: False, sleep=slept.append)
    assert code == 0 and len(report["inquiries"]) == 3 and slept == [7.0, 7.0]


def test_seeing_nothing_is_not_called_a_success(tmp_path):
    client = FakeClient(inquiry={})                                        # 후보가 전부 실패
    code, report, _ = run([], client, tmp_path=tmp_path)
    assert code == 1 and report["observed"] is False and report["inquiries"][0]["answered_by"] is None
    assert "확인하지 못했습니다" in report["summary"]


def test_a_rejected_order_is_reported_as_it_is_and_the_inquiry_still_runs(tmp_path):
    client = FakeClient(inquiry={"VTTC0081R": FILLS})
    ex = FakeExecutor(client, result={"client_order_id": "CO-x", "status": "REJECTED", "reason": "risk_check_failed", "message": "장 운영 시간이 아닙니다"})
    code, report, _ = run(["--send", "--ticker", "005930"], client, executor=ex, tmp_path=tmp_path)
    assert report["order"]["result"]["status"] == "REJECTED" and report["order"]["result"]["message"] == "장 운영 시간이 아닙니다"
    assert report["inquiries"] and code == 0                                 # 조회는 관측했다


def test_the_order_path_blowing_up_is_recorded_with_its_reason(tmp_path):
    client = FakeClient(inquiry={"VTTC0081R": FILLS})

    def broken():
        raise RuntimeError("live_orders 표가 없습니다")

    code, report = probe.run(["--send", "--ticker", "005930", "--out", str(tmp_path / "p.json")], env={"KIS_IS_PAPER": "1"},
                             client_factory=lambda: client, executor_factory=broken, mock_allowed=lambda: False, sleep=lambda s: None)
    assert report["order"]["error"]["message"] == "live_orders 표가 없습니다" and report["order"]["result"] is None
    assert client.placed == [] and code == 0                                 # 조회는 여전히 관측했다
